from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from chatgpt_worker.git_store import GitJobStore
from chatgpt_worker.scripts.queue_manager import claim_next
from chatgpt_worker.queue import (
    QueueConflict,
    claim,
    complete,
    expire_claim,
    heartbeat,
    mark_handed_off,
    reconcile_sources,
    reserve_handoff,
    stable_job_id,
)
from chatgpt_worker.scripts.handoff_content_post import stage_all
from chatgpt_worker.scripts.publish_result import collect_output


NOW = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)
SOURCE = {
    "job_id": "22222222-2222-4222-8222-222222222222",
    "batch_id": "33333333-3333-4333-8333-333333333333",
    "provider": "chatgpt-worker",
    "result_slug": "sample-business",
    "row": {"website": "https://example.com", "business": "Sample", "category": "Home Services"},
}
INTAKE_SOURCE = {
    **SOURCE,
    "job_id": "55555555-5555-4555-8555-555555555555",
    "batch_id": "77777777-7777-4777-8777-777777777777",
    "result_slug": "new-business",
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
            proposed = claim(snapshot["job"], worker, NOW)
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
        job = claim(queued_job(), "worker-a", NOW)
        renewed = heartbeat(job, "worker-a", NOW.replace(minute=30), job["claim_epoch"])
        self.assertEqual(renewed["status"], "generating")
        self.assertEqual(renewed["claim"]["lease_expires_at_utc"], "2026-11-25T18:30:00Z")
        with self.assertRaises(QueueConflict):
            heartbeat(renewed, "worker-a", NOW, job["claim_epoch"] + 1)

    def test_expired_claim_requeues_same_job_and_preserves_attempt(self):
        job = claim(queued_job(), "worker-a", NOW)
        recovered = expire_claim(job, datetime(2026, 11, 25, 18, 1, tzinfo=timezone.utc))
        self.assertEqual(recovered["job_id"], job["job_id"])
        self.assertEqual(recovered["status"], "queued")
        self.assertIsNone(recovered["claim"])
        self.assertEqual(recovered["attempts"][0]["status"], "lease_expired")
        next_claim = claim(recovered, "worker-b", datetime(2026, 11, 25, 18, 2, tzinfo=timezone.utc))
        self.assertEqual(next_claim["claim_epoch"], 2)
        with self.assertRaises(QueueConflict):
            complete(next_claim, "worker-a", NOW, 1, passing_result())

    def test_completion_requires_all_three_passing_candidates(self):
        job = claim(queued_job(), "worker-a", NOW)
        incomplete = passing_result()
        del incomplete["candidates"]["story"]
        with self.assertRaises(QueueConflict):
            complete(job, "worker-a", NOW, 1, incomplete)
        completed = complete(job, "worker-a", NOW, 1, passing_result())
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["handoff"]["status"], "pending")
        self.assertIsNone(completed["claim"])

    def test_handoff_batch_reservation_and_completion_are_idempotent(self):
        claimed = claim(queued_job(), "worker-a", NOW)
        completed = complete(claimed, "worker-a", NOW, 1, passing_result())
        batch_id = "1795645200000-123456789"
        reserved = reserve_handoff(completed, batch_id, NOW)
        retried = reserve_handoff(reserved, batch_id, NOW.replace(minute=1))
        self.assertEqual(retried["handoff"]["reserved_at_utc"], "2026-11-25T17:00:00Z")
        with self.assertRaises(QueueConflict):
            reserve_handoff(reserved, "1795645200001-987654321", NOW)
        handed = mark_handed_off(reserved, batch_id, NOW.replace(minute=2))
        self.assertEqual(mark_handed_off(handed, batch_id, NOW), handed)
        with self.assertRaises(QueueConflict):
            mark_handed_off(reserved, "1795645200001-987654321", NOW)

    def test_publisher_collects_only_digest_matched_pass_output(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-output-test-") as temp:
            root = Path(temp)
            entries = {}
            for slot, filename in (("forty", "candidate-forty.html"), ("landed", "candidate-landed.html"),
                                   ("story", "candidate-story.html")):
                content = ("<!doctype html><title>" + slot + "</title>").encode()
                (root / filename).write_bytes(content)
                entries[slot] = {"filename": filename, "bytes": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest(), "qa_status": "PASS"}
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "native-qa.json").write_text(json.dumps({
                "native_qa_status": "PASS", "candidates": entries,
            }), encoding="utf-8")
            files, _report, measured = collect_output(root)
            self.assertEqual(set(files), {
                "candidate-forty.html", "candidate-landed.html", "candidate-story.html",
                "evidence/native-qa.json",
            })
            self.assertEqual(measured["candidates"]["story"]["sha256"], entries["story"]["sha256"])
            entries["story"]["sha256"] = "0" * 64
            (evidence / "native-qa.json").write_text(json.dumps({
                "native_qa_status": "PASS", "candidates": entries,
            }), encoding="utf-8")
            with self.assertRaises(QueueConflict):
                collect_output(root)

    def test_publisher_adapts_detailed_candidate_results_without_weakening_qa(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-candidate-results-test-") as temp:
            root = Path(temp)
            candidate_results = []
            for slot, filename in (("forty", "candidate-forty.html"), ("landed", "candidate-landed.html"),
                                   ("story", "candidate-story.html")):
                content = ("<!doctype html><title>" + slot + "</title>").encode()
                (root / filename).write_bytes(content)
                candidate_results.append({
                    "slot_id": slot,
                    "final_path": filename,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "status": "PASS",
                    "static_check_status": "PASS",
                    "static_errors": [],
                    "failures": [],
                    "viewports": [
                        {"name": name, "status": "PASS", "errors": []}
                        for name in ("desktop", "tablet", "mobile")
                    ],
                    "checks": [
                        {"name": name, "status": "PASS"}
                        for name in (
                            "exact_saved_bytes_and_static_requirements",
                            "browser_viewport_and_interaction_matrix",
                            "rendered_template_credits_absent",
                        )
                    ],
                })
            evidence = root / "evidence"
            evidence.mkdir()
            report = {
                "native_qa_status": "PASS",
                "finished_checks": True,
                "candidate_results": candidate_results,
            }
            report_path = evidence / "native-qa.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            files, _report, measured = collect_output(root)
            self.assertEqual(set(measured["candidates"]), {"forty", "landed", "story"})
            self.assertEqual(measured["candidates"]["story"]["sha256"], candidate_results[2]["sha256"])
            self.assertEqual(files["evidence/native-qa.json"], report_path.read_bytes())

            candidate_results[0]["viewports"][1]["status"] = "FAIL"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(QueueConflict):
                collect_output(root)

            candidate_results[0]["viewports"][1]["status"] = "PASS"
            candidate_results[1]["checks"].append({"name": "unexpected_failure", "status": "FAIL"})
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(QueueConflict):
                collect_output(root)


class GitStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chatgpt-worker-git-test-")
        root = Path(self.temp.name)
        self.remote = root / "private.git"
        self.seed = root / "seed"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "chatgpt-worker", str(self.seed)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.seed), "config", "user.name", "Queue Test"], check=True)
        subprocess.run(["git", "-C", str(self.seed), "config", "user.email", "queue-test@example.invalid"], check=True)
        self.job = queued_job()
        job_path = self.seed / "private_automation" / "queue" / "generation" / "jobs" / (self.job["job_id"] + ".json")
        job_path.parent.mkdir(parents=True)
        job_path.write_text(json.dumps(self.job), encoding="utf-8")
        source_path = self.seed / "private_automation" / "queue" / "jobs" / (SOURCE["job_id"] + ".json")
        source_path.parent.mkdir(parents=True)
        source_path.write_text(json.dumps(INTAKE_SOURCE), encoding="utf-8")
        legacy = {**INTAKE_SOURCE, "job_id": "66666666-6666-4666-8666-666666666666", "provider": "chatgpt"}
        (source_path.parent / (legacy["job_id"] + ".json")).write_text(json.dumps(legacy), encoding="utf-8")
        self.artifact_contents = {}
        result_dir = self.seed / "results" / "sample-business" / "run-test"
        result_dir.mkdir(parents=True)
        for filename in ("candidate-forty.html", "candidate-landed.html", "candidate-story.html"):
            content = ("<!doctype html><title>" + filename + "</title>").encode("utf-8")
            (result_dir / filename).write_bytes(content)
            self.artifact_contents[filename] = content
        subprocess.run(["git", "-C", str(self.seed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.seed), "commit", "-m", "seed"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.seed), "remote", "add", "origin", str(self.remote)], check=True)
        subprocess.run(["git", "-C", str(self.seed), "push", "-u", "origin", "chatgpt-worker"], check=True, capture_output=True)
        self.store = GitJobStore(str(self.remote), retries=5)

    def tearDown(self):
        self.temp.cleanup()

    def test_remote_compare_and_swap_allows_only_one_claim(self):
        barrier = threading.Barrier(2)
        winners = []
        errors = []

        def contender(worker):
            first_read = True

            def transition(job):
                nonlocal first_read
                if first_read:
                    first_read = False
                    barrier.wait(timeout=10)
                return claim(job, worker, NOW)
            try:
                winners.append(self.store.update_job(self.job["job_id"], transition)["claim"]["worker_id"])
            except QueueConflict as error:
                errors.append(error)

        threads = [threading.Thread(target=contender, args=(worker,)) for worker in ("worker-a", "worker-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(errors), 1)
        stored = self.store.read_job(self.job["job_id"])
        self.assertEqual(stored["claim"]["worker_id"], winners[0])

    def test_remote_transition_retry_is_idempotent_for_same_claim(self):
        transform = lambda job: claim(job, "worker-a", NOW)
        first = self.store.update_job(self.job["job_id"], transform)
        second = self.store.update_job(self.job["job_id"], transform)
        self.assertEqual(first, second)
        self.assertEqual(len(second["attempts"]), 1)

    def test_remote_intake_reconciliation_is_idempotent_and_ignores_legacy(self):
        first = self.store.reconcile_intake(NOW)
        second = self.store.reconcile_intake(NOW)
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["ignored"], 1)
        self.assertEqual(second["created"], 0)
        jobs = self.store.list_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual({job["provider"] for job in jobs}, {"chatgpt-worker"})

    def test_manual_claim_heartbeat_and_expiry_reclaim_persist_remotely(self):
        payload = claim_next(self.store, "worker-a", NOW)
        self.assertIsNotNone(payload)
        job = payload["job"]
        self.assertNotIn("claim_token", payload)
        worker_id = payload["job"]["claim"]["worker_id"]
        renewed = self.store.update_job(
            job["job_id"], lambda current: heartbeat(current, worker_id, NOW.replace(minute=30), job["claim_epoch"])
        )
        self.assertEqual(renewed["status"], "generating")
        recovered = self.store.update_job(
            job["job_id"], lambda current: expire_claim(current, datetime(2026, 11, 25, 19, 31, tzinfo=timezone.utc))
        )
        self.assertEqual(recovered["status"], "queued")
        second = claim_next(self.store, "worker-b", datetime(2026, 11, 25, 19, 32, tzinfo=timezone.utc))
        self.assertEqual(second["job"]["claim_epoch"], 2)
        self.assertNotIn("claim_token_sha256", second["job"]["claim"])

    def test_completion_verifies_saved_candidate_bytes_before_persisting(self):
        claimed = self.store.update_job(self.job["job_id"], lambda current: claim(current, "worker-a", NOW))
        record = passing_result()
        for slot, candidate in record["candidates"].items():
            content = self.artifact_contents[candidate["filename"]]
            candidate["bytes"] = len(content)
            candidate["sha256"] = hashlib.sha256(content).hexdigest()
        completed = self.store.complete_job(self.job["job_id"], "worker-a", claimed["claim_epoch"], record, NOW)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.store.read_job(self.job["job_id"])["handoff"]["status"], "pending")

    def test_completion_rejects_missing_candidate_digests_without_mutating_job(self):
        claimed = self.store.update_job(self.job["job_id"], lambda current: claim(current, "worker-a", NOW))
        record = passing_result()
        with self.assertRaises(QueueConflict):
            self.store.complete_job(self.job["job_id"], "worker-a", claimed["claim_epoch"], record, NOW)
        self.assertEqual(self.store.read_job(self.job["job_id"])["status"], "claimed")

    def test_publisher_commits_exact_artifacts_before_completing(self):
        publish_now = datetime.now(timezone.utc)
        claimed = self.store.update_job(
            self.job["job_id"], lambda current: claim(current, "worker-a", publish_now)
        )
        run_path = f"results/sample-business/run-{self.job['job_id']}-epoch-1"
        qa_bytes = b'{"native_qa_status":"PASS"}\n'
        output_files = dict(self.artifact_contents)
        output_files["evidence/native-qa.json"] = qa_bytes
        artifact_commit = self.store.publish_artifacts(
            self.job["job_id"], "worker-a", 1, run_path, output_files,
        )
        candidates = {}
        for slot, filename in (("forty", "candidate-forty.html"), ("landed", "candidate-landed.html"),
                               ("story", "candidate-story.html")):
            content = self.artifact_contents[filename]
            candidates[slot] = {"filename": filename, "bytes": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(), "qa_status": "PASS"}
        result = {
            "run_path": run_path,
            "qa_status": "PASS",
            "artifact_commit": artifact_commit,
            "qa_evidence": {"filename": "evidence/native-qa.json", "bytes": len(qa_bytes),
                            "sha256": hashlib.sha256(qa_bytes).hexdigest()},
            "candidates": candidates,
        }
        completed = self.store.complete_job(
            self.job["job_id"], "worker-a", 1, result, datetime.now(timezone.utc)
        )
        self.assertEqual(completed["result"]["artifact_commit"], artifact_commit)
        saved_job, saved_files = self.store.read_completed_artifacts(self.job["job_id"])
        self.assertEqual(saved_job["status"], "completed")
        self.assertEqual(saved_files["forty"], self.artifact_contents["candidate-forty.html"])


class ContentPostHandoffTests(unittest.TestCase):
    def test_three_private_slot_branches_stage_idempotent_snapshots(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-content-post-test-") as temp:
            root = Path(temp)
            remote = root / "content-post.git"
            seed = root / "seed"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.name", "Handoff Test"], check=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.email", "handoff-test@example.invalid"], check=True)
            (seed / "README.md").write_text("private fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(seed), "commit", "-m", "seed"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)

            job = {
                "job_id": "22222222-2222-4222-8222-222222222222",
                "created_at_utc": "2026-11-25T17:00:00Z",
                "result_slug": "sample-business",
                "row": {"business": "Sample Business", "website": "https://example.com"},
                "result": {"artifact_commit": "a" * 40},
            }
            batch_id = "1795645200000-123456789"
            queued_at = "2026-11-25T17:00:00Z"
            artifacts = {
                "forty": b"<!doctype html><title>Forty</title>",
                "landed": b"<!doctype html><title>Landed</title>",
                "story": b"<!doctype html><title>Story</title>",
            }
            stage_all(str(remote), job, artifacts, batch_id, queued_at)
            stage_all(str(remote), job, artifacts, batch_id, queued_at)
            for slot, branch in ((1, "chatgpt-slot1"), (2, "chatgpt-slot2"), (3, "chatgpt-slot3")):
                path = f"sites/example/queue/{batch_id}/index.html"
                saved = subprocess.run(["git", "--git-dir", str(remote), "show", f"refs/heads/{branch}:{path}"],
                                       check=True, capture_output=True).stdout
                self.assertEqual(saved, artifacts[{1: "forty", 2: "landed", 3: "story"}[slot]])
                metadata_path = f"sites/example/queue/{batch_id}/metadata.json"
                metadata = json.loads(subprocess.run(
                    ["git", "--git-dir", str(remote), "show", f"refs/heads/{branch}:{metadata_path}"],
                    check=True, capture_output=True, text=True,
                ).stdout)
                self.assertEqual(metadata["slot"], slot)
                self.assertEqual(metadata["batch_id"], batch_id)
                self.assertEqual(metadata["branch"], branch)


if __name__ == "__main__":
    unittest.main()
