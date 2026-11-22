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


def _candidate_digest(candidate: Path) -> str:
    """Hash the final standalone bytes used by Chromium and delivery."""
    path = candidate / "files" / "inlined" / "index.html"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_artifact_digest(candidate: Path) -> str:
    """Hash the editable HTML/CSS state during a grouped repair pass."""
    digest = hashlib.sha256()
    found = False
    for relative in ("files/index.html", "files/styles.css", "files/inlined/index.html"):
        path = candidate / relative
        if path.is_file():
            found = True
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest() if found else ""


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
    before_digest = _candidate_digest(candidate)
    prior_report_path = candidate / "debug" / "checker_report.json"
    prior_report = json.loads(prior_report_path.read_text(encoding="utf-8")) if prior_report_path.is_file() else {}
    triggering_checks = list(prior_report.get("blocking_failures", []))
    repair_steps = []
    step_before = _candidate_artifact_digest(candidate)
    repaired = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "repair_contact_form.py"), str(candidate)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if repaired.returncode:
        raise RuntimeError(f"Source contact-form repair failed: {repaired.stderr or repaired.stdout}")
    step_after = _candidate_artifact_digest(candidate)
    repair_steps.append(("contact_form_repair.json", "Restore captured source contact fields and verified contact channels.", step_before, step_after))
    step_before = step_after
    visuals = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "repair_generated_visuals.py"), str(candidate)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if visuals.returncode:
        raise RuntimeError(f"Generated visual repair failed: {visuals.stderr or visuals.stdout}")
    step_after = _candidate_artifact_digest(candidate)
    repair_steps.append(("visual_repair.json", "Apply the workflow's documented scoped visual fixes.", step_before, step_after))
    step_before = step_after
    local_links = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "repair_local_links.py"), str(candidate)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if local_links.returncode:
        raise RuntimeError(f"Local-link repair failed: {local_links.stderr or local_links.stdout}")
    step_after = _candidate_artifact_digest(candidate)
    repair_steps.append(("local_link_repair.json", "Resolve invalid local routes and fragments when a safe target exists.", step_before, step_after))
    step_before = step_after
    palette = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "palette.py"), str(candidate)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if palette.returncode:
        raise RuntimeError(f"Palette repair or contrast validation failed: {palette.stderr or palette.stdout}")
    step_after = _candidate_artifact_digest(candidate)
    repair_steps.append(("palette.json", "Apply the assigned slot palette and record token/contrast validation.", step_before, step_after))
    step_before = step_after
    normalized = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "normalize_cta_arrows.py"), str(candidate / "files" / "index.html"),
         "--css-file", str(candidate / "files" / "styles.css")],
        capture_output=True, text=True, encoding="utf-8",
    )
    if normalized.returncode:
        raise RuntimeError(f"CTA arrow normalization failed: {normalized.stderr or normalized.stdout}")
    step_after = _candidate_artifact_digest(candidate)
    repair_steps.append(("quality_repair.json", "Apply only measured safe repairs reported by the quality gate.", step_before, step_after))
    step_before = step_after
    inlined = candidate / "files" / "inlined" / "index.html"
    if inlined.is_file():
        inlined_css = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "inline_css.py"), str(candidate / "files" / "index.html"),
             str(candidate / "files" / "styles.css"), str(inlined)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if inlined_css.returncode:
            raise RuntimeError(f"CSS inlining failed: {inlined_css.stderr or inlined_css.stdout}")
        normalized_inline = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "normalize_cta_arrows.py"), str(inlined)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if normalized_inline.returncode:
            raise RuntimeError(f"Inlined CTA arrow normalization failed: {normalized_inline.stderr or normalized_inline.stdout}")
        browser_qa = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "browser_qa.py"), str(candidate), request],
            capture_output=True, text=True, encoding="utf-8",
        )
        if browser_qa.returncode:
            raise RuntimeError(f"Rendered browser QA failed: {browser_qa.stderr or browser_qa.stdout}")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check_website.py"), str(candidate), request],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Checker did not produce JSON: {result.stderr or result.stdout}") from error
    _write_json(candidate / "debug" / "checker_report.json", report)
    after_digest = _candidate_digest(candidate)
    repair_records = []
    for report_name, description, step_before_digest, step_after_digest in repair_steps:
        report_path = candidate / "debug" / report_name
        try:
            repair_report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            repair_report = {}
        changed = bool(step_before_digest and step_after_digest and step_before_digest != step_after_digest)
        raw_status = str(repair_report.get("status", "")).lower()
        outcome = "BLOCKED" if raw_status in {"unavailable", "needs_manual_repair", "partial", "no_safe_repair_available"} else "APPLIED" if changed else "NOT_NEEDED"
        repair_records.append({
            "repair_id": report_name.removesuffix(".json"),
            "triggering_check_ids": triggering_checks,
            "file_or_region": str(report_path.relative_to(candidate)).replace("\\", "/"),
            "problem": description,
            "change_made": json.dumps(repair_report, ensure_ascii=False, separators=(",", ":")) if repair_report else "No change reported by this repair step.",
            "result": outcome,
            "evidence_paths": [str(report_path.relative_to(candidate)).replace("\\", "/")] if report_path.is_file() else [],
            "retest_check_ids": list(report.get("checks", {}).keys()),
            "artifact_sha256_before": step_before_digest,
            "artifact_sha256_after": step_after_digest,
        })
    _write_json(candidate / "debug" / "repairs.json", {
        "schema_version": "1.0",
        "record_type": "repairs",
        "run_id": __import__("os").environ.get("GITHUB_RUN_ID", candidate.name),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate.name,
        "html_sha256_before": before_digest,
        "html_sha256_after": after_digest,
        "repairs": repair_records,
        "repair_attempts": sum(item["result"] == "APPLIED" for item in repair_records),
        "remaining_failures": list(report.get("blocking_failures", [])),
        "retest_status": "PASS" if report.get("automated_success") else "FAIL",
        "retest_check_ids": list(report.get("checks", {}).keys()),
        "status": "PASS" if report.get("automated_success") else "FAIL",
    })
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
