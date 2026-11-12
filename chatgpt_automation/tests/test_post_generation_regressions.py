"""Regression checks for repairs and rendered-layout qualification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from chatgpt_automation.scripts.browser_qa import VIEWPORT_CHECKS_JS
from chatgpt_automation.scripts.repair_contact_form import repair
from chatgpt_automation.scripts.repair_generated_visuals import repair as repair_visuals


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

    def test_verified_email_fallback_stays_outside_contact_detail_grid(self):
        with tempfile.TemporaryDirectory(prefix="contact-detail-grid-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="five" class="wrapper style2 special fade">
                  <div class="contact-layout">
                    <div class="contact-copy">
                      <h2>Let's talk about your project.</h2>
                      <div class="contact-details">
                        <div class="contact-detail"><strong>Phone</strong><a href="tel:+15551234567">(555) 123-4567</a></div>
                        <div class="contact-detail"><strong>Location</strong><span>Denver County</span></div>
                      </div>
                    </div>
                  </div>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")
            email_index = html.index('href="mailto:hello@example.test"')
            details_end = html.index("</div>", html.index('<div class="contact-details">'))
            detail_start = html.rfind('<div class="contact-detail">', 0, email_index)
            detail_end = html.index("</div>", detail_start)

            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-copy")
            self.assertGreater(email_index, details_end)
            self.assertFalse(detail_start < email_index < detail_end)

    def test_email_repair_declines_unsafe_contact_detail_fallback(self):
        with tempfile.TemporaryDirectory(prefix="unsafe-contact-grid-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="contact">
                  <div class="contact-details">
                    <div class="contact-detail"><strong>Location</strong><span>Denver County</span></div>
                  </div>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["contact_channels"]["status"], "needs_manual_repair")
            self.assertIn("hello@example.test", [item["value"] for item in result["contact_channels"]["missing"]])
            self.assertNotIn('href="mailto:hello@example.test"', html)

    def test_candidate_2_and_8_visual_repairs_restore_readable_colors(self):
        html = """
            <section id="contact" style="background:#e9e3d8">
              <div class="contact-actions">
                <a class="button alt" href="#contact">Request a Free Quote</a>
              </div>
            </section>
            <section id="one" class="tiles">
              <article style="background-image:linear-gradient(#222,#444)">
                <header><span class="eyebrow">01 / Kitchen</span></header>
              </article>
            </section>
        """
        source_css = """
            .button.alt { color: #fff; background: transparent; }
            .tiles article .eyebrow { color: #51583d; }
        """
        with tempfile.TemporaryDirectory(prefix="generated-visual-repair-") as temporary:
            candidate = self._candidate(Path(temporary), html)
            stylesheet = candidate / "files" / "styles.css"
            stylesheet.write_text(source_css, encoding="utf-8")
            executable_path = str(EDGE_PATH) if EDGE_PATH.is_file() else None
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.set_content(f"<style>{source_css}</style>{html}")
                    before = page.evaluate(VIEWPORT_CHECKS_JS)
                    self.assertFalse(before["contact_cta_contrast"]["pass"])
                    self.assertFalse(before["image_card_labels"]["pass"])

                    result = repair_visuals(candidate)
                    repaired_css = stylesheet.read_text(encoding="utf-8")
                    page.set_content(f"<style>{repaired_css}</style>{html}")
                    after = page.evaluate(VIEWPORT_CHECKS_JS)

                    self.assertEqual(result["status"], "repaired")
                    self.assertTrue(after["contact_cta_contrast"]["pass"])
                    self.assertTrue(after["image_card_labels"]["pass"])
                finally:
                    browser.close()

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
            <section id="contact"><div class="contact-detail"><div class="contact-actions">
              <a class="button" href="mailto:hello@example.test">Email Us</a>
            </div></div></section>
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
                self.assertEqual(result["contact_email_ctas"]["misplaced_count"], 1)

                page.locator(".contact-actions").evaluate("element => element.classList.remove('contact-actions')")
                result = page.evaluate(VIEWPORT_CHECKS_JS)
                self.assertEqual(result["contact_email_ctas"]["ungrouped_count"], 1)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
