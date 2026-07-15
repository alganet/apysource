# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for name → source patterns."""

import pytest

from apysource.api import default_registry
from apysource.patterns import (
    DEFAULT_PATTERNS,
    SHIPPED_REPOS,
    complete,
    compile_patterns,
    mint_source,
    patterns_from_data,
)
from apysource.repos import RepoRegistry
from apysource.repos.mdn import MdnRepo

MDN = {"match": r"^MDN (?P<page>.+)$",
       "source": {"url": "https://developer.mozilla.org/en-US/docs/{page}"}}


# ── Minting ──────────────────────────────────────────────────────────────

def test_the_shipped_pattern_mints_an_rfc():
    """A project whose every citation names an RFC writes no sources file at all."""
    assert mint_source("RFC 9110") == {
        "url": "https://www.rfc-editor.org/rfc/rfc9110.txt",
        "type": "text/plain",
    }


def test_a_name_no_pattern_claims_is_none_not_a_guess():
    assert mint_source("Fetch") is None
    assert mint_source("RFC 9110 bis") is None      # anchored: not a prefix match


def test_a_minted_source_carries_no_label():
    """The name is the label, and it belongs to whoever asked."""
    assert "label" not in mint_source("RFC 9110")


def test_the_files_patterns_beat_the_shipped_ones():
    """Naming RFC 9110 yourself — as HTML, from datatracker — has to win."""
    patterns = patterns_from_data({"patterns": [
        {"match": r"^RFC (?P<n>\d+)$",
         "source": {"url": "https://datatracker.ietf.org/doc/html/rfc{n}",
                    "type": "text/html"}},
    ]}, "sources.yaml")

    assert mint_source("RFC 9110", patterns)["url"].startswith("https://datatracker")
    assert len(patterns) == len(DEFAULT_PATTERNS) + 1  # the shipped one is still there


# ── The entry wins, key by key ───────────────────────────────────────────

def test_an_entry_key_beats_the_template():
    """A family knows a media type. It does not know that *this* one is HTML."""
    entry = {"label": "RFC 9110", "type": "text/html", "title": "HTTP Semantics"}
    completed = complete(entry, DEFAULT_PATTERNS)

    assert completed["url"] == "https://www.rfc-editor.org/rfc/rfc9110.txt"
    assert completed["type"] == "text/html"       # the entry's, not the pattern's
    assert completed["title"] == "HTTP Semantics"


def test_completing_never_mutates_the_entry():
    """The data belongs to the caller, who walks it again after we accept it."""
    entry = {"label": "RFC 9110"}
    complete(entry, DEFAULT_PATTERNS)
    assert entry == {"label": "RFC 9110"}


def test_an_entry_with_a_url_is_left_alone():
    entry = {"label": "RFC 9110", "url": "https://example.org/x"}
    assert complete(entry, DEFAULT_PATTERNS)["url"] == "https://example.org/x"


# ── A repo's own family, and the drift it could hide ─────────────────────

def test_the_shipped_families_are_rfc_plus_every_repos_own():
    """`RFC` is declared in patterns.py because no repo claims rfc-editor — that
    gap is exactly what patterns are *for*. Every other shipped family is declared
    by the repo that fetches it, because how you name an MDN page is MDN's
    knowledge and patterns.py has none."""
    matches = {p.pattern.pattern for p in DEFAULT_PATTERNS}

    assert r"^RFC (?P<n>\d+)$" in matches
    for repo in SHIPPED_REPOS:
        assert repo.family() is not None, f"{repo.NAME} declares no name family"
        assert repo.NAME_MATCH in matches


@pytest.mark.parametrize("repo_cls", SHIPPED_REPOS, ids=lambda r: r.NAME)
def test_a_repos_family_mints_a_url_that_repo_itself_claims(repo_cls):
    """The test that makes one fact in two places safe.

    A family states its host twice — once in `CANONICAL_URL`, a template that
    *builds* a url, and once in `url_pattern`, a regex that *claims* one. That is
    not laziness, and it cannot be deduplicated: the matchers carry knowledge a
    template cannot express. `(?i:en-US)` accepts `en-us` while excluding
    `/fr/docs/`; `[^#?\\s]+` drops the anchor; Gutenberg's `(\\d+)` admits only an
    ebook number, and matches without the `www.` its canonical url carries. Derive
    either from the other and all three regress.

    So the two halves are *bound* here instead. Mint the family's own example, and
    the repo that declared it must claim what came out — and key it, all the way
    down to the document it will read. Edit one half, forget the other, and this
    fails. Do not "fix" the duplication; this test is the reason it is safe.

    The registry is the default-wired one, so this ties the class attributes to
    what `defaults.toml` actually ships.
    """
    name = repo_cls.NAME_EXAMPLE
    assert name, f"{repo_cls.NAME} declares a family but no example to check it with"

    minted = mint_source(name)
    assert minted is not None, f"no shipped family claims {name!r}"

    repo = default_registry().get_repo(minted["url"])

    assert isinstance(repo, repo_cls), (
        f"{repo_cls.NAME} mints {minted['url']!r} from {name!r}, but the default "
        f"registry hands that url to {type(repo).__name__}. CANONICAL_URL and "
        f"url_pattern have drifted apart."
    )
    assert repo.url_to_key(minted["url"]) is not None, (
        f"{repo_cls.NAME} claims its own minted url but cannot key it: url_pattern "
        f"matches the host, and not the path CANONICAL_URL templated."
    )


def test_a_gutenberg_name_that_is_not_an_ebook_number_names_no_book():
    """The family says `\\d+` for the same reason `url_pattern` does."""
    assert mint_source("Gutenberg Moby-Dick") is None
    assert mint_source("Gutenberg 2701")["url"] == \
        "https://www.gutenberg.org/ebooks/2701"


def test_an_archive_name_with_a_slash_names_no_item():
    """The failure the drift test above *cannot* see, and the limit of binding a
    family by example.

    `NAME_MATCH` was `.+`, so `Archive foo/bar` minted a url ArchiveRepo happily
    claimed — and then keyed as `foo`, because `url_pattern`'s `(.+?)(?:/|...)`
    stops at the first slash. The citation verified against a different item, with
    nothing anywhere to say so. The drift test passed throughout, because its one
    example has no slash in it. An example binds the two halves only where the
    example goes; a family has to say what it does *not* claim, too.
    """
    assert mint_source("Archive foo/bar") is None
    assert mint_source("Archive onthemoralsofplut00plut")["url"] == \
        "https://archive.org/details/onthemoralsofplut00plut"


def test_a_user_pattern_can_name_a_repo_backed_family_too():
    """Nothing is privileged about a shipped family. A minted url is written to
    schema:url by the ordinary loader, so a url a *user's* pattern built is claimed
    by MdnRepo exactly as a hand-written one is. Patterns compose with repos
    because they never had to know repos exist."""
    patterns = patterns_from_data({"patterns": [MDN]}, "sources.yaml")
    url = mint_source("MDN Web/HTTP/Reference/Headers/Origin", patterns)["url"]

    registry = RepoRegistry([MdnRepo(
        url_pattern=r"developer\.mozilla\.org/(?i:en-US)/docs/([^#?\s]+)",
        base_url="https://raw.githubusercontent.com/mdn/content/main/files/en-us",
    )])
    repo = registry.get_repo(url)

    assert isinstance(repo, MdnRepo)
    # And it parsed the minted url the whole way down to the file it will read.
    assert repo.url_to_key(url) == "en-us/web/http/reference/headers/origin"


# ── Refused at load, not at 404 (the validation tranche) ─────────────────

def test_a_template_field_the_pattern_never_captures_is_refused_now():
    """The best refusal in the module: it is knowable at load, and the
    alternative is a fetch against a url with a literal brace in it."""
    with pytest.raises(ValueError, match=r"\{number\}, which"):
        compile_patterns([{"match": r"^RFC (?P<n>\d+)$",
                           "source": {"url": "https://example.org/{number}"}}])


def test_the_refusal_names_what_the_pattern_did_capture():
    with pytest.raises(ValueError, match="Captured: n"):
        compile_patterns([{"match": r"^RFC (?P<n>\d+)$",
                           "source": {"url": "https://example.org/{number}"}}])


def test_a_template_with_a_lone_brace_is_refused_at_load():
    """The check reads the template with `string.Formatter`, the same reader
    `str.format` will use. A `\\{(\\w+)\\}` regex let this through, and the failure
    then arrived at mint time — the exact deferral this check exists to prevent."""
    with pytest.raises(ValueError, match="not a usable template"):
        compile_patterns([{"match": r"^X (?P<n>\d+)$",
                           "source": {"url": "https://e.org/{n}/{"}}])


def test_an_escaped_brace_is_a_literal_brace_and_not_a_field():
    """`{{lit}}` formats to `{lit}` and captures nothing. The old regex saw a
    field named `lit` and refused a template that was perfectly correct."""
    patterns = compile_patterns([{"match": r"^Z (?P<a>\d+)$",
                                  "source": {"url": "https://e.org/{a}/{{lit}}"}}])

    assert mint_source("Z 5", patterns)["url"] == "https://e.org/5/{lit}"


def test_an_optional_group_that_did_not_match_is_absent_not_the_word_None():
    """`groupdict` hands back None for a group that did not participate, and
    `str.format` renders that as four letters. `.../rfc9110None.txt` was minted,
    and fetched, and reported as a dead link."""
    patterns = compile_patterns([{"match": r"^Y (?P<a>\d+)(?P<b>x)?$",
                                  "source": {"url": "https://e.org/{a}{b}"}}])

    assert mint_source("Y 7", patterns)["url"] == "https://e.org/7"
    assert mint_source("Y 7x", patterns)["url"] == "https://e.org/7x"


def test_a_bad_regex_is_refused():
    with pytest.raises(ValueError, match="bad regex"):
        compile_patterns([{"match": r"^RFC (?P<n>\d+$",
                           "source": {"url": "https://example.org/{n}"}}])


def test_patterns_must_be_a_list():
    with pytest.raises(ValueError, match="must be a list"):
        compile_patterns({"match": "^x$"})


def test_a_pattern_must_be_a_mapping():
    with pytest.raises(ValueError, match="must be a mapping"):
        compile_patterns(["^RFC (?P<n>d+)$"])


def test_an_unknown_pattern_key_is_refused():
    with pytest.raises(ValueError, match="unknown key 'sources'"):
        compile_patterns([{"match": "^x$", "sources": {"url": "https://e.org/"}}])


@pytest.mark.parametrize("entry", [
    {"match": r"^RFC (?P<n>\d+)$"},
    {"source": {"url": "https://example.org/x"}},
])
def test_a_pattern_needs_both_halves(entry):
    with pytest.raises(ValueError, match="needs both 'match' and 'source'"):
        compile_patterns([entry])


@pytest.mark.parametrize("source", ["https://example.org/", {"type": "text/plain"}])
def test_a_template_without_a_url_mints_nothing(source):
    with pytest.raises(ValueError, match="mapping with a 'url'"):
        compile_patterns([{"match": "^x$", "source": source}])


def test_an_unknown_template_key_is_refused():
    """A key the source loader would refuse later is refused now."""
    with pytest.raises(ValueError, match="unknown key 'typ'"):
        compile_patterns([{"match": "^x$",
                           "source": {"url": "https://e.org/", "typ": "text/plain"}}])


def test_a_template_key_the_loader_reserves_is_refused():
    """`label` comes from the name; `fragments` are a citation's business."""
    with pytest.raises(ValueError, match="unknown key 'fragments'"):
        compile_patterns([{"match": "^x$",
                           "source": {"url": "https://e.org/", "fragments": []}}])


def test_a_template_url_written_as_a_list_is_refused():
    with pytest.raises(ValueError, match="single piece of text"):
        compile_patterns([{"match": "^x$", "source": {"url": ["https://e.org/"]}}])


def test_the_refusal_names_the_pattern_by_position():
    with pytest.raises(ValueError, match=r"sources\.yaml: patterns\[2\]"):
        compile_patterns([MDN, {"match": "^x$", "source": {}}], "sources.yaml")
