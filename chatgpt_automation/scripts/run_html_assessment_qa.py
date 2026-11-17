"""Run Git Content's existing browser and structural QA on an HTML Assessment candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(candidate: Path) -> dict:
    candidate = candidate.resolve()
    debug = candidate / "debug"
    debug.mkdir(parents=True, exist_ok=True)
    request = (
        "Review this existing customer website page. Preserve its demonstrated content, services, "
        "and contact actions. Check the rendered desktop and mobile layout without requiring "
        "features that are not present in the source."
    )
    request_path = debug / "website_quality_request.txt"
    request_path.write_text(request + "\n", encoding="utf-8")

    browser = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "browser_qa.py"), str(candidate), request],
        capture_output=True, text=True, encoding="utf-8",
    )
    (debug / "html_assessment_browser_qa.log").write_text(
        (browser.stdout or "") + ("\n" + browser.stderr if browser.stderr else ""), encoding="utf-8"
    )
    browser_report_path = debug / "browser_qa.json"
    browser_report = json.loads(browser_report_path.read_text(encoding="utf-8")) if browser_report_path.is_file() else {}

    structural = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check_website.py"), str(candidate), request],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        report = json.loads(structural.stdout)
    except json.JSONDecodeError:
        report = {"automated_success": False, "final_success": False, "error": "structural checker did not return JSON"}
    report["html_assessment_browser_process_exit_code"] = browser.returncode
    report["html_assessment_structural_process_exit_code"] = structural.returncode
    report["browser_qa_status"] = browser_report.get("status", "missing")
    write_json(debug / "checker_report.json", report)

    # Keep Git Content's review templates as optional audit aids. Deterministic repository QA
    # decides final_success; the model's visual pass is advisory and no human review is required.
    review_templates = debug / "review_templates"
    review_templates.mkdir(parents=True, exist_ok=True)
    image_review = {
        "status": "pending",
        "images": [
            {"url": url, "observed_subject": "", "relevant": False, "crop_ok": False, "alt_accurate": False}
            for url in report.get("image_urls", [])
        ],
        "reviewer": "",
        "notes": "Inspect each rendered image and alt text; copy to ../image_review.json and record the result.",
    }
    visual_review = {
        "status": "pending",
        "reviewer": "",
        "checks": {
            "first_screen_hierarchy": False, "section_rhythm": False, "typography": False,
            "business_specificity": False, "footer": False,
        },
        "blocking_defects": ["Pending desktop and mobile review"],
        "screenshots": [
            {"viewport": "desktop", "path": "screenshots/desktop.png", "width": 1440, "height": 900},
            {"viewport": "mobile", "path": "screenshots/mobile.png", "width": 390, "height": 844},
        ],
        "notes": "Inspect both screenshots; copy to ../visual_review.json and record the result.",
    }
    write_json(review_templates / "image_review.json", image_review)
    write_json(review_templates / "visual_review.json", visual_review)

    notes_path = candidate / "run_notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
    repository_qa_passed = report.get("automated_success") is True
    pass1_gate_passed = notes.get("html_assessment_pass1_gate_passed") is not False
    automated_success = repository_qa_passed and pass1_gate_passed
    notes.update({
        "status": "assessment_success" if automated_success else ("pending_review" if repository_qa_passed else "automated_failed"),
        "html_assessment_revision": True,
        "html_assessment_status": "repo_qa_passed" if automated_success else ("pass1_gate_pending" if repository_qa_passed else "repo_qa_failed"),
        "html_assessment_repo_qa_passed": repository_qa_passed,
        "html_assessment_pass1_gate_passed": pass1_gate_passed,
        "automated_success": automated_success,
        "final_success": automated_success,
        "human_visual_review_status": "assessment_replaced_review" if automated_success else "pending",
        "image_relevance_review_status": "assessment_replaced_review" if automated_success else "pending",
        "html_assessment_model_visual_qa_advisory": notes.get("html_assessment_model_review_passed"),
        "browser_qa_status": browser_report.get("status", "missing"),
        "repository_qa_report": "debug/checker_report.json",
        "review_templates": [
            "debug/review_templates/image_review.json", "debug/review_templates/visual_review.json",
        ],
    })
    write_json(notes_path, notes)
    write_json(candidate / "status.json", notes)
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    notes = run(args.candidate)
    print(json.dumps({
        "status": notes["status"],
        "automated_success": notes["automated_success"],
        "final_success": notes["final_success"],
        "browser_qa_status": notes["browser_qa_status"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
