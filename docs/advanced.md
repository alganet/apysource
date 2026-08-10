<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

## Python API

```python
from pathlib import Path
from apysource import check_graph, load_yaml
from apysource.verification import failed, print_report

results = check_graph(load_yaml(Path("sources.yaml")))
print_report(results)
raise SystemExit(1 if failed(results) else 0)
```

`check_graph` runs the same checks `apysource check` runs — it reads the same
`STANDARD_CHECKS` list — and returns results. It never prints and never exits:
what a failure *means* is the caller's decision. Pass `registry=` / `fetcher=`
to check against something other than the default wiring.

Citations you generate rather than write need no file on the way in:

```python
from apysource import check_graph, graph_from_data

results = check_graph(graph_from_data({"sources": [...]}))
```

`graph_from_data` is `load_yaml` minus the reading, so a generator gets the
identical validation — unknown keys refused, colliding identities refused —
without a temp file standing between it and the checker.

Key modules:

```python
from apysource.api import check_graph, STANDARD_CHECKS
from apysource.resolution import resolve_chain, get_text
from apysource.verification import run_checks, print_report, json_report, failed
from apysource.repos import BaseRepo, RepoRegistry
from apysource.graph import load_triples
from apysource.http import CachedFetcher
from apysource.yaml_input import load_yaml, graph_from_data
from apysource.sources import load_sources, sources_from_data
from apysource.patterns import mint_source, patterns_from_data, SourcePattern
from apysource.formats import detect_format, extract_content, locate_snippet
```

## Advanced: writing a sources file, not just checking one

A generator has the opposite problem from a checker. `graph_from_data` answers
*what does this file mean*, and a graph is the wrong shape for a tool that has to
**write** one: it has to emit entries, not triples, and it has to answer for names
its input file never mentioned.

```python
from apysource import load_sources

sources = load_sources(path)            # `None` is fine — the shipped patterns remain
sources.entries["RFC 9110"]["url"]      # entries come back with their url filled in
sources.resolve("RFC 9112")             # a name in no entry at all — minted, or None
```

Two properties are worth relying on.

**Entries come back URL-complete.** An entry written as a bare `label:` is merged
with whatever its pattern minted, *at load*. So a generator can emit the entries
it was handed straight into a file of its own, and that file stands alone — full
URL, full media type, no `patterns:` table required to read it. A reviewer sees
the URL that was actually fetched.

**`resolve` returns `None`, it does not raise.** apysource does not know why you
were asking. You are the one holding the comment, the file and the line the name
was written at, and the refusal is worth reading only if it says so.

Validation is not duplicated: `load_sources` runs the data through
`graph_from_data`. There is one definition of what a sources file means, and a
generator keeping a second copy of it is how a generator ends up emitting a key
the loader silently stopped accepting.

## Advanced: RDF/Turtle input

For projects that already use RDF, you can define sources in Turtle instead of YAML:

```turtle
@prefix sv:      <https://alganet.github.io/apysource/vocab.ttl#> .
@prefix rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
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

Pass a `.ttl` the same way you would pass a `.yaml`:

```sh
apysource check citations.ttl
apysource validate citations.ttl
```

A whole *directory* of Turtle still needs a TOML config file (`-c`) to say where
it is — that is what `rdf_subdir` sets. See `defaults.toml` for a full template.

### What Turtle does not do

A YAML source may name a family instead of an address — `label: RFC 9110` with no
`url`, resolved by a pattern. That is a convenience for writing YAML by hand, and
it is applied before the graph exists: by the time triples are minted the url is
already there. A Turtle source writes its `schema:url` out. This is a deliberate
line, not an oversight — an RDF author already has an identifier and a URL, and
the two front-ends agree about everything downstream of the graph.

### Validation

Turtle gets no loader — there is nothing between `g.parse()` and the checks — so
the SHACL shapes are what a Turtle author gets in place of the refusals a YAML
author gets from `graph_from_data`. Both `check` and `validate` apply the shipped
`shapes.ttl`, adding any `*shapes.ttl` your own project supplies.

`check` runs them only for Turtle input. A graph the YAML loader built has
already passed a stricter gate — unknown keys, non-scalar values, colliding
identities and fragments that quote nothing are all refused there, and none of
those are things SHACL can say.

The shapes need `pyshacl`, which is an optional dependency:

```sh
pip install apysource[shacl]
```

Without it, the check reports **SKIPPED** rather than quietly passing.

### Notes for RDF authors

- **Labels may be language-tagged.** `rdfs:label "Aesop's Fables"@en` is fine, as
  are several languages at once.
- **`schema:url` may be an IRI or a string.** Both resolve the same way.
- **A source may inherit its URL.** Give it `dcterms:isPartOf` a source that has
  one — that is how a chapter names its book — and it needs no `schema:url` of
  its own.
- **Identifiers are file-scoped by default.** A YAML file with no `base:` mints
  `urn:apysource:fragment_…` from labels, so two projects citing the same passage
  mint the same identifier. Fine locally; a merge hazard once published. Set a
  top-level `base:` to an IRI you control and identifiers are minted under it:

  ```yaml
  base: https://example.org/citations
  sources:
    - label: RFC 9110
  ```

  `apysource emit` warns when it is about to write the default identifiers out.
- **`dcterms:format` is a plain media-type string**, not an IANA IRI. Short names
  (`html`, `rfc`, `markdown`) work as well as full types (`text/html`).

### Emitting RDF

A YAML sources file *is* a graph — `apysource emit` writes it out as one:

```sh
apysource emit sources.yaml -o citations.ttl
apysource emit sources.yaml --format json-ld
apysource emit citations.ttl --format nt      # or convert between them
```

Formats: `turtle` (default), `json-ld`, `nt`, `xml`. What it writes conforms to
the shipped shapes, so `apysource validate` accepts the file it produced.

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
| `sv:verificationStatus` | `verified`, `failed`, or `pending` — on a result |
| `sv:citedBy`            | Fragment → a place that cites it                 |
| `sv:citingFile`         | The file a citation is made in                   |
| `sv:citingLine`         | The line it is made at (optional)                |

### The citing side

Everything above describes the *cited* side — the document, the section, the
passage. `sv:CiteSite` is the other end:

```turtle
@prefix sv:   <https://alganet.github.io/apysource/vocab.ttl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix ex:   <http://example.org/rules#> .

ex:host_header a sv:Fragment ;
    sv:citedBy [
        a sv:CiteSite ;
        sv:citingFile "src/rules/client_host_header.rs" ;
        sv:citingLine 29 ;
        prov:wasDerivedFrom ex:host_header
    ] .
```

The `prov:wasDerivedFrom` edge runs code → spec, and the direction is load-bearing:
the line of code was written to satisfy the normative sentence, not the other way
round. `sv:citedBy` is the same edge walked backwards, so a report holding a
fragment can find its sites without scanning the graph in reverse.

Not to be confused with `sv:sourceLocation` / `sv:sourceLines`, which say where in
the *cited* document a passage lives. `sv:citingFile` is the opposite axis.

### Verification provenance

`apysource check --provenance run.ttl` writes what a run found. The verdict is its
own entity rather than a property of the citation, because a verdict belongs to
the run that reached it:

```turtle
@prefix sv:   <https://alganet.github.io/apysource/vocab.ttl#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <http://example.org/rules#> .

[] a sv:VerificationResult ;
    sv:verificationStatus "verified" ;
    prov:wasGeneratedBy [ a sv:VerificationActivity ;
        prov:startedAtTime "2026-07-19T12:00:00+00:00"^^xsd:dateTime ;
        prov:endedAtTime   "2026-07-19T12:00:04+00:00"^^xsd:dateTime ;
        prov:used ex:host_header ] ;
    prov:wasDerivedFrom ex:host_header .
```

The activity `prov:used` the fragments it examined. It did not *generate* them — a
citation does not come into existence from the run that checks it; what the run
generates is the finding.

The file is self-contained: the fragments and sources it names are described in
it, so it can be read without the sources file it came from.

### Vocabulary design

The `sv:` namespace defines only what has no standard equivalent — 7 classes and 7 properties. Everything else uses established vocabularies directly:

- **Web Annotation (OA)**: Fragments are `oa:Annotation` instances. Source links, selectors, and snippet text all use native OA properties — no wrapper aliases.
- **Dublin Core (dcterms)**: Source metadata (title, date, language, format, publisher, license) uses DC terms directly.
- **BIBO**: Bibliographic identifiers (ISBN, DOI, page numbers) use BIBO properties directly.
- **PROV-O**: Sources are `prov:Entity`. A verification activity `prov:used` the fragments it examined, and each `sv:VerificationResult` is `prov:wasGeneratedBy` it. Cite sites are `prov:Entity`, linked by `prov:wasDerivedFrom`.
- **SHACL**: `apysource/vocab/shapes.ttl` validates Sources, Fragments, Terms, Cite Sites and verification provenance. It ships inside the package, so it applies wherever apysource is installed.

`sv:citedBy` is *not* declared `owl:inverseOf prov:wasDerivedFrom`, though the
prose invites it. `prov:wasDerivedFrom` is far more general, and the axiom would
entail a citation edge for every unrelated derivation in a merged graph. Both
directions are written out instead.

The `rdfs:domain` and `rdfs:range` declarations in `vocab.ttl` are documentation
of intent. Under RDFS entailment they would *assign* types rather than restrict
them — a stray `sv:citingLine` would infer `sv:CiteSite` — so validation runs with
inference off, and the shapes carry the constraints.

## Advanced: repository modules

The generic path (CSS selectors, line ranges, section selectors) works for most web pages. For sources that need special handling — multi-page works, API-based sites, structured text formats — repository modules handle the crawling and extraction.

### Built-in repos

| Repo             | Handles           | Location format               |
|------------------|-------------------|-------------------------------|
| `ArchiveRepo`    | archive.org       | `lines:N-M`                   |
| `GutenbergRepo`  | Project Gutenberg | `chapter:N`, title match      |
| `MdnRepo`        | MDN (`en-US`)     | section path, e.g. `Syntax`   |
| `RfcRepo`        | RFCs and I-Ds     | — (address with `section:`)   |
| `WikisourceRepo` | Wikisource        | `section:Name`, subpage match |
| `WiktionaryRepo` | Wiktionary        | term name, `language/section` |

All six built-in repos are enabled by default. Most URLs work without a specialized repo — the generic fetcher + targetters (section selectors, CSS, line ranges) handle any web page. Repos are for sources that need multi-page crawling or domain-specific extraction. To customize URL patterns or add your own repos, use a TOML config file. See `defaults.toml`.

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
- **`location:` is MDN's own hint, and `section:` still applies on top of it.**
  The repo narrows to the section path it was given, and the fragment's own
  targetters then run exactly as they would on a fetched page.

Only `en-US` URLs are handled. Translations live in a different repository
(`mdn/translated-content`), so other locales fall through to the generic
fetcher — weaker (they are redirect-warned, not canonical-enforced), but honest.

Known limitation: `mdn_base_url` ends in `main`, a moving ref, so the text a
citation is checked against can change between runs with no signal. Put a commit
SHA where `main` is to pin it.

### RFCs and Internet-Drafts

`RfcRepo` claims rfc-editor.org, `datatracker.ietf.org/doc/html` and the
`ietf.org` I-D archive, and reads the **HTML** rendition of whatever it is asked
for. `rfc9110.txt`, `rfc9110.html` and datatracker's `/doc/html/rfc9110` are one
cached document: the extension is a rendition, not an identity.

The HTML is chosen because the plain text is a 72-column rendering with page
furniture inside it — a running header and a `[Page 12]` footer every 58 lines,
and words split at the wrap. Reading it means undoing all of that by inference.
The HTML states the same things structurally, and every section carries
`id="section-7.2"`, which is what `#section-7.2` in a cited URL resolves against.

rfc-editor publishes two htmlizations, and the repo tells them apart by shape
rather than by date or host:

- **Modern** (xml2rfc v3, roughly RFC 8650 onward) is a real HTML document and is
  passed through with only its furniture removed — the `¶` self-link the renderer
  puts at the end of every paragraph, which is an affordance and not a character
  the document says. Nothing else is done to it: it has `<pre>` elements of its
  own — ABNF, frame diagrams — and flattening those would lose artwork a citation
  may be quoting.
- **Legacy** is the paginated text inside one `<pre>`, with headings drawn as
  `<span class="h3">` and anchors threaded through. It is rebuilt into the modern
  shape on read: headings hoisted out, prose re-emitted as blocks split at blank
  lines, page furniture dropped, words rejoined across the wrap. Datatracker's
  rendering of an old draft is the same shape and gets the same treatment.

Two consequences worth knowing:

- **The cache holds the rendition as served**, and normalization happens on read.
  A fix to the reader reaches every already-cached document with no `--refresh`.
- **`location:` and `lines:` do not address an RFC.** There is nothing below the
  document with a stable address, and a line number into a paginated rendition
  names a different passage after the next revision. `section:` is the address,
  and it works on appendices too — `§ A.1`, from a heading printed
  `Appendix A.1.` or an anchor spelled `#appendix-A.1`.

Known limitation: an unversioned draft id (`draft-ietf-httpbis-rfc6265bis`)
resolves to whatever datatracker calls current, so the text behind a citation can
change with no signal. Cite `-08` and it is pinned.

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

## The report, as data

`check --format json` writes a machine-readable report to stdout, so a CI job can
route a failure back to whatever produced it. Everything else — progress, the
provenance note — goes to stderr, so stdout carries only JSON.

```bash
apysource check sources.yaml --format json | jq '.checks[].failures[]'
```

```json
{
  "source": "MDN: Origin (stale pre-redirect URL)",
  "label": "mdn_stale",
  "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin",
  "urn": "urn:apysource:fragment_mdn_origin_stale_pre_redirect_url_mdn_stale",
  "reason": "mdn: no such document: en-us/web/http/headers/origin"
}
```

`label` is what you wrote in the YAML, and is what you route on. `urn` is the
stable identity, and the subject of the provenance graph.

A failure on a fragment with `cited_by` also carries `cited_by` — the places that
make the claim, which is what a CI job turns into an annotation on the line that
has to change. Labelling a fragment with the file that made the claim used to be
the only way to get this, and it was a poor one: a label is an identity, and
overloading it with a path meant a fragment could not move without changing its
name.

```json
{
  "label": "client_host_header",
  "reason": "snippet not found in extracted content",
  "cited_by": [{"file": "src/rules/client_host_header.rs", "line": 29}]
}
```

A snippet failure also carries a `hint`: the passage the source actually contains,
how similar it was, and which words differ — as fields, not as rendered lines, so
nothing has to parse prose back apart.

```json
{
  "hint": {
    "source_text": "The \"Host\" header field in a request provides the host and port",
    "kind": "differs only in punctuation",
    "ratio": 1.0, "percent": 100,
    "missing": [], "extra": [], "where": "§ 7.2"
  }
}
```

The verdicts and the exit code are the same ones the printed report uses — they are
computed once — so a CI job and a human are never told different things about the
same run.

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