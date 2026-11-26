"""Pure queue reconciliation and claim transitions.

Callers must persist every returned mutation with compare-and-swap against the
current private branch head. These functions do not provide distributed locks.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL


LEASE = timedelta(minutes=60)
JOB_NAMESPACE = "https://github.com/hometownredesignsites/git-content-private/chatgpt-worker/"
FINAL_FILES = {
    "forty": "candidate-forty.html",
    "landed": "candidate-landed.html",
    "story": "candidate-story.html",
}


class QueueConflict(ValueError):
    """The requested transition is stale or not allowed from the current state."""


def parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Queue timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def stable_job_id(source_job_id: str) -> str:
    UUID(source_job_id)
    return str(uuid5(NAMESPACE_URL, JOB_NAMESPACE + source_job_id))


def reconcile_sources(source_jobs: list[dict[str, Any]], existing: dict[str, dict[str, Any]], now: datetime) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Import only explicitly marked worker jobs; repeated scans are idempotent."""
    current = deepcopy(existing)
    created = 0
    ignored = 0
    for source in source_jobs:
        if source.get("provider") != "chatgpt-worker":
            ignored += 1
            continue
        source_id = source.get("job_id")
        if not isinstance(source_id, str):
            ignored += 1
            continue
        job_id = stable_job_id(source_id)
        if job_id in current:
            continue
        row = source.get("row")
        slug = source.get("result_slug")
        batch_id = source.get("batch_id")
        if (not isinstance(row, dict) or not row or any(not isinstance(value, str) for value in row.values())
                or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)):
            ignored += 1
            continue
        if not isinstance(batch_id, str):
            ignored += 1
            continue
        try:
            UUID(batch_id)
        except ValueError:
            ignored += 1
            continue
        stamp = timestamp(now)
        current[job_id] = {
            "schema_version": 1,
            "job_id": job_id,
            "source_job_id": source_id,
            "batch_id": batch_id,
            "provider": "chatgpt-worker",
            "result_slug": slug,
            "row": deepcopy(row),
            "status": "queued",
            "created_at_utc": stamp,
            "updated_at_utc": stamp,
            "claim_epoch": 0,
            "claim": None,
            "attempts": [],
            "result": None,
            "handoff": {"status": "not_ready", "content_post_batch_id": None, "handed_off_at_utc": None},
        }
        created += 1
    return current, {"created": created, "ignored": ignored, "total": len(current)}


def expire_claim(job: dict[str, Any], now: datetime) -> dict[str, Any]:
    result = deepcopy(job)
    claim = result.get("claim")
    if not claim or result.get("status") not in {"claimed", "generating", "validating"}:
        return result
    if parse_time(claim["lease_expires_at_utc"]) > now:
        return result
    for attempt in reversed(result.get("attempts", [])):
        if attempt.get("claim_epoch") == result.get("claim_epoch") and attempt.get("status") == "active":
            attempt["status"] = "lease_expired"
            attempt["finished_at_utc"] = timestamp(now)
            break
    result["status"] = "queued"
    result["claim"] = None
    result["updated_at_utc"] = timestamp(now)
    return result


def claim(job: dict[str, Any], worker_id: str, token: str, now: datetime) -> dict[str, Any]:
    if not worker_id.strip() or not token:
        raise ValueError("worker_id and claim token are required")
    result = expire_claim(job, now)
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    current_claim = result.get("claim")
    if (current_claim and current_claim.get("worker_id") == worker_id
            and current_claim.get("claim_token_sha256") == token_digest
            and parse_time(current_claim["lease_expires_at_utc"]) > now):
        return result
    if result.get("status") != "queued" or result.get("claim") is not None:
        raise QueueConflict("Job is not claimable")
    epoch = int(result.get("claim_epoch", 0)) + 1
    stamp = timestamp(now)
    result["claim_epoch"] = epoch
    result["status"] = "claimed"
    result["claim"] = {
        "worker_id": worker_id,
        "claim_token_sha256": token_digest,
        "claimed_at_utc": stamp,
        "heartbeat_at_utc": stamp,
        "lease_expires_at_utc": timestamp(now + LEASE),
    }
    result.setdefault("attempts", []).append({
        "attempt": len(result.get("attempts", [])) + 1,
        "claim_epoch": epoch,
        "worker_id": worker_id,
        "started_at_utc": stamp,
        "finished_at_utc": None,
        "status": "active",
        "failure_category": None,
        "artifact_path": None,
    })
    result["updated_at_utc"] = stamp
    return result


def _assert_current_claim(job: dict[str, Any], token: str, now: datetime, epoch: int | None) -> None:
    claim_data = job.get("claim")
    if not claim_data or job.get("status") not in {"claimed", "generating", "validating"}:
        raise QueueConflict("Job has no active claim")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if digest != claim_data.get("claim_token_sha256") or (epoch is not None and epoch != job.get("claim_epoch")):
        raise QueueConflict("Claim token or epoch is stale")
    if parse_time(claim_data["lease_expires_at_utc"]) <= now:
        raise QueueConflict("Claim lease has expired")


def assert_current_claim(job: dict[str, Any], token: str, now: datetime, epoch: int) -> None:
    """Validate a worker fencing token before publishing any result artifacts."""
    _assert_current_claim(job, token, now, epoch)


def heartbeat(job: dict[str, Any], token: str, now: datetime, epoch: int) -> dict[str, Any]:
    _assert_current_claim(job, token, now, epoch)
    result = deepcopy(job)
    result["claim"]["heartbeat_at_utc"] = timestamp(now)
    result["claim"]["lease_expires_at_utc"] = timestamp(now + LEASE)
    result["updated_at_utc"] = timestamp(now)
    if result["status"] == "claimed":
        result["status"] = "generating"
    return result


def complete(job: dict[str, Any], token: str, now: datetime, epoch: int, result_record: dict[str, Any]) -> dict[str, Any]:
    _assert_current_claim(job, token, now, epoch)
    if not isinstance(result_record, dict):
        raise QueueConflict("Result record must be an object")
    if result_record.get("qa_status") != "PASS":
        raise QueueConflict("Only a complete PASS result can finish a generation job")
    candidates = result_record.get("candidates", {})
    if not isinstance(candidates, dict):
        raise QueueConflict("Result candidates must be an object")
    if set(candidates) != set(FINAL_FILES):
        raise QueueConflict("Result must contain exactly Forty, Landed, and Story")
    for slot, filename in FINAL_FILES.items():
        candidate = candidates[slot]
        if not isinstance(candidate, dict):
            raise QueueConflict(f"Result candidate {slot} must be an object")
        if candidate.get("filename") != filename or candidate.get("qa_status") != "PASS":
            raise QueueConflict(f"Candidate {slot} is missing or did not pass")
        size = candidate.get("bytes")
        digest = candidate.get("sha256")
        if (isinstance(size, bool) or not isinstance(size, int) or size <= 0
                or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise QueueConflict(f"Candidate {slot} has no verified byte count and SHA-256")
    updated = deepcopy(job)
    updated["result"] = deepcopy(result_record)
    updated["status"] = "completed"
    updated["claim"] = None
    updated["handoff"]["status"] = "pending"
    updated["updated_at_utc"] = timestamp(now)
    for attempt in reversed(updated.get("attempts", [])):
        if attempt.get("claim_epoch") == epoch and attempt.get("status") == "active":
            attempt["status"] = "completed"
            attempt["finished_at_utc"] = timestamp(now)
            break
    return updated


def reserve_handoff(job: dict[str, Any], batch_id: str, now: datetime) -> dict[str, Any]:
    """Persist one stable content-post batch ID before any slot branch writes."""
    result_data = job.get("result")
    if job.get("status") != "completed" or not isinstance(result_data, dict) or result_data.get("qa_status") != "PASS":
        raise QueueConflict("Only a completed PASS job can enter content-post handoff")
    if not re.fullmatch(r"[0-9]+-[0-9]+", batch_id):
        raise ValueError("Content-post batch IDs must match the existing numeric-numeric format")
    result = deepcopy(job)
    handoff = result.setdefault("handoff", {})
    current_id = handoff.get("content_post_batch_id")
    if current_id:
        if current_id != batch_id:
            raise QueueConflict("A different content-post batch ID is already reserved")
        if handoff.get("status") not in {"pending", "handed_off"}:
            raise QueueConflict("Job handoff is not in a reservable state")
        return result
    if handoff.get("status") != "pending":
        raise QueueConflict("Only a pending handoff can reserve a content-post batch")
    stamp = timestamp(now)
    handoff["content_post_batch_id"] = batch_id
    handoff["reserved_at_utc"] = stamp
    handoff["status"] = "pending"
    result["updated_at_utc"] = stamp
    return result


def mark_handed_off(job: dict[str, Any], batch_id: str, now: datetime) -> dict[str, Any]:
    """Record handoff only after all three slot branches contain the batch."""
    result_data = job.get("result")
    if job.get("status") != "completed" or not isinstance(result_data, dict) or result_data.get("qa_status") != "PASS":
        raise QueueConflict("Only a completed PASS job can be handed off")
    handoff = job.get("handoff", {})
    if handoff.get("content_post_batch_id") != batch_id:
        raise QueueConflict("Content-post batch ID does not match the reserved handoff")
    if handoff.get("status") == "handed_off":
        return deepcopy(job)
    if handoff.get("status") != "pending":
        raise QueueConflict("Job handoff is not pending")
    result = deepcopy(job)
    result["handoff"]["status"] = "handed_off"
    result["handoff"]["handed_off_at_utc"] = timestamp(now)
    result["updated_at_utc"] = timestamp(now)
    return result
