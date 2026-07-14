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

from apysource.repos._base import (
    BaseRepo,
    RepoNotFound,
    SMALL_FILE_THRESHOLD,
    extract_line_range,
)

logger = logging.getLogger(__name__)


class GutenbergRepo(BaseRepo):
    """Unified source + crawler for Project Gutenberg texts.

    Matchers are pluggable modules for domain-specific location formats
    (e.g. Bible verse references, classical citation conventions).
    Pass matchers=[] for plain chapter-based extraction.
    """

    NAME = "gutenberg"
    supports_crawl = True

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
        """Map a sourceLocation to a chapter file."""
        chapters = self._load_chapters(key)
        if not chapters:
            return None

        ch = None
        for matcher in self.matchers:
            ch = matcher.find_chapter(location, chapters)
            if ch:
                break

        if not ch:
            ch = self._find_chapter_by_number(location, chapters)

        if not ch:
            loc_lower = location.lower().strip()
            for candidate in chapters:
                title = candidate.get("title", "").lower()
                if loc_lower in title or title in loc_lower:
                    ch = candidate
                    break

        if ch:
            path = self.cache_dir / ch["file"]
            return path if path.exists() else None
        return None

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
        """Extract content from a chapter file."""
        text = file_path.read_text(encoding="utf-8", errors="replace")

        for matcher in self.matchers:
            if hasattr(matcher, "extract_content"):
                result = matcher.extract_content(text, location)
                if result is not None:
                    return result

        result = extract_line_range(text, location)
        if result is not None:
            return result

        if len(text) < SMALL_FILE_THRESHOLD:
            return text

        return ""

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

        for element in soup.find_all(["h2", "h3", "h4", "p", "blockquote"]):
            if element.name in ("h2", "h3", "h4"):
                if current_parts:
                    text = "\n\n".join(current_parts)
                    if len(text.strip()) > 50:
                        chapters.append({"title": current_title, "text": text})
                current_title = element.get_text(strip=True)
                current_parts = []
            elif element.name in ("p", "blockquote"):
                text = element.get_text(strip=True)
                if text and len(text) > 10:
                    current_parts.append(text)

        if current_parts:
            text = "\n\n".join(current_parts)
            if len(text.strip()) > 50:
                chapters.append({"title": current_title, "text": text})

        return chapters
