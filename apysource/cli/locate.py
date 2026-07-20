# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Locate a snippet at a URL and emit YAML or TTL output."""

import sys

import yaml
from rdflib import Literal
from rdflib.namespace import RDF, RDFS

from rdflib.namespace import DCTERMS

from apysource.cli._base import pop_flag
from apysource.diagnostics import explain_snippet_failure
from apysource.formats import (
    ContentFormat,
    LocateResult,
    detect_format,
    locate_snippet,
    normalize_mime_type,
)
from apysource.namespaces import OA, SCHEMA, SV, new_graph
from apysource.yaml_input import _anon
from apysource.sections import _section_label, locate_section, sections_containing


def _extract_title(body: str, fmt: ContentFormat) -> str:
    """What the document calls itself — the format's own answer.

    This asked the format for its first *section heading*, which is a different
    thing and is why `add` labelled an RFC source `1. Introduction`. An RFC
    states its title in its header block; an HTML page states it in `<title>`;
    a flat text file does not state one at all, and now says so instead of
    offering up a heading that is not a title.
    """
    title = getattr(fmt, "title", None)
    return str(title(body)) if title is not None else ""


def _warn_if_ambiguous(body: str, snippet: str, fmt, result: LocateResult) -> None:
    """Say so when the passage appears in more than one section.

    Specifications repeat themselves — "The response MUST include the following
    header fields:" sits under both § 10.2.7 and § 10.3.5 of RFC 2616 — and
    `locate` can only choose one. Choosing silently is a quiet claim that the
    passage lives there, and the citation would go on passing even after the
    passage was removed from the section its author actually meant, because it
    survives in the other. Naming the alternatives lets the author disambiguate
    now: quote more of the passage, or say which section they meant.
    """
    sections = getattr(fmt, "sections", None)
    if sections is None:
        return

    matches = sections_containing(sections(body), snippet)
    if len(matches) < 2:
        return

    others = [_section_label(node) or node.title for node in matches]
    print(f"  Note: this passage appears in {len(matches)} sections: "
          f"{', '.join(others)}", file=sys.stderr)
    print(f"        citing {result.locator}; quote more of it, or set "
          f"`section:` yourself, to be sure", file=sys.stderr)


def _warn_if_redirected(http_client, url: str) -> None:
    """Say so when the URL being cited is not the one that answered.

    Cheapest possible moment to fix a stale citation: before it is written
    down. The fetcher is duck-typed, so a custom one need not record this.
    """
    redirect_for = getattr(http_client, "redirect_for", None)
    if redirect_for is None:
        return

    info = redirect_for(url)
    if info is None or not info.redirected:
        return

    print(f"  Note: {url} redirects to {info.final_url}", file=sys.stderr)
    print("        consider citing the final URL instead", file=sys.stderr)


def find_snippet(http_client, url: str, snippet: str,
                 *, force: bool = False) -> tuple[str, str, LocateResult]:
    """Fetch URL, locate snippet, return (content_type, title, result).

    ``force=True`` bypasses the HTTP cache and re-fetches the URL.
    Raises SystemExit on fetch failure or snippet not found.
    """
    body = http_client.get(url, force=force)
    if not body:
        print(f"Error: could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    _warn_if_redirected(http_client, url)

    fmt = detect_format(body)
    content_type = fmt.name
    title = _extract_title(body, fmt)

    # Prefer sourceSection when the document has structure
    result = locate_section(body, snippet, fmt)
    if result is None:
        result = locate_snippet(body, snippet, content_type)
    else:
        _warn_if_ambiguous(body, snippet, fmt, result)

    if result is None:
        print(f"Error: snippet not found in {url}", file=sys.stderr)
        for line in explain_snippet_failure(snippet, _searchable_text(body, fmt)):
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)

    return content_type, title, result


def _searchable_text(body: str, fmt) -> str:
    """The document as the snippet would have to match it.

    The format's own answer to "what does this document say" — the same one
    ``check`` matches against. This used to reach for ``strip_tags``, which only
    ``HtmlFormat`` has, so every other format diffed against the **raw body**:
    an RFC hint quoted `[Page 42]` pagination furniture that ``check``'s
    document does not contain, and ``locate`` refused citations that ``check``
    would have verified. A hint is a claim about the source, and it must be a
    claim about the source that was actually read.
    """
    text = getattr(fmt, "text", None)
    if text is not None:
        return str(text(body))
    return body


def _targetter_key(result: LocateResult) -> str:
    """Return the YAML key name for a locate result's targetter."""
    if result.format_name == "section":
        return "section"
    elif result.format_name == "html":
        return "selector"
    else:
        return "lines"


def format_yaml(url: str, content_type: str, snippet: str,
                result: LocateResult) -> str:
    """Format a locate result as a YAML fragment block."""
    key = _targetter_key(result)
    frag = {"label": "", key: result.locator, "snippet": snippet}
    # yaml.dump on a list gives a pasteable fragment entry
    body = yaml.dump([frag], default_flow_style=False, allow_unicode=True,
                     sort_keys=False).rstrip()
    lines = [
        f"# Found in: {url}",
        f"# Targetter: {result.format_name}",
    ]
    if result.matched_text and result.matched_text != snippet:
        preview = result.matched_text[:120]
        if len(result.matched_text) > 120:
            preview += "..."
        lines.append(f"# Matched: {preview}")
    lines.append(f"\n{body}")
    return "\n".join(lines)


def _turtle_labels(url: str, title: str, snippet: str,
                   result: LocateResult) -> tuple[str, str]:
    """Names for the source and the fragment this Turtle describes.

    Both are required — `sv:SourceShape` and `sv:FragmentShape` each demand an
    `rdfs:label`. They were not emitted, so the output of `--ttl`, whose entire
    purpose is to be pasted into a `.ttl` file, did not conform to apysource's
    own shapes: `validate` refused the file it had just been pasted into. Nothing
    caught it because the shapes had never once run.

    The YAML sibling writes `label: ""` and leaves naming to the author. Turtle
    cannot — an empty label is a failed constraint, not a blank to fill — so
    these are real names, derived from what the document and the citation already
    say, and meant to be renamed.
    """
    source_label = title.strip() or url.rstrip("/").rsplit("/", 1)[-1] or url

    # A section path names the passage better than the passage does. Failing
    # that, enough of the quote to recognise it by.
    if _targetter_key(result) == "section" and result.locator:
        fragment_label = result.locator
    else:
        flat = " ".join(snippet.split())
        fragment_label = flat[:60] + "…" if len(flat) > 60 else flat

    return source_label, fragment_label or url


def format_turtle(url: str, content_type: str, snippet: str,
                  result: LocateResult, title: str = "") -> str:
    """Format a locate result as Turtle RDF with OA alignment."""
    g = new_graph()
    # Labelled, not left to `BNode()`'s uuid: rdflib orders the objects of a
    # predicate by blank-node identity, so a fragment with both a quote selector
    # and a section selector printed them in a different order each run. This is
    # output meant to be pasted into a file and committed.
    source = _anon(url, "source")
    fragment = _anon(url, "fragment")

    source_label, fragment_label = _turtle_labels(url, title, snippet, result)

    g.add((source, RDF.type, SV.Source))
    g.add((source, RDFS.label, Literal(source_label)))
    g.add((source, SCHEMA.url, Literal(url)))
    g.add((source, DCTERMS.format, Literal(normalize_mime_type(content_type))))

    g.add((fragment, RDF.type, SV.Fragment))
    g.add((fragment, RDFS.label, Literal(fragment_label)))
    g.add((fragment, OA.motivatedBy, OA.identifying))

    # OA target → source + selectors
    target = _anon(url, "target")
    g.add((fragment, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source))

    # TextQuoteSelector from snippet
    tqs = _anon(url, "quote")
    g.add((target, OA.hasSelector, tqs))
    g.add((tqs, RDF.type, OA.TextQuoteSelector))
    g.add((tqs, OA.exact, Literal(snippet)))

    # Additional selector based on targetter type
    key = _targetter_key(result)
    if key == "selector":
        css = _anon(url, "css")
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(result.locator)))
    elif key == "section":
        fs = _anon(url, "section")
        g.add((target, OA.hasSelector, fs))
        g.add((fs, RDF.type, SV.SectionSelector))
        g.add((fs, RDF.value, Literal(result.locator)))
    elif key == "lines":
        g.add((fragment, SV.sourceLines, Literal(result.locator)))

    return g.serialize(format="turtle")


class LocateCommand:
    """Locate a snippet at a URL and print a YAML fragment (or Turtle, ``--ttl``).

    Accepts ``--refresh`` to re-fetch the URL, bypassing the HTTP cache.
    """

    def __init__(self, http_client):
        self.http_client = http_client

    def run(self, args: list[str] | None = None):
        """Fetch the URL, locate the snippet, and print the result."""
        if args is None:
            args = sys.argv[1:]

        ttl_mode, args = pop_flag(args, "--ttl")
        force, args = pop_flag(args, "--refresh")

        if len(args) < 2:
            print("Usage: apysource locate [--ttl] [--refresh] <url> <snippet>",
                  file=sys.stderr)
            sys.exit(1)

        url = args[0]
        snippet = args[1]

        content_type, title, result = find_snippet(
            self.http_client, url, snippet, force=force)

        if ttl_mode:
            print(format_turtle(url, content_type, snippet, result, title))
        else:
            print(format_yaml(url, content_type, snippet, result))
