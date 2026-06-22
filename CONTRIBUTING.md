<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# Contributing to apysource

Thanks for your interest in improving apysource. This guide covers the essentials.

## Development setup

```bash
git clone https://github.com/alganet/apysource && cd apysource
pip install -e .[dev]
```

## Everyday commands

All workflows go through the `Makefile`:

| Command | What it does |
|---|---|
| `make test` | Run the unit tests (`pytest`) |
| `make lint` | Type-check with `mypy` |
| `make coverage` | Run tests with coverage (`slipcover`) |
| `make check` | Full gate: `lint` + `coverage` — **must pass before a PR** |
| `make compile-defaults` | Regenerate `apysource/_defaults.py` from `defaults.toml` |

CI runs `make check` on Python 3.12 and 3.13, so run it locally before pushing.

## Code conventions

- Target Python 3.12+. Add type hints; `mypy` runs in CI.
- Every source file carries an SPDX header (see existing files); the project is
  [REUSE](https://reuse.software/)-compliant.
- Library code takes all configuration as parameters — it never reads global state or imports
  `apysource.config`. Only CLI entry points load wiring.
- Add or update tests for any behavior change. New fixtures live under `tests/fixtures/`.

## Editing configuration defaults

The runtime defaults are compiled from `defaults.toml` into `apysource/_defaults.py` via
[apywire](https://pypi.org/project/apywire/). **Edit `defaults.toml`, never `_defaults.py`
directly**, then run `make compile-defaults` and commit both files.

## Releasing

1. Bump `__version__` in `apysource/__init__.py` (the build reads it dynamically; the crawler
   `User-Agent` tracks it automatically).
2. Update `CHANGELOG.md` — move items from *Unreleased* into the new version section.
3. Tag the release `vX.Y.Z` and push the tag. The `release.yml` workflow builds and uploads to
   PyPI.

## Submitting changes

- Keep PRs focused; describe the motivation and reference any related issue.
- Ensure `make check` passes and the changelog's *Unreleased* section reflects your change.
