from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from chatgpt_worker.high_sites import load_existing_hosts, select_high_sites
from chatgpt_worker.queue import reconcile_sources
from chatgpt_worker.scripts.poll_high_sites import run_poller


HEADERS = [
    "final_outcome", "assessment_state", "confidence_level", "PreviewURL",
    "Preview_URLs_json", "website_url", "business_name", "category", "location", "score",
]


def candidate(website: str, business: str, **updates: str) -> dict[str, str]:
    row = {
        "final_outcome": "high",
        "assessment_state": "complete",
        "confidence_level": "3",
        "PreviewURL": "",
        "Preview_URLs_json": "[]",
        "website_url": website,
        "business_name": business,
        "category": "Preschool",
        "location": "Example, ST",
        "score": "90",
    }
    row.update(updates)
    return row


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


class HighSiteSelectionTests(unittest.TestCase):
    def test_reuses_eligibility_rules_and_sorts_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            csv_path = Path(temp) / "candidates.csv"
            write_candidates(csv_path, [
                candidate("https://www.zeta.test/", "Zeta", score="95"),
                candidate("https://alpha.test", "Alpha", score="95"),
                candidate("https://excluded.test", "Gino’s Shoes & Repair"),
                candidate("https://preview.test", "Preview", PreviewURL="https://preview.test"),
                candidate("https://low-confidence.test", "Low", confidence_level="2"),
                candidate("https://medium.test", "Medium", final_outcome="medium"),
            ])
            selected = select_high_sites(csv_path, set(), 3)
        self.assertEqual([item["host"] for item in selected], ["alpha.test", "zeta.test", "preview.test"])
        self.assertEqual(selected[0]["row"]["location"], "Example, ST")

    def test_only_worker_queue_records_block_new_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            queue = Path(temp) / "jobs"
            queue.mkdir()
            (queue / "legacy.json").write_text(json.dumps({
                "provider": "chatgpt", "row": {"website": "https://www.Already.test/path"},
            }), encoding="utf-8")
            (queue / "worker.json").write_text(json.dumps({
                "provider": "chatgpt-worker", "row": {"website": "https://worker-existing.test"},
            }), encoding="utf-8")
            self.assertEqual(load_existing_hosts([queue]), {"worker-existing.test"})
            csv_path = Path(temp) / "candidates.csv"
            write_candidates(csv_path, [
                candidate("https://already.test", "Legacy record"),
                candidate("https://worker-existing.test", "Worker record"),
            ])
            selected = select_high_sites(csv_path, load_existing_hosts([queue]), 2)
            self.assertEqual([item["host"] for item in selected], ["already.test"])

    def test_private_write_is_idempotent_and_reconcilable_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bare = root / "private.git"
            checkout = root / "private-worker"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(bare), str(checkout)], check=True, capture_output=True)
            git(checkout, "checkout", "-b", "chatgpt-worker")
            git(checkout, "config", "user.name", "Poller test")
            git(checkout, "config", "user.email", "poller-test@example.invalid")
            (checkout / "README.md").write_text("private fixture\n", encoding="utf-8")
            git(checkout, "add", "README.md")
            git(checkout, "commit", "-m", "fixture")
            git(checkout, "push", "-u", "origin", "chatgpt-worker")

            csv_path = root / "candidates.csv"
            write_candidates(csv_path, [candidate("https://www.one.test/", "One")])
            batch_id = str(uuid4())
            first = run_poller(csv_path, checkout, 1, batch_id=batch_id)
            self.assertEqual(first["status"], "queued")
            self.assertEqual(first["queued"], 1)

            source_paths = list((checkout / "private_automation/queue/jobs").glob("*.json"))
            batch_paths = list((checkout / "private_automation/queue/batches").glob("*.json"))
            self.assertEqual(len(source_paths), 1)
            source = json.loads(source_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(source["provider"], "chatgpt-worker")
            self.assertEqual(source["candidate_attempt_limit"], 12)
            self.assertEqual(len(batch_paths), 1)
            imported, stats = reconcile_sources([source], {}, datetime.now(timezone.utc))
            self.assertEqual(stats["created"], 1)
            self.assertEqual(next(iter(imported.values()))["row"]["website"], "https://www.one.test/")

            second = run_poller(csv_path, checkout, 1)
            self.assertEqual(second["status"], "no_eligible_sites")
            self.assertEqual(len(list((checkout / "private_automation/queue/jobs").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
