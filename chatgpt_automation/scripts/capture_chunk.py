"""Validate and persist one ChatGPT website code chunk."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def expected_parts() -> list[tuple[str, int]]:
    return [("css", part) for part in range(1, 5)] + [("html", part) for part in range(1, 9)]


def accept_chunk(run_dir: Path, *, kind: str, part: int, response: str,
                 code: str, language: str, chat_url: str) -> dict:
    total = 4 if kind == "css" else 8
    label = f"{kind.upper()} PART {part} OF {total}"
    expected_marker = f"/* {label} */" if kind == "css" else f"<!-- {label} -->"
    first_nonblank = next((line.strip() for line in code.splitlines() if line.strip()), "")
    if first_nonblank != expected_marker:
        raise ValueError(f"{label}: expected marker {expected_marker!r}, found {first_nonblank!r}")
    accepted_languages = {"css"} if kind == "css" else {"text", "html", "plaintext", "plain-text"}
    if language.lower().replace("language-", "") not in accepted_languages:
        raise ValueError(f"{label}: unexpected code language {language!r}")
    if len(code.strip()) < 80:
        raise ValueError(f"{label}: code block is unexpectedly short ({len(code.strip())} chars)")

    manifest_path = run_dir / "chunks" / "capture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "chat_url": chat_url, "parts": []
    }
    if manifest.get("chat_url") != chat_url:
        raise ValueError("Chat URL changed during chunk capture; refusing to combine conversations.")
    key = (kind, part)
    if any((item["kind"], item["part"]) == key for item in manifest["parts"]):
        raise ValueError(f"{label}: refusing to overwrite an accepted chunk")
    code = code.rstrip() + "\n"
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if any(item.get("sha256") == digest for item in manifest["parts"]):
        raise ValueError(f"{label}: chunk duplicates a previously accepted part")

    chunks_dir = run_dir / "chunks"
    response_path = chunks_dir / "responses" / f"{kind}-{part}.txt"
    chunk_path = chunks_dir / f"{kind}-{part}.{'css' if kind == 'css' else 'html'}"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    if response_path.exists() or chunk_path.exists():
        raise ValueError(f"{label}: output already exists; refusing to overwrite")
    response_path.write_text(response.rstrip() + "\n", encoding="utf-8")
    chunk_path.write_text(code, encoding="utf-8")
    manifest["parts"].append({
        "kind": kind,
        "part": part,
        "response_file": response_path.relative_to(run_dir).as_posix(),
        "chunk_file": chunk_path.relative_to(run_dir).as_posix(),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "characters": len(code),
        "sha256": digest,
    })
    expected_order = {item: index for index, item in enumerate(expected_parts())}
    manifest["parts"].sort(key=lambda item: expected_order[(item["kind"], item["part"])])
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"label": label, "characters": len(code), "sha256": digest}
