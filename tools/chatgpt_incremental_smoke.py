#!/usr/bin/env python3
"""Exercise labeled CSS/HTML turns incrementally in one ChatGPT conversation.

The script reuses the production Playwright browser/session and newest-response
capture helpers. It intentionally sends only small synthetic code fragments.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright_runner.diagnostics import enable_network_logging
from playwright_runner.recovery import start_new_chat_if_available
from playwright_runner.stage_runner import run_stage_once
from chatgpt_automation.scripts.capture_chunk import PART_TOTALS
from chatgpt_file_playwright_anonymous_ci import restore_newest_code_block_fences


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_prompts(token: str) -> list[tuple[str, str, int, str]]:
    prompts: list[tuple[str, str, int, str]] = []
    for part, focus in enumerate([
        "Define a small neutral palette and readable base typography.",
        "Style a compact site header and one primary button.",
        "Style the content layout, mobile breakpoint, and visible keyboard focus state.",
    ], start=1):
        accepted = (
            f"CSS PART {part - 1} OF 3 was validated and saved. Continue the same page; do not repeat it.\n"
            if part > 1 else ""
        )
        prompt = (
            f"{accepted}Continue this tiny synthetic test page. {focus} Keep this response under 12 CSS rules.\n"
            f"State `RUN TOKEN: {token}` and `CSS PART {part} OF 3` outside the code block. "
            f"Return exactly one fenced code block labeled `css`; its first nonblank line must be exactly "
            f"`/* CSS PART {part} OF 3 */`. Do not add another code block."
        )
        prompts.append(("css", "css", part, prompt))

    html_sections = [
        "Create the document shell, metadata, linked stylesheet, header, hero, and a short overview. Do not close body or html yet.",
        "Add a services section with two concise list items and one clearly labeled sample quotation.",
        "Add a process section and a simple name/email form; do not claim the form submits.",
        "Add a secondary information section, navigation landmark, footer, and close body and html.",
    ]
    for part, focus in enumerate(html_sections, start=1):
        accepted = (
            f"CSS PART 3 OF 3 was validated and saved. Continue the same page.\n"
            if part == 1 else
            f"HTML PART {part - 1} OF 4 was validated and saved. Continue the same page; do not repeat it.\n"
        )
        prompt = (
            f"{accepted}Continue the same tiny synthetic test page and markup. {focus}\n"
            f"State `RUN TOKEN: {token}` and `HTML PART {part} OF 4` outside the code block. "
            f"Return exactly one fenced code block labeled `text`; its first nonblank line must be exactly "
            f"`<!-- HTML PART {part} OF 4 -->`. Do not add another code block."
        )
        prompts.append(("html", "text", part, prompt))
    return prompts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-folder", type=Path, required=True)
    parser.add_argument("--user-data-dir", type=Path, required=True)
    parser.add_argument("--error-screenshot", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=180000)
    parser.add_argument("--wait-seconds", type=int, default=45)
    parser.add_argument("--settle-seconds", type=int, default=3)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    run = args.run_folder.resolve()
    debug = run / "debug"
    debug.mkdir(parents=True, exist_ok=True)
    chat_id = "incremental-css-html-smoke"
    token = secrets.token_hex(8)
    transcript = run / "conversation_transcript.jsonl"
    milestones = []

    def log_turn(role: str, part: str, text: str, **metadata: object) -> None:
        item = {"at_utc": now(), "role": role, "part": part, "text": text, **metadata}
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(args.user_data_dir.resolve()),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            enable_network_logging(page, debug / "network.log", enabled=True)
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=args.timeout_ms)
            start_new_chat_if_available(page, args.timeout_ms)

            setup_prompt = (
                f"This is a short synthetic website generation test. Remember the run token {token}. "
                "Reply exactly: READY"
            )
            log_turn("user", "setup", setup_prompt)
            setup_response, setup_meta = run_stage_once(
                page=page, timeout_ms=args.timeout_ms, prompt_text=setup_prompt,
                wait_seconds=args.wait_seconds, post_response_wait_seconds=args.settle_seconds,
                response_settle_seconds=args.settle_seconds, max_settle_wait_seconds=90,
                allow_retry=False, stage_name="incremental_setup", error_screenshot=args.error_screenshot.resolve(),
            )
            log_turn("assistant", "setup", setup_response, metadata=setup_meta)
            if setup_response.strip() != "READY":
                raise RuntimeError(f"Setup turn failed exact-response check: {setup_response[:300]!r}")
            milestones.append({"stage": "setup", "status": "passed", "response": setup_response})
            write_json(run / "milestones.json", milestones)

            for kind, language, part, prompt in build_prompts(token):
                label = f"{kind.upper()} PART {part} OF {PART_TOTALS[kind]}"
                log_turn("user", label, prompt)
                started = time.monotonic()
                response, response_meta = run_stage_once(
                    page=page, timeout_ms=args.timeout_ms, prompt_text=prompt,
                    wait_seconds=args.wait_seconds, post_response_wait_seconds=args.settle_seconds,
                    response_settle_seconds=args.settle_seconds, max_settle_wait_seconds=180,
                    allow_retry=False, stage_name=f"incremental_{kind}_{part}",
                    error_screenshot=args.error_screenshot.resolve(),
                )
                normalized, dom_meta = restore_newest_code_block_fences(page, response, kind, part)
                log_turn("assistant", label, normalized, metadata={**response_meta, **dom_meta,
                         "duration_seconds": round(time.monotonic() - started, 3)})
                raw_path = debug / "captured_responses" / f"{kind}-{part}.txt"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(normalized, encoding="utf-8")
                command = [
                    sys.executable, "chatgpt_automation/scripts/capture_chunk.py", str(run), str(raw_path),
                    "--kind", kind, "--part", str(part), "--chat-id", chat_id, "--run-token", token,
                ]
                result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError(f"{label} validation failed: {(result.stderr or result.stdout).strip()}")
                milestones.append({"stage": label, "status": "passed", "capture": json.loads(result.stdout)})
                write_json(run / "milestones.json", milestones)
                print(f"PASS {label}: {result.stdout.strip()}", flush=True)

            assemble = subprocess.run(
                [sys.executable, "chatgpt_automation/scripts/assemble_chunks.py", str(run)],
                capture_output=True, text=True, encoding="utf-8",
            )
            if assemble.returncode:
                raise RuntimeError(f"Chunk assembly validation failed: {(assemble.stderr or assemble.stdout).strip()}")
            milestones.append({"stage": "assembly-contract", "status": "passed", "result": json.loads(assemble.stdout)})
            write_json(run / "milestones.json", milestones)
            print("PASS: setup, 3 CSS parts, 4 HTML parts, and assembly contract.", flush=True)
            return 0
        except Exception as error:
            milestones.append({"stage": "first-failure", "status": "failed", "error": str(error), "at_utc": now()})
            write_json(run / "milestones.json", milestones)
            raise
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
