# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for YAML input loading."""

import pytest
from pathlib import Path
from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.resolution import _get_snippet, _get_source, _get_selector_value
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
