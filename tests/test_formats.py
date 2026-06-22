# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.formats — content-format adapters."""

from apysource.formats import (
    HtmlFormat,
    PlainTextFormat,
    detect_format,
    extract_content,
    locate_snippet,
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


def test_detect_plain_text():
    assert detect_format("Just some plain text\nwith lines").name == "plain-text"


def test_detect_plain_text_with_angle_brackets():
    assert detect_format("x > y and a < b").name == "plain-text"


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
