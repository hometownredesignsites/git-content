"""Make telephone-linked action labels explicitly read as phone calls."""

from __future__ import annotations

import argparse
from html import unescape
from pathlib import Path
import re
import sys


ANCHOR_RE = re.compile(r"(<a\b(?P<attrs>[^>]*)>)(?P<body>[\s\S]*?)(</a\s*>)", re.IGNORECASE)
TEL_HREF_RE = re.compile(r"\bhref\s*=\s*(['\"])\s*tel:", re.IGNORECASE)
ATTR_RE = re.compile(r"\b(?P<name>aria-label|title)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.IGNORECASE)
CALL_INTENT_RE = re.compile(r"\b(call|phone|dial|talk|speak)\b", re.IGNORECASE)


def _visible_text(markup: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", markup)).split())


def repair(source: str) -> tuple[str, list[str]]:
    repaired = []

    def replace(match: re.Match) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        if not TEL_HREF_RE.search(attrs):
            return match.group(0)

        label = _visible_text(body)
        if not label or not re.search(r"[a-z]", label, re.IGNORECASE) or CALL_INTENT_RE.search(label):
            return match.group(0)

        # Keep any inline markup and only prefix visible copy. A colon works
        # with both imperative labels ("Request a quote") and descriptions
        # ("Discuss your project") without changing the destination or claim.
        leading = re.match(r"\s*", body).group(0)
        updated_body = leading + "Call: " + body[len(leading):]

        updated_attrs = attrs
        for attribute in reversed(list(ATTR_RE.finditer(attrs))):
            value = attribute.group("value")
            if re.search(r"[a-z]", value, re.IGNORECASE) and not CALL_INTENT_RE.search(value):
                quoted = attribute.group("quote")
                updated = f'{attribute.group("name")}={quoted}Call: {value}{quoted}'
                updated_attrs = updated_attrs[:attribute.start()] + updated + updated_attrs[attribute.end():]

        repaired.append(label)
        opening = match.group(1).replace(attrs, updated_attrs, 1)
        return opening + updated_body + match.group(4)

    return ANCHOR_RE.sub(replace, source), repaired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    args = parser.parse_args()
    path = args.html_file
    if not path.is_file():
        print(f"HTML file not found: {path}", file=sys.stderr)
        return 2

    original = path.read_text(encoding="utf-8")
    updated, repaired = repair(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    print(f"Repaired {len(repaired)} telephone CTA label(s): {repaired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
