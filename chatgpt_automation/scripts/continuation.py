#!/usr/bin/env python3
"""Bounded continuation policy and evidence handling for ChatGPT candidate batches."""

from __future__ import annotations

import argparse
import json
import re
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
BLOCKED_CLASSIFICATIONS = {
    "captcha_required",
    "rate_limited",
    "login_required",
    "conversation_gated",
    "service_error",
}
TARGET_PASSES = 3
MAX_ATTEMPTS_PER_BATCH = 12
NON_BLOCKING_LOGIN_EVIDENCE = {"login_required", "sign in to continue"}


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def candidate_indices(prior_attempts: int, max_attempts: int = MAX_ATTEMPTS_PER_BATCH) -> list[int]:
    """Return one batch of global candidate numbers, with a 24-attempt total cap."""
    if not 0 <= prior_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("prior_attempts must be between zero and twelve")
    if not 1 <= max_attempts <= MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("max_attempts must be between one and twelve")
    if prior_attempts + max_attempts > 2 * MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("candidate indices cannot exceed the 24-attempt total cap")
    return list(range(prior_attempts + 1, prior_attempts + max_attempts + 1))


def _candidate_slot(candidate_dir: Path) -> int | None:
    audit = read_json(candidate_dir / "debug" / "design_reference.json")
    try:
        slot = int(audit.get("template_slot")) if audit else 0
    except (TypeError, ValueError):
        return None
    return slot if slot in {1, 2, 3} else None


def successful_template_slots(candidates_dir: Path) -> set[int]:
    """Return distinct slots represented by automated-passing candidate folders."""
    slots: set[int] = set()
    if not candidates_dir.is_dir():
        return slots
    for candidate_dir in candidates_dir.glob("run-*-site-1-candidate-*"):
        if not candidate_dir.is_dir():
            continue
        notes = read_json(candidate_dir / "run_notes.json")
        slot = _candidate_slot(candidate_dir)
        if notes and notes.get("automated_success") is True and slot is not None:
            slots.add(slot)
    return slots


def next_template_slot(candidates_dir: Path, candidate_index: int) -> int:
    """Choose the least-attempted slot that does not yet have a passing candidate."""
    attempts = {slot: 0 for slot in (1, 2, 3)}
    if candidates_dir.is_dir():
        for candidate_dir in candidates_dir.glob("run-*-site-1-candidate-*"):
            if not candidate_dir.is_dir():
                continue
            slot = _candidate_slot(candidate_dir)
            if slot is not None:
                attempts[slot] += 1
    filled = successful_template_slots(candidates_dir)
    available = [slot for slot in (1, 2, 3) if slot not in filled]
    if not available:
        raise ValueError("all three template slots already have passing candidates")
    preferred = ((candidate_index - 1) % 3) + 1
    rotation = [((preferred - 1 + offset) % 3) + 1 for offset in range(3)]
    return min(available, key=lambda slot: (attempts[slot], rotation.index(slot)))


def _collect_classifications(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        classification = value.get("classification")
        if isinstance(classification, str) and classification in BLOCKED_CLASSIFICATIONS:
            found.add(classification)
        for child in value.values():
            _collect_classifications(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_classifications(child, found)


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
    for metadata_path in candidates_dir.rglob("*.json"):
        if metadata_path.name not in {"runner_metadata.json", "sequence_checkpoint.json"}:
            continue
        metadata = read_json(metadata_path)
        if metadata is not None:
            _collect_classifications(metadata, evidence)
    return sorted(evidence)


def continuation_is_eligible(
    successful_candidates: int,
    attempts: int,
    candidates_dir: Path,
    continued_from: str = "",
) -> bool:
    evidence = access_gate_evidence(candidates_dir)
    blocking_evidence = set(evidence) - NON_BLOCKING_LOGIN_EVIDENCE
    return (
        0 <= successful_candidates < TARGET_PASSES
        and attempts == MAX_ATTEMPTS_PER_BATCH
        and not continued_from
        and not blocking_evidence
    )


def observed_candidate_counts(candidates_dir: Path) -> tuple[int, int]:
    successful = len(successful_template_slots(candidates_dir))
    attempts = 0
    if not candidates_dir.is_dir():
        return successful, attempts
    for candidate_dir in candidates_dir.glob("run-*-site-1-candidate-*"):
        if not candidate_dir.is_dir():
            continue
        if re.search(r"-candidate-\d+$", candidate_dir.name):
            attempts += 1
    return successful, attempts


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
        raise ValueError("Parent ChatGPT run evidence was not found uniquely")
    return matches[0]


def inherit_passing_candidates(
    results_root: Path,
    destination_root: Path,
    parent_job_id: str,
    parent_run_id: int,
    expected_passes: int,
    current_run_id: int,
    current_run_attempt: int,
    design_reference_output: Path | None = None,
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
    copied = []
    for number, candidate in enumerate(passing, start=1):
        destination = prefix.with_name(f"{prefix.name}-{number}")
        shutil.copytree(candidate, destination)
        copied.append(destination)
    if design_reference_output is not None:
        plan_path = next(
            (candidate / "debug" / "design_references.json" for candidate in passing
             if (candidate / "debug" / "design_references.json").is_file()),
            None,
        )
        if plan_path is not None:
            design_reference_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan_path, design_reference_output)
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
    derive_candidate_counts: bool = False,
    prior_attempts: int = 0,
) -> dict[str, Any]:
    if derive_candidate_counts:
        successful_candidates, new_attempts = observed_candidate_counts(candidates_dir)
        attempts = prior_attempts + new_attempts
    if successful_candidates < 0 or not 0 <= new_attempts <= 2 * MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("Candidate and new-attempt counts are outside their valid bounds")
    if not new_attempts <= attempts <= 2 * MAX_ATTEMPTS_PER_BATCH:
        raise ValueError("Total attempts must include this batch and stay within the 24-attempt cap")
    evidence = access_gate_evidence(candidates_dir)
    non_retryable_evidence = sorted(set(evidence) - NON_BLOCKING_LOGIN_EVIDENCE)
    passed_slots = sorted(successful_template_slots(candidates_dir))
    status = {
        "job_id": job_id,
        "status": "passed" if successful_candidates >= TARGET_PASSES and len(passed_slots) == TARGET_PASSES else "failed",
        "successful_candidates": successful_candidates,
        "successful_template_slots": passed_slots,
        "attempts": attempts,
        "new_attempts": new_attempts,
        "continuation_eligible": continuation_is_eligible(
            successful_candidates, attempts, candidates_dir, continued_from
        ),
        "access_gate_evidence": evidence,
        "access_gate_detected": bool(evidence),
        "non_retryable_access_classifications": non_retryable_evidence,
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
    next_slot = subparsers.add_parser("next-slot")
    next_slot.add_argument("--candidates-dir", type=Path, required=True)
    next_slot.add_argument("--candidate-index", type=int, required=True)
    pass_count = subparsers.add_parser("pass-count")
    pass_count.add_argument("--candidates-dir", type=Path, required=True)
    inherit = subparsers.add_parser("inherit")
    inherit.add_argument("--results-root", type=Path, required=True)
    inherit.add_argument("--destination-root", type=Path, required=True)
    inherit.add_argument("--parent-job-id", required=True)
    inherit.add_argument("--parent-run-id", type=int, required=True)
    inherit.add_argument("--expected-passes", type=int, required=True)
    inherit.add_argument("--current-run-id", type=int, required=True)
    inherit.add_argument("--current-run-attempt", type=int, required=True)
    inherit.add_argument("--design-reference-output", type=Path)
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
    status.add_argument("--derive-candidate-counts", action="store_true")
    status.add_argument("--prior-attempts", type=int, default=0)
    args = parser.parse_args()
    if args.command == "indices":
        print("\n".join(map(str, candidate_indices(args.prior_attempts, args.max_attempts))))
    elif args.command == "next-slot":
        print(next_template_slot(args.candidates_dir, args.candidate_index))
    elif args.command == "pass-count":
        print(len(successful_template_slots(args.candidates_dir)))
    elif args.command == "inherit":
        inherit_passing_candidates(args.results_root, args.destination_root, args.parent_job_id,
                                   args.parent_run_id, args.expected_passes, args.current_run_id,
                                   args.current_run_attempt, args.design_reference_output)
    else:
        write_batch_status(args.output, args.job_id, args.successful, args.attempts,
                           args.new_attempts, args.public_workflow_run, args.candidates_dir,
                           args.continued_from, args.parent_run_id, args.derive_candidate_counts,
                           args.prior_attempts)


if __name__ == "__main__":
    main()
