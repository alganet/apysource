# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Content-format adapters for extraction and location.

Each format (HTML, plain text, etc.) implements detect/extract/locate.
Dispatch functions select the right adapter by name or auto-detection.
"""

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LocateResult:
    """Result of locating a snippet in a document."""

    format_name: str
    locator: str
    matched_text: str = ""


class ContentFormat(Protocol):
    """Protocol for content-format adapters."""

    name: str
    mime_type: str

    def detect(self, body: str) -> bool:
        """Return True if this format handles the given body."""
        ...

    def extract(self, body: str, locator: str) -> str:
        """Extract content from body using a format-specific locator."""
        ...

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Find snippet in body, return a LocateResult or None."""
        ...


# Short name → IANA media type mapping
MIME_ALIASES: dict[str, str] = {
    "html": "text/html",
    "markdown": "text/markdown",
    "wikitext": "text/x-wikitext",
    "rfc": "text/plain",
    "plain-text": "text/plain",
}


def normalize_mime_type(value: str) -> str:
    """Normalize a source type to an IANA media type.

    Accepts both short names ('html') and MIME types ('text/html').
    """
    return MIME_ALIASES.get(value, value)


def _normalize(text: str) -> str:
    """Collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text).strip()


class HtmlFormat:
    """HTML content format — CSS selectors for extraction and location."""

    name = "html"
    mime_type = "text/html"

    def detect(self, body: str) -> bool:
        head = body[:1000].lstrip()
        if head[:9].lower().startswith("<!doctype") or head[:5].lower().startswith("<html"):
            return True
        if "<head" in head.lower() or "<body" in head.lower():
            return True
        return False

    def strip_tags(self, body: str) -> str:
        """Convert HTML to plain text by stripping tags."""
        text = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        text = re.sub(r'&#\d+;', ' ', text)
        return re.sub(r'\n{3,}', '\n\n', text).strip()

    def sections(self, body: str):
        """Build a SectionNode tree from HTML headings."""
        from bs4 import BeautifulSoup, Tag
        from apysource.sections import SectionNode

        soup = BeautifulSoup(body, "html.parser")
        root = SectionNode(title="", level=0)
        heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}

        # Collect all headings and paragraphs in document order
        content_area = soup.find("body") or soup
        elements = content_area.find_all(heading_tags | {"p"})

        # Stack of (level, SectionNode) for nesting
        stack: list[tuple[int, SectionNode]] = [(0, root)]

        for el in elements:
            if not isinstance(el, Tag):
                continue

            if el.name in heading_tags:
                level = int(el.name[1])
                title = _normalize(el.get_text())
                node = SectionNode(title=title, level=level)

                # Pop stack until we find a parent with lower level
                while stack and stack[-1][0] >= level:
                    stack.pop()

                parent = stack[-1][1] if stack else root
                parent.children.append(node)
                stack.append((level, node))

            elif el.name == "p":
                text = _normalize(el.get_text())
                if text:
                    # Add paragraph to the most recent section
                    current = stack[-1][1] if stack else root
                    current.paragraphs.append(text)

        return root

    def extract(self, body: str, locator: str) -> str:
        """Extract text from HTML using a CSS selector."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(body, "html.parser")
        elements = soup.select(locator)
        return "\n\n".join(el.get_text(strip=True) for el in elements)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Find a snippet in HTML and produce a CSS selector.

        Prefers the deepest (most specific) element whose text contains
        the snippet — avoids matching a parent div that includes everything.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(body, "html.parser")
        norm_snippet = _normalize(snippet)

        text_tags = {"p", "li", "td", "th", "blockquote", "dd", "dt",
                     "figcaption", "h1", "h2", "h3", "h4", "h5", "h6",
                     "span", "div", "pre", "code"}

        matches = []
        for element in soup.find_all(text_tags):
            text = element.get_text()
            norm_text = _normalize(text)
            if norm_snippet in norm_text:
                depth = len(list(element.parents))
                matches.append((depth, element, norm_text))

        matches.sort(key=lambda m: -m[0])

        for _, element, norm_text in matches:
            selector = _css_selector_for(element)
            found = soup.select(selector)
            if found:
                return LocateResult(
                    format_name="html",
                    locator=selector,
                    matched_text=norm_text,
                )

        return None


class MarkdownFormat:
    """Markdown content format — section selectors for extraction and location."""

    name = "markdown"
    mime_type = "text/markdown"

    def detect(self, body: str) -> bool:
        """Detect Markdown by ATX headings (``# Title``), not HTML structure."""
        head = body[:1000].lstrip()
        # Reject if it looks like HTML
        if HtmlFormat().detect(body):
            return False
        # Require at least one ATX heading
        return bool(re.search(r"^#{1,6}\s", body, re.MULTILINE))

    def sections(self, body: str):
        """Build a SectionNode tree from Markdown ATX headings."""
        from apysource.sections import SectionNode

        root = SectionNode(title="", level=0)
        stack: list[tuple[int, SectionNode]] = [(0, root)]
        heading_re = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")

        current_paragraphs: list[str] = []
        current_block: list[str] = []

        def _flush_block():
            text = _normalize("\n".join(current_block))
            if text:
                current_paragraphs.append(text)
            current_block.clear()

        for line in body.split("\n"):
            m = heading_re.match(line)
            if m:
                _flush_block()
                # Assign accumulated paragraphs to current section
                target = stack[-1][1] if stack else root
                target.paragraphs.extend(current_paragraphs)
                current_paragraphs = []

                level = len(m.group(1))
                title = m.group(2).strip()
                node = SectionNode(title=title, level=level)

                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else root
                parent.children.append(node)
                stack.append((level, node))
            elif line.strip() == "":
                _flush_block()
            else:
                current_block.append(line)

        _flush_block()
        target = stack[-1][1] if stack else root
        target.paragraphs.extend(current_paragraphs)

        return root

    def extract(self, body: str, locator: str) -> str:
        """Extract content using a sourceSection selector."""
        from apysource.sections import extract_section
        return extract_section(body, locator, self)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Locate a snippet and produce a sourceSection selector."""
        from apysource.sections import locate_section
        return locate_section(body, snippet, self)


class WikitextFormat:
    """Wikitext content format — section selectors for extraction and location."""

    name = "wikitext"
    mime_type = "text/x-wikitext"

    def detect(self, body: str) -> bool:
        """Detect Wikitext by ``==Heading==`` patterns or wiki markup."""
        head = body[:2000]
        # Reject if it looks like HTML
        if HtmlFormat().detect(body):
            return False
        # Wikitext headings: == Title ==
        if re.search(r"^={2,6}[^=]", body, re.MULTILINE):
            return True
        # Wiki links or templates
        if "[[" in head or "{{" in head:
            return True
        return False

    def sections(self, body: str):
        """Build a SectionNode tree from Wikitext headings."""
        from apysource.sections import SectionNode

        root = SectionNode(title="", level=0)
        stack: list[tuple[int, SectionNode]] = [(0, root)]
        # Match == Title == through ====== Title ======
        heading_re = re.compile(r"^(={2,6})\s*(.+?)\s*=+\s*$")

        current_paragraphs: list[str] = []
        current_block: list[str] = []

        def _flush_block():
            text = _normalize("\n".join(current_block))
            if text:
                current_paragraphs.append(text)
            current_block.clear()

        for line in body.split("\n"):
            m = heading_re.match(line)
            if m:
                _flush_block()
                target = stack[-1][1] if stack else root
                target.paragraphs.extend(current_paragraphs)
                current_paragraphs = []

                # Wikitext == is level 2 (like h2), so level = len(equals) - 1
                level = len(m.group(1)) - 1
                title = m.group(2).strip()
                node = SectionNode(title=title, level=level)

                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else root
                parent.children.append(node)
                stack.append((level, node))
            elif line.strip() == "":
                _flush_block()
            else:
                current_block.append(line)

        _flush_block()
        target = stack[-1][1] if stack else root
        target.paragraphs.extend(current_paragraphs)

        return root

    def extract(self, body: str, locator: str) -> str:
        """Extract content using a sourceSection selector."""
        from apysource.sections import extract_section
        return extract_section(body, locator, self)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Locate a snippet and produce a sourceSection selector."""
        from apysource.sections import locate_section
        return locate_section(body, snippet, self)


class RfcTextFormat:
    """IETF RFC plain-text format — dotted-number sections for extraction and location."""

    name = "rfc"
    mime_type = "text/plain"

    # Section heading: "1.  Title", "2.1.  Title", or "1 Title", "2.1 Title"
    _SECTION_RE = re.compile(
        r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$", re.MULTILINE)
    # Appendix heading: "Appendix A.  Title" or "Appendix A Title"
    _APPENDIX_RE = re.compile(
        r"^Appendix\s+([A-Z](?:\.\d+)*)\.?\s+(\S.*)$", re.MULTILINE)

    def detect(self, body: str) -> bool:
        """Detect IETF RFC plain text by header markers and section numbering."""
        # Reject HTML
        if HtmlFormat().detect(body):
            return False
        head = body[:3000]
        signals = 0
        # RFC header markers
        if re.search(r"Request for Comments:\s*\d+", head):
            signals += 2
        elif re.search(r"RFC\s+\d{3,5}", head):
            signals += 1
        if re.search(r"Internet.Draft", head, re.IGNORECASE):
            signals += 1
        # Form feed characters
        if "\f" in body[:10000]:
            signals += 1
        # Dotted-number section headings (at least 2)
        sections = self._SECTION_RE.findall(body[:5000])
        if len(sections) >= 2:
            signals += 1
        # RFC-specific boilerplate sections
        if re.search(r"^Status of This Memo", head, re.MULTILINE):
            signals += 1
        return signals >= 2

    def _clean_body(self, body: str) -> str:
        """Strip RFC page headers/footers and form feeds."""
        # Remove form feeds
        text = body.replace("\f", "")
        # Remove page footer/header lines like "Author  ...  [Page N]"
        text = re.sub(r"^.*\[Page \d+\]\s*$", "", text, flags=re.MULTILINE)
        return text

    def sections(self, body: str):
        """Build a SectionNode tree from RFC dotted-number headings."""
        from apysource.sections import SectionNode

        text = self._clean_body(body)
        root = SectionNode(title="", level=0)
        stack: list[tuple[int, SectionNode]] = [(0, root)]

        current_paragraphs: list[str] = []
        current_block: list[str] = []

        def _flush_block():
            t = _normalize("\n".join(current_block))
            if t:
                current_paragraphs.append(t)
            current_block.clear()

        for line in text.split("\n"):
            # Check for numbered section heading
            m = self._SECTION_RE.match(line)
            if not m:
                m = self._APPENDIX_RE.match(line)
            if m:
                _flush_block()
                target = stack[-1][1] if stack else root
                target.paragraphs.extend(current_paragraphs)
                current_paragraphs = []

                num = m.group(1)
                title = f"{num}. {m.group(2).strip()}"
                level = num.count(".") + 1
                node = SectionNode(title=title, level=level)

                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else root
                parent.children.append(node)
                stack.append((level, node))
            elif line.strip() == "":
                _flush_block()
            else:
                current_block.append(line)

        _flush_block()
        target = stack[-1][1] if stack else root
        target.paragraphs.extend(current_paragraphs)

        return root

    def extract(self, body: str, locator: str) -> str:
        """Extract content using a sourceSection selector."""
        from apysource.sections import extract_section
        return extract_section(body, locator, self)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Locate a snippet and produce a sourceSection selector."""
        from apysource.sections import locate_section
        return locate_section(body, snippet, self)


class PlainTextFormat:
    """Plain-text content format — line ranges for extraction and location."""

    name = "plain-text"
    mime_type = "text/plain"

    def detect(self, body: str) -> bool:
        # Fallback format — accepts anything not claimed by another format.
        return True

    def extract(self, body: str, locator: str) -> str:
        """Extract a line range from text. Format: 'N-M' (1-based, inclusive)."""
        match = re.match(r"(\d+)-(\d+)", locator.strip())
        if not match:
            return ""
        start = int(match.group(1))
        end = int(match.group(2))
        lines = body.split("\n")
        extracted = lines[max(0, start - 1):end]
        return "\n".join(extracted)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Find a snippet in plain text and produce a line range."""
        norm_snippet = _normalize(snippet)

        norm_body = _normalize(body)
        pos = norm_body.find(norm_snippet)
        if pos == -1:
            return None

        lines = body.split("\n")
        char_count = 0
        start_line = None
        end_line = None

        for i, line in enumerate(lines):
            char_count += len(line) + 1  # +1 for \n
            norm_so_far = _normalize(body[:char_count])

            if start_line is None and len(norm_so_far) > pos:
                start_line = i
            if start_line is not None and len(norm_so_far) >= pos + len(norm_snippet):
                end_line = i
                break

        if start_line is None or end_line is None:
            return None

        line_range = f"{start_line + 1}-{end_line + 1}"
        return LocateResult(
            format_name="plain-text",
            locator=line_range,
            matched_text=_normalize("\n".join(lines[start_line:end_line + 1])),
        )


# ── Dispatch ────────────────────────────────────────────────────────────

DEFAULT_FORMATS: list[ContentFormat] = [
    HtmlFormat(), MarkdownFormat(), WikitextFormat(), RfcTextFormat(),
    PlainTextFormat(),
]


def _find_format(name: str, formats: list[ContentFormat]) -> ContentFormat | None:
    # Exact match on internal name (unambiguous)
    for fmt in formats:
        if fmt.name == name:
            return fmt
    # Match on MIME type — only if exactly one format has that MIME
    resolved = MIME_ALIASES.get(name, name)
    mime_matches = [fmt for fmt in formats if fmt.mime_type == resolved]
    if len(mime_matches) == 1:
        return mime_matches[0]
    # Ambiguous MIME (e.g. text/plain matches both rfc and plain-text) —
    # return None so the caller falls through to detect_format()
    return None


def detect_format(body: str,
                  formats: list[ContentFormat] = DEFAULT_FORMATS) -> ContentFormat:
    """Auto-detect the content format of a document body."""
    for fmt in formats:
        if fmt.detect(body):
            return fmt
    return formats[-1]


def extract_content(body: str, locator: str | None,
                    format_name: str | None = None,
                    formats: list[ContentFormat] = DEFAULT_FORMATS) -> str:
    """Extract content from body using format-specific locator."""
    if not locator:
        return body
    if format_name == "section":
        from apysource.sections import extract_section
        fmt = detect_format(body, formats)
        return extract_section(body, locator, fmt)
    # Line ranges (N-M) always use PlainTextFormat regardless of document type
    if re.match(r"^\d+-\d+$", locator.strip()):
        return PlainTextFormat().extract(body, locator)
    if format_name:
        found = _find_format(format_name, formats)
        if found:
            return found.extract(body, locator)
    fmt = detect_format(body, formats)
    return fmt.extract(body, locator)


def locate_snippet(body: str, snippet: str,
                   content_type: str | None = None,
                   formats: list[ContentFormat] = DEFAULT_FORMATS) -> LocateResult | None:
    """Locate a snippet in a document body. Returns None if not found."""
    if content_type:
        fmt = _find_format(content_type, formats)
        if fmt:
            return fmt.locate(body, snippet)
    fmt = detect_format(body, formats)
    return fmt.locate(body, snippet)


# ── Private helpers ─────────────────────────────────────────────────────

def _css_selector_for(element) -> str:
    """Generate a CSS selector path from an element to its nearest ancestor with an id."""
    parts = []
    current = element

    while current.name and current.name != "[document]":
        if current.get("id"):
            parts.append(f"#{current['id']}")
            break

        tag = current.name
        siblings = [s for s in current.parent.children
                    if hasattr(s, "name") and s.name == tag]
        if len(siblings) > 1:
            idx = siblings.index(current) + 1
            parts.append(f"{tag}:nth-of-type({idx})")
        else:
            parts.append(tag)

        current = current.parent

    parts.reverse()
    return " > ".join(parts)
