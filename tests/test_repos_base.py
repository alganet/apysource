# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Tests for apysource.repos._base shared utilities."""

from apysource.repos._base import (
    extract_line_range,
    extract_content_with_fallback,
    slugify,
)


# ── extract_line_range ───────────────────────────────────────────────────

def test_extract_line_range_valid():
    """Extracts correct line range from text."""
    text = "line1\nline2\nline3\nline4\nline5"
    result = extract_line_range(text, "lines:2-4")
    assert result == "line2\nline3\nline4"


def test_extract_line_range_no_match():
    """Returns None when location has no lines: pattern."""
    text = "line1\nline2\nline3"
    assert extract_line_range(text, "chapter_one") is None


def test_extract_line_range_out_of_bounds():
    """Out-of-bounds range returns available lines without error."""
    text = "line1\nline2"
    result = extract_line_range(text, "lines:1-100")
    assert result == "line1\nline2"


# ── slugify ──────────────────────────────────────────────────────────────

def test_slugify_basic():
    """Basic slugification: lowercase + spaces to underscores."""
    assert slugify("Hello World") == "hello_world"


def test_slugify_empty():
    """Empty string returns empty string."""
    assert slugify("") == ""


# ── extract_content_with_fallback ────────────────────────────────────────

def test_extract_content_with_fallback_line_range():
    """Line range takes priority over small-file fallback."""
    text = "line1\nline2\nline3"
    result = extract_content_with_fallback(text, "lines:2-2")
    assert result == "line2"


def test_extract_content_with_fallback_small_file():
    """Small file without line range returns full text."""
    text = "short text"
    result = extract_content_with_fallback(text, "chapter_one", threshold=5000)
    assert result == "short text"


def test_extract_content_with_fallback_large_file_no_range():
    """Large file without line range returns empty string."""
    text = "x" * 6000
    result = extract_content_with_fallback(text, "chapter_one", threshold=5000)
    assert result == ""
