#!/usr/bin/env python3
"""Apply one bounded repair pass for measured Duck.ai candidate failures."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

try:
    from .site_quality import (_category_fallback_image_urls_from_prompt, _image_loads_ok,
                               _source_asset_urls_from_prompt, _source_image_urls_from_prompt, _url_key)
except ImportError:  # Direct execution from the workflow script directory.
    from site_quality import (_category_fallback_image_urls_from_prompt, _image_loads_ok,
                              _source_asset_urls_from_prompt, _source_image_urls_from_prompt, _url_key)


IMAGE_CHECKS = {
    "hero_has_image", "hero_images_load_ok", "all_images_load_ok", "image_coverage",
    "source_site_hero_photo_used", "source_site_photos_used", "source_site_photos_load_ok",
    "images_use_source_or_category_assets", "hero_uses_source_or_category_asset",
}
CTA_CHECK = "browser_primary_ctas_readable_desktop_and_mobile"
LAYOUT_CHECK = "browser_template_layout_signature_matches"
SAFE_SELECTOR = re.compile(r"^[A-Za-z0-9_#.:,>+~*()\s-]+$")
CTA_MARKER = "/* QA repair pass: measured primary CTA contrast. */"
LAYOUT_MARKER = "/* QA repair pass: measured template layout. */"
HERO_IMAGE_MARKER = "/* QA repair pass: verified hero fallback. */"


class _Nodes(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        for match in re.finditer("\n", source):
            self.offsets.append(match.end())
        self.stack: list[dict] = []
        self.hero = None
        self.spotlights: list[dict] = []
        self.tiles = []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text() or ""
        line, col = self.getpos()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        node = {"tag": tag.lower(), "attrs": values, "raw": raw,
                "start": self.offsets[line - 1] + col, "end": self.offsets[line - 1] + col + len(raw),
                "content": False, "media": False}
        parent = self.stack[-1] if self.stack else None
        if parent and "spotlight" in parent["attrs"].get("class", "").split():
            if "content" in values.get("class", "").split():
                parent["content"] = True
            if "image" in values.get("class", "").split() or tag.lower() in {"img", "picture", "video"} or "background-image" in values.get("style", ""):
                parent["media"] = True
        classes = values.get("class", "").split()
        if "spotlight" in classes:
            self.spotlights.append(node)
        if "tiles" in classes:
            self.tiles.append(node)
        if tag.lower() == "h1":
            self.hero = next((item for item in reversed(self.stack) if item["tag"] == "section" or "hero" in item["attrs"].get("class", "").split()),
                             next((item for item in reversed(self.stack) if item["tag"] == "main"), None))
        if tag.lower() not in self.VOID:
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


def _classes(raw: str, add: set[str], remove: set[str], identifier: str | None = None) -> str:
    match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", raw, re.I | re.S)
    values = match.group(2).split() if match else []
    values = list(dict.fromkeys([item for item in values if item not in remove] + sorted(add)))
    if match:
        raw = raw[:match.start(2)] + " ".join(values) + raw[match.end(2):]
    else:
        at = raw.rfind("/>") if raw.rfind("/>") >= 0 else raw.rfind(">")
        raw = raw[:at] + f' class="{" ".join(values)}"' + raw[at:]
    if identifier:
        match = re.search(r"\bid\s*=\s*(['\"])(.*?)\1", raw, re.I | re.S)
        if match:
            raw = raw[:match.start(2)] + identifier + raw[match.end(2):]
        else:
            at = raw.rfind("/>") if raw.rfind("/>") >= 0 else raw.rfind(">")
            raw = raw[:at] + f' id="{identifier}"' + raw[at:]
    return raw


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _replace(text: str, old: str, new: str) -> str:
    variants = (old, html.escape(old, quote=True), old.replace("&", "&amp;"))
    for variant in sorted(set(variants), key=len, reverse=True):
        replacement = html.escape(new, quote=True) if "&amp;" in variant else new
        text = text.replace(variant, replacement)
    return text


def _repair_images(candidate: Path, checker: dict, context: str) -> list[dict]:
    source_images = _source_image_urls_from_prompt(context)
    fallback_images = _category_fallback_image_urls_from_prompt(context)
    source_assets = _source_asset_urls_from_prompt(context)
    approved = list(dict.fromkeys(source_assets + source_images + fallback_images))
    repair_images = list(dict.fromkeys(source_images + fallback_images))
    if not approved:
        return []
    source_url = str(_read(candidate / "run_notes.json").get("source_url", ""))
    approved = [url for url in approved if _image_loads_ok(url, base_url=source_url or None)]
    source_images = [url for url in source_images if url in approved]
    fallback_images = [url for url in fallback_images if url in approved]
    source_assets = [url for url in source_assets if url in approved]
    repair_images = list(dict.fromkeys(source_images + fallback_images))
    if not approved:
        return []
    allowed_keys = {_url_key(url, source_url) for url in approved}
    allowed_keys.discard(None)
    html_path, css_path = candidate / "files" / "index.html", candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return []
    source, css = html_path.read_text(encoding="utf-8", errors="replace"), css_path.read_text(encoding="utf-8", errors="replace")
    hero = set(checker.get("hero_image_urls", []))
    images = list(dict.fromkeys([*checker.get("image_urls", []), *hero]))
    replacements = []
    for url in images:
        if not isinstance(url, str) or _url_key(url, source_url) in allowed_keys:
            continue
        options = (source_images or fallback_images or source_assets) if url in hero else (repair_images or source_assets)
        if not options:
            continue
        unused = [item for item in options if item not in {row["to"] for row in replacements}]
        options = unused or options
        new_url = options[0]
        next_source, next_css = _replace(source, url, new_url), _replace(css, url, new_url)
        if next_source != source or next_css != css:
            replacements.append({"from": url, "to": new_url, "hero": url in hero})
            source, css = next_source, next_css
    if not hero and checker.get("hero_image_present") is False and repair_images:
        parser = _Nodes(source)
        try:
            parser.feed(source)
        except Exception:
            parser.hero = None
        hero_node = parser.hero
        if hero_node and (
            hero_node["tag"] == "section"
            or {"hero", "banner"} & set(hero_node["attrs"].get("class", "").casefold().split())
        ) and HERO_IMAGE_MARKER not in css:
            hero_url = repair_images[0]
            start, end = hero_node["start"], hero_node["end"]
            opening = _classes(hero_node["raw"], {"quality-repair-hero"}, set())
            media = f'<img class="quality-repair-hero-media" src="{html.escape(hero_url, quote=True)}" alt="" aria-hidden="true">'
            source = source[:start] + opening + media + source[end:]
            css = css.rstrip() + (
                f"\n{HERO_IMAGE_MARKER}\n"
                ".quality-repair-hero{position:relative!important;isolation:isolate!important;overflow:hidden!important}"
                ".quality-repair-hero>.quality-repair-hero-media{position:absolute!important;inset:0!important;"
                "z-index:-1!important;width:100%!important;height:100%!important;object-fit:cover!important;"
                "object-position:center!important;pointer-events:none!important}\n"
            )
            replacements.append({
                "from": None, "to": hero_url, "hero": True,
                "action": "inserted verified category/source image into a measured empty hero",
            })
    if replacements:
        html_path.write_text(source, encoding="utf-8")
        css_path.write_text(css, encoding="utf-8")
    return replacements


def _repair_cta(candidate: Path, browser: dict) -> list[str]:
    css_path = candidate / "files" / "styles.css"
    if not css_path.is_file():
        return []
    selectors = []
    for viewport in browser.get("viewports", {}).values():
        for issue in viewport.get("primary_cta_contrast", {}).get("issues", []):
            selector = str(issue.get("selector", "")).strip()
            if selector and SAFE_SELECTOR.fullmatch(selector) and selector not in selectors:
                selectors.append(selector)
    if not selectors:
        return []
    css = css_path.read_text(encoding="utf-8", errors="replace")
    if CTA_MARKER in css:
        css = css.split(CTA_MARKER, 1)[0].rstrip()
    rules = [f"{selector} {{ color:#17251d !important; background-color:#fff !important; background-image:none !important; border:2px solid #17251d !important; text-shadow:none !important; }}" for selector in selectors]
    css_path.write_text(css.rstrip() + "\n\n" + CTA_MARKER + "\n" + "\n".join(rules) + "\n", encoding="utf-8")
    return selectors


def _repair_layout(candidate: Path, layout: dict) -> list[str]:
    profile = layout.get("profile")
    if profile not in {"forty", "landed", "story"}:
        return []
    html_path, css_path = candidate / "files" / "index.html", candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return []
    source = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _Nodes(source)
    try:
        parser.feed(source)
    except Exception:
        return []
    edits, repairs = [], []
    if parser.hero:
        add = {"banner"}
        if profile == "forty": add.add("major")
        if profile == "story": add.add("fullscreen")
        updated = _classes(parser.hero["raw"], add, set(), "banner")
        if updated != parser.hero["raw"]:
            edits.append((parser.hero["start"], parser.hero["end"], updated))
            repairs.append(f"restored {profile} hero markers")
    needed = 3 if profile == "landed" else 2 if profile == "story" else 0
    for index, node in enumerate(parser.spotlights[:needed]):
        side = "left" if index % 2 == 0 else "right"
        add = ({f"style{index + 1}", side} if profile == "landed" else {"orient-left" if index % 2 == 0 else "orient-right", side})
        remove = {"left", "right", "top", "bottom", "style1", "style2", "style3", "orient-left", "orient-right"}
        updated = _classes(node["raw"], add, remove)
        if updated != node["raw"]:
            edits.append((node["start"], node["end"], updated))
            repairs.append(f"aligned {profile} section {index + 1}")
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    if edits:
        html_path.write_text(source, encoding="utf-8")
    css = css_path.read_text(encoding="utf-8", errors="replace")
    if profile == "forty" and parser.tiles and LAYOUT_MARKER not in css:
        css += f"\n{LAYOUT_MARKER}\nmain .tiles{{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:1.25rem!important}}@media(max-width:700px){{main .tiles{{grid-template-columns:1fr!important}}}}\n"
        css_path.write_text(css, encoding="utf-8")
        repairs.append("restored Forty tile grid")
    if profile == "landed":
        actual = layout.get("actual", {}).get("spotlight_media_sides", [])
        if len(actual) >= 3 and all(side in {"left", "right"} for side in actual[:3]) and layout.get("actual", {}).get("spotlight_side_alternations", 0) < 2 and LAYOUT_MARKER not in css:
            target = min((("left", "right", "left"), ("right", "left", "right")), key=lambda pattern: sum(a != b for a, b in zip(actual[:3], pattern)))
            rules = [LAYOUT_MARKER, "@media(min-width:701px){"]
            for index, side in enumerate(target, 1):
                media_order = 1 if side == "left" else 2
                content_order = 3 - media_order
                selector = f".spotlight.style{index}"
                rules.extend([f"{selector}{{display:flex!important;flex-direction:row!important}}", f"{selector}>.image,{selector}>picture,{selector}>img,{selector}>video{{order:{media_order}!important;flex:1 1 50%!important;min-width:0!important}}", f"{selector}>.content{{order:{content_order}!important;flex:1 1 50%!important;min-width:0!important}}"])
            rules.append("}")
            css_path.write_text(css.rstrip() + "\n" + "\n".join(rules) + "\n", encoding="utf-8")
            repairs.append("corrected measured Landed media order")
    return repairs


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    debug = candidate / "debug"
    checker, browser = _read(debug / "checker_report.json"), _read(debug / "browser_qa.json")
    context_path = debug / "website_context.md"
    context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.is_file() else ""
    failures = set(checker.get("repair_checks", checker.get("blocking_failures", [])))
    image_replacements = _repair_images(candidate, checker, context) if failures & IMAGE_CHECKS else []
    cta_selectors = _repair_cta(candidate, browser) if CTA_CHECK in failures else []
    layout = browser.get("template_layout", {})
    layout_repairs = _repair_layout(candidate, layout) if LAYOUT_CHECK in failures and isinstance(layout, dict) else []
    result = {
        "status": "repaired" if image_replacements or cta_selectors or layout_repairs else "no_safe_repair_available",
        "changed": bool(image_replacements or cta_selectors or layout_repairs),
        "triggered_failures": sorted(failures & (IMAGE_CHECKS | {CTA_CHECK, LAYOUT_CHECK})),
        "image_replacements": image_replacements,
        "image_evidence": {
            "failed_urls": checker.get("failed_image_urls", []),
            "observed_hero_urls": checker.get("hero_image_urls", []),
            "observed_image_urls": checker.get("image_urls", []),
            "approved_source_urls": _source_image_urls_from_prompt(context),
            "approved_category_urls": _category_fallback_image_urls_from_prompt(context),
        } if failures & IMAGE_CHECKS else None,
        "primary_cta_evidence": {
            "issues": [
                issue
                for data in browser.get("viewports", {}).values()
                if isinstance(data, dict)
                for issue in data.get("primary_cta_contrast", {}).get("issues", [])
                if isinstance(issue, dict)
            ],
            "minimum_text_contrast_ratio": 4.5,
        } if CTA_CHECK in failures else None,
        "cta_selectors": cta_selectors,
        "layout_repairs": layout_repairs,
        "template_layout": {
            "expected": layout.get("expected", {}),
            "actual": layout.get("actual", {}),
            "targeted_correction": layout_repairs or "No safe correction was measured; retry guidance includes expected and actual signatures.",
        } if LAYOUT_CHECK in failures and isinstance(layout, dict) else None,
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
