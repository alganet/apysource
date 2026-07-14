# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""MDN repository module.

MDN pages resolve to the Markdown that *generates* them, in the ``mdn/content``
GitHub repository — not to the rendered page. MDN reorganizes constantly, and a
moved page keeps answering its old URL with a 301, so a citation that has gone
stale still verifies green against whatever the redirect leads to. The authored
file does not play along: a moved page's slug is simply gone from the
repository, the fetch 404s, and the citation fails. That failure is the point of
this module.

The price is that authored Markdown is not what a reader saw. It carries front
matter, Markdown markup, and KumaScript macros (``{{HTTPHeader("Origin")}}``)
that the site expands at build time. ``extract_content`` reproduces the
*rendered* prose, so an author can quote what the browser showed them and have
it verify.

Text that a macro *generates* out of data this file does not contain — the
``{{Compat}}`` and ``{{Specifications}}`` tables, live samples, sidebars —
cannot be reconstructed from the Markdown, and so cannot be quoted. Such a quote
fails. It is marked, not deleted: deleting a macro sews the words on either side
of it into a sentence the page never showed, and a citation that invented *that*
sentence would verify green. ``similar to the {{HTTPHeader("Referer")}} header``
must not become ``similar to the header``.

Only ``en-US`` pages are handled. Translations live in a different repository
(``mdn/translated-content``), so a ``/fr/docs/`` URL deliberately does not match
here and is left to the generic fetcher: mapping it into ``files/fr/`` would
404 on every French citation and report every live, correctly-cited page as
missing.

sourceLocation formats: a section path, or empty for the whole page.
  ""                          -> the whole page
  "Syntax"                    -> the "## Syntax" section
  "Description, paragraph 2"  -> the second paragraph of "## Description"

Known limitation — the moving ref: ``base_url`` ends in ``main``, so the text a
citation is checked against can change between runs with no signal. A commit SHA
can be put where ``main`` is (``.../mdn/content/<sha>/files``) to pin it; a
first-class ``ref`` argument composing ``base_url`` is the seam if that is ever
wanted.
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from apysource.repos._base import BaseRepo, RepoNotFound

logger = logging.getLogger(__name__)

#: What an unrenderable macro leaves behind.
#:
#: Deliberately something no human could paste out of a browser, so it can only
#: ever *prevent* a match, never create one. It also lands in the failure diff,
#: which turns a bare "snippet not found" into a visible "there is a macro here".
MACRO_MARK = "⟨macro⟩"

#: Macros that render as a link whose text is ``$1 || $0`` — the rule shared by
#: every link-like KumaScript macro (yari, ``kumascript/macros/*.ejs``).
#: Confirmed against the rendered page, not assumed: ``{{Glossary("CORS",
#: "cross origin")}}`` shows "cross origin", not "CORS".
TEXT_MACROS = frozenset({
    "glossary", "httpheader", "httpstatus", "httpmethod", "httpstatuscode",
    "domxref", "jsxref", "cssxref", "svgattr", "svgelement", "webextapiref",
})

#: Of those, the ones whose single-argument form renders only the last path
#: segment: ``{{jsxref("Global_Objects/Array")}}`` shows "Array".
PATH_MACROS = frozenset({"domxref", "jsxref", "cssxref"})

#: Inline badges. These *are* visible text on the page, so they render as such
#: rather than vanishing.
BADGE_MACROS = {
    "optional_inline": "Optional",
    "deprecated_inline": "Deprecated",
    "experimental_inline": "Experimental",
    "non-standard_inline": "Non-standard",
    "readonlyinline": "Read only",
    "securecontext_inline": "Secure context",
}

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_TITLE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[^\n]*\n(.*?)^[ \t]*\2[ \t]*$",
                    re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_MACRO = re.compile(r"\{\{\s*([\w.\-]+)\s*(?:\(\s*(.*?)\s*\))?\s*\}\}", re.DOTALL)
_MACRO_DEBRIS = re.compile(r"\{\{.*?\}\}", re.DOTALL)
_ARG = re.compile(r'"([^"]*)"|\'([^\']*)\'|([^,\s][^,]*)')
_IMAGE = re.compile(r"!\[[^\]]*\]\((?:[^()]|\([^()]*\))*\)")
_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\((?:[^()]|\([^()]*\))*\)")
_CALLOUT = re.compile(r"^>\s*\[!(\w+)\][ \t]*$", re.MULTILINE)
_QUOTE_MARK = re.compile(r"^>[ \t]?", re.MULTILINE)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_STAR_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<![\s*])\*(?![\w*])")
_US_ITALIC = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")
_TOKEN_RE = re.compile("\x00(\\d+)\x00")


# ── KumaScript / Markdown normalizer ──────────────────────────────────

def _macro_text(name: str, args: list[str]) -> str:
    """Render one KumaScript macro as the text a browser would show."""
    key = name.lower()

    if key in BADGE_MACROS:
        return BADGE_MACROS[key]

    if key == "htmlelement" and args:
        # {{HTMLElement("img")}} -> "<img>", but a display argument wins
        # outright: {{HTMLElement("iframe", "iframes")}} -> "iframes".
        if len(args) > 1 and args[1]:
            return args[1]
        return f"<{args[0].lower()}>"

    if key == "rfc" and args:
        return f"RFC {args[0]}"

    if key in TEXT_MACROS and args:
        if len(args) > 1 and args[1]:
            return args[1]
        if key in PATH_MACROS:
            return args[0].rsplit("/", 1)[-1]
        return args[0]

    # Everything else generates its text at build time from data this file does
    # not contain. Say so; do not invent it, and do not quietly close the gap.
    return MACRO_MARK


def _expand_macros(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        raw = m.group(2)
        args = [a or b or c for a, b, c in _ARG.findall(raw)] if raw else []
        return _macro_text(m.group(1), [a.strip() for a in args])

    text = _MACRO.sub(repl, text)
    # A macro whose arguments contain braces defeats the parse above. Leaving
    # the debris sitting inside a sentence that a snippet is matched against
    # would be worse than marking it: mark it, so the mismatch is visible.
    return _MACRO_DEBRIS.sub(MACRO_MARK, text)


def _mask_code(text: str) -> tuple[str, list[str]]:
    """Replace code spans and fences with tokens, keeping their text verbatim.

    Code is the one part of a page that must survive untouched. ``Origin:
    <scheme>://<hostname>`` is not an HTML tag, ``2 ** 3`` is not bold, and a
    Handlebars sample's ``{{name}}`` is not a KumaScript macro — every rule
    below would corrupt one of those. Masking first also stops a ``# comment``
    inside a shell sample from being read as a Markdown heading when a section
    is selected.
    """
    store: list[str] = []

    def keep(body: str) -> str:
        store.append(body)
        return f"\x00{len(store) - 1}\x00"

    text = _FENCE.sub(lambda m: keep(m.group(3)), text)
    return _INLINE_CODE.sub(lambda m: keep(m.group(2)), text), store


def _unmask_code(text: str, store: list[str]) -> str:
    return _TOKEN_RE.sub(lambda m: store[int(m.group(1))], text)


def strip_front_matter(text: str) -> str:
    """Drop YAML front matter, keeping the page title as its rendered H1.

    The title *is* rendered, as the page's heading, so it is quotable. The other
    keys — ``slug``, ``browser-compat`` — are not, and emitting them would let a
    quote match text no reader ever saw.
    """
    m = _FRONT_MATTER.match(text)
    if not m:
        return text
    title = _TITLE.search(m.group(1))
    heading = ""
    if title:
        heading = f"# {title.group(1).strip().strip(chr(34) + chr(39))}\n\n"
    return heading + text[m.end():]


def normalize_markup(text: str) -> str:
    """Turn authored MDN Markdown into the prose the page renders.

    Expects code to have been masked already.
    """
    # Before macros, so that the literal "<img>" that {{HTMLElement}} emits
    # survives. A space, never "": deleting <br> would fuse "foo<br>bar".
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    text = _expand_macros(text)
    # An image renders no text. Its alt text is not shown, and emitting it would
    # let a quote match words that were never on the page.
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _CALLOUT.sub(lambda m: m.group(1).capitalize() + ":", text)
    text = _QUOTE_MARK.sub("", text)
    text = _BOLD.sub(r"\1", text)
    text = _STAR_ITALIC.sub(r"\1", text)
    return _US_ITALIC.sub(r"\1", text)


def render(text: str, location: str = "") -> str:
    """Authored MDN Markdown -> rendered prose, optionally just one section."""
    masked, code = _mask_code(strip_front_matter(text))
    prose = normalize_markup(masked)

    location = location.strip()
    if location:
        from apysource.formats import MarkdownFormat
        # Selected on the masked text, so a "#" comment in a code sample cannot
        # forge a heading. A section that is not there yields "" — a loud miss.
        prose = MarkdownFormat().extract(prose, location)

    return _unmask_code(prose, code)


# ── Slug mapping ──────────────────────────────────────────────────────

def slug_to_folder(slug: str) -> str:
    """Map an MDN slug to its folder path in ``mdn/content``.

    Mirrors yari's ``slugToFolder``: ``Web/CSS/:hover`` is stored under
    ``web/css/.../_colon_hover``. Without this, every CSS pseudo-class and
    pseudo-element citation would 404 and be reported as a page that does not
    exist — a real page, failed, with the blame in the wrong place.
    """
    slug = slug.replace("*", "_star_")
    slug = slug.replace("::", "_doublecolon_").replace(":", "_colon_")
    slug = slug.replace("?", "_question_")
    return slug.lower()


class MdnRepo(BaseRepo):
    """Unified source + crawler for MDN pages, backed by ``mdn/content``."""

    NAME = "mdn"
    supports_crawl = True

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Map an MDN page URL to its path under ``files/`` in ``mdn/content``."""
        m = self.url_pattern.search(url)
        if not m:
            return None

        slug = urllib.parse.unquote(m.group(1)).strip("/")
        if not slug:
            return None

        key = "en-us/" + slug_to_folder(slug)

        # The key becomes a filesystem path. A slug is not to be trusted to stay
        # inside the cache directory merely because it arrived in a URL.
        if any(part in ("", ".", "..") for part in key.split("/")):
            logger.warning("refusing suspicious MDN slug: %r", slug)
            return None

        return key

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Map a sourceLocation to the cached authored Markdown file."""
        path = self.cache_root / key / "index.md"
        return path if path.exists() else None

    def extract_content(self, location: str, file_path: Path) -> str:
        """Render the authored Markdown as the prose the MDN page shows."""
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return render(text, location)

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float | None = None,
              force: bool = False, from_cache: bool = False) -> dict:
        """Download one page's authored Markdown from ``mdn/content``.

        A page the repository does not have raises RepoNotFound and writes
        nothing. The prototype this replaces cached an empty file instead, which
        surfaced later as "empty extraction (0 chars)" — loud, blamed on the
        citation rather than on the moved page, and stuck until someone passed
        --refresh.
        """
        path = self.cache_root / key / "index.md"

        if not force and path.exists():
            text = path.read_text(encoding="utf-8")
            return {"id": key, "status": "ok", "text_chars": len(text)}

        url = f"{self.base_url}/{key}/index.md"
        raw = self.fetch(url, key, force=force, from_cache=from_cache)

        if not raw.strip():
            # Never write a zero-byte file: a cached empty page is a permanent
            # false failure that outlives whatever caused it.
            raise RepoNotFound(self.NAME, key, f"{url} is empty")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        logger.info("%s — %s chars", key, f"{len(raw):,}")

        return {
            "id": key, "status": "ok", "text_chars": len(raw),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }
