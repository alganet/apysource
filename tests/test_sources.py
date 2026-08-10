# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for the sources file read back as data, with names resolved."""

import pytest

from apysource.sources import load_sources, sources_from_data

RFC_URL = "https://www.rfc-editor.org/rfc/rfc9110.html"


def _write(tmp_path, text):
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ── Resolving a name ─────────────────────────────────────────────────────

def test_no_sources_file_is_fine():
    """A project whose every citation names an `RFC NNNN` never writes the file.
    The shipped patterns are still there, so the name still resolves."""
    sources = load_sources(None)

    assert sources.entries == {}
    assert sources.resolve("RFC 9110")["url"] == RFC_URL


def test_a_name_in_no_entry_at_all_still_resolves():
    """The case a citation generator lives in: a comment names RFC 9110 and no
    sources file has ever heard of it."""
    sources = sources_from_data({"sources": []})
    minted = sources.resolve("RFC 9110")

    assert minted == {"label": "RFC 9110", "url": RFC_URL}


def test_an_entry_beats_a_pattern():
    sources = sources_from_data({"sources": [
        {"label": "RFC 9110", "url": "https://datatracker.ietf.org/doc/html/rfc9110",
         "type": "text/html"},
    ]})

    assert sources.resolve("RFC 9110")["url"].startswith("https://datatracker")


def test_a_source_set_never_aliases_the_data_it_was_given():
    """One return type, one ownership rule. `complete` handed back the caller's own
    dict when the entry already had a url, and a fresh one when it minted — so a
    consumer editing what it was given was silently editing the document it had
    just read, but only sometimes."""
    data = {"sources": [
        {"label": "Written", "url": "https://example.org/x"},
        {"label": "RFC 9110"},
    ]}
    sources = sources_from_data(data)

    sources.entries["Written"]["title"] = "scribbled on"
    sources.entries["RFC 9110"]["title"] = "scribbled on"

    assert data["sources"][0] == {"label": "Written", "url": "https://example.org/x"}
    assert data["sources"][1] == {"label": "RFC 9110"}


def test_an_unresolvable_name_is_refused_not_guessed():
    """None, never a guess. The caller holds the file and the line, and only it
    can say why it was asking."""
    assert sources_from_data({"sources": []}).resolve("Fetsh") is None


# ── Entries come back URL-complete ───────────────────────────────────────

def test_a_url_less_entry_comes_back_with_its_url(tmp_path):
    """The property a generator depends on: it emits these entries into a file of
    its own, which carries no `patterns:` block. An entry that arrived without a
    url would be written without one, and the file would not load."""
    sources = load_sources(_write(tmp_path, """\
sources:
  - label: RFC 9110
    fragments:
      - label: host_header
        snippet: "A client MUST send a Host header field"
"""))

    entry = sources.entries["RFC 9110"]
    assert entry["url"] == RFC_URL
    # No `type`: the repo that claims this url decides which rendition answers
    # for it, and it decides that after this entry has been completed.
    assert "type" not in entry
    assert entry["fragments"][0]["label"] == "host_header"   # and it kept its own


def test_entries_load_with_their_hand_written_fragments(tmp_path):
    """The whole source vocabulary survives — a selector-only fragment, an ISBN,
    a publisher. The things a pattern cannot say cost nothing."""
    sources = load_sources(_write(tmp_path, """\
sources:
  - label: Moby-Dick
    url: https://www.gutenberg.org/ebooks/2701
    publisher: Harper & Brothers
    fragments:
      - label: by hand
        selector: "#chapter1"
        snippet: "Call me Ishmael."
"""))

    entry = sources.entries["Moby-Dick"]
    assert entry["publisher"] == "Harper & Brothers"
    assert entry["fragments"][0]["selector"] == "#chapter1"


def test_the_files_own_patterns_are_carried(tmp_path):
    sources = load_sources(_write(tmp_path, """\
patterns:
  - match: '^W3C (?P<slug>[a-z0-9-]+)$'
    source: {url: "https://www.w3.org/TR/{slug}/", type: text/html}
sources: []
"""))

    assert sources.resolve("W3C css-color-4")["url"] == \
        "https://www.w3.org/TR/css-color-4/"


# ── Validation is the loader's, not a second copy of it ──────────────────

def test_a_malformed_sources_file_is_refused_by_the_real_loader(tmp_path):
    """`snipet:` must not load without a murmur here either. There is one
    definition of what a sources file means, and this is not it."""
    with pytest.raises(ValueError, match="unknown key"):
        load_sources(_write(tmp_path, """\
sources:
  - label: RFC 9110
    url: https://www.rfc-editor.org/rfc/rfc9110.html
    fragments:
      - label: x
        snipet: "typo"
"""))


def test_a_name_no_pattern_claims_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="no pattern mints one"):
        load_sources(_write(tmp_path, "sources:\n  - label: Fetch\n"))
