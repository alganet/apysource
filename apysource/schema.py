# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""What a sources file may say, and how it is refused when it says otherwise.

The vocabulary and the two refusals, in one place with nothing above them. They
live here rather than in ``yaml_input`` because ``patterns`` needs them too, and
that made a cycle: ``patterns`` imported ``yaml_input`` for these, ``yaml_input``
imported ``patterns`` to mint a url from a label, and the loop was survivable only
by hiding one of the imports inside a function body. An import you have to hide is
telling you the dependency is on the wrong thing. It was: neither module wants the
*other*, they both want the vocabulary, and the vocabulary depends on nobody.
"""

from __future__ import annotations

from rdflib.namespace import DCTERMS

from apysource.formats import normalize_mime_type
from apysource.namespaces import BIBO, SCHEMA, SV

# YAML key → RDF predicate for source-level properties
_SOURCE_KEYS = {
    "url": SCHEMA.url,
    "type": DCTERMS.format,
    "language": DCTERMS.language,
    "title": DCTERMS.title,
    "date": DCTERMS.issued,
    "license": DCTERMS.license,
    "isbn": BIBO.isbn,
    "doi": BIBO.doi,
    "publisher": DCTERMS.publisher,
    "edition": SV.edition,
}

# Keys that need special value normalization
_NORMALIZE_KEYS = {
    "type": normalize_mime_type,
}

# YAML key → RDF predicate for fragment-level properties
# (snippet, selector, section are handled by OA emission, not stored as flat sv: properties)
_FRAGMENT_KEYS = {
    "lines": SV.sourceLines,
    "location": SV.sourceLocation,
    "page_start": BIBO.pageStart,
    "page_end": BIBO.pageEnd,
}

_SOURCE_ALLOWED = set(_SOURCE_KEYS) | {"label", "part_of", "fragments"}
_FRAGMENT_ALLOWED = (set(_FRAGMENT_KEYS)
                     | {"label", "snippet", "selector", "section", "cited_by"})

# Keys of one entry of a fragment's ``cited_by`` list.
_CITE_SITE_ALLOWED = {"file", "line"}

# What the file itself may say. `patterns:` is meaningful now, and a typo'd
# `pattern:` would otherwise be ignored — minting nothing, and leaving every
# url-less source to fail with a message about the wrong thing entirely.
_TOP_ALLOWED = {"sources", "patterns"}

#: What a source may say, and what a fragment may say — as data, on purpose.
#:
#: A tool that *generates* citations has to know what it is allowed to emit, and
#: the honest way to tell it is to say so. The alternative is that it reads the
#: private name, or keeps its own copy — and a second copy of this list is how a
#: generator ends up emitting a key this loader silently stopped accepting.
SOURCE_KEYS = frozenset(_SOURCE_ALLOWED)
FRAGMENT_KEYS = frozenset(_FRAGMENT_ALLOWED)

#: The fragment keys that *select a passage*: everything a citation can say about
#: where in the source its quote lives. `label` names the citation, `snippet` is
#: the quote itself, and `cited_by` is the citing side — none of them target.
TARGETTING_KEYS = FRAGMENT_KEYS - {"label", "snippet", "cited_by"}


def reject_unknown_keys(entry: dict, allowed: set[str], what: str) -> None:
    """A key we do not know is a key we silently ignore.

    ``snipet:`` loaded without a murmur, and the citation went on to verify
    nothing at all. The author wrote the quote down; the tool threw it away and
    called the run a pass.
    """
    unknown = sorted(k for k in entry if k not in allowed)
    if unknown:
        raise ValueError(
            f"{what}: unknown key{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(k) for k in unknown)}. "
            f"Known keys are: {', '.join(sorted(allowed))}. "
            f"A key apysource does not recognise is a key it ignores, and a "
            f"citation whose snippet was dropped verifies nothing.",
        )


def text(value: object, what: str) -> str:
    """A scalar YAML value, as text — or a clear refusal.

    ``str()`` was applied to whatever turned up, so a ``snippet:`` written as a
    YAML *list* was stored as its Python repr — ``"['line one', 'line two']"`` —
    and the citation could then never match, however faithfully it was quoted.
    """
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ValueError(
        f"{what} must be a single piece of text, not a "
        f"{type(value).__name__}. Written as a list or a mapping it would be "
        f"stored as its Python repr and could never match the source.",
    )
