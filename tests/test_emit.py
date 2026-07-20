# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for `apysource emit` and for everything else that writes RDF out.

Emission is where a graph stops being apysource's business and becomes someone
else's input, so each emitter gets the same test: serialize it, read it back,
and hold it to the shapes apysource would hold anyone else's file to.
"""

from pathlib import Path

import pytest
from rdflib import Graph, RDF
from rdflib.compare import isomorphic

from apysource.api import check_graph
from apysource.cli.emit import EmitCommand
from apysource.cli.locate import format_turtle
from apysource.formats import LocateResult
from apysource.namespaces import PROV, SV
from apysource.repos import RepoRegistry
from apysource.shapes import conforms
from apysource.yaml_input import graph_from_data, load_yaml

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

SOURCES = {"sources": [{
    "label": "Aesop", "url": "https://x/", "type": "text/html",
    "fragments": [{"label": "Fox", "snippet": "a fox saw some fine bunches of grapes"}],
}]}


class _Fetcher:
    def __init__(self, body):
        self.body = body

    def get(self, url, force=False):
        return self.body


# ── emit ─────────────────────────────────────────────────────────────────

def test_emit_writes_turtle_that_reads_back_identical(tmp_path, capsys):
    out = tmp_path / "out.ttl"
    g = graph_from_data(SOURCES)
    EmitCommand().run(graph=g, args=["-o", str(out)], vetted=True)

    back = Graph().parse(out, format="turtle")
    assert isomorphic(g, back), "emitting must not change what the graph says"
    assert conforms(back)[0] is True


def test_emit_to_stdout(capsys):
    EmitCommand().run(graph=graph_from_data(SOURCES), args=[], vetted=True)
    out = capsys.readouterr().out
    assert "sv:Fragment" in out


@pytest.mark.parametrize("fmt,marker", [
    ("turtle", "@prefix"),
    ("json-ld", "@id"),
    ("nt", "<urn:apysource:"),
])
def test_emit_formats(fmt, marker, capsys):
    EmitCommand().run(graph=graph_from_data(SOURCES),
                      args=["--format", fmt], vetted=True)
    assert marker in capsys.readouterr().out


def test_emit_refuses_an_unknown_format(capsys):
    with pytest.raises(SystemExit) as exc:
        EmitCommand().run(graph=graph_from_data(SOURCES),
                          args=["--format", "yaml"], vetted=True)
    assert exc.value.code == 1
    assert "unknown --format" in capsys.readouterr().err


def test_emit_refuses_an_empty_graph(capsys):
    """A run that produced nothing is not a run that succeeded.

    The same rule the report follows. An empty file written in silence is how a
    broken generator goes unnoticed.
    """
    with pytest.raises(SystemExit) as exc:
        EmitCommand().run(graph=Graph(), args=[], vetted=True)
    assert exc.value.code == 1
    assert "nothing to emit" in capsys.readouterr().err


def test_emit_refuses_with_no_file(capsys):
    with pytest.raises(SystemExit) as exc:
        EmitCommand().run(graph=None, args=[])
    assert exc.value.code == 1
    assert "needs a citations file" in capsys.readouterr().err


# ── The identifier warning ───────────────────────────────────────────────

def test_emit_warns_about_default_identifiers(capsys):
    """`urn:apysource:` is derived from labels, so it collides across projects.

    Harmless while the graph stays on one machine; a merge hazard the moment it
    leaves, which is exactly what this command does.
    """
    EmitCommand().run(graph=graph_from_data(SOURCES), args=[], vetted=True)
    err = capsys.readouterr().err
    assert "urn:apysource:" in err
    assert "base:" in err


def test_a_base_silences_the_warning(capsys):
    g = graph_from_data({**SOURCES, "base": "https://example.org/citations"})
    EmitCommand().run(graph=g, args=[], vetted=True)
    assert "Warning" not in capsys.readouterr().err


def test_a_base_mints_identifiers_under_it():
    g = graph_from_data({**SOURCES, "base": "https://example.org/citations"})
    subjects = {str(s) for s in g.subjects(RDF.type, SV.Fragment)}
    assert subjects == {"https://example.org/citations#fragment_aesop_fox"}


@pytest.mark.parametrize("base", ["citations", "./relative", "", "  "])
def test_a_relative_base_is_refused(base):
    """A relative base means something different in every file that reads it."""
    with pytest.raises(ValueError, match="absolute IRI"):
        graph_from_data({**SOURCES, "base": base})


# ── locate --ttl ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("result,title", [
    (LocateResult(format_name="section", locator="Preamble"), "UN Charter"),
    (LocateResult(format_name="html", locator="div.main p"), "Fetch Standard"),
    (LocateResult(format_name="text", locator="10-20"), ""),
])
def test_locate_ttl_output_conforms(result, title):
    """The output of `--ttl` exists to be pasted into a `.ttl` file.

    It carried no `rdfs:label` on either the source or the fragment, so
    `validate` refused the file it had just been pasted into — apysource
    emitting RDF its own validator rejects, unnoticed because the shapes had
    never run.
    """
    ttl = format_turtle("https://un.org/charter", "text/html",
                        "to save succeeding generations from the scourge of war",
                        result, title)
    assert conforms(Graph().parse(data=ttl, format="turtle"))[0] is True


def test_locate_ttl_labels_the_source_from_its_title():
    ttl = format_turtle("https://un.org/charter", "text/html", "a quote here",
                        LocateResult(format_name="section", locator="Preamble"),
                        "UN Charter")
    assert '"UN Charter"' in ttl
    assert '"Preamble"' in ttl


def test_locate_ttl_falls_back_to_the_url_when_untitled():
    ttl = format_turtle("https://example.org/spec", "text/plain", "a quote here",
                        LocateResult(format_name="text", locator="1-5"), "")
    assert '"spec"' in ttl


# ── check --provenance ───────────────────────────────────────────────────

def _run_with_provenance():
    body = (Path(__file__).resolve().parent / "fixtures" / "un_charter.html"
            ).read_text(encoding="utf-8", errors="replace")
    g = graph_from_data({"sources": [{
        "label": "UN Charter", "url": "https://un.org/x", "type": "text/html",
        "fragments": [
            {"label": "Preamble",
             "snippet": "to save succeeding generations from the scourge of war"},
            {"label": "Absent",
             "snippet": "this sentence appears nowhere in the charter at all"},
        ],
    }]})
    results, prov = check_graph(g, registry=RepoRegistry([]),
                                fetcher=_Fetcher(body), emit_provenance=True)
    return g, prov


def test_provenance_conforms():
    _, prov = _run_with_provenance()
    assert conforms(prov)[0] is True


def test_provenance_records_every_fragment_it_examined():
    """Including the failures.

    Several failure paths returned before recording anything, so a fragment the
    run had examined and rejected was simply absent — indistinguishable from one
    the run never reached. A file that omits its failures is not a record.
    """
    _, prov = _run_with_provenance()
    verdicts = {
        str(prov.value(v, PROV.wasDerivedFrom)): str(prov.value(v, SV.verificationStatus))
        for v in prov.subjects(RDF.type, SV.VerificationResult)
    }
    assert len(verdicts) == 2
    assert set(verdicts.values()) == {"verified", "failed"}


def test_provenance_says_the_run_used_the_fragment():
    """PROV-O direction. `wasGeneratedBy` claimed the run created the citation."""
    _, prov = _run_with_provenance()
    activities = list(prov.subjects(RDF.type, SV.VerificationActivity))
    assert len(activities) == 1
    used = set(prov.objects(activities[0], PROV.used))
    assert len(used) == 2
    for frag in used:
        assert prov.value(frag, PROV.wasGeneratedBy) is None


def test_provenance_stands_on_its_own():
    """Every identifier it names is described in the file that names it.

    It used to emit fragment URNs and nothing else about them — the type, label
    and target live in the sources graph, which was never serialized alongside.
    Valid Turtle, readable only by someone who already had the YAML.
    """
    _, prov = _run_with_provenance()
    named = {o for _, _, o in prov if str(o).startswith("urn:apysource:")}
    assert named, "the fixture should produce URN-identified subjects"
    for uri in named:
        assert list(prov.predicate_objects(uri)), f"{uri} is a dangling reference"


def test_provenance_survives_a_round_trip():
    _, prov = _run_with_provenance()
    back = Graph().parse(data=prov.serialize(format="turtle"), format="turtle")
    assert isomorphic(prov, back)
    assert conforms(back)[0] is True


# ── The shipped example, end to end ──────────────────────────────────────

def test_the_aesop_example_emits_a_file_validate_accepts(tmp_path):
    """YAML in, Turtle out, and the Turtle passes the same command a
    hand-written `.ttl` passes."""
    out = tmp_path / "aesop.ttl"
    EmitCommand().run(graph=load_yaml(EXAMPLES / "aesop" / "sources.yaml"),
                      args=["-o", str(out)], vetted=True)
    assert conforms(Graph().parse(out, format="turtle"))[0] is True


# ── Findings from review, pinned ─────────────────────────────────────────

def test_emit_reports_an_unwritable_path(tmp_path, capsys):
    """Every other refusal here is one line and an exit; this one tracebacked."""
    with pytest.raises(SystemExit) as exc:
        EmitCommand().run(graph=graph_from_data(SOURCES),
                          args=["-o", str(tmp_path / "missing" / "out.ttl")],
                          vetted=True)
    assert exc.value.code == 1
    assert "could not write" in capsys.readouterr().err


@pytest.mark.parametrize("base", ["https://ex.org/c#v1", "https://ex.org/a#b#c"])
def test_a_base_that_already_has_a_fragment_is_refused(base):
    """`https://ex.org/c#v1` would mint `…#v1#fragment_…` — two '#'.

    Not a legal IRI (RFC 3987 excludes '#' from `ipchar`). rdflib serializes and
    reparses it without complaint, so it escapes silently and fails in whatever
    stricter consumer reads the file.
    """
    with pytest.raises(ValueError, match="fragment"):
        graph_from_data({**SOURCES, "base": base})


@pytest.mark.parametrize("base,expected", [
    ("https://ex.org/c", "https://ex.org/c#fragment_aesop_fox"),
    ("https://ex.org/c#", "https://ex.org/c#fragment_aesop_fox"),
    ("https://ex.org/c/", "https://ex.org/c/fragment_aesop_fox"),
    ("urn:example:cites", "urn:example:cites#fragment_aesop_fox"),
])
def test_base_separators(base, expected):
    g = graph_from_data({**SOURCES, "base": base})
    assert {str(s) for s in g.subjects(RDF.type, SV.Fragment)} == {expected}


def test_provenance_carries_the_whole_part_of_chain():
    """A CBD stops at a named node, so `dcterms:isPartOf` was copied as a bare
    reference to a parent described nowhere in the file.

    That failed apysource's own `SourceShape` — the dangling-reference problem
    the copying was added to fix, one level further up, and only visible once
    the shapes actually ran.
    """
    g = graph_from_data({"sources": [
        {"label": "Series", "url": "https://example.com/"},
        {"label": "Book", "url": "https://example.com/b", "part_of": "Series"},
        {"label": "Chapter", "url": "https://example.com/b/1", "part_of": "Book",
         "fragments": [{"label": "F", "snippet": "a quote long enough to be evidence"}]},
    ]})
    _, prov = check_graph(g, registry=RepoRegistry([]),
                          fetcher=_Fetcher("a quote long enough to be evidence " * 4),
                          emit_provenance=True)

    assert conforms(prov)[0] is True
    described = {str(prov.value(s, __import__("rdflib").RDFS.label))
                 for s in prov.subjects(RDF.type, SV.Source)}
    assert described == {"Series", "Book", "Chapter"}


# ── Emitted RDF is byte-stable ───────────────────────────────────────────

def _turtle_twice(data):
    """Serialize the same data through two independent loads."""
    return (graph_from_data(data).serialize(format="turtle"),
            graph_from_data(data).serialize(format="turtle"))


def test_turtle_is_byte_stable_across_loads():
    """Two runs over the same input must produce the same document.

    `BNode()` mints a fresh uuid each time and rdflib orders the objects of a
    predicate by blank-node identity — so a fragment carrying both a section
    selector and a quote selector emitted them in a different order each run.
    On a real 295-citation project that was 1498 differing lines between two
    serializations of the same file.

    The labels never appear in the output (the serializer nests blank nodes
    inline), so the file looks stable right up until it is committed and
    something diffs it: `apycite extract --frozen` compares bytes, and a CI job
    that reports a diff on every commit teaches everyone to ignore it.
    """
    data = {"sources": [{"label": "S", "url": "https://x/", "fragments": [
        # Two selectors on one target is the case that was unstable.
        {"label": f"F{i}", "snippet": f"quote {i}", "section": f"§ {i}"}
        for i in range(12)
    ]}]}
    a, b = _turtle_twice(data)
    assert a == b


def test_stability_does_not_leak_blank_node_labels():
    """Blank nodes stay blank. The labels are an ordering device, not a name."""
    data = {"sources": [{"label": "S", "url": "https://x/", "fragments": [
        {"label": "F", "snippet": "q", "section": "§ 1",
         "cited_by": [{"file": "a.rs", "line": 3}]}]}]}
    assert "_:" not in graph_from_data(data).serialize(format="turtle")


def test_stability_preserves_the_graph():
    """Labelling the blank nodes must not change what the graph says."""
    data = {"sources": [{"label": "S", "url": "https://x/", "fragments": [
        {"label": "F", "snippet": "q", "section": "§ 1"}]}]}
    g = graph_from_data(data)
    back = Graph().parse(data=g.serialize(format="turtle"), format="turtle")
    assert isomorphic(g, back)


def test_a_local_change_makes_a_local_diff():
    """Derived from the fragment, not from a counter.

    A counter is equally stable but renumbers every node after an insertion, so
    adding one citation would rewrite the whole file — and a diff the size of the
    project says nothing about what changed.
    """
    def doc(fragments):
        return {"sources": [{"label": "S", "url": "https://x/",
                             "fragments": fragments}]}

    base = [{"label": f"F{i}", "snippet": f"quote {i}"} for i in range(20)]
    before = graph_from_data(doc(base)).serialize(format="turtle").splitlines()
    after = graph_from_data(
        doc([{"label": "new", "snippet": "an inserted quote"}, *base]),
    ).serialize(format="turtle").splitlines()

    import difflib
    changed = [line for line in difflib.unified_diff(before, after, lineterm="", n=0)
               if line[:1] in "+-" and line[:3] not in ("---", "+++")]
    # The inserted fragment is a handful of lines; the other 20 must not move.
    assert len(changed) < 15, f"{len(changed)} lines moved for one insertion"


def test_locate_ttl_output_is_byte_stable():
    """`--ttl` output is meant to be pasted into a file and committed."""
    args = ("https://un.org/charter", "text/html", "a quote here",
            LocateResult(format_name="section", locator="Preamble"), "UN Charter")
    assert format_turtle(*args) == format_turtle(*args)
