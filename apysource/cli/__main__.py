# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Unified CLI entry point.

Usage: apysource [-c config.toml] <command> [args...]
"""

import sys
from pathlib import Path

COMMANDS = {
    "check": "check_sources_cmd",
    "check-sources": "check_sources_cmd",
    "validate": "validate_cmd",
    "locate": "locate_cmd",
    "add": "add_cmd",
    "emit": "emit_cmd",
}


def main() -> None:
    args = sys.argv[1:]
    config_path = None

    # Extract -c / --config before command name
    if len(args) >= 2 and args[0] in ("-c", "--config"):
        config_path = args[1]
        args = args[2:]

    if not args or args[0] in ("-h", "--help"):
        print("Usage: apysource [-c <config.toml>] <command> [args...]")
        print(f"\nCommands: {', '.join(sorted(set(COMMANDS) - {'check-sources'}))}")
        print("\nRun 'apysource check sources.yaml' to verify sources.")
        sys.exit(0)

    name = args[0]
    if name not in COMMANDS:
        print(f"Unknown command: {name}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(set(COMMANDS) - {'check-sources'}))}", file=sys.stderr)
        sys.exit(1)

    # Load wiring: explicit config or compiled defaults
    if config_path:
        from apysource.config import get_wiring
        wiring = get_wiring(config_path)
    else:
        from apysource._defaults import compiled as wiring

    cmd = getattr(wiring, COMMANDS[name])()

    # A command opts in to graph input by setting `accepts_graph = True`. Such a
    # command may take a citations file as a positional argument (in any
    # position, e.g. after a flag like `--refresh`); we load it and pass it
    # through as `graph`. Commands that take a URL/snippet (or no) positional
    # argument simply don't opt in.
    #
    # Both front-ends are accepted here, and that is the point: a `.ttl` used to
    # match nothing, so `apysource check citations.ttl` quietly ignored the file
    # it was pointed at, scanned the configured RDF root instead, and passed the
    # filename on as an unrecognised positional. The two ways of writing the same
    # citations are interchangeable at the boundary or they are not really two
    # ways of writing the same thing.
    remaining = args[1:]
    graph = None
    # Whether the graph arrived through a loader that vetted it. YAML has one and
    # Turtle does not, and a caller downstream has no way to tell by looking: the
    # graph is triples either way. It decides whether the shapes still have work
    # to do, so it is carried rather than guessed at.
    vetted = False
    if getattr(cmd, "accepts_graph", False):
        # The value of a flag is not a positional, however much it looks like one.
        #
        # This scan matches on suffix, and once `.ttl` was added to that list the
        # *values* of `-o`, `--provenance` and `--format` became eligible. With
        # the flag written first — `emit -o out.ttl sources.yaml` — `out.ttl` was
        # taken as the input graph and removed from the arguments, leaving
        # `["-o", "sources.yaml"]`, so the command wrote the graph **over the
        # user's citations file** and exited 0. `check --provenance p.ttl
        # sources.yaml` did the same, checking the wrong file first.
        #
        # A command therefore says which of its flags take a value, and those
        # values are stepped over. Skipping every argument after any `-` would be
        # wrong in the other direction: `--refresh` is a boolean, and the file
        # after it is a real positional.
        value_flags = set(getattr(cmd, "value_flags", ()))
        skip_value = False
        for i, arg in enumerate(remaining):
            if skip_value:
                skip_value = False
                continue
            if arg in value_flags:
                skip_value = True
                continue
            if arg.endswith((".yaml", ".yml", ".ttl")):
                try:
                    if arg.endswith(".ttl"):
                        from apysource.graph import load_turtle
                        graph = load_turtle(Path(arg))
                    else:
                        from apysource.yaml_input import load_yaml
                        graph = load_yaml(Path(arg))
                        vetted = True
                except (ValueError, SyntaxError, OSError) as e:
                    # A malformed citations file is the author's mistake, not a
                    # crash. Say what is wrong with it, in one line they can act
                    # on, and stop — rather than spraying a traceback. Turtle
                    # syntax errors arrive from rdflib's parser, so they are
                    # caught here too rather than only YAML's ValueError.
                    print(f"Error in {arg}: {e}", file=sys.stderr)
                    sys.exit(1)
                remaining = remaining[:i] + remaining[i + 1:]
                break

    if graph is not None:
        cmd.run(graph=graph, args=remaining, vetted=vetted)
    else:
        cmd.run(args=remaining)


if __name__ == "__main__":
    main()
