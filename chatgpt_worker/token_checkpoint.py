"""User-bound encrypted storage for one-time generation claim tokens."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import UUID


class CheckpointError(RuntimeError):
    """A claim token could not be safely checkpointed or loaded."""


_MAGIC = b"CTW1"
_ENTROPY = b"hometownredesignsites:chatgpt-worker:claim:v1"
_CHECKPOINT_ID = re.compile(r"([0-9a-f-]{36})\.(\d+)\.([0-9a-f]{16})\Z")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]


def _windows_dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise CheckpointError("Secure claim checkpoints require the Windows user credential store.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    data_buffer = ctypes.create_string_buffer(data, len(data))
    entropy_buffer = ctypes.create_string_buffer(_ENTROPY, len(_ENTROPY))
    input_blob = _DataBlob(len(data), ctypes.cast(data_buffer, ctypes.c_void_p))
    entropy_blob = _DataBlob(len(_ENTROPY), ctypes.cast(entropy_buffer, ctypes.c_void_p))
    output_blob = _DataBlob()
    description = ctypes.c_wchar_p()
    if protect:
        success = crypt32.CryptProtectData(
            ctypes.byref(input_blob), "ChatGPT worker claim", ctypes.byref(entropy_blob),
            None, None, 0x1, ctypes.byref(output_blob),
        )
    else:
        success = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), ctypes.byref(description), ctypes.byref(entropy_blob),
            None, None, 0x1, ctypes.byref(output_blob),
        )
    if not success:
        error_code = ctypes.get_last_error()
        raise CheckpointError(f"Windows could not {'protect' if protect else 'unprotect'} the claim checkpoint (error {error_code}).")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        if description:
            kernel32.LocalFree(description)


class TokenCheckpoint:
    """Persist claim tokens encrypted for the current Windows user account."""

    def __init__(self, directory: Path | None = None):
        if directory is None:
            directory_override = os.environ.get("CHATGPT_WORKER_CHECKPOINT_DIR")
            if directory_override:
                directory = Path(directory_override)
        if directory is None:
            app_data = os.environ.get("LOCALAPPDATA")
            if app_data:
                directory = Path(app_data) / "HometownRedesign" / "ChatGPTWorker" / "claims"
            else:
                directory = Path.home() / ".local" / "share" / "HometownRedesign" / "ChatGPTWorker" / "claims"
        self.directory = Path(directory)

    @staticmethod
    def checkpoint_id(job_id: str, epoch: int, token: str) -> str:
        UUID(job_id)
        if isinstance(epoch, bool) or epoch < 1 or not token:
            raise ValueError("A positive claim epoch and token are required.")
        return f"{job_id}.{epoch}.{hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]}"

    def ensure_available(self) -> None:
        probe = b"chatgpt-worker-dpapi-preflight"
        if _windows_dpapi(_windows_dpapi(probe, protect=True), protect=False) != probe:
            raise CheckpointError("Secure claim checkpoint preflight did not round-trip.")
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, job_id: str, epoch: int, worker_id: str, token: str,
             remote_url: str, branch: str) -> str:
        self.ensure_available()
        checkpoint_id = self.checkpoint_id(job_id, epoch, token)
        payload = {
            "job_id": job_id,
            "claim_epoch": epoch,
            "worker_id": worker_id,
            "claim_token": token,
            "remote_url": remote_url,
            "branch": branch,
        }
        encrypted = _MAGIC + _windows_dpapi(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"), protect=True,
        )
        target = self.directory / f"{checkpoint_id}.dpapi"
        if target.exists():
            existing = self._read_file(target)
            if existing != payload:
                raise CheckpointError("A different claim already uses this checkpoint identity.")
            return checkpoint_id
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix="claim-", suffix=".tmp", delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return checkpoint_id

    def _read_file(self, path: Path) -> dict[str, Any]:
        try:
            content = path.read_bytes()
        except OSError as error:
            raise CheckpointError("Claim checkpoint could not be read.") from error
        if not content.startswith(_MAGIC):
            raise CheckpointError("Claim checkpoint format is invalid.")
        try:
            value = json.loads(_windows_dpapi(content[len(_MAGIC):], protect=False).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CheckpointError("Claim checkpoint payload is invalid.") from error
        if not isinstance(value, dict) or not isinstance(value.get("claim_token"), str):
            raise CheckpointError("Claim checkpoint payload is incomplete.")
        return value

    def load(self, job_id: str, epoch: int, remote_url: str, branch: str,
             expected_sha256: str | None = None) -> dict[str, Any]:
        UUID(job_id)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise CheckpointError("The remote claim digest is missing or invalid.")
        matches = sorted(self.directory.glob(f"{job_id}.{epoch}.*.dpapi"))
        valid = []
        for path in matches:
            payload = self._read_file(path)
            if (payload.get("job_id") == job_id and payload.get("claim_epoch") == epoch
                    and payload.get("remote_url") == remote_url and payload.get("branch") == branch
                    and hashlib.sha256(payload["claim_token"].encode("utf-8")).hexdigest() == expected_sha256
                    and self.checkpoint_id(job_id, epoch, payload["claim_token"]) == path.stem):
                valid.append(payload)
        if len(valid) != 1:
            raise CheckpointError("A unique matching secure claim checkpoint was not found.")
        return valid[0]

    def delete_id(self, checkpoint_id: str) -> bool:
        if not _CHECKPOINT_ID.fullmatch(checkpoint_id):
            raise ValueError("Invalid claim checkpoint ID.")
        path = self.directory / f"{checkpoint_id}.dpapi"
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def delete(self, job_id: str, epoch: int) -> int:
        UUID(job_id)
        removed = 0
        for path in self.directory.glob(f"{job_id}.{epoch}.*.dpapi"):
            path.unlink()
            removed += 1
        return removed

    def list_ids(self) -> list[str]:
        ids = []
        for path in sorted(self.directory.glob("*.dpapi")):
            if _CHECKPOINT_ID.fullmatch(path.stem):
                ids.append(path.stem)
        return ids
