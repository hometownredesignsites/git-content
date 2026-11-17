#!/usr/bin/env python3
"""Print a privacy-safe, concise failure category for a candidate run."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


FAILURE_LABELS = {
    "captcha_required": "ChatGPT access blocked by a CAPTCHA or human-verification gate",
    "login_required": "ChatGPT requires sign-in",
    "rate_limited": "ChatGPT rate or usage limit reached",
    "conversation_gated": "ChatGPT conversation is gated or unavailable",
    "service_error": "ChatGPT reported a service or connection error",
    "empty_response": "ChatGPT returned an empty response",
    "composer_not_found": "ChatGPT composer was not found before prompt submission",
    "response_format_rejected": "response did not match the required format",
    "design_reference_error": "design-reference assessment failed",
    "exchange_error": "ChatGPT response exchange failed",
}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def summarize(candidate: Path) -> str:
    checkpoint = read_json(candidate / "chunks" / "sequence_checkpoint.json")
    last_error = checkpoint.get("last_error")
    if isinstance(last_error, dict):
        classification = str(last_error.get("classification", ""))
        if classification in FAILURE_LABELS:
            return FAILURE_LABELS[classification]

    report = read_json(candidate / "debug" / "checker_report.json")
    blocking = report.get("blocking_failures", [])
    if isinstance(blocking, list):
        names = [
            item for item in blocking
            if isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", item)
        ]
        if names:
            visible = ", ".join(names[:4])
            extra = f" (+{len(names) - 4} more)" if len(names) > 4 else ""
            return f"automated quality checks failed: {visible}{extra}"

    notes = read_json(candidate / "run_notes.json")
    status = str(notes.get("status", ""))
    if status.endswith("_failed"):
        return f"candidate pipeline stage failed ({status.removesuffix('_failed')})"
    return "candidate did not pass; detailed trace is saved privately"


if __name__ == "__main__":
    print(summarize(Path(sys.argv[1])))
