from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
import unittest

from chatgpt_worker.queue import (
    QueueConflict,
    claim,
    complete,
    expire_claim,
    heartbeat,
    reconcile_sources,
    stable_job_id,
)


NOW = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)
SOURCE = {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "batch_id": "33333333-3333-4333-8333-333333333333",
    "provider": "chatgpt-worker",
    "result_slug": "sample-business",
    "row": {"website": "https://example.com", "business": "Sample", "category": "Home Services"},
}


def queued_job() -> dict:
    jobs, _ = reconcile_sources([SOURCE], {}, NOW)
    return jobs[stable_job_id(SOURCE["job_id"])]


def passing_result() -> dict:
    candidates = {}
    for slot, filename in (("forty", "candidate-forty.html"), ("landed", "candidate-landed.html"), ("story", "candidate-story.html")):
        candidates[slot] = {"filename": filename, "bytes": 100, "sha256": "a" * 64, "qa_status": "PASS"}
    return {"run_path": "results/sample-business/run-test", "qa_status": "PASS", "candidates": candidates}


class QueueTests(unittest.TestCase):
    def test_reconciliation_is_idempotent_and_ignores_other_provider(self):
        jobs, stats = reconcile_sources([SOURCE, {**SOURCE, "job_id": "44444444-4444-4444-8444-444444444444", "provider": "chatgpt"}], {}, NOW)
        again, again_stats = reconcile_sources([SOURCE], jobs, NOW)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs, again)
        self.assertEqual(stats, {"created": 1, "ignored": 1, "total": 1})
        self.assertEqual(again_stats["created"], 0)

    def test_only_one_contender_wins_compare_and_swap_claim(self):
        stored = {"job": queued_job(), "revision": 0}
        lock = threading.Lock()
        winners = []
        barrier = threading.Barrier(2)

        def contender(worker):
            snapshot = deepcopy(stored)
            proposed = claim(snapshot["job"], worker, f"token-{worker}", NOW)
            barrier.wait()
            with lock:
                if stored["revision"] != snapshot["revision"]:
                    return
                stored["job"] = proposed
                stored["revision"] += 1
                winners.append(worker)

        threads = [threading.Thread(target=contender, args=(name,)) for name in ("worker-a", "worker-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(winners), 1)
        self.assertEqual(stored["job"]["status"], "claimed")

    def test_heartbeat_extends_lease_and_fences_stale_epoch(self):
        job = claim(queued_job(), "worker-a", "secret", NOW)
        renewed = heartbeat(job, "secret", NOW.replace(minute=30), job["claim_epoch"])
        self.assertEqual(renewed["status"], "generating")
        self.assertEqual(renewed["claim"]["lease_expires_at_utc"], "2026-11-25T18:30:00Z")
        with self.assertRaises(QueueConflict):
            heartbeat(renewed, "secret", NOW, job["claim_epoch"] + 1)

    def test_expired_claim_requeues_same_job_and_preserves_attempt(self):
        job = claim(queued_job(), "worker-a", "first", NOW)
        recovered = expire_claim(job, datetime(2026, 11, 25, 18, 1, tzinfo=timezone.utc))
        self.assertEqual(recovered["job_id"], job["job_id"])
        self.assertEqual(recovered["status"], "queued")
        self.assertIsNone(recovered["claim"])
        self.assertEqual(recovered["attempts"][0]["status"], "lease_expired")
        next_claim = claim(recovered, "worker-b", "second", datetime(2026, 11, 25, 18, 2, tzinfo=timezone.utc))
        self.assertEqual(next_claim["claim_epoch"], 2)
        with self.assertRaises(QueueConflict):
            complete(next_claim, "first", NOW, 1, passing_result())

    def test_completion_requires_all_three_passing_candidates(self):
        job = claim(queued_job(), "worker-a", "secret", NOW)
        incomplete = passing_result()
        del incomplete["candidates"]["story"]
        with self.assertRaises(QueueConflict):
            complete(job, "secret", NOW, 1, incomplete)
        completed = complete(job, "secret", NOW, 1, passing_result())
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["handoff"]["status"], "pending")
        self.assertIsNone(completed["claim"])


if __name__ == "__main__":
    unittest.main()
