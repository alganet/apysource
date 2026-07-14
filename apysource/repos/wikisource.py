# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Wikisource repository module.

Wikisource works are stored with a main.txt for the top-level page
and individual subpage files ({subpage_name}.txt) in a slug-based
directory.

sourceLocation formats:
  "section:Section_1"   -> {slug}/Section_1.txt
  "{subpage_match}"     -> fuzzy match against subpage filenames
"""

import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from apysource.repos._base import (
    BaseRepo,
    RepoError,
    RepoNotFound,
    RepoUnavailable,
    extract_content_with_fallback,
    slugify,
)

logger = logging.getLogger(__name__)


class WikisourceRepo(BaseRepo):
    """Unified source + crawler for Wikisource works."""

    NAME = "wikisource"
    supports_crawl = True

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Extract page title from a Wikisource URL (URL-decoded)."""
        m = self.url_pattern.search(url)
        if m:
            return urllib.parse.unquote(m.group(1))
        return None

    def is_cached(self, key: str) -> bool:
        """Check if a Wikisource work is cached."""
        slug = slugify(key)
        work_dir = self.cache_dir / slug
        return work_dir.exists() and (work_dir / "main.txt").exists()

    def _find_slug_for_key(self, key: str) -> str | None:
        """Resolve a key to an actual slug on disk."""
        slug = slugify(key)
        if (self.cache_dir / slug).exists():
            return slug
        # Scan directories for fuzzy match
        if self.cache_dir.exists():
            for d in self.cache_dir.iterdir():
                if d.is_dir() and (slug in d.name or d.name in slug):
                    return d.name
        return None

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Map a sourceLocation to a cached subpage file."""
        slug = self._find_slug_for_key(key)
        if not slug:
            return None
        work_dir = self.cache_dir / slug

        # Explicit section reference: "section:Section_1"
        m = re.match(r"section:(.+)", location)
        if m:
            subpage_name = m.group(1).strip()
            path = work_dir / f"{subpage_name}.txt"
            if path.exists():
                return path
            for f in work_dir.glob("*.txt"):
                if f.stem.lower() == subpage_name.lower():
                    return f
            return None

        # Direct subpage name match
        path = work_dir / f"{location}.txt"
        if path.exists():
            return path

        # Fuzzy match
        loc_lower = location.lower().replace(" ", "_")
        if ":" in location:
            suffix = location.split(":", 1)[1].strip()
            suffix_slug = suffix.lower().replace(" ", "_")
            for f in sorted(work_dir.glob("*.txt")):
                if f.name == "main.txt":
                    continue
                if suffix_slug in f.stem.lower() or f.stem.lower() in suffix_slug:
                    return f

        for f in sorted(work_dir.glob("*.txt")):
            if f.name == "main.txt":
                continue
            if loc_lower in f.stem.lower() or f.stem.lower() in loc_lower:
                return f

        main = work_dir / "main.txt"
        return main if main.exists() else None

    def extract_content(self, location: str, file_path: Path) -> str:
        """Extract content from a Wikisource subpage file."""
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return extract_content_with_fallback(text, location)

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float | None = None,
              force: bool = False, from_cache: bool = False) -> dict:
        """Download a Wikisource page and its subpages.

        Raises RepoNotFound when Wikisource has no such page.
        """
        return self._process_page(key, force=force, from_cache=from_cache)

    def _get_page_text(self, title: str, slug: str = "",
                       force: bool = False, from_cache: bool = False) -> str:
        """Get full rendered text of a Wikisource page.

        Raises RepoNotFound if Wikisource has no such page, RepoUnavailable if
        it could not be read. Callers that are merely hoovering up subpages
        catch those and move on; the caller fetching the page a citation
        actually names lets them through.
        """
        params = {
            "action": "parse",
            "page": title,
            "prop": "text",
            "disabletoc": "1",
            "format": "json",
        }
        query = urllib.parse.urlencode(params)
        url = f"{f"{self.base_url}/w/api.php"}?{query}"

        raw = self.fetch(url, title, force=force, from_cache=from_cache)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RepoUnavailable(self.NAME, title,
                                  "the API returned invalid JSON") from e

        # MediaWiki reports a missing page in the body, with a 200 status.
        if "error" in data:
            raise RepoNotFound(self.NAME, title,
                               data["error"].get("info", "no such page"))

        html = data.get("parse", {}).get("text", {}).get("*", "")
        if not html:
            raise RepoNotFound(self.NAME, title, "the page has no text")
        from apysource.formats import HtmlFormat
        return HtmlFormat().strip_tags(html)

    def _get_subpages(self, title: str) -> list[str]:
        """Get all subpages of a Wikisource page."""
        params = {
            "action": "query",
            "list": "allpages",
            "apprefix": title + "/",
            "apnamespace": "0",
            "aplimit": "500",
            "format": "json",
        }
        query = urllib.parse.urlencode(params)
        url = f"{f"{self.base_url}/w/api.php"}?{query}"

        raw = self.http_client.get(url)
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        subpages = []
        for page in data.get("query", {}).get("allpages", []):
            subpages.append(page["title"])
        return subpages

    def _process_page(self, title: str,
                      force: bool = False, from_cache: bool = False) -> dict:
        """Download a Wikisource page and its subpages."""
        slug = title.lower().replace(" ", "_")
        logger.info("Processing %s...", title)

        page_dir = self.cache_dir / slug
        main_txt = page_dir / "main.txt"

        if not force and not from_cache and main_txt.exists():
            text = main_txt.read_text(encoding="utf-8")
            logger.info("%s — cached", title)
            return {
                "title": title, "slug": slug,
                "total_chars": len(text),
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch before creating anything. A page Wikisource does not have
        # should leave no directory behind to be mistaken for a crawl that
        # worked — and _get_page_text raises rather than returning "".
        main_text = self._get_page_text(
            title, slug=slug, force=force, from_cache=from_cache)

        page_dir.mkdir(parents=True, exist_ok=True)
        main_txt.write_text(main_text, encoding="utf-8")

        subpages = self._get_subpages(title)
        logger.info("Found %d subpages", len(subpages))

        total_chars = len(main_text)
        for i, sub in enumerate(subpages):
            # A subpage that has gone missing is not a reason to fail the page
            # a citation actually names. Skip it, and say so.
            try:
                sub_text = self._get_page_text(
                    sub, slug=slug, force=force, from_cache=from_cache)
            except RepoError as e:
                logger.warning("skipping subpage %s: %s", sub, e)
                continue
            sub_slug = sub.replace(
                title + "/", "").replace(" ", "_").replace("/", "_")
            (page_dir / f"{sub_slug}.txt").write_text(
                sub_text, encoding="utf-8")
            total_chars += len(sub_text)
            if (i + 1) % 10 == 0:
                logger.info("... %d/%d subpages", i + 1, len(subpages))

        result = {
            "title": title,
            "slug": slug,
            "subpages": len(subpages),
            "total_chars": total_chars,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("%s — %s chars across %d pages", title, f"{total_chars:,}", len(subpages) + 1)
        return result
