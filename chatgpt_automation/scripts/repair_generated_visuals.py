#!/usr/bin/env python3
"""Apply small, context-aware visual repairs to generated stylesheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPAIR_MARKER = "/* Generated visual repairs: contact contrast and image-card labels. */"
REPAIR_CSS = """/* Generated visual repairs: contact contrast and image-card labels. */
.contact-actions .button.alt {
  color: #24372d !important;
  background-color: #fff !important;
  border-color: #24372d !important;
}

.tiles article .eyebrow {
  color: #fff !important;
  padding: .2em .45em;
  background-color: rgba(20, 25, 20, .72) !important;
  text-shadow: 0 1px 3px rgba(0, 0, 0, .85);
}
"""


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    css_path = candidate / "files" / "styles.css"
    report_path = candidate / "debug" / "visual_repair.json"
    result = {"status": "not_needed", "changed": False, "repairs": []}

    if not css_path.is_file():
        result.update(status="unavailable", reason="Generated stylesheet is missing.")
    else:
        css = css_path.read_text(encoding="utf-8", errors="replace")
        if REPAIR_MARKER in css:
            result["status"] = "already_applied"
        else:
            css_path.write_text(css.rstrip() + "\n\n" + REPAIR_CSS, encoding="utf-8")
            result.update(
                status="repaired",
                changed=True,
                repairs=[
                    "high-contrast contact button variant",
                    "white text for image-backed tile eyebrows",
                ],
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="Candidate run directory")
    args = parser.parse_args()
    return 0 if repair(args.candidate).get("status") not in {"unavailable", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
