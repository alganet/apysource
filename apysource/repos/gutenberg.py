# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Project Gutenberg repository module.

Unified source + crawler for Project Gutenberg texts, with pluggable
repo-specific matchers (bible, classical).

Content files are named by gutenberg_id: {id}_chapters.json, {id}_ch001.txt.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from apysource.formats import html_text, normalize_ws
from apysource.repos._base import (
    BaseRepo,
    RepoNotFound,
    extract_line_range,
)

logger = logging.getLogger(__name__)


def _strip_chapter_header(text: str) -> str:
    """Drop the ``#``-prefixed provenance block a chapter file opens with.

    Stitching 143 of those into one document would put 143 "# Accessed:" lines
    through the middle of the book, between the very sentences a citation spans.
    """
    lines = text.splitlines()
    start = 0
    while start < len(lines) and lines[start].startswith("#"):
        start += 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:])


class GutenbergRepo(BaseRepo):
    """Unified source + crawler for Project Gutenberg texts.

    Matchers are pluggable modules for domain-specific location formats
    (e.g. Bible verse references, classical citation conventions).
    Pass matchers=[] for plain chapter-based extraction.
    """

    NAME = "gutenberg"
    supports_crawl = True

    # `\d+` and not `.+`: a Gutenberg book is an ebook number, and a name that is
    # not one names no book. The url_pattern says the same thing about the URL.
    NAME_MATCH = r"^Gutenberg (?P<id>\d+)$"
    CANONICAL_URL = "https://www.gutenberg.org/ebooks/{id}"
    NAME_EXAMPLE = "Gutenberg 2701"

    #: The assembled whole-book file. Distinct from ``{id}_ch001.txt`` so it can
    #: never be mistaken for a chapter, and named so a crawl can find and delete
    #: a stale one.
    WHOLE_SUFFIX = "_full.txt"

    def __init__(self, cache_dir=None, http_client=None, matchers=None,
                 url_pattern=None, base_url=None):
        super().__init__(cache_dir, http_client,
                         url_pattern=url_pattern, base_url=base_url)
        if matchers is None:
            from apysource.repos import gutenberg_bible, gutenberg_classical
            matchers = [gutenberg_bible, gutenberg_classical]
        self.matchers = matchers

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Extract Gutenberg ID from URL."""
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def _load_chapters(self, gutenberg_id: str) -> list[dict]:
        chapters_file = self.cache_dir / f"{gutenberg_id}_chapters.json"
        if not chapters_file.exists():
            return []
        return json.loads(chapters_file.read_text())

    def is_cached(self, key: str) -> bool:
        """Check if a Gutenberg text is cached."""
        return (self.cache_dir / f"{key}_chapters.json").exists()

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Map a sourceLocation to a chapter file — or, naming none, to the book."""
        chapters = self._load_chapters(key)
        if not chapters:
            return None

        # A citation that names no chapter has not asked for one, and what it
        # cited is the book. Everywhere else in apysource a fragment with no
        # targetter is matched against the whole document; a repo does not get
        # to invent targeting the citation did not ask for.
        #
        # This used to fall through to the title search below, where the test is
        # `location in title` — and the empty string is a substring of every
        # title on earth. So it silently resolved to *the first chapter*, which
        # for Moby-Dick is 247 characters of front matter, and apysource then
        # reported that the book does not contain "Call me Ishmael." It does, in
        # chapter 7. A wrong answer, in the tool's own confident voice, about a
        # document it had fetched in full and declined to read.
        if not location.strip():
            return self._whole_text(key, chapters)

        ch = None
        for matcher in self.matchers:
            ch = matcher.find_chapter(location, chapters)
            if ch:
                break

        if not ch:
            ch = self._find_chapter_by_number(location, chapters)

        if not ch:
            ch = self._find_chapter_by_title(location, chapters)

        if ch:
            path = self.cache_dir / ch["file"]
            return path if path.exists() else None
        return None

    @staticmethod
    def _find_chapter_by_title(location: str, chapters: list[dict]) -> dict | None:
        """The loose fallback: a location that reads like a chapter's title.

        Kept loose — a reader writing ``location: The Fox and the Grapes`` should
        not have to reproduce the heading exactly — but no longer *silently*
        loose. It matched the first candidate and moved on; with 143 chapters,
        several can answer to the same substring, and picking one of them without
        saying so is the same sin as picking the first one for an empty location.

        Two chapters that cannot be told apart are not something to guess
        between: nothing is returned, and the report says the location matched
        nothing rather than pretending it matched the right thing.
        """
        needle = location.lower().strip()
        if not needle:
            return None

        matches = [
            candidate for candidate in chapters
            if (title := candidate.get("title", "").lower())
            and (needle in title or title in needle)
        ]
        return matches[0] if len(matches) == 1 else None

    def _whole_text(self, key: str, chapters: list[dict]) -> Path | None:
        """The book, whole — assembled from the chapters already on disk.

        Built lazily from the cache rather than at crawl time, so a cache that
        already exists gets the fix without a re-crawl. A fix that only works on
        a cold cache is not a fix here: the caches that exist are precisely the
        ones that have been lying, and nobody re-crawls a book that verifies.

        An incomplete cache yields nothing at all, not most of the book. Half a
        book would let a quote from the missing half be reported as absent from
        the source — which is the failure this whole method exists to undo, moved
        one shelf along.
        """
        path = self.cache_dir / f"{key}{self.WHOLE_SUFFIX}"
        if path.exists():
            return path

        parts = []
        for ch in chapters:
            ch_path = self.cache_dir / ch["file"]
            if not ch_path.exists():
                logger.warning("[%s] chapter file %s is missing; refusing to "
                               "assemble a partial book", key, ch["file"])
                return None
            parts.append(_strip_chapter_header(
                ch_path.read_text(encoding="utf-8", errors="replace")))

        path.write_text("\n\n".join(parts), encoding="utf-8")
        return path

    @staticmethod
    def _find_chapter_by_number(location: str, chapters: list[dict]) -> dict | None:
        m = re.match(r"chapter:(\d+)", location, re.IGNORECASE)
        if not m:
            return None
        num = int(m.group(1))
        for ch in chapters:
            if ch.get("number") == num:
                return ch
        return None

    def extract_content(self, location: str, file_path: Path) -> str:
        """Extract content from a chapter file — or from the book, whole.

        **The located file is the answer.** ``resolve_location`` has already
        honoured the ``location:`` by choosing this file; there is nothing left
        here to narrow, and the only reason to look at ``location`` again is a
        ``lines:`` range, which narrows *within* a chapter.

        The tail of this used to be ``if len(text) < SMALL_FILE_THRESHOLD: return
        text`` and otherwise ``return ""``. So a chapter that had been located
        correctly, and read correctly, came back as **nothing at all** if it ran
        past five thousand characters — reported as "empty extraction (0 chars)"
        for a chapter that was not empty, just long. Every Gutenberg citation to
        a chapter of any real length failed that way, and said the source was
        empty while doing it.

        It survived because the one example in the repository is Aesop, whose
        fables are a page each. The threshold was never reached, so the branch
        past it was never taken, and the tests agreed with the code because they
        were written from the same book.
        """
        text = file_path.read_text(encoding="utf-8", errors="replace")

        for matcher in self.matchers:
            if hasattr(matcher, "extract_content"):
                result = matcher.extract_content(text, location)
                if result is not None:
                    return result

        lines = extract_line_range(text, location)
        return lines if lines is not None else text

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float | None = None,
              force: bool = False, from_cache: bool = False) -> dict | None:
        """Download, parse, and segment a Gutenberg text.

        Raises RepoNotFound when Gutenberg has no such ebook.
        """
        return self._process_text(key, force=force, from_cache=from_cache)

    def _slugify(self, title: str) -> str:
        """Generate a filesystem slug from a title."""
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        return slug[:50].rstrip("_")

    def _process_text(self, gutenberg_id: str,
                      force: bool = False, from_cache: bool = False) -> dict | None:
        """Download, parse, and segment a Gutenberg text."""
        chapters_file = self.cache_dir / f"{gutenberg_id}_chapters.json"

        if not force and not from_cache and chapters_file.exists():
            logger.info("[%s] cached — skipping", gutenberg_id)
            return None

        url = (f"{self.base_url}/cache/epub/"
               f"{gutenberg_id}/pg{gutenberg_id}-images.html")
        logger.info("[%s] fetching %s ...", gutenberg_id, url)

        html = self.fetch(url, gutenberg_id, force=force,
                          from_cache=from_cache, timeout=60)

        # Extract title from HTML
        title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else f"Gutenberg #{gutenberg_id}"

        chapters = self._extract_chapters(html)
        logger.info("[%s] extracted %d chapters", gutenberg_id, len(chapters))

        if not chapters:
            # Gutenberg answered, but nothing citable came out of it. Writing
            # an empty chapter index would cache this as a successful crawl and
            # leave every citation into it failing as an "empty extraction".
            raise RepoNotFound(self.NAME, gutenberg_id,
                               f"no chapters could be extracted from {url}")

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # A re-crawl rewrites every chapter. An assembled book from the *previous*
        # crawl would survive it and go on being served — the whole point of
        # --refresh being that the old text is not to be trusted. It is rebuilt
        # from the new chapters on next use.
        whole = self.cache_dir / f"{gutenberg_id}{self.WHOLE_SUFFIX}"
        whole.unlink(missing_ok=True)

        for i, ch in enumerate(chapters):
            ch_path = self.cache_dir / f"{gutenberg_id}_ch{i+1:03d}.txt"
            with open(ch_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n")
                f.write(f"# Chapter: {ch['title']}\n")
                f.write(f"# Source: {self.base_url}/ebooks/{gutenberg_id}\n")
                f.write(f"# Accessed: {datetime.now(timezone.utc).isoformat()}\n\n")
                f.write(ch["text"])

        ch_index = [
            {
                "number": i + 1,
                "title": ch["title"],
                "chars": len(ch["text"]),
                "file": f"{gutenberg_id}_ch{i+1:03d}.txt",
            }
            for i, ch in enumerate(chapters)
        ]
        chapters_file.write_text(
            json.dumps(ch_index, indent=2, ensure_ascii=False))

        total_chars = sum(len(ch["text"]) for ch in chapters)

        return {
            "gutenberg_id": gutenberg_id,
            "title": title,
            "chapter_count": len(chapters),
            "total_chars": total_chars,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_chapters(html: str) -> list[dict]:
        """Extract chapters from Gutenberg HTML."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        for div in soup.find_all("div", id=re.compile(r"pg-(header|footer)")):
            div.decompose()

        chapters = []
        current_title = "Preamble"
        current_parts = []

        # Rendered exactly as every other HTML in this codebase is rendered.
        # This used `get_text(strip=True)`, which joins stripped strings with
        # nothing: a paragraph with any inline markup came out as
        # "Call meIshmael." — and because a repo renders at *crawl* time, that
        # was written into the cache, so no quote from it could ever verify and
        # fixing the code alone would not free an existing cache of it.
        for element in soup.find_all(["h2", "h3", "h4", "p", "blockquote"]):
            if element.name in ("h2", "h3", "h4"):
                if current_parts:
                    text = "\n\n".join(current_parts)
                    if len(text.strip()) > 50:
                        chapters.append({"title": current_title, "text": text})
                current_title = normalize_ws(html_text(element))
                current_parts = []
            elif element.name in ("p", "blockquote"):
                text = normalize_ws(html_text(element))
                if text and len(text) > 10:
                    current_parts.append(text)

        if current_parts:
            text = "\n\n".join(current_parts)
            if len(text.strip()) > 50:
                chapters.append({"title": current_title, "text": text})

        return chapters
