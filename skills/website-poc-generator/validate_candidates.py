#!/usr/bin/env python3
"""Validate standalone HTML candidates for the Website POC Generator.

Usage:
  python validate_candidates.py candidate-forty.html candidate-landed.html candidate-story.html

Uses only the Python standard library. These checks are structural heuristics,
not a substitute for browser rendering, accessibility testing, or visual QA.
Source-derived contact fields also require an enabled, named ``<button
type="button">`` send CTA; rendered visibility remains a browser check.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class DocumentCheck(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = Counter()
        self.ids = []
        self.anchors = []
        self.images = []
        self.styles = 0
        self.external_styles = []
        self.focus_css = False
        self.viewport = False
        self.stack = []
        self.contact_depth = 0
        self.contact_fields = 0
        self.file_upload_controls = 0
        self.contact_text = []
        self.contact_buttons = []
        self._button_stack = []
        self._contact_stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        contact_markers = [attrs.get("id", ""), attrs.get("class", ""), attrs.get("aria-label", "")]
        opens_contact = any("contact" in marker.lower() for marker in contact_markers)
        in_contact = self.contact_depth > 0 or opens_contact
        if tag == "style":
            self.styles += 1
        if tag == "link" and "stylesheet" in attrs.get("rel", "").lower():
            self.external_styles.append(attrs.get("href", "(missing href)"))
        if tag == "meta" and attrs.get("name", "").lower() == "viewport":
            self.viewport = True
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])
        if tag == "img":
            self.images.append(attrs.get("src", ""))
        if tag == "input" and attrs.get("type", "text").lower() == "file":
            self.file_upload_controls += 1
        if in_contact and tag in {"input", "select", "textarea"}:
            input_type = attrs.get("type", "text").lower() if tag == "input" else "text"
            if input_type not in {"hidden", "submit", "reset", "button", "image"}:
                self.contact_fields += 1
        if in_contact and tag == "button":
            button = {
                "type": attrs.get("type", "submit").lower(),
                "disabled": "disabled" in attrs,
                "hidden": "hidden" in attrs,
                "aria_hidden": attrs.get("aria-hidden", "").lower() == "true",
                "style": attrs.get("style", "").lower(),
                "aria_label": attrs.get("aria-label", "").strip(),
                "text": "",
            }
            self.contact_buttons.append(button)
            self._button_stack.append(button)
        if tag not in self.VOID:
            self.stack.append(tag)
            self._contact_stack.append(opens_contact)
            if opens_contact:
                self.contact_depth += 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if tag in self.stack:
            # Recover from optional/malformed nesting but flag mismatched structure.
            idx = len(self.stack) - 1 - self.stack[::-1].index(tag)
            if idx != len(self.stack) - 1:
                self.errors.append(f"Unexpected closing tag </{tag}>")
            removed_contact = self._contact_stack[idx:]
            self.contact_depth -= sum(removed_contact)
            del self.stack[idx:]
            del self._contact_stack[idx:]
            if tag == "button" and self._button_stack:
                self._button_stack.pop()
        else:
            self.errors.append(f"Closing tag without open tag: </{tag}>")

    def handle_data(self, data):
        if "focus-visible" in data or ":focus" in data:
            self.focus_css = True
        if self.contact_depth:
            self.contact_text.append(data)
        for button in self._button_stack:
            button["text"] += data


def has_valid_contact_send_cta(parser: DocumentCheck) -> bool:
    send_labels = re.compile(
        r"\b(send(?:\s+(?:inquiry|message|request))?|submit|request\s+(?:a\s+)?quote)\b",
        re.I,
    )
    return any(
        button["type"] == "button"
        and not button["disabled"]
        and not button["hidden"]
        and not button["aria_hidden"]
        and "display:none" not in button["style"].replace(" ", "")
        and "visibility:hidden" not in button["style"].replace(" ", "")
        and send_labels.search(button["text"])
        for button in parser.contact_buttons
    )


def check(path: Path) -> list[str]:
    issues = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read file: {exc}"]

    if not text.lstrip().lower().startswith("<!doctype html"):
        issues.append("Missing HTML5 doctype")
    parser = DocumentCheck()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        issues.append(f"HTML parser error: {exc}")

    for tag in ("html", "head", "body"):
        if parser.tags[tag] != 1:
            issues.append(f"Expected exactly one <{tag}>; found {parser.tags[tag]}")
    if parser.styles < 1:
        issues.append("No embedded <style> block found")
    if parser.file_upload_controls:
        issues.append(
            f"File upload controls are prohibited in POC candidates; found {parser.file_upload_controls}"
        )
    if parser.external_styles:
        issues.append("External stylesheet link(s): " + ", ".join(parser.external_styles))
    if not parser.viewport:
        issues.append("Missing responsive viewport meta")
    duplicates = sorted(k for k, n in Counter(parser.ids).items() if n > 1)
    if duplicates:
        issues.append("Duplicate IDs: " + ", ".join(duplicates))
    known_ids = set(parser.ids)
    broken = sorted(set(parser.anchors) - known_ids)
    if broken:
        issues.append("Broken internal anchors: " + ", ".join("#" + x for x in broken))
    if any(not src.strip() for src in parser.images):
        issues.append("Image with missing/empty src")
    if not parser.focus_css:
        issues.append("No visible-focus CSS selector detected (manual review required)")
    if parser.stack:
        issues.append("Unclosed element(s): " + ", ".join(parser.stack[-8:]))

    if parser.contact_fields:
        if not has_valid_contact_send_cta(parser):
            issues.append(
                "Contact inquiry fields need an enabled, named no-op CTA such as "
                '<button type="button">Send inquiry</button>'
            )
        disclosure = " ".join(" ".join(parser.contact_text).lower().split())
        if "nothing is sent or stored" not in disclosure:
            issues.append('Contact inquiry demo needs a nearby "nothing is sent or stored" disclosure')

    # Heuristic only: catches a few common sources of horizontal overflow.
    if "width: 100vw" in text.lower() and "box-sizing: border-box" not in text.lower():
        issues.append("Possible 100vw overflow; review sizing and box model")
    if "overflow-x: hidden" in text.lower():
        issues.append("Review overflow-x:hidden; it can conceal layout defects")

    return issues


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: validate_candidates.py <candidate.html> [candidate.html ...]")
        return 2
    failed = False
    for filename in argv:
        path = Path(filename)
        issues = check(path)
        if issues:
            failed = True
            print(f"FAIL {path}")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print(f"PASS {path} (structural heuristics only)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
