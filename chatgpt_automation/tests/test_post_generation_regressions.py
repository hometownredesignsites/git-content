"""Regression checks for repairs and rendered-layout qualification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from chatgpt_automation.scripts.browser_qa import VIEWPORT_CHECKS_JS
from chatgpt_automation.scripts.repair_contact_form import repair


EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class PostGenerationRegressionTest(unittest.TestCase):
    def _candidate(self, root: Path, html: str) -> Path:
        candidate = root / "candidate"
        (candidate / "files").mkdir(parents=True)
        (candidate / "debug").mkdir()
        (candidate / "files" / "index.html").write_text(html, encoding="utf-8")
        (candidate / "debug" / "source_facts.json").write_text(json.dumps({
            "pages_reviewed": [{
                "url": "https://example.test/contact/",
                "title": "Contact",
                "text": "Email us at hello@example.test",
                "forms": [],
            }],
        }), encoding="utf-8")
        return candidate

    def test_verified_email_is_inserted_into_contact_actions(self):
        with tempfile.TemporaryDirectory(prefix="contact-actions-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="contact" class="contact-section">
                  <div class="contact-panel">
                    <div class="contact-actions">
                      <a class="button" href="tel:+15551234567">Call</a>
                    </div>
                  </div>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-actions")
            email_index = html.index('href="mailto:hello@example.test"')
            group_start = html.rfind('<div class="contact-actions">', 0, email_index)
            group_end = html.index("</div>", email_index)
            self.assertLess(group_start, email_index)
            self.assertLess(email_index, group_end)

    def test_verified_email_fallback_uses_flex_group_inside_contact_panel(self):
        with tempfile.TemporaryDirectory(prefix="contact-panel-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="contact" class="contact-section">
                  <div class="contact-panel"><h2>Contact us</h2></div>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-panel")
            self.assertIn('class="source-contact-channels contact-actions"', html)
            self.assertIn('href="mailto:hello@example.test">Email Us</a>', html)
            self.assertIn('style="display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-top:18px"', html)

    def test_browser_qa_detects_clipped_heading_dark_hero_cta_and_email_alignment(self):
        html = """
            <style>
              html, body { margin: 0; }
              .hero { width: 390px; height: 844px; overflow: hidden;
                background-image: linear-gradient(#222, #555); }
              h1 { position: relative; left: -24px; white-space: nowrap; }
              .button { color: rgb(69, 75, 59); background: transparent; }
            </style>
            <section class="hero"><h1>Clipped heading</h1>
              <a class="button" href="#contact">Request a quote</a>
            </section>
            <section id="contact"><div class="contact-actions">
              <a class="button" href="mailto:hello@example.test">Email Us</a>
            </div></section>
        """
        executable_path = str(EDGE_PATH) if EDGE_PATH.is_file() else None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.set_content(html)
                result = page.evaluate(VIEWPORT_CHECKS_JS)
                self.assertFalse(result["critical_content_clipping"]["pass"])
                self.assertFalse(result["hero_cta_contrast"]["pass"])
                self.assertEqual(result["contact_email_ctas"]["ungrouped_count"], 0)

                page.locator(".contact-actions").evaluate("element => element.classList.remove('contact-actions')")
                result = page.evaluate(VIEWPORT_CHECKS_JS)
                self.assertEqual(result["contact_email_ctas"]["ungrouped_count"], 1)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
