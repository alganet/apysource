<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Snippet verification now requires the **entire** quoted text to appear in the source.
  Previously only the first 80 characters were compared, so a citation whose opening matched
  but whose tail diverged would pass — the exact misquotation the tool exists to catch.
- A trailing ellipsis (`...` or the Unicode `…`) now consistently marks an intentionally elided
  quote and switches to prefix matching; the Unicode form was previously not recognized.
- `part_of` now resolves to a parent source defined **later** in the same YAML file; forward
  references were previously dropped silently.
- RDF file classification (`shapes`/`inferred`) now matches the file name rather than the full
  path, so a project directory containing those words no longer hides every `.ttl` file.

### Added
- Redirects are now surfaced instead of being followed silently. A source whose URL has moved
  still verifies — against the document it was forwarded to — so `check` reports a new
  `source urls` check that names the new destination, `locate`/`add` note it on stderr, and
  `--strict-redirects` turns the warning into a failure. A page cached before this existed
  reports its destination as *unknown* rather than clean; `--refresh` resolves that.
- `--refresh` flag on `check`, `locate`, and `add` to bypass the HTTP cache and re-fetch sources.
- `AUDIT.md` — a full-breadth audit of the codebase, tests, and documentation.
- `CHANGELOG.md`, `CONTRIBUTING.md`, and `SECURITY.md`.
- `ruff` linting/formatting, wired into `make lint`/`make format` and the `make check` gate.

### Changed
- The crawler `User-Agent` is now derived from the package version (`apysource/<version>`) so it
  tracks releases automatically, instead of the stale hard-coded `apysource/1.0`.
- The package version now lives in `apysource.__version__` and is read dynamically by the build,
  giving a single source of truth.
- Which CLI commands accept a YAML graph as input is now a per-command property instead of a
  hard-coded name list, fixing a latent crash if `validate` were given a `.yaml` argument.

## [0.3.1]

- Baseline release captured at the time this changelog was introduced. Earlier history was not
  recorded in release notes; see the git log for prior commits.

[Unreleased]: https://github.com/alganet/apysource/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/alganet/apysource/releases/tag/v0.3.1
