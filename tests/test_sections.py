# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.sections — human-readable section selectors."""

import pytest

from apysource.formats import (
    HtmlFormat,
    MarkdownFormat,
    PlainTextFormat,
    RfcTextFormat,
    WikitextFormat,
    detect_format,
    extract_content,
    normalize_ws,
)
from apysource.sections import (
    SectionNode,
    SectionNotFound,
    SectionPart,
    extract_by_selector,
    extract_section,
    section_labels,
    generate_selector,
    int_to_roman,
    locate_section,
    match_section,
    parse_selector,
    roman_to_int,
    selector_for_anchor,
)


# ── Roman numeral utilities ───────────────────────────────────────────

def test_roman_to_int_basic():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9
    assert roman_to_int("XLII") == 42


def test_roman_to_int_case_insensitive():
    assert roman_to_int("iv") == 4
    assert roman_to_int("Xlii") == 42


def test_roman_to_int_invalid():
    assert roman_to_int("") is None
    assert roman_to_int("ABC") is None


def test_int_to_roman():
    assert int_to_roman(4) == "IV"
    assert int_to_roman(9) == "IX"
    assert int_to_roman(42) == "XLII"


def test_roman_roundtrip():
    for n in [1, 4, 9, 14, 42, 99, 100, 399, 1000]:
        assert roman_to_int(int_to_roman(n)) == n


# ── Selector parsing ─────────────────────────────────────────────────

def test_parse_simple_heading():
    parts = parse_selector("Chapter 4")
    assert len(parts) == 1
    assert parts[0].kind == "heading"
    assert parts[0].value == "Chapter 4"
    assert parts[0].ordinal == 4


def test_parse_paragraph():
    parts = parse_selector("paragraph 3")
    assert len(parts) == 1
    assert parts[0].kind == "paragraph"
    assert parts[0].ordinal == 3


def test_parse_numbered_section():
    parts = parse_selector("§ 4.1")
    assert len(parts) == 1
    assert parts[0].kind == "numbered"
    assert parts[0].value == "4.1"


def test_parse_combination():
    parts = parse_selector("Preamble, paragraph 1")
    assert len(parts) == 2
    assert parts[0].kind == "heading"
    assert parts[0].value == "Preamble"
    assert parts[1].kind == "paragraph"
    assert parts[1].ordinal == 1


def test_parse_nested_sections():
    parts = parse_selector("Title 1, Subtitle 99, paragraph 3")
    assert len(parts) == 3
    assert parts[0].ordinal == 1
    assert parts[1].ordinal == 99
    assert parts[2].ordinal == 3


def test_parse_quoted_title():
    parts = parse_selector("'Lost, forever...', Section 2, paragraph 3")
    assert len(parts) == 3
    assert parts[0].kind == "heading"
    assert parts[0].value == "Lost, forever..."
    assert parts[1].value == "Section 2"
    assert parts[2].ordinal == 3


def test_parse_roman_heading():
    parts = parse_selector("Chapter IV")
    assert len(parts) == 1
    assert parts[0].ordinal == 4


# ── Section matching ──────────────────────────────────────────────────

def test_match_heading_exact():
    node = SectionNode(title="Preamble", level=1)
    part = SectionPart(kind="heading", value="Preamble")
    assert match_section(node, part)


def test_match_heading_case_insensitive():
    node = SectionNode(title="PREAMBLE", level=1)
    part = SectionPart(kind="heading", value="Preamble")
    assert match_section(node, part)


def test_match_heading_roman_to_int():
    """Chapter 4 matches Chapter IV."""
    node = SectionNode(title="Chapter IV", level=1)
    part = SectionPart(kind="heading", value="Chapter 4", ordinal=4)
    assert match_section(node, part)


def test_match_heading_int_to_roman():
    """Chapter IV matches Chapter 4."""
    node = SectionNode(title="Chapter 4", level=1)
    part = SectionPart(kind="heading", value="Chapter IV", ordinal=4)
    assert match_section(node, part)


def test_match_numbered_section():
    node = SectionNode(title="4.1 Requirements", level=2)
    part = SectionPart(kind="numbered", value="4.1")
    assert match_section(node, part)


def test_match_numbered_no_match():
    node = SectionNode(title="Chapter IV", level=1)
    part = SectionPart(kind="numbered", value="4.1")
    assert not match_section(node, part)


def test_match_different_prefix_no_match():
    """Section 4 should not match Chapter 4."""
    node = SectionNode(title="Section 4", level=1)
    part = SectionPart(kind="heading", value="Chapter 4", ordinal=4)
    assert not match_section(node, part)


# ── HTML section tree ─────────────────────────────────────────────────

def test_html_sections_basic():
    html = """<html><body>
    <h1>Introduction</h1>
    <p>First paragraph.</p>
    <p>Second paragraph.</p>
    <h1>Chapter I</h1>
    <p>Chapter content.</p>
    </body></html>"""
    root = HtmlFormat().sections(html)
    assert len(root.children) == 2
    assert root.children[0].title == "Introduction"
    assert len(root.children[0].paragraphs) == 2
    assert root.children[1].title == "Chapter I"


def test_html_sections_nested():
    html = """<html><body>
    <h1>Part One</h1>
    <h2>Chapter 1</h2>
    <p>Content of chapter 1.</p>
    <h2>Chapter 2</h2>
    <p>Content of chapter 2.</p>
    </body></html>"""
    root = HtmlFormat().sections(html)
    assert len(root.children) == 1  # Part One
    part = root.children[0]
    assert len(part.children) == 2  # Chapter 1, Chapter 2
    assert part.children[0].title == "Chapter 1"
    assert part.children[1].title == "Chapter 2"


def test_html_sections_own_the_pre_beside_their_prose():
    """A section's <pre> is its content, exactly as its <p> is.

    Only <p> used to be collected, so on a W3C-style page the ABNF in a
    section's <pre> was unreachable under a section selector while the prose
    one element up resolved fine — locate then fell back to a CSS selector for
    the grammar and named the same section for the sentence beside it.
    """
    html = """<html><body><main>
    <h2>2. The Server-Timing Header Field</h2>
    <p>The Server-Timing header field is used to communicate metrics.</p>
    <pre>Server-Timing = #server-timing-metric</pre>
    </main></body></html>"""
    fmt = HtmlFormat()
    section = fmt.sections(html).children[0]
    assert "Server-Timing = #server-timing-metric" in section.paragraphs

    located = locate_section(html, "Server-Timing = #server-timing-metric", fmt)
    assert located is not None
    assert located.format_name == "section"
    assert located.locator == "§ 2"


def test_html_sections_collect_lists_definitions_and_cells():
    html = """<html><body>
    <h1>Requirements</h1>
    <ul><li>The user agent MUST reconnect.</li></ul>
    <dl><dt>metric</dt><dd>A named measurement.</dd></dl>
    <table><tr><th>Name</th><td>Value</td></tr></table>
    <blockquote>Quoted requirement.</blockquote>
    </body></html>"""
    section = HtmlFormat().sections(html).children[0]
    assert "The user agent MUST reconnect." in section.paragraphs
    assert "metric" in section.paragraphs
    assert "A named measurement." in section.paragraphs
    assert "Name" in section.paragraphs
    assert "Value" in section.paragraphs
    assert "Quoted requirement." in section.paragraphs


def test_html_sections_content_wrapping_a_heading_is_a_container():
    """A <li> holding an <h3> is structure, not a paragraph of the outer section.

    Collecting it whole would copy the nested section's title into a paragraph
    of the enclosing section and strand the nested section empty. Its children
    are judged one by one instead, so text after the heading belongs to the
    section that heading opens.
    """
    html = """<html><body>
    <h1>Outer</h1>
    <ul><li><h3>Inner Title</h3><p>Inner body requirement.</p></li></ul>
    </body></html>"""
    outer = HtmlFormat().sections(html).children[0]
    assert outer.paragraphs == []
    inner = outer.children[0]
    assert inner.title == "Inner Title"
    assert inner.paragraphs == ["Inner body requirement."]


def test_html_sections_do_not_collect_nested_content_twice():
    """A <p> inside a <li> arrives once, as part of the <li>'s own text."""
    html = """<html><body>
    <h1>Steps</h1>
    <ul><li><p>Run the algorithm.</p><pre>step = 1</pre></li></ul>
    </body></html>"""
    section = HtmlFormat().sections(html).children[0]
    assert len(section.paragraphs) == 1
    assert "Run the algorithm." in section.paragraphs[0]
    assert "step = 1" in section.paragraphs[0]


# ── Markdown section tree ─────────────────────────────────────────────

def test_markdown_sections_basic():
    md = """# Introduction

First paragraph.

Second paragraph.

# Chapter 1

Chapter content.
"""
    root = MarkdownFormat().sections(md)
    assert len(root.children) == 2
    assert root.children[0].title == "Introduction"
    assert len(root.children[0].paragraphs) == 2
    assert root.children[1].title == "Chapter 1"


def test_markdown_sections_nested():
    md = """# Part One

## Section A

Content A.

## Section B

Content B.
"""
    root = MarkdownFormat().sections(md)
    assert len(root.children) == 1
    part = root.children[0]
    assert len(part.children) == 2
    assert part.children[0].title == "Section A"


# ── Wikitext section tree ─────────────────────────────────────────────

def test_wikitext_sections_basic():
    wt = """== Introduction ==

First paragraph.

Second paragraph.

== Chapter 1 ==

Chapter content.
"""
    root = WikitextFormat().sections(wt)
    assert len(root.children) == 2
    assert root.children[0].title == "Introduction"
    assert len(root.children[0].paragraphs) == 2


def test_wikitext_sections_nested():
    wt = """== Part One ==

=== Section A ===

Content A.

=== Section B ===

Content B.
"""
    root = WikitextFormat().sections(wt)
    assert len(root.children) == 1
    part = root.children[0]
    assert len(part.children) == 2


# ── Extract by selector ──────────────────────────────────────────────

def test_extract_heading():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Preamble", level=1,
                    paragraphs=["We the peoples.", "United in purpose."]),
        SectionNode(title="Chapter I", level=1,
                    paragraphs=["Article text."]),
    ])
    result = extract_by_selector(root, "Preamble")
    assert "We the peoples." in result
    assert "United in purpose." in result


def test_extract_heading_paragraph():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Preamble", level=1,
                    paragraphs=["First.", "Second.", "Third."]),
    ])
    result = extract_by_selector(root, "Preamble, paragraph 2")
    assert result == "Second."


def test_extract_roman_match():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Chapter IV", level=1,
                    paragraphs=["Content of chapter 4."]),
    ])
    result = extract_by_selector(root, "Chapter 4")
    assert "Content of chapter 4." in result


def test_extract_nested():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Part 1", level=1, children=[
            SectionNode(title="Section A", level=2,
                        paragraphs=["Deep content."]),
        ]),
    ])
    result = extract_by_selector(root, "Part 1, Section A, paragraph 1")
    assert result == "Deep content."


def test_extract_no_match():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Intro", level=1, paragraphs=["Text."]),
    ])
    result = extract_by_selector(root, "Nonexistent")
    assert result == ""


# ── Generate selector ─────────────────────────────────────────────────

def test_generate_basic():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Preamble", level=1,
                    paragraphs=["We the peoples.", "United in purpose."]),
    ])
    sel = generate_selector(root, "We the peoples.")
    assert sel is not None
    assert "Preamble" in sel
    assert "paragraph 1" in sel


def test_generate_nested():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Part One", level=1, children=[
            SectionNode(title="Chapter 1", level=2,
                        paragraphs=["Opening.", "Middle.", "End."]),
        ]),
    ])
    sel = generate_selector(root, "Middle.")
    assert sel is not None
    assert "Part One" in sel
    assert "Chapter 1" in sel
    assert "paragraph 2" in sel


def test_generate_not_found():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Intro", level=1, paragraphs=["Text."]),
    ])
    assert generate_selector(root, "not here") is None


# ── Roundtrip: generate + extract ─────────────────────────────────────

def test_roundtrip_html():
    html = """<html><body>
    <h1>Preamble</h1>
    <p>We the peoples of the world.</p>
    <p>Determined to save generations.</p>
    <h1>Chapter I</h1>
    <p>Article 1 content.</p>
    </body></html>"""
    fmt = HtmlFormat()
    result = locate_section(html, "Determined to save", fmt)
    assert result is not None
    assert result.format_name == "section"

    extracted = extract_content(html, result.locator, format_name="section")
    assert "Determined to save" in extracted


def test_roundtrip_markdown():
    md = """# Preamble

We the peoples of the world.

Determined to save generations.

# Chapter 1

Article 1 content.
"""
    fmt = MarkdownFormat()
    result = locate_section(md, "Determined to save", fmt)
    assert result is not None

    extracted = extract_content(md, result.locator, format_name="section")
    assert "Determined to save" in extracted


def test_roundtrip_wikitext():
    wt = """== Preamble ==

We the peoples of the world.

Determined to save generations.

== Chapter 1 ==

Article 1 content.
"""
    fmt = WikitextFormat()
    result = locate_section(wt, "Determined to save", fmt)
    assert result is not None

    extracted = extract_content(wt, result.locator, format_name="section")
    assert "Determined to save" in extracted


# ── Locate returns None for structureless documents ───────────────────

def test_locate_no_structure():
    html = "<html><body><p>Just a paragraph, no headings.</p></body></html>"
    result = locate_section(html, "Just a paragraph", HtmlFormat())
    assert result is None


# ── extract_content dispatch for section format ───────────────────────

def test_extract_content_section_dispatch():
    html = """<html><body>
    <h1>Title</h1>
    <p>Paragraph one.</p>
    <p>Paragraph two.</p>
    </body></html>"""
    result = extract_content(html, "Title, paragraph 2", format_name="section")
    assert result == "Paragraph two."


# ── Format detection order ────────────────────────────────────────────

def test_detect_markdown():
    md = "# Title\n\nSome content.\n"
    assert detect_format(md).name == "markdown"


def test_detect_wikitext():
    wt = "== Title ==\n\nSome content.\n"
    assert detect_format(wt).name == "wikitext"


def test_detect_html_over_markdown():
    """HTML detection takes priority over Markdown."""
    html = "<!DOCTYPE html>\n<html><body># Not markdown</body></html>"
    assert detect_format(html).name == "html"


def test_detect_plain_text_fallback():
    assert detect_format("Just text, no markers.").name == "plain-text"


# ── Markdown format operations ────────────────────────────────────────

def test_markdown_detect_no_headings():
    """Plain text with # in middle of line is not Markdown."""
    assert not MarkdownFormat().detect("Use item #3 carefully")


def test_markdown_locate():
    md = "# Intro\n\nHello world.\n\n# Body\n\nGoodbye.\n"
    result = MarkdownFormat().locate(md, "Hello world")
    assert result is not None
    assert result.format_name == "section"
    assert "Intro" in result.locator


def test_markdown_extract():
    md = "# Intro\n\nHello world.\n\n# Body\n\nGoodbye.\n"
    result = MarkdownFormat().extract(md, "Intro, paragraph 1")
    assert "Hello world" in result


# ── Wikitext format operations ────────────────────────────────────────

def test_wikitext_detect_wiki_links():
    """Wikitext detected by [[wiki links]]."""
    assert WikitextFormat().detect("See [[Main Page]] for details.")


def test_wikitext_locate():
    wt = "== Intro ==\n\nHello world.\n\n== Body ==\n\nGoodbye.\n"
    result = WikitextFormat().locate(wt, "Hello world")
    assert result is not None
    assert "Intro" in result.locator


def test_wikitext_extract():
    wt = "== Intro ==\n\nHello world.\n\n== Body ==\n\nGoodbye.\n"
    result = WikitextFormat().extract(wt, "Intro, paragraph 1")
    assert "Hello world" in result


# ── RFC text format ───────────────────────────────────────────────────

_RFC_SAMPLE = """\
Network Working Group                                         J. Doe
Request for Comments: 9999                                Company Inc.
Category: Standards Track                              January 2026


                       Sample RFC Document

Status of This Memo

   This document specifies a sample protocol for testing.

1.  Introduction

   This is the introduction paragraph.

   This is the second paragraph of the introduction.

2.  Overview

   High-level overview of the protocol.

2.1.  Terminology

   Key terms used in this document.

2.2.  Requirements

   Requirements for implementations.

3.  Security Considerations

   There are no security considerations.
"""


def test_rfc_detect():
    assert RfcTextFormat().detect(_RFC_SAMPLE)


def test_rfc_detect_not_plain_text():
    """Regular plain text is not detected as RFC."""
    assert not RfcTextFormat().detect("Just some plain text\nwith lines\n")


def test_rfc_detect_not_html():
    """HTML with RFC-like content is not detected as RFC."""
    assert not RfcTextFormat().detect(
        "<!DOCTYPE html><html><body>RFC 9999</body></html>")


def test_rfc_detect_order():
    """RFC is detected before plain text in the format chain."""
    assert detect_format(_RFC_SAMPLE).name == "rfc"


def test_rfc_sections_basic():
    root = RfcTextFormat().sections(_RFC_SAMPLE)
    # Top-level: Status of This Memo (unnumbered, not captured),
    # 1. Introduction, 2. Overview, 3. Security Considerations
    titles = [c.title for c in root.children]
    assert any("Introduction" in t for t in titles)
    assert any("Overview" in t for t in titles)
    assert any("Security" in t for t in titles)


def test_rfc_sections_nested():
    root = RfcTextFormat().sections(_RFC_SAMPLE)
    # Find section 2
    sec2 = None
    for child in root.children:
        if child.title.startswith("2."):
            sec2 = child
            break
    assert sec2 is not None
    # Should have subsections 2.1 and 2.2
    assert len(sec2.children) == 2
    assert "Terminology" in sec2.children[0].title
    assert "Requirements" in sec2.children[1].title


def test_rfc_locate():
    result = RfcTextFormat().locate(_RFC_SAMPLE, "second paragraph of the introduction")
    assert result is not None
    assert result.format_name == "section"
    assert "§ 1" in result.locator


def test_rfc_extract_by_section_number():
    result = RfcTextFormat().extract(_RFC_SAMPLE, "§ 2.1, paragraph 1")
    assert "Key terms" in result


def test_rfc_roundtrip():
    fmt = RfcTextFormat()
    result = locate_section(_RFC_SAMPLE, "High-level overview", fmt)
    assert result is not None
    extracted = extract_content(_RFC_SAMPLE, result.locator, format_name="section")
    assert "High-level overview" in extracted


def test_rfc_form_feed_handling():
    """Form feeds and page headers are stripped during section parsing."""
    rfc_with_ff = """\
Request for Comments: 8888

1.  Introduction

   First part of intro.
\f
Doe                      Standards Track                    [Page 1]

   Second part of intro.

2.  Next Section

   Content here.
"""
    root = RfcTextFormat().sections(rfc_with_ff)
    sec1 = root.children[0]
    assert "First part" in sec1.paragraphs[0]
    assert "Second part" in sec1.paragraphs[1]


def test_rfc_running_header_after_page_break_is_stripped():
    """The running header — the line after a form feed — is furniture, not prose.

    Real RFC layout: a footer, then the form feed on its own line, then the running
    header ("RFC N   Title   Date"), then the page's content. The footer rule cannot
    catch the header (it has no [Page N] marker), so it is removed keyed on the form
    feed it follows.
    """
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n"
        "   First part of the intro.\n"
        "Doe                       Standards Track                    [Page 1]\n"
        "\f\n"
        "RFC 8888              A Sample Protocol            January 2026\n"
        "\n"
        "   Second part of the intro.\n"
    )
    text = RfcTextFormat().sections(rfc).children[0].all_text()
    assert "First part" in text
    assert "Second part" in text
    assert "A Sample Protocol" not in text  # the running header is gone


def test_rfc_hyphenated_token_across_a_wrap_is_rejoined():
    """A token the 72-column wrap splits at a hyphen is quotable whole.

    RFC text hyphenates only at hyphens already in the token, and the continuation is
    indented to the paragraph, so `ISO-\\n   8859-1` must read as `ISO-8859-1`, not the
    `ISO- 8859-1` that plain whitespace-collapsing would leave.
    """
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n"
        "   The value is encoded with the ISO-\n"
        "   8859-1 character set as described below.\n"
    )
    norm = normalize_ws(RfcTextFormat().sections(rfc).children[0].all_text())
    assert "ISO-8859-1" in norm
    assert "ISO- 8859-1" not in norm


def test_rfc_double_hyphen_line_end_is_not_rejoined():
    """A line ending in '--' (an em-dash) is left alone — only a single hyphen joins."""
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n"
        "   The request target --\n"
        "   regardless of its form -- is normalised.\n"
    )
    norm = normalize_ws(RfcTextFormat().sections(rfc).children[0].all_text())
    assert "-- regardless" in norm
    assert "--regardless" not in norm


def test_rfc_appendix_is_addressable_by_letter():
    """`§ A` resolves to an appendix, and a plain heading is not mistaken for one.

    The appendix node is built as `A. Pseudocode`; matching a `§` selector compares the
    title's leading designator, which now admits an appendix letter. (`§ A.1` for an
    appendix *subsection* needs the bare-`A.1.` heading to be recognised — that is a
    separate change.)
    """
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n"
        "   Intro text.\n"
        "\n"
        "Appendix A.  Pseudocode\n"
        "\n"
        "   The decoding routine is given here.\n"
    )
    fmt = RfcTextFormat()
    assert "decoding routine" in fmt.extract(rfc, "§ A")
    # The appendix now carries a § label, so it can be offered as a candidate.
    labels = section_labels(fmt.sections(rfc))
    assert "§ A" in labels
    # A plain-word heading must never be read as a one-letter designator.
    assert "§ I" not in labels and "§ P" not in labels


def test_rfc_indented_old_style_heading_resolves():
    """Pre-1990s RFCs indent headings and drop the period ('   2.1  Host Names').

    The dotted, indented form is admitted as a fallback, so `§ 2.1` resolves where the
    column-0 matcher would have found nothing.
    """
    rfc1123 = (
        "Network Working Group\n"
        "Request for Comments: 1123\n"
        "\n"
        "1.  INTRODUCTION\n"
        "\n"
        "   This document covers host requirements.\n"
        "\n"
        "   2.1  Host Names and Numbers\n"
        "\n"
        "   The syntax of a legal Internet host name was specified in RFC-952.\n"
        "\n"
        "   2.2  Using Domain Name Service\n"
        "\n"
        "   Host domain names MUST be translated into IP addresses using the DNS.\n"
    )
    fmt = RfcTextFormat()
    assert "legal Internet host name" in fmt.extract(rfc1123, "§ 2.1")
    assert "translated into IP addresses" in fmt.extract(rfc1123, "§ 2.2")


def test_rfc_indented_numbered_list_is_not_promoted_to_a_heading():
    """An indented *single*-number line is a list item, not a section — only a dotted
    number is admitted, which is what tells a subsection from a step list."""
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n"
        "   The procedure has three steps:\n"
        "\n"
        "   1.  Open the connection.\n"
        "\n"
        "   2.  Send the request.\n"
    )
    labels = section_labels(RfcTextFormat().sections(rfc))
    assert labels == ["§ 1"]  # the list items 1./2. did not become sections


def test_rfc_indented_fallback_is_off_when_subsections_are_at_column_0():
    """A modern RFC numbers its subsections at column 0, and there the indented fallback
    stays off — an indented dotted line (an example, an ABNF rule) is never a section.
    The tell is a column-0 *dotted* heading, not the mere presence of column-0 ones."""
    rfc = (
        "Request for Comments: 8888\n"
        "\n"
        "1.  Introduction\n"
        "\n   Intro.\n\n"
        "2.  Overview\n"
        "\n   Overview.\n\n"
        "2.1.  Scope\n"                       # a column-0 subsection: this doc is modern
        "\n   A real subsection at the margin.\n\n"
        "3.  Details\n"
        "\n   An example follows:\n\n"
        "   3.1  the-rule = something   ; an indented example, not a heading\n"
    )
    labels = section_labels(RfcTextFormat().sections(rfc))
    assert "§ 2.1" in labels       # the column-0 subsection is real
    assert "§ 3.1" not in labels   # the indented example is left alone


def test_rfc_mixed_style_indented_subsections_resolve():
    """RFC 1123's shape: several top-level headings at column 0, every subsection
    indented. The *count* of column-0 headings must not switch the fallback off — the
    absence of column-0 *dotted* headings is what marks the old style, and an earlier
    count-based gate misjudged exactly this document."""
    rfc = (
        "Request for Comments: 1123\n"
        "\n"
        "1.  INTRODUCTION\n\n   Requirements for Internet hosts.\n\n"
        "2.  GENERAL ISSUES\n\n"
        "   2.1  Host Names and Numbers\n\n"
        "   The restriction on the first character is relaxed to allow a digit.\n\n"
        "3.  REMOTE LOGIN\n\n"
        "   3.1  TELNET End-of-Line Convention\n\n"
        "   The end-of-line sequence is the two-character CR LF.\n"
    )
    fmt = RfcTextFormat()
    assert "first character is relaxed" in fmt.extract(rfc, "§ 2.1")
    assert "two-character CR LF" in fmt.extract(rfc, "§ 3.1")


def test_rfc_bare_appendix_subsection_resolves():
    """RFC 9000 writes the appendix parent as 'Appendix A.  Pseudocode' but the child
    as a bare 'A.1.  Sample ...' — recognised once its parent has been seen, so `§ A.1`
    resolves (completing the pairing begun by the appendix-letter designator)."""
    rfc9000 = (
        "Request for Comments: 9000\n"
        "\n"
        "1.  Overview\n"
        "\n"
        "   QUIC is a transport protocol.\n"
        "\n"
        "Appendix A.  Pseudocode\n"
        "\n"
        "   The pseudocode below is non-normative.\n"
        "\n"
        "A.1.  Sample Variable-Length Integer Decoding\n"
        "\n"
        "   The following shows a sample decoding of a variable-length integer.\n"
    )
    fmt = RfcTextFormat()
    assert "non-normative" in fmt.extract(rfc9000, "§ A")
    assert "sample decoding" in fmt.extract(rfc9000, "§ A.1")


def test_rfc_generate_section_selector():
    """Generated selectors use § with just the number prefix."""
    root = RfcTextFormat().sections(_RFC_SAMPLE)
    sel = generate_selector(root, "High-level overview")
    assert sel is not None
    assert sel.startswith("§ 2")
    # Should not include the full title text after the number
    assert "Overview" not in sel


# ══════════════════════════════════════════════════════════════════════
# Edge-case unit tests
# ══════════════════════════════════════════════════════════════════════

# ── Roman numerals: boundaries and malformed ─────────────────────────

def test_roman_boundary():
    assert roman_to_int("I") == 1
    assert roman_to_int("MMMCMXCIX") == 3999
    assert int_to_roman(1) == "I"
    assert int_to_roman(3999) == "MMMCMXCIX"


def test_roman_malformed():
    """Non-standard forms like IIII are parsed greedily (4), VV as 10."""
    assert roman_to_int("IIII") == 4
    assert roman_to_int("VV") == 10
    assert roman_to_int("abc123") is None


# ── Selector parsing: edge cases ─────────────────────────────────────

def test_parse_empty():
    assert parse_selector("") == []


def test_parse_whitespace_only():
    assert parse_selector("   ") == []


def test_parse_multiple_numbered():
    parts = parse_selector("§ 1, § 1.2, paragraph 3")
    assert len(parts) == 3
    assert parts[0].kind == "numbered"
    assert parts[0].value == "1"
    assert parts[1].kind == "numbered"
    assert parts[1].value == "1.2"
    assert parts[2].kind == "paragraph"
    assert parts[2].ordinal == 3


def test_parse_deep_numbered():
    parts = parse_selector("§ 3.2.1")
    assert len(parts) == 1
    assert parts[0].value == "3.2.1"


def test_parse_paragraph_needs_its_number():
    """A bare "paragraph" is not an ordinal, so it is not read as one.

    This asserted `kind == "paragraph", ordinal is None` — the old rule was
    "starts with a lowercase letter", which swept in every lowercase *heading*
    too (`document.domain`, `fetch()`, `http2 push`). Both readings end in a
    miss for this input; the difference is that the new one does not also
    misread real titles.
    """
    parts = parse_selector("paragraph")
    assert len(parts) == 1
    assert parts[0].kind == "heading"


def test_a_lowercase_heading_is_a_heading_not_a_paragraph_ordinal():
    """`http2 push` used to mean "paragraph 2". It means the section called that."""
    parts = parse_selector("http2 push")
    assert parts[0].kind == "heading"
    assert parts[0].value == "http2 push"

    lower, upper = parse_selector("section 7"), parse_selector("Section 7")
    assert lower[0].kind == upper[0].kind == "heading", \
        "`section 7` used to parse as an ordinal while `Section 7` parsed as a title"

    para = parse_selector("paragraph 3")
    assert para[0].kind == "paragraph" and para[0].ordinal == 3


def test_parse_adjacent_commas():
    """Empty parts from adjacent commas are skipped."""
    parts = parse_selector("A,, B")
    assert len(parts) == 2
    assert parts[0].value == "A"
    assert parts[1].value == "B"


def test_parse_unclosed_quote():
    """Unclosed quote doesn't crash — remainder treated as one part."""
    parts = parse_selector("'unclosed, Section 1")
    # The comma inside the unclosed quote is not a separator
    assert len(parts) == 1


# ── Section matching: edge cases ─────────────────────────────────────

def test_match_numbered_with_trailing_dot():
    """Title '4.1. Requirements' matches § 4.1."""
    node = SectionNode(title="4.1. Requirements", level=2)
    part = SectionPart(kind="numbered", value="4.1")
    assert match_section(node, part)


def test_match_heading_extra_whitespace():
    """Extra whitespace in title is normalised for matching."""
    node = SectionNode(title="  Chapter   IV  ", level=1)
    part = SectionPart(kind="heading", value="Chapter IV", ordinal=4)
    assert match_section(node, part)


def test_match_paragraph_returns_false():
    """Paragraph kind is never matched by match_section (handled separately)."""
    node = SectionNode(title="paragraph 3", level=1)
    part = SectionPart(kind="paragraph", value="paragraph 3", ordinal=3)
    assert not match_section(node, part)


# ── Extraction: edge cases ───────────────────────────────────────────

def test_extract_paragraph_out_of_range():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Sec", level=1, paragraphs=["Only one."]),
    ])
    assert extract_by_selector(root, "Sec, paragraph 99") == ""


def test_extract_paragraph_zero():
    """Paragraph indexing is 1-based; 0 returns empty."""
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Sec", level=1, paragraphs=["First."]),
    ])
    assert extract_by_selector(root, "Sec, paragraph 0") == ""


def test_a_selector_that_parses_to_nothing_is_a_miss_not_the_whole_document():
    """This asserted the opposite, and the opposite was a false-pass generator.

    `""`, `","`, `"   "` and `"§"` all parsed to zero parts and returned
    `root.all_text()` — the entire document, handed back as though it were the
    section that was asked for. Section scoping evaporated and every quote in
    the document verified. "No locator at all" is a different question, and
    `formats.extract_content` answers it before ever reaching here.
    """
    root = SectionNode(title="", level=0, paragraphs=["Root text."],
                       children=[
                           SectionNode(title="A", level=1,
                                       paragraphs=["Child text."]),
                       ])
    for junk in ("", "   ", ",", "§", "§ "):
        assert extract_by_selector(root, junk) == "", f"{junk!r} returned the document"

    with pytest.raises(SectionNotFound):
        extract_by_selector(root, ",", strict=True)


def test_extract_section_with_only_children():
    """Section with no own paragraphs but with children returns children's text."""
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Parent", level=1, children=[
            SectionNode(title="Child", level=2,
                        paragraphs=["Child content."]),
        ]),
    ])
    result = extract_by_selector(root, "Parent")
    assert "Child content." in result


def test_extract_four_levels_deep():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="1. Top", level=1, children=[
            SectionNode(title="1.1. Mid", level=2, children=[
                SectionNode(title="1.1.1. Low", level=3, children=[
                    SectionNode(title="1.1.1.1. Deep", level=4,
                                paragraphs=["Deep content."]),
                ]),
            ]),
        ]),
    ])
    result = extract_by_selector(root, "§ 1.1.1.1, paragraph 1")
    assert result == "Deep content."


# ── Generation: edge cases ───────────────────────────────────────────

def test_generate_snippet_in_root():
    """Snippet in root paragraphs (before any heading) → just paragraph N."""
    root = SectionNode(title="", level=0,
                       paragraphs=["Root content here."],
                       children=[
                           SectionNode(title="Later", level=1,
                                       paragraphs=["Other."]),
                       ])
    sel = generate_selector(root, "Root content here.")
    assert sel is not None
    assert sel == "paragraph 1"


def test_generate_title_with_commas():
    """Section titled with commas produces a quoted label."""
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Lost, forever", level=1,
                    paragraphs=["Tragic content."]),
    ])
    sel = generate_selector(root, "Tragic content.")
    assert sel is not None
    assert "'Lost, forever'" in sel


def test_generate_numbered_collapse_three_levels():
    """§ 3.2.1 collapses § 3, § 3.2, § 3.2.1 into just § 3.2.1."""
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="3. Top", level=1, children=[
            SectionNode(title="3.2. Mid", level=2, children=[
                SectionNode(title="3.2.1. Deep", level=3,
                            paragraphs=["Target text."]),
            ]),
        ]),
    ])
    sel = generate_selector(root, "Target text.")
    assert sel is not None
    assert sel.startswith("§ 3.2.1")
    assert "§ 3," not in sel
    assert "§ 3.2," not in sel


# ── High-level: edge cases ───────────────────────────────────────────

def test_locate_empty_body():
    assert locate_section("", "anything", HtmlFormat()) is None


def test_locate_headings_only_no_text():
    """Headings but no paragraph text → snippet not found."""
    html = "<html><body><h1>A</h1><h1>B</h1></body></html>"
    result = locate_section(html, "anything", HtmlFormat())
    assert result is None


def test_extract_section_format_without_sections_method():
    """PlainTextFormat has no sections() → returns empty string."""
    assert extract_section("some text", "paragraph 1", PlainTextFormat()) == ""


# ── A section that is not there (A2) ─────────────────────────────────────
#
# A section miss used to extract "", which the report could only call
# "empty extraction (0 chars)" — the same words it used for a document that was
# genuinely empty, and for one that failed to download. A typo'd section number
# and a dead source read identically.

def _rfc_tree():
    return SectionNode(title="", level=0, children=[
        SectionNode(title="7. Routing", level=1, children=[
            SectionNode(title="7.1. Determining the Target", level=2,
                        paragraphs=["Target text."]),
            SectionNode(title="7.2. Host and :authority", level=2,
                        paragraphs=["Host text."]),
        ]),
        SectionNode(title="9. Methods", level=1, paragraphs=["Methods text."]),
    ])


def test_a_missing_section_is_still_silent_by_default():
    """simplify_selector probes with this, and reads "" as "that one missed".

    Raising here would break locate. The verification path opts in instead.
    """
    assert extract_by_selector(_rfc_tree(), "§ 99.9") == ""


def test_a_missing_section_says_so_when_strict():
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(_rfc_tree(), "§ 99.9", strict=True)
    assert 'no section matches "§ 99.9"' in caught.value.message


def test_a_suggested_section_actually_exists():
    """The adversarial one.

    A suggestion is a claim about the source. Offering a section the document
    does not have is the same lie the tool exists to catch, wearing a helpful
    face. Every candidate must come out of the tree.
    """
    root = _rfc_tree()
    real = set(section_labels(root))

    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(root, "§ 7.3", strict=True)

    assert caught.value.candidates                      # it did suggest something
    for candidate in caught.value.candidates:
        assert candidate in real


def test_a_near_miss_suggests_the_section_you_meant():
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(_rfc_tree(), "§ 7.3", strict=True)
    assert "§ 7.2" in caught.value.candidates


def test_a_wild_miss_suggests_nothing_but_says_what_exists():
    """Better to admit there is nothing close than to reach for a bad guess."""
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(_rfc_tree(), "Bibliography", strict=True)
    assert caught.value.candidates == []
    assert "none like it" in caught.value.message
    assert str(caught.value.available) in caught.value.message


def test_a_document_with_no_sections_says_that_instead():
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(SectionNode(), "§ 1", strict=True)
    assert "no sections at all" in caught.value.message


def test_a_paragraph_that_is_not_there_says_how_many_there_are():
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="Intro", level=1, paragraphs=["One.", "Two."]),
    ])
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(root, "Intro, paragraph 7", strict=True)
    assert "2 paragraphs" in caught.value.message


def test_section_labels_are_paste_able_back_into_a_selector():
    """A suggestion you cannot use is barely a suggestion."""
    root = _rfc_tree()
    for label in section_labels(root):
        assert extract_by_selector(root, label) != ""


def test_candidates_come_from_where_the_walk_failed():
    """"§ 7, Nonexistent" should offer what is under § 7, not the whole document."""
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(_rfc_tree(), "§ 7, Appendix", strict=True)
    assert caught.value.available == 2   # 7.1 and 7.2, not all four sections


def test_a_numbered_miss_suggests_siblings_not_lookalikes():
    """String similarity answers "§ 1.5" with "§ 19.5" — same characters, no meaning.

    The section you meant is nearly always a sibling, so a shared dotted prefix
    has to outrank how the text happens to look.
    """
    root = SectionNode(title="", level=0, children=[
        SectionNode(title="1. Intro", level=1, children=[
            SectionNode(title="1.1. Purpose", level=2, paragraphs=["a"]),
            SectionNode(title="1.4. Terminology", level=2, paragraphs=["b"]),
        ]),
        SectionNode(title="19. Appendices", level=1, children=[
            SectionNode(title="19.5. Notes", level=2, paragraphs=["c"]),
        ]),
    ])
    with pytest.raises(SectionNotFound) as caught:
        extract_by_selector(root, "§ 1.5", strict=True)

    top = caught.value.candidates[0]
    assert top.startswith("§ 1.")      # a sibling, not § 19.5
    assert caught.value.candidates.index("§ 1.4") < \
        caught.value.candidates.index("§ 19.5")


# ── A selector names one section, and only the one it names ─────────────

def test_a_section_number_is_a_number_not_a_string_prefix():
    """`§ 5` returned section 50's text, because the match was `startswith`.

    "50. Security Considerations".startswith("5") is true. And because a match
    was *found*, strict mode never fired: the citation was checked against a
    section the author had not named, with no error and no warning.
    """
    doc = ("# 1. Scope\nScope text.\n\n"
           "# 3. Terms\nTerms text.\n\n"
           "# 50. Security Considerations\nThis document has grave problems.\n")
    md = MarkdownFormat()

    assert "grave problems" in extract_section(doc, "§ 50", md, strict=True)

    with pytest.raises(SectionNotFound):
        extract_section(doc, "§ 5", md, strict=True)


def test_a_real_rfc_section_that_does_not_exist_says_so():
    """RFC 2616 jumps from § 13 to § 13.1.1 — there is no § 13.1 heading.

    `§ 13.1` silently returned § 13.1.1, so a genuine quote from § 13.1.4 was
    reported *absent from a document that contains it*, and a `§ 13.1` citation
    was verified against § 13.1.1's text. Both directions of the lie, from one
    line of code.
    """
    from pathlib import Path
    body = (Path(__file__).parent / "fixtures" / "rfc2616.txt").read_text(
        encoding="utf-8")
    fmt = detect_format(body)

    with pytest.raises(SectionNotFound):
        extract_section(body, "§ 13.1", fmt, strict=True)

    # The sections either side of the gap are real, and must still resolve.
    assert extract_section(body, "§ 13.1.1", fmt, strict=True)
    assert "Many user agents make it possible" in \
        extract_section(body, "§ 13.1.4", fmt, strict=True)


def test_add_never_writes_a_section_selector_check_would_misread():
    """Two sections share a title; a heading part matches the first in the tree.

    So a snippet in the *second* "Introduction" was given the selector
    `Introduction, paragraph 1` — which resolves to the *first*. `add` wrote the
    citation and `check` then verified it against a different section's text,
    quietly. `locate` now proves its selector before returning it, and declines
    rather than emit one that resolves elsewhere.
    """
    doc = ("# Introduction\nAlpha, the first introduction.\n\n"
           "# Body\nSomething else.\n\n"
           "# Introduction\nBeta, the second introduction, entirely different.\n")
    md = MarkdownFormat()
    snippet = "Beta, the second introduction, entirely different."

    result = locate_section(doc, snippet, md)
    if result is not None:
        got = extract_by_selector(md.sections(doc), result.locator)
        assert snippet in got, \
            f"locate emitted {result.locator!r}, which check resolves elsewhere"


def test_a_lowercase_heading_round_trips_through_add_and_check():
    """`add` wrote `Guide, http2 push, paragraph 1`; `check` read paragraph 2 of
    *Guide* — "Root paragraph two is about cats" — and reported no error at all.
    """
    doc = ("# Guide\nRoot paragraph one.\n\nRoot paragraph two is about cats.\n\n"
           "## http2 push\nThe push mechanism sends resources proactively.\n")
    md = MarkdownFormat()
    snippet = "The push mechanism sends resources proactively."

    result = locate_section(doc, snippet, md)
    assert result is not None, "a lowercase heading must still be addressable"

    got = extract_section(doc, result.locator, md, strict=True)
    assert snippet in got, f"check resolved {result.locator!r} to: {got!r}"


# ── The anchor the author already wrote (C3) ────────────────────────────

def test_an_rfc_style_anchor_becomes_a_section_selector():
    """`#section-7.2` is the one piece of targeting every citation already has."""
    doc = "# 7. Fields\nField text.\n\n## 7.2 Host\nHost text.\n"
    md = MarkdownFormat()
    assert selector_for_anchor(doc, "section-7.2", md) == "§ 7.2"
    assert selector_for_anchor(doc, "section-7", md) == "§ 7"


def test_an_anchor_naming_a_heading_resolves_to_that_heading():
    """WHATWG's `#origin-header` sits on `<h3>3.2. \\`Origin\\` header</h3>`."""
    page = ('<html><body><h2 id="http-extensions">3. HTTP extensions</h2>'
            '<h3 id="origin-header">3.2. Origin header</h3>'
            '<p>The Origin header indicates where a fetch originates from.</p>'
            '</body></html>')
    html = HtmlFormat()
    assert selector_for_anchor(page, "origin-header", html) == "§ 3.2"
    assert selector_for_anchor(page, "http-extensions", html) == "§ 3"


def test_an_anchor_on_something_that_is_not_a_heading_does_not_narrow():
    """The trap C3 had to survive.

    In the Fetch spec `#cors-safelisted-request-header` is on an inline `<dfn>`.
    Turning it into a CSS selector would narrow the scope to a two-word term and
    fail every honest citation of the sentence around it. An anchor says where
    the author was *looking*, not always what they meant to quote — and where we
    cannot tell, we must not narrow. Our guess must not be able to condemn a
    citation.
    """
    page = ('<html><body><h2 id="terms">1. Terms</h2>'
            '<p>A <dfn id="cors-safelisted-request-header">CORS-safelisted '
            'request-header</dfn> is a header whose name is safe to send.</p>'
            '</body></html>')
    html = HtmlFormat()
    assert selector_for_anchor(page, "cors-safelisted-request-header", html) is None
    assert selector_for_anchor(page, "no-such-anchor", html) is None
    assert selector_for_anchor(page, "page-42", html) is None


def test_a_heading_anchor_matches_by_slug_where_there_are_no_ids():
    """Markdown and wikitext have no id attributes; renderers slugify the title."""
    doc = "# Origin header\nIntro.\n\n## Browser compatibility\nTable.\n"
    md = MarkdownFormat()
    assert selector_for_anchor(doc, "browser-compatibility", md) == "Browser compatibility"


def test_a_selector_is_never_emitted_that_would_parse_as_something_else():
    """A title with a comma must be quoted, or it parses as two selector parts."""
    from apysource.sections import selector_for_title
    assert selector_for_title("Lost, forever") == "'Lost, forever'"
    assert selector_for_title("7.2 Host") == "§ 7.2"
    assert selector_for_title("Introduction") == "Introduction"
