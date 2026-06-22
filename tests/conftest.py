# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared test utilities and fixtures."""

from rdflib import BNode, Graph, Literal
from rdflib.namespace import RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry

EMPTY_REGISTRY = RepoRegistry([])

DEFAULT_HTML = "<html><body><p>Hello world</p></body></html>"


class MockFetcher:
    """Minimal stand-in for ``CachedFetcher`` returning canned content.

    Pass ``content`` for a single fixed body, and/or ``routes`` (a mapping of
    URL substring -> response) to return different payloads per URL — useful
    for repo crawlers that fetch metadata then text. Recorded ``calls`` allow
    asserting which URLs were requested.
    """

    def __init__(self, content=DEFAULT_HTML, *, routes=None):
        self.content = content
        self.routes = routes or {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return self.content

    def get_bytes(self, url, **kwargs):
        response = self.get(url, **kwargs)
        if isinstance(response, str):
            return response.encode("utf-8")
        return response


def build_chain_graph(frag_uri, source_uri, url, location="lines:1-5",
                      label="test fragment"):
    """Build a minimal OA-native chain graph.

    Fragment -> oa:hasTarget -> oa:hasSource -> Source(schema:url).
    """
    g = Graph()
    g.add((frag_uri, RDF.type, SV.Fragment))
    g.add((frag_uri, RDFS.label, Literal(label)))
    g.add((frag_uri, SV.sourceLocation, Literal(location)))

    target = BNode()
    g.add((frag_uri, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source_uri))

    g.add((source_uri, RDF.type, SV.Source))
    g.add((source_uri, RDFS.label, Literal("test source")))
    g.add((source_uri, SCHEMA.url, Literal(url)))
    return g
