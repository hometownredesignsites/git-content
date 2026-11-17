from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.source_brief import build_compact_source_brief, category_fallback_candidates, format_retry_guidance


class SourceBriefTests(unittest.TestCase):
    def setUp(self):
        self.home = "https://example.com/"
        self.assessment = {
            "sources": [self.home, "https://example.com/services/"],
            "pages_reviewed": [{"url": self.home}, {"url": "https://example.com/services/"}],
            "organization_facts": [
                {"fact": "Family-owned flooring installer", "source_urls": [self.home]},
                {"fact": "Unsupported claim", "source_urls": ["https://other.invalid/"]},
            ],
            "selling_points": [{"fact": "Free estimates", "source_urls": ["https://example.com/services/"]}],
            "contact_form_fields": [
                {"label": "Phone", "required": True, "source_urls": [self.home]},
                {"label": "Project details", "required": False, "source_urls": [self.home]},
            ],
            "faq_answers": [{"question": "Do you install tile?", "answer": "Yes", "source_urls": ["https://example.com/services/"]}],
            "audience_and_goals": {"primary_conversion_path": "Call to request an estimate", "source_urls": [self.home]},
            "source_assets": [
                {"url": "https://cdn.example.com/flooring.jpg", "type": "photo", "page_url": self.home},
                {"url": "https://cdn.example.com/logo.svg", "type": "logo", "page_url": self.home},
            ],
        }

    def test_brief_keeps_cited_facts_and_exact_required_status(self):
        brief = build_compact_source_brief(self.assessment)
        self.assertIn("Family-owned flooring installer", brief)
        self.assertIn("source: https://example.com/", brief)
        self.assertNotIn("Unsupported claim", brief)
        self.assertIn("Phone [required]", brief)
        self.assertIn("Project details [optional]", brief)
        self.assertIn("Q: Do you install tile? A: Yes", brief)

    def test_image_allowlist_excludes_logo_and_keeps_exact_url(self):
        brief = build_compact_source_brief(self.assessment)
        allowlist = brief.split("VERIFIED_SOURCE_IMAGE_URLS:\n", 1)[1]
        self.assertIn("- https://cdn.example.com/flooring.jpg", allowlist)
        self.assertNotIn("logo.svg", allowlist)

    def test_compact_brief_includes_byte_validated_category_fallbacks(self):
        fallbacks = category_fallback_candidates("flooring and tile")
        brief = build_compact_source_brief(self.assessment, fallbacks)
        self.assertIn("VERIFIED_CATEGORY_FALLBACK_IMAGE_URLS:", brief)
        self.assertIn(fallbacks[0]["url"], brief)

    def test_uncited_core_fact_does_not_create_a_generation_brief(self):
        assessment = {"organization_facts": [{"fact": "Do not use", "source_urls": ["https://other.invalid/"]}],
                      "pages_reviewed": [{"url": self.home}]}
        self.assertEqual(build_compact_source_brief(assessment), "")

    def test_retry_guidance_names_measured_contrast_and_layout(self):
        guidance = format_retry_guidance(
            {"checks": {"source_site_hero_photo_used": False}},
            {
                "viewports": {"mobile": {"primary_cta_contrast": {"issues": [
                    {"selector": ".hero a.cta", "contrast_ratio": 2.1, "threshold": 4.5}
                ]}}},
                "template_layout": {"status": "fail", "expected": {"spotlights": 3}, "actual": {"spotlights": 2}},
            },
            ["https://cdn.example.com/flooring.jpg"],
        )
        self.assertIn("https://cdn.example.com/flooring.jpg", guidance)
        self.assertIn("4.5:1", guidance)
        self.assertIn(".hero a.cta", guidance)
        self.assertIn('"spotlights":3', guidance)
        self.assertIn('"spotlights":2', guidance)


if __name__ == "__main__":
    unittest.main()
