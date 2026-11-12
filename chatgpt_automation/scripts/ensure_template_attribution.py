#!/usr/bin/env python3
"""Add required HTML5 UP attribution from the validated design reference."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _comment_value(value: object) -> str:
    """Keep metadata on one safe comment line."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("--", "- -").replace("*/", "* /")


def ensure_template_attribution(run_dir: Path) -> dict[str, object]:
    debug_dir = run_dir / "debug"
    reference_path = debug_dir / "design_reference.json"
    html_path = run_dir / "files" / "index.html"
    css_path = run_dir / "files" / "styles.css"
    if not reference_path.is_file():
        raise RuntimeError("debug/design_reference.json is missing")
    if not html_path.is_file():
        raise RuntimeError("files/index.html is missing")
    if not css_path.is_file():
        raise RuntimeError("files/styles.css is missing")

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
    css = css_path.read_text(encoding="utf-8")
    details_present = lambda comment: bool(
        all(value.lower() in comment.lower() for value in (name, template_url, license_url))
        and re.search(r"\b(adapted|adaptation)\b", comment, re.IGNORECASE)
    )

    html_comments = "\n".join(re.findall(r"<!--[\s\S]*?-->", html))
    css_comments = "\n".join(re.findall(r"/\*[\s\S]*?\*/", css))
    html_changed = not details_present(html_comments)
    css_changed = not details_present(css_comments)
    if html_changed:
        html_attribution = (
            f"<!-- Adapted from {name}; source: {template_url}; license: {license_url}. "
            "The licensed scaffold was modified for this business; demo copy and assets were replaced. -->"
        )
        html_path.write_text(f"{html_attribution}\n{html}", encoding="utf-8")
    if css_changed:
        css_attribution = (
            f"/* Adapted from {name} CSS scaffold; source: {template_url}; license: {license_url}. "
            "Template layout rules were tailored for this business. */"
        )
        css_path.write_text(f"{css_attribution}\n{css}", encoding="utf-8")
    return {
        "status": "inserted" if html_changed or css_changed else "already_present",
        "changed": html_changed or css_changed,
        "html_changed": html_changed,
        "css_changed": css_changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    args = parser.parse_args()
    result = ensure_template_attribution(args.run_folder.resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
