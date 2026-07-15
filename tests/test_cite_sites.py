# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The citing side: `cited_by`, and the failure that names it.

The promise under test is not "the loader emits triples". It is: **when a
source stops saying what something claimed it said, the report names the thing
that has to change.** Every test here is written from that end — through the
real loader and the real checker — because a citation whose failure nobody can
act on is barely better than no citation at all.
"""

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import PROV, RDF

from apysource.api import check_graph
from apysource.namespaces import SV
from apysource.verification import failed, json_report, print_report
from apysource.yaml_input import graph_from_data
from tests.conftest import EMPTY_REGISTRY, MockFetcher

RFC_TEXT = "3.2.  Host\n\n   A client MUST send a Host header field in all requests.\n"


def _sources(fragment: dict) -> dict:
    return {"sources": [{
        "label": "RFC 9112",
        "url": "https://www.rfc-editor.org/rfc/rfc9112.txt",
        "type": "text/plain",
        "fragments": [fragment],
    }]}


# ── The promise: a failure names the line that has to change ────────────

def _check_with_source(fragment: dict, body: str):
    """Run the real checker over one fragment against a canned document."""
    g = graph_from_data(_sources(fragment))
    return check_graph(g, registry=EMPTY_REGISTRY, fetcher=MockFetcher(body))


def test_a_failure_names_the_code_that_relies_on_the_quote(capsys):
    """The whole point. The quote is gone; the report says where it is claimed.

    Before this, a failing fragment was named by its label — a slug like
    ``client_host_header``, which is not a place, and which nobody can open.
    """
    results = _check_with_source(
        {"label": "client_host_header",
         "snippet": "A client MUST send a Teapot header field in all requests.",
         "cited_by": [{"file": "src/rules/client_host_header.rs", "line": 29}]},
        RFC_TEXT,
    )

    assert failed(results)
    print_report(results)
    out = capsys.readouterr().out
    assert "cited by src/rules/client_host_header.rs:29" in out


def test_the_quote_that_is_really_there_passes():
    """The control. Without it, every test above could be passing vacuously.

    If the fragment failed for some reason of its own — an unfetchable URL, a
    harness that cannot extract anything — then "the failure names the cite
    site" would be asserting nothing about quotes at all. So: the true sentence
    verifies, and the run is green.
    """
    results = _check_with_source(
        {"label": "client_host_header",
         "snippet": "A client MUST send a Host header field in all requests.",
         "cited_by": [{"file": "src/rules/client_host_header.rs", "line": 29}]},
        RFC_TEXT,
    )

    assert not failed(results)
    assert sum(check.ok for check in results) >= 1, "a green run verified nothing"


def test_the_json_report_carries_the_cite_sites():
    """A CI job routes on this: it is what pins a failure to a line to annotate."""
    results = _check_with_source(
        {"label": "client_host_header",
         "snippet": "A client MUST send a Teapot header field in all requests.",
         "cited_by": [{"file": "src/rules/client_host_header.rs", "line": 29}]},
        RFC_TEXT,
    )

    failures = [f for check in json_report(results)["checks"]
                for f in check["failures"] if f.get("cited_by")]
    assert failures, "a failing fragment with cite sites reported none"
    assert failures[0]["cited_by"] == [
        {"file": "src/rules/client_host_header.rs", "line": 29},
    ]


def test_both_renderers_are_told_the_same_thing(capsys):
    """The printed report and the JSON one cannot disagree about who cites what.

    They are two renderings of one run. A CI job and a human reading the same
    failure must not come away with different ideas of which file to open.
    """
    fragment = {
        "label": "trailer_fields",
        "snippet": "A client MUST send a Teapot header field in all requests.",
        "cited_by": [{"file": "a.rs", "line": 1}, {"file": "b.rs", "line": 2}],
    }
    results = _check_with_source(fragment, RFC_TEXT)

    print_report(results)
    printed = capsys.readouterr().out
    from_json = [f for check in json_report(results)["checks"]
                 for f in check["failures"] if f.get("cited_by")]

    assert from_json
    for site in from_json[0]["cited_by"]:
        assert f"cited by {site['file']}:{site['line']}" in printed


def test_a_source_level_finding_claims_no_cite_site(capsys):
    """A moved URL is a finding about a *source*, which many fragments may cite.

    Naming one of them would be a claim the graph does not support. Only
    fragment-level records — the ones that carry a URN — carry cite sites.
    """
    fragment = {
        "label": "client_host_header",
        "snippet": "A client MUST send a Host header field in all requests.",
        "cited_by": [{"file": "src/rules/client_host_header.rs", "line": 29}],
    }
    g = graph_from_data(_sources(fragment))
    fetcher = MockFetcher(
        RFC_TEXT,
        redirects={"https://www.rfc-editor.org/rfc/rfc9112.txt":
                   "https://example.org/moved"},
    )
    results = check_graph(g, registry=EMPTY_REGISTRY, fetcher=fetcher)

    moved = [f for check in results for f in (*check.failures, *check.warnings)
             if "moved" in f.reason]
    assert moved, "the redirect went unreported"
    assert all(not f.cited_by for f in moved)


def test_a_fragment_nobody_cites_reports_no_sites():
    """Absence of cite sites is silence, not a claim. It must not crash or invent."""
    results = _check_with_source(
        {"label": "uncited",
         "snippet": "A client MUST send a Teapot header field in all requests."},
        RFC_TEXT,
    )

    assert failed(results)
    assert all(not f.cited_by for check in results for f in check.failures)


# ── The graph: the edge points from the code to the sentence ────────────

def test_the_cite_site_was_derived_from_the_fragment():
    """`prov:wasDerivedFrom` runs code -> spec, and that direction is the true one.

    The line of code was derived from the normative sentence; the sentence was
    not derived from the line of code. Getting this backwards would make the
    provenance graph say the RFC was written to justify our source file.
    """
    g = graph_from_data(_sources(
        {"label": "f", "snippet": "x", "cited_by": [{"file": "a.rs", "line": 7}]},
    ))

    sites = list(g.subjects(RDF.type, SV.CiteSite))
    assert len(sites) == 1
    site = sites[0]

    frag = URIRef("urn:apysource:fragment_rfc_9112_f")
    assert (site, PROV.wasDerivedFrom, frag) in g
    assert (frag, SV.citedBy, site) in g
    assert (site, SV.citingFile, Literal("a.rs")) in g
    assert (site, SV.citingLine, Literal(7)) in g


def test_a_cite_site_need_not_have_a_line():
    """Not every citation is made at a line of a file. A footnote cites too."""
    g = graph_from_data(_sources(
        {"label": "f", "snippet": "x", "cited_by": [{"file": "NOTES.md"}]},
    ))

    site = next(iter(g.subjects(RDF.type, SV.CiteSite)))
    assert (site, SV.citingFile, Literal("NOTES.md")) in g
    assert g.value(site, SV.citingLine) is None


# ── The refusals ────────────────────────────────────────────────────────

def test_a_lone_mapping_is_refused_rather_than_wrapped():
    """Guessing is free here, and it is the guess that loses citations.

    ``cited_by: {file: a.rs}`` looks like it means one site. Wrapping it would
    work — until the day someone adds a second and YAML keeps only the last key.
    """
    with pytest.raises(ValueError, match="cited_by must be a list"):
        graph_from_data(_sources(
            {"label": "f", "snippet": "x", "cited_by": {"file": "a.rs"}},
        ))


def test_a_site_with_no_place_is_refused():
    with pytest.raises(ValueError, match="must name the 'file'"):
        graph_from_data(_sources(
            {"label": "f", "snippet": "x", "cited_by": [{"line": 3}]},
        ))


def test_an_unknown_key_in_a_site_is_refused():
    """The `snipet:` lesson, one level down: a key we ignore is a claim we drop."""
    with pytest.raises(ValueError, match="unknown key"):
        graph_from_data(_sources(
            {"label": "f", "snippet": "x",
             "cited_by": [{"file": "a.rs", "lineno": 3}]},
        ))


@pytest.mark.parametrize("line", ["29", 1.5, True, [29]])
def test_a_line_that_is_not_a_line_is_refused(line):
    """`line: true` is not line 1, and bool is an int in Python."""
    with pytest.raises(ValueError, match="line must be a whole number"):
        graph_from_data(_sources(
            {"label": "f", "snippet": "x", "cited_by": [{"file": "a.rs", "line": line}]},
        ))
