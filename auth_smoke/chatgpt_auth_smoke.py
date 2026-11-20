#!/usr/bin/env python3
"""Verify ChatGPT login in a normal headed Chromium process under Xvfb.

Email-only flow:
1. Enter the account email; ChatGPT emails a one-time verification code.
2. If a verification code is supplied (CLI ``--verification-code`` or env
   ``CHATGPT_VERIFICATION_CODE``), enter it to complete sign-in.
3. If no code is supplied, the run stops cleanly at the code screen with
   status ``waiting_for_code`` so a follow-up ``workflow_dispatch`` run can
   complete authentication with the code.

The smoke test stops after the signed-in profile control appears. It does not
send a prompt, upload a file, or save browser cookies beyond the temporary run.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


CHATGPT_HOME = "https://chatgpt.com/"
CHATGPT_LOGIN = "https://chatgpt.com/auth/login"

# Fallback account email used when CHATGPT_LOGIN_EMAIL is not configured as an
# Actions secret. Set the secret to override this default.
CHATGPT_LOGIN_EMAIL_FALLBACK = "hometownredesign1@yahoo.com"

SELECTORS = (
    'input[placeholder="Code"]',
    'input[placeholder*="code" i]',
    'input[aria-label*="code" i]',
    'input[name="code"]',
    'input[id*="code" i]',
)

TOTP_SELECTORS = (
    'input[placeholder*="6-digit" i]',
    'input[placeholder*="authenticator" i]',
    'input[aria-label*="authenticator" i]',
    'input[aria-label*="6-digit" i]',
    'input[name="totp"]',
    'input[id*="totp" i]',
)


def current_totp(secret: str, timestamp: float | None = None) -> str:
    """Generate a six-digit RFC 6238 TOTP using SHA-1 and a 30-second step."""
    normalized = re.sub(r"\s+", "", secret).upper()
    normalized += "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized, casefold=True)
    counter = int((time.time() if timestamp is None else timestamp) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % 1_000_000).zfill(6)


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required Actions secret is missing: {name}")
    return value


def optional_env(name: str) -> str:
    return os.environ.get(name, "").strip()


async def is_logged_in(page) -> bool:
    for selector in (
        'button[aria-label="Open profile menu"]',
        'button[aria-label*="profile menu" i]',
    ):
        try:
            control = page.locator(selector).last
            if await control.count() and await control.is_visible():
                return True
        except Exception:
            continue
    return False


class Diagnostics:
    def __init__(self, result_path: Path, email: str):
        self.result_path = result_path
        self.email = email
        self.screenshots: list[str] = []
        self.screenshot_errors: list[str] = []

    async def capture(self, page, stage: str) -> None:
        filename = f"{stage}.png"
        destination = self.result_path.parent / "screenshots" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        masks = [
            page.locator("input"),
            page.locator("textarea"),
            page.locator('[contenteditable="true"]'),
            page.locator("nav"),
            page.locator("aside"),
            page.locator('button[aria-label*="profile menu" i]'),
        ]
        if self.email:
            masks.append(page.get_by_text(self.email, exact=False))
        try:
            await page.screenshot(
                path=str(destination),
                full_page=False,
                animations="disabled",
                mask=masks,
                mask_color="#555555",
                timeout=20_000,
            )
            relative_path = destination.relative_to(self.result_path.parent.parent).as_posix()
            self.screenshots.append(relative_path)
            print(f"Captured masked diagnostic screenshot: {relative_path}", flush=True)
        except Exception as error:
            self.screenshot_errors.append(f"{stage}: {type(error).__name__}")


async def click_visible_button(page, labels: tuple[str, ...]) -> bool:
    buttons = page.locator("button")
    for label in labels:
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            try:
                text = " ".join((await button.inner_text(timeout=1500)).lower().split())
                if text == label and await button.is_visible() and await button.is_enabled():
                    await button.click(timeout=10_000)
                    return True
            except Exception:
                continue
    submit = page.locator('button[type="submit"]').last
    try:
        if await submit.count() and await submit.is_visible() and await submit.is_enabled():
            await submit.click(timeout=10_000)
            return True
    except Exception:
        pass
    return False


async def has_cloudflare_challenge(page) -> bool:
    """Return whether the visible page looks like a Cloudflare challenge."""
    markers = (
        "cloudflare",
        "cf-chl-",
        "challenges.cloudflare.com",
        "verify you are human",
        "checking your browser",
    )
    try:
        title = (await page.title()).lower()
        body = (await page.locator("body").inner_text(timeout=3_000)).lower()
        markup = (await page.content()).lower()
        visible_text = f"{title}\n{body}"
        return any(marker in visible_text or marker in markup for marker in markers)
    except Exception:
        return False


async def has_human_verification_challenge(page) -> bool:
    """Detect the visible Cloudflare checkbox challenge without matching generic scripts."""
    try:
        body = (await page.locator("body").inner_text(timeout=3_000)).lower()
        markup = (await page.content()).lower()
        if "verify you are human" in body or "checking your browser" in body:
            return True
        if any(
            marker in markup
            for marker in (
                "challenges.cloudflare.com/turnstile",
                "cf-turnstile",
                "cf-chl-",
            )
        ):
            return True
        return bool(await page.locator('iframe[src*="challenges.cloudflare.com"]').count())
    except Exception:
        return False


async def find_code_field(page, timeout_seconds: int = 30):
    """Locate the visible one-time-code input, waiting for it to appear."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for selector in SELECTORS:
            candidate = page.locator(selector).last
            try:
                if await candidate.count() and await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        await asyncio.sleep(0.5)
    return None


async def find_visible_field(page, selectors: tuple[str, ...], timeout_seconds: int = 30):
    """Locate the first visible field matching any of the selectors."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for selector in selectors:
            candidate = page.locator(selector).last
            try:
                if await candidate.count() and await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        await asyncio.sleep(0.5)
    return None


async def authenticate_email(
    page,
    email: str,
    verification_code: str,
    totp_secret: str,
    diagnostics: Diagnostics,
    *,
    attempt_cloudflare_click: bool = False,
) -> str:
    """Run email-first authentication.

    Returns one of:
      * ``authenticated`` — signed-in profile control visible
      * ``waiting_for_code`` — email submitted, ChatGPT sent a code, no code
        supplied to complete sign-in
    """
    response = await page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=60_000)
    await diagnostics.capture(page, "01-chatgpt-home")
    if response is not None and response.status == 403:
        if attempt_cloudflare_click:
            challenge_markers_found = await has_cloudflare_challenge(page)
            await diagnostics.capture(page, "02-cloudflare-before-coordinate-click")
            print(
                "Homepage returned 403; Cloudflare markers found="
                f"{challenge_markers_found}; clicking viewport coordinate (345, 510), then Ctrl+R.",
                flush=True,
            )
            await page.mouse.click(345, 510)
            await page.keyboard.press("Control+r")
            await page.wait_for_timeout(5_000)
            await diagnostics.capture(page, "03-cloudflare-after-coordinate-click-refresh")
            retry_response = await page.goto(
                CHATGPT_HOME, wait_until="domcontentloaded", timeout=60_000
            )
            await diagnostics.capture(page, "04-chatgpt-home-after-refresh")
            if retry_response is not None and retry_response.status == 403:
                raise RuntimeError(
                    "Cloudflare still denied the home-page request after coordinate click/Ctrl+R; "
                    "stopping before credential entry."
                )
        else:
            raise RuntimeError(
                "ChatGPT denied the home-page request; coordinate clicking is disabled for this "
                "browser path, stopping before credential entry."
            )
    await asyncio.sleep(2)
    if await is_logged_in(page):
        await diagnostics.capture(page, "07-profile-visible")
        return "authenticated"

    await page.goto(CHATGPT_LOGIN, wait_until="domcontentloaded", timeout=60_000)
    email_field = page.locator('input[type="email"]').last
    await email_field.wait_for(state="visible", timeout=30_000)
    await diagnostics.capture(page, "02-login-email-prompt")
    await email_field.fill(email, timeout=10_000)
    await click_visible_button(page, ("continue",))
    await asyncio.sleep(4)
    await diagnostics.capture(page, "03-email-submitted")

    # After entering the email, ChatGPT may show a password screen with an
    # alternate "Log in with a one-time code" button. Click it to reach the
    # code field so we can wait for the emailed code.
    await click_visible_button(page, ("log in with a one-time code",))
    await asyncio.sleep(2)
    await diagnostics.capture(page, "03b-one-time-code-link-clicked")

    # ChatGPT may present a one-time-code screen (emailed to the account) or a
    # TOTP/authenticator screen depending on the account's setup. Handle both.
    code_field = await find_visible_field(page, SELECTORS)
    totp_field = await find_visible_field(page, TOTP_SELECTORS)

    if code_field is None and totp_field is None:
        raise RuntimeError(
            "Neither a verification-code nor a TOTP field appeared after email "
            "submission; stopping without fallback entry."
        )

    if code_field is not None:
        await diagnostics.capture(page, "04-verification-code-prompt")
        if not verification_code:
            return "waiting_for_code"
        await code_field.fill(verification_code, timeout=10_000)
        if not await click_visible_button(page, ("continue", "verify", "submit")):
            raise RuntimeError("Could not submit the verification code form.")
        print("Playwright clicked the verification-code Continue/Verify button.", flush=True)
        await asyncio.sleep(2)
        await diagnostics.capture(page, "05-code-after-continue")

    if totp_field is not None:
        if not totp_secret:
            raise RuntimeError(
                "TOTP prompt appeared but CHATGPT_TOTP_SECRET is not configured."
            )
        await diagnostics.capture(page, "06-totp-prompt")
        seconds_remaining = 30 - (time.time() % 30)
        if seconds_remaining < 8:
            delay = seconds_remaining + 0.2
            print(
                f"TOTP window has {seconds_remaining:.1f}s remaining; waiting for the next window.",
                flush=True,
            )
            await asyncio.sleep(delay)
        totp_code = current_totp(totp_secret)
        await totp_field.fill(totp_code, timeout=10_000)
        if not await click_visible_button(page, ("continue", "verify", "submit")):
            raise RuntimeError("Could not submit the TOTP verification form.")
        print("Playwright clicked the TOTP Continue/Verify button.", flush=True)
        await asyncio.sleep(2)
        await diagnostics.capture(page, "07-totp-after-continue")

    profile_challenge_clicked = False
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if await is_logged_in(page):
            await diagnostics.capture(page, "08-profile-visible")
            return "authenticated"
        if not profile_challenge_clicked and await has_human_verification_challenge(page):
            await diagnostics.capture(page, "08-cloudflare-before-profile-click")
            print(
                "Cloudflare verification appeared during profile wait; clicking viewport "
                "coordinate (345, 510) once.",
                flush=True,
            )
            await page.mouse.click(345, 510)
            profile_challenge_clicked = True
            await page.wait_for_timeout(5_000)
            await diagnostics.capture(page, "09-cloudflare-after-profile-click")
        await asyncio.sleep(1)
    await diagnostics.capture(page, "08-profile-timeout")
    raise RuntimeError("Timed out waiting for ChatGPT's signed-in profile control.")


def write_result(path: Path, status: str, stage: str, reason: str = "", diagnostics: Diagnostics | None = None) -> None:
    result = {
        "status": status,
        "stage": stage,
        "reason": reason,
        "screenshots": diagnostics.screenshots if diagnostics else [],
        "screenshot_errors": diagnostics.screenshot_errors if diagnostics else [],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as summary:
            summary.write("## ChatGPT authentication smoke test\n\n")
            summary.write(f"- Status: **{status}**\n- Stage: `{stage}`\n")
            if diagnostics:
                summary.write(f"- Masked screenshots: {len(diagnostics.screenshots)}\n")
            if reason:
                summary.write(f"- Result: {reason}\n")


async def run(result_path: Path, verification_code: str, totp_secret: str) -> int:
    stage = "preflight"
    try:
        email = os.environ.get("CHATGPT_LOGIN_EMAIL", "").strip() or CHATGPT_LOGIN_EMAIL_FALLBACK
        diagnostics = Diagnostics(result_path, email)
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("DISPLAY is unset; run this check under xvfb-run.")

        from playwright.async_api import async_playwright

        stage = "browser_start"
        with tempfile.TemporaryDirectory(prefix="chatgpt-auth-") as temporary:
            runtime = Path(temporary)
            profile = runtime / "browser-profile"
            home = runtime / "home"
            for folder in (profile, home / ".config", home / ".cache"):
                folder.mkdir(parents=True, exist_ok=True)

            async with async_playwright() as playwright:
                browser_environment = os.environ.copy()
                for secret_name in ("CHATGPT_LOGIN_EMAIL", "CHATGPT_VERIFICATION_CODE", "CHATGPT_TOTP_SECRET"):
                    browser_environment.pop(secret_name, None)
                browser_environment.update(
                    {
                        "HOME": str(home),
                        "XDG_CONFIG_HOME": str(home / ".config"),
                        "XDG_CACHE_HOME": str(home / ".cache"),
                    }
                )
                browser_process = subprocess.Popen(
                    [
                        playwright.chromium.executable_path,
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--no-default-browser-check",
                        f"--user-data-dir={profile}",
                        "--remote-debugging-port=0",
                        "about:blank",
                    ],
                    env=browser_environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                browser = None
                try:
                    active_port_file = profile / "DevToolsActivePort"
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and browser_process.poll() is None:
                        if active_port_file.is_file():
                            break
                        await asyncio.sleep(0.25)
                    if not active_port_file.is_file():
                        raise RuntimeError("Chromium did not open its local debugging endpoint.")
                    port = int(active_port_file.read_text(encoding="utf-8").splitlines()[0])
                    browser = await playwright.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{port}", timeout=20_000
                    )
                    context = browser.contexts[0]
                    page = await context.new_page()
                    page.set_default_timeout(20_000)
                    page.set_default_navigation_timeout(60_000)
                    stage = "chatgpt_login"
                    status = await authenticate_email(
                        page,
                        email,
                        verification_code,
                        totp_secret,
                        diagnostics,
                        attempt_cloudflare_click=True,
                    )
                    if status == "waiting_for_code":
                        reason = (
                            "Email submitted; ChatGPT sent a verification code to the account. "
                            "No code was provided, so the run paused at the code screen. "
                            "Trigger workflow_dispatch with input verification_code to complete sign-in."
                        )
                        write_result(result_path, "waiting_for_code", "waiting_for_email_code", reason, diagnostics=diagnostics)
                        print(
                            "ChatGPT email submitted; waiting for verification code to complete sign-in.",
                            flush=True,
                        )
                        return 0
                    write_result(result_path, "authenticated", "profile_control_visible", diagnostics=diagnostics)
                    print("ChatGPT authentication succeeded; signed-in profile control is visible.")
                    return 0
                finally:
                    if browser is not None:
                        try:
                            await browser.close()
                        except Exception:
                            pass
                    if browser_process.poll() is None:
                        browser_process.terminate()
                        try:
                            browser_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            browser_process.kill()
                            browser_process.wait(timeout=5)
    except Exception as error:
        reason = str(error)
        for secret_name in ("CHATGPT_LOGIN_EMAIL", "CHATGPT_VERIFICATION_CODE", "CHATGPT_TOTP_SECRET"):
            secret = os.environ.get(secret_name, "")
            if secret:
                reason = reason.replace(secret, "[redacted]")
        diagnostics_for_report = locals().get("diagnostics")
        write_result(result_path, "failed", stage, reason, diagnostics=diagnostics_for_report)
        print(f"ChatGPT authentication smoke test failed at {stage}: {reason}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", required=True, type=Path)
    parser.add_argument(
        "--verification-code",
        default="",
        help="One-time verification code emailed by ChatGPT to complete sign-in.",
    )
    args = parser.parse_args()
    code = args.verification_code or optional_env("CHATGPT_VERIFICATION_CODE")
    totp_secret = optional_env("CHATGPT_TOTP_SECRET")
    return asyncio.run(run(args.result_file, code, totp_secret))


if __name__ == "__main__":
    raise SystemExit(main())
