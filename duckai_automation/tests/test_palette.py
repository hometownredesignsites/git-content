from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.palette import apply_palette


class PaletteTests(unittest.TestCase):
    def test_assigned_palette_is_used_when_model_only_returns_unrelated_css(self):
        css, report = apply_palette("h1 { font-size: 3rem; }", 2)
        self.assertEqual(report["status"], "passed")
        self.assertIn("color:var(--ink)", css)
        self.assertIn("background-color:var(--paper)", css)
        self.assertIn("color:var(--accent)", css)


if __name__ == "__main__":
    unittest.main()
