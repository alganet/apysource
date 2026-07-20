# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.http.CachedFetcher."""

from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from apysource import __version__
from apysource.http import DEFAULT_USER_AGENT, CachedFetcher


class _FakeRedirect:
    """One hop of a redirect chain, as requests exposes it."""

    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url


class _FakeResponse:
    def __init__(self, content=b"network body", status_ok=True,
                 url="https://example.com/page", history=None, status_code=None,
                 headers=None):
        self.content = content
        # A real response always carries headers, and the fetcher reads
        # `Retry-After` off them to decide how long to hold off. A double
        # without them could not exercise that at all.
        self.headers = headers or {}
        self._status_ok = status_ok
        # A real response always carries a status, and the fetcher now reads it
        # so that a repo can tell "the server said no such page" from "there was
        # no server". A double that omitted it let that distinction go untested.
        self.status_code = status_code if status_code is not None else (
            200 if status_ok else 404)
        self.url = url
        self.history = history or []
        # A session keeps a cookie jar; the fetcher installs a policy that
        # refuses to store into it, so one citation's cookies cannot change
        # what the next one is served.
        self.cookies = requests.cookies.RequestsCookieJar()

    def raise_for_status(self):
        if not self._status_ok:
            # requests attaches the response to the error, and it carries the
            # redirect chain that led to the dead page.
            raise requests.HTTPError("404 Not Found", response=self)


def _no_sleep(tmp_path, **kwargs):
    """A fetcher that never waits for real.

    Retrying is paced through the rate limiter, so a test that provokes a retry
    and leaves the real clock in place pays the backoff in wall-clock — three of
    these turned a 0.1s module into a 13s one. Timing is asserted against an
    injected clock (see `_Clock`); everything else should simply not sleep.
    """
    kwargs.setdefault("default_delay", 0)
    kwargs.setdefault("sleep", lambda seconds: None)
    return CachedFetcher(cache_dir=tmp_path, **kwargs)


class TestCacheKey:
    def test_deterministic(self):
        f = CachedFetcher(cache_dir="/tmp")
        key1 = f._cache_key("https://example.com/page")
        key2 = f._cache_key("https://example.com/page")
        assert key1 == key2

    def test_different_urls(self):
        f = CachedFetcher(cache_dir="/tmp")
        key1 = f._cache_key("https://example.com/a")
        key2 = f._cache_key("https://example.com/b")
        assert key1 != key2

    def test_length(self):
        f = CachedFetcher(cache_dir="/tmp")
        key = f._cache_key("https://example.com/page")
        assert len(key) == 16


class TestCachePath:
    def test_returns_path_in_cache_dir(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        path = f._cache_path("https://example.com/page")
        assert path.parent == tmp_path


class TestGetFromCache:
    def test_cache_hit(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        # Pre-populate cache
        path = f._cache_path("https://example.com/page")
        path.write_bytes(b"cached content")
        result = f.get("https://example.com/page")
        assert result == "cached content"

    def test_from_cache_missing(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        result = f.get("https://example.com/missing", from_cache=True)
        assert result is None


class TestGetBytesFromCache:
    def test_cache_hit(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        path = f._cache_path("https://example.com/binary")
        path.write_bytes(b"\x00\x01\x02")
        result = f.get_bytes("https://example.com/binary")
        assert result == b"\x00\x01\x02"


class TestForce:
    def test_force_deletes_cache(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        path = f._cache_path("https://example.com/page")
        path.write_bytes(b"old content")
        # Force with from_cache should return None (file deleted, no network)
        result = f.get("https://example.com/page", force=True, from_cache=True)
        assert result is None
        assert not path.exists()


class TestStringCacheDir:
    def test_string_path(self, tmp_path):
        f = CachedFetcher(cache_dir=str(tmp_path))
        assert f.cache_dir == tmp_path


class TestDefaultUserAgent:
    def test_tracks_package_version(self):
        assert DEFAULT_USER_AGENT == (
            f"apysource/{__version__} (source verification; gentle crawler)"
        )

    def test_is_the_constructor_default(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path)
        assert f.user_agent == DEFAULT_USER_AGENT


class TestNetworkFetch:
    def test_success_caches_and_returns(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"fresh content")) as mock_get:
            result = f.get("https://example.com/new")
        assert result == "fresh content"
        # Cached for next time.
        assert f._cache_path("https://example.com/new").read_bytes() == b"fresh content"
        # Sent our version-tracking User-Agent.
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["User-Agent"] == DEFAULT_USER_AGENT

    def test_custom_headers_merge_with_user_agent(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get",
                   return_value=_FakeResponse()) as mock_get:
            f.get("https://example.com/h", headers={"Accept": "text/plain"})
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Accept"] == "text/plain"
        assert kwargs["headers"]["User-Agent"] == DEFAULT_USER_AGENT

    def test_request_exception_returns_none_and_does_not_cache(self, tmp_path):
        f = _no_sleep(tmp_path)
        with patch("requests.Session.get",
                   side_effect=requests.ConnectionError("boom")):
            result = f.get("https://example.com/down")
        assert result is None
        assert not f._cache_path("https://example.com/down").exists()

    def test_http_error_status_returns_none(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get",
                   return_value=_FakeResponse(status_ok=False)):
            result = f.get("https://example.com/missing")
        assert result is None
        assert not f._cache_path("https://example.com/missing").exists()

    def test_get_bytes_over_network(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"\x00\x01rawbytes")):
            result = f.get_bytes("https://example.com/bin")
        assert result == b"\x00\x01rawbytes"

    def test_force_refetches_over_network(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        path = f._cache_path("https://example.com/p")
        path.write_bytes(b"stale")
        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"refetched")) as mock_get:
            result = f.get("https://example.com/p", force=True)
        assert result == "refetched"
        assert mock_get.called  # force bypassed the cache hit
        assert path.read_bytes() == b"refetched"


class TestRedirects:
    """Redirects are followed, but recorded so a check can surface them."""

    def _fetch_with(self, tmp_path, resp):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get", return_value=resp):
            f.get("https://old.example.com/page")
        return f

    def test_redirect_chain_is_recorded(self, tmp_path):
        resp = _FakeResponse(
            url="https://new.example.com/page",
            history=[_FakeRedirect(301, "https://old.example.com/page")],
        )
        f = self._fetch_with(tmp_path, resp)

        info = f.redirect_for("https://old.example.com/page")
        assert info is not None
        assert info.redirected
        assert info.final_url == "https://new.example.com/page"
        assert info.chain == [(301, "https://old.example.com/page")]

    def test_direct_fetch_records_no_redirect(self, tmp_path):
        f = self._fetch_with(
            tmp_path, _FakeResponse(url="https://old.example.com/page")
        )

        info = f.redirect_for("https://old.example.com/page")
        assert info is not None
        assert not info.redirected
        assert info.chain == []

    def test_metadata_survives_a_new_fetcher(self, tmp_path):
        """The sidecar is on disk, so a cached run still sees the redirect."""
        resp = _FakeResponse(
            url="https://new.example.com/page",
            history=[_FakeRedirect(302, "https://old.example.com/page")],
        )
        self._fetch_with(tmp_path, resp)

        fresh = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        info = fresh.redirect_for("https://old.example.com/page")
        assert info is not None
        assert info.final_url == "https://new.example.com/page"

    def test_cache_without_metadata_is_unknown_not_clean(self, tmp_path):
        """A body cached before this existed must not read as 'no redirect'.

        Reporting it as clean would silently recreate the bug the metadata
        exists to expose.
        """
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        f._cache_path("https://old.example.com/page").parent.mkdir(
            parents=True, exist_ok=True
        )
        f._cache_path("https://old.example.com/page").write_bytes(b"stale body")

        assert f.redirect_for("https://old.example.com/page") is None

    def test_unknown_url_is_unknown(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        assert f.redirect_for("https://never.fetched.example.com/") is None

    def test_refresh_clears_stale_metadata(self, tmp_path):
        """--refresh re-fetches, so the recorded destination is re-derived."""
        moved = _FakeResponse(
            url="https://new.example.com/page",
            history=[_FakeRedirect(301, "https://old.example.com/page")],
        )
        f = self._fetch_with(tmp_path, moved)

        settled = _FakeResponse(url="https://old.example.com/page")
        with patch("requests.Session.get", return_value=settled):
            f.get("https://old.example.com/page", force=True)

        info = f.redirect_for("https://old.example.com/page")
        assert info is not None
        assert not info.redirected

    def test_corrupt_metadata_is_unknown(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        f.cache_dir.mkdir(parents=True, exist_ok=True)
        f._meta_path("https://old.example.com/page").write_text("{not json")

        assert f.redirect_for("https://old.example.com/page") is None

    def test_a_redirect_to_a_dead_page_keeps_its_chain(self, tmp_path):
        """Moved, and the move led nowhere — the case that matters most.

        The response carries the chain that explains the failure, and it was
        being thrown away with the exception.
        """
        gone = _FakeResponse(status_ok=False, url="https://new.example.com/gone",
                             history=[_FakeRedirect(301, "https://old.example.com/page")])
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get", return_value=gone):
            assert f.get("https://old.example.com/page") is None

        info = f.redirect_for("https://old.example.com/page")
        assert info is not None
        assert info.redirected
        assert info.final_url == "https://new.example.com/gone"

    def test_a_sidecar_naming_another_url_is_not_trusted(self, tmp_path):
        """A copied or merged cache dir must not answer confidently wrong."""
        import json

        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        f.cache_dir.mkdir(parents=True, exist_ok=True)
        f._meta_path("https://a.example.com/").write_text(json.dumps({
            "url": "https://somewhere-else.example.com/",
            "final_url": "https://x.example.com/",
            "chain": [[301, "https://somewhere-else.example.com/"]],
        }))

        assert f.redirect_for("https://a.example.com/") is None

    def test_an_unpersisted_destination_is_not_remembered(self, tmp_path):
        """Remembering what we failed to write would report a URL as checked
        for this run and as unknown ever after."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        resp = _FakeResponse(url="https://new.example.com/page",
                             history=[_FakeRedirect(301, "https://old.example.com/page")])

        with patch("requests.Session.get", return_value=resp), \
             patch.object(Path, "write_text", side_effect=OSError("disk full")):
            f.get("https://old.example.com/page")

        assert f.redirect_for("https://old.example.com/page") is None


class TestStatus:
    """A repo must be able to tell "the server said no" from "there was no server".

    ``get`` returns None for a 404, a 500, a timeout and a DNS failure alike.
    A repo that read all of those as "this document does not exist" would
    report a citation as rotten because a cable was unplugged.
    """

    def test_a_404_is_remembered_as_a_404(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        resp = _FakeResponse(status_ok=False, status_code=404)
        with patch("requests.Session.get", return_value=resp):
            assert f.get("https://example.com/gone") is None
        assert f.status_for("https://example.com/gone") == 404

    def test_a_server_error_is_not_a_404(self, tmp_path):
        f = _no_sleep(tmp_path)
        resp = _FakeResponse(status_ok=False, status_code=503)
        with patch("requests.Session.get", return_value=resp):
            assert f.get("https://example.com/flaky") is None
        assert f.status_for("https://example.com/flaky") == 503

    def test_a_request_that_never_reached_a_server_has_no_status(self, tmp_path):
        """The case that matters: no response at all means no claim at all."""
        f = _no_sleep(tmp_path)
        with patch("requests.Session.get",
                   side_effect=requests.ConnectionError("no route to host")):
            assert f.get("https://example.com/page") is None
        assert f.status_for("https://example.com/page") is None

    def test_an_untried_url_has_no_status(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        assert f.status_for("https://example.com/never-asked") is None

    def test_a_success_records_its_status(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"body")):
            f.get("https://example.com/ok")
        assert f.status_for("https://example.com/ok") == 200

    def test_refresh_clears_a_stale_status(self, tmp_path):
        """A page that 404'd and then came back must not stay a 404."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        url = "https://example.com/back-again"
        with patch("requests.Session.get",
                   return_value=_FakeResponse(status_ok=False, status_code=404)):
            f.get(url)
        assert f.status_for(url) == 404

        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"it returned")):
            assert f.get(url, force=True) == "it returned"
        assert f.status_for(url) == 200


class TestFragmentsAreNotDocuments:
    """An anchor names a place inside a document, not a different document.

    lint-http cites ~350 passages that live in a handful of RFCs, and every
    one of them carries a ``#section-7.2``-style anchor. Keyed on the raw URL
    that was 350 downloads of a handful of documents — each with a polite
    delay, each byte for byte identical to the last.
    """

    URL = "https://www.rfc-editor.org/rfc/rfc9110.html"

    def test_the_cache_key_ignores_the_anchor(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        assert f._cache_key(self.URL) == f._cache_key(f"{self.URL}#section-7.2")
        assert f._cache_key(f"{self.URL}#section-7.2") == \
            f._cache_key(f"{self.URL}#section-8.1")

    def test_a_second_anchor_is_served_from_cache(self, tmp_path):
        """The point of the whole thing: the network is touched once."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)

        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"the whole RFC")) as get:
            assert f.get(f"{self.URL}#section-7.2") == "the whole RFC"
            assert f.get(f"{self.URL}#section-8.1") == "the whole RFC"
            assert f.get(self.URL) == "the whole RFC"

        assert get.call_count == 1

    def test_the_anchor_is_not_sent_to_the_server(self, tmp_path):
        """It never was — the server cannot see a fragment. Now we don't pretend."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)

        with patch("requests.Session.get",
                   return_value=_FakeResponse(b"body")) as get:
            f.get(f"{self.URL}#section-7.2")

        assert get.call_args.args[0] == self.URL

    def test_what_a_url_led_to_is_known_whichever_anchor_asks(self, tmp_path):
        """Otherwise one anchor reports a 301 and the next reports 'unknown'."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        moved = _FakeResponse(b"body", url="https://example.com/new",
                              history=[_FakeRedirect(301, self.URL)])

        with patch("requests.Session.get", return_value=moved):
            f.get(f"{self.URL}#section-7.2")

        info = f.redirect_for(f"{self.URL}#section-8.1")
        assert info is not None, "a second anchor must not report 'destination unknown'"
        assert info.redirected
        assert info.final_url == "https://example.com/new"


class _Clock:
    """A clock a test drives, so politeness can be asserted without waiting.

    Every one of these tests would otherwise be a real `time.sleep`, which makes
    them slow when they pass and flaky when the machine is loaded. What matters
    is *how long the fetcher decided to wait*, and that is a number, not a
    duration.
    """

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class TestPoliteness:
    def test_two_hosts_do_not_wait_on_each_other(self, tmp_path):
        """The delay is owed to a server, not to the run.

        One global sleep meant a citation of rfc-editor and a citation of
        archive.org were three seconds apart, though neither host had been asked
        anything twice. On a sources file spanning fifty domains that is the
        whole runtime, spent apologising to nobody.
        """
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0,
                          sleep=clock.sleep, now=clock.now)

        with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
            f.get("https://one.example/a")
            f.get("https://two.example/b")
            f.get("https://three.example/c")

        assert clock.slept == [], "different hosts must not delay each other"

    def test_the_same_host_twice_waits(self, tmp_path):
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0,
                          sleep=clock.sleep, now=clock.now)

        with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
            f.get("https://one.example/a")
            f.get("https://one.example/b")

        assert clock.slept == [3.0]

    def test_the_first_request_of_a_run_does_not_wait(self, tmp_path):
        """The delay used to be taken *after* the fetch, so a run that fetched
        one page slept three seconds after the last thing it would ever do."""
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0,
                          sleep=clock.sleep, now=clock.now)

        with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
            f.get("https://one.example/only")

        assert clock.slept == []

    def test_a_failed_request_still_costs_the_host_its_delay(self, tmp_path):
        """Politeness is not a reward for answering.

        The sleep came after a successful fetch and was skipped on the error
        path, so a host returning 500s was the one hit hardest and fastest.

        `retries=0` here so this measures the delay and nothing else; retry
        pacing is its own test below.
        """
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0, retries=0,
                          sleep=clock.sleep, now=clock.now)

        with patch("requests.Session.get",
                   side_effect=requests.ConnectionError("boom")):
            f.get("https://flaky.example/a")
            f.get("https://flaky.example/b")

        assert clock.slept == [3.0]

    def test_a_cache_hit_costs_nothing(self, tmp_path):
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0,
                          sleep=clock.sleep, now=clock.now)
        f._cache_path("https://one.example/a").parent.mkdir(parents=True, exist_ok=True)
        f._cache_path("https://one.example/a").write_bytes(b"cached")

        assert f.get("https://one.example/a") == "cached"
        assert clock.slept == []

    def test_a_slow_response_is_credited_against_the_delay(self, tmp_path):
        """The delay is a rate, not an interval added to each request.

        A server that took four seconds to answer has already had more room than
        a three-second delay was asking for; making the next request wait three
        seconds *more* would punish a slow host for being slow.
        """
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=3.0,
                          sleep=clock.sleep, now=clock.now)

        def slow(*args, **kwargs):
            clock.t += 4.0        # the request itself took four seconds
            return _FakeResponse(b"a")

        with patch("requests.Session.get", side_effect=slow):
            f.get("https://one.example/a")
            f.get("https://one.example/b")

        assert clock.slept == []


class TestSessionAndRetries:
    """Retrying is the fetcher's own, so these assert behaviour, not config.

    They used to read fields off the adapter's `Retry` object — which proved the
    object had been constructed, and nothing about what happened on the wire.
    """

    def _responses(self, *sequence):
        """A `Session.get` that answers each call from `sequence` in turn."""
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            item = sequence[min(len(calls) - 1, len(sequence) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        return get, calls

    def test_a_503_is_retried_and_can_succeed(self, tmp_path):
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0, retries=3,
                          sleep=clock.sleep, now=clock.now)
        get, calls = self._responses(
            _FakeResponse(status_ok=False, status_code=503),
            _FakeResponse(status_ok=False, status_code=503),
            _FakeResponse(b"finally"),
        )

        with patch("requests.Session.get", side_effect=get):
            assert f.get("https://example.com/flaky") == "finally"

        assert len(calls) == 3

    def test_a_404_is_asked_exactly_once(self, tmp_path):
        """A 404 is an answer. Retrying one asks a server three times to confirm
        what it already said, and turns a repo's `RepoNotFound` into a slow
        `RepoNotFound`."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0, retries=3)
        get, calls = self._responses(_FakeResponse(status_ok=False, status_code=404))

        with patch("requests.Session.get", side_effect=get):
            assert f.get("https://example.com/gone") is None

        assert len(calls) == 1
        assert f.status_for("https://example.com/gone") == 404

    @pytest.mark.parametrize("status", [403, 410])
    def test_the_other_answers_are_not_retried_either(self, tmp_path, status):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0, retries=3)
        get, calls = self._responses(_FakeResponse(status_ok=False, status_code=status))

        with patch("requests.Session.get", side_effect=get):
            f.get("https://example.com/x")

        assert len(calls) == 1

    def test_an_exhausted_retry_still_reports_the_status_the_server_gave(self, tmp_path):
        """The distinction this class exists to preserve.

        A 503 that never clears must still be "the server said 503", not "there
        was no server" — a repo reading the second would blame a citation for an
        unplugged cable.
        """
        f = _no_sleep(tmp_path, retries=2)
        get, calls = self._responses(_FakeResponse(status_ok=False, status_code=503))

        with patch("requests.Session.get", side_effect=get):
            assert f.get("https://example.com/down") is None

        assert len(calls) == 3                                   # 1 + 2 retries
        assert f.status_for("https://example.com/down") == 503   # not None

    def test_a_connection_error_that_never_clears_has_no_status(self, tmp_path):
        f = _no_sleep(tmp_path, retries=2)
        get, calls = self._responses(requests.ConnectionError("no route"))

        with patch("requests.Session.get", side_effect=get):
            assert f.get("https://example.com/dark") is None

        assert len(calls) == 3
        assert f.status_for("https://example.com/dark") is None

    def test_every_retry_is_paced_like_every_other_request(self, tmp_path):
        """The reason the retrying is ours and not the adapter's.

        `urllib3` sleeps for its backoff *inside* one call, so its retries never
        reached the rate limiter: a host answering 503 got four requests at
        urllib3's spacing rather than at the configured delay — four times the
        volume, at the moment the host could least take it.

        Here each attempt passes through `acquire`, so the waits are the polite
        delay and the backoff composed, never neither.
        """
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=5.0, retries=2,
                          backoff_factor=1.0, sleep=clock.sleep, now=clock.now)
        get, calls = self._responses(_FakeResponse(status_ok=False, status_code=503))

        with patch("requests.Session.get", side_effect=get):
            f.get("https://slow.example/a")

        assert len(calls) == 3
        # Three attempts, two gaps. Each gap is the delay against the backoff,
        # whichever is longer — never one and then the other.
        assert clock.slept == [5.0, 5.0]

    def test_a_backoff_longer_than_the_delay_wins(self, tmp_path):
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=1.0, retries=2,
                          backoff_factor=10.0, sleep=clock.sleep, now=clock.now)
        get, _ = self._responses(_FakeResponse(status_ok=False, status_code=503))

        with patch("requests.Session.get", side_effect=get):
            f.get("https://slow.example/a")

        assert clock.slept == [10.0, 20.0]     # doubling, and it outranks 1.0

    def test_a_server_that_asks_for_a_wait_gets_it(self, tmp_path):
        """`Retry-After` is the server saying what it needs. It knows what it is
        recovering from and we do not."""
        clock = _Clock()
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0, retries=1,
                          backoff_factor=0.5, sleep=clock.sleep, now=clock.now)
        get, _ = self._responses(
            _FakeResponse(status_ok=False, status_code=503,
                          headers={"Retry-After": "30"}),
            _FakeResponse(b"ok"),
        )

        with patch("requests.Session.get", side_effect=get):
            assert f.get("https://slow.example/a") == "ok"

        assert clock.slept == [30.0]

    def test_a_retry_after_date_is_honoured_too(self, tmp_path):
        """A server under load is more likely to send an HTTP-date than an int;
        reading only the int would ignore exactly those servers."""
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime

        from apysource.http import _retry_after

        when = datetime.now(timezone.utc) + timedelta(seconds=45)
        resp = _FakeResponse(headers={"Retry-After": format_datetime(when)})

        assert 40 <= (_retry_after(resp) or 0) <= 50

    def test_the_adapter_no_longer_retries_behind_our_back(self, tmp_path):
        """Two retry mechanisms would multiply, not compose."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        adapter = f._get_session().get_adapter("https://example.com/")

        assert adapter.max_retries.total == 0

    def test_the_session_is_reused_across_fetches(self, tmp_path):
        """One connection pool, not one connection per citation."""
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)

        with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
            f.get("https://example.com/one")
            f.get("https://example.com/two")

        assert f._session is not None

    def test_the_session_refuses_cookies_rather_than_clearing_them(self, tmp_path):
        """A session keeps a cookie jar; bare `requests.get` did not.

        A site that sets a cookie could otherwise serve the second citation
        something different from the first — and "this URL says X" is the only
        claim this tool makes.

        Refused at the policy, not emptied afterwards. Clearing the jar was
        correct in a serial run and unsafe in a parallel one:
        `CookieJar.clear()` rebinds its backing dict without taking
        `_cookies_lock`, which `add_cookie_header` and `extract_cookies` both
        hold — so one worker could drop a cookie another worker's redirect chain
        had just been issued, and a redirect that loses its cookie lands
        somewhere else entirely. A jar that never stores has nothing to race on.
        """
        import http.cookiejar
        from email.message import Message

        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
            f.get("https://example.com/one")

        session = f._session
        assert session is not None

        # Hand the jar a real Set-Cookie the way urllib would.
        class _Resp:
            def info(self):
                message = Message()
                message["Set-Cookie"] = "sid=abc; Domain=example.com; Path=/"
                return message

        class _Req:
            unverifiable = False
            origin_req_host = host = "example.com"
            type = "https"

            def get_full_url(self):
                return "https://example.com/one"

            def has_header(self, name):
                return False

            def get_header(self, name, default=None):
                return default

            def add_unredirected_header(self, *args):
                pass

        session.cookies.extract_cookies(_Resp(), _Req())

        assert len(session.cookies) == 0, "a Set-Cookie was stored"
        assert isinstance(session.cookies._policy, http.cookiejar.DefaultCookiePolicy)


class TestScratchFilesAreNotLeaked:
    """Unique scratch names fixed a corruption risk and created a leak.

    The old fixed name (`<key>.tmp`) reclaimed itself by being overwritten by
    the next run. A name carrying a pid and a thread id never will, so a write
    that does not reach its rename leaves a full-size orphan that nothing
    collides with, reuses, or cleans.
    """

    def test_a_failed_write_leaves_nothing_behind(self, tmp_path):
        from apysource.http import _write_atomic

        target = tmp_path / "abc123"

        def explode(tmp):
            tmp.write_bytes(b"half a document")
            raise OSError("disk full")

        with pytest.raises(OSError):
            _write_atomic(target, explode)

        assert list(tmp_path.glob("*.tmp")) == []
        assert not target.exists()

    def test_a_successful_write_leaves_nothing_behind(self, tmp_path):
        from apysource.http import _write_atomic

        target = tmp_path / "abc123"
        _write_atomic(target, lambda tmp: tmp.write_bytes(b"whole document"))

        assert target.read_bytes() == b"whole document"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_killed_run_is_cleaned_up_by_the_next_one(self, tmp_path):
        """SIGKILL never runs a `finally`. The sweep is what covers that."""
        import os
        import time as _time

        from apysource.http import TMP_STALE_SECONDS, sweep_stale_tmp

        orphan = tmp_path / "deadbeef.999999.888888.tmp"
        orphan.write_bytes(b"a document a dead process was writing")
        old = _time.time() - TMP_STALE_SECONDS - 60
        os.utime(orphan, (old, old))

        assert sweep_stale_tmp(tmp_path) == 1
        assert not orphan.exists()

    def test_a_live_writers_scratch_file_is_left_alone(self, tmp_path):
        """The sweep must not reach into a concurrent run.

        Two processes sharing a cache directory is the case the unique names
        were for; a sweep that deleted a fresh scratch file would reintroduce
        the corruption from the other direction.
        """
        from apysource.http import sweep_stale_tmp

        live = tmp_path / "deadbeef.123.456.tmp"
        live.write_bytes(b"being written right now")

        assert sweep_stale_tmp(tmp_path) == 0
        assert live.exists()

    def test_the_sweep_leaves_real_cache_entries_alone(self, tmp_path):
        import os
        import time as _time

        from apysource.http import TMP_STALE_SECONDS, sweep_stale_tmp

        body = tmp_path / "0f115db062b7c0dd"
        meta = tmp_path / "0f115db062b7c0dd.meta.json"
        for path in (body, meta):
            path.write_bytes(b"x")
            old = _time.time() - TMP_STALE_SECONDS - 60
            os.utime(path, (old, old))

        assert sweep_stale_tmp(tmp_path) == 0
        assert body.exists() and meta.exists()

    def test_a_fetch_sweeps_once_and_not_on_every_write(self, tmp_path):
        import apysource.http as http_mod

        calls = []
        real = http_mod.sweep_stale_tmp
        http_mod.sweep_stale_tmp = lambda d: calls.append(d) or 0
        try:
            f = _no_sleep(tmp_path)
            with patch("requests.Session.get", return_value=_FakeResponse(b"a")):
                f.get("https://example.com/one")
                f.get("https://example.com/two")
        finally:
            http_mod.sweep_stale_tmp = real

        assert len(calls) == 1, "the sweep is once per run, not once per write"


class TestConcurrentWrites:
    def test_two_writers_do_not_share_a_scratch_name(self, tmp_path):
        """The write is tmp-then-rename, which is atomic only if the tmp is
        private. A fixed name let two CI jobs sharing a cache directory publish
        a half-written body under a name that says it is complete."""
        from apysource.http import _tmp_path

        target = tmp_path / "abc123"
        seen = {_tmp_path(target)}

        import threading as _t
        done = []

        def record():
            done.append(_tmp_path(target))

        t = _t.Thread(target=record)
        t.start()
        t.join()

        assert done[0] not in seen, "two threads must not pick the same tmp name"
