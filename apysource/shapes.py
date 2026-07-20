# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The shipped SHACL shapes, and the one way to run them.

A YAML sources file is refused by a loader — unknown keys, non-scalar values,
colliding identities, a `part_of` naming nobody. A Turtle file is refused by
nothing at all: `graph.load_triples` parses and hands back whatever it read. The
shapes are what a Turtle author gets instead of that loader, which only works if
they are *present* and if they actually *run*.

Neither was true. `vocab/` sat outside the package, so an installed apysource
carried no shapes; `validate` looked for them only under the project's own RDF
root, where they were never going to be. Every run took the one branch that
existed — `SHACL — SKIPPED (no shapes found)` — and the shapes drifted for as long
as nothing was checking them, until two of apysource's own emitters no longer
satisfied them.

``conforms`` exists so that "passed" and "did not run" cannot be confused by a
second caller. It returns ``None`` for the latter, and a caller that treats it as
falsey reports a skip rather than a pass. Saying "all checks passed" when one of
them did not run is the same lie in a smaller costume.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from rdflib import Graph


@lru_cache(maxsize=1)
def _shapes_source() -> str:
    """The text of the shipped shapes file, read once."""
    return resources.files("apysource").joinpath(
        "vocab/shapes.ttl").read_text(encoding="utf-8")


def shipped_shapes() -> Graph:
    """The SHACL shapes that travel with apysource.

    A **fresh graph each call**, parsed from cached text. Caching the `Graph`
    itself is the obvious thing and it is wrong twice over: callers merge into it
    (`shapes += shipped_shapes()` in `validate`), and pyshacl *writes* to any
    shapes graph it is handed — it injects two `rdfs:subClassOf` axioms, so the
    cached graph grew from 191 triples to 193 on first use. Neither changes an
    outcome today, but a process-global graph that two callers mutate is a race
    waiting for the first threaded caller, and rdflib's default store is not
    thread-safe. Parsing costs a millisecond; keeping the text is the part worth
    caching.
    """
    g = Graph()
    g.parse(data=_shapes_source(), format="turtle")
    return g


def conforms(data: Graph, shapes: Graph | None = None) -> tuple[bool | None, str]:
    """Validate ``data`` against ``shapes``; ``(None, reason)`` if it could not run.

    Three outcomes, never two: conformed, did not conform, was not able to look.
    The third is why this returns ``bool | None`` rather than a plain bool —
    pyshacl is an optional dependency (``pip install apysource[shacl]``), and a
    missing one must read as a skip everywhere it is reported.

    Inference is off, and that is deliberate rather than incidental. ``vocab.ttl``
    carries ``rdfs:domain`` on most of its properties, which under RDFS entailment
    *assigns* types rather than restricting them: a stray ``sv:citingLine`` would
    infer ``sv:CiteSite`` and then fail ``CiteSiteShape`` for a missing
    ``sv:citingFile`` it never claimed to have. The domains are documentation of
    intent; the shapes are the constraints.
    """
    if shapes is None:
        shapes = shipped_shapes()

    try:
        from pyshacl import validate
    except ImportError:
        return None, "pyshacl is not installed — pip install apysource[shacl]"

    try:
        ok, _, report = validate(data, shacl_graph=shapes, inference="none")
    except Exception as e:
        # A shapes graph pyshacl cannot make sense of raises rather than
        # reporting, and the shapes most likely to be malformed are a project's
        # own `*-shapes.ttl` — which `validate` merges in and exists to give a
        # clean answer about. A traceback there blames the tool for the file.
        #
        # It is the third outcome, not a failure of the data: we could not look.
        return None, f"SHACL could not run: {type(e).__name__}: {e}"

    return bool(ok), report if not ok else ""
