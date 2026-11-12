"""Regression tests for candidate-slot palettes and contrast qualification."""

from __future__ import annotations

import unittest

from chatgpt_automation.scripts.palette import PALETTES, apply_palette, contrast_ratio


class CandidatePaletteTests(unittest.TestCase):
    def test_applies_slot_palette_and_normalizes_template_tokens(self):
        css = """
:root { --olive: #69745d; --olive-dark: #48543f; --ink: #292c29; --paper: #f7f6f2; }
body { color: var(--ink); background: var(--paper); }
.button { color: #fff; background: var(--olive-dark); border-color: var(--olive); }
"""

        result, report = apply_palette(css, 1)

        self.assertIn(f"--accent: {PALETTES[1]['accent']};", result)
        self.assertIn(f"--accent-dark: {PALETTES[1]['accent-dark']};", result)
        self.assertIn("background: var(--accent-dark)", result)
        self.assertTrue(report["token_values_match"])
        self.assertTrue(report["required_tokens_used"])
        self.assertTrue(report["contrast_passed"])
        self.assertEqual(report["status"], "passed")

    def test_palette_slots_are_distinct_and_meet_text_contrast(self):
        self.assertEqual(len({palette["accent"] for palette in PALETTES.values()}), 3)
        for palette in PALETTES.values():
            self.assertGreaterEqual(contrast_ratio(palette["ink"], palette["paper"]), 4.5)
            self.assertGreaterEqual(contrast_ratio(palette["ink-soft"], palette["paper"]), 4.5)
            self.assertGreaterEqual(contrast_ratio("#ffffff", palette["accent"]), 4.5)
            self.assertGreaterEqual(contrast_ratio("#ffffff", palette["accent-dark"]), 4.5)
            self.assertGreaterEqual(contrast_ratio("#ffffff", palette["accent-warm"]), 4.5)

    def test_missing_token_usage_fails_palette_qualification(self):
        result, report = apply_palette("body { color: #222; background: #fff; }", 2)

        self.assertIn("--accent:", result)
        self.assertTrue(report["token_values_match"])
        self.assertFalse(report["required_tokens_used"])
        self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
