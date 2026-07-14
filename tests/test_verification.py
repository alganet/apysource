# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.verification with synthetic graphs."""

from unittest.mock import patch

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF

from apysource.namespaces import OA, SCHEMA, SV
from apysource.results import CheckResult, Failure, FetcherResult, RepoResult
from apysource.verification import print_report, run_checks, strip_headers

from tests.conftest import EMPTY_REGISTRY, MockFetcher, build_chain_graph


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_chain_graph():
    """Build a graph with one Fragment for chain-mode testing (OA-native)."""
    frag = URIRef("http://example.com/data/test#frag1")
    source = URIRef("http://example.com/data/test#src1")
    g = build_chain_graph(frag, source, "http://example.com/item")
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

    # Chain mode: cache resolution, extraction, source urls, snippet
    assert len(results) == 4
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

    assert len(results) == 4
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

    # Direct mode: the check itself, plus the source-url redirect check
    assert len(results) == 2
    check = results[0]
    assert check.ok == 1
    assert check.failures == []


# ── snippet matching ─────────────────────────────────────────────────────

def _chain_graph_with_snippet(snippet_text):
    """Chain-mode graph carrying a TextQuoteSelector snippet."""
    g, frag = _make_chain_graph()
    target = g.value(frag, OA.hasTarget)
    tqs = BNode()
    g.add((target, OA.hasSelector, tqs))
    g.add((tqs, RDF.type, OA.TextQuoteSelector))
    g.add((tqs, OA.exact, Literal(snippet_text)))
    return g, frag


def _run_snippet_check(snippet_text, source_text):
    """Run chain checks and return the 'snippet verified' CheckResult."""
    g, frag = _chain_graph_with_snippet(snippet_text)
    resolved = RepoResult(
        status="resolved", label="test", location="lines:1-5",
        source="test source", url="http://example.com", module="test",
        cache_file="/tmp/fake.txt",
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.get_text", return_value=source_text):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)
    return next(c for c in results if "snippet verified" in c.name)


def test_snippet_full_match_passes():
    """A long snippet present in full in the source passes."""
    snippet = "the quick brown fox jumps over the lazy dog every single morning"
    source = "Prologue. " + snippet + " The end."
    check = _run_snippet_check(snippet, source)
    assert check.ok == 1
    assert check.failures == []


def test_snippet_prefix_match_fails():
    """A snippet whose first 80 chars match but whose tail diverges must FAIL.

    Regression for the old `norm_snippet[:80] in norm_source` truncation.
    """
    prefix = ("the quick brown fox jumps over the lazy dog and then keeps on "
              "running far across the wide green field")
    assert len(prefix) > 80
    snippet = prefix + " to the WRONG ending that is not in the source at all"
    source = "Prologue. " + prefix + " to a completely different and correct ending."
    check = _run_snippet_check(snippet, source)
    assert check.ok == 0
    assert len(check.failures) == 1


def test_snippet_trailing_ellipsis_is_prefix_match():
    """A snippet ending in '...' matches the retained prefix only."""
    snippet = "the quick brown fox jumps over the lazy dog and then..."
    source = "the quick brown fox jumps over the lazy dog and then ran off elsewhere"
    check = _run_snippet_check(snippet, source)
    assert check.ok == 1
    assert check.failures == []


def test_snippet_unicode_ellipsis_is_prefix_match():
    """A snippet ending in the Unicode ellipsis '…' behaves like '...'."""
    snippet = "the quick brown fox jumps over the lazy dog and then…"
    source = "the quick brown fox jumps over the lazy dog and then ran off elsewhere"
    check = _run_snippet_check(snippet, source)
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


# ── Redirects (B1) ───────────────────────────────────────────────────────

def _run_redirect_check(url, redirects, *, strict=False):
    """Run chain checks over one HTTP-resolved source, return 'source urls'."""
    g, _frag = _make_chain_graph()
    fetcher = MockFetcher(redirects=redirects)
    resolved = FetcherResult(
        status="resolved", label="test fragment", source="test source",
        url=url, fetcher=fetcher, format_name="html",
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.get_text", return_value="x" * 100):
        results = run_checks(g, checks_config, EMPTY_REGISTRY,
                             strict_redirects=strict)
    return next(c for c in results if "source urls" in c.name)


def test_direct_url_passes_with_no_warning():
    check = _run_redirect_check("http://example.com/page", {})
    assert check.ok == 1
    assert check.total == 1
    assert check.warnings == []
    assert check.failures == []


def test_redirected_url_warns_but_does_not_fail():
    """A moved source still verifies -- but silently, which is the bug."""
    check = _run_redirect_check(
        "http://old.example.com/page",
        {"http://old.example.com/page": "http://new.example.com/page"},
    )
    assert check.ok == 0
    assert check.total == 1
    assert check.failures == []
    assert len(check.warnings) == 1
    assert "http://new.example.com/page" in check.warnings[0].reason
    assert "consider updating url:" in check.warnings[0].reason


def test_strict_redirects_turns_the_warning_into_a_failure():
    check = _run_redirect_check(
        "http://old.example.com/page",
        {"http://old.example.com/page": "http://new.example.com/page"},
        strict=True,
    )
    assert check.warnings == []
    assert len(check.failures) == 1
    assert print_report([check]) == 1


def test_unknown_destination_is_not_counted_as_clean():
    """A body cached before redirects were recorded proves nothing."""
    check = _run_redirect_check(
        "http://old.example.com/page",
        {"http://old.example.com/page": None},
    )
    assert check.total == 0
    assert check.warnings == []
    assert check.failures == []


def test_repo_resolved_sources_are_not_checked_for_redirects():
    """A repo resolves its own canonical location; its APIs redirect by design."""
    g, _frag = _make_chain_graph()
    resolved = RepoResult(
        status="resolved", label="test", location="lines:1-5",
        source="test source", url="http://example.com", module="test",
        cache_file="/tmp/fake.txt",
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.get_text", return_value="x" * 100):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    check = next(c for c in results if "source urls" in c.name)
    assert check.total == 0


def test_report_tags_a_warned_check_and_counts_it(capsys):
    checks = [
        CheckResult("clean", 1, 1, []),
        CheckResult("moved", 0, 1, [],
                    [Failure("src", "http://old/", "fetched via 301 -> http://new/")]),
    ]
    fail_count = print_report(checks)
    out = capsys.readouterr().out

    assert fail_count == 0
    assert "[WARN]" in out
    assert "1 PASS, 0 FAIL, 1 WARN" in out
    assert "http://new/" in out
    assert "EXIT CODE: 0" in out
