# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""HTTP client with transparent file-based caching.

Stores raw response bodies in a flat directory keyed by URL hash.
No sidecar files, no metadata — just the response body.
"""

import hashlib
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class CachedFetcher:
    """HTTP client that caches response bodies on disk.

    Cache key is sha256(url)[:16]. Cache hits skip the network
    and the polite delay entirely.
    """

    def __init__(self, cache_dir: Path, user_agent: str = "apysource/1.0",
                 default_delay: float = 3.0, default_timeout: int = 30):
        self.cache_dir = Path(cache_dir) if isinstance(cache_dir, str) else cache_dir
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.default_timeout = default_timeout

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / self._cache_key(url)

    def get(self, url: str, *, force: bool = False, from_cache: bool = False,
            delay: float | None = None, timeout: int | None = None,
            headers: dict | None = None, verify: bool = True) -> str | None:
        """Fetch URL and return response text. Cached on disk."""
        data = self._fetch(url, force=force, from_cache=from_cache,
                           delay=delay, timeout=timeout,
                           headers=headers, verify=verify)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    def get_bytes(self, url: str, *, force: bool = False, from_cache: bool = False,
                  delay: float | None = None, timeout: int | None = None,
                  headers: dict | None = None, verify: bool = True) -> bytes | None:
        """Fetch URL and return raw bytes. Cached on disk."""
        return self._fetch(url, force=force, from_cache=from_cache,
                           delay=delay, timeout=timeout,
                           headers=headers, verify=verify)

    def _fetch(self, url: str, *, force: bool = False, from_cache: bool = False,
               delay: float | None = None, timeout: int | None = None,
               headers: dict | None = None, verify: bool = True) -> bytes | None:
        path = self._cache_path(url)

        if force and path.exists():
            path.unlink()

        if path.exists():
            return path.read_bytes()

        if from_cache:
            return None

        actual_delay = delay if delay is not None else self.default_delay
        actual_timeout = timeout if timeout is not None else self.default_timeout

        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)

        try:
            resp = requests.get(url, headers=req_headers,
                                timeout=actual_timeout, verify=verify)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("fetching %s: %s", url, e)
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(resp.content)
        tmp.rename(path)

        if actual_delay > 0:
            time.sleep(actual_delay)

        return bytes(resp.content)
