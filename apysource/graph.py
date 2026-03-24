# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared graph loading and RDF utilities.

Pure functions — no module-level state, no config imports.
All paths are received as parameters from callers.
"""

from pathlib import Path

from rdflib import Graph, URIRef

from apysource.namespaces import SV


def load_triples(
    rdf_dir: Path,
    *,
    include_shapes: bool = False,
    include_inferred: bool = False,
    include_semantic: bool = True,
) -> Graph:
    """Load all .ttl files from a directory into a single Graph."""
    g = Graph()
    for f in sorted(rdf_dir.rglob("*.ttl")):
        name = str(f)
        if not include_shapes and "shapes" in name:
            continue
        if not include_inferred and "inferred" in name:
            continue
        if not include_semantic and f.name.endswith("-semantic.ttl"):
            continue
        g.parse(str(f), format="turtle")
    return g


def load_triples_split(
    rdf_dir: Path,
) -> tuple[Graph, Graph, list[tuple[str, str]]]:
    """Load triples into separate data and shape graphs."""
    g = Graph()
    shapes = Graph()
    errors = []

    for f in sorted(rdf_dir.rglob("*.ttl")):
        if "inferred" in str(f):
            continue
        target = shapes if "shapes" in str(f) else g
        try:
            target.parse(str(f), format="turtle")
        except Exception as e:
            errors.append((str(f), str(e)))

    return g, shapes, errors


def local_name(uri) -> str:
    """Extract local name after # from a URI."""
    return str(uri).split("#")[-1]
