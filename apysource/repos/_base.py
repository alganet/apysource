# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared utilities and base class for apysource repository modules.

No config imports — all values received as parameters.
"""

import re
from pathlib import Path


class BaseRepo:
    """Base class for repos — provides common boilerplate.

    Subclasses must define NAME, url_to_key(), and resolve_location().
    Constructor requires url_pattern and base_url.
    cache_dir and http_client are optional — RepoRegistry fills them
    from its own sources_cache_dir and http_client if not set.
    """

    NAME = ""

    def __init__(self, cache_dir=None, http_client=None,
                 url_pattern=None, base_url=None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.http_client = http_client
        if url_pattern is None:
            raise TypeError(f"{type(self).__name__} requires url_pattern")
        if base_url is None:
            raise TypeError(f"{type(self).__name__} requires base_url")
        self.url_pattern = (re.compile(url_pattern) if isinstance(url_pattern, str)
                            else url_pattern)
        self.base_url = base_url.rstrip("/")

    def url_to_key(self, url: str) -> str | None:
        """Extract a cache key from a URL. Subclasses must override."""
        raise NotImplementedError

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Resolve a location to a cache file path. Subclasses must override."""
        raise NotImplementedError

    def is_cached(self, key: str) -> bool:
        """Check if key is cached by trying resolve_location."""
        loc = self.resolve_location("", key)
        return loc is not None and loc.exists()

    def extract_content(self, location: str, file_path: Path) -> str:
        """Extract content using line range with small-file fallback."""
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return extract_content_with_fallback(text, location)

SMALL_FILE_THRESHOLD = 5000


def extract_line_range(text: str, location: str) -> str | None:
    """Extract lines:N-M range from text based on location string."""
    line_match = re.search(r"lines:(\d+)-(\d+)", location)
    if not line_match:
        return None
    from apysource.formats import PlainTextFormat
    line_range = f"{line_match.group(1)}-{line_match.group(2)}"
    return PlainTextFormat().extract(text, line_range)


def slugify(text: str) -> str:
    """Convert text to a filesystem slug: lowercase, spaces to underscores."""
    return text.lower().replace(" ", "_")


def extract_content_with_fallback(
    text: str, location: str, *, threshold: int = SMALL_FILE_THRESHOLD,
) -> str:
    """Common extract_content pattern: try line range, then small-file fallback."""
    result = extract_line_range(text, location)
    if result is not None:
        return result
    if len(text) < threshold:
        return text
    return ""
