# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared test utilities and fixtures."""

from rdflib import BNode, Graph, Literal
from rdflib.namespace import RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.repos import RepoRegistry
from apysource.results import Redirect

EMPTY_REGISTRY = RepoRegistry([])

DEFAULT_HTML = "<html><body><p>Hello world</p></body></html>"


class MockFetcher:
    """Minimal stand-in for ``CachedFetcher`` returning canned content.

    Pass ``content`` for a single fixed body, and/or ``routes`` (a mapping of
    URL substring -> response) to return different payloads per URL — useful
    for repo crawlers that fetch metadata then text. Recorded ``calls`` allow
    asserting which URLs were requested.
    """

    def __init__(self, content=DEFAULT_HTML, *, routes=None, redirects=None):
        self.content = content
        self.routes = routes or {}
        self.redirects = redirects or {}
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

    def redirect_for(self, url):
        """Where a URL landed. Pass ``redirects={url: final_url}`` to move one.

        An unmapped URL reports a direct fetch; ``None`` (an unrecorded
        destination) is what a real fetcher returns for a body cached before
        redirects were tracked, so tests that need that case map to None.
        """
        if url in self.redirects:
            final = self.redirects[url]
            if final is None:
                return None
            return Redirect(url=url, final_url=final, chain=[(301, url)])
        return Redirect(url=url, final_url=url)


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
