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
import errno
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
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


MAX_TIMEOUT_SECONDS = 3600.0
# JSON-lines is an interactive protocol: a peer may keep stdin open while
# waiting for a response.  Keep both the raw frame and protocol diagnostics
# bounded independently of the peer's eventual EOF.
MAX_FRAME_BYTES = 1 * 1024 * 1024
MAX_ERROR_TEXT = 8 * 1024


def _bounded_text(value: object, limit: int = MAX_ERROR_TEXT) -> str:
    """Convert protocol diagnostics to bounded, valid UTF-8 text."""
    text = str(value)
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return text
    suffix = b" [truncated]"
    prefix_limit = max(0, limit - len(suffix))
    return encoded[:prefix_limit].decode("utf-8", "ignore") + suffix.decode()


def _bounded_lines(stream: Any, limit: int = MAX_FRAME_BYTES):
    """Yield newline-delimited raw frames without waiting for EOF.

    ``readline`` and large ``read(n)`` calls are unsuitable for an interactive
    pipe: depending on the buffering layer they can wait for more input even
    after a complete frame has arrived.  Reading one raw byte at a time gives
    prompt framing while retaining only ``limit`` bytes; oversized content is
    consumed through its newline so the next frame remains synchronized.
    """
    raw_stream = getattr(stream, "buffer", None)
    if raw_stream is None or not hasattr(raw_stream, "read"):
        raw_stream = stream
    pending = bytearray()
    oversized = False
    while True:
        unit = raw_stream.read(1)
        if not unit:
            if pending or oversized:
                yield bytes(pending), oversized
            return
        if isinstance(unit, str):
            encoded = unit.encode("utf-8", "replace")
        else:
            encoded = bytes(unit)
        for byte in encoded:
            if byte == 0x0A:
                yield bytes(pending), oversized
                pending.clear()
                oversized = False
            elif not oversized:
                pending.append(byte)
                if len(pending) > limit:
                    oversized = True
                    del pending[limit:]


def _protocol_error(error: object, message: object) -> dict[str, object]:
    return {"ok": False, "error": _bounded_text(error),
            "message": _bounded_text(message)}


def _path_parts(relative_path: str) -> tuple[str, ...]:
    """Return safe lexical components without resolving attacker-controlled paths."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("path must be a non-empty relative path")
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise PermissionError("path must be a normalized relative path")
    if any("\\" in part or "\x00" in part for part in candidate.parts):
        raise PermissionError("path contains an unsafe component")
    return tuple(candidate.parts)


def _no_follow_flags(directory: bool = False) -> int:
    flags = os.O_RDONLY
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _open_child_dirs(root_fd: int, parts: tuple[str, ...], *, create: bool = False) -> int:
    """Open a directory chain relative to a pinned root, never following links."""
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                child = os.open(part, _no_follow_flags(directory=True), dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=current)
                child = os.open(part, _no_follow_flags(directory=True), dir_fd=current)
            st = os.fstat(child)
            if not stat.S_ISDIR(st.st_mode):
                os.close(child)
                raise NotADirectoryError(part)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


class ExecutionBroker:
    """Allowlisted command and write broker intended to run in a child process.

    Timeout cleanup kills the POSIX process group; Windows uses direct-child
    termination because portable stdlib Job Objects are unavailable. This is
    a bounded policy boundary, not a descriptor-perfect OS sandbox.

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
        self._workspace_fd: int | None = None
        if os.name == "posix":
            try:
                self._workspace_fd = os.open(
                    str(policy.workspace), _no_follow_flags(directory=True)
                )
                st = os.fstat(self._workspace_fd)
                if not stat.S_ISDIR(st.st_mode):
                    raise NotADirectoryError(str(policy.workspace))
            except OSError as exc:
                if self._workspace_fd is not None:
                    os.close(self._workspace_fd)
                    self._workspace_fd = None
                raise PermissionError("workspace cannot be pinned safely") from exc

    def __del__(self) -> None:
        fd = getattr(self, "_workspace_fd", None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def probe(self) -> dict[str, Any]:
        available = list(self.policy.resolved_executables)
        return {
            "host": "fable-execution-broker",
            "capabilities": [
                "execute_command", "inspect_files", "probe_capabilities", "write_file"
            ],
            "available_executables": available,
            "writes_enabled": self._writes_unlocked,
            "read_locked_interpreters": sorted(self.READ_LOCKED_INTERPRETERS),
            "workspace": str(self.policy.workspace),
        }

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("path must be a non-empty relative path")
        raw_candidate = self.policy.workspace / relative_path
        # Resolve only after rejecting links/reparse points in the lexical
        # path; otherwise a symlink could turn strict workspace containment
        # into a pathname illusion.
        cur = raw_candidate
        parts: list[Path] = []
        while True:
            parts.append(cur)
            if cur == self.policy.workspace or cur.parent == cur:
                break
            cur = cur.parent
        for part in reversed(parts):
            try:
                st = part.lstat()
            except FileNotFoundError:
                continue
            attrs = int(getattr(st, "st_file_attributes", 0))
            if (attrs & 0x400 or stat.S_ISLNK(st.st_mode) or stat.S_ISSOCK(st.st_mode)
                    or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode)):
                raise PermissionError("workspace path contains an unsafe link or special file")
        candidate = raw_candidate.resolve()
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

    def _pinned_parent(self, relative_path: str, *, create: bool = False) -> tuple[int, str, tuple[str, ...]]:
        parts = _path_parts(relative_path)
        if self._workspace_fd is None:
            raise PermissionError("descriptor-relative workspace operations require POSIX")
        parent_fd = _open_child_dirs(self._workspace_fd, parts[:-1], create=create)
        return parent_fd, parts[-1], parts

    def inspect_files(self, relative_path: str, max_bytes: int | None = None) -> dict[str, Any]:
        """Read one workspace file through a pinned directory descriptor."""
        limit = self.policy.max_output_bytes if max_bytes is None else int(max_bytes)
        if limit < 1:
            raise ValueError("max_bytes must be positive")
        limit = min(limit, self.policy.max_output_bytes)
        if self._workspace_fd is None:
            # Windows fallback: use the checked path-based implementation and
            # fail closed on unsafe nodes. Native Windows handle-relative
            # validation is a release-runner responsibility.
            target = self._safe_path(relative_path)
            target_st = target.lstat()
            if (not stat.S_ISREG(target_st.st_mode) or target_st.st_nlink != 1
                    or (os.name != "nt" and stat.S_IMODE(target_st.st_mode) & 0o022)):
                raise PermissionError("inspect path must be a private, non-hardlinked file")
            with target.open("rb") as handle:
                raw = handle.read(limit + 1)
            parts = _path_parts(relative_path)
            truncated = len(raw) > limit
            raw = raw[:limit]
            return {"path": "/".join(parts), "content": raw.decode("utf-8", errors="replace"),
                    "content_hash": hashlib.sha256(raw).hexdigest(), "truncated": truncated}
        parent_fd, name, parts = self._pinned_parent(relative_path)
        try:
            fd = os.open(name, _no_follow_flags(), dir_fd=parent_fd)
            try:
                target_st = os.fstat(fd)
                if (not stat.S_ISREG(target_st.st_mode) or target_st.st_nlink != 1
                        or (os.name != "nt" and stat.S_IMODE(target_st.st_mode) & 0o022)):
                    raise PermissionError("inspect path must be a private, non-hardlinked file")
                raw = os.read(fd, limit + 1)
            finally:
                os.close(fd)
        except FileNotFoundError as exc:
            raise ValueError("inspect path must be a file inside the workspace") from exc
        finally:
            os.close(parent_fd)
        truncated = len(raw) > limit
        raw = raw[:limit]
        return {
            "path": "/".join(parts),
            "content": raw.decode("utf-8", errors="replace"),
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "truncated": truncated,
        }

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        self._authorize_write()
        if not isinstance(content, str):
            raise ValueError("file content must be text")
        if self._workspace_fd is None:
            target = self._safe_path(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".fable-", dir=str(target.parent), text=True)
            temp = Path(temporary)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content); handle.flush(); os.fsync(handle.fileno())
                self._safe_path(relative_path)
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            return {"path": relative_path, "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "writes_enabled": True}
        parent_fd, name, parts = self._pinned_parent(relative_path, create=True)
        temporary_name = f".fable-{os.getpid()}-{threading.get_ident()}-{os.urandom(8).hex()}"
        temp_fd = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            temp_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
            raw = content.encode("utf-8")
            view = memoryview(raw)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except (FileNotFoundError, OSError):
                pass
            os.close(parent_fd)
        return {
            "path": "/".join(parts),
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
        try:
            timeout_seconds = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a finite positive number") from exc
        if not math.isfinite(timeout_seconds) or not (0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise ValueError(f"timeout_seconds must be finite and between 0 and {MAX_TIMEOUT_SECONDS}")
        cwd_fd: int | None = None
        if self._workspace_fd is None:
            directory = self.policy.workspace if cwd is None else self._safe_path(cwd)
            if not directory.is_dir():
                raise ValueError("cwd must be a directory inside the workspace")
            cwd_display = "." if cwd is None else str(Path(cwd))
        elif sys.platform == "darwin":
            # macOS has /dev/fd, but its descriptors are not consistently
            # usable as subprocess cwd paths. Keep the validated path fallback
            # for native compatibility; inspect/write remain descriptor-relative.
            directory = self.policy.workspace if cwd is None else self._safe_path(cwd)
            if not directory.is_dir():
                raise ValueError("cwd must be a directory inside the workspace")
            cwd_display = "." if cwd is None else str(Path(cwd))
        else:
            if cwd is None:
                cwd_fd = os.dup(self._workspace_fd)
                cwd_display = "."
            else:
                cwd_parts = _path_parts(cwd)
                cwd_fd = _open_child_dirs(self._workspace_fd, cwd_parts)
                cwd_display = "/".join(cwd_parts)
            directory = f"/proc/self/fd/{cwd_fd}"
            if not os.path.isdir(directory):
                os.close(cwd_fd)
                cwd_fd = None
                raise PermissionError("workspace cwd cannot be pinned safely")
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
        process: subprocess.Popen[bytes] | None = None
        output_limit = self.policy.max_output_bytes
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        output_limited = threading.Event()
        kill_lock = threading.Lock()

        def stop_process() -> None:
            if process is None:
                return
            with kill_lock:
                if process.poll() is not None:
                    return
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except (ProcessLookupError, PermissionError):
                    pass

        def drain(name: str, stream: Any) -> None:
            bucket = captured[name]
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                remaining = output_limit - len(bucket)
                if remaining <= 0:
                    output_limited.set()
                    stop_process()
                    continue
                if len(chunk) > remaining:
                    bucket.extend(chunk[:remaining])
                    output_limited.set()
                    stop_process()
                else:
                    bucket.extend(chunk)

        executed_argv = (registered_path, *argv[1:])
        try:
            process = subprocess.Popen(
                executed_argv,
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=(os.name == "posix"),
                creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                               if os.name == "nt" else 0),
            )
            assert process.stdout is not None and process.stderr is not None
            readers = [
                threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
                threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
            ]
            for reader in readers:
                reader.start()
            try:
                exit_code = process.wait(timeout=timeout_seconds)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                stop_process()
                exit_code = None
            for reader in readers:
                reader.join(timeout=5)
            if process.poll() is None:
                stop_process()
                process.wait(timeout=5)
        finally:
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            if cwd_fd is not None:
                try:
                    os.close(cwd_fd)
                except OSError:
                    pass

        stdout = bytes(captured["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(captured["stderr"]).decode("utf-8", errors="replace")

        def truncate(value: str) -> str:
            # Readers enforce this bound before decoding; this is only a
            # defensive guard for future callers that supply strings directly.
            encoded = value.encode("utf-8")
            if len(encoded) <= output_limit:
                return value
            return encoded[:output_limit].decode("utf-8", errors="ignore") + "\n[truncated]"

        return {
            "command": list(executed_argv),
            "cwd": cwd_display,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "output_limited": output_limited.is_set(),
            "stdout": truncate(stdout),
            "stderr": truncate(stderr),
            "success": exit_code == 0 and not timed_out and not output_limited.is_set(),
        }

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if action in {"probe", "probe_capabilities"}:
            return self.probe()
        if action == "inspect_files":
            return self.inspect_files(
                request.get("path", ""),
                max_bytes=request.get("max_bytes"),
            )
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
        for raw_line, oversized in _bounded_lines(channel, MAX_FRAME_BYTES):
            if oversized:
                print("admin control error: oversized frame", file=sys.stderr)
                continue
            if not raw_line.strip():
                continue
            try:
                request = json.loads(raw_line.decode("utf-8", "replace"))
                if not isinstance(request, dict) or request.get("action") != "unlock_writes":
                    raise ValueError("unsupported admin action")
                broker.unlock_writes(request.get("token", ""))
            except Exception as exc:
                print(f"admin control error: {_bounded_text(type(exc).__name__)}: "
                      f"{_bounded_text(exc)}", file=sys.stderr)


def serve(broker: ExecutionBroker, admin_fd: int | None = None) -> None:
    if admin_fd is not None:
        if os.name == "nt":
            raise ValueError("--admin-fd currently requires a POSIX inherited pipe")
        threading.Thread(target=_serve_admin_fd, args=(broker, admin_fd), daemon=True).start()
    # Do not use ``for line in sys.stdin``: TextIOWrapper iteration calls an
    # unbounded readline and can wait for EOF on an otherwise healthy client.
    for raw_line, oversized in _bounded_lines(sys.stdin, MAX_FRAME_BYTES):
        if oversized:
            response = _protocol_error("InvalidFrame", "request frame exceeds maximum size")
        elif not raw_line.strip():
            continue
        else:
            try:
                request = json.loads(raw_line.decode("utf-8", "replace"))
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                response = {"ok": True, "result": broker.handle(request)}
            except Exception as exc:  # protocol boundary: never crash the broker loop
                response = _protocol_error(type(exc).__name__, exc)
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
