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
from urllib.parse import urldefrag

import requests

from apysource import __version__
from apysource.results import Redirect

logger = logging.getLogger(__name__)

#: Default crawler identity, derived from the package version so it tracks releases.
DEFAULT_USER_AGENT = f"apysource/{__version__} (source verification; gentle crawler)"


def document_url(url: str) -> str:
    """The document a URL names, without the fragment that points inside it.

    A fragment identifies a place *within* a document, never a different
    document — it is resolved by the client and is never sent to the server.
    So two citations into ``rfc9110.html`` that name different sections are
    two citations into one document, and must share one cache entry, one
    download and one polite delay. Keyed on the raw URL they were three
    documents, fetched three times, byte for byte identical.

    The citation keeps its fragment: the report still prints the URL its
    author wrote. Only the identity of *the thing being fetched* drops it.
    """
    return urldefrag(url)[0]


class CachedFetcher:
    """HTTP client that caches response bodies on disk.

    Cache key is sha256 of the *document* URL (see ``document_url``), so the
    same document cited at a dozen different anchors is fetched once. Cache
    hits skip the network and the polite delay entirely.
    """

    def __init__(self, cache_dir: Path, user_agent: str = DEFAULT_USER_AGENT,
                 default_delay: float = 3.0, default_timeout: int = 30):
        self.cache_dir = Path(cache_dir) if isinstance(cache_dir, str) else cache_dir
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.default_timeout = default_timeout
        self._redirects: dict[str, Redirect] = {}
        self._statuses: dict[str, int | None] = {}

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.sha256(document_url(url).encode()).hexdigest()[:16]

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
        url = document_url(url)
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

    def status_for(self, url: str) -> int | None:
        """The HTTP status the last fetch of this URL got, if it got one.

        ``None`` means no status was seen — the URL was never fetched in this
        process, or the request never reached a server at all (DNS failure,
        timeout, connection reset). That distinction is the whole reason this
        exists: ``get`` returns ``None`` for a 404 and for a network outage
        alike, and a repo that reads both as "this document does not exist"
        would blame a citation for an unplugged cable.
        """
        return self._statuses.get(document_url(url))

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
        # Everything below — the cache path, the memos, the request itself —
        # is about one document, so it is keyed on the document and not on
        # whichever anchor the citation happened to name.
        url = document_url(url)
        path = self._cache_path(url)

        if force:
            path.unlink(missing_ok=True)
            self._meta_path(url).unlink(missing_ok=True)
            self._redirects.pop(url, None)
            self._statuses.pop(url, None)

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
            #
            # The status is kept for the same reason, and it is left unset
            # when the request never reached a server: a caller asking "was
            # this a 404?" must be able to hear "I don't know".
            if e.response is not None:
                self._statuses[url] = e.response.status_code
                self._record_redirect(url, e.response)
            else:
                self._statuses[url] = None
            logger.error("fetching %s: %s", url, e)
            return None

        self._statuses[url] = resp.status_code
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(resp.content)
        tmp.rename(path)
        self._record_redirect(url, resp)

        if actual_delay > 0:
            time.sleep(actual_delay)

        return bytes(resp.content)
