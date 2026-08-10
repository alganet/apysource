# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.formats — content-format adapters."""

from apysource.formats import (
    DEFAULT_FORMATS,
    HtmlFormat,
    PlainTextFormat,
    _find_format,
    detect_format,
    extract_content,
    locate_snippet,
    normalize_ws,
)


# ── HtmlFormat.extract ──────────────────────────────────────────────────

def test_html_extract_basic():
    """CSS selector extracts matching elements' text."""
    html = '<div><p class="story">Hello world</p><p class="story">Second</p></div>'
    result = HtmlFormat().extract(html, "p.story")
    assert "Hello world" in result
    assert "Second" in result


def test_html_extract_no_match():
    """Selector with no matches returns empty string."""
    html = "<div><p>content</p></div>"
    result = HtmlFormat().extract(html, "span.missing")
    assert result == ""


def test_html_extract_nested():
    """Selector extracts text from nested elements."""
    html = '<div id="main"><ul><li>one</li><li>two</li></ul></div>'
    result = HtmlFormat().extract(html, "#main li")
    assert "one" in result
    assert "two" in result


# ── PlainTextFormat.extract ─────────────────────────────────────────────

def test_text_extract_basic():
    """Line range extracts the correct lines (1-based, inclusive)."""
    text = "\n".join(f"line{i}" for i in range(1, 11))
    result = PlainTextFormat().extract(text, "3-5")
    assert result == "line3\nline4\nline5"


def test_text_extract_single_line():
    """Single line range works."""
    text = "a\nb\nc\nd"
    result = PlainTextFormat().extract(text, "2-2")
    assert result == "b"


def test_text_extract_bad_format():
    """Bad format returns empty string."""
    fmt = PlainTextFormat()
    assert fmt.extract("some text", "abc") == ""
    assert fmt.extract("some text", "") == ""


def test_text_extract_out_of_range():
    """Out-of-range clips gracefully."""
    text = "a\nb\nc"
    result = PlainTextFormat().extract(text, "2-100")
    assert result == "b\nc"


# ── extract_content (dispatch) ──────────────────────────────────────────

def test_extract_content_html_with_selector():
    """Dispatches to HTML extraction for HTML format."""
    html = '<div><p class="target">Found it</p></div>'
    result = extract_content(html, "p.target", format_name="html")
    assert "Found it" in result


def test_extract_content_with_lines():
    """Dispatches to line extraction for plain-text format."""
    text = "a\nb\nc\nd\ne"
    result = extract_content(text, "2-4", format_name="plain-text")
    assert result == "b\nc\nd"


def test_extract_content_no_locator():
    """Returns full body when no locator provided."""
    body = "full body content"
    result = extract_content(body, None)
    assert result == body


# ── detect_format ───────────────────────────────────────────────────────

def test_detect_html_doctype():
    assert detect_format("<!DOCTYPE html><html>").name == "html"


def test_detect_html_tag():
    assert detect_format("<html><head></head>").name == "html"


def test_detect_html_body():
    assert detect_format("  \n<body>content</body>").name == "html"


#: The shape of an rfc-editor htmlized rendition: no doctype, no head, no
#: body — the file opens at a `<pre>` and references are inline anchors.
_HTMLIZED_RFC = """<pre>Internet Engineering Task Force (IETF)          M. Nottingham
Request for Comments: 8288                                  October 2017

<span class="h1">Web Linking</span>

   o  Language-Tag from [<a href="./rfc5646" title="Tags">RFC5646</a>].
</pre>"""


def test_detect_htmlized_rfc_as_html():
    """A body that opens at an HTML tag is HTML, declared or not.

    Read as RFC text, an htmlized rendition keeps its markup in the text, so
    every `[<a …>RFC5646</a>]` reference splits the sentence it sits in and a
    quote spanning one fails with a closest match ending at the bracket.
    """
    assert detect_format(_HTMLIZED_RFC).name == "html"


def test_htmlized_rfc_quote_spans_an_inline_reference():
    fmt = detect_format(_HTMLIZED_RFC)
    result = fmt.locate(_HTMLIZED_RFC, "Language-Tag from [RFC5646].")
    assert result is not None
    assert result.format_name == "html"


def test_detect_markdown_autolink_is_not_html():
    md = "<https://example.com> is the place.\n\n# Heading\n"
    assert detect_format(md).name == "markdown"


def test_detect_leading_comment_decides_nothing():
    """Markdown and wikitext open with `<!-- … -->` too — sniff what follows."""
    md = "<!-- omit in toc -->\n# Heading\n\nProse.\n"
    assert detect_format(md).name == "markdown"
    wiki = "<!-- Please do not add fluff -->\n{{Infobox}}\n== History ==\nText.\n"
    assert detect_format(wiki).name == "wikitext"
    html = "<!-- generated -->\n<div id=\"main\"><p>Prose.</p></div>"
    assert detect_format(html).name == "html"


def test_detect_plain_text():
    assert detect_format("Just some plain text\nwith lines").name == "plain-text"


def test_detect_plain_text_with_angle_brackets():
    assert detect_format("x > y and a < b").name == "plain-text"


# ── A media type that names one reader ──────────────────────────────────

def test_text_plain_names_exactly_one_format():
    """`text/plain` was claimed by two readers, so it selected neither.

    An ambiguous media type resolves to nothing and the caller falls through to
    sniffing the body — which meant a source that said exactly what it was got
    the same treatment as one that said nothing, and the reader it ended up with
    depended on a heuristic rather than on what its author had written down.
    """
    assert extract_content("line one\nline two\nline three", "2-2",
                           format_name="text/plain") == "line two"
    assert _find_format("text/plain", DEFAULT_FORMATS) is not None
    assert _find_format("text/plain", DEFAULT_FORMATS).name == "plain-text"


def test_two_formats_claiming_one_mime_still_fall_through_to_detection():
    """The guard outlives the collision it was written for.

    `default_formats` is a seam a caller can pass their own list through, and
    picking whichever of two claimants happens to come first is not an answer.
    Built by hand, because no shipped list collides any more.
    """
    class Rival:
        name = "rival"
        mime_type = "text/plain"

        def detect(self, body):
            return True

    assert _find_format("text/plain", [*DEFAULT_FORMATS, Rival()]) is None
    assert _find_format("rival", [*DEFAULT_FORMATS, Rival()]).name == "rival"


# ── HtmlFormat.locate ──────────────────────────────────────────────────

def test_html_locate_basic():
    html = "<html><body><p>Hello world</p></body></html>"
    result = HtmlFormat().locate(html, "Hello world")
    assert result is not None
    assert result.format_name == "html"
    assert result.locator is not None
    assert "p" in result.locator


def test_html_locate_through_tags():
    """Snippet matches even when text spans inline tags."""
    html = "<html><body><p>User is <em>strong</em></p></body></html>"
    result = HtmlFormat().locate(html, "User is strong")
    assert result is not None
    assert "User is strong" in result.matched_text


def test_html_locate_no_match():
    html = "<html><body><p>Something else</p></body></html>"
    result = HtmlFormat().locate(html, "not found anywhere")
    assert result is None


def test_html_locate_with_id():
    """Selector uses #id when ancestor has one."""
    html = '<html><body><div id="main"><p>Target text</p></div></body></html>'
    result = HtmlFormat().locate(html, "Target text")
    assert result is not None
    assert "#main" in result.locator


def test_html_locate_nth_of_type():
    """Selector uses nth-of-type to distinguish siblings."""
    html = "<html><body><p>First</p><p>Second</p><p>Third</p></body></html>"
    result = HtmlFormat().locate(html, "Second")
    assert result is not None
    assert "nth-of-type(2)" in result.locator


def test_html_locate_whitespace_normalization():
    """Matches despite extra whitespace in source."""
    html = "<html><body><p>  lots   of   spaces  </p></body></html>"
    result = HtmlFormat().locate(html, "lots of spaces")
    assert result is not None


# ── PlainTextFormat.locate ──────────────────────────────────────────────

def test_text_locate_basic():
    text = "line one\nline two\nline three\nline four\n"
    result = PlainTextFormat().locate(text, "line two")
    assert result is not None
    assert result.format_name == "plain-text"
    assert result.locator == "2-2"


def test_text_locate_multiline():
    text = "alpha\nbeta\ngamma\ndelta\n"
    result = PlainTextFormat().locate(text, "beta gamma")
    assert result is not None
    assert result.locator == "2-3"


def test_text_locate_no_match():
    text = "some content\nmore content\n"
    result = PlainTextFormat().locate(text, "not here")
    assert result is None


def test_text_locate_whitespace_normalization():
    text = "line with   extra   spaces\n"
    result = PlainTextFormat().locate(text, "line with extra spaces")
    assert result is not None


# ── locate_snippet (dispatch) ───────────────────────────────────────────

def test_dispatch_html():
    html = "<!DOCTYPE html><html><body><p>Found it</p></body></html>"
    result = locate_snippet(html, "Found it")
    assert result is not None
    assert result.format_name == "html"
    assert result.locator is not None


def test_dispatch_plain():
    text = "line 1\nline 2\nline 3\n"
    result = locate_snippet(text, "line 2")
    assert result is not None
    assert result.format_name == "plain-text"
    assert result.locator is not None


def test_dispatch_explicit_type():
    body = "<p>Not detected as HTML by heuristic</p>"
    result = locate_snippet(body, "Not detected", content_type="html")
    assert result is not None
    assert result.format_name == "html"


# ── The text a citation is checked against (E1) ──────────────────────────

_PAGE = '''<!doctype html>
<html><head>
<meta name="description" content="The Origin header tells you the origin of the request.">
<script>var t = "A client MUST send a Host header field.";</script>
<style>.x { content: "never rendered"; }</style>
</head><body>
<main>
<p>The <code>Origin</code> request header indicates the <a href="/x">origin</a>
   that caused the request.</p>
<p>Responses MUST include a Vary header.</p>
</main>
</body></html>'''


def _html_verifies(snippet, locator=None):
    text = extract_content(_PAGE, locator, format_name="text/html")
    return normalize_ws(snippet) in normalize_ws(text)


def test_a_page_is_checked_as_a_reader_sees_it_not_as_markup():
    """A fragment with no selector was matched against raw HTML.

    So a sentence lifted from a `<meta name="description">` — or from inside a
    `<script>` — verified against a page whose prose said something else, while
    the prose a reader actually saw did not match at all. Exactly inverted: it
    passed text nobody was shown and failed text they were.
    """
    assert not _html_verifies("The Origin header tells you the origin of the request."), \
        "a <meta> description is not what the page says"
    assert not _html_verifies("A client MUST send a Host header field."), \
        "a <script> body is not what the page says"
    assert not _html_verifies("never rendered"), "a stylesheet is not what the page says"

    assert _html_verifies(
        "The Origin request header indicates the origin that caused the request."), \
        "the prose a reader can see must verify"


def test_inline_markup_does_not_glue_words_together():
    """`get_text(strip=True)` joined stripped strings with nothing, so
    `<p>The <code>Origin</code> request</p>` extracted as `TheOriginrequest`.
    """
    text = normalize_ws(extract_content(_PAGE, "main p:nth-of-type(1)",
                                        format_name="text/html"))
    assert "The Origin request header" in text
    assert "TheOrigin" not in text


def test_no_whitespace_is_invented_inside_a_word():
    """The other half of the same coin, and the more dangerous half.

    Joining every string with a separator would render `<b>Sub</b>string` as
    "Sub string" — inventing a space a reader never saw, so a misquotation
    would verify. Whitespace is only ever added where a browser also breaks the
    line: at a block boundary, never between inline elements.
    """
    page = "<html><body><p><b>Sub</b>string is one word</p></body></html>"
    text = normalize_ws(extract_content(page, None, format_name="text/html"))
    assert "Substring is one word" in text
    assert "Sub string" not in text


def test_a_quote_spanning_two_paragraphs_verifies():
    """Blocks are separated, so text either side of a `</p>` is not run together."""
    assert _html_verifies("caused the request. Responses MUST include a Vary header.")


def test_add_writes_a_citation_that_check_accepts():
    """The bug this whole class produced: the two commands contradicted each other.

    `locate` (which `add` uses) read the page one way and `extract` (which
    `check` uses) read it another, so `add` emitted a selector that `check`
    rejected on the very next run. They now share one rendering — and `locate`
    additionally *proves* its selector leads back to the snippet before
    returning it, so no future divergence can reopen this.
    """
    snippet = "The Origin request header indicates the origin that caused the request."
    result = locate_snippet(_PAGE, snippet)

    assert result is not None, "locate must find prose that is on the page"
    assert _html_verifies(snippet, result.locator), \
        f"check rejected the selector add wrote: {result.locator}"


def test_locate_never_returns_a_selector_that_does_not_lead_back():
    """The guard itself. A locator that does not yield the snippet is not a locator."""
    from apysource.formats import HtmlFormat, _selector_yields

    soup = HtmlFormat()._soup(_PAGE)
    assert _selector_yields(soup, "main p:nth-of-type(2)",
                            normalize_ws("Responses MUST include a Vary header."))
    assert not _selector_yields(soup, "main p:nth-of-type(1)",
                                normalize_ws("Responses MUST include a Vary header."))
    assert not _selector_yields(soup, "p[[[bad", normalize_ws("anything"))


# ── A title is not the first heading (C2) ───────────────────────────────

def test_a_markdown_title_comes_from_front_matter_when_there_is_some():
    """MDN's Origin page opens with `## Syntax`, so the heading rule named it that."""
    from apysource.formats import MarkdownFormat
    doc = "---\ntitle: Origin\nslug: Web/HTTP/Headers/Origin\n---\n\n## Syntax\n\nOrigin: null\n"
    assert MarkdownFormat().title(doc) == "Origin"


def test_a_flat_text_file_does_not_invent_a_title():
    """It has none. `add` falls back to the URL, which is at least true."""
    assert PlainTextFormat().title("just some words\nand more words\n") == ""


def test_an_html_page_is_titled_by_its_title_tag():
    page = "<html><head><title>Fetch Standard</title></head><body><h1>1. Scope</h1></body></html>"
    assert HtmlFormat().title(page) == "Fetch Standard"


from apysource.documents import _SoupCache  # noqa: E402


class TestASharedParseIsStillEveryonesOwnAnswer:
    """A cached HTML tree is handed to several callers. That is only safe if
    nobody mutates it, and nothing about BeautifulSoup guarantees that — it is
    an invariant of *this* code, so it is asserted here rather than assumed.
    """

    HTML = (
        "<html><head><title>T</title></head><body>"
        "<h2 id='one'>One</h2><p>first paragraph text</p>"
        "<h2 id='two'>Two</h2><p>second paragraph text</p>"
        "<div class='side'>aside text</div>"
        "</body></html>"
    )

    def test_extracting_twice_gives_the_same_text(self):
        shared = HtmlFormat(soup_cache=_SoupCache(4))
        first = shared.extract(self.HTML, "div.side")
        second = shared.extract(self.HTML, "div.side")

        assert first == second

    def test_two_selectors_do_not_disturb_each_other(self):
        """Whichever order they are asked in, each gets its own answer."""
        cache = _SoupCache(4)
        forwards = HtmlFormat(soup_cache=cache)
        a1 = forwards.extract(self.HTML, "div.side")
        b1 = forwards.extract(self.HTML, "p")

        backwards = HtmlFormat(soup_cache=_SoupCache(4))
        b2 = backwards.extract(self.HTML, "p")
        a2 = backwards.extract(self.HTML, "div.side")

        assert (a1, b1) == (a2, b2)

    def test_a_shared_parse_matches_an_unshared_one(self):
        """The cache must not be able to change an answer, only its cost."""
        shared = HtmlFormat(soup_cache=_SoupCache(4))
        fresh = HtmlFormat()

        for locator in ("div.side", "p", "h2"):
            assert shared.extract(self.HTML, locator) == fresh.extract(self.HTML, locator)

        assert shared.text(self.HTML) == fresh.text(self.HTML)
        assert shared.title(self.HTML) == fresh.title(self.HTML)

    def test_the_document_is_parsed_once(self):
        cache = _SoupCache(4)
        fmt = HtmlFormat(soup_cache=cache)

        fmt.extract(self.HTML, "div.side")
        fmt.extract(self.HTML, "p")
        fmt.text(self.HTML)
        fmt.title(self.HTML)

        assert len(cache) == 1, "one document, one tree"

    def test_the_cache_does_not_grow_without_bound(self):
        """A tree is several times the size of its source, so the window is
        small and fixed. Citations of one page arrive together, which is what
        makes a small window enough."""
        from apysource.documents import SOUP_CACHE_DOCUMENTS, DocumentCache

        cache = DocumentCache()
        html = cache.formats[0]
        for i in range(SOUP_CACHE_DOCUMENTS * 3):
            html.text(f"<html><body><p>document {i}</p></body></html>")

        assert len(cache._soups) <= SOUP_CACHE_DOCUMENTS

    def test_the_module_default_shares_nothing(self):
        """`DEFAULT_FORMATS` is process-wide, so it must retain no documents —
        otherwise one run's parse could answer the next run's question."""
        from apysource.formats import DEFAULT_FORMATS

        assert DEFAULT_FORMATS[0]._soup_cache is None
