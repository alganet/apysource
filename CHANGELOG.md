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
- **RFC page furniture and hyphen-wrapped tokens no longer leak into a citation.** Two
  things survive into the extracted text of a paginated RFC and cannot be quoted around:
  - The **running page header** (`RFC 9110  HTTP Semantics  June 2022`), repeated on every
    page, is now removed. It carries no `[Page N]` marker for the footer rule to catch, so
    it is stripped keyed on the form feed it always follows — precise enough that a line of
    body prose of the same shape is left untouched.
  - A **token split across the 72-column wrap at a hyphen** (`ISO-\n   8859-1`; a field
    name, an ABNF rule name, a literal GUID) read as `ISO- 8859-1` — a space the document
    does not contain — and could not be cited whole. It is now rejoined to `ISO-8859-1`.
    Only a single hyphen between two alphanumerics is joined, so a line ending `--` (an
    em-dash) is left alone.
- **An appendix is addressable by its letter.** An `Appendix A.  Pseudocode` heading was
  parsed into a node but could never be selected: `§ A` compares a title's leading
  designator, and that was digits-only, so `A` matched nothing. The designator now admits
  an appendix letter (`A`, `A.1`), but only when a period follows it — a plain heading
  like `Terminology` is not mistaken for a designator `T`. Appendices consequently gain a
  `§ A` label and can be offered as "did you mean" candidates.

## [0.5.0] - 2026-07-14

### Added
- **A source can be named instead of addressed.** A new top-level `patterns` key maps a name
  like `RFC 9110` to the URL it denotes, so a source entry may now carry a `label` and no `url`.
  Your patterns are tried before the shipped ones, an entry with a `url` beats both, and within
  an entry every key you write wins over the template — name the family for the URL, then say the
  `title` or the `part_of` the family cannot know.

  This lives here, and not in a citation generator, for one reason: apysource already owns every
  link in the chain from a URL onward — repo claiming, fetching, caching, format detection, section
  trees, redirect surfacing — and name→URL was the missing *first* link. A generator that minted
  rfc-editor URLs itself was claiming to know what an RFC is, and it does not.

  A pattern is not a repo. They are inverse directions: `url_pattern` *parses* a URL, a pattern's
  `match` *generates* one, and a pattern's output is a repo's input. A pattern is pure data with no
  fetch, no cache, and no 404-vs-outage; it cannot be folded into a repo, because `url_to_key` is
  deliberately non-injective and has no inverse.

  A `{field}` a pattern's regex never captures is refused at load, not at the 404 six weeks later.
- **Six families ship, and five of them are declared by their repos.** `RFC NNNN` belongs to
  `patterns.py` precisely *because* no repo claims rfc-editor — that gap is what patterns exist for.
  `MDN <page>`, `Gutenberg <id>`, `Wikisource <page>`, `Wiktionary <word>` and `Archive <item>` are
  declared by the repo that fetches them, via `BaseRepo.NAME_MATCH` / `CANONICAL_URL`, because how
  you name an MDN page is MDN's knowledge. A third-party `BaseRepo` subclass gets naming by
  declaring two strings, and a named repo source is claimed by its repo exactly as a written URL is.

  A family states its host twice — once as a template that builds a URL, once as the matcher that
  claims one — and that cannot be deduplicated: the matchers carry knowledge a template cannot
  express (`(?i:en-US)` accepts `en-us` while excluding `/fr/docs/`; Gutenberg's `(\d+)` admits only
  an ebook number, and matches without the `www.` its canonical URL carries). The two halves are
  bound by a round-trip test instead: mint each family's example, and the repo that declared it must
  claim and key what came out.
- **`apysource add` takes a name where it takes a URL.** `apysource add sources.yaml "RFC 9110"
  "<snippet>"` resolves the name through the same patterns `check` will use on the file it is
  writing, so the two cannot disagree. The entry it writes carries only the name: writing the
  resolved URL back would defeat the point of naming a family.
- **`apysource.load_sources`** returns the sources file as data with names resolved — entries with
  their URLs filled in, plus `resolve(name)` for a name that appears in no entry at all. This is the
  seam a citation generator needs; `graph_from_data` answers "what does this file mean" and a graph
  is the wrong shape for a tool that has to *write* one. `resolve` returns `None` rather than
  raising, because the caller is the one holding the file and line the name came from.
- **`apysource` exports its public API.** `from apysource import check_graph, graph_from_data` is
  what the README has always said and what `__init__.py` never did — it defined `__version__` and
  nothing else, so the documented import raised `ImportError`.
- **The `#section-7.2` in a citation's URL is now read as targeting.** It always was
  targeting — the author wrote down where in the document they were looking — and nothing
  read it: `rfc9110.html#section-7.2` was verified against the whole of RFC 9110, all 502,907
  characters of it. An anchor now scopes the check to the section it names, so a quote that has
  drifted to a different section is caught instead of passing because the words appear *somewhere*.
  Two forms are understood: the rfc-editor `#section-7.2` convention, and any anchor that names a
  **heading** in the document (WHATWG's `#origin-header` is on an `<h3>`, so it resolves to `§ 3.2`).
  Anything else is **left alone, deliberately**: in the Fetch spec `#cors-safelisted-request-header`
  sits on an inline `<dfn>`, and narrowing to it would cut the scope down to a two-word term and
  fail every honest citation of the sentence around it. An anchor says where the author was
  *looking*, not always what they meant to quote, and a guess of ours must never be able to condemn
  a citation. An explicit `section:` or `selector:` always wins — a statement outranks an inference.
  The one exception to "never fail on a guess" is `#section-99.9`, which is unambiguous: a document
  that has no such section is told so, rather than quietly widening back to the whole text and
  passing.
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

### Changed
- **An unknown top-level key in a sources file is now refused.** It was silently ignored. With
  `patterns:` meaning something, a typo'd `pattern:` would mint nothing and leave every url-less
  source below it failing with a message about entirely the wrong thing. Only `sources` and
  `patterns` are known.
- **`graph_from_data` takes the patterns to mint with as an argument**, defaulting to the file's own
  plus the shipped ones. A caller that has already compiled them (`load_sources` has) passes them in
  rather than making the loader compile every regex in the file a second time.
- **The sources vocabulary moved to `apysource.schema`** — `SOURCE_KEYS`, `FRAGMENT_KEYS`,
  `TARGETTING_KEYS` and the two refusals. `yaml_input` re-exports them, so nothing that imported them
  from there has to change. They moved because `patterns` needs them too, and that made a cycle
  survivable only by hiding an import inside a function body. An import you have to hide is telling
  you the dependency is on the wrong thing: neither module wanted the *other*, both wanted the
  vocabulary, and the vocabulary depends on nobody.
- **`add` labels a source by its title, not by its first heading.** It called every RFC it ever
  saw `1. Introduction`, because it asked the format for its first *section heading* — and for an
  RFC that is always § 1. An RFC states its title in its header block, an HTML page in `<title>`,
  a Markdown file in its front matter; a flat text file states none, and now says so instead of
  offering up a heading that is not a title. `add` falls back to the URL, which is at least true.
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

### Fixed
- **`apysource add <name>` fetched the wrong document when an entry pinned that name to its own URL.**
  It minted the URL from the pattern and ignored the entry, so a file pinning `RFC 9110` to
  datatracker had its snippet located in rfc-editor's *plain text* and the resulting locator written
  into the *HTML* entry — a targetter `check` would then apply to a document it was never measured
  from. `add` now resolves through `complete()`, the same entry-wins rule `check` uses.
- **`apysource add` no longer overwrites a file it cannot read.** A sources file that existed but had
  no top-level `sources:` (a typo'd `source:`, say) was treated as empty and then replaced, costing
  the author everything else in it. It is refused instead.
- **A pattern template with an unbalanced or an escaped brace was mis-validated.** The load-time check
  scanned with a regex instead of `string.Formatter`, so `https://e.org/{n}/{` passed it and then
  raised out of `str.format` at mint time — the very deferred failure the check exists to prevent —
  while a correctly escaped `{{lit}}` was falsely refused.
- **An optional capture group that did not match interpolated the word `"None"` into the URL.**
  `^RFC (?P<n>\d+)(?P<sfx>bis)?$` minted `.../rfc9110None.txt` and fetched it. A group that did not
  participate is the empty string now.
- **`Archive <item>` accepted a name with a slash in it and then fetched a different item.** The
  family allowed `.+` while `url_pattern` stops the key at the first `/`, so `Archive foo/bar` was
  claimed, keyed as `foo`, and verified against the wrong document with nothing to say so.
- **`SourceSet.entries` no longer aliases the data it was given.** `complete()` returned the caller's
  own dict when the entry already had a URL and a fresh one when it minted — two ownership rules for
  one return type, so a consumer editing a resolved entry silently edited the document it had read.
- **A section selector now names the section the passage is actually in.** `locate` looked for
  *the shortest selector that extracts text containing the snippet* — and that objective quietly
  guarantees the wrong answer, because a section always contains its subsections' text and always
  has the shorter label. A passage living in § 4.2.1 was cited as § 4.2. On RFC 9110 that happened
  to **157 of 271** paragraphs; every one of them round-tripped, which is why nothing caught it.
  It is not a cosmetic imprecision: the scope the citation is checked against became the whole
  parent section, so a quote that drifted from § 4.2.1 to § 4.2.5 would still verify — exactly the
  rot that section targeting exists to catch. The objective is now the shortest selector that
  *resolves to the passage's own section*, which also disambiguates repeated headings for free: a
  bare title that lands on the first of two is rejected, and the ancestor path that reaches the
  right one is used instead.
- **`locate` says when a passage appears in more than one section.** A specification repeats
  itself — "The response MUST include the following header fields:" sits under both § 10.2.7 and
  § 10.3.5 of RFC 2616 — and `locate` can only pick one. Picking in silence was a quiet claim that
  the passage lives there, and the citation would go on passing even after the passage was removed
  from the section its author actually meant, because it survives in the other.
- **An HTML page is now checked as a reader sees it, not as markup.** A fragment with no
  `selector:`/`section:` was matched against the raw HTML, so a sentence lifted from a
  `<meta name="description">` — or from inside a `<script>` — verified against a page whose prose
  said something else entirely, while the prose a reader *had* seen did not match at all. Exactly
  inverted: it passed text nobody was ever shown and failed text they were. Extraction with no
  locator now yields the rendered text, with `<head>`, `<script>` and `<style>` left out of it.
- **`add` no longer writes citations that `check` rejects.** `HtmlFormat.extract` rendered a
  selected element with `get_text(strip=True)`, which joins stripped strings with nothing:
  `<p>The <code>Origin</code> request header…</p>` came out as `TheOriginrequest header…`. But
  `locate` — the function that *generates* the selectors `extract` consumes — read the same page
  with a plain `get_text()`. So `apysource add` emitted a fragment that `apysource check` failed on
  the very next run, for any sentence containing a link, `<code>` or `<em>`: most prose in a web
  specification. Both now render through one function, and `locate` additionally *proves* the
  selector it returns leads back to the snippet before returning it, so no future divergence can
  reopen this. Whitespace is inserted only at block boundaries, where a browser also breaks the
  line, and never between inline elements — `<b>Sub</b>string` stays `Substring`, because inventing
  a space would manufacture a passing citation for prose the page never showed.
- **`locate` on a large document was quadratic.** It re-normalized a growing prefix of the whole
  file once per line: 11 seconds on a 422 KB RFC, which is exactly the kind of document this tool
  exists to cite. It is now a single pass — 0.011 s, same answer.
- A whole-document RFC citation no longer trips over pagination. `[Page 42]` footers and form feeds
  were left in the text a snippet was matched against, so a sentence straddling a page break could
  not be quoted at all; `sections` had always removed them, and whole-document extraction now
  agrees.
- **A snippet is now looked for in the whole source, not in the first 100,000 characters of it.**
  RFC 9110 is 502,907 characters, so the check read a fifth of it: a real citation into its
  status-code definitions was reported as `snippet not found in extracted content` — a flat claim
  about a document the check had never read to the end of. Past that cap the check was not merely
  wrong but *inert*, failing accurate and misquoted citations alike, so it distinguished nothing
  in exactly the region a large specification keeps its detail. The cap bought nothing: the
  substring test is linear, and diagnosing a miss across the whole of RFC 9110 takes a tenth of a
  second. Every snippet test patched out `load_text`, which is the function that did the
  truncating, so none of them could have seen it.
- **A URL fragment no longer makes a second copy of the same document.** The cache was keyed on
  the raw URL, so `rfc9110.html`, `rfc9110.html#section-7.2` and `rfc9110.html#section-8.1` were
  three separate documents — three downloads, three polite delays, three cache entries, byte for
  byte identical. A fragment is resolved by the client and never sent to a server; it names a
  place *inside* a document, and cannot name a different one. Repos are now handed the document
  too, so a repo whose pattern ends in a greedy `(.+)` — as `WiktionaryRepo`'s did — no longer
  takes `#English` into its cache key and keeps Aphrodite a second time under
  `aphrodite#english.txt`. Every repo is covered at the resolution seam, including one written by
  someone else. Citations keep the fragment they were written with: it is what the report prints,
  and it is the targeting the author already gave us.

## [0.4.0] - 2026-07-14

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

[Unreleased]: https://github.com/alganet/apysource/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/alganet/apysource/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/alganet/apysource/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/alganet/apysource/releases/tag/v0.3.1
