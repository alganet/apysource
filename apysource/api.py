# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The library entry point: check a graph, get results back.

``apysource check`` is one caller of this. A generator that mints citations
from somewhere else — a source tree, a bibliography, a notebook — is another,
and it should not have to reach into ``_defaults`` or shell out to the CLI to
run the same checks the CLI runs.

Everything here returns data. Nothing here prints, and nothing here exits: the
decision about what a failure *means* belongs to the caller. ``print_report``,
``json_report`` and ``failed`` (in ``apysource.verification``) turn the results
into a report and a verdict, and they are the same ones the CLI uses.
"""

from typing import Any

from rdflib import Graph

from apysource.namespaces import SV
from apysource.results import CheckResult, Failure
from apysource.verification import run_checks

#: What apysource checks, and it is checked the same way whoever asks.
#:
#: This used to be written out inside the check command, where it could only be
#: reached by running the CLI — so a second caller had to restate it, and two
#: statements of what "the standard checks" are is one statement too many.
STANDARD_CHECKS: list[dict[str, Any]] = [
    {"name": "Fragments", "class_uri": SV.Fragment, "mode": "chain"},
    {"name": "Terms", "class_uri": SV.Term, "mode": "direct"},
]

#: "Not given" and "given as nothing" are different questions, and ``None``
#: cannot answer both. A caller that omits ``fetcher`` wants the default one; a
#: caller that passes ``fetcher=None`` — the wiring does, in tests — is saying
#: there is to be no fetcher, and substituting one behind its back would build
#: a real HTTP client where the caller asked for none.
_UNSET: Any = object()


def default_registry() -> Any:
    """The repo registry the CLI uses when no ``-c`` config is given."""
    from apysource._defaults import compiled
    return compiled.registry()


def default_fetcher() -> Any:
    """The HTTP client the CLI uses when no ``-c`` config is given."""
    from apysource._defaults import compiled
    return compiled.http_client()


def check_graph(
    g: Graph,
    *,
    registry: Any = _UNSET,
    fetcher: Any = _UNSET,
    force: bool = False,
    strict_redirects: bool = False,
    strict_repos: bool = False,
    crawl: bool = True,
    emit_provenance: bool = False,
    validate_shapes: bool = False,
) -> list[CheckResult] | tuple[list[CheckResult], Graph]:
    """Run the standard checks against a sources graph.

    ``registry`` and ``fetcher`` default to the wiring the CLI uses, so the
    common case is one argument. Pass them to check against something else — a
    stub in a test, a registry with a repo of your own.

    ``validate_shapes`` adds a SHACL check of the graph itself. Pass it for a
    graph that arrived as Turtle, and not for one the YAML loader built: the
    loader is the stricter gate of the two — it refuses unknown keys, non-scalar
    values, colliding identities and untargeted fragments, none of which SHACL
    expresses — so over its output the shapes are redundant by construction.
    Turtle has no loader at all, and this is what it gets instead.

    Returns the results. With ``emit_provenance``, returns
    ``(results, prov_graph)``, as ``run_checks`` does.
    """
    outcome = run_checks(
        g,
        STANDARD_CHECKS,
        default_registry() if registry is _UNSET else registry,
        fetcher=default_fetcher() if fetcher is _UNSET else fetcher,
        emit_provenance=emit_provenance,
        force=force,
        strict_redirects=strict_redirects,
        strict_repos=strict_repos,
        crawl=crawl,
    )

    if not validate_shapes:
        return outcome

    results, prov = outcome if isinstance(outcome, tuple) else (outcome, None)
    results = [*results, _shape_check(g)]
    return (results, prov) if prov is not None else results


def _shape_check(g: Graph) -> CheckResult:
    """Does this graph say what a citations graph must say?

    Three outcomes, and the third is the one worth spelling out. pyshacl is an
    optional dependency, and a check that could not run must say so rather than
    vanish from the report — an absent check reads as a passed one, which is the
    same lie ``nothing_verified`` was written about. It reports WARN: a missing
    optional dependency is not a broken citation, but it is not nothing either.
    """
    from apysource.shapes import conforms

    ok, report = conforms(g)

    if ok is None:
        return CheckResult(
            "Citations shape", 0, 1, structural=True,
            warnings=[Failure("shapes", "SHACL", f"did not run: {report}")],
        )
    if ok:
        return CheckResult("Citations shape", 1, 1, structural=True)

    # One finding per violation would be nicer; the report is prose, and
    # inventing structure by parsing it back apart is how the two drift.
    return CheckResult(
        "Citations shape", 0, 1, structural=True,
        failures=[Failure("shapes", "SHACL", report.strip())],
    )
