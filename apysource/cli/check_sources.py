# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Run configurable source verification checks."""

import sys
from pathlib import Path

from rdflib import Graph

from apysource.cli._base import CLIContext, pop_flag
from apysource.graph import load_triples
from apysource.http import CachedFetcher
from apysource.namespaces import SV
from apysource.repos import RepoRegistry
from apysource.verification import print_report, run_checks


class CheckSourcesCommand:
    """Verify all configured checks against a sources graph.

    Resolves each fragment/term, extracts its cited content, and confirms the
    snippet is present, printing a pass/fail report and exiting non-zero on
    any failure. Accepts ``--refresh`` (re-fetch, bypassing the HTTP cache),
    ``--strict-redirects`` (fail, rather than warn, on a source URL that has
    moved) and ``--provenance <file>`` (write a PROV-O graph).
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

        # Parse --provenance flag
        prov_path = None
        if "--provenance" in args:
            idx = args.index("--provenance")
            if idx + 1 < len(args):
                prov_path = Path(args[idx + 1])
                args = args[:idx] + args[idx + 2:]
            else:
                print("Error: --provenance requires a file path", file=sys.stderr)
                sys.exit(1)

        if graph is not None:
            g = graph
        else:
            print("\n  Loading RDF...", file=sys.stderr)
            g = load_triples(self.ctx.rdf_root)

        checks_config: list[dict[str, object]] = [
            {"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"},
            {"name": "Terms", "class_uri": SV.Term, "mode": "direct"},
        ]

        emit_prov = prov_path is not None
        results = run_checks(g, checks_config, self.registry,
                             fetcher=self.fetcher, emit_provenance=emit_prov,
                             force=force, strict_redirects=strict_redirects)

        prov_graph = None
        if isinstance(results, tuple):
            results, prov_graph = results

        fail_count = print_report(results)

        if prov_path and prov_graph:
            prov_path.write_text(
                prov_graph.serialize(format="turtle"),
                encoding="utf-8",
            )
            print(f"\n  Provenance written to {prov_path}", file=sys.stderr)

        sys.exit(1 if fail_count > 0 else 0)
