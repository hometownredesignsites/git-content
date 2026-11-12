"""Regression checks for the bundled HTML5 UP source scaffolds."""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
