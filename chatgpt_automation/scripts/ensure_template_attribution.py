#!/usr/bin/env python3
"""Add required HTML5 UP attribution from the validated design reference."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _comment_value(value: object) -> str:
    """Keep metadata on one safe HTML-comment line."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("--", "- -")


def ensure_template_attribution(run_dir: Path) -> dict[str, object]:
    debug_dir = run_dir / "debug"
    reference_path = debug_dir / "design_reference.json"
    html_path = run_dir / "files" / "index.html"
    if not reference_path.is_file():
        raise RuntimeError("debug/design_reference.json is missing")
    if not html_path.is_file():
        raise RuntimeError("files/index.html is missing")

    audit = json.loads(reference_path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise RuntimeError("design reference audit must contain an object")
    status = audit.get("status")
    if status in {"none_selected", "skipped"}:
        return {"status": "not_required", "changed": False}
    if status != "selected":
        raise RuntimeError(f"design reference status is not valid: {status!r}")

    reference = audit.get("design_reference")
    if not isinstance(reference, dict):
        raise RuntimeError("selected design reference is missing")
    name = _comment_value(reference.get("name"))
    template_url = _comment_value(reference.get("template_url"))
    license_url = _comment_value(reference.get("license_url"))
    if not all((name, template_url, license_url)):
        raise RuntimeError("selected design reference needs name, template_url, and license_url")

    html = html_path.read_text(encoding="utf-8")
    comments = "\n".join(re.findall(r"<!--[\s\S]*?-->", html)).lower()
    if all(value.lower() in comments for value in (name, template_url, license_url)) and re.search(
        r"\b(adapted|adaptation)\b", comments
    ):
        return {"status": "already_present", "changed": False}

    attribution = (
        f"<!-- Adapted from {name}; source: {template_url}; license: {license_url}. "
        "The original code, content, and assets are tailored for this business. -->"
    )
    html_path.write_text(f"{attribution}\n{html}", encoding="utf-8")
    return {"status": "inserted", "changed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    args = parser.parse_args()
    result = ensure_template_attribution(args.run_folder.resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
