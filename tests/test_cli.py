# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for CLI commands with injected args (no sys.argv mutation)."""


import json
from unittest.mock import patch

import pytest
from rdflib import URIRef
from rdflib.namespace import RDF

from apysource.cli._base import CLIContext
from apysource.namespaces import SV

from tests.conftest import EMPTY_REGISTRY, MockFetcher, build_chain_graph


def _make_check_graph():
    """Graph with one Fragment + Source for check-sources tests."""
    return build_chain_graph(
        URIRef("urn:test:frag1"), URIRef("urn:test:src1"),
        "http://example.com/page", label="test frag",
    )


# ── LocateCommand ────────────────────────────────────────────────────────

def test_locate_yaml_output(capsys):
    """LocateCommand emits YAML fragment when snippet is found."""
    from apysource.cli.locate import LocateCommand

    fetcher = MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["http://example.com/page", "Hello world"])

    out = capsys.readouterr().out
    assert "snippet:" in out
    assert "Hello world" in out


def test_locate_ttl_output(capsys):
    """LocateCommand emits Turtle with OA triples in --ttl mode."""
    from apysource.cli.locate import LocateCommand

    fetcher = MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["--ttl", "http://example.com/page", "Hello world"])

    out = capsys.readouterr().out
    assert "TextQuoteSelector" in out
    assert "oa:exact" in out or "exact" in out


def test_locate_refresh_forces_fetch(capsys):
    """--refresh makes LocateCommand fetch with force=True (bypass cache)."""
    from apysource.cli.locate import LocateCommand

    class _SpyFetcher(MockFetcher):
        def __init__(self):
            super().__init__()
            self.force_values = []

        def get(self, url, **kwargs):
            self.force_values.append(kwargs.get("force", False))
            return super().get(url, **kwargs)

    fetcher = _SpyFetcher()
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["--refresh", "http://example.com/page", "Hello world"])
    assert fetcher.force_values == [True]


def test_locate_not_found(capsys):
    """LocateCommand exits 1 when snippet is not found."""
    from apysource.cli.locate import LocateCommand

    fetcher = MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    with pytest.raises(SystemExit, match="1"):
        cmd.run(args=["http://example.com/page", "nonexistent text xyz"])


def test_locate_usage(capsys):
    """LocateCommand prints usage when too few args."""
    from apysource.cli.locate import LocateCommand

    fetcher = MockFetcher()
    cmd = LocateCommand(http_client=fetcher)
    with pytest.raises(SystemExit, match="1"):
        cmd.run(args=[])


# ── AddCommand ───────────────────────────────────────────────────────────

def test_add_creates_entry(tmp_path, capsys):
    """AddCommand creates a YAML file with the located snippet."""
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    fetcher = MockFetcher()
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

    fetcher = MockFetcher()
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
    # It printed the number of files it *found* (rglob), not the number it
    # parsed — the two differ exactly when a file is being silently dropped.
    assert "triples — OK" in out
    # No shapes in this directory, so SHACL cannot have run, and the command
    # must not claim otherwise.
    assert "SHACL — SKIPPED" in out
    assert "All checks passed" not in out


def test_validate_refuses_to_pass_when_it_validated_nothing(tmp_path, capsys):
    """It reported "All checks passed" over an empty directory.

    The commonest way to get there is pointing the command at the wrong path —
    and a validator that validates nothing and calls it green is the whole
    disease.
    """
    from apysource.cli.validate import ValidateCommand

    (tmp_path / "rdf").mkdir()
    ctx = CLIContext(project_root=str(tmp_path), rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")

    with pytest.raises(SystemExit) as exc:
        ValidateCommand(ctx=ctx).run(args=[])

    assert exc.value.code == 1
    assert "NOTHING WAS VALIDATED" in capsys.readouterr().out


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

    # No repos and no fetcher -> fragment cannot resolve -> failure -> exit 1.
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


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
    pg = RdfGraph()
    pg.parse(str(prov_file), format="turtle")
    activities = list(pg.subjects(RDF.type, SV.VerificationActivity))
    assert len(activities) >= 1


def test_locate_not_found_explains_the_near_miss(capsys):
    """A blind 'not found' is the thing that made authoring guesswork."""
    from apysource.cli.locate import LocateCommand

    page = ("<html><body><p>A client MUST send a Host header field "
            "(Section 7.2 of [HTTP]) in all HTTP/1.1 request messages."
            "</p></body></html>")
    fetcher = MockFetcher(content=page)
    cmd = LocateCommand(http_client=fetcher)

    with pytest.raises(SystemExit, match="1"):
        cmd.run(args=[
            "http://example.com/page",
            "A client MUST send a Host header field in all HTTP/1.1 "
            "request messages.",
        ])

    err = capsys.readouterr().err
    assert "snippet not found" in err
    assert "closest match" in err
    assert "(Section 7.2 of [HTTP])" in err


def test_locate_notes_a_redirected_url(capsys):
    """The cheapest moment to fix a stale citation: before writing it down."""
    from apysource.cli.locate import LocateCommand

    fetcher = MockFetcher(
        redirects={"http://old.example.com/page": "http://new.example.com/page"},
    )
    cmd = LocateCommand(http_client=fetcher)
    cmd.run(args=["http://old.example.com/page", "Hello world"])

    err = capsys.readouterr().err
    assert "redirects to http://new.example.com/page" in err


def test_check_sources_accepts_the_repo_flags(capsys):
    """--strict-repos and --no-crawl reach run_checks rather than being ignored.

    A flag the CLI silently swallows is worse than no flag: the user believes
    the run was strict, and it was not.
    """
    from apysource.cli.check_sources import CheckSourcesCommand

    g = _make_check_graph()
    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)

    with patch("apysource.cli.check_sources.run_checks",
               return_value=[]) as run:
        with pytest.raises(SystemExit):
            cmd.run(graph=g, args=["--strict-repos", "--no-crawl"])

    kwargs = run.call_args.kwargs
    assert kwargs["strict_repos"] is True
    assert kwargs["crawl"] is False


def test_check_sources_crawls_by_default(capsys):
    from apysource.cli.check_sources import CheckSourcesCommand

    g = _make_check_graph()
    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)

    with patch("apysource.cli.check_sources.run_checks",
               return_value=[]) as run:
        with pytest.raises(SystemExit):
            cmd.run(graph=g, args=[])

    kwargs = run.call_args.kwargs
    assert kwargs["strict_repos"] is False
    assert kwargs["crawl"] is True


# ── check --format json (C1) ────────────────────────────────────────────

def _run_check(args, capsys):
    """Run CheckSourcesCommand, returning (exit_code, stdout, stderr)."""
    from apysource.cli.check_sources import CheckSourcesCommand

    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)
    with pytest.raises(SystemExit) as exc:
        cmd.run(graph=_make_check_graph(), args=args)
    captured = capsys.readouterr()
    return exc.value.code, captured.out, captured.err


def test_check_format_json_stdout_is_parseable(capsys):
    """stdout carries only JSON. Anything chatty belongs on stderr."""
    code, out, _err = _run_check(["--format", "json"], capsys)

    report = json.loads(out)          # the whole point: this must not throw
    assert "checks" in report and "summary" in report
    assert code == 1                  # this graph cannot resolve


def test_check_json_exit_code_matches_the_text_one(capsys):
    """A CI job and a human must not be told different things about one run."""
    text_code, _out, _err = _run_check([], capsys)
    json_code, out, _err = _run_check(["--format", "json"], capsys)

    assert text_code == json_code
    assert json.loads(out)["summary"]["failed"] is (json_code == 1)


def test_check_format_requires_a_value(capsys):
    """A flag that silently does nothing is worse than one that refuses.

    The user believes the run was configured; it was not.
    """
    code, _out, err = _run_check(["--format"], capsys)
    assert code == 1
    assert "requires a value" in err


def test_check_rejects_an_unknown_format(capsys):
    code, _out, err = _run_check(["--format", "xml"], capsys)
    assert code == 1
    assert "unknown --format" in err
