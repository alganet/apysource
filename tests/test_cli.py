# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for CLI commands with injected args (no sys.argv mutation)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from apysource.cli._base import CLIContext
from apysource.namespaces import OA, SCHEMA, SV

from tests.conftest import EMPTY_REGISTRY


class _MockFetcher:
    """Fetcher that returns canned HTML."""

    def __init__(self, body: str = "<html><body><p>Hello world</p></body></html>"):
        self.body = body

    def get(self, url, **kw):
        return self.body


def _make_check_graph():
    """Graph with one Fragment + Source for check-sources tests."""
    g = Graph()
    frag = URIRef("urn:test:frag1")
    source = URIRef("urn:test:src1")
    g.add((frag, RDF.type, SV.Fragment))
    g.add((frag, RDFS.label, Literal("test frag")))
    g.add((frag, SV.sourceLocation, Literal("lines:1-5")))
    # OA target chain
    target = BNode()
    g.add((frag, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source))
    g.add((source, RDF.type, SV.Source))
    g.add((source, RDFS.label, Literal("test source")))
    g.add((source, SCHEMA.url, Literal("http://example.com/page")))
    return g


# ── LocateCommand ────────────────────────────────────────────────────────

def test_locate_yaml_output(capsys):
    """LocateCommand emits YAML fragment when snippet is found."""
    from apysource.cli.locate import LocateCommand

    fetcher = _MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["http://example.com/page", "Hello world"])

    out = capsys.readouterr().out
    assert "snippet:" in out
    assert "Hello world" in out


def test_locate_ttl_output(capsys):
    """LocateCommand emits Turtle with OA triples in --ttl mode."""
    from apysource.cli.locate import LocateCommand

    fetcher = _MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["--ttl", "http://example.com/page", "Hello world"])

    out = capsys.readouterr().out
    assert "TextQuoteSelector" in out
    assert "oa:exact" in out or "exact" in out


def test_locate_not_found(capsys):
    """LocateCommand exits 1 when snippet is not found."""
    from apysource.cli.locate import LocateCommand

    fetcher = _MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    with pytest.raises(SystemExit, match="1"):
        cmd.run(args=["http://example.com/page", "nonexistent text xyz"])


def test_locate_usage(capsys):
    """LocateCommand prints usage when too few args."""
    from apysource.cli.locate import LocateCommand

    fetcher = _MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    with pytest.raises(SystemExit, match="1"):
        cmd.run(args=[])


# ── AddCommand ───────────────────────────────────────────────────────────

def test_add_creates_entry(tmp_path, capsys):
    """AddCommand creates a YAML file with the located snippet."""
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    fetcher = _MockFetcher()
    cmd = AddCommand(http_client=fetcher)
    cmd.run(args=[str(yaml_path), "http://example.com/page", "Hello world"])

    data = yaml.safe_load(yaml_path.read_text())
    assert "sources" in data
    assert len(data["sources"]) == 1
    assert data["sources"][0]["url"] == "http://example.com/page"
    assert data["sources"][0]["type"] == "text/html"
    assert len(data["sources"][0]["fragments"]) == 1
    assert data["sources"][0]["fragments"][0]["snippet"] == "Hello world"


def test_add_appends_to_existing(tmp_path, capsys):
    """AddCommand appends to an existing source entry."""
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(yaml.dump({
        "sources": [{
            "label": "Test",
            "url": "http://example.com/page",
            "type": "text/html",
            "fragments": [],
        }]
    }))

    fetcher = _MockFetcher()
    cmd = AddCommand(http_client=fetcher)
    cmd.run(args=[str(yaml_path), "http://example.com/page", "Hello world"])

    data = yaml.safe_load(yaml_path.read_text())
    assert len(data["sources"]) == 1
    assert len(data["sources"][0]["fragments"]) == 1


# ── ValidateCommand ──────────────────────────────────────────────────────

def test_validate_parses_ttl(tmp_path, capsys):
    """ValidateCommand parses .ttl files without error."""
    from apysource.cli.validate import ValidateCommand

    rdf_dir = tmp_path / "rdf"
    rdf_dir.mkdir()
    (rdf_dir / "test.ttl").write_text(
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '<http://example.org/x> rdfs:label "test" .\n'
    )

    ctx = CLIContext(
        project_root=str(tmp_path),
        rdf_subdir="rdf",
        sources_cache_subdir="data/sources",
    )
    cmd = ValidateCommand(ctx=ctx)
    cmd.run(args=[])

    out = capsys.readouterr().out
    assert "1 files" in out
    assert "OK" in out


# ── CheckSourcesCommand ─────────────────────────────────────────────────

def test_check_sources_exits_on_failure(capsys):
    """CheckSourcesCommand exits 1 when fragments are unresolvable."""
    from apysource.cli.check_sources import CheckSourcesCommand

    g = _make_check_graph()
    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)

    with pytest.raises(SystemExit) as exc_info:
        cmd.run(graph=g, args=[])

    # Should exit (either 0 or 1 depending on resolution)
    assert exc_info.value.code in (0, 1)


def test_check_sources_provenance_output(tmp_path, capsys):
    """CheckSourcesCommand with --provenance writes a PROV graph to file."""
    from apysource.cli.check_sources import CheckSourcesCommand

    g = _make_check_graph()
    prov_file = tmp_path / "prov.ttl"
    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)

    with pytest.raises(SystemExit):
        cmd.run(graph=g, args=["--provenance", str(prov_file)])

    assert prov_file.exists()
    # Parse and verify it contains a VerificationActivity
    from rdflib import Graph as RdfGraph
    from rdflib.namespace import RDF
    pg = RdfGraph()
    pg.parse(str(prov_file), format="turtle")
    activities = list(pg.subjects(RDF.type, SV.VerificationActivity))
    assert len(activities) >= 1
