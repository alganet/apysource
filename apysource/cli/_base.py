# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared CLI context — wired once in TOML, injected into all commands."""

from pathlib import Path


class UsageError(Exception):
    """A flag was given without the value it needs."""


def pop_flag(args: list[str], name: str) -> tuple[bool, list[str]]:
    """Return (present, args_without_flag) for a boolean flag like ``--refresh``."""
    if name in args:
        return True, [a for a in args if a != name]
    return False, args


def pop_value(args: list[str], name: str) -> tuple[str | None, list[str]]:
    """Return (value, args_without_flag) for a flag like ``--format json``.

    Raises UsageError when the flag is there and the value is not — a flag that
    silently does nothing is worse than one that refuses: the user believes the
    run was configured, and it was not.
    """
    if name not in args:
        return None, args

    idx = args.index(name)
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        raise UsageError(f"{name} requires a value")

    return args[idx + 1], args[:idx] + args[idx + 2:]


class CLIContext:
    """Resolved paths and shared state for all CLI commands."""

    def __init__(
        self,
        project_root: str,
        rdf_subdir: str,
        sources_cache_subdir: str,
    ):
        root = Path(project_root).resolve()
        self.project_root = root
        self.rdf_root = root / rdf_subdir
        self.sources_cache = root / sources_cache_subdir
