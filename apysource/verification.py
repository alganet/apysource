# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""apysource Verification — source-grounding checks.

All functions require a RepoRegistry instance — no global state.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, cast

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from apysource.diagnostics import diagnose, render
from apysource.formats import normalize_ws
from apysource.graph import local_name
from apysource.namespaces import PROV, SV
from apysource.repos import RepoRegistry
from apysource.resolution import _get_snippet, get_text, resolve_chain, resolve_direct
from apysource.results import CheckResult, Failure, FetcherResult

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
            ))
        elif info.redirected:
            hops = " -> ".join(f"{status} {hop}" for status, hop in info.chain)
            records.append(Failure(
                result.source or "source", result.url,
                f"moved: {hops} -> {info.final_url}. The snippet was verified "
                f"against the destination, not this URL; update it.",
            ))
        else:
            ok += 1

    total = ok + len(records)
    if strict:
        return CheckResult(name, ok, total, failures=records)
    return CheckResult(name, ok, total, warnings=records)


def run_checks(
    g: Graph, checks_config: list[dict[str, Any]], registry: RepoRegistry,
    fetcher: Any = None, emit_provenance: bool = False, force: bool = False,
    strict_redirects: bool = False,
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
                prov_graph=prov_graph, activity=activity, force=force)
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
                    fail_list.append(Failure(local_name(entity), local_name(entity),
                                            f'"{loc}" -> {result.status}'))
                    continue

                text = get_text(result, max_chars=50000, force=force)
                clean = strip_headers(text) if text else ""
                if len(clean) >= 3:
                    ok_list.append(entity)
                else:
                    loc = str(g.value(entity, SV.sourceLocation) or "")
                    fail_list.append(Failure(local_name(entity), local_name(entity),
                                            f'"{loc}" -> empty extraction ({len(clean)} chars)'))

            results.append(CheckResult(name, len(ok_list), len(entities), fail_list))
            resolved_sources.extend(direct_resolved)

    # A URL is one URL however many fragments cite it, and whichever mode
    # they were checked under, so this is checked once for the whole run.
    # With no HTTP-fetched sources there is nothing to say, so say nothing.
    redirects = _redirect_check("Source URLs", resolved_sources,
                                strict_redirects)
    if redirects.total:
        results.append(redirects)

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
    force: bool = False,
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
            cache_fail.append(Failure(local_name(frag), local_name(frag),
                                      f'"{loc}" -> {result.status}'))

    checks.append(CheckResult(f"{base_name}: cache resolution",
                              len(cache_ok), len(fragments), cache_fail))

    # CHECK: Content extraction
    extract_ok = []
    extract_fail = []
    for frag in fragments:
        result = resolved[frag]
        if result.status != "resolved":
            loc = str(g.value(frag, SV.sourceLocation) or "")
            extract_fail.append(Failure(local_name(frag), local_name(frag),
                                        f'"{loc}" -> no cache'))
            continue

        # Force a refresh (re-fetch) during the extraction phase only; the
        # snippet phase below reads the now-fresh HTTP cache, so each source
        # URL is fetched at most once per run.
        text = get_text(result, max_chars=50000, force=force)
        clean = strip_headers(text)

        if len(clean) < MIN_EXTRACT_CHARS:
            loc = str(g.value(frag, SV.sourceLocation) or "")
            extract_fail.append(Failure(local_name(frag), local_name(frag),
                                        f'"{loc}" -> empty extraction ({len(clean)} chars)'))
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
            snippet_fail.append(Failure(local_name(frag), local_name(frag),
                                        "cache not resolved for verification"))
            continue

        source_text = get_text(result, max_chars=100000)
        norm_source = normalize_ws(source_text)

        if norm_snippet and norm_snippet in norm_source:
            snippet_ok.append(frag)
            # Record provenance for verified fragments
            if prov_graph is not None and activity is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("verified")))
                prov_graph.add((frag, PROV.wasGeneratedBy, activity))
        else:
            # Diagnose from the text already in hand — the extraction is
            # right here, and re-fetching to diff it would be absurd.
            # Diagnose from the text already in hand — the extraction is
            # right here, and re-fetching to diff it would be absurd.
            where = result.locator if isinstance(result, FetcherResult) else ""
            snippet_fail.append(Failure(
                local_name(frag), local_name(frag),
                "snippet not found in extracted content",
                diagnose(norm_snippet, norm_source, where=where or ""),
            ))
            if prov_graph is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("failed")))

    checks.append(CheckResult(f"{base_name}: snippet verified",
                              len(snippet_ok), len(snippet_frags), snippet_fail))

    return checks, list(resolved.values())


def _print_records(records: list[Failure]) -> None:
    """Print failures (or warnings) grouped by their source."""
    if not records:
        return

    by_group = defaultdict(list)
    for f in records:
        by_group[f.group].append(f)

    for group in sorted(by_group, key=lambda t: -len(by_group[t])):
        items = by_group[group]
        print(f"         {group}/ ({len(items)})")
        for f in items:
            print(f"           {f.item}: {f.reason}")
            if f.hint is not None:
                for line in render(f.hint):
                    print(f"             {line}")


def print_report(checks: list[CheckResult], summary: bool = False,
                 title: str = "apysource Verification Report") -> int:
    """Print the verification report. Returns failure count."""
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)

    pass_count = 0
    fail_count = 0
    warn_count = 0

    for check in checks:
        failed = len(check.failures)

        if check.total == 0:
            tag = "----"
        elif failed:
            tag = "FAIL"
            fail_count += 1
        elif check.warnings:
            tag = "WARN"
            warn_count += 1
        else:
            tag = "PASS"
            pass_count += 1

        print(f"\n  [{tag}] {check.name:.<40s} {check.ok}/{check.total}")

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
