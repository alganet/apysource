# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the IETF repository module.

Both fixtures are real documents, downloaded whole, because the thing under test
is a *rendition's* shape and a hand-written approximation of one would be a
description of what this module already believes.

``rfc8288.html`` is rfc-editor's legacy htmlization: the paginated text inside
``<pre>``, headings drawn as ``<span class="h3">``, twenty-four page footers.
``draft-thomson-hybi-http-timeout-03.html`` is datatracker's rendering of an old
Internet-Draft — the same idea with real ``<h2>`` elements nested inside the
``<pre>``, which is the shape lint-http's one draft citation actually resolves
against.

The modern (xml2rfc v3) shape is built inline instead. It is a real HTML
document already, so the interesting claim about it is that nothing happens to
it, and a small document proves that better than a 440 KB one.
"""

from pathlib import Path

import pytest

from apysource.formats import HtmlFormat, extract_content, normalize_ws
from apysource.repos._base import RepoNotFound
from apysource.repos.rfc import RfcRepo, is_preformatted, render

from tests.conftest import MockFetcher

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY = (FIXTURES / "rfc8288.html").read_text(encoding="utf-8")
DRAFT = (FIXTURES / "draft-thomson-hybi-http-timeout-03.html").read_text(
    encoding="utf-8")

URL_PATTERN = (
    r"(?:rfc-editor\.org/rfc|datatracker\.ietf\.org/doc/html|ietf\.org/archive/id)"
    r"/((?:rfc|bcp|std)\d+|draft-[a-zA-Z0-9][a-zA-Z0-9.\-]*?)"
    r"(?:\.[a-z]+)?(?:$|[/?#])"
)
BASE_URL = "https://www.rfc-editor.org/rfc"
DRAFT_BASE_URL = "https://datatracker.ietf.org/doc/html"

#: An xml2rfc v3 rendition in miniature: real headings, and `<pre>` elements of
#: its own holding artwork a citation may well be quoting.
MODERN = (
    "<html><head><title>RFC 9999: Example</title></head><body>"
    '<section id="section-1"><h2 id="name-intro">1. Introduction</h2>'
    "<p>This document does a thing.</p>"
    "<pre>example = 1*DIGIT</pre></section>"
    "</body></html>"
)


def _rfc(tmp_path, fetcher=None, **kw):
    kw.setdefault("crawl_delay", 0.0)
    return RfcRepo(cache_dir=tmp_path, http_client=fetcher,
                   url_pattern=URL_PATTERN, base_url=BASE_URL,
                   draft_base_url=DRAFT_BASE_URL, **kw)


def _section(document, selector):
    return normalize_ws(extract_content(document, selector, format_name="section"))


# ── The two htmlizations ──────────────────────────────────────────────────

def test_a_legacy_section_carries_its_prose_and_not_just_its_heading():
    """Promoting `<span class="h3">` where it stands is not enough.

    `HtmlFormat.sections` walks *elements*, and a legacy rendition's prose is
    bare text inside one enormous `<pre>`. Retag the heading in place and every
    section comes out addressable and **empty** — a tree that resolves `§ 2.1`
    and hands back nothing, which reads as a citation quoting a sentence that is
    not there. The prose has to become elements too.
    """
    text = _section(render(LEGACY), "§ 2.1")
    assert text.startswith("In the simplest case, a link relation type identifies"), \
        f"§ 2.1 must carry its own prose, got {text[:80]!r}"


def test_a_datatracker_htmlization_does_not_answer_one_section_with_another():
    """The wrong text, silently — the one failure this tool exists to prevent.

    Asked for `§ 2` of this draft, the raw htmlization answers with a running
    header and the tail of § 1: `Internet-Draft HTTP Keep-Alive July 2012 which
    is unlikely to be visible to the HTTP implementation, ...`. Not an empty
    extraction that someone would investigate. A quote taken from § 1 would
    verify green against a citation claiming § 2.
    """
    before = _section(DRAFT, "§ 2")
    assert before.startswith("Internet-Draft HTTP Keep-Alive"), \
        "the defect this fixture was chosen for is not reproducing"

    after = _section(render(DRAFT), "§ 2")
    assert after.startswith('The "Keep-Alive" header is a hop-by-hop header'), \
        f"§ 2 must be § 2, got {after[:80]!r}"
    assert "Internet-Draft" not in after


def test_a_modern_rendition_is_passed_through_untouched():
    """The gate, and why it is structural rather than a number or a host.

    An xml2rfc rendition is already what `render` is trying to produce, and it
    carries twenty-odd `<pre>` elements of its own — ABNF, frame diagrams,
    examples. Flattening those would destroy exactly the artwork a citation is
    most likely to be quoting. A version number would be wrong at the boundary
    and meaningless for drafts; a host name would be wrong the day either
    publisher re-renders its archive.
    """
    assert render(MODERN) == MODERN
    assert _section(MODERN, "§ 1") == "This document does a thing. example = 1*DIGIT"


def test_the_shape_is_what_decides_not_the_publisher():
    from bs4 import BeautifulSoup

    from apysource.repos.rfc import document_root

    for name, raw, legacy in (("rfc-editor legacy", LEGACY, True),
                              ("datatracker legacy", DRAFT, True),
                              ("xml2rfc modern", MODERN, False)):
        root = document_root(BeautifulSoup(raw, "html.parser"))
        assert is_preformatted(root) is legacy, name


# ── What the rendering leaves behind ──────────────────────────────────────

def test_the_page_furniture_is_not_in_the_text():
    """A `[Page 24]` in the middle of a sentence makes it unquotable.

    Twenty-three of this document's twenty-four footers are wrapped in
    `<span class="grey">` and go structurally. The last page's is bare text —
    nothing follows it to be wrapped — so a structural rule alone leaves one
    behind, in the Author's Address, which is where a contact citation would
    land.
    """
    before = normalize_ws(HtmlFormat().text(LEGACY))
    after = normalize_ws(HtmlFormat().text(render(LEGACY)))

    assert LEGACY.count("[Page") == 24
    assert "[Page" in before and "[Page" not in after
    # The running header, which the publisher does mark up.
    assert "Web Linking October 2017" in before
    assert "Web Linking October 2017" not in after


def test_a_hyphenated_token_split_across_the_wrap_is_quotable():
    """RFC text hyphenates only at hyphens the token already has.

    `Content-\\n   Language` otherwise reads as `Content- Language`, and the
    field name cannot be quoted whole — which is how a header name ends up
    being the one thing a citation about that header cannot say.
    """
    text = normalize_ws(HtmlFormat().text(render(LEGACY)))
    assert "Content-Language" in text
    assert "Content- Language" not in text
    assert "case-insensitive" in text and "well-defined" in text


def test_paragraph_numbering_addresses_distinct_paragraphs():
    """`§ 2.1, paragraph 3` addressed the text rendition.

    It has to address the htmlization as the *same* paragraph, or every existing
    citation that carries one silently shifts by however many blocks the new
    reader counts differently. The blank line is the boundary in both.
    """
    first = _section(render(LEGACY), "§ 2.1, paragraph 1")
    second = _section(render(LEGACY), "§ 2.1, paragraph 2")
    assert first.startswith("In the simplest case")
    assert second.startswith("Link relation types can also be used")
    assert first != second


def test_a_heading_too_long_for_one_line_is_still_one_heading():
    """Markup copied from RFC 7240 § 4.4, where this was found.

    A heading wider than the column is drawn as *two* heading elements, and the
    continuation carries no anchor. Emitted as two sections, § 4.4 owns the
    heading and no text at all — every word of it hangs under a phantom section
    called `Preferences`. That is worse than a miss: the section resolves, so
    strict mode never fires, and all three citations into it fail as though the
    quotes were wrong.
    """
    raw = (
        "<pre>"
        '<span class="h3"><a class="selflink" id="section-4.3">4.3</a>.  Wait'
        "</span>\n\n   Wait text.\n\n"
        '<span class="h3"><a class="selflink" id="section-4.4">4.4</a>.  The '
        '"handling=strict" and "handling=lenient" Processing</span>\n'
        '<span class="h3">      Preferences</span>\n\n'
        "   The preferences indicate how to handle error conditions.\n"
        "</pre>"
    )
    document = render(raw)

    assert _section(document, "§ 4.4") == \
        "The preferences indicate how to handle error conditions."

    from apysource.sections import section_labels
    tree = HtmlFormat().sections(document)
    assert section_labels(tree) == ["§ 4.3", "§ 4.4"]
    # And the wrapped half is part of the title, not lost with the phantom.
    assert tree.children[1].title.endswith("Processing Preferences")


def test_an_unanchored_heading_after_real_content_is_its_own_section():
    """The join is conditional, and this is what it is conditional on.

    Only whitespace may stand between the two halves of a wrapped heading. A
    heading with no anchor that follows actual prose is a heading the publisher
    simply did not anchor, and swallowing it into the one above would merge two
    sections and hand a citation the wrong scope.
    """
    raw = (
        "<pre>"
        '<span class="h2"><a class="selflink" id="section-1">1</a>.  Intro</span>\n'
        "\n   Intro text.\n\n"
        '<span class="h2">Acknowledgements</span>\n'
        "\n   Thanks to everyone.\n"
        "</pre>"
    )
    from apysource.sections import section_labels
    labels = section_labels(HtmlFormat().sections(render(raw)))
    assert labels == ["§ 1", "Acknowledgements"], labels


def test_an_appendix_is_addressable_on_a_real_document():
    """Both generations print `Appendix A. …` and anchor it `#appendix-A`.

    Neither spelling was understood, so `§ A` on this document extracted the
    empty string — a citation of the appendix reported as a quote that is not in
    a document that contains it. The sub-headings drop the word and always
    worked, which is what made the gap look like a document being inconsistent
    rather than a reader being.
    """
    document = render(LEGACY)
    assert _section(document, "§ A").startswith(
        "Header fields (Section 3) are only one serialisation of links")
    assert _section(document, "§ A.1").startswith("HTML motivated the original")


def test_a_rendition_that_draws_no_title_heading_reads_its_front_matter():
    """The fallback, for a rendition that marks up no title at all.

    An RFC prints its title centred between the author column and the
    `Abstract` that follows, so it is the run of lines just above that word.
    Without this the generic rule takes the first heading and labels the
    document `1. Introduction`, which is what `add` used to call every RFC it
    saw. The comment is here because a page break leaves one behind, and a
    comment is not text the document says.
    """
    raw = (
        "<pre>Network Working Group                          A. Author\n"
        "Request for Comments: 9999                     Example Org\n"
        "\n"
        "\n"
        "          A Study of Nothing In Particular\n"
        "\n"
        "Abstract\n"
        "\n"
        "   This document studies nothing in particular.\n"
        "<!--NewPage-->\n"
        '<span class="h2"><a class="selflink" id="section-1">1</a>.  Intro</span>\n'
        "\n"
        "   Introductory text.\n"
        "</pre>"
    )
    document = render(raw)
    assert HtmlFormat().title(document) == "A Study of Nothing In Particular"
    assert _section(document, "§ 1") == "Introductory text."


def test_the_document_is_labelled_by_its_title_not_by_section_one():
    """The legacy rendition has no `<title>`: the file begins at `<pre>`.

    Without one the generic rule falls back to the first heading, which labels
    every RFC in existence `1. Introduction`. Both publishers draw the title as
    a top-level heading with no section anchor on it, and that absence is the
    signal.
    """
    assert "<title>" not in LEGACY
    assert HtmlFormat().title(render(LEGACY)) == "Web Linking"


# ── One document, several addresses ───────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.rfc-editor.org/rfc/rfc9110.txt",
    "https://www.rfc-editor.org/rfc/rfc9110.html",
    "https://www.rfc-editor.org/rfc/rfc9110",
    "https://datatracker.ietf.org/doc/html/rfc9110#section-7.2",
])
def test_every_rendition_of_one_rfc_is_one_cached_document(tmp_path, url):
    """The extension is a rendition, not an identity.

    Keying on the URL would fetch and store the same document up to four times,
    and — worse — let two citations of one sentence disagree about whether it is
    there, depending on which address their author happened to copy.
    """
    assert _rfc(tmp_path).url_to_key(url) == "rfc9110"


def test_an_id_archive_draft_is_read_from_the_rendition_that_has_anchors(tmp_path):
    """The archive serves a 2012 draft as plain text, which has no anchors.

    Its `section:` citations are only addressable through datatracker's
    rendering of the same draft, so the archive URL an author cites is answered
    from there. The alternative is a citation that can name the document but not
    a place in it.
    """
    fetcher = MockFetcher(content=DRAFT)
    repo = _rfc(tmp_path, fetcher)
    url = "https://www.ietf.org/archive/id/draft-thomson-hybi-http-timeout-03.txt"

    key = repo.url_to_key(url)
    assert key == "draft-thomson-hybi-http-timeout-03"

    repo.crawl(key)
    assert fetcher.calls == [f"{DRAFT_BASE_URL}/{key}"]
    assert repo.resolve_location("", key) is not None


def test_a_metadata_page_is_not_the_document(tmp_path):
    """`/info/rfc9110` is a landing page about the RFC, not the RFC.

    Claiming it would cache the abstract and a download table under the key of
    the document itself, and every quote from the RFC would then fail against
    it.
    """
    assert _rfc(tmp_path).url_to_key(
        "https://www.rfc-editor.org/info/rfc9110") is None


@pytest.mark.parametrize("bogus", [
    "https://www.rfc-editor.org/rfc/draft-../../../etc/passwd",
    "https://datatracker.ietf.org/doc/html/draft-.",
])
def test_a_url_shaped_key_cannot_escape_the_cache_directory(tmp_path, bogus):
    """The key becomes a filename.

    A slug is not to be trusted to stay inside the cache directory merely
    because it arrived in a URL.
    """
    assert _rfc(tmp_path).url_to_key(bogus) is None


def test_a_loosened_url_pattern_still_cannot_name_a_path(tmp_path):
    """`url_pattern` is a constructor argument, so it is not the last word.

    The shipped pattern happens to admit nothing dangerous, which is exactly
    what makes a guard that trusts it worthless: the wiring is a config file,
    and the next person to widen that regex for a mirror they need is not
    thinking about `..`.
    """
    repo = RfcRepo(cache_dir=tmp_path, url_pattern=r"rfc-editor\.org/rfc/(.+)$",
                   base_url=BASE_URL)
    assert repo.url_to_key("https://www.rfc-editor.org/rfc/../../etc/passwd") is None
    assert repo.url_to_key("https://www.rfc-editor.org/rfc/rfc9110") == "rfc9110"


# ── Crawling ──────────────────────────────────────────────────────────────

def test_the_html_rendition_is_what_gets_fetched(tmp_path):
    fetcher = MockFetcher(content=LEGACY)
    repo = _rfc(tmp_path, fetcher)
    repo.crawl("rfc8288")

    assert fetcher.calls == ["https://www.rfc-editor.org/rfc/rfc8288.html"]
    assert (tmp_path / "rfc8288.html").exists()


def test_the_cache_holds_the_rendition_it_was_served(tmp_path):
    """Normalizing before caching would freeze today's `render` into every copy.

    A fix to it would then need `--refresh` across a corpus of documents that
    have not changed — and a stale normalization is invisible, because what is
    on disk still looks like a document.
    """
    repo = _rfc(tmp_path, MockFetcher(content=LEGACY))
    repo.crawl("rfc8288")

    cached = (tmp_path / "rfc8288.html").read_text(encoding="utf-8")
    assert cached == LEGACY
    assert '<span class="h2">' in cached and "<h2" not in cached

    # And what a format is handed is the normalized document, every time.
    assert '<h2 id="section-1">' in repo.extract_content(
        "", tmp_path / "rfc8288.html")


def test_a_warm_cache_is_not_refetched_unless_it_is_forced(tmp_path):
    """An RFC is immutable once published; re-reading one is a wasted request.

    `--refresh` still gets through, because that is the flag whose entire job is
    to distrust the cache.
    """
    fetcher = MockFetcher(content=LEGACY)
    repo = _rfc(tmp_path, fetcher)

    repo.crawl("rfc8288")
    repo.crawl("rfc8288")
    assert len(fetcher.calls) == 1

    repo.crawl("rfc8288", force=True)
    assert len(fetcher.calls) == 2


def test_an_rfc_that_does_not_exist_is_not_found_not_unavailable(tmp_path):
    repo = _rfc(tmp_path, MockFetcher(content=None, statuses={
        "https://www.rfc-editor.org/rfc/rfc99999.html": 404}))
    with pytest.raises(RepoNotFound):
        repo.crawl("rfc99999")


def test_an_empty_document_is_never_written_to_the_cache(tmp_path):
    """A cached empty document is a permanent false failure.

    It outlives whatever caused it, reports as "empty extraction (0 chars)"
    against the citation rather than the fetch, and stays that way until
    somebody passes --refresh.
    """
    repo = _rfc(tmp_path, MockFetcher(content="   \n"))
    with pytest.raises(RepoNotFound):
        repo.crawl("rfc8288")
    assert not list(tmp_path.glob("*.html"))
