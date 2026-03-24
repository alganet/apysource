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

def extract_by_selector(root: SectionNode, selector: str) -> str:
    """Walk the section tree and extract text matching a sourceSection selector."""
    parts = parse_selector(selector)
    if not parts:
        return root.all_text()

    current = root

    for part in parts:
        if part.kind == "paragraph":
            # Return the Nth non-empty paragraph from the current section
            if part.ordinal is not None:
                non_empty = [p for p in current.paragraphs if p.strip()]
                idx = part.ordinal - 1
                if 0 <= idx < len(non_empty):
                    return non_empty[idx]
            return ""

        child = _find_matching_child(current, part)
        if child is None:
            return ""
        current = child

    return current.all_text()


def extract_section(body: str, selector: str, fmt) -> str:
    """High-level: build section tree from body, extract by selector."""
    if not hasattr(fmt, "sections"):
        return ""
    root = fmt.sections(body)
    return extract_by_selector(root, selector)


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
