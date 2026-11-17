#!/usr/bin/env python3
"""Download, review, revise, and visually QA HTML pages with Workers AI or NVIDIA NIM."""

from __future__ import annotations

import argparse
import base64
import http.client
import difflib
import email.utils
import json
import html as html_lib
from html.parser import HTMLParser
import os
import re
import shutil
import socket
import ssl
import sys
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


MODEL_DEFAULT = "@cf/google/gemma-4-26b-a4b-it"
VALID_CRITERIA = {
    "ART-01", "ART-02", "VIS-01", "VIS-02", "VIS-03", "UX-01", "UX-02",
    "RESP-01", "MOTION-01", "A11Y-01", "A11Y-02", "A11Y-03", "CODE-01", "CODE-02",
    "ENH-01", "ENH-02", "ENH-03", "ENH-04", "ENH-05", "ENH-06",
}


def load_credentials(env_file: Path | None) -> None:
    """Read only the two expected secrets. Never print their values."""
    if env_file and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(?:export\s+)?(?:\$env:)?(CLOUDFLARE_ACCOUNT_ID|CLOUDFLARE_API_TOKEN)\s*=\s*(.*?)\s*$", line)
            if match and not os.environ.get(match.group(1)):
                value = match.group(2).strip().strip('"').strip("'")
                os.environ[match.group(1)] = value
    missing = [key for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN") if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing credentials: " + ", ".join(missing) + ". Set them in the environment or provide --env-file.")


def load_nvidia_key(key_file: Path | None) -> str:
    """Load an NVIDIA API key from the environment or a one-line key file."""
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not key and key_file and key_file.is_file():
        key = key_file.read_text(encoding="utf-8-sig").strip()
    if not key:
        raise RuntimeError("Missing NVIDIA_API_KEY. Set it in the environment or provide --env-file with the API key.")
    if not key.startswith("nvapi-") or any(char.isspace() for char in key):
        raise RuntimeError("The NVIDIA API key file must contain a single nvapi- key, without surrounding text.")
    return key


def get_model_text(response: dict) -> str:
    result = response.get("result") or {}
    if result.get("response"):
        return str(result["response"])
    choices = result.get("choices") or response.get("choices") or []
    if choices:
        return str(choices[0].get("message", {}).get("content", ""))
    raise RuntimeError("Inference response did not contain result.response or a chat completion.")


def nvidia_json_schema(name: str) -> dict:
    """Return a compact structured-output schema for NVIDIA calls that must return JSON."""
    if "anchor-repair" in name:
        anchor = {
            "type": "object", "additionalProperties": False,
            "required": ["id", "find"],
            "properties": {
                "id": {"type": "string", "maxLength": 50},
                "find": {"type": "string", "minLength": 40, "maxLength": 1200},
            },
        }
        return {"type": "object", "additionalProperties": False, "required": ["edits"],
                "properties": {"edits": {"type": "array", "maxItems": 5, "items": anchor}}}
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["criterion_id", "priority", "finding", "evidence", "user_impact", "recommendation", "confidence"],
        "properties": {
            "criterion_id": {"type": "string", "enum": sorted(VALID_CRITERIA)},
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "finding": {"type": "string", "maxLength": 500},
            "evidence": {"type": "string", "maxLength": 400},
            "user_impact": {"type": "string", "maxLength": 300},
            "recommendation": {"type": "string", "maxLength": 300},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }
    if name.startswith("assessment"):
        strength = {
            "type": "object", "additionalProperties": False,
            "required": ["criterion_id", "finding", "evidence"],
            "properties": {
                "criterion_id": {"type": "string", "enum": sorted(VALID_CRITERIA)},
                "finding": {"type": "string", "maxLength": 350},
                "evidence": {"type": "string", "maxLength": 300},
            },
        }
        return {
            "type": "object", "additionalProperties": False,
            "required": ["concept", "summary", "strengths", "code_findings", "visual_findings", "content_and_conversion_findings", "preserve", "unknowns_to_verify"],
            "properties": {
                "concept": {"type": "string", "maxLength": 40},
                "summary": {"type": "string", "maxLength": 600},
                "strengths": {"type": "array", "maxItems": 2, "items": strength},
                "code_findings": {"type": "array", "maxItems": 2, "items": finding},
                "visual_findings": {"type": "array", "maxItems": 2, "items": finding},
                "content_and_conversion_findings": {"type": "array", "maxItems": 2, "items": finding},
                "preserve": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
                "unknowns_to_verify": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 200}},
            },
        }
    if "edit" in name or "repair" in name or "enhancement" in name or "correction" in name:
        edit = {
            "type": "object", "additionalProperties": False,
            "required": ["id", "criterion_id", "reason", "find", "replace"],
            "properties": {
                "id": {"type": "string", "maxLength": 50},
                "criterion_id": {"type": "string", "enum": sorted(VALID_CRITERIA)},
                "reason": {"type": "string", "maxLength": 400},
                "find": {"type": "string", "minLength": 20, "maxLength": 1200},
                "replace": {"type": "string", "maxLength": 1200},
            },
        }
        return {"type": "object", "additionalProperties": False, "required": ["edits"],
                "properties": {"edits": {"type": "array", "maxItems": 5, "items": edit}}}
    if "qa" in name or "gate" in name or "verification" in name:
        issue = {"type": "object", "additionalProperties": True}
        return {"type": "object", "additionalProperties": True,
                "required": ["status", "remaining_issues"],
                "properties": {"status": {"type": "string", "enum": ["pass", "revise"]},
                               "remaining_issues": {"type": "array", "maxItems": 5, "items": issue}}}
    return {"type": "object", "additionalProperties": True}


def invoke_workers_ai(name: str, system_text: str, user_text: str, image_paths: list[Path],
                      audit_dir: Path, model: str, account_id: str, token: str,
                      max_tokens: int = 8000) -> str:
    parts: list[dict] = [{"type": "text", "text": user_text}]
    for image_path in image_paths:
        suffix = image_path.suffix.lower()
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": parts},
    ]
    if account_id == "nvidia":
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "html_assessment_response",
                    "strict": name.startswith("assessment") or any(token in name for token in ("edit", "repair", "enhancement", "correction")),
                    "schema": nvidia_json_schema(name),
                },
            },
        }
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        auth_header = f"Bearer {token}"
    else:
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{urllib.parse.quote(model, safe='@/') }"
        auth_header = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": auth_header, "Content-Type": "application/json"},
        method="POST",
    )
    provider = "NVIDIA NIM" if account_id == "nvidia" else "Workers AI"
    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in retryable_statuses and attempt < max_attempts - 1:
                retry_after = exc.headers.get("Retry-After", "").strip()
                delay = 2 ** attempt
                if retry_after:
                    try:
                        delay = max(0, int(float(retry_after)))
                    except ValueError:
                        try:
                            retry_time = email.utils.parsedate_to_datetime(retry_after)
                            delay = max(0, int((retry_time - datetime.now().astimezone()).total_seconds()))
                        except (TypeError, ValueError, OverflowError):
                            pass
                delay = min(delay, 60)
                print(f"{provider} request '{name}' returned HTTP {exc.code}; retry {attempt + 1}/{max_attempts - 1} in {delay}s.", file=sys.stderr)
                time.sleep(delay)
                continue
            for secret in (token, account_id):
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")
            raise RuntimeError(f"{provider} request '{name}' failed (HTTP {exc.code}): {detail[:1500]}") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError) and attempt == 0:
                print(f"{provider} request '{name}' failed TLS verification; retrying once with certificate checks enabled.", file=sys.stderr)
                time.sleep(2)
                continue
            transient = isinstance(exc.reason, (TimeoutError, socket.timeout, ConnectionError, ConnectionResetError))
            if transient and attempt < max_attempts - 1:
                delay = min(2 ** attempt, 60)
                print(f"{provider} request '{name}' encountered a transient connection error; retry {attempt + 1}/{max_attempts - 1} in {delay}s.", file=sys.stderr)
                time.sleep(delay)
                continue
            reason = str(exc.reason)
            for secret in (token, account_id):
                if secret:
                    reason = reason.replace(secret, "[REDACTED]")
            raise RuntimeError(f"{provider} request '{name}' failed: {reason}") from None
    if body.get("success") is False:
        detail = str(body.get("errors"))
        for secret in (token, account_id):
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        raise RuntimeError(f"{provider} request '{name}' failed: {detail[:1500]}")
    text = get_model_text(body)
    for secret in (token, account_id):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    if not text.strip():
        raise RuntimeError(f"{provider} returned an empty response in state '{name}'.")
    (audit_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    return text


def save_screenshot(html_path: Path, target: Path, width: int, height: int,
                    page_url: str, view: str, full_page: bool = False) -> None:
    """Render supplied HTML in headless Chromium while retaining the site's URL as its asset base."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for visual mode. Install requirements-playwright.txt and its Chromium browser.") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    browser_env = {key: value for key, value in os.environ.items()
                   if not any(marker in key.upper() for marker in ("TOKEN", "SECRET", "API_KEY", "PASSWORD", "PRIVATE_KEY"))
                   and not key.upper().startswith(("CLOUDFLARE_", "NVIDIA_"))}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, env=browser_env)
        try:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            html_text = read_html(html_path)
            if not re.search(r"<base\b", html_text, flags=re.IGNORECASE):
                base_tag = f'<base href="{html_lib.escape(page_url, quote=True)}">'
                html_text = re.sub(r"(<head\b[^>]*>)", lambda match: match.group(1) + base_tag, html_text, count=1, flags=re.IGNORECASE)
            page.set_content(html_text, wait_until="load", timeout=60000)
            try:
                page.evaluate("document.fonts.ready")
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(750)
            if view == "section":
                page.evaluate("""() => {
                    const candidates = [...document.querySelectorAll('main section, main article, body > section, section')];
                    const visible = candidates.filter(el => el.getBoundingClientRect().height > 80);
                    const target = visible[Math.min(1, visible.length - 1)];
                    if (target) target.scrollIntoView({block: 'start', behavior: 'instant'});
                }""")
                page.wait_for_timeout(250)
            page.screenshot(path=str(target), full_page=full_page, animations="disabled")
        finally:
            browser.close()
    if not target.is_file() or target.stat().st_size < 1000:
        raise RuntimeError(f"Playwright did not produce a usable screenshot for {html_path.name} ({view}).")

def read_html(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def model_json(text: str) -> dict:
    clean = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", clean)
    if fenced:
        clean = fenced.group(1)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Some responses escape HTML punctuation (such as \>), which JSON forbids.
        # Drop only backslashes before characters that JSON does not allow to be escaped.
        normalized = re.sub(r'\\(?!["\\/bfnrtu])', "", clean)
        # Models can emit literal newlines or tabs inside quoted JSON strings. Escape
        # those control characters without changing JSON structure or existing escapes.
        escaped: list[str] = []
        in_string = False
        index = 0
        while index < len(normalized):
            char = normalized[index]
            if in_string and char == "\\":
                escaped.append(char)
                if index + 1 < len(normalized):
                    escaped.append(normalized[index + 1])
                    index += 2
                    continue
            elif char == '"':
                in_string = not in_string
                escaped.append(char)
            elif in_string and ord(char) < 0x20:
                escaped.append({"\n": r"\n", "\r": r"\r", "\t": r"\t"}.get(char, f"\\u{ord(char):04x}"))
            else:
                escaped.append(char)
            index += 1
        normalized = "".join(escaped)
        try:
            return json.loads(normalized)
        except json.JSONDecodeError as exc:
          # Recover a response that omitted a small number of closing object/array
          # delimiters. Insert a missing inner closer only when a later closer makes
          # the nesting unambiguous; never close an open string.
          stack: list[str] = []
          in_string = False
          escaped_char = False
          structurally_valid = True
          delimiter_repairs = 0
          fixed_chars: list[str] = []
          for char in normalized:
              if in_string:
                  fixed_chars.append(char)
                  if escaped_char:
                      escaped_char = False
                  elif char == "\\":
                      escaped_char = True
                  elif char == '"':
                      in_string = False
              elif char == '"':
                  in_string = True
                  fixed_chars.append(char)
              elif char in "{[":
                  stack.append("}" if char == "{" else "]")
                  fixed_chars.append(char)
              elif char in "}]":
                  if stack and stack[-1] != char and char in stack:
                      while stack and stack[-1] != char:
                          fixed_chars.append(stack.pop())
                          delimiter_repairs += 1
                  if not stack or stack[-1] != char:
                      structurally_valid = False
                      break
                  stack.pop()
                  fixed_chars.append(char)
              else:
                  fixed_chars.append(char)
          if structurally_valid and not in_string and delimiter_repairs <= 2 and len(stack) <= 2:
              fixed_chars.extend(reversed(stack))
              try:
                  candidate = json.loads("".join(fixed_chars))
                  if isinstance(candidate, dict) and ("edits" in candidate or "status" in candidate):
                      return candidate
              except json.JSONDecodeError:
                  pass
          decoder = json.JSONDecoder()
          for match in re.finditer(r"\{", normalized):
              try:
                  candidate, _ = decoder.raw_decode(normalized[match.start():])
              except json.JSONDecodeError:
                  continue
              if isinstance(candidate, dict) and ("edits" in candidate or "status" in candidate):
                  return candidate
          raise ValueError(f"Model returned invalid JSON after escape normalization: {exc}") from None


def validate_assessment(text: str, concept: str, provider_name: str = "Model") -> None:
    report = model_json(text)
    for group in ("strengths", "code_findings", "visual_findings", "content_and_conversion_findings"):
        findings = report.get(group)
        if not isinstance(findings, list):
            raise RuntimeError(f"Assessment for {concept} is missing the {group} array.")
        for index, finding in enumerate(findings, start=1):
            if finding.get("criterion_id") not in VALID_CRITERIA or not finding.get("evidence"):
                raise RuntimeError(f"{provider_name} assessment for {concept} finding {group}[{index}] lacks a valid rubric criterion or evidence.")
            if group != "strengths" and (not finding.get("user_impact") or finding.get("confidence") not in {"high", "medium", "low"}):
                raise RuntimeError(f"{provider_name} assessment for {concept} finding {group}[{index}] lacks user impact or confidence.")


def remove_contradicted_missing_attribute_claims(text: str, source: str) -> tuple[str, list[dict]]:
    """Drop only missing-attribute claims whose cited opening tag proves them false."""
    report = model_json(text)
    missing_patterns = (
        re.compile(r"\b(?:missing|lacks?|without|does not have|doesn't have)\s+(?:(?:a|an|the)\s+)?([a-z][\w:-]*)\s+attribute\b", re.I),
        re.compile(r"\b([a-z][\w:-]*)\s+attribute\s+(?:is|appears)\s+(?:missing|absent)\b", re.I),
    )
    rejected = []
    for group in ("code_findings", "content_and_conversion_findings"):
        kept = []
        for finding in report.get(group, []):
            description = " ".join(str(finding.get(key, "")) for key in ("finding", "recommendation", "evidence"))
            missing_attributes = {match.group(1).lower() for pattern in missing_patterns for match in pattern.finditer(description)}
            contradiction = None
            if missing_attributes:
                evidence = str(finding.get("evidence", ""))
                for tag in re.findall(r"<([a-z][\w:-]*)\b[^>]*>", evidence, re.I):
                    snippets = re.findall(rf"<{re.escape(tag)}\b[^>]*>", evidence, re.I)
                    for snippet in snippets:
                        if snippet not in source and not re.search(re.escape(snippet).replace(r"\ ", r"\s+"), source, re.I):
                            continue
                        attributes = {
                            match.group(1).lower()
                            for match in re.finditer(r"\s([a-z_:][\w:.-]*)(?:\s*=|\s|/?>)", snippet, re.I)
                        }
                        contradicted = sorted(missing_attributes & attributes)
                        if contradicted:
                            contradiction = {"attributes": contradicted, "evidence": snippet}
                            break
                    if contradiction:
                        break
            if contradiction:
                rejected.append({"group": group, "finding": finding.get("finding", ""), "contradiction": contradiction})
            else:
                kept.append(finding)
        report[group] = kept
    return json.dumps(report, ensure_ascii=False), rejected


def ensure_assessment_rubric(text: str, concept: str, system_text: str, audit_dir: Path,
                             model: str, account_id: str, token: str) -> str:
    try:
        validate_assessment(text, concept)
        return text
    except (RuntimeError, ValueError) as first_error:
        bounded_previous = text[:9000]
        repair = (
            f"STATE A FORMAT RECOVERY — {concept}\n"
            "The prior response may be truncated, overlong, speculative, or invalid JSON. Reassess only the evidence preserved below and return a concise valid State A object. "
            "Use at most 2 strengths and at most 4 total findings across all finding arrays. Ignore unsupported or generic checklist items. "
            "Use empty arrays when the evidence does not support a finding. Summary: at most 60 words. Stay within 2500 output tokens. Return JSON only.\n\n"
            f"Prior response excerpt (may be incomplete):\n{bounded_previous}"
        )
        repaired = invoke_workers_ai(f"assessment-format-repair-{concept}", system_text, repair, [], audit_dir, model, account_id, token, 3000)
        validate_assessment(repaired, concept)
        return repaired


def unique_whitespace_quote_anchor(source: str, anchor: str) -> str | None:
    """Find one literal source span when a model changed only quote style or whitespace."""
    pieces = re.split(r"(\s+)", anchor)
    pattern = "".join(r"\s+" if piece.isspace() else re.escape(piece).replace("'", "[\"']") for piece in pieces)
    try:
        matches = list(re.finditer(pattern, source, flags=re.DOTALL))
    except re.error:
        return None
    if len(matches) != 1:
        return None
    return matches[0].group(0)


class ImageSourceParser(HTMLParser):
    """Collect image source attributes so model edits cannot silently replace assets."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}
        image_input = tag == "input" and str(attributes.get("type") or "").lower() == "image"
        if tag not in {"img", "source"} and not image_input:
            return
        for name in ("src", "srcset"):
            if name not in attributes or (tag == "source" and name == "src"):
                continue
            self.sources.append((tag, name, attributes[name] or ""))


def image_sources(html: str) -> list[tuple[str, str, str]]:
    parser = ImageSourceParser()
    parser.feed(html)
    return parser.sources


def supported_form_wrapper_repair(source: str, candidate: str) -> bool:
    """Allow wrapping proven existing form controls without adding fields or behavior."""
    source_form_values = {
        (name.lower(), value)
        for name, _quote, value in re.findall(r"\b(action|method)\s*=\s*(['\"])(.*?)\2", source, re.I)
    }
    for form_tag in re.findall(r"<form\b[^>]*>", candidate, re.I):
        for name, _quote, value in re.findall(r"\b(action|method)\s*=\s*(['\"])(.*?)\2", form_tag, re.I):
            if (name.lower(), value) not in source_form_values:
                return False
    source_open = len(re.findall(r"<form\b", source, re.I))
    candidate_open = len(re.findall(r"<form\b", candidate, re.I))
    source_closes = len(re.findall(r"</form\s*>", source, re.I))
    candidate_closes = len(re.findall(r"</form\s*>", candidate, re.I))
    if candidate_closes != source_closes or candidate_open < source_open:
        return False
    source_controls = {
        tag: len(re.findall(rf"<{tag}\b", source, re.I))
        for tag in ("input", "textarea", "select", "button")
    }
    candidate_controls = {
        tag: len(re.findall(rf"<{tag}\b", candidate, re.I))
        for tag in source_controls
    }
    if candidate_controls != source_controls:
        return False
    if candidate_open == source_open:
        return True
    if candidate_open != source_open + 1:
        return False
    if not any(source_controls[tag] for tag in ("input", "textarea", "select")):
        return False
    orphaned_action = bool(re.search(r"\baction\s*=\s*(['\"])[^'\"]+\1", source, re.I))
    source_submit = bool(
        re.search(r"<input\b[^>]*\btype\s*=\s*(['\"])submit\1", source, re.I)
        or re.search(r"<button\b[^>]*\btype\s*=\s*(['\"])submit\1", source, re.I)
    )
    if (source_closes <= source_open and not orphaned_action) or (not source_submit and not orphaned_action):
        return False
    return True


def apply_model_edits(html: str, edit_response: str, rejected_path: Path) -> str:
    parsed = model_json(edit_response)
    edits = parsed.get("edits")
    if not isinstance(edits, list):
        raise ValueError("Model edit response did not contain an edits array.")
    rejected: list[dict] = []
    for edit in edits:
        if edit.get("criterion_id") not in VALID_CRITERIA:
            rejected.append({"id": edit.get("id"), "reason": "Edit did not cite a valid assessment rubric criterion."})
            continue
        find, replace = edit.get("find"), edit.get("replace")
        if not isinstance(find, str) or not find or not isinstance(replace, str):
            rejected.append({"id": edit.get("id"), "reason": "Edit needs non-empty find and string replace fields."})
            continue
        count = html.count(find)
        matched_find = find
        if count != 1:
            tolerant_match = unique_whitespace_quote_anchor(html, find)
            if tolerant_match is not None:
                matched_find = tolerant_match
                count = 1
                rejected.append({"id": edit.get("id"), "reason": "Matched a unique literal source span after normalizing only quote style and whitespace; replacement used the exact source text.", "original_find": find, "matched_source": matched_find})
            else:
                rejected.append({"id": edit.get("id"), "reason": f"Exact source snippet matched {count} times and no unique quote/whitespace-equivalent span was found; skipped.", "find": find})
                continue
        candidate = html.replace(matched_find, replace, 1)
        if not supported_form_wrapper_repair(html, candidate):
            rejected.append({"id": edit.get("id"), "reason": "Edit attempted to add form functionality, fields, or an unproven action instead of repairing an existing source-backed form wrapper."})
            continue
        if image_sources(candidate) != image_sources(html):
            rejected.append({
                "id": edit.get("id"),
                "reason": "Edit changed an existing image src/srcset or added/removed an image source; image asset changes require a separate verified workflow and were skipped.",
                "find": find,
            })
            continue
        html = candidate
    rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    return html


def apply_model_edits_with_anchor_repair(html: str, edit_response: str, rejected_path: Path,
                                        call_name: str, system_text: str, audit_dir: Path,
                                        model: str, account_id: str, token: str) -> str:
    """Apply valid edits, then ask the selected provider to re-anchor only exact-snippet failures."""
    revised = apply_model_edits(html, edit_response, rejected_path)
    first_rejections = json.loads(rejected_path.read_text(encoding="utf-8"))
    anchor_failures = [item for item in first_rejections if "Exact source snippet matched" in item.get("reason", "")]
    if not anchor_failures:
        return revised
    original_edits = model_json(edit_response).get("edits", [])
    originals_by_id = {str(edit.get("id")): edit for edit in original_edits if isinstance(edit, dict)}
    requested = []
    for item in anchor_failures:
        original = originals_by_id.get(str(item.get("id")), {})
        requested.append({
            "id": item.get("id"),
            "criterion_id": original.get("criterion_id"),
            "reason": original.get("reason", ""),
            "original_find": original.get("find", item.get("find", "")),
            "intended_replacement": original.get("replace", ""),
            "anchor_error": item.get("reason", ""),
        })
    repair_text = (
        f"STATE {call_name.upper()} PATCH-ANCHOR REPAIR\n"
        "For only the listed failures, locate the exact HTML element described by that edit's reason and intended replacement. Return JSON with an `edits` array "
        "containing each original edit id and only a new `find` value copied character-for-character from the current HTML. The new find must be a useful, unique snippet of at least 40 characters, not a generic tag prefix. If the same class or element appears more than once, include inner content or nearby sibling text so only the intended occurrence matches. Preserve the source's quotes, entities, whitespace, and newlines exactly. Do not normalize or paraphrase it. Do not return replacements or other fields. "
        "Encode newlines inside JSON strings as \\\\n. Return exactly one valid JSON object and no prose.\n\n"
        f"Requested IDs and criteria:\n{json.dumps(requested, ensure_ascii=False)}\n\n"
        f"Anchor failures:\n{json.dumps(anchor_failures, ensure_ascii=False)}\n\n"
        f"Current HTML after valid edits were applied:\n<page_html>\n{revised}\n</page_html>"
    )
    cached_anchor_path = audit_dir / f"{call_name}-anchor-repair.txt"
    repaired_response = None
    if cached_anchor_path.exists():
        cached_anchor = cached_anchor_path.read_text(encoding="utf-8")
        try:
            if isinstance(model_json(cached_anchor).get("edits"), list):
                repaired_response = cached_anchor
        except ValueError:
            pass
    if repaired_response is None:
        repaired_response = invoke_workers_ai(f"{call_name}-anchor-repair", system_text, repair_text, [], audit_dir, model, account_id, token, 5000)
    repair_rejections_path = rejected_path.with_name(rejected_path.stem + "-anchor-repair.json")
    repaired_edits = model_json(repaired_response).get("edits", [])
    composed_edits = []
    for anchor in repaired_edits:
        if not isinstance(anchor, dict):
            continue
        original = originals_by_id.get(str(anchor.get("id")))
        new_find = anchor.get("find")
        if original and isinstance(new_find, str) and new_find:
            composed_edits.append({**original, "find": new_find})
    revised = apply_model_edits(revised, json.dumps({"edits": composed_edits}, ensure_ascii=False), repair_rejections_path)
    all_rejections = [item for item in first_rejections if "Exact source snippet matched" not in item.get("reason", "")]
    all_rejections.extend(json.loads(repair_rejections_path.read_text(encoding="utf-8")))
    rejected_path.write_text(json.dumps(all_rejections, ensure_ascii=False, indent=2), encoding="utf-8")
    return revised


def screenshot_paths(page: dict, stage: str) -> list[Path]:
    return [page[f"{stage}_{key}"] for key in ("hero", "section", "mobile")]


def preserve_original_inline_html(source_html: Path, inline_dir: Path) -> Path:
    """Save the staged, unmodified source once before replacing candidate HTML."""
    inline_dir.mkdir(parents=True, exist_ok=True)
    old_inline = inline_dir / "index-old.html"
    if not old_inline.exists():
        shutil.copy2(source_html, old_inline)
    return old_inline


def validate_qa_report(text: str, concept: str, stage: str) -> dict:
    report = model_json(text)
    if report.get("status") not in {"pass", "revise"}:
        raise RuntimeError(f"Selected-provider {stage} QA for {concept} did not return pass/revise status.")
    for issue in report.get("remaining_issues", []):
        if issue.get("criterion_id") not in VALID_CRITERIA or not issue.get("evidence"):
            raise RuntimeError(f"Selected-provider {stage} QA for {concept} contains an issue without a valid criterion or evidence.")
    return report


def ensure_qa_report(text: str, concept: str, stage: str, system_text: str, audit_dir: Path,
                     model: str, account_id: str, token: str) -> tuple[str, dict]:
    try:
        return text, validate_qa_report(text, concept, stage)
    except (RuntimeError, ValueError):
        repair = (
            f"STATE {stage.upper()} QA FORMAT REPAIR — {concept}\n"
            "Reformat the previous QA result as valid JSON matching the QA schema in the system instructions. "
            "Preserve its status and supported findings. Every remaining issue must use a valid criterion ID and include evidence. "
            "If an issue cannot be assigned from the existing evidence, omit it rather than guessing. Do not add new findings. Return JSON only.\n\n"
            f"Previous QA result:\n{text}"
        )
        repaired = invoke_workers_ai(f"{stage.lower().replace(' ', '-')}-qa-format-repair-{concept}", system_text, repair, [], audit_dir, model, account_id, token, 4000)
        try:
            return repaired, validate_qa_report(repaired, concept, stage)
        except (RuntimeError, ValueError):
            # Keep the malformed provider output in the audit and continue with an
            # explicit non-passing status instead of losing all generated pages.
            return repaired, {"concept": concept, "status": "invalid", "remaining_issues": []}


def run_repository_qa(html_path: Path, label: str, url: str, run_dir: Path, source_candidate: Path | None = None) -> dict:
    """Run Git Content's existing deterministic QA against an isolated HTML snapshot."""
    package = Path(__file__).resolve().parent
    qa_script = package.parent / "scripts" / "run_html_assessment_qa.py"
    if not qa_script.is_file():
        return {"available": False, "automated_success": None, "blocking_failures": [], "note": "No Git Content repository QA is installed in this assessment project."}

    candidate = run_dir / "audit" / "repository-qa" / label
    files_dir = candidate / "files"
    inline_dir = files_dir / "inlined"
    debug_dir = candidate / "debug"
    inline_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    (files_dir / "index.html").write_text(html, encoding="utf-8")
    (inline_dir / "index.html").write_text(html, encoding="utf-8")
    styles = re.findall(r"<style\b[^>]*>([\s\S]*?)</style\s*>", html, flags=re.IGNORECASE)
    (files_dir / "styles.css").write_text("\n\n".join(styles), encoding="utf-8")
    (candidate / "run_notes.json").write_text(json.dumps({"source_url": url}), encoding="utf-8")

    # Preserve only source facts and selected-template metadata used by the
    # repository's deterministic validators. Never copy credentials or old QA.
    if source_candidate:
        source_debug = source_candidate / "debug"
        for name in ("source_facts.json", "design_reference.json", "design_references.json"):
            source_file = source_debug / name
            if source_file.is_file():
                shutil.copy2(source_file, debug_dir / name)

    child_env = os.environ.copy()
    for secret_name in ("NVIDIA_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
        child_env.pop(secret_name, None)
    result = subprocess.run(
        [sys.executable, str(qa_script), str(candidate)],
        capture_output=True, text=True, encoding="utf-8", env=child_env,
    )
    try:
        report = json.loads((debug_dir / "checker_report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {"automated_success": False, "blocking_failures": ["repository QA did not produce a valid checker report"]}
    try:
        browser = json.loads((debug_dir / "browser_qa.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        browser = {"status": "missing", "checks": {}}
    report["browser_qa_status"] = browser.get("status", "missing")
    report["browser_qa_checks"] = browser.get("checks", {})
    report["browser_qa"] = browser
    report["process_exit_code"] = result.returncode
    report["available"] = True
    (debug_dir / "assessment_gate_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def repository_qa_prompt(report: dict) -> str:
    """Keep QA prompts compact while retaining every deterministic blocker and CTA detail."""
    checks = report.get("checks", {})
    browser = report.get("browser_qa_checks", {})
    viewport_reports = (report.get("browser_qa") or {}).get("viewports", {})
    template_layout = (report.get("browser_qa") or {}).get("template_layout", {})
    cta_measurements = {
        viewport: {
            key: details.get(key)
            for key in ("cta", "hero_cta_contrast", "contact_cta_contrast", "primary_cta_contrast")
            if key in details
        }
        for viewport, details in viewport_reports.items()
    }
    return json.dumps({
        "automated_success": report.get("automated_success", False),
        "available": report.get("available", False),
        "blocking_failures": report.get("blocking_failures", []),
        "missing_sections": report.get("missing_sections", []),
        "browser_qa_status": report.get("browser_qa_status", "missing"),
        "browser_checks_failed": {name: value for name, value in browser.items() if value is False},
        "cta_contrast": {
            name: value for name, value in browser.items()
            if "cta" in name.lower() and (value is False or isinstance(value, dict))
        },
        "cta_measurements_by_viewport": cta_measurements,
        "failed_image_urls": report.get("failed_image_urls", []),
        "source_contact_form_fields_missing": report.get("source_form_fields_missing", []),
        "source_contact_form_required_fields_missing": report.get("source_form_required_fields_missing", []),
        "template_layout": {
            key: template_layout.get(key)
            for key in (
                "status", "signature_id", "profile", "below_hero_section_count",
                "spotlight_count", "spotlight_media_sides", "spotlight_side_alternations",
                "divided_page", "has_gallery_or_items", "has_both_orientations",
            )
            if key in template_layout
        },
        "failed_structural_checks": [name for name, passed in checks.items() if passed is False],
        "source_contact_form": {
            name: value for name, value in checks.items()
            if name.startswith("source_contact_form")
        },
    }, indent=2, ensure_ascii=False)


def run(args: argparse.Namespace) -> Path:
    package = Path(__file__).resolve().parent
    provider = args.provider
    env_file = Path(args.env_file).expanduser() if args.env_file else None
    if provider == "nvidia":
        key_file = env_file or Path.home() / "Documents" / "nvidia-api-key.txt"
        account_id, token = "nvidia", load_nvidia_key(key_file)
        model = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    else:
        cloudflare_env = env_file or Path.home() / "Documents" / "CLOUDFLARE_ENV.txt"
        load_credentials(cloudflare_env if cloudflare_env.is_file() else None)
        account_id, token = os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]
        model = os.environ.get("CLOUDFLARE_MODEL", MODEL_DEFAULT)
    target = {}
    if args.target_json_file:
        target = json.loads(Path(args.target_json_file).read_text(encoding="utf-8"))
        if not isinstance(target, dict):
            raise RuntimeError("The target JSON file must contain one object.")
    elif args.resume_directory:
        saved_manifest_path = Path(args.resume_directory).resolve() / "manifest.json"
        if saved_manifest_path.is_file():
            target = json.loads(saved_manifest_path.read_text(encoding="utf-8")).get("target", {})
    urls = args.urls or ([target.get("source_url") or target["website"]] if target.get("website") else [])
    if not urls and args.resume_directory:
        saved_manifest = Path(args.resume_directory).resolve() / "manifest.json"
        if saved_manifest.is_file():
            urls = json.loads(saved_manifest.read_text(encoding="utf-8")).get("urls", [])
    if not urls:
        raise RuntimeError("Provide --urls or a Git Content target JSON file with a website field.")
    if (args.candidate_output_dir or args.results_root) and len(urls) != 1:
        raise RuntimeError("Git Content candidate export expects exactly one target page per workflow run.")
    if (args.candidate_output_dir or args.results_root) and args.code_only:
        raise RuntimeError("Git Content candidate export requires visual mode so desktop/mobile screenshots are produced.")
    if args.source_html_file and len(urls) != 1:
        raise RuntimeError("A private inline HTML source file must be paired with exactly one source URL.")
    if args.results_root and not args.site_slug:
        raise RuntimeError("--site-slug is required with --results-root.")
    if args.site_slug and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", args.site_slug):
        raise RuntimeError("Site slug must be a single safe path segment.")
    for url in urls:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError(f"Invalid public page URL: {url}")
    run_id = args.workflow_id or os.environ.get("GITHUB_RUN_ID", "") or datetime.now().strftime("%Y%m%d%H%M%S")
    run_attempt = args.workflow_attempt or os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    run_dir = Path(args.resume_directory).resolve() if args.resume_directory else (Path(args.output_root) if args.output_root else package / "generated") / ("run-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    if args.results_root and not args.candidate_output_dir:
        candidate_id = args.candidate_id or f"run-{run_id}-{run_attempt}-site-1-candidate-1"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}", candidate_id):
            raise RuntimeError("Candidate ID must be a single safe path segment.")
        args.candidate_output_dir = str(Path(args.results_root).resolve() / "results" / args.site_slug / f"run-{run_id}-{run_attempt}" / "candidates" / candidate_id)
    if args.candidate_output_dir:
        candidate_path = Path(args.candidate_output_dir).resolve()
        if candidate_path == run_dir or run_dir in candidate_path.parents or candidate_path in run_dir.parents:
            raise RuntimeError("Candidate output directory must be separate from the assessment run directory.")
        if args.update_existing_candidate:
            expected_source = (candidate_path / "files" / "inlined" / "index.html").resolve()
            if not candidate_path.is_dir() or not args.source_html_file or Path(args.source_html_file).resolve() != expected_source:
                raise RuntimeError("In-place updates require the source HTML to be this candidate's files/inlined/index.html.")
        elif candidate_path.exists():
            raise RuntimeError("Candidate output directory already exists; refusing to overwrite an earlier candidate.")
    elif args.update_existing_candidate:
        raise RuntimeError("--update-existing-candidate requires --candidate-output-dir.")
    if not args.resume_directory:
        run_dir.mkdir(parents=True, exist_ok=False)
    source_dir, shots_dir, audit_dir = run_dir / "source", run_dir / "screenshots", run_dir / "audit"
    for directory in (source_dir, shots_dir, audit_dir):
        directory.mkdir(parents=True, exist_ok=True)
    prompt = (package / "workflow-prompt.md").read_text(encoding="utf-8")
    rubric = (package / "assessment-rubric.md").read_text(encoding="utf-8")
    enhancement_rubric = (package / "enhancement-rubric.md").read_text(encoding="utf-8")
    rubric_metadata = json.loads((package / "assessment-rubric.json").read_text(encoding="utf-8"))
    context_fields = {key: str(target.get(key, "")).strip() for key in ("business", "category", "location")}
    context_fields.update({key: str(getattr(args, key, "") or "").strip() for key in ("business", "category", "location") if getattr(args, key, None)})
    context_block = "\n\n## Caller-supplied target context (unverified)\n" + json.dumps(context_fields, ensure_ascii=False) + "\nUse this only as context; treat the page source as factual authority."
    repair_prompt = prompt + "\n\n## Pass 1 repair rubric\n\n" + rubric + context_block
    enhancement_prompt = repair_prompt + "\n\n## Pass 2 design enhancement rubric\n\n" + enhancement_rubric
    if args.code_only:
        override = "\n\nActive run override: code-only. No screenshots were supplied. Do not make visual claims; explicitly record that rendered visual QA was skipped.\n"
        repair_prompt += override
        enhancement_prompt += override

    pages: list[dict] = []
    for index, url in enumerate(urls, start=1):
        name = f"page-{index}"
        source = source_dir / f"{name}.html"
        page = {"name": name, "url": url, "source": source}
        if not args.resume_directory:
            if args.source_html_file:
                source_file = Path(args.source_html_file).resolve()
                if not source_file.is_file():
                    raise RuntimeError("The selected private inline HTML source file is missing.")
                shutil.copyfile(source_file, source)
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "HTMLAssessmentWorkflow/1.0"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    source.write_bytes(response.read())
            if source.stat().st_size < 100:
                raise RuntimeError(f"Downloaded source for {name} was unexpectedly small.")
        else:
            for key in ("hero", "section", "mobile"):
                page[f"source_{key}"] = shots_dir / f"{name}-source-{key}.png"
        pages.append(page)

    assessments: dict[str, str] = {}
    code_assessments: dict[str, str] = {}
    comparative_path = audit_dir / "comparative-recommendations.txt"

    # Stage 1: complete source-code audits for every page before making screenshots.
    for page in pages:
        name = page["name"]
        assessment_path = audit_dir / f"assessment-{name}.txt"
        if args.resume_directory and assessment_path.exists():
            cached = assessment_path.read_text(encoding="utf-8")
            try:
                validate_assessment(cached, name)
                assessments[name], contradicted = remove_contradicted_missing_attribute_claims(cached, read_html(page["source"]))
                (audit_dir / f"source-claim-validation-{name}.json").write_text(
                    json.dumps({"rejected_contradictions": contradicted}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                )
                assessment_path.write_text(assessments[name], encoding="utf-8")
                continue
            except (RuntimeError, ValueError):
                pass

        code_path = audit_dir / f"assessment-code-{name}.txt"
        code_report = None
        if args.resume_directory and code_path.exists():
            code_report = code_path.read_text(encoding="utf-8")
            try:
                validate_assessment(code_report, name)
            except (RuntimeError, ValueError):
                code_report = None
        if code_report is None:
            code_user = (
                f"STATE A — PASS 1 SOURCE-CODE AUDIT: ASSESS {name}\n"
                f"Page URL: {page['url']}\n"
                "Inspect the original HTML and CSS only. No screenshots have been captured or supplied. "
                "Report source-supported structure, content, semantics, links, forms, image-reference and CSS issues. "
                "Do not make rendered or visual claims, propose edits, or recommend a redesign. Return the requested assessment JSON.\n"
                f"<page_html>\n{read_html(page['source'])}\n</page_html>"
            )
            code_report = invoke_workers_ai(f"assessment-code-{name}", repair_prompt, code_user, [], audit_dir, model, account_id, token, 4500)
            code_report = ensure_assessment_rubric(code_report, name, repair_prompt, audit_dir, model, account_id, token)
        code_report, contradicted = remove_contradicted_missing_attribute_claims(code_report, read_html(page["source"]))
        (audit_dir / f"source-claim-validation-{name}.json").write_text(
            json.dumps({"rejected_contradictions": contradicted}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        validate_assessment(code_report, name)
        code_path.write_text(code_report, encoding="utf-8")

        if args.code_only:
            assessments[name] = code_report
            assessment_path.write_text(code_report, encoding="utf-8")
        else:
            code_assessments[name] = code_report

    # Stage 2: screenshots and visual review begin only after every code audit is saved.
    if not args.code_only:
        for page in pages:
            name = page["name"]
            if name not in code_assessments:
                continue
            for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                path = shots_dir / f"{name}-source-{key}.png"
                if not path.is_file():
                    save_screenshot(page["source"], path, width, height, page["url"], "section" if key == "section" else "top")
                page[f"source_{key}"] = path

        for page in pages:
            name = page["name"]
            if name in assessments:
                continue
            visual_user = (
                f"STATE A2 — PASS 1 SOURCE SCREENSHOT REVIEW: ASSESS {name}\n"
                f"Page URL: {page['url']}\n"
                "The original source-code audit below was completed before these screenshots were captured. "
                "Review the rendered desktop hero, desktop content section, and mobile hero against the original HTML. "
                "Return the complete assessment JSON, preserving all still-valid code findings and adding only screenshot-supported observations. "
                "Focus on image relevance, alt-text mismatch, crop/scale, layout, primary CTA visibility/readability, and responsive issues. "
                "Do not propose edits in this review. Do not claim measured contrast or pass status based on visual guess.\n"
                f"<code_audit>\n{code_assessments[name]}\n</code_audit>\n"
                f"<page_html>\n{read_html(page['source'])}\n</page_html>"
            )
            assessment = invoke_workers_ai(f"assessment-visual-{name}", repair_prompt, visual_user, screenshot_paths(page, "source"), audit_dir, model, account_id, token, 4500)
            assessments[name] = ensure_assessment_rubric(assessment, name, repair_prompt, audit_dir, model, account_id, token)
            assessments[name], contradicted = remove_contradicted_missing_attribute_claims(assessments[name], read_html(page["source"]))
            (audit_dir / f"source-claim-validation-{name}.json").write_text(
                json.dumps({"rejected_contradictions": contradicted}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            (audit_dir / f"assessment-{name}.txt").write_text(assessments[name], encoding="utf-8")

    baseline_qa_results: dict[str, dict] = {}
    source_candidate_dir = Path(args.candidate_output_dir).resolve() if args.candidate_output_dir else None
    for page in pages:
        name = page["name"]
        baseline_qa_results[name] = run_repository_qa(
            page["source"], f"{name}-source", page["url"], run_dir, source_candidate_dir,
        )
        (audit_dir / f"repository-qa-{name}-source.json").write_text(
            json.dumps(baseline_qa_results[name], indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )

    if args.resume_directory and (comparative_path.exists() or (audit_dir / "recommendations.json").exists()):
        comparative = comparative_path.read_text(encoding="utf-8") if comparative_path.exists() else (audit_dir / "recommendations.json").read_text(encoding="utf-8")
    else:
        all_assessments = "\n".join(
            f"--- {page['name']} ---\n{assessments[page['name']]}\n"
            f"Git Content deterministic baseline QA:\n{repository_qa_prompt(baseline_qa_results[page['name']])}"
            for page in pages
        )
        comparative = invoke_workers_ai(
            "comparative-recommendations", repair_prompt,
            "STATE B — PASS 1 REPAIR PRIORITIES\nCompare the completed code and screenshot assessments. Prioritize only evidence-backed repairs; do not propose a redesign. Return the requested comparative JSON.\n" + all_assessments,
            [], audit_dir, model, account_id, token, 6000,
        )
        comparative_path.write_text(comparative, encoding="utf-8")
        (audit_dir / "recommendations.json").write_text(comparative, encoding="utf-8")

    # A resumable run can continue at Pass 2 when every saved Pass 1 output passed
    # its final QA gate. This avoids repeating costly inference after a later failure.
    pass1_qa_reports: dict[str, str] = {}
    pass1_repo_qa_results: dict[str, dict] = {}
    reuse_pass1 = bool(args.resume_directory)
    if reuse_pass1:
        for page in pages:
            name = page["name"]
            pass1_path = run_dir / f"{name}-pass1.html"
            reports = sorted(
                (audit_dir.glob(f"pass1-final-qa*-{name}.txt")),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            passed_report = None
            for report_path in reports:
                report_text = report_path.read_text(encoding="utf-8")
                try:
                    if validate_qa_report(report_text, name, "Pass 1 final")["status"] == "pass":
                        passed_report = report_text
                        break
                except (ValueError, RuntimeError):
                    continue
            if not pass1_path.is_file() or passed_report is None:
                reuse_pass1 = False
                break
            page["pass1"] = pass1_path
            pass1_qa_reports[name] = passed_report

    for page in pages:
        name = page["name"]
        if reuse_pass1:
            page["pass1_draft"] = run_dir / f"{name}-pass1-draft.html"
            continue
        draft = run_dir / f"{name}-pass1-draft.html"
        patch_path = audit_dir / f"pass1-repair-edits-{name}.txt"
        if args.resume_directory and patch_path.exists():
            draft_edits = patch_path.read_text(encoding="utf-8")
        else:
            user = f"STATE C — PASS 1 REPAIR {name}\nAssessment:\n{assessments[name]}\nRepair priorities:\n{comparative}\nGit Content deterministic baseline QA (blocking failures must be repaired when supported by the source and existing page purpose):\n{repository_qa_prompt(baseline_qa_results[name])}\nOriginal complete HTML:\n<page_html>\n{read_html(page['source'])}\n</page_html>\nMake minimal corrections to proven flaws only. Do not redesign or invent content, sections, controls, or functionality. Repair an already-intended form only when the source proves its existing fields, submit control, or orphaned form attributes; do not invent fields, endpoints, or behavior. Return exact JSON edits with valid repair criterion IDs."
            draft_edits = invoke_workers_ai(f"pass1-repair-edits-{name}", repair_prompt, user, [], audit_dir, model, account_id, token, 5000)
        revised = apply_model_edits_with_anchor_repair(read_html(page["source"]), draft_edits, audit_dir / f"rejected-pass1-repair-edits-{name}.json", f"pass1-repair-{name}", repair_prompt, audit_dir, model, account_id, token)
        if not re.search(r"(?is)(<!doctype\s+html|<html\b)", revised) or not re.search(r"(?is)</html>\s*$", revised):
            raise RuntimeError(f"Draft for {name} is not a complete HTML document.")
        draft.write_text(revised, encoding="utf-8")
        page["pass1_draft"] = draft
        if not args.code_only:
            page["pass1_draft_hero"] = shots_dir / f"{name}-pass1-draft-hero.png"
            page["pass1_draft_section"] = shots_dir / f"{name}-pass1-draft-section.png"
            page["pass1_draft_mobile"] = shots_dir / f"{name}-pass1-draft-mobile.png"
            for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                save_screenshot(draft, page[f"pass1_draft_{key}"], width, height, page["url"], "section" if key == "section" else "top")

    for page in pages:
        name = page["name"]
        if reuse_pass1:
            pass1_repo_qa_results[name] = run_repository_qa(
                page["pass1"], f"{name}-pass1-reused", page["url"], run_dir, source_candidate_dir,
            )
            (audit_dir / f"repository-qa-{name}-pass1-reused.json").write_text(
                json.dumps(pass1_repo_qa_results[name], indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            continue
        instruction = "STATE D — PASS 1 CODE-ONLY REPAIR QA. Make no visual claims." if args.code_only else "STATE D — PASS 1 REPAIR QA. Review HTML and attached screenshots (desktop hero, desktop content section, mobile hero). Identify defects only; do not suggest design enhancements."
        user = f"{instruction}\nConcept: {name}\nAssessment:\n{assessments[name]}\nRepair priorities:\n{comparative}\nPass 1 repair draft:\n<page_html>\n{read_html(page['pass1_draft'])}\n</page_html>\nReturn the requested QA JSON."
        images = [] if args.code_only else screenshot_paths(page, "pass1_draft")
        pass1_qa_reports[name] = invoke_workers_ai(f"pass1-qa-{name}", repair_prompt, user, images, audit_dir, model, account_id, token, 5000)
        pass1_qa_reports[name], _ = ensure_qa_report(pass1_qa_reports[name], name, "Pass 1", repair_prompt, audit_dir, model, account_id, token)

    # Finish Pass 1 by applying only the repair findings from its QA report.
    for page in pages:
        name = page["name"]
        if reuse_pass1:
            continue
        user = f"STATE E — FINISH PASS 1 REPAIRS FOR {name}\nAssessment:\n{assessments[name]}\nRepair priorities:\n{comparative}\nPass 1 QA report:\n{pass1_qa_reports[name]}\nCurrent Pass 1 draft:\n<page_html>\n{read_html(page['pass1_draft'])}\n</page_html>\nApply only necessary defect corrections. Do not enhance the design. Return exact repair edits or an empty edits array."
        pass1_edits = invoke_workers_ai(f"pass1-final-edits-{name}", repair_prompt, user, [], audit_dir, model, account_id, token, 5000)
        pass1_html = apply_model_edits_with_anchor_repair(read_html(page["pass1_draft"]), pass1_edits, audit_dir / f"rejected-pass1-final-edits-{name}.json", f"pass1-finalize-{name}", repair_prompt, audit_dir, model, account_id, token)
        if not re.search(r"(?is)(<!doctype\s+html|<html\b)", pass1_html) or not re.search(r"(?is)</html>\s*$", pass1_html):
            raise RuntimeError(f"Pass 1 output for {name} is not a complete HTML document.")
        page["pass1"] = run_dir / f"{name}-pass1.html"
        page["pass1"].write_text(pass1_html, encoding="utf-8")

    # Gate Pass 2 on both the selected-provider review and Git Content's deterministic QA.
    for page in pages:
        name = page["name"]
        if not args.code_only:
            page["pass1_hero"] = shots_dir / f"{name}-pass1-hero.png"
            page["pass1_section"] = shots_dir / f"{name}-pass1-section.png"
            page["pass1_mobile"] = shots_dir / f"{name}-pass1-mobile.png"
            for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                if not page[f"pass1_{key}"].is_file():
                    save_screenshot(page["pass1"], page[f"pass1_{key}"], width, height, page["url"], "section" if key == "section" else "top")
        if reuse_pass1:
            continue
        pass1_verification = None
        # Allow three model correction rounds, with deterministic QA rerun after
        # each one. The fourth QA pass is verification only; failure stays pending.
        for attempt in range(4):
            verify_instruction = "STATE E2 — PASS 1 FINAL CODE-ONLY GATE. No visual claims." if args.code_only else "STATE E2 — PASS 1 FINAL GATE. Verify the final repaired HTML and attached desktop hero, desktop section, and mobile hero screenshots. Pass only when every previously supported issue is resolved. Do not suggest design enhancements."
            current_repo_qa = run_repository_qa(
                page["pass1"], f"{name}-pass1-attempt-{attempt + 1}", page["url"], run_dir, source_candidate_dir,
            )
            pass1_repo_qa_results[name] = current_repo_qa
            (audit_dir / f"repository-qa-{name}-pass1-attempt-{attempt + 1}.json").write_text(
                json.dumps(current_repo_qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            repo_qa_text = repository_qa_prompt(current_repo_qa)
            verify_user = f"{verify_instruction}\nConcept: {name}\nOriginal repair assessment and issue ledger:\n{assessments[name]}\nFirst Pass 1 QA (historical findings remain open until exact current evidence shows resolution):\n{pass1_qa_reports[name]}\nGit Content deterministic QA (authoritative; do not omit or overrule a failed check):\n{repo_qa_text}\nCurrent corrected Pass 1 HTML:\n<page_html>\n{read_html(page['pass1'])}\n</page_html>\nVerify each earlier issue against the current HTML and screenshots. A finding may be marked resolved only with exact current evidence. Claims that an attribute or element is missing must be checked against the actual source. Return the Pass 1 QA JSON."
            verify_images = [] if args.code_only else screenshot_paths(page, "pass1")
            verify_name = "pass1-final-qa" if attempt == 0 else f"pass1-final-qa-recheck-{attempt}"
            verification_text = invoke_workers_ai(f"{verify_name}-{name}", repair_prompt, verify_user, verify_images, audit_dir, model, account_id, token, 5000)
            verification_text, pass1_verification = ensure_qa_report(verification_text, name, "Pass 1 final", repair_prompt, audit_dir, model, account_id, token)
            if pass1_verification["status"] == "pass" and current_repo_qa.get("automated_success") is not False:
                pass1_qa_reports[name] = verification_text
                break
            if attempt == 3:
                unresolved = list(pass1_verification.get("remaining_issues", []))
                if current_repo_qa.get("automated_success") is False:
                    unresolved.append({
                        "criterion_id": "CODE-01", "priority": "high",
                        "evidence": "Git Content deterministic blockers: " + ", ".join(current_repo_qa.get("blocking_failures", [])),
                        "user_impact": "A required repository structural or browser check remains unresolved.",
                        "correction": "Resolve the listed deterministic blockers or leave this candidate pending review.",
                        "confidence": "high",
                    })
                pass1_verification = {"concept": name, "status": "revise", "remaining_issues": unresolved, "deterministic_repository_qa_passed": current_repo_qa.get("automated_success") is not False}
                pass1_qa_reports[name] = json.dumps(pass1_verification, indent=2, ensure_ascii=False)
                (audit_dir / f"pass1-final-qa-blocked-{name}.json").write_text(pass1_qa_reports[name] + "\n", encoding="utf-8")
                break
            fix_user = f"STATE E3 — REPAIR PASS 1 GATE FINDINGS FOR {name}\nPass 1 final QA report (retain unresolved findings until fixed):\n{verification_text}\nGit Content deterministic QA blockers (all are authoritative):\n{repo_qa_text}\nOriginal customer HTML (restoration reference; preserve its demonstrated sections, copy, forms, fields, contact details, and links):\n<source_html>\n{read_html(page['source'])}\n</source_html>\nCurrent corrected HTML to edit:\n<page_html>\n{read_html(page['pass1'])}\n</page_html>\nUse the failed checks as a concrete repair list. Fix each blocker with the smallest valid HTML/CSS edits. You may restore omitted content only from the original source above; do not invent copy, sections, fields, endpoints, or behavior. For contrast failures, change the relevant foreground/background CSS colors and verify the measured target; hiding or relabeling the CTA is not a fix. Preserve every image src and srcset value exactly. If an issue cannot be resolved from supplied evidence, do not guess; leave it for review. Return exact JSON edits using repair criterion IDs."
            gate_images = [] if args.code_only else screenshot_paths(page, "pass1")
            gate_edits = invoke_workers_ai(f"pass1-gate-repair-{name}-{attempt + 1}", repair_prompt, fix_user, gate_images, audit_dir, model, account_id, token, 5000)
            gate_html = apply_model_edits_with_anchor_repair(read_html(page["pass1"]), gate_edits, audit_dir / f"rejected-pass1-gate-repair-{name}-{attempt + 1}.json", f"pass1-gate-repair-{name}-{attempt + 1}", repair_prompt, audit_dir, model, account_id, token)
            page["pass1"].write_text(gate_html, encoding="utf-8")
            if not args.code_only:
                for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                    save_screenshot(page["pass1"], page[f"pass1_{key}"], width, height, page["url"], "section" if key == "section" else "top")

    # Failed gates retain their Pass 1 HTML as a pending candidate and never enter Pass 2.
    final_qa_results: dict[str, dict] = {}
    pass2_pages = []
    for page in pages:
        name = page["name"]
        repo_passed = pass1_repo_qa_results.get(name, {}).get("automated_success") is not False
        model_gate_passed = False
        if name in pass1_qa_reports:
            try:
                model_gate_passed = validate_qa_report(pass1_qa_reports[name], name, "Pass 1 final")["status"] == "pass"
            except (ValueError, RuntimeError):
                model_gate_passed = False
        if repo_passed and model_gate_passed:
            pass2_pages.append(page)
            continue
        final_path = run_dir / f"{name}.html"
        shutil.copy2(page["pass1"], final_path)
        if not args.code_only:
            for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                save_screenshot(final_path, shots_dir / f"{name}-final-{key}.png", width, height, page["url"], "section" if key == "section" else "top")
        gate_report = pass1_repo_qa_results.get(name, {})
        final_qa_results[name] = {
            "status": "revise",
            "remaining_issues": [
                {"criterion_id": "CODE-01", "priority": "high", "evidence": ", ".join(gate_report.get("blocking_failures", [])) or "Pass 1 model QA did not pass", "user_impact": "The candidate has not cleared every required review gate.", "correction": "Resolve the reported gate findings; retain as pending until then.", "confidence": "high"}
            ],
            "pass2_skipped": True,
        }

    # Pass 2 starts only from pages cleared by both gates.
    for page in pass2_pages:
        name = page["name"]
        direction_user = f"STATE F — PASS 2 DESIGN DIRECTION FOR {name}\nAudience/context: use the business category and location context supplied with this target, if any; treat it as unverified unless confirmed by the page source.\nOriginal assessment, including strengths and page identity:\n{assessments[name]}\nPass 1 repair QA:\n{pass1_qa_reports[name]}\nCross-page repair context:\n{comparative}\nCorrected Pass 1 HTML:\n<page_html>\n{read_html(page['pass1'])}\n</page_html>\nUse the appended Pass 2 enhancement rubric to propose a restrained, page-specific design direction. This is a proposal for this page, not a rewrite. Return JSON with concept, identity_to_preserve, design_direction, design_system (pattern, palette_roles, typography, spacing, imagery, interactions), prioritized_enhancements (each with criterion_id, priority, design_rationale, evidence, user_benefit, change, confidence), and avoid. Do not add business claims or form behavior."
        direction_images = [] if args.code_only else screenshot_paths(page, "pass1")
        direction_path = audit_dir / f"pass2-design-direction-{name}.txt"
        page["design_direction"] = direction_path.read_text(encoding="utf-8") if args.resume_directory and direction_path.exists() else invoke_workers_ai(f"pass2-design-direction-{name}", enhancement_prompt, direction_user, direction_images, audit_dir, model, account_id, token, 6000)
        design_draft = run_dir / f"{name}-pass2-draft.html"
        if not (args.resume_directory and design_draft.exists()):
            design_user = f"STATE G — APPLY PASS 2 DESIGN ENHANCEMENTS TO {name}\nPass 1 corrected HTML:\n<page_html>\n{read_html(page['pass1'])}\n</page_html>\nPass 1 assessment and fixes to preserve:\n{assessments[name]}\n{pass1_qa_reports[name]}\nCross-page repair context:\n{comparative}\nThe Pass 2 design direction:\n{page['design_direction']}\nApply only the highest-priority evidence-backed enhancements. Keep all Pass 1 corrections, preserve this concept's identity, and do not introduce unsupported facts or functionality. Return at most three exact JSON edits with ENH criterion IDs, or an empty edits array if the existing design should remain. Each `find` and `replace` must be a small, local snippet of at most 1200 characters; never output a full section or whole document. Prefer an attribute, concise CSS rule, or single component-level change. Ensure every find snippet is copied from the supplied HTML and every replacement is complete valid HTML."
            saved_edits_path = audit_dir / f"pass2-enhancement-edits-{name}.txt"
            design_edits = None
            if args.resume_directory and saved_edits_path.exists():
                cached_edits = saved_edits_path.read_text(encoding="utf-8")
                try:
                    if isinstance(model_json(cached_edits).get("edits"), list):
                        design_edits = cached_edits
                except ValueError:
                    pass
            if design_edits is None:
                design_edits = invoke_workers_ai(f"pass2-enhancement-edits-{name}", enhancement_prompt, design_user, [], audit_dir, model, account_id, token, 8000)
            design_html = apply_model_edits_with_anchor_repair(read_html(page["pass1"]), design_edits, audit_dir / f"rejected-pass2-enhancement-edits-{name}.json", f"pass2-enhance-{name}", enhancement_prompt, audit_dir, model, account_id, token)
            if not re.search(r"(?is)(<!doctype\s+html|<html\b)", design_html) or not re.search(r"(?is)</html>\s*$", design_html):
                raise RuntimeError(f"Pass 2 draft for {name} is not a complete HTML document.")
            design_draft.write_text(design_html, encoding="utf-8")
        page["pass2_draft"] = design_draft
        if not args.code_only:
            page["pass2_draft_hero"] = shots_dir / f"{name}-pass2-draft-hero.png"
            page["pass2_draft_section"] = shots_dir / f"{name}-pass2-draft-section.png"
            page["pass2_draft_mobile"] = shots_dir / f"{name}-pass2-draft-mobile.png"
            for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                if not (args.resume_directory and page[f"pass2_draft_{key}"].is_file()):
                    save_screenshot(design_draft, page[f"pass2_draft_{key}"], width, height, page["url"], "section" if key == "section" else "top")

    pass2_qa_reports: dict[str, str] = {}
    for page in pass2_pages:
        name = page["name"]
        cached_qa = audit_dir / f"pass2-qa-{name}.txt"
        if args.resume_directory and cached_qa.exists():
            try:
                validate_qa_report(cached_qa.read_text(encoding="utf-8"), name, "Pass 2")
                pass2_qa_reports[name] = cached_qa.read_text(encoding="utf-8")
                continue
            except (ValueError, RuntimeError):
                pass
        instruction = "STATE H — PASS 2 CODE-ONLY QA. Make no visual claims." if args.code_only else "STATE H — PASS 2 VISUAL AND CODE QA. Attached screenshots are desktop hero, desktop content section, and mobile hero, in that order."
        user = f"{instruction}\nConcept: {name}\nPass 1 QA and corrected source:\n{pass1_qa_reports[name]}\n{read_html(page['pass1'])}\nPass 2 design direction:\n{page['design_direction']}\nPass 2 revised HTML:\n<page_html>\n{read_html(page['pass2_draft'])}\n</page_html>\nCheck that the Pass 1 repairs remain correct and the Pass 2 enhancements are coherent, responsive, and accessible. Return the requested QA JSON; for remaining issues use ENH criteria for design-only issues and repair criteria for regressions."
        images = [] if args.code_only else screenshot_paths(page, "pass2_draft")
        pass2_qa_reports[name] = invoke_workers_ai(f"pass2-qa-{name}", enhancement_prompt, user, images, audit_dir, model, account_id, token, 5000)
        pass2_qa_reports[name], _ = ensure_qa_report(pass2_qa_reports[name], name, "Pass 2", enhancement_prompt, audit_dir, model, account_id, token)

    for page in pass2_pages:
        name = page["name"]
        final_path = run_dir / f"{name}.html"
        if args.resume_directory and final_path.exists():
            continue
        user = f"STATE I — FINALIZE PASS 2 FOR {name}\nPass 1 corrected HTML (preserve these repairs):\n<pass1_html>\n{read_html(page['pass1'])}\n</pass1_html>\nPass 2 design direction:\n{page['design_direction']}\nPass 2 QA report:\n{pass2_qa_reports[name]}\nCurrent Pass 2 HTML:\n<page_html>\n{read_html(page['pass2_draft'])}\n</page_html>\nApply only supported corrections. Use the relevant ENH or repair criterion ID for each exact edit. If QA passes, return an empty edits array."
        cached_final_path = audit_dir / f"pass2-final-edits-{name}.txt"
        final_edits = None
        if args.resume_directory and cached_final_path.exists():
            cached_final = cached_final_path.read_text(encoding="utf-8")
            try:
                if isinstance(model_json(cached_final).get("edits"), list):
                    final_edits = cached_final
            except ValueError:
                pass
        if final_edits is None:
            final_edits = invoke_workers_ai(f"pass2-final-edits-{name}", enhancement_prompt, user, [], audit_dir, model, account_id, token, 10000)
        final_html = apply_model_edits_with_anchor_repair(read_html(page["pass2_draft"]), final_edits, audit_dir / f"rejected-pass2-final-edits-{name}.json", f"pass2-finalize-{name}", enhancement_prompt, audit_dir, model, account_id, token)
        if not re.search(r"(?is)(<!doctype\s+html|<html\b)", final_html) or not re.search(r"(?is)</html>\s*$", final_html):
            raise RuntimeError(f"Final output for {name} is not a complete HTML document.")
        final_path.write_text(final_html, encoding="utf-8")

    # Review the actual final files after State I; preserve any unresolved items in the audit.
    for page in pages:
        name = page["name"]
        if name in final_qa_results:
            continue
        final_path = run_dir / f"{name}.html"
        cached_reports = sorted(audit_dir.glob(f"pass2-final-qa*-{name}.txt"), key=lambda item: item.stat().st_mtime, reverse=True)
        if args.resume_directory and cached_reports and cached_reports[0].stat().st_mtime >= final_path.stat().st_mtime:
            try:
                cached_report = validate_qa_report(cached_reports[0].read_text(encoding="utf-8"), name, "Pass 2 final")
                final_qa_results[name] = cached_report
                continue
            except (ValueError, RuntimeError):
                pass
        if not args.code_only:
            page["final_hero"] = shots_dir / f"{name}-final-hero.png"
            page["final_section"] = shots_dir / f"{name}-final-section.png"
            page["final_mobile"] = shots_dir / f"{name}-final-mobile.png"
        verification = None
        for attempt in range(3):
            if not args.code_only:
                for key, width, height in (("hero", 1440, 1000), ("section", 1440, 1000), ("mobile", 390, 844)):
                    if not page[f"final_{key}"].is_file():
                        save_screenshot(final_path, page[f"final_{key}"], width, height, page["url"], "section" if key == "section" else "top")
            instruction = "STATE J — FINAL PASS 2 CODE-ONLY GATE. Make no visual claims." if args.code_only else "STATE J — FINAL PASS 2 VISUAL AND CODE GATE. Review the actual final HTML and its desktop hero, desktop content-section, and mobile hero screenshots."
            verify_user = f"{instruction}\nConcept: {name}\nPass 1 final repair QA (historical context only):\n{pass1_qa_reports[name]}\nPass 2 draft QA (historical context only; State I may have corrected these):\n{pass2_qa_reports[name]}\nFinal HTML after State I corrections:\n<page_html>\n{read_html(final_path)}\n</page_html>\nAudit only the current final HTML and attached current screenshots. Prior reports are not evidence: independently verify every candidate issue before including it. For a source issue, cite a short exact snippet that is present in this final HTML. For a visual issue, describe the supplied final screenshot and viewport. Do not repeat a finding if it is corrected, absent from this file, or unsupported by these screenshots. Check that an empty form is an actual empty form element, not just a CSS selector. Return status pass only when no supported repair or enhancement issue remains. Return the requested QA JSON."
            verify_images = [] if args.code_only else [page[f"final_{key}"] for key in ("hero", "section", "mobile")]
            qa_name = f"pass2-final-qa-{name}" if attempt == 0 else f"pass2-final-qa-recheck-{attempt}-{name}"
            verify_text = invoke_workers_ai(qa_name, enhancement_prompt, verify_user, verify_images, audit_dir, model, account_id, token, 5000)
            verify_text, verification = ensure_qa_report(verify_text, name, "Pass 2 final", enhancement_prompt, audit_dir, model, account_id, token)
            if verification["status"] == "pass":
                break
            if verification["status"] == "invalid":
                break
            if attempt == 2:
                break
            fix_user = f"STATE J2 — FINAL PASS 2 REPAIRS FOR {name}\nFinal QA report:\n{verify_text}\nCurrent final HTML:\n<page_html>\n{read_html(final_path)}\n</page_html>\nApply only the listed supported repairs. Use exact snippets and the cited criterion IDs. Return JSON edits only."
            fix_text = invoke_workers_ai(f"pass2-final-gate-repair-{name}-{attempt + 1}", enhancement_prompt, fix_user, [], audit_dir, model, account_id, token, 8000)
            corrected = apply_model_edits_with_anchor_repair(read_html(final_path), fix_text, audit_dir / f"rejected-pass2-final-gate-repair-{name}-{attempt + 1}.json", f"pass2-final-gate-repair-{name}-{attempt + 1}", enhancement_prompt, audit_dir, model, account_id, token)
            if not re.search(r"(?is)(<!doctype\s+html|<html\b)", corrected) or not re.search(r"(?is)</html>\s*$", corrected):
                raise RuntimeError(f"Final Pass 2 gate repair for {name} did not preserve a complete HTML document.")
            final_path.write_text(corrected, encoding="utf-8")
            if not args.code_only:
                for key in ("hero", "section", "mobile"):
                    page[f"final_{key}"].unlink(missing_ok=True)
        if verification is None:
            raise RuntimeError(f"Final Pass 2 QA did not produce a report for {name}.")
        final_qa_results[name] = verification

    diff_paths: dict[str, str] = {}
    for page in pages:
        name = page["name"]
        source_text = read_html(page["source"])
        final_text = read_html(run_dir / f"{name}.html")
        diff_text = "".join(difflib.unified_diff(
            source_text.splitlines(keepends=True), final_text.splitlines(keepends=True),
            fromfile=f"source/{name}.html", tofile=f"{name}.html",
        ))
        diff_path = audit_dir / f"{name}-before-after.diff"
        diff_path.write_text(diff_text, encoding="utf-8")
        diff_paths[name] = str(diff_path.relative_to(run_dir))

    manifest = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "provider": provider,
        "model": model,
        "reviewMode": "code-only; no visual assessment" if args.code_only else "source and visual",
        "urls": urls,
        "sourceKind": "private_results_inline_html" if args.source_html_file else "remote_url",
        "sourceCandidateId": str(target.get("source_candidate_id", "")),
        "target": {key: target.get(key, "") for key in ("business", "category", "location")},
        "outputs": [f"{page['name']}.html" for page in pages],
        "pass1Outputs": [f"{page['name']}-pass1.html" for page in pages],
        "beforeAfterDiffs": diff_paths,
        "pass1RepositoryQA": {
            name: {
                "available": report.get("available", False),
                "automatedSuccess": report.get("automated_success"),
                "blockingFailures": report.get("blocking_failures", []),
            }
            for name, report in pass1_repo_qa_results.items()
        },
        "pass2Skipped": [page["name"] for page in pages if page not in pass2_pages],
        "pass1GatePassed": all(page in pass2_pages for page in pages),
        "finalQA": {name: {"status": report["status"], "remainingIssueCount": len(report.get("remaining_issues", [])) if report["status"] != "invalid" else None, "reportParsed": report["status"] != "invalid"} for name, report in final_qa_results.items()},
        "finalQAPassed": all(report["status"] == "pass" for report in final_qa_results.values()),
        "pipeline": ["download", f"{provider}-pass1-code-audit", "source-screenshots", f"{provider}-pass1-visual-review", "repository-qa-baseline", f"{provider}-repair-priorities", "pass1-minimal-repairs", "pass1-visual-code-qa", "pass1-final-repair", "repository-qa-pass1", f"{provider}-pass2-design-direction", "pass2-design-enhancement", "pass2-visual-code-qa", "pass2-final-corrections", "pass2-final-visual-code-gate"] if pass2_pages and not args.code_only else (["download", f"{provider}-pass1-code-audit", "source-screenshots", f"{provider}-pass1-visual-review", "repository-qa-baseline", f"{provider}-repair-priorities", "pass1-minimal-repairs", "pass1-visual-code-qa", "pass1-final-repair", "repository-qa-pass1", "pass2-skipped-pending-gates"] if not args.code_only else ["download", f"{provider}-pass1-code-assessment", "repository-qa-baseline", "pass1-repairs", "pass1-code-qa", "repository-qa-pass1", "pass2-skipped-or-not-configured"]),
        "screenshotsSentToInferenceProvider": not args.code_only,
        "assessmentRubric": rubric_metadata,
        "enhancementRubric": {"file": "enhancement-rubric.md", "sources": ["UI/UX Pro Max", "Apple Design for the web"]},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary_lines = [
        f"# HTML assessment run — {provider}", "",
        f"Provider/model: `{provider}` / `{model}`", f"Review mode: {manifest['reviewMode']}",
        "", "## Before and after", "",
        "| Page | Downloaded source | Pass 1 repaired | Final Pass 2 | Unified diff | Final QA |",
        "|---|---|---|---|---|---|",
    ]
    for page in pages:
        name = page["name"]
        report = final_qa_results[name]
        status = report["status"]
        result = "invalid (response could not be parsed)" if status == "invalid" else f"{status} ({len(report.get('remaining_issues', []))} issues)"
        summary_lines.append(f"| {name} | `source/{name}.html` | `{name}-pass1.html` | `{name}.html` | `audit/{name}-before-after.diff` | {result} |")
    summary_lines.extend(["", f"All final Pass 2 gates passed: **{manifest['finalQAPassed']}**", "", "Source URLs were not changed. See `manifest.json` and the audit folder for per-state assessments, QA reports, edit responses, and screenshots."])
    (run_dir / "run-summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    if args.candidate_output_dir:
        candidate_dir = Path(args.candidate_output_dir).resolve()
        if not args.update_existing_candidate:
            candidate_dir.mkdir(parents=True, exist_ok=False)
        final_html = run_dir / f"{pages[0]['name']}.html"
        files_dir = candidate_dir / "files"
        inline_dir = files_dir / "inlined"
        debug_dir = candidate_dir / "debug"
        inline_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)
        attempt_dir = None
        if args.update_existing_candidate:
            attempt_dir = debug_dir / "assessment-runs" / f"run-{run_id}-{run_attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            previous_state = attempt_dir / "previous-state"
            for relative in (
                Path("screenshots"), Path("browser_qa.json"), Path("checker_report.json"),
                Path("image_review.json"), Path("visual_review.json"), Path("review_templates"),
            ):
                existing = debug_dir / relative
                if existing.is_dir():
                    shutil.copytree(existing, previous_state / relative)
                elif existing.is_file():
                    (previous_state / relative).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(existing, previous_state / relative)
            for name in ("image_review.json", "visual_review.json"):
                (debug_dir / name).unlink(missing_ok=True)
        else:
            attempt_dir = debug_dir
        # Preserve the staged original before writing back to the in-place source path.
        original_source = source_dir / f"{pages[0]['name']}.html"
        preserve_original_inline_html(original_source, inline_dir)
        html_text = read_html(final_html)
        (files_dir / "index.html").write_text(html_text, encoding="utf-8")
        (inline_dir / "index.html").write_text(html_text, encoding="utf-8")
        styles = re.findall(r"<style\b[^>]*>([\s\S]*?)</style\s*>", html_text, flags=re.IGNORECASE)
        (files_dir / "styles.css").write_text("\n\n".join(styles), encoding="utf-8")
        evidence_zip = attempt_dir / "assessment-run.zip"
        with zipfile.ZipFile(evidence_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for evidence_file in run_dir.rglob("*"):
                if evidence_file.is_file():
                    archive.write(evidence_file, Path("assessment-run") / evidence_file.relative_to(run_dir))
        shutil.copy2(run_dir / "manifest.json", attempt_dir / "assessment-manifest.json")
        shutil.copy2(run_dir / "run-summary.md", attempt_dir / "run-summary.md")
        final_screenshots = debug_dir / "screenshots"
        final_screenshots.mkdir(parents=True, exist_ok=True)
        if not args.code_only:
            save_screenshot(final_html, final_screenshots / "desktop.png", 1440, 900, urls[0], "top", full_page=True)
            save_screenshot(final_html, final_screenshots / "mobile.png", 390, 844, urls[0], "top", full_page=True)
        model_review_passed = manifest["finalQAPassed"]
        notes_path = candidate_dir / "run_notes.json"
        run_notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
        run_notes.update({
            "status": "assessment_complete_pending_repo_qa",
            "html_assessment_job_id": str(target.get("job_id", "")),
            "html_assessment_source_candidate_id": str(target.get("source_candidate_id", "")),
            "automated_success": False,
            "final_success": False,
            "human_visual_review_status": "pending",
            "image_relevance_review_status": "pending",
            "html_assessment_model_review_passed": model_review_passed,
            "html_assessment_pass1_gate_passed": manifest["pass1GatePassed"],
            "html_assessment_repo_qa_passed": False,
            "html_assessment_provider": provider,
            "html_assessment_model": model,
            "source_url": urls[0],
            "html_assessment_workflow_id": run_id,
            "html_assessment_workflow_attempt": run_attempt,
            "html_assessment_review_mode": manifest["reviewMode"],
            "html_assessment_final_qa": manifest["finalQA"],
            "assessment_manifest": str((attempt_dir / "assessment-manifest.json").relative_to(candidate_dir).as_posix()),
            "assessment_evidence_archive": str(evidence_zip.relative_to(candidate_dir).as_posix()),
        })
        notes_path.write_text(json.dumps(run_notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (candidate_dir / "status.json").write_text(json.dumps(run_notes, indent=2), encoding="utf-8")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("cloudflare", "nvidia"), default="cloudflare", help="Inference provider (default: cloudflare).")
    parser.add_argument("--env-file", help="Credential file (provider default: ~/Documents/CLOUDFLARE_ENV.txt or ~/Documents/nvidia-api-key.txt).")
    parser.add_argument("--output-root", help="Directory for new timestamped runs.")
    parser.add_argument("--resume-directory", help="Resume using saved HTML and assessment files.")
    parser.add_argument("--code-only", action="store_true", help="Skip screenshots and visual assessment.")
    parser.add_argument("--urls", nargs="+", help="One or more page URLs to assess.")
    parser.add_argument("--target-json-file", help="Git Content target object with website, business, category, and location fields.")
    parser.add_argument("--source-html-file", help="Use an existing private inline HTML file as the page source instead of downloading the URL.")
    parser.add_argument("--business", help="Optional business context for the design pass.")
    parser.add_argument("--category", help="Optional industry/category context.")
    parser.add_argument("--location", help="Optional service-area context.")
    parser.add_argument("--candidate-output-dir", help="Explicit Git Content candidate directory to export into.")
    parser.add_argument("--update-existing-candidate", action="store_true", help="Update an existing private candidate in place after preserving its original inline HTML.")
    parser.add_argument("--results-root", help="Private results checkout root; derive the Git Content candidate directory from run metadata.")
    parser.add_argument("--site-slug", help="Required with --results-root; site slug used under results/.")
    parser.add_argument("--candidate-id", help="Candidate directory name (defaults to the GitHub run and attempt ID).")
    parser.add_argument("--workflow-id", help="Override GITHUB_RUN_ID for local dry runs.")
    parser.add_argument("--workflow-attempt", help="Override GITHUB_RUN_ATTEMPT for local dry runs.")
    args = parser.parse_args()
    try:
        run_dir = run(args)
        print(f"Review complete. Final pages and reports: {run_dir}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
