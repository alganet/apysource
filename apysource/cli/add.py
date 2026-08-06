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
from apysource.patterns import complete, patterns_from_data


class AddError(Exception):
    """The file, or the name, is not something to guess at."""


def _load(yaml_path: Path) -> dict:
    """The sources file, or a new empty one. Patterns and all.

    A file that exists but is not a sources file is **refused**, not started
    over: this command ends by writing the whole document back, so treating an
    unreadable one as empty would silently replace it — a typo'd ``source:`` (or
    a file that is only a ``patterns:`` block) would cost the author everything
    else in it.
    """
    if not yaml_path.exists():
        return {"sources": []}

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if data is None:
        return {"sources": []}
    if not isinstance(data, dict) or "sources" not in data:
        raise AddError(
            f"{yaml_path} exists but has no top-level 'sources' list, so it is "
            f"not a sources file. `add` rewrites the whole document, and it will "
            f"not overwrite something it cannot read.",
        )
    return data


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
            print("Usage: apysource add <sources.yaml> <url-or-name> <snippet> "
                  "[--label name] [--refresh]",
                  file=sys.stderr)
            sys.exit(1)

        yaml_path = Path(args[0])
        target = args[1]
        snippet = args[2]

        if label is None:
            label = _auto_label(snippet)

        # The file has to be read before the fetch now, not after: it is where the
        # patterns are, and without them a name is not yet a URL.
        #
        # A file we will not touch, or a `patterns:` block that does not compile,
        # is the author's mistake and not a crash: one line they can act on, and
        # stop — rather than a traceback out of a command that wrote nothing.
        try:
            data = _load(yaml_path)
        except (AddError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        # A name, not a URL — `apysource add sources.yaml "RFC 9110" "..."`.
        name = None if "://" in target else target

        # The entry is found *before* the URL is resolved, and that order is the
        # whole point. A name is matched by label, because the entry it makes
        # carries no url to match on — matching by url would append a second
        # `RFC 9110` on every add, and two entries with one identity is precisely
        # what the loader refuses.
        source_entry = None
        for s in data["sources"]:
            if (s.get("label") == name) if name else (s.get("url") == target):
                source_entry = s
                break

        if name is None:
            url = target
        else:
            # `complete`, not `mint_source`: the same rule `check` will apply to
            # the file this command is about to write, which is that **the entry
            # wins**. A sources file that pins `RFC 9110` to datatracker is asking
            # for datatracker, and minting rfc-editor here would locate the snippet
            # in one document and write the targetter into an entry naming another.
            try:
                patterns = patterns_from_data(data, str(yaml_path))
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)

            resolved = complete(source_entry or {"label": name}, patterns)
            if resolved is None:
                tried = ", ".join(repr(p.pattern.pattern) for p in patterns)
                print(f"Error: no pattern mints a url from {name!r}. Pass a url, "
                      f"or add a 'patterns:' entry that claims it. Tried: {tried}",
                      file=sys.stderr)
                sys.exit(1)
            url = resolved["url"]
            if source_entry is None or not source_entry.get("url"):
                print(f"  Minted:  {name} → {url}", file=sys.stderr)
            else:
                print(f"  Pinned:  {name} → {url}  (the entry's own url)",
                      file=sys.stderr)

        # Locate the snippet
        content_type, title, result = find_snippet(
            self.http_client, url, snippet, force=force)
        key = _targetter_key(result)

        if key is None:
            print("  Located: document-scoped — the quote locates itself",
                  file=sys.stderr)
        else:
            print(f"  Located: {result.format_name} → {result.locator}",
                  file=sys.stderr)
        if result.matched_text:
            preview = result.matched_text[:120]
            if len(result.matched_text) > 120:
                preview += "..."
            print(f"  Matched: {preview}", file=sys.stderr)

        # Build the fragment dict; a document-scoped one carries no targetter
        # key, and the snippet locates itself.
        frag = {"label": label, "snippet": snippet}
        if key is not None:
            frag = {"label": label, key: result.locator, "snippet": snippet}

        if source_entry is None:
            if name is not None:
                # Only the name. The pattern supplies the url and the type, and
                # writing the resolved url back would defeat the point of naming
                # a family: the file would stop being about `RFC 9110` and start
                # being about one rfc-editor link.
                source_entry = {"label": name, "fragments": []}
            else:
                source_entry = {
                    "label": title or url,
                    "url": url,
                    "type": normalize_mime_type(content_type),
                    "fragments": [],
                }
            data["sources"].append(source_entry)
            print(f"  Added new source: {name or url}", file=sys.stderr)

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
