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


def _write_ttl(path: Path, subject: str):
    path.write_text(
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        f'<http://example.org/{subject}> rdfs:label "{subject}" .\n',
        encoding="utf-8",
    )


def test_load_triples_classifies_by_filename_not_path(tmp_path):
    """A data file under a directory whose name contains 'shapes' is still
    loaded — classification must use the file name, not the full path."""
    data_dir = tmp_path / "shapes-archive"  # path contains "shapes"
    data_dir.mkdir()
    _write_ttl(data_dir / "data.ttl", "thing")

    g = load_triples(tmp_path)
    assert any("example.org/thing" in str(s) for s in g.subjects())


def test_load_triples_split_classifies_by_filename(tmp_path):
    """A shapes file goes to the shapes graph; a data file under a path that
    contains 'shapes' still goes to the data graph."""
    nested = tmp_path / "shapes-dir"
    nested.mkdir()
    _write_ttl(nested / "data.ttl", "datum")     # data, despite the dir name
    _write_ttl(tmp_path / "shapes.ttl", "shape")  # shapes, by file name

    data_g, shapes_g, errors = load_triples_split(tmp_path)
    assert errors == []
    assert any("example.org/datum" in str(s) for s in data_g.subjects())
    assert any("example.org/shape" in str(s) for s in shapes_g.subjects())


# ── local_name ────────────────────────────────────────────────────────────

def test_local_name_extracts_fragment():
    """local_name extracts the local name after # from a URI."""
    uri = URIRef("https://alganet.github.io/apysource/vocab.ttl#Source")
    assert local_name(uri) == "Source"


def test_local_name_no_fragment():
    """local_name returns full string when no # present."""
    uri = URIRef("https://example.com/thing")
    assert local_name(uri) == "https://example.com/thing"
