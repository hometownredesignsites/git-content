from __future__ import annotations

import re
import time
from pathlib import Path


def first_visible_locator(page, selectors: list[str], timeout_ms: int):
    # Keep selector probing quick; we loop repeatedly in callers, so long
    # per-selector waits only add latency without improving reliability.
    per_selector_timeout = min(700, max(250, int(timeout_ms / max(1, len(selectors)))))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=per_selector_timeout)
            return locator
        except Exception:
            continue
    return None


def dismiss_blocking_modals(page) -> None:
    modal_selectors = [
        "#modal-moonshine-nux-v2",
        "[data-testid='modal-moonshine-nux-v2']",
    ]
    close_selectors = [
        "button[aria-label='Close']",
        "button:has-text('Close')",
        "button:has-text('Got it')",
        "button:has-text('Continue')",
        "button:has-text('Skip')",
        "button:has-text('Done')",
    ]
    for modal_selector in modal_selectors:
        modal = page.locator(modal_selector).first
        try:
            if modal.count() == 0 or not modal.is_visible():
                continue
        except Exception:
            continue
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:
            pass
        for close_selector in close_selectors:
            try:
                btn = modal.locator(close_selector).first
                if btn.count() > 0 and btn.is_visible():
                    try:
                        btn.click(timeout=1500)
                    except Exception:
                        handle = btn.element_handle()
                        if handle is not None:
                            handle.evaluate("(el) => el.click()")
                    page.wait_for_timeout(250)
                    break
            except Exception:
                continue


def find_chat_composer(page, timeout_ms: int):
    selectors = [
        "#prompt-textarea",
        "[data-testid='prompt-textarea']",
        "textarea[data-testid='prompt-textarea']",
        "form textarea#prompt-textarea",
        "form textarea[placeholder*='Message']",
        "form textarea",
        "textarea[placeholder*='Message']",
        "textarea[aria-label*='Message']",
        "textarea",
        "[contenteditable='true'][id*='prompt']",
        "[contenteditable='true'][data-testid*='prompt']",
        "[contenteditable='true'][data-lexical-editor='true']",
        "[contenteditable='true'][aria-label*='Message']",
        "[contenteditable='true'][role='textbox']",
        "div[contenteditable='true'][role='textbox']",
    ]
    deadline = time.time() + max(1.0, timeout_ms / 1000.0)
    while time.time() < deadline:
        dismiss_blocking_modals(page)
        composer = first_visible_locator(page, selectors, timeout_ms=min(2500, max(1000, timeout_ms)))
        if composer is not None:
            try:
                if composer.is_enabled():
                    return composer
            except Exception:
                return composer
        page.wait_for_timeout(350)
    return None


def assistant_turns(page):
    selectors = [
        "[data-testid^='conversation-turn-'][data-turn='assistant'] [data-message-author-role='assistant']",
        "div[data-assistant-markdown]",
        "[data-testid^='conversation-turn-'][data-turn='assistant']",
        "[data-message-author-role='assistant']",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return page.locator("[data-message-author-role='assistant']")


def extract_response_text(assistant_messages, before_count: int, before_last_text: str) -> str:
    def _normalize(text: str) -> str:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^\s*chatgpt\s+said:\s*\n+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*chatgpt\s*:\s*\n+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    after_count = assistant_messages.count()
    if after_count == 0:
        return ""
    if after_count > before_count:
        return _normalize(assistant_messages.nth(after_count - 1).inner_text())
    text = _normalize(assistant_messages.last.inner_text())
    if text and text != before_last_text:
        return text
    return ""


def extract_labeled_response(page, prompt_text: str, before_body_text: str = "") -> str:
    """Extract the reply from ChatGPT's guest UI, which may expose text labels
    instead of assistant-role DOM attributes.

    Anchor on the submitted prompt and the following "ChatGPT said:" label so
    earlier turns, navigation text, and unrelated page content are excluded.
    """
    try:
        body = page.locator("body").inner_text()
    except Exception:
        return ""
    if not body:
        return ""

    def normalize_with_offsets(value: str) -> tuple[str, list[int]]:
        chars: list[str] = []
        offsets: list[int] = []
        pending_space_index: int | None = None
        for index, char in enumerate(value or ""):
            if char.isspace():
                if chars and pending_space_index is None:
                    pending_space_index = index
                continue
            if pending_space_index is not None:
                chars.append(" ")
                offsets.append(pending_space_index)
                pending_space_index = None
            chars.append(char)
            offsets.append(index)
        return "".join(chars), offsets

    normalized_body, body_offsets = normalize_with_offsets(body)
    normalized_prompt, _ = normalize_with_offsets(prompt_text)
    start = -1
    if normalized_prompt:
        start = normalized_body.rfind(normalized_prompt)

    # If the browser rewrites whitespace inside a prompt, use the newest
    # guest user label, but only when it appeared after the pre-send snapshot.
    if start < 0:
        before_len = len(normalize_with_offsets(before_body_text)[0])
        user_matches = list(re.finditer(r"\bYou said\s*:", normalized_body, re.IGNORECASE))
        recent_users = [m for m in user_matches if m.start() >= before_len]
        if recent_users:
            start = recent_users[-1].end()
        elif user_matches and not before_body_text:
            start = user_matches[-1].end()
        else:
            return ""

    reply_label = re.search(r"\bChatGPT\s+said\s*:\s*", normalized_body[start:], re.IGNORECASE)
    if not reply_label:
        # Some page versions shorten the label.
        reply_label = re.search(r"\bChatGPT\s*:\s*", normalized_body[start:], re.IGNORECASE)
    if not reply_label:
        return ""

    response_start = start + reply_label.end()
    if response_start >= len(body_offsets):
        return ""
    raw_response_start = body_offsets[response_start - 1] + 1
    response = normalized_body[response_start:]
    footer = re.search(
        r"\b(?:ChatGPT is AI and can make mistakes\.?|Regenerate|Copy response|Copy|Read aloud|New chat)\b",
        response,
        re.IGNORECASE,
    )
    raw_response_end = len(body)
    if footer:
        footer_start = response_start + footer.start()
        raw_response_end = body_offsets[footer_start] if footer_start < len(body_offsets) else len(body)
    return body[raw_response_start:raw_response_end].strip()


def looks_like_non_answer_text(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    blocked_markers = [
        "i hit an internal automation issue while generating a response",
        "please send your message again",
        "new session started",
    ]
    return any(marker in lowered for marker in blocked_markers)


def set_composer_text(composer, text: str) -> None:
    handle = composer.element_handle()
    if handle is None:
        raise RuntimeError("Failed to resolve composer element.")
    handle.evaluate(
        """(el, value) => {
            const isEditable = el.getAttribute('contenteditable') === 'true' || el.isContentEditable;
            if (isEditable) {
                el.focus();
                el.textContent = '';
                const lines = value.split('\\n');
                for (let i = 0; i < lines.length; i++) {
                    if (i > 0) el.appendChild(document.createElement('br'));
                    el.appendChild(document.createTextNode(lines[i]));
                }
                el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return;
            }
            el.focus();
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        text,
    )


def send_prompt(page, composer, prompt_text: str) -> None:
    dismiss_blocking_modals(page)
    try:
        composer.click(timeout=3000)
    except Exception:
        composer.click(force=True, timeout=3000)
    set_composer_text(composer, prompt_text)
    send_selectors = [
        "button[data-testid='send-button']",
        "button[aria-label*='Send']:not([data-testid='composer-plus-btn'])",
        "button[aria-label*='send']:not([data-testid='composer-plus-btn'])",
        "form button:not([data-testid='composer-plus-btn']):has(svg[data-icon='arrow-up'])",
    ]
    deadline = time.time() + 15
    while time.time() < deadline:
        for selector in send_selectors:
            btn = page.locator(selector).first
            try:
                if btn.count() == 0 or not btn.is_visible() or not btn.is_enabled():
                    continue
                btn.click(timeout=2000)
                return
            except Exception:
                continue
        page.wait_for_timeout(300)
    composer.press("Enter")


def wait_for_valid_response(
    page,
    assistant_messages,
    before_count: int,
    before_last_text: str,
    wait_seconds: int,
    prompt_text: str = "",
    before_body_text: str = "",
) -> str:
    deadline = time.time() + max(1, wait_seconds)
    while time.time() < deadline:
        text = extract_response_text(assistant_messages, before_count, before_last_text)
        if not text:
            text = extract_labeled_response(page, prompt_text, before_body_text)
        lowered = text.lower()
        if text and "something went wrong" not in lowered and not looks_like_non_answer_text(text):
            return text
        page.wait_for_timeout(1000)
    return ""


def stabilize_response(
    page,
    assistant_messages,
    post_response_wait_seconds: int,
    response_settle_seconds: int,
    max_settle_wait_seconds: int,
    prompt_text: str = "",
    before_body_text: str = "",
    before_count: int = 0,
    before_last_text: str = "",
) -> str:
    if post_response_wait_seconds > 0:
        page.wait_for_timeout(post_response_wait_seconds * 1000)
    stable_for = 0
    waited = 0
    previous = ""
    while waited < max_settle_wait_seconds:
        stop_visible = False
        try:
            stop_visible = page.locator(
                "button[data-testid='stop-button'], button:has-text('Stop generating')"
            ).first.is_visible()
        except Exception:
            pass
        current = extract_response_text(assistant_messages, before_count, before_last_text)
        if not current:
            current = extract_labeled_response(page, prompt_text, before_body_text)
        if current and current == previous and not stop_visible:
            stable_for += 1
        else:
            stable_for = 0
        previous = current
        if stable_for >= max(1, response_settle_seconds):
            break
        page.wait_for_timeout(1000)
        waited += 1
    return previous
