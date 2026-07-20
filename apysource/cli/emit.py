# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Write the citations graph out as RDF.

apysource has always *been* an RDF tool — a YAML sources file is parsed straight
into a graph, and everything downstream sees only triples. What it had no way of
doing was letting that graph back out. `--provenance` writes PROV-O about a run,
`locate --ttl` writes one fragment; neither is the citations themselves. Anyone
who wanted their sources file as RDF had to import `load_yaml` and call
`.serialize()` by hand, which is a strange thing to require of a tool whose whole
premise is that you get RDF without having to know you are using it.

The command is thin on purpose. Everything about the *RDF* — the format table,
the serializing, the identifier warning — lives in ``apysource.emit``, so a
generator writing citations of its own says it the same way rather than restating
it. What stays here is the arguments, the paths and the exits.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph

from apysource.cli._base import UsageError, pop_value
from apysource.emit import UnknownFormat, identifier_warning, is_stable, serialize


class EmitCommand:
    """Serialize a citations file as RDF.

    Takes the same file arguments `check` and `validate` take, through the same
    dispatch — so `emit` on a `.ttl` is a format conversion, and the two ways of
    writing citations stay interchangeable at the boundary.
    """

    #: Opt in to graph input (see ``cli.__main__``).
    accepts_graph = True

    #: Flags whose next argument is a value, not a positional. Without this the
    #: dispatcher took `-o out.ttl` as the *input* file and wrote the graph over
    #: whatever came after it — which, in `emit -o out.ttl sources.yaml`, is the
    #: citations file.
    value_flags = ("--format", "-o", "--output")

    def run(self, graph: Graph | None = None, args: list[str] | None = None,
            vetted: bool = False) -> None:
        """Write the graph to ``-o`` or to stdout; exit 1 on a usage error."""
        args = list(args or [])

        try:
            fmt_name, args = pop_value(args, "--format")
            out_name, args = pop_value(args, "-o")
            if out_name is None:
                out_name, args = pop_value(args, "--output")
        except UsageError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if graph is None:
            print(
                "Error: emit needs a citations file — "
                "apysource emit sources.yaml [-o out.ttl] [--format turtle]",
                file=sys.stderr,
            )
            sys.exit(1)

        fmt = fmt_name or "turtle"

        if not len(graph):
            # The same rule the report follows: a run that produced nothing is
            # not a run that succeeded. An empty file written in silence is how
            # a broken generator goes unnoticed.
            print("Error: nothing to emit — this file holds no triples.",
                  file=sys.stderr)
            sys.exit(1)

        out = Path(out_name) if out_name else None

        try:
            body = serialize(graph, fmt)
        except UnknownFormat as e:
            # Named for the flag the user actually typed. The library cannot
            # know it was reached through `--format`.
            print(f"Error: unknown --format {e.name!r} (known: {e.known})",
                  file=sys.stderr)
            sys.exit(1)

        warning = identifier_warning(graph, str(out) if out else "")
        if warning:
            print(warning, file=sys.stderr)

        # Only Turtle can be committed and diffed. Saying so at the moment the
        # file is written is cheaper than a reviewer working out why a file
        # nobody edited shows a diff.
        if out and not is_stable(fmt):
            print(f"Note: {fmt} labels its blank nodes afresh each run, so this "
                  f"file will differ byte for byte between identical runs. "
                  f"Use turtle for anything you commit.", file=sys.stderr)
        if out:
            try:
                out.write_text(body, encoding="utf-8")
            except OSError as e:
                # A missing directory or an unwritable path is the user's typo,
                # and every other refusal in this command is one line and an exit.
                # This one sprayed a traceback.
                print(f"Error: could not write {out}: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"  {len(graph)} triples written to {out}", file=sys.stderr)
        else:
            print(body)
