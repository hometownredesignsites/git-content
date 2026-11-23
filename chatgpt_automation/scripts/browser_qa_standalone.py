#!/usr/bin/env python3
"""Self-contained Chromium/Playwright QA runner for the website POC skill.

Generated from browser_qa.py and its exact helper implementations. Runtime imports
are limited to Python's standard library and Playwright; no repository checkout or
sibling scripts are required.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import concurrent.futures
import hashlib
import html as html_module
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SECTION_ALIASES = {
    "hero": ("hero", "banner", "welcome", "introduction", "intro", "site-header", "masthead"),
    "contact": ("contact", "booking", "book", "appointment", "get in touch", "form"),
    "footer": ("footer",),
    "services": ("services", "service", "repairs", "repair", "offerings", "experiences", "attractions"),
    "process": ("process", "how it works", "steps", "what to expect"),
    "testimonials": ("testimonials", "reviews", "customer stories", "guest stories", "player stories"),
    "location": ("location", "directions", "find us", "address", "visit"),
    "hours": ("hours", "opening times", "opening hours", "business hours", "shop hours", "when we're open"),
    "about": ("about", "our story", "who we are", "mission"),
    "faq": ("faq", "frequently asked", "questions"),
    "pricing": ("pricing", "prices", "cost", "rates"),
    "team": ("team", "staff", "our people"),
    "gallery": ("gallery", "portfolio", "our work", "photos"),
}

def _looks_like_image(data, content_type=""):
    """Accept recognized image data and reject HTML, JSON, or MIME-only claims."""
    if not data:
        return False
    sample = data[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if sample.startswith((b"<!doctype html", b"<html", b"{", b"[")):
        return False
    if (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        and len(data) >= 24
        and int.from_bytes(data[16:20], "big") > 0
        and int.from_bytes(data[20:24], "big") > 0
    ):
        return True
    if data.startswith(b"\xff\xd8\xff") and len(data) >= 4:
        return True
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 14:
        return True
    if (data.startswith(b"BM") and len(data) >= 26) or (
        data.startswith((b"II*\x00", b"MM\x00*")) and len(data) >= 8
    ):
        return True
    if data.startswith(b"\x00\x00\x01\x00") and len(data) >= 22:
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        return True
    if len(data) >= 16 and data[4:8] == b"ftyp" and data[8:12] in {
        b"avif", b"avis", b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"jxl "
    }:
        return True
    if re.match(
        rb"^(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<svg(?:\s|>)",
        sample,
        re.DOTALL,
    ):
        return True
    return False

def _required_sections(prompt):
    # The scraped source audit is factual input, not a list of requested sections.
    # Infer requirements only from the actual redesign request before the audit block.
    request_text = re.split(
        r"\n\s*(?:VERIFIED SOURCE SITE AUDIT|The runner could not fetch the public source homepage)",
        prompt,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    request_text = re.sub(
        r"\b(?:avoid|do\s+not|don't|never)\s+"
        r"(?:invent(?:ing)?|include|add|create|feature|use|request)\b[^.!?\n]*[.!?]?",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    # Generic redesign briefs often mention optional sections and conditional
    # policies (for example, "do not assume every organization has hours" or
    # "if hours conflict, ask visitors to confirm"). Those mentions describe
    # constraints; they do not make the section mandatory for every target.
    request_text = re.sub(
        r"\bdo\s+not\s+assume\b[^.!?\n]*[.!?]?",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    request_text = re.sub(
        r"[^.!?\n]*\b(?:if|when)\b[^.!?\n]*[.!?]?",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    request_text = re.sub(
        r"[^.!?\n]*\bonly\s+when\b[^.!?\n]*[.!?]?",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    request_text = re.sub(
        r"\boptional\s+(?:business\s+)?(?:location|hours|business\s+hours|testimonials?|reviews?)\b",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    request_text = re.sub(
        r"[^.!?\n]*\bwhen\s+present\b[^.!?\n]*[.!?]?",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    text = request_text.lower()
    required = {"hero", "contact", "footer"}
    trigger_terms = {
        "services": r"\b(?:services?|repairs?|offerings?|experiences?|attractions?)\b",
        "process": r"\b(?:process|steps?|how it works|what to expect)\b",
        "testimonials": r"\b(?:testimonials?|reviews?|customer stories|guest stories|player stories)\b",
        "location": r"\b(?:location|directions|find us|address|visit)\b",
        "hours": r"\b(?:hours|opening times|business hours)\b",
        "about": r"\babout(?:\s+(?:us|section|page|the\s+(?:business|company|brand|shop|team)))\b|\bour\s+story\b|\bmission\b",
        "faq": r"\b(?:faq|frequently asked questions)\b",
        "pricing": r"\b(?:pricing|prices|cost|rates)\b",
        "team": r"\b(?:team|staff)\b",
        "gallery": r"\b(?:gallery|portfolio|photos)\b",
    }
    for section, pattern in trigger_terms.items():
        if re.search(pattern, text, re.IGNORECASE):
            required.add(section)
    return sorted(required)

SOURCE_IMAGE_CDN_SUFFIXES = (
    "wixstatic.com",
    "squarespace-cdn.com",
    "shopifycdn.net",
    "website-files.com",
    "cloudinary.com",
    "imgix.net",
    "ctfassets.net",
    "wsimg.com",
)

def _is_source_image_host_allowed(image_url: str, source_domain: str) -> bool:
    """Allow source-host photos and URLs served by common first-party image CDNs."""
    host = (urlsplit(image_url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    if host == source_domain or host.endswith("." + source_domain):
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in SOURCE_IMAGE_CDN_SUFFIXES)


QA_TEMPLATE_PROFILES = {
    "forty": {"slug": "forty", "signature_id": "forty-image-tiles", "profile": "forty"},
    "landed": {"slug": "landed", "signature_id": "landed-alternating-spotlights", "profile": "landed"},
    "story": {"slug": "story", "signature_id": "story-fullbleed-divided-panels-gallery", "profile": "story"},
}
QA_TEMPLATE_URLS = {
    "forty": "https://html5up.net/forty",
    "landed": "https://html5up.net/landed",
    "story": "https://html5up.net/story",
}

def qa_profile(reference):
    if not isinstance(reference, dict):
        return None
    slug = urlsplit(str(reference.get("template_url", ""))).path.strip("/").split("/")[-1].lower()
    return QA_TEMPLATE_PROFILES.get(slug)

def selection_is_supported(references):
    if not isinstance(references, list) or len(references) != 3:
        return False
    slugs = {urlsplit(str(item.get("template_url", ""))).path.strip("/").split("/")[-1].lower()
             for item in references if isinstance(item, dict)}
    return slugs == set(QA_TEMPLATE_PROFILES)



CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)

IMAGE_ATTRS = {"src", "data-src", "data-lazy-src", "poster"}

SRCSET_ATTRS = {"srcset", "data-srcset", "data-lazy-srcset"}

SVG_IMAGE_ATTRS = {"href", "xlink:href"}

MAX_IMAGE_BYTES = 25 * 1024 * 1024

MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024

def _srcset_urls(value: str) -> list[str]:
    """Return URL tokens from ordinary srcset values (data URIs stay untouched)."""
    result = []
    for candidate in value.split(","):
        fields = candidate.strip().split()
        if fields and not fields[0].lower().startswith("data:"):
            result.append(fields[0])
    return result

def _external_url(raw_url: str, base_url: str) -> str | None:
    raw_url = raw_url.strip().strip("'\"")
    if not raw_url or raw_url.startswith(("#", "data:", "blob:", "javascript:")):
        return None
    resolved = urllib.parse.urljoin(base_url, raw_url) if base_url else raw_url
    parsed = urllib.parse.urlsplit(resolved)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return resolved
    # Preserve unresolved relative paths so the integrity manifest fails closed.
    return resolved if not parsed.scheme else None

def _references_from_html(source: str, base_url: str) -> list[str]:
    references: list[str] = []

    class Collector(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_style = False

        def handle_starttag(self, tag, attrs):
            self.in_style = tag.lower() == "style"
            for name, value in attrs:
                if not value:
                    continue
                if name.lower() in IMAGE_ATTRS or (tag.lower() == "image" and name.lower() in SVG_IMAGE_ATTRS):
                    candidate = _external_url(value, base_url)
                    if candidate:
                        references.append(candidate)
                elif name.lower() in SRCSET_ATTRS:
                    references.extend(
                        candidate for raw in _srcset_urls(value)
                        if (candidate := _external_url(raw, base_url))
                    )
                elif name.lower() == "style":
                    for match in CSS_URL_RE.finditer(value):
                        candidate = _external_url(match.group(2), base_url)
                        if candidate:
                            references.append(candidate)

        def handle_endtag(self, tag):
            if tag.lower() == "style":
                self.in_style = False

        def handle_data(self, data):
            # The parser also calls this for script text; only CSS url() syntax
            # is considered, and non-URL/data references are discarded above.
            for match in CSS_URL_RE.finditer(data if self.in_style else ""):
                candidate = _external_url(match.group(2), base_url)
                if candidate:
                    references.append(candidate)

    Collector().feed(source)
    return list(dict.fromkeys(references))

def _validate_image_bytes(data: bytes, content_type: str) -> str:
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds {MAX_IMAGE_BYTES} byte limit")
    if not data:
        raise ValueError("empty image response")
    if not _looks_like_image(data, content_type):
        raise ValueError("response bytes are not a recognized image")
    if content_type and not (content_type.startswith("image/") or content_type == "application/octet-stream"):
        raise ValueError(f"unexpected content type {content_type}")
    signature_mime = _signature_mime(data)
    if not signature_mime:
        raise ValueError("recognized image signature has no supported MIME type")
    if content_type.startswith("image/") and content_type not in {signature_mime, "image/jpg" if signature_mime == "image/jpeg" else signature_mime}:
        raise ValueError(f"content type {content_type} does not match image bytes ({signature_mime})")
    return signature_mime

def _read_image(url: str, source_domain: str, opener: Callable = urllib.request.urlopen) -> tuple[bytes, str, dict]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("relative image URL cannot be resolved without a source page URL")
    if parsed.username or parsed.password or not _is_source_image_host_allowed(url, source_domain) and (parsed.hostname or "").lower() != "images.unsplash.com":
        raise ValueError("image host is outside the source-site and approved image-CDN allowlist")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
    )
    with opener(request, timeout=15) as response:
        status = int(response.getcode() or 0)
        final_url = response.geturl()
        final_parsed = urllib.parse.urlsplit(final_url)
        if final_parsed.scheme not in {"http", "https"} or not final_parsed.netloc or final_parsed.username or final_parsed.password:
            raise ValueError("image redirect ended at a disallowed URL")
        if not _is_source_image_host_allowed(final_url, source_domain) and (final_parsed.hostname or "").lower() != "images.unsplash.com":
            raise ValueError("image redirect left the source-site and approved image-CDN allowlist")
        content_type = (response.headers.get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
        data = response.read(MAX_IMAGE_BYTES + 1)
    if not 200 <= status < 300:
        raise ValueError(f"HTTP status {status}")
    mime = _validate_image_bytes(data, content_type)
    return data, mime, {"http_status": status, "final_url": final_url, "content_type": content_type,
                        "runtime_network_fetch": "completed"}

def _signature_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if re.match(rb"^(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<svg(?:\s|>)", data[:4096].lstrip(), re.I):
        return "image/svg+xml"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "image/avif" if data[8:12] in {b"avif", b"avis"} else "image/heic"
    return ""

def _embed_url(value: str, replacements: dict[str, str], base_url: str) -> str:
    resolved = _external_url(value, base_url)
    return replacements.get(resolved, value) if resolved else value

def _rewrite_srcset(value: str, replacements: dict[str, str], base_url: str) -> str:
    entries = []
    for candidate in value.split(","):
        fields = candidate.strip().split()
        if not fields:
            continue
        fields[0] = _embed_url(fields[0], replacements, base_url)
        entries.append(" ".join(fields))
    return ", ".join(entries)

def _rewrite_css(css: str, replacements: dict[str, str], base_url: str) -> str:
    def replace(match):
        raw = match.group(2)
        return f"url('{_embed_url(raw, replacements, base_url)}')"
    return CSS_URL_RE.sub(replace, css)

def _rewrite_html(source: str, replacements: dict[str, str], base_url: str) -> str:
    class Rewriter(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.parts: list[str] = []
            self.in_style = False

        def handle_starttag(self, tag, attrs):
            self.in_style = tag.lower() == "style"
            rendered = []
            for name, value in attrs:
                if value is None:
                    rendered.append(name)
                    continue
                lower = name.lower()
                if lower in IMAGE_ATTRS or (tag.lower() == "image" and lower in SVG_IMAGE_ATTRS):
                    value = _embed_url(value, replacements, base_url)
                elif lower in SRCSET_ATTRS:
                    value = _rewrite_srcset(value, replacements, base_url)
                elif lower == "style":
                    value = _rewrite_css(value, replacements, base_url)
                rendered.append(f'{name}="{escape(value, quote=True)}"')
            self.parts.append("<" + tag + (" " + " ".join(rendered) if rendered else "") + ">")

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            self.parts[-1] = self.parts[-1][:-1] + "/>"

        def handle_endtag(self, tag):
            if tag.lower() == "style":
                self.in_style = False
            self.parts.append(f"</{tag}>")

        def handle_data(self, data):
            self.parts.append(_rewrite_css(data, replacements, base_url) if self.in_style else data)

        def handle_entityref(self, name):
            self.parts.append(f"&{name};")

        def handle_charref(self, name):
            self.parts.append(f"&#{name};")

        def handle_comment(self, data):
            self.parts.append(f"<!--{data}-->")

        def handle_decl(self, decl):
            self.parts.append(f"<!{decl}>")

        def unknown_decl(self, data):
            self.parts.append(f"<![{data}]>")

    parser = Rewriter()
    parser.feed(source)
    parser.close()
    return "".join(parser.parts)

def build_embedded_screenshot_html(source_html: bytes, base_url: str, output_path: Path,
                                  opener: Callable = urllib.request.urlopen,
                                  asset_manifest_path: Path | None = None) -> dict:
    """Download, validate, and embed candidate image references into a temp HTML copy."""
    source = source_html.decode("utf-8")
    urls = _references_from_html(source, base_url)
    source_domain = (urllib.parse.urlsplit(base_url).hostname or "").lower().removeprefix("www.")
    bundle_assets: dict[str, dict] = {}
    bundle_root: Path | None = None
    bundle_meta: dict = {}
    same_session_cache = False
    bundle_load_error = ""
    if asset_manifest_path is not None:
        try:
            manifest_path = Path(asset_manifest_path).resolve()
            bundle_root = manifest_path.parent
            bundle_meta = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(bundle_meta, dict) or not isinstance(bundle_meta.get("assets"), list):
                raise ValueError("image asset manifest must contain an assets array")
            same_session_cache = bundle_meta.get("network_retrieval_status") == "completed_current_runtime_before_generation"
            bundle_assets = {
                str(item.get("url", "")): item for item in bundle_meta["assets"] if isinstance(item, dict)
            }
        except (OSError, json.JSONDecodeError, ValueError) as error:
            bundle_load_error = str(error)[:300]
    records = []
    replacements: dict[str, str] = {}
    total_bytes = 0
    for url in urls:
        record = {"url": url, "status": "blocked", "bytes": 0, "mime_type": "", "sha256": "", "width": None, "height": None}
        try:
            if asset_manifest_path is not None:
                if bundle_load_error:
                    raise ValueError(f"provided image asset manifest is invalid: {bundle_load_error}")
                asset = bundle_assets.get(url)
                if not asset:
                    raise ValueError("exact URL is absent from the supplied image asset bundle")
                asset_path = (bundle_root / str(asset.get("path", ""))).resolve()
                if bundle_root not in asset_path.parents:
                    raise ValueError("image asset path escapes the supplied bundle directory")
                data = asset_path.read_bytes()
                content_type = str(asset.get("mime_type", "")).lower().strip()
                mime = _validate_image_bytes(data, content_type)
                digest = hashlib.sha256(data).hexdigest()
                if len(data) != int(asset.get("bytes", -1)) or digest != str(asset.get("sha256", "")):
                    raise ValueError("provided image bytes do not match the asset manifest size/SHA-256")
                response = {
                    "runtime_network_fetch": "completed_before_generation_same_session" if same_session_cache else "not_attempted_using_bundle",
                    "bundle_path": str(asset_path.relative_to(bundle_root).as_posix()),
                    "bundle_network_retrieval": asset.get("network_retrieval", {}),
                    "bundle_digest_verified": True,
                    "content_type": content_type,
                }
            else:
                data, mime, response = _read_image(url, source_domain, opener)
            total_bytes += len(data)
            if total_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise ValueError(f"images exceed {MAX_TOTAL_IMAGE_BYTES} byte total limit")
            uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            replacements[url] = uri
            record.update(response)
            record.update({"status": "embedded", "bytes": len(data), "mime_type": mime,
                           "sha256": hashlib.sha256(data).hexdigest()})
        except Exception as error:
            record["error"] = str(error)[:300]
        records.append(record)

    failed = [item["url"] for item in records if item["status"] != "embedded"]
    report = {
        "status": "blocked" if failed else "pass",
        "source_html_sha256": hashlib.sha256(source_html).hexdigest(),
        "embedded_html_path": str(output_path) if not failed else "",
        "reference_count": len(urls),
        "embedded_count": len(replacements),
        "failed_urls": failed,
        "images": records,
        "asset_source": "same_session_cache" if same_session_cache else "provided_bundle" if asset_manifest_path is not None else "live_network",
        "runtime_network_retrieval": "completed_before_generation_same_session" if same_session_cache else "not_attempted_using_bundle" if asset_manifest_path is not None else "attempted",
        "bundle_capture_network_status": bundle_meta.get("network_retrieval_status") if bundle_meta else None,
        "temporary_only": True,
        "_url_to_data_uri": replacements,
    }
    if not failed:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_rewrite_html(source, replacements, base_url), encoding="utf-8")
    return report



def _browser_launch_options(chromium: Any, env: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prefer Playwright's managed Chromium, then an explicitly configured/system Chromium."""
    env = os.environ if env is None else env
    configured = env.get("WEBSITE_POC_CHROMIUM_EXECUTABLE", "").strip()
    if configured:
        executable = Path(configured).expanduser()
        if not executable.is_file():
            raise FileNotFoundError(
                f"WEBSITE_POC_CHROMIUM_EXECUTABLE does not name a file: {executable}"
            )
        launch = {"headless": True, "executable_path": str(executable)}
        details = {"mode": "configured_system_chromium", "executable_path": str(executable)}
    else:
        managed = Path(chromium.executable_path)
        if managed.is_file():
            launch = {"headless": True}
            details = {"mode": "playwright_managed_chromium", "executable_path": str(managed)}
        else:
            executable = next(
                (Path(found) for name in ("chromium", "chromium-browser") if (found := shutil.which(name))),
                None,
            )
            if executable is None or not executable.is_file():
                raise FileNotFoundError(
                    "Playwright's managed Chromium is missing and no system Chromium was found. "
                    "Install the Playwright browser or set WEBSITE_POC_CHROMIUM_EXECUTABLE to a Chromium binary."
                )
            launch = {"headless": True, "executable_path": str(executable)}
            details = {"mode": "system_chromium_fallback", "executable_path": str(executable)}

    no_sandbox = env.get("WEBSITE_POC_CHROMIUM_NO_SANDBOX", "").strip().lower() in {"1", "true", "yes"}
    if no_sandbox:
        launch["args"] = ["--no-sandbox"]
    details["no_sandbox"] = no_sandbox
    return launch, details

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
  const header = document.querySelector('#header') || document.querySelector('header');
  const headerNavs = header ? Array.from(header.querySelectorAll('nav')) : [];
  const menuButton = header && header.querySelector('button[aria-controls]');
  const controlledNavId = menuButton && menuButton.getAttribute('aria-controls');
  const controlledNav = controlledNavId && document.getElementById(controlledNavId);
  const headerNavigation = {
    nav_count: headerNavs.length,
    visible_nav_count: headerNavs.filter(visible).length,
    links_within_limit: headerNavs.every(nav => nav.querySelectorAll('a[href]').length <= 5),
    navs: headerNavs.map(nav => ({
      id: nav.id || '',
      label: nav.getAttribute('aria-label') || '',
      link_count: nav.querySelectorAll('a[href]').length,
      visible: visible(nav)
    })),
    controlled_menu_hidden: !controlledNav || !controlledNav.classList.contains('mobile-nav') || !visible(controlledNav)
  };
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

  const ctaWords = /ask|call|contact|email|book|schedule|inquir|reserve|visit|get in touch|quote|estimate|get started|start a project|let.s talk/i;
  const arrowGlyphs = /[←↑→↓↗↘↙↖↩↪⇢⇨⟶⟹➔➜➝➞➟➠➡➢➤⮕⮞❯❱›»]/;
  const actions = Array.from(document.querySelectorAll('a,button,[role="button"],input[type="submit"]'));
  const visibleCtas = actions.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const ctaClass = /(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(String(element.className || ''));
    return (ctaWords.test(label) || ctaClass) && visible(element);
  });
  const ctaCandidates = actions.filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const ctaClass = /(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(String(element.className || ''));
    return ctaWords.test(label) || ctaClass;
  }).map(element => {
    const rect = element.getBoundingClientRect();
    return {
      text: (element.innerText || element.getAttribute('aria-label') || element.getAttribute('value') || '').trim().slice(0, 100),
      href: element.getAttribute('href') || '',
      tag: element.tagName.toLowerCase(),
      visible: visible(element),
      top: Math.round(rect.top),
      bottom: Math.round(rect.bottom)
    };
  }).slice(0, 12);
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
  const contactSections = Array.from(document.querySelectorAll('section')).filter(section => {
    const marker = [section.id, section.className, section.getAttribute('aria-label')].join(' ');
    return /contact|quote|estimate|booking|appointment/i.test(marker) || section.hasAttribute('data-source-contact-region') || Boolean(
      section.querySelector('[class~="contact-detail"], [class~="contact-details"], [class*="contact-form" i]')
    );
  });
  const contactSectionFor = element => element.closest('section') && contactSections.includes(element.closest('section'));
  const contactEmailButtons = Array.from(document.querySelectorAll('a[href^="mailto:"]'))
    .filter(element => contactSectionFor(element) && /(?:^|\s)(?:button|btn|cta)(?:\s|$)/i.test(String(element.className || '')));
  const ungroupedContactEmailButtons = contactEmailButtons.filter(element =>
    !element.closest('[class*="contact-actions" i], [class~="actions"], [class*="cta-group" i], [class*="button-group" i]')
  );
  const misplacedContactEmailButtons = contactEmailButtons.filter(element =>
    element.closest('[class~="contact-detail"], [class~="contact-details"]') || (() => {
      const group = element.closest('.source-contact-channels');
      if (!group || !group.parentElement) return false;
      if (group.getAttribute('data-contact-channel-placement') === 'full-row') return false;
      if (group.style.gridColumn === '1 / -1' && group.style.width === '100%') return false;
      const parent = group.parentElement;
      const parentClasses = String(parent.className || '').split(/\s+/);
      if (parentClasses.includes('contact-copy') || parentClasses.includes('contact-panel')) return false;
      const parentStyle = getComputedStyle(parent);
      return Boolean(parent.querySelector(
        ':scope > .contact-layout, :scope > .contact-inner, :scope > .contact-grid, :scope > .contact-details'
      )) || (['grid', 'inline-grid'].includes(parentStyle.display) && parent.children.length > 1);
    })()
  );
  const contactChannelButtons = contactSections.flatMap(section =>
    Array.from(section.querySelectorAll('a[href^="tel:"], a[href^="mailto:"]'))
  ).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label')].filter(Boolean).join(' ');
    return visible(element) && (/(?:^|\s)(?:button|btn|cta)(?:\s|$)/i.test(String(element.className || '')) ||
      /\b(call now|call us|email us|contact us)\b/i.test(label));
  });
  const contactChannelGroups = contactChannelButtons.map(element =>
    element.closest('.source-contact-channel-actions, [class*="contact-actions" i], [class~="actions"], [class*="cta-group" i], [class*="button-group" i]')
  );
  const contactChannelGroup = contactChannelGroups[0];
  const contactChannelStyle = contactChannelGroup ? getComputedStyle(contactChannelGroup) : null;
  const contactChannelAlignment = contactChannelButtons.length < 2 || Boolean(
    contactChannelGroup && contactChannelGroups.every(group => group === contactChannelGroup) &&
    ['flex', 'inline-flex'].includes(contactChannelStyle.display) &&
    contactChannelStyle.alignItems === 'center' && contactChannelStyle.justifyContent === 'center'
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
  const rgba = value => {
    const parts = String(value || '').match(/[\d.]+/g);
    if (!parts || parts.length < 3) return null;
    return {
      channels: parts.slice(0, 3).map(Number),
      alpha: parts.length > 3 ? Number(parts[3]) : 1
    };
  };
  const effectiveBackground = element => {
    let background = [255, 255, 255];
    const ancestors = [];
    for (let node = element; node; node = node.parentElement) ancestors.push(node);
    let unknownImageLayer = false;
    for (const node of ancestors.reverse()) {
      const style = getComputedStyle(node);
      const hasImage = Boolean(style.backgroundImage && style.backgroundImage !== 'none');
      if (hasImage) unknownImageLayer = true;
      const layer = rgba(style.backgroundColor);
      if (!layer || layer.alpha <= 0) continue;
      if (layer.alpha >= 0.98) {
        background = layer.channels;
        unknownImageLayer = hasImage;
        continue;
      }
      background = background.map((channel, index) => layer.channels[index] * layer.alpha + channel * (1 - layer.alpha));
    }
    return unknownImageLayer ? null : background;
  };
  const contactCtas = contactSections.flatMap(section =>
    Array.from(section.querySelectorAll('a,button,[role="button"],input[type="submit"]'))
  ).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const buttonClass = /(?:^|[\s_-])(?:button|btn|cta|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(String(element.className || ''));
    return visible(element) && (ctaWords.test(label) || buttonClass);
  });
  const contactCtaContrastIssues = contactCtas.flatMap(element => {
    const foreground = luminance(rgb(getComputedStyle(element).color));
    const backgroundColor = effectiveBackground(element);
    const background = backgroundColor === null ? null : luminance(rgb(`rgb(${backgroundColor.join(',')})`));
    const ratio = foreground === null || background === null
      ? null
      : (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
    if (ratio !== null && ratio >= 4.5) return [];
    return [{
      text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 100),
      color: getComputedStyle(element).color,
      background: backgroundColor ? `rgb(${backgroundColor.join(',')})` : 'unknown',
      contrast_ratio: ratio === null ? null : Math.round(ratio * 100) / 100,
      reason: ratio === null ? 'rendered background could not be measured reliably' : 'contrast ratio is below 4.5:1'
    }];
  });
  const imageCardLabels = Array.from(document.querySelectorAll('.tiles article .eyebrow')).filter(visible);
  const imageCardLabelIssues = imageCardLabels.filter(element => {
    const style = getComputedStyle(element);
    const color = luminance(rgb(style.color));
    const background = rgba(style.backgroundColor);
    return color === null || color < 0.8 || !background || background.alpha < 0.65;
  }).map(element => ({
    text: (element.innerText || '').trim().slice(0, 100),
    color: getComputedStyle(element).color,
    background: getComputedStyle(element).backgroundColor
  }));
  const h1Node = document.querySelector('h1');
  const heroNode = h1Node && (h1Node.closest('section') || h1Node.closest('[class*="hero" i]') || h1Node.closest('main'));
  const heroCtas = heroNode ? Array.from(heroNode.querySelectorAll('a,button,[role="button"]')).filter(element => {
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('href')].filter(Boolean).join(' ');
    const isAction = /quote|estimate|contact|call|book|schedule|inquir|email|start a project|let.s talk/i.test(label) ||
      /(?:^|\s)(?:button|btn|cta)(?:\s|$)/i.test(String(element.className || ''));
    return isAction && visible(element);
  }) : [];
  const heroCtaContrastIssues = heroCtas.flatMap(element => {
    const style = getComputedStyle(element);
    const foreground = luminance(rgb(style.color));
    const measuredBackground = effectiveBackground(element);
    const background = measuredBackground === null ? null : luminance(rgb(`rgb(${measuredBackground.join(',')})`));
    const ratio = foreground === null || background === null
      ? null
      : (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
    if (ratio !== null && ratio >= 4.5) return [];
    return [{
      text: (element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 100),
      color: style.color,
      background: measuredBackground ? `rgb(${measuredBackground.join(',')})` : style.backgroundColor,
      contrast_ratio: ratio === null ? null : Math.round(ratio * 100) / 100,
      reason: ratio === null ? 'rendered background could not be measured reliably' : 'contrast ratio is below 4.5:1'
    }];
  });
  const primaryCtas = Array.from(document.querySelectorAll('a,button,[role="button"],input[type="submit"]')).filter(element => {
    if (!visible(element)) return false;
    // A full-card link is a click target, not a visible button. Measuring its
    // hidden label as CTA text can trigger a repair that covers the card image.
    if (element.matches('a.tile-link') && element.closest('.tiles article')?.querySelector('.image img')) return false;
    const label = [element.innerText, element.getAttribute('aria-label'), element.getAttribute('value'), element.getAttribute('href')].filter(Boolean).join(' ');
    const classes = String(element.className || '');
    return ctaWords.test(label) || /(?:^|[\s_-])(?:button|btn|cta|primary|call[-_]?to[-_]?action)(?:$|[\s_-])/i.test(classes);
  });
  const stableSelector = element => {
    if (element.id) {
      const idSelector = `#${CSS.escape(element.id)}`;
      if (document.querySelectorAll(idSelector).length === 1) return idSelector;
    }
    const parts = [];
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
      let part = node.tagName.toLowerCase();
      const classes = Array.from(node.classList || []).slice(0, 2);
      if (classes.length) part += classes.map(name => `.${CSS.escape(name)}`).join('');
      const parent = node.parentElement;
      if (parent) {
        const peers = Array.from(parent.children).filter(child => child.tagName === node.tagName);
        if (peers.length > 1) part += `:nth-of-type(${peers.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      const selector = parts.join(' > ');
      try {
        if (document.querySelectorAll(selector).length === 1) return selector;
      } catch (_) {}
    }
    return parts.join(' > ');
  };
  const primaryCtaContrastIssues = primaryCtas.flatMap(element => {
    const foreground = luminance(rgb(getComputedStyle(element).color));
    const backgroundColor = effectiveBackground(element);
    const background = backgroundColor && luminance(rgb(`rgb(${backgroundColor.join(',')})`));
    const ratio = foreground !== null && background !== null
      ? (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05)
      : null;
    if (ratio !== null && ratio >= 4.5) return [];
    return [{
      text: (element.innerText || element.getAttribute('aria-label') || element.getAttribute('value') || '').trim().slice(0, 100),
      selector: stableSelector(element),
      color: getComputedStyle(element).color,
      background: backgroundColor ? `rgb(${backgroundColor.join(',')})` : 'unknown',
      contrast_ratio: ratio === null ? null : Math.round(ratio * 100) / 100,
      reason: ratio === null ? 'rendered background could not be measured reliably' : 'contrast ratio is below 4.5:1'
    }];
  });
  const images = Array.from(document.images);
  images.forEach(image => { image.loading = 'eager'; });
  const opaqueImageTileOverlays = Array.from(document.querySelectorAll('.tiles article a.tile-link')).flatMap(element => {
    const article = element.closest('article');
    const image = article && article.querySelector('.image img');
    if (!image) return [];
    const style = getComputedStyle(element);
    const overlay = element.getBoundingClientRect();
    const card = article.getBoundingClientRect();
    const coversCard = style.position === 'absolute' && overlay.width >= card.width * 0.9 && overlay.height >= card.height * 0.9;
    const background = rgba(style.backgroundColor);
    return coversCard && background && background.alpha >= 0.95
      ? [{selector: stableSelector(element), background: style.backgroundColor}]
      : [];
  });
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
    header_navigation: headerNavigation,
    cta: {
      visible_first_screen: Boolean(cta),
      text: cta ? (cta.innerText || cta.getAttribute('aria-label') || '').trim() : '',
      href: cta ? (cta.getAttribute('href') || '') : '',
      tag: cta ? cta.tagName.toLowerCase() : '',
      bottom: ctaRect ? Math.round(ctaRect.bottom) : null,
      candidates: ctaCandidates,
      arrow_issues: ctaArrowIssues.map(element => (element.innerText || element.getAttribute('aria-label') || '').trim())
    },
    critical_content_clipping: {pass: clippingIssues.length === 0, issues: clippingIssues},
    contact_email_ctas: {
      count: contactEmailButtons.length,
      ungrouped_count: ungroupedContactEmailButtons.length,
      misplaced_count: misplacedContactEmailButtons.length
    },
    contact_channel_ctas: {
      count: contactChannelButtons.length,
      aligned: contactChannelAlignment,
      labels: contactChannelButtons.map(element => (element.innerText || element.getAttribute('aria-label') || '').trim())
    },
    contact_cta_contrast: {pass: contactCtaContrastIssues.length === 0, issues: contactCtaContrastIssues},
    image_card_labels: {count: imageCardLabels.length, pass: imageCardLabelIssues.length === 0, issues: imageCardLabelIssues},
    hero_cta_contrast: {pass: heroCtaContrastIssues.length === 0, issues: heroCtaContrastIssues},
    primary_cta_contrast: {
      count: primaryCtas.length,
      pass: primaryCtas.length > 0 && primaryCtaContrastIssues.length === 0,
      issues: primaryCtas.length ? primaryCtaContrastIssues : [{reason: 'no visible primary CTA could be identified'}]
    },
    opaque_image_tile_overlays: opaqueImageTileOverlays,
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

HEADER_NAV_AUDIT_JS = r"""() => {
  const visible = element => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.getAttribute('aria-hidden') === 'true' || style.display === 'none' ||
          style.visibility === 'hidden' || Number(style.opacity) <= 0.01) return false;
    }
    return true;
  };
  const header = document.querySelector('#header') || document.querySelector('header');
  const navs = header ? Array.from(header.querySelectorAll('nav')) : [];
  const button = header && header.querySelector('button[aria-controls]');
  const id = button && button.getAttribute('aria-controls');
  const controlled = id && document.getElementById(id);
  return {
    nav_count: navs.length,
    visible_nav_count: navs.filter(visible).length,
    links_within_limit: navs.every(nav => nav.querySelectorAll('a[href]').length <= 5),
    controlled_nav_visible: Boolean(controlled && visible(controlled)),
    navs: navs.map(nav => ({id: nav.id || '', link_count: nav.querySelectorAll('a[href]').length, visible: visible(nav)}))
  };
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

def _enforce_story_full_bleed_hero(profile: dict | None, report: dict) -> None:
    """Require Story's hero image to cover its full rendered hero on both viewports."""
    if not isinstance(profile, dict) or profile.get("profile") != "story":
        return
    coverage = {
        name: bool(report.get("viewports", {}).get(name, {}).get("hero_media_covers_hero"))
        for name in ("desktop", "mobile")
    }
    layout = report.setdefault("template_layout", {})
    actual = layout.setdefault("actual", {})
    expected = layout.setdefault("expected", {})
    actual["hero_media_covers_hero_by_viewport"] = coverage
    expected["hero_media_covers_hero_desktop_and_mobile"] = True
    if not all(coverage.values()):
        layout["status"] = "fail"
        layout["pass"] = False
        layout["reason"] = "The Story hero photo must cover the full hero on desktop and mobile."

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
            "cta_arrows_absent_when_open": False, "hidden_until_open": False,
            "only_one_nav_visible_when_open": False, "link_limit_pass": False,
            "pass": False,
        }

    nav_id = button.get_attribute("aria-controls")
    result = {
        "found": True,
        "controlled_nav_id": nav_id,
        "button_inside_navigation": bool(button.evaluate("(button, id) => { const nav = document.getElementById(id); return Boolean(nav && nav.contains(button)); }", nav_id)),
    }
    try:
        initial_nav_audit = page.evaluate(HEADER_NAV_AUDIT_JS)
        result["hidden_until_open"] = not initial_nav_audit.get("controlled_nav_visible", True)
        result["mobile_nav_link_count"] = next(
            (item["link_count"] for item in initial_nav_audit.get("navs", []) if item.get("id") == nav_id),
            0,
        )
        result["link_limit_pass"] = bool(
            initial_nav_audit.get("links_within_limit") and result["mobile_nav_link_count"] <= 5
        )
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
            open_nav_audit = page.evaluate(HEADER_NAV_AUDIT_JS)
            result["visible_nav_count_when_open"] = open_nav_audit.get("visible_nav_count")
            result["only_one_nav_visible_when_open"] = open_nav_audit.get("visible_nav_count") == 1
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
        result.setdefault("hidden_until_open", False)
        result.setdefault("only_one_nav_visible_when_open", False)
        result.setdefault("link_limit_pass", False)
    result.setdefault("control_visible", False)
    result["pass"] = all(result.get(key, False) for key in (
        "control_visible", "click_opens", "click_closes", "tab_reachable",
        "focus_indicator_visible", "enter_opens", "space_toggles", "escape_closes",
        "hidden_until_open", "only_one_nav_visible_when_open", "link_limit_pass"
    ))
    return result

def main(argv: list[str] | None = None, emit: bool = True) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    parser.add_argument("request", help="Original website request used to determine required sections")
    parser.add_argument("--image-assets-manifest", type=Path, help="Offline image bundle manifest; exact URLs and hashes must match")
    parser.add_argument("--offline-no-network", action="store_true", help="Abort all HTTP(S) requests during rendering")
    args = parser.parse_args(argv)

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
        "image_gate": {"status": "blocked", "reason": "image preparation has not completed", "viewports": {}},
        "screenshots_visual_qa_eligible": False,
        "offline_no_network": args.offline_no_network,
        "blocked_external_requests": [],
    }
    if not html_file.is_file():
        report["error"] = "inlined HTML file is missing"
    else:
        saved_html_bytes = html_file.read_bytes()
        saved_html_sha256 = hashlib.sha256(saved_html_bytes).hexdigest()
        report["html_sha256"] = saved_html_sha256
        notes_path = run_dir / "run_notes.json"
        source_url = ""
        if notes_path.is_file():
            try:
                source_url = str(json.loads(notes_path.read_text(encoding="utf-8")).get("source_url", ""))
            except (OSError, json.JSONDecodeError):
                source_url = ""
        temporary_dir = tempfile.TemporaryDirectory(prefix="website-poc-screenshot-")
        embedded_file = Path(temporary_dir.name) / "candidate-embedded-images.html"
        image_manifest = build_embedded_screenshot_html(
            saved_html_bytes, source_url, embedded_file,
            asset_manifest_path=args.image_assets_manifest,
        )
        image_url_to_uri = image_manifest.pop("_url_to_data_uri", {})
        report["image_gate"] = {
            "status": "blocked" if image_manifest["status"] != "pass" else "pending_browser_decode",
            "reason": "one or more image references could not be verified and embedded" if image_manifest["status"] != "pass" else "image bytes verified and embedded; browser decoding is pending",
            "asset_source": image_manifest["asset_source"],
            "runtime_network_retrieval": image_manifest["runtime_network_retrieval"],
            "bundle_capture_network_status": image_manifest["bundle_capture_network_status"],
            "reference_count": image_manifest["reference_count"],
            "embedded_count": image_manifest["embedded_count"],
            "failed_urls": image_manifest["failed_urls"],
            "images": image_manifest["images"],
            "viewports": {},
            "temporary_html_sha256": "",
            "temporary_only": True,
        }
        manifest_path = debug_dir / "image_embed_manifest.json"
        manifest_path.write_text(json.dumps(image_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        render_html_bytes = embedded_file.read_bytes() if image_manifest["status"] == "pass" else saved_html_bytes
        report["screenshot_candidate"] = "embedded_image_temporary_copy" if image_manifest["status"] == "pass" else "production_html_diagnostic_only"
        report["image_gate"]["temporary_html_sha256"] = hashlib.sha256(render_html_bytes).hexdigest() if image_manifest["status"] == "pass" else ""
        with sync_playwright() as playwright:
            browser = None
            try:
                launch_options, runtime = _browser_launch_options(playwright.chromium)
                browser = playwright.chromium.launch(**launch_options)
                runtime["version"] = browser.version
                report["browser_runtime"] = runtime
            except Exception as error:
                report["status"] = "blocked"
                report["error"] = f"Chromium launch unavailable: {error}"
            try:
                for name, (width, height) in viewports.items():
                    if browser is None:
                        report["viewports"][name] = {
                            "width": width,
                            "height": height,
                            "error": report.get("error", "Chromium is unavailable."),
                            "all_required_sections_visible": False,
                            "hero_spans_viewport": False,
                            "hero_media_covers_hero": False,
                            "hero_image_loaded": False,
                            "no_horizontal_overflow": False,
                            "images_loaded": False,
                            "fonts_loaded": False,
                        }
                        continue
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page_errors: list[dict] = []
                    page.on("requestfailed", lambda request, dest=page_errors: _resource_event(request, dest))
                    page.on("response", lambda response, dest=page_errors: _resource_event(response, dest))
                    if args.offline_no_network:
                        def abort_external(route):
                            if urlsplit(route.request.url).scheme in {"http", "https"}:
                                report["blocked_external_requests"].append(route.request.url)
                                route.abort()
                            else:
                                route.continue_()
                        page.route("**/*", abort_external)
                    try:
                        parsed_source_url = urlsplit(source_url)
                        source_html = render_html_bytes.decode("utf-8")
                        if parsed_source_url.scheme in {"http", "https"} and parsed_source_url.hostname:
                            base_tag_injected = False
                            if not re.search(r"<base\b", source_html, flags=re.IGNORECASE):
                                base_tag = f'<base href="{html_module.escape(source_url, quote=True)}">'
                                if re.search(r"<head\b[^>]*>", source_html, flags=re.IGNORECASE):
                                    source_html = re.sub(r"(<head\b[^>]*>)", rf"\1{base_tag}", source_html, count=1, flags=re.IGNORECASE)
                                else:
                                    source_html = f"<head>{base_tag}</head>" + source_html
                                base_tag_injected = True
                            page.set_content(source_html, wait_until="domcontentloaded", timeout=45000)
                            render_transport = "page.set_content_embedded_image_copy" if image_manifest["status"] == "pass" else "page.set_content_source_url_diagnostic_only"
                        else:
                            # Avoid file:// navigation: restricted runtimes may block it.
                            base_tag_injected = False
                            page.set_content(source_html, wait_until="domcontentloaded", timeout=45000)
                            render_transport = "page.set_content_embedded_image_copy" if image_manifest["status"] == "pass" else "page.set_content_exact_saved_html_diagnostic_only"
                        report["rendered_html_sha256"] = hashlib.sha256(source_html.encode("utf-8")).hexdigest()
                        report["exact_candidate_bytes_loaded"] = report["rendered_html_sha256"] == saved_html_sha256
                        report["candidate_source_sha256_verified"] = image_manifest["source_html_sha256"] == saved_html_sha256
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
                            pending_images: images.filter(image => !image.complete).map(image => image.currentSrc || image.src),
                            image_dimensions: images.map(image => ({src: image.currentSrc || image.src || '', loaded: image.complete && image.naturalWidth > 0, natural_width: image.naturalWidth, natural_height: image.naturalHeight})),
                            font_status: document.fonts.status,
                            loaded_faces: Array.from(document.fonts).filter(face => face.status === 'loaded').length,
                            failed_faces: Array.from(document.fonts).filter(face => face.status === 'error').length
                          };
                        }""")
                        embedded_data_uris = list(dict.fromkeys(re.findall(r"data:image/[\w.+-]+;base64,[A-Za-z0-9+/=]+", source_html, re.IGNORECASE)))
                        embedded_decode = page.evaluate(r"""async uris => {
                          const decode = uri => new Promise(resolve => {
                            const image = new Image();
                            const timer = setTimeout(() => resolve({loaded: false, natural_width: 0, natural_height: 0}), 10000);
                            image.onload = () => { clearTimeout(timer); resolve({loaded: image.naturalWidth > 0 && image.naturalHeight > 0, natural_width: image.naturalWidth, natural_height: image.naturalHeight}); };
                            image.onerror = () => { clearTimeout(timer); resolve({loaded: false, natural_width: 0, natural_height: 0}); };
                            image.src = uri;
                          });
                          return await Promise.all(uris.map(decode));
                        }""", embedded_data_uris)
                        decode_by_uri = {uri: embedded_decode[index] for index, uri in enumerate(embedded_data_uris)}
                        for image_record in report["image_gate"]["images"]:
                            uri = image_url_to_uri.get(image_record["url"])
                            decoded = decode_by_uri.get(uri, {})
                            image_record["width"] = decoded.get("natural_width")
                            image_record["height"] = decoded.get("natural_height")
                            image_record["browser_decoded"] = bool(decoded.get("loaded"))
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
                            "render_transport": render_transport,
                            "base_tag_injected": base_tag_injected,
                            "sections": sections,
                            "all_required_sections_visible": required_present,
                            "hero": visual["hero"],
                            "header_navigation": visual["header_navigation"],
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
                            "contact_email_ctas_grouped": (
                                visual["contact_email_ctas"]["ungrouped_count"] == 0
                                and visual["contact_email_ctas"]["misplaced_count"] == 0
                            ),
                            "contact_channel_ctas": visual["contact_channel_ctas"],
                            "contact_channel_ctas_aligned": bool(visual["contact_channel_ctas"]["aligned"]),
                            "contact_cta_contrast": visual["contact_cta_contrast"],
                            "contact_ctas_readable": bool(visual["contact_cta_contrast"]["pass"]),
                            "primary_cta_contrast": visual["primary_cta_contrast"],
                            "image_card_labels": visual["image_card_labels"],
                            "image_card_labels_readable": bool(visual["image_card_labels"]["pass"]),
                            "hero_cta_contrast": visual["hero_cta_contrast"],
                            "hero_ctas_readable": bool(visual["hero_cta_contrast"]["pass"]),
                            "primary_ctas_readable": bool(visual["primary_cta_contrast"]["pass"]),
                            "images": resource_state,
                            "embedded_image_decodes": embedded_decode,
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
                        viewport_images_pass = bool(
                            image_manifest["status"] == "pass"
                            and all(item.get("loaded") and item.get("natural_width", 0) > 0 and item.get("natural_height", 0) > 0 for item in embedded_decode)
                            and not resource_state["failed_images"] and not resource_state["pending_images"]
                            and resource_state["loaded_images"] == resource_state["image_count"]
                            and not visual["visible_content_images"]["failures"]
                            and visual["visible_content_images"]["distinct_count"] >= 1
                        )
                        report["image_gate"]["viewports"][name] = {
                            "status": "pass" if viewport_images_pass else "blocked",
                            "required_embedded_asset_count": len(embedded_data_uris),
                            "decoded_asset_count": sum(1 for item in embedded_decode if item.get("loaded")),
                            "failed_embedded_asset_indexes": [index for index, item in enumerate(embedded_decode) if not item.get("loaded")],
                            "failed_img_urls": resource_state["failed_images"],
                            "pending_img_urls": resource_state["pending_images"],
                            "visible_content_image_failures": visual["visible_content_images"]["failures"],
                            "visible_content_image_count": visual["visible_content_images"]["distinct_count"],
                        }
                        report["viewports"][name]["screenshot_usage"] = (
                            "visual_qa_evidence" if viewport_images_pass else "layout_diagnostic_only"
                        )
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
                            "header_navigation": {"nav_count": 0, "visible_nav_count": 0, "links_within_limit": False, "controlled_menu_hidden": False, "navs": []},
                            "hero_media_covers_hero": False,
                            "hero_image_loaded": False,
                            "cta_visible_first_screen": False,
                            "no_horizontal_overflow": False,
                            "critical_content_clipping": {"pass": False, "issues": []},
                            "no_critical_content_clipping": False,
                            "contact_email_ctas": {"count": 0, "ungrouped_count": 0, "misplaced_count": 0},
                            "contact_email_ctas_grouped": False,
                            "contact_channel_ctas": {"count": 0, "aligned": False, "labels": []},
                            "contact_channel_ctas_aligned": False,
                            "contact_cta_contrast": {"pass": False, "issues": []},
                            "contact_ctas_readable": False,
                            "image_card_labels": {"count": 0, "pass": False, "issues": []},
                            "image_card_labels_readable": False,
                            "hero_cta_contrast": {"pass": False, "issues": []},
                            "hero_ctas_readable": False,
                            "primary_ctas_readable": False,
                            "images_loaded": False,
                            "visible_content_images": {"distinct_count": 0, "loaded_count": 0, "failures": []},
                            "screenshot_usage": "layout_diagnostic_only",
                            "cta_arrows_absent": False,
                            "fonts_loaded": False,
                            "screenshot": f"screenshots/{name}.png",
                        }
                    finally:
                        page.close()
            finally:
                if browser is not None:
                    browser.close()

        desktop = report["viewports"].get("desktop", {})
        mobile = report["viewports"].get("mobile", {})
        mobile_menu = report["mobile_menu"]
        _enforce_story_full_bleed_hero(template_profile, report)
        report["checks"] = {
            "desktop_navigation_has_single_visible_menu": bool(
                desktop.get("header_navigation", {}).get("visible_nav_count") == 1
                and desktop.get("header_navigation", {}).get("controlled_menu_hidden")
            ),
            "header_navigation_link_limit": bool(
                desktop.get("header_navigation", {}).get("links_within_limit")
                and mobile.get("header_navigation", {}).get("links_within_limit")
                and mobile_menu.get("link_limit_pass")
            ),
            "mobile_navigation_hidden_until_opened": bool(mobile_menu.get("hidden_until_open")),
            "mobile_navigation_is_only_visible_menu_when_open": bool(mobile_menu.get("only_one_nav_visible_when_open")),
            "rendered_sections_visible_desktop_and_mobile": bool(desktop.get("all_required_sections_visible") and mobile.get("all_required_sections_visible")),
            "hero_spans_viewport_desktop_and_mobile": bool(desktop.get("hero_spans_viewport") and mobile.get("hero_spans_viewport")),
            "hero_media_covers_hero_desktop_and_mobile": bool(desktop.get("hero_media_covers_hero") and mobile.get("hero_media_covers_hero")),
            "hero_image_loads_desktop_and_mobile": bool(desktop.get("hero_image_loaded") and mobile.get("hero_image_loaded")),
            "image_tile_overlays_do_not_hide_photos": bool(
                not desktop.get("opaque_image_tile_overlays") and not mobile.get("opaque_image_tile_overlays")
            ),
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
            "contact_channel_ctas_aligned": bool(
                desktop.get("contact_channel_ctas_aligned") and mobile.get("contact_channel_ctas_aligned")
            ),
            "contact_ctas_readable_desktop_and_mobile": bool(
                desktop.get("contact_ctas_readable") and mobile.get("contact_ctas_readable")
            ),
            "image_card_labels_readable_desktop_and_mobile": bool(
                desktop.get("image_card_labels_readable") and mobile.get("image_card_labels_readable")
            ),
            "hero_ctas_readable_desktop_and_mobile": bool(
                desktop.get("hero_ctas_readable") and mobile.get("hero_ctas_readable")
            ),
            "primary_ctas_readable_desktop_and_mobile": bool(
                desktop.get("primary_ctas_readable") and mobile.get("primary_ctas_readable")
            ),
            "fonts_load_in_browser": bool(desktop.get("fonts_loaded") and mobile.get("fonts_loaded")),
            "images_load_in_browser": bool(desktop.get("images_loaded") and mobile.get("images_loaded")),
            "template_layout_signature_matches": bool(report["template_layout"].get("pass")),
        }
        image_viewports_pass = len(report["image_gate"]["viewports"]) == 2 and all(
            item.get("status") == "pass" for item in report["image_gate"]["viewports"].values()
        )
        report["image_gate"]["status"] = "pass" if image_manifest["status"] == "pass" and image_viewports_pass else "blocked"
        report["image_gate"]["reason"] = "all referenced image bytes were verified from the selected source, embedded, and decoded in Chromium at both viewports" if report["image_gate"]["status"] == "pass" else "image bytes, embedding, browser decoding, or viewport image loading did not pass"
        report["screenshots_visual_qa_eligible"] = report["image_gate"]["status"] == "pass"
        manifest_path.write_text(json.dumps({
            "status": image_manifest["status"],
            "source_html_sha256": image_manifest["source_html_sha256"],
            "reference_count": image_manifest["reference_count"],
            "embedded_count": image_manifest["embedded_count"],
            "failed_urls": image_manifest["failed_urls"],
            "images": report["image_gate"]["images"],
            "asset_source": image_manifest["asset_source"],
            "runtime_network_retrieval": image_manifest["runtime_network_retrieval"],
            "bundle_capture_network_status": image_manifest["bundle_capture_network_status"],
            "temporary_only": True,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if report.get("status") != "blocked":
            source_verified = report.get("candidate_source_sha256_verified") is True
            report["status"] = "pass" if all(report["checks"].values()) and source_verified and report["image_gate"]["status"] == "pass" else ("blocked" if report["image_gate"]["status"] != "pass" else "fail")
        temporary_dir.cleanup()

    output = debug_dir / "browser_qa.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if emit:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0




def _run_chatgpt_candidates_sync(candidates, request, output_dir, source_url="", image_assets_manifest=None):
    """Run all three exact candidate strings in this Python session.

    candidates: [{"candidate_id": "forty|landed|story", "html": str | bytes}]
    Returns paths to the saved production HTML and candidate-specific evidence.
    """
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError("Use a new, empty output directory so evidence cannot be mixed across runs.")
    required = {"forty", "landed", "story"}
    if (not isinstance(candidates, list) or len(candidates) != 3
            or {item.get("candidate_id") for item in candidates if isinstance(item, dict)} != required):
        raise ValueError("Provide exactly one candidate each for forty, landed, and story.")
    summary = {"status": "pass", "runner": "browser_qa_standalone.py", "candidates": {}}
    with tempfile.TemporaryDirectory(prefix="website-poc-chatgpt-run-") as staging:
        for item in candidates:
            candidate_id = item["candidate_id"]
            candidate_html = item.get("html")
            if not isinstance(candidate_html, (str, bytes)) or not candidate_html.strip():
                raise ValueError(f"Candidate {candidate_id} has no HTML string.")
            html_bytes = candidate_html if isinstance(candidate_html, bytes) else candidate_html.encode("utf-8")
            try:
                html_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"Candidate {candidate_id} is not UTF-8 HTML: {error}") from error
            final_html = output_root / f"candidate-{candidate_id}.html"
            final_html.write_bytes(html_bytes)
            run_dir = Path(staging) / candidate_id
            inlined = run_dir / "files" / "inlined"
            debug = run_dir / "debug"
            inlined.mkdir(parents=True)
            debug.mkdir(parents=True)
            (inlined / "index.html").write_bytes(html_bytes)
            (run_dir / "run_notes.json").write_text(json.dumps({"source_url": source_url}), encoding="utf-8")
            (debug / "design_reference.json").write_text(json.dumps({
                "status": "selected", "design_reference": {"template_url": QA_TEMPLATE_URLS[candidate_id]}
            }), encoding="utf-8")
            evidence_dir = output_root / "evidence" / candidate_id
            (debug / "screenshots").mkdir(parents=True, exist_ok=True)
            qa_args = [str(run_dir), request, "--offline-no-network"]
            if image_assets_manifest is not None:
                qa_args.extend(["--image-assets-manifest", str(image_assets_manifest)])
            main(qa_args, emit=False)
            report_path = debug / "browser_qa.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            evidence_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(report_path, evidence_dir / "browser_qa.json")
            manifest_path = debug / "image_embed_manifest.json"
            if manifest_path.exists():
                shutil.copy2(manifest_path, evidence_dir / "image_embed_manifest.json")
            screenshot_dest = evidence_dir / "screenshots"
            if (debug / "screenshots").exists():
                shutil.copytree(debug / "screenshots", screenshot_dest, dirs_exist_ok=True)
            candidate_record = {
                "status": report.get("status", "blocked"),
                "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
                "html_path": str(final_html),
                "report_path": str(evidence_dir / "browser_qa.json"),
                "screenshots": [str(path) for path in sorted(screenshot_dest.glob("*.png"))],
                "image_gate": report.get("image_gate", {}),
                "checks": report.get("checks", {}),
            }
            summary["candidates"][candidate_id] = candidate_record
            if candidate_record["status"] != "pass":
                summary["status"] = "blocked" if candidate_record["status"] == "blocked" else "fail"
    summary_path = output_root / "browser_qa_summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
    return summary

def run_chatgpt_candidates(candidates, request, output_dir, source_url="", image_assets_manifest=None):
    """Notebook-safe entry point; isolates synchronous Playwright in a worker thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_chatgpt_candidates_sync(candidates, request, output_dir, source_url, image_assets_manifest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            _run_chatgpt_candidates_sync, candidates, request, output_dir, source_url, image_assets_manifest
        ).result()


if __name__ == "__main__":
    raise SystemExit(main())
