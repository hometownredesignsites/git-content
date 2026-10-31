"""Re-evaluate a saved candidate after reviewers record image and visual decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def recheck(candidate: Path) -> dict:
    candidate = candidate.resolve()
    approved_root = (Path(__file__).resolve().parents[2] / "chatgpt-runs").resolve()
    try:
        candidate.relative_to(approved_root)
    except ValueError as error:
        raise RuntimeError("Candidate folder must be inside this repository's chatgpt-runs directory.") from error
    request_path = candidate / "debug" / "website_quality_request.txt"
    if not request_path.is_file():
        raise RuntimeError(f"Candidate is missing {request_path}")
    request = request_path.read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check_website.py"), str(candidate), request],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Checker did not produce JSON: {result.stderr or result.stdout}") from error
    _write_json(candidate / "debug" / "checker_report.json", report)
    notes_path = candidate / "run_notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.is_file() else {}
    notes.update({
        "status": "final_success" if report.get("final_success") else "automated_success_review_pending" if report.get("automated_success") else "automated_failed",
        "automated_success": bool(report.get("automated_success")),
        "final_success": bool(report.get("final_success")),
        "human_visual_review_status": report.get("visual_design_review_status", "pending"),
        "image_relevance_review_status": report.get("visual_review_status", "pending"),
        "review_rechecked_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    _write_json(notes_path, notes)
    checkpoint_path = candidate / "chunks" / "sequence_checkpoint.json"
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["quality"] = {
            "automated_success": report.get("automated_success"),
            "final_success": report.get("final_success"),
            "file_sha256": {
                relative: hashlib.sha256((candidate / relative).read_bytes()).hexdigest()
                for relative in ("files/index.html", "files/styles.css", "files/inlined/index.html")
            },
            "screenshot_sha256": {
                name: hashlib.sha256((candidate / "debug" / "screenshots" / f"{name}.png").read_bytes()).hexdigest()
                for name in ("desktop", "mobile")
            },
        }
        checkpoint["quality_rechecked_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(checkpoint_path, checkpoint)
    print(json.dumps({"candidate": str(candidate), **notes}, indent=2, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_folder", type=Path)
    args = parser.parse_args()
    recheck(args.candidate_folder.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
