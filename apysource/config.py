# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Configuration loading via apywire dependency injection.

Only CLI entry points should call get_wiring(). Library code receives
all configuration as constructor/function parameters — it never imports
this module.

apywire is a dev-only dependency — the compiled defaults (_defaults.py)
work without it. This module is only reached when the user passes ``-c``.
"""

from pathlib import Path


def get_wiring(config_path: str | Path) -> object:
    """Load wiring from a TOML config file. Path is mandatory."""
    try:
        from apywire import Wiring
        from apywire.formats import toml_to_spec
    except ImportError:
        raise RuntimeError(
            "Custom config requires apywire: pip install apysource[dev]"
        ) from None
    with open(config_path) as f:
        spec = toml_to_spec(f.read())
    return Wiring(spec)
