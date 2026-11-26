#!/usr/bin/env python3
"""Manually reconcile and operate the private ChatGPT generation queue."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatgpt_worker.git_store import GitJobStore, GitStoreError  # noqa: E402
from chatgpt_worker.queue import QueueConflict, claim, heartbeat  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_next(store: GitJobStore, worker_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    if not worker_id.strip():
        raise ValueError("worker_id is required.")
    now = now or utc_now()
    candidates = [job for job in store.list_jobs() if job.get("status") == "queued"]
    candidates.sort(key=lambda job: (job.get("created_at_utc", ""), job.get("job_id", "")))
    for job in candidates:
        try:
            claimed = store.update_job(job["job_id"], lambda current: claim(current, worker_id, now))
        except QueueConflict:
            continue
        return {"job": claimed}
    return None


def load_result(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Result JSON is missing or invalid.") from error
    if not isinstance(value, dict):
        raise ValueError("Result JSON must contain an object.")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-url", default=os.environ.get(
        "GIT_CONTENT_PRIVATE_REMOTE", "https://github.com/hometownredesignsites/git-content-private.git"
    ))
    parser.add_argument("--branch", default="chatgpt-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reconcile-intake", help="Import opted-in private source jobs idempotently")
    sub.add_parser("recover-expired", help="Return expired claims to the queue")
    sub.add_parser("list", help="List queue state without customer fields")
    claim_parser = sub.add_parser("claim-next", help="Claim the oldest queued job")
    claim_parser.add_argument("--worker-id", required=True)
    heartbeat_parser = sub.add_parser("heartbeat", help="Renew a current worker lease")
    heartbeat_parser.add_argument("--job-id", required=True)
    heartbeat_parser.add_argument("--claim-epoch", required=True, type=int)
    heartbeat_parser.add_argument("--worker-id", required=True)
    heartbeat_loop = sub.add_parser("heartbeat-loop", help="Renew a claim on a fixed interval")
    heartbeat_loop.add_argument("--job-id", required=True)
    heartbeat_loop.add_argument("--claim-epoch", required=True, type=int)
    heartbeat_loop.add_argument("--worker-id", required=True)
    heartbeat_loop.add_argument("--interval-seconds", type=int, default=900)
    complete_parser = sub.add_parser("complete", help="Verify private candidate bytes and finish a job")
    complete_parser.add_argument("--job-id", required=True)
    complete_parser.add_argument("--claim-epoch", required=True, type=int)
    complete_parser.add_argument("--worker-id", required=True)
    complete_parser.add_argument("--result-json", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = GitJobStore(args.remote_url, args.branch)
    try:
        if args.command == "reconcile-intake":
            result = store.reconcile_intake()
        elif args.command == "recover-expired":
            result = store.recover_expired()
        elif args.command == "list":
            jobs = store.list_jobs()
            result = {"total": len(jobs), "states": {state: sum(job.get("status") == state for job in jobs)
                                                           for state in ("queued", "claimed", "generating", "validating", "completed", "blocked", "failed")}}
        elif args.command == "claim-next":
            result = claim_next(store, args.worker_id)
            if result is None:
                result = {"status": "empty"}
        elif args.command == "heartbeat":
            result = store.update_job(
                args.job_id,
                lambda job: heartbeat(job, args.worker_id, utc_now(), args.claim_epoch),
            )
        elif args.command == "heartbeat-loop":
            if not 60 <= args.interval_seconds <= 1800:
                raise ValueError("Heartbeat interval must be between 60 and 1800 seconds.")
            try:
                while True:
                    try:
                        renewed = store.update_job(
                            args.job_id,
                            lambda job: heartbeat(job, args.worker_id, utc_now(), args.claim_epoch),
                        )
                    except QueueConflict:
                        print(json.dumps({"status": "claim_no_longer_active", "job_id": args.job_id,
                                          "claim_epoch": args.claim_epoch}), flush=True)
                        return 0
                    print(json.dumps({
                        "status": renewed.get("status"),
                        "job_id": args.job_id,
                        "claim_epoch": args.claim_epoch,
                        "lease_expires_at_utc": renewed.get("claim", {}).get("lease_expires_at_utc"),
                    }, sort_keys=True), flush=True)
                    time.sleep(args.interval_seconds)
            except KeyboardInterrupt:
                print(json.dumps({"status": "heartbeat_stopped", "job_id": args.job_id,
                                  "claim_epoch": args.claim_epoch}), flush=True)
                return 130
        elif args.command == "complete":
            result_record = load_result(args.result_json)
            result = store.complete_job(args.job_id, args.worker_id, args.claim_epoch, result_record)
        else:
            raise ValueError("Unsupported queue command.")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (GitStoreError, QueueConflict, ValueError, OSError) as error:
        print(f"Queue operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
