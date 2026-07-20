# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Explain why a snippet did not match.

A quote either appears in the source or it does not, and saying only that
leaves the reader to fetch the document and diff it by hand — which is the
authoring loop, run blind. When a snippet fails, the source almost always
contains something very close to it: a dropped parenthetical, a changed
case, a stray backtick that survived rendering. Find that passage and say
what differs.

Everything works in words, not characters. Words are what the reader is
comparing, and a character-level diff of a long quote is both unreadable
and quadratic in its length.

The one rule this module must never break: **do not claim something about
the source that is not true.** A hint that sends the author hunting for a
word already in front of them is worse than no hint at all.
"""

from collections import Counter
import re
import string
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from apysource.formats import TRUNCATION_MARKER, normalize_ws

#: Below this similarity, the closest passage is not worth showing — the
#: snippet is unrelated to the text, not a near-miss in it.
MIN_SIMILARITY = 0.5

#: Longest passage to render, in words. A block quote diffed in full is a
#: wall of text no one reads.
MAX_RENDERED_WORDS = 60

#: Markup that survives into rendered-ish text. Underscore is deliberately
#: absent: stripping it would report `get_text` as a marked-up `gettext`,
#: and this tool's corpus is full of snake_case.
_MARKUP = "`*"

_ELISION = re.compile(r"(\.\.\.|…)$")


@dataclass
class Diagnosis:
    """Why a snippet did not match, as data rather than as prose.

    Kept structured so a machine-readable report can serve it without
    parsing text back out of a rendered hint.
    """

    #: The passage in the source that comes closest to the snippet.
    source_text: str
    ratio: float
    #: Set when the words are right and only the typography is wrong.
    kind: str = ""
    #: Words the citation has that the passage does not, and vice versa.
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    #: The region that was searched (a section selector), when known.
    where: str = ""

    @property
    def percent(self) -> int:
        return round(self.ratio * 100)


def _words(text: str) -> list[str]:
    """Split text into the words a reader would compare."""
    text = normalize_ws(TRUNCATION_MARKER.sub("", text))
    return _ELISION.sub("", text).strip().split()


def _fold_case(word: str) -> str:
    return word.casefold()


def _fold_punctuation(word: str) -> str:
    return word.strip(string.punctuation)


def _fold_markup(word: str) -> str:
    return word.strip(_MARKUP)


def _fold_all(word: str) -> str:
    return _fold_punctuation(_fold_markup(word.casefold()))


#: Ways a quote can be right about the words and wrong about the writing.
#: Ordered from most specific to least, so the narrowest true statement wins
#: — markup before punctuation, because `string.punctuation` contains the
#: markup characters and would otherwise claim every backtick as a comma.
_TYPOGRAPHY = [
    ("differs only in case", _fold_case),
    ("differs only in inline markup (backticks, emphasis)", _fold_markup),
    ("differs only in punctuation", _fold_punctuation),
    ("differs only in case, punctuation or markup", _fold_all),
]


def _sublist_index(haystack: list[str], needle: list[str]) -> int:
    """Index of ``needle`` within ``haystack``, or -1. Whole words only."""
    if not needle or len(needle) > len(haystack):
        return -1
    first = needle[0]
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i] == first and haystack[i:i + len(needle)] == needle:
            return i
    return -1


def _typographic_difference(snippet: list[str],
                            source: list[str]) -> tuple[str, list[str]] | None:
    """Name the difference when the quote's words are all present.

    Each candidate must be a *whole-word* match — folding across word
    boundaries would let "the rat elimiter" claim to be "the rate limiter",
    which is not a typo but a different sentence. And each must describe a
    difference that actually exists: a passage identical to the snippet is
    not a case difference.
    """
    for kind, fold in _TYPOGRAPHY:
        at = _sublist_index([fold(w) for w in source],
                            [fold(w) for w in snippet])
        if at < 0:
            continue
        found = source[at:at + len(snippet)]
        if found == snippet:
            # Identical. Whatever failed, it was not typography.
            return None
        return kind, found
    return None


def closest_match(snippet: str, source: str) -> Diagnosis | None:
    """Find the passage of ``source`` that best matches ``snippet``.

    Returns None when nothing is close enough to be worth showing. Saying
    nothing beats inventing a diagnosis for a quote that was never there.
    """
    snippet_words = _words(snippet)
    source_words = _words(source)
    if not snippet_words or not source_words:
        return None

    typographic = _typographic_difference(snippet_words, source_words)
    if typographic is not None:
        kind, found = typographic
        return Diagnosis(source_text=" ".join(found), ratio=1.0, kind=kind)

    best = _best_window(snippet_words, source_words)
    if best is None:
        return None

    missing, extra = _word_delta(snippet_words, best)
    return Diagnosis(
        source_text=" ".join(best),
        ratio=_ratio(snippet_words, best),
        missing=missing,
        extra=extra,
    )


def _ratio(snippet: list[str], window: list[str]) -> float:
    return SequenceMatcher(None, _keys(snippet), _keys(window)).ratio()


def _keys(words: list[str]) -> list[str]:
    """Compare words by what they say, not by how they are punctuated."""
    return [_fold_all(w) for w in words]


def _best_window(snippet: list[str], source: list[str]) -> list[str] | None:
    """Scan the source for the run of words closest to the snippet.

    ``quick_ratio`` is an upper bound on ``ratio`` and far cheaper, so it
    screens every window and only the best few are scored properly.

    The source is folded **once**, up front, and the windows are slices of the
    folded array. Folding each window instead meant every word of the document
    was folded about four times over (the windows are ``width`` wide and step
    ``width // 4``), which on a long document is most of the work this function
    does. Slicing is equivalent because ``_fold_all`` is positionwise — it reads
    one word and knows nothing of its neighbours — so the fold of a slice and a
    slice of the fold are the same list.
    """
    width = len(snippet)
    step = max(1, width // 4)

    source_keys = _keys(source)

    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(_keys(snippet))

    scored: list[tuple[float, int]] = []
    for start in range(0, max(1, len(source) - width + 1), step):
        matcher.set_seq1(source_keys[start:start + width])
        scored.append((matcher.quick_ratio(), start))

    scored.sort(key=lambda pair: -pair[0])

    # Windows are cut at fixed offsets, so the passage almost never sits
    # neatly inside one — and the source's version of the quote may simply
    # be longer than the quote (that is the commonest failure: something was
    # left out). Pad generously, then trim back to what actually matched, so
    # a word falling outside a cut is never reported missing from the source.
    pad = max(4, width // 2)

    # Score the padded window, not the trimmed quote. Trimming cuts away
    # whatever failed to match, so a short span that matches a fragment of
    # the snippet would score higher than the longer passage that is
    # actually the source's version of it.
    best: list[str] | None = None
    best_ratio = 0.0
    for _, start in scored[:5]:
        window = source[max(0, start - pad):start + width + pad]
        ratio = _ratio(snippet, window)
        if ratio > best_ratio:
            best, best_ratio = window, ratio

    if best is None:
        return None

    quote = _trim_to_quote(snippet, best)
    if _ratio(snippet, quote) < MIN_SIMILARITY:
        return None
    return quote


def _trim_to_quote(snippet: list[str], window: list[str]) -> list[str]:
    """Cut the surrounding context back off the passage.

    The window is deliberately padded so the whole quote lands inside it.
    That padding did its job during matching; showing it would just make
    the reader hunt for where the quote actually starts.
    """
    matcher = SequenceMatcher(None, _keys(snippet), _keys(window),
                              autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size]
    if not blocks:
        return window

    start = blocks[0].b
    end = blocks[-1].b + blocks[-1].size
    return window[start:end]


def _word_delta(snippet: list[str],
                window: list[str]) -> tuple[list[str], list[str]]:
    """Which words the citation and the passage disagree about.

    Compared by their folded form, so a word the source merely punctuates
    differently is not reported as absent from it — the citation says
    ``URI`` and the source says ``URI.``; the word is there.
    """
    matcher = SequenceMatcher(None, _keys(snippet), _keys(window),
                              autojunk=False)

    missing = []
    extra = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            missing.extend(snippet[i1:i2])
        if tag in ("replace", "insert"):
            extra.extend(window[j1:j2])

    # A word that turns up in *both* lists has not gone missing and has not been
    # added: it has moved. Reporting it twice made the diagnosis contradict
    # itself in adjacent lines —
    #
    #     the passage does not have: entity-header
    #     the passage also has:      entity-header
    #
    # — with the word plainly visible in the passage printed above them. Cancel
    # the pairs off; what survives is the real disagreement.
    shared = Counter(_keys(missing)) & Counter(_keys(extra))
    return _drop(missing, Counter(shared)), _drop(extra, Counter(shared))


def _drop(words: list[str], budget: Counter) -> list[str]:
    """Remove up to ``budget`` occurrences of each word, by folded form."""
    kept = []
    for word in words:
        key = _fold_all(word)
        if budget[key]:
            budget[key] -= 1
            continue
        kept.append(word)
    return kept


def _elide(text: str) -> str:
    """Cut a passage to a readable length. Rendering only — the diagnosis
    keeps the whole passage, so a machine-readable report gets all of it."""
    words = text.split()
    if len(words) <= MAX_RENDERED_WORDS:
        return text
    return " ".join(words[:MAX_RENDERED_WORDS]) + " ..."


def render(diagnosis: Diagnosis) -> list[str]:
    """Render a diagnosis as report lines."""
    where = diagnosis.where
    location = f", {where}" if where else ""

    if diagnosis.kind:
        # The words are right; only the writing is wrong. A word diff would
        # relist the whole sentence, so show what to paste instead.
        return [
            f"snippet {diagnosis.kind}{location}",
            f"  source says: {_elide(diagnosis.source_text)}",
        ]

    lines = [f"closest match ({diagnosis.percent}% similar{location})",
             f"  source says: {_elide(diagnosis.source_text)}"]

    # "not in the source" was a claim the diagnosis had no right to make. The
    # diff is against the *closest passage*, not against the document, and a word
    # missing from that passage is very often present elsewhere: `cacheable`
    # occurs 33 times in RFC 2616, and the report said it was not in the source
    # — sending the author hunting for a word already in front of them, which is
    # the exact failure this module was written to end.
    if diagnosis.missing:
        lines.append(
            f"  not in that passage: {_elide(' '.join(diagnosis.missing))}")
    if diagnosis.extra:
        lines.append(
            f"  that passage also has: {_elide(' '.join(diagnosis.extra))}")
    return lines


def diagnose(snippet: str, source: str, where: str = "") -> Diagnosis | None:
    """Diagnose a failed snippet. None when nothing in the source is close.

    ``where`` names the region searched (a section selector), when known.
    """
    diagnosis = closest_match(snippet, source)
    if diagnosis is not None:
        diagnosis.where = where
    return diagnosis


def explain_snippet_failure(snippet: str, source: str,
                            where: str = "") -> list[str]:
    """Explain a failed snippet, as report lines. Empty if nothing is close."""
    diagnosis = diagnose(snippet, source, where)
    if diagnosis is None:
        return []
    return render(diagnosis)
