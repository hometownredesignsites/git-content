"""Build a compact, source-traceable generation brief from Duck.ai's audit."""

from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MAX_BRIEF_CHARS = 4800
MAX_ASSETS = 5
MAX_SOURCE_PHOTOS = 3
MAX_CONTACT_FIELDS = 16
MAX_NAVIGATION_LINKS = 3
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "share"}

FALLBACK_IMAGES = {
    "fence": [
        ("https://images.unsplash.com/photo-1769831190663-95fe8454d8c9?auto=format&fit=crop&w=1800&q=85", "wooden fence and gate"),
        ("https://images.unsplash.com/photo-1792628953895-5d46f431b402?auto=format&fit=crop&w=1800&q=85", "backyard privacy fence"),
        ("https://images.unsplash.com/photo-1769690177043-c28ce822a4f7?auto=format&fit=crop&w=1800&q=85", "garden gate and fence"),
    ],
    "deck": [
        ("https://images.unsplash.com/photo-1773979638724-c6ffed7fe0de?auto=format&fit=crop&w=1800&q=85", "wooden backyard deck"),
        ("https://images.unsplash.com/photo-1716904519810-349244919824?auto=format&fit=crop&w=1800&q=85", "outdoor deck and seating"),
        ("https://images.unsplash.com/photo-1741277031817-146e7ed13f8d?auto=format&fit=crop&w=1800&q=85", "backyard pool and deck"),
    ],
    "landscape": [
        ("https://images.unsplash.com/photo-1416879595882-3373a0480b5b?auto=format&fit=crop&w=1800&q=85", "garden planting and landscape work"),
        ("https://images.unsplash.com/photo-1585320806297-9794b3e4eeae?auto=format&fit=crop&w=1800&q=85", "garden plants and outdoor design"),
        ("https://images.unsplash.com/photo-1501004318641-b39e6451bec6?auto=format&fit=crop&w=1800&q=85", "plants and garden detail"),
    ],
    "interior": [
        ("https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1800&q=85", "finished home interior and renovation"),
        ("https://images.unsplash.com/photo-1600566753086-00f18fb6b3ea?auto=format&fit=crop&w=1800&q=85", "home renovation interior"),
        ("https://images.unsplash.com/photo-1770063817031-f3b98dff347f?auto=format&fit=crop&w=1800&q=85", "modern kitchen and flooring"),
    ],
    "carpentry": [
        ("https://images.unsplash.com/photo-1769353086138-19ee65291a04?auto=format&fit=crop&w=1800&q=85", "carpenter working with wood"),
        ("https://images.unsplash.com/photo-1722411927625-0e478acf502b?auto=format&fit=crop&w=1800&q=85", "woodworker in a workshop"),
        ("https://images.unsplash.com/photo-1759756480941-7230dedf5fc9?auto=format&fit=crop&w=1800&q=85", "woodworking tools and machinery"),
    ],
}


def category_fallback_candidates(category: str) -> list[dict]:
    lowered = category.casefold()
    key = None
    if any(term in lowered for term in ("fence", "gate")):
        key = "fence"
    elif any(term in lowered for term in ("deck", "patio")):
        key = "deck"
    elif any(term in lowered for term in ("landscape", "garden", "lawn")):
        key = "landscape"
    elif any(term in lowered for term in ("floor", "tile", "carpet", "kitchen", "bath", "home", "remodel", "renovat")):
        key = "interior"
    elif any(term in lowered for term in ("carpent", "woodwork")):
        key = "carpentry"
    return [{"url": url, "type": "verified_category_fallback", "context": description}
            for url, description in FALLBACK_IMAGES.get(key, [])]


def _text(value: object, limit: int = 160) -> str:
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    if isinstance(value, dict):
        for key in ("fact", "text", "answer", "value", "label", "field", "section", "observation", "name"):
            if isinstance(value.get(key), str):
                return " ".join(value[key].split())[:limit]
    return ""


def _source_urls(item: object, valid_sources: set[str]) -> list[str]:
    values = []
    if isinstance(item, dict):
        for key in ("source_urls", "sources", "source_url", "page_url", "found_on", "where_it_appears", "url"):
            value = item.get(key)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(entry for entry in value if isinstance(entry, str))
    normalized = []
    for value in values:
        if value in valid_sources and value not in normalized:
            normalized.append(value)
    return normalized[:2]


def _render_items(title: str, values: object, valid_sources: set[str], limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for item in values:
        fact = _text(item)
        sources = _source_urls(item, valid_sources)
        if not fact or not sources:
            continue
        detail = ""
        if "CONTACT FORM" in title and isinstance(item, dict):
            required = item.get("required")
            detail = " [required]" if required is True else " [optional]" if required is False else " [required status unknown]"
        if title == "FAQ ANSWERS" and isinstance(item, dict):
            question = _text(item.get("question"), 140)
            if question:
                fact = f"Q: {question} A: {fact}"
        result.append(f"- {fact}{detail} (source: {', '.join(sources)})")
        if len(result) >= limit:
            break
    return [f"{title}:\n" + "\n".join(result)] if result else []


def _render_contact_form(values: object, valid_sources: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    fields = []
    for item in values:
        if len(fields) >= MAX_CONTACT_FIELDS:
            break
        if not isinstance(item, dict):
            continue
        field_type = _text(item.get("type") or item.get("input_type"), 40).casefold()
        # Public uploads are excluded from generated demos even when the source has them.
        if field_type == "file":
            continue
        raw_label = item.get("label") or item.get("field")
        label = " ".join(raw_label.split()) if isinstance(raw_label, str) else ""
        sources = _source_urls(item, valid_sources)
        if not label or not sources:
            continue
        details = []
        if field_type:
            details.append(f"type={field_type}")
        required = item.get("required")
        details.append("required" if required is True else "optional" if required is False else "required status unknown")
        placeholder = item.get("placeholder")
        if isinstance(placeholder, str) and placeholder:
            details.append(f"placeholder={json.dumps(placeholder, ensure_ascii=False)}")
        options = item.get("options")
        if isinstance(options, list) and options:
            details.append("options=" + json.dumps(options, ensure_ascii=False))
        name = item.get("name")
        name = " ".join(name.split()) if isinstance(name, str) else ""
        if name:
            details.append(f"name={name}")
        fields.append(f"- {label} ({'; '.join(details)}) (source: {', '.join(sources)})")
    return ["CONTACT FORM (preserve exact fields and supplied attributes):\n" + "\n".join(fields)] if fields else []


def _render_navigation(values: object, valid_sources: set[str], source_host: str) -> list[str]:
    if not isinstance(values, list):
        return []
    links = []
    seen = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"), 80)
        target = str(item.get("url") or item.get("href") or "").strip()
        cited_pages = _source_urls({"source_urls": item.get("source_urls") or item.get("page_url")}, valid_sources)
        parsed = urlsplit(target)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        if not label or not cited_pages or parsed.scheme not in {"http", "https"} or host != source_host:
            continue
        query = urlencode([
            (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS and not key.casefold().startswith("utm_")
        ])
        clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))
        dedupe_key = (
            parsed.scheme.casefold(), host, (parsed.path.rstrip("/") or "/").casefold(),
            tuple(sorted(parse_qsl(query, keep_blank_values=True))),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        links.append(f"- {label}: {clean_url} (observed on: {cited_pages[0]})")
        if len(links) >= MAX_NAVIGATION_LINKS:
            break
    return ["SOURCE NAVIGATION (verified internal links):\n" + "\n".join(links)] if links else []


def build_compact_source_brief(
    assessment: dict,
    category_fallback_images: list[dict] | None = None,
    expected_source_url: str = "",
    verified_asset_source_pages: list[str] | None = None,
) -> str:
    """Keep only source-backed facts and URLs from pages the audit says it reviewed."""
    if not isinstance(assessment, dict):
        return ""
    reviewed_pages = assessment.get("pages_reviewed", [])
    base_url = expected_source_url or next(
        (str(item.get("url", "")) for item in reviewed_pages if isinstance(item, dict)), ""
    )
    source_host = (urlsplit(base_url).hostname or "").casefold().removeprefix("www.")
    valid_sources = {
        str(item.get("url", ""))
        for item in reviewed_pages
        if isinstance(item, dict)
        and urlsplit(str(item.get("url", ""))).scheme in {"http", "https"}
        and (urlsplit(str(item.get("url", ""))).hostname or "").casefold().removeprefix("www.") == source_host
    }
    sections = []
    core_facts = _render_items("IDENTITY / SERVICES / LOCATIONS", assessment.get("organization_facts"), valid_sources, 6)
    if not core_facts:
        return ""
    sections.extend(core_facts)
    service_facts = assessment.get("organization_facts", [])
    if isinstance(service_facts, list):
        verified_services = [
            item for item in service_facts
            if isinstance(item, dict) and str(item.get("kind", "")).strip().casefold() == "service"
        ]
        sections.extend(_render_items("VERIFIED SERVICES (source-backed facts only)", verified_services, valid_sources, 8))
    for title, key, limit in (
        ("SELLING POINTS", "selling_points", 3),
        ("CONTACT DETAILS", "contact_details", 5),
        ("FAQ ANSWERS", "faq_answers", 3),
        ("IMPORTANT SOURCE SECTIONS", "content_structure", 4),
    ):
        sections.extend(_render_items(title, assessment.get(key), valid_sources, limit))
    sections.extend(_render_contact_form(assessment.get("contact_form_fields"), valid_sources))
    sections.extend(_render_navigation(assessment.get("navigation_links"), valid_sources, source_host))

    visual = assessment.get("brand_and_visual_observations")
    visual_items = visual if isinstance(visual, list) else [visual]
    sections.extend(_render_items("SOURCE VISUAL OBSERVATIONS", visual_items, valid_sources, 2))

    audience = assessment.get("audience_and_goals")
    if isinstance(audience, dict):
        goal = _text(audience.get("primary_conversion_path") or audience.get("primary_goal"), 180)
        goal_sources = _source_urls(audience, valid_sources)
        if goal and goal_sources:
            sections.append(f"CONVERSION PATH:\n- {goal} (source: {', '.join(goal_sources)})")
    elif isinstance(audience, str):
        # A prose-only legacy assessment is retained only as a short, explicitly
        # inferential note; it is never promoted to a verified business fact.
        sections.append(f"AUDIENCE / GOAL (audit summary, verify against cited facts):\n- {_text(audience, 200)}")

    assets = assessment.get("source_assets", [])
    asset_lines = []
    approved_image_urls = []
    valid_asset_sources = set(valid_sources)
    for page_url in verified_asset_source_pages or []:
        if not isinstance(page_url, str) or urlsplit(page_url).scheme not in {"http", "https"}:
            continue
        page_host = (urlsplit(page_url).hostname or "").casefold().removeprefix("www.")
        if page_host == source_host:
            valid_asset_sources.add(page_url)
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            url = str(asset.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            cited_pages = _source_urls(asset, valid_asset_sources)
            if not cited_pages:
                continue
            kind = _text(asset.get("type"), 40) or "image"
            if any(term in kind.casefold() for term in ("icon", "social", "favicon")) and "logo" not in kind.casefold():
                continue
            where = _text(asset.get("where_it_appears") or asset.get("context"), 80)
            cite = cited_pages[0] if cited_pages else ""
            distinct_context = f" ({where})" if where and where not in cited_pages else ""
            asset_lines.append(f"- {kind}: {url}" + (f" (found on: {cite})" if cite else "") + distinct_context)
            if not any(term in kind.casefold() for term in ("logo", "icon", "social")) and url not in approved_image_urls and len(approved_image_urls) < MAX_SOURCE_PHOTOS:
                approved_image_urls.append(url)
            if len(asset_lines) >= MAX_ASSETS:
                break
    if asset_lines:
        sections.append("VERIFIED SOURCE ASSETS (logo and relevant photos only; each URL was observed on a cited source page):\n" + "\n".join(asset_lines))
        source_asset_urls = [line.split(": ", 1)[1].split(" (", 1)[0] for line in asset_lines]
        sections.append("VERIFIED_SOURCE_ASSET_URLS:\n" + "\n".join(f"- {url}" for url in source_asset_urls))
    if approved_image_urls:
        sections.append("VERIFIED_SOURCE_IMAGE_URLS:\n" + "\n".join(f"- {url}" for url in approved_image_urls))
    fallback_lines = []
    for item in category_fallback_images or []:
        url = str(item.get("url", "")).strip()
        context = _text(item.get("context"), 90)
        if url.startswith(("https://", "http://")):
            fallback_lines.append(f"- {url}" + (f" ({context})" if context else ""))
    if fallback_lines:
        sections.append("VERIFIED CATEGORY FALLBACK IMAGE URLS (direct image URLs passed image-byte validation):\n" + "\n".join(fallback_lines[:3]))
        sections.append("VERIFIED_CATEGORY_FALLBACK_IMAGE_URLS:\n" + "\n".join(line[2:].split(" (", 1)[0] for line in fallback_lines[:3]))

    result = "\n\n".join(sections)
    if len(result) > MAX_BRIEF_CHARS:
        raise ValueError(
            f"Source-grounded brief is {len(result)} characters; limit is {MAX_BRIEF_CHARS}. "
            "Shorten cited descriptions while preserving every contact-form field and its required status."
        )
    return result


def format_retry_guidance(checker: dict, browser: dict, approved_images: list[str], category_fallback_images: list[str] | None = None) -> str:
    """Translate measured failures into concise, specific next-candidate directions."""
    failed = [name for name, value in checker.get("checks", {}).items() if value is False]
    lines = []
    if failed:
        lines.append("Measured failures from the previous candidate: " + ", ".join(failed[:8]) + ".")
    if checker.get("checks", {}).get("public_file_uploads_omitted") is False:
        lines.append("Remove every public file-upload control. The demo must omit uploads even when the source has them.")
    missing_fields = checker.get("source_contact_form_fields_missing", [])
    if missing_fields:
        lines.append("The verified inquiry form is missing these exact source fields: " + "; ".join(str(item) for item in missing_fields[:8]) + ". Add them with their cited labels and required states.")
    required_mismatches = checker.get("source_contact_form_required_state_mismatches", [])
    if required_mismatches:
        lines.append("Correct the required status for these verified inquiry fields: " + "; ".join(str(item) for item in required_mismatches[:8]) + ".")
    type_mismatches = checker.get("source_contact_form_type_mismatches", [])
    if type_mismatches:
        lines.append("Correct the control type for these verified inquiry fields: " + "; ".join(str(item) for item in type_mismatches[:8]) + ".")
    image_checks = {
        "hero_has_image", "hero_images_load_ok", "all_images_load_ok", "image_coverage",
        "image_alt_text_present", "source_site_hero_photo_used", "source_site_photos_used",
        "source_site_photos_load_ok", "images_use_source_or_category_assets",
        "hero_uses_source_or_category_asset",
    }
    if any(name in image_checks and value is False for name, value in checker.get("checks", {}).items()):
        all_allowed = list(dict.fromkeys([*approved_images, *(category_fallback_images or [])]))
        failed_urls = list(checker.get("failed_image_urls", []))
        for viewport, data in browser.get("viewports", {}).items():
            images = data.get("images", {}) if isinstance(data, dict) else {}
            for issue in images.get("failures", []) if isinstance(images, dict) else []:
                url = issue.get("src") or issue.get("url") if isinstance(issue, dict) else ""
                if isinstance(url, str) and url and url not in failed_urls:
                    failed_urls.append(url)
        observed = list(checker.get("image_urls", []))
        for url in checker.get("hero_image_urls", []):
            if isinstance(url, str) and url and url not in observed:
                observed.append(url)
        unapproved_urls = [url for url in observed if isinstance(url, str) and url and url not in all_allowed]
        if failed_urls:
            lines.append("These exact image URLs failed to load: " + "; ".join(failed_urls[:3]) + ". Replace each with an approved URL below and recheck it in the browser.")
        if unapproved_urls:
            lines.append("These image URLs are outside the approved source/category set: " + "; ".join(unapproved_urls[:3]) + ". Replace them; do not alter or invent an asset URL.")
        if all_allowed:
            lines.append("Use only these exact approved source or category image URLs, and place a verified source photo in the hero when one is available: " + "; ".join(all_allowed[:6]))
        else:
            lines.append("No source image URLs were verified; use stable, directly loadable category-relevant image files and do not invent source asset URLs.")
    cta_issues = []
    for viewport, data in browser.get("viewports", {}).items():
        contrast = data.get("primary_cta_contrast", {}) if isinstance(data, dict) else {}
        for issue in contrast.get("issues", []) if isinstance(contrast, dict) else []:
            if isinstance(issue, dict):
                ratio = issue.get("contrast_ratio")
                measured = f"{ratio}:1" if isinstance(ratio, (int, float)) else "unmeasurable"
                cta_issues.append(
                    f"{viewport} {issue.get('selector', 'CTA')}: {measured} "
                    f"(required {issue.get('threshold', 4.5)}:1)"
                )
    if cta_issues:
        lines.append("Primary CTA contrast failed the measured threshold: " + "; ".join(cta_issues[:4]) + ". Set a solid foreground/background pair that reaches at least 4.5:1, then recheck desktop and mobile.")
    browser_checks = browser.get("checks", {}) if isinstance(browser.get("checks"), dict) else {}
    if browser_checks.get("rendered_sections_visible_desktop_and_mobile") is False:
        hidden = []
        for viewport, data in browser.get("viewports", {}).items():
            sections = data.get("sections", {}) if isinstance(data, dict) else {}
            for name, result in sections.items() if isinstance(sections, dict) else []:
                if isinstance(result, dict) and result.get("visible") is False:
                    hidden.append(f"{viewport} {name} ({result.get('selector_hint') or 'unmatched'})")
        lines.append("Required section visibility failed" + (": " + "; ".join(hidden[:4]) if hidden else "") + ". Keep each required section in the page and make it visibly render at both tested viewport sizes; remove hiding styles only from the measured section or hidden ancestor.")
    if browser_checks.get("cta_visible_first_screen_desktop_and_mobile") is False:
        missed = [name for name, data in browser.get("viewports", {}).items()
                  if isinstance(data, dict) and data.get("cta_visible_first_screen") is False]
        lines.append("The primary contact/action CTA was not fully visible in the first screen at " + ", ".join(missed or ["one or more viewports"]) + ". Place the primary CTA inside the hero and shorten/reflow the hero content so the entire CTA fits within the initial viewport on desktop and mobile.")
    failed_checks = checker.get("checks", {}) if isinstance(checker.get("checks"), dict) else {}
    if failed_checks.get("section_services") is False:
        lines.append("The required services section is missing. Add a visible Services section using only the verified service facts and their supplied source URLs; do not infer or invent offerings.")
    layout = browser.get("template_layout", {})
    if layout and layout.get("status") == "fail":
        expected = json.dumps(layout.get("expected", {}), ensure_ascii=False, separators=(",", ":"))[:550]
        actual = json.dumps(layout.get("actual", {}), ensure_ascii=False, separators=(",", ":"))[:550]
        lines.append(
            "Preserve the selected template structure. Expected: "
            + expected
            + "; actual: "
            + actual
            + ". Correct these structural mismatches without flattening the template rhythm."
        )
    return "\n".join(lines)[:2500]
