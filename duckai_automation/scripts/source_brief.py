"""Build a compact, source-traceable generation brief from Duck.ai's audit."""

from __future__ import annotations

import json
from urllib.parse import urlsplit


MAX_BRIEF_CHARS = 4200
MAX_FACTS = 14
MAX_ASSETS = 5

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
        for key in ("source_urls", "sources", "source_url", "page_url", "found_on", "url"):
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


def build_compact_source_brief(assessment: dict, category_fallback_images: list[dict] | None = None) -> str:
    """Keep only source-backed facts and URLs from pages the audit says it reviewed."""
    if not isinstance(assessment, dict):
        return ""
    valid_sources = {
        str(item.get("url", ""))
        for item in assessment.get("pages_reviewed", [])
        if isinstance(item, dict) and urlsplit(str(item.get("url", ""))).scheme in {"http", "https"}
    }
    valid_sources.update(
        value for value in assessment.get("sources", [])
        if isinstance(value, str) and urlsplit(value).scheme in {"http", "https"}
    )
    sections = []
    core_facts = _render_items("IDENTITY / SERVICES / LOCATIONS", assessment.get("organization_facts"), valid_sources, 6)
    if not core_facts:
        return ""
    sections.extend(core_facts)
    for title, key, limit in (
        ("SELLING POINTS", "selling_points", 3),
        ("CONTACT DETAILS", "contact_details", 5),
        ("CONTACT FORM (preserve exact labels and required status)", "contact_form_fields", 12),
        ("FAQ ANSWERS", "faq_answers", 3),
        ("IMPORTANT SOURCE SECTIONS", "content_structure", 4),
    ):
        sections.extend(_render_items(title, assessment.get(key), valid_sources, limit))

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
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            url = str(asset.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            cited_pages = _source_urls(asset, valid_sources)
            if not cited_pages and not any(urlsplit(url).hostname == urlsplit(source).hostname for source in valid_sources):
                continue
            kind = _text(asset.get("type"), 40) or "image"
            where = _text(asset.get("where_it_appears") or asset.get("context"), 80)
            cite = cited_pages[0] if cited_pages else ""
            asset_lines.append(f"- {kind}: {url}" + (f" (found on: {cite})" if cite else "") + (f" ({where})" if where else ""))
            if not any(term in kind.casefold() for term in ("logo", "icon", "social")) and url not in approved_image_urls:
                approved_image_urls.append(url)
            if len(asset_lines) >= MAX_ASSETS:
                break
    if asset_lines:
        sections.append("VERIFIED SOURCE IMAGE URLS (only these are approved source assets):\n" + "\n".join(asset_lines))
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
    image_checks = {"source_site_hero_photo_used", "source_site_photos_used", "source_site_photos_load_ok",
                    "images_use_source_or_category_assets", "hero_uses_source_or_category_asset"}
    if any(name in image_checks and value is False for name, value in checker.get("checks", {}).items()):
        all_allowed = list(dict.fromkeys([*approved_images, *(category_fallback_images or [])]))
        if all_allowed:
            lines.append("Use only these approved source or category image URLs, and use a verified source photo in the hero when one is available: " + "; ".join(all_allowed[:6]))
        else:
            lines.append("No source image URLs were verified; use stable, directly loadable category-relevant image files and do not invent source asset URLs.")
    cta_issues = []
    for viewport, data in browser.get("viewports", {}).items():
        contrast = data.get("primary_cta_contrast", {}) if isinstance(data, dict) else {}
        for issue in contrast.get("issues", []) if isinstance(contrast, dict) else []:
            if isinstance(issue, dict):
                cta_issues.append(f"{viewport} {issue.get('selector', 'CTA')}: {issue.get('contrast_ratio', 'unmeasurable')} (required {issue.get('threshold', 4.5)}:1)")
    if cta_issues:
        lines.append("Primary CTA contrast failed the 4.5:1 text threshold: " + "; ".join(cta_issues[:4]) + ". Use a solid, high-contrast CTA treatment.")
    layout = browser.get("template_layout", {})
    if layout and layout.get("status") == "fail":
        lines.append(
            "Preserve the selected template structure. Expected: "
            + json.dumps(layout.get("expected", {}), ensure_ascii=False, separators=(",", ":"))
            + "; actual: "
            + json.dumps(layout.get("actual", {}), ensure_ascii=False, separators=(",", ":"))
            + ". Correct these structural mismatches without flattening the template rhythm."
        )
    return "\n".join(lines)[:1800]
