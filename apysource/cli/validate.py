# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Validate all Turtle files: parse and optional SHACL."""

import sys

from apysource.cli._base import CLIContext
from apysource.graph import load_triples_split


class ValidateCommand:
    def __init__(self, ctx: CLIContext):
        self.ctx = ctx

    def run(self, args: list[str] | None = None) -> None:
        rdf_root = self.ctx.rdf_root

        print("=" * 60)
        print("  apysource Validation")
        print("=" * 60)

        print("\n[1/2] Parsing .ttl files...")
        g, shapes, errors = load_triples_split(rdf_root)

        if errors:
            print(f"  PARSE ERRORS ({len(errors)}):")
            for p, err in errors:
                print(f"    {p}: {err}")
            sys.exit(1)

        file_count = len(list(rdf_root.rglob("*.ttl")))
        print(f"  {file_count} files, {len(g)} triples — OK")

        print("\n[2/2] SHACL validation...")
        try:
            from pyshacl import validate
            conforms, _, results_text = validate(g, shacl_graph=shapes)
            if conforms:
                print("  SHACL — PASSED")
            else:
                print("  SHACL — FAILED")
                for line in results_text.split("\n")[:20]:
                    print(f"    {line}")
                sys.exit(1)
        except ImportError:
            print("  SHACL — SKIPPED (pyshacl not installed)")

        print(f"\n{'=' * 60}")
        print("  All checks passed.")
