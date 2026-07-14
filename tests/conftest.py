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

    def __init__(self, content=DEFAULT_HTML, *, routes=None, redirects=None,
                 statuses=None):
        self.content = content
        self.routes = routes or {}
        self.redirects = redirects or {}
        self.statuses = statuses or {}
        self.calls = []
        #: (url, kwargs) per request, so a test can assert *how* it was asked —
        #: a per-repo crawl delay that never reaches the fetch is decoration.
        self.requests = []

    def _body(self, url):
        """The canned response for a URL, without recording a call."""
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return self.content

    def get(self, url, **kwargs):
        self.calls.append(url)
        self.requests.append((url, kwargs))
        return self._body(url)

    def get_bytes(self, url, **kwargs):
        response = self.get(url, **kwargs)
        if isinstance(response, str):
            return response.encode("utf-8")
        return response

    def status_for(self, url):
        """The status a fetch got, as the real fetcher reports it.

        Defaults to 404 for a URL that answered ``None`` — the common case a
        repo cares about. Pass ``statuses={url: 503}`` (or ``{url: None}``, for
        a request that never reached a server) to say otherwise, which is how
        the "a timeout is not an absence" tests are written.

        Asking does not count as fetching; it must not show up in ``calls``,
        or a test that proves a URL was never fetched would prove it by
        accident and then stop being able to.
        """
        for fragment, status in self.statuses.items():
            if fragment in url:
                return status
        return 404 if self._body(url) is None else 200

    def redirect_for(self, url):
        """Where a URL landed, as the real fetcher would report it.

        A real fetcher only knows a destination for a URL it actually
        fetched; anything else is unknown (None). Faithfully reproducing
        that matters: a mock that calls every URL clean would let a check
        pass on evidence that does not exist in production.

        Pass ``redirects={url: final_url}`` to move one, or
        ``{url: None}`` to make it unknown despite having been fetched.
        """
        if url in self.redirects:
            final = self.redirects[url]
            if final is None:
                return None
            return Redirect(url=url, final_url=final, chain=[(301, url)])
        if url in self.calls:
            return Redirect(url=url, final_url=url)
        return None


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
