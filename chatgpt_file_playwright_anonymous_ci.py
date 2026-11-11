#!/usr/bin/env python3
"""Stage-capable Playwright runner for ChatGPT guest browser execution."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

from playwright_runner.chunk_orchestrator import run_chunk_plan
from playwright_runner.diagnostics import enable_network_logging, save_failure_diagnostics
from playwright_runner.prompt_contracts import build_prompt_text, extract_json_payload
from playwright_runner.recovery import refresh_chat, start_new_chat_from_login_gate, start_new_chat_if_available
from playwright_runner.stage_runner import EmptyAssistantResponseError, run_stage_once, write_stage_outputs
from playwright_runner.browser_session import assistant_turns, find_chat_composer
from chatgpt_automation.scripts.website_chunks import CSS_PART_COUNT, HTML_PART_COUNT, WebsiteTurnError, run_website_chunks


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
    expected_language = {"css": "css", "html": "text", "json": "json"}.get(kind)
    if not expected_language:
        return response_text, {"dom_code_block_count": 1, "normalization_error": f"Unsupported rendered code kind: {kind}"}
    if language != expected_language:
        return response_text, {
            "dom_code_block_count": 1,
            "dom_code_language": language,
            "normalization_error": f"Expected a rendered {expected_language} code block.",
        }
    code = code_block.inner_text().strip("\r\n")
    if kind != "json":
        expected_total = CSS_PART_COUNT if kind == "css" else HTML_PART_COUNT
        expected_marker = f"/* CSS PART {part} OF {expected_total} */" if kind == "css" else f"<!-- HTML PART {part} OF {expected_total} -->"
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


def inspect_chatgpt_page_state(page) -> dict:
    """Classify visible access/service gates without interacting with them."""
    import re

    url = page.url
    title = page.title()
    root = page.locator("html")
    auth_gated = root.get_attribute("data-conversation-auth-gated") is not None
    conversation_gated = root.get_attribute("data-conversation-gated") is not None
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=2500)
    except Exception:
        pass

    captcha_selectors = (
        'iframe[src*="captcha" i], iframe[title*="captcha" i], '
        '[id*="captcha" i], [class*="captcha" i], [data-sitekey]'
    )
    captcha_visible = False
    captcha_nodes = page.locator(captcha_selectors)
    for index in range(min(captcha_nodes.count(), 8)):
        try:
            if captcha_nodes.nth(index).is_visible():
                captcha_visible = True
                break
        except Exception:
            continue

    visible_dialog_text = []
    dialogs = page.locator('[role="dialog"], dialog[open]')
    for index in range(min(dialogs.count(), 6)):
        dialog = dialogs.nth(index)
        try:
            if dialog.is_visible():
                visible_dialog_text.append(dialog.inner_text(timeout=1000))
        except Exception:
            continue
    dialog_text = "\n".join(visible_dialog_text)
    combined_text = f"{dialog_text}\n{body_text}"
    signals = []
    classification = "ready"

    if captcha_visible or re.search(r"verify (?:that )?you(?:'re| are) human|complete the captcha|security challenge", combined_text, re.IGNORECASE):
        classification = "captcha_required"
        signals.append("visible CAPTCHA or human-verification prompt")
    elif re.search(r"you(?:'|’)ve reached (?:your )?(?:usage )?limit|too many requests|rate limit|try again later", combined_text, re.IGNORECASE):
        classification = "rate_limited"
        signals.append("visible rate-limit or usage-limit message")
    elif auth_gated or re.search(r"/auth/(?:login|signin)|/login(?:/|$)", url, re.IGNORECASE):
        classification = "login_required"
        signals.append("ChatGPT page reports an authentication gate")
    elif conversation_gated:
        classification = "conversation_gated"
        signals.append("ChatGPT page marks the conversation as gated")
    elif re.search(r"log in or sign up|sign in to continue", combined_text, re.IGNORECASE):
        classification = "login_required"
        signals.append("visible sign-in screen blocks the conversation")
    elif re.search(
        r"something went wrong|error generating response|failed to load conversation|"
        r"chat stopped unexpectedly|unable to connect|no internet|"
        r"temporarily experiencing issues|working to restore service|"
        r"this (?:may|might) take a while",
        combined_text,
        re.IGNORECASE,
    ):
        classification = "service_error"
        signals.append("visible ChatGPT connection, response, or service error")

    observation = {
        "classification": classification,
        "url": url,
        "title": title,
        "conversation_gated": conversation_gated,
        "authentication_gated": auth_gated,
        "visible_dialog_count": len(visible_dialog_text),
        "signals": signals,
    }
    if classification != "ready":
        observation["visible_text_excerpt"] = re.sub(r"\s+", " ", combined_text).strip()[:900]
    return observation


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
    parser.add_argument("--website-run-folder", help="Enable full CSS/HTML website capture in this same ChatGPT session")
    parser.add_argument("--website-chat-id", help="Stable candidate conversation key used by the chunk manifest")
    parser.add_argument("--website-run-token", help="Resume token from the candidate checkpoint; generated when omitted")
    parser.add_argument("--website-quality-request", help="Short source-grounded request used to select QA sections")
    parser.add_argument("--website-design-reference-file", help="Shared path for the three-template HTML5 UP assessment")
    parser.add_argument("--website-design-reference-slot", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--website-context-mode",
        choices=("source", "minimal"),
        default="source",
        help="Use compact source facts for a real candidate or a synthetic prompt for the chunk ladder",
    )
    parser.add_argument(
        "--website-stop-after",
        choices=["css-1", "css-2", "css-3", "html-1", "html-2", "html-3"],
        help="Stop after validating this part and save the conversation checkpoint for the next ladder stage",
    )
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

                def recover_login_gate(observation: dict) -> tuple[dict, bool]:
                    nonlocal started_new_chat
                    if observation.get("classification") != "login_required":
                        return observation, False
                    checkpoint_path = Path(args.website_run_folder) / "chunks" / "sequence_checkpoint.json"
                    try:
                        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                        accepted_parts = checkpoint.get("accepted_parts", [])
                    except (OSError, json.JSONDecodeError):
                        # If saved conversational context is uncertain, preserve the current tab.
                        return observation, False
                    if accepted_parts:
                        return observation, False
                    if not start_new_chat_from_login_gate(page, args.timeout_ms):
                        return inspect_chatgpt_page_state(page), False
                    started_new_chat = True
                    return inspect_chatgpt_page_state(page), True

                def exchange_website_turn(turn_text: str):
                    # Reuse the existing newest-assistant-response capture on this same page.
                    before_state = inspect_chatgpt_page_state(page)
                    before_state, _ = recover_login_gate(before_state)
                    if before_state["classification"] != "ready":
                        raise WebsiteTurnError(
                            before_state["classification"],
                            f"ChatGPT page is unavailable for a website turn: {before_state['classification']}",
                            before_state,
                        )

                    def submit_turn():
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
                        return response_text, response_metadata

                    try:
                        response_text, response_metadata = submit_turn()
                    except Exception as error:
                        after_error = inspect_chatgpt_page_state(page)
                        after_error, recovered_login_gate = recover_login_gate(after_error)
                        if recovered_login_gate and after_error["classification"] == "ready":
                            # No response was captured, so retry this exact prompt in the fresh chat.
                            try:
                                response_text, response_metadata = submit_turn()
                            except Exception as retry_error:
                                retry_state = inspect_chatgpt_page_state(page)
                                if retry_state["classification"] != "ready":
                                    raise WebsiteTurnError(
                                        retry_state["classification"],
                                        f"ChatGPT page became unavailable after starting a new chat: {retry_state['classification']}; {retry_error}",
                                        retry_state,
                                    ) from retry_error
                                if isinstance(retry_error, EmptyAssistantResponseError):
                                    raise WebsiteTurnError(
                                        "empty_response",
                                        "The assistant response was empty after starting a new chat.",
                                        retry_state,
                                    ) from retry_error
                                raise
                        elif after_error["classification"] != "ready":
                            raise WebsiteTurnError(
                                after_error["classification"],
                                f"ChatGPT page became unavailable during the turn: {after_error['classification']}; {error}",
                                after_error,
                            ) from error
                        elif isinstance(error, EmptyAssistantResponseError):
                            raise WebsiteTurnError(
                                "empty_response",
                                "The assistant response was empty while the ChatGPT page remained available.",
                                after_error,
                            ) from error
                        else:
                            raise
                    after_state = inspect_chatgpt_page_state(page)
                    if after_state["classification"] != "ready":
                        raise WebsiteTurnError(
                            after_state["classification"],
                            f"ChatGPT page became unavailable after the turn: {after_state['classification']}",
                            after_state,
                        )
                    if re.search(r"DESIGN REFERENCE ASSESSMENT", turn_text, re.IGNORECASE):
                        expected_part = None
                        response_kind, response_part = "json", 0
                    else:
                        expected_part = re.search(
                            r"(?:Now produce exactly|previous response for) (CSS|HTML) PART (\d+) OF \d+",
                            turn_text,
                            re.IGNORECASE,
                        )
                        if not expected_part:
                            raise RuntimeError("Website turn prompt is missing its exact part label.")
                        response_kind, response_part = expected_part.group(1).lower(), int(expected_part.group(2))
                    normalized_text, dom_metadata = restore_newest_code_block_fences(
                        page, response_text, response_kind, response_part
                    )
                    return normalized_text, {
                        **response_metadata,
                        **dom_metadata,
                        "page_state": after_state,
                    }

                website_brief = "\n\n".join(part for part in (instructions_text, prompt_text) if part).strip()
                if args.website_context_mode == "minimal":
                    website_brief = prompt_text.strip()
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
                    stop_after=args.website_stop_after,
                    context_mode=args.website_context_mode,
                    design_reference_file=args.website_design_reference_file,
                    design_reference_slot=args.website_design_reference_slot,
                )
                if website_state.get("status") == "stage_complete":
                    notes_path = Path(args.website_run_folder) / "run_notes.json"
                    notes_path.write_text(json.dumps({
                        "status": "stage_complete",
                        "stage": website_state.get("staged_until"),
                        "accepted_parts": website_state.get("accepted_parts", []),
                        "automated_success": False,
                        "final_success": False,
                        "human_visual_review_status": "pending",
                        "context_mode": args.website_context_mode,
                    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                response_text = json.dumps({
                    "website_chunks_complete": bool(website_state.get("complete")),
                    "accepted_parts": len(website_state.get("accepted_parts", [])),
                    "website_stage": website_state.get("staged_until"),
                    "design_reference_status": website_state.get("design_reference_status"),
                    "design_reference_name": website_state.get("design_reference_name"),
                    "design_reference_slot": website_state.get("design_reference_slot"),
                    "context_mode": args.website_context_mode,
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
                    "website_stage": website_state.get("staged_until"),
                    "context_mode": args.website_context_mode,
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
