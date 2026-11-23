#!/usr/bin/env python3
"""Build the single-file ChatGPT browser runner from the maintained QA modules."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
import zlib


SCRIPTS = Path(__file__).resolve().parent
OUTPUT = SCRIPTS / "browser_qa_standalone.py"
COMPACT_OUTPUT = SCRIPTS / "browser_qa_standalone_compact.py"
CHUNKS_DIR = SCRIPTS / "browser_qa_payload_chunks"
CHUNK_MANIFEST = SCRIPTS / "browser_qa_payload_manifest.json"
PAYLOAD_CHUNK_SIZE = 4000


def _nodes(path: Path, names: set[str]) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    return [
        ast.get_source_segment(source, node)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id in names
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else [ast.Name(id=node.name)])
        )
    ]


def _browser_body() -> str:
    path = SCRIPTS / "browser_qa.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.If))]
    # Preserve every browser QA definition and CLI body, but discard the module's imports.
    return "\n\n".join(ast.get_source_segment(source, node) for node in nodes)


def build() -> None:
    headers = '''#!/usr/bin/env python3
"""Self-contained Chromium/Playwright QA runner for the website POC skill.

Generated from browser_qa.py and its exact helper implementations. Runtime imports
are limited to Python's standard library and Playwright; no repository checkout or
sibling scripts are required.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import concurrent.futures
import hashlib
import html as html_module
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

'''
    helper_names = {
        "SECTION_ALIASES", "_required_sections", "_looks_like_image",
        "SOURCE_IMAGE_CDN_SUFFIXES", "_is_source_image_host_allowed",
        "CSS_URL_RE", "IMAGE_ATTRS", "SRCSET_ATTRS", "SVG_IMAGE_ATTRS",
        "MAX_IMAGE_BYTES", "MAX_TOTAL_IMAGE_BYTES", "_srcset_urls", "_external_url",
        "_references_from_html", "_validate_image_bytes", "_read_image", "_signature_mime",
        "_embed_url", "_rewrite_srcset", "_rewrite_css", "_rewrite_html",
        "build_embedded_screenshot_html",
    }
    source_assets = SCRIPTS / "screenshot_assets.py"
    template_profile_code = '''
QA_TEMPLATE_PROFILES = {
    "forty": {"slug": "forty", "signature_id": "forty-image-tiles", "profile": "forty"},
    "landed": {"slug": "landed", "signature_id": "landed-alternating-spotlights", "profile": "landed"},
    "story": {"slug": "story", "signature_id": "story-fullbleed-divided-panels-gallery", "profile": "story"},
}
QA_TEMPLATE_URLS = {
    "forty": "https://html5up.net/forty",
    "landed": "https://html5up.net/landed",
    "story": "https://html5up.net/story",
}

def qa_profile(reference):
    if not isinstance(reference, dict):
        return None
    slug = urlsplit(str(reference.get("template_url", ""))).path.strip("/").split("/")[-1].lower()
    return QA_TEMPLATE_PROFILES.get(slug)

def selection_is_supported(references):
    if not isinstance(references, list) or len(references) != 3:
        return False
    slugs = {urlsplit(str(item.get("template_url", ""))).path.strip("/").split("/")[-1].lower()
             for item in references if isinstance(item, dict)}
    return slugs == set(QA_TEMPLATE_PROFILES)

'''
    image_allowlist = _nodes(SCRIPTS / "prepare_candidate_context.py", {"SOURCE_IMAGE_CDN_SUFFIXES", "_is_source_image_host_allowed"})
    quality_nodes = _nodes(SCRIPTS / "site_quality.py", {"SECTION_ALIASES", "_required_sections", "_looks_like_image"})
    asset_nodes = _nodes(source_assets, helper_names - {"SECTION_ALIASES", "_required_sections", "_looks_like_image", "SOURCE_IMAGE_CDN_SUFFIXES", "_is_source_image_host_allowed"})
    body = _browser_body()
    body = body.replace("SCRIPT_DIR = Path(__file__).resolve().parent", "")
    body = body.replace("def main() -> int:", "def main(argv: list[str] | None = None, emit: bool = True) -> int:")
    body = body.replace("args = parser.parse_args()", "args = parser.parse_args(argv)")
    body = body.replace('print(json.dumps(report, indent=2, ensure_ascii=False))', 'if emit:\n        print(json.dumps(report, indent=2, ensure_ascii=False))')
    body = body.replace('''if __name__ == "__main__":
    raise SystemExit(main())''', "")
    integration = '''
def _run_chatgpt_candidates_sync(candidates, request, output_dir, source_url="", image_assets_manifest=None):
    """Run all three exact candidate strings in this Python session.

    candidates: [{"candidate_id": "forty|landed|story", "html": str | bytes}]
    Returns paths to the saved production HTML and candidate-specific evidence.
    """
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError("Use a new, empty output directory so evidence cannot be mixed across runs.")
    required = {"forty", "landed", "story"}
    if (not isinstance(candidates, list) or len(candidates) != 3
            or {item.get("candidate_id") for item in candidates if isinstance(item, dict)} != required):
        raise ValueError("Provide exactly one candidate each for forty, landed, and story.")
    summary = {"status": "pass", "runner": "browser_qa_standalone.py", "candidates": {}}
    with tempfile.TemporaryDirectory(prefix="website-poc-chatgpt-run-") as staging:
        for item in candidates:
            candidate_id = item["candidate_id"]
            candidate_html = item.get("html")
            if not isinstance(candidate_html, (str, bytes)) or not candidate_html.strip():
                raise ValueError(f"Candidate {candidate_id} has no HTML string.")
            html_bytes = candidate_html if isinstance(candidate_html, bytes) else candidate_html.encode("utf-8")
            try:
                html_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"Candidate {candidate_id} is not UTF-8 HTML: {error}") from error
            final_html = output_root / f"candidate-{candidate_id}.html"
            final_html.write_bytes(html_bytes)
            run_dir = Path(staging) / candidate_id
            inlined = run_dir / "files" / "inlined"
            debug = run_dir / "debug"
            inlined.mkdir(parents=True)
            debug.mkdir(parents=True)
            (inlined / "index.html").write_bytes(html_bytes)
            (run_dir / "run_notes.json").write_text(json.dumps({"source_url": source_url}), encoding="utf-8")
            (debug / "design_reference.json").write_text(json.dumps({
                "status": "selected", "design_reference": {"template_url": QA_TEMPLATE_URLS[candidate_id]}
            }), encoding="utf-8")
            evidence_dir = output_root / "evidence" / candidate_id
            (debug / "screenshots").mkdir(parents=True, exist_ok=True)
            qa_args = [str(run_dir), request, "--offline-no-network"]
            if image_assets_manifest is not None:
                qa_args.extend(["--image-assets-manifest", str(image_assets_manifest)])
            main(qa_args, emit=False)
            report_path = debug / "browser_qa.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            evidence_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(report_path, evidence_dir / "browser_qa.json")
            manifest_path = debug / "image_embed_manifest.json"
            if manifest_path.exists():
                shutil.copy2(manifest_path, evidence_dir / "image_embed_manifest.json")
            screenshot_dest = evidence_dir / "screenshots"
            if (debug / "screenshots").exists():
                shutil.copytree(debug / "screenshots", screenshot_dest, dirs_exist_ok=True)
            candidate_record = {
                "status": report.get("status", "blocked"),
                "html_sha256": hashlib.sha256(html_bytes).hexdigest(),
                "html_path": str(final_html),
                "report_path": str(evidence_dir / "browser_qa.json"),
                "screenshots": [str(path) for path in sorted(screenshot_dest.glob("*.png"))],
                "image_gate": report.get("image_gate", {}),
                "checks": report.get("checks", {}),
            }
            summary["candidates"][candidate_id] = candidate_record
            if candidate_record["status"] != "pass":
                summary["status"] = "blocked" if candidate_record["status"] == "blocked" else "fail"
    summary_path = output_root / "browser_qa_summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")
    return summary

def run_chatgpt_candidates(candidates, request, output_dir, source_url="", image_assets_manifest=None):
    """Notebook-safe entry point; isolates synchronous Playwright in a worker thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_chatgpt_candidates_sync(candidates, request, output_dir, source_url, image_assets_manifest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            _run_chatgpt_candidates_sync, candidates, request, output_dir, source_url, image_assets_manifest
        ).result()

'''
    OUTPUT.write_text(headers + "\n\n".join(quality_nodes + image_allowlist) + "\n\n" + template_profile_code + "\n\n" + "\n\n".join(asset_nodes) + "\n\n" + body + "\n\n" + integration + '\nif __name__ == "__main__":\n    raise SystemExit(main())\n', encoding="utf-8")
    standalone_bytes = OUTPUT.read_bytes()
    compressed_payload = base64.b85encode(zlib.compress(standalone_bytes, 9)).decode("ascii")
    wrapped_payload = "\n".join(
        "    " + repr(compressed_payload[index:index + 100])
        for index in range(0, len(compressed_payload), 100)
    )
    compact_source = f'''#!/usr/bin/env python3
"""Compact transport wrapper for the self-contained ChatGPT browser QA runner.

The compressed payload is the complete browser_qa_standalone.py source, verified
by SHA-256 before it is compiled and executed. This wrapper avoids copying a
100+ KB script into ChatGPT Python Run while keeping the runner self-contained.
"""
from __future__ import annotations

import base64 as _base64
import hashlib as _hashlib
import zlib as _zlib

_SOURCE_SHA256 = "{hashlib.sha256(standalone_bytes).hexdigest()}"
_COMPRESSED_SOURCE_B85 = (\n{wrapped_payload}\n)
_source = _zlib.decompress(_base64.b85decode(_COMPRESSED_SOURCE_B85)).decode("utf-8")
if _hashlib.sha256(_source.encode("utf-8")).hexdigest() != _SOURCE_SHA256:
    raise RuntimeError("Embedded browser QA runner SHA-256 mismatch")
exec(compile(_source, "browser_qa_standalone.py", "exec"), globals())
del _base64, _hashlib, _zlib, _source, _COMPRESSED_SOURCE_B85
'''
    COMPACT_OUTPUT.write_text(compact_source, encoding="utf-8")
    CHUNKS_DIR.mkdir(exist_ok=True)
    payload_manifest = {
        "format": "base85(zlib(utf8(browser_qa_standalone.py)))",
        "chunk_size_chars": PAYLOAD_CHUNK_SIZE,
        "chunk_count": (len(compressed_payload) + PAYLOAD_CHUNK_SIZE - 1) // PAYLOAD_CHUNK_SIZE,
        "payload_chars": len(compressed_payload),
        "payload_sha256": hashlib.sha256(compressed_payload.encode("ascii")).hexdigest(),
        "runner_source_sha256": hashlib.sha256(standalone_bytes).hexdigest(),
        "runner_source_bytes": len(standalone_bytes),
        "chunks": [],
    }
    for index in range(payload_manifest["chunk_count"]):
        chunk = compressed_payload[index * PAYLOAD_CHUNK_SIZE:(index + 1) * PAYLOAD_CHUNK_SIZE]
        chunk_source = f"runner_payload_parts[{index}] = {chunk!r}\n"
        chunk_path = CHUNKS_DIR / f"part-{index + 1:02d}.py"
        chunk_path.write_text(chunk_source, encoding="utf-8")
        payload_manifest["chunks"].append({
            "index": index,
            "path": f"chatgpt_automation/scripts/browser_qa_payload_chunks/{chunk_path.name}",
            "chars": len(chunk),
            "sha256": hashlib.sha256(chunk.encode("ascii")).hexdigest(),
        })
    CHUNK_MANIFEST.write_text(
        json.dumps(payload_manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    build()
