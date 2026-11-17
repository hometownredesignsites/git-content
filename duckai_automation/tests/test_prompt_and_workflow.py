from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

AUTOMATION = Path(__file__).resolve().parents[1]
REPO = AUTOMATION.parent
sys.path.insert(0, str(AUTOMATION))
from run_duckai import MAX_INITIAL_PROMPT_CHARS, build_initial_prompt
from scripts.summarize_candidate_failure import summarize


class PromptAndWorkflowTests(unittest.TestCase):
    def test_generation_prompt_keeps_verified_facts_but_stays_bounded(self):
        prompt = build_initial_prompt(
            "Redesign the flooring company website.",
            "Use a warm, clear visual direction. " * 500,
            "https://example.com/",
            {"name": "Landed", "url": "https://html5up.net/landed", "license_url": "https://html5up.net/license", "patterns_to_adapt": ["split image sections"]},
            "Example Floors",
            "Flooring",
            "Denver",
            "SERVICES: installation (source: https://example.com/services/)\nVERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/photo.jpg",
            "Primary CTA contrast measured 2.1:1; required 4.5:1.",
        )
        self.assertLessEqual(len(prompt), MAX_INITIAL_PROMPT_CHARS)
        self.assertIn("installation (source: https://example.com/services/)", prompt)
        self.assertIn("https://example.com/photo.jpg", prompt)
        self.assertIn("4.5:1", prompt)
        self.assertLessEqual(len(" ".join(prompt.split())), MAX_INITIAL_PROMPT_CHARS)

    def test_generation_prompt_fails_closed_above_budget(self):
        with self.assertRaisesRegex(ValueError, "Compact generation prompt"):
            build_initial_prompt("x" * 12000, "brief")

    def test_workflow_checkpoints_each_candidate_on_private_duckai_branch(self):
        workflow = (REPO / ".github" / "workflows" / "duckai-private-queue.yml").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_ATTEMPT_LIMIT:-12', workflow)
        self.assertIn("checkpoint_candidate \"$run_dir\"", workflow)
        self.assertIn('HEAD:refs/heads/duckai', workflow)
        self.assertIn("continuation.py inherit", workflow)
        self.assertIn("continuation.py status", workflow)
        continuation = (AUTOMATION / "scripts" / "continuation.py").read_text(encoding="utf-8")
        self.assertIn("continuation_eligible", continuation)
        self.assertIn("MAX_TOTAL_ATTEMPTS = 24", continuation)
        self.assertNotIn("refs/heads/fallback", workflow)
        self.assertLess(workflow.index("Check out private Duck.ai evidence branch before generation"), workflow.index("Generate candidate sites"))

    def test_failure_summary_uses_non_sensitive_category(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp)
            (candidate / "run_notes.json").write_text('{"failure_category":"access_gate","failure_reason":"secret detail"}', encoding="utf-8")
            self.assertEqual(summarize(candidate), "Duck.ai guest chat was gated or unavailable")


if __name__ == "__main__":
    unittest.main()
