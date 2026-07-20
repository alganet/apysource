# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for CLI commands with injected args (no sys.argv mutation)."""


import json
from unittest.mock import patch

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from apysource.cli._base import CLIContext
from apysource.graph import load_turtle
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


def test_add_takes_a_name_and_writes_only_the_name(tmp_path, capsys):
    """`apysource add sources.yaml "RFC 9110" "..."` — no rfc-editor url to paste.

    And the entry it writes carries *only* the name. Writing the resolved url back
    would defeat the point of naming a family: the file would stop being about
    RFC 9110 and start being about one particular rfc-editor link.
    """
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    AddCommand(http_client=MockFetcher()).run(
        args=[str(yaml_path), "RFC 9110", "Hello world"])

    entry = yaml.safe_load(yaml_path.read_text())["sources"][0]
    assert entry["label"] == "RFC 9110"
    assert "url" not in entry
    assert entry["fragments"][0]["snippet"] == "Hello world"


def test_a_second_add_by_name_appends_rather_than_duplicating(tmp_path, capsys):
    """A url-less entry has no url to match on. Matching by url anyway would mint
    a second `RFC 9110` — and two entries with one identity is exactly what the
    loader refuses, so the file `add` wrote would not load."""
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    cmd = AddCommand(http_client=MockFetcher("<p>Hello world</p><p>Goodbye world</p>"))
    cmd.run(args=[str(yaml_path), "RFC 9110", "Hello world"])
    cmd.run(args=[str(yaml_path), "RFC 9110", "Goodbye world"])

    sources = yaml.safe_load(yaml_path.read_text())["sources"]
    assert len(sources) == 1
    assert len(sources[0]["fragments"]) == 2


def test_add_uses_the_files_own_patterns(tmp_path, capsys):
    """The patterns `add` resolves with are the ones `check` will use on the file
    it is writing. The two cannot disagree."""
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        "patterns:\n"
        "  - match: '^W3C (?P<slug>[a-z0-9-]+)$'\n"
        "    source: {url: 'http://example.com/TR/{slug}/', type: text/html}\n"
        "sources: []\n")

    AddCommand(http_client=MockFetcher()).run(
        args=[str(yaml_path), "W3C css-color-4", "Hello world"])

    sources = yaml.safe_load(yaml_path.read_text())["sources"]
    assert sources[0]["label"] == "W3C css-color-4"
    assert "http://example.com/TR/css-color-4/" in capsys.readouterr().err


def test_add_by_name_fetches_the_entrys_own_url_not_the_patterns(tmp_path, capsys):
    """The rule `check` applies is that **the entry wins**, and `add` has to apply
    the same one or it writes a targetter it did not measure.

    It minted the url from the pattern and ignored the entry, so a file pinning
    RFC 9110 to datatracker had its snippet located in rfc-editor's *plain text*
    and the resulting locator appended to the *HTML* entry. `check` then ran that
    targetter against a document it was never computed from.
    """
    import yaml
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(yaml.dump({"sources": [{
        "label": "RFC 9110",
        "url": "https://datatracker.ietf.org/doc/html/rfc9110",
        "type": "text/html",
        "fragments": [],
    }]}))

    fetcher = MockFetcher()
    AddCommand(http_client=fetcher).run(args=[str(yaml_path), "RFC 9110", "Hello world"])

    assert fetcher.calls == ["https://datatracker.ietf.org/doc/html/rfc9110"], \
        "add fetched the pattern's url instead of the one the entry pins"

    sources = yaml.safe_load(yaml_path.read_text())["sources"]
    assert len(sources) == 1
    assert sources[0]["url"] == "https://datatracker.ietf.org/doc/html/rfc9110"
    assert len(sources[0]["fragments"]) == 1


def test_add_will_not_overwrite_a_file_it_cannot_read(tmp_path, capsys):
    """`add` rewrites the whole document. A file that exists but has no `sources:`
    was treated as empty and then replaced — a typo'd `source:` cost the author
    everything else in the file, including any `patterns:` block."""
    from apysource.cli.add import AddCommand

    yaml_path = tmp_path / "sources.yaml"
    original = "source:\n  - label: typo\npatterns: []\n"
    yaml_path.write_text(original)

    with pytest.raises(SystemExit):
        AddCommand(http_client=MockFetcher()).run(
            args=[str(yaml_path), "RFC 9110", "Hello world"])

    assert "not a sources file" in capsys.readouterr().err
    assert yaml_path.read_text() == original, "add destroyed the file it refused"


def test_add_refuses_a_name_no_pattern_claims(tmp_path, capsys):
    from apysource.cli.add import AddCommand

    with pytest.raises(SystemExit):
        AddCommand(http_client=MockFetcher()).run(
            args=[str(tmp_path / "sources.yaml"), "Fetsh", "Hello world"])

    assert "no pattern mints a url from 'Fetsh'" in capsys.readouterr().err


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
    # The project supplies no shapes of its own, and it does not need to: the
    # shipped ones always apply. This used to report SKIPPED — on every run
    # anyone has ever made, since apysource's own shapes could never be found
    # under a *project's* RDF root.
    assert "SHACL — PASSED" in out
    assert "All checks passed" in out


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

    # Patched where the checker is *called from*, not where the CLI happens to
    # import it: the promise is that the flag reaches the thing that does the
    # checking, however many layers sit in between.
    with patch("apysource.api.run_checks", return_value=[]) as run:
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

    # Patched where the checker is *called from*, not where the CLI happens to
    # import it: the promise is that the flag reaches the thing that does the
    # checking, however many layers sit in between.
    with patch("apysource.api.run_checks", return_value=[]) as run:
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


# ── The shape check, and who gets it ────────────────────────────────────

def _shape_checks(report):
    return [c for c in report["checks"] if c["name"] == "Citations shape"]


def test_a_yaml_loaded_graph_gets_no_shape_check(capsys):
    """The loader is the stricter gate; running the shapes after it buys nothing.

    This is also the regression test for downstream YAML users: `check` must not
    grow a new check, a new failure mode, or a pyshacl dependency on the path
    everybody already runs.
    """
    from apysource.cli.check_sources import CheckSourcesCommand

    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)
    with pytest.raises(SystemExit):
        cmd.run(graph=_make_check_graph(), args=["--format", "json"], vetted=True)

    assert _shape_checks(json.loads(capsys.readouterr().out)) == []


def test_a_turtle_graph_gets_a_shape_check(capsys):
    """Turtle has no loader. The shapes are the only thing that looks at it."""
    from apysource.cli.check_sources import CheckSourcesCommand

    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)
    with pytest.raises(SystemExit):
        cmd.run(graph=_make_check_graph(), args=["--format", "json"], vetted=False)

    checks = _shape_checks(json.loads(capsys.readouterr().out))
    assert len(checks) == 1


def test_the_shape_check_does_not_make_an_empty_run_pass(capsys):
    """A structural check is not work.

    The shape check has to carry a total — one with none renders `----` and can
    never fail — but counting it as work would let an empty Turtle project
    conform vacuously, report 1/1, and go out green. That is the silent pass
    this tool exists to abolish, delivered by the machinery meant to strengthen
    it.
    """
    from apysource.cli.check_sources import CheckSourcesCommand
    from rdflib import Graph as _Graph

    ctx = CLIContext(project_root=".", rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    cmd = CheckSourcesCommand(ctx=ctx, registry=EMPTY_REGISTRY)
    with pytest.raises(SystemExit) as exc:
        cmd.run(graph=_Graph(), args=["--format", "json"], vetted=False)

    report = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert report["summary"]["nothing_verified"] is True


# ── A .ttl argument is read ─────────────────────────────────────────────

def test_validate_reads_a_ttl_argument(tmp_path, capsys):
    """It used to match no suffix, so the file named on the command line was
    never opened: `validate` scanned the configured RDF root instead and passed
    the filename on as an unrecognised positional."""
    from apysource.cli.validate import ValidateCommand

    ttl = tmp_path / "citations.ttl"
    ttl.write_text(
        '@prefix sv: <https://alganet.github.io/apysource/vocab.ttl#> .\n'
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix schema: <https://schema.org/> .\n'
        '<http://example.org/s> a sv:Source ; rdfs:label "S" ;\n'
        '  schema:url "https://example.org/" .\n',
        encoding="utf-8",
    )
    ctx = CLIContext(project_root=str(tmp_path), rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    ValidateCommand(ctx=ctx).run(graph=load_turtle(ttl), args=[], vetted=False)

    out = capsys.readouterr().out
    assert "Turtle file — parsed OK" in out
    assert "SHACL — PASSED" in out


def test_validate_fails_a_ttl_the_shapes_refuse(tmp_path, capsys):
    from apysource.cli.validate import ValidateCommand

    ttl = tmp_path / "bad.ttl"
    ttl.write_text(
        '@prefix sv: <https://alganet.github.io/apysource/vocab.ttl#> .\n'
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix oa: <http://www.w3.org/ns/oa#> .\n'
        '@prefix schema: <https://schema.org/> .\n'
        '<http://example.org/s> a sv:Source ; rdfs:label "S" ;\n'
        '  schema:url "https://example.org/" .\n'
        '<http://example.org/f> a sv:Fragment ; rdfs:label "F" ;\n'
        '  oa:hasTarget [ a oa:SpecificResource ;\n'
        '    oa:hasSource <http://example.org/s> ;\n'
        '    oa:hasSelector [ a oa:TextQuoteSelector ;\n'
        '      oa:exact "one", "two" ] ] .\n',
        encoding="utf-8",
    )
    ctx = CLIContext(project_root=str(tmp_path), rdf_subdir="rdf",
                     sources_cache_subdir="data/sources")
    with pytest.raises(SystemExit) as exc:
        ValidateCommand(ctx=ctx).run(graph=load_turtle(ttl), args=[], vetted=False)

    assert exc.value.code == 1
    assert "SHACL — FAILED" in capsys.readouterr().out


class TestWorkersFlag:
    """`--workers` is validated; a valid value must not then be dropped."""

    def _command(self, tmp_path, fetcher):
        from apysource.cli._base import CLIContext
        from apysource.cli.check_sources import CheckSourcesCommand
        from tests.conftest import EMPTY_REGISTRY

        return CheckSourcesCommand(
            ctx=CLIContext(project_root=str(tmp_path), rdf_subdir="rdf",
                           sources_cache_subdir="sources"),
            registry=EMPTY_REGISTRY, fetcher=fetcher,
        )

    def test_it_reaches_the_fetcher(self, tmp_path):
        from apysource.http import CachedFetcher

        fetcher = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        command = self._command(tmp_path, fetcher)

        with pytest.raises(SystemExit):
            command.run(graph=Graph(), args=["--workers", "7"])

        assert fetcher.workers == 7

    def test_a_valid_value_with_no_fetcher_is_an_error_not_a_shrug(self, tmp_path):
        """The one outcome that leaves the user nothing to go on.

        Having rejected `--workers 0` and `--workers abc`, accepting `8` and
        silently ignoring it means waiting out a serial run believing it is
        parallel.
        """
        command = self._command(tmp_path, fetcher=None)

        with pytest.raises(SystemExit) as exit_info:
            command.run(graph=Graph(), args=["--workers", "8"])

        assert exit_info.value.code == 1

    @pytest.mark.parametrize("value", ["0", "-3", "abc"])
    def test_a_value_that_is_not_a_worker_count_is_refused(self, tmp_path, value):
        from apysource.http import CachedFetcher

        command = self._command(tmp_path, CachedFetcher(cache_dir=tmp_path))

        with pytest.raises(SystemExit) as exit_info:
            command.run(graph=Graph(), args=["--workers", value])

        assert exit_info.value.code == 1
