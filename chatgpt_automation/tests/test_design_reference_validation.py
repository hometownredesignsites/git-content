"""Regression coverage for HTML5 UP design-reference assessment validation."""

from __future__ import annotations

import json
import unittest

from chatgpt_automation.scripts.website_chunks import (
    _parse_design_reference_response,
    _validate_design_reference_result,
)


def _reference(slot, name, template, *, full_bleed=True):
    return {
        "slot": slot,
        "name": name,
        "template_url": f"https://html5up.net/{template}",
        "demo_url": f"https://html5up.net/uploads/demos/{template}/",
        "license_url": "https://html5up.net/license",
        "fit_summary": "A verified fit. " + "x" * 600,
        "patterns_to_adapt": ["Fullscreen image banner with readable overlay content."],
        "demo_observations": ["The official demo supports a full-height image banner."],
        "criteria_fit": {
            "full_bleed_hero": full_bleed,
            "responsive_layout": True,
        },
    }


def _assessment(references):
    return {
        "search_status": "completed",
        "design_references": references,
        "reason_if_none": "",
        "sources": [
            url
            for reference in references
            for url in (reference["template_url"], reference["demo_url"], reference["license_url"])
        ],
    }


class DesignReferenceValidationTest(unittest.TestCase):
    def test_accepts_three_distinct_references_and_long_fit_summaries(self):
        assessment = _assessment([
            _reference(1, "Story — Banner Style 5", "story"),
            _reference(2, "Landed", "landed"),
            _reference(3, "Big Picture", "big-picture"),
        ])
        self.assertIs(_validate_design_reference_result(assessment), assessment)

    def test_parser_normalizes_valid_json_schema_drift(self):
        references = [
            _reference(1, "Story", "story"),
            _reference(2, "Landed", "landed"),
            _reference(3, "Big Picture", "big-picture"),
        ]
        references[0]["patterns_to_adapt"] = [
            "  Fullscreen   image hero with readable overlay content and a clear first-screen action " * 3,
            "Modular sections with varied image and text compositions.",
            "Responsive image positioning.",
            "An extra detail beyond the supported three-item limit.",
        ]
        references[0]["demo_observations"] = [
            "The official demo uses a full-height image banner with content overlay. " * 4,
        ]
        assessment = _assessment(references)
        assessment.pop("sources")

        parsed = _parse_design_reference_response(
            "DESIGN REFERENCE ASSESSMENT\n```json\n"
            + json.dumps(assessment)
            + "\n```"
        )
        reference = parsed["design_references"][0]
        self.assertEqual(len(reference["patterns_to_adapt"]), 3)
        self.assertTrue(all(len(item) <= 120 for item in reference["patterns_to_adapt"]))
        self.assertEqual(len(reference["demo_observations"]), 1)
        self.assertLessEqual(len(reference["demo_observations"][0]), 120)
        self.assertIn("fit_summary", reference)
        self.assertEqual(len(parsed["sources"]), 9)

    def test_parser_still_rejects_invalid_core_criteria(self):
        references = [
            _reference(1, "Story", "story", full_bleed=False),
            _reference(2, "Landed", "landed"),
            _reference(3, "Big Picture", "big-picture"),
        ]
        response = "DESIGN REFERENCE ASSESSMENT\n```json\n" + json.dumps(_assessment(references)) + "\n```"
        with self.assertRaisesRegex(ValueError, "fullscreen hero"):
            _parse_design_reference_response(response)


if __name__ == "__main__":
    unittest.main()
