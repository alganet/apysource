# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared utilities and base class for apysource repository modules.

No config imports — all values received as parameters.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apysource.repos.errors import RepoError, RepoNotFound, RepoUnavailable
from apysource.results import CrawlOutcome

__all__ = [
    "SMALL_FILE_THRESHOLD",
    "BaseRepo",
    "RepoError",
    "RepoNotFound",
    "RepoUnavailable",
    "extract_content_with_fallback",
    "extract_line_range",
    "slugify",
]


class BaseRepo:
    """Base class for repos — provides common boilerplate.

    Subclasses must define NAME, url_to_key(), and resolve_location().
    Constructor requires url_pattern and base_url.
    cache_dir and http_client are optional — RepoRegistry fills them
    from its own sources_cache_dir and http_client if not set.
    """

    NAME = ""

    #: Whether this repo can fetch a document it does not already have.
    #:
    #: A repo that only reads a cache someone else populated leaves this
    #: False, and a cold cache is then *reported* rather than silently
    #: re-routed to the generic fetcher — which would verify the citation
    #: against the rendered web page instead of against the repository the
    #: citation names. Two different documents; no signal that it happened.
    #:
    #: A flag, and not ``hasattr(repo, "crawl")``: duck-typing this would be
    #: true for any repo that happened to name a private helper ``crawl``,
    #: and the cost of guessing wrong is a network fetch and a changed source
    #: of truth.
    supports_crawl: bool = False

    # ── The name family, if this repo has one ─────────────────────────
    #
    # How you *name* an MDN page is MDN's knowledge, so it is declared here and
    # not in ``patterns.py``, which knows nothing about MDN and should not start.
    # Optional: a repo may claim URLs without offering any way to name them.
    #
    # Read the direction carefully, because it is the opposite of ``url_pattern``:
    #
    #     name --[NAME_MATCH]--> CANONICAL_URL --[url_pattern]--> key --[base_url]--> fetch url
    #          ^ generates a url                ^ parses one
    #
    # ``CANONICAL_URL`` is **not** ``base_url``. ``base_url`` builds the *fetch*
    # URL, which for every shipped repo is a different endpoint and usually a
    # different host (MDN fetches from raw.githubusercontent). ``CANONICAL_URL``
    # is the public address a human clicks and the one that goes in ``schema:url``.
    #
    # There is no inverse. ``url_to_key`` is deliberately non-injective — MDN
    # case-folds and rewrites ``:``, ``*``, ``?`` — so a key cannot be turned back
    # into a URL, and the family cannot be derived from the matcher.

    #: A regex over *names*, with named groups that fill ``CANONICAL_URL``.
    NAME_MATCH: str = ""

    #: The canonical public URL a matched name denotes.
    CANONICAL_URL: str = ""

    #: A real name in this family. ``tests/test_patterns.py`` mints it and asserts
    #: this very repo claims what came out — the two halves of a family state the
    #: host twice by necessity, and that test is what keeps them from drifting.
    NAME_EXAMPLE: str = ""

    @classmethod
    def family(cls) -> dict[str, Any] | None:
        """This repo's name family, in the shape ``compile_patterns`` already eats.

        Returning the raw dict rather than a ``SourcePattern`` keeps ``repos`` from
        importing ``patterns`` — the dependency runs the other way, and it has to:
        a pattern is data a repo happens to declare, not a thing a repo needs.
        """
        if not cls.NAME_MATCH or not cls.CANONICAL_URL:
            return None
        return {"match": cls.NAME_MATCH, "source": {"url": cls.CANONICAL_URL}}

    def __init__(self, cache_dir: Any = None, http_client: Any = None,
                 url_pattern: Any = None, base_url: str | None = None,
                 crawl_delay: float | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.http_client = http_client
        if url_pattern is None:
            raise TypeError(f"{type(self).__name__} requires url_pattern")
        if base_url is None:
            raise TypeError(f"{type(self).__name__} requires base_url")
        self.url_pattern = (re.compile(url_pattern) if isinstance(url_pattern, str)
                            else url_pattern)
        self.base_url = base_url.rstrip("/")

        #: Politeness gap for *this* repo's fetches. None means "use the
        #: fetcher's default". It is passed per request and never assigned
        #: onto the shared fetcher: a repo backed by a CDN can be read
        #: briskly without turning every other source — rfc-editor,
        #: archive.org — into a rude crawl as a side effect.
        self.crawl_delay = crawl_delay

        self._crawls: dict[str, CrawlOutcome] = {}

    @property
    def cache_root(self) -> Path:
        """Where this repo keeps its documents.

        The registry injects it. A repo constructed outside one, and never given
        a directory, has nowhere to put anything — better to say so than to
        raise something obscure deep inside a crawl.
        """
        if self.cache_dir is None:
            raise RuntimeError(
                f"{type(self).__name__} has no cache_dir; construct it with one, "
                f"or register it with a RepoRegistry that has a sources_cache_dir",
            )
        return self.cache_dir

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Extract a cache key from a URL. Subclasses must override."""
        raise NotImplementedError

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Resolve a location to a cache file path. Subclasses must override.

        This is a *cache lookup*. It must not fetch: resolution asks it what
        is on disk, and a resolver that quietly reaches for the network makes
        every caller's cost and failure modes unpredictable. Fetching is what
        ``crawl`` is for.
        """
        raise NotImplementedError

    def is_cached(self, key: str) -> bool:
        """Check if key is cached by trying resolve_location."""
        loc = self.resolve_location("", key)
        return loc is not None and loc.exists()

    def extract_content(self, location: str, file_path: Path) -> str:
        """Extract content using line range with small-file fallback."""
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return extract_content_with_fallback(text, location)

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float | None = None,
              force: bool = False, from_cache: bool = False) -> Any:
        """Fetch and cache the document for ``key``.

        The contract, for anyone implementing it:

        - return once the document is on disk, such that
          ``resolve_location`` finds it for any location it supports;
        - raise :class:`RepoNotFound` when the repository authoritatively
          has no such document, having written *nothing* — so a page that
          returns upstream verifies on the next run with no ``--refresh``;
        - raise :class:`RepoUnavailable` when the fetch failed for any other
          reason. A timeout is not an absence.

        Implementations must set ``supports_crawl = True``. The return value
        is unspecified and the library ignores it.
        """
        raise NotImplementedError

    def fetch(self, url: str, key: str, *, force: bool = False,
              from_cache: bool = False, timeout: int | None = None) -> str:
        """Fetch a URL for this repo, or raise the failure that explains why not.

        The one place the 404-versus-outage distinction is drawn, so that it
        cannot rot differently in each repo. The fetcher answers ``None`` to a
        missing page and to an unreachable server alike; only the status it saw
        can tell them apart, and when it saw none, we say we do not know.
        """
        if self.http_client is None:
            # A repo wired without a fetcher used to reach this line and die on
            # `NoneType has no attribute 'get'` — a traceback, out of the middle
            # of a crawl, for what is a one-line mistake in a config file. A
            # misconfiguration is the author's to fix and ours to name.
            raise RepoUnavailable(
                self.NAME, key,
                "no HTTP client is wired into this repo, so it cannot fetch "
                "anything. Give the registry an `http_client` (see defaults.toml).",
            )

        text = self.http_client.get(url, delay=self.crawl_delay, timeout=timeout,
                                    force=force, from_cache=from_cache)
        if text is not None:
            return str(text)

        status = None
        status_for = getattr(self.http_client, "status_for", None)
        if status_for is not None:
            status = status_for(url)

        if status in (404, 410):
            raise RepoNotFound(self.NAME, key, f"{url} returned {status}")
        if status is not None:
            raise RepoUnavailable(self.NAME, key, f"{url} returned {status}")
        raise RepoUnavailable(self.NAME, key, f"{url} could not be reached")

    def ensure(self, key: str, *, force: bool = False) -> None:
        """Crawl ``key`` at most once per run, replaying the same outcome.

        Twenty fragments citing one missing page must produce one request and
        twenty identical failures — not twenty requests, and not one failure
        followed by nineteen different ones.
        """
        if not force and key in self._crawls:
            outcome = self._crawls[key]
            if outcome.status == "not_found":
                raise RepoNotFound(self.NAME, key, outcome.reason)
            if outcome.status == "unavailable":
                raise RepoUnavailable(self.NAME, key, outcome.reason)
            return

        try:
            self.crawl(key, delay=self.crawl_delay, force=force)
        except RepoError as e:
            status = "not_found" if isinstance(e, RepoNotFound) else "unavailable"
            self._crawls[key] = CrawlOutcome(self.NAME, key, status, e.reason)
            raise

        self._crawls[key] = CrawlOutcome(self.NAME, key, "ok")

    def crawl_outcome(self, key: str) -> CrawlOutcome | None:
        """What happened when this key was crawled, or None if it never was.

        A warm cache crawls nothing, so it has no outcome. Reporting must
        read that as "nothing to say", not as a pass.
        """
        return self._crawls.get(key)


SMALL_FILE_THRESHOLD = 5000


def extract_line_range(text: str, location: str) -> str | None:
    """Extract lines:N-M range from text based on location string."""
    line_match = re.search(r"lines:(\d+)-(\d+)", location)
    if not line_match:
        return None
    from apysource.formats import PlainTextFormat
    line_range = f"{line_match.group(1)}-{line_match.group(2)}"
    return PlainTextFormat().extract(text, line_range)


def slugify(text: str) -> str:
    """Convert text to a filesystem slug: lowercase, spaces to underscores."""
    return text.lower().replace(" ", "_")


def extract_content_with_fallback(
    text: str, location: str, *, threshold: int = SMALL_FILE_THRESHOLD,
) -> str:
    """Common extract_content pattern: try line range, then small-file fallback.

    A document nobody asked to narrow is returned whole, however long it is.
    It used to be cut off at ``threshold`` and come back as ``""`` — reported as
    "empty extraction (0 chars)" for a document that was not empty at all, just
    longer than five thousand characters, which is to say: almost any real page.
    The citation was blamed for the size of its source.
    """
    result = extract_line_range(text, location)
    if result is not None:
        return result
    if not location.strip():
        return text
    if len(text) < threshold:
        return text
    return ""
