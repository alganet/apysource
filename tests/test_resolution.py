# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.resolution with synthetic RDF graphs."""

import re
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry
from apysource.resolution import get_text, resolve_chain, resolve_direct
from apysource.results import FetcherResult, RepoResult, ResolveResult


# ── Mock repo ────────────────────────────────────────────────────────

def _make_mock_repo(tmp_path):
    """Create a mock repo module-like object backed by tmp_path."""

    class MockRepo:
        NAME = "mock"

        def __init__(self, base):
            self._base = base
            self.url_pattern = re.compile(r"example\.com")

        def url_to_key(self, url):
            return "key1"

        def resolve_location(self, loc, key):
            p = self._base / key / "fulltext.txt"
            return p if p.exists() else None

        def extract_content(self, loc, path):
            return path.read_text()

    return MockRepo(tmp_path)


def _make_registry(mock_repo):
    """Create a RepoRegistry wrapping a single mock repo."""
    return RepoRegistry([mock_repo])


def _build_chain_graph(frag_uri, source_uri, url, location="lines:1-2"):
    """Build a minimal OA-native graph: Fragment → hasTarget → hasSource → Source."""
    g = Graph()
    g.add((frag_uri, RDF.type, SV.Fragment))
    g.add((frag_uri, RDFS.label, Literal("test fragment")))
    g.add((frag_uri, SV.sourceLocation, Literal(location)))

    # OA target chain (replaces sv:fragmentSource)
    target = BNode()
    g.add((frag_uri, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source_uri))

    g.add((source_uri, RDF.type, SV.Source))
    g.add((source_uri, RDFS.label, Literal("test source")))
    g.add((source_uri, SCHEMA.url, Literal(url)))
    return g


# ── resolve_chain ────────────────────────────────────────────────────

def test_resolve_chain_resolved(tmp_path):
    """Fragment with source and cached file resolves to 'resolved'."""
    mock = _make_mock_repo(tmp_path)
    registry = _make_registry(mock)
    item_dir = tmp_path / "key1"
    item_dir.mkdir()
    (item_dir / "fulltext.txt").write_text("line1\nline2\nline3")

    frag = URIRef("http://example.com/data/test#frag1")
    source = URIRef("http://example.com/data/test#src1")
    g = _build_chain_graph(frag, source, "http://example.com/item")

    result = resolve_chain(g, frag, registry)

    assert result.status == "resolved"
    assert result.module == "mock"


def test_resolve_chain_no_source():
    """Fragment without OA target returns 'no_source'."""
    g = Graph()
    frag = URIRef("http://example.com/data/test#frag1")
    g.add((frag, RDF.type, SV.Fragment))
    g.add((frag, RDFS.label, Literal("orphan fragment")))

    registry = RepoRegistry([])
    result = resolve_chain(g, frag, registry)
    assert result.status == "no_source"


# ── resolve_direct ───────────────────────────────────────────────────

def test_resolve_direct_resolved(tmp_path):
    """Entity with schema:url and cached file resolves to 'resolved'."""
    mock = _make_mock_repo(tmp_path)
    registry = _make_registry(mock)
    item_dir = tmp_path / "key1"
    item_dir.mkdir()
    (item_dir / "fulltext.txt").write_text("some text content")

    entity = URIRef("http://example.com/data/test#term1")
    g = Graph()
    g.add((entity, SCHEMA.url, Literal("http://example.com/item")))
    g.add((entity, SV.sourceLocation, Literal("chapter_one")))

    result = resolve_direct(g, entity, registry)

    assert result.status == "resolved"


def test_resolve_direct_no_url():
    """Entity without schema:url returns 'no_url'."""
    entity = URIRef("http://example.com/data/test#term1")
    g = Graph()
    g.add((entity, RDF.type, SV.Term))

    registry = RepoRegistry([])
    result = resolve_direct(g, entity, registry)
    assert result.status == "no_url"


# ── get_text ─────────────────────────────────────────────────────────

def test_get_text_with_cache_file(tmp_path):
    """get_text extracts text from cache file via mock repo."""
    mock = _make_mock_repo(tmp_path)
    item_dir = tmp_path / "key1"
    item_dir.mkdir()
    cache_file = item_dir / "fulltext.txt"
    cache_file.write_text("extracted passage text")

    frag_result = RepoResult(
        status="resolved",
        cache_file=str(cache_file),
        location="some_loc",
        url="http://example.com/item",
        repo=mock,
    )

    text = get_text(frag_result)

    assert "extracted passage text" in text


def test_get_text_without_cache_file():
    """get_text returns empty string when no cache_file in result."""
    frag_result = RepoResult(status="no_file", cache_file=None)
    text = get_text(frag_result)
    assert text == ""


# ── Fetcher fallback (repo-free) ────────────────────────────────────

class _MockFetcher:
    """Minimal mock for CachedFetcher."""

    def __init__(self, cached_content=None):
        self._content = cached_content

    def get(self, url, *, from_cache=False):
        return self._content


def _build_chain_graph_with_selectors(frag_uri, source_uri, url, source_type,
                                       css_selector=None, lines=None):
    """Build a graph with dcterms:format and OA selectors."""
    g = _build_chain_graph(frag_uri, source_uri, url)
    g.add((source_uri, DCTERMS.format, Literal(source_type)))

    # Get the existing target bnode
    target = g.value(frag_uri, OA.hasTarget)

    if css_selector:
        css = BNode()
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(css_selector)))
    if lines:
        g.add((frag_uri, SV.sourceLines, Literal(lines)))
    return g


def test_resolve_chain_http_fallback():
    """No matching repo but fetcher provided resolves via HTTP fallback."""
    frag = URIRef("http://other.com/data#frag1")
    source = URIRef("http://other.com/data#src1")
    fetcher = _MockFetcher()
    g = _build_chain_graph_with_selectors(
        frag, source, "http://other.com/page",
        "html", css_selector="div.content", lines="10-20",
    )

    registry = RepoRegistry([])
    result = resolve_chain(g, frag, registry, fetcher=fetcher)

    assert result.status == "resolved"
    assert result.module == "http"
    assert result.format_name == "html"
    assert result.locator == "div.content"
    assert result.fetcher is fetcher


def test_resolve_chain_no_fetcher_no_repo():
    """No repo and no fetcher still returns 'no_module'."""
    frag = URIRef("http://other.com/data#frag1")
    source = URIRef("http://other.com/data#src1")
    g = _build_chain_graph(frag, source, "http://other.com/page")

    registry = RepoRegistry([])
    result = resolve_chain(g, frag, registry)

    assert result.status == "no_module"


def test_resolve_direct_http_fallback():
    """Direct resolve with fetcher falls back to HTTP when no repo matches."""
    entity = URIRef("http://other.com/data#term1")
    g = Graph()
    g.add((entity, SCHEMA.url, Literal("http://other.com/page")))
    g.add((entity, DCTERMS.format, Literal("html")))

    # Add CSS selector via OA structure
    target = BNode()
    g.add((entity, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    css = BNode()
    g.add((target, OA.hasSelector, css))
    g.add((css, RDF.type, OA.CssSelector))
    g.add((css, RDF.value, Literal("p.extract")))

    fetcher = _MockFetcher()
    registry = RepoRegistry([])
    result = resolve_direct(g, entity, registry, fetcher=fetcher)

    assert result.status == "resolved"
    assert result.module == "http"
    assert result.locator == "p.extract"


def test_get_text_with_fetcher():
    """get_text extracts content via fetcher when result has fetcher key."""
    html = '<div><p class="target">Extracted text here</p></div>'
    fetcher = _MockFetcher(cached_content=html)

    result = FetcherResult(
        status="resolved",
        url="http://other.com/page",
        fetcher=fetcher,
        format_name="html",
        locator="p.target",
    )

    text = get_text(result)
    assert "Extracted text here" in text


def test_get_text_with_fetcher_no_cache():
    """get_text returns empty when fetcher has no cached content."""
    fetcher = _MockFetcher(cached_content=None)

    result = FetcherResult(
        status="resolved",
        url="http://other.com/page",
        fetcher=fetcher,
        format_name="html",
        locator="p.target",
    )

    text = get_text(result)
    assert text == ""
