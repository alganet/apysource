# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""apysource namespace definitions and RDF prefix bindings."""

from rdflib import Graph, Namespace
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD

SV = Namespace("https://alganet.github.io/apysource#")

OA = Namespace("http://www.w3.org/ns/oa#")
BIBO = Namespace("http://purl.org/ontology/bibo/")
SCHEMA = Namespace("https://schema.org/")

ALL_PREFIXES = {
    "sv": SV,
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "xsd": XSD,
    "dcterms": DCTERMS,
    "prov": PROV,
    "skos": SKOS,
    "oa": OA,
    "bibo": BIBO,
    "schema": SCHEMA,
}


def bind_prefixes(g: Graph, prefixes: dict | None = None) -> Graph:
    """Bind namespace prefixes to a graph."""
    for prefix, ns in (prefixes or ALL_PREFIXES).items():
        g.bind(prefix, ns)
    return g


def new_graph(prefixes: dict | None = None) -> Graph:
    """Create a new graph with all prefixes bound."""
    g = Graph()
    bind_prefixes(g, prefixes)
    return g
