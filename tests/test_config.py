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
