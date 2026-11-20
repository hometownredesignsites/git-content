#!/usr/bin/env python3
"""Verify ChatGPT login in a normal headed Chromium process under Xvfb.

This smoke test stops after the signed-in profile control appears. It does not
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
from urllib.parse import urlsplit


CHATGPT_HOME = "https://chatgpt.com/"
CHATGPT_LOGIN = "https://chatgpt.com/auth/login"
PASSWORD_ACTIONS = {
    "use password",
    "continue with password",
    "sign in with password",
}


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


def is_password_action_text(text: str) -> bool:
    return " ".join(text.lower().split()) in PASSWORD_ACTIONS


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required Actions secret is missing: {name}")
    return value


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


async def choose_password_sign_in(page) -> None:
    controls = page.locator("button, a")
    for index in range(await controls.count()):
        control = controls.nth(index)
        try:
            text = (await control.inner_text(timeout=1500)).strip()
            if is_password_action_text(text) and await control.is_visible():
                await control.click(timeout=10_000)
                return
        except Exception:
            continue


async def visible_password_field(page, timeout_seconds: int = 30):
    field = page.locator('input[type="password"]').last
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if await field.count() and await field.is_visible():
                return field
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("Password field did not appear; login may be gated or the page changed.")


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


async def authenticate(
    page,
    email: str,
    password: str,
    totp_secret: str,
    diagnostics: Diagnostics,
    *,
    attempt_cloudflare_tab_enter: bool = False,
) -> None:
    response = await page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=60_000)
    await diagnostics.capture(page, "01-chatgpt-home")
    if response is not None and response.status == 403:
        if attempt_cloudflare_tab_enter and await has_cloudflare_challenge(page):
            await diagnostics.capture(page, "02-cloudflare-before-tab-enter")
            print("Cloudflare challenge detected; sending one Tab then Enter key sequence.", flush=True)
            await page.keyboard.press("Tab")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5_000)
            await diagnostics.capture(page, "03-cloudflare-after-tab-enter")
            retry_response = await page.goto(
                CHATGPT_HOME, wait_until="domcontentloaded", timeout=60_000
            )
            await diagnostics.capture(page, "04-chatgpt-home-after-tab-enter")
            if retry_response is not None and retry_response.status == 403:
                raise RuntimeError(
                    "Cloudflare still denied the home-page request after one Tab/Enter attempt; "
                    "stopping before credential entry."
                )
        else:
            raise RuntimeError(
                "ChatGPT denied the home-page request; no recognizable Cloudflare challenge "
                "was available for the requested keypress attempt, stopping before credential entry."
            )
    await asyncio.sleep(2)
    if await is_logged_in(page):
        await diagnostics.capture(page, "07-profile-visible")
        return

    await page.goto(CHATGPT_LOGIN, wait_until="domcontentloaded", timeout=60_000)
    email_field = page.locator('input[type="email"]').last
    await email_field.wait_for(state="visible", timeout=30_000)
    await diagnostics.capture(page, "02-login-email-prompt")
    await email_field.fill(email, timeout=10_000)
    await click_visible_button(page, ("continue",))
    await asyncio.sleep(4)
    await diagnostics.capture(page, "03-email-submitted")

    # Only click exact password sign-in options; this avoids the unrelated
    # "Forgot password?" link that appeared in the previous skill version.
    await choose_password_sign_in(page)
    password_field = await visible_password_field(page)
    await diagnostics.capture(page, "04-password-prompt")
    await password_field.fill(password, timeout=10_000)
    if not await click_visible_button(page, ("sign in", "continue")):
        raise RuntimeError("Could not submit the password form.")
    await asyncio.sleep(3)
    await diagnostics.capture(page, "05-password-submitted")

    code_field = None
    for selector in (
        'input[placeholder="Code"]',
        'input[placeholder*="code" i]',
        'input[aria-label*="code" i]',
        'input[name="code"]',
        'input[id*="code" i]',
    ):
        candidate = page.locator(selector).last
        try:
            if await candidate.count() and await candidate.is_visible():
                code_field = candidate
                break
        except Exception:
            continue
    if code_field is None:
        raise RuntimeError("TOTP verification field did not appear; stopping without fallback entry.")

    await diagnostics.capture(page, "06-totp-prompt")
    await code_field.fill(current_totp(totp_secret), timeout=10_000)
    await asyncio.sleep(2)
    if not await click_visible_button(page, ("continue", "verify", "submit")):
        raise RuntimeError("Could not submit the TOTP verification form.")
    await asyncio.sleep(2)
    await diagnostics.capture(page, "07-totp-submitted")

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if await is_logged_in(page):
            await diagnostics.capture(page, "08-profile-visible")
            return
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


async def run(result_path: Path) -> int:
    stage = "preflight"
    try:
        email = required_secret("CHATGPT_LOGIN_EMAIL")
        password = required_secret("CHATGPT_LOGIN_PASSWORD")
        totp_secret = required_secret("CHATGPT_TOTP_SECRET")
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
                for secret_name in (
                    "CHATGPT_LOGIN_EMAIL",
                    "CHATGPT_LOGIN_PASSWORD",
                    "CHATGPT_TOTP_SECRET",
                ):
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
                    await authenticate(
                        page,
                        email,
                        password,
                        totp_secret,
                        diagnostics,
                        attempt_cloudflare_tab_enter=True,
                    )
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
        # Do not serialize page contents, URLs with query strings, or secrets.
        for secret_name in (
            "CHATGPT_LOGIN_EMAIL",
            "CHATGPT_LOGIN_PASSWORD",
            "CHATGPT_TOTP_SECRET",
        ):
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
    args = parser.parse_args()
    return asyncio.run(run(args.result_file))


if __name__ == "__main__":
    raise SystemExit(main())
