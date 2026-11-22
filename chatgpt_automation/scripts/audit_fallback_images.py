#!/usr/bin/env python3
"""Download and visually audit every Unsplash fallback candidate.

Run from the repository root:
  python -m pip install Pillow
  python chatgpt_automation/scripts/audit_fallback_images.py

The script reads FALLBACK_IMAGES directly from prepare_candidate_context.py (AST only;
it does not import or execute that workflow module). It downloads each configured
candidate, verifies that the response is an image Pillow can fully decode, records
dimensions/bytes/SHA-256, detects duplicate photo IDs and identical image bytes,
and creates one contact sheet per pool plus a browsable HTML gallery.

A successful decode proves the file is a valid image; it does NOT prove that the
photograph semantically matches its human-written description. Review the generated
contact sheets/gallery for that final visual judgment.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import html
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow is required. Install it with: python -m pip install Pillow")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = SCRIPT_DIR / "prepare_candidate_context.py"
DEFAULT_OUTPUT = Path("artifacts/fallback-image-audit")
USER_AGENT = "FishersInfoGroup-FallbackImageAudit/1.0 (+https://github.com/hometownredesignsites/git-content)"
MAX_BYTES = 25 * 1024 * 1024
THUMB_SIZE = (440, 280)


def load_fallbacks(source: Path) -> dict:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FALLBACK_IMAGES"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise ValueError("FALLBACK_IMAGES must be a dictionary")
            return value
    raise ValueError(f"FALLBACK_IMAGES assignment not found in {source}")


def photo_id_from_url(url: str) -> str:
    match = re.search(r"/photo-([^/?]+)", urlparse(url).path)
    return match.group(1) if match else hashlib.sha1(url.encode()).hexdigest()[:12]


def download_one(item: dict, output: Path) -> dict:
    request = Request(item["url"], headers={"User-Agent": USER_AGENT, "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8"})
    result = {**item, "status": "error", "http_status": None, "content_type": None,
              "bytes": None, "width": None, "height": None, "sha256": None,
              "file": None, "error": None}
    try:
        with urlopen(request, timeout=35) as response:
            result["http_status"] = response.status
            result["content_type"] = response.headers.get("Content-Type", "").split(";")[0].lower()
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"image exceeds {MAX_BYTES} byte safety limit")
        if not data:
            raise ValueError("empty response body")
        result["bytes"] = len(data)
        # Decode/verify the actual bytes rather than trusting URL or Content-Type.
        from io import BytesIO
        with Image.open(BytesIO(data)) as probe:
            image_format = probe.format
            probe.verify()
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            result["width"], result["height"] = decoded.size
        if image_format not in {"JPEG", "PNG", "WEBP", "GIF"}:
            raise ValueError(f"unsupported decoded image format: {image_format}")
        result["format"] = image_format
        result["sha256"] = hashlib.sha256(data).hexdigest()
        filename = f'{item["pool"]}__{item["index"]:02d}__{item["photo_id"]}.{image_format.lower()}'
        target = output / "images" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        result["file"] = str(target.as_posix())
        result["status"] = "ok"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def make_contact_sheet(pool: str, records: list[dict], output: Path) -> str | None:
    valid = [r for r in records if r["status"] == "ok" and r["file"]]
    if not valid:
        return None
    cols, cell_w, cell_h, caption_h = 2, 460, 340, 60
    rows = (len(valid) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + caption_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(valid):
        x, y = (index % cols) * cell_w, (index // cols) * (cell_h + caption_h)
        try:
            with Image.open(record["file"]) as source:
                thumb = source.convert("RGB")
                thumb.thumbnail(THUMB_SIZE)
            frame = Image.new("RGB", THUMB_SIZE, "#eeeeee")
            frame.paste(thumb, ((THUMB_SIZE[0] - thumb.width) // 2, (THUMB_SIZE[1] - thumb.height) // 2))
            sheet.paste(frame, (x + 10, y + 8))
        except Exception as exc:
            draw.text((x + 10, y + 10), f"Could not render: {exc}", fill="red")
        caption = f'{record["index"]:02d} | {record["photo_id"]}'
        draw.text((x + 10, y + cell_h + 8), caption, fill="black")
        description = record["description"]
        draw.text((x + 10, y + cell_h + 29), description[:65], fill="#333333")
    path = output / "contact-sheets" / f"{pool}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, quality=88, optimize=True)
    return path.as_posix()


def write_reports(records: list[dict], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fields = ["pool", "index", "photo_id", "description", "url", "status", "http_status",
              "content_type", "format", "width", "height", "bytes", "sha256", "file", "error"]
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    (output / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    by_id, by_hash = defaultdict(list), defaultdict(list)
    for r in records:
        by_id[r["photo_id"]].append(f'{r["pool"]}[{r["index"]}]')
        if r["sha256"]:
            by_hash[r["sha256"]].append(f'{r["pool"]}[{r["index"]}]')
    duplicate_ids = {k: v for k, v in by_id.items() if len(v) > 1}
    duplicate_bytes = {k: v for k, v in by_hash.items() if len(v) > 1}
    summary = {
        "candidate_count": len(records),
        "pool_count": len({r["pool"] for r in records}),
        "downloaded_and_decoded": sum(r["status"] == "ok" for r in records),
        "failed": sum(r["status"] != "ok" for r in records),
        "unique_photo_ids": len(by_id),
        "duplicate_photo_ids": duplicate_ids,
        "identical_image_bytes": duplicate_bytes,
        "note": "Image decoding validates file integrity, not semantic relevance or licensing."
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    groups = defaultdict(list)
    for r in records:
        groups[r["pool"]].append(r)
    sheet_links = {}
    for pool, pool_records in sorted(groups.items()):
        sheet_links[pool] = make_contact_sheet(pool, pool_records, output)

    cards = []
    for pool, pool_records in sorted(groups.items()):
        cards.append(f'<section><h2>{html.escape(pool)}</h2>')
        if sheet_links.get(pool):
            rel = Path(sheet_links[pool]).relative_to(output).as_posix()
            cards.append(f'<p><a href="{html.escape(rel)}">Open contact sheet</a></p>')
        cards.append('<div class="grid">')
        for r in pool_records:
            if r["status"] == "ok":
                rel = Path(r["file"]).relative_to(output).as_posix()
                image = f'<img loading="lazy" src="{html.escape(rel)}" alt="{html.escape(r["description"])}">'
                status = f'{r["width"]}×{r["height"]} · {r["format"]} · {r["bytes"]:,} bytes'
            else:
                image = '<div class="failed">Image download/decode failed</div>'
                status = html.escape(r["error"] or "unknown error")
            cards.append(
                f'<article>{image}<strong>{r["index"]:02d} · {html.escape(r["photo_id"])}</strong>'
                f'<p>{html.escape(r["description"])}</p><small>{html.escape(status)}</small>'
                f'<p><a href="{html.escape(r["url"])}" target="_blank" rel="noreferrer">Unsplash source URL</a></p></article>'
            )
        cards.append("</div></section>")
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Fallback image audit</title>
<style>body{font:15px/1.45 system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:1200px;color:#222}
section{border-top:1px solid #ddd;padding:1rem 0 2rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
article{border:1px solid #ddd;border-radius:8px;padding:.75rem;min-width:0}img{width:100%;height:190px;object-fit:contain;background:#eee}
p{margin:.4rem 0}small{color:#555}.failed{height:190px;display:grid;place-items:center;background:#fee;color:#900}
</style></head><body><h1>Fallback image audit</h1>
<p>Review whether each photograph actually matches its description and pool. A successful image decode only confirms valid image bytes; it does not establish semantic relevance or reuse rights.</p>
""" + "\n".join(cards) + "\n</body></html>"
    (output / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="workflow file containing FALLBACK_IMAGES")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="audit artifact directory")
    parser.add_argument("--workers", type=int, default=8, help="parallel downloads (default: 8)")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")

    fallbacks = load_fallbacks(args.source)
    candidates = []
    for pool, entries in fallbacks.items():
        for index, entry in enumerate(entries, 1):
            url, description = entry
            candidates.append({"pool": pool, "index": index, "url": url,
                               "description": description, "photo_id": photo_id_from_url(url)})
    if not candidates:
        raise SystemExit("No fallback image candidates found")

    print(f"Found {len(candidates)} candidates across {len(fallbacks)} pools.")
    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, item, args.output): item for item in candidates}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            label = f'{result["pool"]}/{result["index"]}: {result["photo_id"]}'
            print(f'{"OK" if result["status"] == "ok" else "FAIL"} {label}'
                  + (f' — {result["error"]}' if result["error"] else ""))
    results.sort(key=lambda r: (r["pool"], r["index"]))
    write_reports(results, args.output)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"\nCompleted in {time.time() - started:.1f}s: {ok}/{len(results)} images decoded.")
    print(f"Open {args.output / 'index.html'} for the categorized visual gallery.")
    print(f"CSV/JSON manifests and contact sheets: {args.output}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
