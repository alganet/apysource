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
from rdflib.namespace import RDF, RDFS, XSD

from apysource.graph import local_name
from apysource.namespaces import PROV, SV
from apysource.repos import RepoRegistry
from apysource.resolution import _get_snippet, get_text, resolve_chain, resolve_direct
from apysource.results import CheckResult, Failure


def strip_headers(text: str) -> str:
    """Strip comment headers and blank lines, return actual content only."""
    if not text:
        return ""
    lines = text.split("\n")
    content = [line for line in lines if not line.startswith("#") and line.strip()]
    return "\n".join(content).strip()


def run_checks(
    g: Graph, checks_config: list[dict[str, Any]], registry: RepoRegistry,
    fetcher: Any = None, emit_provenance: bool = False,
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
            chain_results = _run_chain_checks(g, entities, name, registry,
                                              fetcher=fetcher,
                                              prov_graph=prov_graph,
                                              activity=activity)
            results.extend(chain_results)

        elif mode == "direct":
            ok_list = []
            fail_list = []
            for entity in entities:
                result = resolve_direct(g, entity, registry, fetcher=fetcher)
                if result.status != "resolved":
                    loc = str(g.value(entity, SV.sourceLocation) or "")
                    fail_list.append(Failure(local_name(entity), local_name(entity),
                                            f'"{loc}" -> {result.status}'))
                    continue

                text = get_text(result, max_chars=50000)
                clean = strip_headers(text) if text else ""
                if len(clean) >= 3:
                    ok_list.append(entity)
                else:
                    loc = str(g.value(entity, SV.sourceLocation) or "")
                    fail_list.append(Failure(local_name(entity), local_name(entity),
                                            f'"{loc}" -> empty extraction ({len(clean)} chars)'))

            results.append(CheckResult(name, len(ok_list), len(entities), fail_list))

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
) -> list[CheckResult]:
    """Run the three chain-mode checks: cache resolution, content extraction,
    and snippet verification."""
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

        text = get_text(result, max_chars=50000)
        clean = strip_headers(text)

        if len(clean) < 20:
            loc = str(g.value(frag, SV.sourceLocation) or "")
            extract_fail.append(Failure(local_name(frag), local_name(frag),
                                        f'"{loc}" -> empty extraction ({len(clean)} chars)'))
        else:
            extract_ok.append(frag)

    checks.append(CheckResult(f"{base_name}: content extraction",
                              len(extract_ok), len(fragments), extract_fail))

    # CHECK: Snippet verified (reads oa:exact from TextQuoteSelector)
    snippet_frags = [f for f in fragments
                     if _get_snippet(g, f) is not None and
                     len((_get_snippet(g, f) or "").strip()) >= 20]
    snippet_ok = []
    snippet_fail = []
    for frag in snippet_frags:
        snippet_str = _get_snippet(g, frag) or ""
        norm_snippet = re.sub(r"\s+", " ", snippet_str).strip()
        if norm_snippet.endswith("..."):
            norm_snippet = norm_snippet[:-3]

        result = resolved[frag]
        if result.status != "resolved":
            snippet_fail.append(Failure(local_name(frag), local_name(frag),
                                        "cache not resolved for verification"))
            continue

        source_text = get_text(result, max_chars=100000)
        norm_source = re.sub(r"\s+", " ", source_text).strip()

        if norm_snippet[:80] in norm_source:
            snippet_ok.append(frag)
            # Record provenance for verified fragments
            if prov_graph is not None and activity is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("verified")))
                prov_graph.add((frag, PROV.wasGeneratedBy, activity))
        else:
            snippet_fail.append(Failure(local_name(frag), local_name(frag),
                                        "snippet not found in extracted content"))
            if prov_graph is not None:
                prov_graph.add((frag, SV.verificationStatus, Literal("failed")))

    checks.append(CheckResult(f"{base_name}: snippet verified",
                              len(snippet_ok), len(snippet_frags), snippet_fail))

    return checks


def print_report(checks: list[CheckResult], summary: bool = False,
                 title: str = "apysource Verification Report") -> int:
    """Print the verification report. Returns failure count."""
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)

    pass_count = 0
    fail_count = 0

    for check in checks:
        failed = len(check.failures)

        if check.total == 0:
            tag = "----"
        elif failed == 0:
            tag = "PASS"
            pass_count += 1
        else:
            tag = "FAIL"
            fail_count += 1

        print(f"\n  [{tag}] {check.name:.<40s} {check.ok}/{check.total}")

        if check.failures and not summary:
            by_group = defaultdict(list)
            for f in check.failures:
                by_group[f.group].append(f"{f.item}: {f.reason}")

            for group in sorted(by_group, key=lambda t: -len(by_group[t])):
                items = by_group[group]
                print(f"         {group}/ ({len(items)})")
                for item in items:
                    print(f"           {item}")

    print(f"\n  {'=' * 70}")
    print(f"  Summary: {pass_count} PASS, {fail_count} FAIL, 0 WARN")
    if fail_count > 0:
        print("  EXIT CODE: 1 (failures present)")
    else:
        print("  EXIT CODE: 0 (all checks passed)")
    print(f"  {'=' * 70}")

    return fail_count
