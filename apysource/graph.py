# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Shared graph loading and RDF utilities.

Pure functions — no module-level state, no config imports.
All paths are received as parameters from callers.
"""

from pathlib import Path

from rdflib import Graph

from apysource.namespaces import new_graph

#: Separators before a role suffix — `spec-shapes.ttl`, `spec.shapes.ttl`.
_ROLES = ("shapes", "inferred")


def classify(name: str) -> str:
    """What a `.ttl` file is: ``shapes``, ``inferred``, ``semantic`` or ``data``.

    Decided from a *naming convention*, not from a substring anywhere in the
    name. It used to be `"shapes" in name`, so `landshapes.ttl` was parsed as
    SHACL and `inferred-meanings.ttl` was dropped from **both** graphs — a file
    of citations, silently, entirely gone, with `validate` still reporting the
    number of files it had *found* rather than the number it had read.

    A file is shapes or inferred only if that is what its name *ends with*:
    ``shapes.ttl``, ``http-shapes.ttl``, ``http.shapes.ttl``. Everything else
    is data, and data is never quietly discarded.
    """
    stem = name[:-4] if name.endswith(".ttl") else name
    if stem.endswith("-semantic"):
        return "semantic"
    for role in _ROLES:
        if stem == role or stem.endswith((f"-{role}", f".{role}", f"_{role}")):
            return role
    return "data"


def load_triples(
    rdf_dir: Path,
    *,
    include_shapes: bool = False,
    include_inferred: bool = False,
    include_semantic: bool = True,
) -> Graph:
    """Load all .ttl files from a directory into a single Graph.

    See ``classify`` for how a file's role is decided from its name.
    """
    g = Graph()
    for f in sorted(rdf_dir.rglob("*.ttl")):
        kind = classify(f.name)
        if not include_shapes and kind == "shapes":
            continue
        if not include_inferred and kind == "inferred":
            continue
        if not include_semantic and kind == "semantic":
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
        kind = classify(f.name)
        if kind == "inferred":
            continue
        target = shapes if kind == "shapes" else g
        try:
            target.parse(str(f), format="turtle")
        except Exception as e:
            errors.append((str(f), str(e)))

    return g, shapes, errors


def load_turtle(path: Path) -> Graph:
    """Read one Turtle file, the way ``load_yaml`` reads one YAML file.

    The counterpart that was missing. ``check`` and ``validate`` could be handed
    a ``.yaml`` and would load it; handed a ``.ttl`` they matched no suffix, fell
    through to scanning the configured RDF root, and passed the filename along as
    an unrecognised positional — so the file named on the command line was never
    opened, and nothing said so.

    Prefixes are bound (via ``new_graph``) so anything re-serialized from here
    comes back out readable rather than as a wall of full IRIs.
    """
    g = new_graph()
    g.parse(str(path), format="turtle")
    return g


def local_name(uri) -> str:
    """Extract local name after # from a URI."""
    return str(uri).split("#")[-1]
