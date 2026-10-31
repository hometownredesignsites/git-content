#!/usr/bin/env python3
"""Generate one website candidate through a persistent ChatGPT guest chat."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPTS))
from capture_chunk import accept_chunk, expected_parts  # noqa: E402
from assemble_chunks import assemble  # noqa: E402
from playwright_runner.browser_session import assistant_turns, find_chat_composer  # noqa: E402
from playwright_runner.diagnostics import save_failure_diagnostics  # noqa: E402
from playwright_runner.stage_runner import run_stage_once  # noqa: E402
from site_quality import assess_website  # noqa: E402

RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
RUN_DIR = REPO / "chatgpt-runs" / f"website-run-{RUN_ID}-{RUN_ATTEMPT}" / "candidate-1"
NETWORK_EVENTS: list[str] = []


class SourceParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title: list[str] = []
        self.description = ""
        self.text: list[str] = []
        self.images: list[dict] = []
        self.forms: list[dict] = []
        self.links: list[dict] = []
        self._title = False
        self._ignored = 0
        self._form: dict | None = None
        self._label = False
        self._label_text: list[str] = []

    def handle_starttag(self, tag: str, raw_attrs: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in raw_attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag == "title":
            self._title = True
        if tag == "meta" and attrs.get("name", "").lower() in {"description", "og:description"}:
            self.description = attrs.get("content", "")[:500]
        if tag == "img":
            raw = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
            if raw:
                self.images.append({"url": urllib.parse.urljoin(self.base_url, raw), "alt": attrs.get("alt", "")})
        if tag == "source" and attrs.get("srcset"):
            first = attrs["srcset"].split(",", 1)[0].strip().split(" ", 1)[0]
            if first:
                self.images.append({"url": urllib.parse.urljoin(self.base_url, first), "alt": ""})
        if tag == "a" and attrs.get("href"):
            href = urllib.parse.urljoin(self.base_url, attrs["href"])
            if urllib.parse.urlparse(href).hostname == urllib.parse.urlparse(self.base_url).hostname:
                self.links.append({"url": href, "text": attrs.get("aria-label", ""), "href": attrs["href"]})
        if tag == "form":
            self._form = {"action": urllib.parse.urljoin(self.base_url, attrs.get("action", "")),
                          "method": attrs.get("method", "get").lower(), "fields": []}
            self.forms.append(self._form)
        if self._form is not None and tag in {"input", "select", "textarea", "button"}:
            field = {name: attrs.get(name, "") for name in ("type", "name", "id", "placeholder", "aria-label")}
            field["element"] = tag
            self._form["fields"].append(field)
        if tag == "label":
            self._label = True
            self._label_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._title = False
        if tag == "form":
            self._form = None
        if tag == "label":
            self._label = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._title:
            self.title.append(text)
        if not self._ignored:
            self.text.append(text)
        if self._label:
            self._label_text.append(text)


def fetch_html(url: str) -> tuple[str, str] | tuple[None, str]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; GitContentWebsiteAudit/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None, f"Non-HTML response: {content_type or 'unknown content type'}"
            charset = response.headers.get_content_charset() or "utf-8"
            return response.geturl(), response.read(2_000_000).decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"


def audit_source(url: str) -> dict:
    final_url, markup = fetch_html(url)
    if not final_url:
        return {"status": "unavailable", "error": markup, "pages": [], "images": [], "contact_form": "unknown"}
    parser = SourceParser(final_url)
    parser.feed(markup)
    pages = [{"url": final_url, "title": " ".join(parser.title).strip(),
              "description": parser.description, "text": " ".join(parser.text)[:6000]}]
    images = parser.images[:20]
    forms = list(parser.forms)
    domain = urllib.parse.urlparse(final_url).hostname
    contact_links = [link["url"] for link in parser.links
                     if re.search(r"contact|appointment|booking|estimate|quote", link["url"] + " " + link["text"], re.I)]
    seen = {final_url}
    for contact_url in contact_links[:4]:
        if contact_url in seen:
            continue
        seen.add(contact_url)
        contact_final, contact_markup = fetch_html(contact_url)
        if not contact_final or urllib.parse.urlparse(contact_final).hostname != domain:
            continue
        contact_parser = SourceParser(contact_final)
        contact_parser.feed(contact_markup)
        pages.append({"url": contact_final, "title": " ".join(contact_parser.title).strip(),
                      "description": contact_parser.description, "text": " ".join(contact_parser.text)[:2500]})
        images.extend(contact_parser.images)
        forms.extend(contact_parser.forms)
    unique_images = []
    seen_images = set()
    for image in images:
        image_url = image["url"]
        if image_url.startswith(("http://", "https://")) and image_url not in seen_images:
            seen_images.add(image_url)
            unique_images.append(image)
    return {"status": "fetched", "source_url": final_url, "pages": pages,
            "images": unique_images[:20], "contact_form": "present" if forms else "unknown",
            "contact_forms": forms[:5], "domain": domain}


def load_target() -> dict:
    path = ROOT / "source_urls.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"Pilot expects exactly one CSV row; found {len(rows)} in {path.name}.")
    row = {str(key).strip().lower(): (value or "").strip() for key, value in rows[0].items() if key}
    if not row.get("website") or not row.get("business") or not row.get("category"):
        raise ValueError("CSV must contain website, business, and category fields.")
    parsed = urllib.parse.urlparse(row["website"])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("website must be an absolute http(s) URL.")
    return row


def build_prompt(row: dict, audit: dict) -> str:
    business = row["business"]
    category = row["category"]
    location = row.get("location", "")
    source_url = row["website"]
    source_info = "Source homepage could not be fetched; do not claim to have reviewed it."
    image_lines = "(no source image URLs verified)"
    contact_form = "unknown"
    contact_fields = []
    if audit.get("status") == "fetched":
        source_info = "\n".join(
            f"- Page: {page['url']}\n  Title: {page['title'] or '(none)'}\n  Description: {page['description'] or '(none)'}\n  Visible text: {page['text'] or '(none)'}"
            for page in audit["pages"]
        )
        image_lines = "\n".join(f"- {image['url']} (alt: {image.get('alt') or 'not provided'})" for image in audit["images"]) or "(none found)"
        contact_form = audit.get("contact_form", "unknown")
        contact_fields = audit.get("contact_forms", [])
    location_note = f"CSV location clue (not verified): {location}" if location else "No location clue supplied."
    return f"""Redesign the real business website at {source_url}.

Business: {business}
Industry: {category}
{location_note}

SOURCE AUDIT (directly fetched static homepage plus linked contact/booking pages; source facts are authoritative):
{source_info}

VERIFIED_SOURCE_IMAGE_URLS:
{image_lines}
VERIFIED_SOURCE_CONTACT_FORM: {contact_form}
VERIFIED_SOURCE_CONTACT_FORM_FIELDS: {json.dumps(contact_fields, ensure_ascii=False)}

Use only facts supported by the source pages above. Do not invent services, contact details, hours, awards, reviews,
statistics, or credentials. The source audit is static HTML; do not assume a missing form is absent if the site may
render one with JavaScript. If source photos are listed, use suitable exact source URLs, including one in the hero.
Do not copy source copy or reproduce its layout wholesale. Create a polished responsive redesign with a distinctive,
business-specific art direction, full-bleed image hero, useful service/project sections, contact area, and substantive
semantic footer. Preserve the purpose and fields of a verified source form; do not invent a backend or claim it works.
Use an accessible three-bar mobile hamburger, no arrow glyphs/icons inside CTA buttons, meaningful image alt text,
and only verified claims. Include at least three distinct relevant images when available.

OUTPUT CONTRACT: create separate CSS and HTML files. Provide exactly 4 CSS parts, then exactly 8 HTML parts, one
complete contiguous code block in each response. Use a css fence for CSS. Use a text fence containing raw HTML for
HTML. Include a response heading in the form CSS Part N of 4 or HTML Part N of 8. The first nonblank line in each
code block must be exactly /* CSS PART N OF 4 */ or <!-- HTML PART N OF 8 -->. Keep the HTML compatible with the CSS
and link it to styles.css. Do not repeat earlier code. Keep each CSS part at rule boundaries. HTML Part 1 starts the
complete document (doctype, html, head, metadata, stylesheet link), header/navigation and full hero. Parts 2–7 add
distinct, nonduplicated business sections in a sensible order; HTML Part 8 finishes the footer and closes body and html.
Use the same chat and context for every part. Start with CSS Part 1 of 4 now; after each response, wait for the next
instruction. Do not provide an HTML preview."""


def next_part_prompt(kind: str, part: int) -> str | None:
    sequence = expected_parts()
    index = sequence.index((kind, part))
    if index + 1 >= len(sequence):
        return None
    next_kind, next_part = sequence[index + 1]
    next_total = 4 if next_kind == "css" else 8
    fence = "css" if next_kind == "css" else "text"
    return (f"{kind.upper()} part {part} acknowledged and parsed. Continue with {next_kind.upper()} Part "
            f"{next_part} of {next_total} only. Use exactly one fenced {fence} code block with the matching "
            "in-code marker and response heading. Do not repeat earlier code; preserve compatibility with the chunks.")


def attach_network_diagnostics(page) -> None:
    def on_response(response):
        parsed = urllib.parse.urlparse(response.url)
        if parsed.hostname and parsed.hostname.endswith("chatgpt.com") and response.status >= 400:
            NETWORK_EVENTS.append(f"{response.status} {response.request.method} {parsed.hostname}{parsed.path}"[:500])
    def on_request_failed(request):
        parsed = urllib.parse.urlparse(request.url)
        if parsed.hostname and parsed.hostname.endswith("chatgpt.com"):
            NETWORK_EVENTS.append(f"{request.method} {parsed.hostname}{parsed.path} failed: {request.failure}"[:500])
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)


def gate_state(page) -> str:
    try:
        title = page.title().lower()
        body = page.locator("body").inner_text(timeout=2500).lower()
    except Exception:
        return ""
    terms = ("verify you are human", "verify that you are human", "captcha", "just a moment",
             "checking your browser", "attention required", "cloudflare", "usage limit reached",
             "sign in to continue", "temporarily unavailable")
    return next((term for term in terms if term in title or term in body), "")


def wait_for_guest_composer(page, timeout_seconds: int = 45):
    deadline = time.monotonic() + timeout_seconds
    guest_markers = ("log in to get answers based on saved chats", "sign up for free")
    while time.monotonic() < deadline:
        blocked = gate_state(page)
        if blocked:
            raise RuntimeError(f"ChatGPT guest access is gated ({blocked}); stopping without bypassing the gate.")
        composer = find_chat_composer(page, timeout_ms=1800)
        try:
            body = page.locator("body").inner_text(timeout=1500).lower()
        except Exception:
            body = ""
        if composer and any(marker in body for marker in guest_markers):
            return composer
        page.wait_for_timeout(500)
    raise RuntimeError("ChatGPT's logged-out guest composer was not available before timeout.")


def latest_code_block(page, before_count: int) -> tuple[str, str, object]:
    blocks = page.locator("main pre")
    count = blocks.count()
    delta = count - before_count
    if delta != 1:
        raise ValueError(f"Expected one new rendered code block; found {delta}.")
    block = blocks.nth(count - 1)
    code_node = block.locator("code").first
    if code_node.count():
        code = code_node.inner_text().strip("\r\n")
        language = code_node.get_attribute("class") or ""
        language_match = re.search(r"language-([\w+-]+)", language, re.I)
        language = language_match.group(1) if language_match else language
    else:
        code = block.inner_text().strip("\r\n")
        language = ""
    return code, language, block


def message_has_label(block, label: str, code: str) -> bool:
    try:
        return bool(block.evaluate(
            """(element, args) => {
              const normalize = value => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              for (let node = element; node && node !== document.body && node.tagName !== 'MAIN'; node = node.parentElement) {
                if (node.querySelectorAll('pre').length !== 1) continue;
                const text = (node.innerText || '').replace(args.code, ' ');
                if (normalize(text).includes(normalize(args.label))) return true;
              }
              return false;
            }""", {"label": label, "code": code}))
    except Exception:
        return False


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def run() -> dict:
    row = load_target()
    audit = audit_source(row["website"])
    prompt = build_prompt(row, audit)
    RUN_DIR.mkdir(parents=True, exist_ok=False)
    (RUN_DIR / "debug").mkdir(parents=True, exist_ok=True)
    write_json(RUN_DIR / "debug" / "inputs.json", {"target": row, "source_audit": audit,
               "css_parts": 4, "html_parts": 8})
    (RUN_DIR / "debug" / "website_prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    turn_log = {"chat_url": "", "turns": [], "source_audit": audit}
    run_notes = {"status": "generating", "automated_success": False, "final_success": False,
                 "source_url": row["website"], "business": row["business"], "chunk_count": {"css": 4, "html": 8}}
    write_json(RUN_DIR / "run_notes.json", run_notes)
    chat_url = ""
    try:
        with tempfile.TemporaryDirectory(prefix="chatgpt-website-profile-") as profile_dir:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=False,
                    viewport={"width": 1440, "height": 900},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(15000)
                attach_network_diagnostics(page)
                try:
                    page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60000)
                    wait_for_guest_composer(page)
                    for kind, part in expected_parts():
                        prompt_text = prompt if (kind, part) == ("css", 1) else next_part_prompt(kind, part)
                        for parse_attempt in range(1, 4):
                            before_pre = page.locator("main pre").count()
                            response, metadata = run_stage_once(
                                page=page, timeout_ms=15000, prompt_text=prompt_text,
                                wait_seconds=360, post_response_wait_seconds=1,
                                response_settle_seconds=3, max_settle_wait_seconds=20,
                                allow_retry=False, stage_name=f"{kind}-{part}-parse-{parse_attempt}",
                                error_screenshot=RUN_DIR / "debug" / "chatgpt_error.png",
                            )
                            label = f"{kind.upper()} PART {part} OF {4 if kind == 'css' else 8}"
                            try:
                                code, language, block = latest_code_block(page, before_pre)
                                if len(code) < 80:
                                    raise ValueError(f"{label}: code is too short or truncated.")
                                if not message_has_label(block, label, code):
                                    raise ValueError(f"{label}: response heading was missing outside its code block.")
                                chat_url = page.url
                                result = accept_chunk(RUN_DIR, kind=kind, part=part, response=response,
                                                     code=code, language=language, chat_url=chat_url)
                                turn_log["chat_url"] = chat_url
                                turn_log["turns"].append({"kind": kind, "part": part,
                                    "response": response, "capture": result, "metadata": metadata})
                                write_json(RUN_DIR / "conversation_turns.json", turn_log)
                                print(f"Captured {label}: {result['characters']} characters.", flush=True)
                                break
                            except ValueError as error:
                                if parse_attempt == 3:
                                    raise RuntimeError(f"{label} failed validation after three responses: {error}") from error
                                prompt_text = (f"I could not validate the prior response ({error}). Resend {label} only, "
                                    f"with the matching response heading, exactly one code block, and exact marker "
                                    f"{('/* ' + label + ' */') if kind == 'css' else ('<!-- ' + label + ' -->')}. "
                                    "Do not repeat any other part.")
                        else:
                            raise RuntimeError(f"Failed to capture {kind} part {part}.")
                    context.close()
                except Exception:
                    try:
                        save_failure_diagnostics(page, RUN_DIR / "debug" / "chatgpt_failure.png",
                            metadata={"url": page.url, "title": page.title(), "network_events": NETWORK_EVENTS},
                            html_path=RUN_DIR / "debug" / "chatgpt_failure.html")
                    except Exception:
                        pass
                    context.close()
                    raise
        assembly = assemble(RUN_DIR)
        inlined = RUN_DIR / "files" / "inlined" / "index.html"
        subprocess.run([sys.executable, str(SCRIPTS / "inline_css.py"),
                        str(RUN_DIR / "files" / "index.html"), str(RUN_DIR / "files" / "styles.css"), str(inlined)],
                       check=True, cwd=REPO)
        subprocess.run([sys.executable, str(SCRIPTS / "browser_qa.py"), str(RUN_DIR), prompt],
                       check=True, cwd=REPO)
        browser_report = json.loads((RUN_DIR / "debug" / "browser_qa.json").read_text(encoding="utf-8"))
        report = assess_website(prompt, RUN_DIR)
        report["browser_qa_status"] = browser_report.get("status", "missing")
        report["browser_qa_checks"] = browser_report.get("checks", {})
        report["automated_success"] = bool(report.get("complete") and browser_report.get("status") == "pass")
        write_json(RUN_DIR / "debug" / "checker_report.json", report)
        run_notes.update({"status": "automated_checks_passed_pending_visual_review" if report["automated_success"] else "automated_checks_failed",
                          "automated_success": report["automated_success"],
                          "final_success": False,
                          "chat_url": chat_url,
                          "source_audit_status": audit.get("status"),
                          "source_contact_form": audit.get("contact_form", "unknown"),
                          "browser_qa_status": report.get("browser_qa_status", "missing"),
                          "visual_review_status": report.get("visual_review_status", "pending"),
                          "visual_design_review_status": report.get("visual_design_review_status", "pending"),
                          "assembly": assembly,
                          "note": "Automated checks are provisional until image relevance and desktop/mobile screenshot review are completed."})
        write_json(RUN_DIR / "run_notes.json", run_notes)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write("## ChatGPT website candidate generated\n\n")
                handle.write(f"- Target: `{row['website']}`\n- Captured chunks: `4 CSS + 8 HTML`\n")
                handle.write(f"- Automated checks: `{run_notes['status']}`\n- Preview: `{RUN_DIR.relative_to(REPO).as_posix()}/files/inlined/index.html`\n")
                handle.write("- Visual approval: pending screenshot-backed review.\n")
        print(f"Candidate output: {RUN_DIR}", flush=True)
        return report
    except Exception as error:
        run_notes.update({"status": "generation_failed", "error": str(error), "chat_url": chat_url,
                          "network_events": NETWORK_EVENTS, "captured_parts": len(turn_log["turns"])})
        write_json(RUN_DIR / "run_notes.json", run_notes)
        write_json(RUN_DIR / "conversation_turns.json", turn_log)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write("## ChatGPT website candidate failed\n\n")
                safe_error = str(error).replace("`", "'").replace("\n", " ")
                handle.write(f"- Error: `{safe_error}`\n")
                handle.write(f"- Captured chunks: `{len(turn_log['turns'])}/12`\n")
                if chat_url:
                    handle.write(f"- Chat: `{chat_url}`\n")
        raise


if __name__ == "__main__":
    try:
        result = run()
        if not result.get("automated_success"):
            raise SystemExit(2)
    except Exception as error:
        print(f"ChatGPT website run failed: {error}", file=sys.stderr)
        raise SystemExit(1)
