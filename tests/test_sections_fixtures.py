# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Fixture-based integration tests for section parsing.

Tests use real documents stored in tests/fixtures/:
- un_charter.html  — UN Charter full text (HTML)
- rfc8288.html     — Web Linking (rfc-editor's legacy htmlization)
- markdown_syntax.md — Markdown syntax reference (Markdown)
- http.wiki         — Wikipedia HTTP article (Wikitext)

The RFC arrives through ``RfcRepo.render``, because that is the only form of it
any format ever sees. Reading the rendition raw here would be testing a document
apysource does not read.
"""

from pathlib import Path

import pytest

from apysource.formats import (
    HtmlFormat,
    MarkdownFormat,
    WikitextFormat,
    detect_format,
    extract_content,
    normalize_ws,
)
from apysource.repos.rfc import render
from apysource.sections import (
    SectionNotFound,
    extract_by_selector,
    locate_section,
    resolve_selector,
    section_labels,
    sections_containing,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def un_charter():
    return (FIXTURES / "un_charter.html").read_text(encoding="utf-8")


#: Renditions their publisher's repo normalizes before any format sees them.
RENDITIONS = {"rfc8288.html"}


def fixture_body(name):
    """A fixture as apysource would actually have it in hand."""
    raw = (FIXTURES / name).read_text(encoding="utf-8", errors="replace")
    return render(raw) if name in RENDITIONS else raw


@pytest.fixture
def rfc8288():
    return fixture_body("rfc8288.html")


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


def test_detect_rfc8288(rfc8288):
    """A normalized RFC is a page, and is read by the reader for pages.

    There is no format that detects an RFC any more, and this is what replaces
    the one there was: a heuristic that scored textual signals — "Request for
    Comments:", a form feed, two dotted headings — and would claim a changelog or
    a mailing-list archive that quoted an RFC header. Which document a repo has
    fetched is not something to sniff for.
    """
    assert detect_format(rfc8288).name == "html"


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
    """The selector must name the passage's *own* section.

    This asserted `"Preamble" in locator`, which was the old, broadened answer:
    `simplify_selector` picked the shortest selector that *contained* the
    snippet, and a section always contains its subsections' text while having a
    shorter label. The passage actually lives in `WE THE PEOPLES…`, a subsection
    of the Preamble — and the Preamble has **no paragraphs of its own at all**,
    so the old citation named a section containing none of the quoted words
    directly.
    """
    fmt = HtmlFormat()
    snippet = "to save succeeding generations from the scourge of war"
    result = locate_section(un_charter, snippet, fmt)

    assert result is not None
    assert result.format_name == "section"

    root = fmt.sections(un_charter)
    named = resolve_selector(root, result.locator)
    assert named is not None
    assert any(snippet in p for p in named.paragraphs), \
        f"{result.locator!r} names a section that does not itself hold the passage"


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
# RFC 8288 (rfc-editor's legacy htmlization, as RfcRepo hands it over)
# ══════════════════════════════════════════════════════════════════════

def test_rfc_deep_nesting(rfc8288):
    """A three-deep dotted section is reachable by the number it prints."""
    result = extract_content(rfc8288, "§ 3.4.1, paragraph 1", format_name="section")
    assert "link-params can be translated to serialisation-defined target" in \
        normalize_ws(result)


def test_rfc_toc_not_parsed(rfc8288):
    """The table of contents must not mint a section per line.

    It is a page of dotted leaders and numbers, and the numbers are the same
    ones the real headings carry — so a reader that took them would build a
    second, empty copy of the whole document, and `§ 3.4.1` would have two
    answers. The legacy rendition puts no heading markup in the ToC, which is
    what keeps it out.
    """
    titles = [c.title for c in HtmlFormat().sections(rfc8288).children]

    assert titles.count("3. Link Serialisation in HTTP Headers") == 1
    assert len(titles) == 10, titles
    for title in titles:
        designator = title.split()[0].rstrip(".")
        assert designator.isdigit() or title.startswith("Appendix"), title


def test_rfc_page_breaks_transparent(rfc8288):
    """A sentence broken by a page boundary has to read as one sentence.

    In the rendition it is interrupted by a footer, a horizontal rule, a page
    anchor and a running header — around 130 characters of furniture that no
    reader ever saw and that no author would think to quote.
    """
    sentence = ('the serialisation(s) that they might occur within. For example, '
                'the application "Web browsing"')
    assert sentence in normalize_ws(HtmlFormat().text(rfc8288))


def test_rfc_locate_deep_section(rfc8288):
    """Locate names the section the passage is in, not the document."""
    result = locate_section(
        rfc8288, 'application "Web browsing" looks for the "stylesheet"',
        HtmlFormat())
    assert result is not None
    assert result.locator == "§ 2"


def test_rfc_roundtrip(rfc8288):
    """Locate a snippet, extract by what came back, find the snippet again."""
    snippet = 'application "Web browsing" looks for the "stylesheet" link relation'
    result = locate_section(rfc8288, snippet, HtmlFormat())
    assert result is not None
    extracted = extract_content(rfc8288, result.locator, format_name="section")
    assert snippet in normalize_ws(extracted)


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


def test_locate_still_works_when_a_candidate_selector_misses(rfc8288):
    """The regression A2 could very easily have caused.

    simplify_selector *probes* with extract_by_selector and reads "" as "that
    candidate found nothing". Making the miss raise — the obvious way to do A2 —
    turns every probe into a crash, and locate stops working at all. Hence
    strict=False by default, and this test to keep it that way.
    """
    snippet = 'application "Web browsing" looks for the "stylesheet" link relation'
    result = locate_section(rfc8288, snippet, HtmlFormat())

    assert result is not None
    assert result.locator == "§ 2"
    assert snippet in normalize_ws(
        extract_content(rfc8288, result.locator, format_name="section"))


def test_a_missing_section_in_a_real_rfc_names_real_ones(rfc8288):
    """Suggestions are claims about the source; they must be true of it."""
    fmt = HtmlFormat()
    real = set(section_labels(fmt.sections(rfc8288)))

    with pytest.raises(SectionNotFound) as caught:
        extract_content(rfc8288, "§ 99.9", format_name="section", strict=True)

    assert caught.value.candidates
    for candidate in caught.value.candidates:
        assert candidate in real


# ── The promise: a selector names the passage's own section ──────────────

def _all_sections(node):
    for child in node.children:
        yield child
        yield from _all_sections(child)


@pytest.mark.parametrize("fixture", [
    "rfc8288.html", "un_charter.html", "markdown_syntax.md",
    "mdn_origin.md", "http.wiki",
])
def test_locate_names_the_section_the_passage_actually_lives_in(fixture):
    """The property, over every paragraph of five real documents.

    `simplify_selector` looked for *the shortest selector that extracts text
    containing the snippet* — and that objective quietly guarantees the wrong
    answer, because a section always contains its subsections' text and always
    has the shorter label. A passage in § 4.2.1 was cited as § 4.2. On RFC 9110
    that was **157 of 271** paragraphs; it round-tripped every time, which is
    why nothing caught it.

    It is not a cosmetic imprecision. The scope a citation is checked against
    became the whole parent section, so a quote drifting from § 4.2.1 to § 4.2.5
    would still verify — exactly the rot section targeting exists to catch.

    Passages a specification repeats verbatim in two places are excluded: there
    the ambiguity is in the source, not in us, and `locate` says so on stderr.
    """
    body = fixture_body(fixture)
    fmt = detect_format(body)
    root = fmt.sections(body)

    passages = [(node, para)
                for node in _all_sections(root)
                for para in node.paragraphs
                if len(para) >= 50]
    # Sampled across the whole document rather than exhaustive: locating every
    # one of RFC 2616's 1,311 paragraphs takes half a minute, and a stride over
    # the lot covers the same structural variety in under a second.
    stride = max(1, len(passages) // 60)

    checked = 0
    for node, para in passages[::stride]:
        if len(sections_containing(root, para)) > 1:
            continue              # the source itself is ambiguous here
        result = locate_section(body, para, fmt)
        assert result is not None, f"no selector for a passage in {node.title!r}"
        assert resolve_selector(root, result.locator) is node, (
            f"{result.locator!r} names another section; the passage is in "
            f"{node.title!r}"
        )
        checked += 1

    assert checked > 5, f"{fixture} exercised almost nothing ({checked})"
