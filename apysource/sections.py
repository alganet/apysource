# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Human-readable section selectors for document navigation.

sourceSection is a universal, human-readable selector format that works
across HTML, Markdown, and Wikitext.  It replaces verbose CSS selectors
with readable strings like ``Preamble, paragraph 1``.

Syntax
------
- ``§ 4.1``             — numbered section (matches title starting with "4.1")
- ``Chapter 4``         — section by title (roman↔int normalisation)
- ``paragraph 3``       — Nth paragraph in current scope
- ``Preamble, paragraph 1`` — section then paragraph
- ``'Lost, forever...', Section 2`` — quoted literal title
"""

import re
from dataclasses import dataclass, field

from apysource.formats import LocateResult, _normalize

# ── Roman numeral utilities ───────────────────────────────────────────

_ROMAN_MAP = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def roman_to_int(s: str) -> int | None:
    """Convert a Roman numeral string to an integer."""
    s = s.upper().strip()
    if not s:
        return None
    result = 0
    i = 0
    for value, numeral in _ROMAN_MAP:
        while s[i:i + len(numeral)] == numeral:
            result += value
            i += len(numeral)
    return result if i == len(s) and result > 0 else None


def int_to_roman(n: int) -> str:
    """Convert an integer to a Roman numeral string."""
    parts: list[str] = []
    for value, numeral in _ROMAN_MAP:
        while n >= value:
            parts.append(numeral)
            n -= value
    return "".join(parts)


# ── Section tree ──────────────────────────────────────────────────────

@dataclass
class SectionNode:
    """A node in the document section tree."""

    title: str = ""
    level: int = 0
    paragraphs: list[str] = field(default_factory=list)
    children: list["SectionNode"] = field(default_factory=list)
    start_offset: int = 0
    end_offset: int = 0

    def all_text(self) -> str:
        """Return all text in this section and its children."""
        parts = list(self.paragraphs)
        for child in self.children:
            parts.append(child.all_text())
        return "\n\n".join(p for p in parts if p)


# ── Selector parsing ─────────────────────────────────────────────────

@dataclass
class SectionPart:
    """A parsed component of a sourceSection selector."""

    kind: str        # "numbered" (§), "heading" (uppercase), "paragraph" (lowercase)
    value: str       # raw text: "Chapter 4", "paragraph 3", "§ 4.1"
    ordinal: int | None = None  # extracted number if present


def parse_selector(selector: str) -> list[SectionPart]:
    """Parse a comma-separated sourceSection selector into parts.

    Respects single-quoted segments so commas inside quotes are preserved.
    """
    parts: list[SectionPart] = []
    raw_parts = _split_selector(selector)

    for raw in raw_parts:
        raw = raw.strip()
        if not raw:
            continue

        # Quoted literal title
        if raw.startswith("'") and raw.endswith("'") and len(raw) > 1:
            parts.append(SectionPart(kind="heading", value=raw[1:-1]))
            continue

        # § numbered section
        if raw.startswith("§"):
            num_str = raw[1:].strip()
            parts.append(SectionPart(kind="numbered", value=num_str))
            continue

        # Lowercase start → element ordinal (paragraph N)
        if raw[0].islower():
            match = re.search(r"(\d+)", raw)
            ordinal = int(match.group(1)) if match else None
            parts.append(SectionPart(kind="paragraph", value=raw, ordinal=ordinal))
            continue

        # Uppercase start → heading/section title
        match = re.search(r"(\d+|[IVXLCDM]+)\s*$", raw)
        ordinal = None
        if match:
            num_text = match.group(1)
            if num_text.isdigit():
                ordinal = int(num_text)
            else:
                ordinal = roman_to_int(num_text)
        parts.append(SectionPart(kind="heading", value=raw, ordinal=ordinal))

    return parts


def _split_selector(selector: str) -> list[str]:
    """Split selector on commas, respecting single-quoted segments."""
    parts: list[str] = []
    current: list[str] = []
    in_quote = False

    for char in selector:
        if char == "'" :
            in_quote = not in_quote
            current.append(char)
        elif char == "," and not in_quote:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append("".join(current))
    return parts


# ── Section matching ──────────────────────────────────────────────────


def _extract_title_number(title: str) -> int | None:
    """Extract a trailing number (integer or roman) from a section title."""
    match = re.search(r"(\d+|[IVXLCDM]+)\s*$", title.strip())
    if not match:
        return None
    num_text = match.group(1)
    if num_text.isdigit():
        return int(num_text)
    return roman_to_int(num_text)


def _title_prefix_number(title: str) -> str | None:
    """Extract a leading dotted number prefix like '4.1' from a title."""
    match = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    return match.group(1) if match else None


def match_section(node: SectionNode, part: SectionPart) -> bool:
    """Check if a SectionNode matches a SectionPart selector."""
    if part.kind == "numbered":
        # § 4.1 — match title starting with that number prefix
        prefix = _title_prefix_number(node.title)
        if prefix and prefix == part.value:
            return True
        # Also match if the number appears as the title prefix
        return _normalize(node.title).startswith(part.value)

    if part.kind == "heading":
        norm_title = _normalize(node.title)
        norm_value = _normalize(part.value)

        # Exact match (case-insensitive)
        if norm_title.lower() == norm_value.lower():
            return True

        # Roman ↔ integer equivalence
        if part.ordinal is not None:
            title_num = _extract_title_number(node.title)
            if title_num is not None and title_num == part.ordinal:
                # Check that the non-numeric prefix matches
                value_prefix = re.sub(
                    r"\s*(\d+|[IVXLCDM]+)\s*$", "", norm_value).strip().lower()
                title_prefix = re.sub(
                    r"\s*(\d+|[IVXLCDM]+)\s*$", "", norm_title).strip().lower()
                if value_prefix == title_prefix:
                    return True

        return False

    # paragraph kind is handled separately by ordinal, not by title match
    return False


def _find_matching_child(node: SectionNode, part: SectionPart) -> SectionNode | None:
    """Find the first child of node that matches the given part.

    Searches the entire subtree — ``Preamble`` or ``§ 2.1`` finds the
    matching section even if it's nested under a wrapper heading.
    """
    for child in node.children:
        if match_section(child, part):
            return child
    for child in node.children:
        result = _find_matching_child(child, part)
        if result is not None:
            return result
    return None


# ── Extraction ────────────────────────────────────────────────────────

#: How many candidate sections to offer. Enough to recognize the one you meant,
#: few enough to read.
MAX_CANDIDATES = 6


class SectionNotFound(LookupError):
    """The document has no such section.

    A section that is not there used to extract the empty string, which the
    report could only describe as ``empty extraction (0 chars)`` — the same
    thing it says about a document that really is empty, and about one that
    failed to download. A typo'd section number and a dead source read
    identically.

    ``candidates`` are sections that **do** exist in the document, so the
    message can say what you might have meant. They are never invented: a
    suggestion is a claim about the source, and suggesting a section the
    document does not have would be the same lie in new clothes.
    """

    def __init__(self, selector: str, candidates: list[str] | None = None,
                 available: int = 0, detail: str = "") -> None:
        self.selector = selector
        self.candidates = candidates or []
        self.available = available
        self.detail = detail
        super().__init__(self.message)

    @property
    def message(self) -> str:
        if self.detail:
            return self.detail
        head = f'no section matches "{self.selector}"'
        if self.candidates:
            return f"{head}; did you mean {', '.join(self.candidates)}?"
        if self.available:
            return f"{head}; the document has {self.available} sections, none like it"
        return f"{head}; the document has no sections at all"


def section_labels(node: SectionNode) -> list[str]:
    """Every selector label in this subtree, in document order.

    Rendered through ``_section_label``, so each one can be pasted straight
    back into ``section:`` — a suggestion you cannot use is barely a suggestion.
    """
    out: list[str] = []
    for child in node.children:
        label = _section_label(child)
        if label:
            out.append(label)
        out.extend(section_labels(child))
    return out


def _dotted(label: str) -> tuple[int, ...] | None:
    """"§ 7.2" -> (7, 2). Anything not a dotted number -> None."""
    text = label[1:].strip() if label.startswith("§") else label
    if not re.fullmatch(r"\d+(\.\d+)*", text.strip()):
        return None
    return tuple(int(n) for n in text.strip().split("."))


def _shared_prefix(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """How many leading components two section numbers agree on."""
    count = 0
    for x, y in zip(a, b):
        if x != y:
            break
        count += 1
    return count


def _candidates_for(node: SectionNode, part: SectionPart) -> tuple[list[str], int]:
    """Sections under ``node`` that come closest to the part that missed.

    Numbered sections are ranked by *where they live*, not by how their text
    looks. String similarity answers "§ 1.5" with "§ 19.5" — which shares a lot
    of characters and no meaning at all. The section you actually meant is
    almost always a sibling, so a shared dotted prefix outranks everything, and
    similarity only breaks the ties.
    """
    from difflib import SequenceMatcher, get_close_matches

    from apysource.diagnostics import MIN_SIMILARITY

    labels = section_labels(node)
    if not labels:
        return [], 0

    if part.kind != "numbered":
        return get_close_matches(part.value, labels, n=MAX_CANDIDATES,
                                 cutoff=MIN_SIMILARITY), len(labels)

    query = f"§ {part.value}"
    wanted = _dotted(query)
    if wanted is None:
        return get_close_matches(query, labels, n=MAX_CANDIDATES,
                                 cutoff=MIN_SIMILARITY), len(labels)

    scored: list[tuple[int, float, str]] = []
    for label in labels:
        number = _dotted(label)
        if number is None:
            continue
        shared = _shared_prefix(wanted, number)
        ratio = SequenceMatcher(None, query, label).ratio()
        # A sibling always qualifies; a stranger has to look like the target.
        if shared or ratio >= MIN_SIMILARITY:
            scored.append((shared, ratio, label))

    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [label for _, _, label in scored[:MAX_CANDIDATES]], len(labels)


def extract_by_selector(root: SectionNode, selector: str, *,
                        strict: bool = False) -> str:
    """Walk the section tree and extract text matching a sourceSection selector.

    ``strict`` raises SectionNotFound instead of returning "" when nothing
    matches. It is off by default because ``simplify_selector`` uses this to
    *probe* candidate selectors, and relies on "" meaning "that one found
    nothing" — the verification path opts in, the search path does not.
    """
    parts = parse_selector(selector)
    if not parts:
        return root.all_text()

    current = root

    for part in parts:
        if part.kind == "paragraph":
            # Return the Nth non-empty paragraph from the current section
            non_empty = [p for p in current.paragraphs if p.strip()]
            if part.ordinal is not None:
                idx = part.ordinal - 1
                if 0 <= idx < len(non_empty):
                    return non_empty[idx]
            if strict:
                where = _section_label(current) or "the document"
                raise SectionNotFound(
                    selector,
                    detail=f'no {part.value} in {where}; it has '
                           f'{len(non_empty)} paragraphs',
                )
            return ""

        child = _find_matching_child(current, part)
        if child is None:
            if strict:
                candidates, available = _candidates_for(current, part)
                raise SectionNotFound(selector, candidates, available)
            return ""
        current = child

    return current.all_text()


def extract_section(body: str, selector: str, fmt, *,
                    strict: bool = False) -> str:
    """High-level: build section tree from body, extract by selector."""
    if not hasattr(fmt, "sections"):
        if strict:
            # Plain text has no headings to target. Saying "empty extraction"
            # blamed the selector for a document that never had sections.
            raise SectionNotFound(
                selector,
                detail=f'cannot target "{selector}": this document has no '
                       f"section structure ({fmt.name}); use a line range",
            )
        return ""
    root = fmt.sections(body)
    return extract_by_selector(root, selector, strict=strict)


# ── Location (generate selector from snippet) ────────────────────────

def _find_snippet_path(node: SectionNode, snippet: str,
                       path: list[SectionNode]) -> list[SectionNode] | None:
    """Find the deepest section containing the snippet, return path from root."""
    norm_snippet = _normalize(snippet)

    # Check children first (prefer deeper matches)
    for child in node.children:
        result = _find_snippet_path(child, snippet, path + [child])
        if result is not None:
            return result

    # Check this node's own paragraphs
    for para in node.paragraphs:
        if norm_snippet in _normalize(para):
            return path

    return None


def _paragraph_index(node: SectionNode, snippet: str) -> int | None:
    """Find which paragraph (1-based) contains the snippet."""
    norm_snippet = _normalize(snippet)
    idx = 0
    for para in node.paragraphs:
        if not para.strip():
            continue
        idx += 1
        if norm_snippet in _normalize(para):
            return idx
    return None


def _section_label(node: SectionNode) -> str:
    """Generate a selector label for a section node."""
    title = node.title.strip()
    if not title:
        return ""

    # If the title starts with a dotted number, use § prefix with just the number
    prefix = _title_prefix_number(title)
    if prefix:
        return f"§ {prefix}"

    # If the title contains commas, quote it
    if "," in title:
        return f"'{title}'"

    return title


def generate_selector(root: SectionNode, snippet: str) -> str | None:
    """Find a snippet in the section tree and build a human-readable selector."""
    path = _find_snippet_path(root, snippet, [])
    if path is None:
        return None

    # The last node in the path is where the snippet lives
    target = path[-1] if path else root

    # Build section parts of the selector, collapsing redundant § prefixes.
    # § 1.4 already implies § 1, so skip numbered parents when a numbered
    # child encodes the full hierarchy.
    raw_labels = [_section_label(node) for node in path]
    labels = []
    for i, label in enumerate(raw_labels):
        if not label:
            continue
        # Skip this § label if a later § label's number is a sub-path
        if label.startswith("§ "):
            parent_num = label[2:]
            skip = False
            for later in raw_labels[i + 1:]:
                if later.startswith("§ ") and later[2:].startswith(parent_num):
                    skip = True
                    break
            if skip:
                continue
        labels.append(label)

    # Find which paragraph it's in
    para_idx = _paragraph_index(target, snippet)
    if para_idx is not None:
        labels.append(f"paragraph {para_idx}")

    if not labels:
        return None

    return ", ".join(labels)


def simplify_selector(root: SectionNode, selector: str, snippet: str) -> str:
    """Find the shortest selector that still extracts text containing the snippet.

    Tries ancestor labels and suffixes of the full selector, picks the shortest.
    Skips the root-level title (too broad to be useful).
    """
    norm_snippet = _normalize(snippet)
    candidates = []

    # Strategy 1: try each non-root ancestor as a standalone selector
    path = _find_snippet_path(root, snippet, [])
    if path and len(path) > 1:
        target = path[-1]
        para_idx = _paragraph_index(target, snippet)
        para_suffix = f", paragraph {para_idx}" if para_idx else ""

        # Skip path[0] (root-level title, too broad)
        for node in path[1:]:
            label = _section_label(node)
            if not label:
                continue
            for suffix in ([para_suffix, ""] if para_suffix else [""]):
                candidate = label + suffix
                text = extract_by_selector(root, candidate)
                if text and norm_snippet in _normalize(text):
                    candidates.append(candidate)

    # Strategy 2: try suffixes of the full selector (skip the full thing)
    parts = [p.strip() for p in selector.split(",")]
    for start in range(len(parts) - 1, 0, -1):
        candidate = ", ".join(parts[start:])
        text = extract_by_selector(root, candidate)
        if text and norm_snippet in _normalize(text):
            candidates.append(candidate)

    if candidates:
        return min(candidates, key=len)

    return selector


def locate_section(body: str, snippet: str, fmt) -> LocateResult | None:
    """High-level: build section tree, generate a sourceSection selector."""
    if not hasattr(fmt, "sections"):
        return None

    root = fmt.sections(body)
    if not root.children:
        return None

    selector = generate_selector(root, snippet)
    if selector is None:
        return None

    selector = simplify_selector(root, selector, snippet)

    return LocateResult(
        format_name="section",
        locator=selector,
        matched_text=_normalize(snippet),
    )
