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

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, cast

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.documents import DocumentCache, document_key
from apysource.formats import (
    DEFAULT_FORMATS,
    detect_format,
    extract_content,
    truncate,
)
from apysource.http import CachedFetcher, document_url, url_anchor
from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry
from apysource.repos._base import BaseRepo
from apysource.repos.errors import RepoNotFound, RepoUnavailable
from apysource.sections import SectionNotFound, selector_for_anchor
from apysource.results import FetcherResult, RepoResult, ResolveResult, TextOutcome

logger = logging.getLogger(__name__)


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


def _apply_targeting(result: ResolveResult, text: str,
                     formats: list | None = None) -> tuple[str, str | None]:
    """The format and locator to extract with, once the document is in hand.

    An explicit ``section:``/``selector:`` always wins — the author said it
    outright. Only when they said nothing do we read the anchor their URL was
    already carrying, and only where we can be sure what it points at.
    """
    format_name = getattr(result, "format_name", "")
    locator = getattr(result, "locator", None)
    if locator or not result.anchor:
        return format_name, locator

    fmts = formats if formats is not None else DEFAULT_FORMATS
    inferred = selector_for_anchor(text, result.anchor, detect_format(text, fmts))
    if inferred is None:
        return format_name, locator
    return "section", inferred


def _load_repo_text(result: RepoResult, max_chars: int | None, *,
                    force: bool, crawl: bool,
                    cache: DocumentCache | None = None) -> TextOutcome:
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
    #
    # It runs with no locator too, exactly as the fetcher path does. A repo hands
    # back a *document*, not necessarily prose: one that returns markup was, for
    # an untargeted fragment, checked against its own tags, where a quote can
    # match a running header or an href and the page's real sentences — split by
    # every inline link — can match nothing at all. Asking the format what the
    # document says is the same question in both lanes, so it is asked the same
    # way. For a repo whose text is already prose this changes nothing: the
    # plain-text, Markdown and wikitext readers all answer with what they were
    # given.
    formats = cache.formats if cache is not None else DEFAULT_FORMATS
    format_name, locator = _apply_targeting(result, text, formats)
    try:
        text = extract_content(text, locator, format_name=format_name,
                               formats=formats, strict=True)
    except SectionNotFound as e:
        # Only reachable with a locator: no selector means the whole document,
        # and the whole document is never a section that went missing.
        return TextOutcome("", "no_section", e.message)

    return TextOutcome(truncate(text, max_chars))


def _needs_fetching(result: ResolveResult, force: bool) -> bool:
    """Would getting this document actually require the network?

    ``force`` means every document is being re-fetched, so the answer is yes
    whatever is on disk.

    A source that cannot answer — a stub fetcher in a test, a repo written
    before this contract — is assumed to need fetching. That is the safe way
    round: the cost of being wrong is a warm-up that was not needed, and the
    cost of the other answer is a serial crawl that thought it was parallel.
    """
    if force:
        return True

    if isinstance(result, FetcherResult) and result.fetcher is not None:
        cached = getattr(result.fetcher, "is_cached", None)
        return not cached(result.url) if callable(cached) else True

    if isinstance(result, RepoResult) and result.repo is not None:
        if not result.key:
            return False
        try:
            return not result.repo.is_cached(result.key)
        except Exception:  # noqa: BLE001 - a repo that cannot say gets warmed
            return True

    return False


def prefetch(results: Iterable[ResolveResult], *, cache: DocumentCache,
             workers: int = 1, force: bool = False, crawl: bool = True) -> None:
    """Warm the caches for a run's documents, several at a time.

    **This is advisory, and that is the whole design.** It returns nothing, and
    the only trace it leaves is in two caches that already existed and were
    already memoized: the fetcher's directory on disk, and ``BaseRepo._crawls``,
    which replays a crawl's outcome — including its failures — rather than
    repeating it. Skip this function entirely, or lose every worker to an
    exception, and the serial code that follows is unchanged and self-sufficient.
    It simply runs slower.

    That is what makes the report's ordering **provable** rather than merely
    tested. Nothing here appends to a result list, and nothing here decides a
    verdict; the checks that follow still walk ``fragments`` in the order they
    were given, on this thread. ``workers=1`` is not a special case handled
    somewhere — it is literally the behaviour this whole function is optional to.

    rdflib is never touched from a worker, and cannot be: resolution finished
    before this was called, and a ``ResolveResult`` holds plain strings. The
    store's documented lack of thread safety is therefore not in play.
    """
    if workers <= 1:
        return

    #: One task per *document*, not per fragment. Fifty citations of one page
    #: are one download, which is the same rule `document_url` already applies.
    #:
    #: And only documents that are not already here. This exists to overlap
    #: *network* waits; a document on disk has none to overlap, and warming it
    #: from a worker is pure cost — it reads and decodes the whole corpus up
    #: front, where the serial path would have read each one just before using
    #: it. Measured at about 7% on a fully warm run over a thousand documents,
    #: plus the memory to hold them all at once. A re-check of an unchanged
    #: sources file is the commonest thing this tool does, and it should not pay
    #: for a concurrency it cannot use.
    tasks: dict[str, ResolveResult] = {}
    for result in results:
        if result.status != "resolved":
            continue
        key = document_key(result)
        if key is not None and key not in tasks and _needs_fetching(result, force):
            tasks[key] = result

    # One document is not worth a thread pool; nor is none.
    if len(tasks) < 2:
        return

    def warm(key: str, result: ResolveResult) -> None:
        # Claimed here so the serial pass does not refresh the same document a
        # second time — and so `--refresh` is one request per document rather
        # than one per citation of it.
        forced = force and cache.claim_force(key)
        if isinstance(result, FetcherResult) and result.fetcher is not None:
            fetcher, url = result.fetcher, result.url
            # Stored, not merely fetched. Handing the body to the memo is what
            # makes this one read of the document rather than two — the serial
            # pass would otherwise ask the fetcher again and get the same bytes
            # back off disk.
            cache.body(key, lambda: fetcher.get(url, force=forced))
        elif isinstance(result, RepoResult) and result.repo is not None:
            if crawl and result.key:
                result.repo.ensure(result.key, force=forced)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(warm, key, result)
                   for key, result in tasks.items()]
        for future in futures:
            try:
                future.result()
            except BaseException as e:  # noqa: BLE001
                # A warm-up can never be *necessary*, so it must never be able
                # to fail the run. Whatever went wrong here will happen again on
                # the serial path, where there is a report to say it in.
                logger.debug("prefetch: %s", e)


def load_text(result: ResolveResult, max_chars: int | None = 5000, *,
              force: bool = False, crawl: bool = True,
              cache: DocumentCache | None = None) -> TextOutcome:
    """Extract source text, and say why there is none when there is none.

    ``max_chars=None`` returns the whole document. Verification asks for that:
    a citation is either in the source or it is not, and a cap turns "I only
    read the first 100,000 characters" into "your snippet is not there".

    ``force`` re-fetches a fetcher-backed source and re-crawls a repo-backed
    one. ``crawl=False`` refuses to fetch a repo document that is not cached,
    reporting it instead — an honest miss rather than a quiet fetch of some
    other document.

    ``cache`` memoizes both the document and the text a given targetting pulls
    out of it, for the length of one run. ``None`` — the default, and what every
    caller outside ``run_checks`` passes — does none of that and behaves exactly
    as this function always has.
    """
    if cache is not None:
        key = document_key(result)
        if key is not None:
            return _cached_load(result, max_chars, force=force, crawl=crawl,
                                cache=cache, key=key)

    return _load_text(result, max_chars, force=force, crawl=crawl)


def _cached_load(result: ResolveResult, max_chars: int | None, *,
                 force: bool, crawl: bool, cache: DocumentCache,
                 key: str) -> TextOutcome:
    """``load_text`` with the per-run memos in front of it.

    The extraction key carries everything that can change the answer for a given
    document: which format was named, what was targeted, the anchor the URL
    already carried, and how much was asked for. ``force`` is not part of it —
    it decides whether the document is fetched afresh, not what the extraction
    makes of it — and it is claimed once per document so a hundred fragments
    citing one page produce one refresh rather than a hundred.
    """
    if force and not cache.claim_force(key):
        force = False

    extract_key = (key, getattr(result, "format_name", ""),
                   getattr(result, "locator", None), result.anchor,
                   max_chars, crawl, force)

    return cache.extraction(
        extract_key,
        lambda: _load_text(result, max_chars, force=force, crawl=crawl,
                           cache=cache, key=key),
    )


def _load_text(result: ResolveResult, max_chars: int | None = 5000, *,
               force: bool = False, crawl: bool = True,
               cache: DocumentCache | None = None,
               key: str = "") -> TextOutcome:
    """The actual work, with no memoization of its own."""
    if isinstance(result, FetcherResult) and result.fetcher is not None:
        fetcher = result.fetcher
        url = result.url
        if cache is not None and not force:
            # Only a non-forced read may be answered from the body memo; a
            # forced one is the request that refills it.
            body = cache.body(key, lambda: fetcher.get(url, force=False))
        else:
            body = fetcher.get(url, force=force)
        if not body:
            return TextOutcome("", "unavailable", f"could not fetch {result.url}")

        formats = cache.formats if cache is not None else DEFAULT_FORMATS
        format_name, locator = _apply_targeting(result, body, formats)
        try:
            text = extract_content(
                body, locator, format_name=format_name, formats=formats,
                strict=True,
            )
        except SectionNotFound as e:
            # The document arrived; it just has no such section. That is a
            # finding about the citation, and a different one from a document
            # that came back empty — which is the only thing it could say before.
            return TextOutcome("", "no_section", e.message)

        return TextOutcome(truncate(text, max_chars))

    if isinstance(result, RepoResult):
        return _load_repo_text(result, max_chars, force=force, crawl=crawl,
                               cache=cache)

    return TextOutcome("", "no_file", "")


def get_text(result: ResolveResult, max_chars: int | None = 5000,
             *, force: bool = False) -> str:
    """Extract content text using the repo or fetcher from the resolve result.

    ``force=True`` bypasses the HTTP cache for fetcher-backed results, and
    re-crawls repo-backed ones. It used to do nothing at all for a repo, which
    is why ``--refresh`` could not refresh one.
    """
    return load_text(result, max_chars, force=force).text
