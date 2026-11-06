"""Fetch a bounded set of same-domain source pages and extract redesign facts."""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


PAGE_LIMIT = 8
BYTE_LIMIT = 1_500_000
KEYWORDS = re.compile(r"about|service|product|solution|work|portfolio|contact|location|team|process|faq|support|hours|booking", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _urls_from_srcset(value: str) -> list[str]:
    candidates = []
    for part in (value or "").split(","):
        match = re.match(r"\s*(\S+)(?:\s+(\d+(?:\.\d+)?)(w|x))?", part)
        if match:
            weight = float(match.group(2) or 0)
            candidates.append((weight, match.group(1)))
    return [url for _, url in sorted(candidates, reverse=True)]


def _urls_from_css(value: str) -> list[str]:
    return [html.unescape(match.group(2).strip(" \\\"'")) for match in re.finditer(
        r"url\(\s*(['\"]?)(.*?)\1\s*\)", value or "", re.IGNORECASE
    ) if match.group(2).strip()]


def _assert_public_http_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"Not an allowed public HTTP(S) URL: {url}")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local hostnames are not valid CSV source websites.")
    try:
        resolved = {ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except OSError as error:
        raise ValueError(f"Could not resolve source host {host}: {error}") from error
    if not resolved or any(not address.is_global for address in resolved):
        raise ValueError(f"Source host must resolve only to public IP addresses: {host}")
    return parsed


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.headings: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.image_meta: list[dict[str, str]] = []
        self.background_images: list[dict[str, str]] = []
        self.forms: list[dict] = []
        self.stylesheets: list[str] = []
        self.labels: dict[str, str] = {}
        self._skip = 0
        self._title = False
        self._heading: tuple[str, list[str]] | None = None
        self._anchor: dict[str, str] | None = None
        self._label_for: str | None = None
        self._form: dict | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._title = True
        if re.fullmatch(r"h[1-6]", tag):
            self._heading = (tag, [])
        if tag == "a":
            self._anchor = {"href": values.get("href", ""), "text": values.get("aria-label", "")}
        if tag == "link" and "stylesheet" in values.get("rel", "").lower().split():
            if values.get("href"):
                self.stylesheets.append(values["href"])
        if tag == "img":
            candidates = []
            for name in ("src", "data-src", "data-lazy-src", "data-original", "data-image", "data-image-url"):
                if values.get(name):
                    candidates.append((values[name], name))
            for name in ("srcset", "data-srcset", "data-lazy-srcset"):
                for src in _urls_from_srcset(values.get(name, "")):
                    candidates.append((src, name))
            seen = set()
            for src, discovery in candidates:
                src = src.strip()
                if src and src not in seen:
                    seen.add(src)
                    self.images.append({
                        "src": src,
                        "alt": values.get("alt", ""),
                        "title": values.get("title", ""),
                        "width": values.get("width", ""),
                        "height": values.get("height", ""),
                        "discovery_method": discovery,
                    })
        if tag == "source" and (values.get("type", "").startswith("image/") or values.get("srcset") or values.get("data-srcset")):
            for name in ("src", "data-src"):
                if values.get(name):
                    self.images.append({"src": values[name], "alt": "", "discovery_method": name})
            for name in ("srcset", "data-srcset"):
                for src in _urls_from_srcset(values.get(name, "")):
                    self.images.append({"src": src, "alt": "", "discovery_method": name})
        if tag == "video" and values.get("poster"):
            self.images.append({"src": values["poster"], "alt": values.get("aria-label", ""), "discovery_method": "video_poster"})
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"} and values.get("content"):
                self.image_meta.append({"src": values["content"], "alt": values.get("alt", ""), "discovery_method": key})
        for image_url in _urls_from_css(values.get("style", "")):
            self.background_images.append({"src": image_url, "alt": values.get("aria-label", ""), "discovery_method": "inline_background"})
        if tag == "form":
            self._form = {"action": values.get("action", ""), "method": values.get("method", "get").lower(), "fields": []}
            self.forms.append(self._form)
        if tag == "label":
            self._label_for = values.get("for")
        if self._form is not None and tag in {"input", "select", "textarea"}:
            field_type = values.get("type", "text").lower() if tag == "input" else tag
            if field_type not in {"hidden", "submit", "image", "reset"}:
                self._form["fields"].append({
                    "tag": tag,
                    "type": field_type,
                    "name": values.get("name", ""),
                    "id": values.get("id", ""),
                    "label": values.get("aria-label", ""),
                    "placeholder": values.get("placeholder", ""),
                    "required": "required" in values,
                })

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._title = False
        if self._heading and tag == self._heading[0]:
            self.headings.append({"tag": self._heading[0], "text": _clean(" ".join(self._heading[1]))})
            self._heading = None
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = _clean(self._anchor["text"])
            if self._anchor["href"]:
                self.links.append(self._anchor)
            self._anchor = None
        if tag == "label":
            self._label_for = None
        if tag == "form":
            self._form = None

    def handle_data(self, data: str) -> None:
        value = _clean(data)
        if not value:
            return
        if self._title:
            self.title_parts.append(value)
        if self._heading:
            self._heading[1].append(value)
        if self._anchor is not None and not self._anchor["text"]:
            self._anchor["text"] = value
        if self._label_for:
            self.labels[self._label_for] = _clean(self.labels.get(self._label_for, "") + " " + value)
        if not self._skip:
            self.text_parts.append(value)

    def result(self) -> dict:
        for form in self.forms:
            for field in form["fields"]:
                field["label"] = field["label"] or self.labels.get(field["id"], "")
        return {
            "title": _clean(" ".join(self.title_parts)),
            "headings": self.headings,
            "text": _clean(" ".join(self.text_parts))[:16000],
            "links": self.links,
            "images": self.images + self.image_meta + self.background_images,
            "forms": self.forms,
            "stylesheets": self.stylesheets,
        }


def _fetch_page(url: str) -> tuple[str, _PageParser]:
    _assert_public_http_url(url)
    opener = urllib.request.build_opener(_PublicRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "ChatGPT-Website-SourceFacts/1.0", "Accept": "text/html"})
    with opener.open(request, timeout=15) as response:
        final_url = response.geturl()
        _assert_public_http_url(final_url)
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text/plain" not in content_type:
            raise ValueError(f"Source page is not HTML: {final_url} ({content_type})")
        body = response.read(BYTE_LIMIT + 1)
    if len(body) > BYTE_LIMIT:
        body = body[:BYTE_LIMIT]
    parser = _PageParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return final_url, parser


def collect_source_facts(source_url: str, *, business: str = "", category: str = "", location: str = "") -> dict:
    requested = _assert_public_http_url(source_url)
    base_host = (requested.hostname or "").lower().removeprefix("www.")
    queue = [source_url]
    seen: set[str] = set()
    pages = []
    errors = []
    while queue and len(pages) < PAGE_LIMIT:
        current = queue.pop(0)
        normalized = urllib.parse.urldefrag(current)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            final_url, parser = _fetch_page(current)
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower().removeprefix("www.")
            if final_host != base_host:
                raise ValueError(f"Source page redirected outside the requested domain: {final_url}")
            page = parser.result()
            page["url"] = final_url
            pages.append(page)
            if len(pages) == 1:
                for link in page["links"]:
                    candidate = urllib.parse.urljoin(final_url, link["href"])
                    parsed = urllib.parse.urlsplit(candidate)
                    host = (parsed.hostname or "").lower().removeprefix("www.")
                    if host == base_host and KEYWORDS.search(link["text"] + " " + parsed.path):
                        if urllib.parse.urldefrag(candidate)[0] not in seen:
                            queue.append(candidate)
        except Exception as error:
            errors.append({"url": current, "error": str(error)[:500]})
    if not pages:
        raise RuntimeError(f"Could not retrieve the target website. Source-fetch errors: {errors}")
    all_images = []
    for page in pages:
        for image in page["images"]:
            url = urllib.parse.urljoin(page["url"], image.get("src", ""))
            if urllib.parse.urlsplit(url).scheme in {"http", "https"}:
                all_images.append({
                    "url": url,
                    "alt": image.get("alt", ""),
                    "title": image.get("title", ""),
                    "width": image.get("width", ""),
                    "height": image.get("height", ""),
                    "discovery_method": image.get("discovery_method", "img_src"),
                    "source_page": page["url"],
                    "source_provenance": "embedded_on_requested_site",
                })
    return {
        "requested_url": source_url,
        "business_metadata_unverified": {"business": business, "category": category, "location": location},
        "source_domain": base_host,
        "pages_reviewed": [{key: page[key] for key in ("url", "title", "headings", "text", "forms")} for page in pages],
        "source_assets": all_images[:120],
        "navigation_links": [{"page": page["url"], **link} for page in pages for link in page["links"][:100]],
        "source_fetch_errors": errors,
        "facts_are_observations_not_independently_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--business", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    facts = collect_source_facts(args.source_url, business=args.business, category=args.category, location=args.location)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Fetched {len(facts['pages_reviewed'])} source page(s) for {args.source_url}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
