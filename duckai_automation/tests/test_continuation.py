from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from duckai_automation.scripts.continuation import (
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

    def test_fresh_batch_at_cap_can_continue_when_under_target(self) -> None:
        self.assertTrue(continuation_is_eligible(2, 10, self.candidates))

    def test_requires_attempt_cap_under_target_and_no_previous_continuation(self) -> None:
        self.assertFalse(continuation_is_eligible(3, 10, self.candidates))
        self.assertFalse(continuation_is_eligible(2, 9, self.candidates))
        self.assertFalse(continuation_is_eligible(2, 20, self.candidates))
        self.assertFalse(continuation_is_eligible(2, 10, self.candidates, "parent-job"))
        self.assertFalse(continuation_is_eligible(-1, 10, self.candidates))

    def test_access_gate_evidence_blocks_continuation(self) -> None:
        failure = self.candidates / "candidate" / "failure.txt"
        failure.parent.mkdir()
        failure.write_text("Guest chat is gated or unavailable", encoding="utf-8")
        self.assertFalse(continuation_is_eligible(1, 10, self.candidates))

    def test_unavailable_or_unreadable_source_assessment_blocks(self) -> None:
        assessment = self.candidates / "candidate" / "source_assessment.json"
        assessment.parent.mkdir()
        assessment.write_text("{not json", encoding="utf-8")
        self.assertFalse(continuation_is_eligible(1, 10, self.candidates))
        assessment.write_text(json.dumps({"access_status": "blocked"}), encoding="utf-8")
        self.assertFalse(continuation_is_eligible(1, 10, self.candidates))

    def test_indices_are_global_and_enforce_ten_attempt_batches(self) -> None:
        first_batch = candidate_indices(0)
        second_batch = candidate_indices(10)
        self.assertEqual(first_batch, list(range(1, 11)))
        self.assertEqual(second_batch, list(range(11, 21)))
        self.assertEqual([first_batch[offset] for offset in range(10)], list(range(1, 11)))
        self.assertEqual([second_batch[offset] for offset in range(10)], list(range(11, 21)))
        with self.assertRaises(ValueError):
            candidate_indices(11)
        with self.assertRaises(ValueError):
            candidate_indices(0, 11)
        with self.assertRaises(ValueError):
            candidate_indices(10, 11)

    def _parent_evidence(self, passes: int = 1) -> tuple[Path, Path]:
        parent = self.root / "results" / "site" / "run-123-1"
        parent_candidates = parent / "candidates"
        parent_candidates.mkdir(parents=True)
        for number in range(1, passes + 1):
            candidate = parent_candidates / f"run-123-site-1-candidate-{number}"
            candidate.mkdir()
            (candidate / "run_notes.json").write_text(
                json.dumps({"automated_success": True}), encoding="utf-8"
            )
        (parent / "status.json").write_text(
            json.dumps({
                "job_id": "parent-job",
                "public_workflow_run": 123,
                "status": "failed",
                "continuation_eligible": True,
                "attempts": 10,
                "successful_candidates": passes,
            }), encoding="utf-8"
        )
        return self.root / "results", parent_candidates

    def test_inherits_only_verified_passing_candidates(self) -> None:
        results, parent_candidates = self._parent_evidence(passes=2)
        failed = parent_candidates / "run-123-site-1-candidate-3"
        failed.mkdir()
        (failed / "run_notes.json").write_text(
            json.dumps({"automated_success": False}), encoding="utf-8"
        )
        destinations = self.root / "duckai-runs"
        copied = inherit_passing_candidates(results, destinations, "parent-job", 123, 2, 456, 1)
        self.assertEqual(len(copied), 2)
        self.assertTrue(all((path / "run_notes.json").is_file() for path in copied))

    def test_rejects_parent_without_authorizing_status_or_matching_pass_count(self) -> None:
        results, _ = self._parent_evidence(passes=1)
        status_path = next(results.glob("*/run-*/status.json"))
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["continuation_eligible"] = False
        status_path.write_text(json.dumps(status), encoding="utf-8")
        with self.assertRaises(ValueError):
            inherit_passing_candidates(results, self.root / "dest", "parent-job", 123, 1, 456, 1)
        status["continuation_eligible"] = True
        status_path.write_text(json.dumps(status), encoding="utf-8")
        with self.assertRaises(ValueError):
            inherit_passing_candidates(results, self.root / "dest", "parent-job", 123, 0, 456, 1)

    def test_status_records_eligibility_and_disables_second_continuation(self) -> None:
        status = write_batch_status(
            self.root / "status.json", "job", 2, 10, 10, 456, self.candidates
        )
        self.assertTrue(status["continuation_eligible"])
        child = write_batch_status(
            self.root / "child-status.json", "child", 2, 20, 10, 789,
            self.candidates, "job", "456"
        )
        self.assertFalse(child["continuation_eligible"])
        self.assertEqual(child["continued_from"], {"job_id": "job", "run_id": "456"})
        with self.assertRaises(ValueError):
            write_batch_status(self.root / "bad.json", "bad", 1, 21, 10, 1, self.candidates)

    def test_persisted_candidate_folders_recover_counts_after_interrupted_step(self) -> None:
        for name, passed in (("run-777-1-site-1-candidate-11", True),
                             ("run-777-1-site-1-candidate-12", False),
                             ("run-777-1-site-1-candidate-inherited-1", True)):
            folder = self.candidates / name
            folder.mkdir()
            (folder / "run_notes.json").write_text(
                json.dumps({"automated_success": passed}), encoding="utf-8"
            )
        self.assertEqual(observed_candidate_counts(self.candidates), (2, 2))
        status = write_batch_status(
            self.root / "recovered-status.json", "job", 0, 0, 0, 777,
            self.candidates, derive_candidate_counts=True, prior_attempts=10
        )
        self.assertEqual(status["successful_candidates"], 2)
        self.assertEqual(status["attempts"], 12)
        self.assertEqual(status["new_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
