# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""apysource Verification — source-grounding checks.

All functions require a RepoRegistry instance — no global state.
"""

import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, cast

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from apysource.diagnostics import diagnose, render
from apysource.formats import normalize_ws
from apysource.graph import local_name
from apysource.namespaces import PROV, SV
from apysource.repos import RepoRegistry
from apysource.resolution import _get_snippet, load_text, resolve_chain, resolve_direct
from apysource.results import CheckResult, Failure, FetcherResult, RepoResult

#: Minimum extracted-content length (in characters) to treat as a usable
#: extraction. Below this, the snippet/extraction check fails rather than
#: silently matching against near-empty text.
MIN_EXTRACT_CHARS = 20


def strip_headers(text: str) -> str:
    """Strip comment headers and blank lines, return actual content only."""
    if not text:
        return ""
    lines = text.split("\n")
    content = [line for line in lines if not line.startswith("#") and line.strip()]
    return "\n".join(content).strip()


def _failure(result: Any, uri: URIRef, reason: str,
             hint: Any = None) -> Failure:
    """Name a failure the way its author would recognize it.

    The labels are what someone wrote in the YAML; the URN is what the loader
    made of them, by gluing the source and fragment labels together and
    slugifying the result. Reporting the URN — twice, as it happens — made the
    reader de-slugify their own file to find out what had failed, and mangled
    the separators on the way (``/`` became ``_``), so grepping the report for
    a rule id did not work either.

    The URN is still carried, because it is the stable identity and the subject
    of the provenance graph. It is simply not what a person should have to read.
    """
    return Failure(
        group=result.source or "(no source)",
        item=result.label or local_name(uri),
        reason=reason,
        hint=hint,
        url=result.url,
        urn=str(uri),
    )


def _redirect_check(name: str, results: list[Any],
                    strict: bool = False) -> CheckResult:
    """Report source URLs that were answered by a different URL.

    Only URLs fetched over HTTP are considered: a repo resolves its own
    canonical location, and its API endpoints redirect by design.

    A URL whose destination is unknown — its body was cached before any of
    this existed — is reported, not skipped. Dropping it would render a
    warm pre-existing cache as a confident green, which is the silent pass
    this check exists to end, just moved one level up. ``--refresh`` turns
    an unknown into a known.
    """
    ok = 0
    records = []
    seen: set[str] = set()

    for result in results:
        if not isinstance(result, FetcherResult) or result.fetcher is None:
            continue
        if not result.url or result.url in seen:
            continue

        # The fetcher is injected and duck-typed; a custom one need not
        # record redirects at all, and then there is nothing to report.
        redirect_for = getattr(result.fetcher, "redirect_for", None)
        if redirect_for is None:
            continue

        seen.add(result.url)
        info = redirect_for(result.url)

        if info is None:
            records.append(Failure(
                result.source or "source", result.url,
                "destination not recorded; run --refresh to check whether "
                "this URL still answers for itself",
                url=result.url,
            ))
        elif info.redirected:
            hops = " -> ".join(f"{status} {hop}" for status, hop in info.chain)
            records.append(Failure(
                result.source or "source", result.url,
                f"moved: {hops} -> {info.final_url}. The snippet was verified "
                f"against the destination, not this URL; update it.",
                url=result.url,
            ))
        else:
            ok += 1

    total = ok + len(records)
    if strict:
        return CheckResult(name, ok, total, failures=records)
    return CheckResult(name, ok, total, warnings=records)


def _repo_check(name: str, results: list[Any], strict: bool = False) -> CheckResult:
    """Report what the repos could and could not serve.

    Reads what the extraction phase already produced — the crawl outcomes the
    repos recorded — the way the URL check reads the sidecar the fetch wrote.
    It performs no I/O and invents no outcome for a document nobody had to
    crawl.

    A repo that matched a URL but could not serve it is a *warning*, not a
    pass: the snippet was verified, but against the rendered web page rather
    than the repository the citation names. That warning depends on the URL
    pattern and the crawler, never on the cache, so it cannot go quiet on a
    warm run.

    A warm cache crawls nothing and so has no outcome at all. It contributes
    neither a pass nor a failure here — counting it ``ok`` would report success
    for a document this check never looked at, which is the confident green it
    exists to prevent.
    """
    ok = 0
    records = []
    seen: set[tuple[str, str]] = set()
    fallbacks: set[str] = set()

    for result in results:
        if isinstance(result, RepoResult) and result.repo is not None:
            crawl_outcome = getattr(result.repo, "crawl_outcome", None)
            if crawl_outcome is None:
                continue
            outcome = crawl_outcome(result.key)
            if outcome is None:  # never crawled: already cached, nothing to say
                continue

            ident = (outcome.repo, outcome.key)
            if ident in seen:
                continue
            seen.add(ident)

            if outcome.status == "ok":
                ok += 1
            elif outcome.status == "not_found":
                records.append(Failure(
                    result.source or outcome.repo, result.url or outcome.key,
                    f"{outcome.repo} has no such document: {outcome.key}. "
                    f"The page this cites has moved or been removed; the URL "
                    f"may still redirect somewhere, but the source does not.",
                    url=result.url,
                ))
            else:
                records.append(Failure(
                    result.source or outcome.repo, result.url or outcome.key,
                    f"{outcome.repo} could not fetch {outcome.key}"
                    + (f": {outcome.reason}" if outcome.reason else "")
                    + ". Whether the document exists is unknown.",
                    url=result.url,
                ))

        elif isinstance(result, FetcherResult) and result.fallback_from:
            if result.url in fallbacks:
                continue
            fallbacks.add(result.url)
            records.append(Failure(
                result.source or "source", result.url,
                f"{result.fallback_from} claims this URL but "
                f"{result.fallback_reason}. The snippet was verified against "
                f"the fetched page, not against {result.fallback_from}.",
                url=result.url,
            ))

    total = ok + len(records)
    if strict:
        return CheckResult(name, ok, total, failures=records)

    # A document the repo genuinely does not have is a failure either way: it
    # is a finding about the source, not a caveat about how it was checked.
    hard = [f for f in records if " has no such document: " in f.reason
            or " could not fetch " in f.reason]
    soft = [f for f in records if f not in hard]
    return CheckResult(name, ok, total, failures=hard, warnings=soft)


def run_checks(
    g: Graph, checks_config: list[dict[str, Any]], registry: RepoRegistry,
    fetcher: Any = None, emit_provenance: bool = False, force: bool = False,
    strict_redirects: bool = False, strict_repos: bool = False,
    crawl: bool = True,
) -> list[CheckResult] | tuple[list[CheckResult], Graph]:
    """Run all checks, return structured results.

    checks_config: list of dicts with keys:
      - name: str
      - class_uri: URIRef
      - mode: "chain" | "direct" | "custom"
      - handler: callable (only for mode="custom")

    When emit_provenance is True, returns (results, prov_graph) where
    prov_graph contains PROV-O triples recording the verification activity.
    """
    results = []
    resolved_sources: list[Any] = []
    prov_graph = Graph() if emit_provenance else None
    activity = None

    if emit_provenance and prov_graph is not None:
        from apysource.namespaces import bind_prefixes
        bind_prefixes(prov_graph)
        activity = BNode()
        now = datetime.now(timezone.utc)
        prov_graph.add((activity, RDF.type, SV.VerificationActivity))
        prov_graph.add((activity, PROV.startedAtTime,
                        Literal(now.isoformat(), datatype=XSD.dateTime)))

    for check in checks_config:
        name = check["name"]
        class_uri = check["class_uri"]
        mode = check["mode"]

        entities = [cast(URIRef, e) for e in sorted(g.subjects(RDF.type, class_uri), key=str)]

        if mode == "custom":
            handler = check["handler"]
            ok_list, fail_list = handler(g, entities)
            results.append(CheckResult(name, len(ok_list), len(entities), fail_list))

        elif mode == "chain":
            chain_results, chain_resolved = _run_chain_checks(
                g, entities, name, registry, fetcher=fetcher,
                prov_graph=prov_graph, activity=activity, force=force,
                crawl=crawl)
            results.extend(chain_results)
            resolved_sources.extend(chain_resolved)

        elif mode == "direct":
            ok_list = []
            fail_list = []
            direct_resolved = []
            for entity in entities:
                result = resolve_direct(g, entity, registry, fetcher=fetcher)
                direct_resolved.append(result)
                if result.status != "resolved":
                    loc = str(g.value(entity, SV.sourceLocation) or "")
                    fail_list.append(
                        _failure(result, entity, f'"{loc}" -> {result.status}'))
                    continue

                outcome = load_text(result, max_chars=50000, force=force,
                                    crawl=crawl)
                clean = strip_headers(outcome.text) if outcome.text else ""
                if len(clean) >= 3:
                    ok_list.append(entity)
                else:
                    loc = str(g.value(entity, SV.sourceLocation) or "")
                    # Say what actually went wrong. A missing page, a failed
                    # fetch and a genuinely empty document used to arrive as
                    # one indistinguishable "empty extraction".
                    detail = (outcome.reason if outcome.status != "ok"
                              else f"empty extraction ({len(clean)} chars)")
                    fail_list.append(
                        _failure(result, entity, f'"{loc}" -> {detail}'))

            results.append(CheckResult(name, len(ok_list), len(entities), fail_list))
            resolved_sources.extend(direct_resolved)

    # A URL is one URL however many fragments cite it, and whichever mode
    # they were checked under, so this is checked once for the whole run.
    # With no HTTP-fetched sources there is nothing to say, so say nothing.
    redirects = _redirect_check("Source URLs", resolved_sources,
                                strict_redirects)
    if redirects.total:
        results.append(redirects)

    repos = _repo_check("Repo documents", resolved_sources, strict_repos)
    if repos.total:
        results.append(repos)

    if emit_provenance and prov_graph is not None and activity is not None:
        now = datetime.now(timezone.utc)
        prov_graph.add((activity, PROV.endedAtTime,
                        Literal(now.isoformat(), datatype=XSD.dateTime)))
        return results, prov_graph

    return results


def _run_chain_checks(
    g: Graph, fragments: list[URIRef], base_name: str,
    registry: RepoRegistry, fetcher: Any = None,
    prov_graph: Graph | None = None, activity: BNode | None = None,
    force: bool = False, crawl: bool = True,
) -> tuple[list[CheckResult], list[Any]]:
    """Run the three chain-mode checks: cache resolution, content extraction,
    and snippet verification.

    Also returns the resolved sources, so the caller can check their URLs
    once across every mode rather than once per mode.
    """
    checks = []

    # Resolve all fragments once
    resolved = {frag: resolve_chain(g, frag, registry, fetcher=fetcher)
                for frag in fragments}

    # CHECK: Cache resolution
    cache_ok = []
    cache_fail = []
    for frag in fragments:
        result = resolved[frag]
        if result.status == "resolved":
            cache_ok.append(frag)
        else:
            loc = str(g.value(frag, SV.sourceLocation) or "")
            cache_fail.append(
                _failure(result, frag, f'"{loc}" -> {result.status}'))

    checks.append(CheckResult(f"{base_name}: cache resolution",
                              len(cache_ok), len(fragments), cache_fail))

    # CHECK: Content extraction
    extract_ok = []
    extract_fail = []
    for frag in fragments:
        result = resolved[frag]
        if result.status != "resolved":
            loc = str(g.value(frag, SV.sourceLocation) or "")
            extract_fail.append(_failure(result, frag, f'"{loc}" -> no cache'))
            continue

        # Force a refresh (re-fetch, and re-crawl) during the extraction phase
        # only; the snippet phase below reads the now-fresh caches, so each
        # source is fetched at most once per run.
        outcome = load_text(result, max_chars=50000, force=force, crawl=crawl)
        clean = strip_headers(outcome.text)

        if len(clean) < MIN_EXTRACT_CHARS:
            loc = str(g.value(frag, SV.sourceLocation) or "")
            # A page the repo does not have, a fetch that failed, and a
            # document that really is empty are three different findings.
            # Reporting all three as "empty extraction" blamed the citation
            # for things the citation had nothing to do with.
            detail = (outcome.reason if outcome.status != "ok"
                      else f"empty extraction ({len(clean)} chars)")
            extract_fail.append(_failure(result, frag, f'"{loc}" -> {detail}'))
        else:
            extract_ok.append(frag)

    checks.append(CheckResult(f"{base_name}: content extraction",
                              len(extract_ok), len(fragments), extract_fail))

    # CHECK: Snippet verified (reads oa:exact from TextQuoteSelector)
    # Resolve each fragment's snippet once, then keep those long enough to verify.
    snippets = {f: (_get_snippet(g, f) or "") for f in fragments}
    snippet_frags = [f for f in fragments
                     if len(snippets[f].strip()) >= MIN_EXTRACT_CHARS]
    snippet_ok = []
    snippet_fail = []
    for frag in snippet_frags:
        norm_snippet = normalize_ws(snippets[frag])
        # A trailing ellipsis ("..." or "…") marks a deliberately elided quote:
        # the author kept only the opening of a longer passage, so matching the
        # retained prefix is correct. Stripping it leaves the text that must
        # appear verbatim. Without an ellipsis, the *entire* snippet must appear
        # in the source — otherwise drift in the tail would go undetected.
        norm_snippet = re.sub(r"(\.\.\.|…)$", "", norm_snippet).strip()

        result = resolved[frag]
        if result.status != "resolved":
            snippet_fail.append(
                _failure(result, frag, "cache not resolved for verification"))
            continue

        # The whole document, not a prefix of it. This read the first 100,000
        # characters, which is a fifth of RFC 9110 — so a real citation into
        # its status-code definitions was reported as "snippet not found in
        # extracted content", a flat claim about a source the check had never
        # looked at. Nothing was bought by the cap: the substring test is
        # linear, and diagnosing a miss across the whole of RFC 9110 takes a
        # tenth of a second.
        #
        # No force here: the extraction phase above already refreshed and
        # re-crawled, so this reads the warm cache.
        loaded = load_text(result, max_chars=None, crawl=crawl)
        if loaded.status != "ok":
            # The source never arrived. Running the snippet against the empty
            # string would report "snippet not found" — blaming the quote for
            # a page that was missing or a fetch that failed.
            snippet_fail.append(
                _failure(result, frag, loaded.reason or "source unavailable"))
            if prov_graph is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("failed")))
            continue

        norm_source = normalize_ws(loaded.text)

        if norm_snippet and norm_snippet in norm_source:
            snippet_ok.append(frag)
            # Record provenance for verified fragments
            if prov_graph is not None and activity is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("verified")))
                prov_graph.add((frag, PROV.wasGeneratedBy, activity))
        else:
            # Diagnose from the text already in hand — the extraction is
            # right here, and re-fetching to diff it would be absurd.
            where = result.locator if isinstance(result, FetcherResult) else ""
            snippet_fail.append(_failure(
                result, frag, "snippet not found in extracted content",
                diagnose(norm_snippet, norm_source, where=where or ""),
            ))
            if prov_graph is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("failed")))

    checks.append(CheckResult(f"{base_name}: snippet verified",
                              len(snippet_ok), len(snippet_frags), snippet_fail))

    return checks, list(resolved.values())


def _print_records(records: list[Failure]) -> None:
    """Print failures (or warnings) grouped by their source.

    The group header names the source and the URL it was checked at, because
    the URL is the thing you go and look at; the lines under it name the
    fragments. Both used to be the same slugified URN, printed twice.
    """
    if not records:
        return

    by_group: defaultdict[tuple[str, str], list[Failure]] = defaultdict(list)
    for f in records:
        by_group[(f.group, f.url)].append(f)

    for group, url in sorted(by_group, key=lambda t: -len(by_group[t])):
        items = by_group[(group, url)]
        # The URL-level checks itemize *by* URL, so printing it in the header
        # too would just say the same thing twice.
        redundant = all(f.item == url for f in items)
        where = f" ({url})" if url and not redundant else ""
        print(f"         {group}{where} ({len(items)})")
        for f in items:
            print(f"           {f.item}: {f.reason}")
            if f.hint is not None:
                for line in render(f.hint):
                    print(f"             {line}")


def verdict(check: CheckResult) -> str:
    """How a single check came out: PASS, FAIL, WARN, or nothing to say.

    The one place this is decided. Two renderers is two chances to disagree
    about whether a run was green, and the exit code hangs off the answer.
    """
    if check.total == 0:
        return "----"
    if check.failures:
        return "FAIL"
    if check.warnings:
        return "WARN"
    return "PASS"


def tally(checks: list[CheckResult]) -> dict[str, int]:
    """Count the verdicts. ``fail`` is what the exit code is built from."""
    counts = {"pass": 0, "fail": 0, "warn": 0}
    for check in checks:
        tag = verdict(check)
        if tag == "FAIL":
            counts["fail"] += 1
        elif tag == "WARN":
            counts["warn"] += 1
        elif tag == "PASS":
            counts["pass"] += 1
    return counts


def print_report(checks: list[CheckResult], summary: bool = False,
                 title: str = "apysource Verification Report") -> int:
    """Print the verification report. Returns failure count."""
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)

    counts = tally(checks)
    pass_count = counts["pass"]
    fail_count = counts["fail"]
    warn_count = counts["warn"]

    for check in checks:
        print(f"\n  [{verdict(check)}] {check.name:.<40s} {check.ok}/{check.total}")

        if not summary:
            _print_records(check.failures)
            _print_records(check.warnings)

    print(f"\n  {'=' * 70}")
    print(f"  Summary: {pass_count} PASS, {fail_count} FAIL, {warn_count} WARN")
    if fail_count > 0:
        print("  EXIT CODE: 1 (failures present)")
    else:
        print("  EXIT CODE: 0 (all checks passed)")
    print(f"  {'=' * 70}")

    return fail_count


def _record_json(f: Failure) -> dict[str, Any]:
    """One failure, as data.

    The diagnosis is served as its fields rather than as its rendered lines —
    it was kept structured precisely so a consumer would not have to parse the
    prose back apart.
    """
    record: dict[str, Any] = {
        "source": f.group,
        "label": f.item,
        "url": f.url,
        "urn": f.urn,
        "reason": f.reason,
    }
    if f.hint is not None:
        hint = asdict(f.hint)
        # percent is a property, so asdict drops it, and it is the number a
        # reader of the JSON would actually look at.
        hint["percent"] = f.hint.percent
        record["hint"] = hint
    return record


def json_report(checks: list[CheckResult]) -> dict[str, Any]:
    """The verification report, as data.

    Same verdicts as the printed one — they come from the same function — so a
    CI job and a human cannot be told different things about the same run.
    Failures name the source and the fragment by their labels, which is what a
    consumer routes on (the label is what someone wrote in the YAML; the URN is
    what the loader made of it), and carry the URL and the URN besides.
    """
    counts = tally(checks)
    return {
        "checks": [
            {
                "name": check.name,
                "status": verdict(check),
                "ok": check.ok,
                "total": check.total,
                "failures": [_record_json(f) for f in check.failures],
                "warnings": [_record_json(f) for f in check.warnings],
            }
            for check in checks
        ],
        "summary": {**counts, "failed": counts["fail"] > 0},
    }
