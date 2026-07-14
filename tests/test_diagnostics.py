# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.diagnostics — explaining a failed snippet."""

from apysource.diagnostics import (
    closest_match,
    describe_difference,
    explain_snippet_failure,
    strip_truncation_marker,
)

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
        match = closest_match(MISQUOTE, RFC_9112)
        assert match is not None
        assert match.percent >= 80
        assert "Section 7.2 of [HTTP]" in match.text

    def test_unrelated_text_has_no_close_match(self):
        match = closest_match(
            "The quick brown fox jumps over the lazy dog entirely",
            RFC_9112,
        )
        assert match is None

    def test_empty_inputs_have_no_match(self):
        assert closest_match("", RFC_9112) is None
        assert closest_match(MISQUOTE, "") is None

    def test_truncation_marker_never_enters_a_match(self):
        source = RFC_9112 + "\n... [4200 more chars]"
        match = closest_match(MISQUOTE, source)
        assert match is not None
        assert "more chars" not in match.text


class TestMechanicalDifferences:
    """Near-misses worth naming, rather than diffing word by word."""

    def test_case_only(self):
        match = closest_match(RFC_9112.lower(), RFC_9112)
        assert match is not None
        assert match.kind == "differs only in case"

    def test_whitespace_only(self):
        wrapped = RFC_9112.replace(" ", "\n  ", 3)
        match = closest_match(wrapped, RFC_9112)
        assert match is not None
        assert match.kind in (
            "differs only in whitespace",
            "differs only in case",
        )

    def test_inline_markup_only(self):
        """The Fetch spec case: backticks survive into the extracted text."""
        source = "The `Origin` request header indicates the origin."
        snippet = "The Origin request header indicates the origin."
        match = closest_match(snippet, source)
        assert match is not None
        assert "inline markup" in match.kind

    def test_a_real_difference_is_not_called_mechanical(self):
        match = closest_match(MISQUOTE, RFC_9112)
        assert match is not None
        assert match.kind == ""


class TestDescribeDifference:
    def test_names_the_words_the_citation_is_missing(self):
        lines = describe_difference(MISQUOTE, RFC_9112)
        joined = "\n".join(lines)
        assert "- " in joined and "+ " in joined
        assert "present in source:" in joined
        assert "(Section" in joined

    def test_identical_text_reports_no_delta(self):
        lines = describe_difference(MISQUOTE, MISQUOTE)
        joined = "\n".join(lines)
        assert "missing from source" not in joined
        assert "present in source" not in joined

    def test_context_around_the_quote_is_not_a_discrepancy(self):
        """Words the source has around the quote are not missing from it."""
        lines = describe_difference(
            "the middle words here",
            "leading context the middle words here trailing context",
        )
        joined = "\n".join(lines)
        assert "missing from source" not in joined
        assert "present in source" not in joined


class TestNoFalseMissingWords:
    """A hint that lies about the source is worse than no hint."""

    def test_does_not_claim_a_word_is_missing_when_it_is_present(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112)
        joined = "\n".join(lines)

        # "A client MUST send..." — the leading "A" is right there in the
        # source. Only the parenthetical is genuinely absent from the quote.
        assert "missing from source: A" not in joined
        assert "present in source:" in joined
        assert "(Section" in joined

    def test_reports_only_the_genuinely_absent_words(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112)
        missing = [ln for ln in lines if "missing from source" in ln]
        assert missing == []


class TestExplainSnippetFailure:
    def test_produces_a_readable_block(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112)
        assert lines
        assert lines[0].startswith("closest match (")
        assert "% similar)" in lines[0]

    def test_names_the_region_searched(self):
        lines = explain_snippet_failure(MISQUOTE, RFC_9112, where="§ 3.2")
        assert "§ 3.2" in lines[0]

    def test_says_when_the_difference_is_only_case(self):
        lines = explain_snippet_failure(RFC_9112.lower(), RFC_9112)
        assert "differs only in case" in lines[0]

    def test_a_mechanical_difference_shows_what_to_paste_not_a_diff(self):
        """The words are right; a word diff would just relist the sentence."""
        lines = explain_snippet_failure(RFC_9112.lower(), RFC_9112)
        joined = "\n".join(lines)
        assert "source says: " in joined
        assert RFC_9112 in joined
        assert "missing from source" not in joined

    def test_silent_when_nothing_is_close(self):
        assert explain_snippet_failure("totally unrelated wording here",
                                       RFC_9112) == []


class TestStripTruncationMarker:
    def test_removes_the_marker(self):
        assert strip_truncation_marker("body\n... [42 more chars]") == "body"

    def test_leaves_ordinary_text_alone(self):
        assert strip_truncation_marker("body ... more") == "body ... more"
