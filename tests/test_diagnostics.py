# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.diagnostics — explaining a failed snippet."""

import time

from apysource.diagnostics import closest_match, diagnose, explain_snippet_failure

# The real sentence from RFC 9112 § 3.2, and the quote a human wrote from
# memory while citing it — the parenthetical is the bit that got dropped.
RFC_9112 = (
    "A client MUST send a Host header field (Section 7.2 of [HTTP]) in all "
    "HTTP/1.1 request messages. If the target URI includes an authority "
    "component, then a client MUST send a field value for Host that is "
    "identical to that authority component."
)
MISQUOTE = (
    "A client MUST send a Host header field in all HTTP/1.1 request messages."
)


class TestClosestMatch:
    def test_finds_the_near_miss_passage(self):
        d = closest_match(MISQUOTE, RFC_9112)
        assert d is not None
        assert d.percent >= 80
        assert "Section 7.2 of [HTTP]" in d.source_text

    def test_names_the_words_the_source_has_and_the_quote_lacks(self):
        d = closest_match(MISQUOTE, RFC_9112)
        assert " ".join(d.extra) == "(Section 7.2 of [HTTP])"

    def test_unrelated_text_has_no_close_match(self):
        assert closest_match(
            "The quick brown fox jumps over the lazy dog entirely", RFC_9112
        ) is None

    def test_empty_inputs_have_no_match(self):
        assert closest_match("", RFC_9112) is None
        assert closest_match(MISQUOTE, "") is None

    def test_truncation_marker_never_enters_a_match(self):
        d = closest_match(MISQUOTE, RFC_9112 + "\n... [4200 more chars]")
        assert d is not None
        assert "more chars" not in d.source_text


class TestNeverLiesAboutTheSource:
    """A hint that sends the author hunting for a word already there is
    worse than no hint. Every one of these was a real defect."""

    def test_does_not_claim_a_present_word_is_missing(self):
        d = closest_match(MISQUOTE, RFC_9112)
        # The leading "A" is right there in the source; only the
        # parenthetical is genuinely absent from the quote.
        assert d.missing == []

    def test_picks_the_whole_passage_not_a_fragment_of_it(self):
        """Scoring a trimmed span rewards cutting away whatever failed to
        match, so a fragment of the sentence outscored the sentence — and
        the words it cut off were then reported missing from the source."""
        d = closest_match(MISQUOTE, RFC_9112)
        assert d.source_text.endswith("request messages.")
        assert d.missing == []

    def test_punctuation_does_not_make_a_word_go_missing(self):
        """'URI' is present; the source merely follows it with a period."""
        d = closest_match(
            "A resource MUST be identifed by a URI",
            "called a resource. A resource MUST be identified by a URI.",
        )
        assert "URI" not in d.missing
        assert d.missing == ["identifed"]

    def test_identical_text_is_not_a_case_difference(self):
        """It reported 'differs only in case' for byte-identical strings."""
        d = closest_match("hello world and so on", "hello world and so on")
        assert d is None or d.kind == ""

    def test_a_different_sentence_is_not_a_whitespace_difference(self):
        """Folding across word boundaries let 'rat elimiter' pass as
        'rate limiter' — a different sentence, not a typo."""
        d = closest_match(
            "The rat elimiter",
            "The rate limiter throttles requests per second for each client",
        )
        assert d is None or d.kind == ""

    def test_snake_case_is_not_inline_markup(self):
        """Stripping '_' reported get_text as a marked-up 'gettext'."""
        d = closest_match(
            "Call gettext() then runchecks()",
            "Call get_text() then run_checks() to verify the catalogue.",
        )
        assert d is None or "markup" not in d.kind


class TestTypographicDifferences:
    """Near-misses worth naming rather than diffing word by word."""

    def test_case_only(self):
        d = closest_match(RFC_9112.lower(), RFC_9112)
        assert d.kind == "differs only in case"
        assert d.source_text == RFC_9112

    def test_inline_markup_only(self):
        """The Fetch spec case: backticks survive into the extracted text."""
        d = closest_match(
            "The Origin request header indicates the origin.",
            "The `Origin` request header indicates the origin.",
        )
        assert "inline markup" in d.kind
        assert "`Origin`" in d.source_text

    def test_punctuation_only(self):
        d = closest_match(
            "the server must not send a body",
            "the server must not send a body.",
        )
        assert d.kind == "differs only in punctuation"

    def test_case_and_markup_together(self):
        """Each kind was tested alone, so a quote wrong in two ways at once
        fell through to a word diff that called present words missing."""
        d = closest_match(
            "the Content-Length header field is required",
            "The `Content-Length` header field is required for this.",
        )
        assert d.kind == "differs only in case, punctuation or markup"
        assert d.missing == []

    def test_a_real_difference_is_not_called_typographic(self):
        assert closest_match(MISQUOTE, RFC_9112).kind == ""


class TestRendering:
    def test_produces_a_readable_block(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112)
        assert lines[0].startswith("closest match (")
        assert any("that passage also has:" in ln for ln in lines)

    def test_names_the_region_searched(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112, where="§ 3.2")
        assert "§ 3.2" in lines[0]

    def test_typographic_slip_shows_what_to_paste_not_a_diff(self):
        lines = explain_snippet_failure(RFC_9112.lower(), RFC_9112)
        joined = "\n".join(lines)
        assert "differs only in case" in joined
        assert RFC_9112 in joined
        assert "not in that passage" not in joined

    def test_silent_when_nothing_is_close(self):
        assert explain_snippet_failure("totally unrelated wording", RFC_9112) == []

    def test_diagnose_carries_the_region(self):
        d = diagnose(MISQUOTE, RFC_9112, where="§ 3.2")
        assert d.where == "§ 3.2"


class TestScale:
    def test_a_long_quote_against_a_long_document_is_fast(self):
        """Scoring in character space took 37 seconds for this."""
        source = ("The quick brown fox jumps over the lazy dog. " * 2300)[:100000]
        snippet = "Lorem ipsum dolor sit amet consectetur " * 128  # ~5000 ch

        started = time.perf_counter()
        closest_match(snippet, source)
        assert time.perf_counter() - started < 2.0

    def test_the_rendered_passage_is_bounded(self):
        """A block quote diffed in full is a wall no one reads.

        The cap is a rendering concern: the diagnosis itself keeps the whole
        passage, so a machine-readable report is not truncated, and the
        similarity ratio is not computed against a chopped passage.
        """
        source = " ".join(f"word{i}" for i in range(4000))
        snippet = " ".join(f"word{i}" for i in range(500, 900)) + " intruder"

        d = closest_match(snippet, source)
        assert d is not None
        assert len(d.source_text.split()) > 60

        lines = explain_snippet_failure(snippet, source)
        assert all(len(ln.split()) <= 64 for ln in lines)
        assert lines[1].endswith("...")
