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
from rdflib.namespace import DCTERMS, RDF, RDFS

from apysource.formats import normalize_mime_type
from apysource.namespaces import BIBO, OA, SCHEMA, SV, new_graph


def _slugify(text: str) -> str:
    """Convert text to a URI-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _make_uri(label: str, kind: str = "") -> URIRef:
    """Create a deterministic URN from a label."""
    prefix = f"{kind}_" if kind else ""
    return URIRef(f"urn:apysource:{prefix}{_slugify(label)}")


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


def _emit_oa_target(g: Graph, frag_uri: URIRef, source_uri: URIRef,
                    frag_def: dict[str, object]) -> None:
    """Emit OA Web Annotation triples for a fragment.

    This is the primary way fragments link to their source and carry
    snippet/selector/section data — via standard OA properties.
    """
    snippet = frag_def.get("snippet")
    selector_css = frag_def.get("selector")
    section = frag_def.get("section")

    if not snippet and not selector_css and not section:
        return

    # Annotation motivation
    g.add((frag_uri, OA.motivatedBy, OA.identifying))

    # oa:hasTarget → oa:SpecificResource → oa:hasSource
    target = BNode()
    g.add((frag_uri, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source_uri))

    # TextQuoteSelector from snippet
    if snippet:
        tqs = BNode()
        g.add((target, OA.hasSelector, tqs))
        g.add((tqs, RDF.type, OA.TextQuoteSelector))
        g.add((tqs, OA.exact, Literal(str(snippet))))

    # CssSelector from selector
    if selector_css:
        css = BNode()
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(str(selector_css))))

    # SectionSelector from section
    if section:
        fs = BNode()
        g.add((target, OA.hasSelector, fs))
        g.add((fs, RDF.type, SV.SectionSelector))
        g.add((fs, RDF.value, Literal(str(section))))


def load_yaml(path: Path) -> Graph:
    """Load a YAML sources file and return an rdflib Graph.

    The YAML file should contain a top-level ``sources`` list.
    Each source may have a nested ``fragments`` list.
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError(f"YAML file must contain a top-level 'sources' list: {path}")

    g = new_graph()
    sources_by_label: dict[str, URIRef] = {}

    for source_def in data["sources"]:
        label = source_def.get("label")
        if not label:
            raise ValueError("Each source must have a 'label'")
        url = source_def.get("url")
        if not url:
            raise ValueError(f"Source '{label}' must have a 'url'")

        source_uri = _make_uri(label, "source")
        sources_by_label[label] = source_uri

        g.add((source_uri, RDF.type, SV.Source))
        g.add((source_uri, RDFS.label, Literal(label)))

        for key, predicate in _SOURCE_KEYS.items():
            value = source_def.get(key)
            if value is not None:
                normalizer = _NORMALIZE_KEYS.get(key)
                value_str = normalizer(str(value)) if normalizer else str(value)
                g.add((source_uri, predicate, Literal(value_str)))

        # Handle part_of reference
        part_of = source_def.get("part_of")
        if part_of:
            parent_uri = sources_by_label.get(part_of)
            if parent_uri:
                g.add((source_uri, DCTERMS.isPartOf, parent_uri))

        for frag_def in source_def.get("fragments", []):
            frag_label = frag_def.get("label")
            if not frag_label:
                raise ValueError(f"Each fragment in source '{label}' must have a 'label'")

            frag_uri = _make_uri(f"{label} {frag_label}", "fragment")
            g.add((frag_uri, RDF.type, SV.Fragment))
            g.add((frag_uri, RDFS.label, Literal(frag_label)))

            for key, predicate in _FRAGMENT_KEYS.items():
                value = frag_def.get(key)
                if value is not None:
                    g.add((frag_uri, predicate, Literal(str(value))))

            # OA Web Annotation triples (source link + selectors)
            _emit_oa_target(g, frag_uri, source_uri, frag_def)

    return g
