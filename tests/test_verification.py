# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.verification with synthetic graphs."""

from unittest.mock import patch

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

from apysource.namespaces import OA, SCHEMA, SV
from apysource.results import CheckResult, Failure, RepoResult, ResolveResult
from apysource.verification import print_report, run_checks, strip_headers

from tests.conftest import EMPTY_REGISTRY


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_chain_graph():
    """Build a graph with one Fragment for chain-mode testing (OA-native)."""
    g = Graph()
    frag = URIRef("http://example.com/data/test#frag1")
    source = URIRef("http://example.com/data/test#src1")
    g.add((frag, RDF.type, SV.Fragment))
    g.add((frag, RDFS.label, Literal("test fragment")))
    g.add((frag, SV.sourceLocation, Literal("lines:1-5")))

    # OA target chain
    target = BNode()
    g.add((frag, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source))

    g.add((source, RDF.type, SV.Source))
    g.add((source, RDFS.label, Literal("test source")))
    g.add((source, SCHEMA.url, Literal("http://example.com/item")))
    return g, frag


def _make_direct_graph():
    """Build a graph with one entity for direct-mode testing."""
    g = Graph()
    entity = URIRef("http://example.com/data/test#term1")
    g.add((entity, RDF.type, SV.Term))
    g.add((entity, SCHEMA.url, Literal("http://example.com/item")))
    g.add((entity, SV.sourceLocation, Literal("chapter_one")))
    return g, entity


# ── strip_headers ────────────────────────────────────────────────────────

def test_strip_headers_removes_hash_lines():
    """strip_headers removes lines starting with # and blank lines."""
    text = "# Header\n\nActual content\n# Another header\nMore content"
    result = strip_headers(text)
    assert result == "Actual content\nMore content"


def test_strip_headers_empty():
    """strip_headers returns empty string for empty input."""
    assert strip_headers("") == ""


# ── run_checks chain mode ────────────────────────────────────────────────

def test_chain_mode_resolvable():
    """Chain-mode check with resolvable fragment produces PASS results."""
    g, frag = _make_chain_graph()

    resolved_result = RepoResult(
        status="resolved",
        label="test fragment",
        location="lines:1-5",
        source="test source",
        url="http://example.com/item",
        module="mock",
        cache_file="/tmp/fake/file.txt",
    )

    long_text = "A" * 100  # longer than 20 chars for passage extraction check

    checks_config = [
        {"name": "fragments", "class_uri": SV.Fragment, "mode": "chain"},
    ]

    with patch("apysource.verification.resolve_chain", return_value=resolved_result), \
         patch("apysource.verification.get_text", return_value=long_text):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    # Chain mode produces 3 sub-checks
    assert len(results) == 3
    # Cache resolution should pass
    check = results[0]
    assert "cache resolution" in check.name
    assert check.ok == 1
    assert check.total == 1
    assert check.failures == []


def test_chain_mode_unresolvable():
    """Chain-mode check with unresolvable fragment produces FAIL results."""
    g, frag = _make_chain_graph()

    unresolved_result = RepoResult(
        status="no_file",
        label="test fragment",
        location="lines:1-5",
        source="test source",
        url="http://example.com/item",
        module="mock",
        cache_file=None,
    )

    checks_config = [
        {"name": "fragments", "class_uri": SV.Fragment, "mode": "chain"},
    ]

    with patch("apysource.verification.resolve_chain", return_value=unresolved_result), \
         patch("apysource.verification.get_text", return_value=""):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    assert len(results) == 3
    check = results[0]
    assert "cache resolution" in check.name
    assert check.ok == 0
    assert len(check.failures) == 1


# ── run_checks direct mode ──────────────────────────────────────────────

def test_direct_mode_resolvable():
    """Direct-mode check with resolvable entity produces PASS."""
    g, entity = _make_direct_graph()

    resolved_result = RepoResult(
        status="resolved",
        url="http://example.com/item",
        location="chapter_one",
        module="mock",
        cache_file="/tmp/fake/file.txt",
    )

    long_text = "A" * 100

    checks_config = [
        {"name": "terms", "class_uri": SV.Term, "mode": "direct"},
    ]

    with patch("apysource.verification.resolve_direct", return_value=resolved_result), \
         patch("apysource.verification.get_text", return_value=long_text):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    assert len(results) == 1
    check = results[0]
    assert check.ok == 1
    assert check.failures == []


# ── print_report ─────────────────────────────────────────────────────────

def test_emit_provenance_returns_graph(capsys):
    """run_checks with emit_provenance=True returns (results, prov_graph)."""
    g, frag = _make_chain_graph()

    # Add a snippet via TextQuoteSelector (OA-native)
    snippet_text = "this is test content for verification purposes and more"
    target = g.value(frag, OA.hasTarget)
    tqs = BNode()
    g.add((target, OA.hasSelector, tqs))
    g.add((tqs, RDF.type, OA.TextQuoteSelector))
    g.add((tqs, OA.exact, Literal(snippet_text)))

    resolved_result = RepoResult(
        status="resolved", label="test", location="lines:1-5",
        source="test source", url="http://example.com", module="test",
        cache_file="/tmp/fake.txt",
    )
    long_text = "this is test content for verification purposes and more text here"

    checks_config = [
        {"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"},
    ]

    with patch("apysource.verification.resolve_chain", return_value=resolved_result), \
         patch("apysource.verification.get_text", return_value=long_text):
        result = run_checks(g, checks_config, EMPTY_REGISTRY,
                            emit_provenance=True)

    # Returns a tuple
    assert isinstance(result, tuple)
    results, prov_graph = result
    assert isinstance(results, list)
    assert isinstance(prov_graph, Graph)

    # PROV graph contains a VerificationActivity
    activities = list(prov_graph.subjects(RDF.type, SV.VerificationActivity))
    assert len(activities) == 1
    activity = activities[0]

    # Activity has timestamps
    start = prov_graph.value(activity, PROV.startedAtTime)
    end = prov_graph.value(activity, PROV.endedAtTime)
    assert start is not None
    assert end is not None

    # Verified fragment has provenance
    status = prov_graph.value(frag, SV.verificationStatus)
    assert str(status) == "verified"
    assert prov_graph.value(frag, PROV.wasGeneratedBy) == activity


# ── print_report ─────────────────────────────────────────────────────────

def test_print_report_returns_fail_count(capsys):
    """print_report returns the correct number of failed checks."""
    checks = [
        CheckResult("check_a", 5, 5, []),  # PASS
        CheckResult("check_b", 3, 5, [
            Failure("trad1", "item1", "reason1"),
            Failure("trad1", "item2", "reason2"),
        ]),  # FAIL
    ]
    fail_count = print_report(checks)
    assert fail_count == 1


def test_print_report_all_pass(capsys):
    """print_report returns 0 when all checks pass."""
    checks = [
        CheckResult("check_a", 5, 5, []),
        CheckResult("check_b", 3, 3, []),
    ]
    fail_count = print_report(checks)
    assert fail_count == 0
