"""High-site candidate rules shared by the worker-side intake poller."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid5


DELIVERY_READY_EXCEPTIONS = {
    "gino's shoes & repair",
    "antique emporium of carmel",
    "goodfellas landscape",
}
MAX_SITES_PER_POLL = 24
PROVIDER = "chatgpt-worker"


def site_host(value: str) -> str:
    value = (value or "").strip()
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        hostname = parsed.hostname or ""
    except ValueError:
        return ""
    return hostname.lower().removeprefix("www.").rstrip(".")


def normalized_business(value: str) -> str:
    return " ".join((value or "").casefold().replace("’", "'").split())


def score_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def load_existing_hosts(job_directories: list[Path]) -> set[str]:
    """Read worker source/state records for new-queue duplicate protection."""
    seen: set[str] = set()
    for directory in job_directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("An existing private queue job is invalid; refusing to poll safely.") from error
            if not isinstance(record, dict):
                raise ValueError("An existing private queue job is not an object; refusing to poll safely.")
            if record.get("provider") != PROVIDER:
                continue
            row = record.get("row")
            if isinstance(row, dict):
                host = site_host(str(row.get("website", "")))
                if host:
                    seen.add(host)
    return seen


def select_high_sites(csv_path: Path, existing_hosts: set[str], max_sites: int) -> list[dict[str, Any]]:
    """Select completed confidence-3 High leads not already in the worker queue."""
    if not 1 <= max_sites <= MAX_SITES_PER_POLL:
        raise ValueError(f"max_sites must be between 1 and {MAX_SITES_PER_POLL}.")
    if not csv_path.is_file():
        raise ValueError("High/Medium candidates CSV was not found.")
    seen = set(existing_hosts)
    candidates: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("final_outcome") or "").strip().lower() != "high":
                continue
            if (row.get("assessment_state") or "").strip().lower() != "complete":
                continue
            if (row.get("confidence_level") or "").strip() != "3":
                continue
            website = (row.get("website_url") or "").strip()
            business = (row.get("business_name") or "").strip()
            if normalized_business(business) in DELIVERY_READY_EXCEPTIONS:
                continue
            try:
                parsed = urlsplit(website)
                hostname = parsed.hostname
            except ValueError:
                continue
            host = site_host(website)
            if (not host or host in seen or not business or parsed.scheme not in {"http", "https"}
                    or not hostname):
                continue
            target = {
                "website": website,
                "business": business,
                "category": (row.get("category") or "").strip() or "Local business",
            }
            if row.get("location"):
                target["location"] = row["location"].strip()
            candidates.append({"host": host, "row": target, "score": score_value(row.get("score", ""))})
    candidates.sort(key=lambda item: (-item["score"], item["host"]))
    unique: list[dict[str, Any]] = []
    selected_hosts = set(existing_hosts)
    for item in candidates:
        if item["host"] in selected_hosts:
            continue
        selected_hosts.add(item["host"])
        unique.append(item)
        if len(unique) == max_sites:
            break
    return unique


def build_source_records(
    candidates: list[dict[str, Any]],
    batch_id: str,
    source_commit: str,
    slug_map: dict[str, str],
    created_at: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """Create private intake jobs using the same stable identity and slug rules as manual intake."""
    batch_uuid = UUID(batch_id)
    updated_slugs = dict(slug_map)
    used_slugs = {value for value in updated_slugs.values() if isinstance(value, str)}
    jobs: list[dict[str, Any]] = []
    for candidate in candidates:
        host = candidate["host"]
        row = candidate["row"]
        website_identity = " ".join(str(row["website"]).strip().split()).rstrip("/").lower()
        job_id = str(uuid5(batch_uuid, website_identity))
        slug = updated_slugs.get(host)
        if not isinstance(slug, str):
            base_slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "site"
            slug = base_slug
            if slug in used_slugs:
                slug = f"{base_slug}-{hashlib.sha256(host.encode('utf-8')).hexdigest()[:6]}"
            updated_slugs[host] = slug
            used_slugs.add(slug)
        jobs.append({
            "job_id": job_id,
            "batch_id": batch_id,
            "provider": PROVIDER,
            "result_slug": slug,
            "candidate_attempt_limit": 12,
            "row": row,
        })
    batch = {
        "schema_version": 1,
        "batch_id": batch_id,
        "created_at": created_at,
        "source_commit_before_batch": source_commit,
        "job_ids": [job["job_id"] for job in jobs],
        "target_count": len(jobs),
    }
    return jobs, batch, updated_slugs
