#!/usr/bin/env python3
"""Bounded continuation policy and evidence handling for Duck.ai candidate batches."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


ACCESS_GATE_MARKERS = (
    "verify you are human",
    "verify that you are human",
    "captcha",
    "sign in to continue",
    "usage limit reached",
    "temporarily unavailable",
    "guest chat is gated or unavailable",
    "could not confirm it accessed the source site",
)
TARGET_PASSES = 3
MAX_ATTEMPTS_PER_BATCH = 10


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def candidate_indices(prior_attempts: int, max_attempts: int = MAX_ATTEMPTS_PER_BATCH) -> list[int]:
    """Return this batch's global candidate numbers, enforcing the 20-attempt cap."""
    if not 0 <= prior_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("prior_attempts must be between zero and ten")
    if not 1 <= max_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("max_attempts must be between one and ten")
    return list(range(prior_attempts + 1, prior_attempts + max_attempts + 1))


def access_gate_evidence(candidates_dir: Path) -> list[str]:
    evidence: set[str] = set()
    if not candidates_dir.is_dir():
        return []
    for failure_path in candidates_dir.rglob("failure.txt"):
        try:
            content = failure_path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        evidence.update(marker for marker in ACCESS_GATE_MARKERS if marker in content)
    for assessment_path in candidates_dir.rglob("source_assessment.json"):
        assessment = read_json(assessment_path)
        if assessment is None or assessment.get("access_status") != "accessed":
            evidence.add("source assessment did not confirm access")
    return sorted(evidence)


def continuation_is_eligible(
    successful_candidates: int,
    attempts: int,
    candidates_dir: Path,
    continued_from: str = "",
) -> bool:
    return (
        successful_candidates >= 0
        and attempts >= 0
        and not continued_from
        and successful_candidates < TARGET_PASSES
        and attempts == MAX_ATTEMPTS_PER_BATCH
        and not access_gate_evidence(candidates_dir)
    )


def find_parent_run(results_root: Path, parent_job_id: str, parent_run_id: int) -> tuple[Path, dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for status_path in results_root.glob("*/run-*/status.json"):
        status = read_json(status_path)
        try:
            status_run_id = int(status.get("public_workflow_run", 0) or 0) if status else 0
        except (TypeError, ValueError):
            continue
        if status and status.get("job_id") == parent_job_id and status_run_id == parent_run_id:
            matches.append((status_path.parent, status))
    if len(matches) != 1:
        raise ValueError("Parent Duck.ai run evidence was not found uniquely")
    return matches[0]


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
    parent_dir, parent_status = find_parent_run(results_root, parent_job_id, parent_run_id)
    if (
        parent_status.get("continuation_eligible") is not True
        or parent_status.get("status") != "failed"
        or int(parent_status.get("attempts", 0) or 0) != MAX_ATTEMPTS_PER_BATCH
        or int(parent_status.get("successful_candidates", -1) or 0) != expected_passes
    ):
        raise ValueError("Parent run status does not authorize this continuation")

    passing = []
    for candidate in sorted((parent_dir / "candidates").glob("run-*-site-1-candidate-*")):
        notes = read_json(candidate / "run_notes.json")
        if notes and notes.get("automated_success") is True:
            passing.append(candidate)
    if len(passing) != expected_passes:
        raise ValueError("Inherited passing-candidate folders do not match the parent status")

    prefix = destination_root / f"run-{current_run_id}-{current_run_attempt}-site-1-candidate-inherited"
    copied: list[Path] = []
    for number, candidate in enumerate(passing, start=1):
        destination = prefix.with_name(f"{prefix.name}-{number}")
        shutil.copytree(candidate, destination)
        copied.append(destination)
    return copied


def write_batch_status(
    output_path: Path,
    job_id: str,
    successful_candidates: int,
    attempts: int,
    new_attempts: int,
    public_workflow_run: int,
    candidates_dir: Path,
    continued_from: str = "",
    parent_run_id: str = "",
) -> dict[str, Any]:
    if successful_candidates < 0 or not 0 <= new_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("Candidate and new-attempt counts are outside their valid bounds")
    if not new_attempts <= attempts <= 2 * MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("Total attempts must include this batch and stay within the 20-attempt cap")
    evidence = access_gate_evidence(candidates_dir)
    status = {
        "job_id": job_id,
        "status": "passed" if successful_candidates >= TARGET_PASSES else "failed",
        "successful_candidates": successful_candidates,
        "attempts": attempts,
        "new_attempts": new_attempts,
        "continuation_eligible": continuation_is_eligible(
            successful_candidates, attempts, candidates_dir, continued_from
        ),
        "access_gate_evidence": evidence,
        "access_gate_detected": bool(evidence),
        "continued_from": {"job_id": continued_from, "run_id": parent_run_id} if continued_from else None,
        "public_workflow_run": public_workflow_run,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    indices = subparsers.add_parser("indices")
    indices.add_argument("--prior-attempts", type=int, required=True)
    indices.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_PER_BATCH)
    inherit = subparsers.add_parser("inherit")
    inherit.add_argument("--results-root", type=Path, required=True)
    inherit.add_argument("--destination-root", type=Path, required=True)
    inherit.add_argument("--parent-job-id", required=True)
    inherit.add_argument("--parent-run-id", type=int, required=True)
    inherit.add_argument("--expected-passes", type=int, required=True)
    inherit.add_argument("--current-run-id", type=int, required=True)
    inherit.add_argument("--current-run-attempt", type=int, required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--output", type=Path, required=True)
    status.add_argument("--candidates-dir", type=Path, required=True)
    status.add_argument("--job-id", required=True)
    status.add_argument("--successful", type=int, required=True)
    status.add_argument("--attempts", type=int, required=True)
    status.add_argument("--new-attempts", type=int, required=True)
    status.add_argument("--public-workflow-run", type=int, required=True)
    status.add_argument("--continued-from", default="")
    status.add_argument("--parent-run-id", default="")
    args = parser.parse_args()

    if args.command == "indices":
        print("\n".join(str(index) for index in candidate_indices(args.prior_attempts, args.max_attempts)))
    elif args.command == "inherit":
        inherit_passing_candidates(
            args.results_root,
            args.destination_root,
            args.parent_job_id,
            args.parent_run_id,
            args.expected_passes,
            args.current_run_id,
            args.current_run_attempt,
        )
    else:
        write_batch_status(
            args.output,
            args.job_id,
            args.successful,
            args.attempts,
            args.new_attempts,
            args.public_workflow_run,
            args.candidates_dir,
            args.continued_from,
            args.parent_run_id,
        )


if __name__ == "__main__":
    main()
