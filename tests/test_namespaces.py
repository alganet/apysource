# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.namespaces."""

from rdflib import Graph

from apysource.namespaces import SV, bind_prefixes, new_graph


# ── SV namespace ─────────────────────────────────────────────────────────

def test_sv_namespace_uri():
    """SV namespace has the correct base URI."""
    assert str(SV) == "https://alganet.github.io/apysource#"


def test_sv_term_expansion():
    """SV terms expand to the correct full URI."""
    assert str(SV.Source) == "https://alganet.github.io/apysource#Source"
    assert str(SV.Fragment) == "https://alganet.github.io/apysource#Fragment"


# ── bind_prefixes ────────────────────────────────────────────────────────

def test_bind_prefixes_binds_to_graph():
    """bind_prefixes registers namespace prefixes on a graph."""
    g = Graph()
    bind_prefixes(g)
    namespaces = dict(g.namespaces())
    assert "sv" in namespaces
    assert str(namespaces["sv"]) == "https://alganet.github.io/apysource#"


def test_bind_prefixes_custom():
    """bind_prefixes accepts custom prefix dict."""
    g = Graph()
    bind_prefixes(g, {"custom": SV})
    namespaces = dict(g.namespaces())
    assert "custom" in namespaces


# ── new_graph ────────────────────────────────────────────────────────────

def test_new_graph_creates_graph_with_prefixes():
    """new_graph returns a Graph with all standard prefixes bound."""
    g = new_graph()
    assert isinstance(g, Graph)
    namespaces = dict(g.namespaces())
    assert "sv" in namespaces
    assert "rdf" in namespaces
    assert "rdfs" in namespaces
    assert "owl" in namespaces
