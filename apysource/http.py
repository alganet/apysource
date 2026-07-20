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
import http.cookiejar as cookiejar
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urldefrag, urlsplit

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


#: How old a scratch file must be before it is certainly abandoned. A write
#: takes milliseconds, so anything from an hour ago belongs to a run that died —
#: and the margin is wide enough that a *live* writer, in this process or
#: another, is never mistaken for a corpse.
TMP_STALE_SECONDS = 3600


def _tmp_path(path: Path) -> Path:
    """A scratch name only this writer will use.

    The write is ``tmp`` then ``rename``, which is atomic — but only if no two
    writers share the ``tmp``. It used to be a fixed name per URL, so two CI jobs
    pointed at one cache directory, or two threads within a run, could interleave
    a half-written body with a rename and publish a truncated document under a
    name that says it is complete. A corrupt cache entry is worse than a slow
    one: it verifies against nothing and blames the citation.

    The cost of uniqueness is that nothing reclaims the name afterwards, which
    the fixed one did by being overwritten. ``_write_atomic`` removes it on the
    way out, and ``sweep_stale_tmp`` clears what a killed process could not.
    """
    return path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")


def _write_atomic(path: Path, write: Callable[[Path], object]) -> None:
    """Publish ``path`` in one step, leaving no scratch file behind.

    ``write`` is handed the scratch path and puts the content there; this
    renames it into place. The ``finally`` is the point: without it, a failed
    write or a raised exception leaves a uniquely-named orphan that, unlike the
    old fixed name, no later run will ever reuse or overwrite.
    """
    tmp = _tmp_path(path)
    try:
        write(tmp)
        tmp.rename(path)
    finally:
        # A successful rename means this is already gone; missing_ok covers both.
        tmp.unlink(missing_ok=True)


def sweep_stale_tmp(cache_dir: Path) -> int:
    """Delete scratch files left by runs that were killed. Returns the count.

    A process stopped with SIGKILL, or a CI job that hit its timeout, never runs
    its ``finally``. Its scratch file is named for a pid and a thread that no
    longer exist, so nothing will ever collide with it, reuse it, or clean it —
    it simply sits in the cache directory holding a document's worth of bytes.
    Over a nightly job that occasionally times out, that is a slow leak of disk
    in the one directory nobody looks at.

    Deliberately quiet and best-effort: a cache directory that cannot be listed,
    or a file that vanishes under us or belongs to another user, is not this
    run's problem and certainly not a reason to fail a verification.
    """
    removed = 0
    try:
        entries = list(os.scandir(cache_dir))
    except OSError:
        return 0

    cutoff = time.time() - TMP_STALE_SECONDS
    for entry in entries:
        if not entry.name.endswith(".tmp"):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                os.unlink(entry.path)
                removed += 1
        except OSError:
            continue

    if removed:
        logger.debug("removed %d stale scratch file(s) from %s", removed, cache_dir)
    return removed


def url_anchor(url: str) -> str:
    """The fragment a citation's URL carries, or "".

    It is the one piece of targeting the author has already written down —
    `rfc9110.html#section-7.2` says, in the author's own hand, *where in the
    document this is*. It was read by nobody.
    """
    return urldefrag(url)[1]


#: A cookie policy that stores nothing and sends nothing.
#:
#: A ``Session`` exists here for connection reuse, and a cookie jar comes with
#: it. Carrying a cookie from one citation to the next is not a performance
#: detail: a site that sets one could serve the second request something the
#: first never saw, and "this URL says X" is the only claim this tool makes.
#: Bare ``requests.get`` had no jar, so this restores that guarantee rather than
#: relying on emptying the jar afterwards.
_REFUSE_COOKIES = cookiejar.DefaultCookiePolicy(allowed_domains=[])

#: Statuses worth asking again about. 404, 403 and 410 are deliberately absent:
#: they are answers, not failures, and retrying one turns a repo's
#: ``RepoNotFound`` into a slow ``RepoNotFound`` while asking a server three
#: times to confirm what it already said.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _retry_after(resp: requests.Response) -> float | None:
    """The wait a server asked for, in seconds, or None if it did not ask.

    ``Retry-After`` is either a number of seconds or an HTTP-date, and a server
    under load is far more likely to send the second. Honouring only the first
    would mean ignoring exactly the servers that bothered to tell us.
    """
    value = resp.headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    from datetime import datetime, timezone
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


class HostRateLimiter:
    """One request per host per delay, counted from when the request is made.

    Politeness is owed to a *server*, and the old delay was owed to nobody in
    particular: one ``time.sleep`` after every fetch, so a run citing rfc-editor
    and archive.org waited three seconds between them for no reason, and a run
    that fetched one page slept three seconds after the last thing it did.

    The slot is reserved under the lock and slept for outside it, which is what
    makes this correct with several workers: two threads asking about one host
    get two different times to start, and neither holds the lock while waiting.
    Threads asking about different hosts do not meet at all.
    """

    def __init__(self, sleep: Callable[[float], object] = time.sleep,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._sleep = sleep
        self._now = now
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, url: str, delay: float) -> float:
        """Wait until this host may be asked again. Returns the wait, for tests.

        Deliberately does **not** short-circuit on ``delay <= 0``. A zero delay
        means "no rate of our own", not "no waiting" — a retry may have put a
        backoff on this host through ``penalize``, and returning early ignored
        it. That is the common case, not a corner: the MDN repo crawls at
        ``crawl_delay = 0.5`` and a caller may pass 0 outright, and those are
        precisely the runs where a 503 storm would go unpaced.
        """
        host = urlsplit(url).netloc
        with self._lock:
            now = self._now()
            allowed = self._next.get(host, now)
            wait = max(0.0, allowed - now)
            # Reserved from the moment this request may start, not from when it
            # finishes: the delay is a rate, and a slow response has already
            # given the server the room the delay was asking for.
            self._next[host] = max(allowed, now) + delay

        if wait > 0:
            self._sleep(wait)
        return wait

    def penalize(self, url: str, seconds: float) -> None:
        """Hold this host off for at least ``seconds``, on top of any rate.

        This is how a retry's backoff is spent. Letting the HTTP layer sleep for
        it instead — which is what ``urllib3``'s ``Retry`` does — meant the
        backoff and the politeness delay knew nothing about each other: three
        retries went out from inside one ``acquire``, spaced by urllib3 and not
        by the configured delay, so a host answering 503 received about four
        times the requests at a fraction of the intended spacing. The one moment
        a server is least able to take it.

        A **maximum**, not a sum: the next request waits for whichever of the
        rate and the backoff is longer. Both constraints are then satisfied, and
        adding them would compound two answers to the same question.
        """
        if seconds <= 0:
            return
        host = urlsplit(url).netloc
        with self._lock:
            now = self._now()
            self._next[host] = max(self._next.get(host, now), now + seconds)


class CachedFetcher:
    """HTTP client that caches response bodies on disk.

    Cache key is sha256 of the *document* URL (see ``document_url``), so the
    same document cited at a dozen different anchors is fetched once. Cache
    hits skip the network and the polite delay entirely.
    """

    def __init__(self, cache_dir: Path, user_agent: str = DEFAULT_USER_AGENT,
                 default_delay: float = 3.0, default_timeout: int = 30,
                 workers: int = 1, retries: int = 3,
                 backoff_factor: float = 0.5,
                 sleep: Callable[[float], object] = time.sleep,
                 now: Callable[[], float] = time.monotonic):
        self.cache_dir = Path(cache_dir) if isinstance(cache_dir, str) else cache_dir
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.default_timeout = default_timeout
        self.workers = max(1, workers)
        self.retries = retries
        self.backoff_factor = backoff_factor
        self._redirects: dict[str, Redirect] = {}
        self._statuses: dict[str, int | None] = {}
        # Plain dict writes are atomic under the GIL, so this guards nothing
        # against corruption — it guards the read-then-write in `redirect_for`,
        # and it says out loud that these are reached from several threads.
        self._memo_lock = threading.Lock()
        self._limiter = HostRateLimiter(sleep=sleep, now=now)
        self._session: requests.Session | None = None
        self._session_lock = threading.Lock()
        #: The stale-scratch sweep runs once per fetcher, on the first write.
        #: Doing it in the constructor would touch the disk for a run that
        #: turns out to be entirely cache hits and never writes anything.
        self._swept = False

    def _prepare_cache_dir(self) -> None:
        """Make sure the cache directory exists, and sweep it once per run."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self._swept:
            # Set first: a sweep that raises must not make every later write
            # try again, and there is nothing here worth retrying anyway.
            self._swept = True
            sweep_stale_tmp(self.cache_dir)

    def _get_session(self) -> requests.Session:
        """The shared session, built on first use.

        Every fetch used to be a bare ``requests.get``, which opens a new TCP
        connection and repeats the TLS handshake — for a crawl of a hundred
        pages from one host, a hundred handshakes to a server that offered
        keep-alive the first time.

        Retrying is deliberately **not** delegated to the adapter. ``urllib3``
        sleeps for its own backoff inside a single call, which put those requests
        outside the per-host rate limiter entirely — see ``_fetch``, which does
        the retrying itself so that every attempt is paced like every other
        request to that host. The adapter is left with ``max_retries=0``.

        What it is still for is the connection pool: sized to the worker count,
        so eight workers do not fight over one connection or open more than they
        can use.
        """
        if self._session is not None:
            return self._session

        with self._session_lock:
            if self._session is not None:
                return self._session

            from requests.adapters import HTTPAdapter

            session = requests.Session()
            # Refuse cookies outright rather than clear them after each request.
            #
            # Clearing worked, and was unsafe the moment there were workers:
            # `CookieJar.clear()` rebinds its backing dict without taking
            # `_cookies_lock`, while `add_cookie_header` and `extract_cookies`
            # both take it. One worker clearing mid-flight could therefore drop
            # a cookie another worker's redirect chain had just been issued —
            # and a consent or session redirect that loses its cookie lands
            # somewhere else, which means a citation checked against a different
            # document. A policy that never stores has nothing to race over.
            session.cookies.set_policy(_REFUSE_COOKIES)
            adapter = HTTPAdapter(
                max_retries=0,
                pool_connections=self.workers,
                pool_maxsize=self.workers,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._session = session
            return session

    @staticmethod
    def _cache_key(url: str) -> str:
        return hashlib.sha256(document_url(url).encode()).hexdigest()[:16]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / self._cache_key(url)

    def _meta_path(self, url: str) -> Path:
        return self.cache_dir / f"{self._cache_key(url)}.meta.json"

    def is_cached(self, url: str) -> bool:
        """Is this document already on disk, so that reading it needs no network?

        Asked before a run decides whether a document is worth handing to a
        worker. It is a stat, not a read: the answer is only used to skip work
        that would cost nothing to do serially anyway, so being wrong about a
        file that vanishes underneath us is harmless.
        """
        return self._cache_path(url).exists()

    def redirect_for(self, url: str) -> Redirect | None:
        """Where this URL actually led, or None if that is not known.

        None means the body was cached before redirects were recorded, not
        that the URL is clean — callers must not report it as such. A
        ``--refresh`` re-fetch is what turns an unknown into a known.
        """
        url = document_url(url)
        with self._memo_lock:
            found = self._redirects.get(url)
        if found is not None:
            return found

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

        with self._memo_lock:
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
        with self._memo_lock:
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
        try:
            self._prepare_cache_dir()
            _write_atomic(meta, lambda tmp: tmp.write_text(json.dumps(payload)))
        except OSError as e:
            logger.warning("could not record redirect for %s: %s", url, e)
            return

        with self._memo_lock:
            self._redirects[url] = info

    def _request(self, url: str, headers: dict, timeout: int, verify: bool,
                 delay: float) -> requests.Response:
        """One document, asked for up to ``retries + 1`` times, politely.

        Every attempt — the first and each retry — goes through
        ``limiter.acquire`` before it leaves, so a retry is paced exactly like
        any other request to that host. This is the whole reason the retrying is
        here and not on the adapter: ``urllib3`` sleeps for its backoff *inside*
        one call, so its retries never reached the limiter at all and a
        struggling host got four times the requests at a quarter of the spacing.

        The backoff is spent as a penalty on the host's slot rather than as a
        sleep of its own, so the wait is whichever of the two is longer instead
        of one and then the other.

        A response that is not worth retrying — including every 4xx — is
        returned as it stands, for ``raise_for_status`` to judge. The last
        attempt's outcome is always what the caller sees, success or not.
        """
        attempts = max(1, self.retries + 1)
        session = self._get_session()

        for attempt in range(attempts):
            self._limiter.acquire(url, delay)
            last = attempt + 1 >= attempts

            try:
                resp = session.get(url, headers=headers, timeout=timeout,
                                   verify=verify)
            except requests.RequestException:
                # No response at all: a reset, a timeout, a name that would not
                # resolve. Worth another go, but not worth pretending we know
                # anything about it.
                if last:
                    raise
                self._limiter.penalize(url, self._backoff(attempt, None))
                continue

            if resp.status_code in RETRY_STATUSES and not last:
                self._limiter.penalize(url, self._backoff(attempt, resp))
                continue

            return resp

        raise AssertionError("unreachable: the loop returns or raises")

    def _backoff(self, attempt: int, resp: requests.Response | None) -> float:
        """How long to hold off before asking again.

        A server that said ``Retry-After`` gets to choose; it knows what it is
        recovering from and we do not. Otherwise the usual doubling, which is
        the same schedule ``urllib3`` would have used.
        """
        if resp is not None:
            asked = _retry_after(resp)
            if asked is not None:
                return asked
        return float(self.backoff_factor) * (2.0 ** attempt)

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
            with self._memo_lock:
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
            resp = self._request(url, req_headers, actual_timeout, verify,
                                 actual_delay)
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
            with self._memo_lock:
                self._statuses[url] = (e.response.status_code
                                       if e.response is not None else None)
            if e.response is not None:
                self._record_redirect(url, e.response)
            logger.error("fetching %s: %s", url, e)
            return None

        with self._memo_lock:
            self._statuses[url] = resp.status_code
        self._prepare_cache_dir()
        _write_atomic(path, lambda tmp: tmp.write_bytes(resp.content))
        self._record_redirect(url, resp)

        return bytes(resp.content)
