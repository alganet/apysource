# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.sections — human-readable section selectors."""

from apysource.formats import (
    HtmlFormat,
    MarkdownFormat,
    PlainTextFormat,
    RfcTextFormat,
    WikitextFormat,
    detect_format,
    extract_content,
)
from apysource.sections import (
    SectionNode,
    SectionPart,
    extract_by_selector,
    extract_section,
    generate_selector,
    int_to_roman,
    locate_section,
    match_section,
    parse_selector,
    roman_to_int,
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


def test_parse_paragraph_no_number():
    parts = parse_selector("paragraph")
    assert len(parts) == 1
    assert parts[0].kind == "paragraph"
    assert parts[0].ordinal is None


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


def test_extract_empty_selector():
    """Empty selector returns all text."""
    root = SectionNode(title="", level=0, paragraphs=["Root text."],
                       children=[
                           SectionNode(title="A", level=1,
                                       paragraphs=["Child text."]),
                       ])
    result = extract_by_selector(root, "")
    assert "Root text." in result
    assert "Child text." in result


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
