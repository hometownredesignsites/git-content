"""Git-backed per-job compare-and-swap persistence for the private queue."""

from __future__ import annotations

import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any, Callable
from uuid import UUID

from chatgpt_worker.queue import (
    FINAL_FILES, QueueConflict, assert_current_claim, complete, expire_claim, mark_handed_off,
    reconcile_sources, reserve_handoff,
)


class GitStoreError(RuntimeError):
    """A private branch transaction failed for a reason other than contention."""


class GitJobStore:
    """Persist one-job mutations using remote fast-forward push as CAS.

    Each update gets its own temporary clone. If another writer advances the
    branch after this clone's read, Git rejects the non-fast-forward push; the
    store then rereads and recomputes the transition. Credentials come from the
    configured Git credential helper/environment, never from job records.
    """

    def __init__(self, remote_url: str, branch: str = "chatgpt-worker", retries: int = 5):
        if not remote_url or not branch or retries < 1:
            raise ValueError("remote_url, branch, and positive retry count are required")
        self.remote_url = remote_url
        self.branch = branch
        self.retries = retries

    @staticmethod
    def _git(cwd: Path | None, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd, text=True, encoding="utf-8",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                timeout=120, env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise GitStoreError("Private queue Git operation exceeded its time limit.") from error
        if check and result.returncode:
            raise GitStoreError("Private queue Git operation failed; command output is withheld.")
        return result

    @staticmethod
    def _git_bytes(cwd: Path, input_bytes: bytes, *args: str) -> subprocess.CompletedProcess[bytes]:
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd, input=input_bytes,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                timeout=120, env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise GitStoreError("Private artifact Git operation exceeded its time limit.") from error
        if result.returncode:
            raise GitStoreError("Private artifact Git operation failed; command output is withheld.")
        return result

    @staticmethod
    def _job_path(job_id: str) -> PurePosixPath:
        UUID(job_id)
        return PurePosixPath("private_automation/queue/generation/jobs") / f"{job_id}.json"

    def _clone(self, parent: Path, name: str) -> Path:
        checkout = parent / name
        self._git(None, "clone", "-c", "core.autocrlf=false", "--quiet", "--single-branch", "--branch", self.branch,
                  self.remote_url, str(checkout))
        # Candidate and evidence blobs are digest-bound; autocrlf is disabled
        # during clone so checkout and subsequent staging preserve exact bytes.
        return checkout

    def _push(self, checkout: Path, base: str, paths: list[PurePosixPath], message: str) -> bool:
        for relative in paths:
            self._git(checkout, "add", "--", relative.as_posix())
        self._git(checkout, "-c", "user.name=ChatGPT Worker Queue", "-c",
                  "user.email=chatgpt-worker-queue@users.noreply.github.com",
                  "commit", "--quiet", "-m", message)
        pushed = self._git(checkout, "push", "origin", f"HEAD:refs/heads/{self.branch}", check=False)
        if pushed.returncode == 0:
            return True
        remote = self._git(checkout, "ls-remote", "origin", f"refs/heads/{self.branch}", check=False)
        if remote.returncode:
            raise GitStoreError("Could not verify private queue branch after a rejected push.")
        remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
        if remote_head == base:
            raise GitStoreError("Private queue push failed without a concurrent branch update.")
        return False

    def read_job(self, job_id: str) -> dict[str, Any]:
        relative = self._job_path(job_id)
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-read-") as temp:
            checkout = self._clone(Path(temp), "repo")
            path = checkout.joinpath(*relative.parts)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise GitStoreError("Private generation job is missing or invalid.") from error
            if not isinstance(value, dict) or value.get("job_id") != job_id:
                raise GitStoreError("Private generation job identity did not match its path.")
            return value

    def read_completed_artifacts(self, job_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
        """Read and reverify a completed result for an idempotent downstream handoff."""
        relative = self._job_path(job_id)
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-result-read-") as temp:
            checkout = self._clone(Path(temp), "repo")
            try:
                job = json.loads(checkout.joinpath(*relative.parts).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise GitStoreError("Private generation job is missing or invalid.") from error
            if not isinstance(job, dict) or job.get("job_id") != job_id:
                raise GitStoreError("Private generation job identity did not match its path.")
            result = job.get("result")
            if job.get("status") != "completed" or not isinstance(result, dict) or result.get("qa_status") != "PASS":
                raise QueueConflict("Only a completed PASS result can be handed to content-post")
            self._verify_result_files(checkout, job, result)
            artifact_commit = result.get("artifact_commit")
            if not isinstance(artifact_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", artifact_commit):
                raise QueueConflict("Completed result has no valid private artifact commit")
            ancestor = self._git(checkout, "merge-base", "--is-ancestor", artifact_commit, "HEAD", check=False)
            if ancestor.returncode != 0:
                raise QueueConflict("Recorded artifact commit is not present in the current private branch history")
            run_path = PurePosixPath(result["run_path"])
            artifacts = {}
            for slot, candidate in result["candidates"].items():
                relative_candidate = run_path / candidate["filename"]
                artifacts[slot] = checkout.joinpath(*relative_candidate.parts).read_bytes()
            return job, artifacts

    def update_job(self, job_id: str, transition: Callable[[dict[str, Any]], dict[str, Any]],
                   validate: Callable[[Path, dict[str, Any], dict[str, Any]], None] | None = None) -> dict[str, Any]:
        """Apply a deterministic transition and commit it only if the read head wins CAS."""
        relative = self._job_path(job_id)
        last_error = ""
        for attempt in range(self.retries):
            with tempfile.TemporaryDirectory(prefix="chatgpt-worker-update-") as temp:
                checkout = self._clone(Path(temp), "repo")
                base = self._git(checkout, "rev-parse", "HEAD").stdout.strip()
                path = checkout.joinpath(*relative.parts)
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise GitStoreError("Private generation job is missing or invalid.") from error
                if not isinstance(current, dict) or current.get("job_id") != job_id:
                    raise GitStoreError("Private generation job identity did not match its path.")
                updated = transition(current)
                if not isinstance(updated, dict) or updated.get("job_id") != job_id:
                    raise GitStoreError("Queue transition returned an invalid job record.")
                if updated == current:
                    return current
                if validate is not None:
                    validate(checkout, current, updated)
                path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                if self._push(checkout, base, [relative], f"generation queue: update job {job_id}"):
                    return updated
                last_error = "Private queue branch advanced concurrently."
            # The temporary checkout is removed before retrying from a fresh remote snapshot.
        raise GitStoreError(f"Private queue update did not converge after {self.retries} attempts. {last_error}")

    def list_jobs(self) -> list[dict[str, Any]]:
        folder = PurePosixPath("private_automation/queue/generation/jobs")
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-list-") as temp:
            checkout = self._clone(Path(temp), "repo")
            directory = checkout.joinpath(*folder.parts)
            jobs = []
            if not directory.exists():
                return jobs
            for path in sorted(directory.glob("*.json")):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise GitStoreError("A private generation job record is invalid.") from error
                if not isinstance(record, dict) or record.get("job_id") != path.stem:
                    raise GitStoreError("Private generation job identity did not match its path.")
                self._job_path(record["job_id"])
                jobs.append(record)
            return jobs

    def reconcile_intake(self, now: datetime | None = None) -> dict[str, int]:
        """Import opted-in source jobs and commit all new ledger records atomically."""
        now = now or datetime.now(timezone.utc)
        source_dir = PurePosixPath("private_automation/queue/jobs")
        generation_dir = PurePosixPath("private_automation/queue/generation/jobs")
        last_error = ""
        for _ in range(self.retries):
            with tempfile.TemporaryDirectory(prefix="chatgpt-worker-reconcile-") as temp:
                checkout = self._clone(Path(temp), "repo")
                base = self._git(checkout, "rev-parse", "HEAD").stdout.strip()
                source_jobs = []
                for path in sorted(checkout.joinpath(*source_dir.parts).glob("*.json")):
                    try:
                        value = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as error:
                        raise GitStoreError("A private source job record is invalid.") from error
                    if isinstance(value, dict):
                        source_jobs.append(value)
                existing = {}
                directory = checkout.joinpath(*generation_dir.parts)
                if directory.exists():
                    for path in sorted(directory.glob("*.json")):
                        value = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(value, dict) and isinstance(value.get("job_id"), str):
                            existing[value["job_id"]] = value
                updated, stats = reconcile_sources(source_jobs, existing, now)
                created = sorted(set(updated) - set(existing))
                if not created:
                    return stats
                directory.mkdir(parents=True, exist_ok=True)
                paths = []
                for job_id in created:
                    self._job_path(job_id)
                    path = directory / f"{job_id}.json"
                    path.write_text(json.dumps(updated[job_id], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    paths.append(generation_dir / path.name)
                if self._push(checkout, base, paths, f"generation queue: reconcile {len(created)} intake job(s)"):
                    return stats
                last_error = "Private queue branch advanced during reconciliation."
        raise GitStoreError(f"Private queue reconciliation did not converge. {last_error}")

    def recover_expired(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(timezone.utc)
        recovered = 0
        for job in self.list_jobs():
            updated = self.update_job(job["job_id"], lambda current: expire_claim(current, now))
            if job.get("claim") is not None and updated.get("claim") is None and updated.get("status") == "queued":
                recovered += 1
        return {"recovered": recovered, "total": len(self.list_jobs())}

    def complete_job(self, job_id: str, worker_id: str, epoch: int, result_record: dict[str, Any],
                     now: datetime | None = None) -> dict[str, Any]:
        def verify(checkout: Path, _current: dict[str, Any], updated: dict[str, Any]) -> None:
            self._verify_result_files(checkout, updated, result_record)

        return self.update_job(
            job_id,
            lambda current: complete(current, worker_id, now or datetime.now(timezone.utc), epoch, result_record),
            verify,
        )

    def publish_artifacts(self, job_id: str, worker_id: str, epoch: int, run_path: str,
                          files: dict[str, bytes]) -> str:
        """Persist exact output bytes while the same fenced claim is current.

        Artifact paths are immutable: a retry may confirm identical bytes but
        cannot replace a path already committed with different content.
        """
        relative_run = PurePosixPath(run_path)
        if (relative_run.is_absolute() or ".." in relative_run.parts
                or len(relative_run.parts) < 3 or relative_run.parts[0] != "results"):
            raise QueueConflict("Result run_path is not a safe private results path")
        if not files:
            raise QueueConflict("No result artifacts were supplied")
        checked: dict[PurePosixPath, bytes] = {}
        for name, content in files.items():
            relative_file = PurePosixPath(name)
            if relative_file.is_absolute() or not name or ".." in relative_file.parts:
                raise QueueConflict("Result artifact path is unsafe")
            if not isinstance(content, bytes):
                raise TypeError("Result artifacts must be bytes")
            checked[relative_run / relative_file] = content
        job_relative = self._job_path(job_id)
        last_error = ""
        for _ in range(self.retries):
            with tempfile.TemporaryDirectory(prefix="chatgpt-worker-publish-") as temp:
                checkout = self._clone(Path(temp), "repo")
                base = self._git(checkout, "rev-parse", "HEAD").stdout.strip()
                record_path = checkout.joinpath(*job_relative.parts)
                try:
                    job = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    raise GitStoreError("Private generation job is missing or invalid.") from error
                if not isinstance(job, dict) or job.get("job_id") != job_id:
                    raise GitStoreError("Private generation job identity did not match its path.")
                if job.get("result_slug") != relative_run.parts[1]:
                    raise QueueConflict("Result files must stay under this job's private results folder")
                attempt_now = datetime.now(timezone.utc)
                assert_current_claim(job, worker_id, attempt_now, epoch)
                results_root = (checkout / "results").resolve()
                site_dir = checkout / "results" / str(job.get("result_slug"))
                if (checkout / "results").is_symlink() or site_dir.is_symlink():
                    raise QueueConflict("Private result folders cannot use symbolic links")
                site_root = site_dir.resolve()
                if not site_root.is_relative_to(results_root):
                    raise QueueConflict("Private site results folder resolves outside the results tree")
                changed_paths: list[PurePosixPath] = []
                for relative, content in checked.items():
                    target = checkout.joinpath(*relative.parts)
                    resolved = target.resolve()
                    if not resolved.is_relative_to(site_root):
                        raise QueueConflict("Result artifact path escaped this job's private results folder")
                    cursor = target
                    while cursor != checkout and cursor != site_root:
                        if cursor.is_symlink():
                            raise QueueConflict("Result artifact paths cannot use symbolic links")
                        cursor = cursor.parent
                    if target.exists():
                        if not target.is_file() or target.read_bytes() != content:
                            raise QueueConflict("An immutable result artifact path already has different bytes")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    changed_paths.append(relative)
                if not changed_paths:
                    return base
                for relative in changed_paths:
                    content = checked[relative]
                    blob = self._git_bytes(checkout, content, "hash-object", "-w", "--no-filters", "--stdin").stdout.decode().strip()
                    self._git(checkout, "update-index", "--add", "--cacheinfo", "100644", blob,
                              relative.as_posix())
                self._git(checkout, "-c", "user.name=ChatGPT Worker Publisher", "-c",
                          "user.email=chatgpt-worker-publisher@users.noreply.github.com",
                          "commit", "--quiet", "-m", f"generation artifacts: publish {job_id} epoch {epoch}")
                published_commit = self._git(checkout, "rev-parse", "HEAD").stdout.strip()
                assert_current_claim(job, worker_id, datetime.now(timezone.utc), epoch)
                pushed = self._git(checkout, "push", "origin", f"HEAD:refs/heads/{self.branch}", check=False)
                if pushed.returncode == 0:
                    return published_commit
                remote = self._git(checkout, "ls-remote", "origin", f"refs/heads/{self.branch}", check=False)
                if remote.returncode:
                    raise GitStoreError("Could not verify private branch after an artifact push was rejected.")
                remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
                if remote_head == base:
                    raise GitStoreError("Private artifact push failed without a concurrent branch update.")
                last_error = "Private worker branch advanced while publishing artifacts."
        raise GitStoreError(f"Private artifact publication did not converge. {last_error}")

    def reserve_content_post_handoff(self, job_id: str, batch_id: str,
                                     now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        return self.update_job(job_id, lambda current: reserve_handoff(current, batch_id, now))

    def mark_content_post_handed_off(self, job_id: str, batch_id: str,
                                     now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        return self.update_job(job_id, lambda current: mark_handed_off(current, batch_id, now))

    @staticmethod
    def _verify_result_files(checkout: Path, job: dict[str, Any], result_record: dict[str, Any]) -> None:
        if not isinstance(result_record, dict):
            raise QueueConflict("Result record must be an object")
        run_path = PurePosixPath(str(result_record.get("run_path", "")))
        if run_path.is_absolute() or ".." in run_path.parts or len(run_path.parts) < 3:
            raise QueueConflict("Result run_path is not a safe private results path")
        if run_path.parts[0] != "results" or run_path.parts[1] != job.get("result_slug"):
            raise QueueConflict("Result files must stay under this job's private results folder")
        results_root = (checkout / "results").resolve()
        result_root = (checkout / "results" / str(job.get("result_slug"))).resolve()
        if ((checkout / "results").is_symlink()
                or not results_root.is_relative_to(checkout.resolve())
                or not result_root.is_relative_to(results_root)):
            raise QueueConflict("Private site results folder resolves outside the results tree")
        candidates = result_record.get("candidates")
        if not isinstance(candidates, dict) or set(candidates) != set(FINAL_FILES):
            raise QueueConflict("Result must contain exactly Forty, Landed, and Story")
        for slot, candidate in candidates.items():
            if not isinstance(candidate, dict) or candidate.get("filename") != FINAL_FILES[slot]:
                raise QueueConflict(f"Candidate file metadata for {slot} is invalid")
            relative = run_path / candidate["filename"]
            candidate_path = checkout.joinpath(*relative.parts).resolve()
            if not candidate_path.is_relative_to(result_root):
                raise QueueConflict("Candidate file path escaped this job's private results folder")
            try:
                content = candidate_path.read_bytes()
            except OSError as error:
                raise QueueConflict(f"Candidate file for {slot} is missing from the private branch") from error
            if len(content) != candidate["bytes"]:
                raise QueueConflict(f"Candidate byte count for {slot} does not match the private file")
            if hashlib.sha256(content).hexdigest() != candidate["sha256"]:
                raise QueueConflict(f"Candidate SHA-256 for {slot} does not match the private file")
        evidence = result_record.get("qa_evidence")
        if evidence is not None:
            if not isinstance(evidence, dict):
                raise QueueConflict("QA evidence metadata must be an object")
            evidence_path = run_path / str(evidence.get("filename", ""))
            if evidence_path.is_absolute() or ".." in evidence_path.parts or not evidence_path.parts:
                raise QueueConflict("QA evidence path is unsafe")
            target = checkout.joinpath(*evidence_path.parts).resolve()
            if not target.is_relative_to(result_root):
                raise QueueConflict("QA evidence path escaped this job's private results folder")
            try:
                content = target.read_bytes()
            except OSError as error:
                raise QueueConflict("QA evidence file is missing from the private branch") from error
            expected_bytes = evidence.get("bytes")
            expected_sha = evidence.get("sha256")
            if (isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int)
                    or expected_bytes != len(content) or not isinstance(expected_sha, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", expected_sha)
                    or hashlib.sha256(content).hexdigest() != expected_sha):
                raise QueueConflict("QA evidence digest does not match the private file")
