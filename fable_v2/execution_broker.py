"""Process-isolated execution boundary for Fable V2.

The broker is the only component in this foundation that should be granted
workspace write permission. It exposes a small JSON-lines protocol so hosts
can launch it as a child process and keep model-facing tools away from direct
filesystem writes. This is a policy boundary, not a complete OS sandbox;
production deployments should add containers, OS MAC, seccomp/job objects,
or an equivalent hardened isolation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterable


@dataclass(frozen=True)
class BrokerPolicy:
    workspace: Path
    allowed_executables: tuple[str, ...] = ("python", "python3", "pytest")
    max_output_bytes: int = 1_000_000
    write_token_digest: str | None = None
    resolved_executables: dict[str, str] = field(
        init=False, default_factory=dict, repr=False, compare=False
    )  # populated from trusted PATH at startup

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("workspace must be an existing directory")
        if self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        if not self.allowed_executables:
            raise ValueError("at least one executable must be allowlisted")
        resolved: dict[str, str] = {}
        normalized_names: list[str] = []
        for item in self.allowed_executables:
            requested = Path(item).expanduser()
            located = requested if requested.is_absolute() else Path(shutil.which(str(requested)) or "")
            if not located or not located.exists() or not located.is_file():
                continue
            absolute = str(located.resolve())
            key = os.path.normcase(Path(item).name)
            if key in resolved and os.path.normcase(resolved[key]) != os.path.normcase(absolute):
                raise ValueError(f"ambiguous executable allowlist entry: {item}")
            resolved[key] = absolute
            normalized_names.append(Path(item).name)
        if not resolved:
            raise ValueError("no allowlisted executable could be resolved at broker startup")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "allowed_executables", tuple(dict.fromkeys(normalized_names)))
        object.__setattr__(self, "resolved_executables", resolved)


class ExecutionBroker:
    """Allowlisted command and write broker intended to run in a child process.

    General interpreters and shell entry points are blocked while writes are
    locked. ``shell=False`` alone is not a filesystem sandbox: an invocation
    such as ``python -c`` can still write files directly.
    """

    READ_LOCKED_INTERPRETERS = frozenset({
        "bash", "cmd", "node", "perl", "php", "pypy", "powershell",
        "pwsh", "python", "pytest", "ruby", "sh", "zsh",
    })

    def __init__(self, policy: BrokerPolicy):
        self.policy = policy
        self._writes_unlocked = False

    def probe(self) -> dict[str, Any]:
        available = list(self.policy.resolved_executables)
        return {
            "host": "fable-execution-broker",
            "capabilities": ["execute_command", "inspect_files", "probe_capabilities"],
            "available_executables": available,
            "writes_enabled": self._writes_unlocked,
            "read_locked_interpreters": sorted(self.READ_LOCKED_INTERPRETERS),
            "workspace": str(self.policy.workspace),
        }

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("path must be a non-empty relative path")
        candidate = (self.policy.workspace / relative_path).resolve()
        try:
            candidate.relative_to(self.policy.workspace)
        except ValueError as exc:
            raise PermissionError("path escapes the broker workspace") from exc
        return candidate

    def unlock_writes(self, token: str) -> None:
        """Unlock writes through an administrator-only control channel."""
        if self._writes_unlocked:
            return
        digest = self.policy.write_token_digest
        if not digest or not token:
            raise PermissionError("workspace writes are locked")
        supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(supplied, digest):
            raise PermissionError("invalid write authorization")
        self._writes_unlocked = True

    def _authorize_write(self) -> None:
        if not self._writes_unlocked:
            raise PermissionError("workspace writes are locked")

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        self._authorize_write()
        if not isinstance(content, str):
            raise ValueError("file content must be text")
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".fable-", dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {
            "path": str(target.relative_to(self.policy.workspace)),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "writes_enabled": True,
        }

    def execute_command(
        self,
        command: Iterable[str],
        cwd: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        argv = tuple(command)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("command must be a non-empty sequence of strings")
        requested_executable = Path(argv[0])
        executable = requested_executable.name
        executable_key = Path(executable).stem.lower()
        is_interpreter = (
            executable_key in self.READ_LOCKED_INTERPRETERS
            or executable_key.startswith("python")
        )
        registered_path = self.policy.resolved_executables.get(os.path.normcase(executable))
        if not registered_path:
            raise PermissionError(f"executable is not allowlisted: {executable}")
        requested_path = requested_executable if requested_executable.is_absolute() else Path(
            shutil.which(str(requested_executable)) or ""
        )
        if not requested_path or not requested_path.exists():
            raise PermissionError(f"executable cannot be resolved: {argv[0]}")
        if os.path.normcase(str(requested_path.resolve())) != os.path.normcase(registered_path):
            raise PermissionError("executable path does not match its startup registration")
        if is_interpreter and not self._writes_unlocked:
            raise PermissionError(
                "general interpreters and shells are blocked while workspace writes are locked"
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        directory = self.policy.workspace if cwd is None else self._safe_path(cwd)
        if not directory.is_dir():
            raise ValueError("cwd must be a directory inside the workspace")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
        try:
            completed = subprocess.run(
                (registered_path, *argv[1:]),
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=timeout_seconds,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            timed_out = False
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            timed_out = True
            exit_code = None

        def truncate(value: str) -> str:
            if len(value.encode("utf-8")) <= self.policy.max_output_bytes:
                return value
            encoded = value.encode("utf-8")[: self.policy.max_output_bytes]
            return encoded.decode("utf-8", errors="ignore") + "\n[truncated]"

        executed_argv = (registered_path, *argv[1:])
        return {
            "command": list(executed_argv),
            "cwd": str(directory.relative_to(self.policy.workspace)),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": truncate(stdout),
            "stderr": truncate(stderr),
            "success": exit_code == 0 and not timed_out,
        }

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if action == "probe":
            return self.probe()
        if action == "execute_command":
            return self.execute_command(
                request.get("command", ()),
                cwd=request.get("cwd"),
                timeout_seconds=float(request.get("timeout_seconds", 120.0)),
            )
        if action == "write_file":
            # No authorization token is accepted on the model JSON channel.
            return self.write_file(request.get("path", ""), request.get("content", ""))
        raise ValueError(f"unsupported broker action: {action}")


def _serve_admin_fd(broker: ExecutionBroker, fd: int) -> None:
    """Consume admin commands from an inherited, non-model file descriptor."""
    with os.fdopen(os.dup(fd), "r", encoding="utf-8") as channel:
        for line in channel:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if request.get("action") != "unlock_writes":
                    raise ValueError("unsupported admin action")
                broker.unlock_writes(request.get("token", ""))
            except Exception as exc:
                print(f"admin control error: {type(exc).__name__}: {exc}", file=sys.stderr)


def serve(broker: ExecutionBroker, admin_fd: int | None = None) -> None:
    if admin_fd is not None:
        if os.name == "nt":
            raise ValueError("--admin-fd currently requires a POSIX inherited pipe")
        threading.Thread(target=_serve_admin_fd, args=(broker, admin_fd), daemon=True).start()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = {"ok": True, "result": broker.handle(json.loads(line))}
        except Exception as exc:  # protocol boundary: never crash the broker loop
            response = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _load_write_token_digest() -> str | None:
    """Load write authorization from administrator-controlled configuration."""
    digest = os.environ.get("FABLE_BROKER_WRITE_TOKEN_DIGEST", "").strip()
    digest_file = os.environ.get("FABLE_BROKER_WRITE_TOKEN_DIGEST_FILE", "").strip()
    if digest and digest_file:
        raise ValueError("configure only one write-token digest source")
    if digest_file:
        digest = Path(digest_file).read_text(encoding="utf-8").strip()
    if not digest:
        return None
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise ValueError("write-token digest must be a SHA-256 hexadecimal string")
    return digest.lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fable V2 execution broker")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--allow-executable", action="append", default=[])
    parser.add_argument(
        "--admin-fd", type=int,
        help="POSIX inherited one-way admin control FD; never expose to a model",
    )
    args = parser.parse_args(argv)
    allowed = tuple(args.allow_executable) or BrokerPolicy.allowed_executables
    policy = BrokerPolicy(
        workspace=args.workspace,
        allowed_executables=allowed,
        write_token_digest=_load_write_token_digest(),
    )
    serve(ExecutionBroker(policy), admin_fd=args.admin_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
