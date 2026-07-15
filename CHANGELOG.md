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
- **`check --format json`.** The report as data, on stdout, with everything else on stderr. Each
  failure carries the source and fragment *labels* — what you wrote in the YAML, and what you route
  on: label a fragment with the file that made the claim and the JSON hands that file straight back
  to you. It also carries the URL and the URN, and, for a snippet failure, the diagnosis as fields
  rather than as rendered lines — the passage the source actually contains, how similar it was, and
  which words differ. That was kept structured for exactly this. The verdicts and the exit code are
  computed once and shared with the printed report, so a CI job and a human are never told different
  things about the same run.
- **A section that is not there now says so, and names the ones that are.** A section selector that
  matched nothing extracted the empty string, and the report could only call that `empty extraction
  (0 chars)` — the same words it used for a document that really was empty, and for one that failed
  to download. A typo'd section number and a dead source read identically. Now: `no section matches
  "§ 99.9"; did you mean § 9.9, § 3.9, § 9.1, …?` Suggestions come out of the parsed document and
  nowhere else, and are rendered as selectors you can paste straight back into `section:` — a
  suggestion the document does not contain would be the very thing this tool exists to catch,
  wearing a helpful face. Numbered sections rank by where they live rather than how they look: the
  section you meant is nearly always a sibling, so `§ 1.5` offers `§ 1.1`–`§ 1.4`, not the
  character-similar `§ 19.5`. Two neighbouring cases that also arrived as "empty extraction" are
  fixed with it: a paragraph ordinal past the end now says how many there are, and a section
  selector against a document with no headings at all now says *that*, instead of blaming the
  selector for a document that never had sections.
- **MDN pages now verify against the Markdown MDN is *written in*, not the page it renders.**
  MDN reorganizes constantly, and a moved page keeps answering its old URL with a 301 — so a
  citation that had gone stale still passed, against whatever the redirect led to. The new
  `MdnRepo` resolves an MDN URL to its authored file in `mdn/content`, where a moved page's slug
  is simply gone: the citation fails, and says which slug it could not find. Because authored
  Markdown is not what a reader sees, quotes are matched against a rendering of it — KumaScript
  macros expand the way the site expands them, so `{{HTTPHeader("Origin")}}` is the word `Origin`
  and you can still quote what the browser showed you. Text a macro *generates* — the
  browser-compatibility and specifications tables, live samples — is not in the source file,
  cannot be reconstructed from it, and is **marked rather than quietly deleted**: deleting it
  would sew the surrounding words into a sentence the page never showed, and a citation that
  invented that sentence would have passed. Only `en-US` is handled; translations live in a
  different repository, and mapping them here would report every live, correctly-cited page in a
  locale as missing.
- **A repo now fetches a document it does not have.** Previously a cold cache made `check` fall
  back to the generic fetcher without a word, so the snippet was verified against the rendered web
  page instead of the repository the citation names — a different document, checked with no signal
  that anything had changed, and the answer flipped depending on what happened to be in the cache.
  A repo that matches a URL now owns it: `check` crawls the document on a miss, `--refresh`
  re-crawls it (it previously had *no effect* on a repo, so a repo could not be refreshed at all),
  and the new `--no-crawl` reports the miss honestly rather than fetching something else. A repo
  that matches a URL but has no crawler still falls back — but the new `Repo documents` check
  names it out loud, and `--strict-repos` turns that warning into a failure.
- **A repo can now say that a document does not exist.** `RepoNotFound` reports it as its own
  failure — `mdn: no such document: en-us/web/http/headers/origin` — where a missing page used to
  arrive as `empty extraction (0 chars)`, indistinguishable from a document that was merely empty,
  blamed on the citation rather than on the page, and stuck that way until the next `--refresh`.
  Nothing is written to the cache, so a page that returns upstream verifies on the next run with
  no flag at all. A fetch that merely *failed* raises `RepoUnavailable` and is reported as an
  unknown: a timeout is not an absence, and saying so would be a confident wrong answer.
- **Repos can set their own crawl delay.** `crawl_delay` (defaulting from the registry's
  `default_crawl_delay`) is passed per request, so a CDN-backed repo can be read briskly without
  making every other source a rude crawler as a side effect.
- A failed snippet now explains itself. `check` and `locate` find the passage the source
  actually contains and show what differs — a word-level diff naming the words the citation
  lacks, or, when the words are right and only the typography is wrong, a plain
  "differs only in case" (or whitespace, or inline markup) plus the source's exact wording.
  Previously "snippet not found" was the entire diagnosis, and finding out why meant fetching
  the document and diffing it by hand.
- Redirects are now surfaced instead of being followed silently. A source whose URL has moved
  still verifies — against the document it was forwarded to — so `check` reports a new
  `Source URLs` check naming the new destination, `locate`/`add` note it on stderr, and
  `--strict-redirects` turns the warning into a failure. A page cached before this existed has
  no recorded destination; that is reported as *unknown*, not passed over as clean, and
  `--refresh` resolves it. A URL that moved to a page which is now **gone** keeps its redirect
  chain, so the report can say the move led nowhere rather than only "could not fetch".
- `--refresh` flag on `check`, `locate`, and `add` to bypass the HTTP cache and re-fetch sources.
- `AUDIT.md` — a full-breadth audit of the codebase, tests, and documentation.
- `CHANGELOG.md`, `CONTRIBUTING.md`, and `SECURITY.md`.
- `ruff` linting/formatting, wired into `make lint`/`make format` and the `make check` gate.

### Changed
- **A failure is now reported by the names its author gave it**, not by the slugified URN the
  loader made of them — which was printed twice, once as the group header and once as the line
  prefix. `urn:apysource:fragment_mdn_origin_stale_pre_redirect_url_mdn_stale` is now
  `MDN: Origin (stale pre-redirect URL)` with `mdn_stale` under it, and the URL beside it. The slug
  also mangled separators, so a fragment labelled by file path — how a build routes a failure back
  to the code that made the claim — came out with its slashes eaten, and grepping the report for it
  did not work. The URN is untouched in the provenance graph, where it is the subject and the
  stable identity; it is simply no longer what a person is made to read.
- **`crawl()` is now part of the `BaseRepo` contract** rather than a convention nothing called.
  Repos that implement it set `supports_crawl = True`, and its `delay` argument — which every
  built-in repo accepted and then ignored — is now honored. A custom repo written before this
  keeps working unchanged; it simply has no crawler, and says so when it falls back.
- **Breaking, for anyone calling a built-in `crawl()` directly.** `WiktionaryRepo.crawl()` returned
  `None` for a word Wiktionary does not have — the same answer it gave for "already cached", two
  opposite outcomes sharing one indistinguishable value. It now raises `RepoNotFound`.
  `ArchiveRepo`, `GutenbergRepo` and `WikisourceRepo` likewise raise `RepoNotFound` /
  `RepoUnavailable` where they returned error dicts or `None`. They also no longer leave anything
  behind on failure: Wikisource created the page directory before knowing the page existed, and
  Gutenberg wrote an empty chapter index for a book it could not parse — caching the failure as a
  success, and leaving every citation into it failing forever as an "empty extraction".
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
