"""Compact, source-backed HTML5 UP scaffolds and layout signatures."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SCAFFOLD_ROOT = SCRIPT_DIR.parent / "templates" / "html5up"

TEMPLATES: dict[str, dict[str, Any]] = {
    "forty": {
        "name": "Forty",
        "template_url": "https://html5up.net/forty",
        "demo_url": "https://html5up.net/uploads/demos/forty/",
        "license_url": "https://html5up.net/license",
        "source_markers": (
            'id="banner" class="major"',
            'id="one" class="tiles"',
            "<article",
            'id="contact"',
            'id="footer"',
        ),
        "html_outline": (
            '<header id="header"> → <section id="banner" class="major"> → '
            '<main id="main"><section id="one" class="tiles"><article>…</article></section> → '
            '<section id="two"> → <section id="contact"> → <footer id="footer">'
        ),
        "css_selectors": (".tiles", ".tiles article", ".tiles article header", ".tiles article .image"),
        "signature_id": "forty-image-tiles",
        "signature_note": (
            "Keep the shared full-screen hero as source id=banner class=major. Below it, preserve Forty’s image-tile grid: "
            "a two-column desktop grid of at least three image-backed article tiles with copy over the images, "
            "then a separate text section and contact band. Use the source classes .tiles and .tiles article."
        ),
        "qa_profile": "forty",
    },
    "landed": {
        "name": "Landed",
        "template_url": "https://html5up.net/landed",
        "demo_url": "https://html5up.net/uploads/demos/landed/",
        "license_url": "https://html5up.net/license",
        "source_markers": (
            'id="one" class="spotlight style1 bottom"',
            'id="two" class="spotlight style2 right"',
            'id="three" class="spotlight style3 left"',
            'id="four" class="wrapper style1 special fade-up"',
        ),
        "html_outline": (
            '<section id="banner"> → <section id="one" class="spotlight style1 bottom"> → '
            '<section id="two" class="spotlight style2 right"> → '
            '<section id="three" class="spotlight style3 left"> → '
            '<section id="four" class="wrapper style1 special fade-up"> → '
            '<section id="five" class="wrapper style2 special fade"> → footer'
        ),
        "css_selectors": (".spotlight", ".spotlight .content", ".spotlight .image", ".wrapper"),
        "signature_id": "landed-alternating-spotlights",
        "signature_note": (
            "Keep the shared full-screen hero as source id=banner. Below it, use at least three wide split feature bands "
            "with substantial image and copy columns, alternating image sides left/right/left (or the reverse), "
            "followed by a compact feature grid and a distinct contact band. Preserve the source classes "
            ".spotlight, .style1/.style2/.style3, .left/.right, and .wrapper."
        ),
        "qa_profile": "landed",
    },
    "story": {
        "name": "Story",
        "template_url": "https://html5up.net/story",
        "demo_url": "https://html5up.net/uploads/demos/story/",
        "license_url": "https://html5up.net/license",
        "source_markers": (
            'id="wrapper" class="divided"',
            'class="banner style1 orient-left content-align-left image-position-right fullscreen',
            'class="spotlight style1 orient-right',
            'class="gallery style2 medium',
            'class="items style1 medium',
        ),
        "html_outline": (
            '<div id="wrapper" class="divided"> → '
            '<section class="banner style1 orient-left … fullscreen"> → '
            '<section class="spotlight style1 orient-right …"> → '
            '<section class="spotlight style1 orient-left …"> → '
            '<section class="wrapper align-center"><div class="gallery style2 medium">…</div> → '
            '<div class="items style1 medium">…</div> → contact'
        ),
        "css_selectors": (".banner.style1", ".spotlight.style1", ".gallery.style2", ".items.style1"),
        "signature_id": "story-divided-panels-gallery",
        "signature_note": (
            "Keep the shared full-screen hero as .banner.fullscreen. Below it, preserve "
            "the divided, editorial rhythm: at least two broad alternating image/text spotlight panels, then a "
            "separate image gallery or compact items band and contact. Preserve .banner, .spotlight, "
            ".orient-left/.orient-right, .gallery or .items, and .divided."
        ),
        "qa_profile": "story",
    },
}


def template_slug(reference: dict[str, Any] | None) -> str | None:
    if not isinstance(reference, dict):
        return None
    url = reference.get("template_url")
    if not isinstance(url, str):
        return None
    slug = urlsplit(url.strip()).path.strip("/").split("/")[-1].lower()
    return slug if slug in TEMPLATES else None


def supported_references() -> list[dict[str, Any]]:
    """Return the three templates with maintained source scaffolds, in stable order."""
    return [
        {
            "slot": slot,
            "name": config["name"],
            "template_url": config["template_url"],
            "demo_url": config["demo_url"],
            "license_url": config["license_url"],
            "fit_summary": config["signature_note"],
            "patterns_to_adapt": {
                "forty": ["Image-backed overlay tile grid", "Separate full-width story and contact bands"],
                "landed": ["Alternating image/copy spotlight sections", "Compact feature grid then contact band"],
                "story": ["Alternating divided spotlight panels", "Separate image gallery or items band"],
            }[slug],
            "demo_observations": {
                "forty": ["Tiles are image-backed articles in a grid."],
                "landed": ["Spotlight sections alternate image and copy."],
                "story": ["Divided spotlight panels alternate with gallery/items modules."],
            }[slug],
            "criteria_fit": {"full_bleed_hero": True, "responsive_layout": True},
        }
        for slot, (slug, config) in enumerate(TEMPLATES.items(), start=1)
    ]


def selection_is_supported(references: Any) -> bool:
    if not isinstance(references, list) or len(references) != len(TEMPLATES):
        return False
    return {template_slug(reference) for reference in references} == set(TEMPLATES)


def _css_rule(css: str, wanted: str) -> str | None:
    """Extract one short top-level CSS rule from the official template source."""
    cleaned = re.sub(r"/\*[\s\S]*?\*/", "", css)
    index = 0
    while index < len(cleaned):
        open_brace = cleaned.find("{", index)
        if open_brace < 0:
            break
        selector = cleaned[index:open_brace].strip()
        depth = 1
        cursor = open_brace + 1
        while cursor < len(cleaned) and depth:
            if cleaned[cursor] == "{":
                depth += 1
            elif cleaned[cursor] == "}":
                depth -= 1
            cursor += 1
        if depth:
            break
        if not selector.startswith("@"):
            selectors = {part.strip() for part in selector.split(",")}
            if wanted in selectors:
                body = re.sub(r"\s+", " ", cleaned[open_brace + 1:cursor - 1]).strip()
                if len(body) > 190:
                    body = body[:187].rstrip() + "…"
                return f"{selector} {{ {body} }}"
        index = cursor
    return None


def _source_markup_excerpt(html: str, markers: tuple[str, ...]) -> list[str]:
    """Select exact component opening tags from the official template markup."""
    tags = re.findall(r"<(?:(?:header|main|section|footer|div|nav|article)\b)[^>]*>", html, re.IGNORECASE | re.DOTALL)
    output: list[str] = []
    for marker in markers:
        found = next((tag for tag in tags if marker.lower() in " ".join(tag.split()).lower()), None)
        if found:
            normalized = " ".join(found.split())
            if normalized not in output:
                output.append(normalized)
    return output


def scaffold_context(reference: dict[str, Any] | None) -> str:
    """Render a compact real-source scaffold excerpt for the selected template."""
    slug = template_slug(reference)
    if not slug:
        return ""
    config = TEMPLATES[slug]
    source_dir = SCAFFOLD_ROOT / slug
    html_path = source_dir / "index.html"
    css_path = source_dir / "assets" / "css" / "main.css"
    license_path = source_dir / "LICENSE.txt"
    if not all(path.is_file() for path in (html_path, css_path, license_path)):
        raise RuntimeError(f"Bundled HTML5 UP {config['name']} scaffold is incomplete.")
    html = html_path.read_text(encoding="utf-8", errors="replace")
    css = css_path.read_text(encoding="utf-8", errors="replace")
    if not all(marker in html for marker in config["source_markers"]):
        raise RuntimeError(f"Bundled HTML5 UP {config['name']} HTML no longer matches its scaffold manifest.")
    if "Creative Commons Attribution 3.0" not in license_path.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"Bundled HTML5 UP {config['name']} license file is missing or changed.")
    rules = [rule for selector in config["css_selectors"] if (rule := _css_rule(css, selector))]
    if len(rules) < 2:
        raise RuntimeError(f"Bundled HTML5 UP {config['name']} source CSS is missing its scaffold selectors.")
    markup = _source_markup_excerpt(html, config["source_markers"])
    if len(markup) != len(config["source_markers"]):
        raise RuntimeError(f"Bundled HTML5 UP {config['name']} source HTML excerpt is incomplete.")
    return (
        f"REAL HTML5 UP SOURCE SCAFFOLD — {config['name']} ({config['template_url']})\n"
        f"Original source is bundled at `chatgpt_automation/templates/html5up/{slug}` under CCA 3.0; "
        "adapt its structure and CSS layout patterns, replace demo text/images/branding, and keep the pipeline's "
        "HTML and CSS attribution comments.\n"
        f"HTML sequence from official source: {config['html_outline']}\n"
        "Exact component tags from the source scaffold (adapt their children and business content):\n"
        + "\n".join(markup)
        + "\n"
        "Source CSS excerpts (retain the component geometry, then restyle for this business):\n"
        + "\n".join(rules)
        + "\n"
        f"LAYOUT SIGNATURE: {config['signature_note']}\n\n"
    )


def qa_profile(reference: dict[str, Any] | None) -> dict[str, str] | None:
    slug = template_slug(reference)
    if not slug:
        return None
    config = TEMPLATES[slug]
    return {"slug": slug, "signature_id": config["signature_id"], "profile": config["qa_profile"]}
