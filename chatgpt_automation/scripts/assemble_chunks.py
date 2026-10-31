"""Verify the 4 CSS and 8 HTML captures, then assemble the website files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from capture_chunk import expected_parts


def assemble(run_dir: Path) -> dict:
    manifest_path = run_dir / "chunks" / "capture_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Capture manifest is missing.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parts = manifest.get("parts", [])
    actual = [(item.get("kind"), item.get("part")) for item in parts]
    if actual != expected_parts():
        raise ValueError(f"Expected 4 CSS then 8 HTML chunks; captured {actual!r}.")

    css_parts: list[str] = []
    html_parts: list[str] = []
    for item in parts:
        chunk_path = run_dir / item["chunk_file"]
        if not chunk_path.is_file():
            raise ValueError(f"Missing captured chunk: {chunk_path.name}")
        code = chunk_path.read_text(encoding="utf-8")
        if hashlib.sha256(code.encode("utf-8")).hexdigest() != item.get("sha256"):
            raise ValueError(f"Captured chunk hash mismatch: {chunk_path.name}")
        kind, part = item["kind"], item["part"]
        total = 4 if kind == "css" else 8
        marker = f"/* {kind.upper()} PART {part} OF {total} */" if kind == "css" else f"<!-- {kind.upper()} PART {part} OF {total} -->"
        first_nonblank = next((line.strip() for line in code.splitlines() if line.strip()), "")
        if first_nonblank != marker:
            raise ValueError(f"Marker mismatch in {chunk_path.name}")
        (css_parts if kind == "css" else html_parts).append(code.rstrip() + "\n")

    html = "\n".join(html_parts)
    css = "\n".join(css_parts)
    if not re.search(r"</body\s*>\s*</html\s*>\s*$", html, re.IGNORECASE):
        raise ValueError("Assembled HTML must end with </body></html>.")
    if not re.search(r"<link\b[^>]*href\s*=\s*['\"](?:\./)?styles\.css['\"]", html, re.IGNORECASE):
        raise ValueError("Assembled HTML must link to styles.css before CSS inlining.")

    files_dir = run_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / "styles.css").write_text(css, encoding="utf-8")
    (files_dir / "index.html").write_text(html, encoding="utf-8")
    return {"assembled": True, "css_parts": 4, "html_parts": 8,
            "css_bytes": len(css.encode("utf-8")), "html_bytes": len(html.encode("utf-8"))}
