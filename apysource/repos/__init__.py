# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Repository registry and base class — no global state, explicit construction only."""

from __future__ import annotations

from pathlib import Path

from apysource.repos._base import (  # noqa: F401 — public re-exports
    SMALL_FILE_THRESHOLD,
    BaseRepo,
    extract_content_with_fallback,
    extract_line_range,
    slugify,
)
from apysource.http import document_url
from apysource.repos.errors import (  # noqa: F401 — public re-exports
    RepoError,
    RepoNotFound,
    RepoUnavailable,
)


class RepoRegistry:
    """Registry of repo instances. Constructed explicitly, injected everywhere.

    Repos that don't set cache_dir, http_client or crawl_delay get them from
    the registry: cache_dir defaults to sources_cache_dir / repo.NAME, and
    http_client and default_crawl_delay are shared.
    """

    def __init__(self, repos: list[BaseRepo], sources_cache_dir: str | Path | None = None,
                 http_client: object | None = None,
                 default_crawl_delay: float | None = None) -> None:
        self.repos = repos
        #: document url -> the repo that claims it, memoized. Every fragment
        #: asks this two or three times (routing, then again to name the repo a
        #: fallback came from), and a run over one document asks it once per
        #: fragment on top of that. The patterns are arbitrary regexes, so there
        #: is no index to build — but the answer cannot change within a run.
        #:
        #: Keyed on the *document*, with the anchor dropped, exactly as the
        #: fetcher keys its own cache. Keyed on the URL as written, fifty
        #: citations into one page at fifty anchors were fifty entries and fifty
        #: regex scans — the fan-in shape this memo exists for was the one it
        #: helped least.
        self._claims: dict[str, BaseRepo | None] = {}
        for repo in repos:
            if getattr(repo, "cache_dir", None) is None and sources_cache_dir:
                repo.cache_dir = Path(sources_cache_dir) / repo.NAME
            if getattr(repo, "http_client", None) is None and http_client:
                repo.http_client = http_client
            if getattr(repo, "crawl_delay", None) is None and default_crawl_delay is not None:
                repo.crawl_delay = float(default_crawl_delay)

    def get_repo(self, url: str) -> BaseRepo | None:
        """Find the repo that handles a given URL.

        The anchor is dropped before matching as well as before caching. A
        fragment names a place inside a document, never a different document, so
        it cannot change which repo owns it — and every shipped pattern already
        stops before a ``#``. Matching the document is what the answer is about.
        """
        key = document_url(url)
        try:
            return self._claims[key]
        except KeyError:
            pass

        found = None
        for repo in self.repos:
            pattern = getattr(repo, "url_pattern", None)
            if pattern and pattern.search(key):
                found = repo
                break

        self._claims[key] = found
        return found

    def all_repos(self) -> list[BaseRepo]:
        """Return all registered repos."""
        return list(self.repos)
