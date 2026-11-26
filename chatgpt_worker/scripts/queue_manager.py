#!/usr/bin/env python3
"""Manually reconcile and operate the private ChatGPT generation queue."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatgpt_worker.git_store import GitJobStore, GitStoreError  # noqa: E402
from chatgpt_worker.queue import QueueConflict, claim, heartbeat  # noqa: E402
from chatgpt_worker.token_checkpoint import CheckpointError, TokenCheckpoint  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_next(store: GitJobStore, worker_id: str, now: datetime | None = None,
               checkpoint: TokenCheckpoint | None = None) -> dict[str, Any] | None:
    if not worker_id.strip():
        raise ValueError("worker_id is required.")
    now = now or utc_now()
    candidates = [job for job in store.list_jobs() if job.get("status") == "queued"]
    candidates.sort(key=lambda job: (job.get("created_at_utc", ""), job.get("job_id", "")))
    for job in candidates:
        token = secrets.token_urlsafe(32)
        checkpoint_id = None
        epoch = int(job.get("claim_epoch", 0)) + 1
        if checkpoint is not None:
            # Persist the token first. If the remote push succeeds but its
            # response is lost, the worker can still validate and resume it.
            checkpoint_id = checkpoint.save(
                job["job_id"], epoch, worker_id, token,
                store.remote_url, store.branch,
            )
        try:
            claimed = store.update_job(job["job_id"], lambda current: claim(current, worker_id, token, now))
        except QueueConflict:
            if checkpoint is not None and checkpoint_id is not None:
                checkpoint.delete_id(checkpoint_id)
            continue
        except ValueError:
            if checkpoint is not None and checkpoint_id is not None:
                checkpoint.delete_id(checkpoint_id)
            raise
        result = {"job": claimed, "claim_token": token}
        if checkpoint_id is not None:
            result["checkpoint_id"] = checkpoint_id
        return result
    return None


def load_result(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Result JSON is missing or invalid.") from error
    if not isinstance(value, dict):
        raise ValueError("Result JSON must contain an object.")
    return value


def load_claim_token(store: GitJobStore, checkpoint: TokenCheckpoint,
                     job_id: str, epoch: int, remote_url: str, branch: str) -> str:
    current = store.read_job(job_id)
    claim_data = current.get("claim")
    if (current.get("status") not in {"claimed", "generating", "validating"}
            or current.get("claim_epoch") != epoch or not isinstance(claim_data, dict)):
        raise QueueConflict("The job does not have this active claim epoch.")
    return checkpoint.load(
        job_id, epoch, remote_url, branch,
        expected_sha256=claim_data.get("claim_token_sha256"),
    )["claim_token"]


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
    heartbeat_loop = sub.add_parser("heartbeat-loop", help="Renew a claim on a fixed interval")
    heartbeat_loop.add_argument("--job-id", required=True)
    heartbeat_loop.add_argument("--claim-epoch", required=True, type=int)
    heartbeat_loop.add_argument("--interval-seconds", type=int, default=900)
    sub.add_parser("checkpoint-list", help="List local encrypted claim checkpoint IDs")
    complete_parser = sub.add_parser("complete", help="Verify private candidate bytes and finish a job")
    complete_parser.add_argument("--job-id", required=True)
    complete_parser.add_argument("--claim-epoch", required=True, type=int)
    complete_parser.add_argument("--result-json", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("CHATGPT_WORKER_CLAIM_TOKEN", "")
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
            checkpoint = TokenCheckpoint()
            checkpoint.ensure_available()
            result = claim_next(store, args.worker_id, checkpoint=checkpoint)
            if result is None:
                result = {"status": "empty"}
            else:
                result.pop("claim_token", None)
        elif args.command == "heartbeat":
            checkpoint = TokenCheckpoint()
            try:
                token = load_claim_token(store, checkpoint, args.job_id, args.claim_epoch,
                                         args.remote_url, args.branch)
            except CheckpointError:
                if not token:
                    raise
            result = store.update_job(args.job_id, lambda job: heartbeat(job, token, utc_now(), args.claim_epoch))
        elif args.command == "heartbeat-loop":
            checkpoint = TokenCheckpoint()
            if not 60 <= args.interval_seconds <= 1800:
                raise ValueError("Heartbeat interval must be between 60 and 1800 seconds.")
            token = load_claim_token(store, checkpoint, args.job_id, args.claim_epoch,
                                     args.remote_url, args.branch)
            try:
                while True:
                    try:
                        renewed = store.update_job(
                            args.job_id,
                            lambda job: heartbeat(job, token, utc_now(), args.claim_epoch),
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
        elif args.command == "checkpoint-list":
            checkpoint = TokenCheckpoint()
            result = {"checkpoint_ids": checkpoint.list_ids()}
        elif args.command == "complete":
            checkpoint = TokenCheckpoint()
            try:
                token = load_claim_token(store, checkpoint, args.job_id, args.claim_epoch,
                                         args.remote_url, args.branch)
            except CheckpointError:
                if not token:
                    raise
            result_record = load_result(args.result_json)
            result = store.complete_job(args.job_id, token, args.claim_epoch, result_record)
            checkpoint.delete(args.job_id, args.claim_epoch)
        else:
            raise ValueError("Unsupported queue command.")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (CheckpointError, GitStoreError, QueueConflict, ValueError, OSError) as error:
        print(f"Queue operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
