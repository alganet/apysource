# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for YAML input loading."""

import pytest
from pathlib import Path
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.resolution import _get_source, _get_selector_value
from apysource.yaml_input import load_yaml, _slugify, _make_uri


# ── Helpers ──────────────────────────────────────────────────────────────

SIMPLE_YAML = """\
sources:
  - label: "UN Charter"
    url: "https://www.un.org/en/about-us/un-charter/full-text"
    type: html
    language: en
    fragments:
      - label: "Preamble"
        selector: "p"
        snippet: "to save succeeding generations"
      - label: "Article 1"
        section: "Article 1"
        snippet: "The Purposes of the United Nations are"
"""

LINES_YAML = """\
sources:
  - label: "RFC 2616"
    url: "https://www.rfc-editor.org/rfc/rfc2616.txt"
    type: plain-text
    fragments:
      - label: "HTTP Overview"
        lines: "30-35"
        snippet: "application-level protocol"
"""

PART_OF_YAML = """\
sources:
  - label: "The Book"
    url: "https://example.com/book"
    type: html
  - label: "Chapter 1"
    url: "https://example.com/book/ch1"
    part_of: "The Book"
    fragments:
      - label: "Opening"
        location: "chapter:1"
        snippet: "It was a dark and stormy night"
"""

NO_SOURCES_YAML = """\
something_else:
  - foo: bar
"""

MISSING_LABEL_YAML = """\
sources:
  - url: "https://example.com"
"""

MISSING_URL_YAML = """\
sources:
  - label: "No URL Source"
"""

MISSING_FRAG_LABEL_YAML = """\
sources:
  - label: "Source"
    url: "https://example.com"
    fragments:
      - snippet: "some text"
"""


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "sources.yaml"
    p.write_text(content)
    return p


# ── Unit tests ───────────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("UN Charter") == "un_charter"


def test_slugify_special_chars():
    assert _slugify("Hello, World! (2026)") == "hello_world_2026"


def test_make_uri_source():
    uri = _make_uri("UN Charter", "source")
    assert str(uri) == "urn:apysource:source_un_charter"


def test_make_uri_fragment():
    uri = _make_uri("UN Charter Preamble", "fragment")
    assert str(uri) == "urn:apysource:fragment_un_charter_preamble"


# ── Integration tests ────────────────────────────────────────────────────

def test_load_simple(tmp_path):
    """Sources and fragments load with correct triples."""
    g = load_yaml(_write_yaml(tmp_path, SIMPLE_YAML))

    sources = list(g.subjects(RDF.type, SV.Source))
    assert len(sources) == 1

    source = sources[0]
    assert str(g.value(source, RDFS.label)) == "UN Charter"
    assert str(g.value(source, SCHEMA.url)) == "https://www.un.org/en/about-us/un-charter/full-text"
    assert str(g.value(source, DCTERMS.format)) == "text/html"
    assert str(g.value(source, DCTERMS.language)) == "en"

    frags = list(g.subjects(RDF.type, SV.Fragment))
    assert len(frags) == 2

    labels = {str(g.value(f, RDFS.label)) for f in frags}
    assert labels == {"Preamble", "Article 1"}

    # Fragment source is linked via OA target chain
    for frag in frags:
        assert _get_source(g, frag) == source
        label = str(g.value(frag, RDFS.label))
        if label == "Preamble":
            assert _get_selector_value(g, frag, OA.CssSelector) == "p"
        elif label == "Article 1":
            assert _get_selector_value(g, frag, SV.SectionSelector) == "Article 1"


def test_load_lines(tmp_path):
    """Line-range fragments load correctly."""
    g = load_yaml(_write_yaml(tmp_path, LINES_YAML))

    frags = list(g.subjects(RDF.type, SV.Fragment))
    assert len(frags) == 1
    assert str(g.value(frags[0], SV.sourceLines)) == "30-35"


def test_load_part_of(tmp_path):
    """partOfSource references resolve by label."""
    g = load_yaml(_write_yaml(tmp_path, PART_OF_YAML))

    sources = sorted(g.subjects(RDF.type, SV.Source), key=str)
    assert len(sources) == 2

    ch1 = [s for s in sources if str(g.value(s, RDFS.label)) == "Chapter 1"][0]
    parent = g.value(ch1, DCTERMS.isPartOf)
    assert parent is not None
    assert str(g.value(parent, RDFS.label)) == "The Book"


PART_OF_FORWARD_YAML = """\
sources:
  - label: "Chapter 1"
    url: "https://example.com/book/ch1"
    part_of: "The Book"
  - label: "The Book"
    url: "https://example.com/book"
    type: html
"""


def test_load_part_of_forward_reference(tmp_path):
    """part_of resolves even when the parent is defined later in the file."""
    g = load_yaml(_write_yaml(tmp_path, PART_OF_FORWARD_YAML))

    sources = list(g.subjects(RDF.type, SV.Source))
    ch1 = [s for s in sources if str(g.value(s, RDFS.label)) == "Chapter 1"][0]
    parent = g.value(ch1, DCTERMS.isPartOf)
    assert parent is not None
    assert str(g.value(parent, RDFS.label)) == "The Book"


def test_load_location(tmp_path):
    """sourceLocation maps correctly."""
    g = load_yaml(_write_yaml(tmp_path, PART_OF_YAML))

    frags = list(g.subjects(RDF.type, SV.Fragment))
    assert len(frags) == 1
    assert str(g.value(frags[0], SV.sourceLocation)) == "chapter:1"


def test_deterministic_uris(tmp_path):
    """Same YAML produces identical URIs on repeated loads."""
    g1 = load_yaml(_write_yaml(tmp_path, SIMPLE_YAML))
    g2 = load_yaml(_write_yaml(tmp_path, SIMPLE_YAML))

    sources1 = sorted(str(s) for s in g1.subjects(RDF.type, SV.Source))
    sources2 = sorted(str(s) for s in g2.subjects(RDF.type, SV.Source))
    assert sources1 == sources2


# ── OA Web Annotation alignment ─────────────────────────────────────────

def test_oa_triples_emitted(tmp_path):
    """Fragments emit full OA Web Annotation structure."""
    g = load_yaml(_write_yaml(tmp_path, SIMPLE_YAML))
    frags = list(g.subjects(RDF.type, SV.Fragment))
    assert len(frags) == 2

    for frag in frags:
        # Every fragment with a snippet gets oa:motivatedBy
        assert g.value(frag, OA.motivatedBy) == OA.identifying

        # oa:hasTarget → oa:SpecificResource
        target = g.value(frag, OA.hasTarget)
        assert target is not None
        assert (target, RDF.type, OA.SpecificResource) in g

        # oa:hasSource points back to the Source
        source = g.value(target, OA.hasSource)
        assert source is not None
        assert (source, RDF.type, SV.Source) in g

        # TextQuoteSelector with oa:exact (snippet lives here, not on sv:sourceSnippet)
        selectors = list(g.objects(target, OA.hasSelector))
        tqs_selectors = [s for s in selectors
                         if (s, RDF.type, OA.TextQuoteSelector) in g]
        assert len(tqs_selectors) == 1
        assert g.value(tqs_selectors[0], OA.exact) is not None

    # Fragment with CSS selector gets CssSelector
    for frag in frags:
        label = str(g.value(frag, RDFS.label))
        target = g.value(frag, OA.hasTarget)
        selectors = list(g.objects(target, OA.hasSelector))
        selector_types = {type_uri for s in selectors
                          for type_uri in g.objects(s, RDF.type)}
        if label == "Preamble":
            assert OA.CssSelector in selector_types
        elif label == "Article 1":
            assert SV.SectionSelector in selector_types


# ── Error handling ───────────────────────────────────────────────────────

def test_error_no_sources_key(tmp_path):
    with pytest.raises(ValueError, match="sources"):
        load_yaml(_write_yaml(tmp_path, NO_SOURCES_YAML))


def test_error_missing_label(tmp_path):
    with pytest.raises(ValueError, match="label"):
        load_yaml(_write_yaml(tmp_path, MISSING_LABEL_YAML))


def test_error_missing_url(tmp_path):
    with pytest.raises(ValueError, match="url"):
        load_yaml(_write_yaml(tmp_path, MISSING_URL_YAML))


def test_error_missing_fragment_label(tmp_path):
    with pytest.raises(ValueError, match="label"):
        load_yaml(_write_yaml(tmp_path, MISSING_FRAG_LABEL_YAML))


# ── An identity is an identity (the URN-collision tranche) ───────────────

def _write(tmp_path, text):
    p = tmp_path / "sources.yaml"
    p.write_text(text, encoding="utf-8")
    return p


_TWO_FRAGMENTS = """
sources:
  - label: "RFC 9110"
    url: "https://example.com/spec"
    type: text/plain
    fragments:
      - label: "{a}"
        snippet: "a quote that is genuinely in the source somewhere"
      - label: "{b}"
        snippet: "a fabrication that appears in no document anywhere"
"""


def test_two_labels_that_mint_one_urn_are_refused(tmp_path):
    """The worst outcome this tool can produce, and it shipped.

    `_slugify` collapses every run of non-alphanumeric characters to `_`, so
    `rules/host_header` and `rules-host-header` are one URN. RDF being a set,
    the two fragments silently became **one**, carrying both snippets — and
    `_get_snippet` reads one of them with `g.value()`, which picks arbitrarily.

    The fabricated quote verified **green**, because the arbitrary pick landed
    on the other fragment's honest snippet. One citation was checked twice and
    the other was not checked at all.
    """
    path = _write(tmp_path, _TWO_FRAGMENTS.format(a="rules/host_header",
                                                  b="rules-host-header"))
    with pytest.raises(ValueError, match="identity collision"):
        load_yaml(path)


def test_the_same_label_twice_is_refused(tmp_path):
    """Two entries with one identity are one entry; the second would vanish."""
    path = _write(tmp_path, _TWO_FRAGMENTS.format(a="expires", b="expires"))
    with pytest.raises(ValueError, match="duplicate fragment"):
        load_yaml(path)


def test_two_source_labels_that_mint_one_urn_are_refused(tmp_path):
    """Worse than the fragment case: the snippet is checked against the wrong
    *document*. Two colliding sources merge, carrying two schema:url, and
    `_resolve_source_url` takes one arbitrarily — so a citation can be verified
    against a document it does not name, and the one it does name is never
    fetched.
    """
    path = _write(tmp_path, """
sources:
  - label: "RFC 9110"
    url: "https://example.com/2024"
    type: text/plain
    fragments:
      - label: "one"
        snippet: "a quote long enough to be taken seriously"
  - label: "RFC-9110"
    url: "https://example.com/2025"
    type: text/plain
    fragments:
      - label: "two"
        snippet: "another quote long enough to be taken seriously"
""")
    with pytest.raises(ValueError, match="identity collision"):
        load_yaml(path)


def test_a_non_ascii_label_keeps_its_letters(tmp_path):
    """`[^a-z0-9]` erased every character of a Cyrillic label, so three
    fragments minted one empty URN between them and two citations vanished.
    """
    path = _write(tmp_path, """
sources:
  - label: "Устав"
    url: "https://example.com/spec"
    type: text/plain
    fragments:
      - label: "Преамбула"
        snippet: "a quote long enough to be taken seriously here"
      - label: "Введение"
        snippet: "another quote long enough to be taken seriously"
""")
    g = load_yaml(path)
    urns = {str(f) for f in g.subjects(RDF.type, SV.Fragment)}
    assert len(urns) == 2, f"two fragments must have two identities, got {urns}"
    assert all(u != "urn:apysource:fragment_" for u in urns)


# ── Nothing the author wrote is thrown away ──────────────────────────────

def test_an_unknown_key_is_refused(tmp_path):
    """`snipet:` loaded without a murmur and the citation verified nothing."""
    path = _write(tmp_path, """
sources:
  - label: "S"
    url: "https://example.com/x"
    fragments:
      - label: "f"
        snipet: "the quote the author actually wrote down"
""")
    with pytest.raises(ValueError, match="unknown key"):
        load_yaml(path)


def test_a_snippet_written_as_a_list_is_refused(tmp_path):
    """It was stored as its Python repr and could never match anything."""
    path = _write(tmp_path, """
sources:
  - label: "S"
    url: "https://example.com/x"
    fragments:
      - label: "f"
        snippet:
          - "line one of the quote"
          - "line two of the quote"
""")
    with pytest.raises(ValueError, match="single piece of text"):
        load_yaml(path)


def test_a_section_of_zero_is_not_dropped(tmp_path):
    """`if section:` dropped `section: 0` — and a dropped section is a false
    pass, because the quote is then matched against the whole document.
    """
    path = _write(tmp_path, """
sources:
  - label: "S"
    url: "https://example.com/x"
    fragments:
      - label: "f"
        section: 0
        snippet: "a quote long enough to be taken seriously"
""")
    g = load_yaml(path)
    values = {str(v) for v in g.objects(None, RDF.value)}
    assert "0" in values, "the section the author wrote must reach the graph"


def test_a_part_of_that_names_nothing_is_refused(tmp_path):
    """A typo'd parent silently unhooked the source from its book."""
    path = _write(tmp_path, """
sources:
  - label: "Chapter"
    url: "https://example.com/x"
    part_of: "The Bok"
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
""")
    with pytest.raises(ValueError, match="not a source in this file"):
        load_yaml(path)


# ── A name is enough, when a pattern knows the family ────────────────────

RFC_URL = "https://www.rfc-editor.org/rfc/rfc9110.txt"


def _one(g, predicate):
    """The single object of this predicate in the graph."""
    return str(next(iter(g.objects(None, predicate))))


def test_a_url_less_source_gets_one_from_the_shipped_pattern(tmp_path):
    """`url` stops being required — but only because something else supplies it.
    A source apysource cannot fetch is still refused; it just has one more way of
    learning where to fetch from."""
    g = load_yaml(_write(tmp_path, """
sources:
  - label: "RFC 9110"
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))
    assert _one(g, SCHEMA.url) == RFC_URL
    assert _one(g, DCTERMS.format) == "text/plain"


def test_a_named_source_and_a_written_one_mean_the_same_thing(tmp_path):
    """The minted url is written by the ordinary loader, so nothing downstream —
    repo claiming, format detection, verification — can tell the two apart."""
    named = load_yaml(_write(tmp_path, """
sources:
  - label: "RFC 9110"
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))
    written = load_yaml(_write(tmp_path, f"""
sources:
  - label: "RFC 9110"
    url: "{RFC_URL}"
    type: text/plain
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))
    assert named.isomorphic(written)


def test_the_file_beats_the_shipped_pattern(tmp_path):
    g = load_yaml(_write(tmp_path, """
patterns:
  - match: '^RFC (?P<n>\\d+)$'
    source:
      url: "https://datatracker.ietf.org/doc/html/rfc{n}"
      type: text/html
sources:
  - label: "RFC 9110"
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))
    assert _one(g, SCHEMA.url) == "https://datatracker.ietf.org/doc/html/rfc9110"


def test_an_entry_key_beats_the_pattern_that_minted_the_url(tmp_path):
    """Name the family, then say the one thing the family cannot know."""
    g = load_yaml(_write(tmp_path, """
sources:
  - label: "RFC 9110"
    title: "HTTP Semantics"
    type: text/html
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))
    assert _one(g, SCHEMA.url) == RFC_URL          # the pattern's
    assert _one(g, DCTERMS.format) == "text/html"  # the entry's
    assert _one(g, DCTERMS.title) == "HTTP Semantics"


def test_a_name_no_pattern_claims_names_the_patterns_it_tried(tmp_path):
    with pytest.raises(ValueError, match=r"no pattern mints one.*Tried:.*RFC"):
        load_yaml(_write(tmp_path, """
sources:
  - label: "Fetch"
    fragments:
      - label: "f"
        snippet: "a quote long enough to be taken seriously"
"""))


def test_two_url_less_labels_that_mint_one_urn_are_still_refused(tmp_path):
    """Identity is minted from the label, before any url is looked at. Naming a
    family changes nothing about that: two citations that cannot be told apart
    are refused however their url arrived."""
    with pytest.raises(ValueError, match="identity collision"):
        load_yaml(_write(tmp_path, """
patterns:
  - match: '^rfc[- ](?P<n>\\d+)$'
    source: {url: "https://example.com/rfc{n}"}
  - match: '^RFC (?P<n>\\d+)$'
    source: {url: "https://example.com/rfc{n}"}
sources:
  - label: "RFC 9110"
  - label: "rfc-9110"
"""))


def test_a_top_level_key_nobody_knows_is_refused(tmp_path):
    """A typo'd `pattern:` would mint nothing, and every url-less source below it
    would then fail with a message about entirely the wrong thing."""
    with pytest.raises(ValueError, match="unknown key 'pattern'"):
        load_yaml(_write(tmp_path, """
pattern:
  - match: '^RFC (?P<n>\\d+)$'
    source: {url: "https://example.com/rfc{n}"}
sources:
  - label: "RFC 9110"
"""))
