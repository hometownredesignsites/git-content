#!/usr/bin/env python3
"""Apply one bounded repair pass for measured Duck.ai candidate failures."""

from __future__ import annotations

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

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
FORM_CHECK = "requested_form_present"
FORM_FIELDS_CHECK = "source_contact_form_fields_preserved"
FORM_REQUIRED_CHECK = "source_contact_form_required_states_preserved"
FORM_TYPES_CHECK = "source_contact_form_types_preserved"
SECTION_VISIBILITY_CHECK = "rendered_sections_visible_desktop_and_mobile"
SERVICES_CHECK = "section_services"
FIRST_SCREEN_CTA_CHECK = "cta_visible_first_screen_desktop_and_mobile"
CSS_LINK_CHECK = "styles_css_linked"
FILE_UPLOAD_CHECK = "public_file_uploads_omitted"
CTA_VISIBILITY_CHECK = "cta_visible_first_screen_desktop_and_mobile"


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
            specific_cta = bool(re.search(r"\.(?:button|btn|cta|primary|call[-_]?to[-_]?action)(?:$|[.#:\s>])", selector, re.IGNORECASE))
            anchored_path = selector.startswith("#") and len(selector) > 1
            generic_control = selector.lower() in {"a", "button", "input", "[role=button]", "*"}
            if (selector and not generic_control and (specific_cta or anchored_path)
                    and SAFE_SELECTOR.fullmatch(selector) and selector not in selectors):
                selectors.append(selector)
    if not selectors:
        return []
    css = css_path.read_text(encoding="utf-8", errors="replace")
    if CTA_MARKER in css:
        css = css.split(CTA_MARKER, 1)[0].rstrip()
    rules = [f"{selector} {{ color:#17251d !important; background-color:#fff !important; border:2px solid #17251d !important; text-shadow:none !important; }}" for selector in selectors]
    css_path.write_text(css.rstrip() + "\n\n" + CTA_MARKER + "\n" + "\n".join(rules) + "\n", encoding="utf-8")
    return selectors


def _repair_stylesheet_link(candidate: Path) -> bool:
    """Link the existing generated stylesheet when HTML omitted the link."""
    html_path = candidate / "files" / "index.html"
    css_path = candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return False
    source = html_path.read_text(encoding="utf-8", errors="replace")
    if re.search(
        r"<link\b(?=[^>]*\brel\s*=\s*(['\"])stylesheet\1)(?=[^>]*\bhref\s*=\s*(['\"])(?:\./)?styles\.css\2)[^>]*>",
        source,
        re.IGNORECASE,
    ):
        return False
    link = '<link rel="stylesheet" href="styles.css">'
    head_close = re.search(r"</head\s*>", source, re.IGNORECASE)
    if head_close:
        source = source[:head_close.start()] + link + "\n" + source[head_close.start():]
    else:
        head_open = re.search(r"<head\b[^>]*>", source, re.IGNORECASE)
        if head_open:
            source = source[:head_open.end()] + "\n" + link + source[head_open.end():]
        else:
            html_open = re.search(r"<html\b[^>]*>", source, re.IGNORECASE)
            if not html_open:
                return False
            source = source[:html_open.end()] + "\n<head>" + link + "</head>" + source[html_open.end():]
    html_path.write_text(source, encoding="utf-8")
    return True


def _remove_public_file_uploads(candidate: Path) -> int:
    """Remove public file inputs from the demo markup, as required by policy."""
    html_path = candidate / "files" / "index.html"
    if not html_path.is_file():
        return 0
    source = html_path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r"<input\b(?=[^>]*\btype\s*=\s*(?:['\"]file['\"]|file\b))[^>]*?/?>",
        re.IGNORECASE | re.DOTALL,
    )
    updated, count = pattern.subn("", source)
    if count:
        html_path.write_text(updated, encoding="utf-8")
    return count


def _repair_mobile_navigation(candidate: Path, browser: dict, failures: set[str]) -> list[str]:
    checks = {
        "browser_mobile_menu_clicks_work", "browser_mobile_menu_keyboard_works",
        "browser_mobile_navigation_hidden_until_opened", "browser_mobile_menu_focus_indicator_visible",
    }
    if not failures & checks:
        return []
    html_path = candidate / "files" / "index.html"
    css_path = candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return []
    menu = browser.get("mobile_menu", {}) if isinstance(browser, dict) else {}
    nav_id = str(menu.get("controlled_nav_id", "")) if isinstance(menu, dict) else ""
    if (not re.fullmatch(r"[A-Za-z0-9_-]+", nav_id)
            or menu.get("button_inside_navigation") is not False):
        return []
    source = html_path.read_text(encoding="utf-8", errors="replace")
    css = css_path.read_text(encoding="utf-8", errors="replace")
    marker = "/* QA repair pass: measured mobile navigation behavior. */"
    if marker in source or marker in css:
        return []
    escaped_id = re.escape(nav_id)
    if not re.search(rf"<nav\b(?=[^>]*\bid\s*=\s*(['\"]){escaped_id}\1)[^>]*>", source, re.IGNORECASE):
        return []
    button = re.search(rf"<button\b(?=[^>]*\baria-controls\s*=\s*(['\"]){escaped_id}\1)[^>]*>", source, re.IGNORECASE)
    if not button:
        return []
    body_close = re.search(r"</body\s*>", source, re.IGNORECASE)
    if not body_close:
        return []
    script = f'''\n<script>
  {marker}
  (() => {{
    const id = {json.dumps(nav_id)};
    const button = document.querySelector(`button[aria-controls="${{id}}"]`);
    const menu = document.getElementById(id);
    if (!button || !menu || menu.contains(button)) return;
    const setOpen = open => {{
      button.setAttribute("aria-expanded", String(open));
      menu.hidden = !open;
      menu.setAttribute("aria-hidden", String(!open));
      menu.classList.toggle("is-open", open);
    }};
    setOpen(false);
    document.addEventListener("click", event => {{
      const target = event.target instanceof Element ? event.target : null;
      if (target && target.closest(`button[aria-controls="${{id}}"]`) === button) {{
        event.preventDefault(); event.stopImmediatePropagation();
        setOpen(button.getAttribute("aria-expanded") !== "true");
      }} else if (button.getAttribute("aria-expanded") === "true" && target && target.closest("a") && menu.contains(target)) {{
        setOpen(false);
      }}
    }}, true);
    document.addEventListener("keydown", event => {{
      if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {{
        event.preventDefault(); event.stopImmediatePropagation(); setOpen(false); button.focus();
      }}
    }}, true);
  }})();
</script>\n'''
    css += (
        f"\n\n{marker}\n"
        f'@media (max-width: 700px) {{ nav[id="{nav_id}"][hidden] {{ display:none !important; }} '
        f'nav[id="{nav_id}"]:not([hidden]) {{ display:flex !important; flex-direction:column !important; }} '
        f'button[aria-controls="{nav_id}"]:focus-visible {{ outline:3px solid var(--accent-warm,#f5c36a) !important; outline-offset:3px !important; }} }}\n'
    )
    html_path.write_text(source[:body_close.start()] + script + source[body_close.start():], encoding="utf-8")
    css_path.write_text(css, encoding="utf-8")
    return ["restored click, keyboard activation, Escape, and visibility behavior for the measured mobile menu"]


def _repair_first_screen_cta(candidate: Path, browser: dict) -> dict | None:
    html_path = candidate / "files" / "index.html"
    css_path = candidate / "files" / "styles.css"
    if not html_path.is_file() or not css_path.is_file():
        return None
    source = html_path.read_text(encoding="utf-8", errors="replace")
    if 'id="qa-first-screen-cta"' in source:
        return None
    viewports = browser.get("viewports", {}) if isinstance(browser, dict) else {}
    cta = None
    if isinstance(viewports, dict):
        for name in ("desktop", "mobile"):
            viewport = viewports.get(name, {})
            candidate_cta = viewport.get("cta", {}) if isinstance(viewport, dict) else {}
            if isinstance(candidate_cta, dict) and candidate_cta.get("href") and candidate_cta.get("text"):
                cta = candidate_cta
                break
    if not isinstance(cta, dict):
        return None
    href = html.unescape(str(cta.get("href", "")).strip())
    parsed = urlsplit(href)
    if not href or parsed.scheme.casefold() not in {"", "http", "https", "mailto", "tel"}:
        return None
    if parsed.scheme.casefold() in {"http", "https"} or parsed.netloc:
        source_url = str(_read(candidate / "run_notes.json").get("source_url", ""))
        if not source_url or (urlsplit(parsed.geturl()).hostname or "").casefold() != (urlsplit(source_url).hostname or "").casefold():
            return None
    label = " ".join(str(cta.get("text", "")).split())
    if not label or re.search(r"[<>\r\n]", label):
        return None
    heading = re.search(r"</h1\s*>", source, re.IGNORECASE)
    if not heading:
        return None
    anchor = (
        f'\n<a id="qa-first-screen-cta" class="button primary" href="{html.escape(href, quote=True)}">'
        f'{html.escape(label)}</a>\n'
    )
    source = source[:heading.end()] + anchor + source[heading.end():]
    css = css_path.read_text(encoding="utf-8", errors="replace")
    css += (
        "\n\n/* QA repair pass: place measured primary action in the first screen. */\n"
        "#qa-first-screen-cta{display:inline-flex!important;visibility:visible!important;opacity:1!important;"
        "position:relative;z-index:2;margin-top:1rem;color:#fff!important;background-color:var(--accent-dark,#24352b)!important;"
        "border:2px solid var(--accent-dark,#24352b)!important;text-shadow:none!important}\n"
        "#qa-first-screen-cta::before,#qa-first-screen-cta::after{content:none!important}\n"
    )
    html_path.write_text(source, encoding="utf-8")
    css_path.write_text(css, encoding="utf-8")
    return {"label": label, "href": href, "inserted_after": "h1"}


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


def _repair_verified_form(candidate: Path) -> dict | None:
    """Add a clearly labeled, non-submitting preview from audited source fields."""
    html_path = candidate / "files" / "index.html"
    assessment = _read(candidate / "debug" / "source_assessment.json")
    fields = assessment.get("contact_form_fields", [])
    if not html_path.is_file() or not isinstance(fields, list) or not fields:
        return None
    source_url = str(_read(candidate / "run_notes.json").get("source_url", ""))
    source_host = (urlsplit(source_url).hostname or "").casefold().removeprefix("www.")
    reviewed = {
        str(page.get("url", "")) for page in assessment.get("pages_reviewed", [])
        if isinstance(page, dict)
    }
    verified = []
    for field in fields:
        if len(verified) >= 16:
            break
        if not isinstance(field, dict):
            continue
        field_type = str(field.get("type") or field.get("input_type") or "").strip().casefold()
        if field_type == "file":
            continue
        citations = field.get("source_urls", [])
        if not isinstance(citations, list) or not any(url in reviewed for url in citations):
            continue
        if not any((urlsplit(str(url)).hostname or "").casefold().removeprefix("www.") == source_host for url in citations):
            continue
        label = str(field.get("label") or field.get("field") or "").strip()
        if label:
            verified.append(field)
    if not verified:
        return None

    source = html_path.read_text(encoding="utf-8", errors="replace")
    form_exists = bool(re.search(r"<form\b", source, re.IGNORECASE))
    present_labels = {
        " ".join(html.unescape(value).split()).casefold()
        for value in re.findall(r"<label\b[^>]*>([\s\S]*?)</label\s*>", source, re.IGNORECASE)
    }
    verified = [field for field in verified if " ".join(str(field.get("label") or field.get("field") or "").split()).casefold() not in present_labels]
    controls = []
    allowed_types = {
        "text", "email", "tel", "url", "number", "date", "datetime-local", "month", "time", "week",
        "search", "password", "checkbox", "radio", "color", "range",
    }
    for index, field in enumerate(verified, start=1):
        label = html.escape(str(field.get("label") or field.get("field") or "").strip())
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", str(field.get("name") or f"inquiry-field-{index}")).strip("-")
        control_id = f"verified-inquiry-{index}"
        field_type = str(field.get("type") or field.get("input_type") or "text").casefold()
        required = " required" if field.get("required") is True else ""
        placeholder = field.get("placeholder")
        placeholder_attr = f' placeholder="{html.escape(str(placeholder), quote=True)}"' if isinstance(placeholder, str) and placeholder else ""
        if field_type == "textarea":
            control = f'<textarea id="{control_id}" name="{html.escape(name, quote=True)}"{required}{placeholder_attr}></textarea>'
        elif field_type in {"select", "dropdown"}:
            options = [str(value) for value in field.get("options", []) if isinstance(value, (str, int, float))]
            if not options:
                continue
            option_html = "".join(f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>' for value in options)
            control = f'<select id="{control_id}" name="{html.escape(name, quote=True)}"{required}>{option_html}</select>'
        else:
            normalized_type = field_type if field_type in allowed_types else "text"
            control = f'<input id="{control_id}" name="{html.escape(name, quote=True)}" type="{normalized_type}"{required}{placeholder_attr}>'
        controls.append(f'<div class="field"><label for="{control_id}">{label}</label>{control}</div>')
    if not controls:
        return None
    if form_exists:
        form_close = re.search(r"</form\s*>", source, re.IGNORECASE)
        if not form_close:
            return None
        updated = source[:form_close.start()] + "\n" + "".join(controls) + source[form_close.start():]
        html_path.write_text(updated, encoding="utf-8")
        return {"fields_added": len(controls), "reason": "added verified source fields missing from the candidate form"}
    section = (
        '<section id="verified-inquiry"><h2>Project inquiry</h2>'
        '<p>This form preview does not submit messages.</p><form aria-label="Project inquiry preview">'
        + "".join(controls) + "</form></section>\n"
    )
    insertion = re.search(r"</main\s*>", source, re.IGNORECASE)
    if insertion:
        updated = source[:insertion.start()] + section + source[insertion.start():]
    else:
        footer = re.search(r"<footer\b", source, re.IGNORECASE)
        if not footer:
            return None
        updated = source[:footer.start()] + section + source[footer.start():]
    html_path.write_text(updated, encoding="utf-8")
    return {"fields_added": len(controls), "reason": "verified source fields were present and the candidate omitted a form"}


def _repair_verified_services(candidate: Path) -> dict | None:
    """Insert a services section only when the source audit explicitly typed facts as services."""
    html_path = candidate / "files" / "index.html"
    assessment = _read(candidate / "debug" / "source_assessment.json")
    reviewed = {
        str(page.get("url", "")) for page in assessment.get("pages_reviewed", [])
        if isinstance(page, dict)
    }
    source_url = str(_read(candidate / "run_notes.json").get("source_url", ""))
    source_host = (urlsplit(source_url).hostname or "").casefold().removeprefix("www.")
    facts = assessment.get("organization_facts", [])
    verified = []
    for item in facts if isinstance(facts, list) else []:
        if not isinstance(item, dict) or str(item.get("kind", "")).casefold() != "service":
            continue
        fact = str(item.get("fact", "")).strip()
        citations = item.get("source_urls", [])
        if not fact or not isinstance(citations, list):
            continue
        if not any(str(url) in reviewed and (urlsplit(str(url)).hostname or "").casefold().removeprefix("www.") == source_host for url in citations):
            continue
        verified.append(fact)
    if not verified or not html_path.is_file():
        return None
    source = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _Nodes(source)
    try:
        parser.feed(source)
    except Exception:
        return None
    # A visible alias already exists, so don't add duplicate content when the
    # static check failed for another structural reason.
    if re.search(r"\b(?:services?|repairs?|offerings?)\b", source, re.IGNORECASE):
        return None
    items = "".join(f"<li>{html.escape(fact)}</li>" for fact in verified[:8])
    section = f'<section id="services"><h2>Services</h2><ul>{items}</ul></section>\n'
    insertion = re.search(r"</main\s*>", source, re.IGNORECASE)
    if insertion:
        updated = source[:insertion.start()] + section + source[insertion.start():]
    else:
        return None
    html_path.write_text(updated, encoding="utf-8")
    return {"facts_added": min(len(verified), 8), "reason": "only source-cited facts explicitly typed as services were available"}


def _repair_section_visibility(candidate: Path, browser: dict) -> list[str]:
    """Restore visibility only on sections/ancestors identified by browser QA."""
    css_path = candidate / "files" / "styles.css"
    if not css_path.is_file():
        return []
    selectors = []
    for viewport in browser.get("viewports", {}).values():
        sections = viewport.get("sections", {}) if isinstance(viewport, dict) else {}
        for result in sections.values() if isinstance(sections, dict) else []:
            if (not isinstance(result, dict) or result.get("visible") is not False
                    or result.get("style_hidden") is not True or result.get("aria_hidden_ancestor") is True):
                continue
            candidates = [result.get("selector_hint"), *result.get("hidden_ancestors", [])]
            for selector in candidates:
                selector = str(selector or "").strip()
                if selector and SAFE_SELECTOR.fullmatch(selector) and selector not in selectors:
                    selectors.append(selector)
    if not selectors:
        return []
    css = css_path.read_text(encoding="utf-8", errors="replace")
    marker = "/* QA repair pass: restore measured section visibility. */"
    if marker in css:
        css = css.split(marker, 1)[0].rstrip()
    rules = [f"{selector}{{display:revert!important;visibility:visible!important;opacity:1!important}}" for selector in selectors]
    css_path.write_text(css.rstrip() + "\n\n" + marker + "\n" + "\n".join(rules) + "\n", encoding="utf-8")
    return selectors


def repair(candidate: Path, only_check: str | None = None) -> dict:
    candidate = candidate.resolve()
    debug = candidate / "debug"
    checker, browser = _read(debug / "checker_report.json"), _read(debug / "browser_qa.json")
    context_path = debug / "website_context.md"
    context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.is_file() else ""
    failures = set(checker.get("repair_checks", checker.get("blocking_failures", [])))
    targeted_failures = failures if only_check is None else ({only_check} & failures)
    image_replacements = _repair_images(candidate, checker, context) if targeted_failures & IMAGE_CHECKS else []
    cta_selectors = _repair_cta(candidate, browser) if CTA_CHECK in targeted_failures else []
    stylesheet_link_repaired = _repair_stylesheet_link(candidate) if CSS_LINK_CHECK in targeted_failures else False
    removed_file_uploads = _remove_public_file_uploads(candidate) if FILE_UPLOAD_CHECK in targeted_failures else 0
    mobile_navigation_repairs = _repair_mobile_navigation(candidate, browser, targeted_failures)
    first_screen_cta = _repair_first_screen_cta(candidate, browser) if CTA_VISIBILITY_CHECK in targeted_failures else None
    form_repair = _repair_verified_form(candidate) if targeted_failures & {FORM_CHECK, FORM_FIELDS_CHECK, FORM_REQUIRED_CHECK, FORM_TYPES_CHECK} else None
    services_repair = _repair_verified_services(candidate) if SERVICES_CHECK in targeted_failures else None
    visibility_selectors = _repair_section_visibility(candidate, browser) if SECTION_VISIBILITY_CHECK in targeted_failures else []
    layout = browser.get("template_layout", {})
    layout_repairs = _repair_layout(candidate, layout) if LAYOUT_CHECK in targeted_failures and isinstance(layout, dict) else []
    result = {
        "status": "repaired" if image_replacements or cta_selectors or layout_repairs or form_repair or services_repair or visibility_selectors or stylesheet_link_repaired or removed_file_uploads or mobile_navigation_repairs or first_screen_cta else "no_safe_repair_available",
        "changed": bool(image_replacements or cta_selectors or layout_repairs or form_repair or services_repair or visibility_selectors or stylesheet_link_repaired or removed_file_uploads or mobile_navigation_repairs or first_screen_cta),
        "triggered_failures": sorted(targeted_failures & (IMAGE_CHECKS | {CTA_CHECK, LAYOUT_CHECK, FORM_CHECK, FORM_FIELDS_CHECK, FORM_REQUIRED_CHECK, FORM_TYPES_CHECK, SERVICES_CHECK, SECTION_VISIBILITY_CHECK, FIRST_SCREEN_CTA_CHECK, CSS_LINK_CHECK, FILE_UPLOAD_CHECK, "browser_mobile_menu_clicks_work", "browser_mobile_menu_keyboard_works", "browser_mobile_navigation_hidden_until_opened", "browser_mobile_menu_focus_indicator_visible"})),
        "image_replacements": image_replacements,
        "image_evidence": {
            "failed_urls": checker.get("failed_image_urls", []),
            "observed_hero_urls": checker.get("hero_image_urls", []),
            "observed_image_urls": checker.get("image_urls", []),
            "approved_source_urls": _source_image_urls_from_prompt(context),
            "approved_category_urls": _category_fallback_image_urls_from_prompt(context),
        } if targeted_failures & IMAGE_CHECKS else None,
        "primary_cta_evidence": {
            "issues": [
                issue
                for data in browser.get("viewports", {}).values()
                if isinstance(data, dict)
                for issue in data.get("primary_cta_contrast", {}).get("issues", [])
                if isinstance(issue, dict)
            ],
            "minimum_text_contrast_ratio": 4.5,
        } if CTA_CHECK in targeted_failures else None,
        "cta_selectors": cta_selectors,
        "stylesheet_link_repaired": stylesheet_link_repaired,
        "public_file_uploads_removed": removed_file_uploads,
        "mobile_navigation_repairs": mobile_navigation_repairs,
        "first_screen_cta": first_screen_cta,
        "layout_repairs": layout_repairs,
        "verified_form_repair": form_repair,
        "verified_services_repair": services_repair,
        "section_visibility_selectors": visibility_selectors,
        "template_layout": {
            "expected": layout.get("expected", {}),
            "actual": layout.get("actual", {}),
            "targeted_correction": layout_repairs or "No safe correction was measured; retry guidance includes expected and actual signatures.",
        } if LAYOUT_CHECK in targeted_failures and isinstance(layout, dict) else None,
    }
    debug.mkdir(parents=True, exist_ok=True)
    (debug / "quality_repair.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--only-check", help="attempt a safe repair for only this current failed check")
    args = parser.parse_args()
    repair(args.candidate, args.only_check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
