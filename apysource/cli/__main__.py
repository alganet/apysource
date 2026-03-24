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

    # Detect YAML input from remaining args (not for commands that take YAML as output)
    remaining = args[1:]
    graph = None
    if (name not in ("add", "locate") and
            remaining and remaining[0].endswith((".yaml", ".yml"))):
        from apysource.yaml_input import load_yaml
        graph = load_yaml(Path(remaining[0]))
        remaining = remaining[1:]

    cmd = getattr(wiring, COMMANDS[name])()
    if graph is not None and hasattr(cmd, "run"):
        cmd.run(graph=graph, args=remaining)
    else:
        cmd.run(args=remaining)


if __name__ == "__main__":
    main()
