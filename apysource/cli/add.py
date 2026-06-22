# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Locate a snippet and add it to a YAML sources file."""

import sys
from pathlib import Path

import yaml

from apysource.cli._base import pop_flag
from apysource.cli.locate import find_snippet, _targetter_key
from apysource.formats import normalize_mime_type


def _auto_label(snippet: str, max_words: int = 5) -> str:
    """Generate a short label from the first few words of a snippet."""
    words = snippet.split()[:max_words]
    label = " ".join(words)
    if len(words) < len(snippet.split()):
        label += "..."
    return label


class AddCommand:
    """Locate a snippet at a URL and append it as a fragment to a YAML file.

    Reuses an existing source entry with the same URL or creates one. Accepts
    ``--label <name>`` and ``--refresh`` (re-fetch, bypassing the HTTP cache).
    """

    def __init__(self, http_client: object) -> None:
        self.http_client = http_client

    def run(self, args: list[str] | None = None) -> None:
        """Locate the snippet and write it into the YAML sources file."""
        if args is None:
            args = sys.argv[1:]

        # Parse --refresh flag (re-fetch the URL, bypassing the HTTP cache)
        force, args = pop_flag(args, "--refresh")

        # Parse --label flag
        label = None
        if "--label" in args:
            idx = args.index("--label")
            if idx + 1 < len(args):
                label = args[idx + 1]
                args = args[:idx] + args[idx + 2:]
            else:
                print("Error: --label requires a value", file=sys.stderr)
                sys.exit(1)

        if len(args) < 3:
            print("Usage: apysource add <sources.yaml> <url> <snippet> "
                  "[--label name] [--refresh]",
                  file=sys.stderr)
            sys.exit(1)

        yaml_path = Path(args[0])
        url = args[1]
        snippet = args[2]

        if label is None:
            label = _auto_label(snippet)

        # Locate the snippet
        content_type, title, result = find_snippet(
            self.http_client, url, snippet, force=force)
        key = _targetter_key(result)

        print(f"  Located: {result.format_name} → {result.locator}",
              file=sys.stderr)
        if result.matched_text:
            preview = result.matched_text[:120]
            if len(result.matched_text) > 120:
                preview += "..."
            print(f"  Matched: {preview}", file=sys.stderr)

        # Build the fragment dict
        frag = {"label": label, key: result.locator, "snippet": snippet}

        # Load or create the YAML file
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "sources" not in data:
                data = {"sources": []}
        else:
            data = {"sources": []}

        # Find existing source by URL, or create one
        source_entry = None
        for s in data["sources"]:
            if s.get("url") == url:
                source_entry = s
                break

        if source_entry is None:
            source_label = title or url
            source_entry = {
                "label": source_label,
                "url": url,
                "type": normalize_mime_type(content_type),
                "fragments": [],
            }
            data["sources"].append(source_entry)
            print(f"  Added new source: {url}", file=sys.stderr)

        if "fragments" not in source_entry:
            source_entry["fragments"] = []

        source_entry["fragments"].append(frag)

        # Write back
        yaml_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True,
                      sort_keys=False),
            encoding="utf-8",
        )

        print(f"  Added fragment \"{label}\" to {yaml_path}", file=sys.stderr)
