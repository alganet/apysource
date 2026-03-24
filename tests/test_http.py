# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.http.CachedFetcher."""

from apysource.http import CachedFetcher


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
