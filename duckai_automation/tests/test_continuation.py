from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
from scripts.continuation import (candidate_indices, inherit_passing_candidates, next_template_slot,
                                  passing_candidates, write_batch_status)


class ContinuationTests(unittest.TestCase):
    def test_success_count_requires_a_distinct_verified_template_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            candidates = Path(temp)
            for index, slot, verified in ((1, 1, True), (2, 1, True), (3, 2, True), (4, 3, False)):
                candidate = candidates / f"run-1-1-site-1-candidate-{index}"
                candidate.mkdir()
                (candidate / "run_notes.json").write_text(json.dumps({
                    "counted_as_pass": True,
                    "template_slot": slot,
                    "template_layout_passed": verified,
                }), encoding="utf-8")
            self.assertEqual(len(passing_candidates(candidates)), 2)

    def test_next_slot_prioritizes_templates_without_a_qualifying_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            candidates = Path(temp)
            entries = ((1, True), (1, False), (2, False), (3, False))
            for index, (slot, passed) in enumerate(entries, start=1):
                candidate = candidates / f"run-1-1-site-1-candidate-{index}"
                candidate.mkdir()
                (candidate / "run_notes.json").write_text(json.dumps({
                    "counted_as_pass": passed,
                    "template_slot": slot,
                    "template_layout_passed": passed,
                }), encoding="utf-8")
            self.assertEqual(next_template_slot(candidates), 2)

    def test_candidate_indices_continue_at_13_and_stop_at_24(self):
        self.assertEqual(candidate_indices(0, 12), list(range(1, 13)))
        self.assertEqual(candidate_indices(12, 12), list(range(13, 25)))
        with self.assertRaises(ValueError):
            candidate_indices(12, 13)

    def test_only_full_gate_free_first_batch_is_eligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = root / "candidates"
            candidates.mkdir()
            status = write_batch_status(root / "status.json", "job", candidates, 12, 12, 123)
            self.assertTrue(status["continuation_eligible"])
            (candidates / "run-123-1-site-1-candidate-1").mkdir()
            (candidates / "run-123-1-site-1-candidate-1" / "run_notes.json").write_text(
                json.dumps({"failure_category": "access_gate", "automated_success": False}), encoding="utf-8"
            )
            status = write_batch_status(root / "status.json", "job", candidates, 12, 12, 123)
            self.assertFalse(status["continuation_eligible"])
            self.assertEqual(status["access_gate_evidence"], ["access_gate"])

    def test_inherit_requires_parent_authorization_and_copies_only_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent = root / "results" / "biz" / "run-123-1"
            candidates = parent / "candidates"
            passed = candidates / "run-123-1-site-1-candidate-4"
            passed.mkdir(parents=True)
            (passed / "run_notes.json").write_text('{"automated_success": true}', encoding="utf-8")
            status = {
                "job_id": "parent", "public_workflow_run": 123, "status": "failed",
                "continuation_eligible": True, "attempts": 12, "successful_candidates": 1,
            }
            (parent / "status.json").write_text(json.dumps(status), encoding="utf-8")
            copied = inherit_passing_candidates(root / "results", root / "new-run", "parent", 123, 1, 456, 1)
            self.assertEqual(len(copied), 1)
            self.assertTrue((copied[0] / "run_notes.json").is_file())


if __name__ == "__main__":
    unittest.main()
