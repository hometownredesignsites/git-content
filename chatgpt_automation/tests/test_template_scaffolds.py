"""Regression checks for the bundled HTML5 UP source scaffolds."""

from __future__ import annotations

import unittest

from chatgpt_automation.scripts.browser_qa import _enforce_story_full_bleed_hero
from chatgpt_automation.scripts.template_scaffolds import (
    TEMPLATES,
    scaffold_context,
    supported_references,
)


class TemplateScaffoldsTest(unittest.TestCase):
    def test_every_supported_template_builds_a_source_css_excerpt(self):
        for reference in supported_references():
            with self.subTest(template=reference["name"]):
                context = scaffold_context(reference)
                self.assertIn("Source CSS excerpts", context)

    def test_story_uses_selectors_present_in_its_bundled_stylesheet(self):
        story = next(
            reference for reference in supported_references()
            if reference["name"] == "Story"
        )

        context = scaffold_context(story)

        for selector in TEMPLATES["story"]["css_selectors"]:
            self.assertIn(f"{selector} {{", context)

    def test_story_scaffold_requires_full_bleed_hero_photo(self):
        story = next(reference for reference in supported_references() if reference["name"] == "Story")
        context = scaffold_context(story)

        self.assertEqual(TEMPLATES["story"]["signature_id"], "story-fullbleed-divided-panels-gallery")
        self.assertIn("full-bleed flooring photo", context)
        self.assertIn("cover the entire hero edge-to-edge and top-to-bottom on desktop and mobile", context)
        self.assertIn("Do not use a half-width side-by-side hero image or a narrow mobile image rail", context)

    def test_story_signature_fails_if_hero_photo_does_not_cover_both_viewports(self):
        report = {
            "viewports": {
                "desktop": {"hero_media_covers_hero": True},
                "mobile": {"hero_media_covers_hero": False},
            },
            "template_layout": {"status": "pass", "pass": True, "actual": {}, "expected": {}},
        }

        _enforce_story_full_bleed_hero({"profile": "story"}, report)

        self.assertFalse(report["template_layout"]["pass"])
        self.assertEqual(
            report["template_layout"]["actual"]["hero_media_covers_hero_by_viewport"],
            {"desktop": True, "mobile": False},
        )

    def test_full_bleed_template_gate_leaves_other_profiles_unchanged(self):
        report = {"viewports": {}, "template_layout": {"pass": True}}

        _enforce_story_full_bleed_hero({"profile": "forty"}, report)

        self.assertTrue(report["template_layout"]["pass"])


if __name__ == "__main__":
    unittest.main()
