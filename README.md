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
| **Section**       | `section`  | `"Chapter I, Article 1"` | Structured documents (HTML, Markdown, Wikitext, RFC) |
| **CSS selector**  | `selector` | `"div.content p"`        | HTML pages                                           |
| **Line range**    | `lines`    | `"40-41"`                | Plain text, RFCs                                     |
| **Repo location** | `location` | `"chapter:1"`            | Repository modules (Gutenberg, Wikisource, etc.)     |

**Section selectors** are the most versatile — they work across HTML, Markdown, Wikitext, and RFC plain text. They support roman numeral equivalence (`Chapter IV` = `Chapter 4`), nested paths (`Chapter I, Article 1, paragraph 2`), and quoted titles (`'The Fox and the Grapes'`).

**CSS selectors** target HTML elements directly. Useful when section headings aren't available or you need a specific element.

**Line ranges** extract by line number (1-based, inclusive). Useful for plain text and RFCs.

If no targetter is given, apysource checks the full page text for your snippet.

## YAML schema

Each YAML file has a top-level `sources` list. Each source has nested `fragments`.
An optional top-level `patterns` list says how to turn a *name* into a source.

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

Six families ship: `RFC NNNN`, and one for each repo — `MDN <page>`,
`Gutenberg <id>`, `Wikisource <page>`, `Wiktionary <word>`, `Archive <item>`. A
family of your own is three lines, and it is not a release of this package:

```yaml
patterns:
  - match: '^W3C (?P<slug>[a-z0-9-]+)$'
    source: {url: "https://www.w3.org/TR/{slug}/", type: text/html}
```

Your patterns are tried before the shipped ones, and an entry with a `url` beats
both — so pinning `RFC 9110` to datatracker is one entry. Within an entry, every
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

So they sit on opposite sides of the URL, and neither replaces the other. `RFC` is
declared by apysource itself precisely *because* no repo claims rfc-editor — that
gap is what patterns are for. Every other family is declared by the repo that
fetches it, because how you name an MDN page is MDN's business. Name one, and it is
claimed by its repo exactly as a URL you typed would be.

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
         RFC 9112 (https://www.rfc-editor.org/rfc/rfc9112.txt) (1)
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

| Command                                        | What it does                                                  |
|------------------------------------------------|---------------------------------------------------------------|
| `check [sources.yaml] [--provenance file.ttl]` | Fetch, extract, and verify all snippets                       |
| `locate <url> <snippet>`                       | Find a snippet in a page, show the targetter                  |
| `add <file> <url-or-name> <snippet>`           | Locate a snippet and add it to a YAML file                    |
| `validate`                                     | Check that `.ttl` files parse correctly (with optional SHACL) |

Without `-c`, apysource uses built-in defaults (all built-in repos enabled). Pass `-c config.toml` to customize repos and HTTP settings (requires `pip install apysource[dev]`).

Pass `--provenance file.ttl` to `check` to write a PROV-O graph recording which fragments were verified, when, and by which activity.

Fetched pages are cached on disk and reused indefinitely (no time-based expiry). Pass `--refresh` to `check`, `locate`, or `add` to bypass the cache and re-fetch. See [docs/advanced.md](docs/advanced.md#caching-and-freshness).

Pass `--strict-redirects` to `check` to fail, rather than warn, when a source URL has moved. Note that a page cached before apysource recorded redirect destinations reports its destination as *unknown*, not as clean — `--refresh` resolves that.

## Advanced Features

For RDF support, Python API, custom source repositories and more, 
see [docs/advanced.md](docs/advanced.md).

## License

ISC
