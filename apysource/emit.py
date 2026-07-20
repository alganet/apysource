# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Turning a citations graph into a file, for whoever is writing one.

`apysource emit` is one caller. A generator that produces citations from
somewhere else — a source tree, a bibliography — is another, and it should not
have to restate what apysource RDF looks like in order to write some. Two
statements of that is one too many, and the second one drifts.

So the CLI keeps the arguments, the paths and the exits, and everything about the
*RDF* lives here.
"""

from __future__ import annotations

from rdflib import Graph, URIRef

from apysource.yaml_input import URN_PREFIX

#: rdflib's serializer names, by the name a person would type.
#:
#: Only ``turtle`` is byte-stable. The others label their blank nodes, and those
#: labels are minted per process — so a file emitted twice from identical input
#: differs, and anything that diffs the output (a `--frozen` check, a review)
#: reports a change that did not happen. Turtle is the one you commit; see
#: ``STABLE_FORMATS``.
FORMATS = {
    "turtle": "turtle",
    "ttl": "turtle",
    "nt": "nt",
    "n-triples": "nt",
    "ntriples": "nt",
    "json-ld": "json-ld",
    "jsonld": "json-ld",
    "xml": "xml",
    "rdf-xml": "xml",
}

#: The serializations whose output is the same every time, for the same graph.
#:
#: rdflib's Turtle writer nests blank nodes inline, so their labels never reach
#: the file; combined with the deterministic labels `yaml_input` mints, the bytes
#: are reproducible. Every other serializer here has to *name* its blank nodes,
#: and rdflib names them per run.
STABLE_FORMATS = frozenset({"turtle"})


class UnknownFormat(ValueError):
    """A serialization nobody here knows.

    Carries ``name`` and ``known`` so a caller can phrase the refusal in its own
    terms — a CLI reached through ``--format`` should say so, and only it knows
    that.
    """

    def __init__(self, name: object) -> None:
        self.name = name
        self.known = ", ".join(sorted(set(FORMATS)))
        super().__init__(f"unknown format {name!r} (known: {self.known})")


def serialize(graph: Graph, fmt: str = "turtle") -> str:
    """The graph as text, in one of ``FORMATS``.

    Defaults to Turtle because it is the only one that can be committed and
    diffed — see ``STABLE_FORMATS``.
    """
    resolved = FORMATS.get(str(fmt).lower())
    if resolved is None:
        raise UnknownFormat(fmt)
    return str(graph.serialize(format=resolved))


def is_stable(fmt: str) -> bool:
    """Whether emitting this format twice gives the same bytes twice."""
    return FORMATS.get(str(fmt).lower(), "") in STABLE_FORMATS


def default_identifiers(graph: Graph) -> set[URIRef]:
    """The subjects still carrying apysource's fallback identifiers.

    ``urn:apysource:fragment_rfc_9110_7_2`` is minted from a label, so every
    project citing RFC 9110 § 7.2 mints exactly that. Inside one file it is safe
    and the loader guarantees it: two citations that collide are refused by name.
    Across files nothing guarantees anything — and RDF graphs are *built* to
    merge, so two projects' citations quietly become one, which is the same
    fabricated-green failure the loader exists to prevent, one scope up.

    Anything writing a graph out should say so, which is why this is here rather
    than inside one command: the warning belongs at the moment the identifiers
    become someone else's problem, and there is more than one such moment.
    """
    return {s for s in graph.subjects()
            if isinstance(s, URIRef) and str(s).startswith(URN_PREFIX)}


def identifier_warning(graph: Graph, where: str = "") -> str:
    """The warning to print for a graph with fallback identifiers, or ``""``.

    Returned rather than printed so a library caller can route it — a CLI to
    stderr, a generator into its own diagnostics — and so both say the same thing.
    """
    urns = default_identifiers(graph)
    if not urns:
        return ""

    at = f" to {where}" if where else ""
    return (
        f"Warning: emitting{at} with {len(urns)} default "
        f"'{URN_PREFIX}' identifiers.\n"
        f"  They are derived from labels, so another project citing the same "
        f"thing mints the same identifier, and merging the two graphs would "
        f"silently conflate the citations.\n"
        f"  Set a top-level 'base:' in the sources file — an IRI you control, "
        f"such as 'https://example.org/citations' — to mint identifiers that "
        f"can be published and merged."
    )
