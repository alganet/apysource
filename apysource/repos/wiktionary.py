# SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>
#
# SPDX-License-Identifier: ISC

"""Wiktionary repository module.

Wiktionary entries provide etymological data for terms.
Each term is cached as a plain-text etymology file.

sourceLocation format: "{term}"
  Examples: "Aphrodite", "deva"
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from apysource.repos._base import (
    BaseRepo,
    SMALL_FILE_THRESHOLD,
    extract_line_range,
    slugify,
)

logger = logging.getLogger(__name__)


class WiktionaryRepo(BaseRepo):
    """Unified source + crawler for Wiktionary etymology data."""

    NAME = "wiktionary"

    # ── Source interface ──────────────────────────────────────────────

    def url_to_key(self, url: str) -> str | None:
        """Extract the wiki page title from a Wiktionary URL."""
        m = self.url_pattern.search(url)
        return unquote(m.group(1)) if m else None

    def is_cached(self, key: str) -> bool:
        """Check if a term's etymology data is cached with content."""
        txt = self.cache_dir / f"{slugify(key)}.txt"
        return txt.exists()

    def resolve_location(self, location: str, key: str) -> Path | None:
        """Map a term to its cached text file."""
        for candidate in (key, location):
            if candidate:
                cache_file = self.cache_dir / f"{slugify(candidate)}.txt"
                if cache_file.exists():
                    return cache_file
        return None

    def extract_content(self, location: str, file_path: Path) -> str:
        """Extract a specific language/etymology section from a Wiktionary cache file."""
        text = file_path.read_text(encoding="utf-8", errors="replace")

        result = extract_line_range(text, location)
        if result is not None:
            return result

        if "/" in location:
            target_header = f"## {location}"
            lines = text.split("\n")
            section_lines = []
            in_section = False
            for line in lines:
                if line.strip().startswith("## "):
                    if line.strip().lower() == target_header.lower():
                        in_section = True
                        continue
                    elif in_section:
                        break
                elif line.strip().startswith("### ") and in_section:
                    break
                elif in_section:
                    section_lines.append(line)

            if section_lines:
                return "\n".join(section_lines).strip()

        if location.strip().lower() in ("etymology", ""):
            lines = text.split("\n")
            section_lines = []
            in_section = False
            for line in lines:
                if line.strip().startswith("## ") and "/Etymology" in line:
                    if not in_section:
                        in_section = True
                        continue
                    else:
                        break
                elif line.strip().startswith("## ") and in_section:
                    break
                elif line.strip().startswith("### ") and in_section:
                    break
                elif in_section:
                    section_lines.append(line)

            if section_lines:
                return "\n".join(section_lines).strip()

        if len(text) < SMALL_FILE_THRESHOLD:
            return text

        return ""

    # ── Crawler interface ─────────────────────────────────────────────

    def crawl(self, key: str, *, delay: float = 3.0,
              force: bool = False, from_cache: bool = False) -> dict | None:
        """Fetch a term's etymology from Wiktionary API."""
        return self._fetch_term(key, force=force, from_cache=from_cache)

    def _fetch_term(self, term: str,
                    force: bool = False, from_cache: bool = False) -> dict | None:
        """Fetch a term's etymology from Wiktionary API."""
        api_term = term[0].upper() + term[1:] if term else term
        slug = term.lower().replace(" ", "_")
        txt_path = self.cache_dir / f"{slug}.txt"

        if not force and not from_cache and txt_path.exists():
            logger.info("[%s] cached — skipping", term)
            return None

        url = f"{f"{self.base_url}/w/api.php"}?action=parse&page={api_term}&prop=wikitext&format=json"
        raw = self.http_client.get(url, force=force, from_cache=from_cache,
                                   timeout=15)
        if not raw:
            logger.warning("[%s] fetch failed", term)
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[%s] invalid JSON response", term)
            return None

        if "error" in data:
            logger.warning("[%s] NOT FOUND: %s", term, data['error'].get('info', '?'))
            return None

        wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
        language_etymologies = self._parse_language_sections(wikitext)

        all_templates = []
        for lang, sections in language_etymologies.items():
            for _section_name, raw_text in sections:
                all_templates.extend(self._parse_wikitext_templates(raw_text))

        crawled_at = datetime.now(timezone.utc).isoformat()

        result = {
            "term": term,
            "languages": {
                lang: [{"section": name, "raw": raw_text,
                        "clean": self._clean_wikitext(raw_text)}
                       for name, raw_text in sections]
                for lang, sections in language_etymologies.items()
            },
            "templates": all_templates,
            "language_count": len(language_etymologies),
            "wikitext_length": len(wikitext),
            "crawled_at": crawled_at,
        }

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"# Wiktionary: {term}\n")
            f.write(f"# Source: https://en.wiktionary.org/wiki/{api_term}\n")
            f.write(f"# Accessed: {crawled_at}\n")
            f.write(f"# Languages: {', '.join(language_etymologies.keys())}\n\n")

            for lang, sections in language_etymologies.items():
                for section_name, raw_text in sections:
                    header = (f"{lang}/{section_name}"
                              if section_name != "Etymology"
                              else f"{lang}/Etymology")
                    clean = self._clean_wikitext(raw_text)
                    f.write(f"## {header}\n\n")
                    f.write(f"{clean}\n\n")
                    f.write(f"### Raw wikitext\n\n{raw_text.strip()}\n\n")

        lang_count = len(language_etymologies)
        total_templates = len(all_templates)
        logger.info("[%s] %d languages, %d templates", term, lang_count, total_templates)

        return result

    @staticmethod
    def _parse_wikitext_templates(text: str) -> list[dict]:
        """Extract etymology-relevant templates from wikitext."""
        templates = []

        pattern = r'\{\{(inh|bor|der|cog|m|lbor)\|([^}]+)\}\}'
        for match in re.finditer(pattern, text):
            tmpl_type = match.group(1)
            parts = match.group(2).split("|")
            entry = {"type": tmpl_type, "parts": parts}

            if len(parts) >= 3:
                entry["source_lang"] = parts[1]
                entry["term"] = parts[2].replace("*", "").strip()
            if len(parts) >= 4:
                for p in parts[3:]:
                    p = p.strip()
                    if p and not p.startswith("tr=") and not p.startswith("sc="):
                        entry["gloss"] = p
                        break
                    elif p.startswith("tr="):
                        entry["transliteration"] = p[3:]

            templates.append(entry)

        root_pattern = r'\{\{root\|([^|]+)\|([^|]+)\|([^}]+)\}\}'
        for match in re.finditer(root_pattern, text):
            templates.append({
                "type": "root",
                "target_lang": match.group(1),
                "source_lang": match.group(2),
                "term": match.group(3).strip(),
            })

        return templates

    @staticmethod
    def _parse_language_sections(wikitext: str) -> dict:
        """Parse Wikitext into {language: [(section_name, raw_text), ...]}."""
        result = {}
        current_lang = None
        current_section = None
        current_text = []

        for line in wikitext.split("\n"):
            lang_match = re.match(r'^==\s*([^=]+?)\s*==$', line)
            if lang_match:
                if current_lang and current_section and current_text:
                    result.setdefault(current_lang, []).append(
                        (current_section, "\n".join(current_text).strip()))
                current_lang = lang_match.group(1).strip()
                current_section = None
                current_text = []
                continue

            etym_match = re.match(r'^===\s*(Etymology[^=]*?)\s*===$', line)
            if etym_match and current_lang:
                if current_section and current_text:
                    result.setdefault(current_lang, []).append(
                        (current_section, "\n".join(current_text).strip()))
                current_section = etym_match.group(1).strip()
                current_text = []
                continue

            if re.match(r'^===', line) and current_section:
                if current_text:
                    result.setdefault(current_lang, []).append(
                        (current_section, "\n".join(current_text).strip()))
                current_section = None
                current_text = []
                continue

            if current_section:
                current_text.append(line)

        if current_lang and current_section and current_text:
            result.setdefault(current_lang, []).append(
                (current_section, "\n".join(current_text).strip()))

        return result

    @staticmethod
    def _clean_wikitext(text: str) -> str:
        """Strip Wikitext markup to produce readable text."""
        def _clean_template(tmpl: str) -> str:
            inner = tmpl[2:-2]
            parts = inner.split("|")
            if len(parts) >= 3:
                term = parts[2]
                gloss = ""
                for p in parts[3:]:
                    p = p.strip()
                    if p and not p.startswith(("tr=", "sc=", "pos=")):
                        gloss = p
                        break
                if gloss:
                    return f"{term} ({gloss})"
                return term
            return tmpl

        clean = re.sub(
            r'\{\{[^}]+\}\}', lambda m: _clean_template(m.group(0)), text)
        clean = re.sub(
            r'\[\[([^|\]]+\|)?([^\]]+)\]\]', r'\2', clean)
        clean = re.sub(r"'{2,}", "", clean)
        return clean.strip()
