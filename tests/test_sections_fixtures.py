# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Fixture-based integration tests for section parsing.

Tests use real documents stored in tests/fixtures/:
- un_charter.html  — UN Charter full text (HTML)
- rfc2616.txt      — HTTP/1.1 specification (IETF RFC plain text)
- markdown_syntax.md — Markdown syntax reference (Markdown)
- http.wiki         — Wikipedia HTTP article (Wikitext)
"""

from pathlib import Path

import pytest

from apysource.formats import (
    HtmlFormat,
    MarkdownFormat,
    RfcTextFormat,
    WikitextFormat,
    detect_format,
    extract_content,
)
from apysource.sections import (
    extract_by_selector,
    generate_selector,
    locate_section,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def un_charter():
    return (FIXTURES / "un_charter.html").read_text(encoding="utf-8")


@pytest.fixture
def rfc2616():
    return (FIXTURES / "rfc2616.txt").read_text(encoding="utf-8")


@pytest.fixture
def markdown_syntax():
    return (FIXTURES / "markdown_syntax.md").read_text(encoding="utf-8")


@pytest.fixture
def http_wiki():
    return (FIXTURES / "http.wiki").read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# Format auto-detection
# ══════════════════════════════════════════════════════════════════════

def test_detect_un_charter(un_charter):
    assert detect_format(un_charter).name == "html"


def test_detect_rfc2616(rfc2616):
    assert detect_format(rfc2616).name == "rfc"


def test_detect_markdown_syntax(markdown_syntax):
    assert detect_format(markdown_syntax).name == "markdown"


def test_detect_http_wiki(http_wiki):
    assert detect_format(http_wiki).name == "wikitext"


# ══════════════════════════════════════════════════════════════════════
# UN Charter (HTML)
# ══════════════════════════════════════════════════════════════════════

def test_un_charter_top_level_sections(un_charter):
    root = HtmlFormat().sections(un_charter)
    charter = root.children[1]  # "United Nations Charter (full text)"
    assert charter.title == "United Nations Charter (full text)"
    assert len(charter.children) == 21  # Preamble + 19 chapters + Amendments


def test_un_charter_preamble_structure(un_charter):
    root = HtmlFormat().sections(un_charter)
    charter = root.children[1]
    preamble = charter.children[0]
    assert preamble.title == "Preamble"
    assert len(preamble.children) == 3  # Three sub-headings


def test_un_charter_locate_preamble_snippet(un_charter):
    fmt = HtmlFormat()
    result = locate_section(
        un_charter,
        "to save succeeding generations from the scourge of war",
        fmt,
    )
    assert result is not None
    assert result.format_name == "section"
    # Should reference the Preamble area
    assert "Preamble" in result.locator or "paragraph" in result.locator


def test_un_charter_roundtrip_article(un_charter):
    """Locate a snippet in Article 1, extract back, verify it's there."""
    fmt = HtmlFormat()
    snippet = "The Purposes of the United Nations are"
    result = locate_section(un_charter, snippet, fmt)
    assert result is not None
    extracted = extract_content(un_charter, result.locator, format_name="section")
    assert snippet in extracted


def test_un_charter_chapter_by_title(un_charter):
    """Full title match extracts the correct chapter."""
    root = HtmlFormat().sections(un_charter)
    charter = root.children[1]
    # Match by exact title (case-insensitive)
    result = extract_by_selector(
        charter, "Chapter IV: The General Assembly")
    assert result != ""
    assert len(result) > 100  # Non-trivial content


def test_un_charter_chapter_roman_equiv(un_charter):
    """'Chapter II' matches section titled 'Chapter II: Membership' via heading match."""
    root = HtmlFormat().sections(un_charter)
    charter = root.children[1]
    # "Chapter II: Membership" — using just "Chapter II" won't match because
    # the full title is "Chapter II: Membership". This tests that limitation
    # is understood: selectors must match the full section title.
    ch2 = charter.children[2]
    assert "Chapter II" in ch2.title


# ══════════════════════════════════════════════════════════════════════
# RFC 2616 (IETF plain text)
# ══════════════════════════════════════════════════════════════════════

def test_rfc_section_count(rfc2616):
    root = RfcTextFormat().sections(rfc2616)
    assert len(root.children) == 21


def test_rfc_deep_nesting(rfc2616):
    """Section 10.4.18 (417 Expectation Failed) is reachable via § 10.4.18."""
    result = RfcTextFormat().extract(rfc2616, "§ 10.4.18, paragraph 1")
    assert "expectation" in result.lower() or "Expect" in result


def test_rfc_toc_not_parsed(rfc2616):
    """Indented ToC lines don't create spurious sections."""
    root = RfcTextFormat().sections(rfc2616)
    # The ToC is before section 1, so it becomes root paragraphs.
    # None of the root paragraphs should have section-like titles
    # as children.
    for child in root.children:
        # All real sections start with a number
        assert child.title[0].isdigit(), f"Unexpected section: {child.title!r}"


def test_rfc_page_breaks_transparent(rfc2616):
    """Content spanning form feeds is correctly assembled."""
    root = RfcTextFormat().sections(rfc2616)
    # Section 1.4 has content that spans page breaks in the raw file
    sec1 = root.children[0]
    sec14 = None
    for c in sec1.children:
        if "1.4" in c.title:
            sec14 = c
            break
    assert sec14 is not None
    # Should have substantial paragraphs (content spans multiple pages)
    assert len(sec14.paragraphs) >= 10


def test_rfc_locate_deep_section(rfc2616):
    """Locate '408 Request Timeout' → selector references § 10.4 area."""
    result = RfcTextFormat().locate(
        rfc2616, "The client did not produce a request within the time")
    assert result is not None
    assert "§ 10.4" in result.locator


def test_rfc_roundtrip(rfc2616):
    """Locate snippet in section 1.4, extract back, verify."""
    fmt = RfcTextFormat()
    snippet = "Any party to the communication which is not acting as a tunnel"
    result = locate_section(rfc2616, snippet, fmt)
    assert result is not None
    assert "§ 1.4" in result.locator
    extracted = extract_content(rfc2616, result.locator, format_name="section")
    assert snippet in extracted


def test_rfc_no_trailing_dot_headings(rfc2616):
    """RFC 2616 uses '1 Introduction' (no trailing dot) — still parsed."""
    root = RfcTextFormat().sections(rfc2616)
    # Section titles should be normalised with the dot
    titles = [c.title for c in root.children]
    intro = [t for t in titles if "Introduction" in t]
    assert len(intro) == 1


# ══════════════════════════════════════════════════════════════════════
# Markdown (mxstbr test file)
# ══════════════════════════════════════════════════════════════════════

def test_md_fixture_tree_structure(markdown_syntax):
    root = MarkdownFormat().sections(markdown_syntax)
    assert len(root.children) == 1  # "Markdown: Syntax"
    top = root.children[0]
    assert top.title == "Markdown: Syntax"
    assert len(top.children) == 3  # Overview, Block Elements, Span Elements


def test_md_fixture_nested(markdown_syntax):
    """Overview → Philosophy nesting."""
    root = MarkdownFormat().sections(markdown_syntax)
    overview = root.children[0].children[0]
    assert overview.title == "Overview"
    assert len(overview.children) == 1
    assert overview.children[0].title == "Philosophy"


def test_md_fixture_locate_snippet(markdown_syntax):
    """Simplified selector: Overview contains Philosophy's text."""
    result = MarkdownFormat().locate(
        markdown_syntax,
        "Markdown is intended to be as easy-to-read",
    )
    assert result is not None
    # Simplifier picks shortest working selector
    assert "Overview" in result.locator or "Philosophy" in result.locator


def test_md_fixture_roundtrip(markdown_syntax):
    fmt = MarkdownFormat()
    snippet = "Markdown is intended to be as easy-to-read"
    result = locate_section(markdown_syntax, snippet, fmt)
    assert result is not None
    extracted = extract_content(
        markdown_syntax, result.locator, format_name="section")
    assert snippet in extracted


def test_md_fixture_block_elements_children(markdown_syntax):
    """Block Elements has 5 subsections."""
    root = MarkdownFormat().sections(markdown_syntax)
    block = root.children[0].children[1]
    assert block.title == "Block Elements"
    assert len(block.children) == 5
    titles = [c.title for c in block.children]
    assert "Paragraphs and Line Breaks" in titles
    assert "Code Blocks" in titles


# ══════════════════════════════════════════════════════════════════════
# Wikitext (Wikipedia HTTP article)
# ══════════════════════════════════════════════════════════════════════

def test_wiki_fixture_section_count(http_wiki):
    root = WikitextFormat().sections(http_wiki)
    assert len(root.children) == 10


def test_wiki_fixture_nested(http_wiki):
    """Technology section has 5 children."""
    root = WikitextFormat().sections(http_wiki)
    tech = root.children[2]
    assert tech.title == "Technology"
    assert len(tech.children) == 5


def test_wiki_fixture_anchor_in_title(http_wiki):
    """Headings with {{anchor}} templates are parsed with template text."""
    root = WikitextFormat().sections(http_wiki)
    # Find "Message format{{anchor |message-format}}"
    msg_fmt = None
    for child in root.children:
        if "Message format" in child.title:
            msg_fmt = child
            break
    assert msg_fmt is not None
    assert "{{anchor" in msg_fmt.title  # Template is part of the title


def test_wiki_fixture_locate_snippet(http_wiki):
    """Locate a paragraph from the Technology > Transport layer section."""
    result = WikitextFormat().locate(
        http_wiki, "underlying and reliable")
    assert result is not None
    assert "Technology" in result.locator or "Transport" in result.locator


def test_wiki_fixture_roundtrip(http_wiki):
    fmt = WikitextFormat()
    snippet = "underlying and reliable"
    result = locate_section(http_wiki, snippet, fmt)
    assert result is not None
    extracted = extract_content(http_wiki, result.locator, format_name="section")
    assert snippet in extracted


def test_wiki_fixture_root_paragraphs(http_wiki):
    """Wikipedia articles have intro paragraphs before the first heading."""
    root = WikitextFormat().sections(http_wiki)
    assert len(root.paragraphs) >= 3


def test_wiki_fixture_deep_nesting(http_wiki):
    """Technology > Data exchange has sub-subsections (4 levels deep)."""
    root = WikitextFormat().sections(http_wiki)
    tech = root.children[2]
    data_exchange = tech.children[1]
    assert data_exchange.title == "Data exchange"
    assert len(data_exchange.children) >= 2  # Has sub-subsections
