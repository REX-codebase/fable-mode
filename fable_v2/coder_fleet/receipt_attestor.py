"""Receipt Attestor Engine for Cryptographic Tool Execution Attestation.

Records process execution telemetry (PID, exit code, stdout/stderr hashes, timestamps)
and signs them using HMAC-SHA256 into a tamper-evident ToolReceipt.
"""
from __future__ import annotations

import hashlib
import hmac
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any


class ReceiptAttestorEngine:
    """Engine for attesting subprocess execution and cryptographically verifying execution receipts."""

    def __init__(self, secret_key: bytes | None = None) -> None:
        self._secret_key = secret_key or hashlib.sha256(b"fable_receipt_attestor_default_secret").digest()

    def _compute_signature(
        self,
        cmd: list[str],
        cwd: str,
        pid: int,
        started_at: str,
        finished_at: str,
        exit_code: int,
        stdout_hash: str,
        stderr_hash: str,
    ) -> str:
        payload = f"{' '.join(cmd)}|{cwd}|{pid}|{started_at}|{finished_at}|{exit_code}|{stdout_hash}|{stderr_hash}"
        return hmac.new(self._secret_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def attest_execution(self, cmd: list[str], cwd: str = ".") -> dict[str, Any]:
        """Execute subprocess, record OS PID, start/end time, exit code, stdout hash,

        and HMAC-SHA256 signature, creating a tamper-evident ToolReceipt.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pid = proc.pid
        stdout, stderr = proc.communicate()
        duration_ms = (time.perf_counter() - t0) * 1000.0
        finished_at = datetime.now(timezone.utc).isoformat()
        exit_code = proc.returncode

        stdout_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        stderr_hash = hashlib.sha256(stderr.encode("utf-8")).hexdigest()

        signature = self._compute_signature(
            cmd=cmd,
            cwd=cwd,
            pid=pid,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_hash=stdout_hash,
            stderr_hash=stderr_hash,
        )

        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"

        return {
            "receipt_id": receipt_id,
            "cmd": list(cmd),
            "cwd": cwd,
            "pid": pid,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": round(duration_ms, 2),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_hash": stdout_hash,
            "stderr_hash": stderr_hash,
            "signature": signature,
            "tamper_evident": True,
        }

    def verify_receipt(self, receipt: dict[str, Any]) -> bool:
        """Validate hash and HMAC-SHA256 signature integrity of a ToolReceipt."""
        if not isinstance(receipt, dict):
            return False

        required = ("cmd", "cwd", "pid", "started_at", "finished_at", "exit_code", "stdout_hash", "stderr_hash", "signature")
        if not all(k in receipt for k in required):
            return False

        # If full stdout / stderr text is provided, verify against hashes
        if "stdout" in receipt:
            actual_stdout_hash = hashlib.sha256(str(receipt["stdout"]).encode("utf-8")).hexdigest()
            if actual_stdout_hash != receipt["stdout_hash"]:
                return False

        if "stderr" in receipt:
            actual_stderr_hash = hashlib.sha256(str(receipt["stderr"]).encode("utf-8")).hexdigest()
            if actual_stderr_hash != receipt["stderr_hash"]:
                return False

        expected_sig = self._compute_signature(
            cmd=receipt["cmd"],
            cwd=receipt["cwd"],
            pid=int(receipt["pid"]),
            started_at=str(receipt["started_at"]),
            finished_at=str(receipt["finished_at"]),
            exit_code=int(receipt["exit_code"]),
            stdout_hash=str(receipt["stdout_hash"]),
            stderr_hash=str(receipt["stderr_hash"]),
        )

        return hmac.compare_digest(expected_sig, str(receipt["signature"]))
