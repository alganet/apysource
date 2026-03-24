# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Structured result types for resolution and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apysource.http import CachedFetcher
    from apysource.repos._base import BaseRepo


# ── Resolution results ──────────────────────────────────────────────────

@dataclass
class ResolveResult:
    """Base result — covers error cases (no_source, no_url, no_module, no_file)."""

    status: str
    label: str = ""
    url: str = ""
    source: str = ""


@dataclass
class RepoResult(ResolveResult):
    """Resolved via a repository module."""

    location: str = ""
    module: str = ""
    repo: BaseRepo | None = None
    cache_file: str | None = None


@dataclass
class FetcherResult(ResolveResult):
    """Resolved via HTTP fetcher (no repo needed)."""

    location: str = ""
    module: str = "http"
    fetcher: CachedFetcher | None = None
    format_name: str = ""
    locator: str | None = None


# ── Verification results ────────────────────────────────────────────────

@dataclass
class Failure:
    """A single verification failure."""

    group: str
    item: str
    reason: str


@dataclass
class CheckResult:
    """Result of a verification check."""

    name: str
    ok: int
    total: int
    failures: list[Failure] = field(default_factory=list)
