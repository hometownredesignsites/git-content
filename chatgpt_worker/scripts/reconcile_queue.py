#!/usr/bin/env python3
"""Dry-run-first import of explicitly opted-in generation jobs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from chatgpt_worker.queue import reconcile_sources  # noqa: E402


def read_jobs(folder: Path) -> list[dict]:
    jobs = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "result-slugs.json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Could not read source job record {path.name}") from error
        if isinstance(value, dict):
            jobs.append(value)
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-jobs", type=Path, required=True, help="Private source job directory")
    parser.add_argument("--generation-jobs", type=Path, required=True, help="Private generation job directory")
    parser.add_argument("--apply", action="store_true", help="Write new idempotent job records; default is dry-run")
    args = parser.parse_args()
    if not args.source_jobs.is_dir():
        raise SystemExit("The private source job directory must exist")
    if args.generation_jobs.exists() and not args.generation_jobs.is_dir():
        raise SystemExit("The private generation job path must be a directory")

    existing = {}
    for path in sorted(args.generation_jobs.glob("*.json")) if args.generation_jobs.exists() else []:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("job_id"), str):
            existing[value["job_id"]] = value
    # Keep source records whose provider is explicitly chatgpt-worker; legacy
    # provider jobs are deliberately not imported by this new queue.
    updated, stats = reconcile_sources(read_jobs(args.source_jobs), existing, datetime.now(timezone.utc))
    created_ids = sorted(set(updated) - set(existing))
    if args.apply:
        args.generation_jobs.mkdir(parents=True, exist_ok=True)
        for job_id in created_ids:
            path = args.generation_jobs / f"{job_id}.json"
            if path.exists():
                raise RuntimeError(f"Refusing to overwrite an existing generation job: {path.name}")
            path.write_text(json.dumps(updated[job_id], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", **stats, "created_job_ids": created_ids}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
