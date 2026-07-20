# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Validate all Turtle files: parse and optional SHACL."""

import sys

from rdflib import Graph

from apysource.cli._base import CLIContext
from apysource.graph import load_triples_split
from apysource.shapes import conforms, shipped_shapes


class ValidateCommand:
    """Check a citations file, or every ``.ttl`` under the RDF root.

    Given a ``.yaml``, the file is loaded — which is where the real invariants
    live: every citation must have an identity of its own, every key must be one
    apysource knows, every value must be the kind of thing it claims to be.

    Exits non-zero on a parse error, a SHACL conformance failure, or a run that
    validated nothing at all. It used to accept a YAML argument, **silently
    discard it**, validate an empty directory and report "All checks passed" —
    a validator that validated nothing and said so in green, which is the very
    thing this tool exists to abolish.
    """

    #: Opt in to YAML-graph input (see ``cli.__main__``). Without this, a
    #: ``.yaml`` argument was dropped on the floor.
    accepts_graph = True

    def __init__(self, ctx: CLIContext):
        self.ctx = ctx

    def run(self, graph: Graph | None = None,
            args: list[str] | None = None, vetted: bool = False) -> None:
        """Validate the given citations file, or every Turtle file; exit 1 on failure."""
        print("=" * 60)
        print("  apysource Validation")
        print("=" * 60)

        if graph is not None:
            # Reaching here at all means the file parsed. For a `.yaml` that also
            # means it *loaded* — identity, known keys, scalar values, a quote to
            # verify — and `__main__` turned any refusal into one clear line and
            # exited before we were called. For a `.ttl` it means only that the
            # syntax was Turtle; the shapes below are what reads it.
            kind = "Citations file" if vetted else "Turtle file"
            print(f"\n  {kind} — parsed OK ({len(graph)} triples)")
            shapes = Graph()
            g = graph
        else:
            rdf_root = self.ctx.rdf_root
            print("\n[1/2] Parsing .ttl files...")
            g, shapes, errors = load_triples_split(rdf_root)

            if errors:
                print(f"  PARSE ERRORS ({len(errors)}):")
                for p, err in errors:
                    print(f"    {p}: {err}")
                sys.exit(1)

            print(f"  {len(g)} triples — OK")

        if not len(g):
            # The commonest way to get here is pointing the command at the wrong
            # directory. It reported success.
            print("\n  NOTHING WAS VALIDATED: no triples were found.")
            print(f"{'=' * 60}")
            sys.exit(1)

        print("\n[2/2] SHACL validation...")
        skipped = False

        # The shipped shapes always apply; a project's own are *added* to them,
        # never a replacement. Before, shapes were looked for only under the
        # project's RDF root — where apysource's own could never be — so this
        # step reported "SKIPPED (no shapes found)" on every run there has ever
        # been, and the constraints rotted unobserved for want of anything
        # checking them.
        shapes += shipped_shapes()

        ok, report = conforms(g, shapes)
        if ok is None:
            print(f"  SHACL — SKIPPED ({report})")
            skipped = True
        elif ok:
            print("  SHACL — PASSED")
        else:
            print("  SHACL — FAILED")
            for line in report.split("\n")[:20]:
                print(f"    {line}")
            sys.exit(1)

        print(f"\n{'=' * 60}")
        if skipped:
            # Saying "all checks passed" when one of them did not run is the
            # same lie in a smaller costume.
            print("  Parsed and loaded cleanly. SHACL did not run.")
        else:
            print("  All checks passed.")
