#!/usr/bin/env python3
"""Apply one conservative repair pass for measurable candidate QA failures."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from site_quality import (
    _category_fallback_image_urls_from_prompt,
    _source_image_urls_from_prompt,
    _url_key,
)


REPAIR_MARKER = "/* QA repair pass: measured primary CTA contrast. */"
LAYOUT_REPAIR_MARKER = "/* QA repair pass: selected scaffold layout. */"
LANDED_MEDIA_ORDER_REPAIR_MARKER = "/* QA repair pass: measured Landed media order. */"
REPAIRABLE_IMAGE_CHECKS = {
    "images_use_source_or_category_assets",
    "hero_uses_source_or_category_asset",
}
CTA_CHECK = "browser_primary_ctas_readable_desktop_and_mobile"
LAYOUT_CHECK = "browser_template_layout_signature_matches"
SAFE_SELECTOR = re.compile(r"^[A-Za-z0-9_#.:,>+~*\\()\s-]+$")


class _LayoutTags(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.stack: list[dict] = []
        self.spotlights: list[dict] = []
        self.tiles: list[dict] = []
        self.hero: dict | None = None

    def handle_starttag(self, tag, attrs):
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        raw = self.get_starttag_text() or ""
        line, column = self.getpos()
        node = {
            "tag": tag.lower(),
            "attrs": values,
            "start": self.line_offsets[line - 1] + column,
            "end": self.line_offsets[line - 1] + column + len(raw),
            "raw": raw,
        }
        classes = values.get("class", "").split()
        if "spotlight" in classes:
            node["has_direct_content"] = False
            node["has_direct_media"] = False
            self.spotlights.append(node)
        parent = self.stack[-1] if self.stack else None
        if parent and "spotlight" in parent["attrs"].get("class", "").split():
            if "content" in classes:
                parent["has_direct_content"] = True
            if (
                "image" in classes
                or tag.lower() in {"img", "picture", "video"}
                or "background-image" in values.get("style", "").casefold()
            ):
                parent["has_direct_media"] = True
        if "tiles" in classes:
            self.tiles.append(node)
        if tag.lower() == "h1":
            self.hero = next(
                (item for item in reversed(self.stack)
                 if item["tag"] == "section" or "hero" in item["attrs"].get("class", "").split()),
                next((item for item in reversed(self.stack) if item["tag"] == "main"), None),
            )
        if tag.lower() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]["tag"] == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag.lower():
                del self.stack[index:]
                break


def _patched_classes(raw: str, add: set[str], remove: set[str], identifier: str | None = None) -> str:
    class_match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", raw, re.IGNORECASE | re.DOTALL)
    classes = class_match.group(2).split() if class_match else []
    classes = [item for item in classes if item not in remove]
    classes = list(dict.fromkeys(classes + sorted(add)))
    if class_match:
        raw = raw[:class_match.start(2)] + " ".join(classes) + raw[class_match.end(2):]
    else:
        insert_at = raw.rfind("/>")
        if insert_at < 0:
            insert_at = raw.rfind(">")
        raw = raw[:insert_at] + f' class="{" ".join(classes)}"' + raw[insert_at:]
    if identifier:
        id_match = re.search(r"\bid\s*=\s*(['\"])(.*?)\1", raw, re.IGNORECASE | re.DOTALL)
        if id_match:
            raw = raw[:id_match.start(2)] + identifier + raw[id_match.end(2):]
        else:
            insert_at = raw.rfind("/>")
            if insert_at < 0:
                insert_at = raw.rfind(">")
            raw = raw[:insert_at] + f' id="{identifier}"' + raw[insert_at:]
    return raw


def _repair_template_layout(candidate: Path, layout: dict) -> list[str]:
    profile = str(layout.get("profile", ""))
    if profile not in {"forty", "landed", "story"}:
        return []
    html_path = candidate / "files" / "index.html"
    css_path = candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return []
    source = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _LayoutTags(source)
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        return []
    replacements: list[tuple[int, int, str]] = []
    repairs = []
    hero = parser.hero
    if hero and profile in {"forty", "landed", "story"}:
        classes = {"banner"}
        if profile == "forty":
            classes.add("major")
        if profile == "story":
            classes.add("fullscreen")
        identifier = "banner" if profile in {"forty", "landed"} else None
        updated = _patched_classes(hero["raw"], classes, set(), identifier)
        if updated != hero["raw"]:
            replacements.append((hero["start"], hero["end"], updated))
            repairs.append(f"restored the selected {profile} hero markers")

    needed_spotlights = 3 if profile == "landed" else 2 if profile == "story" else 0
    if needed_spotlights and len(parser.spotlights) >= needed_spotlights:
        spotlight_changed = False
        for index, node in enumerate(parser.spotlights[:needed_spotlights]):
            side = "left" if index % 2 == 0 else "right"
            if profile == "landed":
                style = f"style{index + 1}"
                add = {style, side}
                remove = {"left", "right", "top", "bottom", "style1", "style2", "style3"}
            else:
                orientation = "orient-left" if index % 2 == 0 else "orient-right"
                add = {orientation, side}
                remove = {"left", "right", "top", "bottom", "orient-left", "orient-right"}
            updated = _patched_classes(node["raw"], add, remove)
            if updated != node["raw"]:
                replacements.append((node["start"], node["end"], updated))
                spotlight_changed = True
        if spotlight_changed:
            repairs.append(f"aligned the selected {profile} spotlight structure")

        # The browser signature measures where the media actually renders. A
        # left/right class change alone can be ineffective when generated CSS
        # still orders the image and copy incorrectly. If browser QA measured a
        # failed Landed alternation, use a small desktop flex-order override on
        # the existing direct content/media children; the normal browser QA
        # recheck remains the authority on whether it worked.
        measured_sides = layout.get("spotlight_media_sides")
        measured_alternations = int(layout.get("spotlight_side_alternations", 0) or 0)
        if (
            profile == "landed"
            and isinstance(measured_sides, list)
            and len(measured_sides) >= 3
            and measured_alternations < 2
            and all(side in {"left", "right"} for side in measured_sides[:3])
            and all(node.get("has_direct_content") and node.get("has_direct_media") for node in parser.spotlights[:3])
        ):
            target_sides = min(
                (("left", "right", "left"), ("right", "left", "right")),
                key=lambda pattern: sum(actual != expected for actual, expected in zip(measured_sides[:3], pattern)),
            )
            css = css_path.read_text(encoding="utf-8", errors="replace")
            if LANDED_MEDIA_ORDER_REPAIR_MARKER not in css:
                rules = [LANDED_MEDIA_ORDER_REPAIR_MARKER, "@media (min-width: 701px) {"]
                for index, side in enumerate(target_sides, start=1):
                    image_order = 1 if side == "left" else 2
                    content_order = 3 - image_order
                    section = f".spotlight.style{index}"
                    media = (
                        f"{section} > .image, {section} > picture, {section} > img, "
                        f"{section} > video, {section} > [style*='background-image']"
                    )
                    rules.extend([
                        f"  {section} {{ display: flex !important; flex-direction: row !important; }}",
                        f"  {media} {{ order: {image_order} !important; flex: 1 1 50% !important; min-width: 0 !important; }}",
                        f"  {section} > .content {{ order: {content_order} !important; flex: 1 1 50% !important; min-width: 0 !important; }}",
                    ])
                rules.append("}")
                css_path.write_text(css.rstrip() + "\n\n" + "\n".join(rules) + "\n", encoding="utf-8")
                before = "/".join(measured_sides[:3])
                after = "/".join(target_sides)
                repairs.append(f"corrected measured Landed media order from {before} to {after}")

    if profile == "story" and not layout.get("has_gallery_or_items") and parser.tiles:
        node = parser.tiles[0]
        updated = _patched_classes(node["raw"], {"items"}, set())
        if updated != node["raw"]:
            replacements.append((node["start"], node["end"], updated))
            repairs.append("marked the existing tile collection as the story template items region")

    if replacements:
        for start, end, replacement in sorted(replacements, reverse=True):
            source = source[:start] + replacement + source[end:]
        html_path.write_text(source, encoding="utf-8")

    if profile == "forty" and parser.tiles:
        evidence = layout
        if int(evidence.get("tile_count", 0) or 0) >= 3 and int(evidence.get("media_tile_count", 0) or 0) >= 3:
            css = css_path.read_text(encoding="utf-8", errors="replace")
            if "desktop_tile_columns" in evidence and int(evidence.get("desktop_tile_columns", 0) or 0) < 2:
                rule = (
                    f"\n{LAYOUT_REPAIR_MARKER}\nmain .tiles {{ display: grid !important; "
                    "grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 1.25rem !important; }\n"
                    "@media (max-width: 700px) { main .tiles { grid-template-columns: 1fr !important; } }\n"
                )
                if LAYOUT_REPAIR_MARKER not in css:
                    css_path.write_text(css.rstrip() + rule, encoding="utf-8")
                    repairs.append("restored the selected forty tile grid columns")
    return repairs


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _replace_url(text: str, old_url: str, new_url: str) -> str:
    variants = {
        old_url,
        html.escape(old_url, quote=True),
        old_url.replace("&", "&amp;"),
    }
    for old in sorted(variants, key=len, reverse=True):
        if old in text:
            replacement = html.escape(new_url, quote=True) if "&amp;" in old else new_url
            text = text.replace(old, replacement)
    return text


def _approved_images(context: str) -> tuple[list[str], list[str]]:
    source = _source_image_urls_from_prompt(context)
    fallback = _category_fallback_image_urls_from_prompt(context)
    return list(dict.fromkeys(source)), list(dict.fromkeys(fallback))


def _repair_images(candidate: Path, checker: dict, context: str) -> list[dict]:
    source_urls, fallback_urls = _approved_images(context)
    approved = list(dict.fromkeys(source_urls + fallback_urls))
    source_url = str(_read_json(candidate / "run_notes.json").get("source_url", ""))
    if not source_url:
        source_url = str(_read_json(candidate / "debug" / "inputs.json").get("source_url", ""))
    approved_keys = {_url_key(url, source_url) for url in approved}
    approved_keys.discard(None)
    used_keys: set[tuple[str, str]] = set()
    replacements: list[dict] = []

    page_urls = checker.get("image_urls", [])
    hero_urls = checker.get("hero_image_urls", [])
    if not isinstance(page_urls, list):
        page_urls = []
    if not isinstance(hero_urls, list):
        hero_urls = []
    urls = list(dict.fromkeys(str(url) for url in page_urls + hero_urls if isinstance(url, str)))
    html_path = candidate / "files" / "index.html"
    css_path = candidate / "files" / "styles.css"
    if not approved or not html_path.is_file() or not css_path.is_file():
        return replacements
    source = html_path.read_text(encoding="utf-8", errors="replace")
    css = css_path.read_text(encoding="utf-8", errors="replace")

    for old_url in sorted(urls, key=len, reverse=True):
        old_key = _url_key(old_url, source_url)
        if old_key is None or old_key in approved_keys:
            continue
        hero_url = old_url in hero_urls
        options = source_urls if hero_url and source_urls else approved
        if not options:
            options = fallback_urls
        if not options:
            continue
        new_url = next(
            (url for url in options if _url_key(url, source_url) not in used_keys),
            options[len(replacements) % len(options)],
        )
        used_key = _url_key(new_url, source_url)
        if used_key:
            used_keys.add(used_key)
        new_source = _replace_url(source, old_url, new_url)
        new_css = _replace_url(css, old_url, new_url)
        if new_source != source or new_css != css:
            replacements.append({"from": old_url, "to": new_url, "hero": hero_url})
            source, css = new_source, new_css

    if replacements:
        html_path.write_text(source, encoding="utf-8")
        css_path.write_text(css, encoding="utf-8")
    return replacements


def _cta_issues(browser: dict) -> list[dict]:
    issues = []
    viewports = browser.get("viewports", {})
    if not isinstance(viewports, dict):
        return issues
    for viewport_name in ("desktop", "mobile"):
        viewport = viewports.get(viewport_name, {})
        contrast = viewport.get("primary_cta_contrast", {}) if isinstance(viewport, dict) else {}
        for issue in contrast.get("issues", []) if isinstance(contrast, dict) else []:
            if isinstance(issue, dict) and issue.get("selector"):
                issues.append({**issue, "viewport": viewport_name})
    return issues


def _repair_cta_contrast(candidate: Path, browser: dict) -> list[str]:
    css_path = candidate / "files" / "styles.css"
    if not css_path.is_file():
        return []
    selectors = []
    for issue in _cta_issues(browser):
        selector = str(issue.get("selector", "")).strip()
        if SAFE_SELECTOR.fullmatch(selector) and selector not in selectors:
            selectors.append(selector)
    if not selectors:
        return []
    css = css_path.read_text(encoding="utf-8", errors="replace")
    if REPAIR_MARKER in css:
        css = css.split(REPAIR_MARKER, 1)[0].rstrip()
    rules = [
        f"{selector} {{ color: #17251d !important; background-color: #ffffff !important; "
        "border: 2px solid #17251d !important; text-shadow: none !important; }"
        for selector in selectors
    ]
    css_path.write_text(css.rstrip() + "\n\n" + REPAIR_MARKER + "\n" + "\n".join(rules) + "\n", encoding="utf-8")
    return selectors


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    debug = candidate / "debug"
    checker = _read_json(debug / "checker_report.json")
    browser = _read_json(debug / "browser_qa.json")
    context_path = debug / "website_context.md"
    context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.is_file() else ""
    failures = set(checker.get("blocking_failures", []))
    image_replacements = _repair_images(candidate, checker, context) if failures & REPAIRABLE_IMAGE_CHECKS else []
    cta_selectors = _repair_cta_contrast(candidate, browser) if CTA_CHECK in failures else []

    layout = browser.get("template_layout", {})
    layout_repairs = _repair_template_layout(candidate, layout) if LAYOUT_CHECK in failures and isinstance(layout, dict) else []
    layout_diagnostic = None
    if LAYOUT_CHECK in failures and isinstance(layout, dict):
        layout_diagnostic = {
            "expected": {
                "profile": layout.get("profile"),
                "template": layout.get("slug"),
                "signature_id": layout.get("signature_id"),
            },
            "actual": {
                key: value for key, value in layout.items()
                if key not in {"status", "pass", "profile", "slug", "signature_id"}
            },
            "targeted_correction": layout_repairs or "No safe structural repair was possible; retry guidance will include expected and actual signatures.",
        }

    result = {
        "status": "repaired" if image_replacements or cta_selectors or layout_repairs else "no_safe_repair_available",
        "changed": bool(image_replacements or cta_selectors or layout_repairs),
        "triggered_failures": sorted(failures & (REPAIRABLE_IMAGE_CHECKS | {CTA_CHECK, LAYOUT_CHECK})),
        "image_replacements": image_replacements,
        "cta_selectors": cta_selectors,
        "layout_repairs": layout_repairs,
        "template_layout": layout_diagnostic,
    }
    debug.mkdir(parents=True, exist_ok=True)
    (debug / "quality_repair.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    repair(args.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
