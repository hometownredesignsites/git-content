"""Validate an existing private Git Content job and emit a private assessment target."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def select_source_html(source_candidate: Path) -> Path:
    """Prefer the preserved original; use the current inline page for legacy candidates."""
    inline_dir = source_candidate / "files" / "inlined"
    original = inline_dir / "index-old.html"
    current = inline_dir / "index.html"
    return original if original.is_file() else current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_file", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-candidate-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    job = json.loads(args.job_file.read_text(encoding="utf-8"))
    if not isinstance(job, dict) or job.get("job_id") != args.job_id or job.get("provider") != "chatgpt":
        raise SystemExit("The selected private Git Content job record is invalid.")
    row = job.get("row")
    if not isinstance(row, dict):
        raise SystemExit("The selected private job has no target row.")
    fields = {str(key).strip().lower(): " ".join(str(value or "").split()) for key, value in row.items()}
    website, business, category = (fields.get(name, "") for name in ("website", "business", "category"))
    parsed = urlsplit(website)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise SystemExit("The configured target website must be a public HTTP(S) URL.")
    if not business or not category:
        raise SystemExit("The selected private job is missing configured business or category fields.")

    if not re.fullmatch(r"[0-9]+-[0-9]+", args.source_run_id):
        raise SystemExit("The selected source run ID is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}", args.source_candidate_id):
        raise SystemExit("The selected source candidate ID is invalid.")
    results_root = args.results_root.resolve()
    slug_map_path = results_root / "private_automation" / "queue" / "result-slugs.json"
    if not slug_map_path.is_file():
        raise SystemExit("The private results checkout is missing the existing result-slug configuration.")
    slug_map = json.loads(slug_map_path.read_text(encoding="utf-8"))
    site_slug = slug_map.get((parsed.hostname or "").lower().removeprefix("www."))
    if not isinstance(site_slug, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", site_slug):
        raise SystemExit("The configured website has no safe private results slug.")
    source_candidate = (
        results_root / "results" / site_slug / f"run-{args.source_run_id}" / "candidates" / args.source_candidate_id
    ).resolve()
    if not source_candidate.is_dir():
        raise SystemExit("The selected source candidate was not found under this configured target and run.")
    try:
        source_candidate.relative_to(results_root / "results")
    except ValueError as error:
        raise SystemExit("The selected source candidate must be inside the private results tree.") from error
    inline_html = source_candidate / "files" / "inlined" / "index.html"
    source_html = select_source_html(source_candidate)
    notes_path = source_candidate / "run_notes.json"
    inputs_path = source_candidate / "debug" / "inputs.json"
    if not inline_html.is_file() or not notes_path.is_file() or not inputs_path.is_file():
        raise SystemExit("The selected private candidate is missing inline HTML, inputs, or run notes.")
    run_status_path = source_candidate.parent.parent / "status.json"
    run_status = json.loads(run_status_path.read_text(encoding="utf-8")) if run_status_path.is_file() else {}
    if (
        run_status.get("job_id") != args.job_id
        or run_status.get("status") != "passed"
        or int(run_status.get("successful_candidates", 0) or 0) < 3
    ):
        raise SystemExit("The selected source run does not belong to this job or is not a completed three-candidate run.")
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    source_url = str(inputs.get("source_url", "")).strip()
    source_host = (urlsplit(source_url).hostname or "").lower().removeprefix("www.")
    target_host = (parsed.hostname or "").lower().removeprefix("www.")
    if not source_host or source_host != target_host:
        raise SystemExit("The selected candidate source URL does not match the configured private target.")
    if source_html.stat().st_size < 100:
        raise SystemExit("The selected candidate source HTML is unexpectedly small.")

    target = {
        "job_id": args.job_id,
        "website": website,
        "source_url": source_url,
        "source_run_id": args.source_run_id,
        "source_candidate_id": args.source_candidate_id,
        "business": business,
        "category": category,
        "location": fields.get("location", ""),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(target, ensure_ascii=False), encoding="utf-8")

    # Hide all customer-provided values in Actions logs before any later step can fail.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            source_path = str(source_html)
            handle.write(f"site_slug={site_slug}\n")
            handle.write(f"source_html_file={source_path}\n")
            handle.write(f"candidate_dir={source_candidate}\n")
    for value in target.values():
        if value:
            print(f"::add-mask::{value}")
    print("Loaded one configured private customer target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
