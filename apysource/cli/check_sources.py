# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Run configurable source verification checks."""

import json
import sys
from pathlib import Path

from rdflib import Graph

from apysource.cli._base import CLIContext, UsageError, pop_flag, pop_value
from apysource.graph import load_triples
from apysource.http import CachedFetcher
from apysource.namespaces import SV
from apysource.repos import RepoRegistry
from apysource.verification import json_report, print_report, run_checks


class CheckSourcesCommand:
    """Verify all configured checks against a sources graph.

    Resolves each fragment/term, extracts its cited content, and confirms the
    snippet is present, printing a pass/fail report and exiting non-zero on
    any failure. Accepts ``--refresh`` (re-fetch and re-crawl, bypassing the
    caches), ``--strict-redirects`` (fail, rather than warn, on a source URL
    that has moved), ``--strict-repos`` (fail on a repo that claimed a URL but
    could not serve it), ``--no-crawl`` (never fetch a repo document that is
    not already cached), ``--format json`` (a machine-readable report; stdout
    then carries only JSON) and ``--provenance <file>`` (write a PROV-O graph).
    """

    #: Opt in to YAML-graph input: ``check`` may take a sources file as its
    #: first positional argument (see ``cli.__main__``).
    accepts_graph = True

    def __init__(self, ctx: CLIContext, registry: RepoRegistry,
                 fetcher: CachedFetcher | None = None) -> None:
        self.ctx = ctx
        self.registry = registry
        self.fetcher = fetcher

    def run(self, graph: Graph | None = None, args: list[str] | None = None) -> None:
        """Run the configured checks and exit 1 if any fragment fails."""
        if args is None:
            args = []

        # Parse --refresh flag (re-fetch sources, bypassing the HTTP cache)
        force, args = pop_flag(args, "--refresh")

        # A moved source URL warns by default; --strict-redirects fails on it.
        strict_redirects, args = pop_flag(args, "--strict-redirects")

        # A repo that claimed a URL but could not serve it warns by default:
        # the snippet was still checked, but against the fetched page rather
        # than the repository the citation names. --strict-repos fails on it.
        strict_repos, args = pop_flag(args, "--strict-repos")

        # --no-crawl refuses to fetch a repo document that is not cached,
        # reporting the miss instead of quietly fetching a different document.
        no_crawl, args = pop_flag(args, "--no-crawl")

        try:
            fmt, args = pop_value(args, "--format")
            prov, args = pop_value(args, "--provenance")
        except UsageError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if fmt is not None and fmt != "json":
            print(f"Error: unknown --format {fmt!r} (only 'json')", file=sys.stderr)
            sys.exit(1)

        as_json = fmt == "json"
        prov_path = Path(prov) if prov else None

        if graph is not None:
            g = graph
        else:
            # stderr, so that --format json leaves stdout carrying only JSON.
            print("\n  Loading RDF...", file=sys.stderr)
            g = load_triples(self.ctx.rdf_root)

        checks_config: list[dict[str, object]] = [
            {"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"},
            {"name": "Terms", "class_uri": SV.Term, "mode": "direct"},
        ]

        emit_prov = prov_path is not None
        results = run_checks(g, checks_config, self.registry,
                             fetcher=self.fetcher, emit_provenance=emit_prov,
                             force=force, strict_redirects=strict_redirects,
                             strict_repos=strict_repos, crawl=not no_crawl)

        prov_graph = None
        if isinstance(results, tuple):
            results, prov_graph = results

        if as_json:
            report = json_report(results)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            fail_count = report["summary"]["fail"]
        else:
            fail_count = print_report(results)

        if prov_path and prov_graph:
            prov_path.write_text(
                prov_graph.serialize(format="turtle"),
                encoding="utf-8",
            )
            print(f"\n  Provenance written to {prov_path}", file=sys.stderr)

        sys.exit(1 if fail_count > 0 else 0)
