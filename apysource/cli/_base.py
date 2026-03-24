# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared CLI context — wired once in TOML, injected into all commands."""

from pathlib import Path


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
