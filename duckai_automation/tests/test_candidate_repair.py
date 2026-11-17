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


if __name__ == "__main__":
    unittest.main()
