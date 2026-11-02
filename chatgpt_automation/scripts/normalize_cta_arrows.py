"""Remove arrow glyphs from CTA labels before website quality checks."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

CTA_ARROW_GLYPHS = re.compile(r"[←↑→↓↗↘↙↖↩↪⇢⇨⟶⟹➔➜➝➞➟➠➡➢➤⮕⮞❯❱›»]")
CTA_ARROW_ICON_CLASS = re.compile(r"(?:^|[\s_-])(?:button[-_]?arrow|cta[-_]?arrow|arrow[-_]?icon|icon[-_]?arrow|chevron[-_]?right|caret[-_]?right)(?:$|[\s_-])", re.IGNORECASE)
CTA_CLASS = re.compile(
    r"(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])",
    re.IGNORECASE,
)
CTA_CSS_SELECTOR = re.compile(r"\.(?:button|btn|cta|call[-_]?to[-_]?action)(?:[-_:\s.#\[:]|$)|(?:^|[\s>+~,])button(?:[#.:\s>+~\[]|$)", re.IGNORECASE)
CSS_ARROW_ESCAPE = re.compile(r"\\([0-9a-fA-F]{1,6})\s?")
CTA_LINK_INTENT = re.compile(r"contact|quote|estimate|book|appointment|call|request|schedule|inquir", re.IGNORECASE)


def _decode_css_escapes(value: str) -> str:
    def decode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except (ValueError, OverflowError):
            return ""
    return CSS_ARROW_ESCAPE.sub(decode, value)


def normalize_css(source: str) -> tuple[str, int]:
    """Remove arrow-producing CTA pseudo-element rules from stylesheet text."""
    rule = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
    edits = []
    for match in rule.finditer(source):
        selectors, declarations = match.group(1), match.group(2)
        selector_list = [part.strip() for part in selectors.split(",")]
        cta_pseudo_selectors = [
            selector for selector in selector_list
            if CTA_CSS_SELECTOR.search(selector)
            and re.search(r"::?(?:before|after)\b", selector, re.IGNORECASE)
        ]
        if not cta_pseudo_selectors:
            continue
        content = re.search(r"\bcontent\s*:\s*([^;]+)", declarations, re.IGNORECASE)
        background = re.search(r"\b(?:background|background-image|mask|mask-image)\s*:\s*([^;]+)", declarations, re.IGNORECASE)
        content_is_arrow = bool(content and CTA_ARROW_GLYPHS.search(_decode_css_escapes(content.group(1))))
        content_is_icon = bool(content and re.search(r"url\s*\(", content.group(1), re.IGNORECASE))
        background_is_arrow = bool(background and (
            re.search(r"(?:arrow|chevron)[^)]*\.(?:svg|png|webp)", background.group(1), re.IGNORECASE)
            or CTA_ARROW_GLYPHS.search(_decode_css_escapes(background.group(1)))
        ))
        background_is_icon = bool(background and re.search(r"url\s*\(", background.group(1), re.IGNORECASE))
        geometric_arrow = bool(
            re.search(r"\btransform\s*:\s*[^;]*rotate\s*\(", declarations, re.IGNORECASE)
            and re.search(r"\bborder(?:-(?:width|style|top|right|bottom|left))?\s*:", declarations, re.IGNORECASE)
        )
        if content_is_arrow or content_is_icon or background_is_arrow or background_is_icon or geometric_arrow:
            retained = [selector for selector in selector_list if selector not in cta_pseudo_selectors]
            replacement = f"{', '.join(retained)} {{{declarations}}}" if retained else ""
            edits.append((match.start(), match.end(), replacement))
    output = source
    for start, end, replacement in reversed(edits):
        output = output[:start] + replacement + output[end:]
    return output, len(edits)


def _is_cta(tag: str, attrs: dict[str, str | None]) -> bool:
    classes = (attrs.get("class") or "").lower()
    return tag == "button" or (
        tag == "a"
        and (
            (attrs.get("role") or "").lower() == "button"
            or (attrs.get("href") or "").lower().startswith(("tel:", "mailto:"))
            or bool(CTA_LINK_INTENT.search(attrs.get("href") or ""))
            or bool(CTA_LINK_INTENT.search(" ".join(str(attrs.get(key) or "") for key in ("aria-label", "title"))))
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
        self.stack: list[tuple[str, bool, int | None]] = []
        self.edits: list[tuple[int, int]] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def _remove_matches(self, decoded: str, source_text: str, start: int) -> None:
        if not self.cta_depth or any(icon_start is not None for _, _, icon_start in self.stack):
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
                    r"&(?:#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);?|[←↑→↓↗↘↙↖↩↪⇢⇨⟶⟹➔➜➝➞➟➠➡➢➤⮕⮞❯❱›»]",
                    raw_value,
                )
                for token in tokens:
                    if CTA_ARROW_GLYPHS.search(html.unescape(token.group())):
                        self.edits.append((value_start + token.start(), value_start + token.end()))
        icon_start = None
        values = dict(attrs)
        classes = (values.get("class") or "").strip()
        icon_metadata = " ".join(str(values.get(key) or "") for key in ("class", "data-icon", "data-lucide", "aria-label", "title"))
        is_arrow_icon = bool(CTA_ARROW_ICON_CLASS.search(icon_metadata) or re.search(r"arrow|chevron", icon_metadata, re.IGNORECASE))
        # CTA SVGs are decorative icon children; removing them also handles
        # anonymous inline SVG arrows whose paths have no useful class name.
        if (self.cta_depth or is_cta) and tag.lower() == "svg":
            icon_start = self._offset()
        elif (self.cta_depth or is_cta) and tag.lower() in {"span", "i"} and is_arrow_icon:
            icon_start = self._offset()
        self.stack.append((tag.lower(), is_cta, icon_start))
        self.cta_depth += int(is_cta)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self._offset()
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][2] is not None:
            end = self.source.find(">", start)
            if end >= 0:
                self.edits.append((start, end + 1))
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        # Mirror the quality checker’s tag-based CTA closure behavior.
        for index in range(len(self.stack) - 1, -1, -1):
            stack_tag, is_cta, icon_start = self.stack[index]
            if is_cta:
                self.cta_depth -= 1
            if stack_tag == tag.lower() and icon_start is not None:
                end = self.source.find(">", self._offset())
                if end >= 0:
                    self.edits.append((icon_start, end + 1))
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
    css_removed = 0
    style_pattern = re.compile(r"(<style\b[^>]*>)([\s\S]*?)(</style\s*>)", re.IGNORECASE)
    def clean_style(match: re.Match[str]) -> str:
        nonlocal css_removed
        cleaned, removed = normalize_css(match.group(2))
        css_removed += removed
        return match.group(1) + cleaned + match.group(3)
    source = style_pattern.sub(clean_style, source)
    parser = _ArrowRemover(source)
    parser.feed(source)
    parser.close()
    output = source
    for start, end in sorted(set(parser.edits), reverse=True):
        output = output[:start] + output[end:]
    return output, len(set(parser.edits)) + css_removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--css-file", type=Path)
    args = parser.parse_args()
    original = args.html_file.read_text(encoding="utf-8")
    normalized, removed = normalize(original)
    if normalized != original:
        args.html_file.write_text(normalized, encoding="utf-8")
    css_removed = 0
    if args.css_file:
        css = args.css_file.read_text(encoding="utf-8")
        normalized_css, css_removed = normalize_css(css)
        if normalized_css != css:
            args.css_file.write_text(normalized_css, encoding="utf-8")
    print(json.dumps({
        "file": str(args.html_file),
        "removed_cta_arrow_glyphs": removed + css_removed,
        "removed_cta_css_rules": css_removed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
