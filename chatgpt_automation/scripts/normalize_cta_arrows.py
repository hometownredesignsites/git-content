"""Remove arrow glyphs from CTA labels before website quality checks."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

CTA_ARROW_GLYPHS = re.compile(r"[←↑→↓↗↘↙↖↩↪➔➜➝➞➟➠➡➢➤›»]")
CTA_CLASS = re.compile(
    r"(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])",
    re.IGNORECASE,
)


def _is_cta(tag: str, attrs: dict[str, str | None]) -> bool:
    classes = (attrs.get("class") or "").lower()
    return tag == "button" or (
        tag == "a"
        and (
            (attrs.get("role") or "").lower() == "button"
            or (attrs.get("href") or "").lower().startswith(("tel:", "mailto:"))
            or bool(CTA_CLASS.search(classes))
        )
    )


class _ArrowRemover(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.cta_depth = 0
        self.stack: list[tuple[str, bool]] = []
        self.edits: list[tuple[int, int]] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def _remove_matches(self, decoded: str, source_text: str, start: int) -> None:
        if not self.cta_depth:
            return
        if decoded == source_text:
            self.edits.extend(
                (start + match.start(), start + match.end())
                for match in CTA_ARROW_GLYPHS.finditer(decoded)
            )
            return
        # A character reference decodes to one Unicode character; remove the
        # complete reference when that character is one of the gated arrows.
        if CTA_ARROW_GLYPHS.search(decoded):
            self.edits.append((start, start + len(source_text)))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_cta = _is_cta(tag.lower(), dict(attrs))
        if is_cta:
            start = self._offset()
            raw_tag = self.source[start:self.source.find(">", start) + 1]
            for match in re.finditer(
                r"\b(?:aria-label|title)\s*=\s*([\"'])(.*?)\1|\b(?:aria-label|title)\s*=\s*([^\s>]+)",
                raw_tag,
                re.IGNORECASE | re.DOTALL,
            ):
                value_group = 2 if match.group(2) is not None else 3
                value_start = start + match.start(value_group)
                raw_value = match.group(value_group)
                tokens = re.finditer(
                    r"&(?:#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);?|[←↑→↓↗↘↙↖↩↪➔➜➝➞➟➠➡➢➤›»]",
                    raw_value,
                )
                for token in tokens:
                    if CTA_ARROW_GLYPHS.search(html.unescape(token.group())):
                        self.edits.append((value_start + token.start(), value_start + token.end()))
        self.stack.append((tag.lower(), is_cta))
        self.cta_depth += int(is_cta)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        # Mirror the quality checker’s tag-based CTA closure behavior.
        for index in range(len(self.stack) - 1, -1, -1):
            stack_tag, is_cta = self.stack[index]
            if is_cta:
                self.cta_depth -= 1
            del self.stack[index]
            if stack_tag == tag.lower():
                break

    def handle_data(self, data: str) -> None:
        self._remove_matches(data, data, self._offset())

    def handle_entityref(self, name: str) -> None:
        start = self._offset()
        raw = self.source[start:]
        match = re.match(r"&" + re.escape(name) + r";?", raw)
        if match:
            self._remove_matches(html.unescape(match.group()), match.group(), start)

    def handle_charref(self, name: str) -> None:
        start = self._offset()
        raw = self.source[start:]
        match = re.match(r"&#" + re.escape(name) + r";?", raw, re.IGNORECASE)
        if match:
            self._remove_matches(html.unescape(match.group()), match.group(), start)


def normalize(source: str) -> tuple[str, int]:
    parser = _ArrowRemover(source)
    parser.feed(source)
    parser.close()
    output = source
    for start, end in sorted(set(parser.edits), reverse=True):
        output = output[:start] + output[end:]
    return output, len(set(parser.edits))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    args = parser.parse_args()
    original = args.html_file.read_text(encoding="utf-8")
    normalized, removed = normalize(original)
    if normalized != original:
        args.html_file.write_text(normalized, encoding="utf-8")
    print(json.dumps({"file": str(args.html_file), "removed_cta_arrow_glyphs": removed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
