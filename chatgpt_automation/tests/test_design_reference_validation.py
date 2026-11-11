"""Regression coverage for HTML5 UP design-reference assessment validation."""

from __future__ import annotations

import json
import unittest

from chatgpt_automation.scripts.website_chunks import (
    _parse_design_reference_response,
    _validate_design_reference_result,
)


class DesignReferenceValidationTest(unittest.TestCase):
    def test_accepts_nonempty_fit_summary_longer_than_500_characters(self):
        assessment = {
            "search_status": "completed",
            "design_reference": {
                "name": "Story — HTML5 UP",
                "template_url": "https://html5up.net/story",
                "demo_url": "https://html5up.net/uploads/demos/story/",
                "license_url": "https://html5up.net/license",
                "fit_summary": "A verified fit. " + "x" * 600,
                "patterns_to_adapt": ["Fullscreen image banner with readable overlay content."],
                "demo_observations": ["The official demo supports a full-height image banner."],
                "criteria_fit": {
                    "full_bleed_hero": True,
                    "responsive_layout": True,
                },
            },
            "reason_if_none": "",
            "sources": [
                "https://html5up.net/story",
                "https://html5up.net/uploads/demos/story/",
                "https://html5up.net/license",
            ],
        }

        self.assertIs(_validate_design_reference_result(assessment), assessment)

    def test_parser_normalizes_valid_json_schema_drift(self):
        assessment = {
            "search_status": "completed",
            "design_reference": {
                "name": "Story",
                "template_url": "https://html5up.net/story",
                "demo_url": "https://html5up.net/uploads/demos/story/",
                "license_url": "https://html5up.net/license",
                "patterns_to_adapt": [
                    "  Fullscreen   image hero with readable overlay content and a clear first-screen action " * 3,
                    "Modular sections with varied image and text compositions.",
                    "Responsive image positioning.",
                    "An extra detail beyond the supported three-item limit.",
                ],
                "demo_observations": [
                    "The official demo uses a full-height image banner with content overlay. " * 4,
                ],
                "criteria_fit": {
                    "full_bleed_hero": True,
                    "responsive_layout": True,
                },
            },
            "reason_if_none": "",
        }

        parsed = _parse_design_reference_response(
            "DESIGN REFERENCE ASSESSMENT\n```json\n"
            + json.dumps(assessment)
            + "\n```"
        )
        reference = parsed["design_reference"]
        self.assertEqual(len(reference["patterns_to_adapt"]), 3)
        self.assertTrue(all(len(item) <= 120 for item in reference["patterns_to_adapt"]))
        self.assertEqual(len(reference["demo_observations"]), 1)
        self.assertLessEqual(len(reference["demo_observations"][0]), 120)
        self.assertIn("fit_summary", reference)
        self.assertEqual(len(parsed["sources"]), 3)

    def test_parser_still_rejects_invalid_core_criteria(self):
        assessment = {
            "search_status": "completed",
            "design_reference": {
                "name": "Story",
                "template_url": "https://html5up.net/story",
                "demo_url": "https://html5up.net/uploads/demos/story/",
                "license_url": "https://html5up.net/license",
                "fit_summary": "A verified fullscreen responsive anchor.",
                "patterns_to_adapt": ["Use a fullscreen image banner."],
                "demo_observations": ["The demo has a full-height banner."],
                "criteria_fit": {
                    "full_bleed_hero": False,
                    "responsive_layout": True,
                },
            },
            "reason_if_none": "",
        }
        response = "DESIGN REFERENCE ASSESSMENT\n```json\n" + json.dumps(assessment) + "\n```"
        with self.assertRaisesRegex(ValueError, "fullscreen hero"):
            _parse_design_reference_response(response)


if __name__ == "__main__":
    unittest.main()
