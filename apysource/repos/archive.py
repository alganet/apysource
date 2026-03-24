# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Internet Archive repository module.

Archive items are stored as single full-text files. Each item has
its own subdirectory named by item_id containing fulltext.txt.

sourceLocation format: "{item_id}" (always resolves to fulltext.txt)
  Examples: "TheEpicofGilgamesh_201606", "rigvedacomplete"
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from apysource.repos._base import BaseRepo

logger = logging.getLogger(__name__)


class ArchiveRepo(BaseRepo):
    """Unified source + crawler for Internet Archive items."""

    NAME = "archive"

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Extract item_id from URL."""
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Map a sourceLocation to the fulltext file."""
        fulltext = self.cache_dir / key / "fulltext.txt"
        return fulltext if fulltext.exists() else None

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float = 3.0,
              force: bool = False, from_cache: bool = False) -> dict:
        """Download and cache an archive.org item's text."""
        return self._process_item(key, delay, force=force, from_cache=from_cache)

    def _get_metadata(self, item_id: str) -> dict | None:
        """Fetch archive.org metadata for an item."""
        url = f"{self.base_url}/metadata/{item_id}"
        text = self.http_client.get(url)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _find_text_file(self, metadata: dict) -> str | None:
        """Find the best text file in archive.org item metadata."""
        files = metadata.get("files", [])
        item_id = metadata.get("metadata", {}).get("identifier", "")

        candidates = []
        for f in files:
            name = f.get("name", "")
            fmt = f.get("format", "")
            if name.endswith("_djvu.txt") or "DjVuTXT" in fmt:
                candidates.append((0, name))
            elif name.endswith(".txt") and "Full Text" in fmt:
                candidates.append((1, name))
            elif name.endswith(".txt"):
                candidates.append((2, name))

        if not candidates:
            return None

        candidates.sort()
        return f"{self.base_url}/download/{item_id}/{candidates[0][1]}"

    def _process_item(self, item_id: str, delay: float,
                      force: bool = False, from_cache: bool = False) -> dict:
        """Download and cache an archive.org item's text."""
        logger.info("Processing %s...", item_id)
        item_dir = self.cache_dir / item_id
        fulltext_path = item_dir / "fulltext.txt"

        if not force and not from_cache and fulltext_path.exists():
            text_content = fulltext_path.read_text(encoding="utf-8")
            logger.info("%s — %s chars (cached)", item_id, f"{len(text_content):,}")
            return {
                "id": item_id, "status": "ok",
                "text_chars": len(text_content),
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch metadata via HTTP cache
        meta_url = f"{self.base_url}/metadata/{item_id}"
        meta_text = self.http_client.get(meta_url, force=force, from_cache=from_cache)
        if not meta_text:
            return {"id": item_id, "status": "error", "error": "metadata fetch failed"}

        try:
            meta = json.loads(meta_text)
        except json.JSONDecodeError:
            return {"id": item_id, "status": "error", "error": "invalid metadata JSON"}

        title = meta.get("metadata", {}).get("title", item_id)
        creator = meta.get("metadata", {}).get("creator", "")

        text_url = self._find_text_file(meta)
        text_content = ""
        if text_url:
            logger.info("Downloading text: %s", text_url.split('/')[-1])
            text_content = self.http_client.get(
                text_url, force=force, from_cache=from_cache) or ""

        if text_content:
            item_dir.mkdir(parents=True, exist_ok=True)
            fulltext_path.write_text(text_content, encoding="utf-8")

        result = {
            "id": item_id, "title": title, "creator": creator,
            "status": "ok" if text_content else "metadata_only",
            "text_chars": len(text_content),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("%s — %s chars", title[:60], f"{len(text_content):,}")
        return result
