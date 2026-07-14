# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Resolve entity sourceLocation to cached source text.

All functions require a RepoRegistry instance — no global state.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.formats import extract_content, truncate
from apysource.http import CachedFetcher
from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry
from apysource.results import FetcherResult, RepoResult, ResolveResult


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

    repo = registry.get_repo(url)
    if repo:
        key = repo.url_to_key(url)
        cache_file = repo.resolve_location(location, key) if key else None
        if cache_file:
            return RepoResult(
                status="resolved",
                label=label, location=location, source=source_label,
                url=url, module=repo.NAME, repo=repo,
                cache_file=str(cache_file),
            )

    if fetcher:
        section = _get_selector_value(g, frag_uri, SV.SectionSelector)
        if section:
            format_name = "section"
            locator: str | None = section
        else:
            format_name = str(g.value(source, DCTERMS.format) or "")
            css = _get_selector_value(g, frag_uri, OA.CssSelector)
            lines = str(g.value(frag_uri, SV.sourceLines) or "")
            locator = (css or lines) or None
        return FetcherResult(
            status="resolved", label=label, location=location,
            source=source_label, url=url,
            fetcher=fetcher, format_name=format_name, locator=locator,
        )

    return ResolveResult(status="no_module", label=label, url=url,
                         source=source_label)


def resolve_direct(g: Graph, entity_uri: URIRef, registry: RepoRegistry,
                    fetcher: CachedFetcher | None = None) -> ResolveResult:
    """Resolve any entity with schema:url directly on it."""
    url = str(g.value(entity_uri, SCHEMA.url) or "")
    location = str(g.value(entity_uri, SV.sourceLocation) or "")

    if not url:
        return ResolveResult(status="no_url")

    repo = registry.get_repo(url)
    if repo:
        key = repo.url_to_key(url)
        cache_file = repo.resolve_location(location, key) if key else None
        if cache_file:
            return RepoResult(
                status="resolved",
                url=url, location=location, module=repo.NAME,
                repo=repo, cache_file=str(cache_file),
            )

    if fetcher:
        section = _get_selector_value(g, entity_uri, SV.SectionSelector)
        if section:
            format_name = "section"
            locator: str | None = section
        else:
            format_name = str(g.value(entity_uri, DCTERMS.format) or "")
            css = _get_selector_value(g, entity_uri, OA.CssSelector)
            lines = str(g.value(entity_uri, SV.sourceLines) or "")
            locator = (css or lines) or None
        return FetcherResult(
            status="resolved", url=url, location=location,
            fetcher=fetcher, format_name=format_name, locator=locator,
        )

    return ResolveResult(status="no_module", url=url)


def get_text(result: ResolveResult, max_chars: int = 5000,
             *, force: bool = False) -> str:
    """Extract content text using the repo or fetcher from the resolve result.

    ``force=True`` bypasses the HTTP cache for fetcher-backed results, causing
    a fresh download (and re-cache). It has no effect on repo-backed results,
    which read already-crawled files.
    """
    if isinstance(result, FetcherResult) and result.fetcher is not None:
        body = result.fetcher.get(result.url, force=force)
        if not body:
            return ""

        text = extract_content(
            body, result.locator, format_name=result.format_name,
        )
        return truncate(text, max_chars)

    if isinstance(result, RepoResult):
        if not result.cache_file:
            return ""
        path = Path(result.cache_file)
        if not path.exists():
            return ""
        if result.repo and hasattr(result.repo, "extract_content"):
            text = result.repo.extract_content(result.location, path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return truncate(text, max_chars)

    return ""
