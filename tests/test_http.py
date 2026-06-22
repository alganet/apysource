# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.http.CachedFetcher."""

from unittest.mock import patch

import requests

from apysource import __version__
from apysource.http import DEFAULT_USER_AGENT, CachedFetcher


class _FakeResponse:
    def __init__(self, content=b"network body", status_ok=True):
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("404 Not Found")


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
        with patch("apysource.http.requests.get",
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
        with patch("apysource.http.requests.get",
                   return_value=_FakeResponse()) as mock_get:
            f.get("https://example.com/h", headers={"Accept": "text/plain"})
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Accept"] == "text/plain"
        assert kwargs["headers"]["User-Agent"] == DEFAULT_USER_AGENT

    def test_request_exception_returns_none_and_does_not_cache(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("apysource.http.requests.get",
                   side_effect=requests.ConnectionError("boom")):
            result = f.get("https://example.com/down")
        assert result is None
        assert not f._cache_path("https://example.com/down").exists()

    def test_http_error_status_returns_none(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("apysource.http.requests.get",
                   return_value=_FakeResponse(status_ok=False)):
            result = f.get("https://example.com/missing")
        assert result is None
        assert not f._cache_path("https://example.com/missing").exists()

    def test_get_bytes_over_network(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        with patch("apysource.http.requests.get",
                   return_value=_FakeResponse(b"\x00\x01rawbytes")):
            result = f.get_bytes("https://example.com/bin")
        assert result == b"\x00\x01rawbytes"

    def test_force_refetches_over_network(self, tmp_path):
        f = CachedFetcher(cache_dir=tmp_path, default_delay=0)
        path = f._cache_path("https://example.com/p")
        path.write_bytes(b"stale")
        with patch("apysource.http.requests.get",
                   return_value=_FakeResponse(b"refetched")) as mock_get:
            result = f.get("https://example.com/p", force=True)
        assert result == "refetched"
        assert mock_get.called  # force bypassed the cache hit
        assert path.read_bytes() == b"refetched"
