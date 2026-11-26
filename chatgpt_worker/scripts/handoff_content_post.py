#!/usr/bin/env python3
"""Stage a completed three-candidate batch on the existing private slot branches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from chatgpt_worker.git_store import GitJobStore, GitStoreError  # noqa: E402
from chatgpt_worker.queue import FINAL_FILES, QueueConflict  # noqa: E402


SLOT_BRANCHES = {1: "chatgpt-slot1", 2: "chatgpt-slot2", 3: "chatgpt-slot3"}
SLOT_KEYS = {1: "forty", 2: "landed", 3: "story"}
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BATCH_RE = re.compile(r"[0-9]+-[0-9]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def batch_id_for(job: dict) -> str:
    created = datetime.fromisoformat(str(job["created_at_utc"]).replace("Z", "+00:00"))
    if created.tzinfo is None:
        raise ValueError("Generation job timestamp must include a timezone.")
    millis = int(created.timestamp() * 1000)
    suffix = int(job["job_id"].replace("-", ""), 16)
    return f"{millis}-{suffix}"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                timeout=120, env=environment)
    except subprocess.TimeoutExpired as error:
        raise GitStoreError("A content-post Git operation exceeded its time limit.") from error
    if check and result.returncode:
        raise GitStoreError("A content-post Git operation failed; command output is withheld.")
    return result


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def stage_exact_html(repo: Path, path: Path) -> None:
    relative = path.relative_to(repo).as_posix()
    content = path.read_bytes()
    try:
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--no-filters", "--stdin"], cwd=repo,
            input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise GitStoreError("Exact HTML staging exceeded its time limit.") from error
    if blob.returncode:
        raise GitStoreError("Could not stage exact HTML bytes for content-post.")
    blob_id = blob.stdout.decode("ascii").strip()
    git(repo, "update-index", "--add", "--cacheinfo", "100644", blob_id, relative)


def safe_repo_path(repo: Path, relative: Path) -> Path:
    root = repo.resolve()
    target = repo / relative
    cursor = repo
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise QueueConflict("Content-post handoff paths cannot use symbolic links.")
    if not target.resolve().is_relative_to(root):
        raise QueueConflict("Content-post handoff path escaped its repository.")
    return target


def remote_batch_order(value: str) -> tuple[int, int]:
    if not BATCH_RE.fullmatch(value):
        return (-1, -1)
    left, right = value.split("-", 1)
    return int(left), int(right)


def content_post_slug(website: str) -> str:
    parsed = urlsplit(website if "://" in website else "https://" + website)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    slug = host.split(".")[0]
    if parsed.scheme not in {"http", "https"} or not SLUG_RE.fullmatch(slug):
        raise QueueConflict("Private generation job has no valid content-post website slug.")
    return slug


def select_branch(repo: Path, branch: str) -> str:
    exists = git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", check=False)
    if exists.returncode:
        raise GitStoreError("Could not inspect a content-post slot branch.")
    if exists.stdout.strip():
        git(repo, "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        git(repo, "switch", "--quiet", "--force-create", branch, f"origin/{branch}")
    else:
        git(repo, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main")
        git(repo, "switch", "--quiet", "--force-create", branch, "origin/main")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def stage_slot(repo: Path, remote_url: str, slot: int, *, slug: str, company: str,
               website: str, batch_id: str, queued_at: str, job_id: str,
               artifact_commit: str, filename: str, html: bytes, retries: int = 5) -> None:
    branch = SLOT_BRANCHES[slot]
    metadata = {
        "schema_version": 1,
        "company": company,
        "website": website,
        "site_slug": slug,
        "slot": slot,
        "branch": branch,
        "batch_id": batch_id,
        "source_run": job_id,
        "source_commit": artifact_commit,
        "source_candidate": filename,
        "queued_at_utc": queued_at,
    }
    metadata_text = json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    site_rel = Path("sites") / slug
    queue_rel = site_rel / "queue" / batch_id
    for attempt in range(retries):
        base = select_branch(repo, branch)
        queue_html = safe_repo_path(repo, queue_rel / "index.html")
        queue_metadata = safe_repo_path(repo, queue_rel / "metadata.json")
        draft = safe_repo_path(repo, site_rel / "draft")
        has_html = queue_html.exists()
        has_metadata = queue_metadata.exists()
        if has_html or has_metadata:
            if not (has_html and has_metadata):
                raise QueueConflict(f"Immutable slot {slot} snapshot is incomplete; refusing to replace it.")
            if queue_html.read_bytes() != html or read_json(queue_metadata) != metadata:
                raise QueueConflict(f"Immutable slot {slot} snapshot conflicts with this handoff batch.")
            return

        draft_html = draft / "index.html"
        draft_metadata = draft / "metadata.json"
        update_draft = not draft_html.exists() and not draft_metadata.exists()
        if draft_html.exists() != draft_metadata.exists():
            raise QueueConflict(f"Current slot {slot} draft has incomplete metadata; refusing to replace it.")
        if draft_html.exists():
            current = read_json(draft_metadata)
            if not current:
                raise QueueConflict(f"Current slot {slot} draft metadata is invalid; refusing to replace it.")
            current_batch = str(current.get("batch_id", ""))
            if current_batch == batch_id:
                if draft_html.read_bytes() != html or current != metadata:
                    raise QueueConflict(f"Current slot {slot} draft conflicts with its batch snapshot.")
                update_draft = False
            else:
                update_draft = remote_batch_order(current_batch) <= remote_batch_order(batch_id)

        safe_repo_path(repo, queue_rel).mkdir(parents=True, exist_ok=True)
        queue_html.write_bytes(html)
        queue_metadata.write_text(metadata_text, encoding="utf-8")
        if update_draft:
            draft.mkdir(parents=True, exist_ok=True)
            safe_repo_path(repo, site_rel / "draft" / "index.html").write_bytes(html)
            safe_repo_path(repo, site_rel / "draft" / "metadata.json").write_text(metadata_text, encoding="utf-8")

        exact_html_paths = [queue_html]
        metadata_paths = [f"{queue_rel.as_posix()}/metadata.json"]
        if update_draft:
            exact_html_paths.append(safe_repo_path(repo, site_rel / "draft" / "index.html"))
            metadata_paths.append(f"{(site_rel / 'draft' / 'metadata.json').as_posix()}")
        for html_path in exact_html_paths:
            stage_exact_html(repo, html_path)
        git(repo, "add", "--", *metadata_paths)
        if git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        git(repo, "-c", "user.name=ChatGPT Worker Publisher", "-c",
            "user.email=chatgpt-worker-publisher@users.noreply.github.com",
            "commit", "--quiet", "-m", f"content-post: stage slot {slot} batch {batch_id}")
        pushed = git(repo, "push", "origin", f"HEAD:refs/heads/{branch}", check=False)
        if pushed.returncode == 0:
            return
        remote = git(repo, "ls-remote", "origin", f"refs/heads/{branch}", check=False)
        if remote.returncode:
            raise GitStoreError("Could not verify content-post slot branch after a rejected push.")
        remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
        if remote_head == base:
            raise GitStoreError(f"Content-post slot {slot} push failed without a concurrent branch update.")
        if attempt + 1 == retries:
            break
        time.sleep(1)
    raise GitStoreError(f"Content-post slot {slot} branch kept advancing; handoff remains pending.")


def stage_all(remote_url: str, job: dict, artifacts: dict[str, bytes], batch_id: str,
              queued_at: str) -> None:
    row = job.get("row", {})
    company = str(row.get("business", "")).strip()
    website = str(row.get("website", "")).strip()
    if not company or not website:
        raise QueueConflict("Private generation job is missing valid content-post identity fields.")
    slug = content_post_slug(website)
    artifact_commit = job["result"].get("artifact_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", str(artifact_commit)):
        raise QueueConflict("Private result has no valid source artifact commit.")
    with tempfile.TemporaryDirectory(prefix="chatgpt-content-post-handoff-") as temp:
        checkout = Path(temp) / "repo"
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            cloned = subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--quiet", "--no-checkout", remote_url, str(checkout)],
                                    text=True, encoding="utf-8", stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=False, timeout=120, env=environment)
        except subprocess.TimeoutExpired as error:
            raise GitStoreError("Content-post clone exceeded its time limit.") from error
        if cloned.returncode:
            raise GitStoreError("Could not open the private content-post repository.")
        for slot in (1, 2, 3):
            key = SLOT_KEYS[slot]
            filename = FINAL_FILES[key]
            html = artifacts.get(key)
            if not isinstance(html, bytes) or not html:
                raise QueueConflict(f"Completed private result is missing slot {slot} bytes.")
            stage_slot(checkout, remote_url, slot, slug=slug, company=company, website=website,
                       batch_id=batch_id, queued_at=queued_at, job_id=job["job_id"],
                       artifact_commit=artifact_commit, filename=filename, html=html)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-remote", default=os.environ.get(
        "GIT_CONTENT_PRIVATE_REMOTE", "https://github.com/hometownredesignsites/git-content-private.git"
    ))
    parser.add_argument("--private-branch", default="chatgpt-worker")
    parser.add_argument("--content-post-remote", default=os.environ.get(
        "CONTENT_POST_REMOTE", "https://github.com/hometownredesignsites/content-post.git"
    ))
    parser.add_argument("--job-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = GitJobStore(args.private_remote, args.private_branch)
        job, artifacts = store.read_completed_artifacts(args.job_id)
        batch_id = job.get("handoff", {}).get("content_post_batch_id") or batch_id_for(job)
        reserved = store.reserve_content_post_handoff(args.job_id, batch_id, utc_now())
        queued_at = reserved.get("handoff", {}).get("reserved_at_utc")
        if not queued_at:
            raise QueueConflict("Reserved handoff has no stable queue timestamp.")
        stage_all(args.content_post_remote, job, artifacts, batch_id, queued_at)
        finished = store.mark_content_post_handed_off(args.job_id, batch_id, utc_now())
        print(json.dumps({
            "status": finished.get("handoff", {}).get("status"),
            "job_id": args.job_id,
            "content_post_batch_id": batch_id,
            "slots_staged": 3,
        }, sort_keys=True))
        return 0
    except (GitStoreError, QueueConflict, ValueError, TypeError, KeyError, OSError) as error:
        print(f"Content-post handoff failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
