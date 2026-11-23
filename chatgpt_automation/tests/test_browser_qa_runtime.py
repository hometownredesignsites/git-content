from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chatgpt_automation.scripts.browser_qa import _browser_launch_options


class FakeChromium:
    def __init__(self, executable_path: str):
        self.executable_path = executable_path


class BrowserQARuntimeTests(unittest.TestCase):
    def test_uses_playwright_managed_chromium_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chrome"
            executable.write_bytes(b"browser")
            options, details = _browser_launch_options(FakeChromium(str(executable)), env={})
        self.assertEqual({"headless": True}, options)
        self.assertEqual("playwright_managed_chromium", details["mode"])

    def test_falls_back_to_system_chromium_when_managed_binary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chromium"
            executable.write_bytes(b"browser")
            with patch("chatgpt_automation.scripts.browser_qa.shutil.which", return_value=str(executable)):
                options, details = _browser_launch_options(FakeChromium(str(Path(directory) / "missing")), env={})
        self.assertEqual(str(executable), options["executable_path"])
        self.assertEqual("system_chromium_fallback", details["mode"])

    def test_configured_chromium_path_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chromium"
            executable.write_bytes(b"browser")
            options, details = _browser_launch_options(
                FakeChromium(str(Path(directory) / "missing")),
                env={"WEBSITE_POC_CHROMIUM_EXECUTABLE": str(executable)},
            )
            self.assertEqual(str(executable), options["executable_path"])
            self.assertEqual("configured_system_chromium", details["mode"])
            with self.assertRaisesRegex(FileNotFoundError, "does not name a file"):
                _browser_launch_options(
                    FakeChromium(str(Path(directory) / "missing")),
                    env={"WEBSITE_POC_CHROMIUM_EXECUTABLE": str(Path(directory) / "bad")},
                )

    def test_no_sandbox_is_explicitly_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "chromium"
            executable.write_bytes(b"browser")
            with patch("chatgpt_automation.scripts.browser_qa.shutil.which", return_value=str(executable)):
                options, details = _browser_launch_options(
                    FakeChromium(str(Path(directory) / "missing")),
                    env={"WEBSITE_POC_CHROMIUM_NO_SANDBOX": "1"},
                )
        self.assertEqual(["--no-sandbox"], options["args"])
        self.assertTrue(details["no_sandbox"])

    def test_missing_managed_and_system_chromium_fails_with_guidance(self) -> None:
        with patch("chatgpt_automation.scripts.browser_qa.shutil.which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "Playwright's managed Chromium is missing"):
                _browser_launch_options(FakeChromium("missing"), env={})


if __name__ == "__main__":
    unittest.main()
