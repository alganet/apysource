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


#: The one element ordinal the grammar has: ``paragraph 3``.
_PARAGRAPH_RE = re.compile(r"^(?:paragraph|para)\s+(\d+)$", re.IGNORECASE)


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

        # Paragraph ordinal — spelled out, because it is the only element
        # ordinal the grammar has and the only one `generate_selector` emits.
        #
        # This used to be "starts with a lowercase letter", which quietly ate
        # every lowercase *heading*: `document.domain`, `fetch()`, `http2 push`
        # — the house style of exactly the documents this targets. Worse, it
        # then dug a number out of the title with `re.search(r"(\d+)")`, so
        # `http2 push` meant *paragraph 2*, and a citation `add` had written
        # itself was verified against an unrelated paragraph, silently. Also why
        # `Section 7` worked and `section 7` did not.
        match = _PARAGRAPH_RE.match(raw)
        if match:
            parts.append(SectionPart(kind="paragraph", value=raw,
                                     ordinal=int(match.group(1))))
            continue

        # Anything else → heading/section title
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
    """Extract a leading section designator like '4.1' — or an appendix's 'A' / 'A.1'.

    An appendix heading is built as ``A. Pseudocode`` / ``A.1. Sample`` (a letter, an
    optional dotted number, then the ``. `` the builder always inserts), so the
    letter form is admitted **only when a period follows** it. That lookahead is what
    keeps a plain heading such as ``Terminology`` from reporting a designator of ``T``.
    """
    match = re.match(r"^(\d+(?:\.\d+)*|[A-Z](?:\.\d+)*(?=\.))", title.strip())
    return match.group(1) if match else None


def match_section(node: SectionNode, part: SectionPart) -> bool:
    """Check if a SectionNode matches a SectionPart selector."""
    if part.kind == "numbered":
        # § 4.1 — the section *numbered* 4.1, compared as a number and not as
        # the characters it happens to be spelled with.
        #
        # This fell back to `node.title.startswith(part.value)`, a string test:
        # "50. Security Considerations".startswith("5") is true, so `§ 5` in a
        # document with no section 5 returned section 50's text — and because a
        # match was *found*, strict mode never fired and nothing was reported.
        # On RFC 2616, which has no § 13.1 heading, `§ 13.1` silently returned
        # § 13.1.1, so a real quote from § 13.1.4 was declared absent from a
        # document that contains it. Both lies the tool exists to prevent, from
        # one line.
        #
        # An empty value ("§" with no number) names no section at all.
        if not part.value:
            return False
        return _title_prefix_number(node.title) == part.value

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
        # A selector that parses to nothing — "§", ",", "   " — used to return
        # `root.all_text()`: the *entire document*, offered as though it were the
        # section that was asked for. Section scoping silently evaporated and
        # every quote in the document passed. A selector we cannot understand is
        # a miss, and never a licence to check against everything.
        if strict:
            raise SectionNotFound(
                selector, [], len(section_labels(root)),
                detail=f'cannot understand the section selector "{selector}"',
            )
        return ""

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


def sections_containing(root: SectionNode, snippet: str) -> list[SectionNode]:
    """Every section that contains this passage — usually one, sometimes not.

    A specification repeats itself: "The response MUST include the following
    header fields:" appears verbatim under both § 10.2.7 (206 Partial Content)
    and § 10.3.5 (304 Not Modified) of RFC 2616. ``locate`` can only pick one,
    and picking silently is a quiet claim that the passage lives *there* —
    a citation which would go on passing even after the passage was deleted from
    the section its author actually meant, because it survives in the other.

    Only the deepest section on each branch is reported: every ancestor contains
    the passage too, and saying so would be noise rather than ambiguity.
    """
    norm = _normalize(snippet)
    found: list[SectionNode] = []

    def visit(node: SectionNode) -> None:
        deeper = False
        for child in node.children:
            if norm in _normalize(child.all_text()):
                deeper = True
                visit(child)
        if not deeper and node is not root and norm in _normalize(node.all_text()):
            found.append(node)

    visit(root)
    return found


def resolve_selector(root: SectionNode, selector: str) -> SectionNode | None:
    """The section a selector names, or None if it names none.

    A trailing ``paragraph N`` narrows *within* a section rather than choosing a
    different one, so the section it lands in is the answer.
    """
    parts = parse_selector(selector)
    if not parts:
        return None

    current = root
    for part in parts:
        if part.kind == "paragraph":
            return current
        child = _find_matching_child(current, part)
        if child is None:
            return None
        current = child
    return current


def simplify_selector(root: SectionNode, selector: str, snippet: str) -> str:
    """The shortest selector that names *the passage's own section*.

    The objective used to be "the shortest selector that extracts text
    containing the snippet", and that quietly guaranteed the wrong answer: a
    section always contains its subsections' text, and its label is always
    shorter. So a passage living in § 4.2.1 was cited as § 4.2 — never wrong
    enough to fail a round-trip, and never right. On RFC 9110 that happened to
    **157 of 271** paragraphs.

    It matters twice over. The citation is less precise than the author's own
    source (and lint-http's rules cite exact subsections); and the scope it
    checks against is the whole parent, so a quote drifting between § 4.2.1 and
    § 4.2.5 would still verify — the very rot section targeting exists to catch.

    Naming the target also disambiguates for free: where two sections share a
    title, the bare title resolves to the first, so it is *rejected* here and the
    ancestor path that does reach the right one is used instead.
    """
    norm_snippet = _normalize(snippet)

    path = _find_snippet_path(root, snippet, [])
    if not path:
        return selector

    target = path[-1]
    para_idx = _paragraph_index(target, snippet)
    para_suffix = f", paragraph {para_idx}" if para_idx else ""

    # Suffixes of the path from root to the passage: the shortest that still
    # lands on the passage's own section wins. "§ 4.2.1" beats
    # "§ 4, § 4.2, § 4.2.1"; "§ 4.2" is not a candidate at all, because it names
    # a different section.
    candidates = []
    for start in range(len(path)):
        labels = [_section_label(node) for node in path[start:]]
        if not all(labels):
            continue
        base = ", ".join(labels)
        for suffix in ([para_suffix, ""] if para_suffix else [""]):
            candidate = base + suffix
            if resolve_selector(root, candidate) is not target:
                continue
            text = extract_by_selector(root, candidate)
            if text and norm_snippet in _normalize(text):
                candidates.append(candidate)

    if candidates:
        return min(candidates, key=len)

    return selector


#: `#section-7.2` — the rfc-editor convention, and unambiguous wherever it appears.
_ANCHOR_SECTION_RE = re.compile(r"^(?:section|sec)-(\d+(?:\.\d+)*)$", re.IGNORECASE)


def anchor_slug(title: str) -> str:
    """A heading's title reduced to the anchor a renderer would give it."""
    slug = _normalize(title).lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def selector_for_title(title: str) -> str | None:
    """A selector that names this heading, or None if the grammar cannot.

    Prefers the section number, which is short and unambiguous. Falls back to
    the literal title, quoted when it contains a comma — and gives up rather
    than emit something that would parse as a different selector than intended.
    """
    number = _title_prefix_number(title)
    if number:
        return f"§ {number}"
    if "'" in title:
        return None if "," in title else title
    return f"'{title}'" if "," in title else title


def _headings(node: SectionNode) -> list[SectionNode]:
    out: list[SectionNode] = []
    for child in node.children:
        out.append(child)
        out.extend(_headings(child))
    return out


def selector_for_anchor(body: str, anchor: str, fmt) -> str | None:
    """The section a URL fragment points at, or None to leave the scope alone.

    An anchor is targeting the author already wrote down, and until now nothing
    read it: `rfc9110.html#section-7.2` was checked against the whole of RFC 9110.

    Two ways it is understood, and one firm refusal:

    * ``#section-7.2`` — the rfc-editor convention, and unambiguous. It is taken
      at its word, so a section that is not there *fails*, rather than quietly
      widening back to the whole document and passing.
    * any other anchor — looked up **in the document**. If it names a heading,
      that heading's section is the scope.
    * anything else — **declined**. In the Fetch spec, `#cors-safelisted-request-header`
      sits on an inline `<dfn>` and `#origin-header` on an `<h3>`: turning the
      first into a CSS selector would narrow the scope to a two-word term and
      fail every honest citation of the sentence around it. An anchor says where
      the author was looking, not always what they meant to quote — and where we
      cannot tell, we do not narrow. Our guess must not be able to condemn a
      citation.
    """
    if not anchor or not hasattr(fmt, "sections"):
        return None

    match = _ANCHOR_SECTION_RE.match(anchor)
    if match:
        return f"§ {match.group(1)}"

    title = _title_for_anchor(body, anchor, fmt)
    return selector_for_title(title) if title else None


def _title_for_anchor(body: str, anchor: str, fmt) -> str | None:
    """The heading this anchor is attached to, if it is attached to one."""
    by_id = getattr(fmt, "heading_by_id", None)
    if by_id is not None:
        found = by_id(body, anchor)
        if found:
            return str(found)

    wanted = anchor_slug(anchor)
    for node in _headings(fmt.sections(body)):
        if anchor_slug(node.title) == wanted:
            return node.title
    return None


def locate_section(body: str, snippet: str, fmt) -> LocateResult | None:
    """High-level: build section tree, generate a sourceSection selector.

    The selector returned is one that has been *proved* to lead back to the
    snippet. ``simplify_selector`` always verified its candidates, but fell back
    to ``generate_selector``'s output unverified — and that output is ambiguous
    whenever two sections share a title, because a heading part matches the
    first one in document order. So a snippet in the *second* "Introduction" was
    given the selector ``Introduction, paragraph 1``, which resolves to the
    first: ``add`` wrote a citation and ``check`` then verified it against a
    different section's text, quietly.

    When no faithful selector can be built — two same-titled sections at the
    same level cannot be told apart in this grammar — we return None rather than
    emit one that resolves elsewhere. A citation that cannot be addressed
    honestly is better left unwritten than written wrong.
    """
    if not hasattr(fmt, "sections"):
        return None

    root = fmt.sections(body)
    if not root.children:
        return None

    selector = generate_selector(root, snippet)
    if selector is None:
        return None

    selector = simplify_selector(root, selector, snippet)

    norm_snippet = _normalize(snippet)
    extracted = extract_by_selector(root, selector)
    if not extracted or norm_snippet not in _normalize(extracted):
        return None

    return LocateResult(
        format_name="section",
        locator=selector,
        matched_text=norm_snippet,
    )
