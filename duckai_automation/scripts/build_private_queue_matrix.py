#!/usr/bin/env python3
"""Resolve an opaque public queue marker into a matrix of private target IDs."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from private_queue_api import read_private_json


MARKER_PATTERN = re.compile(r"^\.private-queue/pending/([A-Za-z0-9._-]+)\.json$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def changed_marker_paths() -> list[str]:
    before = os.environ.get("GITHUB_EVENT_BEFORE", "")
    after = os.environ.get("GITHUB_SHA", "")
    if not after:
        raise RuntimeError("The push commit SHA is unavailable.")
    if before and not set(before) == {"0"}:
        result = subprocess.run(
            ["git", "diff", "--name-only", before, after],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", after],
            check=True,
            capture_output=True,
            text=True,
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    marker_paths = [path for path in changed_marker_paths() if MARKER_PATTERN.fullmatch(path)]
    if len(marker_paths) != 1:
        raise RuntimeError("A queue push must add or update exactly one private batch marker.")
    match = MARKER_PATTERN.fullmatch(marker_paths[0])
    assert match is not None
    marker = json.loads(Path(marker_paths[0]).read_text(encoding="utf-8"))
    batch_id = str(marker.get("batch_id", ""))
    chunk_index = marker.get("chunk_index")
    if not ID_PATTERN.fullmatch(batch_id):
        raise RuntimeError("The queue marker has an invalid batch ID.")
    if not isinstance(chunk_index, int) or chunk_index < 0:
        raise RuntimeError("The queue marker has an invalid chunk index.")
    if Path(marker_paths[0]).name != f"{batch_id}-{chunk_index:04d}.json":
        raise RuntimeError("The queue marker filename does not match its batch and chunk IDs.")
    manifest_path = f"private_automation/queue/batches/{batch_id}/manifest.json"
    manifest = read_private_json(manifest_path)
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or chunk_index >= len(chunks):
        raise RuntimeError("The private batch manifest does not contain the requested chunk.")
    site_ids = chunks[chunk_index]
    if not isinstance(site_ids, list) or not site_ids:
        raise RuntimeError("The private batch chunk is empty or invalid.")
    targets = []
    for site_index, site_id in enumerate(site_ids, start=1):
        if not isinstance(site_id, str) or not ID_PATTERN.fullmatch(site_id):
            raise RuntimeError("The private batch contains an invalid target ID.")
        targets.append({"batch_id": batch_id, "chunk_index": chunk_index, "site_id": site_id, "site_index": site_index})
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GITHUB_OUTPUT is not available.")
    matrix = json.dumps(targets, separators=(",", ":"))
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write(f"targets={matrix}\n")
    print(f"Prepared {len(targets)} private target(s) for batch {batch_id}, chunk {chunk_index}.")


if __name__ == "__main__":
    main()
