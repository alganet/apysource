# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the MDN repository module.

The fixture is the real ``mdn/content`` Markdown for the Origin page, so the
normalizer is exercised against actual KumaScript rather than a hand-written
approximation of it. The prototype this module replaces was validated against a
single sentence of that page — the only one whose macros it happened to handle —
and was wrong about four of the other five. Hence RENDERED, below: those strings
were copied from the page as a browser shows it.
"""

from pathlib import Path

import pytest
from rdflib import BNode, Literal, URIRef
from rdflib.namespace import RDF

from apysource.formats import normalize_ws
from apysource.namespaces import OA, SV
from apysource.repos import RepoRegistry
from apysource.repos._base import RepoNotFound, RepoUnavailable
from apysource.repos.mdn import MACRO_MARK, MdnRepo, render, slug_to_folder
from apysource.verification import run_checks

from tests.conftest import MockFetcher, build_chain_graph

FIXTURE = Path(__file__).parent / "fixtures" / "mdn_origin.md"
URL_PATTERN = r"developer\.mozilla\.org/(?i:en-US)/docs/([^#?\s]+)"
BASE_URL = "https://raw.githubusercontent.com/mdn/content/main/files"


def _mdn(tmp_path, fetcher=None, **kw):
    kw.setdefault("crawl_delay", 0.0)
    return MdnRepo(cache_dir=tmp_path, http_client=fetcher,
                   url_pattern=URL_PATTERN, base_url=BASE_URL, **kw)


#: Sentences as the rendered MDN page shows them, copied from the browser.
#: Every one but the first is broken by the prototype's normalizer.
RENDERED = [
    # The one sentence the prototype got right — and the only one it tested.
    "The HTTP Origin request header indicates the origin (scheme, hostname, "
    "and port) that caused the request.",
    # {{HTTPHeader("Referer")}} renders as the word. Deleting it produced
    # "similar to the header" — prose the page never showed.
    "The Origin header is similar to the Referer header, but does not disclose "
    "the path, and may be null.",
    # {{Glossary("CORS", "cross origin")}} renders its SECOND argument.
    "cross origin requests.",
    # {{HTTPMethod("GET")}} and friends render as the method names.
    "same-origin requests except for GET or HEAD requests (i.e., they are "
    "added to same-origin POST, OPTIONS, PUT, PATCH, and DELETE requests).",
    # {{HTMLElement("img")}} renders as "<img>", angle brackets and all.
    "Cross-origin images and media data, including that in <img>, <video> and "
    "<audio> elements.",
    # {{HTMLElement("iframe", "iframes")}} renders its display argument.
    "iframes with a sandbox attribute whose value doesn't include "
    "allow-same-origin.",
]


# ── The normalizer reproduces what a reader saw ──────────────────────

@pytest.mark.parametrize("sentence", RENDERED)
def test_mdn_normalizer_reproduces_the_rendered_sentence(sentence):
    """The whole contract: quote what the browser showed you, and it verifies.

    A macro that renders as a word must come out as that word. If it does not,
    a correct citation fails — and the near-miss hint then tells the author that
    a word in front of them is missing, which is a lie about the source.
    """
    out = normalize_ws(render(FIXTURE.read_text()))
    assert normalize_ws(sentence) in out


def test_mdn_deleted_macro_cannot_forge_a_phrase():
    """Deleting a macro sews its neighbours into a sentence the page never showed.

    "similar to the {{HTTPHeader("Referer")}} header" must never normalize to
    "similar to the header" — a citation that invented that would verify green.
    """
    out = normalize_ws(render("similar to the {{Compat}} header"))
    assert "similar to the header" not in out
    assert MACRO_MARK in out


def test_mdn_macro_debris_never_reaches_the_text():
    """No braces survive into the text a snippet is matched against."""
    out = render(FIXTURE.read_text())
    assert "{{" not in out and "}}" not in out


def test_mdn_pathological_macros_are_marked_not_left_behind():
    """A macro whose arguments hold braces defeats the parse. Mark it anyway."""
    out = render('a {{Foo({"a": 1})}} b')
    assert "{{" not in out and "}}" not in out
    assert MACRO_MARK in out


def test_mdn_generated_tables_cannot_be_quoted():
    """{{Compat}} and {{Specifications}} generate text this file does not hold.

    It cannot be reconstructed, so it must not be faked — a quote of it fails,
    and the mark in the diff says why.
    """
    out = render(FIXTURE.read_text())
    assert "Browser compatibility" in out  # the heading is real
    assert MACRO_MARK in out               # the table it introduces is not


# ── Code survives the normalizer ─────────────────────────────────────

def test_mdn_code_samples_are_not_mutated():
    """Real case, Origin page: "Origin: <scheme>://<hostname>" in a fence.

    Strip HTML tags without masking code first and the syntax is eaten.
    """
    out = render(FIXTURE.read_text())
    assert "Origin: <scheme>://<hostname>" in out
    assert "Origin: <scheme>://<hostname>:<port>" in out


def test_mdn_code_is_not_read_as_markup():
    body = "text\n\n```js\n2 ** 3\n```\n\nand `{{ user.name }}` inline\n"
    out = render(body)
    assert "2 ** 3" in out                 # not bold
    assert "{{ user.name }}" in out        # not a KumaScript macro


def test_mdn_no_front_matter_is_left_alone():
    assert render("Just prose, no front matter.") == "Just prose, no front matter."


def test_mdn_front_matter_becomes_the_rendered_h1():
    out = render("---\ntitle: Origin header\nslug: Web/HTTP\n---\n\nBody.\n")
    assert "# Origin header" in out
    assert "slug" not in out  # never rendered, so never quotable


# ── Sections ─────────────────────────────────────────────────────────

def test_mdn_extract_content_selects_a_section(tmp_path):
    repo = _mdn(tmp_path)
    out = repo.extract_content("Syntax", FIXTURE)
    assert "Origin: null" in out
    assert "is similar to the Referer header" not in out  # that is Description


def test_mdn_a_missing_section_extracts_nothing(tmp_path):
    """A loud miss beats quietly falling back to the whole page."""
    assert _mdn(tmp_path).extract_content("Nonexistent", FIXTURE) == ""


# ── URL -> key ───────────────────────────────────────────────────────

def test_mdn_url_to_key(tmp_path):
    repo = _mdn(tmp_path)
    key = repo.url_to_key(
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin")
    assert key == "en-us/web/http/reference/headers/origin"


def test_mdn_url_to_key_ignores_fragment_and_query(tmp_path):
    repo = _mdn(tmp_path)
    for suffix in ("#syntax", "?x=1", "/"):
        key = repo.url_to_key(
            f"https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin{suffix}")
        assert key == "en-us/web/http/headers/origin"


def test_mdn_url_to_key_mangles_special_characters(tmp_path):
    """Web/CSS/:hover lives at .../_colon_hover in mdn/content.

    Without this, every pseudo-class page 404s and a real page is reported
    missing.
    """
    repo = _mdn(tmp_path)
    assert repo.url_to_key(
        "https://developer.mozilla.org/en-US/docs/Web/CSS/:hover",
    ).endswith("/_colon_hover")
    assert repo.url_to_key(
        "https://developer.mozilla.org/en-US/docs/Web/CSS/::before",
    ).endswith("/_doublecolon_before")
    # Percent-encoded, as a browser would give it.
    assert repo.url_to_key(
        "https://developer.mozilla.org/en-US/docs/Web/CSS/%3Ahover",
    ).endswith("/_colon_hover")


def test_slug_to_folder_matches_yari():
    assert slug_to_folder("Web/CSS/:hover") == "web/css/_colon_hover"
    assert slug_to_folder("Web/CSS/::before") == "web/css/_doublecolon_before"
    assert slug_to_folder("Web/CSS/*") == "web/css/_star_"


def test_mdn_url_to_key_refuses_traversal(tmp_path):
    """The key becomes a filesystem path; a URL is not a reason to trust it."""
    repo = _mdn(tmp_path)
    assert repo.url_to_key(
        "https://developer.mozilla.org/en-US/docs/../../etc/passwd") is None


def test_mdn_non_english_locale_does_not_match(tmp_path):
    """Deliberate: translations live in mdn/translated-content, not here.

    Matching /fr/docs/ and mapping it into files/fr/ would 404 on every French
    citation and report every live, correctly-cited page as missing — a
    confident wrong answer at a 100% rate, across a whole locale. Not matching
    hands it to the generic fetcher, which at least redirect-warns it.
    """
    repo = _mdn(tmp_path)
    assert repo.url_pattern.search(
        "https://developer.mozilla.org/fr/docs/Web/HTTP/Headers/Origin") is None
    assert repo.url_pattern.search(
        "https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/Origin") is None
    # But the locale's own case must not be a way to slip past the repo.
    assert repo.url_pattern.search(
        "https://developer.mozilla.org/en-us/docs/Web/HTTP/Headers/Origin")


# ── Crawling ─────────────────────────────────────────────────────────

def test_mdn_resolve_location_is_a_pure_cache_lookup(tmp_path):
    """The prototype fetched inside resolve_location. Resolution does not fetch."""
    fetcher = MockFetcher()
    repo = _mdn(tmp_path, fetcher)
    assert repo.resolve_location("", "en-us/web/http/headers/origin") is None
    assert fetcher.calls == []


def test_mdn_crawl_writes_then_resolve_finds(tmp_path):
    fetcher = MockFetcher(content="# Origin\n\nSome prose.\n")
    repo = _mdn(tmp_path, fetcher)
    repo.crawl("en-us/web/http/reference/headers/origin")

    path = repo.resolve_location("", "en-us/web/http/reference/headers/origin")
    assert path is not None and path.read_text().startswith("# Origin")
    assert fetcher.calls == [
        f"{BASE_URL}/en-us/web/http/reference/headers/origin/index.md"]


def test_mdn_404_is_not_an_empty_page(tmp_path):
    """The stale-URL case, and the prototype's worst habit.

    A moved page 404s. The prototype cached a 0-byte file for it, so the failure
    arrived as "empty extraction (0 chars)" — blamed on the citation, and stuck
    that way until someone passed --refresh even after MDN restored the page.
    """
    repo = _mdn(tmp_path, MockFetcher(content=None))
    with pytest.raises(RepoNotFound):
        repo.crawl("en-us/web/http/headers/origin")
    assert not any(tmp_path.rglob("index.md"))


def test_mdn_an_empty_body_writes_nothing(tmp_path):
    repo = _mdn(tmp_path, MockFetcher(content="   \n"))
    with pytest.raises(RepoNotFound):
        repo.crawl("en-us/web/http/headers/origin")
    assert not any(tmp_path.rglob("index.md"))


def test_mdn_an_outage_is_not_a_missing_page(tmp_path):
    """GitHub being down must not report the citation as rotten."""
    repo = _mdn(tmp_path, MockFetcher(content=None, statuses={"index.md": None}))
    with pytest.raises(RepoUnavailable):
        repo.crawl("en-us/web/http/reference/headers/origin")


def test_mdn_crawl_passes_the_repo_delay_to_the_fetcher(tmp_path):
    """raw.githubusercontent is a CDN; it does not need the 3s courtesy gap."""
    fetcher = MockFetcher(content="# Origin\n\nProse.\n")
    repo = _mdn(tmp_path, fetcher, crawl_delay=0.5)
    repo.crawl("en-us/web/http/reference/headers/origin")
    assert fetcher.requests[0][1]["delay"] == 0.5


def test_mdn_crawl_uses_the_cache(tmp_path):
    key = "en-us/web/http/reference/headers/origin"
    (tmp_path / key).mkdir(parents=True)
    (tmp_path / key / "index.md").write_text("cached")

    fetcher = MockFetcher()
    _mdn(tmp_path, fetcher).crawl(key)
    assert fetcher.calls == []


def test_mdn_force_refetches(tmp_path):
    key = "en-us/web/http/reference/headers/origin"
    (tmp_path / key).mkdir(parents=True)
    (tmp_path / key / "index.md").write_text("stale")

    fetcher = MockFetcher(content="fresh")
    _mdn(tmp_path, fetcher).crawl(key, force=True)
    assert (tmp_path / key / "index.md").read_text() == "fresh"


# ── End to end: the reason this module exists ────────────────────────

def _mdn_run(tmp_path, url, snippet, fetcher, **kw):
    """Run the real checks over one MDN citation."""
    frag = URIRef("http://x/frag")
    g = build_chain_graph(frag, URIRef("http://x/src"), url, location="")
    target = next(g.objects(frag, OA.hasTarget))
    sel = BNode()
    g.add((target, OA.hasSelector, sel))
    g.add((sel, RDF.type, OA.TextQuoteSelector))
    g.add((sel, OA.exact, Literal(snippet)))

    repo = _mdn(tmp_path, fetcher)
    checks_config = [{"name": "Fragments", "class_uri": SV.Fragment,
                      "mode": "chain"}]
    results = run_checks(g, checks_config, RepoRegistry([repo]),
                         fetcher=fetcher, **kw)
    return {c.name: c for c in results}


CANONICAL = ("https://developer.mozilla.org"
             "/en-US/docs/Web/HTTP/Reference/Headers/Origin")
STALE = "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin"
QUOTE = RENDERED[1]  # the Referer sentence — the one the prototype broke


class _MdnFetcher(MockFetcher):
    """Serves mdn/content for the canonical slug, 404s the stale one.

    And serves the *rendered page* — containing the very snippet — for the
    developer.mozilla.org URL, which is what a redirect would have led to. That
    is the trap: if the repo falls back to HTTP, the citation passes.
    """

    def _body(self, url):
        if "raw.githubusercontent.com" in url:
            if "reference/headers/origin" in url:
                return FIXTURE.read_text()
            return None  # the stale slug is gone from mdn/content
        return f"<html><body><p>{QUOTE}</p></body></html>"


def test_mdn_canonical_url_verifies_against_the_authored_markdown(tmp_path):
    checks = _mdn_run(tmp_path, CANONICAL, QUOTE, _MdnFetcher())
    assert checks["Fragments: snippet verified"].ok == 1
    assert checks["Repo documents"].failures == []


def test_mdn_stale_url_fails_and_does_not_fall_back(tmp_path):
    """The test the whole tranche exists to pass.

    The stale URL still 301s on the live web to a page that contains this exact
    sentence — so the generic fetcher verifies it green, which is precisely the
    rot MdnRepo is here to catch. If the repo can fall back to HTTP when its own
    lookup misses, the feature is decoration: it would pass here.
    """
    fetcher = _MdnFetcher()
    checks = _mdn_run(tmp_path, STALE, QUOTE, fetcher)

    assert checks["Fragments: snippet verified"].ok == 0
    assert len(checks["Repo documents"].failures) == 1
    assert "no such document" in checks["Repo documents"].failures[0].reason

    # And it never asked the rendered page, which would have said yes.
    assert not any("developer.mozilla.org" in c for c in fetcher.calls)


def test_mdn_a_missing_page_is_not_reported_as_an_empty_extraction(tmp_path):
    checks = _mdn_run(tmp_path, STALE, QUOTE, _MdnFetcher())
    reason = checks["Fragments: content extraction"].failures[0].reason
    assert "empty extraction" not in reason
    assert "no such document" in reason
