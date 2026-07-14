<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

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
@prefix sv:      <https://alganet.github.io/apysource/vocab.ttl#> .
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

| Property                          | What it does                                |
|-----------------------------------|---------------------------------------------|
| `schema:url`                      | The URL to fetch                            |
| `dcterms:format`                  | IANA media type (`text/html`, `text/plain`) |
| `dcterms:title`                   | Document title                              |
| `dcterms:issued`                  | Publication or access date                  |
| `dcterms:language`                | Language code (RFC 5646)                    |
| `dcterms:publisher`               | Publisher name                              |
| `dcterms:license`                 | License URI                                 |
| `dcterms:isPartOf`                | Hierarchical sources (chapter of a book)    |
| `bibo:isbn`                       | ISBN                                        |
| `bibo:doi`                        | DOI                                         |
| `bibo:pageStart` / `bibo:pageEnd` | Page numbers                                |

OA properties used on fragments:

| Property                            | What it does                                                |
|-------------------------------------|-------------------------------------------------------------|
| `oa:hasTarget`                      | Links to `oa:SpecificResource` with `oa:hasSource` → Source |
| `oa:TextQuoteSelector` / `oa:exact` | The snippet text to verify                                  |
| `oa:CssSelector` / `rdf:value`      | CSS selector for HTML extraction                            |
| `sv:SectionSelector` / `rdf:value`  | Human-readable section path (custom)                        |
| `oa:motivatedBy oa:identifying`     | Annotation purpose                                          |

Properties unique to `sv:`:

| Property                | What it does                                     |
|-------------------------|--------------------------------------------------|
| `sv:sourceLocation`     | Opaque repo-specific location (e.g. `chapter:1`) |
| `sv:sourceLines`        | Line range (e.g. `10-20`)                        |
| `sv:edition`            | Edition or version string                        |
| `sv:verificationStatus` | `verified`, `failed`, or `pending`               |

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

| Repo             | Handles           | Location format               |
|------------------|-------------------|-------------------------------|
| `ArchiveRepo`    | archive.org       | `lines:N-M`                   |
| `GutenbergRepo`  | Project Gutenberg | `chapter:N`, title match      |
| `MdnRepo`        | MDN (`en-US`)     | section path, e.g. `Syntax`   |
| `WikisourceRepo` | Wikisource        | `section:Name`, subpage match |
| `WiktionaryRepo` | Wiktionary        | term name, `language/section` |

All built-in repos are enabled by default. Most URLs work without a specialized repo — the generic fetcher + targetters (section selectors, CSS, line ranges) handle any web page. Repos are for sources that need multi-page crawling or domain-specific extraction. To customize URL patterns or add your own repos, use a TOML config file. See `defaults.toml`.

### MDN

`MdnRepo` checks an MDN citation against the Markdown MDN is *written in*, in the
`mdn/content` repository — not against the page it renders. MDN reorganizes
constantly and a moved page keeps answering its old URL with a 301, so a stale
citation otherwise passes against whatever the redirect leads to. The authored
file does not play along: a moved page's slug is gone, and the citation fails.

Three things follow from checking the source rather than the page:

- **Quotes are matched against a rendering of the Markdown**, so you can still
  paste what the browser showed you. KumaScript macros expand the way the site
  expands them: `{{HTTPHeader("Origin")}}` is the word `Origin`.
- **Text a macro *generates* cannot be quoted.** The browser-compatibility and
  specifications tables, live samples and sidebars are not in the source file
  and cannot be reconstructed from it. A quote of one fails, and the failure
  shows a `⟨macro⟩` mark where the generated text would have been.
- **MDN fragments target with `location:`, not `section:`.** A repo is handed
  only the location hint, so a `section:` on an MDN fragment is ignored.

Only `en-US` URLs are handled. Translations live in a different repository
(`mdn/translated-content`), so other locales fall through to the generic
fetcher — weaker (they are redirect-warned, not canonical-enforced), but honest.

Known limitation: `mdn_base_url` ends in `main`, a moving ref, so the text a
citation is checked against can change between runs with no signal. Put a commit
SHA where `main` is to pin it.

### Fetching on demand

A repo that matches a URL *owns* that URL. Routing does not depend on what
happens to be in the cache: `check` crawls a document the repo does not have
yet, `--refresh` re-crawls it, and `--no-crawl` reports the miss instead of
fetching. (Previously a cold cache fell back to the generic fetcher, so the
snippet was quietly verified against the rendered web page rather than the
repository the citation names — a different document, with no signal.)

A repo that matches a URL but has *no* crawler still falls back to the fetcher.
That is no longer silent: the `Repo documents` check names the repo it fell back
from, and `--strict-repos` turns that warning into a failure.

### When a repo has no such document

`crawl()` raises `RepoNotFound` when the repository authoritatively has no such
document, and `RepoUnavailable` when the fetch merely failed. The distinction is
load-bearing: a 404 is knowledge, a timeout is the absence of it, and reporting
"no such page" because the network was down would be a confident wrong answer
about the source.

Neither writes anything to the cache. A page that comes back upstream verifies
on the next run, with no `--refresh` needed.

### Writing a custom repo

```python
from apysource.repos import BaseRepo, RepoNotFound

class MyRepo(BaseRepo):
    NAME = "myrepo"
    supports_crawl = True          # opt in; without it, a cold cache falls back

    def url_to_key(self, url):
        m = self.url_pattern.search(url)
        return m.group(1) if m else None

    def resolve_location(self, location, key):
        # A cache lookup. It must not fetch — that is what crawl is for.
        path = self.cache_root / key / "content.txt"
        return path if path.exists() else None

    def crawl(self, key, *, delay=None, force=False, from_cache=False):
        # self.fetch raises RepoNotFound on a 404 and RepoUnavailable otherwise.
        body = self.fetch(f"{self.base_url}/{key}.txt", key, force=force)
        if not body.strip():
            raise RepoNotFound(self.NAME, key, "the document is empty")
        path = self.cache_root / key / "content.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
```

`BaseRepo` requires `url_pattern` and `base_url` (from TOML config). `cache_dir`,
`http_client` and `crawl_delay` come from the registry — `crawl_delay` defaults
from the registry's `default_crawl_delay` unless the repo sets its own, and is
passed per request, so a repo backed by a CDN can be read briskly without making
every other source a rude crawl. Override `extract_content` for custom extraction
logic.

## Caching and freshness

apysource caches every fetched URL on disk (under `data/cache/` by default), keyed by a hash of
the URL. Cache hits skip both the network and the polite crawl delay, which makes re-runs fast and
keeps you a courteous crawler.

Alongside each cached body sits a `<hash>.meta.json` sidecar recording where the request actually
landed — the final URL, and the redirect chain that led there if any. That is what lets `check`
report a source whose URL has **moved**: redirects are followed, so a stale citation still
verifies against the page it was forwarded to, and without this the weakening would be invisible.

There is no time-based expiry: **once a URL is cached, that body is reused until you refresh it.**
For a link-rot checker this is a deliberate trade-off — verification is reproducible, but a source
that changes upstream won't be noticed until you re-fetch. To force a fresh download, bypassing the
cache:

```bash
apysource check sources.yaml --refresh     # re-fetch every source, then verify
apysource locate <url> <snippet> --refresh # re-fetch this URL while locating
apysource add sources.yaml <url> <snippet> --refresh
```

`--refresh` re-crawls repo-backed sources too. It previously had no effect on
one at all, which meant a repo's cache could not be refreshed by any means.

A body cached before apysource recorded destinations has no sidecar, so its URL's destination is
simply **unknown**. `check` says so rather than passing it: an unchecked URL is not a clean one,
and reporting it as clean is exactly the silent green the `Source URLs` check exists to end. One
`--refresh` turns every unknown into a known.

```bash
apysource check sources.yaml --strict-redirects   # a moved (or unchecked) URL fails the run
```

The crawler identifies itself with a `User-Agent` derived from the package version
(`apysource/<version>`). Set a custom one in a TOML config if needed (see `defaults.toml`).

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