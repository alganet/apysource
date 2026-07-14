# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.repos._base shared utilities and the repo contract."""

import pytest

from apysource.repos._base import (
    BaseRepo,
    RepoNotFound,
    RepoUnavailable,
    extract_line_range,
    extract_content_with_fallback,
    slugify,
)


class _ScriptedRepo(BaseRepo):
    """A repo whose crawl does whatever the test tells it to.

    Records every crawl so the tests can prove how many actually happened —
    the point of ``ensure`` is that twenty fragments citing one missing page
    make one request, not twenty.
    """

    NAME = "scripted"
    supports_crawl = True

    def __init__(self, tmp_path, raises=None, **kw):
        super().__init__(cache_dir=tmp_path, url_pattern=r"example\.com/(.+)",
                         base_url="https://example.com", **kw)
        self.raises = raises
        self.crawls: list[tuple[str, float | None, bool]] = []

    def url_to_key(self, url):
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def resolve_location(self, location, key):
        path = self.cache_dir / f"{key}.txt"
        return path if path.exists() else None

    def crawl(self, key, *, delay=None, force=False, from_cache=False):
        self.crawls.append((key, delay, force))
        if self.raises is not None:
            raise self.raises
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.txt").write_text("the document")


# ── The repo contract ────────────────────────────────────────────────────

def test_base_repo_does_not_crawl_by_default(tmp_path):
    """A repo that never opted in is not asked to fetch anything.

    Custom repos predate the crawl contract entirely; inheriting a False flag
    is what keeps them working unchanged.
    """
    repo = BaseRepo(cache_dir=tmp_path, url_pattern="x", base_url="https://x")
    assert repo.supports_crawl is False
    with pytest.raises(NotImplementedError):
        repo.crawl("anything")


def test_crawl_delay_defaults_to_none(tmp_path):
    """No delay set means "use the fetcher's default" — today's behavior exactly."""
    assert _ScriptedRepo(tmp_path).crawl_delay is None


def test_ensure_crawls_a_key_once_per_run(tmp_path):
    """A second fragment citing the same page must not re-fetch it."""
    repo = _ScriptedRepo(tmp_path)
    repo.ensure("doc")
    repo.ensure("doc")
    assert len(repo.crawls) == 1
    assert repo.crawl_outcome("doc").status == "ok"


def test_ensure_passes_the_repo_delay_to_crawl(tmp_path):
    """The per-repo politeness gap reaches the fetch, rather than decorating it."""
    repo = _ScriptedRepo(tmp_path, crawl_delay=0.5)
    repo.ensure("doc")
    assert repo.crawls == [("doc", 0.5, False)]


def test_ensure_replays_a_failure_without_refetching(tmp_path):
    """Twenty fragments, one missing page: one request, twenty identical failures."""
    repo = _ScriptedRepo(tmp_path, raises=RepoNotFound("scripted", "gone", "404"))

    for _ in range(3):
        with pytest.raises(RepoNotFound) as caught:
            repo.ensure("gone")
        assert caught.value.reason == "404"

    assert len(repo.crawls) == 1
    assert repo.crawl_outcome("gone").status == "not_found"


def test_ensure_replays_an_unavailable_as_unavailable(tmp_path):
    """A replayed failure keeps its kind. A timeout must not become a 404 on retry."""
    repo = _ScriptedRepo(tmp_path, raises=RepoUnavailable("scripted", "doc", "timeout"))
    for _ in range(2):
        with pytest.raises(RepoUnavailable):
            repo.ensure("doc")
    assert repo.crawl_outcome("doc").status == "unavailable"


def test_ensure_recrawls_when_forced(tmp_path):
    """--refresh must reach a repo, warm cache and memo notwithstanding."""
    repo = _ScriptedRepo(tmp_path)
    repo.ensure("doc")
    repo.ensure("doc", force=True)
    assert len(repo.crawls) == 2
    assert repo.crawls[-1][2] is True


def test_a_key_never_crawled_has_no_outcome(tmp_path):
    """A warm cache crawls nothing, and nothing is neither a pass nor a failure.

    Counting it "ok" would let a check report success for a document it never
    so much as looked at.
    """
    assert _ScriptedRepo(tmp_path).crawl_outcome("doc") is None


# ── extract_line_range ───────────────────────────────────────────────────

def test_extract_line_range_valid():
    """Extracts correct line range from text."""
    text = "line1\nline2\nline3\nline4\nline5"
    result = extract_line_range(text, "lines:2-4")
    assert result == "line2\nline3\nline4"


def test_extract_line_range_no_match():
    """Returns None when location has no lines: pattern."""
    text = "line1\nline2\nline3"
    assert extract_line_range(text, "chapter_one") is None


def test_extract_line_range_out_of_bounds():
    """Out-of-bounds range returns available lines without error."""
    text = "line1\nline2"
    result = extract_line_range(text, "lines:1-100")
    assert result == "line1\nline2"


# ── slugify ──────────────────────────────────────────────────────────────

def test_slugify_basic():
    """Basic slugification: lowercase + spaces to underscores."""
    assert slugify("Hello World") == "hello_world"


def test_slugify_empty():
    """Empty string returns empty string."""
    assert slugify("") == ""


# ── extract_content_with_fallback ────────────────────────────────────────

def test_extract_content_with_fallback_line_range():
    """Line range takes priority over small-file fallback."""
    text = "line1\nline2\nline3"
    result = extract_content_with_fallback(text, "lines:2-2")
    assert result == "line2"


def test_extract_content_with_fallback_small_file():
    """Small file without line range returns full text."""
    text = "short text"
    result = extract_content_with_fallback(text, "chapter_one", threshold=5000)
    assert result == "short text"


def test_extract_content_with_fallback_large_file_no_range():
    """Large file without line range returns empty string."""
    text = "x" * 6000
    result = extract_content_with_fallback(text, "chapter_one", threshold=5000)
    assert result == ""
