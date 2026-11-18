from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.repair_candidate_quality import repair


class CandidateRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.candidate = Path(self.temp.name)
        (self.candidate / "files").mkdir()
        (self.candidate / "debug").mkdir()
        (self.candidate / "files" / "index.html").write_text(
            '<main><section id="hero"><h1>Flooring</h1><img src="https://bad.invalid/photo.jpg"></section>'
            '<section class="spotlight"><div class="image"><img src="https://cdn.example.com/good.jpg"></div>'
            '<div class="content">Services</div></section><div class="tiles"><article><img src="https://cdn.example.com/good.jpg"></article></div></main>',
            encoding="utf-8",
        )
        (self.candidate / "files" / "styles.css").write_text(".hero a.cta { color: #aaa; }", encoding="utf-8")
        (self.candidate / "debug" / "website_context.md").write_text(
            "VERIFIED_SOURCE_IMAGE_URLS:\n- https://cdn.example.com/good.jpg\n", encoding="utf-8"
        )
        (self.candidate / "run_notes.json").write_text(
            json.dumps({"source_url": "https://example.com/"}), encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_report(self, checks, browser):
        (self.candidate / "debug" / "checker_report.json").write_text(
            json.dumps({"checks": checks, "blocking_failures": [key for key, value in checks.items() if not value],
                        "image_urls": ["https://bad.invalid/photo.jpg", "https://cdn.example.com/good.jpg"],
                        "hero_image_urls": ["https://bad.invalid/photo.jpg"]}), encoding="utf-8"
        )
        (self.candidate / "debug" / "browser_qa.json").write_text(json.dumps(browser), encoding="utf-8")

    def test_replaces_unapproved_hero_image_with_verified_source_url(self):
        self._write_report({"source_site_hero_photo_used": False}, {})
        with patch("scripts.repair_candidate_quality._image_loads_ok", return_value=True):
            result = repair(self.candidate)
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(result["changed"])
        self.assertIn('src="https://cdn.example.com/good.jpg"', html)
        self.assertNotIn("bad.invalid", html)

    def test_repairs_only_measured_cta_selector(self):
        browser = {"viewports": {"mobile": {"primary_cta_contrast": {"issues": [
            {"selector": ".hero a.cta", "contrast_ratio": 2.2, "threshold": 4.5}
        ]}}}}
        self._write_report({"browser_primary_ctas_readable_desktop_and_mobile": False}, browser)
        result = repair(self.candidate)
        css = (self.candidate / "files" / "styles.css").read_text(encoding="utf-8")
        self.assertEqual(result["cta_selectors"], [".hero a.cta"])
        self.assertIn("background-color:#fff", css)

    def test_uses_category_fallback_when_no_verified_source_photo_exists(self):
        fallback = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1800&q=85"
        (self.candidate / "debug" / "website_context.md").write_text(
            "VERIFIED_CATEGORY_FALLBACK_IMAGE_URLS:\n- " + fallback + "\n", encoding="utf-8"
        )
        self._write_report({"hero_uses_source_or_category_asset": False}, {})
        with patch("scripts.repair_candidate_quality._image_loads_ok", return_value=True):
            result = repair(self.candidate)
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(result["image_replacements"])
        self.assertIn(fallback, html)

    def test_layout_repair_restores_selected_hero_and_spotlight_markers(self):
        browser = {"template_layout": {"profile": "landed", "status": "fail",
            "expected": {"spotlight_count": 3},
            "actual": {"spotlight_media_sides": ["right", "right", "right"], "spotlight_side_alternations": 0}}}
        self._write_report({"browser_template_layout_signature_matches": False}, browser)
        result = repair(self.candidate)
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(result["layout_repairs"])
        self.assertIn('id="banner"', html)
        self.assertIn("style1", html)

    def test_adds_only_verified_captured_form_fields_as_non_submitting_preview(self):
        self._write_report({"requested_form_present": False}, {})
        (self.candidate / "debug" / "source_assessment.json").write_text(json.dumps({
            "pages_reviewed": [{"url": "https://example.com/contact/"}],
            "contact_form_fields": [{
                "name": "email", "type": "email", "label": "Email address",
                "required": True, "source_urls": ["https://example.com/contact/"],
            }],
        }), encoding="utf-8")
        result = repair(self.candidate)
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(result["changed"])
        self.assertEqual(result["verified_form_repair"]["fields_added"], 1)
        self.assertIn('<label for="verified-inquiry-1">Email address</label>', html)
        self.assertIn('type="email" required', html)
        self.assertIn("This form preview does not submit messages.", html)

    def test_does_not_invent_form_when_source_has_no_captured_fields(self):
        self._write_report({"requested_form_present": False}, {})
        (self.candidate / "debug" / "source_assessment.json").write_text(
            json.dumps({"pages_reviewed": [], "contact_form_fields": []}), encoding="utf-8"
        )
        result = repair(self.candidate)
        self.assertFalse(result["changed"])
        self.assertNotIn("<form", (self.candidate / "files" / "index.html").read_text(encoding="utf-8"))

    def test_adds_services_section_only_from_explicitly_typed_verified_facts(self):
        self._write_report({"section_services": False}, {})
        html_path = self.candidate / "files" / "index.html"
        html_path.write_text(html_path.read_text(encoding="utf-8").replace("Services", "Flooring"), encoding="utf-8")
        (self.candidate / "debug" / "source_assessment.json").write_text(json.dumps({
            "pages_reviewed": [{"url": "https://example.com/services/"}],
            "organization_facts": [
                {"kind": "service", "fact": "Hardwood floor installation", "source_urls": ["https://example.com/services/"]},
                {"kind": "location", "fact": "Albany", "source_urls": ["https://example.com/services/"]},
            ],
        }), encoding="utf-8")
        result = repair(self.candidate)
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(result["changed"])
        self.assertIn('id="services"', html)
        self.assertIn("Hardwood floor installation", html)
        self.assertNotIn(">Albany<", html)

    def test_repairs_visibility_only_for_browser_measured_hidden_section(self):
        browser = {"viewports": {"mobile": {"sections": {
            "services": {"visible": False, "style_hidden": True, "selector_hint": "section#services", "hidden_ancestors": ["main#content"]}
        }}}}
        self._write_report({"rendered_sections_visible_desktop_and_mobile": False}, browser)
        result = repair(self.candidate)
        css = (self.candidate / "files" / "styles.css").read_text(encoding="utf-8")
        self.assertEqual(result["section_visibility_selectors"], ["section#services", "main#content"])
        self.assertIn("section#services{display:revert!important", css)
        self.assertIn("main#content{display:revert!important", css)

    def test_only_repairs_the_exact_check_requested(self):
        self._write_report({"requested_form_present": False, "section_services": False}, {})
        (self.candidate / "debug" / "source_assessment.json").write_text(json.dumps({
            "pages_reviewed": [{"url": "https://example.com/contact/"}, {"url": "https://example.com/services/"}],
            "contact_form_fields": [{"name": "email", "type": "email", "label": "Email", "required": True,
                                     "source_urls": ["https://example.com/contact/"]}],
            "organization_facts": [{"kind": "service", "fact": "Hardwood installation",
                                    "source_urls": ["https://example.com/services/"]}],
        }), encoding="utf-8")
        result = repair(self.candidate, "requested_form_present")
        html = (self.candidate / "files" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(result["triggered_failures"], ["requested_form_present"])
        self.assertIn("<form", html)
        self.assertNotIn('id="services"', html)

    def test_first_screen_cta_is_reported_without_unsafe_layout_edit(self):
        self._write_report({"cta_visible_first_screen_desktop_and_mobile": False}, {})
        result = repair(self.candidate, "cta_visible_first_screen_desktop_and_mobile")
        self.assertEqual(result["status"], "no_safe_repair_available")
        self.assertEqual(result["triggered_failures"], ["cta_visible_first_screen_desktop_and_mobile"])
        self.assertFalse(result["changed"])


if __name__ == "__main__":
    unittest.main()
