#!/usr/bin/env python3
"""Apply small, context-aware visual repairs to generated stylesheets."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re


REPAIR_MARKER = "/* Generated visual repairs: CTA contrast, image-card labels, and template layout. */"
REPAIR_CSS = """/* Generated visual repairs: CTA contrast, image-card labels, and template layout. */
#banner a.button, #banner button, #banner [role="button"],
.hero a.button, .hero button, .hero [role="button"] {
  color: #17251d !important;
  background-color: #fff !important;
  border-color: #fff !important;
}

[data-source-contact-region] a.button, [data-source-contact-region] a.btn,
[data-source-contact-region] a.cta, [data-source-contact-region] a[href^="mailto:"],
[data-source-contact-region] a[href^="tel:"], [data-source-contact-region] button,
[data-source-contact-region] [role="button"],
[data-source-contact-region] input[type="submit"],
#contact a.button, #contact a.btn, #contact a.cta, #contact a[href^="mailto:"], #contact a[href^="tel:"], #contact button, #contact [role="button"],
.contact-section a.button, .contact-section a.btn, .contact-section a.cta, .contact-section a[href^="mailto:"], .contact-section a[href^="tel:"], .contact-section button, .contact-section [role="button"] {
  color: #fff !important;
  background-color: #24372d !important;
  border-color: #24372d !important;
}

.tiles article .eyebrow {
  color: #fff !important;
  padding: .2em .45em;
  background-color: rgba(20, 25, 20, .72) !important;
  text-shadow: 0 1px 3px rgba(0, 0, 0, .85);
}
"""


class _TagOffsets(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.spotlights: list[tuple[int, int, str]] = []

    def get_offset(self) -> int:
        line, column = self.getpos()
        return min(len(self.source), self.line_offsets[line - 1] + column)

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        classes = values.get("class", "").split()
        if "spotlight" in classes and any(re.fullmatch(r"style[123]", item) for item in classes):
            raw = self.get_starttag_text() or ""
            self.spotlights.append((self.get_offset(), self.get_offset() + len(raw), raw))


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    css_path = candidate / "files" / "styles.css"
    report_path = candidate / "debug" / "visual_repair.json"
    result = {"status": "not_needed", "changed": False, "repairs": []}

    if not css_path.is_file():
        result.update(status="unavailable", reason="Generated stylesheet is missing.")
    else:
        css = css_path.read_text(encoding="utf-8", errors="replace")
        if REPAIR_MARKER in css:
            result["status"] = "already_applied"
        else:
            css_path.write_text(css.rstrip() + "\n\n" + REPAIR_CSS, encoding="utf-8")
            result.update(
                status="repaired",
                changed=True,
                repairs=[
                    "high-contrast hero and contact CTA variants",
                    "white text for image-backed tile eyebrows",
                ],
            )

    html_path = candidate / "files" / "index.html"
    reference_path = candidate / "debug" / "design_reference.json"
    if html_path.is_file() and reference_path.is_file():
        try:
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reference = {}
        selected = reference.get("design_reference") or {}
        if str(selected.get("name", "")).casefold() == "landed" or str(selected.get("template_url", "")).rstrip("/").endswith("/landed"):
            source = html_path.read_text(encoding="utf-8", errors="replace")
            parser = _TagOffsets(source)
            parser.feed(source)
            replacements = []
            for index, (start, end, raw) in enumerate(parser.spotlights[:3]):
                match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", raw, re.I | re.S)
                if not match:
                    continue
                classes = match.group(2).split()
                side = "left" if index % 2 == 0 else "right"
                normalized = [item for item in classes if item not in {"left", "right", "top", "bottom"}]
                normalized.append(side)
                new_raw = raw[:match.start(2)] + " ".join(normalized) + raw[match.end(2):]
                if new_raw != raw:
                    replacements.append((start, end, new_raw))
            if replacements:
                for start, end, replacement in reversed(replacements):
                    source = source[:start] + replacement + source[end:]
                html_path.write_text(source, encoding="utf-8")
                result["repairs"].append("alternating left/right Landed spotlight layout")
                result["changed"] = True
                result["status"] = "repaired"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="Candidate run directory")
    args = parser.parse_args()
    return 0 if repair(args.candidate).get("status") not in {"unavailable", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
