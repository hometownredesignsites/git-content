#!/usr/bin/env python3
"""Render the inlined page and automate objective desktop/mobile checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from site_quality import SECTION_ALIASES, _required_sections  # noqa: E402
from template_scaffolds import qa_profile, selection_is_supported  # noqa: E402


SECTION_VISIBILITY_JS = r"""(required) => {
  const normalize = value => (value || '').toString().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
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
    results[name] = {
      visible: usable.length > 0,
      selector_hint: element ? `${element.tagName.toLowerCase()}${element.id ? '#' + element.id : ''}${element.className && typeof element.className === 'string' ? '.' + element.className.trim().split(/\s+/).slice(0, 2).join('.') : ''}` : null,
      width: rect ? Math.round(rect.width) : 0,
      height: rect ? Math.round(rect.height) : 0
    };
  }
  return results;
}"""


VIEWPORT_CHECKS_JS = r"""async () => {
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
  const imageUrls = value => Array.from((value || '').matchAll(/url\((?:["']?)(.*?)(?:["']?)\)/gi))
    .map(match => match[1]).filter(Boolean);
  const loadImage = url => new Promise(resolve => {
    const image = new Image();
    const timer = setTimeout(() => resolve({url, loaded: false}), 10000);
    image.onload = () => { clearTimeout(timer); resolve({url, loaded: image.naturalWidth > 0}); };
    image.onerror = () => { clearTimeout(timer); resolve({url, loaded: false}); };
    image.src = url;
  });
  let heroData = {present: false, spans_viewport: false, media_covers_hero: false, image_loaded: false};
  let visibleMediaResults = [];
  if (hero) {
    const hr = hero.getBoundingClientRect();
    const nodes = [hero, ...hero.querySelectorAll('*')];
    const heroUrls = new Set();
    const heroImageNodes = nodes.filter(node => node.tagName.toLowerCase() === 'img' && visible(node));
    heroImageNodes.forEach(image => { if (image.currentSrc || image.src) heroUrls.add(image.currentSrc || image.src); });
    for (const node of nodes.filter(visible)) {
      const styles = [getComputedStyle(node), getComputedStyle(node, '::before'), getComputedStyle(node, '::after')];
      styles.forEach(style => imageUrls(style.backgroundImage).forEach(url => heroUrls.add(new URL(url, document.baseURI).href)));
    }
    const heroLoads = await Promise.all(Array.from(heroUrls, loadImage));
    const visibleNodes = Array.from(document.querySelectorAll('body *')).filter(visible);
    const visibleUrls = new Set();
    visibleNodes.filter(node => node.tagName.toLowerCase() === 'img').forEach(image => {
      if (image.currentSrc || image.src) visibleUrls.add(image.currentSrc || image.src);
    });
    for (const node of visibleNodes) {
      for (const pseudo of ['', '::before', '::after']) {
        const style = getComputedStyle(node, pseudo || null);
        imageUrls(style.backgroundImage).forEach(url => visibleUrls.add(new URL(url, document.baseURI).href));
      }
    }
    visibleMediaResults = await Promise.all(Array.from(visibleUrls, loadImage));
    const media = nodes.filter(node => {
      const style = getComputedStyle(node);
      const pseudoHasImage = ['::before', '::after'].some(pseudo => getComputedStyle(node, pseudo).backgroundImage !== 'none');
      return (node.tagName.toLowerCase() === 'img' || style.backgroundImage !== 'none' || pseudoHasImage) && visible(node);
    }).map(node => ({
      rect: node.getBoundingClientRect(),
      image: node.tagName.toLowerCase() === 'img' ? node.naturalWidth > 0 : true
    }));
    const covers = media.some(item => item.image && item.rect.left <= hr.left + 2 && item.rect.right >= hr.right - 2 && item.rect.top <= hr.top + 2 && item.rect.bottom >= hr.bottom - 2);
    heroData = {
      present: true,
      left: Math.round(hr.left),
      right: Math.round(hr.right),
      width: Math.round(hr.width),
      height: Math.round(hr.height),
      viewport_width: window.innerWidth,
      spans_viewport: hr.left <= 2 && hr.right >= window.innerWidth - 2,
      media_covers_hero: covers,
      image_loaded: heroLoads.length > 0 && heroLoads.every(item => item.loaded),
      image_assets: heroLoads
    };
  }

  const ctaWords = /ask|call|contact|book|schedule|inquir|reserve|visit|get in touch|quote|estimate|get started|start a project|let.s talk/i;
  const arrowGlyphs = /[←↑→↓↗↘↙↖↩↪⇢⇨⟶⟹➔➜➝➞➟➠➡➢➤⮕⮞❯❱›»]/;
  const actions = Array.from(document.querySelectorAll('a,button,[role="button"],input[type="submit"]'));
  const visibleCtas = actions.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const ctaClass = /(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(String(element.className || ''));
    return (ctaWords.test(label) || ctaClass) && visible(element);
  });
  const ctaArrowIssues = visibleCtas.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('title'), element.getAttribute('value')].filter(Boolean).join(' ');
    if (arrowGlyphs.test(label)) return true;
    if (element.querySelector('svg,[class*="arrow" i],[class*="chevron" i],[data-icon*="arrow" i],[data-lucide*="arrow" i]')) return true;
    const nodes = [element, ...element.querySelectorAll('*')];
    return nodes.some(node => ['', '::before', '::after'].some(pseudo => {
      const style = getComputedStyle(node, pseudo || null);
      if (arrowGlyphs.test(style.content || '') || /url\s*\(/i.test(style.content || '') ||
          /(?:arrow|chevron)[^)]*\.(?:svg|png|webp)/i.test(style.backgroundImage || '') ||
          /url\s*\(/i.test(style.backgroundImage || '') || /url\s*\(/i.test(style.maskImage || '')) return true;
      if (!pseudo || pseudo === '') return false;
      const borders = ['Top', 'Right', 'Bottom', 'Left'].filter(side =>
        parseFloat(style[`border${side}Width`]) > 0 && style[`border${side}Style`] !== 'none'
      );
      return borders.length >= 2 && (style.transform !== 'none' || parseFloat(style.width) === 0 || parseFloat(style.height) === 0);
    }));
  });
  const cta = actions.find(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    if (!ctaWords.test(label) || !visible(element)) return false;
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= window.innerHeight && rect.left >= 0 && rect.right <= window.innerWidth;
  });
  const ctaRect = cta ? cta.getBoundingClientRect() : null;
  const criticalElements = Array.from(document.querySelectorAll('h1, a.button, button.button, a[class*="cta" i], button[class*="cta" i]'))
    .filter(visible);
  const clippingIssues = [];
  for (const element of criticalElements) {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let textNode;
    while ((textNode = walker.nextNode())) {
      if (!textNode.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(textNode);
      for (const line of Array.from(range.getClientRects())) {
        for (let ancestor = element; ancestor && ancestor !== document.documentElement; ancestor = ancestor.parentElement) {
          const style = getComputedStyle(ancestor);
          if (!['hidden', 'clip', 'scroll', 'auto'].includes(style.overflowX)) continue;
          const box = ancestor.getBoundingClientRect();
          if (line.left < Math.max(0, box.left) - 1 || line.right > Math.min(window.innerWidth, box.right) + 1) {
            clippingIssues.push({
              element: `${element.tagName.toLowerCase()}${element.id ? '#' + element.id : ''}`,
              text: (element.innerText || '').trim().slice(0, 100),
              clipped_by: `${ancestor.tagName.toLowerCase()}${ancestor.id ? '#' + ancestor.id : ''}`,
              left: Math.round(line.left), right: Math.round(line.right),
              container_left: Math.round(box.left), container_right: Math.round(box.right)
            });
            break;
          }
          if (ancestor === document.body) break;
        }
      }
    }
  }
  const contactEmailButtons = Array.from(document.querySelectorAll('section[id*="contact" i] a[href^="mailto:"]'))
    .filter(element => /(?:^|\s)(?:button|btn|cta)(?:\s|$)/i.test(String(element.className || '')));
  const ungroupedContactEmailButtons = contactEmailButtons.filter(element =>
    !element.closest('[class*="contact-actions" i], [class~="actions"], [class*="cta-group" i], [class*="button-group" i]')
  );
  const rgb = value => {
    const parts = String(value || '').match(/[\d.]+/g);
    if (!parts || parts.length < 3) return null;
    return [Number(parts[0]), Number(parts[1]), Number(parts[2])].map(channel => {
      const s = channel / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
  };
  const luminance = color => color ? 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] : null;
  const h1Node = document.querySelector('h1');
  const heroNode = h1Node && (h1Node.closest('section') || h1Node.closest('[class*="hero" i]') || h1Node.closest('main'));
  const heroHasImage = Boolean(heroNode && [heroNode, ...heroNode.querySelectorAll('*')].some(node => {
    const styles = [getComputedStyle(node), getComputedStyle(node, '::before'), getComputedStyle(node, '::after')];
    return styles.some(style => style.backgroundImage && style.backgroundImage !== 'none');
  }));
  const heroCtas = heroNode ? Array.from(heroNode.querySelectorAll('a,button,[role="button"]')).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('href')].filter(Boolean).join(' ');
    const isAction = /quote|estimate|contact|call|book|schedule|inquir|email|start a project|let.s talk/i.test(label) ||
      /(?:^|\s)(?:button|btn|cta)(?:\s|$)/i.test(String(element.className || ''));
    return isAction && visible(element);
  }) : [];
  const heroCtaContrastIssues = heroCtas.filter(element => {
    const style = getComputedStyle(element);
    const foreground = luminance(rgb(style.color));
    const backgroundParts = String(style.backgroundColor || '').match(/[\d.]+/g);
    const alpha = backgroundParts && backgroundParts.length > 3 ? Number(backgroundParts[3]) : 1;
    const background = alpha >= 0.85 ? luminance(rgb(style.backgroundColor)) : null;
    if (background !== null && foreground !== null) {
      const ratio = (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
      return ratio < 4.5;
    }
    // A dark label over a photographic hero with no opaque button surface is
    // unreadable over common dark image areas. Require a solid contrast surface.
    return heroHasImage && alpha < 0.85 && foreground !== null && foreground < 0.35;
  }).map(element => ({
    text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 100),
    color: getComputedStyle(element).color,
    background: getComputedStyle(element).backgroundColor
  }));
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
  const assetKey = url => { try { const parsed = new URL(url, document.baseURI); return parsed.host + parsed.pathname; } catch (_) { return url; } };
  const distinctVisibleAssets = new Set(visibleMediaResults.map(item => assetKey(item.url)));
  const loadedVisibleAssets = new Set(visibleMediaResults.filter(item => item.loaded).map(item => assetKey(item.url)));
  return {
    hero: heroData,
    cta: {visible_first_screen: Boolean(cta), text: cta ? (cta.innerText || cta.getAttribute('aria-label') || '') : '', bottom: ctaRect ? Math.round(ctaRect.bottom) : null, arrow_issues: ctaArrowIssues.map(element => (element.innerText || element.getAttribute('aria-label') || '').trim())},
    critical_content_clipping: {pass: clippingIssues.length === 0, issues: clippingIssues},
    contact_email_ctas: {count: contactEmailButtons.length, ungrouped_count: ungroupedContactEmailButtons.length},
    hero_cta_contrast: {pass: heroCtaContrastIssues.length === 0, issues: heroCtaContrastIssues},
    visible_content_images: {distinct_count: distinctVisibleAssets.size, loaded_count: loadedVisibleAssets.size, failures: visibleMediaResults.filter(item => !item.loaded)},
    horizontal_overflow: {scroll_width: documentWidth, viewport_width: root.clientWidth, overflow: documentWidth > root.clientWidth + 1},
    images: {count: images.length, loaded_count: imageResults.filter(item => item.loaded).length, failures: imageResults.filter(item => !item.loaded)},
    fonts: {status: document.fonts.status, loaded_face_count: Array.from(document.fonts).filter(face => face.status === 'loaded').length, failed_face_count: Array.from(document.fonts).filter(face => face.status === 'error').length}
  };
}"""


MENU_BUTTON_JS = r"""button => {
  const controls = button.getAttribute('aria-controls');
  const nav = controls && document.getElementById(controls);
  const bars = Array.from(button.querySelectorAll(':scope > span[aria-hidden="true"]'));
  return Boolean(controls && nav && button.getAttribute('aria-expanded') !== null && bars.length === 3);
}"""


OPEN_MENU_CTA_ARROWS_JS = r"""() => {
  const glyphs = /[←↑→↓↗↘↙↖↩↪⇢⇨⟶⟹➔➜➝➞➟➠➡➢➤⮕⮞❯❱›»]/;
  const id = document.querySelector('button[aria-controls][aria-expanded="true"]')?.getAttribute('aria-controls');
  const nav = id && document.getElementById(id);
  if (!nav) return {pass: false, issues: ['open navigation was not found']};
  const candidates = Array.from(nav.querySelectorAll('a,button,[role="button"]')).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('href')].filter(Boolean).join(' ');
    return /ask|call|contact|book|schedule|inquir|reserve|visit|get in touch|quote|estimate|get started|start a project|let.s talk/i.test(label) ||
      /(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(String(element.className || ''));
  });
  const issues = candidates.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('title')].filter(Boolean).join(' ');
    if (glyphs.test(label) || element.querySelector('svg,[class*="arrow" i],[class*="chevron" i]')) return true;
    return [element, ...element.querySelectorAll('*')].some(node => ['::before', '::after'].some(pseudo => {
      const style = getComputedStyle(node, pseudo);
      return glyphs.test(style.content || '') || /url\s*\(/i.test(style.content || '') ||
        glyphs.test(style.backgroundImage || '') || /url\s*\(/i.test(style.backgroundImage || '') ||
        glyphs.test(style.maskImage || '') || /url\s*\(/i.test(style.maskImage || '');
    }));
  });
  return {pass: issues.length === 0, issues: issues.map(element => (element.innerText || element.getAttribute('aria-label') || '').trim())};
}"""


MENU_VISUAL_JS = r"""button => {
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      // aria-hidden affects assistive technology, not visual rendering. The
      // hamburger bars are intentionally aria-hidden, so test rendered styles.
      if (style.display === 'none' || style.visibility === 'hidden' ||
          Number(style.opacity) <= 0.01) return false;
    }
    return true;
  };
  const bars = Array.from(button.querySelectorAll(':scope > span[aria-hidden="true"]'));
  const hasVisibleColor = value => value !== 'transparent' &&
    !/^rgba\([^)]*,\s*0\s*\)$/.test(value);
  const visibleBars = bars.length === 3 && bars.every(bar => {
    const rect = bar.getBoundingClientRect();
    const style = getComputedStyle(bar);
    return visible(bar) && rect.width >= 10 && rect.height >= 1 &&
      hasVisibleColor(style.backgroundColor);
  });
  const rect = button.getBoundingClientRect();
  return {
    button_visible: visible(button) && rect.width >= 32 && rect.height >= 32,
    bars_visible: visibleBars,
    bar_count: bars.length,
    bar_rects: bars.map(bar => {
      const barRect = bar.getBoundingClientRect();
      return {width: Math.round(barRect.width), height: Math.round(barRect.height)};
    })
  };
}"""


MENU_FOCUSABLE_BEFORE_JS = r"""button => {
  const selector = 'a[href],area[href],input:not([disabled]),select:not([disabled]),' +
    'textarea:not([disabled]),button:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const visible = element => {
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.getAttribute('aria-hidden') === 'true' || style.display === 'none' ||
          style.visibility === 'hidden' || Number(style.opacity) <= 0.01) return false;
    }
    return true;
  };
  const focusable = Array.from(document.querySelectorAll(selector)).filter(visible);
  const index = focusable.indexOf(button);
  if (index < 1) return false;
  focusable[index - 1].focus();
  return document.activeElement === focusable[index - 1];
}"""


FOCUS_INDICATOR_JS = r"""element => {
  const style = getComputedStyle(element);
  const outlineVisible = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
  return outlineVisible || (style.boxShadow !== 'none' && style.boxShadow !== '');
}"""


TEMPLATE_LAYOUT_JS = r"""profile => {
  const main = document.querySelector('main');
  const h1 = document.querySelector('h1');
  const hero = h1 && (h1.closest('section') || h1.closest('[class*="hero" i]') || h1.closest('main'));
  const below = element => !!element && element !== hero && !(hero && hero.contains(element));
  const hasMedia = element => !!element.querySelector('img, picture, video, .image, [style*="background-image"]') ||
    ['::before', '::after'].some(pseudo => /url\s*\(/i.test(getComputedStyle(element, pseudo).backgroundImage || ''));
  const mediaSide = element => {
    const section = element.getBoundingClientRect();
    const media = element.querySelector('.image, picture, img, video, [style*="background-image"]');
    if (!media) return null;
    const rect = media.getBoundingClientRect();
    if (!rect.width || !section.width || rect.width < section.width * 0.18) return null;
    return rect.left + rect.width / 2 < section.left + section.width / 2 ? 'left' : 'right';
  };
  const alternations = sides => sides.slice(1).reduce((count, side, index) =>
    count + (side && sides[index] && side !== sides[index] ? 1 : 0), 0);
  const mainClasses = main ? main.className : '';
  const visibleSections = main ? Array.from(main.querySelectorAll(':scope > section, :scope > div > section'))
    .filter(section => section !== hero && !section.contains(hero)) : [];
  const spotlightSections = visibleSections.filter(section => section.matches('.spotlight'));
  const sides = spotlightSections.map(mediaSide);
  const common = {
    hero_has_banner_marker: !!(hero && hero.classList.contains('banner')),
    below_hero_section_count: visibleSections.length,
    below_hero_section_classes: visibleSections.slice(0, 8).map(section => String(section.className || '').trim()),
    spotlight_count: spotlightSections.length,
    spotlight_media_sides: sides,
    spotlight_side_alternations: alternations(sides),
    main_classes: mainClasses
  };
  let pass = false;
  let evidence = {};
  if (profile.profile === 'forty') {
    const tiles = main && main.querySelector('.tiles');
    const articles = tiles ? Array.from(tiles.querySelectorAll(':scope > article')) : [];
    const positions = [...new Set(articles.map(article => Math.round(article.getBoundingClientRect().left / 16)))];
    const mediaTiles = articles.filter(hasMedia).length;
    const layout = tiles ? getComputedStyle(tiles).display : 'missing';
    const columns = layout === 'grid' ? getComputedStyle(tiles).gridTemplateColumns.split(/\s+/).filter(Boolean).length : positions.length;
    evidence = {tile_grid_present: !!tiles, tile_count: articles.length, media_tile_count: mediaTiles,
      tile_layout: layout, desktop_tile_columns: columns};
    pass = !!(hero && hero.id === 'banner' && hero.classList.contains('major') && tiles && articles.length >= 3 &&
      mediaTiles >= 3 && (layout === 'grid' || layout === 'flex') && columns >= 2);
  } else if (profile.profile === 'landed') {
    const hasThreeStyles = ['style1', 'style2', 'style3'].every(name =>
      spotlightSections.some(section => section.classList.contains(name)));
    evidence = {has_three_spotlights: spotlightSections.length >= 3, has_three_source_styles: hasThreeStyles,
      alternating_media_columns: alternations(sides), wide_split_media_count: sides.filter(Boolean).length};
    pass = !!(hero && hero.id === 'banner' && spotlightSections.length >= 3 && hasThreeStyles && alternations(sides) >= 2);
  } else if (profile.profile === 'story') {
    const hasGalleryOrItems = !!(main && main.querySelector('.gallery, .items'));
    const hasOrientations = !!(main && main.querySelector('.orient-left') && main.querySelector('.orient-right'));
    evidence = {divided_page: !!document.querySelector('.divided, #wrapper.divided'),
      has_gallery_or_items: hasGalleryOrItems, has_both_orientations: hasOrientations,
      alternating_media_columns: alternations(sides), spotlight_media_count: sides.filter(Boolean).length};
    pass = !!(hero && hero.classList.contains('banner') && hero.classList.contains('fullscreen') && spotlightSections.length >= 2 &&
      hasGalleryOrItems && hasOrientations && alternations(sides) >= 1);
  }
  return {status: pass ? 'pass' : 'fail', pass, slug: profile.slug,
    signature_id: profile.signature_id, profile: profile.profile, ...common, ...evidence};
}"""


def _selected_template_profile(run_dir: Path) -> tuple[dict | None, dict]:
    audit_path = run_dir / "debug" / "design_reference.json"
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {"status": "not_required", "pass": True, "reason": "no selected template audit"}
    if not isinstance(audit, dict) or audit.get("status") != "selected":
        return None, {"status": "not_required", "pass": True, "reason": "no selected template"}
    profile = qa_profile(audit.get("design_reference"))
    if not profile:
        try:
            plan = json.loads((run_dir / "debug" / "design_references.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            plan = {}
        if isinstance(plan, dict) and isinstance(plan.get("design_references"), list):
            if selection_is_supported(plan["design_references"]):
                return {"profile": "unsupported"}, {"status": "pending", "pass": False, "reason": "selected template does not match maintained scaffold plan"}
            return None, {"status": "legacy_unverified", "pass": True, "reason": "saved continuation uses a pre-scaffold template plan"}
        try:
            checkpoint = json.loads((run_dir / "chunks" / "sequence_checkpoint.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoint = {}
        if checkpoint.get("sequence_plan") != "html5up-source-scaffolds-three-reference-slots-css-2-html-2-single-chat-v4":
            return None, {"status": "legacy_unverified", "pass": True, "reason": "saved candidate uses a pre-scaffold template plan"}
        return {"profile": "unsupported"}, {"status": "pending", "pass": False, "reason": "selected template has no maintained scaffold signature"}
    return profile, {"status": "pending", "pass": False}


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
        return {
            "found": False, "control_visible": False, "click_opens": False,
            "click_closes": False, "tab_reachable": False,
            "focus_indicator_visible": False, "enter_opens": False,
            "space_toggles": False, "escape_closes": False,
            "cta_arrows_absent_when_open": False, "pass": False,
        }

    nav_id = button.get_attribute("aria-controls")
    result = {"found": True}
    try:
        result["visual"] = button.evaluate(MENU_VISUAL_JS)
        result["control_visible"] = bool(
            result["visual"].get("button_visible") and result["visual"].get("bars_visible")
        )
        if button.get_attribute("aria-expanded") == "true":
            button.click()
        button.click()
        page.wait_for_timeout(150)
        result["click_opens"] = button.get_attribute("aria-expanded") == "true" and _nav_visible(page, nav_id)
        if result["click_opens"]:
            result["cta_arrows_when_open"] = page.evaluate(OPEN_MENU_CTA_ARROWS_JS)
            result["cta_arrows_absent_when_open"] = bool(result["cta_arrows_when_open"].get("pass"))
        button.click()
        page.wait_for_timeout(150)
        result["click_closes"] = button.get_attribute("aria-expanded") == "false" and not _nav_visible(page, nav_id)

        preceding_focusable = button.evaluate(MENU_FOCUSABLE_BEFORE_JS)
        if preceding_focusable:
            page.keyboard.press("Tab")
        result["tab_reachable"] = bool(
            preceding_focusable and button.evaluate("element => element === document.activeElement")
        )
        if result["tab_reachable"]:
            result["focus_indicator_visible"] = button.evaluate(FOCUS_INDICATOR_JS)
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
            result["enter_opens"] = button.get_attribute("aria-expanded") == "true" and _nav_visible(page, nav_id)
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            result["escape_closes"] = (
                button.get_attribute("aria-expanded") == "false"
                and not _nav_visible(page, nav_id)
                and button.evaluate("element => element === document.activeElement")
            )
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
            page.keyboard.press("Space")
            page.wait_for_timeout(150)
            result["space_toggles"] = button.get_attribute("aria-expanded") == "false" and not _nav_visible(page, nav_id)
        else:
            result["enter_opens"] = False
            result["space_toggles"] = False
            result["escape_closes"] = False
            result["focus_indicator_visible"] = False
    except Exception as error:
        result["error"] = str(error)
        result.setdefault("click_opens", False)
        result.setdefault("click_closes", False)
        result.setdefault("control_visible", False)
        result.setdefault("tab_reachable", False)
        result.setdefault("enter_opens", False)
        result.setdefault("space_toggles", False)
        result.setdefault("escape_closes", False)
        result.setdefault("focus_indicator_visible", False)
        result.setdefault("cta_arrows_absent_when_open", False)
    result.setdefault("control_visible", False)
    result["pass"] = all(result.get(key, False) for key in (
        "control_visible", "click_opens", "click_closes", "tab_reachable",
        "focus_indicator_visible", "enter_opens", "space_toggles", "escape_closes"
    ))
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
            browser = playwright.chromium.launch(headless=True)
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
                        sections = page.evaluate(SECTION_VISIBILITY_JS, section_aliases)
                        visual = page.evaluate(VIEWPORT_CHECKS_JS)
                        if name == "desktop" and template_profile:
                            report["template_layout"] = page.evaluate(TEMPLATE_LAYOUT_JS, template_profile)
                        page.screenshot(path=str(screenshots_dir / f"{name}.png"), full_page=False)
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
                            "hero_media_covers_hero": bool(visual["hero"].get("media_covers_hero")),
                            "hero_image_loaded": bool(visual["hero"].get("image_loaded")),
                            "cta": visual["cta"],
                            "cta_visible_first_screen": visual["cta"]["visible_first_screen"],
                            "horizontal_overflow": visual["horizontal_overflow"],
                            "no_horizontal_overflow": not visual["horizontal_overflow"]["overflow"],
                            "critical_content_clipping": visual["critical_content_clipping"],
                            "no_critical_content_clipping": bool(visual["critical_content_clipping"]["pass"]),
                            "contact_email_ctas": visual["contact_email_ctas"],
                            "contact_email_ctas_grouped": visual["contact_email_ctas"]["ungrouped_count"] == 0,
                            "hero_cta_contrast": visual["hero_cta_contrast"],
                            "hero_ctas_readable": bool(visual["hero_cta_contrast"]["pass"]),
                            "images": resource_state,
                            "visible_content_images": visual["visible_content_images"],
                            "cta_arrows_absent": not visual["cta"].get("arrow_issues"),
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
                        if name == "desktop" and template_profile and report["template_layout"].get("status") == "pending":
                            report["template_layout"] = {
                                **report["template_layout"], "status": "fail", "pass": False,
                                "reason": "desktop template layout could not be measured",
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
                            "hero_media_covers_hero": False,
                            "hero_image_loaded": False,
                            "cta_visible_first_screen": False,
                            "no_horizontal_overflow": False,
                            "critical_content_clipping": {"pass": False, "issues": []},
                            "no_critical_content_clipping": False,
                            "contact_email_ctas": {"count": 0, "ungrouped_count": 0},
                            "contact_email_ctas_grouped": False,
                            "hero_cta_contrast": {"pass": False, "issues": []},
                            "hero_ctas_readable": False,
                            "images_loaded": False,
                            "visible_content_images": {"distinct_count": 0, "loaded_count": 0, "failures": []},
                            "cta_arrows_absent": False,
                            "fonts_loaded": False,
                            "screenshot": f"screenshots/{name}.png",
                        }
                    finally:
                        page.close()
            finally:
                browser.close()

        desktop = report["viewports"].get("desktop", {})
        mobile = report["viewports"].get("mobile", {})
        mobile_menu = report["mobile_menu"]
        report["checks"] = {
            "rendered_sections_visible_desktop_and_mobile": bool(desktop.get("all_required_sections_visible") and mobile.get("all_required_sections_visible")),
            "hero_spans_viewport_desktop_and_mobile": bool(desktop.get("hero_spans_viewport") and mobile.get("hero_spans_viewport")),
            "hero_media_covers_hero_desktop_and_mobile": bool(desktop.get("hero_media_covers_hero") and mobile.get("hero_media_covers_hero")),
            "hero_image_loads_desktop_and_mobile": bool(desktop.get("hero_image_loaded") and mobile.get("hero_image_loaded")),
            "visible_content_images_load_in_browser": bool(
                desktop.get("visible_content_images", {}).get("distinct_count", 0) >= 1
                and mobile.get("visible_content_images", {}).get("distinct_count", 0) >= 1
                and desktop.get("visible_content_images", {}).get("loaded_count", 0) == desktop.get("visible_content_images", {}).get("distinct_count", 0)
                and mobile.get("visible_content_images", {}).get("loaded_count", 0) == mobile.get("visible_content_images", {}).get("distinct_count", 0)
            ),
            "cta_arrows_absent_desktop_and_mobile": bool(
                desktop.get("cta_arrows_absent") and mobile.get("cta_arrows_absent")
                and mobile_menu.get("cta_arrows_absent_when_open")
            ),
            "cta_visible_first_screen_desktop_and_mobile": bool(desktop.get("cta_visible_first_screen") and mobile.get("cta_visible_first_screen")),
            "mobile_menu_clicks_work": bool(mobile_menu.get("click_opens") and mobile_menu.get("click_closes")),
            "mobile_menu_control_visible": bool(mobile_menu.get("control_visible")),
            "mobile_menu_focus_indicator_visible": bool(mobile_menu.get("focus_indicator_visible")),
            "mobile_menu_keyboard_works": bool(
                mobile_menu.get("tab_reachable") and mobile_menu.get("enter_opens")
                and mobile_menu.get("space_toggles") and mobile_menu.get("escape_closes")
            ),
            "mobile_has_no_horizontal_overflow": bool(mobile.get("no_horizontal_overflow")),
            "critical_content_within_viewport_desktop_and_mobile": bool(
                desktop.get("no_critical_content_clipping") and mobile.get("no_critical_content_clipping")
            ),
            "contact_email_ctas_grouped": bool(
                desktop.get("contact_email_ctas_grouped") and mobile.get("contact_email_ctas_grouped")
            ),
            "hero_ctas_readable_desktop_and_mobile": bool(
                desktop.get("hero_ctas_readable") and mobile.get("hero_ctas_readable")
            ),
            "fonts_load_in_browser": bool(desktop.get("fonts_loaded") and mobile.get("fonts_loaded")),
            "images_load_in_browser": bool(desktop.get("images_loaded") and mobile.get("images_loaded")),
            "template_layout_signature_matches": bool(report["template_layout"].get("pass")),
        }
        report["status"] = "pass" if all(report["checks"].values()) else "fail"

    output = debug_dir / "browser_qa.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
