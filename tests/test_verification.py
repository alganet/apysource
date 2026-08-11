# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.verification with synthetic graphs."""

import json
from unittest.mock import patch

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS

from apysource.namespaces import OA, SCHEMA, SV
from apysource.diagnostics import Diagnosis
from apysource.repos import RepoRegistry
from apysource.repos._base import BaseRepo, RepoNotFound, RepoUnavailable
from apysource.results import (
    CheckResult,
    Failure,
    FetcherResult,
    RepoResult,
    Supersession,
    TextOutcome,
)
from apysource.verification import (
    failed,
    json_report,
    print_report,
    run_checks,
    strip_headers,
    verdict,
)

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
         patch("apysource.verification.load_text", return_value=TextOutcome(long_text)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    # Chain mode: cache resolution, extraction, snippet verified.
    # No Source URLs check: this source is repo-resolved, not fetched.
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
         patch("apysource.verification.load_text", return_value=TextOutcome("")):
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
         patch("apysource.verification.load_text", return_value=TextOutcome(long_text)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    # Direct mode: just the check. The source is repo-resolved, so there
    # are no fetched URLs to report on.
    assert len(results) == 1
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
         patch("apysource.verification.load_text", return_value=TextOutcome(source_text)):
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
         patch("apysource.verification.load_text", return_value=TextOutcome(long_text)):
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

    # The run *used* the fragment. It did not generate it: a citation does not
    # come into existence from the run that checks it, and the edge used to
    # claim it did.
    assert (activity, PROV.used, frag) in prov_graph
    assert prov_graph.value(frag, PROV.wasGeneratedBy) is None

    # The verdict is its own entity — it belongs to the run that reached it,
    # not to the citation it judged.
    verdicts = list(prov_graph.subjects(RDF.type, SV.VerificationResult))
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert str(prov_graph.value(verdict, SV.verificationStatus)) == "verified"
    assert prov_graph.value(verdict, PROV.wasGeneratedBy) == activity
    assert prov_graph.value(verdict, PROV.wasDerivedFrom) == frag

    # And the file stands on its own: the fragment it names is described here,
    # not only in the sources graph the reader may not have.
    assert (frag, RDF.type, SV.Fragment) in prov_graph


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

def _redirect_run(url, redirects, *, strict=False, fetched=True):
    """Run chain checks over one HTTP-resolved source, return 'Source URLs'.

    ``fetched=False`` leaves the URL unfetched, which is what a body cached
    before redirects were recorded looks like: destination unknown.
    """
    g, _frag = _make_chain_graph()
    fetcher = MockFetcher(redirects=redirects)
    if fetched:
        fetcher.get(url)
    resolved = FetcherResult(
        status="resolved", label="test fragment", source="test source",
        url=url, fetcher=fetcher, format_name="html",
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.load_text", return_value=TextOutcome("x" * 100)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY,
                             strict_redirects=strict)
    return next(c for c in results if c.name == "Source URLs")


def test_a_url_that_answered_for_itself_passes():
    check = _redirect_run("http://example.com/page", {})
    assert (check.ok, check.total) == (1, 1)
    assert check.warnings == [] and check.failures == []


def test_a_moved_url_warns_but_does_not_fail():
    """A moved source still verifies — silently, which is the bug."""
    check = _redirect_run(
        "http://old.example.com/page",
        {"http://old.example.com/page": "http://new.example.com/page"},
    )
    assert (check.ok, check.total) == (0, 1)
    assert check.failures == []
    assert "http://new.example.com/page" in check.warnings[0].reason


def test_an_unrecorded_destination_is_reported_not_skipped():
    """The bug this test used to enshrine.

    A body cached before any of this existed proves nothing about its URL.
    Dropping it from the tally rendered a warm cache as a confident green —
    the very silent pass the check exists to end, moved one level up.
    """
    check = _redirect_run("http://old.example.com/page", {}, fetched=False)

    assert check.total == 1
    assert check.ok == 0
    assert len(check.warnings) == 1
    assert "--refresh" in check.warnings[0].reason


def test_strict_redirects_fails_on_a_move():
    check = _redirect_run(
        "http://old.example.com/page",
        {"http://old.example.com/page": "http://new.example.com/page"},
        strict=True,
    )
    assert check.warnings == []
    assert len(check.failures) == 1
    assert print_report([check]) == 1


def test_strict_redirects_fails_on_an_unknown_destination():
    """"I have no evidence this URL is clean" is not a pass."""
    check = _redirect_run("http://old.example.com/page", {}, strict=True,
                          fetched=False)
    assert len(check.failures) == 1
    assert print_report([check]) == 1


def test_repo_resolved_sources_have_no_url_check():
    """A repo resolves its own canonical location; its APIs redirect by design.

    With no fetched URLs at all, the check is not emitted — an empty 0/0 line
    would say nothing.
    """
    g, _frag = _make_chain_graph()
    resolved = RepoResult(
        status="resolved", label="test", location="lines:1-5",
        source="test source", url="http://example.com", module="test",
        cache_file="/tmp/fake.txt",
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.load_text", return_value=TextOutcome("x" * 100)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    assert [c for c in results if c.name == "Source URLs"] == []


def test_the_url_check_is_emitted_once_for_the_whole_run():
    """A URL is one URL, whichever mode cited it and however many times."""
    g, _frag = _make_chain_graph()
    fetcher = MockFetcher()
    fetcher.get("http://example.com/page")
    resolved = FetcherResult(
        status="resolved", label="f", source="s",
        url="http://example.com/page", fetcher=fetcher, format_name="html",
    )
    checks_config = [
        {"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"},
        {"name": "Terms", "class_uri": SV.Term, "mode": "direct"},
    ]
    with patch("apysource.verification.resolve_chain", return_value=resolved), \
         patch("apysource.verification.resolve_direct", return_value=resolved), \
         patch("apysource.verification.load_text", return_value=TextOutcome("x" * 100)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    url_checks = [c for c in results if c.name == "Source URLs"]
    assert len(url_checks) == 1
    assert url_checks[0].total == 1


def test_report_tags_a_warned_check_and_counts_it(capsys):
    checks = [
        CheckResult("clean", 1, 1, []),
        CheckResult("moved", 0, 1, [],
                    [Failure("src", "http://old/", "moved: 301 -> http://new/")]),
    ]
    fail_count = print_report(checks)
    out = capsys.readouterr().out

    assert fail_count == 0
    assert "[WARN]" in out
    assert "1 PASS, 0 FAIL, 1 WARN" in out
    assert "http://new/" in out
    assert "EXIT CODE: 0" in out


# ── Snippet failure hints (A1) ───────────────────────────────────────────

RFC_9112 = (
    "A client MUST send a Host header field (Section 7.2 of [HTTP]) in all "
    "HTTP/1.1 request messages. If the target URI includes an authority "
    "component, then a client MUST send a field value for Host."
)


def test_snippet_failure_names_what_the_citation_dropped():
    """The spike's own mistake: the parenthetical went missing."""
    misquote = ("A client MUST send a Host header field in all HTTP/1.1 "
                "request messages.")
    check = _run_snippet_check(misquote, RFC_9112)

    hint = check.failures[0].hint
    assert hint is not None
    assert " ".join(hint.extra) == "(Section 7.2 of [HTTP])"
    assert hint.missing == []


def test_snippet_failure_calls_out_a_case_difference():
    check = _run_snippet_check(RFC_9112.lower(), RFC_9112)

    hint = check.failures[0].hint
    assert hint.kind == "differs only in case"
    assert hint.source_text == RFC_9112


def test_snippet_failure_with_nothing_close_carries_no_hint():
    """Don't invent a diagnosis when the quote is simply not there."""
    check = _run_snippet_check(
        "Entirely unrelated wording about marmalade and bicycles",
        RFC_9112,
    )
    assert check.failures[0].hint is None


def test_report_prints_the_hint_under_its_failure(capsys):
    diagnosis = Diagnosis(source_text="what the source says", ratio=0.81,
                          extra=["(Section", "7.2)"])
    checks = [
        CheckResult("snippet", 0, 1, [
            Failure("src", "frag", "snippet not found in extracted content",
                    diagnosis),
        ]),
    ]
    print_report(checks)
    out = capsys.readouterr().out

    assert "snippet not found in extracted content" in out
    assert "closest match (81% similar)" in out
    assert "that passage also has: (Section 7.2)" in out


# ── Repo documents (B4/B5) ───────────────────────────────────────────────
#
# These run end to end: real registry, real resolution, real crawl. Patching
# the text out would skip the very code under test — the crawl, and what it
# does when the document is not there.

class _ScriptedRepo(BaseRepo):
    NAME = "scripted"
    supports_crawl = True

    def __init__(self, tmp_path, outcome="ok"):
        super().__init__(cache_dir=tmp_path, url_pattern=r"example\.com",
                         base_url="https://example.com")
        self.outcome = outcome

    def url_to_key(self, url):
        return "doc"

    def resolve_location(self, loc, key):
        p = self.cache_dir / f"{key}.txt"
        return p if p.exists() else None

    def extract_content(self, loc, path):
        return path.read_text()

    def crawl(self, key, *, delay=None, force=False, from_cache=False):
        if self.outcome == "not_found":
            raise RepoNotFound(self.NAME, key, "404")
        if self.outcome == "unavailable":
            raise RepoUnavailable(self.NAME, key, "connection reset")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.txt").write_text("the document " * 20)


class _NoCrawlerRepo(BaseRepo):
    NAME = "lazy"

    def url_to_key(self, url):
        return "doc"

    def resolve_location(self, loc, key):
        return None


def _repo_run(repo, *, strict=False, snippet=None, fetcher=None,
              strict_supersession=False, crawl=True):
    """Run the full checks over one repo-claimed source."""
    frag = URIRef("http://x/frag")
    g = build_chain_graph(frag, URIRef("http://x/src"),
                          "https://example.com/page", location="")
    if snippet is not None:
        target = next(g.objects(frag, OA.hasTarget))
        sel = BNode()
        g.add((target, OA.hasSelector, sel))
        g.add((sel, RDF.type, OA.TextQuoteSelector))
        g.add((sel, OA.exact, Literal(snippet)))

    checks_config = [{"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"}]
    results = run_checks(g, checks_config, RepoRegistry([repo]),
                         fetcher=fetcher or MockFetcher(), strict_repos=strict,
                         strict_supersession=strict_supersession, crawl=crawl)
    return {c.name: c for c in results}


def test_a_crawled_document_passes_the_repo_check(tmp_path):
    checks = _repo_run(_ScriptedRepo(tmp_path))
    repo_check = checks["Repo documents"]
    assert (repo_check.ok, repo_check.total) == (1, 1)
    assert repo_check.failures == [] and repo_check.warnings == []


def test_a_missing_repo_document_fails_with_its_own_reason(tmp_path):
    """Not "empty extraction (0 chars)". The page is gone; say that."""
    checks = _repo_run(_ScriptedRepo(tmp_path, "not_found"))

    repo_check = checks["Repo documents"]
    assert len(repo_check.failures) == 1
    assert "has no such document" in repo_check.failures[0].reason

    extraction = checks["Fragments: content extraction"]
    assert len(extraction.failures) == 1
    assert "no such document" in extraction.failures[0].reason
    assert "empty extraction" not in extraction.failures[0].reason


def test_a_missing_repo_document_does_not_blame_the_snippet(tmp_path):
    """The source never arrived, so "snippet not found" would be a lie about it."""
    checks = _repo_run(_ScriptedRepo(tmp_path, "not_found"),
                       snippet="a quote that is long enough to be checked")
    snippets = checks["Fragments: snippet verified"]
    assert len(snippets.failures) == 1
    assert "snippet not found" not in snippets.failures[0].reason
    assert "no such document" in snippets.failures[0].reason


def test_a_transient_failure_is_not_reported_as_a_missing_page(tmp_path):
    checks = _repo_run(_ScriptedRepo(tmp_path, "unavailable"))
    failures = checks["Repo documents"].failures
    assert len(failures) == 1
    assert "could not fetch" in failures[0].reason
    assert "unknown" in failures[0].reason
    assert "no such document" not in failures[0].reason


def test_a_repo_fallback_warns_but_does_not_fail(tmp_path):
    """It still verified — against the fetched page, not the repo. Say so."""
    repo = _NoCrawlerRepo(cache_dir=tmp_path, url_pattern=r"example\.com",
                          base_url="https://example.com")
    checks = _repo_run(repo, fetcher=MockFetcher(content="x" * 200))

    repo_check = checks["Repo documents"]
    assert repo_check.failures == []
    assert len(repo_check.warnings) == 1
    assert "lazy claims this URL" in repo_check.warnings[0].reason


def test_strict_repos_turns_a_fallback_into_a_failure(tmp_path):
    repo = _NoCrawlerRepo(cache_dir=tmp_path, url_pattern=r"example\.com",
                          base_url="https://example.com")
    checks = _repo_run(repo, strict=True, fetcher=MockFetcher(content="x" * 200))
    assert len(checks["Repo documents"].failures) == 1


def test_the_repo_check_is_silent_when_nothing_had_to_be_crawled(tmp_path):
    """A warm cache crawls nothing, and nothing is not a pass.

    Reporting "1/1 PASS" for a document this check never looked at is exactly
    the confident green that made the redirect check inert on a warm cache.
    """
    (tmp_path / "doc.txt").write_text("already here " * 20)
    checks = _repo_run(_ScriptedRepo(tmp_path))
    assert "Repo documents" not in checks


def test_the_repo_check_is_absent_without_repos():
    """No repos, nothing to say."""
    g, _frag = _make_chain_graph()
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.load_text",
               return_value=TextOutcome("x" * 100)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY,
                             fetcher=MockFetcher())
    assert all(c.name != "Repo documents" for c in results)


# ── Document supersession ────────────────────────────────────────────────
#
# The only check here that asks whether this is still the source, rather than
# whether the source still says this.

class _CurrencyRepo(_ScriptedRepo):
    """A repo whose publisher records when a document has been replaced."""

    supports_supersession = True

    def __init__(self, tmp_path, status="current", by=(), outcome="ok"):
        super().__init__(tmp_path, outcome=outcome)
        self.status = status
        self.by = list(by)
        self.asks = 0
        self.from_cache_asks = []

    def supersession(self, key, *, from_cache=False):
        self.asks += 1
        self.from_cache_asks.append(from_cache)
        if self.status == "unknown":
            raise RepoUnavailable(self.NAME, key, "connection reset")
        return Supersession(self.NAME, key, self.status, superseded_by=self.by)


def test_a_document_still_in_force_passes_the_supersession_check(tmp_path):
    check = _repo_run(_CurrencyRepo(tmp_path))["Document supersession"]
    assert (check.ok, check.total) == (1, 1)
    assert check.failures == [] and check.warnings == []


def test_a_superseded_document_warns_and_names_its_successor(tmp_path):
    """The run stays green. The quote is there; it is the document that moved on.

    Citing a replaced document is sometimes the only option available — the
    successor may have deleted the very thing being described — so this is a
    thing to know, not a thing to fail on.
    """
    checks = _repo_run(_CurrencyRepo(tmp_path, "superseded", ["rfc9110"]),
                       snippet="the document the document")

    check = checks["Document supersession"]
    assert check.failures == []
    assert len(check.warnings) == 1
    assert "superseded by rfc9110" in check.warnings[0].reason

    # The quote itself verified, and the run goes out green. The two are
    # independent findings: the sentence really is in that document, and that
    # document really has been replaced.
    assert checks["Fragments: snippet verified"].failures == []
    assert not failed(list(checks.values()))


def test_a_document_withdrawn_with_no_successor_says_so(tmp_path):
    """An empty successor list must not read as "replaced by nothing in
    particular, we just didn't look it up"."""
    checks = _repo_run(_CurrencyRepo(tmp_path, "superseded"))
    reason = checks["Document supersession"].warnings[0].reason
    assert "with no replacement named" in reason


def test_strict_supersession_turns_the_warning_into_a_failure(tmp_path):
    """For a collection that means to track only documents in force."""
    checks = _repo_run(_CurrencyRepo(tmp_path, "superseded", ["rfc9110"]),
                       snippet="the document the document",
                       strict_supersession=True)

    check = checks["Document supersession"]
    assert len(check.failures) == 1 and check.warnings == []
    assert failed(list(checks.values()))


def test_an_undetermined_currency_is_reported_rather_than_assumed_good(tmp_path):
    """Silence would render "we could not tell" as green.

    This is the argument the redirect check makes for reporting an unrecorded
    destination instead of skipping it, and it applies here unchanged.
    """
    check = _repo_run(_CurrencyRepo(tmp_path, "unknown"))["Document supersession"]

    assert (check.ok, check.total) == (0, 1)
    assert len(check.warnings) == 1
    assert "could not determine" in check.warnings[0].reason
    assert "connection reset" in check.warnings[0].reason


def test_a_repo_that_does_not_track_supersession_produces_no_row(tmp_path):
    """There is no such thing as an obsolete Wiktionary entry.

    A row of zeroes would be an answer to a question nobody can ask, and the
    reader would be left to work out which of "none" and "not applicable" it
    meant.
    """
    assert "Document supersession" not in _repo_run(_ScriptedRepo(tmp_path))


def test_a_warm_cache_still_reports_a_superseded_document(tmp_path):
    """The load-bearing case, and the one an obvious implementation loses.

    A crawl happens only when the cache is cold, so anything hung off it goes
    quiet on a warm run — which is exactly the run where this has had time to
    become true. The document was cached while it was current and replaced
    afterwards; not one byte of it changed.

    Note what the repo check does on this same run: nothing, correctly, because
    nothing was crawled. These two must not share a trigger.
    """
    (tmp_path / "doc.txt").write_text("already here " * 20)
    repo = _CurrencyRepo(tmp_path, "superseded", ["rfc9110"])
    checks = _repo_run(repo)

    assert "Repo documents" not in checks
    assert len(checks["Document supersession"].warnings) == 1
    assert repo.asks == 1


def test_an_offline_run_still_reports_from_a_cached_answer(tmp_path):
    """`--no-crawl` verifies quotes from disk; this must read from disk too.

    Found by running the real corpus: every quote verified against a fully
    warm cache and six superseded documents went unmentioned, while the
    answers for all of them were already in the HTTP cache. Skipping the
    lookup entirely made this the one check that stayed quiet about something
    it knew.
    """
    (tmp_path / "doc.txt").write_text("already here " * 20)
    repo = _CurrencyRepo(tmp_path, "superseded", ["rfc9110"])
    checks = _repo_run(repo, crawl=False)

    assert len(checks["Document supersession"].warnings) == 1
    assert repo.from_cache_asks == [True]


def test_an_offline_run_with_no_cached_answer_says_nothing(tmp_path):
    """Not a row of "unknown" per document. We declined to ask."""
    (tmp_path / "doc.txt").write_text("already here " * 20)
    repo = _CurrencyRepo(tmp_path, "unknown")
    assert "Document supersession" not in _repo_run(repo, crawl=False)


def test_the_supersession_question_is_asked_once_for_the_run(tmp_path):
    """Resolution and prefetch both reach for it; the memo makes that one ask."""
    repo = _CurrencyRepo(tmp_path)
    _repo_run(repo)
    assert repo.asks == 1


# ── Naming failures (A3) ─────────────────────────────────────────────────
#
# A failure used to be reported as the slugified URN the loader made by gluing
# the source and fragment labels together — printed twice, once as the group
# header and once as the line prefix. The author then had to de-slugify their
# own YAML to find out what had failed.

def _named_run(source_label, frag_label, url, snippet=None, text="x" * 100):
    frag = URIRef("http://x/frag")
    src = URIRef("http://x/src")
    g = build_chain_graph(frag, src, url, location="", label=frag_label)
    g.set((src, RDFS.label, Literal(source_label)))
    if snippet is not None:
        target = next(g.objects(frag, OA.hasTarget))
        sel = BNode()
        g.add((target, OA.hasSelector, sel))
        g.add((sel, RDF.type, OA.TextQuoteSelector))
        g.add((sel, OA.exact, Literal(snippet)))

    checks_config = [{"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.load_text",
               return_value=TextOutcome(text)):
        results = run_checks(g, checks_config, EMPTY_REGISTRY,
                             fetcher=MockFetcher())
    return {c.name: c for c in results}


def test_a_failure_names_the_source_and_the_fragment():
    """The live MDN case: the labels the author wrote, not a mangled URN."""
    checks = _named_run(
        "MDN: Origin (stale pre-redirect URL)", "mdn_stale",
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin",
        snippet="a quote long enough to actually be verified",
    )
    failure = checks["Fragments: snippet verified"].failures[0]

    assert failure.group == "MDN: Origin (stale pre-redirect URL)"
    assert failure.item == "mdn_stale"
    assert failure.url == (
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin")
    # The URN is still carried — it is the identity, and the provenance
    # subject — it is simply not what a person is made to read.
    assert failure.urn.startswith("http://x/frag")


def test_a_failure_does_not_print_the_urn(capsys):
    """What the reader actually sees."""
    checks = _named_run(
        "MDN: Origin (stale pre-redirect URL)", "mdn_stale",
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Origin",
        snippet="a quote long enough to actually be verified",
    )
    print_report(list(checks.values()))
    out = capsys.readouterr().out

    assert "MDN: Origin (stale pre-redirect URL)" in out
    assert "mdn_stale" in out
    assert "urn:apysource:" not in out


def test_a_label_with_a_slash_survives_the_report():
    """The URN mangles separators (`/` -> `_`), so grepping the report failed.

    lint-http labels fragments by rule-file path; the slug ate the paths.
    """
    checks = _named_run("RFC 9110", "helpers/headers.rs",
                        "https://www.rfc-editor.org/rfc/rfc9110.txt",
                        snippet="a quote long enough to actually be verified")
    assert checks["Fragments: snippet verified"].failures[0].item == \
        "helpers/headers.rs"


def test_a_fragment_with_no_source_still_reports_something():
    """The no_source path leaves the labels empty. A blank name is worse than an ugly one."""
    frag = URIRef("http://example.com/data#orphan")
    g = Graph()
    g.add((frag, RDF.type, SV.Fragment))
    g.add((frag, RDFS.label, Literal("orphaned")))

    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    results = run_checks(g, checks_config, EMPTY_REGISTRY, fetcher=MockFetcher())
    failure = next(c for c in results if "cache resolution" in c.name).failures[0]

    assert failure.group == "(no source)"
    assert failure.item == "orphaned"   # the fragment label survives
    assert failure.reason.endswith("no_source")


def test_a_term_failure_carries_its_label():
    """resolve_direct never read the Term's rdfs:label, though SHACL mandates one."""
    term = URIRef("http://example.com/data#term1")
    g = Graph()
    g.add((term, RDF.type, SV.Term))
    g.add((term, RDFS.label, Literal("aletheia")))
    g.add((term, SCHEMA.url, Literal("http://example.com/lexicon")))

    checks_config = [{"name": "Terms", "class_uri": SV.Term, "mode": "direct"}]
    with patch("apysource.verification.load_text",
               return_value=TextOutcome("", "unavailable", "could not fetch")):
        results = run_checks(g, checks_config, EMPTY_REGISTRY,
                             fetcher=MockFetcher())

    failure = results[0].failures[0]
    assert failure.item == "aletheia"
    assert failure.url == "http://example.com/lexicon"


# ── The report as data (C1) ──────────────────────────────────────────────

def _both_reports(source_text="x" * 100, snippet=None):
    checks = _named_run("RFC 9110", "client_host_header",
                        "https://www.rfc-editor.org/rfc/rfc9110.txt",
                        snippet=snippet, text=source_text)
    return list(checks.values())


def test_json_and_text_reports_agree_on_the_verdict(capsys):
    """Two renderers is two chances to disagree about whether a run was green.

    They share one verdict function precisely so they cannot.
    """
    checks = _both_reports(snippet="a quote that is nowhere in this source text")

    fail_count = print_report(checks)
    capsys.readouterr()
    report = json_report(checks)

    assert report["summary"]["fail"] == fail_count
    assert report["summary"]["failed"] is (fail_count > 0)

    for check, record in zip(checks, report["checks"]):
        assert record["name"] == check.name
        assert record["ok"] == check.ok
        assert record["total"] == check.total
        assert record["status"] == verdict(check)


def test_json_report_is_serializable_and_routes_by_label():
    """What CI actually needs: the label, to route a failure back to its file."""
    checks = _both_reports(snippet="a quote that is nowhere in this source text")
    report = json_report(checks)

    round_tripped = json.loads(json.dumps(report))   # no live objects survive in

    failures = [f for c in round_tripped["checks"] for f in c["failures"]]
    assert failures
    record = failures[0]
    assert record["source"] == "RFC 9110"
    assert record["label"] == "client_host_header"
    assert record["url"] == "https://www.rfc-editor.org/rfc/rfc9110.txt"
    assert record["urn"].startswith("http://x/frag")


def test_json_serves_the_diagnosis_as_data_not_prose():
    """The diagnosis was kept structured for exactly this. Cash the cheque."""
    source = "The quick brown fox jumps over the lazy dog every single morning."
    snippet = "The quick brown fox leaps over the lazy dog every single morning."
    checks = _both_reports(source_text=source, snippet=snippet)

    report = json_report(checks)
    failures = [f for c in report["checks"] for f in c["failures"] if "hint" in f]
    assert failures

    hint = failures[0]["hint"]
    assert "leaps" in hint["missing"] or "jumps" in hint["extra"]
    assert hint["source_text"]
    # percent is a property, so asdict drops it; it is the number a reader looks
    # at, so it is put back explicitly.
    assert hint["percent"] == round(hint["ratio"] * 100)


def test_a_green_run_reports_no_failures_either_way(capsys):
    source = "the quick brown fox jumps over the lazy dog every single morning"
    checks = _both_reports(source_text="Prologue. " + source + " The end.",
                           snippet=source)
    fail_count = print_report(checks)
    capsys.readouterr()

    report = json_report(checks)
    assert fail_count == 0
    assert report["summary"]["fail"] == 0
    assert report["summary"]["failed"] is False
    assert all(not c["failures"] for c in report["checks"])


# ── The whole document, not a prefix of it ───────────────────────────────

def test_a_citation_past_the_first_100k_chars_is_still_found():
    """The snippet check read the first 100,000 characters of the source.

    RFC 9110 is 502,907 characters, so that is a fifth of it — and a real
    citation into its status-code definitions came back as "snippet not found
    in extracted content": a flat claim about a document the check had never
    read to the end of. Nothing was bought by the cap. The substring test is
    linear, and diagnosing a miss across a whole specification takes a tenth of
    a second.

    Every other snippet test patches ``load_text`` — which is the function
    that did the truncating — so none of them could ever have seen this. This
    one goes through the real thing.
    """
    from pathlib import Path
    body = (Path(__file__).parent / "fixtures" / "un_charter.html").read_text(
        encoding="utf-8")
    snippet = ("The General Assembly and, under its authority, the Trusteeship "
               "Council, in carrying out their functions")

    at = body.find(snippet)
    assert at > 100_000, "fixture no longer reaches past the old cap; pick a later passage"

    g, frag = _chain_graph_with_snippet(snippet)
    resolved = FetcherResult(
        status="resolved", label="trusteeship", source="UN Charter",
        url="http://example.com/charter.html",
        fetcher=MockFetcher(content=body),
        format_name="text/html", locator=None,
    )
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)

    check = next(c for c in results if "snippet verified" in c.name)
    assert check.ok == 1, f"a passage at char {at:,} must still be found"
    assert check.failures == []


# ── A green run must have verified something ─────────────────────────────

def _snippet_check(graph_builder):
    resolved = FetcherResult(
        status="resolved", label="frag", source="RFC 9110",
        url="http://example.com/spec",
        fetcher=MockFetcher(content="The Host header field provides the host."),
        format_name="text/plain", locator=None,
    )
    g, _frag = graph_builder()
    checks_config = [{"name": "F", "class_uri": SV.Fragment, "mode": "chain"}]
    with patch("apysource.verification.resolve_chain", return_value=resolved):
        results = run_checks(g, checks_config, EMPTY_REGISTRY)
    return next(c for c in results if "snippet verified" in c.name)


def test_a_fragment_with_no_snippet_is_a_failure_not_an_omission():
    """It reported `[----] snippet verified 0/0` and `EXIT CODE: 0`.

    Fragments with no usable snippet were filtered out of the check entirely —
    not passed, not failed, absent from both sides of the tally. A file whose
    fragments had lost their snippets (a misspelled `snipet:`, or a `section:`
    and nothing else) printed "all checks passed" for a run in which **not one
    citation was checked**. The single thing this tool exists to do had been
    skipped, silently, and the build was green.
    """
    check = _snippet_check(_make_chain_graph)   # a fragment with no oa:exact

    assert check.total == 1, "the fragment must be answered for, not dropped"
    assert check.ok == 0
    assert len(check.failures) == 1
    assert "nothing to verify" in check.failures[0].reason


def test_a_snippet_too_short_to_be_evidence_is_a_failure():
    """"MUST" appears in every specification ever written."""
    check = _snippet_check(lambda: _chain_graph_with_snippet("MUST"))

    assert check.total == 1 and check.ok == 0
    assert "too short to be evidence" in check.failures[0].reason


def test_a_real_snippet_still_passes():
    """The fix must not simply fail everything."""
    check = _snippet_check(
        lambda: _chain_graph_with_snippet("The Host header field provides the host."))
    assert check.ok == 1 and check.failures == []


def test_a_run_that_verified_nothing_is_not_a_pass():
    """`sources: []` reported "0 PASS, 0 FAIL — EXIT CODE: 0 (all checks passed)".

    A verifier asked to verify nothing, answering "everything is fine", is the
    silent green this tool exists to abolish. It happens in practice when a
    generator breaks and emits an empty file — after which CI stays green
    forever and nobody looks again.
    """
    from apysource.verification import failed, nothing_verified, tally

    empty = [CheckResult("Fragments", 0, 0, []), CheckResult("Terms", 0, 0, [])]
    assert nothing_verified(empty)
    assert failed(empty), "a run that checked nothing has not passed"
    assert tally(empty)["fail"] == 0, "no citation failed; the *run* did"

    real = [CheckResult("Fragments", 1, 1, [])]
    assert not nothing_verified(real)
    assert not failed(real)


# ── Concurrency: what must not change when workers are added ────────────

class TestWorkersChangeNothingButSpeed:
    """The prefetch is advisory. These say what that has to mean."""

    def _graph_and_fetcher(self, count, workers):
        """`count` fragments over `count` sources, all fetchable."""
        from tests.conftest import MockFetcher
        from rdflib import BNode, Graph, Literal
        from rdflib.namespace import RDF, RDFS
        from apysource.namespaces import OA, SCHEMA, SV

        body = "Hello world. " + ("the quick brown fox jumps over it. " * 40)
        g = Graph()
        for i in range(count):
            frag = URIRef(f"urn:apysource:fragment_{i:03d}")
            src = URIRef(f"urn:apysource:source_{i:03d}")
            g.add((frag, RDF.type, SV.Fragment))
            g.add((frag, RDFS.label, Literal(f"fragment {i:03d}")))
            target = BNode()
            g.add((frag, OA.hasTarget, target))
            g.add((target, OA.hasSource, src))
            sel = BNode()
            g.add((target, OA.hasSelector, sel))
            g.add((sel, RDF.type, OA.TextQuoteSelector))
            g.add((sel, OA.exact, Literal("the quick brown fox jumps over it.")))
            g.add((src, RDF.type, SV.Source))
            g.add((src, RDFS.label, Literal(f"source {i:03d}")))
            g.add((src, SCHEMA.url, Literal(f"https://example.com/doc{i:03d}")))

        fetcher = MockFetcher(content=body)
        fetcher.workers = workers
        return g, fetcher

    def test_one_worker_and_eight_report_exactly_the_same_thing(self):
        """Not "the same counts" — the same report.

        Ordering is the thing at risk when work is spread across threads, and a
        pass/fail tally would hide a reordering completely. `json_report`
        carries the failures in the order the checks built them, so comparing it
        whole is what actually pins the promise.
        """
        from apysource.api import check_graph
        from apysource.verification import json_report

        g1, f1 = self._graph_and_fetcher(24, workers=1)
        g8, f8 = self._graph_and_fetcher(24, workers=8)

        serial = json_report(check_graph(g1, registry=EMPTY_REGISTRY, fetcher=f1))
        parallel = json_report(check_graph(g8, registry=EMPTY_REGISTRY, fetcher=f8))

        assert serial == parallel

    def test_a_document_is_still_fetched_once_per_url(self):
        """The prefetch must dedupe by document, not fan out per fragment."""
        from apysource.api import check_graph

        g, fetcher = self._graph_and_fetcher(12, workers=4)
        check_graph(g, registry=EMPTY_REGISTRY, fetcher=fetcher)

        assert len(fetcher.calls) == len(set(fetcher.calls)), (
            f"a URL was fetched more than once: {fetcher.calls}"
        )

    def test_a_prefetch_that_explodes_does_not_fail_the_run(self):
        """A warm-up can never be necessary, so it must never be fatal.

        Whatever it hit will be hit again on the serial path, where there is a
        report to say it in — so the run must come out the same as if the
        prefetch had never been asked for.
        """
        from apysource.api import check_graph
        from apysource.verification import json_report

        g_ok, f_ok = self._graph_and_fetcher(8, workers=1)
        expected = json_report(check_graph(g_ok, registry=EMPTY_REGISTRY, fetcher=f_ok))

        g, fetcher = self._graph_and_fetcher(8, workers=4)
        real_get = fetcher.get
        calls = {"n": 0}

        def explode_during_prefetch(url, **kwargs):
            # Blow up only while several threads are running; the serial pass
            # that follows gets the real thing.
            calls["n"] += 1
            if calls["n"] <= 8:
                raise RuntimeError("prefetch went wrong")
            return real_get(url, **kwargs)

        fetcher.get = explode_during_prefetch
        got = json_report(check_graph(g, registry=EMPTY_REGISTRY, fetcher=fetcher))

        assert got == expected


class TestOneDocumentIsReadOnce:
    def test_many_fragments_on_one_url_fetch_it_once(self):
        """The shape a large sources file actually has.

        Fifty citations of one specification are one document. This was two
        loads per fragment — a hundred reads, and for HTML a hundred parses —
        of bytes that had not changed between the first and the last.
        """
        from rdflib import BNode, Graph, Literal
        from rdflib.namespace import RDF, RDFS
        from apysource.api import check_graph
        from apysource.namespaces import OA, SCHEMA, SV
        from tests.conftest import MockFetcher

        url = "https://example.com/one-big-page"
        body = "Hello world. " + ("the quick brown fox jumps over it. " * 40)

        g = Graph()
        src = URIRef("urn:apysource:source_one")
        g.add((src, RDF.type, SV.Source))
        g.add((src, RDFS.label, Literal("one source")))
        g.add((src, SCHEMA.url, Literal(url)))
        for i in range(50):
            frag = URIRef(f"urn:apysource:fragment_{i:03d}")
            g.add((frag, RDF.type, SV.Fragment))
            g.add((frag, RDFS.label, Literal(f"fragment {i:03d}")))
            target = BNode()
            g.add((frag, OA.hasTarget, target))
            g.add((target, OA.hasSource, src))
            sel = BNode()
            g.add((target, OA.hasSelector, sel))
            g.add((sel, RDF.type, OA.TextQuoteSelector))
            g.add((sel, OA.exact, Literal("the quick brown fox jumps over it.")))

        fetcher = MockFetcher(content=body)
        check_graph(g, registry=EMPTY_REGISTRY, fetcher=fetcher)

        assert fetcher.calls.count(url) == 1, (
            f"one document, 50 citations, {fetcher.calls.count(url)} fetches"
        )


class TestPrefetchOnlyWarmsWhatIsNotHere:
    """Concurrency that cannot be used should not be paid for.

    Warming a document that is already on disk overlaps nothing — there is no
    network wait — and costs a thread pool plus reading and decoding the whole
    corpus up front, where the serial path reads each one just before using it.
    Measured at about 7% and tens of megabytes on a warm run over a thousand
    documents. Re-checking an unchanged sources file is the commonest thing this
    tool does, and it is exactly the case with nothing to gain.
    """

    def test_a_cached_document_is_not_warmed(self):
        from apysource.resolution import _needs_fetching
        from apysource.results import FetcherResult
        from tests.conftest import MockFetcher

        result = FetcherResult(status="resolved", url="https://example.com/a",
                               fetcher=MockFetcher(cached=True))

        assert _needs_fetching(result, force=False) is False

    def test_an_uncached_document_is_warmed(self):
        from apysource.resolution import _needs_fetching
        from apysource.results import FetcherResult
        from tests.conftest import MockFetcher

        result = FetcherResult(status="resolved", url="https://example.com/a",
                               fetcher=MockFetcher(cached=False))

        assert _needs_fetching(result, force=True) is True
        assert _needs_fetching(result, force=False) is True

    def test_refresh_warms_everything_however_warm_the_cache_is(self):
        """`--refresh` is the one case where a cached document still needs the
        network, so the skip must not apply to it."""
        from apysource.resolution import _needs_fetching
        from apysource.results import FetcherResult
        from tests.conftest import MockFetcher

        result = FetcherResult(status="resolved", url="https://example.com/a",
                               fetcher=MockFetcher(cached=True))

        assert _needs_fetching(result, force=True) is True

    def test_a_fetcher_that_cannot_answer_is_warmed_anyway(self):
        """The safe way round: a needless warm-up costs a little, and a serial
        crawl that believed it was parallel costs the whole run."""
        from apysource.resolution import _needs_fetching
        from apysource.results import FetcherResult

        class _Old:
            def get(self, url, **kwargs):
                return "body"

        result = FetcherResult(status="resolved", url="https://example.com/a",
                               fetcher=_Old())

        assert _needs_fetching(result, force=False) is True

    def test_a_warm_run_reads_each_document_once_whatever_the_worker_count(self):
        """The end of it: warm, the worker count changes nothing at all."""
        from apysource.api import check_graph

        counts = {}
        for workers in (1, 8):
            g, fetcher = TestWorkersChangeNothingButSpeed()._graph_and_fetcher(
                12, workers=workers)
            fetcher.cached = True
            check_graph(g, registry=EMPTY_REGISTRY, fetcher=fetcher)
            counts[workers] = len(fetcher.calls)

        assert counts[1] == counts[8], (
            f"warm run did {counts[8]} reads with workers, {counts[1]} without"
        )
