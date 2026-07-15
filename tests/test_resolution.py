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
from apysource.repos._base import BaseRepo, RepoNotFound, RepoUnavailable
from apysource.resolution import get_text, load_text, resolve_chain, resolve_direct
from apysource.results import FetcherResult, RepoResult

from tests.conftest import EMPTY_REGISTRY, MockFetcher, build_chain_graph


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
    g = build_chain_graph(frag, source, "http://example.com/item")

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

def _build_chain_graph_with_selectors(frag_uri, source_uri, url, source_type,
                                       css_selector=None, lines=None):
    """Build a graph with dcterms:format and OA selectors."""
    g = build_chain_graph(frag_uri, source_uri, url)
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
    fetcher = MockFetcher()
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
    g = build_chain_graph(frag, source, "http://other.com/page")

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

    fetcher = MockFetcher()
    registry = RepoRegistry([])
    result = resolve_direct(g, entity, registry, fetcher=fetcher)

    assert result.status == "resolved"
    assert result.module == "http"
    assert result.locator == "p.extract"


def test_get_text_with_fetcher():
    """get_text extracts content via fetcher when result has fetcher key."""
    html = '<div><p class="target">Extracted text here</p></div>'
    fetcher = MockFetcher(html)

    result = FetcherResult(
        status="resolved",
        url="http://other.com/page",
        fetcher=fetcher,
        format_name="html",
        locator="p.target",
    )

    text = get_text(result)
    assert "Extracted text here" in text


def test_get_text_force_passes_through_to_fetcher():
    """get_text(force=True) bypasses the HTTP cache via fetcher.get(force=True)."""
    class _SpyFetcher(MockFetcher):
        def __init__(self):
            super().__init__("<p>body</p>")
            self.forces = []

        def get(self, url, **kwargs):
            self.forces.append(kwargs.get("force"))
            return super().get(url, **kwargs)

    fetcher = _SpyFetcher()
    result = FetcherResult(
        status="resolved", url="http://other.com/page",
        fetcher=fetcher, format_name="html", locator=None,
    )
    get_text(result, force=True)
    assert fetcher.forces == [True]


def test_get_text_with_fetcher_no_cache():
    """get_text returns empty when fetcher has no cached content."""
    fetcher = MockFetcher(None)

    result = FetcherResult(
        status="resolved",
        url="http://other.com/page",
        fetcher=fetcher,
        format_name="html",
        locator="p.target",
    )

    text = get_text(result)
    assert text == ""


# ── Routing is decided by the URL, not by the cache ───────────────────
#
# A repo used to win only if its file was already on disk. That made cache
# state decide *which document* a citation is checked against: cold, the
# citation quietly went to the generic fetcher and was verified against the
# rendered web page instead of the repository it names. These tests pin the
# routing so it cannot depend on what happens to be lying around.

class _CrawlingRepo(BaseRepo):
    """A repo that can fetch what it does not have."""

    NAME = "crawly"
    supports_crawl = True

    def __init__(self, tmp_path, missing=False, broken=False, empty=False):
        super().__init__(cache_dir=tmp_path, url_pattern=r"example\.com",
                         base_url="https://example.com")
        self.missing = missing
        self.broken = broken
        self.empty = empty
        self.crawls = []

    def url_to_key(self, url):
        return "key1"

    def resolve_location(self, loc, key):
        p = self.cache_dir / f"{key}.txt"
        return p if p.exists() else None

    def extract_content(self, loc, path):
        return path.read_text()

    def crawl(self, key, *, delay=None, force=False, from_cache=False):
        self.crawls.append((key, force))
        if self.missing:
            raise RepoNotFound(self.NAME, key, "404")
        if self.broken:
            raise RepoUnavailable(self.NAME, key, "connection reset")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.txt").write_text(
            "" if self.empty else "the document, crawled")


def _chain(url="https://example.com/page"):
    frag = URIRef("http://x/frag")
    g = build_chain_graph(frag, URIRef("http://x/src"), url, location="")
    return g, frag


def test_a_matched_repo_with_a_cold_cache_still_routes_to_the_repo(tmp_path):
    """The whole point: an empty cache must not change the source of truth."""
    g, frag = _chain()
    repo = _CrawlingRepo(tmp_path)
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    assert isinstance(result, RepoResult)
    assert result.cache_file is None  # nothing crawled yet, and that is fine
    assert result.key == "key1"


def test_load_text_crawls_a_cold_cache(tmp_path):
    g, frag = _chain()
    repo = _CrawlingRepo(tmp_path)
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    outcome = load_text(result)
    assert outcome.status == "ok"
    assert outcome.text == "the document, crawled"
    assert repo.crawls == [("key1", False)]


def test_load_text_does_not_crawl_a_warm_cache(tmp_path):
    (tmp_path / "key1.txt").write_text("already here")
    g, frag = _chain()
    repo = _CrawlingRepo(tmp_path)
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    assert load_text(result).text == "already here"
    assert repo.crawls == []


def test_refresh_recrawls_a_repo_whose_cache_is_already_warm(tmp_path):
    """--refresh could not refresh a repo at all: force was documented as a no-op.

    The cache file is deliberately present. B1 shipped inert on exactly this
    state, because nobody ran the warm case.
    """
    (tmp_path / "key1.txt").write_text("stale")
    g, frag = _chain()
    repo = _CrawlingRepo(tmp_path)
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    outcome = load_text(result, force=True)
    assert repo.crawls == [("key1", True)]
    assert outcome.text == "the document, crawled"


def test_a_missing_repo_page_never_reaches_the_fetcher(tmp_path):
    """The dangerous one.

    If a repo says "no such document" and the fetcher then answers anyway, the
    rendered page happily verifies a citation for a document the repository no
    longer has. Green, and wrong — and it is the exact bug the repo exists to
    kill, so it must be unreachable, not merely unlikely.
    """
    g, frag = _chain()
    fetcher = MockFetcher(content="<html>the snippet is right here</html>")
    result = resolve_chain(g, frag, RepoRegistry([_CrawlingRepo(tmp_path, missing=True)]),
                           fetcher=fetcher)

    outcome = load_text(result)
    assert outcome.status == "not_found"
    assert "no such document" in outcome.reason
    assert outcome.text == ""
    assert fetcher.calls == []


def test_a_transient_repo_failure_does_not_claim_the_page_is_missing(tmp_path):
    """A timeout is not an absence. Blaming the citation for one is a lie."""
    g, frag = _chain()
    result = resolve_chain(g, frag, RepoRegistry([_CrawlingRepo(tmp_path, broken=True)]),
                           fetcher=MockFetcher())

    outcome = load_text(result)
    assert outcome.status == "unavailable"
    assert "could not fetch" in outcome.reason
    assert "no such document" not in outcome.reason


def test_a_crawled_but_empty_document_is_not_a_snippet_failure(tmp_path):
    """An empty file on disk is a fetch that went wrong, not a bad quote."""
    g, frag = _chain()
    result = resolve_chain(g, frag, RepoRegistry([_CrawlingRepo(tmp_path, empty=True)]),
                           fetcher=MockFetcher())

    outcome = load_text(result)
    assert outcome.status == "empty"
    assert "cached but empty" in outcome.reason


def test_no_crawl_reports_a_cold_repo_instead_of_fetching_it(tmp_path):
    g, frag = _chain()
    fetcher = MockFetcher()
    repo = _CrawlingRepo(tmp_path)
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=fetcher)

    outcome = load_text(result, crawl=False)
    assert outcome.status == "no_file"
    assert "crawling is off" in outcome.reason
    assert repo.crawls == []
    assert fetcher.calls == []


# ── Falling back to the fetcher, out loud ────────────────────────────

def test_a_repo_without_a_crawler_falls_back_but_names_itself(tmp_path):
    """Falling back is allowed. Doing it silently is not.

    The snippet gets verified against the rendered page rather than against
    the repository the citation names — a different document, and the report
    has to be able to say so.
    """
    g, frag = _chain()
    result = resolve_chain(g, frag, _make_registry(_make_mock_repo(tmp_path)),
                           fetcher=MockFetcher())

    assert isinstance(result, FetcherResult)
    assert result.fallback_from == "mock"
    assert "no crawler" in result.fallback_reason


def test_a_repo_fallback_warns_on_a_warm_cache_too(tmp_path):
    """State-independence, which is what B1 lacked.

    The fallback is decided by the pattern and the crawler, never by disk, so
    a warm HTTP cache cannot render this inert the way it did the redirect check.
    """
    g, frag = _chain()
    fetcher = MockFetcher()
    reg = _make_registry(_make_mock_repo(tmp_path))

    first = resolve_chain(g, frag, reg, fetcher=fetcher)
    load_text(first)
    second = resolve_chain(g, frag, reg, fetcher=fetcher)

    assert second.fallback_from == "mock"


def test_a_url_the_repo_cannot_key_falls_back_but_names_itself(tmp_path):
    class _KeylessRepo(BaseRepo):
        NAME = "keyless"

        def url_to_key(self, url):
            return None

    repo = _KeylessRepo(cache_dir=tmp_path, url_pattern=r"example\.com",
                        base_url="https://example.com")
    g, frag = _chain()
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    assert isinstance(result, FetcherResult)
    assert result.fallback_from == "keyless"
    assert "no key" in result.fallback_reason


def test_a_url_no_repo_claims_reports_no_fallback(tmp_path):
    """A plain HTTP source is not "falling back" from anything."""
    g, frag = _chain(url="https://unclaimed.test/page")
    result = resolve_chain(g, frag, RepoRegistry([_CrawlingRepo(tmp_path)]),
                           fetcher=MockFetcher())

    assert isinstance(result, FetcherResult)
    assert result.fallback_from == ""


def test_a_duck_typed_repo_survives_a_cold_cache(tmp_path):
    """Custom repos predate this contract and are read with getattr.

    One that never heard of supports_crawl has no crawler — which is the safe
    reading of it, and must not be a crash.
    """
    class _Legacy:
        NAME = "legacy"
        url_pattern = re.compile(r"example\.com")

        def url_to_key(self, url):
            return "key1"

        def resolve_location(self, loc, key):
            return None

    g, frag = _chain()
    result = resolve_chain(g, frag, RepoRegistry([_Legacy()]), fetcher=MockFetcher())
    assert isinstance(result, FetcherResult)
    assert result.fallback_from == "legacy"


def test_get_text_still_returns_a_bare_string(tmp_path):
    """The old signature keeps working for anyone calling the library."""
    (tmp_path / "key1.txt").write_text("plain text please")
    g, frag = _chain()
    result = resolve_chain(g, frag, RepoRegistry([_CrawlingRepo(tmp_path)]),
                           fetcher=MockFetcher())
    assert get_text(result) == "plain text please"


def test_resolve_direct_routes_by_pattern_too(tmp_path):
    """resolve_direct and resolve_chain share one repo branch, so they cannot drift."""
    entity = URIRef("http://x/term")
    g = Graph()
    g.add((entity, RDF.type, SV.Term))
    g.add((entity, SCHEMA.url, Literal("https://example.com/page")))

    result = resolve_direct(g, entity, RepoRegistry([_CrawlingRepo(tmp_path)]),
                            fetcher=MockFetcher())
    assert isinstance(result, RepoResult)
    assert result.key == "key1"
    assert result.cache_file is None
    assert load_text(result).text == "the document, crawled"


# ── A section that is not there (A2) ─────────────────────────────────

RFC_BODY = (Path(__file__).parent / "fixtures" / "rfc2616.txt").read_text(
    encoding="utf-8")


def _section_outcome(section):
    frag = URIRef("http://x/frag")
    g = build_chain_graph(frag, URIRef("http://x/src"),
                          "https://rfc.test/rfc2616.txt", location="")
    target = next(g.objects(frag, OA.hasTarget))
    sel = BNode()
    g.add((target, OA.hasSelector, sel))
    g.add((sel, RDF.type, SV.SectionSelector))
    g.add((sel, RDF.value, Literal(section)))

    result = resolve_chain(g, frag, EMPTY_REGISTRY,
                           fetcher=MockFetcher(content=RFC_BODY))
    return load_text(result)


def test_a_real_section_still_extracts():
    outcome = _section_outcome("§ 1.4")
    assert outcome.status == "ok"
    assert outcome.text.strip()


def test_a_missing_section_is_not_an_empty_extraction():
    """It used to be indistinguishable from a document that came back empty."""
    outcome = _section_outcome("§ 99.9")
    assert outcome.status == "no_section"
    assert "no section matches" in outcome.reason
    assert "empty extraction" not in outcome.reason


def test_a_missing_section_names_sections_that_exist():
    outcome = _section_outcome("§ 1.5")
    assert "§ 1.4" in outcome.reason


def test_a_section_selector_on_a_plain_document_says_so():
    """Plain text has no headings to target; blaming the selector was wrong."""
    frag = URIRef("http://x/frag")
    g = build_chain_graph(frag, URIRef("http://x/src"),
                          "https://plain.test/notes.txt", location="")
    target = next(g.objects(frag, OA.hasTarget))
    sel = BNode()
    g.add((target, OA.hasSelector, sel))
    g.add((sel, RDF.type, SV.SectionSelector))
    g.add((sel, RDF.value, Literal("§ 1")))

    result = resolve_chain(g, frag, EMPTY_REGISTRY,
                           fetcher=MockFetcher(content="just some loose prose\n"))
    outcome = load_text(result)
    assert outcome.status == "no_section"
    assert "no section structure" in outcome.reason


# ── An anchor is not a document (stray-bug tranche) ──────────────────

def test_a_repo_is_asked_about_the_document_not_the_anchor(tmp_path):
    """Every repo is protected here, not one url_pattern at a time.

    A repo whose pattern ends in a greedy `(.+)` — which a third-party repo
    is perfectly free to do — would take `#English` into its cache key and
    keep a second copy of the same page under it. Resolution hands repos the
    document, so a greedy pattern has nothing to be greedy about.
    """
    seen = []

    class GreedyRepo(BaseRepo):
        NAME = "greedy"

        def url_to_key(self, url):
            seen.append(url)
            m = self.url_pattern.search(url)
            return m.group(1) if m else None

        def resolve_location(self, loc, key):
            p = self.cache_root / f"{key}.txt"
            return p if p.exists() else None

    repo = GreedyRepo(cache_dir=tmp_path, url_pattern=r"example\.com/wiki/(.+)",
                      base_url="https://example.com")
    (tmp_path / "Aphrodite.txt").write_text("the passage")

    g, frag = _chain("https://example.com/wiki/Aphrodite#English")
    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())

    assert seen == ["https://example.com/wiki/Aphrodite"]
    assert isinstance(result, RepoResult)
    assert result.key == "Aphrodite"
    assert result.cache_file is not None, "the anchor must not hide the cached page"


def test_the_citation_keeps_the_anchor_the_author_wrote(tmp_path):
    """The document is what we fetch; the URL is what we report. Not the same thing.

    Stripping the anchor from the result would make the report name a URL the
    author never wrote — and would throw away the one piece of targeting they
    already gave us (C3).
    """
    url = "https://www.rfc-editor.org/rfc/rfc9110.html#section-7.2"
    g, frag = _chain(url)
    result = resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=MockFetcher())
    assert result.url == url


# ── A repo honours the fragment's targeting, like everyone else ──────────

def _repo_with(tmp_path, body, name="mock"):
    """A repo serving one document, so we can test what happens after it."""
    (tmp_path / "doc.md").write_text(body)

    class Repo(BaseRepo):
        NAME = name

        def url_to_key(self, url):
            return "doc"

        def resolve_location(self, loc, key):
            p = self.cache_root / "doc.md"
            return p if p.exists() else None

    return Repo(cache_dir=tmp_path, url_pattern=r"example\.com",
                base_url="https://example.com")


_DOC = ("# Origin header\nThe HTTP Origin request header indicates the origin.\n\n"
        "## Syntax\nOrigin: null\n\n"
        "## Directives\nA directive is a thing.\n")


def _section_fragment(section):
    frag = URIRef("urn:test:frag")
    g = build_chain_graph(frag, URIRef("urn:test:src"),
                          "https://example.com/doc", location="")
    target = g.value(frag, OA.hasTarget)
    sel = BNode()
    g.add((target, OA.hasSelector, sel))
    g.add((sel, RDF.type, SV.SectionSelector))
    g.add((sel, RDF.value, Literal(section)))
    return g, frag


def test_a_section_that_does_not_exist_fails_on_the_repo_path_too(tmp_path):
    """It verified GREEN. This is the worst defect the audit turned up.

    A repo was handed only `location:`; a `section:` was dropped without a word.
    So `section: "Chapter Nine Hundred"` — naming a section the document does
    not have — passed, because the repo returned the whole page and the snippet
    was found somewhere in it. The identical fragment on a *fetched* URL failed
    correctly. Which answer you got depended on who served the file.
    """
    repo = _repo_with(tmp_path, _DOC)
    g, frag = _section_fragment("Chapter Nine Hundred")

    result = resolve_chain(g, frag, RepoRegistry([repo]), fetcher=MockFetcher())
    assert isinstance(result, RepoResult)

    outcome = load_text(result, max_chars=None)
    assert outcome.status == "no_section", \
        f"a nonexistent section must not extract anything, got {outcome.text!r}"
    assert "Chapter Nine Hundred" in outcome.reason


def test_a_repo_section_scopes_the_snippet_like_a_fetched_one(tmp_path):
    """And the flip side: the section must actually *narrow* the text.

    Otherwise the quote is matched against the whole page and section targeting
    is decorative — which is precisely what it was.
    """
    repo = _repo_with(tmp_path, _DOC)
    registry = RepoRegistry([repo])
    sentence = "The HTTP Origin request header indicates the origin."

    g, frag = _section_fragment("Origin header")
    right = load_text(resolve_chain(g, frag, registry, fetcher=MockFetcher()),
                      max_chars=None)
    assert right.status == "ok" and sentence in right.text

    g, frag = _section_fragment("Syntax")
    wrong = load_text(resolve_chain(g, frag, registry, fetcher=MockFetcher()),
                      max_chars=None)
    assert wrong.status == "ok"
    assert sentence not in wrong.text, \
        "the sentence is not in § Syntax; the section must scope the match"


# ── The anchor the citation already carried (C3) ─────────────────────────

_RFC_ISH = ("# 7. Fields\nFields are things.\n\n"
            "## 7.2 Host\nThe Host header field provides the host and port.\n\n"
            "# 15. Status Codes\nA status code is a three-digit integer.\n")


def _anchored(url, section=None):
    frag = URIRef("urn:test:frag")
    g = build_chain_graph(frag, URIRef("urn:test:src"), url, location="")
    g.add((URIRef("urn:test:src"), DCTERMS.format, Literal("text/markdown")))
    if section:
        target = g.value(frag, OA.hasTarget)
        sel = BNode()
        g.add((target, OA.hasSelector, sel))
        g.add((sel, RDF.type, SV.SectionSelector))
        g.add((sel, RDF.value, Literal(section)))
    return g, frag


def test_an_anchor_scopes_the_check_to_the_section_it_names():
    """`rfc9110.html#section-7.2` was checked against the whole of RFC 9110.

    The anchor is targeting the author already wrote down, in their own hand,
    and nothing read it. lint-http's ~350 references all carry one.
    """
    fetcher = MockFetcher(content=_RFC_ISH)
    g, frag = _anchored("https://example.com/spec#section-7.2")
    out = load_text(resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=fetcher),
                    max_chars=None)

    assert out.status == "ok"
    assert "Host header field" in out.text
    assert "three-digit integer" not in out.text, \
        "the anchor names § 7.2; § 15 must not be in scope"


def test_a_quote_from_the_wrong_section_now_fails():
    """The point of scoping. This used to pass against the whole document."""
    fetcher = MockFetcher(content=_RFC_ISH)
    g, frag = _anchored("https://example.com/spec#section-7.2")
    out = load_text(resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=fetcher),
                    max_chars=None)
    assert "three-digit integer" not in out.text


def test_an_explicit_section_beats_the_anchor():
    """The author said it outright; a guess must not override a statement."""
    fetcher = MockFetcher(content=_RFC_ISH)
    g, frag = _anchored("https://example.com/spec#section-7.2",
                        section="§ 15")
    out = load_text(resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=fetcher),
                    max_chars=None)

    assert out.status == "ok"
    assert "three-digit integer" in out.text
    assert "Host header field" not in out.text


def test_an_anchor_we_cannot_read_leaves_the_scope_alone():
    """A guess of ours must never be able to condemn a citation.

    `#page-42` names no section. We do not narrow, we do not fail — we check the
    whole document, exactly as before anchors were read at all.
    """
    fetcher = MockFetcher(content=_RFC_ISH)
    g, frag = _anchored("https://example.com/spec#page-42")
    out = load_text(resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=fetcher),
                    max_chars=None)

    assert out.status == "ok"
    assert "Host header field" in out.text
    assert "three-digit integer" in out.text


def test_an_anchor_naming_a_section_that_is_gone_says_so():
    """`#section-99.9` is the author's claim about the document, and it is false.

    Widening back to the whole document would let the citation pass and hide the
    rot. This is the one inference confident enough to fail on.
    """
    fetcher = MockFetcher(content=_RFC_ISH)
    g, frag = _anchored("https://example.com/spec#section-99.9")
    out = load_text(resolve_chain(g, frag, EMPTY_REGISTRY, fetcher=fetcher),
                    max_chars=None)

    assert out.status == "no_section"
    assert "99.9" in out.reason
