"""Bounded continuation and evidence handling for Duck.ai candidate batches."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


TARGET_PASSES = 3
MAX_ATTEMPTS_PER_BATCH = 12
MAX_TOTAL_ATTEMPTS = 24


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def candidate_indices(prior_attempts: int, batch_limit: int = MAX_ATTEMPTS_PER_BATCH) -> list[int]:
    if not 0 <= prior_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("prior_attempts must be between zero and twelve")
    if not 1 <= batch_limit <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("batch_limit must be between one and twelve")
    if prior_attempts + batch_limit > MAX_TOTAL_ATTEMPTS:
        raise ValueError("candidate indices cannot exceed the 24-attempt total cap")
    return list(range(prior_attempts + 1, prior_attempts + batch_limit + 1))


def automated_passing_candidates(candidates_dir: Path) -> list[Path]:
    found = []
    if candidates_dir.is_dir():
        for candidate in sorted(candidates_dir.glob("run-*-site-1-candidate-*")):
            notes = read_json(candidate / "run_notes.json")
            if notes and notes.get("counted_as_pass", notes.get("automated_success")) is True:
                found.append(candidate)
    return found


def passing_candidates(candidates_dir: Path) -> list[Path]:
    found = []
    covered_slots: set[int] = set()
    for candidate in automated_passing_candidates(candidates_dir):
        notes = read_json(candidate / "run_notes.json") or {}
        slot = notes.get("template_slot")
        if (
            notes.get("template_layout_passed") is True
            and isinstance(slot, int) and not isinstance(slot, bool) and slot in {1, 2, 3}
            and slot not in covered_slots
        ):
            found.append(candidate)
            covered_slots.add(slot)
    return found


def next_template_slot(candidates_dir: Path) -> int:
    """Choose the least-tried slot that still lacks a qualifying pass."""
    tried = {1: 0, 2: 0, 3: 0}
    passed_slots = {
        (read_json(candidate / "run_notes.json") or {}).get("template_slot")
        for candidate in passing_candidates(candidates_dir)
    }
    if candidates_dir.is_dir():
        for candidate in candidates_dir.glob("run-*-site-1-candidate-*"):
            slot = (read_json(candidate / "run_notes.json") or {}).get("template_slot")
            if isinstance(slot, int) and not isinstance(slot, bool) and slot in tried:
                tried[slot] += 1
    eligible = [slot for slot in tried if slot not in passed_slots]
    return min(eligible or tried.keys(), key=lambda slot: (tried[slot], slot))


def access_gate_evidence(candidates_dir: Path) -> list[str]:
    evidence: set[str] = set()
    if not candidates_dir.is_dir():
        return []
    for candidate in candidates_dir.glob("run-*-site-1-candidate-*"):
        notes = read_json(candidate / "run_notes.json") or {}
        if notes.get("failure_category") == "access_gate":
            evidence.add("access_gate")
        failure_path = candidate / "debug" / "failure.txt"
        try:
            message = failure_path.read_text(encoding="utf-8", errors="replace").casefold()
        except OSError:
            message = ""
        if any(marker in message for marker in (
            "captcha", "verify you are human", "sign in to continue",
            "usage limit reached", "temporarily unavailable",
        )):
            evidence.add("access_gate")
    return sorted(evidence)


def inherit_passing_candidates(
    results_root: Path,
    destination_root: Path,
    parent_job_id: str,
    parent_run_id: int,
    expected_passes: int,
    current_run_id: int,
    current_run_attempt: int,
) -> list[Path]:
    if not 0 <= expected_passes < TARGET_PASSES:
        raise ValueError("A continuation must inherit zero, one, or two passing candidates")
    matches = []
    for status_path in results_root.glob("*/run-*/status.json"):
        status = read_json(status_path)
        try:
            status_run = int(status.get("public_workflow_run", 0) or 0) if status else 0
        except (TypeError, ValueError):
            continue
        if status and status.get("job_id") == parent_job_id and status_run == parent_run_id:
            matches.append((status_path.parent, status))
    if len(matches) != 1:
        raise ValueError("Parent Duck.ai run evidence was not found uniquely")
    parent_dir, status = matches[0]
    if (
        status.get("continuation_eligible") is not True
        or status.get("status") != "failed"
        or int(status.get("attempts", 0) or 0) != MAX_ATTEMPTS_PER_BATCH
        or int(status.get("successful_candidates", -1) or 0) != expected_passes
    ):
        raise ValueError("Parent run status does not authorize this continuation")
    # Preserve earlier automated candidates in continuation evidence, even if
    # they predate template-slot qualification. They are not counted toward
    # the new three-distinct-template success gate.
    source_candidates = automated_passing_candidates(parent_dir / "candidates")
    if len(source_candidates) != expected_passes:
        raise ValueError("Parent passing-candidate folders do not match its status")
    prefix = destination_root / f"run-{current_run_id}-{current_run_attempt}-site-1-candidate-inherited"
    copied = []
    for index, candidate in enumerate(source_candidates, start=1):
        destination = prefix.with_name(f"{prefix.name}-{index}")
        shutil.copytree(candidate, destination)
        copied.append(destination)
    return copied


def write_batch_status(
    output_path: Path,
    job_id: str,
    candidates_dir: Path,
    attempts: int,
    new_attempts: int,
    public_workflow_run: int,
    continued_from: str = "",
    parent_run_id: str = "",
) -> dict[str, Any]:
    passed = passing_candidates(candidates_dir)
    evidence = access_gate_evidence(candidates_dir)
    success_count = len(passed)
    eligible = (
        not continued_from
        and success_count < TARGET_PASSES
        and attempts == MAX_ATTEMPTS_PER_BATCH
        and new_attempts == MAX_ATTEMPTS_PER_BATCH
        and not evidence
    )
    status = {
        "job_id": job_id,
        "status": "passed" if success_count >= TARGET_PASSES else "failed",
        "successful_candidates": success_count,
        "attempts": attempts,
        "new_attempts": new_attempts,
        "continuation_eligible": eligible,
        "access_gate_evidence": evidence,
        "access_gate_detected": bool(evidence),
        "continued_from": {"job_id": continued_from, "run_id": str(parent_run_id)} if continued_from else None,
        "public_workflow_run": public_workflow_run,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def write_status_from_args(args: argparse.Namespace) -> None:
    write_batch_status(
        args.output, args.job_id, args.candidates_dir, args.attempts,
        args.new_attempts, args.public_workflow_run, args.continued_from,
        args.parent_run_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    indices = subparsers.add_parser("indices")
    indices.add_argument("--prior-attempts", type=int, required=True)
    indices.add_argument("--batch-limit", type=int, default=MAX_ATTEMPTS_PER_BATCH)
    inherit = subparsers.add_parser("inherit")
    inherit.add_argument("--results-root", type=Path, required=True)
    inherit.add_argument("--destination-root", type=Path, required=True)
    inherit.add_argument("--parent-job-id", required=True)
    inherit.add_argument("--parent-run-id", type=int, required=True)
    inherit.add_argument("--expected-passes", type=int, required=True)
    inherit.add_argument("--current-run-id", type=int, required=True)
    inherit.add_argument("--current-run-attempt", type=int, required=True)
    count = subparsers.add_parser("pass-count")
    count.add_argument("--candidates-dir", type=Path, required=True)
    next_slot = subparsers.add_parser("next-slot")
    next_slot.add_argument("--candidates-dir", type=Path, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--output", type=Path, required=True)
    status.add_argument("--job-id", required=True)
    status.add_argument("--candidates-dir", type=Path, required=True)
    status.add_argument("--attempts", type=int, required=True)
    status.add_argument("--new-attempts", type=int, required=True)
    status.add_argument("--public-workflow-run", type=int, required=True)
    status.add_argument("--continued-from", default="")
    status.add_argument("--parent-run-id", default="")
    args = parser.parse_args()
    if args.command == "indices":
        print("\n".join(map(str, candidate_indices(args.prior_attempts, args.batch_limit))))
    elif args.command == "inherit":
        paths = inherit_passing_candidates(
            args.results_root, args.destination_root, args.parent_job_id,
            args.parent_run_id, args.expected_passes, args.current_run_id,
            args.current_run_attempt,
        )
        print(json.dumps([str(path) for path in paths]))
    elif args.command == "pass-count":
        print(len(passing_candidates(args.candidates_dir)))
    elif args.command == "next-slot":
        print(next_template_slot(args.candidates_dir))
    elif args.command == "status":
        write_status_from_args(args)


if __name__ == "__main__":
    main()
