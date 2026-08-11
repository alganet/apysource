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
from apysource.results import Supersession


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


# ── The supersession contract ────────────────────────────────────────────

class _CurrencyRepo(_ScriptedRepo):
    """A repo that tracks whether its documents are still in force."""

    supports_supersession = True

    def __init__(self, tmp_path, answer=None, raises=None, **kw):
        super().__init__(tmp_path, **kw)
        self.answer = answer
        self.asks: list[str] = []
        self.from_cache_asks: list[bool] = []
        self.supersession_raises = raises

    def supersession(self, key, *, from_cache=False):
        self.asks.append(key)
        self.from_cache_asks.append(from_cache)
        if self.supersession_raises is not None:
            raise self.supersession_raises
        return self.answer or Supersession(self.NAME, key, "current")


def test_a_repo_does_not_track_supersession_by_default(tmp_path):
    """Most publishers say nothing about it, and silence must stay available.

    A repo of a wiki is not failing to answer — there is no answer to be had,
    and a report claiming otherwise for every page would be noise.
    """
    repo = BaseRepo(cache_dir=tmp_path, url_pattern="x", base_url="https://x")
    assert repo.supports_supersession is False
    with pytest.raises(NotImplementedError):
        repo.supersession("anything")


def test_a_repo_that_does_not_track_it_is_never_asked(tmp_path):
    """`ensure_supersession` on an ordinary repo is a no-op, not a crash.

    Every repo-backed document goes through this call, so a repo that never
    opted in has to pass through it untouched.
    """
    repo = _ScriptedRepo(tmp_path)
    repo.ensure_supersession("doc")
    assert repo.supersession_outcome("doc") is None


def test_supersession_is_asked_once_per_run(tmp_path):
    """Fifty fragments of one document ask the registry once."""
    repo = _CurrencyRepo(tmp_path)
    repo.ensure_supersession("doc")
    repo.ensure_supersession("doc")

    assert repo.asks == ["doc"]
    assert repo.supersession_outcome("doc").status == "current"


def test_supersession_is_asked_again_when_forced(tmp_path):
    """--refresh is the flag whose whole job is to distrust a cached answer.

    It matters more here than for a document: an RFC never changes once
    published, but whether it is the one in force changes without warning.
    """
    repo = _CurrencyRepo(tmp_path)
    repo.ensure_supersession("doc")
    repo.ensure_supersession("doc", force=True)
    assert repo.asks == ["doc", "doc"]


def test_a_failed_lookup_is_recorded_as_unknown_and_never_raised(tmp_path):
    """The citation is not at fault for an outage at the index.

    Letting this propagate would fail an extraction that had already
    succeeded — the document was read, the quote was found, and then a
    question *about* the document brought the whole thing down.
    """
    repo = _CurrencyRepo(
        tmp_path, raises=RepoUnavailable("scripted", "doc", "timeout"))
    repo.ensure_supersession("doc")

    outcome = repo.supersession_outcome("doc")
    assert outcome.status == "unknown"
    assert outcome.reason == "timeout"


def test_a_lookup_that_breaks_in_an_unforeseen_way_is_still_unknown(tmp_path):
    """Not every failure arrives as a RepoError.

    A malformed payload reaches this as a TypeError from somewhere inside a
    parser, and it means exactly what a timeout means: the question is open.
    """
    repo = _CurrencyRepo(tmp_path, raises=TypeError("not subscriptable"))
    repo.ensure_supersession("doc")

    assert repo.supersession_outcome("doc").status == "unknown"
    assert "not subscriptable" in repo.supersession_outcome("doc").reason


def test_a_cache_only_lookup_still_reports_what_is_on_disk(tmp_path):
    """`--no-crawl` reads the answer; it does not pretend there isn't one.

    The document itself is served from disk on such a run, so declining to
    look at a supersession answer already sitting there would make this the
    one thing that goes quiet about something it knows.
    """
    repo = _CurrencyRepo(
        tmp_path, answer=Supersession("scripted", "doc", "superseded", ["x"]))
    repo.ensure_supersession("doc", from_cache=True)

    assert repo.from_cache_asks == [True]
    assert repo.supersession_outcome("doc").status == "superseded"


def test_a_cache_only_miss_records_nothing_rather_than_unknown(tmp_path):
    """A question declined is not a question that could not be answered.

    `unknown` means "asked, and could not tell". Recording it here would
    report a failure to do the very thing the caller forbade — and would put
    a row of caveats on every document of an offline run.
    """
    repo = _CurrencyRepo(
        tmp_path, raises=RepoUnavailable("scripted", "doc", "not cached"))
    repo.ensure_supersession("doc", from_cache=True)

    assert repo.supersession_outcome("doc") is None


def test_a_key_never_asked_has_no_supersession_outcome(tmp_path):
    """None means the question was never put, not that the answer was good."""
    assert _CurrencyRepo(tmp_path).supersession_outcome("doc") is None


def test_a_document_withdrawn_with_no_successor_is_still_superseded(tmp_path):
    """An empty successor list is a state, not a missing value.

    A statute can be revoked with nothing put in its place. Requiring a
    successor would model the IETF's habits rather than the relation.
    """
    repo = _CurrencyRepo(
        tmp_path, answer=Supersession("scripted", "doc", "superseded"))
    repo.ensure_supersession("doc")

    outcome = repo.supersession_outcome("doc")
    assert outcome.status == "superseded"
    assert outcome.superseded_by == []


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
