from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_automation.scripts.continuation import (
    access_gate_evidence,
    candidate_indices,
    continuation_is_eligible,
    inherit_passing_candidates,
    observed_candidate_counts,
    write_batch_status,
)


class ContinuationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidates = self.root / "candidates"
        self.candidates.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_global_indices_enforce_ten_attempt_batches_and_twenty_total(self) -> None:
        self.assertEqual(candidate_indices(0), list(range(1, 11)))
        self.assertEqual(candidate_indices(10), list(range(11, 21)))
        for args in ((11,), (0, 11), (10, 11)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                candidate_indices(*args)

    def test_eligibility_requires_failed_first_batch_at_exact_cap(self) -> None:
        self.assertTrue(continuation_is_eligible(2, 10, self.candidates))
        for values in ((3, 10, ""), (1, 9, ""), (1, 20, ""), (-1, 10, ""), (1, 10, "parent")):
            with self.subTest(values=values):
                self.assertFalse(continuation_is_eligible(values[0], values[1], self.candidates, values[2]))

    def test_access_gate_markers_and_classifications_block_retry(self) -> None:
        candidate = self.candidates / "candidate"
        candidate.mkdir()
        (candidate / "failure.txt").write_text("Guest chat is gated or unavailable", encoding="utf-8")
        self.assertIn("guest chat is gated or unavailable", access_gate_evidence(self.candidates))
        (candidate / "failure.txt").unlink()
        (candidate / "runner_metadata.json").write_text(
            json.dumps({"page_state": {"classification": "captcha_required"}}), encoding="utf-8"
        )
        self.assertIn("captcha_required", access_gate_evidence(self.candidates))

    def test_unavailable_source_assessment_blocks_retry(self) -> None:
        candidate = self.candidates / "candidate"
        candidate.mkdir()
        assessment = candidate / "source_assessment.json"
        assessment.write_text("{bad json", encoding="utf-8")
        self.assertFalse(continuation_is_eligible(1, 10, self.candidates))
        assessment.write_text(json.dumps({"access_status": "blocked"}), encoding="utf-8")
        self.assertFalse(continuation_is_eligible(1, 10, self.candidates))

    def _parent_evidence(self, passes: int = 1) -> Path:
        parent = self.root / "results" / "site" / "run-123-1"
        candidates = parent / "candidates"
        candidates.mkdir(parents=True)
        for number in range(1, passes + 1):
            folder = candidates / f"run-123-site-1-candidate-{number}"
            folder.mkdir()
            (folder / "run_notes.json").write_text(json.dumps({"automated_success": True}), encoding="utf-8")
        (parent / "status.json").write_text(json.dumps({
            "job_id": "parent-job", "public_workflow_run": 123, "status": "failed",
            "continuation_eligible": True, "attempts": 10, "successful_candidates": passes,
        }), encoding="utf-8")
        return self.root / "results"

    def test_inherits_only_verified_passing_candidates(self) -> None:
        results = self._parent_evidence(passes=2)
        copied = inherit_passing_candidates(results, self.root / "chatgpt-runs", "parent-job", 123, 2, 456, 1)
        self.assertEqual(len(copied), 2)
        self.assertTrue(all(json.loads((path / "run_notes.json").read_text())["automated_success"] for path in copied))

    def test_inheritance_rejects_unauthorized_or_mismatched_parent(self) -> None:
        results = self._parent_evidence(passes=1)
        status_path = next(results.glob("*/run-*/status.json"))
        status = json.loads(status_path.read_text())
        status["continuation_eligible"] = False
        status_path.write_text(json.dumps(status))
        with self.assertRaises(ValueError):
            inherit_passing_candidates(results, self.root / "dest", "parent-job", 123, 1, 456, 1)

    def test_observed_counts_include_inherited_passes_not_attempts(self) -> None:
        for name, passed in (("run-456-1-site-1-candidate-11", True),
                             ("run-456-1-site-1-candidate-12", False),
                             ("run-456-1-site-1-candidate-inherited-1", True)):
            folder = self.candidates / name
            folder.mkdir()
            (folder / "run_notes.json").write_text(json.dumps({"automated_success": passed}), encoding="utf-8")
        self.assertEqual(observed_candidate_counts(self.candidates), (2, 2))

    def test_status_derives_counts_and_disables_second_continuation(self) -> None:
        for name, passed in (("run-456-1-site-1-candidate-11", True),
                             ("run-456-1-site-1-candidate-inherited-1", True)):
            folder = self.candidates / name
            folder.mkdir()
            (folder / "run_notes.json").write_text(json.dumps({"automated_success": passed}), encoding="utf-8")
        status = write_batch_status(self.root / "status.json", "job", 0, 0, 0, 456, self.candidates,
                                    derive_candidate_counts=True, prior_attempts=10)
        self.assertEqual((status["successful_candidates"], status["attempts"]), (2, 11))
        self.assertFalse(status["continuation_eligible"])


if __name__ == "__main__":
    unittest.main()
