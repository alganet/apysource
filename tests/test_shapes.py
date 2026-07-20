# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the shipped SHACL shapes and the one wrapper that runs them.

The shapes are what a Turtle author gets instead of the loader a YAML author
gets, so these tests are in two halves: the shapes must *accept* everything the
loader accepts (or the two front-ends have drifted apart), and they must *reject*
the things nothing else catches.
"""

from pathlib import Path

import pytest
from rdflib import Graph
from rdflib.compare import isomorphic

from apysource.shapes import conforms, shipped_shapes
from apysource.yaml_input import graph_from_data, load_yaml

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

PREFIXES = """
@prefix sv:      <https://alganet.github.io/apysource/vocab.ttl#> .
@prefix rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix oa:      <http://www.w3.org/ns/oa#> .
@prefix schema:  <https://schema.org/> .
@prefix ex:      <http://example.org/#> .
"""


def check(body: str):
    """Conformance of a Turtle body, with the standard prefixes prepended."""
    return conforms(Graph().parse(data=PREFIXES + body, format="turtle"))[0]


# ── The shapes are actually there ────────────────────────────────────────

def test_shipped_shapes_is_not_empty():
    """The shapes travel with the package.

    They used to live in a top-level `vocab/` that `packages.find` did not
    match, so an installed apysource carried none — and every SHACL run said
    "SKIPPED (no shapes found)" rather than failing, which is how it went
    unnoticed. A packaging regression looks exactly like this: an empty graph,
    conforming vacuously, forever.
    """
    assert len(shipped_shapes()) > 0


def test_conforms_distinguishes_failure_from_not_running():
    """`False` and `None` are different answers and must stay different."""
    ok, report = conforms(Graph().parse(
        data=PREFIXES + 'ex:s a sv:Source ; rdfs:label "S" .', format="turtle"))
    assert ok is False, "a Source with no schema:url does not conform"
    assert report, "a failure explains itself"


# ── What a YAML author writes, an RDF author may also write ──────────────

@pytest.mark.parametrize("body", [
    # Plain labels.
    'ex:s a sv:Source ; rdfs:label "S" ; schema:url "https://x/" .',
    # Language-tagged labels. `sh:datatype xsd:string` excluded rdf:langString,
    # so the most idiomatic thing an RDF author writes was refused — by shapes
    # that had never once run, which is why nobody found out.
    'ex:s a sv:Source ; rdfs:label "S"@en ; schema:url "https://x/" .',
    'ex:s a sv:Source ; rdfs:label "S"@en, "S"@fr ; schema:url "https://x/" .',
    # A URL may be an IRI rather than a string; an RDF author will reach for it.
    'ex:s a sv:Source ; rdfs:label "S" ; schema:url <https://x/> .',
    # A source that is part of another.
    'ex:b a sv:Source ; rdfs:label "B" ; schema:url "https://x/" .\n'
    'ex:s a sv:Source ; rdfs:label "S" ; schema:url "https://x/1" ; '
    '  dcterms:isPartOf ex:b .',
])
def test_idiomatic_rdf_conforms(body):
    assert check(body) is True


def test_language_tagged_fragment_conforms():
    """The whole chain in @en, not just the source."""
    assert check('''
        ex:s a sv:Source ; rdfs:label "Aesop"@en ; schema:url "https://x/" .
        ex:f a sv:Fragment ; rdfs:label "Fox"@en ;
            oa:hasTarget [ a oa:SpecificResource ; oa:hasSource ex:s ;
                oa:hasSelector [ a oa:TextQuoteSelector ; oa:exact "quote"@en ] ] .
    ''') is True


# ── What nothing else catches ────────────────────────────────────────────

_SOURCE = 'ex:s a sv:Source ; rdfs:label "S" ; schema:url "https://x/" .\n'


@pytest.mark.parametrize("name,body", [
    # Everything read with `g.value()` picks arbitrarily among several. If the
    # arbitrary pick lands on the honest quote, a fabricated citation verifies
    # green — the worst outcome this tool can produce.
    ("two oa:exact on one selector", _SOURCE + '''
        ex:f a sv:Fragment ; rdfs:label "F" ; oa:hasTarget [ a oa:SpecificResource ;
            oa:hasSource ex:s ;
            oa:hasSelector [ a oa:TextQuoteSelector ; oa:exact "q1", "q2" ] ] .'''),
    ("two TextQuoteSelectors on one target", _SOURCE + '''
        ex:f a sv:Fragment ; rdfs:label "F" ; oa:hasTarget [ a oa:SpecificResource ;
            oa:hasSource ex:s ;
            oa:hasSelector [ a oa:TextQuoteSelector ; oa:exact "q1" ] ,
                           [ a oa:TextQuoteSelector ; oa:exact "q2" ] ] .'''),
    ("two sources on one target", _SOURCE + '''
        ex:s2 a sv:Source ; rdfs:label "S2" ; schema:url "https://y/" .
        ex:f a sv:Fragment ; rdfs:label "F" ; oa:hasTarget [ a oa:SpecificResource ;
            oa:hasSource ex:s, ex:s2 ;
            oa:hasSelector [ a oa:TextQuoteSelector ; oa:exact "q" ] ] .'''),
    # The RDF echo of the loader's `part_of names X, which is not a source`.
    ("isPartOf a non-Source",
     'ex:s a sv:Source ; rdfs:label "S" ; schema:url "https://x/" ; '
     '  dcterms:isPartOf ex:nobody .'),
    ("malformed sourceLines", _SOURCE + '''
        ex:f a sv:Fragment ; rdfs:label "F" ; sv:sourceLines "ten to twenty" ;
            oa:hasTarget [ a oa:SpecificResource ; oa:hasSource ex:s ;
                oa:hasSelector [ a oa:TextQuoteSelector ; oa:exact "q" ] ] .'''),
    ("a fragment with no target",
     _SOURCE + 'ex:f a sv:Fragment ; rdfs:label "F" .'),
    ("a source with no url", 'ex:s a sv:Source ; rdfs:label "S" .'),
    ("a source with no label", 'ex:s a sv:Source ; schema:url "https://x/" .'),
    # resolve_direct reads schema:url with g.value() too.
    ("a Term with two urls",
     'ex:t a sv:Term ; rdfs:label "T" ; schema:url "https://x/", "https://y/" .'),
    ("a status nobody defined", 'ex:r sv:verificationStatus "probably-fine" .'),
])
def test_broken_rdf_is_refused(name, body):
    assert check(body) is False, name


def test_a_stray_property_does_not_acquire_a_type():
    """`rdfs:domain` in vocab.ttl assigns types; it does not restrict them.

    Under RDFS entailment a stray `sv:citingLine` would *infer* `sv:CiteSite`,
    and CiteSiteShape would then fail it for a missing `sv:citingFile` it never
    claimed to have.
    """
    assert check("ex:thing sv:citingLine 3 .") is True


def test_inference_is_off_even_when_the_ontology_is_in_the_graph():
    """The previous test passes for the wrong reason, so this one exists.

    `rdfs:domain` lives in `vocab.ttl`, which `conforms` never loads — only
    `shapes.ttl`, which declares none. So nothing could be entailed regardless of
    the setting, and a test on the shipped shapes alone would pass with inference
    switched on. Putting the domains into the *data* graph makes the entailment
    reachable, and pins that we do not perform it.
    """
    vocab = Path(__file__).resolve().parent.parent / "apysource" / "vocab" / "vocab.ttl"
    data = Graph().parse(vocab, format="turtle")
    data.parse(data=PREFIXES + "ex:thing sv:citingLine 3 .", format="turtle")

    ok, report = conforms(data)
    assert ok is True, (
        "sv:citingLine rdfs:domain sv:CiteSite was applied as a constraint "
        f"rather than left as documentation:\n{report}"
    )


# ── The two front-ends agree ─────────────────────────────────────────────

_SRC = {"label": "S", "url": "https://x/"}

#: Every shape of fragment the loader accepts. Between them these must exercise
#: every key in ``schema.FRAGMENT_KEYS`` — asserted below, so the claim in
#: ``test_every_fragment_the_loader_accepts_conforms`` is enforced rather than
#: merely believed.
_FRAGMENT_CASES = [
    {"label": "F", "snippet": "q"},
    {"label": "F", "section": "Chapter I"},
    {"label": "F", "selector": "div.main p"},
    {"label": "F", "snippet": "q", "location": "chapter:1"},
    {"label": "F", "snippet": "q", "lines": "10-20"},
    {"label": "F", "snippet": "q", "page_start": "1", "page_end": "2"},
    {"label": "F", "snippet": "q", "section": "Ch I", "selector": "p"},
    {"label": "F", "snippet": "q", "cited_by": [{"file": "a.rs", "line": 3}]},
    {"label": "F", "snippet": "q", "cited_by": [{"file": "a.rs"}]},
]


def test_the_fragment_cases_cover_every_key_a_fragment_may_have():
    """A hand-written list goes stale the moment a key is added.

    The parametrized test below claims that a key added to `schema.py` without a
    matching shape fails there. That is only true while these cases exercise
    every key, so it is checked rather than asserted in a docstring.
    """
    from apysource.schema import FRAGMENT_KEYS

    covered = {k for case in _FRAGMENT_CASES for k in case}
    assert covered == set(FRAGMENT_KEYS), (
        f"not exercised: {set(FRAGMENT_KEYS) - covered}; "
        f"unknown to the schema: {covered - set(FRAGMENT_KEYS)}"
    )


@pytest.mark.parametrize("fragment", _FRAGMENT_CASES)
def test_every_fragment_the_loader_accepts_conforms(fragment):
    """The load-bearing one: loader and shapes must agree about what is valid.

    This is what "RDF for people who don't know they're using it" actually
    rests on — and it is checked here rather than at runtime, because after the
    loader refuses an untargeted fragment the two agree *by construction*, and
    a construction is exactly the kind of claim a test should hold.

    A key added to `schema.py` without a matching shape fails here.
    """
    g = graph_from_data({"sources": [{**_SRC, "fragments": [fragment]}]})
    assert conforms(g)[0] is True


def test_every_source_key_conforms():
    g = graph_from_data({"sources": [{
        "label": "S", "url": "https://x/", "type": "html", "language": "en",
        "title": "T", "date": "2020", "license": "ISC", "isbn": "1", "doi": "d",
        "publisher": "P", "edition": "2",
        "fragments": [{"label": "F", "snippet": "q"}],
    }]})
    assert conforms(g)[0] is True


def test_part_of_chain_conforms():
    g = graph_from_data({"sources": [
        {"label": "Book", "url": "https://x/"},
        {"label": "Ch1", "url": "https://x/1", "part_of": "Book",
         "fragments": [{"label": "F", "snippet": "q"}]},
    ]})
    assert conforms(g)[0] is True


def test_a_source_may_inherit_its_url_from_its_parent():
    """A chapter that names its book and stops there.

    `_resolve_source_url` walks `dcterms:isPartOf` when a source has no
    `schema:url` of its own — that walk exists precisely for this. The shape
    used to demand a url outright, so the case the resolver was written for
    could not be expressed in Turtle, and the walk was unreachable.
    """
    assert check('''
        ex:book a sv:Source ; rdfs:label "Book" ; schema:url "https://x/" .
        ex:ch a sv:Source ; rdfs:label "Ch" ; dcterms:isPartOf ex:book .
    ''') is True


def test_a_source_with_neither_url_nor_parent_is_refused():
    """Nothing to inherit from is still nothing to fetch."""
    assert check('ex:s a sv:Source ; rdfs:label "S" .') is False


def test_pattern_minted_source_conforms():
    """A source named rather than addressed still produces a valid graph."""
    g = graph_from_data({"sources": [
        {"label": "RFC 9110", "fragments": [{"label": "7.2", "snippet": "q"}]},
    ]})
    assert conforms(g)[0] is True


@pytest.mark.parametrize("name", ["aesop", "simple"])
def test_shipped_examples_conform(name):
    """The examples are what a reader copies; they had better be valid."""
    assert conforms(load_yaml(EXAMPLES / name / "sources.yaml"))[0] is True


def test_shipped_turtle_example_conforms():
    g = Graph().parse(EXAMPLES / "aesop" / "rdf" / "sources.ttl", format="turtle")
    assert conforms(g)[0] is True


# ── Emitting and reading back ────────────────────────────────────────────

def test_yaml_graph_survives_a_turtle_round_trip():
    """Emit RDF from a YAML file, read it back, and get the same graph.

    The guarantee behind `apysource emit`: a YAML author's citations *are* a
    graph, and saying so in Turtle must not change what they say. Compared with
    `isomorphic` because serializing renames every blank node, and the OA target
    chain is made of them.
    """
    g = load_yaml(EXAMPLES / "aesop" / "sources.yaml")
    back = Graph().parse(data=g.serialize(format="turtle"), format="turtle")
    assert isomorphic(g, back)
    assert conforms(back)[0] is True


# ── The documentation is copy-pasteable ──────────────────────────────────

DOCS = [Path(__file__).resolve().parent.parent / p
        for p in ("docs/advanced.md", "README.md")]


def _turtle_blocks():
    import re
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"```turtle\n(.*?)```", text, re.S), 1):
            yield f"{doc.name}#{i}", block


@pytest.mark.parametrize("where,block", list(_turtle_blocks()))
def test_documented_turtle_parses(where, block):
    """Every Turtle example in the docs is valid Turtle.

    The RDF example in `advanced.md` used `rdf:value` without declaring the
    `rdf:` prefix — rdflib predeclares nothing, so the one thing the RDF section
    invited a reader to copy did not parse. Documentation drifts silently unless
    something reads it.
    """
    Graph().parse(data=block, format="turtle")


# ── conforms() must never traceback on a shapes file it cannot run ───────

@pytest.mark.parametrize("bad_shapes", [
    # An invalid regex — pyshacl surfaces `re.error`, which is not even one of
    # its own exception types, so catching its base class would not be enough.
    'ex:S a sh:NodeShape ; sh:targetClass ex:T ;\n'
    '  sh:property [ sh:path ex:p ; sh:pattern "[unclosed" ] .',
    # A cardinality that is not a number.
    'ex:S a sh:NodeShape ; sh:targetClass ex:T ;\n'
    '  sh:property [ sh:path ex:p ; sh:minCount "lots" ] .',
    # Two sh:path on one implicit property shape.
    'ex:S a sh:NodeShape ; sh:targetClass ex:T ;\n'
    '  sh:property [ sh:path ex:p, ex:q ; sh:minCount 1 ] .',
])
def test_a_shapes_file_we_cannot_run_reads_as_did_not_run(bad_shapes):
    """`validate` merges in a project's own `*-shapes.ttl`, and those are the
    shapes most likely to be malformed.

    pyshacl raises rather than reporting, and the raise was unguarded — so the
    command that exists to give a clean answer about a user's file answered with
    a traceback, blaming the tool for the file. It is the third outcome, not a
    failure of the data: we could not look.
    """
    shapes = Graph().parse(data=(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix ex: <http://example.org/#> .\n" + bad_shapes), format="turtle")
    data = Graph().parse(
        data=PREFIXES + "ex:a a ex:T ; ex:p 'v' .", format="turtle")

    ok, reason = conforms(data, shapes)
    assert ok is None
    assert "could not run" in reason


def test_the_shipped_shapes_are_not_mutated_by_validating():
    """pyshacl writes into any shapes graph it is handed.

    It injects two `rdfs:subClassOf` axioms, so a cached `Graph` grew 191 -> 193
    on first use. Nothing changes outcome today, but a process-global graph two
    callers mutate is a race waiting for the first threaded caller, and rdflib's
    default store is not thread-safe.
    """
    before = len(shipped_shapes())
    data = Graph().parse(data=PREFIXES + "ex:x a ex:Nothing .", format="turtle")
    conforms(data)
    conforms(data)
    assert len(shipped_shapes()) == before


def test_shipped_shapes_hands_out_independent_graphs():
    """`validate` does `shapes += shipped_shapes()`; that must not accumulate."""
    a, b = shipped_shapes(), shipped_shapes()
    assert a is not b
    a.parse(data=PREFIXES + "ex:scribble a ex:Thing .", format="turtle")
    assert len(b) == len(shipped_shapes())
