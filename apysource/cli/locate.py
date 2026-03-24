# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Locate a snippet at a URL and emit YAML or TTL output."""

import re
import sys

import yaml
from rdflib import BNode, Literal
from rdflib.namespace import RDF

from rdflib.namespace import DCTERMS

from apysource.formats import ContentFormat, LocateResult, detect_format, locate_snippet, normalize_mime_type
from apysource.namespaces import OA, SCHEMA, SV, new_graph
from apysource.sections import locate_section


def _extract_title(body: str, fmt: ContentFormat) -> str:
    """Extract a document title from the page content."""
    if fmt.name == "html":
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.DOTALL | re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    # For structured text formats, use the first heading
    if hasattr(fmt, "sections"):
        root = fmt.sections(body)
        if root.children:
            return str(root.children[0].title)
    return ""


def find_snippet(http_client, url: str, snippet: str) -> tuple[str, str, LocateResult]:
    """Fetch URL, locate snippet, return (content_type, title, result).

    Raises SystemExit on fetch failure or snippet not found.
    """
    body = http_client.get(url)
    if not body:
        print(f"Error: could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    fmt = detect_format(body)
    content_type = fmt.name
    title = _extract_title(body, fmt)

    # Prefer sourceSection when the document has structure
    result = locate_section(body, snippet, fmt)
    if result is None:
        result = locate_snippet(body, snippet, content_type)

    if result is None:
        print(f"Error: snippet not found in {url}", file=sys.stderr)
        sys.exit(1)

    return content_type, title, result


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


def format_turtle(url: str, content_type: str, snippet: str,
                  result: LocateResult) -> str:
    """Format a locate result as Turtle RDF with OA alignment."""
    g = new_graph()
    source = BNode()
    fragment = BNode()

    g.add((source, RDF.type, SV.Source))
    g.add((source, SCHEMA.url, Literal(url)))
    g.add((source, DCTERMS.format, Literal(normalize_mime_type(content_type))))

    g.add((fragment, RDF.type, SV.Fragment))
    g.add((fragment, OA.motivatedBy, OA.identifying))

    # OA target → source + selectors
    target = BNode()
    g.add((fragment, OA.hasTarget, target))
    g.add((target, RDF.type, OA.SpecificResource))
    g.add((target, OA.hasSource, source))

    # TextQuoteSelector from snippet
    tqs = BNode()
    g.add((target, OA.hasSelector, tqs))
    g.add((tqs, RDF.type, OA.TextQuoteSelector))
    g.add((tqs, OA.exact, Literal(snippet)))

    # Additional selector based on targetter type
    key = _targetter_key(result)
    if key == "selector":
        css = BNode()
        g.add((target, OA.hasSelector, css))
        g.add((css, RDF.type, OA.CssSelector))
        g.add((css, RDF.value, Literal(result.locator)))
    elif key == "section":
        fs = BNode()
        g.add((target, OA.hasSelector, fs))
        g.add((fs, RDF.type, SV.SectionSelector))
        g.add((fs, RDF.value, Literal(result.locator)))
    elif key == "lines":
        g.add((fragment, SV.sourceLines, Literal(result.locator)))

    return g.serialize(format="turtle")


class LocateCommand:
    def __init__(self, http_client):
        self.http_client = http_client

    def run(self, args: list[str] | None = None):
        if args is None:
            args = sys.argv[1:]

        ttl_mode = "--ttl" in args
        if ttl_mode:
            args = [a for a in args if a != "--ttl"]

        if len(args) < 2:
            print("Usage: apysource locate [--ttl] <url> <snippet>",
                  file=sys.stderr)
            sys.exit(1)

        url = args[0]
        snippet = args[1]

        content_type, title, result = find_snippet(self.http_client, url, snippet)

        if ttl_mode:
            print(format_turtle(url, content_type, snippet, result))
        else:
            print(format_yaml(url, content_type, snippet, result))
