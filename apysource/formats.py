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

    def text(self, body: str) -> str:
        """The document as a reader sees it — the text a citation is checked against.

        This is the format's *one* answer to "what does this document say", and
        every other entry point is built on it, so that they cannot disagree.
        They used to: extraction with no locator handed back raw HTML (so a
        snippet matched `<meta>` attributes and `<script>` bodies, while the
        page's actual prose did not match), extraction *with* a selector glued
        words together across inline tags, and `locate` searched a third text
        again — which is how ``add`` came to write citations that ``check``
        rejected.
        """
        ...

    def title(self, body: str) -> str:
        """What this document is called, or "" if it does not say.

        A document's title and its first heading are different things, and
        conflating them made ``add`` label a source `1. Introduction` — the first
        heading of every RFC ever written.
        """
        ...

    def extract(self, body: str, locator: str) -> str:
        """Extract content from body using a format-specific locator."""
        ...

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Find snippet in body, return a LocateResult or None."""
        ...


class SectionedFormat(ContentFormat, Protocol):
    """A format that can name the parts of a document.

    Kept separate because ``PlainTextFormat`` genuinely cannot do this: a flat
    text file has no sections to speak of. Callers ask with
    ``hasattr(fmt, "sections")``, and ``sections.extract_section`` turns the
    absence into an honest "this document has no sections" rather than blaming
    the selector.
    """

    def sections(self, body: str):
        """Build a SectionNode tree for this document."""
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


#: How a truncated extraction announces what it left out. Defined next to
#: the code that writes it, so the code that has to recognize it cannot
#: drift from the code that emits it.
TRUNCATION_MARKER = re.compile(r"\n?\.\.\. \[\d+ more chars\]\s*$")


def truncate(text: str, max_chars: int | None) -> str:
    """Cut text to length, saying how much was left behind.

    ``None`` means the whole document, and is what verification asks for: a
    snippet must be looked for in all of the source, not in a prefix of it.
    """
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [{len(text) - max_chars} more chars]"


def normalize_ws(text: str) -> str:
    """Collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text).strip()


#: Long-standing private alias; `normalize_ws` is the public name.
_normalize = normalize_ws


#: Elements a browser does not render as page text. Their contents are not
#: prose a reader could ever have quoted — a `<script>` body, a stylesheet, the
#: `<meta name="description">` in the head — so they are not part of what a
#: citation is checked against. Matching them let a snippet lifted from a meta
#: description verify against a page whose prose said something else entirely.
NON_CONTENT_TAGS = frozenset({"script", "style", "head", "noscript", "template"})

#: Elements a browser lays out as blocks. Text either side of one is separated
#: on screen, so it is separated here too — otherwise `<p>one</p><p>two</p>`
#: reads as `onetwo` and no quote spanning the two paragraphs can ever match.
BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table",
    "td", "th", "tr", "ul",
})


#: `title:` inside a leading YAML front-matter block (MDN, Jekyll, Hugo, …).
_FRONT_MATTER_TITLE = re.compile(
    r"^---\s*\n(?:.*\n)*?title:\s*(.+?)\s*\n(?:.*\n)*?---\s*$",
    re.MULTILINE,
)


def _first_heading_title(fmt, body: str) -> str:
    """The first top-level heading, for formats whose title *is* one.

    True of Markdown and wikitext, where the opening `# Heading` names the
    document. Emphatically *not* true of an RFC, whose first heading is
    `1. Introduction` — which is what `add` used to call every RFC it saw.
    """
    root = fmt.sections(body)
    return root.children[0].title if root.children else ""


def html_text(node) -> str:
    """The rendered text of an HTML node, with block boundaries kept apart.

    Whitespace is *never invented between inline elements*, and that is the
    whole design. A browser separates words only where the source separates
    them, so `The <code>Origin</code> request` reads `The Origin request`
    (the space is in the source) while `<b>Sub</b>string` reads `Substring`
    (it is not). Joining with a separator would forge the second; joining with
    nothing — which is what `get_text(strip=True)` did — mangles the first into
    `TheOriginrequest`.

    That asymmetry matters more than it looks: a normalizer mutates the very
    text a snippet is matched against, so inventing a space can manufacture a
    passing citation for prose the page never showed. Only block boundaries,
    where a reader really does see a break, get one.
    """
    from bs4 import NavigableString

    if isinstance(node, NavigableString):
        return str(node)

    out: list[str] = []
    for child in node.children:
        name = getattr(child, "name", None)
        if name in NON_CONTENT_TAGS:
            continue
        out.append(html_text(child))
        if name in BLOCK_TAGS:
            out.append("\n")
    return "".join(out)


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

    def _soup(self, body: str):
        """Parse once, the same way for every entry point.

        `sections`, `extract`, `locate` and `text` all read the document through
        this, so a selector that `locate` mints is a selector `extract` can
        honour. They used to parse and render the page three different ways.
        """
        from bs4 import BeautifulSoup
        return BeautifulSoup(body, "html.parser")

    def _content(self, body: str):
        """The part of the parse a reader actually sees."""
        soup = self._soup(body)
        return soup.find("body") or soup

    def text(self, body: str) -> str:
        """The page as a reader sees it: no markup, no head, no scripts."""
        return html_text(self._content(body))

    def title(self, body: str) -> str:
        """The `<title>`, which is what the page calls itself."""
        tag = self._soup(body).find("title")
        return _normalize(tag.get_text()) if tag else ""

    def heading_by_id(self, body: str, anchor: str) -> str | None:
        """The heading carrying this id, or None if the id is on something else.

        HTML says outright what an anchor points at, so there is no need to guess
        from the slug. The answer is often "not a heading": in the Fetch spec
        `#cors-safelisted-request-header` is on an inline `<dfn>`. Then this
        returns None, and the caller leaves the scope alone rather than narrow a
        citation down to a two-word term.
        """
        element = self._content(body).find(id=anchor)
        if element is None or element.name not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return None
        return _normalize(html_text(element))

    def strip_tags(self, body: str) -> str:
        """Convert HTML to plain text.

        Kept as the long-standing name, but no longer a regex over the markup:
        `<[^>]+>` terminates on the first `>`, so an attribute value containing
        one spilled into the text, and `<head>` was never removed at all. It now
        answers exactly what `text` answers, so the diagnosis a failure prints
        describes the same document the check actually read.
        """
        return self.text(body)

    def sections(self, body: str):
        """Build a SectionNode tree from HTML headings."""
        from bs4 import Tag
        from apysource.sections import SectionNode

        root = SectionNode(title="", level=0)
        heading_tags = {"h1", "h2", "h3", "h4", "h5", "h6"}

        # Collect all headings and paragraphs in document order
        content_area = self._content(body)
        elements = content_area.find_all(heading_tags | {"p"})

        # Stack of (level, SectionNode) for nesting
        stack: list[tuple[int, SectionNode]] = [(0, root)]

        for el in elements:
            if not isinstance(el, Tag):
                continue

            if el.name in heading_tags:
                level = int(el.name[1])
                title = _normalize(html_text(el))
                node = SectionNode(title=title, level=level)

                # Pop stack until we find a parent with lower level
                while stack and stack[-1][0] >= level:
                    stack.pop()

                parent = stack[-1][1] if stack else root
                parent.children.append(node)
                stack.append((level, node))

            elif el.name == "p":
                text = _normalize(html_text(el))
                if text:
                    # Add paragraph to the most recent section
                    current = stack[-1][1] if stack else root
                    current.paragraphs.append(text)

        return root

    def extract(self, body: str, locator: str) -> str:
        """Extract text from HTML using a CSS selector."""
        soup = self._soup(body)
        elements = soup.select(locator)
        return "\n\n".join(html_text(el) for el in elements)

    def locate(self, body: str, snippet: str) -> LocateResult | None:
        """Find a snippet in HTML and produce a CSS selector.

        Prefers the deepest (most specific) element whose text contains
        the snippet — avoids matching a parent div that includes everything.

        The selector it returns is one it has *proved* works: see
        ``_verified_locator``. A locator that does not lead back to the snippet
        is not a locator, and emitting one made ``add`` write citations that
        ``check`` then rejected.
        """
        soup = self._soup(body)
        norm_snippet = _normalize(snippet)

        text_tags = {"p", "li", "td", "th", "blockquote", "dd", "dt",
                     "figcaption", "h1", "h2", "h3", "h4", "h5", "h6",
                     "span", "div", "pre", "code"}

        matches = []
        for element in soup.find_all(text_tags):
            norm_text = _normalize(html_text(element))
            if norm_snippet in norm_text:
                depth = len(list(element.parents))
                matches.append((depth, element, norm_text))

        matches.sort(key=lambda m: -m[0])

        for _, element, norm_text in matches:
            selector = _css_selector_for(element)
            if _selector_yields(soup, selector, norm_snippet):
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
        # Reject if it looks like HTML
        if HtmlFormat().detect(body):
            return False
        # Require at least one ATX heading
        return bool(re.search(r"^#{1,6}\s", body, re.MULTILINE))

    def text(self, body: str) -> str:
        """Markdown source is what a Markdown citation is checked against.

        Deliberately *not* rendered. Inline markup does survive into the text a
        quote is matched against (a `` `code span` `` keeps its backticks), which
        is C4 — but rendering it here would mean stripping characters out of the
        very text a snippet is compared with, and an over-eager strip
        manufactures passing citations for prose the document never contained.
        That is exactly how the MDN macro normalizer forged sentences (E4). The
        A1 diagnosis already names this case ("differs only in inline markup")
        and shows the source's exact wording, so the author is told what to do
        rather than quietly told a falsehood.
        """
        return body

    def title(self, body: str) -> str:
        """Front matter first, then the first heading.

        A Markdown file that carries YAML front matter states its title there,
        and it is not the same as its first heading — MDN's `Origin` page opens
        with `## Syntax`, so the heading rule called that page "Syntax".
        """
        front = _FRONT_MATTER_TITLE.match(body)
        if front:
            return _normalize(front.group(1)).strip("'\"")
        return _first_heading_title(self, body)

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

    def text(self, body: str) -> str:
        """Wikitext source, unrendered — same reasoning as Markdown."""
        return body

    def title(self, body: str) -> str:
        """A wiki page's title is its first top-level heading."""
        return _first_heading_title(self, body)

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
        r"""Strip RFC pagination furniture and repair tokens broken across a wrap.

        Four steps, in order:

        * The running **header** (``RFC 9110  Semantics  June 2022``) is the line right
          after a page break, so it is removed keyed on the form feed it follows. Keying
          on the ``\f`` is what keeps this from touching a line of body prose that merely
          looks like a header — the same discipline the footer rule below cannot use,
          because a footer's ``[Page N]`` marker is unambiguous on its own.
        * Any stray form feed left over — a document may end on one with no line after it.
        * The page **footer** (``Author  ...  [Page N]``), which sits *before* the break.
        * A word split across the 72-column wrap **at a single hyphen** is rejoined
          without a space. RFC text hyphenates only at hyphens already in the token — a
          field name, an ABNF rule name, a charset like ``ISO-8859-1`` — so a wrap of
          ``ISO-\n   8859-1`` otherwise reads as ``ISO- 8859-1`` and the token cannot be
          quoted whole. The continuation is indented to the paragraph, so the newline and
          that indent are both consumed, leaving ``ISO-8859-1``. Only a *single* hyphen
          between two alphanumerics is joined, which leaves a line ending ``--`` (an
          em-dash) alone; and because every heading is preceded by a blank line, no
          heading is ever pulled up onto a hyphen above it.
        """
        # Running header: the line immediately after a form feed (removes both).
        text = re.sub(r"\f\n[^\n]*\n", "\n", body)
        # Any remaining form feed with no line of its own to carry a header.
        text = text.replace("\f", "")
        # Page footer, which is not adjacent to the break.
        text = re.sub(r"^.*\[Page \d+\]\s*$", "", text, flags=re.MULTILINE)
        # Rejoin a token split at a single hyphen across a wrap (never "--"). The
        # continuation is indented to its paragraph, so consume that indent too.
        text = re.sub(r"(?<=[A-Za-z0-9])-\n[ \t]*(?=[A-Za-z0-9])", "-", text)
        return text

    def text(self, body: str) -> str:
        """The RFC's prose, with the pagination furniture taken out.

        ``sections`` already read the document this way; whole-document
        extraction did not, so a sentence that happened to straddle a page break
        had `[Page 42]` and a form feed sitting in the middle of it and could
        not be quoted at all. The footers are not part of what the RFC says.
        """
        return self._clean_body(body)

    def title(self, body: str) -> str:
        """The RFC's own title, from its header block.

        An RFC prints its title centred between the author column and the
        ``Abstract``/``Status of this Memo`` that follows it — so it is the run
        of lines immediately before that heading. Falling back to the first
        *section* heading, as the generic rule does, labelled every RFC in
        existence `1. Introduction`.
        """
        head = self._clean_body(body).split("\n")[:60]
        for i, line in enumerate(head):
            if re.match(r"^(Abstract|Status of [Tt]his Memo)\b", line):
                title: list[str] = []
                for prev in reversed(head[:i]):
                    if not prev.strip():
                        if title:
                            break
                        continue
                    title.insert(0, prev.strip())
                return _normalize(" ".join(title))
        return ""

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

    def text(self, body: str) -> str:
        """A plain-text file is already its own text."""
        return body

    def title(self, body: str) -> str:
        """A flat text file does not say what it is called, so we do not guess.

        `add` falls back to the URL, which is at least true.
        """
        return ""

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
        """Find a snippet in plain text and produce a line range.

        One pass. This used to re-normalize a growing prefix of the whole
        document once per line — quadratic, and 11 seconds on a 422 KB RFC,
        which is the exact shape of document this tool exists to cite. Authoring
        a few hundred citations against RFCs was an hour of regex.

        Collapsing each line and joining the non-empty ones with a single space
        gives precisely ``normalize_ws(body)``, because a run of whitespace
        spanning a newline collapses to one space either way — so the offsets
        below index the same string the caller matched against.
        """
        norm_snippet = _normalize(snippet)
        if not norm_snippet:
            return None

        lines = body.split("\n")
        spans: list[tuple[int, int, int]] = []   # (norm_start, norm_end, line index)
        pieces: list[str] = []
        at = 0
        for i, line in enumerate(lines):
            norm_line = _normalize(line)
            if not norm_line:
                continue
            spans.append((at, at + len(norm_line), i))
            pieces.append(norm_line)
            at += len(norm_line) + 1             # + the space that will join it on

        norm_body = " ".join(pieces)
        pos = norm_body.find(norm_snippet)
        if pos == -1:
            return None
        end = pos + len(norm_snippet)

        start_line = next((i for s, e, i in spans if e > pos), None)
        end_line = next((i for s, e, i in reversed(spans) if s < end), None)
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


def _explain_empty(body: str, locator: str, fmt: ContentFormat) -> None:
    """Ask a section-capable format *why* it extracted nothing, and raise.

    Only reached when the extraction already came back empty, so the cost of
    re-walking the tree is paid exactly once, on the failure path — and only
    there is there anything to explain.
    """
    if not hasattr(fmt, "sections"):
        return
    from apysource.sections import extract_section
    extract_section(body, locator, fmt, strict=True)


def extract_content(body: str, locator: str | None,
                    format_name: str | None = None,
                    formats: list[ContentFormat] = DEFAULT_FORMATS,
                    *, strict: bool = False) -> str:
    """Extract content from body using format-specific locator.

    ``strict`` raises ``sections.SectionNotFound`` when a section selector
    matches nothing, rather than returning "" — which the report could only
    describe as an empty extraction, indistinguishable from an empty document.
    """
    if format_name == "section":
        from apysource.sections import extract_section
        fmt = detect_format(body, formats)
        return extract_section(body, locator or "", fmt, strict=strict)
    if not locator:
        # No selector means "the whole document" — which for HTML is the page a
        # reader sees, not its markup. This returned `body` verbatim, so a quote
        # lifted from a `<meta name="description">` or from inside a `<script>`
        # verified happily, while the page's own prose did not match at all: the
        # tool passed text nobody was ever shown and failed text they were.
        found = _find_format(format_name, formats) if format_name else None
        return (found or detect_format(body, formats)).text(body)
    # Line ranges (N-M) always use PlainTextFormat regardless of document type
    if re.match(r"^\d+-\d+$", locator.strip()):
        return PlainTextFormat().extract(body, locator)
    if format_name:
        found = _find_format(format_name, formats)
        if found:
            text = found.extract(body, locator)
            # Markdown/wikitext/RFC route their own extract() through the
            # section machinery, so a section miss can arrive by this door too.
            if strict and not text:
                _explain_empty(body, locator, found)
            return text
    fmt = detect_format(body, formats)
    text = fmt.extract(body, locator)
    if strict and not text:
        _explain_empty(body, locator, fmt)
    return text


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

def _selector_yields(soup, selector: str, norm_snippet: str) -> bool:
    """Does this selector actually lead back to the snippet?

    ``locate`` used to ask only whether the selector matched *something*, which
    is a weaker question than the one that matters, and the gap between the two
    is exactly where the bug lived: ``extract`` rendered the selected element
    differently from how ``locate`` had read it, so ``add`` happily wrote a
    citation that ``check`` rejected on the very next run.

    Asking the real question closes that class of bug for good, whatever future
    divergence anyone introduces — a locator that does not lead back to the
    snippet simply is not returned.
    """
    try:
        found = soup.select(selector)
    except Exception:  # noqa: BLE001 — a malformed selector is just a miss
        return False
    if not found:
        return False
    rendered = _normalize("\n\n".join(html_text(el) for el in found))
    return norm_snippet in rendered


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
