"""Repair local page links that safely map to an existing in-page anchor."""

from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "sms", "javascript", "data", "blob"}
SECTION_ALIASES = {
    "contact": ("contact", "contact-us", "contact-section", "get-in-touch", "quote"),
    "contact-us": ("contact-us", "contact", "contact-section", "get-in-touch", "quote"),
    "request-a-quote": ("quote", "contact", "contact-us", "get-in-touch"),
    "about-us": ("about-us", "about", "our-story"),
    "our-services": ("our-services", "services", "service"),
    "services": ("services", "our-services", "service"),
    "gallery": ("gallery", "portfolio", "projects"),
}


class _LinkInventory(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.ids: set[str] = set()
        self.attributes: list[dict] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        if line - 1 >= len(self.line_offsets):
            return len(self.source)
        return min(len(self.source), self.line_offsets[line - 1] + column)

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text() or ""
        start = self._offset()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if values.get("id"):
            self.ids.add(values["id"])
        attribute = "href" if tag.lower() == "a" else "action" if tag.lower() == "form" else ""
        if not attribute:
            return
        match = re.search(rf"\b{attribute}\s*=\s*(['\"])(.*?)\1", raw, re.I | re.S)
        if match:
            self.attributes.append({
                "tag": tag.lower(),
                "attribute": attribute,
                "value": html.unescape(match.group(2)),
                "value_start": start + match.start(2),
                "value_end": start + match.end(2),
            })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _safe_file_target(files_dir: Path, path: str) -> bool:
    decoded = unquote(path).lstrip("/")
    if not decoded:
        return True
    target = (files_dir / decoded).resolve()
    try:
        target.relative_to(files_dir.resolve())
    except ValueError:
        return False
    if path.endswith("/"):
        target = target / "index.html"
    return target.is_file()


def _section_for_path(path: str, ids: set[str]) -> str | None:
    segments = [segment for segment in unquote(path).strip("/").split("/") if segment]
    if not segments:
        return None
    slug = re.sub(r"\.html?$", "", segments[-1], flags=re.I).lower()
    if slug in ids:
        return slug
    return next((candidate for candidate in SECTION_ALIASES.get(slug, ()) if candidate in ids), None)


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    files_dir = candidate / "files"
    html_path = files_dir / "index.html"
    report_path = candidate / "debug" / "local_link_repair.json"
    result = {
        "status": "unavailable",
        "changed": False,
        "repaired_links": [],
        "unresolved_local_routes": [],
    }
    if not html_path.is_file():
        result["reason"] = "Generated HTML is missing."
    else:
        source = html_path.read_text(encoding="utf-8", errors="replace")
        inventory = _LinkInventory(source)
        inventory.feed(source)
        inventory.close()
        replacements = []
        for item in inventory.attributes:
            value = item["value"].strip()
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme.lower() in EXTERNAL_SCHEMES or value.startswith("//"):
                continue
            path = parsed.path
            if not path or path in {"/", "/index.html"} or _safe_file_target(files_dir, path):
                continue
            fragment = unquote(parsed.fragment)
            section = fragment if fragment in inventory.ids else _section_for_path(path, inventory.ids)
            if section:
                replacement = f"#{section}"
                replacements.append((item["value_start"], item["value_end"], replacement))
                result["repaired_links"].append({
                    "tag": item["tag"],
                    "from": value,
                    "to": replacement,
                    "reason": "The path is not a candidate file, but a matching in-page section exists.",
                })
            else:
                result["unresolved_local_routes"].append({
                    "tag": item["tag"],
                    "value": value,
                    "reason": "The local path does not resolve to a candidate file or an existing fragment.",
                })
        for start, end, replacement in sorted(replacements, reverse=True):
            source = source[:start] + replacement + source[end:]
        if replacements:
            html_path.write_text(source, encoding="utf-8")
            result["changed"] = True
        if result["unresolved_local_routes"]:
            result["status"] = "needs_candidate_regeneration"
        elif replacements:
            result["status"] = "repaired"
        else:
            result["status"] = "not_needed"
        result["reason"] = "Local page links were checked against candidate files and in-page anchors."

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_folder", type=Path)
    args = parser.parse_args()
    repair(args.candidate_folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
