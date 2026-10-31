#!/usr/bin/env python3
"""Stage-capable Playwright runner for ChatGPT guest browser execution."""

from __future__ import annotations

import argparse
import importlib
import re
import subprocess
import sys
from pathlib import Path

from playwright_runner.chunk_orchestrator import run_chunk_plan
from playwright_runner.diagnostics import enable_network_logging, save_failure_diagnostics
from playwright_runner.prompt_contracts import build_prompt_text, extract_json_payload
from playwright_runner.recovery import refresh_chat, start_new_chat_if_available
from playwright_runner.stage_runner import run_stage_once, write_stage_outputs
from playwright_runner.browser_session import assistant_turns
from chatgpt_automation.scripts.website_chunks import run_website_chunks


def ensure_package(module_name: str, pip_name: str | None = None):
    target = pip_name or module_name.split(".")[0]
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", target])
        return importlib.import_module(module_name)


def ensure_browser_installed() -> None:
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def restore_newest_code_block_fences(page, response_text: str, kind: str, part: int) -> tuple[str, dict]:
    """Restore Markdown fences omitted by Playwright's existing DOM inner_text capture.

    The runner still determines and captures the newest assistant response. ChatGPT's
    rendered code block exposes its language and contents as DOM, while ``inner_text``
    omits the literal triple-backtick delimiters. This adapter validates that the
    newest assistant message has exactly one real code block and reconstructs its
    Markdown representation for the chunk validator.
    """
    messages = assistant_turns(page)
    if messages.count() == 0:
        return response_text, {"dom_code_block_count": 0, "normalization_error": "No newest assistant message is available."}
    message = messages.last
    pre_blocks = message.locator("pre")
    code_blocks = message.locator("pre code[data-code-language]")
    if pre_blocks.count() != 1 or code_blocks.count() != 1:
        return response_text, {
            "dom_code_block_count": pre_blocks.count(),
            "dom_labeled_code_block_count": code_blocks.count(),
            "normalization_error": "Expected exactly one rendered assistant code block.",
        }

    code_block = code_blocks.first
    language = (code_block.get_attribute("data-code-language") or "").strip().lower()
    expected_language = "css" if kind == "css" else "text"
    if language != expected_language:
        return response_text, {
            "dom_code_block_count": 1,
            "dom_code_language": language,
            "normalization_error": f"Expected a rendered {expected_language} code block.",
        }
    code = code_block.inner_text().strip("\r\n")
    expected_marker = (
        f"/* CSS PART {part} OF 4 */" if kind == "css"
        else f"<!-- HTML PART {part} OF 8 -->"
    )
    marker = re.search(rf"(?m)^[ \t]*{re.escape(expected_marker)}[ \t]*$", code)
    if not marker:
        return response_text, {
            "dom_code_block_count": 1,
            "dom_code_language": language,
            "normalization_error": "Rendered code block does not begin with the expected in-code part marker.",
        }

    code_offset = response_text.find(code)
    if code_offset < 0:
        return response_text, {
            "dom_code_block_count": 1,
            "dom_code_language": language,
            "normalization_error": "Newest-response text did not contain the rendered code block contents.",
        }
    prefix_lines = response_text[:code_offset].rstrip().splitlines()
    if not prefix_lines or prefix_lines[-1].strip().lower() != language:
        return response_text, {
            "dom_code_block_count": 1,
            "dom_code_language": language,
            "normalization_error": "Newest-response text is missing the code block language label before its contents.",
        }
    outside_before = "\n".join(prefix_lines[:-1]).rstrip()
    outside_after = response_text[code_offset + len(code):]
    normalized = f"{outside_before}\n```{language}\n{code}\n```{outside_after}"
    return normalized, {
        "dom_code_block_count": 1,
        "dom_code_language": language,
        "markdown_fences_restored_from_rendered_dom": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a named Playwright stage against ChatGPT as guest.")
    parser.add_argument("--stage-name", default="generic")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--instructions-file")
    parser.add_argument("--context-file")
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--parsed-output-file")
    parser.add_argument("--metadata-output-file")
    parser.add_argument("--expect-json", action="store_true")
    parser.add_argument("--fail-if-invalid-json", action="store_true")
    parser.add_argument("--response-mode", default="text", choices=["text", "markdown", "json"])
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--wait-seconds", type=int, default=60)
    parser.add_argument("--post-response-wait-seconds", type=int, default=10)
    parser.add_argument("--response-settle-seconds", type=int, default=8)
    parser.add_argument("--max-settle-wait-seconds", type=int, default=180)
    parser.add_argument("--user-data-dir", default=".playwright-chatgpt-profile")
    parser.add_argument("--omit-sections", default="")
    parser.add_argument("--start-new-chat", action="store_true")
    parser.add_argument("--refresh-before-send", action="store_true")
    parser.add_argument("--allow-retry", action="store_true")
    parser.add_argument("--refresh-before-retry", action="store_true")
    parser.add_argument("--network-log", action="store_true")
    parser.add_argument("--network-log-file", default="chatgpt_network.log")
    parser.add_argument("--error-screenshot", default="chatgpt_playwright_error.png")
    parser.add_argument("--chunks", type=int, default=1)
    parser.add_argument("--chunk-mode", choices=["none", "map_reduce", "finalize_on_last_chunk", "legacy"], default="none")
    parser.add_argument("--website-run-folder", help="Enable 4-CSS/8-HTML website capture in this same ChatGPT session")
    parser.add_argument("--website-chat-id", help="Stable candidate conversation key used by the chunk manifest")
    parser.add_argument("--website-run-token", help="Resume token from the candidate checkpoint; generated when omitted")
    parser.add_argument("--website-quality-request", help="Short source-grounded request used to select QA sections")
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    playwright_sync_api = ensure_package("playwright.sync_api")
    sync_playwright = playwright_sync_api.sync_playwright

    input_file = Path(args.input_file).expanduser().resolve()
    instructions_file = Path(args.instructions_file).expanduser().resolve() if args.instructions_file else None
    context_file = Path(args.context_file).expanduser().resolve() if args.context_file else None
    output_file = Path(args.output_file).expanduser().resolve()
    parsed_output_file = Path(args.parsed_output_file).expanduser().resolve() if args.parsed_output_file else None
    metadata_output_file = Path(args.metadata_output_file).expanduser().resolve() if args.metadata_output_file else None
    user_data_dir = Path(args.user_data_dir).expanduser().resolve()
    network_log_file = Path(args.network_log_file).expanduser().resolve()
    error_screenshot = Path(args.error_screenshot).expanduser().resolve() if args.error_screenshot else None

    omit_sections = [s.strip() for s in args.omit_sections.split(",") if s.strip()]
    input_text, instructions_text = build_prompt_text(input_file, instructions_file=instructions_file, omit_sections=omit_sections)

    prompt_parts = []
    if context_file is not None and context_file.exists():
        context_text = context_file.read_text(encoding="utf-8").strip()
        if context_text:
            prompt_parts.append("Structured context:\n" + context_text)
    prompt_parts.append(input_text)
    prompt_text = "\n\n".join([p for p in prompt_parts if p]).strip()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            enable_network_logging(page, network_log_file, enabled=args.network_log)
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)

            if args.refresh_before_send:
                refresh_chat(page, args.timeout_ms)

            started_new_chat = False
            if args.start_new_chat:
                started_new_chat = start_new_chat_if_available(page, args.timeout_ms)

            if args.website_run_folder:
                if not args.website_chat_id:
                    raise RuntimeError("--website-chat-id is required with --website-run-folder.")

                def exchange_website_turn(turn_text: str):
                    # Reuse the existing newest-assistant-response capture on this same page.
                    response_text, response_metadata = run_stage_once(
                        page=page,
                        timeout_ms=args.timeout_ms,
                        prompt_text=turn_text,
                        wait_seconds=args.wait_seconds,
                        post_response_wait_seconds=args.post_response_wait_seconds,
                        response_settle_seconds=args.response_settle_seconds,
                        max_settle_wait_seconds=args.max_settle_wait_seconds,
                        allow_retry=False,
                        stage_name="website_chunk",
                        error_screenshot=error_screenshot,
                    )
                    expected_part = re.search(
                        r"(?:Now produce exactly|previous response for) (CSS|HTML) PART (\d+) OF \d+",
                        turn_text,
                        re.IGNORECASE,
                    )
                    if not expected_part:
                        if re.fullmatch(
                            r"HTML PART 8 OF 8 was validated and saved\. Reply exactly: ACK HTML 8/8",
                            turn_text.strip(),
                            re.IGNORECASE,
                        ):
                            return response_text, {**response_metadata, "website_final_ack": True}
                        raise RuntimeError("Website turn prompt is missing its exact part label.")
                    normalized_text, dom_metadata = restore_newest_code_block_fences(
                        page, response_text, expected_part.group(1).lower(), int(expected_part.group(2))
                    )
                    return normalized_text, {**response_metadata, **dom_metadata}

                website_brief = "\n\n".join(part for part in (instructions_text, prompt_text) if part).strip()
                source_match = re.search(r'"requested_url"\s*:\s*"(https?://[^\"]+)"', prompt_text)
                quality_request = args.website_quality_request or "Redesign this organization with a source-supported hero, contact section, and substantive footer. Use relevant imagery."
                if source_match:
                    quality_request = f"Source website: {source_match.group(1)}. {quality_request}"
                website_state = run_website_chunks(
                    run_folder=args.website_run_folder,
                    chat_id=args.website_chat_id,
                    source_facts_and_design_brief=website_brief,
                    exchange=exchange_website_turn,
                    conversation_url=lambda: page.url,
                    run_token=args.website_run_token,
                    quality_request=quality_request,
                )
                response_text = json.dumps({
                    "website_chunks_complete": bool(website_state.get("complete")),
                    "accepted_parts": len(website_state.get("accepted_parts", [])),
                    "conversation_url": website_state.get("conversation_url"),
                    "run_folder": str(Path(args.website_run_folder).resolve()),
                }, ensure_ascii=False)
                run_metadata = {
                    "attempt": 1,
                    "retry_count": 0,
                    "thread_reused": True,
                    "new_chat_started": started_new_chat,
                    "website_chunks": True,
                    "accepted_parts": len(website_state.get("accepted_parts", [])),
                    "final_url": page.url,
                }
            elif args.chunk_mode != "none" and args.chunks > 1:
                response_text = run_chunk_plan(
                    page=page,
                    prompt_text=prompt_text,
                    instructions_text=instructions_text,
                    chunks=args.chunks,
                    mode=args.chunk_mode,
                    timeout_ms=args.timeout_ms,
                    wait_seconds=args.wait_seconds,
                    post_response_wait_seconds=args.post_response_wait_seconds,
                    response_settle_seconds=args.response_settle_seconds,
                    max_settle_wait_seconds=args.max_settle_wait_seconds,
                )
                run_metadata = {
                    "attempt": 1,
                    "retry_count": 0,
                    "used_retry": False,
                    "page_refreshed": bool(args.refresh_before_send),
                    "thread_reused": not started_new_chat,
                    "new_chat_started": started_new_chat,
                    "chunk_mode": args.chunk_mode,
                    "chunks": args.chunks,
                }
            else:
                response_text, run_metadata = run_stage_once(
                    page=page,
                    timeout_ms=args.timeout_ms,
                    prompt_text=(f"{instructions_text}\n\n{prompt_text}" if instructions_text else prompt_text),
                    wait_seconds=args.wait_seconds,
                    post_response_wait_seconds=args.post_response_wait_seconds,
                    response_settle_seconds=args.response_settle_seconds,
                    max_settle_wait_seconds=args.max_settle_wait_seconds,
                    allow_retry=args.allow_retry,
                    refresh_before_retry=args.refresh_before_retry,
                    stage_name=args.stage_name,
                    error_screenshot=error_screenshot,
                )
                run_metadata["page_refreshed"] = bool(run_metadata.get("page_refreshed")) or bool(args.refresh_before_send)
                run_metadata["thread_reused"] = not started_new_chat
                run_metadata["new_chat_started"] = started_new_chat
            run_metadata["final_url"] = page.url

            if args.expect_json and args.fail_if_invalid_json and extract_json_payload(response_text) is None:
                raise RuntimeError(f"Stage {args.stage_name} expected valid JSON but did not receive it.")

            write_stage_outputs(
                response_text=response_text,
                output_file=output_file,
                metadata_output_file=metadata_output_file,
                parsed_output_file=parsed_output_file,
                stage_name=args.stage_name,
                expect_json=bool(args.expect_json),
                run_metadata=run_metadata,
                response_mode=args.response_mode,
            )
        except Exception:
            save_failure_diagnostics(page, error_screenshot)
            raise
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        msg = str(exc).lower()
        if "executable doesn't exist" in msg or "please run the following command to download new browsers" in msg:
            ensure_browser_installed()
            raise SystemExit(run())
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
