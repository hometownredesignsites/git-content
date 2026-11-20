#!/usr/bin/env python3
"""Push the three generation-approved inline HTML files to content-post slot branches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit


SLOT_BRANCHES = {1: "chatgpt-slot1", 2: "chatgpt-slot2", 3: "chatgpt-slot3"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def git(directory: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=directory, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError("A content-post Git operation failed; details are withheld from public logs.")
    return result


def slot_number(candidate: Path) -> int | None:
    reference = read_json(candidate / "debug" / "design_reference.json")
    try:
        number = int(reference.get("template_slot", 0))
    except (TypeError, ValueError):
        return None
    return number if number in SLOT_BRANCHES else None


def passed_candidates(root: Path) -> dict[int, Path]:
    selected: dict[int, Path] = {}
    signatures: set[str] = set()
    for candidate in sorted(root.glob("run-*-site-1-candidate-*")):
        if not candidate.is_dir():
            continue
        notes = read_json(candidate / "run_notes.json")
        if notes.get("automated_success") is not True:
            continue
        number = slot_number(candidate)
        if number is None or number in selected:
            continue
        browser = read_json(candidate / "debug" / "browser_qa.json")
        layout = browser.get("template_layout", {}) if isinstance(browser, dict) else {}
        signature = str(layout.get("signature_id", f"slot-{number}"))
        if layout.get("pass") is False or signature in signatures:
            continue
        html = candidate / "files" / "inlined" / "index.html"
        if not html.is_file():
            continue
        text = html.read_text(encoding="utf-8-sig")
        if not re.search(r"(?is)(<!doctype\s+html|<html\b)", text) or not re.search(r"(?is)</html>\s*$", text):
            continue
        selected[number] = candidate
        signatures.add(signature)
    if set(selected) != {1, 2, 3}:
        raise RuntimeError(f"Expected passing inline HTML for all three template slots; found {sorted(selected)}")
    return selected


def site_slug(website: str) -> str:
    parsed = urlsplit(website if "://" in website else "https://" + website)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    slug = host.split(".")[0]
    if parsed.scheme not in {"http", "https"} or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("Job record does not contain a valid website host")
    return slug


def push_slot(repo: Path, slot: int, candidate: Path, *, company: str, website: str,
              batch_id: str, source_run: str, source_commit: str) -> None:
    branch = SLOT_BRANCHES[slot]
    git(repo, "fetch", "origin", "main", check=True)
    remote_ref = git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", check=False)
    if remote_ref.returncode != 0:
        raise RuntimeError(f"Could not inspect remote branch {branch}")
    if remote_ref.stdout.strip():
        git(repo, "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}", check=True)
        git(repo, "switch", "--force-create", branch, f"origin/{branch}")
    else:
        git(repo, "switch", "--force-create", branch, "origin/main")

    slug = site_slug(website)
    site = repo / "sites" / slug
    draft = site / "draft"
    draft.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate / "files" / "inlined" / "index.html", draft / "index.html")
    metadata = {
        "schema_version": 1,
        "company": company,
        "website": website,
        "site_slug": slug,
        "slot": slot,
        "branch": branch,
        "batch_id": batch_id,
        "source_run": source_run,
        "source_commit": source_commit,
        "source_candidate": candidate.name,
        "queued_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (draft / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    queue = site / "queue" / batch_id
    queue.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate / "files" / "inlined" / "index.html", queue / "index.html")
    (queue / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    git(repo, "add", "-A", "--", f"sites/{slug}")
    if git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print(f"{branch}: slot candidate is already staged")
        return
    git(repo, "-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", f"content-post: stage {slug} candidate {slot} ({batch_id})")
    git(repo, "push", "origin", f"HEAD:refs/heads/{branch}")
    print(f"{branch}: staged draft and queue snapshot for slot {slot}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-dir", type=Path, required=True)
    parser.add_argument("--job-file", type=Path, required=True)
    parser.add_argument("--content-post-dir", type=Path, required=True)
    args = parser.parse_args()
    job = read_json(args.job_file)
    row = job.get("row", {}) if isinstance(job.get("row"), dict) else {}
    company = str(row.get("business", "")).strip()
    website = str(row.get("website", "")).strip()
    if not company or not website or job.get("provider") != "chatgpt":
        raise RuntimeError("Private job record is missing its ChatGPT company and website context")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    source_commit = os.environ.get("GITHUB_SHA", "")
    if not run_id.isdigit() or not attempt.isdigit() or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("GitHub workflow run metadata is missing or invalid")
    batch_id = f"{run_id}-{attempt}"
    candidates = passed_candidates(args.candidates_dir.resolve())
    repo = args.content_post_dir.resolve()
    for slot in (1, 2, 3):
        push_slot(repo, slot, candidates[slot], company=company, website=website,
                  batch_id=batch_id, source_run=batch_id, source_commit=source_commit)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## Content-post draft slots staged\n\n- Three slot drafts and immutable queue snapshots were staged.\n- Revisions are pending; Cloudflare deployment waits until all three are promoted to main.\n")


if __name__ == "__main__":
    main()
