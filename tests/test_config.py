# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.config.get_wiring."""

from pathlib import Path

import pytest

from apysource.config import get_wiring

DEFAULTS_TOML = Path(__file__).resolve().parent.parent / "defaults.toml"


def test_get_wiring_loads_real_defaults():
    """get_wiring parses a TOML spec and returns a usable wiring object."""
    wiring = get_wiring(DEFAULTS_TOML)
    # The wiring should expose the CLI command factories defined in defaults.toml.
    assert hasattr(wiring, "check_sources_cmd")
    assert hasattr(wiring, "http_client")


def test_get_wiring_without_apywire_raises_runtime_error(monkeypatch):
    """When apywire is unavailable, get_wiring raises a helpful RuntimeError."""
    # Force `from apywire import ...` to fail even though it is installed.
    monkeypatch.setitem(__import__("sys").modules, "apywire", None)
    with pytest.raises(RuntimeError, match="apywire"):
        get_wiring(DEFAULTS_TOML)


def test_the_shipped_repos_do_not_take_an_anchor_into_a_cache_key():
    """Ask the config that ships, not a copy of it in a test file.

    Every repo test constructs its repo from a ``url_pattern`` literal written
    out by hand, and the wiktionary one read ``(.+)`` for exactly as long as
    ``defaults.toml`` did — so the greedy tail that swallowed ``#English`` into
    the cache key was, by construction, never once exercised. This reads the
    compiled defaults, which is what a user actually gets.
    """
    from apysource._defaults import Compiled

    registry = Compiled().registry()
    cases = [
        ("https://en.wiktionary.org/wiki/Aphrodite#English", "Aphrodite"),
        ("https://en.wikisource.org/wiki/Odyssey#Book_I", "Odyssey"),
        ("https://archive.org/details/somebook#page/n5", "somebook"),
        ("https://www.gutenberg.org/ebooks/11339#toc", "11339"),
        ("https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin#syntax",
         "en-us/web/http/headers/origin"),
    ]

    for url, expected in cases:
        repo = registry.get_repo(url)
        assert repo is not None, f"no repo claimed {url}"
        assert repo.url_to_key(url) == expected, f"{repo.NAME} keyed {url}"
