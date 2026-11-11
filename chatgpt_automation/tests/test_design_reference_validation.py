"""Regression coverage for HTML5 UP design-reference assessment validation."""

from __future__ import annotations

import unittest

from chatgpt_automation.scripts.website_chunks import _validate_design_reference_result


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


if __name__ == "__main__":
    unittest.main()
