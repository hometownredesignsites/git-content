from __future__ import annotations

from .browser_session import find_chat_composer


def click_retry_if_visible(page) -> bool:
    retry_selectors = [
        "button:has-text('Retry')",
        "button:has(div:has-text('Retry'))",
        "div.text-token-text-error button:has-text('Retry')",
        "div.text-token-text-error button",
        "[data-testid='retry-button']",
        ".text-token-text-error button",
    ]
    for selector in retry_selectors:
        try:
            buttons = page.locator(selector)
            count = min(buttons.count(), 5)
            for i in range(count):
                retry_btn = buttons.nth(i)
                if retry_btn.is_visible() and retry_btn.is_enabled():
                    try:
                        retry_btn.click(timeout=3000)
                    except Exception:
                        handle = retry_btn.element_handle()
                        if handle is not None:
                            handle.evaluate("(el) => el.click()")
                        else:
                            continue
                    page.wait_for_timeout(1500)
                    return True
        except Exception:
            continue
    return False


def start_new_chat_if_available(page, timeout_ms: int) -> bool:
    try:
        page.keyboard.press("Control+Shift+O")
        page.wait_for_timeout(1200)
        composer = find_chat_composer(page, timeout_ms=1500)
        if composer is not None:
            return True
    except Exception:
        pass

    selectors = [
        "[data-testid='create-new-chat-button']",
        "button:has-text('New chat')",
        "a:has-text('New chat')",
        "a[href*='new-chat']",
    ]
    for selector in selectors:
        candidate = page.locator(selector).first
        try:
            if candidate.count() > 0 and candidate.is_visible():
                candidate.click()
                page.wait_for_timeout(1200)
                composer = find_chat_composer(page, timeout_ms=timeout_ms)
                if composer is not None:
                    return True
        except Exception:
            continue
    return False


def start_new_chat_from_login_gate(page, timeout_ms: int) -> bool:
    """Use the visible login-screen New chat action only when it restores a composer."""
    try:
        body_text = page.locator("body").inner_text(timeout=2500)
    except Exception:
        return False
    lowered = body_text.casefold()
    if "sign in to continue" not in lowered and "log in or sign up" not in lowered:
        return False

    # Prefer the centered sign-in card's action over the sidebar's New chat link.
    for selector in (
        "[role='dialog'] button:has-text('New chat')",
        "main button:has-text('New chat')",
        "button:has-text('New chat')",
        "a:has-text('New chat')",
    ):
        try:
            candidates = page.locator(selector)
            for index in reversed(range(min(candidates.count(), 6))):
                candidate = candidates.nth(index)
                if not candidate.is_visible() or not candidate.is_enabled():
                    continue
                candidate.click(timeout=3000)
                page.wait_for_timeout(1200)
                return find_chat_composer(page, timeout_ms=timeout_ms) is not None
        except Exception:
            continue
    return False


def refresh_chat(page, timeout_ms: int) -> None:
    try:
        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        # Some anti-bot/interstitial states can fail reload with non-2xx responses.
        # Fall back to a best-effort navigate to the current URL and continue.
        try:
            current_url = page.url
            if current_url:
                page.goto(current_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
    page.wait_for_timeout(1200)
