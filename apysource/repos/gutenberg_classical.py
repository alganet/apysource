# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Classical text abbreviation matching for Gutenberg texts."""

import re

from apysource.sections import roman_to_int


def find_chapter(location: str, chapters: list[dict]) -> dict | None:
    """Match classical text abbreviations like 'Aen. VI', 'Od. 9', 'Theog. 116-132'."""
    classical = re.match(
        r"(Aen|Od|Theog|Met|Metamorphoses|Homeric Hymn)[.\s]+([IVXLCDM\d]+)",
        location, re.IGNORECASE
    )
    if not classical:
        return None

    ref = classical.group(2)
    ref_num = roman_to_int(ref) if ref.isalpha() else None

    for candidate in chapters:
        title = candidate.get("title", "").lower()
        if ref_num:
            if re.search(rf"book\s+{re.escape(ref)}\b", title, re.IGNORECASE):
                return candidate
        elif ref.isdigit():
            if re.search(rf"book\s+{ref}\b", title):
                return candidate

    return None
