<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# apysource

[![PyPI](https://img.shields.io/pypi/v/apysource)](https://pypi.org/project/apysource/)
[![Tests](https://github.com/alganet/apysource/actions/workflows/test.yml/badge.svg)](https://github.com/alganet/apysource/actions/workflows/test.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![License: ISC](https://img.shields.io/badge/license-ISC-green)](LICENSE)

AIs hallucinate citations. Link rot silently breaks the real ones. Silent edits change what your sources actually say.

apysource is an automated verifier: define what text you expect at which URL, and it fetches, caches, and checks that it still matches. Use it as a CI gate, a research notebook guard, or a self-correction layer for AI-generated content — the tool can verify its own output.

## Install

```bash
pip install apysource
```

Requires Python 3.12+.

## Quick start

### 1. Define your sources

Create `sources.yaml`:

```yaml
sources:
  - label: "UN Charter"
    url: "https://www.un.org/en/about-us/un-charter/full-text"
    type: text/html
    fragments:
      - label: "Preamble"
        section: "Preamble"
        snippet: "to save succeeding generations from the scourge of war"
      - label: "Article 2 principles"
        section: "Article 2, paragraph 1"
        snippet: "The Organization and its Members, in pursuit of the Purposes stated in Article 1, shall act in accordance with the following Principles"
```

### 2. Check

```bash
apysource check sources.yaml
```

apysource fetches the page (caching it on disk), finds the section by name, and checks that your snippet appears in the result. Cached pages aren't re-fetched on subsequent runs.

```
======================================================================
  apysource Verification Report
======================================================================

  [PASS] Fragments: cache resolution............. 2/2

  [PASS] Fragments: content extraction........... 2/2

  [PASS] Fragments: snippet verified............. 2/2

  [PASS] Source URLs............................. 1/1

  ======================================================================
  Summary: 4 PASS, 0 FAIL, 0 WARN
  EXIT CODE: 0 (all checks passed)
  ======================================================================
```

`Source URLs` counts *URLs*, not fragments — the two fragments above cite one
document. It reports a citation whose URL has **moved**: redirects are
followed, so such a source still verifies, against whatever it was forwarded
to, which quietly turns "this URL says X" into "wherever this URL leads says
X". A moved source warns (exit 0) and names its new home; `--strict-redirects`
fails on it instead.

It also reports a URL whose destination it has **no record of** — a page cached
before apysource tracked this. That is not the same as a clean URL, and it is
not reported as one: run `--refresh` to find out which it is.

When a snippet fails, apysource shows the passage the source actually contains:

```
  [FAIL] Fragments: snippet verified............. 1/2
         urn:apysource:fragment_rfc_9110_method_safe/ (1)
           ...: snippet not found in extracted content
             snippet differs only in punctuation, § 9.2.1
               source says: Request methods are considered "safe" if their
               defined semantics are essentially read-only;
```

### 3. Discover

Use `locate` to find how apysource would target a snippet, then `add` to save it:

```bash
# Find where a snippet lives in a page
apysource locate "https://www.un.org/en/about-us/un-charter/full-text" \
  "to save succeeding generations from the scourge of war"

# Add it directly to your sources file
apysource add sources.yaml "https://www.un.org/en/about-us/un-charter/full-text" \
  "to save succeeding generations from the scourge of war" \
  --label "Preamble"
```

`locate` outputs a YAML fragment you can paste directly. `add` writes it to the file for you. Use `locate --ttl` for Turtle output with full Web Annotation alignment.

### Targeting content

apysource supports several ways to pinpoint where in a document your snippet lives:

| Targetter         | Key        | Example                  | Best for                                             |
|-------------------|------------|--------------------------|------------------------------------------------------|
| **Section**       | `section`  | `"Chapter I, Article 1"` | Structured documents (HTML, Markdown, Wikitext)      |
| **CSS selector**  | `selector` | `"div.content p"`        | HTML pages                                           |
| **Line range**    | `lines`    | `"40-41"`                | Plain text                                           |
| **Repo location** | `location` | `"chapter:1"`            | Repository modules (Gutenberg, Wikisource, etc.)     |

**Section selectors** are the most versatile — they work across HTML, Markdown and Wikitext, and so across every RFC, which arrives as HTML. They support roman numeral equivalence (`Chapter IV` = `Chapter 4`), nested paths (`Chapter I, Article 1, paragraph 2`), and quoted titles (`'The Fox and the Grapes'`).

**CSS selectors** target HTML elements directly. Useful when section headings aren't available or you need a specific element.

**Line ranges** extract by line number (1-based, inclusive). Useful for plain text — a document with no structure to name.

If no targetter is given, apysource checks the full page text for your snippet.

## YAML schema

Each YAML file has a top-level `sources` list. Each source has nested `fragments`.
An optional top-level `patterns` list says how to turn a *name* into a source, and
an optional top-level `base` names the identifiers the file mints.

A fragment must say **at least one** of `snippet`, `section` or `selector` — those
are what tie it to a place in its source. Without one it quotes nothing, so there
is nothing to verify, and the file is refused rather than loaded.

### Source properties

| Key         | What it does                                                                                                                                  |
|-------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `label`     | Name of the source (required)                                                                                                                 |
| `url`       | URL to fetch — required, unless a `patterns` entry mints one from the label                                                                   |
| `type`      | IANA media type: `text/html`, `text/plain`, `text/markdown`, etc. Short names (`html`, `plain-text`) also accepted. Auto-detected if omitted. |
| `language`  | Language code, RFC 5646 (metadata)                                                                                                            |
| `title`     | Document title (metadata)                                                                                                                     |
| `date`      | Publication or access date (metadata)                                                                                                         |
| `part_of`   | Parent source label (for hierarchical sources)                                                                                                |
| `isbn`      | International Standard Book Number                                                                                                            |
| `doi`       | Digital Object Identifier                                                                                                                     |
| `publisher` | Publisher name                                                                                                                                |
| `edition`   | Edition or version                                                                                                                            |
| `license`   | License URI                                                                                                                                   |

### Fragment properties

| Key          | What it does                                                 |
|--------------|--------------------------------------------------------------|
| `label`      | Name of the fragment (required)                              |
| `snippet`    | The text you expect to find                                  |
| `selector`   | CSS selector to narrow extraction (HTML)                     |
| `lines`      | Line range to extract, e.g. `30-35`                          |
| `section`    | Human-readable section selector, e.g. `Chapter I, Article 1` |
| `location`   | Repo-specific location hint (e.g. `chapter:1`)               |
| `page_start` | Starting page number (for print sources)                     |
| `page_end`   | Ending page number (for print sources)                       |
| `cited_by`   | Where this claim is made — see below                         |

### Patterns: a name instead of a URL

Writing 350 entries for RFC 1..9999 by hand is silly. A pattern names a *uniform
family* — a URL shape and a media type — and every member of it resolves without
an entry of its own:

```yaml
sources:
  - label: RFC 9110        # no url: a pattern mints it
    fragments:
      - label: host_header
        section: "7.2"
        snippet: "A user agent MUST generate a Host header field"

  - label: MDN Web/HTTP/Reference/Headers/Origin
  - label: Gutenberg 2701
```

Six families ship, one for each repo: `RFC <n>`, `MDN <page>`, `Gutenberg <id>`,
`Wikisource <page>`, `Wiktionary <word>`, `Archive <item>`. A family of your own
is three lines, and it is not a release of this package:

```yaml
patterns:
  - match: '^W3C (?P<slug>[a-z0-9-]+)$'
    source: {url: "https://www.w3.org/TR/{slug}/", type: text/html}
```

Your patterns are tried before the shipped ones, and an entry with a `url` beats
both — so pinning `RFC 9110` to a mirror of your own is one entry. Within an entry, every
key you write wins over the template: name the family for the URL, then say the
`title` or the `part_of` the family cannot know.

A `{field}` the regex never captures is refused at load, not at the 404 six weeks
later.

Patterns are for uniform families. A book needs an ISBN, a publisher, an edition;
a chapter needs a `part_of`. Those have biographies, and a biography goes in an
entry.

#### A pattern is not a repo

They are inverse directions, and they compose:

```
name --[pattern]--> canonical URL --[repo]--> cached document
     ^ generates a url             ^ parses one
```

A pattern's output is a repo's input. A pattern is pure data — one string
substitution, no fetch, no cache, no 404-vs-outage. A repo is the machinery behind
the URL: crawling, caching, and for MDN a rewrite to the authored Markdown in
`mdn/content` with the KumaScript macros rendered.

So they sit on opposite sides of the URL, and neither replaces the other. Every
family that *ships* is declared by the repo that fetches it, because how you name
an MDN page is MDN's business and how you name an RFC is rfc-editor's. Name one,
and it is claimed by its repo exactly as a URL you typed would be — which is also
what keeps the two halves honest, since a family that minted a URL its own repo
did not claim would be caught by nothing but a failing citation.

A pattern is what you write when a uniform family has **no repo to claim it**.
`W3C <slug>` above is one: nothing special is needed to read a W3C page — the
generic fetcher gets it and the HTML reader reads it — and all that was missing
was the step from a name to a URL.

Adding a repo is a Python class and a release. Adding a pattern is three lines of
your own YAML.

### Who cites it

A source that has moved on only matters because something *relies* on what it
used to say. `cited_by` names that something, so a failure can point at the
thing that has to change:

```yaml
fragments:
  - label: client_host_header
    section: "§ 3.2"
    snippet: "A client MUST send a Host header field ... in all HTTP/1.1 request messages."
    cited_by:
      - file: src/rules/client_host_header.rs
        line: 29
```

When the quote stops matching, the report ends with the place to open:

```
  [FAIL] Fragments: snippet verified............. 2/3
         RFC 9112 (https://www.rfc-editor.org/rfc/rfc9112.html) (1)
           client_host_header: snippet not found in extracted content
             closest match (94% similar, § 3.2)
               source says: A client MUST send a Host header field ... request messages.
               not in that passage: response
             cited by src/rules/client_host_header.rs:29
```

`file` is required; `line` is optional, because not every citation is made at a
line of a file — a footnote cites too. In the graph each entry becomes an
`sv:CiteSite` linked by `prov:wasDerivedFrom` back to the fragment: the citing
passage is derived from the cited one, not the reverse.

### Naming what the file mints

Your sources file *is* an RDF graph — `apysource emit sources.yaml -o out.ttl`
writes it out as one, and `check --provenance` writes a record of a run.

Identifiers for those are minted from labels, so by default two projects that both
cite RFC 9110 § 7.2 mint the same `urn:apysource:fragment_rfc_9110_7_2`. That is
harmless while the graph stays on your machine, and a merge hazard once it does
not: RDF graphs are built to merge, and two citations that collide become one.

Set a top-level `base` to an IRI you control and identifiers are minted under it:

```yaml
base: https://example.org/citations
sources:
  - label: RFC 9110
```

`emit` warns when it is about to write the default identifiers out. If you never
publish the graph, you can ignore it.

## Library

`apysource check` is one caller of the checks; your own generator can be
another, without shelling out or reaching into private modules.

```python
from apysource import check_graph, graph_from_data
from apysource.verification import failed, print_report

graph = graph_from_data({"sources": [...]})   # load_yaml, minus the file
results = check_graph(graph)                  # the same checks the CLI runs
print_report(results)
raise SystemExit(1 if failed(results) else 0)
```

`check_graph` returns results; it never prints and never exits. What a failure
*means* is the caller's decision. `json_report` is there too, and it is the
same one `--format json` uses.

A generator that *writes* a sources file needs the other direction — the entries
back as data, and an answer for a name that appears in no entry at all:

```python
from apysource import load_sources

sources = load_sources(path)          # or None: the shipped patterns still resolve
sources.entries["RFC 9110"]["url"]    # entries come back with their url filled in
sources.resolve("RFC 9112")           # a name nobody wrote an entry for — or None
```

`resolve` returns `None` rather than raising. You are the one holding the file and
the line the name came from, so the refusal is yours to write.

## CLI

```bash
apysource [-c config.toml] <command> [args...]
```

| Command                                          | What it does                                                    |
|--------------------------------------------------|-----------------------------------------------------------------|
| `check [sources.yaml\|.ttl] [--provenance f.ttl]` | Fetch, extract, and verify all snippets                         |
| `locate <url> <snippet>`                         | Find a snippet in a page, show the targetter                    |
| `add <file> <url-or-name> <snippet>`             | Locate a snippet and add it to a YAML file                      |
| `emit <sources.yaml\|.ttl> [-o out.ttl]`          | Write the citations out as RDF (turtle, json-ld, nt, xml)       |
| `validate [sources.yaml\|.ttl]`                   | Parse and check against the SHACL shapes                        |

`check`, `emit` and `validate` take either front-end: a `.yaml` sources file or a
`.ttl` one. Without `-c`, apysource uses built-in defaults (all built-in repos enabled). Pass `-c config.toml` to customize repos and HTTP settings (requires `pip install apysource[dev]`).

Pass `--provenance file.ttl` to `check` to write a self-contained PROV-O graph recording which fragments were verified, when, and by which run.

SHACL validation needs `pip install apysource[shacl]`; without it the check reports SKIPPED rather than quietly passing.

Fetched pages are cached on disk and reused indefinitely (no time-based expiry). Pass `--refresh` to `check`, `locate`, or `add` to bypass the cache and re-fetch. See [docs/advanced.md](docs/advanced.md#caching-and-freshness).

Pass `--strict-redirects` to `check` to fail, rather than warn, when a source URL has moved. Note that a page cached before apysource recorded redirect destinations reports its destination as *unknown*, not as clean — `--refresh` resolves that.

### Crawling a large collection

`check --workers N` fetches several documents at once, and defaults to 8. The
polite delay is enforced **per host**, so this parallelises a run *across* the
sites it cites and never *within* one of them — a sources file naming twenty
domains gets twenty times the throughput, while no single server is asked for
more than it was before. A file citing one host is paced exactly as it was,
whatever `N` says.

It changes speed and nothing else. Fetching happens up front and returns nothing;
every check, diagnosis and line of the report is still produced serially, in
fragment order. `--workers 16` and `--workers 1` yield the same report.

Only documents that are not already cached are fetched concurrently, so a warm
re-check — the commonest thing this tool does — has nothing to overlap, starts no
workers, and costs what it always did. Set `--workers 1` if you want to be sure
of that; there is otherwise little reason to.

Documents are read and parsed once per run rather than once per citation, so a
page carrying a hundred citations costs one fetch and one parse. Set
`default_document_cache_bytes` in your config to bound what that holds (64 MB by
default); a document larger than the budget is used and not retained.

## Advanced Features

For RDF support, Python API, custom source repositories and more, 
see [docs/advanced.md](docs/advanced.md).

## License

ISC
