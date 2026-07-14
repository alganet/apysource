# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Typed failures a repository can report.

A repo used to have no way to say "this document does not exist here". The
one that tried cached an empty file on a 404, so a page that had been moved
surfaced later as ``empty extraction (0 chars)`` — loud, but blamed on the
citation rather than on the missing page, and stuck that way until the next
``--refresh``.

The distinction these two errors draw is the whole point of them, and it is
not a shade of meaning: a 404 is knowledge, a timeout is the absence of it.
Reporting "no such page" because the network was down would be a confident
wrong answer about the source, which is the one thing this tool must never
give.
"""


class RepoError(Exception):
    """Base for repository failures. Carries the repo, the key, and why."""

    def __init__(self, repo: str, key: str, reason: str = "") -> None:
        self.repo = repo
        self.key = key
        self.reason = reason
        super().__init__(self.message)

    @property
    def message(self) -> str:
        """Report-ready phrasing, attributed to the repo that failed."""
        detail = f": {self.reason}" if self.reason else ""
        return f"{self.repo}: {self.key}{detail}"


class RepoNotFound(RepoError):
    """The repository authoritatively has no such document.

    Raise this *only* on an authoritative absence — an HTTP 404 or 410, an
    API payload that says the item does not exist. A timeout, a 5xx or a 429
    is not an absence; it is an unknown, and it must raise RepoUnavailable.

    Nothing may be written to the cache before or after this is raised. A
    cached "missing" is a false failure that outlives the thing that caused
    it: the page comes back upstream and the check stays red until someone
    thinks to pass --refresh.
    """

    @property
    def message(self) -> str:
        detail = f" ({self.reason})" if self.reason else ""
        return f"{self.repo}: no such document: {self.key}{detail}"


class RepoUnavailable(RepoError):
    """The document could not be fetched. Whether it exists is unknown."""

    @property
    def message(self) -> str:
        detail = f": {self.reason}" if self.reason else ""
        return f"{self.repo}: could not fetch {self.key}{detail}"
