#!/usr/bin/env python3
"""Append lifecycle events to a private content-generation batch record."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-file", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--event", choices=("attempt", "final"), required=True)
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--status", default="")
    parser.add_argument("--failure-category", default="")
    parser.add_argument("--failure-details", default="")
    args = parser.parse_args()

    batch = read_json(args.batch_file)
    if not batch or args.job_id not in batch.get("job_ids", []):
        raise SystemExit("Batch record is missing or does not include this job ID.")

    stamp = now()
    lifecycle = batch.setdefault("lifecycle", {})
    lifecycle.setdefault("created_at", batch.get("created_at") or stamp)
    lifecycle.setdefault("started_at", None)
    lifecycle.setdefault("finished_at", None)
    lifecycle.setdefault("source_run_ids", [])
    lifecycle.setdefault("items", {})
    lifecycle.setdefault("attempt_count", 0)
    lifecycle.setdefault("completed_count", 0)
    lifecycle.setdefault("failed_count", 0)
    lifecycle.setdefault("pending_count", len(batch.get("job_ids", [])))

    if not lifecycle["started_at"]:
        lifecycle["started_at"] = stamp
    run_id = str(args.run_id)
    if run_id not in lifecycle["source_run_ids"]:
        lifecycle["source_run_ids"].append(run_id)

    item = lifecycle["items"].setdefault(args.job_id, {
        "job_id": args.job_id,
        "status": "pending",
        "attempt_count": 0,
        "attempts": [],
        "failure_category": None,
        "failure_details": None,
        "diagnostic_url": None,
        "source_run_ids": [],
    })
    if run_id not in item["source_run_ids"]:
        item["source_run_ids"].append(run_id)

    if args.event == "attempt":
        item["status"] = "running"
        item["failure_category"] = None
        item["failure_details"] = None
        item["diagnostic_url"] = None
        lifecycle["finished_at"] = None
        candidate = args.candidate_dir
        notes = read_json(candidate / "run_notes.json") if candidate else {}
        attempt_key = f"{run_id}-{args.run_attempt}-{candidate.name if candidate else 'unknown'}"
        if not any(entry.get("event_id") == attempt_key for entry in item["attempts"]):
            item["attempts"].append({
                "event_id": attempt_key,
                "recorded_at": stamp,
                "run_id": run_id,
                "run_attempt": int(args.run_attempt),
                "candidate": candidate.name if candidate else None,
                "outcome": "passed" if notes.get("automated_success") is True else "failed",
                "failure_category": None if notes.get("automated_success") is True else (notes.get("status") or "candidate_failed"),
                "failure_details": None if notes.get("automated_success") is True else args.failure_details[:2000] or "Candidate did not pass automated quality gates.",
                "diagnostic_url": f"https://github.com/hometownredesignsites/git-content/actions/runs/{run_id}",
            })
            item["attempt_count"] = len(item["attempts"])

    if args.event == "final":
        item["status"] = args.status if args.status in {"completed", "failed"} else "failed"
        if item["status"] == "completed":
            item["failure_category"] = None
            item["failure_details"] = None
            item["diagnostic_url"] = None
        else:
            item["failure_category"] = args.failure_category or "workflow_failed"
            item["failure_details"] = args.failure_details[:4000] or "Workflow ended without meeting the completion gate."
            item["diagnostic_url"] = f"https://github.com/hometownredesignsites/git-content/actions/runs/{run_id}"

    ids = batch.get("job_ids", [])
    states = [lifecycle["items"].get(job_id, {}).get("status", "pending") for job_id in ids]
    lifecycle["completed_count"] = sum(state == "completed" for state in states)
    lifecycle["failed_count"] = sum(state == "failed" for state in states)
    lifecycle["pending_count"] = sum(state not in {"completed", "failed"} for state in states)
    lifecycle["attempt_count"] = sum(int(lifecycle["items"].get(job_id, {}).get("attempt_count", 0) or 0) for job_id in ids)
    lifecycle["status"] = "completed" if lifecycle["pending_count"] == 0 and lifecycle["failed_count"] == 0 else "failed" if lifecycle["pending_count"] == 0 else "running"
    if lifecycle["pending_count"] == 0 and not lifecycle["finished_at"]:
        lifecycle["finished_at"] = stamp
    batch["lifecycle"] = lifecycle
    write_json(args.batch_file, batch)
    print(f"Updated batch {batch['batch_id']} lifecycle: {lifecycle['completed_count']} completed, {lifecycle['failed_count']} failed, {lifecycle['pending_count']} pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
