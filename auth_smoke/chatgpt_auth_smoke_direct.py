#!/usr/bin/env python3
"""Verify ChatGPT login using Playwright's direct headed launch under Xvfb.

This comparison runner uses the same authentication flow and masked diagnostics
as chatgpt_auth_smoke.py, but launches a persistent Chromium context directly
instead of starting Chromium separately and attaching over CDP.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from chatgpt_auth_smoke import Diagnostics, authenticate, required_secret, write_result


async def run(result_path: Path) -> int:
    stage = "preflight"
    diagnostics = None
    try:
        email = required_secret("CHATGPT_LOGIN_EMAIL")
        password = required_secret("CHATGPT_LOGIN_PASSWORD")
        totp_secret = required_secret("CHATGPT_TOTP_SECRET")
        diagnostics = Diagnostics(result_path, email)
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("DISPLAY is unset; run this check under xvfb-run.")

        from playwright.async_api import async_playwright

        stage = "browser_start"
        with tempfile.TemporaryDirectory(prefix="chatgpt-auth-direct-") as temporary:
            runtime = Path(temporary)
            profile = runtime / "browser-profile"
            home = runtime / "home"
            for folder in (profile, home / ".config", home / ".cache"):
                folder.mkdir(parents=True, exist_ok=True)

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

            async with async_playwright() as playwright:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile),
                    headless=False,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    env=browser_environment,
                )
                try:
                    page = await context.new_page()
                    page.set_default_timeout(20_000)
                    page.set_default_navigation_timeout(60_000)
                    stage = "chatgpt_login"
                    await authenticate(page, email, password, totp_secret, diagnostics)
                    write_result(
                        result_path,
                        "authenticated",
                        "profile_control_visible",
                        diagnostics=diagnostics,
                    )
                    print("ChatGPT authentication succeeded; signed-in profile control is visible.")
                    return 0
                finally:
                    await context.close()
    except Exception as error:
        reason = str(error)
        for secret_name in (
            "CHATGPT_LOGIN_EMAIL",
            "CHATGPT_LOGIN_PASSWORD",
            "CHATGPT_TOTP_SECRET",
        ):
            secret = os.environ.get(secret_name, "")
            if secret:
                reason = reason.replace(secret, "[redacted]")
        write_result(result_path, "failed", stage, reason, diagnostics=diagnostics)
        print(f"Direct Playwright authentication smoke test failed at {stage}: {reason}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", required=True, type=Path)
    args = parser.parse_args()
    return asyncio.run(run(args.result_file))


if __name__ == "__main__":
    raise SystemExit(main())
