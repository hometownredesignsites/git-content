"""Build a disposable HTML copy with verified image URLs embedded as data URIs."""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from html.parser import HTMLParser
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

try:
    from .site_quality import _looks_like_image
    from .prepare_candidate_context import _is_source_image_host_allowed
except ImportError:  # Direct execution from the workflow script directory.
    from site_quality import _looks_like_image
    from prepare_candidate_context import _is_source_image_host_allowed


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
