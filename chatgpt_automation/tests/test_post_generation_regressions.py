"""Regression checks for repairs and rendered-layout qualification."""

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from chatgpt_automation.scripts.browser_qa import HEADER_NAV_AUDIT_JS, TEMPLATE_LAYOUT_JS, VIEWPORT_CHECKS_JS
from chatgpt_automation.scripts.repair_contact_form import repair
from chatgpt_automation.scripts.repair_candidate_quality import _repair_template_layout
from chatgpt_automation.scripts.repair_local_links import repair as repair_local_links
from chatgpt_automation.scripts.repair_generated_visuals import repair as repair_visuals
from chatgpt_automation.scripts.run_html_assessment_qa import run as run_html_assessment_qa
from chatgpt_automation.scripts.site_quality import _PageInventory, _header_navigation_link_limit
from chatgpt_automation.html_assessment.html_assessment import (
    apply_model_edits,
    remove_contradicted_missing_attribute_claims,
    repository_qa_prompt,
    run_repository_qa,
    validate_full_rebuild,
)


CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


class PostGenerationRegressionTest(unittest.TestCase):
    def test_full_rebuild_preserves_asset_links_and_form_contract(self):
        source = '''<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>
        <a href="/contact/">Contact</a><picture><source srcset="hero.webp 2x"><img src="hero.jpg" srcset="hero-2x.jpg 2x"></picture>
        <form action="/send" method="post"><input type="email" name="email" required><select name="service"><option value="roof">Roof</option></select></form>
        </body></html>'''
        rebuilt = source.replace("<body>", '<body class="new-layout">')
        self.assertEqual(validate_full_rebuild(source, rebuilt), [])

    def test_full_rebuild_rejects_changed_image_urls_and_form_fields(self):
        source = '''<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>
        <a href="/contact/">Contact</a><img src="hero.jpg"><form action="/send" method="post"><input name="email"></form>
        </body></html>'''
        rebuilt = source.replace("hero.jpg", "other.jpg").replace('<input name="email">', "")
        failures = validate_full_rebuild(source, rebuilt)
        self.assertIn("image src/srcset values changed or image sources were added/removed", failures)
        self.assertIn("existing form fields or select options changed", failures)

    def test_full_rebuild_requires_stylesheet_link_and_preserves_anchor_destinations(self):
        source = '''<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body><a href="/one">One</a></body></html>'''
        rebuilt = source.replace('href="styles.css"', 'href="theme.css"').replace('href="/one"', 'href="/two"')
        failures = validate_full_rebuild(source, rebuilt)
        self.assertIn("existing link destinations changed, or links were added/removed", failures)
        self.assertIn("candidate does not link the extracted files/styles.css stylesheet", failures)

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

    def test_target_selection_prefers_preserved_original_and_falls_back_for_legacy_candidate(self):
        target_script = Path(__file__).resolve().parents[1] / "scripts" / "prepare_html_assessment_target.py"
        select_source = runpy.run_path(str(target_script))["select_source_html"]
        with tempfile.TemporaryDirectory(prefix="assessment-target-source-") as temporary:
            candidate = Path(temporary)
            inline_dir = candidate / "files" / "inlined"
            inline_dir.mkdir(parents=True)
            current = inline_dir / "index.html"
            original = inline_dir / "index-old.html"
            current.write_text("<html>revised page</html>", encoding="utf-8")
            self.assertEqual(select_source(candidate), current)

            original.write_text("<html>preserved source</html>", encoding="utf-8")
            self.assertEqual(select_source(candidate), original)

    def test_assessment_export_preserves_source_before_overwriting_inline_html(self):
        assessor_path = Path(__file__).resolve().parents[1] / "html_assessment" / "html_assessment.py"
        preserve_source = runpy.run_path(str(assessor_path))["preserve_original_inline_html"]
        with tempfile.TemporaryDirectory(prefix="assessment-source-backup-") as temporary:
            root = Path(temporary)
            staged_source = root / "source.html"
            inline_dir = root / "candidate" / "files" / "inlined"
            inline_dir.mkdir(parents=True)
            live_inline = inline_dir / "index.html"
            original_html = "<html><body><h1>Original source</h1></body></html>"
            staged_source.write_text(original_html, encoding="utf-8")
            live_inline.write_text(original_html, encoding="utf-8")

            backup = preserve_source(staged_source, inline_dir)
            live_inline.write_text("<html><body><h1>Revised page</h1></body></html>", encoding="utf-8")

            self.assertEqual(backup.name, "index-old.html")
            self.assertEqual(backup.read_text(encoding="utf-8"), original_html)
            self.assertIn("Revised page", live_inline.read_text(encoding="utf-8"))

    def test_repository_qa_approves_assessment_without_human_review(self):
        with tempfile.TemporaryDirectory(prefix="assessment-qa-approval-") as temporary:
            candidate = self._candidate(Path(temporary), "<main><h1>Example</h1></main>")
            (candidate / "run_notes.json").write_text(json.dumps({
                "html_assessment_model_review_passed": False,
            }), encoding="utf-8")
            (candidate / "debug" / "browser_qa.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            browser_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            structural_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps({"automated_success": True}), stderr=""
            )

            with patch("chatgpt_automation.scripts.run_html_assessment_qa.subprocess.run", side_effect=[browser_result, structural_result]):
                notes = run_html_assessment_qa(candidate)

            self.assertTrue(notes["automated_success"])
            self.assertTrue(notes["final_success"])
            self.assertEqual(notes["human_visual_review_status"], "assessment_replaced_review")
            self.assertEqual(notes["image_relevance_review_status"], "assessment_replaced_review")
            self.assertFalse(notes["html_assessment_model_visual_qa_advisory"])

    def test_repository_qa_keeps_candidate_pending_when_pass1_gate_was_not_cleared(self):
        with tempfile.TemporaryDirectory(prefix="assessment-pass1-pending-") as temporary:
            candidate = self._candidate(Path(temporary), "<main><h1>Example</h1></main>")
            (candidate / "run_notes.json").write_text(json.dumps({
                "html_assessment_pass1_gate_passed": False,
            }), encoding="utf-8")
            (candidate / "debug" / "browser_qa.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            browser_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            structural_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps({"automated_success": True}), stderr=""
            )

            with patch("chatgpt_automation.scripts.run_html_assessment_qa.subprocess.run", side_effect=[browser_result, structural_result]):
                notes = run_html_assessment_qa(candidate)

            self.assertTrue(notes["html_assessment_repo_qa_passed"])
            self.assertFalse(notes["automated_success"])
            self.assertEqual(notes["status"], "pending_review")
            self.assertEqual(notes["html_assessment_status"], "pass1_gate_pending")
            self.assertEqual(notes["human_visual_review_status"], "pending")

    def test_assessment_repository_qa_uses_isolated_candidate_and_strips_provider_secrets(self):
        with tempfile.TemporaryDirectory(prefix="assessment-intermediate-qa-") as temporary:
            root = Path(temporary)
            html_path = root / "source.html"
            html_path.write_text('<html><head><style>body{color:#111}</style></head><body><h1>Source</h1></body></html>', encoding="utf-8")
            source_candidate = root / "private-candidate"
            (source_candidate / "debug").mkdir(parents=True)
            (source_candidate / "debug" / "source_facts.json").write_text('{"pages_reviewed":[]}', encoding="utf-8")
            seen = {}

            def fake_run(command, **kwargs):
                seen["env"] = kwargs["env"]
                candidate = Path(command[-1])
                debug = candidate / "debug"
                (debug / "checker_report.json").write_text(json.dumps({
                    "automated_success": False,
                    "blocking_failures": ["browser_primary_ctas_readable_desktop_and_mobile"],
                    "checks": {},
                    "missing_sections": [],
                    "failed_image_urls": [],
                }), encoding="utf-8")
                (debug / "browser_qa.json").write_text(json.dumps({
                    "status": "fail",
                    "checks": {"primary_ctas_readable_desktop_and_mobile": False},
                    "viewports": {"desktop": {"cta": {"visible_first_screen": True}}},
                }), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-private", "CLOUDFLARE_API_TOKEN": "cf-private"}):
                with patch("chatgpt_automation.html_assessment.html_assessment.subprocess.run", side_effect=fake_run):
                    report = run_repository_qa(html_path, "page-1-source", "https://example.test/", root / "run", source_candidate)

            self.assertFalse(report["automated_success"])
            self.assertNotIn("NVIDIA_API_KEY", seen["env"])
            self.assertNotIn("CLOUDFLARE_API_TOKEN", seen["env"])
            snapshot = root / "run" / "audit" / "repository-qa" / "page-1-source"
            self.assertTrue((snapshot / "debug" / "source_facts.json").is_file())
            self.assertEqual((snapshot / "files" / "styles.css").read_text(encoding="utf-8"), "body{color:#111}")
            prompt = repository_qa_prompt(report)
            self.assertIn("browser_primary_ctas_readable_desktop_and_mobile", prompt)

    def test_repository_qa_prompt_includes_viewport_cta_measurements_and_image_failures(self):
        prompt = repository_qa_prompt({
            "available": True,
            "automated_success": False,
            "blocking_failures": ["browser_primary_ctas_readable_desktop_and_mobile"],
            "missing_sections": [],
            "browser_qa_status": "fail",
            "browser_qa_checks": {"primary_ctas_readable_desktop_and_mobile": False},
            "browser_qa": {"viewports": {"desktop": {
                "hero_cta_contrast": {"issues": [{"text": "Request a quote", "contrast_ratio": 2.1}]},
                "primary_cta_contrast": {"issues": [{"selector": "a.hero-cta", "text": "Request a quote", "contrast_ratio": 2.1}]},
            }}},
            "failed_image_urls": ["https://example.test/broken.jpg"],
            "checks": {},
        })
        self.assertIn("contrast_ratio", prompt)
        self.assertIn("a.hero-cta", prompt)
        self.assertIn("broken.jpg", prompt)

    def test_repository_qa_prompt_includes_concrete_repair_context(self):
        prompt = repository_qa_prompt({
            "available": True,
            "automated_success": False,
            "blocking_failures": ["browser_template_layout_signature_matches"],
            "checks": {"styles_css_linked": False, "section_services": True},
            "source_form_fields_missing": ["phone"],
            "source_form_required_fields_missing": ["phone"],
            "browser_qa": {"template_layout": {
                "status": "fail", "signature_id": "story-divided-panels-gallery",
                "profile": "story", "spotlight_side_alternations": 0,
            }},
        })
        self.assertIn('"styles_css_linked"', prompt)
        self.assertIn('"phone"', prompt)
        self.assertIn('"story-divided-panels-gallery"', prompt)
        self.assertIn('"spotlight_side_alternations": 0', prompt)

    def test_source_audit_drops_a_missing_attribute_claim_contradicted_by_its_exact_evidence(self):
        report = {
            "concept": "page-1", "summary": "Menu button exists.",
            "strengths": [],
            "code_findings": [{
                "criterion_id": "A11Y-01", "priority": "low",
                "finding": "The menu toggle lacks a type attribute.",
                "evidence": 'The source contains <button class="menu-toggle" type="button">Menu</button>.',
                "user_impact": "The control may submit a form.",
                "recommendation": "Set type to button.", "confidence": "medium",
            }],
            "visual_findings": [], "content_and_conversion_findings": [],
        }
        result, rejected = remove_contradicted_missing_attribute_claims(
            json.dumps(report), '<button class="menu-toggle" type="button">Menu</button>',
        )
        self.assertEqual(json.loads(result)["code_findings"], [])
        self.assertEqual(rejected[0]["contradiction"]["attributes"], ["type"])

    def test_assessment_can_repair_only_a_source_proven_broken_form_wrapper(self):
        source = '<div action="/contact"><input name="name"><button type="submit">Send</button></div></form>'
        edit = {"edits": [{
            "id": "repair-form", "criterion_id": "CODE-01", "reason": "Restore the missing wrapper.",
            "find": '<div action="/contact">',
            "replace": '<form action="/contact"><div action="/contact">',
        }]}
        with tempfile.TemporaryDirectory(prefix="assessment-form-wrapper-") as temporary:
            rejected_path = Path(temporary) / "rejected.json"
            revised = apply_model_edits(source, json.dumps(edit), rejected_path)
            self.assertIn('<form action="/contact">', revised)
            self.assertEqual(json.loads(rejected_path.read_text(encoding="utf-8")), [])

            invented = {"edits": [{
                "id": "invent-field", "criterion_id": "CODE-01", "reason": "Add another field.",
                "find": '<button type="submit">Send</button>',
                "replace": '<input name="email"><button type="submit">Send</button>',
            }]}
            unchanged = apply_model_edits(source, json.dumps(invented), rejected_path)
            self.assertEqual(unchanged, source)
            self.assertIn("instead of repairing an existing", json.loads(rejected_path.read_text(encoding="utf-8"))[0]["reason"])

    def test_assessment_edit_cannot_change_image_src_or_srcset(self):
        source = '<img src="room.jpg" srcset="room-small.jpg 480w, room-large.jpg 1200w" alt="Room">'
        edit = {"edits": [{
            "id": "replace-image", "criterion_id": "VIS-01", "reason": "Use a more relevant image.",
            "find": source,
            "replace": source.replace("room.jpg", "different.jpg"),
        }]}
        with tempfile.TemporaryDirectory(prefix="assessment-image-guard-") as temporary:
            rejected_path = Path(temporary) / "rejected.json"
            revised = apply_model_edits(source, json.dumps(edit), rejected_path)
            self.assertEqual(revised, source)
            self.assertIn("changed an existing image src/srcset", json.loads(rejected_path.read_text(encoding="utf-8"))[0]["reason"])

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
            self.assertIn("display:flex;flex-wrap:wrap;align-items:center;justify-content:center", html)

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

            self.assertEqual(result["contact_channels"]["status"], "repaired")
            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-section-full-row")
            self.assertNotIn("hello@example.test", [item["value"] for item in result["contact_channels"].get("missing", [])])
            self.assertIn('href="mailto:hello@example.test"', html)

    def test_verified_email_gets_a_centered_full_row_outside_contact_details(self):
        with tempfile.TemporaryDirectory(prefix="contact-full-row-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="five" class="wrapper style2 special fade">
                  <div class="contact-layout"><div class="contact-details">
                    <div class="contact-detail"><strong>Phone</strong><a href="tel:+15551234567">Call</a></div>
                  </div></div>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-section-full-row")
            self.assertIn('data-source-contact-region="true"', html)
            self.assertIn("justify-content:center", html)
            self.assertIn("grid-column:1/-1", html)
            self.assertGreater(html.index('href="mailto:hello@example.test"'), html.index("</div></div>"))

    def test_existing_contact_email_marks_generic_contact_section_for_styling(self):
        with tempfile.TemporaryDirectory(prefix="contact-region-marker-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <section id="five" class="wrapper style2"><h2>Contact</h2>
                  <a class="button secondary" href="mailto:hello@example.test">Email Us</a>
                </section>
            """)

            result = repair(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["contact_channels"]["status"], "repaired")
            self.assertEqual(result["contact_channels"]["inserted_into"], "contact-section-marker")
            self.assertIn('id="five" class="wrapper style2" data-source-contact-region="true"', html)

    def test_contact_call_and_email_buttons_move_to_one_centered_row(self):
        html = """
            <section id="contact" data-source-contact-region="true">
              <div class="contact-copy">
                <h2>Let's talk about your remodel.</h2>
                <a class="button light" href="tel:+15551234567">Call Now: (555) 123-4567</a>
                <div class="contact-details"><a href="tel:+15551234567">(555) 123-4567</a></div>
                <div class="source-contact-channels contact-actions" style="display:flex;justify-content:center">
                  <a class="button" href="mailto:hello@example.test">Email Us</a>
                </div>
              </div>
            </section>
        """
        with tempfile.TemporaryDirectory(prefix="aligned-contact-actions-") as temporary:
            candidate = self._candidate(Path(temporary), html)

            result = repair(candidate)
            repaired = (candidate / "files" / "index.html").read_text(encoding="utf-8")
            executable_path = str(CHROME_PATH) if CHROME_PATH.is_file() else None
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
                try:
                    page = browser.new_page(viewport={"width": 390, "height": 844})
                    page.set_content(repaired)
                    visual = page.evaluate(VIEWPORT_CHECKS_JS)
                    row = page.locator(".source-contact-channel-actions")

                    self.assertEqual(result["contact_cta_alignment"]["placement"], "shared_centered_row")
                    self.assertEqual(row.locator("a").count(), 2)
                    self.assertTrue(visual["contact_channel_ctas"]["aligned"])
                    self.assertEqual(visual["contact_email_ctas"]["ungrouped_count"], 0)
                    self.assertEqual(visual["contact_email_ctas"]["misplaced_count"], 0)
                    self.assertIn('href="tel:+15551234567">(555) 123-4567</a>', repaired)
                finally:
                    browser.close()

    def test_contact_us_route_maps_to_semantic_section_with_generic_id(self):
        with tempfile.TemporaryDirectory(prefix="contact-route-repair-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <a class="button" href="/contact-us/#quote">Request a quote</a>
                <section id="five" class="wrapper contact-band"><h2>Contact us</h2><a href="mailto:hello@example.test">Email</a></section>
            """)

            result = repair_local_links(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")

            self.assertEqual(result["status"], "repaired")
            self.assertIn('href="#five"', html)
            self.assertEqual(result["unresolved_local_routes"], [])

    def test_candidate_2_and_8_visual_repairs_restore_readable_colors(self):
        html = """
            <section id="banner" class="hero" style="background-image:url('https://example.test/hero.jpg')"><h1>Westwood Remodel</h1><a class="button secondary" href="#contact">Request a quote</a></section>
            <section id="contact" style="background:#e9e3d8">
              <div class="contact-actions">
                <a class="button secondary" href="#contact">Request a Free Quote</a>
              </div>
            </section>
            <section id="one" class="tiles">
              <article style="background-image:linear-gradient(#222,#444)">
                <header><span class="eyebrow">01 / Kitchen</span></header>
              </article>
            </section>
        """
        source_css = """
            .button.secondary { color: #fff; background: transparent; }
            #banner .button.secondary { color: #24372d; }
            .tiles article .eyebrow { color: #51583d; }
        """
        with tempfile.TemporaryDirectory(prefix="generated-visual-repair-") as temporary:
            candidate = self._candidate(Path(temporary), html)
            stylesheet = candidate / "files" / "styles.css"
            stylesheet.write_text(source_css, encoding="utf-8")
            executable_path = str(CHROME_PATH) if CHROME_PATH.is_file() else None
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.set_content(f"<style>{source_css}</style>{html}")
                    before = page.evaluate(VIEWPORT_CHECKS_JS)
                    self.assertFalse(before["contact_cta_contrast"]["pass"])
                    self.assertFalse(before["hero_cta_contrast"]["pass"])
                    self.assertFalse(before["image_card_labels"]["pass"])

                    result = repair_visuals(candidate)
                    repaired_css = stylesheet.read_text(encoding="utf-8")
                    self.assertIn("background-color: var(--accent-dark, #24372d)", repaired_css)
                    page.set_content(f"<style>{repaired_css}</style>{html}")
                    after = page.evaluate(VIEWPORT_CHECKS_JS)

                    self.assertEqual(result["status"], "repaired")
                    self.assertTrue(after["contact_cta_contrast"]["pass"])
                    self.assertTrue(after["hero_cta_contrast"]["pass"])
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
        executable_path = str(CHROME_PATH) if CHROME_PATH.is_file() else None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
            try:
                page = browser.new_page(viewport={"width": 390, "height": 844})
                page.set_content(html)
                result = page.evaluate(VIEWPORT_CHECKS_JS)
                self.assertFalse(result["critical_content_clipping"]["pass"])
                self.assertFalse(result["hero_cta_contrast"]["pass"])
                self.assertFalse(result["primary_cta_contrast"]["pass"])
                self.assertEqual(result["hero_cta_contrast"]["issues"][0]["reason"], "rendered background could not be measured reliably")
                self.assertEqual(result["contact_email_ctas"]["ungrouped_count"], 0)
                self.assertEqual(result["contact_email_ctas"]["misplaced_count"], 1)

                page.locator(".contact-actions").evaluate("element => element.classList.remove('contact-actions')")
                result = page.evaluate(VIEWPORT_CHECKS_JS)
                self.assertEqual(result["contact_email_ctas"]["ungrouped_count"], 1)
            finally:
                browser.close()

    def test_landed_layout_repair_alternates_first_three_split_spotlights(self):
        with tempfile.TemporaryDirectory(prefix="landed-layout-repair-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <main>
                  <section id="one" class="spotlight style1 bottom"><div class="content">One</div><div class="image"><img src="one.jpg"></div></section>
                  <section id="two" class="spotlight style2 right"><div class="content">Two</div><div class="image"><img src="two.jpg"></div></section>
                  <section id="three" class="spotlight style3 right"><div class="content">Three</div><div class="image"><img src="three.jpg"></div></section>
                </main>
            """)
            (candidate / "files" / "styles.css").write_text(".spotlight {display:flex}.spotlight.left .content{order:2}.spotlight.right .content{order:1}", encoding="utf-8")
            (candidate / "debug" / "design_reference.json").write_text(json.dumps({
                "design_reference": {"name": "Landed", "template_url": "https://html5up.net/landed"},
            }), encoding="utf-8")

            result = repair_visuals(candidate)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")
            parser = __import__("chatgpt_automation.scripts.repair_generated_visuals", fromlist=["_TagOffsets"])._TagOffsets(html)
            parser.feed(html)
            classes = [re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", raw, re.I).group(2).split() for _, _, raw in parser.spotlights[:3]]

            self.assertIn("alternating left/right Landed spotlight layout", result["repairs"])
            self.assertEqual(["left" if "left" in value else "right" for value in classes], ["left", "right", "left"])
            self.assertTrue(all("top" not in value and "bottom" not in value for value in classes))

    def test_bounded_landed_repair_corrects_measured_media_positions(self):
        with tempfile.TemporaryDirectory(prefix="bounded-landed-layout-repair-") as temporary:
            candidate = self._candidate(Path(temporary), """
                <main>
                  <section id="banner"><h1>Flooring</h1></section>
                  <section class="spotlight style1 right"><div class="content">One</div><div class="image"></div></section>
                  <section class="spotlight style2 right"><div class="content">Two</div><div class="image"></div></section>
                  <section class="spotlight style3 left"><div class="content">Three</div><div class="image"></div></section>
                </main>
            """)
            stylesheet = candidate / "files" / "styles.css"
            stylesheet.write_text("""
                main { width: 1200px; }
                .spotlight { display: flex; flex-direction: row; }
                .spotlight > .content, .spotlight > .image { flex: 0 0 50%; min-height: 100px; }
                .spotlight.style1 > .content, .spotlight.style2 > .content { order: 1; }
                .spotlight.style1 > .image, .spotlight.style2 > .image { order: 2; }
                .spotlight.style3 > .image { order: 1; }
                .spotlight.style3 > .content { order: 2; }
            """, encoding="utf-8")
            layout = {
                "profile": "landed",
                "slug": "landed",
                "signature_id": "landed-alternating-spotlights",
                "spotlight_count": 3,
                "spotlight_media_sides": ["right", "right", "left"],
                "spotlight_side_alternations": 1,
            }

            repairs = _repair_template_layout(candidate, layout)
            html = (candidate / "files" / "index.html").read_text(encoding="utf-8")
            css = stylesheet.read_text(encoding="utf-8")

            self.assertTrue(any("from right/right/left to left/right/left" in repair for repair in repairs))
            self.assertIn("QA repair pass: measured Landed media order", css)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=str(CHROME_PATH) if CHROME_PATH.is_file() else None,
                )
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.set_content(f"<style>{css}</style>{html}")
                    result = page.evaluate(TEMPLATE_LAYOUT_JS, {
                        "profile": "landed",
                        "slug": "landed",
                        "signature_id": "landed-alternating-spotlights",
                    })
                    self.assertEqual(result["spotlight_media_sides"], ["left", "right", "left"])
                    self.assertTrue(result["pass"])
                finally:
                    browser.close()

    def test_mobile_nav_repair_hides_separate_menu_until_it_is_open(self):
        with tempfile.TemporaryDirectory(prefix="mobile-nav-repair-") as temporary:
            html = """
                <header id="header">
                  <nav class="primary-nav" id="desktop-menu"><a href="#one">One</a></nav>
                  <button class="menu-toggle" aria-label="Open menu" aria-controls="mobile-menu" aria-expanded="false">
                    <span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span>
                  </button>
                  <nav class="mobile-nav" id="mobile-menu" aria-label="Mobile menu">
                    <a href="#one">One</a><a href="#two">Two</a><a href="#three">Three</a>
                  </nav>
                </header>
                <script>document.querySelector('.menu-toggle').addEventListener('click', () => {
                  const nav = document.getElementById('mobile-menu');
                  nav.classList.toggle('is-open');
                });</script>
            """
            candidate = self._candidate(Path(temporary), html)
            css = """
                #header nav { display: flex; }
                @media (max-width: 760px) {
                  #header nav.primary-nav { display: none; }
                  .mobile-nav { position: absolute; }
                  .mobile-nav.is-open { display: flex; }
                  .menu-toggle { display: block; }
                }
            """
            stylesheet = candidate / "files" / "styles.css"
            stylesheet.write_text(css, encoding="utf-8")

            result = repair_visuals(candidate)
            repaired_css = stylesheet.read_text(encoding="utf-8")

            self.assertIn("hide the controlled mobile navigation until opened", result["repairs"])
            self.assertIn("header nav.mobile-nav { display: none !important; }", repaired_css)
            self.assertIn("header nav.mobile-nav.is-open { display: flex !important; }", repaired_css)
            self.assertEqual((candidate / "files" / "index.html").read_text(encoding="utf-8"), html)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=str(CHROME_PATH) if CHROME_PATH.is_file() else None,
                )
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 900})
                    page.set_content(f"<style>{repaired_css}</style>{html}")
                    desktop = page.evaluate(VIEWPORT_CHECKS_JS)
                    self.assertEqual(desktop["header_navigation"]["visible_nav_count"], 1)
                    self.assertTrue(desktop["header_navigation"]["controlled_menu_hidden"])

                    page.set_viewport_size({"width": 390, "height": 844})
                    mobile_before = page.evaluate(HEADER_NAV_AUDIT_JS)
                    self.assertFalse(mobile_before["controlled_nav_visible"])
                    page.locator(".menu-toggle").click()
                    mobile_open = page.evaluate(HEADER_NAV_AUDIT_JS)
                    self.assertEqual(mobile_open["visible_nav_count"], 1)
                    self.assertTrue(mobile_open["links_within_limit"])
                finally:
                    browser.close()

    def test_header_navigation_link_limit_counts_ctas_and_separate_menus(self):
        inventory = _PageInventory()
        inventory.feed("""
            <header><nav aria-label="Primary">
              <a href="#1">One</a><a href="#2">Two</a><a href="#3">Three</a>
              <a href="#4">Four</a><a class="button" href="#5">Call</a>
            </nav><nav class="mobile-nav" aria-label="Mobile">
              <a href="#1">One</a><a href="#2">Two</a><a href="#3">Three</a>
              <a href="#4">Four</a><a href="#5">Call</a><a href="#6">Quote</a>
            </nav></header>
        """)
        inventory.close()

        self.assertEqual([nav["links"] for nav in inventory.header_navs], [5, 6])
        self.assertFalse(_header_navigation_link_limit(inventory))


if __name__ == "__main__":
    unittest.main()
