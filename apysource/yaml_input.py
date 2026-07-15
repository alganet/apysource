# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Load source definitions from YAML files into an rdflib Graph.

Pure function — no config imports, no global state.
"""

import re
from pathlib import Path

import yaml
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS

from apysource.formats import normalize_mime_type
from apysource.namespaces import BIBO, OA, SCHEMA, SV, new_graph


def _slugify(text: str) -> str:
    """Convert text to a URI-safe slug.

    Keeps any letter or digit, not only ASCII ones. It matched `[^a-z0-9]`, so
    a label written in Cyrillic, Greek or Chinese lost *every* character and
    slugged to the empty string — and three such labels minted one identical
    URN between them, merging three citations into one. `Übergabe` became
    `bergabe`; `§ 8` became `8`.
    """
    slug = text.lower().strip()
    slug = re.sub(r"\W+", "_", slug, flags=re.UNICODE)
    return slug.strip("_")


def _make_uri(label: str, kind: str = "") -> URIRef:
    """Create a deterministic URN from a label."""
    prefix = f"{kind}_" if kind else ""
    return URIRef(f"urn:apysource:{prefix}{_slugify(label)}")


class _Minter:
    """Hands out URNs, and refuses to hand the same one out twice.

    Identity is a slug, and ``_slugify`` collapses *every* run of non-alphanumeric
    characters to a single ``_``. So ``rules/host_header`` and
    ``rules-host-header`` are the same URN — and RDF being a set of triples, the
    two fragments silently became *one*, carrying both snippets. ``_get_snippet``
    then read one of them with ``g.value()``, which picks arbitrarily.

    The result was the worst outcome this tool can produce: a fabricated quote,
    appearing nowhere in the source, **verified green** — because the arbitrary
    pick happened to land on the other fragment's honest snippet. One citation
    was checked twice and the other was not checked at all, and nothing said so.

    Two citations that cannot be told apart are not something to guess between.
    They are refused, by name, with the URN they collided on.
    """

    def __init__(self) -> None:
        self._minted: dict[URIRef, str] = {}

    def mint(self, key: str, kind: str, what: str) -> URIRef:
        uri = _make_uri(key, kind)
        prior = self._minted.get(uri)
        if prior is not None:
            if prior == what:
                raise ValueError(
                    f"duplicate {kind}: {what} appears twice. "
                    f"Two entries with one identity are one entry; the second "
                    f"would silently vanish.",
                )
            raise ValueError(
                f"{kind} identity collision: {prior} and {what} both become "
                f"<{uri}>. They differ only in characters the identifier does "
                f"not keep (punctuation, spacing, case), so one citation would "
                f"silently overwrite the other. Give them labels that differ in "
                f"letters or digits.",
            )
        self._minted[uri] = what
        return uri


# YAML key → RDF predicate for source-level properties
_SOURCE_KEYS = {
    "url": SCHEMA.url,
    "type": DCTERMS.format,
    "language": DCTERMS.language,
    "title": DCTERMS.title,
    "date": DCTERMS.issued,
    "license": DCTERMS.license,
    "isbn": BIBO.isbn,
    "doi": BIBO.doi,
    "publisher": DCTERMS.publisher,
    "edition": SV.edition,
}

# Keys that need special value normalization
_NORMALIZE_KEYS = {
    "type": normalize_mime_type,
}

# YAML key → RDF predicate for fragment-level properties
# (snippet, selector, section are handled by OA emission, not stored as flat sv: properties)
_FRAGMENT_KEYS = {
    "lines": SV.sourceLines,
    "location": SV.sourceLocation,
    "page_start": BIBO.pageStart,
    "page_end": BIBO.pageEnd,
}

_SOURCE_ALLOWED = set(_SOURCE_KEYS) | {"label", "part_of", "fragments"}
_FRAGMENT_ALLOWED = (set(_FRAGMENT_KEYS)
                     | {"label", "snippet", "selector", "section", "cited_by"})

# Keys of one entry of a fragment's ``cited_by`` list.
_CITE_SITE_ALLOWED = {"file", "line"}

#: What a source may say, and what a fragment may say — as data, on purpose.
#:
#: A tool that *generates* citations has to know what it is allowed to emit, and
#: the honest way to tell it is to say so. The alternative is that it reads the
#: private name, or keeps its own copy — and a second copy of this list is how a
#: generator ends up emitting a key this loader silently stopped accepting.
SOURCE_KEYS = frozenset(_SOURCE_ALLOWED)
FRAGMENT_KEYS = frozenset(_FRAGMENT_ALLOWED)

#: The fragment keys that *select a passage*: everything a citation can say about
#: where in the source its quote lives. `label` names the citation, `snippet` is
#: the quote itself, and `cited_by` is the citing side — none of them target.
TARGETTING_KEYS = FRAGMENT_KEYS - {"label", "snippet", "cited_by"}


def _reject_unknown_keys(entry: dict, allowed: set[str], what: str) -> None:
    """A key we do not know is a key we silently ignore.

    ``snipet:`` loaded without a murmur, and the citation went on to verify
    nothing at all. The author wrote the quote down; the tool threw it away and
    called the run a pass.
    """
    unknown = sorted(k for k in entry if k not in allowed)
    if unknown:
        raise ValueError(
            f"{what}: unknown key{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(k) for k in unknown)}. "
            f"Known keys are: {', '.join(sorted(allowed))}. "
            f"A key apysource does not recognise is a key it ignores, and a "
            f"citation whose snippet was dropped verifies nothing.",
        )


def _text(value: object, what: str) -> str:
    """A scalar YAML value, as text — or a clear refusal.

    ``str()`` was applied to whatever turned up, so a ``snippet:`` written as a
    YAML *list* was stored as its Python repr — ``"['line one', 'line two']"`` —
    and the citation could then never match, however faithfully it was quoted.
    """
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ValueError(
        f"{what} must be a single piece of text, not a "
        f"{type(value).__name__}. Written as a list or a mapping it would be "
        f"stored as its Python repr and could never match the source.",
    )


def _emit_oa_target(g: Graph, frag_uri: URIRef, source_uri: URIRef,
                    frag_def: dict[str, object], what: str) -> None:
    """Emit OA Web Annotation triples for a fragment.

    This is the primary way fragments link to their source and carry
    snippet/selector/section data — via standard OA properties.

    Absence is ``None``, never falsiness: ``snippet: ""`` and ``section: 0`` were
    dropped by a truthiness test, and a dropped ``section:`` is the false-pass
    shape — the quote is then matched against the whole document instead of the
    section the citation named.
    """
    snippet = frag_def.get("snippet")
    selector_css = frag_def.get("selector")
    section = frag_def.get("section")

    if snippet is None and selector_css is None and section is None:
        return

    # Annotation motivation
    g.add((frag_uri, OA.motivatedBy, OA.identifying))

    # oa:hasTarget → oa:SpecificResource → oa:hasSource
    target = BNode()
    g.add((frag_uri, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source_uri))

    # TextQuoteSelector from snippet
    if snippet is not None:
        tqs = BNode()
        g.add((target, OA.hasSelector, tqs))
        g.add((tqs, RDF.type, OA.TextQuoteSelector))
        g.add((tqs, OA.exact, Literal(_text(snippet, f"{what}: snippet"))))

    # CssSelector from selector
    if selector_css is not None:
        css = BNode()
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(_text(selector_css, f"{what}: selector"))))

    # SectionSelector from section
    if section is not None:
        fs = BNode()
        g.add((target, OA.hasSelector, fs))
        g.add((fs, RDF.type, SV.SectionSelector))
        g.add((fs, RDF.value, Literal(_text(section, f"{what}: section"))))


def _emit_cite_sites(g: Graph, frag_uri: URIRef, frag_def: dict[str, object],
                     what: str) -> None:
    """Emit the *citing* side: the places that make this claim.

    ``prov:wasDerivedFrom`` points from the cite site to the fragment, and that
    direction is the true one — the line of code was derived from the normative
    sentence, not the other way round. ``sv:citedBy`` is the same edge walked
    backwards, so a report holding a fragment can find its sites without a
    reverse scan of the graph.

    A ``cited_by:`` written as a single mapping rather than a list of them is
    refused rather than wrapped. Guessing would be free here, and it is exactly
    the guess that turns one dropped entry into a citation nobody is told about.
    """
    sites = frag_def.get("cited_by")
    if sites is None:
        return

    if not isinstance(sites, list):
        raise ValueError(
            f"{what}: cited_by must be a list of places, not a "
            f"{type(sites).__name__}. Write it as a list even when there is "
            f"only one — a single mapping is one entry away from silently "
            f"becoming none.",
        )

    for i, site in enumerate(sites, 1):
        where = f"{what}: cited_by[{i}]"
        if not isinstance(site, dict):
            raise ValueError(
                f"{where} must be a mapping with a 'file', not a "
                f"{type(site).__name__}.",
            )
        _reject_unknown_keys(site, _CITE_SITE_ALLOWED, where)

        file = site.get("file")
        if not file:
            raise ValueError(
                f"{where}: a cite site must name the 'file' it is in. A site "
                f"with no place is not a place.",
            )

        node = BNode()
        g.add((node, RDF.type, SV.CiteSite))
        g.add((node, SV.citingFile, Literal(_text(file, f"{where}: file"))))
        g.add((node, PROV.wasDerivedFrom, frag_uri))
        g.add((frag_uri, SV.citedBy, node))

        line = site.get("line")
        if line is not None:
            # bool is an int in Python, and `line: true` is not line 1.
            if not isinstance(line, int) or isinstance(line, bool):
                raise ValueError(
                    f"{where}: line must be a whole number, not a "
                    f"{type(line).__name__}.",
                )
            g.add((node, SV.citingLine, Literal(line)))


def load_yaml(path: Path) -> Graph:
    """Load a YAML sources file and return an rdflib Graph.

    The YAML file should contain a top-level ``sources`` list.
    Each source may have a nested ``fragments`` list.
    """
    text = Path(path).read_text(encoding="utf-8")
    return graph_from_data(yaml.safe_load(text), origin=str(path))


def graph_from_data(data: object, origin: str = "<data>") -> Graph:
    """Mint a graph from already-parsed sources data.

    The same loader ``load_yaml`` runs, minus the reading — so a caller that
    already holds the data (a generator emitting citations, a test) gets the
    identical validation without writing a file first. ``origin`` names the
    data in error messages; it is the path when there is one.

    There is one definition of what a sources file means, and this is it.
    """
    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError(f"YAML file must contain a top-level 'sources' list: {origin}")

    g = new_graph()
    minter = _Minter()
    sources_by_label: dict[str, URIRef] = {}

    # Pre-pass: register every source URI up front so that `part_of` can
    # reference a source defined *later* in the file (forward references).
    for source_def in data["sources"]:
        label = source_def.get("label")
        if not label:
            raise ValueError("Each source must have a 'label'")
        sources_by_label[label] = minter.mint(label, "source", f"source {label!r}")

    for source_def in data["sources"]:
        label = source_def["label"]
        what_source = f"source {label!r}"
        _reject_unknown_keys(source_def, _SOURCE_ALLOWED, what_source)

        url = source_def.get("url")
        if not url:
            raise ValueError(f"Source '{label}' must have a 'url'")

        source_uri = sources_by_label[label]

        g.add((source_uri, RDF.type, SV.Source))
        g.add((source_uri, RDFS.label, Literal(label)))

        for key, predicate in _SOURCE_KEYS.items():
            value = source_def.get(key)
            if value is not None:
                value_str = _text(value, f"{what_source}: {key}")
                normalizer = _NORMALIZE_KEYS.get(key)
                if normalizer:
                    value_str = normalizer(value_str)
                g.add((source_uri, predicate, Literal(value_str)))

        # Handle part_of reference
        part_of = source_def.get("part_of")
        if part_of is not None:
            parent = _text(part_of, f"{what_source}: part_of")
            parent_uri = sources_by_label.get(parent)
            if parent_uri is None:
                # It was discarded in silence, so a typo'd parent simply
                # unhooked the source from its book and nobody heard.
                raise ValueError(
                    f"{what_source}: part_of names {parent!r}, which is not a "
                    f"source in this file.",
                )
            g.add((source_uri, DCTERMS.isPartOf, parent_uri))

        for frag_def in source_def.get("fragments", []):
            frag_label = frag_def.get("label")
            if not frag_label:
                raise ValueError(f"Each fragment in source '{label}' must have a 'label'")

            what_frag = f"fragment {frag_label!r} of source {label!r}"
            _reject_unknown_keys(frag_def, _FRAGMENT_ALLOWED, what_frag)

            frag_uri = minter.mint(f"{label} {frag_label}", "fragment", what_frag)
            g.add((frag_uri, RDF.type, SV.Fragment))
            g.add((frag_uri, RDFS.label, Literal(frag_label)))

            for key, predicate in _FRAGMENT_KEYS.items():
                value = frag_def.get(key)
                if value is not None:
                    g.add((frag_uri, predicate,
                           Literal(_text(value, f"{what_frag}: {key}"))))

            # OA Web Annotation triples (source link + selectors)
            _emit_oa_target(g, frag_uri, source_uri, frag_def, what_frag)

            # PROV triples for the citing side (file and line)
            _emit_cite_sites(g, frag_uri, frag_def, what_frag)

    return g
