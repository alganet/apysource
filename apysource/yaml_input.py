# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Load source definitions from YAML files into an rdflib Graph.

Pure function — no config imports, no global state.

``graph_from_data`` takes the patterns it should mint url-less sources with as an
argument, defaulting to the file's own plus the shipped ones. It is a parameter
and not a lookup so that this stays a function of its inputs: a caller that has
already compiled the patterns (``sources.load_sources`` has) passes them in rather
than making this module compile them a second time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import yaml
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, RDF, RDFS

from apysource.namespaces import OA, SV, new_graph
from apysource.patterns import SourcePattern, complete, patterns_from_data
from apysource.schema import (  # noqa: F401 — the vocabulary lives here now
    _CITE_SITE_ALLOWED,
    _FRAGMENT_ALLOWED,
    _FRAGMENT_KEYS,
    _NORMALIZE_KEYS,
    _SOURCE_ALLOWED,
    _SOURCE_KEYS,
    _TOP_ALLOWED,
    FRAGMENT_KEYS,
    SOURCE_KEYS,
    TARGETTING_KEYS,
    reject_unknown_keys,
    text,
)


def _slugify(text: str) -> str:
    """Convert text to a URI-safe slug.

    Keeps any letter or digit, not only ASCII ones. It matched `[^a-z0-9]`, so
    a label written in Cyrillic, Greek or Chinese lost *every* character and
    slugged to the empty string — and three such labels minted one identical
    URN between them, merging three citations into one. `Übergabe` became
    `bergabe`; `§ 8` became `8`.
    """
    slug = text.lower().strip()
    slug = re.sub(r"\W+", "_", slug, flags=re.UNICODE)
    return slug.strip("_")


#: The identifier scheme a file gets when it does not name one of its own.
#:
#: It is deterministic, readable, and **not globally unique** — that last part
#: matters, because RDF graphs are built to merge. `urn:apysource:fragment_…` is
#: minted from a *file-local* label, so two projects that both cite RFC 9110 §7.2
#: mint the identical identifier. Merge their graphs and the two citations become
#: one, which is the failure `_Minter` guards against *within* a file reappearing
#: *across* files, where no minter can see it.
#:
#: (It is also not a valid URN: RFC 8141 §5 requires the namespace be registered
#: with IANA, and `apysource` is not.)
#:
#: A file that sets `base:` gets identifiers under a name it controls, and those
#: are safe to publish and to merge. See `graph_from_data`.
URN_PREFIX = "urn:apysource:"


def _make_uri(label: str, kind: str = "", base: str = "") -> URIRef:
    """Create a deterministic identifier from a label.

    With ``base``, an http(s) identifier under a name the author controls; without
    one, a ``urn:apysource:`` fallback that is file-scoped. See ``URN_PREFIX``.
    """
    prefix = f"{kind}_" if kind else ""
    slug = f"{prefix}{_slugify(label)}"
    if base:
        sep = "" if base.endswith(("#", "/", ":")) else "#"
        return URIRef(f"{base}{sep}{slug}")
    return URIRef(f"{URN_PREFIX}{slug}")


class _Minter:
    """Hands out URNs, and refuses to hand the same one out twice.

    Identity is a slug, and ``_slugify`` collapses *every* run of non-alphanumeric
    characters to a single ``_``. So ``rules/host_header`` and
    ``rules-host-header`` are the same URN — and RDF being a set of triples, the
    two fragments silently became *one*, carrying both snippets. ``_get_snippet``
    then read one of them with ``g.value()``, which picks arbitrarily.

    The result was the worst outcome this tool can produce: a fabricated quote,
    appearing nowhere in the source, **verified green** — because the arbitrary
    pick happened to land on the other fragment's honest snippet. One citation
    was checked twice and the other was not checked at all, and nothing said so.

    Two citations that cannot be told apart are not something to guess between.
    They are refused, by name, with the URN they collided on.
    """

    def __init__(self, base: str = "") -> None:
        self._minted: dict[URIRef, str] = {}
        self._base = base

    def mint(self, key: str, kind: str, what: str) -> URIRef:
        uri = _make_uri(key, kind, self._base)
        prior = self._minted.get(uri)
        if prior is not None:
            if prior == what:
                raise ValueError(
                    f"duplicate {kind}: {what} appears twice. "
                    f"Two entries with one identity are one entry; the second "
                    f"would silently vanish.",
                )
            raise ValueError(
                f"{kind} identity collision: {prior} and {what} both become "
                f"<{uri}>. They differ only in characters the identifier does "
                f"not keep (punctuation, spacing, case), so one citation would "
                f"silently overwrite the other. Give them labels that differ in "
                f"letters or digits.",
            )
        self._minted[uri] = what
        return uri


# The vocabulary and the two refusals now live in `schema`, which depends on
# nobody — see that module for why. Re-exported here because this is where a
# caller has always found them, and `SOURCE_KEYS` exists precisely so that a
# generator does not keep its own copy.
_reject_unknown_keys = reject_unknown_keys
_text = text


def _anon(owner: str | URIRef, role: str) -> BNode:
    """A blank node whose *label* is decided by what it belongs to.

    ``owner`` is whatever names the thing these nodes hang off. Usually a
    fragment's URI; in ``locate`` there is no URI to key on — the subjects it
    emits are themselves blank — so it keys on the URL it was asked about, which
    is equally the one stable name in play.

    ``BNode()`` mints a fresh uuid every time, and rdflib's Turtle serializer
    orders the objects of a predicate by blank-node identity. So a fragment
    carrying both a section selector and a quote selector emitted them in an
    order that changed from one process to the next, and serializing the same
    file twice produced two different documents — 1498 differing lines on a real
    295-citation project. Nothing showed it until something diffed the output:
    the labels themselves never appear, because the serializer nests blank nodes
    inline, so the file *looks* stable right up until you commit it.

    That matters to more than tidiness. ``apycite extract --frozen`` compares the
    committed citations file byte for byte, and a CI job that reports a diff on
    every commit teaches everyone to ignore it.

    The label is derived from the owning subject rather than from a counter.
    Both are stable, but a counter renumbers every node after an insertion, so
    adding one citation would rewrite the whole file — and a diff the size of the
    project says nothing about what changed.

    Not an identity: blank nodes stay blank, two graphs that differ only in these
    labels remain isomorphic, and nobody outside can name one.
    """
    return BNode(f"{_slugify(str(owner))}_{role}")


def _emit_oa_target(g: Graph, frag_uri: URIRef, source_uri: URIRef,
                    frag_def: dict[str, object], what: str,
                    origin: str = "<data>") -> None:
    """Emit OA Web Annotation triples for a fragment.

    This is the primary way fragments link to their source and carry
    snippet/selector/section data — via standard OA properties.

    Absence is ``None``, never falsiness: ``snippet: ""`` and ``section: 0`` were
    dropped by a truthiness test, and a dropped ``section:`` is the false-pass
    shape — the quote is then matched against the whole document instead of the
    section the citation named.

    A fragment that says none of the three is **refused**, where it used to be
    emitted target-less. ``location:``, ``lines:``, ``page_start:`` or a lone
    ``cited_by:`` all reach here, and each of them produced an ``sv:Fragment``
    with no ``oa:hasTarget`` — floating free of the source it claims to quote.
    Nothing downstream can do anything with one: ``_get_source`` walks
    ``oa:hasTarget``, finds nothing, and reports ``no_source``, which reads as a
    problem with the *source* when the citation simply never said what it was
    quoting. It is the ``snipet:``-typo failure wearing different clothes — the
    author believes a citation is being checked, and none is.
    """
    snippet = frag_def.get("snippet")
    selector_css = frag_def.get("selector")
    section = frag_def.get("section")

    if snippet is None and selector_css is None and section is None:
        raise ValueError(
            f"{what}: has no 'snippet', 'selector' or 'section', so it does not "
            f"point at anything in its source and verifies nothing. Give it the "
            f"quote you are citing. ('location', 'lines' and 'page_start' say "
            f"where to look; they do not say what to look for.) ({origin})",
        )

    # Annotation motivation
    g.add((frag_uri, OA.motivatedBy, OA.identifying))

    # oa:hasTarget → oa:SpecificResource → oa:hasSource
    target = _anon(frag_uri, "target")
    g.add((frag_uri, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source_uri))

    # TextQuoteSelector from snippet
    if snippet is not None:
        tqs = _anon(frag_uri, "quote")
        g.add((target, OA.hasSelector, tqs))
        g.add((tqs, RDF.type, OA.TextQuoteSelector))
        g.add((tqs, OA.exact, Literal(_text(snippet, f"{what}: snippet"))))

    # CssSelector from selector
    if selector_css is not None:
        css = _anon(frag_uri, "css")
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(_text(selector_css, f"{what}: selector"))))

    # SectionSelector from section
    if section is not None:
        fs = _anon(frag_uri, "section")
        g.add((target, OA.hasSelector, fs))
        g.add((fs, RDF.type, SV.SectionSelector))
        g.add((fs, RDF.value, Literal(_text(section, f"{what}: section"))))


def _emit_cite_sites(g: Graph, frag_uri: URIRef, frag_def: dict[str, object],
                     what: str) -> None:
    """Emit the *citing* side: the places that make this claim.

    ``prov:wasDerivedFrom`` points from the cite site to the fragment, and that
    direction is the true one — the line of code was derived from the normative
    sentence, not the other way round. ``sv:citedBy`` is the same edge walked
    backwards, so a report holding a fragment can find its sites without a
    reverse scan of the graph.

    A ``cited_by:`` written as a single mapping rather than a list of them is
    refused rather than wrapped. Guessing would be free here, and it is exactly
    the guess that turns one dropped entry into a citation nobody is told about.
    """
    sites = frag_def.get("cited_by")
    if sites is None:
        return

    if not isinstance(sites, list):
        raise ValueError(
            f"{what}: cited_by must be a list of places, not a "
            f"{type(sites).__name__}. Write it as a list even when there is "
            f"only one — a single mapping is one entry away from silently "
            f"becoming none.",
        )

    for i, site in enumerate(sites, 1):
        where = f"{what}: cited_by[{i}]"
        if not isinstance(site, dict):
            raise ValueError(
                f"{where} must be a mapping with a 'file', not a "
                f"{type(site).__name__}.",
            )
        _reject_unknown_keys(site, _CITE_SITE_ALLOWED, where)

        file = site.get("file")
        if not file:
            raise ValueError(
                f"{where}: a cite site must name the 'file' it is in. A site "
                f"with no place is not a place.",
            )

        # Numbered by position in the list, which `_dedupe`-style callers keep
        # sorted, so a site added in the middle does not relabel the ones after it.
        node = _anon(frag_uri, f"cite_{i}")
        g.add((node, RDF.type, SV.CiteSite))
        g.add((node, SV.citingFile, Literal(_text(file, f"{where}: file"))))
        g.add((node, PROV.wasDerivedFrom, frag_uri))
        g.add((frag_uri, SV.citedBy, node))

        line = site.get("line")
        if line is not None:
            # bool is an int in Python, and `line: true` is not line 1.
            if not isinstance(line, int) or isinstance(line, bool):
                raise ValueError(
                    f"{where}: line must be a whole number, not a "
                    f"{type(line).__name__}.",
                )
            g.add((node, SV.citingLine, Literal(line)))


def load_yaml(path: Path) -> Graph:
    """Load a YAML sources file and return an rdflib Graph.

    The YAML file should contain a top-level ``sources`` list.
    Each source may have a nested ``fragments`` list.
    """
    body = Path(path).read_text(encoding="utf-8")
    return graph_from_data(yaml.safe_load(body), origin=str(path))


def graph_from_data(data: object, origin: str = "<data>",
                    patterns: Sequence[SourcePattern] | None = None) -> Graph:
    """Mint a graph from already-parsed sources data.

    The same loader ``load_yaml`` runs, minus the reading — so a caller that
    already holds the data (a generator emitting citations, a test) gets the
    identical validation without writing a file first. ``origin`` names the
    data in error messages; it is the path when there is one.

    ``patterns`` defaults to the file's own plus the shipped ones. Pass them when
    you have already compiled them, so they are not compiled twice.

    There is one definition of what a sources file means, and this is it.
    """
    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError(f"YAML file must contain a top-level 'sources' list: {origin}")

    reject_unknown_keys(data, _TOP_ALLOWED, origin)
    if patterns is None:
        patterns = patterns_from_data(data, origin)

    # `base:` names the identifiers this file mints. Without it they fall back to
    # `urn:apysource:`, which is derived from labels and therefore collides with
    # every other project that cites the same thing — fine while the graph stays
    # on this machine, wrong the moment it is emitted. See `URN_PREFIX`.
    base = data.get("base")
    if base is not None:
        base = _text(base, f"{origin}: base").strip()
        if not base.startswith(("http://", "https://", "urn:")):
            raise ValueError(
                f"{origin}: base must be an absolute IRI you control, such as "
                f"'https://example.org/citations'. Got {base!r}. A relative base "
                f"mints relative identifiers, which mean something different in "
                f"every file that reads them.",
            )
        if "#" in base.rstrip("#"):
            # `https://ex.org/c#v1` would mint `https://ex.org/c#v1#fragment_…`,
            # and a second `#` is not a legal IRI (RFC 3987 excludes it from
            # `ipchar`). rdflib serializes it without complaint, so it escapes
            # here and fails in whatever stricter tool reads the file later.
            raise ValueError(
                f"{origin}: base must not already contain a fragment. Got "
                f"{base!r}, which would mint identifiers with two '#' in them — "
                f"not a valid IRI. Give the part before the '#', or end the base "
                f"with '/' or '#'.",
            )
    base = base or ""

    g = new_graph()
    minter = _Minter(base)
    sources_by_label: dict[str, URIRef] = {}

    # Pre-pass: register every source URI up front so that `part_of` can
    # reference a source defined *later* in the file (forward references).
    for source_def in data["sources"]:
        label = source_def.get("label")
        if not label:
            raise ValueError("Each source must have a 'label'")
        sources_by_label[label] = minter.mint(label, "source", f"source {label!r}")

    for source_def in data["sources"]:
        label = source_def["label"]
        what_source = f"source {label!r}"
        _reject_unknown_keys(source_def, _SOURCE_ALLOWED, what_source)

        # A name is enough, when a pattern knows the family it belongs to. This is
        # a local rebind, never a mutation: `data` is the caller's, and a generator
        # walks it again after this loader has accepted it.
        completed = complete(source_def, patterns)
        if completed is None:
            tried = ", ".join(repr(p.pattern.pattern) for p in patterns)
            raise ValueError(
                f"{what_source}: must have a 'url', and no pattern mints one from "
                f"its label. Give it a 'url', or a top-level 'patterns' entry whose "
                f"'match' claims {label!r}. Tried: {tried}. ({origin})",
            )
        source_def = completed

        source_uri = sources_by_label[label]

        g.add((source_uri, RDF.type, SV.Source))
        g.add((source_uri, RDFS.label, Literal(label)))

        for key, predicate in _SOURCE_KEYS.items():
            value = source_def.get(key)
            if value is not None:
                value_str = _text(value, f"{what_source}: {key}")
                normalizer = _NORMALIZE_KEYS.get(key)
                if normalizer:
                    value_str = normalizer(value_str)
                g.add((source_uri, predicate, Literal(value_str)))

        # Handle part_of reference
        part_of = source_def.get("part_of")
        if part_of is not None:
            parent = _text(part_of, f"{what_source}: part_of")
            parent_uri = sources_by_label.get(parent)
            if parent_uri is None:
                # It was discarded in silence, so a typo'd parent simply
                # unhooked the source from its book and nobody heard.
                raise ValueError(
                    f"{what_source}: part_of names {parent!r}, which is not a "
                    f"source in this file.",
                )
            g.add((source_uri, DCTERMS.isPartOf, parent_uri))

        for frag_def in source_def.get("fragments", []):
            frag_label = frag_def.get("label")
            if not frag_label:
                raise ValueError(f"Each fragment in source '{label}' must have a 'label'")

            what_frag = f"fragment {frag_label!r} of source {label!r}"
            _reject_unknown_keys(frag_def, _FRAGMENT_ALLOWED, what_frag)

            frag_uri = minter.mint(f"{label} {frag_label}", "fragment", what_frag)
            g.add((frag_uri, RDF.type, SV.Fragment))
            g.add((frag_uri, RDFS.label, Literal(frag_label)))

            for key, predicate in _FRAGMENT_KEYS.items():
                value = frag_def.get(key)
                if value is not None:
                    g.add((frag_uri, predicate,
                           Literal(_text(value, f"{what_frag}: {key}"))))

            # OA Web Annotation triples (source link + selectors)
            # `origin` reaches this one refusal because a generator's user has
            # two citation files in play — the one they wrote and the one the
            # generator produced — and "fragment 'by hand' of source 'RFC 9110'"
            # says nothing about which of them to open.
            _emit_oa_target(g, frag_uri, source_uri, frag_def, what_frag, origin)

            # PROV triples for the citing side (file and line)
            _emit_cite_sites(g, frag_uri, frag_def, what_frag)

    return g
