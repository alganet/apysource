# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The library entry points: `graph_from_data` and `check_graph`.

The promise: **a caller that is not the CLI gets the same checks the CLI runs.**
A second definition of "the standard checks" is one definition too many — it is
how two callers end up disagreeing about whether the same graph passed.
"""

from unittest.mock import patch

import pytest
import yaml
from rdflib.compare import isomorphic

from apysource.api import STANDARD_CHECKS, check_graph
from apysource.verification import failed
from apysource.yaml_input import graph_from_data, load_yaml
from tests.conftest import EMPTY_REGISTRY, MockFetcher

BODY = "A client MUST send a Host header field in all requests."

DATA = {"sources": [{
    "label": "RFC 9112",
    "url": "https://www.rfc-editor.org/rfc/rfc9112.txt",
    "type": "text/plain",
    "fragments": [{"label": "host", "snippet": BODY}],
}]}


# ── graph_from_data ─────────────────────────────────────────────────────

def test_data_and_file_mint_the_same_graph(tmp_path):
    """One definition of what a sources file means, whether it is a file or not.

    A generator holding the data must not get a *different* graph from the one
    it would get by writing the data out and reading it back. If it did, its
    round-trip check would be checking a different thing than `check` runs.
    """
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(DATA), encoding="utf-8")

    # Isomorphism, not set equality: the OA chain hangs off blank nodes, and
    # blank nodes are named afresh on every load. Two graphs that say the same
    # thing are the same graph, whatever their bnodes ended up called.
    assert isomorphic(load_yaml(path), graph_from_data(DATA))


def test_the_same_refusals_apply_to_data():
    """The validation is the loader's, not the file reader's."""
    with pytest.raises(ValueError, match="unknown key"):
        graph_from_data({"sources": [{"label": "s", "url": "http://x",
                                      "fragments": [{"label": "f",
                                                     "snipet": "typo"}]}]})


def test_data_that_is_not_a_sources_file_is_named_in_the_error():
    with pytest.raises(ValueError, match="specs.yaml"):
        graph_from_data({"srcs": []}, origin="specs.yaml")


# ── check_graph ─────────────────────────────────────────────────────────

def test_check_graph_verifies_a_quote_that_is_there():
    results = check_graph(graph_from_data(DATA), registry=EMPTY_REGISTRY,
                          fetcher=MockFetcher(BODY))

    assert not failed(results)
    assert sum(check.ok for check in results) >= 1, "a green run verified nothing"


def test_check_graph_fails_a_quote_that_is_not():
    moved = {"sources": [{**DATA["sources"][0],
                          "fragments": [{"label": "host",
                                         "snippet": "A client MUST send a Teapot."}]}]}

    assert failed(check_graph(graph_from_data(moved), registry=EMPTY_REGISTRY,
                              fetcher=MockFetcher(BODY)))


def test_the_cli_and_the_library_run_the_same_checks():
    """The reason this module exists.

    `apysource check` and a library caller must not be able to disagree about
    what "checked" means — so they read the same list, and this is the test
    that keeps a second copy of it from growing back.
    """
    from apysource.cli import check_sources

    assert check_sources.check_graph is check_graph
    assert [c["name"] for c in STANDARD_CHECKS] == ["Fragments", "Terms"]


def test_omitting_a_fetcher_is_not_the_same_as_passing_none():
    """"Not given" and "given as nothing" are different questions.

    The wiring passes ``fetcher=None`` deliberately; substituting a real HTTP
    client behind its back would build a network client where the caller asked
    for none. Omitting the argument, by contrast, means "the usual one".
    """
    g = graph_from_data(DATA)

    with patch("apysource.api.run_checks", return_value=[]) as run:
        check_graph(g, registry=EMPTY_REGISTRY, fetcher=None)
    assert run.call_args.kwargs["fetcher"] is None

    sentinel = MockFetcher(BODY)
    with patch("apysource.api.default_fetcher", return_value=sentinel):
        with patch("apysource.api.run_checks", return_value=[]) as run:
            check_graph(g, registry=EMPTY_REGISTRY)
    assert run.call_args.kwargs["fetcher"] is sentinel
