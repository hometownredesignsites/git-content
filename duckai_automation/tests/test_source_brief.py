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
            "sources": [self.home, "https://example.com/services/", "https://other.invalid/"],
            "pages_reviewed": [{"url": self.home}, {"url": "https://example.com/services/"}],
            "organization_facts": [
                {"fact": "Family-owned flooring installer", "source_urls": [self.home]},
                {"fact": "Unsupported claim", "source_urls": ["https://other.invalid/"]},
            ],
            "selling_points": [{"fact": "Free estimates", "source_urls": ["https://example.com/services/"]}],
            "contact_form_fields": [
                {"name": "phone", "type": "tel", "label": "Phone", "required": True,
                 "placeholder": "Your phone number", "source_urls": [self.home]},
                {"type": "textarea", "label": "Project details", "required": False,
                 "placeholder": "Describe your project", "source_urls": [self.home]},
                {"type": "select", "label": "Floor type", "required": False,
                 "options": ["wood", "tile"], "source_urls": [self.home]},
            ],
            "navigation_links": [
                {"label": "Services", "url": "https://example.com/services/?utm_source=nav", "source_urls": [self.home]},
                {"label": "Services duplicate", "url": "https://www.example.com/services/", "source_urls": [self.home]},
                {"label": "Contact", "url": "https://example.com/contact/", "source_urls": [self.home]},
                {"label": "Other site", "url": "https://other.invalid/", "source_urls": [self.home]},
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
        self.assertIn('Phone (type=tel; required; placeholder="Your phone number"; name=phone)', brief)
        self.assertIn('Project details (type=textarea; optional; placeholder="Describe your project")', brief)
        self.assertIn('Floor type (type=select; optional; options=["wood", "tile"])', brief)
        self.assertIn("https://example.com/services/ (observed on: https://example.com/)", brief)
        self.assertEqual(brief.count("https://example.com/services/ (observed on:"), 1)
        self.assertNotIn("utm_source", brief)
        self.assertNotIn("other.invalid", brief)
        self.assertIn("Q: Do you install tile? A: Yes", brief)

    def test_separates_explicitly_typed_verified_service_facts(self):
        assessment = dict(self.assessment)
        assessment["organization_facts"] = [
            {"fact": "Hardwood floor installation", "kind": "service", "source_urls": ["https://example.com/services/"]},
            {"fact": "Located in Albany", "kind": "location", "source_urls": [self.home]},
        ]
        brief = build_compact_source_brief(assessment)
        service_block = brief.split("VERIFIED SERVICES", 1)[1]
        self.assertIn("Hardwood floor installation", service_block)
        self.assertNotIn("Located in Albany", service_block)

    def test_image_allowlist_excludes_logo_and_keeps_exact_url(self):
        brief = build_compact_source_brief(self.assessment)
        allowlist = brief.split("VERIFIED_SOURCE_IMAGE_URLS:\n", 1)[1]
        self.assertIn("- https://cdn.example.com/flooring.jpg", allowlist)
        self.assertNotIn("logo.svg", allowlist)

    def test_inventory_image_uses_where_it_appears_as_its_source_citation(self):
        assessment = dict(self.assessment)
        assessment["source_assets"] = [{
            "url": "https://cdn.example.com/source-floor.jpg",
            "type": "photo",
            "where_it_appears": "https://example.com/services/",
        }]
        brief = build_compact_source_brief(assessment)
        self.assertIn("https://cdn.example.com/source-floor.jpg", brief)
        self.assertIn("VERIFIED_SOURCE_IMAGE_URLS:\n- https://cdn.example.com/source-floor.jpg", brief)

    def test_inventory_page_is_not_repeated_as_asset_context(self):
        assessment = dict(self.assessment)
        assessment["source_assets"] = [{
            "url": "https://cdn.example.com/source-floor.jpg",
            "type": "photo",
            "where_it_appears": "https://example.com/services/",
        }]
        brief = build_compact_source_brief(assessment)
        self.assertIn("(found on: https://example.com/services/)", brief)
        self.assertNotIn("(https://example.com/services/)", brief)

    def test_scanned_same_site_page_can_cite_images_without_citing_unreviewed_facts(self):
        assessment = dict(self.assessment)
        assessment["source_assets"] = [{
            "url": "https://cdn.example.com/deep-floor.jpg",
            "type": "photo",
            "where_it_appears": "https://example.com/gallery/",
        }]
        brief = build_compact_source_brief(
            assessment,
            expected_source_url=self.home,
            verified_asset_source_pages=["https://example.com/gallery/", "https://other.invalid/gallery/"],
        )
        self.assertIn("https://cdn.example.com/deep-floor.jpg", brief)
        self.assertIn("(found on: https://example.com/gallery/)", brief)
        self.assertNotIn("gallery", brief.split("IDENTITY / SERVICES / LOCATIONS:", 1)[1].split("SELLING POINTS:", 1)[0])

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

    def test_retry_guidance_targets_missing_services_visibility_and_first_screen_cta(self):
        guidance = format_retry_guidance(
            {"checks": {"section_services": False}},
            {"checks": {
                "rendered_sections_visible_desktop_and_mobile": False,
                "cta_visible_first_screen_desktop_and_mobile": False,
            }, "viewports": {
                "mobile": {"cta_visible_first_screen": False, "sections": {
                    "services": {"visible": False, "selector_hint": "section#services"}
                }}
            }}, [],
        )
        self.assertIn("visible Services section", guidance)
        self.assertIn("section#services", guidance)
        self.assertIn("Place the primary CTA inside the hero", guidance)


if __name__ == "__main__":
    unittest.main()
