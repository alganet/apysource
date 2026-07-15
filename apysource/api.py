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
from apysource.results import CheckResult
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
) -> list[CheckResult] | tuple[list[CheckResult], Graph]:
    """Run the standard checks against a sources graph.

    ``registry`` and ``fetcher`` default to the wiring the CLI uses, so the
    common case is one argument. Pass them to check against something else — a
    stub in a test, a registry with a repo of your own.

    Returns the results. With ``emit_provenance``, returns
    ``(results, prov_graph)``, as ``run_checks`` does.
    """
    return run_checks(
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
