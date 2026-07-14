# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.repos registry and ArchiveRepo."""

import re

from apysource.repos import RepoRegistry
from apysource.repos.archive import ArchiveRepo


# ── Fake repo objects for registry tests ─────────────────────────────────

class _FakeRepo:
    def __init__(self, name, pattern):
        self.NAME = name
        self.url_pattern = re.compile(pattern)


_FAKE_REPOS = [
    _FakeRepo("archive", r"archive\.org/details/"),
    _FakeRepo("gutenberg", r"gutenberg\.org/"),
]


# ── RepoRegistry ─────────────────────────────────────────────────────────

def test_get_repo_known_url():
    """get_repo returns the correct module for an archive.org URL."""
    registry = RepoRegistry(_FAKE_REPOS)
    repo = registry.get_repo("https://archive.org/details/some_item")
    assert repo is not None
    assert repo.NAME == "archive"


def test_get_repo_unknown_url():
    """get_repo returns None for an unrecognized URL."""
    registry = RepoRegistry(_FAKE_REPOS)
    assert registry.get_repo("https://unknown-site.com/page") is None


def test_all_repos():
    """all_repos returns list of all registered modules."""
    registry = RepoRegistry(_FAKE_REPOS)
    repos = registry.all_repos()
    assert len(repos) == 2
    assert repos[0].NAME == "archive"
    assert repos[1].NAME == "gutenberg"


def test_registry_fills_crawl_delay_from_its_default(tmp_path):
    """A repo with no delay of its own inherits the shared one."""
    repo = _make_archive(tmp_path)
    assert repo.crawl_delay is None
    RepoRegistry([repo], default_crawl_delay=3.0)
    assert repo.crawl_delay == 3.0


def test_registry_leaves_an_explicit_repo_delay_alone(tmp_path):
    """A repo that set its own delay keeps it — that is the point of the knob.

    A CDN-backed repo asks to be read briskly; the shared default must not
    quietly overwrite that back to the polite gap an origin server needs.
    """
    repo = ArchiveRepo(
        cache_dir=tmp_path, crawl_delay=0.5,
        url_pattern=r"archive\.org/details/(.+?)(?:/|$|\?|#)",
        base_url="https://archive.org",
    )
    RepoRegistry([repo], default_crawl_delay=3.0)
    assert repo.crawl_delay == 0.5


# ── ArchiveRepo ──────────────────────────────────────────────────────────

def _make_archive(tmp_path):
    return ArchiveRepo(
        cache_dir=tmp_path,
        url_pattern=r"archive\.org/details/(.+?)(?:/|$|\?|#)",
        base_url="https://archive.org",
    )


def test_archive_url_to_key(tmp_path):
    """url_to_key extracts item_id from an Archive.org URL."""
    repo = _make_archive(tmp_path)
    key = repo.url_to_key("https://archive.org/details/TheEpicOfGilgamesh")
    assert key == "TheEpicOfGilgamesh"


def test_archive_url_to_key_none(tmp_path):
    """url_to_key returns None for a non-matching URL."""
    repo = _make_archive(tmp_path)
    assert repo.url_to_key("https://example.com/page") is None


def test_archive_resolve_location_cached(tmp_path):
    """resolve_location returns Path when cached file exists."""
    repo = _make_archive(tmp_path)
    item_dir = tmp_path / "myitem"
    item_dir.mkdir()
    (item_dir / "fulltext.txt").write_text("some text")

    result = repo.resolve_location("myitem", "myitem")
    assert result is not None
    assert result.exists()


def test_archive_resolve_location_not_cached(tmp_path):
    """resolve_location returns None when file does not exist."""
    repo = _make_archive(tmp_path)
    assert repo.resolve_location("myitem", "myitem") is None


def test_archive_extract_content_line_range(tmp_path):
    """extract_content extracts lines when location has lines: pattern."""
    repo = _make_archive(tmp_path)
    text_file = tmp_path / "test.txt"
    text_file.write_text("line1\nline2\nline3\nline4\nline5")

    result = repo.extract_content("lines:2-3", text_file)
    assert result == "line2\nline3"


def test_archive_extract_content_small_file(tmp_path):
    """extract_content returns full text for small files without line range."""
    repo = _make_archive(tmp_path)
    text_file = tmp_path / "test.txt"
    text_file.write_text("short content")

    result = repo.extract_content("some_item", text_file)
    assert result == "short content"
