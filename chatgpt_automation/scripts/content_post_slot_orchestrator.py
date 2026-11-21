#!/usr/bin/env python3
"""Queue, assign, and reconcile ChatGPT slot work in private content-post."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo


SLOT_BRANCHES = {number: f"chatgpt-slot{number}" for number in (1, 2, 3)}
LEDGER_PATH = Path("automation/slot-ledger.json")
SITE_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
BATCH_RE = re.compile(r"(\d+)-(\d+)")


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise RuntimeError(f"Git operation failed: {args[0]}")
    return result


def read_json(data: bytes | None) -> dict:
    if data is None:
        return {}
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_ref(repo: Path, ref: str, relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"], cwd=repo,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout if result.returncode == 0 else None


def list_ref_paths(repo: Path, ref: str, prefix: str = "sites") -> list[str]:
    result = git(repo, "ls-tree", "-r", "--name-only", ref, "--", prefix)
    return [path for path in result.stdout.splitlines() if path]


def valid_html(data: bytes) -> bool:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return bool(
        re.search(r"(?is)(<!doctype\s+html|<html\b)", text)
        and re.search(r"(?is)</html>\s*$", text)
    )


def batch_order(batch_id: str) -> tuple[int, int]:
    match = BATCH_RE.fullmatch(batch_id)
    if not match:
        raise ValueError("Invalid content-post batch ID")
    return int(match.group(1)), int(match.group(2))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(repo: Path) -> dict:
    path = repo / LEDGER_PATH
    if not path.is_file():
        return {
            "schema_version": 1,
            "updated_at_utc": None,
            "assignment_timezone": "America/New_York",
            "last_assignment_date": None,
            "active_task_id": None,
            "tasks": {},
        }
    value = read_json(path.read_bytes())
    if value.get("schema_version") != 1 or not isinstance(value.get("tasks"), dict):
        raise ValueError("The slot ledger has an unsupported or invalid schema")
    return value


def discover_slot_candidates(repo: Path) -> dict[str, dict]:
    """Build a complete site/batch queue from immutable queue files or legacy drafts."""
    discovered: dict[str, dict] = {}
    for slot, branch in SLOT_BRANCHES.items():
        ref = f"origin/{branch}"
        paths = list_ref_paths(repo, ref)
        queue_metadata = [
            path for path in paths
            if re.fullmatch(r"sites/[^/]+/queue/[^/]+/metadata\.json", path)
        ]
        seen: set[tuple[str, str]] = set()
        records = [(path, "queue") for path in queue_metadata]
        for path in paths:
            if re.fullmatch(r"sites/[^/]+/draft/metadata\.json", path):
                records.append((path, "draft"))

        for metadata_path, source_kind in records:
            metadata = read_json(read_ref(repo, ref, metadata_path))
            slug = str(metadata.get("site_slug", ""))
            batch_id = str(metadata.get("batch_id", ""))
            path_slug = Path(metadata_path).parts[1]
            if (
                metadata.get("slot") != slot
                or metadata.get("branch") != branch
                or not SITE_SLUG_RE.fullmatch(slug)
                or path_slug != slug
                or not BATCH_RE.fullmatch(batch_id)
            ):
                continue
            key = (slug, batch_id)
            if key in seen:
                continue
            if source_kind == "queue":
                source_path = metadata_path.removesuffix("metadata.json") + "index.html"
            else:
                source_path = f"sites/{slug}/draft/index.html"
            html = read_ref(repo, ref, source_path)
            if html is None or not valid_html(html):
                continue
            seen.add(key)
            task_id = f"{slug}--{batch_id}"
            task = discovered.setdefault(task_id, {
                "task_id": task_id,
                "site_slug": slug,
                "batch_id": batch_id,
                "company": str(metadata.get("company", "")).strip(),
                "website": str(metadata.get("website", "")).strip(),
                "queued_at_utc": str(metadata.get("queued_at_utc", "")),
                "status": "queued",
                "slots": {},
            })
            if task["company"] != str(metadata.get("company", "")).strip() or task["website"] != str(metadata.get("website", "")).strip():
                continue
            # Prefer immutable queue snapshots to the mutable latest-draft path.
            prior = task["slots"].get(str(slot))
            if prior is None or source_kind == "queue":
                task["slots"][str(slot)] = {
                    "status": "queued",
                    "source_path": source_path,
                    "source_candidate": str(metadata.get("source_candidate", "")),
                    "source_run": str(metadata.get("source_run", "")),
                    "source_commit": str(metadata.get("source_commit", "")),
                }
    return discovered


def merge_discovered_tasks(ledger: dict, discovered: dict[str, dict]) -> bool:
    changed = False
    tasks = ledger["tasks"]
    for task_id, candidate in discovered.items():
        if set(candidate["slots"]) != {"1", "2", "3"}:
            continue
        if not candidate["company"] or not candidate["website"]:
            continue
        if task_id not in tasks:
            tasks[task_id] = candidate
            changed = True
        elif tasks[task_id].get("status") == "queued":
            for slot, slot_candidate in candidate["slots"].items():
                prior = tasks[task_id].setdefault("slots", {}).get(slot, {})
                if "/queue/" in slot_candidate.get("source_path", "") and prior.get("source_path") != slot_candidate["source_path"]:
                    tasks[task_id]["slots"][slot] = slot_candidate
                    changed = True
    return changed


def ensure_queue_snapshots(repo: Path) -> None:
    """Migrate pre-queue drafts once and keep every batch available for assignment."""
    for slot, branch in SLOT_BRANCHES.items():
        def snapshot_legacy_drafts() -> None:
            for metadata_path in sorted((repo / "sites").glob("*/draft/metadata.json")):
                metadata = read_json(metadata_path.read_bytes())
                if metadata.get("slot") != slot or metadata.get("branch") != branch:
                    continue
                slug = str(metadata.get("site_slug", ""))
                batch_id = str(metadata.get("batch_id", ""))
                if not SITE_SLUG_RE.fullmatch(slug) or not BATCH_RE.fullmatch(batch_id):
                    continue
                draft_html = metadata_path.parent / "index.html"
                if not draft_html.is_file() or not valid_html(draft_html.read_bytes()):
                    continue
                queue = repo / "sites" / slug / "queue" / batch_id
                if (queue / "index.html").is_file() and (queue / "metadata.json").is_file():
                    continue
                queue.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(draft_html, queue / "index.html")
                queue_metadata = dict(metadata)
                queue_metadata["queued_at_utc"] = queue_metadata.get("queued_at_utc") or utc_now()
                (queue / "metadata.json").write_text(
                    json.dumps(queue_metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                )

        commit_slot_branch(repo, branch, snapshot_legacy_drafts,
                           f"content-post: preserve queued candidates for slot {slot}")


def check_task_identity(task: dict, metadata: dict, slot: int) -> bool:
    return (
        metadata.get("task_id") == task.get("task_id")
        and metadata.get("site_slug") == task.get("site_slug")
        and metadata.get("batch_id") == task.get("batch_id")
        and str(metadata.get("slot", "")) == str(slot)
        and metadata.get("branch") == SLOT_BRANCHES[slot]
    )


def commit_slot_branch(repo: Path, branch: str, mutate, message: str) -> bool:
    """Apply one idempotent branch update, retrying if a worker pushes meanwhile."""
    for attempt in range(4):
        git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
        git(repo, "switch", "--force-create", branch, f"origin/{branch}")
        should_commit = mutate()
        if should_commit is False:
            git(repo, "switch", "--force-create", "main", "origin/main")
            return False
        git(repo, "add", "-A", "--", "sites")
        if git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
            git(repo, "switch", "--force-create", "main", "origin/main")
            return False
        git(repo, "-c", "user.name=github-actions[bot]", "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", message)
        result = git(repo, "push", "origin", f"HEAD:refs/heads/{branch}", check=False)
        if result.returncode == 0:
            git(repo, "switch", "--force-create", "main", "origin/main")
            return True
        git(repo, "switch", "--force-create", "main", "origin/main")
        if attempt == 3:
            raise RuntimeError("Could not safely update a content-post slot branch after concurrent pushes")
    return False


def reconcile_returns(repo: Path, ledger: dict) -> bool:
    changed = False
    for task in ledger["tasks"].values():
        if task.get("status") not in {"assigned", "ready_for_promotion"}:
            continue
        task_id = task["task_id"]
        slug = task["site_slug"]
        for slot in (1, 2, 3):
            slot_record = task["slots"].get(str(slot), {})
            if slot_record.get("status") in {"revision_received", "promoted"}:
                continue
            branch = SLOT_BRANCHES[slot]
            base = f"sites/{slug}"
            stable_html = f"{base}/revised/index.html"
            stable_metadata = f"{base}/revised/metadata.json"
            accepted: dict = {}

            def save_revision() -> bool:
                assignment_path = repo / "todo-today" / "assignment.json"
                assignment = read_json(assignment_path.read_bytes()) if assignment_path.is_file() else {}
                result_metadata_path = repo / "todo-today" / "revised" / "metadata.json"
                result_metadata = read_json(result_metadata_path.read_bytes()) if result_metadata_path.is_file() else {}
                revised_path = repo / "todo-today" / "revised" / "index.html"
                revised = revised_path.read_bytes() if revised_path.is_file() else None
                if not check_task_identity(task, assignment, slot):
                    return False
                if not check_task_identity(task, result_metadata, slot):
                    return False
                if revised is None or not valid_html(revised):
                    return False
                current = read_json((repo / stable_metadata).read_bytes()) if (repo / stable_metadata).is_file() else {}
                prior_task_id = str(current.get("task_id", ""))
                if prior_task_id and prior_task_id != task_id:
                    prior_task = ledger["tasks"].get(prior_task_id, {})
                    if prior_task.get("status") != "promoted":
                        raise RuntimeError("Refusing to replace a revision that has not been promoted")
                target = repo / stable_html
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_file() or target.read_bytes() != revised or prior_task_id != task_id:
                    target.write_bytes(revised)
                    durable_metadata = dict(assignment)
                    durable_metadata.update({
                        "received_at_utc": utc_now(),
                        "worker_commit": git(repo, "rev-parse", "HEAD"),
                    })
                    (repo / stable_metadata).write_text(
                        json.dumps(durable_metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    )
                accepted.update(assignment)
                return True

            commit_slot_branch(
                repo, branch, save_revision,
                f"content-post: record revised slot {slot}",
            )
            if not accepted:
                continue
            slot_record["status"] = "revision_received"
            slot_record["received_at_utc"] = utc_now()
            changed = True

        if all(task["slots"].get(str(slot), {}).get("status") in {"revision_received", "promoted"}
               for slot in (1, 2, 3)):
            if task.get("status") != "ready_for_promotion":
                task["status"] = "ready_for_promotion"
                changed = True
            if ledger.get("active_task_id") == task_id:
                ledger["active_task_id"] = None
                changed = True
    return changed


def sync_promotions(repo: Path, ledger: dict) -> bool:
    changed = False
    for task in ledger["tasks"].values():
        if task.get("status") not in {"ready_for_promotion", "assigned"}:
            continue
        slug = task["site_slug"]
        root = repo / "sites" / slug / "chatgpt"
        progress_path = root / "progress.json"
        marker_path = root / "ready-for-cloudflare.json"
        if not progress_path.is_file():
            continue
        progress = read_json(progress_path.read_bytes())
        if progress.get("batch_id") != task.get("batch_id"):
            continue
        slots = progress.get("slots", {})
        for slot in (1, 2, 3):
            state = slots.get(str(slot), {})
            slot_record = task["slots"].get(str(slot), {})
            if state.get("batch_id") == task.get("batch_id") and state.get("status") == "revised_ready":
                if slot_record.get("status") != "promoted":
                    slot_record["status"] = "promoted"
                    slot_record["promoted_at_utc"] = str(progress.get("updated_at_utc", ""))
                    changed = True
        if (
            progress.get("ready_for_cloudflare") is True
            and marker_path.is_file()
            and all(task["slots"].get(str(slot), {}).get("status") == "promoted" for slot in (1, 2, 3))
        ):
            if task.get("status") != "promoted":
                task["status"] = "promoted"
                task["promoted_at_utc"] = str(progress.get("updated_at_utc", ""))
                changed = True
    return changed


def assign_task(repo: Path, task: dict, assigned_at: str) -> None:
    task["status"] = "assigning"
    task["assigned_at_utc"] = assigned_at
    for slot in (1, 2, 3):
        task["slots"][str(slot)]["status"] = "assigning"
        task["slots"][str(slot)]["assigned_at_utc"] = assigned_at


def ensure_active_assignment(repo: Path, ledger: dict) -> bool:
    task_id = ledger.get("active_task_id")
    task = ledger.get("tasks", {}).get(task_id)
    if not task or task.get("status") not in {"assigning", "assigned"}:
        return False
    changed = False
    slug = task["site_slug"]
    assigned_at = task.get("assigned_at_utc") or utc_now()
    task_id = task["task_id"]
    for slot in (1, 2, 3):
        branch = SLOT_BRANCHES[slot]
        source_path = task["slots"][str(slot)]["source_path"]
        current_assignment = read_json(read_ref(
            repo, f"origin/{branch}", "todo-today/assignment.json",
        ))
        if check_task_identity(task, current_assignment, slot):
            if task["slots"][str(slot)].get("status") not in {"assigned", "revision_received", "promoted"}:
                task["slots"][str(slot)]["status"] = "assigned"
                changed = True
            continue
        if task.get("status") != "assigning":
            raise RuntimeError("The active slot assignment changed unexpectedly; refusing to replace it")
        source = read_ref(repo, f"origin/{branch}", source_path)
        if source is None or not valid_html(source):
            raise RuntimeError("A queued slot candidate is missing or invalid")
        assignment = {
            "schema_version": 1,
            "task_id": task_id,
            "site_slug": slug,
            "company": task["company"],
            "website": task["website"],
            "batch_id": task["batch_id"],
            "slot": slot,
            "branch": branch,
            "assigned_at_utc": assigned_at,
            "source_path": source_path,
            "source_candidate": task["slots"][str(slot)].get("source_candidate", ""),
            "source_run": task["slots"][str(slot)].get("source_run", ""),
            "source_commit": task["slots"][str(slot)].get("source_commit", ""),
        }

        def write_assignment() -> bool:
            existing = repo / "todo-today" / "assignment.json"
            existing_data = read_json(existing.read_bytes()) if existing.is_file() else {}
            if check_task_identity(task, existing_data, slot):
                return False
            todo = repo / "todo-today"
            if todo.is_dir():
                shutil.rmtree(todo)
            elif todo.exists():
                todo.unlink()
            todo.mkdir(parents=True, exist_ok=True)
            (todo / "index.html").write_bytes(source)
            (todo / "assignment.json").write_text(
                json.dumps(assignment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
            )
            return True

        commit_slot_branch(repo, branch, write_assignment, f"content-post: assign slot {slot}")
        task["slots"][str(slot)]["status"] = "assigned"
        task["slots"][str(slot)]["assigned_at_utc"] = assigned_at
        changed = True
    if task.get("status") != "assigned":
        task["status"] = "assigned"
        changed = True
    return changed


def commit_ledger(repo: Path, ledger: dict) -> bool:
    path = repo / LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at_utc"] = utc_now()
    path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    git(repo, "add", "--", LEDGER_PATH.as_posix())
    if git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    git(repo, "-c", "user.name=github-actions[bot]", "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "content-post: update daily slot ledger")
    for attempt in range(5):
        result = git(repo, "push", "origin", "HEAD:refs/heads/main", check=False)
        if result.returncode == 0:
            return True
        git(repo, "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main")
        rebase = git(repo, "rebase", "origin/main", check=False)
        if rebase.returncode:
            git(repo, "rebase", "--abort", check=False)
            raise RuntimeError("Could not reconcile the slot ledger with a concurrent main-branch update")
        if attempt == 4:
            raise RuntimeError("Could not push the slot ledger after repeated concurrent updates")
    return False


def run(repo: Path, mode: str, timezone_name: str) -> dict:
    if git(repo, "status", "--porcelain").stdout.strip():
        raise RuntimeError("The content-post checkout must be clean")
    git(repo, "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main")
    git(repo, "switch", "--force-create", "main", "origin/main")
    for branch in SLOT_BRANCHES.values():
        git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")

    ensure_queue_snapshots(repo)
    for branch in SLOT_BRANCHES.values():
        git(repo, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    git(repo, "switch", "--force-create", "main", "origin/main")
    ledger = load_ledger(repo)
    original = json.dumps(ledger, sort_keys=True)
    discovered = discover_slot_candidates(repo)
    merge_discovered_tasks(ledger, discovered)
    ensure_active_assignment(repo, ledger)
    reconcile_returns(repo, ledger)
    sync_promotions(repo, ledger)

    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    assignment_made = False
    if mode == "auto" and ledger.get("active_task_id") is None and ledger.get("last_assignment_date") != today:
        candidates = [task for task in ledger["tasks"].values() if task.get("status") == "queued"]
        candidates.sort(key=lambda task: (batch_order(task["batch_id"]), task["site_slug"]))
        blocked_sites = {
            task["site_slug"] for task in ledger["tasks"].values()
            if task.get("status") in {"assigned", "ready_for_promotion"}
        }
        selected = next((task for task in candidates if task["site_slug"] not in blocked_sites), None)
        if selected is not None:
            assigned_at = utc_now()
            assign_task(repo, selected, assigned_at)
            ledger["active_task_id"] = selected["task_id"]
            ledger["last_assignment_date"] = today
            commit_ledger(repo, ledger)
            original = json.dumps(ledger, sort_keys=True)
            ensure_active_assignment(repo, ledger)
            assignment_made = True

    changed = json.dumps(ledger, sort_keys=True) != original
    if changed:
        commit_ledger(repo, ledger)
    return {
        "new_queue_tasks": len(discovered),
        "task_count": len(ledger["tasks"]),
        "assignment_made": assignment_made,
        "active": ledger.get("active_task_id") is not None,
        "ledger_changed": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-post-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("auto", "reconcile"), default="auto")
    parser.add_argument("--timezone", default="America/New_York")
    args = parser.parse_args()
    try:
        result = run(args.content_post_dir.resolve(), args.mode, args.timezone)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Slot orchestration failed ({type(error).__name__}); details are withheld from public logs.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
