# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""The sources file as *data*, with names resolved.

``graph_from_data`` answers "what does this file mean" and returns a graph. That
is the right answer for a checker and the wrong one for a generator: a tool that
has to *write* a sources file needs the entries back as they were written, plus
the url a pattern minted for the ones that named a family instead.

So this module is the second reading of the same file, and it is deliberately
thin. It does not validate — ``graph_from_data`` does, and it is the only thing
that ever will. A generator holding its own copy of what a source entry may say
is how a generator ends up emitting a key the loader silently stopped accepting.

What it adds is one question the graph cannot answer: *what source does this name
denote?* — including for a name that appears in no entry at all, which is the case
a citation generator lives in. A comment says ``cite(RFC 9110 § 7.2)``, no sources
file mentions RFC 9110, and the answer is still not "guess".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apysource.patterns import SourcePattern, complete, mint_source, patterns_from_data
from apysource.yaml_input import graph_from_data


@dataclass
class SourceSet:
    """Every source a file names, and every source its patterns could mint."""

    #: label -> the entry as written, in file order, with its url filled in. A
    #: consumer emitting these into a file of its own gets one that stands alone:
    #: full url, full media type, no pattern table needed to read it.
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    patterns: list[SourcePattern] = field(default_factory=list)

    #: The file's own ``base:``, or ``""``.
    #:
    #: Kept because a generator writing a file of its own has to carry it
    #: forward. Without it the base is silently dropped at exactly the moment it
    #: matters: the *generated* file is the one that gets verified and emitted as
    #: RDF, so an author who asked for identifiers under a name they control got
    #: ``urn:apysource:`` back — the collide-on-merge form — and nothing said so.
    base: str = ""

    def resolve(self, name: str) -> dict[str, Any] | None:
        """The source this name denotes — an entry, or a minted one, or ``None``.

        ``None``, never a guess. The caller knows why it was asking (a cite at a
        file and a line, a name typed on a command line), and only it can say so.
        """
        entry = self.entries.get(name)
        if entry is not None:
            return entry
        minted = mint_source(name, self.patterns)
        if minted is None:
            return None
        return {"label": name, **minted}


def sources_from_data(data: object, origin: str = "<data>") -> SourceSet:
    """A ``SourceSet`` from already-parsed sources data, validated as usual."""
    # Compiled once, here, and handed to the loader — which would otherwise compile
    # every regex in the file a second time and complete every entry a second time,
    # for the same answer.
    patterns = patterns_from_data(data, origin)

    # The one definition of what a sources file means. It refuses every entry that
    # `complete` below would have no url for, so by the time we walk them again
    # there is nothing left to refuse.
    graph_from_data(data, origin=origin, patterns=patterns)

    entries: dict[str, dict[str, Any]] = {}
    for source_def in data["sources"]:  # type: ignore[index]
        completed = complete(source_def, patterns)
        if completed is None:  # pragma: no cover — graph_from_data already refused it
            raise ValueError(
                f"{origin}: source {source_def.get('label')!r} has no url and no "
                f"pattern mints one. (This should have been refused by the loader; "
                f"if you are seeing it, the two have disagreed.)",
            )
        entries[completed["label"]] = completed

    # Read after `graph_from_data`, which has already refused a base that is not
    # an absolute IRI or that carries a fragment of its own — so what reaches a
    # consumer here is a base the loader would accept back.
    base = data.get("base") or "" if isinstance(data, dict) else ""

    return SourceSet(entries=entries, patterns=patterns, base=str(base))


def load_sources(path: Path | None) -> SourceSet:
    """Read a sources file — or don't.

    ``None`` is a sources file with nothing in it, and it is not an error: the
    shipped patterns still resolve, so a project whose every citation names an
    ``RFC NNNN`` never has to write the file at all.
    """
    if path is None:
        return SourceSet(patterns=list(patterns_from_data({}, "<none>")))

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return sources_from_data(data, origin=str(path))
