<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# Security Policy

## Supported versions

apysource is pre-1.0 software. Security fixes are applied to the latest released version only.

## Reporting a vulnerability

Please report suspected vulnerabilities privately rather than opening a public issue.

- Preferred: open a [GitHub security advisory](https://github.com/alganet/apysource/security/advisories/new).
- Alternatively, email the maintainer at <alganet@gmail.com>.

Include a description, reproduction steps, and the affected version. You can expect an initial
acknowledgement within a few days. Once a fix is available, it will be released and the advisory
published with credit to the reporter (unless anonymity is requested).

## Scope notes

apysource fetches remote URLs and caches their content on disk. When running it against untrusted
source definitions, be aware that:

- TLS certificate verification is on by default; disabling it (`verify=False`) is unsafe on
  untrusted networks.
- Cached responses are stored as raw bytes under the configured cache directory and are served
  from disk on subsequent runs until refreshed.
