# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the concrete repository modules (archive, gutenberg, wikisource,
wiktionary) and the Gutenberg matchers. Network access is mocked via
``tests.conftest.MockFetcher``."""

import json

import pytest

from apysource.repos import gutenberg_bible, gutenberg_classical
from apysource.repos._base import RepoNotFound, RepoUnavailable
from apysource.repos.archive import ArchiveRepo
from apysource.repos.gutenberg import GutenbergRepo
from apysource.repos.wikisource import WikisourceRepo
from apysource.repos.wiktionary import WiktionaryRepo

from tests.conftest import MockFetcher


# ── ArchiveRepo crawler ────────────────────────────────────────────────────

def _archive(tmp_path, fetcher=None):
    return ArchiveRepo(
        cache_dir=tmp_path, http_client=fetcher,
        url_pattern=r"archive\.org/details/(.+?)(?:/|$|\?|#)",
        base_url="https://archive.org",
    )


def test_archive_find_text_file_priority(tmp_path):
    repo = _archive(tmp_path)
    meta = {
        "metadata": {"identifier": "item1"},
        "files": [
            {"name": "scan.txt", "format": "Text"},
            {"name": "book_djvu.txt", "format": "DjVuTXT"},
            {"name": "full.txt", "format": "Full Text"},
        ],
    }
    # DjVu wins (priority 0).
    url = repo._find_text_file(meta)
    assert url == "https://archive.org/download/item1/book_djvu.txt"


def test_archive_find_text_file_none(tmp_path):
    repo = _archive(tmp_path)
    meta = {"metadata": {"identifier": "x"}, "files": [{"name": "cover.jpg"}]}
    assert repo._find_text_file(meta) is None


def test_archive_get_metadata_invalid_json(tmp_path):
    repo = _archive(tmp_path, MockFetcher("not json"))
    assert repo._get_metadata("item1") is None


def test_archive_process_item_success(tmp_path):
    meta = json.dumps({
        "metadata": {"identifier": "item1", "title": "A Book", "creator": "Anon"},
        "files": [{"name": "book_djvu.txt", "format": "DjVuTXT"}],
    })
    fetcher = MockFetcher(routes={"/metadata/": meta, "/download/": "the full text"})
    repo = _archive(tmp_path, fetcher)

    result = repo.crawl("item1")
    assert result["status"] == "ok"
    assert result["title"] == "A Book"
    assert result["text_chars"] == len("the full text")
    # Cached to disk for resolve_location.
    assert (tmp_path / "item1" / "fulltext.txt").read_text() == "the full text"


def test_archive_crawl_raises_not_found_for_an_item_that_is_not_there(tmp_path):
    """A 404 from archive.org means archive.org has no such item. Say that."""
    fetcher = MockFetcher(routes={"/metadata/": None})
    repo = _archive(tmp_path, fetcher)
    with pytest.raises(RepoNotFound):
        repo.crawl("item1")


def test_archive_crawl_raises_unavailable_when_the_server_is_down(tmp_path):
    """A 503 is not an absence, and must not be reported as one."""
    fetcher = MockFetcher(routes={"/metadata/": None},
                          statuses={"/metadata/": 503})
    repo = _archive(tmp_path, fetcher)
    with pytest.raises(RepoUnavailable):
        repo.crawl("item1")


def test_archive_crawl_raises_unavailable_when_unreachable(tmp_path):
    """No response at all means no claim at all about whether the item exists."""
    fetcher = MockFetcher(routes={"/metadata/": None},
                          statuses={"/metadata/": None})
    repo = _archive(tmp_path, fetcher)
    with pytest.raises(RepoUnavailable):
        repo.crawl("item1")


def test_archive_process_item_invalid_json(tmp_path):
    """Garbage back from the API says nothing about whether the item exists."""
    fetcher = MockFetcher(routes={"/metadata/": "{bad json"})
    repo = _archive(tmp_path, fetcher)
    with pytest.raises(RepoUnavailable):
        repo.crawl("item1")


def test_archive_crawl_raises_not_found_when_the_item_holds_no_text(tmp_path):
    """A real item with nothing citable in it is still nothing to cite."""
    meta = json.dumps({
        "metadata": {"identifier": "item1", "title": "A Painting"},
        "files": [{"name": "scan.jpg", "format": "JPEG"}],
    })
    repo = _archive(tmp_path, MockFetcher(routes={"/metadata/": meta}))
    with pytest.raises(RepoNotFound):
        repo.crawl("item1")


def test_archive_crawl_leaves_nothing_behind_when_the_item_is_missing(tmp_path):
    """No 0-byte sentinel. A page that returns later must need no --refresh."""
    repo = _archive(tmp_path, MockFetcher(routes={"/metadata/": None}))
    with pytest.raises(RepoNotFound):
        repo.crawl("item1")
    assert list(tmp_path.rglob("*.txt")) == []


def test_archive_crawl_passes_the_repo_delay_to_the_fetcher(tmp_path):
    """A per-repo delay that never reaches the fetch is decoration."""
    meta = json.dumps({
        "metadata": {"identifier": "item1", "title": "A Book"},
        "files": [{"name": "b_djvu.txt", "format": "DjVuTXT"}],
    })
    fetcher = MockFetcher(routes={"/metadata/": meta, "/download/": "text"})
    repo = ArchiveRepo(
        cache_dir=tmp_path, http_client=fetcher, crawl_delay=0.5,
        url_pattern=r"archive\.org/details/(.+?)(?:/|$|\?|#)",
        base_url="https://archive.org",
    )
    repo.crawl("item1")
    assert all(kw.get("delay") == 0.5 for _url, kw in fetcher.requests)


def test_archive_crawl_uses_cache(tmp_path):
    (tmp_path / "item1").mkdir()
    (tmp_path / "item1" / "fulltext.txt").write_text("cached body")
    repo = _archive(tmp_path, MockFetcher())  # fetcher must not be needed
    result = repo.crawl("item1")
    assert result["status"] == "ok"
    assert result["text_chars"] == len("cached body")


# ── GutenbergRepo ──────────────────────────────────────────────────────────

def _gutenberg(tmp_path, fetcher=None, matchers=None):
    return GutenbergRepo(
        cache_dir=tmp_path, http_client=fetcher, matchers=matchers,
        url_pattern=r"gutenberg\.org/ebooks/(\d+)",
        base_url="https://www.gutenberg.org",
    )


def test_gutenberg_url_to_key(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    assert repo.url_to_key("https://www.gutenberg.org/ebooks/1342") == "1342"
    assert repo.url_to_key("https://example.com/x") is None


def test_gutenberg_is_cached(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    assert repo.is_cached("1342") is False
    (tmp_path / "1342_chapters.json").write_text("[]")
    assert repo.is_cached("1342") is True


def test_gutenberg_resolve_location_by_chapter_number(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    (tmp_path / "1_chapters.json").write_text(json.dumps([
        {"number": 1, "title": "Chapter One", "file": "1_ch001.txt"},
        {"number": 2, "title": "Chapter Two", "file": "1_ch002.txt"},
    ]))
    (tmp_path / "1_ch002.txt").write_text("second chapter body")
    path = repo.resolve_location("chapter:2", "1")
    assert path is not None
    assert path.name == "1_ch002.txt"


def test_gutenberg_resolve_location_by_title(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    (tmp_path / "1_chapters.json").write_text(json.dumps([
        {"number": 1, "title": "The Prologue", "file": "1_ch001.txt"},
    ]))
    (tmp_path / "1_ch001.txt").write_text("prologue body")
    path = repo.resolve_location("prologue", "1")
    assert path is not None and path.name == "1_ch001.txt"


def test_gutenberg_resolve_location_not_cached(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    assert repo.resolve_location("chapter:1", "999") is None


def test_gutenberg_find_chapter_by_number_no_match():
    assert GutenbergRepo._find_chapter_by_number("not a chapter ref", []) is None


def test_gutenberg_extract_content_line_range(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    f = tmp_path / "c.txt"
    f.write_text("a\nb\nc\nd")
    assert repo.extract_content("lines:2-3", f) == "b\nc"


def test_gutenberg_slugify(tmp_path):
    repo = _gutenberg(tmp_path, matchers=[])
    assert repo._slugify("Pride & Prejudice!") == "pride_prejudice"


def test_gutenberg_extract_chapters_from_html():
    html = """
    <html><body>
      <div id="pg-header">boilerplate</div>
      <h2>Chapter I</h2>
      <p>It is a truth universally acknowledged that this paragraph is long enough.</p>
      <h2>Chapter II</h2>
      <p>However little known the feelings of a man, this is also a long paragraph.</p>
      <div id="pg-footer">license</div>
    </body></html>
    """
    chapters = GutenbergRepo._extract_chapters(html)
    titles = [c["title"] for c in chapters]
    assert "Chapter I" in titles and "Chapter II" in titles
    assert all("boilerplate" not in c["text"] for c in chapters)


def test_gutenberg_process_text_crawls_and_segments(tmp_path):
    html = ("<html><head><title>My Book</title></head><body>"
            "<h2>Chapter I</h2><p>" + "word " * 30 + "</p>"
            "<h2>Chapter II</h2><p>" + "more " * 30 + "</p></body></html>")
    repo = _gutenberg(tmp_path, MockFetcher(html), matchers=[])
    result = repo.crawl("42")
    assert result is not None
    assert result["title"] == "My Book"
    assert result["chapter_count"] == 2
    assert (tmp_path / "42_chapters.json").exists()


# ── Gutenberg matchers ─────────────────────────────────────────────────────

def test_bible_matcher_finds_book():
    chapters = [{"title": "The Book of Genesis", "file": "g.txt"}]
    assert gutenberg_bible.find_chapter("Gen 3:1-6", chapters)["file"] == "g.txt"


def test_bible_matcher_unknown_abbrev():
    assert gutenberg_bible.find_chapter("Zzz 1:1", [{"title": "Genesis"}]) is None


def test_bible_extract_verses():
    text = "3:1 In the beginning\n3:2 of verses\n4:1 next chapter"
    out = gutenberg_bible.extract_content(text, "Gen 3:1-2")
    assert "3:1 In the beginning" in out
    assert "4:1 next chapter" not in out


def test_bible_extract_not_a_verse_ref():
    assert gutenberg_bible.extract_content("text", "chapter:1") is None


def test_classical_matcher_roman_book():
    chapters = [{"title": "Book VI", "file": "aen6.txt"}]
    assert gutenberg_classical.find_chapter("Aen. VI", chapters)["file"] == "aen6.txt"


def test_classical_matcher_no_match():
    assert gutenberg_classical.find_chapter("Chapter 1", []) is None


# ── WikisourceRepo ─────────────────────────────────────────────────────────

def _wikisource(tmp_path, fetcher=None):
    return WikisourceRepo(
        cache_dir=tmp_path, http_client=fetcher,
        url_pattern=r"wikisource\.org/wiki/(.+?)(?:\?|#|$)",
        base_url="https://en.wikisource.org",
    )


def test_wikisource_url_to_key_decodes(tmp_path):
    repo = _wikisource(tmp_path)
    key = repo.url_to_key("https://en.wikisource.org/wiki/On_Liberty")
    assert key == "On_Liberty"


def test_wikisource_is_cached(tmp_path):
    repo = _wikisource(tmp_path)
    assert repo.is_cached("On Liberty") is False
    work = tmp_path / "on_liberty"
    work.mkdir()
    (work / "main.txt").write_text("body")
    assert repo.is_cached("On Liberty") is True


def test_wikisource_resolve_location_section(tmp_path):
    repo = _wikisource(tmp_path)
    work = tmp_path / "on_liberty"
    work.mkdir()
    (work / "main.txt").write_text("main")
    (work / "Chapter_1.txt").write_text("chapter one")
    path = repo.resolve_location("section:Chapter_1", "On Liberty")
    assert path is not None and path.name == "Chapter_1.txt"


def test_wikisource_resolve_location_main_fallback(tmp_path):
    repo = _wikisource(tmp_path)
    work = tmp_path / "on_liberty"
    work.mkdir()
    (work / "main.txt").write_text("main body")
    path = repo.resolve_location("unmatched-location", "On Liberty")
    assert path is not None and path.name == "main.txt"


def test_wikisource_get_page_text_parses_api_json(tmp_path):
    payload = json.dumps({"parse": {"text": {"*": "<p>Rendered body</p>"}}})
    repo = _wikisource(tmp_path, MockFetcher(payload))
    text = repo._get_page_text("On Liberty")
    assert "Rendered body" in text


def test_wikisource_get_page_text_invalid_json(tmp_path):
    """Unparseable API output is an unknown, not a missing page."""
    repo = _wikisource(tmp_path, MockFetcher("nope"))
    with pytest.raises(RepoUnavailable):
        repo._get_page_text("X")


def test_wikisource_crawl_raises_not_found_for_a_missing_page(tmp_path):
    payload = json.dumps({"error": {"info": "missing title"}})
    repo = _wikisource(tmp_path, MockFetcher(payload))
    with pytest.raises(RepoNotFound):
        repo.crawl("No Such Work")
    # And it leaves no directory behind to be mistaken for a crawl that worked.
    assert list(tmp_path.iterdir()) == []


def test_wikisource_get_subpages(tmp_path):
    payload = json.dumps({"query": {"allpages": [
        {"title": "On Liberty/Chapter 1"},
        {"title": "On Liberty/Chapter 2"},
    ]}})
    repo = _wikisource(tmp_path, MockFetcher(payload))
    subs = repo._get_subpages("On Liberty")
    assert subs == ["On Liberty/Chapter 1", "On Liberty/Chapter 2"]


def test_wikisource_process_page_crawls_main_and_subpages(tmp_path):
    parse_json = json.dumps({"parse": {"text": {"*": "<p>Main and subpage body</p>"}}})
    subpages_json = json.dumps({"query": {"allpages": [
        {"title": "On Liberty/Chapter 1"},
    ]}})
    fetcher = MockFetcher(routes={
        "list=allpages": subpages_json,
        "action=parse": parse_json,
    })
    repo = _wikisource(tmp_path, fetcher)

    result = repo.crawl("On Liberty")
    assert result["slug"] == "on_liberty"
    assert result["subpages"] == 1
    work = tmp_path / "on_liberty"
    assert (work / "main.txt").exists()
    assert (work / "Chapter_1.txt").exists()


def test_wikisource_process_page_uses_cache(tmp_path):
    work = tmp_path / "on_liberty"
    work.mkdir()
    (work / "main.txt").write_text("cached main")
    repo = _wikisource(tmp_path, MockFetcher())
    result = repo.crawl("On Liberty")
    assert result["total_chars"] == len("cached main")


# ── WiktionaryRepo ─────────────────────────────────────────────────────────

def _wiktionary(tmp_path, fetcher=None):
    return WiktionaryRepo(
        cache_dir=tmp_path, http_client=fetcher,
        url_pattern=r"wiktionary\.org/wiki/(.+)",
        base_url="https://en.wiktionary.org",
    )


def test_wiktionary_url_to_key(tmp_path):
    repo = _wiktionary(tmp_path)
    assert repo.url_to_key("https://en.wiktionary.org/wiki/deva") == "deva"


def test_wiktionary_resolve_location(tmp_path):
    repo = _wiktionary(tmp_path)
    (tmp_path / "deva.txt").write_text("etymology")
    assert repo.resolve_location("", "deva") is not None
    assert repo.resolve_location("missing", "missing") is None


def test_wiktionary_extract_content_language_section(tmp_path):
    repo = _wiktionary(tmp_path)
    f = tmp_path / "deva.txt"
    f.write_text(
        "# Wiktionary: deva\n\n"
        "## Sanskrit/Etymology\n\nFrom Proto-Indo-European.\n\n"
        "### Raw wikitext\n\n{{inh|sa|...}}\n\n"
        "## Latin/Etymology\n\nUnrelated.\n"
    )
    out = repo.extract_content("Sanskrit/Etymology", f)
    assert "Proto-Indo-European" in out
    assert "Unrelated" not in out


def test_wiktionary_parse_language_sections():
    wikitext = (
        "==English==\n"
        "===Etymology===\n"
        "From Old English.\n"
        "===Noun===\n"
        "a word\n"
        "==Latin==\n"
        "===Etymology===\n"
        "From Proto-Italic.\n"
    )
    result = WiktionaryRepo._parse_language_sections(wikitext)
    assert "English" in result and "Latin" in result
    eng_sections = dict(result["English"])
    assert "Old English" in eng_sections["Etymology"]


def test_wiktionary_parse_templates():
    templates = WiktionaryRepo._parse_wikitext_templates(
        "{{inh|en|enm|word|a gloss}} and {{root|en|ine-pro|*bʰer-}}"
    )
    types = {t["type"] for t in templates}
    assert "inh" in types and "root" in types


def test_wiktionary_clean_wikitext():
    cleaned = WiktionaryRepo._clean_wikitext(
        "From [[Latin|the Latin]] ''deus'' {{m|la|deus|a god}}."
    )
    assert "[[" not in cleaned and "{{" not in cleaned
    assert "the Latin" in cleaned


def test_wiktionary_fetch_term_success(tmp_path):
    payload = json.dumps({"parse": {"wikitext": {"*":
        "==English==\n===Etymology===\nFrom {{inh|en|enm|word}}.\n"}}})
    repo = _wiktionary(tmp_path, MockFetcher(payload))
    result = repo.crawl("word")
    assert result is not None
    assert result["term"] == "word"
    assert "English" in result["languages"]
    assert (tmp_path / "word.txt").exists()


def test_wiktionary_fetch_term_not_found(tmp_path):
    """It used to return None — the same answer it gave for "already cached".

    Two opposite outcomes, one indistinguishable value. Now it says which.
    """
    payload = json.dumps({"error": {"info": "missing title"}})
    repo = _wiktionary(tmp_path, MockFetcher(payload))
    with pytest.raises(RepoNotFound) as caught:
        repo.crawl("nonexistentword")
    assert caught.value.reason == "missing title"


def test_wiktionary_crawl_writes_nothing_when_the_word_is_absent(tmp_path):
    payload = json.dumps({"error": {"info": "missing title"}})
    repo = _wiktionary(tmp_path, MockFetcher(payload))
    with pytest.raises(RepoNotFound):
        repo.crawl("nonexistentword")
    assert list(tmp_path.rglob("*.txt")) == []
