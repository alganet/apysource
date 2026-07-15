# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""A name shaped like ``RFC 9110`` → the source apysource would fetch.

Patterns exist only because writing 350 entries for RFC 1..9999 by hand is silly.
They can express a *uniform family* — a URL and a media type. A book needs an
ISBN, a publisher, an edition; a chapter needs a ``part_of``. Those have
biographies, and a biography goes in the sources file.

This is the one link in the chain that used to live somewhere else. Everything
downstream of a URL is here — repo claiming, fetching, caching, format detection,
section trees, redirect surfacing — so the tool that turns a *name* into that URL
has to be here too, next to the fetcher that has to know the URL anyway. A
citation generator that minted rfc-editor links itself would be claiming to know
what an RFC is, and it does not.

**A pattern is not a repo, and the two are not alternatives.** They are inverse
directions, and they compose::

    name --[pattern.match]--> canonical URL --[repo.url_pattern]--> key --> fetch url
          ^ GENERATES a url                  ^ PARSES one

A pattern's output is a repo's input. ``url_pattern`` is a *parser*: it claims a URL
that already exists and takes it apart. ``match`` is a *generator*: it produces a URL
that did not exist until someone wrote a name. Nothing in this module fetches,
caches, renders, or knows a 404 from an outage — a ``SourcePattern`` is a frozen
dataclass with one pure string substitution. That is the whole of it.

Nor can the two be merged. ``BaseRepo`` has no key→URL direction and cannot get one:
``MdnRepo.url_to_key`` is deliberately non-injective, so ``Web/CSS/:hover`` becomes
``web/css/_colon_hover`` and there is no way back. To make repos mint URLs from names
you would have to give each one a second, *forward* template — which is precisely a
``SourcePattern``, wearing a repo's name. So that is what they declare: see
``BaseRepo.family``, and ``DEFAULT_PATTERNS`` below.

The families that ship are of two kinds, and the split is the point:

* ``RFC NNNN`` — declared *here*, because no repo claims rfc-editor. Patterns exist
  for exactly this gap: a family with a uniform URL and nobody to fetch it specially.
* ``MDN <page>``, ``Gutenberg <id>``, and the rest — declared by *their repos*, because
  how you name an MDN page is MDN's knowledge and this module has none.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from string import Formatter
from typing import Any

from apysource.repos.archive import ArchiveRepo
from apysource.repos.gutenberg import GutenbergRepo
from apysource.repos.mdn import MdnRepo
from apysource.repos.wikisource import WikisourceRepo
from apysource.repos.wiktionary import WiktionaryRepo
from apysource.schema import SOURCE_KEYS, reject_unknown_keys, text


@dataclass(frozen=True)
class SourcePattern:
    """A regex over names, and the source template it fills in."""

    pattern: re.Pattern[str]
    source: dict[str, str]

    def mint(self, name: str) -> dict[str, str] | None:
        """The source this name denotes, or ``None`` if the pattern does not claim it.

        No ``label``: the name *is* the label, and it belongs to the caller — the
        loader already holds it, and a generator resolving a name it read from a
        comment holds a different one.
        """
        match = self.pattern.match(name)
        if match is None:
            return None

        # A group that did not participate is the empty string, not ``None``.
        # ``groupdict`` hands back ``None``, and ``str.format`` would render that
        # as the four letters "None" — so `^RFC (?P<n>\d+)(?P<sfx>bis)?$` minted
        # `.../rfc9110None.txt` and fetched it. A url with "None" in it is never
        # what anyone meant; an optional part that is absent is simply absent.
        fields = {key: "" if value is None else value
                  for key, value in match.groupdict().items()}
        return {key: value.format(**fields) for key, value in self.source.items()}


#: What one entry of a ``patterns:`` list may say.
PATTERN_KEYS = frozenset({"match", "source"})

#: What a pattern's ``source:`` template may say. ``label`` comes from the name
#: that matched; ``fragments`` are a citation's business, not a family's.
TEMPLATE_KEYS = SOURCE_KEYS - {"label", "fragments"}

#: The one family that is this module's own, because no repo claims rfc-editor:
#: `check` falls through to the generic fetcher and `RfcTextFormat` reads it. This
#: is the gap patterns exist for.
RFC_FAMILY: dict[str, Any] = {
    "match": r"^RFC (?P<n>\d+)$",
    "source": {
        "url": "https://www.rfc-editor.org/rfc/rfc{n}.txt",
        "type": "text/plain",
    },
}

#: The repos whose families ship. The same five the default registry wires — but
#: these are the *classes*, and no instance is built: a family is data a repo
#: declares, not a thing it does. Hence no apywire, no `_defaults`, no compile
#: step, and no release standing between a user and a name that resolves.
SHIPPED_REPOS = [ArchiveRepo, GutenbergRepo, MdnRepo, WikisourceRepo, WiktionaryRepo]

#: The shipped patterns, tried *after* whatever the sources file declares — so a
#: project that wants RFC 9110 from datatracker, or as HTML, writes one entry and
#: wins. A family of your own is a `patterns:` block, not a release of this package.
DEFAULT_PATTERN_DATA: list[dict[str, Any]] = [
    RFC_FAMILY,
    *(family for repo in SHIPPED_REPOS if (family := repo.family()) is not None),
]


def compile_patterns(raw: object, origin: str = "<data>",
                     what: str = "patterns") -> list[SourcePattern]:
    """Validate a ``patterns:`` list into ``SourcePattern``s, or refuse it.

    Everything refusable here is refused *now*, at load, because every one of
    these mistakes otherwise surfaces as a 404 against a URL nobody wrote.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"{origin}: '{what}' must be a list of {{match, source}} mappings, "
            f"not a {type(raw).__name__}.",
        )

    compiled: list[SourcePattern] = []
    for index, entry in enumerate(raw, start=1):
        where = f"{origin}: {what}[{index}]"

        if not isinstance(entry, dict):
            raise ValueError(
                f"{where} must be a mapping with 'match' and 'source', not a "
                f"{type(entry).__name__}.",
            )
        reject_unknown_keys(entry, set(PATTERN_KEYS), where)

        if "match" not in entry or "source" not in entry:
            raise ValueError(
                f"{where}: needs both 'match' and 'source'. A pattern with no "
                f"template mints nothing, and a template with no match claims "
                f"nothing.",
            )

        source = entry["source"]
        if not isinstance(source, dict) or not source.get("url"):
            raise ValueError(
                f"{where}: 'source' must be a mapping with a 'url'. The url is "
                f"the only thing a pattern exists to produce.",
            )
        reject_unknown_keys(source, set(TEMPLATE_KEYS), f"{where}: source")

        try:
            pattern = re.compile(str(entry["match"]))
        except re.error as exc:
            raise ValueError(
                f"{where}: bad regex {entry['match']!r}: {exc}",
            ) from None

        template = {key: text(value, f"{where}: source.{key}")
                    for key, value in source.items()}

        # A template field the pattern never captures is a 404 waiting to happen,
        # and it is knowable *now* — at load, not weeks later out of a stack trace.
        #
        # Read with `string.Formatter`, and not with a `\{(\w+)\}` regex, because
        # the regex is not the parser that will actually run. It got this wrong in
        # both directions: it let `https://e.org/{n}/{` through, whereupon
        # `str.format` raised "Single '{'" at mint time — the very deferred failure
        # this check exists to prevent — and it refused `{{lit}}`, a correctly
        # escaped literal brace that formats to `{lit}` and captures nothing.
        # `Formatter().parse` is the same reader `format` uses, so what it says is
        # a field *is* a field.
        captured = set(pattern.groupindex)
        for key, value in template.items():
            try:
                fields = [name for _, name, _, _ in Formatter().parse(value)
                          if name is not None]
            except ValueError as exc:
                raise ValueError(
                    f"{where}: source.{key} is not a usable template: {exc}. "
                    f"Write a literal brace as {{{{ or }}}}.",
                ) from None

            for field in fields:
                # `{n[0]}` / `{n.x}` reach into the captured value; the field the
                # pattern has to supply is the root name before any of that.
                root = re.split(r"[.\[]", field, maxsplit=1)[0]
                if root not in captured:
                    raise ValueError(
                        f"{where}: source.{key} uses {{{field}}}, which "
                        f"{entry['match']!r} does not capture. "
                        f"Captured: {', '.join(sorted(captured)) or '(nothing)'}. "
                        f"A template field the pattern never fills is a 404 "
                        f"waiting to happen, and it is knowable now.",
                    )

        compiled.append(SourcePattern(pattern, template))

    return compiled


#: Compiled once, through the same validator a user's patterns go through — there
#: is no privileged path for the ones that ship.
DEFAULT_PATTERNS: list[SourcePattern] = compile_patterns(
    DEFAULT_PATTERN_DATA, "<shipped>")


def patterns_from_data(data: object, origin: str = "<data>") -> list[SourcePattern]:
    """The patterns a sources file declares, then the shipped ones.

    The file's come first, so naming ``RFC NNNN`` yourself beats the RFC pattern
    apysource ships. First match wins, as with repos claiming a URL.
    """
    declared = data.get("patterns") if isinstance(data, dict) else None
    return compile_patterns(declared, origin) + DEFAULT_PATTERNS


def mint_source(name: str,
                patterns: Sequence[SourcePattern] = DEFAULT_PATTERNS,
                ) -> dict[str, str] | None:
    """The first pattern that claims this name, as a source dict — or ``None``.

    ``None``, not an exception: the caller is the one holding the context that
    makes a refusal readable (a file and a line, a sources file it was reading),
    and it is the one that should write the sentence.
    """
    for pattern in patterns:
        minted = pattern.mint(name)
        if minted is not None:
            return minted
    return None


def complete(source_def: dict[str, Any],
             patterns: Sequence[SourcePattern] = DEFAULT_PATTERNS,
             ) -> dict[str, Any] | None:
    """A source entry with its url filled in from a pattern, if it needs one.

    The merge order is the whole rule, and it lives here so that the loader and a
    generator cannot drift on it: **the entry wins, key by key**. A family knows a
    URL and a media type; it cannot know this book's `title`, this chapter's
    `part_of`, or that you want *this* RFC as HTML. So naming the family gets you
    the url for free and costs you nothing you would otherwise have written.
    """
    # Always a fresh dict, even when nothing was minted. Handing back the caller's
    # own object would make an entry that needed no url a *reference* into their
    # parsed YAML while a minted one was a copy — two ownership rules for one
    # return type, and a consumer that edits what it was given silently editing
    # the document it was reading.
    if source_def.get("url"):
        return dict(source_def)
    minted = mint_source(str(source_def.get("label", "")), patterns)
    if minted is None:
        return None
    return {**minted, **source_def}
