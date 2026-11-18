#!/usr/bin/env python3
"""Render the inlined page and automate objective desktop/mobile checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from site_quality import SECTION_ALIASES, _required_sections  # noqa: E402
from template_scaffolds import qa_profile  # noqa: E402


TEMPLATE_LAYOUT_JS = r"""profile => {
  const main = document.querySelector('main') || document.body;
  const h1 = document.querySelector('h1');
  const hero = h1 && (h1.closest('section') || h1.closest('[class*="hero" i]') || h1.closest('main'));
  const sections = Array.from(main.querySelectorAll(':scope > section, :scope > div > section'))
    .filter(section => section !== hero && !(hero && hero.contains(section)));
  const mediaSide = section => {
    const media = section.querySelector('.image, picture, img, video, [style*="background-image"]');
    if (!media) return null;
    const sr = section.getBoundingClientRect(), mr = media.getBoundingClientRect();
    if (!sr.width || mr.width < sr.width * 0.18) return null;
    return mr.left + mr.width / 2 < sr.left + sr.width / 2 ? 'left' : 'right';
  };
  const spotlights = sections.filter(section => section.matches('.spotlight'));
  const sides = spotlights.map(mediaSide);
  const alternations = sides.slice(1).reduce((n, side, i) => n + (side && sides[i] && side !== sides[i] ? 1 : 0), 0);
  let evidence = {}, pass = false;
  if (profile.profile === 'forty') {
    const tiles = main.querySelector('.tiles');
    const articles = tiles ? Array.from(tiles.querySelectorAll(':scope > article')) : [];
    const display = tiles ? getComputedStyle(tiles).display : 'missing';
    const columns = display === 'grid' ? getComputedStyle(tiles).gridTemplateColumns.split(/\s+/).length :
      new Set(articles.map(item => Math.round(item.getBoundingClientRect().left / 16))).size;
    const mediaCount = articles.filter(item => item.querySelector('img,picture,video,.image,[style*="background-image"]')).length;
    evidence = {tile_count: articles.length, media_tile_count: mediaCount, tile_display: display, desktop_columns: columns};
    pass = !!(hero && hero.id === 'banner' && hero.classList.contains('major') && articles.length >= 3 && mediaCount >= 3 && columns >= 2);
  } else if (profile.profile === 'landed') {
    const styles = ['style1','style2','style3'].every(name => spotlights.some(section => section.classList.contains(name)));
    evidence = {spotlight_count: spotlights.length, has_three_styles: styles, spotlight_media_sides: sides,
      spotlight_side_alternations: alternations, media_sides: sides, side_alternations: alternations};
    pass = !!(hero && hero.id === 'banner' && spotlights.length >= 3 && styles && alternations >= 2);
  } else if (profile.profile === 'story') {
    const gallery = !!main.querySelector('.gallery,.items');
    const orientations = !!(main.querySelector('.orient-left') && main.querySelector('.orient-right'));
    evidence = {divided_page: !!document.querySelector('.divided,#wrapper.divided'), gallery_or_items: gallery,
      both_orientations: orientations, spotlight_count: spotlights.length, spotlight_media_sides: sides,
      spotlight_side_alternations: alternations, media_sides: sides, side_alternations: alternations};
    pass = !!(hero && hero.classList.contains('banner') && hero.classList.contains('fullscreen') &&
      evidence.divided_page && gallery && orientations && spotlights.length >= 2 && alternations >= 1);
  }
  const expected = profile.profile === 'forty' ? {hero: '#banner.major', tiles: '>=3 image-backed articles in a 2+ column grid'} :
    profile.profile === 'landed' ? {hero: '#banner', spotlights: '>=3 sections with style1/style2/style3 and >=2 media-side alternations'} :
    {hero: '.banner.fullscreen', spotlights: '>=2 alternating orient-left/orient-right panels', gallery: '.gallery or .items'};
  return {status: pass ? 'pass' : 'fail', pass, profile: profile.profile, slug: profile.slug,
    signature_id: profile.signature_id, expected, actual: evidence, ...evidence};
}""";


def _selected_template_profile(run_dir: Path):
    try:
        audit = json.loads((run_dir / "debug" / "design_reference.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {"status": "fail", "pass": False, "reason": "selected HTML5 UP template audit is missing"}
    profile = qa_profile(audit.get("design_reference") if isinstance(audit, dict) else None)
    if not profile or audit.get("status") != "selected":
        return None, {"status": "fail", "pass": False, "reason": "selected HTML5 UP template is unsupported"}
    return profile, {"status": "pending", "pass": False, "slug": profile["slug"], "signature_id": profile["signature_id"]}


SECTION_VISIBILITY_JS = r"""(required) => {
  const normalize = value => (value || '').toString().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  const selectorHint = element => {
    if (!element) return null;
    if (element.id && document.querySelectorAll(`#${CSS.escape(element.id)}`).length === 1) return `#${CSS.escape(element.id)}`;
    const classes = Array.from(element.classList || []).filter(value => /^[a-zA-Z_-][\w-]*$/.test(value)).slice(0, 2);
    return `${element.tagName.toLowerCase()}${classes.map(value => `.${CSS.escape(value)}`).join('')}`;
  };
  const visible = element => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) <= 0.01) return false;
    }
    return true;
  };
  const candidates = Array.from(document.querySelectorAll('main,section,footer,header,article,aside,form,[role="region"],[id],[class]'));
  const results = {};
  for (const [name, aliases] of Object.entries(required)) {
    let matches = [];
    if (name === 'hero') {
      const h1 = document.querySelector('h1');
      const target = h1 && (h1.closest('section') || h1.closest('main') || h1.parentElement);
      if (target) matches = [target];
    } else if (name === 'footer') {
      matches = Array.from(document.querySelectorAll('footer'));
    }
    if (!matches.length) {
      matches = candidates.filter(element => {
        const headings = Array.from(element.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(node => node.innerText || node.textContent || '').join(' ');
        const evidence = normalize([element.id, element.className, headings].join(' '));
        return aliases.some(alias => evidence.includes(normalize(alias)));
      });
    }
    const usable = matches.filter(visible).sort((a, b) => {
      const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
      return (ar.width * ar.height) - (br.width * br.height);
    });
    const element = usable[0] || matches[0];
    const rect = element ? element.getBoundingClientRect() : null;
    const hiddenAncestors = [];
    let ariaHiddenAncestor = false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.getAttribute('aria-hidden') === 'true') ariaHiddenAncestor = true;
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) <= 0.01) {
        const selector = selectorHint(node);
        if (selector) hiddenAncestors.push(selector);
      }
    }
    results[name] = {
      visible: usable.length > 0,
      style_hidden: hiddenAncestors.length > 0,
      aria_hidden_ancestor: ariaHiddenAncestor,
      selector_hint: selectorHint(element),
      hidden_ancestors: hiddenAncestors,
      width: rect ? Math.round(rect.width) : 0,
      height: rect ? Math.round(rect.height) : 0
    };
  }
  return results;
}"""


VIEWPORT_CHECKS_JS = r"""() => {
  const visible = element => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) <= 0.01) return false;
    }
    return true;
  };
  const h1 = document.querySelector('h1');
  const hero = h1 && (h1.closest('section') || h1.closest('[class*="hero" i]') || h1.closest('main'));
  let heroData = {present: false, spans_viewport: false, media_covers_hero: false};
  if (hero) {
    const hr = hero.getBoundingClientRect();
    const nodes = [hero, ...hero.querySelectorAll('*')];
    const media = nodes.filter(node => {
      const style = getComputedStyle(node);
      const pseudoHasImage = ['::before', '::after'].some(pseudo => getComputedStyle(node, pseudo).backgroundImage !== 'none');
      return (node.tagName.toLowerCase() === 'img' || style.backgroundImage !== 'none' || pseudoHasImage) && visible(node);
    }).map(node => ({
      rect: node.getBoundingClientRect(),
      image: node.tagName.toLowerCase() === 'img' ? node.naturalWidth > 0 : true
    })).filter(item => item.image);
    const covers = media.some(item => item.rect.left <= hr.left + 2 && item.rect.right >= hr.right - 2 && item.rect.top <= hr.top + 2 && item.rect.bottom >= hr.bottom - 2);
    heroData = {
      present: true,
      left: Math.round(hr.left),
      right: Math.round(hr.right),
      width: Math.round(hr.width),
      height: Math.round(hr.height),
      viewport_width: window.innerWidth,
      spans_viewport: hr.left <= 2 && hr.right >= window.innerWidth - 2,
      media_covers_hero: covers
    };
  }

  const ctaWords = /ask|contact|book|schedule|inquir|reserve|visit|get in touch|explore|discover|learn|view|see|browse|compare/i;
  const actions = Array.from(document.querySelectorAll('a,button,[role="button"],input[type="submit"]'));
  const cta = actions.find(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const className = String(element.className || '');
    const ctaClass = /(?:^|[\s_-])(?:button|btn|cta|primary|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(className);
    const menuControl = element.hasAttribute('aria-controls') || /menu[-_]?toggle|hamburger/i.test(className);
    const contentAction = !element.closest('header,nav,footer') && Boolean(element.closest('main,[role="main"],section,article'));
    if ((!ctaClass && !ctaWords.test(label)) || menuControl || !contentAction || !visible(element)) return false;
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= window.innerHeight && rect.left >= 0 && rect.right <= window.innerWidth;
  });
  const ctaRect = cta ? cta.getBoundingClientRect() : null;
  const rgb = value => {
    const parts = String(value || '').match(/[\d.]+/g);
    if (!parts || parts.length < 3) return null;
    return parts.slice(0, 3).map(Number);
  };
  const luminance = color => color ? color.map(channel => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0) : null;
  const stableSelector = element => {
    if (element.id && document.querySelectorAll(`#${CSS.escape(element.id)}`).length === 1) return `#${CSS.escape(element.id)}`;
    const classes = Array.from(element.classList || []).filter(value => /^[a-zA-Z_-][\w-]*$/.test(value)).slice(0, 2);
    const direct = `${element.tagName.toLowerCase()}${classes.map(value => `.${CSS.escape(value)}`).join('')}`;
    if (document.querySelectorAll(direct).length === 1) return direct;
    const parts = [];
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
        return `#${CSS.escape(node.id)} > ${parts.reverse().join(' > ') || direct}`;
      }
      const tag = node.tagName.toLowerCase();
      const siblings = node.parentElement ? Array.from(node.parentElement.children).filter(item => item.tagName === node.tagName) : [];
      parts.push(`${tag}:nth-of-type(${siblings.indexOf(node) + 1})`);
    }
    return parts.reverse().join(' > ') || direct;
  };
  const effectiveBackground = element => {
    let background = [255, 255, 255];
    const ancestors = [];
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) ancestors.push(node);
    let unknownImageLayer = false;
    for (const node of ancestors.reverse()) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== 'none') unknownImageLayer = true;
      const match = style.backgroundColor.match(/[\d.]+/g);
      if (!match || match.length < 3) continue;
      const alpha = match.length > 3 ? Number(match[3]) : 1;
      const color = match.slice(0, 3).map(Number);
      if (alpha >= 0.98) {
        background = color;
        unknownImageLayer = style.backgroundImage !== 'none';
      } else if (alpha > 0) {
        background = color.map((channel, index) => channel * alpha + background[index] * (1 - alpha));
      }
    }
    return unknownImageLayer ? null : background;
  };
  const ctaCandidates = actions.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const className = String(element.className || '');
    const ctaClass = /(?:^|[\s_-])(?:button|btn|cta|primary|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(className);
    const submitControl = element.matches('input[type="submit"],input[type="button"]');
    const labeledButton = (element.tagName.toLowerCase() === 'button' || element.getAttribute('role') === 'button')
      && !element.hasAttribute('aria-controls')
      && ctaWords.test(label);
    const contentLink = element.tagName.toLowerCase() === 'a'
      && !element.closest('nav,header,footer')
      && Boolean(element.closest('main'))
      && ctaWords.test(label);
    return visible(element) && (ctaClass || submitControl || labeledButton || contentLink);
  });
  const contrastIssues = ctaCandidates.flatMap(element => {
    const fg = luminance(rgb(getComputedStyle(element).color));
    const background = effectiveBackground(element);
    const bg = luminance(background);
    const ratio = fg === null || bg === null ? null : (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    if (ratio !== null && ratio >= 4.5) return [];
    return [{selector: stableSelector(element), text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 80),
      contrast_ratio: ratio === null ? null : Math.round(ratio * 100) / 100, threshold: 4.5,
      reason: ratio === null ? 'contrast could not be measured' : 'contrast ratio below 4.5:1'}];
  });
  const images = Array.from(document.images);
  images.forEach(image => { image.loading = 'eager'; });
  const imageResults = images.map(image => ({
    src: image.currentSrc || image.src || '',
    loaded: image.complete && image.naturalWidth > 0,
    natural_width: image.naturalWidth
  }));
  const root = document.documentElement;
  const body = document.body;
  const documentWidth = Math.max(root.scrollWidth, body ? body.scrollWidth : 0);
  return {
    hero: heroData,
    cta: {visible_first_screen: Boolean(cta), text: cta ? (cta.innerText || cta.getAttribute('aria-label') || '') : '', bottom: ctaRect ? Math.round(ctaRect.bottom) : null},
    primary_cta_contrast: {count: ctaCandidates.length, pass: ctaCandidates.length > 0 && contrastIssues.length === 0, issues: ctaCandidates.length ? contrastIssues : [{selector: '', reason: 'no visible primary CTA found', contrast_ratio: null, threshold: 4.5}]},
    horizontal_overflow: {scroll_width: documentWidth, viewport_width: root.clientWidth, overflow: documentWidth > root.clientWidth + 1},
    images: {count: images.length, loaded_count: imageResults.filter(item => item.loaded).length, failures: imageResults.filter(item => !item.loaded)},
    fonts: {status: document.fonts.status, loaded_face_count: Array.from(document.fonts).filter(face => face.status === 'loaded').length, failed_face_count: Array.from(document.fonts).filter(face => face.status === 'error').length}
  };
}"""


TEMPLATE_LAYOUT_JS = r"""profile => {
  const main = document.querySelector('main');
  const h1 = document.querySelector('h1');
  const hero = h1 && (h1.closest('section') || h1.closest('[class*="hero" i]') || h1.closest('main'));
  const below = main ? Array.from(main.querySelectorAll(':scope > section, :scope > div > section')).filter(section => section !== hero && !section.contains(hero)) : [];
  const spots = below.filter(section => section.classList.contains('spotlight'));
  const mediaSide = section => {
    const node = section.querySelector('.image,picture,img,video,[style*="background-image"]');
    if (!node) return null;
    const a = section.getBoundingClientRect(), b = node.getBoundingClientRect();
    if (!a.width || b.width < a.width * 0.18) return null;
    return b.left + b.width / 2 < a.left + a.width / 2 ? 'left' : 'right';
  };
  const sides = spots.map(mediaSide);
  const alternations = sides.slice(1).reduce((n, side, i) => n + (side && sides[i] && side !== sides[i] ? 1 : 0), 0);
  const actual = {hero_banner: Boolean(hero && hero.classList.contains('banner')), below_hero_sections: below.length,
    spotlight_count: spots.length, spotlight_media_sides: sides, spotlight_side_alternations: alternations,
    tiles: Boolean(main && main.querySelector('.tiles')), gallery_or_items: Boolean(main && main.querySelector('.gallery,.items')),
    oriented_left: Boolean(main && main.querySelector('.orient-left')), oriented_right: Boolean(main && main.querySelector('.orient-right'))};
  let pass = true, expected = {};
  if (profile === 'forty') {
    const tiles = main && main.querySelector('.tiles');
    const articles = tiles ? Array.from(tiles.querySelectorAll(':scope > article')) : [];
    const positions = [...new Set(articles.map(article => Math.round(article.getBoundingClientRect().left / 16)))];
    const layout = tiles ? getComputedStyle(tiles).display : 'missing';
    const columns = layout === 'grid' ? getComputedStyle(tiles).gridTemplateColumns.split(/\s+/).filter(Boolean).length : positions.length;
    actual.tile_count = articles.length; actual.tile_columns = columns;
    expected = {hero_banner: true, tile_count_min: 3, tile_columns_min: 2};
    pass = Boolean(hero && hero.id === 'banner' && hero.classList.contains('major') && articles.length >= 3 && columns >= 2);
  } else if (profile === 'landed') {
    const styles = ['style1','style2','style3'].every(name => spots.some(section => section.classList.contains(name)));
    actual.three_source_styles = styles;
    expected = {hero_id: 'banner', spotlight_count_min: 3, source_styles: ['style1','style2','style3'], media_side_alternations_min: 2};
    pass = Boolean(hero && hero.id === 'banner' && spots.length >= 3 && styles && alternations >= 2);
  } else if (profile === 'story') {
    expected = {hero_banner_fullscreen: true, spotlight_count_min: 2, gallery_or_items: true, both_orientations: true, media_side_alternations_min: 1};
    pass = Boolean(hero && hero.classList.contains('banner') && hero.classList.contains('fullscreen') && spots.length >= 2 && actual.gallery_or_items && actual.oriented_left && actual.oriented_right && alternations >= 1);
  }
  return {status: pass ? 'pass' : 'fail', pass, profile, expected, actual};
}""";


def _selected_template_profile(run_dir: Path) -> tuple[str | None, dict]:
    try:
        audit = json.loads((run_dir / "debug" / "design_reference.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        audit = None
    if not isinstance(audit, dict) or audit.get("status") != "selected":
        return None, {"status": "fail", "pass": False, "reason": "selected HTML5 UP template audit is missing"}
    reference = audit.get("design_reference")
    profile = qa_profile(reference)
    if not profile:
        return None, {"status": "fail", "pass": False, "reason": "selected HTML5 UP template is unsupported", "template": reference.get("name") if isinstance(reference, dict) else None}
    return profile["slug"], {"status": "pending", "pass": False, "profile": profile["slug"], "template": reference.get("name"), "signature_id": profile["signature_id"]}


MENU_BUTTON_JS = r"""button => {
  const controls = button.getAttribute('aria-controls');
  const nav = controls && document.getElementById(controls);
  const bars = Array.from(button.querySelectorAll('span')).filter(span => !span.querySelector('span'));
  return Boolean(controls && nav && button.getAttribute('aria-expanded') !== null && bars.length === 3);
}"""


def _resource_event(event, collection: list[dict]) -> None:
    request = event.request if hasattr(event, "request") else event
    if request.resource_type not in {"image", "font"}:
        return
    if hasattr(event, "status"):
        if event.status < 400:
            return
        collection.append({"type": request.resource_type, "status": event.status, "url": request.url})
    else:
        collection.append({"type": request.resource_type, "error": request.failure, "url": request.url})


def _nav_visible(page, nav_id: str) -> bool:
    return bool(page.evaluate(
        """id => {
          const nav = document.getElementById(id);
          if (!nav) return false;
          const style = getComputedStyle(nav), rect = nav.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0.01 && rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth;
        }""",
        nav_id,
    ))


def _exercise_mobile_menu(page) -> dict:
    buttons = page.locator("button").all()
    button = next((item for item in buttons if item.evaluate(MENU_BUTTON_JS)), None)
    if button is None:
        return {"found": False, "click_opens": False, "click_closes": False, "tab_reachable": False, "enter_opens": False, "space_toggles": False, "escape_closes": False}

    nav_id = button.get_attribute("aria-controls")
    result = {"found": True}
    try:
        if button.get_attribute("aria-expanded") == "true":
            button.click()
        button.click()
        page.wait_for_timeout(150)
        result["click_opens"] = button.get_attribute("aria-expanded") == "true" and _nav_visible(page, nav_id)
        button.click()
        page.wait_for_timeout(150)
        result["click_closes"] = button.get_attribute("aria-expanded") == "false" and not _nav_visible(page, nav_id)

        page.evaluate("document.activeElement && document.activeElement.blur()")
        result["tab_reachable"] = False
        for _ in range(20):
            page.keyboard.press("Tab")
            if button.evaluate("element => element === document.activeElement"):
                result["tab_reachable"] = True
                break
        if result["tab_reachable"]:
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
            result["enter_opens"] = button.get_attribute("aria-expanded") == "true" and _nav_visible(page, nav_id)
            page.keyboard.press("Space")
            page.wait_for_timeout(150)
            result["space_toggles"] = button.get_attribute("aria-expanded") == "false" and not _nav_visible(page, nav_id)
            if result["space_toggles"]:
                page.keyboard.press("Enter")
                page.wait_for_timeout(150)
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            result["escape_closes"] = button.get_attribute("aria-expanded") == "false" and not _nav_visible(page, nav_id)
        else:
            result["enter_opens"] = False
            result["space_toggles"] = False
            result["escape_closes"] = False
    except Exception as error:
        result["error"] = str(error)
        result.setdefault("click_opens", False)
        result.setdefault("click_closes", False)
        result.setdefault("tab_reachable", False)
        result.setdefault("enter_opens", False)
        result.setdefault("space_toggles", False)
        result.setdefault("escape_closes", False)
    result["pass"] = all(result.get(key, False) for key in ("click_opens", "click_closes", "tab_reachable", "enter_opens", "space_toggles"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    parser.add_argument("request", help="Original website request used to determine required sections")
    args = parser.parse_args()

    run_dir = args.run_folder.resolve()
    html_file = run_dir / "files" / "inlined" / "index.html"
    debug_dir = run_dir / "debug"
    screenshots_dir = debug_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    template_profile, template_layout = _selected_template_profile(run_dir)
    requested_sections = _required_sections(args.request)
    section_aliases = {name: list(SECTION_ALIASES.get(name, (name,))) for name in requested_sections}
    viewports = {"desktop": (1440, 900), "mobile": (390, 844)}
    report = {
        "status": "fail",
        "tested_file": str(html_file.relative_to(run_dir).as_posix()),
        "required_sections": requested_sections,
        "viewports": {},
        "mobile_menu": {},
        "template_layout": template_layout,
        "checks": {},
        "resource_errors": [],
    }
    if not html_file.is_file():
        report["error"] = "inlined HTML file is missing"
    else:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
            if executable_path:
                launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_options)
            try:
                for name, (width, height) in viewports.items():
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page_errors: list[dict] = []
                    page.on("requestfailed", lambda request, dest=page_errors: _resource_event(request, dest))
                    page.on("response", lambda response, dest=page_errors: _resource_event(response, dest))
                    try:
                        page.goto(html_file.as_uri(), wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(800)
                        resource_state = page.evaluate(r"""async () => {
                          const timeout = ms => new Promise(resolve => setTimeout(resolve, ms));
                          const images = Array.from(document.images);
                          images.forEach(image => { image.loading = 'eager'; });
                          await Promise.race([
                            Promise.all(images.map(image => image.decode().catch(() => null))),
                            timeout(12000)
                          ]);
                          await Promise.race([document.fonts.ready, timeout(8000)]);
                          return {
                            image_count: images.length,
                            loaded_images: images.filter(image => image.complete && image.naturalWidth > 0).length,
                            failed_images: images.filter(image => image.complete && image.naturalWidth === 0).map(image => image.currentSrc || image.src),
                            font_status: document.fonts.status,
                            loaded_faces: Array.from(document.fonts).filter(face => face.status === 'loaded').length,
                            failed_faces: Array.from(document.fonts).filter(face => face.status === 'error').length
                          };
                        }""")
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(150)
                        page.screenshot(path=str(screenshots_dir / f"{name}.png"), full_page=False)
                        sections = page.evaluate(SECTION_VISIBILITY_JS, section_aliases)
                        visual = page.evaluate(VIEWPORT_CHECKS_JS)
                        if name == "desktop" and template_profile:
                            report["template_layout"] = page.evaluate(TEMPLATE_LAYOUT_JS, template_profile)
                        font_errors = [item for item in page_errors if item["type"] == "font"]
                        image_errors = [item for item in page_errors if item["type"] == "image"]
                        required_present = all(sections.get(section, {}).get("visible", False) for section in requested_sections)
                        report["viewports"][name] = {
                            "width": width,
                            "height": height,
                            "sections": sections,
                            "all_required_sections_visible": required_present,
                            "hero": visual["hero"],
                            "hero_spans_viewport": bool(visual["hero"].get("spans_viewport")),
                            "cta": visual["cta"],
                            "cta_visible_first_screen": visual["cta"]["visible_first_screen"],
                            "primary_cta_contrast": visual["primary_cta_contrast"],
                            "primary_ctas_readable": bool(visual["primary_cta_contrast"]["pass"]),
                            "horizontal_overflow": visual["horizontal_overflow"],
                            "no_horizontal_overflow": not visual["horizontal_overflow"]["overflow"],
                            "images": resource_state,
                            "images_loaded": (
                                resource_state["loaded_images"] == resource_state["image_count"]
                                and not resource_state["failed_images"]
                                and not image_errors
                            ),
                            "fonts": resource_state,
                            "fonts_loaded": (
                                resource_state["font_status"] == "loaded"
                                and resource_state["failed_faces"] == 0
                                and not font_errors
                            ),
                            "resource_errors": page_errors,
                            "screenshot": f"screenshots/{name}.png",
                        }
                        report["resource_errors"].extend(page_errors)
                        if name == "mobile":
                            report["mobile_menu"] = _exercise_mobile_menu(page)
                    except Exception as error:
                        report["viewports"][name] = {
                            "width": width,
                            "height": height,
                            "error": str(error),
                            "all_required_sections_visible": False,
                            "hero_spans_viewport": False,
                            "cta_visible_first_screen": False,
                            "primary_ctas_readable": False,
                            "primary_cta_contrast": {"pass": False, "issues": []},
                            "no_horizontal_overflow": False,
                            "images_loaded": False,
                            "fonts_loaded": False,
                            "screenshot": f"screenshots/{name}.png",
                        }
                    finally:
                        page.close()
            finally:
                browser.close()

        if template_profile and report["template_layout"].get("status") == "pending":
            report["template_layout"] = {
                **report["template_layout"], "status": "fail", "pass": False,
                "reason": "desktop template layout could not be measured",
            }

        desktop = report["viewports"].get("desktop", {})
        mobile = report["viewports"].get("mobile", {})
        mobile_menu = report["mobile_menu"]
        report["checks"] = {
            "rendered_sections_visible_desktop_and_mobile": bool(desktop.get("all_required_sections_visible") and mobile.get("all_required_sections_visible")),
            "hero_spans_viewport_desktop_and_mobile": bool(desktop.get("hero_spans_viewport") and mobile.get("hero_spans_viewport")),
            "cta_visible_first_screen_desktop_and_mobile": bool(desktop.get("cta_visible_first_screen") and mobile.get("cta_visible_first_screen")),
            "primary_ctas_readable_desktop_and_mobile": bool(desktop.get("primary_ctas_readable") and mobile.get("primary_ctas_readable")),
            "template_layout_signature_matches": bool(report["template_layout"].get("pass")),
            "mobile_menu_clicks_work": bool(mobile_menu.get("click_opens") and mobile_menu.get("click_closes")),
            "mobile_menu_keyboard_works": bool(mobile_menu.get("tab_reachable") and mobile_menu.get("enter_opens") and mobile_menu.get("space_toggles")),
            "mobile_has_no_horizontal_overflow": bool(mobile.get("no_horizontal_overflow")),
            "fonts_load_in_browser": bool(desktop.get("fonts_loaded") and mobile.get("fonts_loaded")),
            "images_load_in_browser": bool(desktop.get("images_loaded") and mobile.get("images_loaded")),
        }
        report["status"] = "pass" if all(report["checks"].values()) else "fail"

    output = debug_dir / "browser_qa.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
