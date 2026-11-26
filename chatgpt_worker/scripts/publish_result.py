#!/usr/bin/env python3
"""Publish a PASS skill result to private storage and complete its queue job."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatgpt_worker.git_store import GitJobStore, GitStoreError  # noqa: E402
from chatgpt_worker.queue import FINAL_FILES, QueueConflict  # noqa: E402

REQUIRED_CANDIDATE_CHECKS = {
    "exact_saved_bytes_and_static_requirements",
    "browser_viewport_and_interaction_matrix",
    "rendered_template_credits_absent",
}
REQUIRED_VIEWPORTS = {"desktop", "tablet", "mobile"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("The native QA evidence file is missing or invalid.") from error
    if not isinstance(value, dict):
        raise ValueError("The native QA evidence file must contain an object.")
    return value


def normalize_candidate_entries(value: object) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if isinstance(value, dict):
        source = value.items()
    elif isinstance(value, list):
        source = []
        for item in value:
            if not isinstance(item, dict):
                raise QueueConflict("Each native QA candidate entry must be an object.")
            name = item.get("template", item.get("slot", item.get("slot_id", "")))
            source.append((name, item))
    else:
        raise QueueConflict("Native QA candidate entries must be an object or array.")
    aliases = {"forty": "forty", "landed": "landed", "story": "story"}
    filenames = {filename: key for key, filename in FINAL_FILES.items()}
    for name, entry in source:
        if not isinstance(name, str) or not isinstance(entry, dict):
            raise QueueConflict("Native QA candidate identity or entry is invalid.")
        key = aliases.get(name.lower()) or filenames.get(Path(name).name)
        if key is None or key in entries:
            raise QueueConflict("Native QA evidence must identify each of Forty, Landed, and Story once.")
        entries[key] = entry
    if set(entries) != set(FINAL_FILES):
        raise QueueConflict("Native QA evidence must describe exactly Forty, Landed, and Story.")
    return entries


def candidate_results_from_report(report: dict) -> dict[str, dict]:
    """Adapt the skill's detailed candidate_results without weakening its QA record."""
    if report.get("finished_checks") is not True:
        raise QueueConflict("Native QA checks were not marked finished.")
    raw_results = report.get("candidate_results")
    if not isinstance(raw_results, list):
        raise QueueConflict("Native QA candidate_results must be an array.")

    for entry in raw_results:
        if not isinstance(entry, dict):
            raise QueueConflict("Each native QA candidate result must be an object.")
        if entry.get("status") != "PASS" or entry.get("static_check_status") != "PASS":
            raise QueueConflict("Every native QA candidate and static check must pass.")
        if entry.get("static_errors") != [] or entry.get("failures") != []:
            raise QueueConflict("Native QA candidate results contain static errors or failures.")

        viewports = entry.get("viewports")
        if not isinstance(viewports, list):
            raise QueueConflict("Native QA candidate results must include viewport checks.")
        viewport_statuses: dict[str, dict] = {}
        for viewport in viewports:
            if not isinstance(viewport, dict):
                raise QueueConflict("Each native QA viewport result must be an object.")
            name = viewport.get("name")
            if not isinstance(name, str) or name in viewport_statuses:
                raise QueueConflict("Native QA viewport names must be unique strings.")
            viewport_statuses[name] = viewport
        if set(viewport_statuses) != REQUIRED_VIEWPORTS:
            raise QueueConflict("Native QA must include desktop, tablet, and mobile viewport results.")
        if any(viewport.get("status") != "PASS" or viewport.get("errors") != []
               for viewport in viewport_statuses.values()):
            raise QueueConflict("Every native QA viewport must pass without errors.")

        checks = entry.get("checks")
        if not isinstance(checks, list):
            raise QueueConflict("Native QA candidate results must include required check records.")
        check_statuses: dict[str, str] = {}
        for check in checks:
            if not isinstance(check, dict):
                raise QueueConflict("Each native QA check must be an object.")
            name = check.get("name")
            status = check.get("status")
            if not isinstance(name, str) or name in check_statuses:
                raise QueueConflict("Native QA check names must be unique strings.")
            check_statuses[name] = status
        if not REQUIRED_CANDIDATE_CHECKS.issubset(check_statuses):
            raise QueueConflict("Native QA is missing one or more required candidate checks.")
        if any(status != "PASS" for status in check_statuses.values()):
            raise QueueConflict("Every native QA candidate check must pass.")

    return normalize_candidate_entries(raw_results)


def collect_output(root: Path) -> tuple[dict[str, bytes], dict, dict]:
    root = root.resolve(strict=True)
    qa_path = root / "evidence" / "native-qa.json"
    report = read_json(qa_path)
    if report.get("native_qa_status") != "PASS":
        raise QueueConflict("Only native_qa_status PASS output can be published.")
    if "candidates" in report:
        candidates = normalize_candidate_entries(report.get("candidates"))
    elif "candidate_results" in report:
        candidates = candidate_results_from_report(report)
    else:
        raise QueueConflict("Native QA evidence must include candidate or candidate_results records.")
    files: dict[str, bytes] = {}
    result_candidates: dict[str, dict] = {}
    for key, filename in FINAL_FILES.items():
        entry = candidates.get(key)
        if not isinstance(entry, dict):
            raise QueueConflict(f"Native QA evidence does not show a PASS for {key}.")
        candidate_status = entry.get("qa_status", entry.get("status"))
        if candidate_status is not None and candidate_status != "PASS":
            raise QueueConflict(f"Native QA evidence does not show a PASS for {key}.")
        stated_filename = entry.get("filename", entry.get("final_path", entry.get("path")))
        if not isinstance(stated_filename, str) or Path(stated_filename).name != filename:
            raise QueueConflict(f"Native QA evidence names the wrong file for {key}.")
        source = root / filename
        if source.is_symlink() or not source.is_file():
            raise QueueConflict(f"Required candidate file for {key} is missing or not a regular file.")
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise QueueConflict("Candidate file escaped the worker output folder.")
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        stated_bytes = entry.get("bytes", entry.get("byte_count"))
        if stated_bytes != len(content) or entry.get("sha256") != digest:
            raise QueueConflict(f"Exact byte count or SHA-256 in native QA evidence does not match {filename}.")
        files[filename] = content
        result_candidates[key] = {
            "filename": filename,
            "bytes": len(content),
            "sha256": digest,
            "qa_status": "PASS",
        }

    evidence_root = root / "evidence"
    if evidence_root.is_symlink() or not evidence_root.is_dir() or not evidence_root.resolve().is_relative_to(root):
        raise QueueConflict("Evidence folder is missing or escaped the worker output folder.")
    total = 0
    evidence_count = 0
    for path in sorted(evidence_root.rglob("*")):
        if path.is_symlink():
            raise QueueConflict("Evidence folders cannot contain symbolic links.")
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        safe = PurePosixPath(rel)
        if safe.is_absolute() or ".." in safe.parts:
            raise QueueConflict("Evidence file path is unsafe.")
        content = path.read_bytes()
        total += len(content)
        evidence_count += 1
        if total > 100 * 1024 * 1024 or evidence_count > 1000:
            raise QueueConflict("Evidence package exceeds the publication size or file-count limit.")
        files[rel] = content

    qa_bytes = files.get("evidence/native-qa.json")
    if qa_bytes is None:
        raise QueueConflict("The native QA report must be included in the private evidence package.")
    qa_record = {
        "filename": "evidence/native-qa.json",
        "bytes": len(qa_bytes),
        "sha256": hashlib.sha256(qa_bytes).hexdigest(),
    }
    return files, report, {"candidates": result_candidates, "qa_evidence": qa_record}


def source_host(value: str) -> str:
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise QueueConflict("Source URL in the QA report is invalid.")
    return parsed.hostname.lower().removeprefix("www.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-url", default=os.environ.get(
        "GIT_CONTENT_PRIVATE_REMOTE", "https://github.com/hometownredesignsites/git-content-private.git"
    ))
    parser.add_argument("--branch", default="chatgpt-worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--claim-epoch", required=True, type=int)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--skill-output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        files, report, measured = collect_output(args.skill_output)
        store = GitJobStore(args.remote_url, args.branch)
        current = store.read_job(args.job_id)
        row = current.get("row", {})
        expected_website = str(row.get("website", "")).strip() if isinstance(row, dict) else ""
        reported_source = report.get("source_url")
        if not expected_website or not isinstance(reported_source, str):
            raise QueueConflict("QA evidence and private job must identify the source website.")
        if source_host(expected_website) != source_host(reported_source):
            raise QueueConflict("QA evidence source host does not match the claimed generation job.")
        result_slug = current.get("result_slug", "")
        if not isinstance(result_slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result_slug):
            raise QueueConflict("Private job has an invalid result slug.")
        run_path = f"results/{result_slug}/run-{args.job_id}-epoch-{args.claim_epoch}"
        result_record = {
            "run_path": run_path,
            "qa_status": "PASS",
            "candidates": measured["candidates"],
            "qa_evidence": measured["qa_evidence"],
        }
        if current.get("status") == "completed":
            current, _saved_artifacts = store.read_completed_artifacts(args.job_id)
            if current.get("result", {}).get("run_path") != run_path:
                raise QueueConflict("Job is already completed with a different result run.")
            for key in ("qa_status", "candidates", "qa_evidence"):
                if current["result"].get(key) != result_record.get(key):
                    raise QueueConflict("Job is already completed with different exact result bytes.")
            print(json.dumps({"status": "already_published", "job_id": args.job_id}, sort_keys=True))
            return 0
        claim_data = current.get("claim")
        if (current.get("status") not in {"claimed", "generating", "validating"}
                or current.get("claim_epoch") != args.claim_epoch or not isinstance(claim_data, dict)):
            raise QueueConflict("The job does not have this active claim epoch.")
        if claim_data.get("worker_id") != args.worker_id:
            raise QueueConflict("Worker ID does not match the active claim.")
        artifact_commit = store.publish_artifacts(
            args.job_id, args.worker_id, args.claim_epoch, run_path, files,
        )
        result_record["artifact_commit"] = artifact_commit
        store.complete_job(args.job_id, args.worker_id, args.claim_epoch, result_record)
        print(json.dumps({"status": "completed", "job_id": args.job_id, "artifact_commit": artifact_commit}, sort_keys=True))
        return 0
    except (GitStoreError, QueueConflict, ValueError, TypeError, KeyError, OSError) as error:
        print(f"Result publication failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
