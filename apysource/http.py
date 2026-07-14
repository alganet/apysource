# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""HTTP client with transparent file-based caching.

Stores raw response bodies in a flat directory keyed by URL hash, next to
a small JSON sidecar recording where the request actually landed.

Redirects are followed, as they must be, but they are not forgotten: a
source whose URL now 301s still verifies against the document it was
forwarded to, which quietly turns "this URL says X" into "wherever this
URL leads says X". The sidecar is what lets a check say so out loud.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from apysource import __version__
from apysource.results import Redirect

logger = logging.getLogger(__name__)

#: Default crawler identity, derived from the package version so it tracks releases.
DEFAULT_USER_AGENT = f"apysource/{__version__} (source verification; gentle crawler)"


class CachedFetcher:
    """HTTP client that caches response bodies on disk.

    Cache key is sha256(url)[:16]. Cache hits skip the network
    and the polite delay entirely.
    """

    def __init__(self, cache_dir: Path, user_agent: str = DEFAULT_USER_AGENT,
                 default_delay: float = 3.0, default_timeout: int = 30):
        self.cache_dir = Path(cache_dir) if isinstance(cache_dir, str) else cache_dir
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.default_timeout = default_timeout
        self._redirects: dict[str, Redirect] = {}

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / self._cache_key(url)

    def _meta_path(self, url: str) -> Path:
        return self.cache_dir / f"{self._cache_key(url)}.meta.json"

    def redirect_for(self, url: str) -> Redirect | None:
        """Where this URL actually led, or None if that is not known.

        None means the body was cached before redirects were recorded, not
        that the URL is clean — callers must not report it as such. A
        ``--refresh`` re-fetch is what turns an unknown into a known.
        """
        if url in self._redirects:
            return self._redirects[url]

        meta = self._meta_path(url)
        if not meta.exists():
            return None

        try:
            data = json.loads(meta.read_text())
            info = Redirect(
                url=data["url"],
                final_url=data["final_url"],
                chain=[(int(s), u) for s, u in data.get("chain", [])],
            )
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("unreadable redirect metadata for %s: %s", url, e)
            return None

        # The sidecar names the URL it was written for. A cache directory
        # that was copied or merged can hold a file that does not answer the
        # question asked; say "unknown" rather than answer confidently wrong.
        if info.url != url:
            logger.warning("redirect metadata for %s names %s", url, info.url)
            return None

        self._redirects[url] = info
        return info

    def _record_redirect(self, url: str, resp: requests.Response) -> None:
        """Persist where a fetch landed, alongside its cached body.

        The memo is only set once the sidecar is on disk. Remembering a
        destination this process failed to persist would report a URL as
        checked for the rest of the run and as unknown ever after.
        """
        info = Redirect(
            url=url,
            final_url=resp.url,
            chain=[(r.status_code, r.url) for r in resp.history],
        )
        payload = {"url": info.url, "final_url": info.final_url,
                   "chain": [list(hop) for hop in info.chain]}

        meta = self._meta_path(url)
        tmp = meta.with_suffix(".tmp")
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload))
            tmp.rename(meta)
        except OSError as e:
            logger.warning("could not record redirect for %s: %s", url, e)
            return

        self._redirects[url] = info

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
        """Return cached bytes, or fetch over HTTP and cache them.

        ``force`` deletes any cached copy and re-fetches; ``from_cache`` returns
        cached bytes only (no network, ``None`` on a miss). On a network error
        the response is logged and ``None`` is returned without caching.
        """
        path = self._cache_path(url)

        if force:
            path.unlink(missing_ok=True)
            self._meta_path(url).unlink(missing_ok=True)
            self._redirects.pop(url, None)

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
            # A moved source whose new home is dead is the case that matters
            # most, and the response carries the chain that explains it. Keep
            # the destination even though there is no body to cache, so the
            # report can say "moved, and the move led nowhere" instead of a
            # bare "could not fetch".
            if e.response is not None:
                self._record_redirect(url, e.response)
            logger.error("fetching %s: %s", url, e)
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(resp.content)
        tmp.rename(path)
        self._record_redirect(url, resp)

        if actual_delay > 0:
            time.sleep(actual_delay)

        return bytes(resp.content)
