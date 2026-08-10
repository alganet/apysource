# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""IETF repository module — RFCs and Internet-Drafts.

An RFC is not a file format. It is a document family with a publisher, and that
publisher issues one document in several renditions at once: ``rfc9110.txt``,
``rfc9110.html``, a datatracker rendering, a PDF. Which of them a citation is
checked against is a decision, and only something that knows where the document
comes from can make it. A content format cannot: it is handed bytes and asked
what they say, long after the choice was made.

So this repo makes the choice, and it chooses the HTML. The plain text is a
72-column rendering with page furniture in the middle of it — a running header
and a ``[Page 12]`` footer every 58 lines, and words split at the wrap. Reading
it means undoing all of that by inference. The HTML says the same things
structurally: a heading is a heading, a table is a table, and every section
carries ``id="section-7.2"``, which the publisher wrote down rather than
something we deduced from the shape of a line.

The catch, and the reason this module is not three lines long, is that
rfc-editor publishes **two** htmlizations:

* Modern (xml2rfc v3, roughly RFC 8650 onward) is a real HTML document. Real
  ``<h2>`` elements, ``<section id="section-3.1">`` wrappers, ``<table>`` where
  the text rendition drew a box out of ``|`` and ``+``. Nothing needs doing to
  it, and doing something to it would be destructive: these documents carry
  twenty-odd ``<pre>`` elements of their own — ABNF, frame diagrams, examples —
  and flattening those loses the artwork the citation may be quoting.

* Legacy (everything older, and every datatracker rendering of an old draft) is
  the paginated text wrapped in ``<pre>``, with anchors threaded through it.
  There is not one heading element in the whole file. Headings are
  ``<span class="h3"><a class="selflink" id="section-2.1">2.1</a>. Title</span>``
  on rfc-editor, and a real ``<h2>`` *nested inside the* ``<pre>`` on
  datatracker, which amounts to the same thing: an HTML reader walks elements,
  and everything that matters here is bare text inside one giant element.

Left alone, the second kind is worse than useless — it is quietly wrong. Asked
for ``§ 2`` of ``draft-thomson-hybi-http-timeout-03`` today, an HTML reader
answers with a running header and the tail of § 1. Not an empty extraction that
someone would investigate: the wrong section's text, silently, which is the one
failure this whole tool exists to prevent.

``render`` therefore normalizes the legacy shape into the modern one — hoisting
the pseudo-headings out of the ``<pre>`` and re-emitting the prose around them
as sibling blocks — and passes the modern shape through untouched. The gate
between them is **structural**, never a host name and never an RFC number:
a document is legacy if it has heading-ish elements *inside* a ``<pre>``.
Numbers would be wrong at the boundary and wrong for drafts; hosts would be
wrong the day either publisher re-renders its archive.

What ``render`` returns is HTML, not prose, on purpose. The point of fetching
this rendition is that ``HtmlFormat`` can then section it and the ``#section-7.2``
an author's URL was already carrying resolves against the same tree. Turning it
into text here would throw away the structure this module exists to recover.

The cache holds the **raw** rendition and normalization happens on read, so a
fix here reaches every already-cached document without ``--refresh``.

Known limitations:

* An unversioned draft id (``draft-ietf-httpbis-rfc6265bis``) resolves to
  whatever datatracker calls current, so the text behind a citation can change
  with no signal. Cite ``-08`` and it is pinned. This is the same moving ref
  ``MdnRepo`` has at ``.../main/files``, for the same reason.
* ``location:`` is not honoured. On an RFC there is nothing below the document
  that has a stable address — a line range into a paginated rendition names a
  different passage after the next revision. ``section:`` is the address.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apysource.repos._base import BaseRepo, RepoNotFound

logger = logging.getLogger(__name__)

#: Where a rendition's document sits inside whatever chrome wraps it.
#: rfc-editor serves the document bare; datatracker wraps it in navigation.
DOCUMENT_CONTAINERS = "div.rfcmarkup, div.rfchtml, #content"

#: Classes the publisher puts on things a reader is not meant to read as text:
#: the running header, the ``[Page 12]`` footer, the print-only rules.
FURNITURE_CLASSES = frozenset({"grey", "noprint"})

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

#: The gate. A heading *inside* a ``<pre>`` is what a legacy htmlization looks
#: like, in both of the shapes it comes in, and is a thing no real HTML document
#: does. Checked as a selector rather than a count so that a modern document's
#: own twenty ``<pre>`` elements never trip it.
_PREFORMATTED = ", ".join(
    [f"pre {tag}" for tag in _HEADING_TAGS]
    + [f"pre span.{tag}" for tag in _HEADING_TAGS]
)

#: ``<span class="h3">`` — a heading drawn as a span because the whole document
#: is one ``<pre>`` and a real heading would have broken the layout.
_HEADING_CLASS = re.compile(r"^h([1-6])$")

#: The ``Author  ...  [Page 24]`` footer, for the copies of it the publisher did
#: not mark up. ``FURNITURE_CLASSES`` removes 23 of rfc8288's 24; the last page's
#: is bare text, because nothing follows it to be wrapped. A structural rule
#: cannot see what carries no structure, and ``[Page N]`` at the end of a line is
#: unambiguous on its own — which is why the text rendition's reader could key on
#: it directly and this one only needs it as a backstop.
_PAGE_FOOTER = re.compile(r"^.*\[Page \d+\]\s*$", re.MULTILINE)

#: A blank line, which is what separates one paragraph from the next inside a
#: ``<pre>``. Splitting on it is what keeps ``§ 2.1, paragraph 3`` addressing the
#: same paragraph it addressed in the text rendition.
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")

#: A word split across the 72-column wrap at a single hyphen. RFC text
#: hyphenates only at hyphens already in the token — a field name, an ABNF rule,
#: a charset like ``ISO-8859-1`` — so ``ISO-\n   8859-1`` otherwise reads as
#: ``ISO- 8859-1`` and the token cannot be quoted whole. Only a *single* hyphen
#: between two alphanumerics is joined, which leaves a line ending ``--`` alone.
_WRAPPED_HYPHEN = re.compile(r"(?<=[A-Za-z0-9])-\n[ \t]*(?=[A-Za-z0-9])")

#: A key is about to become a filename. A slug is not to be trusted to stay
#: inside the cache directory merely because it arrived in a URL.
_SAFE_KEY = re.compile(r"^(?:rfc|bcp|std)\d+$|^draft-[a-z0-9][a-z0-9.\-]*$")

_TITLE_ENDS = re.compile(r"^(Abstract|Status of [Tt]his Memo)\b")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def document_root(soup: Any) -> Any:
    """The document, out of whatever chrome the host wrapped it in."""
    return soup.select_one(DOCUMENT_CONTAINERS) or soup.find("body") or soup


def is_preformatted(root: Any) -> bool:
    """Is this the legacy htmlization — paginated text with anchors in it?"""
    return root.select_one(_PREFORMATTED) is not None


def _heading_level(el: Any) -> int | None:
    """The heading level this element stands for, or None if it is not one."""
    if el.name in _HEADING_TAGS:
        return int(el.name[1])
    if el.name == "span":
        for cls in el.get("class") or ():
            match = _HEADING_CLASS.match(cls)
            if match:
                return int(match.group(1))
    return None


def _heading_id(el: Any) -> str | None:
    """The anchor a heading carries.

    Both generations put it on the ``a.selflink`` inside the heading rather than
    on the heading itself, and both spell it identically — ``section-2.1``,
    ``appendix-A.1``. That identity across renditions is why the anchor, and not
    the shape of the heading text, is the reliable address.
    """
    link = el.find("a", class_="selflink") or el.find("a", id=True)
    if link is not None and link.get("id"):
        return str(link["id"])
    return str(el["id"]) if el.get("id") else None


def _is_furniture(el: Any) -> bool:
    """Page furniture: what the renderer drew, not what the document says."""
    if el.name == "hr":
        return True
    if FURNITURE_CLASSES & set(el.get("class") or ()):
        return True
    return str(el.get("id") or "").startswith("page-")


def _document_title(out: Any, blocks: list[str]) -> str:
    """What the document calls itself.

    The legacy rendition has no ``<title>`` at all — the file begins at ``<pre>``
    — and without one the generic rule falls back to the first heading, which
    labels every RFC in existence ``1. Introduction``.

    Both publishers draw the document's own title as a top-level heading with no
    section anchor on it, every section heading having one. That absence is the
    signal, and it is a cheaper and more direct answer than reading the front
    matter. The front-matter scan below is the fallback for a rendition that
    draws no title heading at all.
    """
    for heading in out.find_all("h1"):
        if not heading.get("id"):
            return _collapse(heading.get_text())
    return _front_matter_title(blocks)


def _front_matter_title(blocks: list[str]) -> str:
    """The title from the header block above ``Abstract``.

    An RFC prints its title centred between the author column and the
    ``Abstract``/``Status of This Memo`` that follows it, so it is the run of
    lines immediately before that heading.
    """
    lines = "\n\n".join(blocks).split("\n")[:60]
    for i, line in enumerate(lines):
        if _TITLE_ENDS.match(line):
            title: list[str] = []
            for prev in reversed(lines[:i]):
                if not prev.strip():
                    if title:
                        break
                    continue
                title.insert(0, prev.strip())
            return _collapse(" ".join(title))
    return ""


def promote(root: Any, out: Any) -> Any:
    """Rebuild a legacy rendition as headings with prose between them.

    Retagging each ``<span class="h3">`` where it stands is not enough, and the
    way it fails is silent: ``HtmlFormat.sections`` walks *elements*, and a
    legacy document's prose is bare text inside the ``<pre>``. Leave the heading
    in there and every section comes out addressable and **empty** — a tree that
    resolves ``§ 2.1`` and hands back nothing. The prose has to become elements
    too, which is what the blank-line split below is for.
    """
    from bs4 import Comment, NavigableString, Tag

    body = out.body
    blocks: list[list[Any]] = [[]]
    plain: list[str] = []

    def add_text(text: str) -> None:
        text = _WRAPPED_HYPHEN.sub("-", _PAGE_FOOTER.sub("", text))
        parts = _PARAGRAPH_BREAK.split(text)
        blocks[-1].append(parts[0])
        for part in parts[1:]:
            blocks.append([part])

    def flush() -> None:
        for block in blocks:
            rendered = "".join(
                item if isinstance(item, str) else item.get_text() for item in block
            )
            if not rendered.strip():
                continue
            plain.append(rendered)
            pre = out.new_tag("pre")
            for item in block:
                pre.append(out.new_string(item) if isinstance(item, str) else item)
            body.append(pre)
        blocks.clear()
        blocks.append([])

    for pre in root.find_all("pre"):
        # A `<pre>` already moved into `out` as part of a block is not walked
        # again; find_all was taken before anything moved, so check the parent.
        if pre.parent is body:
            continue
        for child in list(pre.children):
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                add_text(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if _is_furniture(child):
                continue
            level = _heading_level(child)
            if level is None:
                blocks[-1].append(child)
                continue
            flush()
            heading = out.new_tag(f"h{level}")
            anchor = _heading_id(child)
            if anchor:
                heading["id"] = anchor
            heading.string = _collapse(child.get_text())
            body.append(heading)

    flush()

    title = _document_title(out, plain)
    if title and out.find("title") is None:
        head = out.new_tag("head")
        tag = out.new_tag("title")
        tag.string = title
        head.append(tag)
        out.html.insert(0, head)

    return out


def render(raw: str) -> str:
    """One rendition in, one HTML document ``HtmlFormat`` can read out.

    A modern rendition comes back byte for byte: it is already the thing this
    function is trying to produce, and rewriting it would only lose whatever
    this module failed to anticipate.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    root = document_root(soup)
    if not is_preformatted(root):
        return raw

    out = BeautifulSoup("<html><body></body></html>", "html.parser")
    return str(promote(root, out))


class RfcRepo(BaseRepo):
    """Unified source + crawler for RFCs and Internet-Drafts."""

    NAME = "rfc"
    supports_crawl = True

    # RFCs only. `CANONICAL_URL` is one template and cannot branch, and a draft
    # is named by a slug rather than by a number, so drafts are cited by URL —
    # which the `url_pattern` above claims all the same.
    NAME_MATCH = r"^RFC (?P<n>\d+)$"
    CANONICAL_URL = "https://www.rfc-editor.org/rfc/rfc{n}.html"
    NAME_EXAMPLE = "RFC 9110"

    def __init__(self, *args: Any, draft_base_url: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: Where Internet-Drafts are fetched from. rfc-editor has none, and the
        #: I-D archive serves a 2012 draft only as plain text, so the archive
        #: URL an author cites is answered from datatracker's rendering of the
        #: same draft — the only rendition of it that carries section anchors.
        self.draft_base_url = (draft_base_url
                               or "https://datatracker.ietf.org/doc/html").rstrip("/")

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Map any rendition's URL to the one document behind it.

        Deliberately non-injective, and that is the point: ``rfc9110.txt``,
        ``rfc9110.html`` and datatracker's ``/doc/html/rfc9110`` are three
        addresses for one document, so they are one cache entry. The extension
        is a rendition, not an identity.
        """
        match = self.url_pattern.search(url)
        if not match:
            return None

        key = match.group(1).lower()
        if not _SAFE_KEY.match(key):
            logger.warning("refusing suspicious IETF document id: %r", key)
            return None
        return key

    def resolve_location(self, location: str, key: str) -> Path | None:
        """The cached rendition. ``location`` is not an address here."""
        path = self.cache_root / f"{key}.html"
        return path if path.exists() else None

    def extract_content(self, location: str, file_path: Path) -> str:
        """Normalize the cached rendition into a page with a structure."""
        return render(file_path.read_text(encoding="utf-8", errors="replace"))

    # ── Crawler interface ─────────────────────────────────────────────

    def _document_url(self, key: str) -> str:
        if key.startswith("draft-"):
            return f"{self.draft_base_url}/{key}"
        return f"{self.base_url}/{key}.html"

    def crawl(self, key: str, *, delay: float | None = None,
              force: bool = False, from_cache: bool = False) -> dict:
        """Download one document's HTML rendition.

        The raw rendition is what lands on disk. Normalizing before caching
        would freeze whatever ``render`` believed on the day of the fetch into
        every cached copy, and a fix to it would then need ``--refresh`` on a
        corpus of documents that have not changed.
        """
        path = self.cache_root / f"{key}.html"

        if not force and path.exists():
            return {"id": key, "status": "ok",
                    "text_chars": path.stat().st_size}

        url = self._document_url(key)
        raw = self.fetch(url, key, force=force, from_cache=from_cache)

        if not raw.strip():
            # Never write a zero-byte file: a cached empty document is a
            # permanent false failure that outlives whatever caused it.
            raise RepoNotFound(self.NAME, key, f"{url} is empty")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        logger.info("%s — %s chars", key, f"{len(raw):,}")

        return {
            "id": key, "status": "ok", "text_chars": len(raw),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }
