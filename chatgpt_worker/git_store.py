"""Git-backed per-job compare-and-swap persistence for the private queue."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any, Callable
from uuid import UUID

from chatgpt_worker.queue import QueueConflict


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
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if check and result.returncode:
            raise GitStoreError("Private queue Git operation failed; command output is withheld.")
        return result

    @staticmethod
    def _job_path(job_id: str) -> PurePosixPath:
        UUID(job_id)
        return PurePosixPath("private_automation/queue/generation/jobs") / f"{job_id}.json"

    def read_job(self, job_id: str) -> dict[str, Any]:
        relative = self._job_path(job_id)
        with tempfile.TemporaryDirectory(prefix="chatgpt-worker-read-") as temp:
            checkout = Path(temp) / "repo"
            self._git(None, "clone", "--quiet", "--single-branch", "--branch", self.branch,
                      self.remote_url, str(checkout))
            path = checkout.joinpath(*relative.parts)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise GitStoreError("Private generation job is missing or invalid.") from error
            if not isinstance(value, dict) or value.get("job_id") != job_id:
                raise GitStoreError("Private generation job identity did not match its path.")
            return value

    def update_job(self, job_id: str, transition: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        """Apply a deterministic transition and commit it only if the read head wins CAS."""
        relative = self._job_path(job_id)
        last_error = ""
        for attempt in range(self.retries):
            with tempfile.TemporaryDirectory(prefix="chatgpt-worker-update-") as temp:
                checkout = Path(temp) / "repo"
                self._git(None, "clone", "--quiet", "--single-branch", "--branch", self.branch,
                          self.remote_url, str(checkout))
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
                path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                self._git(checkout, "add", "--", relative.as_posix())
                self._git(checkout, "-c", "user.name=ChatGPT Worker Queue", "-c",
                          "user.email=chatgpt-worker-queue@users.noreply.github.com",
                          "commit", "--quiet", "-m", f"generation queue: update job {job_id}")
                pushed = self._git(checkout, "push", "origin", f"HEAD:refs/heads/{self.branch}", check=False)
                if pushed.returncode == 0:
                    return updated

                remote = self._git(checkout, "ls-remote", "origin", f"refs/heads/{self.branch}", check=False)
                if remote.returncode:
                    raise GitStoreError("Could not verify private queue branch after a rejected push.")
                remote_head = remote.stdout.split()[0] if remote.stdout.strip() else ""
                if remote_head == base:
                    raise GitStoreError("Private queue push failed without a concurrent branch update.")
                last_error = "Private queue branch advanced concurrently."
            # The temporary checkout is removed before retrying from a fresh remote snapshot.
        raise GitStoreError(f"Private queue update did not converge after {self.retries} attempts. {last_error}")
