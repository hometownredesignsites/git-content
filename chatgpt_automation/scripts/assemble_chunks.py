"""Verify two ordered CSS captures and two HTML captures, then assemble website files."""

import argparse
import hashlib
import json
import re
from pathlib import Path


CSS_PART_COUNT = 2
HTML_PART_COUNT = 2
EXPECTED = [("css", number) for number in range(1, CSS_PART_COUNT + 1)] + [("html", number) for number in range(1, HTML_PART_COUNT + 1)]


MENU_TOGGLE_FALLBACK_CSS = """/* Keep the generated mobile menu icon visibly rendered. */
.menu-toggle {
  flex-direction: column;
  gap: 4px;
}

.menu-toggle > span[aria-hidden=\"true\"] {
  display: block;
  width: 20px;
  height: 2px;
  flex: 0 0 2px;
  border-radius: 2px;
  background-color: currentColor;
}
"""


def fail(message):
    raise SystemExit(f"assembly rejected: {message}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_folder", type=Path)
    args = parser.parse_args()
    run = args.run_folder.resolve()
    chunks = run / "chunks"
    manifest_path = chunks / "capture_manifest.json"
    if not manifest_path.is_file():
        fail("capture manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("chat_id"):
        fail("capture manifest is missing its conversation ID")
    if manifest.get("run_token") and any(entry.get("run_token") != manifest["run_token"] for entry in manifest.get("parts", [])):
        fail("part run token differs from the candidate manifest")
    parts = manifest.get("parts", [])
    actual = [(item.get("kind"), item.get("part")) for item in parts]
    if actual != EXPECTED:
        fail(f"expected two ordered CSS responses followed by two HTML responses; found {actual}")
    css, html = [], []
    seen_hashes = set()
    for entry in parts:
        path = run / entry["chunk_file"]
        if not path.is_file():
            fail(f"chunk file is missing: {path}")
        code = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if digest != entry.get("sha256"):
            fail(f"chunk changed since capture: {path.name}")
        if digest in seen_hashes:
            fail(f"repeated chunk content detected: {path.name}")
        seen_hashes.add(digest)
        kind, part = entry["kind"], entry["part"]
        expected_marker = f"/* CSS PART {part} OF {CSS_PART_COUNT} */" if kind == "css" else f"<!-- HTML PART {part} OF {HTML_PART_COUNT} -->"
        first_nonblank = next((line.strip() for line in code.splitlines() if line.strip()), "")
        if first_nonblank != expected_marker:
            fail(f"part marker mismatch: {path.name}")
        (css if kind == "css" else html).append(code.rstrip() + "\n")
    html_text = "\n".join(html)
    if not re.search(r"</body>\s*</html>\s*$", html_text, re.IGNORECASE):
        fail("assembled HTML does not end with </body></html>")
    files = run / "files"
    files.mkdir(parents=True, exist_ok=True)
    assembled_css = "\n".join(css).rstrip() + "\n\n" + MENU_TOGGLE_FALLBACK_CSS
    (files / "styles.css").write_text(assembled_css, encoding="utf-8")
    (files / "index.html").write_text(html_text, encoding="utf-8")
    print(json.dumps({"assembled": True, "chat_id": manifest.get("chat_id"), "css_parts": CSS_PART_COUNT, "html_parts": HTML_PART_COUNT,
                      "index_html_bytes": (files / "index.html").stat().st_size,
                      "styles_css_bytes": (files / "styles.css").stat().st_size}))


if __name__ == "__main__":
    main()
