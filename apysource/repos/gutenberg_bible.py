# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Bible-specific location matching and verse extraction for Gutenberg texts."""

import re

# Bible book abbreviation -> full name (lowercase for matching)
BIBLE_BOOKS = {
    "gen": "genesis", "ex": "exodus", "lev": "leviticus",
    "num": "numbers", "deut": "deuteronomy", "josh": "joshua",
    "judg": "judges", "ruth": "ruth",
    "1 sam": "samuel", "2 sam": "samuel",
    "1 kgs": "kings", "2 kgs": "kings",
    "1 chr": "chronicles", "2 chr": "chronicles",
    "esth": "esther", "job": "job", "ps": "psalms",
    "prov": "proverbs", "eccl": "ecclesiastes",
    "song": "song of solomon", "isa": "isaiah", "jer": "jeremiah",
    "lam": "lamentations", "ezek": "ezekiel", "dan": "daniel",
    "hos": "hosea", "joel": "joel", "amos": "amos",
    "obad": "obadiah", "jonah": "jonah", "mic": "micah",
    "nah": "nahum", "hab": "habakkuk", "zeph": "zephaniah",
    "hag": "haggai", "zech": "zechariah", "mal": "malachi",
    "matt": "matthew", "mark": "mark", "luke": "luke",
    "john": "john", "acts": "acts",
    "rom": "romans", "1 cor": "corinthians", "2 cor": "corinthians",
    "gal": "galatians", "eph": "ephesians", "phil": "philippians",
    "col": "colossians", "1 thess": "thessalonians", "2 thess": "thessalonians",
    "1 tim": "timothy", "2 tim": "timothy",
    "titus": "titus", "phlm": "philemon", "heb": "hebrews",
    "jas": "james", "1 pet": "peter", "2 pet": "peter",
    "1 john": "john", "2 john": "john", "3 john": "john",
    "jude": "jude", "rev": "revelation",
}


def find_chapter(location: str, chapters: list[dict]) -> dict | None:
    """Match a Bible-style location like 'Gen 3:1-6' to a chapter."""
    m = re.match(r"(\d?\s*[a-zA-Z]+)", location)
    if not m:
        return None
    abbrev = m.group(1).strip().lower()
    full_name = BIBLE_BOOKS.get(abbrev)
    if not full_name:
        return None
    for ch in chapters:
        if full_name in ch.get("title", "").lower():
            return ch
    return None


def extract_content(text: str, location: str) -> str | None:
    """Extract Bible verses from text.

    Matches patterns like "Gen 3:1-7", "1 Sam 17:40-50".
    Returns None if location is not a Bible verse reference.
    """
    verse_match = re.match(
        r"(?:\d\s+)?[A-Za-z]+\s+(\d+):(\d+)[-\u2013](\d+)", location
    )
    if not verse_match:
        return None

    chapter = int(verse_match.group(1))
    start_verse = int(verse_match.group(2))
    end_verse = int(verse_match.group(3))

    lines = text.split("\n")
    extracted = []
    for line in lines:
        m = re.match(r"^(\d+):(\d+)\s", line)
        if m:
            ch = int(m.group(1))
            vs = int(m.group(2))
            if ch == chapter and start_verse <= vs <= end_verse:
                extracted.append(line)

    if extracted:
        return "\n".join(extracted)
    return ""  # verses not found
