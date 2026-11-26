#!/usr/bin/env python3
"""Queue eligible High-site leads for ChatGPT workers without dispatching a generator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatgpt_worker.high_sites import build_source_records, load_existing_hosts, select_high_sites  # noqa: E402
from chatgpt_worker.git_store import GitStoreError  # noqa: E402


PRIVATE_BRANCH = "chatgpt-worker"
QUEUE_ROOT = Path("private_automation/queue")


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            timeout=120, env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise GitStoreError("Private intake Git operation exceeded its time limit.") from error
    if check and result.returncode:
        raise GitStoreError("Private intake Git operation failed; command output is withheld.")
    return result


def read_slug_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Private result slug map is invalid; refusing to queue sites.") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(slug, str)
                                          for key, slug in value.items()):
        raise ValueError("Private result slug map has an invalid shape.")
    return value


def run_poller(candidate_csv: Path, private_checkout: Path,
               max_sites: int, batch_id: str | None = None, retries: int = 5) -> dict[str, Any]:
    """Reevaluate candidates against each fresh private branch head and push only source queue records."""
    if not 1 <= max_sites <= 24:
        raise ValueError("max_sites must be between 1 and 24.")
    if retries < 1:
        raise ValueError("retries must be positive.")
    if git(private_checkout, "branch", "--show-current").stdout.strip() != PRIVATE_BRANCH:
        raise ValueError("Private checkout must be on chatgpt-worker.")
    if git(private_checkout, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        raise ValueError("Private worker checkout must be clean before polling.")
    batch_id = batch_id or str(uuid4())
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    last_error = ""

    for attempt in range(retries):
        git(private_checkout, "fetch", "origin",
            f"+refs/heads/{PRIVATE_BRANCH}:refs/remotes/origin/{PRIVATE_BRANCH}")
        git(private_checkout, "reset", "--hard", f"origin/{PRIVATE_BRANCH}")
        base = git(private_checkout, "rev-parse", "HEAD").stdout.strip()

        jobs_root = private_checkout / QUEUE_ROOT / "jobs"
        generation_jobs = private_checkout / QUEUE_ROOT / "generation" / "jobs"
        existing = load_existing_hosts([jobs_root, generation_jobs])
        candidates = select_high_sites(candidate_csv, existing, max_sites)
        if not candidates:
            return {"queued": 0, "batch_id": batch_id, "status": "no_eligible_sites"}

        slug_path = private_checkout / QUEUE_ROOT / "result-slugs.json"
        slug_map = read_slug_map(slug_path)
        jobs, batch, updated_slugs = build_source_records(candidates, batch_id, base, slug_map, stamp)
        batches_root = private_checkout / QUEUE_ROOT / "batches"
        jobs_root.mkdir(parents=True, exist_ok=True)
        batches_root.mkdir(parents=True, exist_ok=True)
        changed_paths: list[str] = []
        for job in jobs:
            path = jobs_root / f"{job['job_id']}.json"
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise ValueError("An existing private source job is invalid.") from error
                if current != job:
                    raise ValueError("Refusing to overwrite a different private source job with the same ID.")
            else:
                path.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                changed_paths.append(path.relative_to(private_checkout).as_posix())

        batch_path = batches_root / f"{batch_id}.json"
        if batch_path.exists():
            try:
                current_batch = json.loads(batch_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("An existing private intake batch is invalid.") from error
            if current_batch != batch:
                raise ValueError("Refusing to overwrite a different private intake batch with the same ID.")
        else:
            batch_path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed_paths.append(batch_path.relative_to(private_checkout).as_posix())

        if updated_slugs != slug_map:
            slug_path.parent.mkdir(parents=True, exist_ok=True)
            slug_path.write_text(json.dumps(updated_slugs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            changed_paths.append(slug_path.relative_to(private_checkout).as_posix())
        if not changed_paths:
            return {"queued": 0, "batch_id": batch_id, "status": "already_present"}

        git(private_checkout, "add", "--", *changed_paths)
        staged = git(private_checkout, "diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return {"queued": 0, "batch_id": batch_id, "status": "already_present"}
        if staged.returncode != 1:
            raise GitStoreError("Could not inspect staged private intake changes.")
        git(private_checkout, "-c", "user.name=ChatGPT High-site Poller", "-c",
            "user.email=chatgpt-high-poller@users.noreply.github.com",
            "commit", "--quiet", "-m", f"private: queue worker High batch {batch_id}")
        pushed = git(private_checkout, "push", "origin", f"HEAD:refs/heads/{PRIVATE_BRANCH}", check=False)
        if pushed.returncode == 0:
            return {"queued": len(jobs), "batch_id": batch_id, "status": "queued"}
        remote = git(private_checkout, "ls-remote", "origin", f"refs/heads/{PRIVATE_BRANCH}", check=False)
        if remote.returncode:
            raise GitStoreError("Could not inspect the private worker branch after a rejected intake push.")
        remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
        if remote_head == base:
            raise GitStoreError("Private intake push failed without a concurrent branch update.")
        last_error = "Private worker branch advanced during High-site polling."
        if attempt + 1 < retries:
            time.sleep(1)
    raise GitStoreError(f"High-site poller did not converge after {retries} attempts. {last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-csv", required=True, type=Path)
    parser.add_argument("--private-checkout", required=True, type=Path)
    parser.add_argument("--max-sites", type=int, default=int(os.environ.get("MAX_SITES", "1")))
    parser.add_argument("--batch-id", help="Stable UUID for retrying this exact poller invocation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_poller(args.candidate_csv, args.private_checkout, args.max_sites, args.batch_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (GitStoreError, ValueError, OSError) as error:
        print(f"High-site poll failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
