
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