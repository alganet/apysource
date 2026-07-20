# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Resolve entity sourceLocation to cached source text.

All functions require a RepoRegistry instance — no global state.

Routing is decided by the URL a citation names, never by what happens to be
in the cache. A repo used to win only if its file was already on disk, which
meant a cold cache quietly re-routed the citation to the generic fetcher and
verified it against the *rendered web page* instead of against the repository
the citation names — two different documents, with no signal that the swap had
occurred. Cache state now decides only whether we must crawl, never what we
are checking against.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.formats import detect_format, extract_content, truncate
from apysource.http import CachedFetcher, document_url, url_anchor
from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry
from apysource.repos._base import BaseRepo
from apysource.repos.errors import RepoNotFound, RepoUnavailable
from apysource.sections import SectionNotFound, selector_for_anchor
from apysource.results import FetcherResult, RepoResult, ResolveResult, TextOutcome


# ── OA graph traversal helpers ──────────────────────────────────────────

def _get_source(g: Graph, frag: URIRef) -> URIRef | None:
    """Get source URI from OA target chain: frag → oa:hasTarget → oa:hasSource."""
    for target in g.objects(frag, OA.hasTarget):
        source = g.value(target, OA.hasSource)
        if source:
            return cast(URIRef, source)
    return None


def _get_selector_value(g: Graph, frag: URIRef, selector_type: URIRef) -> str:
    """Get rdf:value from a specific OA selector type."""
    for target in g.objects(frag, OA.hasTarget):
        for sel in g.objects(target, OA.hasSelector):
            if (sel, RDF.type, selector_type) in g:
                val = g.value(sel, RDF.value)
                if val:
                    return str(val)
    return ""


def _get_snippet(g: Graph, frag: URIRef) -> str | None:
    """Get snippet text from TextQuoteSelector oa:exact."""
    for target in g.objects(frag, OA.hasTarget):
        for sel in g.objects(target, OA.hasSelector):
            if (sel, RDF.type, OA.TextQuoteSelector) in g:
                exact = g.value(sel, OA.exact)
                if exact:
                    return str(exact)
    return None


# ── Resolution functions ────────────────────────────────────────────────

def _resolve_repo(registry: RepoRegistry, url: str, location: str,
                  ) -> tuple[BaseRepo | None, str, Path | None, str]:
    """Decide whether a repo owns this URL, and what it already has.

    Returns ``(repo, key, cache_file, fallback_reason)``. A repo is returned
    only when it can actually serve the document — it has the file, or it can
    fetch it. When it matched the URL but can do neither, ``fallback_reason``
    says why, so the caller can fall back to the fetcher *out loud* rather
    than silently checking a different document.

    The repo is asked about the *document*, never about the anchor: a key is
    the identity of a document in a repo, and an anchor names a place inside
    one. A repo whose pattern ends in a greedy ``(.+)`` would otherwise swallow
    ``#English`` into its cache key and keep a second copy of the same page
    under it — and every repo, including one written by someone else, is
    protected here rather than one pattern at a time.
    """
    url = document_url(url)

    repo = registry.get_repo(url)
    if repo is None:
        return None, "", None, ""

    key = repo.url_to_key(url) or ""
    if not key:
        return None, "", None, "this URL yields no key for it"

    cache_file = repo.resolve_location(location, key)
    # Repos are injected and duck-typed — the registry reads them with getattr
    # and a custom one predates this contract entirely. Such a repo simply has
    # no crawler, which is the safe reading, not a crash.
    if cache_file is None and not getattr(repo, "supports_crawl", False):
        return None, key, None, "it has no crawler and the document is not cached"

    return repo, key, cache_file, ""


def _resolve_source_url(g: Graph, source: URIRef, depth: int = 3) -> str:
    """Get schema:url, following dcterms:isPartOf chain."""
    url = g.value(source, SCHEMA.url)
    if url:
        return str(url)
    if depth <= 0:
        return ""
    parent = g.value(source, DCTERMS.isPartOf)
    if parent:
        return _resolve_source_url(g, cast(URIRef, parent), depth - 1)
    return ""


def _targeting(g: Graph, frag_uri: URIRef,
               format_holder: URIRef) -> tuple[str, str | None]:
    """What this fragment says to target, and in what format.

    Read the same way no matter who will serve the document. It used to be read
    only on the fetcher branch, so a ``section:`` on a repo-backed fragment was
    dropped without a word — and a fragment naming a section the document does
    not have verified **green**, because the repo handed back the whole page and
    the snippet turned up somewhere in it. Whether a citation was checked against
    the section it named depended on whether a repo happened to claim its URL.
    """
    section = _get_selector_value(g, frag_uri, SV.SectionSelector)
    if section:
        return "section", section

    # Deliberately *not* normalized here, though it looks like it should be.
    # `_find_format` already matches an internal name ("html", "rfc") before it
    # tries MIME, so a Turtle author writing `dcterms:format "html"` was always
    # understood. Normalizing first would make things worse, not better: "rfc"
    # and "plain-text" both canonicalize to "text/plain", which two formats
    # claim, and an ambiguous MIME resolves to nothing — so a source that says
    # exactly what it is would fall through to auto-detection instead.
    format_name = str(g.value(format_holder, DCTERMS.format) or "")
    css = _get_selector_value(g, frag_uri, OA.CssSelector)
    lines = str(g.value(frag_uri, SV.sourceLines) or "")
    return format_name, (css or lines) or None


def resolve_chain(g: Graph, frag_uri: URIRef, registry: RepoRegistry,
                   fetcher: CachedFetcher | None = None) -> ResolveResult:
    """Resolve a fragment via OA target chain: Fragment → hasTarget → hasSource → url."""
    label = str(g.value(frag_uri, RDFS.label) or "")
    location = str(g.value(frag_uri, SV.sourceLocation) or "")
    source = _get_source(g, frag_uri)

    if not source:
        return ResolveResult(status="no_source", label=label)

    source_label = str(g.value(source, RDFS.label) or "")
    url = _resolve_source_url(g, source)

    if not url:
        return ResolveResult(status="no_url", label=label, source=source_label)

    format_name, locator = _targeting(g, frag_uri, source)
    anchor = url_anchor(url)

    repo, key, cache_file, fallback = _resolve_repo(registry, url, location)
    if repo is not None:
        return RepoResult(
            status="resolved",
            label=label, location=location, source=source_label,
            url=url, module=repo.NAME, repo=repo, key=key,
            cache_file=str(cache_file) if cache_file else None,
            format_name=format_name, locator=locator, anchor=anchor,
        )

    if fetcher:
        matched = registry.get_repo(url)
        return FetcherResult(
            status="resolved", label=label, location=location,
            source=source_label, url=url,
            fetcher=fetcher, format_name=format_name, locator=locator,
            anchor=anchor,
            fallback_from=matched.NAME if matched and fallback else "",
            fallback_reason=fallback,
        )

    return ResolveResult(status="no_module", label=label, url=url,
                         source=source_label)


def resolve_direct(g: Graph, entity_uri: URIRef, registry: RepoRegistry,
                    fetcher: CachedFetcher | None = None) -> ResolveResult:
    """Resolve any entity with schema:url directly on it."""
    # A Term is required to carry an rdfs:label (the SHACL shapes say so), and
    # it was being dropped on the floor here — so a Term failure had nothing to
    # report itself by except its URI.
    label = str(g.value(entity_uri, RDFS.label) or "")
    url = str(g.value(entity_uri, SCHEMA.url) or "")
    location = str(g.value(entity_uri, SV.sourceLocation) or "")

    if not url:
        return ResolveResult(status="no_url", label=label)

    format_name, locator = _targeting(g, entity_uri, entity_uri)
    anchor = url_anchor(url)

    repo, key, cache_file, fallback = _resolve_repo(registry, url, location)
    if repo is not None:
        return RepoResult(
            status="resolved", label=label,
            url=url, location=location, module=repo.NAME,
            repo=repo, key=key,
            cache_file=str(cache_file) if cache_file else None,
            format_name=format_name, locator=locator, anchor=anchor,
        )

    if fetcher:
        matched = registry.get_repo(url)
        return FetcherResult(
            status="resolved", label=label, url=url, location=location,
            fetcher=fetcher, format_name=format_name, locator=locator,
            anchor=anchor,
            fallback_from=matched.NAME if matched and fallback else "",
            fallback_reason=fallback,
        )

    return ResolveResult(status="no_module", label=label, url=url)


def _apply_targeting(result: ResolveResult, text: str) -> tuple[str, str | None]:
    """The format and locator to extract with, once the document is in hand.

    An explicit ``section:``/``selector:`` always wins — the author said it
    outright. Only when they said nothing do we read the anchor their URL was
    already carrying, and only where we can be sure what it points at.
    """
    format_name = getattr(result, "format_name", "")
    locator = getattr(result, "locator", None)
    if locator or not result.anchor:
        return format_name, locator

    inferred = selector_for_anchor(text, result.anchor, detect_format(text))
    if inferred is None:
        return format_name, locator
    return "section", inferred


def _load_repo_text(result: RepoResult, max_chars: int | None, *,
                    force: bool, crawl: bool) -> TextOutcome:
    """Read a repo-backed document, crawling it first if it is not here yet.

    Every path returns. The generic fetcher is deliberately unreachable from
    here: a repo that owns a URL and finds no document must say so, not hand
    the citation to HTTP, where the rendered page would happily answer for a
    document the repository no longer has — green, and wrong.
    """
    repo = result.repo
    if repo is None:
        return TextOutcome("", "no_file", "no repo on the result")

    path = Path(result.cache_file) if result.cache_file else None
    stale = force or path is None or not path.exists()

    if stale and result.key:
        if not crawl:
            return TextOutcome(
                "", "no_file",
                f"{repo.NAME}: {result.key} is not cached, and crawling is off",
            )
        try:
            repo.ensure(result.key, force=force)
        except RepoNotFound as e:
            return TextOutcome("", "not_found", e.message)
        except RepoUnavailable as e:
            return TextOutcome("", "unavailable", e.message)

        # The crawl reports where it put things by putting them there.
        path = repo.resolve_location(result.location, result.key)
        if path is None:
            return TextOutcome(
                "", "no_file",
                f"{repo.NAME}: crawled {result.key}, but it holds nothing for "
                f'location "{result.location}"',
            )
        result.cache_file = str(path)

    if path is None or not path.exists():
        return TextOutcome("", "no_file", f"{repo.NAME}: {result.key} is not cached")

    # A document that is on disk but empty is a fetch that went wrong, not a
    # citation that is wrong. Handing it to the snippet check would blame the
    # quote for it.
    if path.stat().st_size == 0:
        return TextOutcome(
            "", "empty",
            f"{repo.NAME}: {result.key} is cached but empty; run --refresh",
        )

    # Duck-typed again: a custom repo need not override extraction at all.
    if hasattr(repo, "extract_content"):
        text = repo.extract_content(result.location, path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    # And now the fragment's own targeting, through the very same function the
    # fetcher path uses. `location:` is the repo's own hint — which chapter, which
    # lines — and the repo has just honoured it. A `section:` is a claim about
    # the *document*, and section parsing is format-level, so it applies just as
    # well to the text a repo returned as to a page that was fetched.
    #
    # Skipping this was a false pass: `section: "Chapter Nine Hundred"` on an MDN
    # URL verified green, because the repo returned the whole page and the
    # snippet was found somewhere in it. The identical fragment on a fetched URL
    # failed, correctly. Which answer you got depended on who served the file.
    format_name, locator = _apply_targeting(result, text)
    if locator:
        try:
            text = extract_content(text, locator,
                                   format_name=format_name, strict=True)
        except SectionNotFound as e:
            return TextOutcome("", "no_section", e.message)

    return TextOutcome(truncate(text, max_chars))


def load_text(result: ResolveResult, max_chars: int | None = 5000, *,
              force: bool = False, crawl: bool = True) -> TextOutcome:
    """Extract source text, and say why there is none when there is none.

    ``max_chars=None`` returns the whole document. Verification asks for that:
    a citation is either in the source or it is not, and a cap turns "I only
    read the first 100,000 characters" into "your snippet is not there".

    ``force`` re-fetches a fetcher-backed source and re-crawls a repo-backed
    one. ``crawl=False`` refuses to fetch a repo document that is not cached,
    reporting it instead — an honest miss rather than a quiet fetch of some
    other document.
    """
    if isinstance(result, FetcherResult) and result.fetcher is not None:
        body = result.fetcher.get(result.url, force=force)
        if not body:
            return TextOutcome("", "unavailable", f"could not fetch {result.url}")

        format_name, locator = _apply_targeting(result, body)
        try:
            text = extract_content(
                body, locator, format_name=format_name,
                strict=True,
            )
        except SectionNotFound as e:
            # The document arrived; it just has no such section. That is a
            # finding about the citation, and a different one from a document
            # that came back empty — which is the only thing it could say before.
            return TextOutcome("", "no_section", e.message)

        return TextOutcome(truncate(text, max_chars))

    if isinstance(result, RepoResult):
        return _load_repo_text(result, max_chars, force=force, crawl=crawl)

    return TextOutcome("", "no_file", "")


def get_text(result: ResolveResult, max_chars: int | None = 5000,
             *, force: bool = False) -> str:
    """Extract content text using the repo or fetcher from the resolve result.

    ``force=True`` bypasses the HTTP cache for fetcher-backed results, and
    re-crawls repo-backed ones. It used to do nothing at all for a repo, which
    is why ``--refresh`` could not refresh one.
    """
    return load_text(result, max_chars, force=force).text
