"""Fetch same-site pages and extract validated source photo URLs."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

try:
    from .site_quality import _image_loads_ok
except ImportError:  # pragma: no cover - direct script execution path
    from site_quality import _image_loads_ok


PAGE_LIMIT = 8
BYTE_LIMIT = 1_500_000
IMAGE_LIMIT = 6
PAGE_KEYWORDS = re.compile(
    r"about|service|product|solution|work|portfolio|contact|location|team|process|faq|support|hours|booking",
    re.IGNORECASE,
)
IMAGE_CDN_SUFFIXES = (
    "wixstatic.com", "squarespace-cdn.com", "shopifycdn.net", "website-files.com",
    "cloudinary.com", "imgix.net", "ctfassets.net", "wsimg.com",
)
NON_PHOTO_HINTS = re.compile(
    r"logo|icon|favicon|social|facebook|instagram|twitter|linkedin|youtube|tiktok|pinterest|whatsapp|pixel|spacer|blank",
    re.IGNORECASE,
)


def _assert_public_http_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Source URLs must be public HTTP(S) URLs without embedded credentials.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local hostnames are not valid source websites.")
    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except OSError as error:
        raise ValueError(f"Could not resolve source host {host}.") from error
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Source hosts must resolve only to public IP addresses.")
    return parsed


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _srcset_urls(value: str) -> list[str]:
    """Parse candidate URLs without splitting commas inside CDN transform paths."""
    pattern = re.compile(
        r"(?:^|,\s+)(\S+?)(?:\s+\d+(?:\.\d+)?[wx])?(?=\s*,\s+|\s*$)",
        re.IGNORECASE,
    )
    return [html.unescape(match.group(1).rstrip(",")) for match in pattern.finditer(value or "")]


def _css_urls(value: str) -> list[str]:
    return [
        html.unescape(match.group(2).strip(" \"'"))
        for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", value or "", re.IGNORECASE)
        if match.group(2).strip()
    ]


class _SourcePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self._title = False
        self._heading: tuple[str, list[str]] | None = None
        self._anchor: dict[str, str] | None = None

    def _record(self, raw_url: str, attrs: dict[str, str], method: str) -> None:
        value = html.unescape((raw_url or "").strip())
        if not value:
            return
        self.images.append({
            "url": value,
            "alt": attrs.get("alt", ""),
            "title": attrs.get("title", ""),
            "method": method,
        })

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag == "title":
            self._title = True
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = (tag, [])
        if tag == "a":
            self._anchor = {"href": values.get("href", ""), "text": values.get("aria-label", "")}
        if tag == "img":
            for name in ("src", "data-src", "data-lazy-src", "data-original", "data-image", "data-image-url", "data-original-src"):
                self._record(values.get(name, ""), values, name)
            for name in ("srcset", "data-srcset", "data-lazy-srcset", "data-original-srcset"):
                for image_url in _srcset_urls(values.get(name, "")):
                    self._record(image_url, values, name)
        if tag == "source" and (
            values.get("type", "").lower().startswith("image/")
            or any(values.get(name) for name in ("srcset", "data-srcset", "data-lazy-srcset"))
        ):
            for name in ("src", "data-src", "srcset", "data-srcset", "data-lazy-srcset"):
                urls = _srcset_urls(values.get(name, "")) if "srcset" in name else [values.get(name, "")]
                for image_url in urls:
                    self._record(image_url, values, name)
        if tag == "video" and values.get("poster"):
            self._record(values["poster"], values, "video_poster")
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
                self._record(values.get("content", ""), values, key)
        for image_url in _css_urls(values.get("style", "")):
            self._record(image_url, values, "inline_background")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._title = False
        if self._heading and tag == self._heading[0]:
            self.heading_parts.append(" ".join(self._heading[1]))
            self._heading = None
        if tag == "a" and self._anchor is not None:
            self.links.append({**self._anchor, "text": " ".join(self._anchor["text"].split())})
            self._anchor = None

    def handle_data(self, data: str) -> None:
        clean = " ".join((data or "").split())
        if not clean:
            return
        if self._title:
            self.title_parts.append(clean)
        if self._heading:
            self._heading[1].append(clean)
        if self._anchor is not None and not self._anchor["text"]:
            self._anchor["text"] = clean


def _fetch_page(url: str) -> tuple[str, _SourcePageParser]:
    _assert_public_http_url(url)
    opener = urllib.request.build_opener(_PublicRedirects())
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Git-Content-DuckAI-SourceImages/1.0", "Accept": "text/html"},
    )
    with opener.open(request, timeout=15) as response:
        final_url = response.geturl()
        _assert_public_http_url(final_url)
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text/plain" not in content_type:
            raise ValueError("Source response was not an HTML page.")
        body = response.read(BYTE_LIMIT + 1)[:BYTE_LIMIT]
    parser = _SourcePageParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return final_url, parser


def _allowed_image_host(url: str, source_domain: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    return bool(host) and (
        host == source_domain
        or host.endswith("." + source_domain)
        or any(host == suffix or host.endswith("." + suffix) for suffix in IMAGE_CDN_SUFFIXES)
    )


def _asset_identity(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = urllib.parse.unquote(parsed.path)
    if host == "static.wixstatic.com" and "/media/" in path:
        wix_asset = path.split("/media/", 1)[1].split("/", 1)[0]
        if wix_asset:
            return host, wix_asset
    return parsed.netloc.lower(), path


def collect_source_images(source_url: str) -> dict:
    """Inspect a bounded set of same-domain pages and return direct, validated image assets."""
    requested = _assert_public_http_url(source_url)
    source_domain = (requested.hostname or "").lower().removeprefix("www.")
    queue = [source_url]
    seen_pages: set[str] = set()
    pages: list[tuple[str, _SourcePageParser]] = []
    errors: list[dict[str, str]] = []
    while queue and len(pages) < PAGE_LIMIT:
        current = queue.pop(0)
        normalized = urllib.parse.urldefrag(current)[0]
        if normalized in seen_pages:
            continue
        seen_pages.add(normalized)
        try:
            final_url, parser = _fetch_page(current)
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower().removeprefix("www.")
            if final_host != source_domain:
                raise ValueError("A source page redirected outside the requested domain.")
            pages.append((final_url, parser))
            if len(pages) == 1:
                for link in parser.links:
                    candidate = urllib.parse.urljoin(final_url, link.get("href", ""))
                    parsed = urllib.parse.urlsplit(candidate)
                    host = (parsed.hostname or "").lower().removeprefix("www.")
                    if host == source_domain and PAGE_KEYWORDS.search(link.get("text", "") + " " + parsed.path):
                        if urllib.parse.urldefrag(candidate)[0] not in seen_pages:
                            queue.append(candidate)
        except Exception as error:
            errors.append({"url": current[:500], "error": str(error)[:240]})

    if not pages:
        return {"requested_url": source_url, "source_domain": source_domain, "pages_scanned": [], "source_assets": [], "errors": errors}

    candidates: dict[tuple[str, str], dict] = {}
    priority = {"srcset": 0, "data-srcset": 0, "data-lazy-srcset": 0, "data-original-srcset": 0,
                "data-src": 1, "data-lazy-src": 1, "data-original": 1, "data-image": 1,
                "og:image": 2, "og:image:url": 2, "twitter:image": 2,
                "inline_background": 3, "src": 4, "video_poster": 4}
    for page_url, parser in pages:
        for image in parser.images:
            url = urllib.parse.urljoin(page_url, image.get("url", ""))
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not _allowed_image_host(url, source_domain):
                continue
            hint = " ".join((image.get("alt", ""), image.get("title", ""), parsed.path))
            if NON_PHOTO_HINTS.search(hint):
                continue
            key = _asset_identity(url)
            description = " ".join((image.get("alt") or image.get("title") or "unknown").split())
            if re.fullmatch(r"[\w.-]+\.(?:jpe?g|png|webp|gif|avif)", description, re.IGNORECASE):
                description = "unknown"
            record = {
                "type": "photo",
                "url": url,
                "visible_subject": description[:120],
                "where_it_appears": page_url,
                "discovery_method": image.get("method", "src"),
                "source_provenance": "embedded_on_requested_site",
            }
            image_width_match = re.search(r"(?:^|/)w_(\d+)(?:,|/|$)", parsed.path)
            candidate = {
                **record,
                "_priority": priority.get(image.get("method", "src"), 5),
                "_width": int(image_width_match.group(1)) if image_width_match else 0,
            }
            current = candidates.get(key)
            if current is None or (candidate["_priority"], -candidate["_width"]) < (
                current["_priority"], -current["_width"]
            ):
                candidates[key] = candidate

    ordered = sorted(candidates.values(), key=lambda item: item["_priority"])[:24]
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(ordered)))) as pool:
        valid = list(pool.map(lambda item: _image_loads_ok(item["url"]), ordered))
    assets = []
    for record, is_image in zip(ordered, valid):
        if not is_image:
            continue
        record.pop("_priority", None)
        record.pop("_width", None)
        assets.append(record)
        if len(assets) >= IMAGE_LIMIT:
            break
    return {
        "requested_url": source_url,
        "source_domain": source_domain,
        "pages_scanned": [url for url, _ in pages],
        "source_assets": assets,
        "errors": errors,
    }
