<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# apysource

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

  [PASS] Fragments: cache resolution.................. 2/2
  [PASS] Fragments: content extraction................ 2/2
  [PASS] Fragments: snippet verified.................. 2/2

  ======================================================================
  Summary: 3 PASS, 0 FAIL, 0 WARN
  EXIT CODE: 0 (all checks passed)
  ======================================================================
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

| Targetter | Key | Example | Best for |
|---|---|---|---|
| **Section** | `section` | `"Chapter I, Article 1"` | Structured documents (HTML, Markdown, Wikitext, RFC) |
| **CSS selector** | `selector` | `"div.content p"` | HTML pages |
| **Line range** | `lines` | `"40-41"` | Plain text, RFCs |
| **Repo location** | `location` | `"chapter:1"` | Repository modules (Gutenberg, Wikisource, etc.) |

**Section selectors** are the most versatile — they work across HTML, Markdown, Wikitext, and RFC plain text. They support roman numeral equivalence (`Chapter IV` = `Chapter 4`), nested paths (`Chapter I, Article 1, paragraph 2`), and quoted titles (`'The Fox and the Grapes'`).

**CSS selectors** target HTML elements directly. Useful when section headings aren't available or you need a specific element.

**Line ranges** extract by line number (1-based, inclusive). Useful for plain text and RFCs.

If no targetter is given, apysource checks the full page text for your snippet.

## YAML schema

Each YAML file has a top-level `sources` list. Each source has nested `fragments`.

### Source properties

| Key | What it does |
|---|---|
| `label` | Name of the source (required) |
| `url` | URL to fetch (required) |
| `type` | IANA media type: `text/html`, `text/plain`, `text/markdown`, etc. Short names (`html`, `plain-text`) also accepted. Auto-detected if omitted. |
| `language` | Language code, RFC 5646 (metadata) |
| `title` | Document title (metadata) |
| `date` | Publication or access date (metadata) |
| `part_of` | Parent source label (for hierarchical sources) |
| `isbn` | International Standard Book Number |
| `doi` | Digital Object Identifier |
| `publisher` | Publisher name |
| `edition` | Edition or version |
| `license` | License URI |

### Fragment properties

| Key | What it does |
|---|---|
| `label` | Name of the fragment (required) |
| `snippet` | The text you expect to find |
| `selector` | CSS selector to narrow extraction (HTML) |
| `lines` | Line range to extract, e.g. `30-35` |
| `section` | Human-readable section selector, e.g. `Chapter I, Article 1` |
| `location` | Repo-specific location hint (e.g. `chapter:1`) |
| `page_start` | Starting page number (for print sources) |
| `page_end` | Ending page number (for print sources) |

## CLI

```bash
apysource [-c config.toml] <command> [args...]
```

| Command | What it does |
|---|---|
| `check [sources.yaml] [--provenance file.ttl]` | Fetch, extract, and verify all snippets |
| `locate <url> <snippet>` | Find a snippet in a page, show the targetter |
| `add <file> <url> <snippet>` | Locate a snippet and add it to a YAML file |
| `validate` | Check that `.ttl` files parse correctly (with optional SHACL) |

Without `-c`, apysource uses built-in defaults (all built-in repos enabled). Pass `-c config.toml` to customize repos and HTTP settings (requires `pip install apysource[dev]`).

Pass `--provenance file.ttl` to `check` to write a PROV-O graph recording which fragments were verified, when, and by which activity.

## Python API

```python
from pathlib import Path
from apysource.yaml_input import load_yaml
from apysource.verification import run_checks, print_report
from apysource.repos import RepoRegistry

g = load_yaml(Path("sources.yaml"))
results = run_checks(g, [{"name": "Fragments", "class_uri": ..., "mode": "chain"}],
                     RepoRegistry([]))
print_report(results)
```

Key modules:

```python
from apysource.resolution import resolve_chain, get_text
from apysource.verification import run_checks, print_report
from apysource.repos import BaseRepo, RepoRegistry
from apysource.graph import load_triples
from apysource.http import CachedFetcher
from apysource.yaml_input import load_yaml
from apysource.formats import detect_format, extract_content, locate_snippet
```

## Advanced: RDF/Turtle input

For projects that already use RDF, you can define sources in Turtle instead of YAML:

```turtle
@prefix sv:      <https://alganet.github.io/apysource#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix oa:      <http://www.w3.org/ns/oa#> .
@prefix schema:  <https://schema.org/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ex:      <http://example.org/un#> .

ex:un_charter a sv:Source ;
    rdfs:label "UN Charter" ;
    schema:url "https://www.un.org/en/about-us/un-charter/full-text" ;
    dcterms:format "text/html" .

ex:preamble a sv:Fragment ;
    rdfs:label "Preamble" ;
    oa:motivatedBy oa:identifying ;
    oa:hasTarget [
        a oa:SpecificResource ;
        oa:hasSource ex:un_charter ;
        oa:hasSelector [
            a oa:TextQuoteSelector ;
            oa:exact "to save succeeding generations from the scourge of war"
        ] ;
        oa:hasSelector [
            a sv:SectionSelector ;
            rdf:value "Preamble"
        ]
    ] .
```

The `sv:` vocabulary is intentionally minimal — it only defines classes and properties with no standard equivalent. Everything else uses standard properties directly.

The RDF path requires a TOML config file (`-c`) to wire up the CLI context and repos. See `defaults.toml` for a full template.

### RDF properties

Standard properties used on sources:

| Property | What it does |
|---|---|
| `schema:url` | The URL to fetch |
| `dcterms:format` | IANA media type (`text/html`, `text/plain`) |
| `dcterms:title` | Document title |
| `dcterms:issued` | Publication or access date |
| `dcterms:language` | Language code (RFC 5646) |
| `dcterms:publisher` | Publisher name |
| `dcterms:license` | License URI |
| `dcterms:isPartOf` | Hierarchical sources (chapter of a book) |
| `bibo:isbn` | ISBN |
| `bibo:doi` | DOI |
| `bibo:pageStart` / `bibo:pageEnd` | Page numbers |

OA properties used on fragments:

| Property | What it does |
|---|---|
| `oa:hasTarget` | Links to `oa:SpecificResource` with `oa:hasSource` → Source |
| `oa:TextQuoteSelector` / `oa:exact` | The snippet text to verify |
| `oa:CssSelector` / `rdf:value` | CSS selector for HTML extraction |
| `sv:SectionSelector` / `rdf:value` | Human-readable section path (custom) |
| `oa:motivatedBy oa:identifying` | Annotation purpose |

Properties unique to `sv:`:

| Property | What it does |
|---|---|
| `sv:sourceLocation` | Opaque repo-specific location (e.g. `chapter:1`) |
| `sv:sourceLines` | Line range (e.g. `10-20`) |
| `sv:edition` | Edition or version string |
| `sv:verificationStatus` | `verified`, `failed`, or `pending` |

### Vocabulary design

The `sv:` namespace defines only what has no standard equivalent — 5 classes and 4 properties. Everything else uses established vocabularies directly:

- **Web Annotation (OA)**: Fragments are `oa:Annotation` instances. Source links, selectors, and snippet text all use native OA properties — no wrapper aliases.
- **Dublin Core (dcterms)**: Source metadata (title, date, language, format, publisher, license) uses DC terms directly.
- **BIBO**: Bibliographic identifiers (ISBN, DOI, page numbers) use BIBO properties directly.
- **PROV-O**: Sources are `prov:Entity`. Verification activities use `prov:wasGeneratedBy`, `prov:startedAtTime`, `prov:endedAtTime`.
- **SHACL**: `vocab/shapes.ttl` validates Sources, Fragments, and Terms.

## Advanced: repository modules

The generic path (CSS selectors, line ranges, section selectors) works for most web pages. For sources that need special handling — multi-page works, API-based sites, structured text formats — repository modules handle the crawling and extraction.

### Built-in repos

| Repo | Handles | Location format |
|---|---|---|
| `ArchiveRepo` | archive.org | `lines:N-M` |
| `GutenbergRepo` | Project Gutenberg | `chapter:N`, title match |
| `WikisourceRepo` | Wikisource | `section:Name`, subpage match |
| `WiktionaryRepo` | Wiktionary | term name, `language/section` |

All built-in repos are enabled by default. Most URLs work without a specialized repo — the generic fetcher + targetters (section selectors, CSS, line ranges) handle any web page. Repos are for sources that need multi-page crawling or domain-specific extraction. To customize URL patterns or add your own repos, use a TOML config file. See `defaults.toml`.

### Writing a custom repo

```python
from apysource.repos import BaseRepo

class MyRepo(BaseRepo):
    NAME = "myrepo"

    def url_to_key(self, url):
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def resolve_location(self, location, key):
        path = self.cache_dir / key / "content.txt"
        return path if path.exists() else None
```

`BaseRepo` requires `url_pattern` and `base_url` (from TOML config). `cache_dir` and `http_client` come from the registry. Override `extract_content` for custom extraction logic.

## Development

```bash
git clone <repo-url> && cd apysource
pip install -e .[dev]

make test               # run unit tests
make lint               # type checking with mypy
make coverage           # run tests with coverage
make check              # full verification gate (lint + coverage)
make compile-defaults   # regenerate _defaults.py from defaults.toml
```

## License

ISC
