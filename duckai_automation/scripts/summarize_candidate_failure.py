#!/usr/bin/env python3
"""Emit a concise, privacy-safe failure reason for a saved candidate."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SAFE_CATEGORIES = {
    "access_gate": "Duck.ai guest chat was gated or unavailable",
    "prompt_budget": "generation prompt exceeded the compact prompt budget",
    "source_assessment": "source assessment did not return traceable, valid facts",
    "response_capture": "Duck.ai response did not match the required chunk format",
    "browser_qa": "rendered browser checks failed",
    "candidate_quality": "candidate failed automated quality checks",
    "unknown": "candidate failed before producing a complete report",
}


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def summarize(candidate: Path) -> str:
    notes = _load(candidate / "run_notes.json")
    category = notes.get("failure_category")
    if category in SAFE_CATEGORIES:
        return SAFE_CATEGORIES[category]
    report = _load(candidate / "debug" / "checker_report.json")
    failures = report.get("blocking_failures", [])
    if isinstance(failures, list):
        safe = [item for item in failures if isinstance(item, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", item)]
        if safe:
            return "automated checks failed: " + ", ".join(safe[:4])
    if notes.get("status") == "automated_checks_failed":
        return "candidate failed automated quality checks; inspect the private checker report"
    return "candidate failed before producing a complete report; inspect private debug artifacts"


if __name__ == "__main__":
    print(summarize(Path(sys.argv[1])))
