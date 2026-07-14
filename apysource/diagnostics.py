# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Explain why a snippet did not match.

A quote either appears in the source or it does not, and saying only that
leaves the reader to fetch the document and diff it by hand — which is the
authoring loop, run blind. When a snippet fails, the source almost always
contains something very close to it: a dropped parenthetical, a changed
case, a stray backtick that survived rendering. Find that passage and show
what differs.

Everything here runs only on failure, so it can afford to be thorough.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Below this similarity, the closest passage is not worth showing — the
#: snippet is unrelated to the text, not a near-miss in it.
MIN_SIMILARITY = 0.5

#: get_text() truncates long extractions and appends this marker. It is not
#: part of the document and must never surface inside a diff.
_TRUNCATION_MARKER = re.compile(r"\n?\.\.\. \[\d+ more chars\]\s*$")


@dataclass
class Match:
    """The passage in the source that comes closest to the snippet."""

    text: str
    ratio: float
    #: A plain-language summary when the difference is entirely mechanical
    #: ("differs only in case"), else "".
    kind: str = ""

    @property
    def percent(self) -> int:
        return round(self.ratio * 100)


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs to single spaces and trim."""
    return re.sub(r"\s+", " ", text).strip()


def strip_truncation_marker(text: str) -> str:
    """Remove the "... [N more chars]" tail get_text() may have appended."""
    return _TRUNCATION_MARKER.sub("", text)


def closest_match(snippet: str, source: str) -> Match | None:
    """Find the passage of ``source`` that best matches ``snippet``.

    Scans windows of roughly the snippet's length. ``quick_ratio`` is an
    upper bound on ``ratio`` and far cheaper, so it screens the windows and
    only the best few are scored properly.

    Returns None when nothing is close enough to be worth showing.
    """
    snippet = _normalize_ws(snippet)
    source = _normalize_ws(strip_truncation_marker(source))
    if not snippet or not source:
        return None

    mechanical = _mechanical_difference(snippet, source)
    if mechanical is not None:
        kind, exact = mechanical
        if exact:
            return Match(text=exact, ratio=1.0, kind=kind)
    else:
        kind = ""

    width = len(snippet)
    step = max(1, width // 4)
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(snippet)

    scored = []
    for start in range(0, max(1, len(source) - width + 1), step):
        window = source[start:start + width + width // 4]
        matcher.set_seq1(window)
        scored.append((matcher.quick_ratio(), window))

    scored.sort(key=lambda pair: -pair[0])

    best = None
    for _, window in scored[:5]:
        matcher.set_seq1(window)
        ratio = matcher.ratio()
        if best is None or ratio > best.ratio:
            best = Match(text=window, ratio=ratio, kind=kind)

    if best is None or best.ratio < MIN_SIMILARITY:
        return None

    best.text = _widen_to_words(source, best.text, width)
    return best


def _widen_to_words(source: str, window: str, width: int) -> str:
    """Grow a window to whole words, with slack on each side.

    Windows are cut at fixed offsets, so the passage that matches rarely
    sits neatly inside one — a word of the snippet can fall just outside
    the cut. Without slack the diff would then report that word as missing
    from the source, which is a lie: it is missing from the *window*. Pad
    first, and let the diff drop whatever context it does not need.
    """
    start = source.find(window)
    if start < 0:
        return window
    end = start + len(window)

    slack = max(8, width // 3)
    start = max(0, start - slack)
    end = min(len(source), end + slack)

    while start > 0 and not source[start - 1].isspace():
        start -= 1
    while end < len(source) and not source[end - 1].isspace():
        end += 1

    return source[start:end].strip()


def _mechanical_difference(snippet: str, source: str) -> tuple[str, str] | None:
    """Name the difference when the snippet is present but for spelling.

    These are the near-misses worth naming rather than diffing: the author
    has the words right and the typography wrong, and a word-level diff
    renders that as noise. Returns the kind and, where it can be recovered,
    the source's exact wording — which is the thing to paste.
    """
    lowered = source.lower()
    at = lowered.find(snippet.lower())
    if at >= 0:
        return "differs only in case", source[at:at + len(snippet)]

    squashed_snippet = re.sub(r"\s+", "", snippet)
    squashed_source = re.sub(r"\s+", "", source)
    if squashed_snippet and squashed_snippet in squashed_source:
        return "differs only in whitespace", ""

    stripped_snippet = _strip_inline_markup(snippet)
    stripped_source = _strip_inline_markup(source)
    if stripped_snippet and stripped_snippet in stripped_source:
        return "differs only in inline markup (backticks, emphasis)", ""

    return None


def _strip_inline_markup(text: str) -> str:
    """Drop the markup characters that survive into rendered-ish text."""
    return re.sub(r"[`*_]", "", text)


def describe_difference(snippet: str, candidate: str) -> list[str]:
    """Render a word-level diff of the snippet against the found passage.

    ``-`` is what the citation claims; ``+`` is what the source says.
    """
    expected = _normalize_ws(snippet).split()
    actual = _normalize_ws(candidate).split()

    matcher = SequenceMatcher(None, expected, actual, autojunk=False)
    opcodes = matcher.get_opcodes()

    # The passage carries context on either side of the cited span. Words
    # the source has *around* the quote are not a discrepancy in it, so
    # drop a leading and trailing run of pure insertions.
    while opcodes and opcodes[0][0] == "insert":
        opcodes = opcodes[1:]
    while opcodes and opcodes[-1][0] == "insert":
        opcodes = opcodes[:-1]

    missing = []
    extra = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("replace", "delete"):
            missing.extend(expected[i1:i2])
        if tag in ("replace", "insert"):
            extra.extend(actual[j1:j2])

    lines = [f"  - {' '.join(expected)}", f"  + {' '.join(actual)}"]
    if missing:
        lines.append(f"    missing from source: {' '.join(missing)}")
    if extra:
        lines.append(f"    present in source:   {' '.join(extra)}")
    return lines


def explain_snippet_failure(snippet: str, source: str,
                            where: str = "") -> list[str]:
    """Explain a failed snippet, as report lines. Empty if nothing is close.

    ``where`` names the region searched (a section selector), when known.
    """
    match = closest_match(snippet, source)
    if match is None:
        return []

    location = f", {where}" if where else ""

    if match.kind:
        # The words are right; only the typography is wrong. A word diff
        # would just relist the whole sentence, so show what to paste.
        return [
            f"snippet {match.kind}{location}",
            f"  source says: {match.text}",
        ]

    return [
        f"closest match ({match.percent}% similar{location})",
        *describe_difference(snippet, match.text),
    ]
