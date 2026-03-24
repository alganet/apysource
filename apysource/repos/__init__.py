# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Repository registry and base class — no global state, explicit construction only."""

from __future__ import annotations

from pathlib import Path

from apysource.repos._base import (  # noqa: F401 — public re-exports
    SMALL_FILE_THRESHOLD,
    BaseRepo,
    extract_content_with_fallback,
    extract_line_range,
    slugify,
)


class RepoRegistry:
    """Registry of repo instances. Constructed explicitly, injected everywhere.

    Repos that don't set cache_dir or http_client get them from the registry:
    cache_dir defaults to sources_cache_dir / repo.NAME, http_client is shared.
    """

    def __init__(self, repos: list[BaseRepo], sources_cache_dir: str | Path | None = None,
                 http_client: object | None = None) -> None:
        self.repos = repos
        for repo in repos:
            if getattr(repo, "cache_dir", None) is None and sources_cache_dir:
                repo.cache_dir = Path(sources_cache_dir) / repo.NAME
            if getattr(repo, "http_client", None) is None and http_client:
                repo.http_client = http_client

    def get_repo(self, url: str) -> BaseRepo | None:
        """Find the repo that handles a given URL."""
        for repo in self.repos:
            pattern = getattr(repo, "url_pattern", None)
            if pattern and pattern.search(url):
                return repo
        return None

    def all_repos(self) -> list[BaseRepo]:
        """Return all registered repos."""
        return list(self.repos)
