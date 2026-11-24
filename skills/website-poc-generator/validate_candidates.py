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

UPLOAD_OPTION_TEXT = re.compile(
    r"\b(?:upload|attach(?:ment)?|drop\s+(?:a\s+)?files?|"
    r"(?:choose|browse|select)\s+(?:a\s+)?(?:files?|photos?|images?)|"
    r"add\s+(?:a\s+)?(?:files?|photos?|images?))\b",
    re.IGNORECASE,
)
UPLOAD_OPTION_MARKER = re.compile(r"(?:upload|attachment|drop[-_ ]?zone|file[-_ ]?picker)", re.IGNORECASE)


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
        self.upload_option_issues = []
        self._upload_text_stack = []
        self.mobile_menu_buttons = []
        self._active_mobile_menu_button = None
        self.contact_text = []
        self.contact_buttons = []
        self._button_stack = []
        self._contact_stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags[tag] += 1
        attributes = " ".join(
            str(attrs.get(key, "")) for key in ("id", "class", "aria-label", "title", "value")
        )
        if UPLOAD_OPTION_MARKER.search(" ".join(str(attrs.get(key, "")) for key in ("id", "class"))):
            self.upload_option_issues.append(f"<{tag}> upload-related UI marker")
        upload_text_target = tag in {"label", "button", "a", "summary"} or attrs.get("role", "").lower() == "button"
        if upload_text_target:
            target = {"tag": tag, "parts": [attributes]}
            self._upload_text_stack.append(target)
            if UPLOAD_OPTION_TEXT.search(attributes):
                self.upload_option_issues.append(f"<{tag}> upload option label")
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
        if tag == "button" and attrs.get("aria-controls"):
            self._active_mobile_menu_button = {
                "in_header": "header" in self.stack,
                "type": attrs.get("type", "").lower(),
                "class": attrs.get("class", "").lower(),
                "controls": attrs.get("aria-controls", "").strip(),
                "expanded": attrs.get("aria-expanded", "").lower(),
                "aria_label": attrs.get("aria-label", "").strip(),
                "labelledby": attrs.get("aria-labelledby", "").split(),
                "visible_text": "",
                "bars": [],
            }
            self.mobile_menu_buttons.append(self._active_mobile_menu_button)
        if (
            tag == "span"
            and self._active_mobile_menu_button is not None
            and self.stack
            and self.stack[-1] == "button"
            and attrs.get("aria-hidden", "").lower() == "true"
        ):
            self._active_mobile_menu_button["bars"].append(attrs)
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
            if tag == "button":
                self._active_mobile_menu_button = None
        else:
            self.errors.append(f"Closing tag without open tag: </{tag}>")
        for index in range(len(self._upload_text_stack) - 1, -1, -1):
            if self._upload_text_stack[index]["tag"] == tag:
                target = self._upload_text_stack.pop(index)
                if UPLOAD_OPTION_TEXT.search(" ".join(target["parts"])):
                    self.upload_option_issues.append(f"<{tag}> upload option label")
                break

    def handle_data(self, data):
        if "focus-visible" in data or ":focus" in data:
            self.focus_css = True
        if self.contact_depth:
            self.contact_text.append(data)
        for target in self._upload_text_stack:
            target["parts"].append(data)
        for button in self._button_stack:
            button["text"] += data
        if self._active_mobile_menu_button is not None:
            self._active_mobile_menu_button["visible_text"] += data

    def has_accessible_mobile_hamburger(self) -> bool:
        known_ids = set(self.ids)
        menu_buttons = [button for button in self.mobile_menu_buttons if button["in_header"]]
        return len(menu_buttons) == 1 and any(
            button["in_header"]
            and button["type"] == "button"
            and button["controls"] in known_ids
            and button["expanded"] in {"true", "false"}
            and (
                button["aria_label"]
                or (button["labelledby"] and all(label_id in known_ids for label_id in button["labelledby"]))
            )
            and re.search(r"(?:^|[\s_-])(?:menu|nav)(?:$|[\s_-])", button["class"]) is not None
            and len(button["bars"]) == 3
            and " ".join(button["visible_text"].split()).lower() != "menu"
            for button in self.mobile_menu_buttons
        )


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
    if parser.file_upload_controls or parser.upload_option_issues:
        issues.append(
            "File upload options and controls are prohibited in POC candidates; "
            f"found {parser.file_upload_controls} file input(s) and "
            f"{len(parser.upload_option_issues)} upload label/control marker(s)"
        )
    if not parser.has_accessible_mobile_hamburger():
        issues.append(
            'Mobile menu must use one accessible header button with aria-controls, aria-expanded, '
            'type="button", and exactly three direct <span aria-hidden="true"> bars'
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
