# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.verification with synthetic graphs."""

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
    TextOutcome,
)
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
    assert "the source also has: (Section 7.2)" in out


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


def _repo_run(repo, *, strict=False, snippet=None, fetcher=None):
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
                         fetcher=fetcher or MockFetcher(), strict_repos=strict)
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
