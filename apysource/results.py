# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Structured result types for fetching, resolution and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apysource.diagnostics import Diagnosis
    from apysource.http import CachedFetcher
    from apysource.repos._base import BaseRepo


# ── Resolution results ──────────────────────────────────────────────────

@dataclass
class ResolveResult:
    """Base result — covers error cases (no_source, no_url, no_module, no_file)."""

    status: str
    label: str = ""
    url: str = ""
    source: str = ""


@dataclass
class RepoResult(ResolveResult):
    """Resolved via a repository module.

    ``cache_file`` of ``None`` means the document has not been crawled yet,
    not that this is not a repo's document. Routing is decided by the URL the
    citation names, never by what happens to be on disk — otherwise a cold
    cache silently changes *which document* is the source of truth.

    ``format_name``/``locator`` carry the fragment's own targeting — a
    ``section:`` or a ``selector:`` — exactly as they do for a fetched source.
    A repo used to be handed only ``location:``, and everything else was
    dropped on the floor: a fragment naming a section the document does not
    have verified **green**, because the repo returned the whole page and the
    snippet was found somewhere in it. Whether a citation was checked against
    the section it named came down to whether some repo happened to claim
    its URL.
    """

    location: str = ""
    module: str = ""
    repo: BaseRepo | None = None
    key: str = ""
    cache_file: str | None = None
    format_name: str = ""
    locator: str | None = None


@dataclass
class FetcherResult(ResolveResult):
    """Resolved via HTTP fetcher (no repo needed).

    ``fallback_from`` names the repo that claimed this URL but could not
    serve it. The fetch still happens — but against the rendered web page
    rather than the repository the citation names, which is a different
    document, and the report says so instead of letting it pass unremarked.
    """

    location: str = ""
    module: str = "http"
    fetcher: CachedFetcher | None = None
    format_name: str = ""
    locator: str | None = None
    fallback_from: str = ""
    fallback_reason: str = ""


# ── Repo outcomes ───────────────────────────────────────────────────────

@dataclass
class CrawlOutcome:
    """What happened when a repo was asked for a document.

    The *absence* of one (``crawl_outcome`` returning ``None``) means the
    document was never asked for, because it was already cached. That is
    neither a success nor a failure and must not be reported as either —
    counting a warm cache as ``ok`` is how a check ends up confirming
    something it never looked at.
    """

    repo: str
    key: str
    status: str  # "ok" | "not_found" | "unavailable"
    reason: str = ""


@dataclass
class TextOutcome:
    """Extracted source text, and why there is none when there is none.

    ``status`` is what the report needs in order to blame the right thing:
    a page that does not exist, a fetch that failed, and a document that
    really is empty are three different findings, and they used to arrive
    as one indistinguishable "empty extraction (0 chars)".
    """

    text: str
    status: str = "ok"  # ok | not_found | unavailable | no_file | empty | no_section
    reason: str = ""


# ── Fetch metadata ──────────────────────────────────────────────────────

@dataclass
class Redirect:
    """Where a URL actually led.

    An empty ``chain`` means the URL was fetched directly. The *absence*
    of a Redirect (``None``) means something different and important: the
    fetch predates redirect recording, so nothing is known. Reporting must
    not read that as "no redirect" — a silently-followed 301 is the bug
    this exists to surface.
    """

    url: str
    final_url: str
    chain: list[tuple[int, str]] = field(default_factory=list)

    @property
    def redirected(self) -> bool:
        """Whether the request was answered by a different URL."""
        return bool(self.chain)


# ── Verification results ────────────────────────────────────────────────

@dataclass
class Failure:
    """A single verification failure.

    ``group`` and ``item`` are what a human reads: the source this failed
    under, and which fragment of it. They were both the same slugified URN
    until this carried enough to say otherwise — the report printed
    ``urn:apysource:fragment_mdn_origin_stale_pre_redirect_url_mdn_stale``
    twice, and left the author to de-slugify their own labels.

    ``url`` and ``urn`` are what a machine reads. The URN stays the stable
    identity — it is the subject of the provenance graph — while the label
    is what someone wrote in the YAML and would grep for.

    ``hint`` carries the diagnosis when there is one — the passage the
    source actually contains, and how it differs from what was cited. It
    is kept as data, not as rendered lines, so a machine-readable report
    can serve it without parsing prose back apart.
    """

    group: str
    item: str
    reason: str
    hint: Diagnosis | None = None
    url: str = ""
    urn: str = ""


@dataclass
class CheckResult:
    """Result of a verification check.

    Warnings report something worth knowing that is not, on its own, a
    reason to fail the run — a source that still verifies, but only
    because a redirect carried it somewhere else.
    """

    name: str
    ok: int
    total: int
    failures: list[Failure] = field(default_factory=list)
    warnings: list[Failure] = field(default_factory=list)
