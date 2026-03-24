# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.graph loading and utility functions."""

from pathlib import Path

from rdflib import Graph, URIRef

from apysource.graph import local_name, load_triples, load_triples_split

VOCAB_DIR = Path(__file__).resolve().parent.parent / "vocab"


# ── load_triples ────────────────────────────────────────────────────────

def test_load_triples_loads_ttl():
    """load_triples loads the vocab/vocab.ttl file successfully."""
    g = load_triples(VOCAB_DIR)
    assert len(g) > 0
    # Should contain sv:Source class
    assert any("apysource/vocab.ttl#Source" in str(s) for s in g.subjects())


# ── load_triples_split ──────────────────────────────────────────────────

def test_load_triples_split_returns_graphs():
    """load_triples_split returns data graph, shapes graph, and errors list."""
    data_g, shapes_g, errors = load_triples_split(VOCAB_DIR)
    assert isinstance(data_g, Graph)
    assert isinstance(shapes_g, Graph)
    assert isinstance(errors, list)
    assert len(data_g) > 0


# ── local_name ────────────────────────────────────────────────────────────

def test_local_name_extracts_fragment():
    """local_name extracts the local name after # from a URI."""
    uri = URIRef("https://alganet.github.io/apysource/vocab.ttl#Source")
    assert local_name(uri) == "Source"


def test_local_name_no_fragment():
    """local_name returns full string when no # present."""
    uri = URIRef("https://example.com/thing")
    assert local_name(uri) == "https://example.com/thing"
