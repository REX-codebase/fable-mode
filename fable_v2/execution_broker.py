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
from contextlib import contextmanager
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
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping
import uuid

from .protocol import CANONICAL_SERIALIZATION_VERSION, canonical_hash, utc_now
from .system3 import KripkeStructure, KripkeModelChecker, CausalDAG, CausalNode, CausalNodeType


@dataclass(frozen=True)
class BrokerReceipt:
    """Measured record of one broker operation, suitable for external attestation."""

    receipt_id: str
    session_id: str
    action: str
    capability: str
    tool_name: str
    input_hash: str
    output_hash: str
    executable_identity: Mapping[str, Any]
    workspace_identity: Mapping[str, Any]
    started_at: str
    finished_at: str
    success: bool
    cancelled: bool = False
    cancellation_status: str = "not_cancelled"
    timed_out: bool = False
    canonicalization: str = CANONICAL_SERIALIZATION_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id, "session_id": self.session_id,
            "action": self.action, "capability": self.capability,
            "tool_name": self.tool_name, "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "executable_identity": dict(self.executable_identity),
            "workspace_identity": dict(self.workspace_identity),
            "started_at": self.started_at, "finished_at": self.finished_at,
            "success": self.success, "cancelled": self.cancelled,
            "cancellation_status": self.cancellation_status,
            "timed_out": self.timed_out, "canonicalization": self.canonicalization,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BrokerPolicy:
    workspace: Path
    allowed_executables: tuple[str, ...] = ("python", "python3", "pytest")
    max_output_bytes: int = 1_000_000
    write_token_digest: str | None = None
    # Workspace writes are bounded both per replacement and in aggregate.
    # Accounting charges UTF-8 bytes attempted through the shared workspace
    # ledger; the publication lock serializes independent instances.
    max_file_write_bytes: int = 16 * 1024 * 1024
    max_workspace_write_bytes: int = 64 * 1024 * 1024
    resolved_executables: dict[str, str] = field(
        init=False, default_factory=dict, repr=False, compare=False
    )  # populated from trusted PATH at startup
    resolved_executable_identities: dict[str, dict[str, Any]] = field(
        init=False, default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("workspace must be an existing directory")
        if self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        if self.max_file_write_bytes < 1 or self.max_workspace_write_bytes < 1:
            raise ValueError("write quotas must be positive")
        if self.max_file_write_bytes > self.max_workspace_write_bytes:
            raise ValueError("per-file write quota cannot exceed workspace quota")
        object.__setattr__(self, "max_file_write_bytes", int(self.max_file_write_bytes))
        object.__setattr__(self, "max_workspace_write_bytes", int(self.max_workspace_write_bytes))
        if not self.allowed_executables:
            raise ValueError("at least one executable must be allowlisted")
        resolved: dict[str, str] = {}
        identities: dict[str, dict[str, Any]] = {}
        normalized_names: list[str] = []
        for item in self.allowed_executables:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise ValueError("allowlisted executable names must be safe strings")
            requested = Path(item).expanduser()
            if requested.is_absolute() and requested.is_symlink():
                raise ValueError(f"unsafe executable allowlist entry: {item}")
            # ``Path("")`` is ``Path(".")``.  Do not use it as the
            # not-found sentinel: a missing optional default (notably pytest
            # in a minimal installation) would otherwise be classified as the
            # workspace directory and rejected as an unsafe executable.
            located = requested if requested.is_absolute() else None
            if located is None:
                found = shutil.which(str(requested))
                if not found:
                    continue
                located = Path(found)
            if not located.exists():
                continue
            try:
                # Explicit link entries are never accepted. A bare PATH name
                # may be a distribution's standard alias for this exact
                # running interpreter; permit only that trusted alias and
                # reject every other linked executable.
                if (not requested.is_absolute() and located.is_symlink()
                        and located.resolve() != Path(sys.executable).resolve()):
                    raise PermissionError("linked PATH executable is not the running interpreter")
                measure_path = located.resolve() if not requested.is_absolute() else located
                identity = _measure_executable_path(measure_path)
            except (OSError, ValueError, PermissionError) as exc:
                # An explicitly supplied unsafe entry must never silently turn
                # into a different PATH entry.  This is especially important
                # for symlinks, Windows reparse points, and hardlinks.
                raise ValueError(f"unsafe executable allowlist entry: {item}") from exc
            absolute = identity["path"]
            key = os.path.normcase(Path(item).name)
            if key in resolved and os.path.normcase(resolved[key]) != os.path.normcase(absolute):
                raise ValueError(f"ambiguous executable allowlist entry: {item}")
            resolved[key] = absolute
            identities[key] = identity
            normalized_names.append(Path(item).name)
        if not resolved:
            raise ValueError("no allowlisted executable could be resolved at broker startup")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "allowed_executables", tuple(dict.fromkeys(normalized_names)))
        object.__setattr__(self, "resolved_executables", resolved)
        object.__setattr__(self, "resolved_executable_identities", identities)


@dataclass
class _ActiveRequest:
    """Mutable broker-side state for one cancellable command request."""

    request_id: Any
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[bytes] | None = None
    finished: bool = False


MAX_TIMEOUT_SECONDS = 3600.0
# JSON-lines is an interactive protocol: a peer may keep stdin open while
# waiting for a response.  Keep both the raw frame and protocol diagnostics
# bounded independently of the peer's eventual EOF.
MAX_FRAME_BYTES = 1 * 1024 * 1024
MAX_ERROR_TEXT = 8 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# MCP tool calls run in daemon workers so cancellation notifications can be
# consumed while a command is running.  The admission limit is deliberately
# per stdio connection: separate broker processes/connections do not share a
# scheduler or bypass this bound within one connection.
DEFAULT_MAX_MCP_WORKERS = 8
MAX_MCP_WORKERS = 256
MCP_OVERLOAD_ERROR_CODE = -32004
MAX_CANCEL_REQUEST_ID_BYTES = 256
MAX_CANCEL_TOMBSTONES = 4096
MAX_CANCEL_TOMBSTONE_BYTES = 1 * 1024 * 1024
CANCEL_TOMBSTONE_TTL_SECONDS = 300.0
# Workspace write accounting is persisted in a small broker-owned ledger.  The
# entry bound is independent of the byte quota so zero-byte writes cannot grow
# the metadata without limit.
MAX_WORKSPACE_QUOTA_LEDGER_ENTRIES = 4096
MAX_WORKSPACE_QUOTA_LEDGER_BYTES = 1 * 1024 * 1024
WORKSPACE_QUOTA_LOCK_NAME = ".fable-workspace-quota.lock"
WORKSPACE_QUOTA_LEDGER_NAME = ".fable-workspace-quota.json"
# Public alias matching the engine's transport quota naming.
MAX_RPC_RESPONSE_BYTES = MAX_RESPONSE_BYTES
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26")
SERVER_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

# Stable top-level fields in the side-effect-free probe response.  This is the
# host-facing broker contract: consumers may rely on these fields, while any
# addition or removal must be deliberate and update the documentation checks.
BROKER_PROBE_FIELDS = (
    "host", "capabilities", "available_executables", "executable_identities",
    "execution_binding", "writes_enabled", "read_locked_interpreters",
    "workspace", "workspace_identity",
)


def _identity_from_fd(fd: int, path: str | Path, *, digest: bool = True) -> dict[str, Any]:
    """Measure the object represented by an already-open descriptor."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise PermissionError("executable must be a regular, non-hardlinked file")
    result: dict[str, Any] = {
        "path": str(Path(path).absolute()),
        "device": int(getattr(st, "st_dev", 0)),
        "inode": int(getattr(st, "st_ino", 0)),
        "size": int(st.st_size), "mode": stat.S_IMODE(st.st_mode),
    }
    if digest:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        h = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
        os.lseek(fd, position, os.SEEK_SET)
        result["sha256"] = h.hexdigest()
    return result


def _measure_executable_path(path: str | Path) -> dict[str, Any]:
    """Classify and hash an allowlist entry without following links."""
    target = Path(path)
    # A regular leaf under a linked directory is just as much a pathname
    # indirection as a symlink leaf. Walk the existing components first.
    cur = target
    components: list[Path] = []
    while True:
        components.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for component in reversed(components):
        cst = component.lstat()
        attrs = int(getattr(cst, "st_file_attributes", 0))
        if stat.S_ISLNK(cst.st_mode) or attrs & 0x400:
            raise PermissionError("executable path contains a link or reparse point")
    st = target.lstat()
    attrs = int(getattr(st, "st_file_attributes", 0))
    if stat.S_ISLNK(st.st_mode) or attrs & 0x400 or not stat.S_ISREG(st.st_mode):
        raise PermissionError("executable allowlist entry is a link, reparse point, or non-regular file")
    if st.st_nlink != 1:
        raise PermissionError("executable allowlist entry is hardlinked")
    if os.name == "posix" and not (st.st_mode & 0o111):
        raise PermissionError("executable allowlist entry is not executable")
    fd = os.open(str(target), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        measured = _identity_from_fd(fd, target)
    finally:
        os.close(fd)
    # The descriptor, not a later pathname lookup, determines startup identity.
    measured["path"] = str(target.absolute()) if target.is_absolute() else str(target.resolve())
    measured["classification"] = "regular-executable"
    return measured


def _file_identity(path: str | Path) -> dict[str, Any]:
    """Return measured identity; fail closed if the pathname is unsafe."""
    target = Path(path)
    fd = os.open(str(target), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return _identity_from_fd(fd, target)
    finally:
        os.close(fd)


def _workspace_identity(path: Path, fd: int | None = None) -> dict[str, Any]:
    """Derive workspace identity from the pinned descriptor when available."""
    if fd is not None:
        st = os.fstat(fd)
    else:
        st = path.stat()
    if not stat.S_ISDIR(st.st_mode):
        raise PermissionError("workspace identity is not a directory")
    return {"path": str(path), "device": int(getattr(st, "st_dev", 0)),
            "inode": int(getattr(st, "st_ino", 0))}


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
        # Request IDs are scoped to this broker connection.  Entries are
        # removed when execution finishes so a later request cannot inherit a
        # stale cancellation signal.
        self._active_requests: dict[str, _ActiveRequest] = {}
        # A cancellation notification can overtake a worker thread before it
        # enters execute_command. Tombstones close that registration race;
        # request IDs are single-use for the lifetime of this connection.
        self._cancelled_request_keys: dict[str, float] = {}
        self._cancelled_request_bytes = 0
        self._active_requests_lock = threading.Lock()
        self._workspace_quota_thread_lock = threading.Lock()
        self._workspace_written_bytes = 0
        self._file_written_bytes: dict[str, int] = {}
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

    @staticmethod
    def _request_key(request_id: Any) -> str:
        """Canonicalize a JSON-RPC/action request ID for registry lookup."""
        if isinstance(request_id, bool) or request_id is None:
            raise ValueError("request_id must be a string or number")
        if not isinstance(request_id, (str, int, float)):
            raise ValueError("request_id must be a string or number")
        # Empty strings are valid JSON-RPC string IDs (adapters generate
        # non-empty UUIDs by default).
        if isinstance(request_id, float) and not math.isfinite(request_id):
            raise ValueError("request_id must be a finite number")
        key = json.dumps(request_id, sort_keys=True, separators=(",", ":"))
        if len(key.encode("utf-8")) > MAX_CANCEL_REQUEST_ID_BYTES:
            raise ValueError("request_id exceeds cancellation ID size limit")
        return key

    def _cleanup_cancel_tombstones_locked(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        expired = [key for key, expiry in self._cancelled_request_keys.items()
                   if expiry <= now]
        for key in expired:
            self._cancelled_request_keys.pop(key, None)
            self._cancelled_request_bytes = max(
                0, self._cancelled_request_bytes - len(key.encode("utf-8")))

    def _add_cancel_tombstone_locked(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._cleanup_cancel_tombstones_locked(now)
        key_bytes = len(key.encode("utf-8"))
        if key in self._cancelled_request_keys:
            self._cancelled_request_keys[key] = now + CANCEL_TOMBSTONE_TTL_SECONDS
            return True
        # Evict oldest-expiring tombstones until both independent bounds hold.
        while (len(self._cancelled_request_keys) >= MAX_CANCEL_TOMBSTONES or
               self._cancelled_request_bytes + key_bytes > MAX_CANCEL_TOMBSTONE_BYTES):
            if not self._cancelled_request_keys:
                return False
            victim = min(self._cancelled_request_keys,
                         key=lambda item: self._cancelled_request_keys[item])
            self._cancelled_request_keys.pop(victim, None)
            self._cancelled_request_bytes = max(
                0, self._cancelled_request_bytes - len(victim.encode("utf-8")))
        self._cancelled_request_keys[key] = now + CANCEL_TOMBSTONE_TTL_SECONDS
        self._cancelled_request_bytes += key_bytes
        return True

    def _register_request(self, request_id: Any) -> _ActiveRequest | None:
        if request_id is None:
            return None
        key = self._request_key(request_id)
        active = _ActiveRequest(request_id=request_id)
        with self._active_requests_lock:
            self._cleanup_cancel_tombstones_locked()
            if key in self._active_requests:
                raise ValueError(f"request_id is already active: {request_id}")
            if key in self._cancelled_request_keys:
                active.cancel_event.set()
            self._active_requests[key] = active
        return active

    def _unregister_request(self, active: _ActiveRequest | None) -> None:
        if active is None:
            return
        key = self._request_key(active.request_id)
        with self._active_requests_lock:
            if self._active_requests.get(key) is active:
                del self._active_requests[key]
            if key in self._cancelled_request_keys:
                self._cancelled_request_keys.pop(key, None)
                self._cancelled_request_bytes = max(
                    0, self._cancelled_request_bytes - len(key.encode("utf-8")))
            self._cleanup_cancel_tombstones_locked()

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        """Terminate one registered process without raising a cancellation error."""
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass

    def _cancel_request(self, request_id: Any) -> dict[str, Any]:
        key = self._request_key(request_id)
        with self._active_requests_lock:
            self._cleanup_cancel_tombstones_locked()
            active = self._active_requests.get(key)
            if active is None or active.finished:
                # Keep a bounded, expiring tombstone so an in-flight worker
                # that has not registered yet cannot start after cancellation.
                if active is None:
                    self._add_cancel_tombstone_locked(key)
                return {"request_id": request_id, "cancelled": False}
            # Set the event before taking the process snapshot.  If the
            # execution thread is between registration and Popen, it checks
            # this event immediately after publishing its process handle.
            active.cancel_event.set()
            process = active.process
        if process is not None:
            self._terminate_process(process)
        return {"request_id": request_id, "cancelled": True}

    def probe(self) -> dict[str, Any]:
        available = list(self.policy.resolved_executables)
        capabilities = ["probe_capabilities"]
        if os.name != "nt":
            capabilities += ["execute_command", "inspect_files", "write_file"]
        return {
            "host": "fable-execution-broker",
            "capabilities": capabilities,
            "available_executables": available,
            "executable_identities": {key: dict(value) for key, value in
                                      self.policy.resolved_executable_identities.items()},
            "execution_binding": ("posix-open-descriptor" if os.name == "posix"
                                   else "unavailable-on-windows"),
            "writes_enabled": self._writes_unlocked,
            "read_locked_interpreters": sorted(self.READ_LOCKED_INTERPRETERS),
            "workspace": str(self.policy.workspace),
            "workspace_identity": _workspace_identity(self.policy.workspace, self._workspace_fd),
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
        if os.name == "nt":
            raise PermissionError("safe handle-relative file inspection is unavailable on Windows")
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

    @contextmanager
    def _workspace_quota_guard(self):
        """Lock aggregate write accounting across broker processes where possible."""
        with self._workspace_quota_thread_lock:
            if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
                if self._workspace_fd is None:
                    raise PermissionError("descriptor-relative workspace operations require POSIX")
                # Keep the lock beside the ledger in the already-pinned root;
                # opening an absolute path would reintroduce a workspace swap
                # race between broker startup and accounting.
                fd = os.open(WORKSPACE_QUOTA_LOCK_NAME,
                             os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                             dir_fd=self._workspace_fd)
                try:
                    import fcntl as _fcntl
                    _fcntl.flock(fd, _fcntl.LOCK_EX)
                    yield
                finally:
                    try:
                        _fcntl.flock(fd, _fcntl.LOCK_UN)
                    finally:
                        os.close(fd)
            else:
                # No portable stdlib handle lock exists on every Windows
                # version; the process/thread lock is intentionally best effort.
                yield

    def _workspace_usage_bytes(self) -> int:
        total = 0
        stack = [self.policy.workspace]
        while stack:
            directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise PermissionError("workspace quota cannot be measured safely") from exc
            for entry in entries:
                if (directory == self.policy.workspace and
                        entry.name in {WORKSPACE_QUOTA_LOCK_NAME, WORKSPACE_QUOTA_LEDGER_NAME}):
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise PermissionError("workspace quota cannot be measured safely") from exc
                if stat.S_ISLNK(st.st_mode) or int(getattr(st, "st_file_attributes", 0)) & 0x400:
                    raise PermissionError("workspace contains an unsafe link")
                if stat.S_ISDIR(st.st_mode):
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(st.st_mode):
                    total += int(st.st_size)
                else:
                    raise PermissionError("workspace contains an unsafe special file")
        return total

    def _read_workspace_quota_ledger(self) -> dict[str, Any]:
        """Read the bounded, broker-owned attempted-write accounting ledger."""
        if self._workspace_fd is None:
            raise PermissionError("descriptor-relative workspace operations require POSIX")
        try:
            fd = os.open(WORKSPACE_QUOTA_LEDGER_NAME, _no_follow_flags(),
                         dir_fd=self._workspace_fd)
        except FileNotFoundError:
            return {"version": 1, "attempted_bytes": 0, "files": {}}
        except OSError as exc:
            raise PermissionError("workspace quota ledger cannot be opened safely") from exc
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                    st.st_size > MAX_WORKSPACE_QUOTA_LEDGER_BYTES):
                raise PermissionError("workspace quota ledger is unsafe or oversized")
            raw = os.read(fd, MAX_WORKSPACE_QUOTA_LEDGER_BYTES + 1)
        finally:
            os.close(fd)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
            raise PermissionError("workspace quota ledger is invalid") from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise PermissionError("workspace quota ledger has an unsupported version")
        attempted = value.get("attempted_bytes")
        files = value.get("files")
        if (isinstance(attempted, bool) or not isinstance(attempted, int) or attempted < 0
                or not isinstance(files, dict) or len(files) > MAX_WORKSPACE_QUOTA_LEDGER_ENTRIES):
            raise PermissionError("workspace quota ledger has invalid accounting")
        checked: dict[str, int] = {}
        for key, amount in files.items():
            if (not isinstance(key, str) or not key or
                    isinstance(amount, bool) or not isinstance(amount, int) or amount < 0):
                raise PermissionError("workspace quota ledger has invalid accounting")
            checked[key] = amount
        if sum(checked.values()) != attempted:
            raise PermissionError("workspace quota ledger accounting is inconsistent")
        return {"version": 1, "attempted_bytes": attempted, "files": checked}

    def _persist_workspace_quota_ledger(self, ledger: dict[str, Any]) -> None:
        """Atomically persist accounting while the workspace quota lock is held."""
        if self._workspace_fd is None:
            raise PermissionError("descriptor-relative workspace operations require POSIX")
        raw = json.dumps(ledger, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        if len(raw) > MAX_WORKSPACE_QUOTA_LEDGER_BYTES:
            raise PermissionError("workspace quota ledger is oversized")
        if not hasattr(os, "O_NOFOLLOW"):
            raise PermissionError("safe quota ledger persistence is unavailable")
        temporary_name = f".fable-quota-{os.getpid()}-{threading.get_ident()}-{os.urandom(8).hex()}"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(temporary_name,
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=self._workspace_fd)
            view = memoryview(raw)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(temporary_name, WORKSPACE_QUOTA_LEDGER_NAME,
                       src_dir_fd=self._workspace_fd, dst_dir_fd=self._workspace_fd)
            try:
                os.fsync(self._workspace_fd)
            except OSError:
                # The ledger replacement is still atomic; some filesystems do
                # not permit fsync on directory descriptors.
                pass
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temporary_name, dir_fd=self._workspace_fd)
            except (FileNotFoundError, OSError):
                pass

    def _check_write_quota(self, relative_path: str, content_bytes: int) -> tuple[str, dict[str, Any]]:
        if content_bytes > self.policy.max_file_write_bytes:
            raise PermissionError("per-file workspace write quota exceeded")
        parts = _path_parts(relative_path)
        if len(parts) == 1 and parts[0] in {WORKSPACE_QUOTA_LOCK_NAME, WORKSPACE_QUOTA_LEDGER_NAME}:
            raise PermissionError("workspace quota metadata is broker-owned")
        # Charge attempted writes, not just final file size.  The ledger is
        # shared by broker instances and survives their lifetimes, so repeated
        # replacement of one small file cannot provide an unbounded stream.
        key = "/".join(parts)
        ledger = self._read_workspace_quota_ledger()
        files = ledger["files"]
        previous_file_bytes = files.get(key, 0)
        if (previous_file_bytes + content_bytes > self.policy.max_file_write_bytes):
            raise PermissionError("per-file aggregate write quota exceeded")
        if (ledger["attempted_bytes"] + content_bytes
                > self.policy.max_workspace_write_bytes):
            raise PermissionError("aggregate workspace write quota exceeded")
        if key not in files and len(files) >= MAX_WORKSPACE_QUOTA_LEDGER_ENTRIES:
            raise PermissionError("workspace quota ledger entry limit exceeded")
        # Validate the current target before mutation.  This also prevents an
        # atomic replacement from silently converting a hardlink/special node.
        target = self._safe_path(relative_path)
        old_size = 0
        try:
            st = target.lstat()
        except FileNotFoundError:
            st = None
        if st is not None:
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                    int(getattr(st, "st_file_attributes", 0)) & 0x400):
                raise PermissionError("write target must be a private regular file")
            old_size = int(st.st_size)
        # Include the resulting workspace footprint so separate broker
        # instances/processes cannot bypass the aggregate limit by each using
        # a fresh in-memory counter.
        if (self._workspace_usage_bytes() - old_size + content_bytes
                > self.policy.max_workspace_write_bytes):
            raise PermissionError("aggregate workspace footprint quota exceeded")
        return key, ledger

    def write_file(self, relative_path: str, content: str) -> dict[str, Any]:
        if os.name == "nt":
            raise PermissionError("safe handle-relative workspace writes are unavailable on Windows")
        self._authorize_write()
        if not isinstance(content, str):
            raise ValueError("file content must be text")
        content_bytes = len(content.encode("utf-8"))
        with self._workspace_quota_guard():
            key, ledger = self._check_write_quota(relative_path, content_bytes)
            ledger["attempted_bytes"] += content_bytes
            ledger["files"][key] = ledger["files"].get(key, 0) + content_bytes
            # Reserve before publication.  A failed publication remains
            # charged because this quota measures attempted writes.
            self._persist_workspace_quota_ledger(ledger)
            self._workspace_written_bytes = ledger["attempted_bytes"]
            self._file_written_bytes = dict(ledger["files"])
            return self._write_file_unlocked(relative_path, content)

    def _write_file_unlocked(self, relative_path: str, content: str) -> dict[str, Any]:
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

    def check_kripke_pre_execution_invariants(self, command: Iterable[str]) -> dict[str, Any]:
        """Verify modal safety invariants AG(safe_execution) prior to running a command."""
        kripke = KripkeStructure()
        kripke.add_world("w_pre", propositions={"ready", "safe_execution", "workspace_isolated"})
        kripke.add_world("w_exec", propositions={"running", "safe_execution", "workspace_isolated"})
        kripke.add_world("w_post", propositions={"completed", "safe_execution", "workspace_isolated"})
        kripke.add_transition("w_pre", "w_exec")
        kripke.add_transition("w_exec", "w_post")
        kripke.add_transition("w_post", "w_post")
        checker = KripkeModelChecker(kripke)
        res = checker.check("AG(safe_execution)", "w_pre")
        return {
            "formula": "AG(safe_execution)",
            "is_satisfied": res.is_satisfied,
            "satisfying_worlds": sorted(list(res.satisfied_worlds)),
        }

    def validate_causal_boundaries(self, command: Iterable[str], cwd: str | None = None) -> dict[str, Any]:
        """Validate causal isolation boundaries do(Execute(cmd)) prior to running."""
        cmd_list = list(command)
        exe_name = Path(cmd_list[0]).name if cmd_list else "unknown"
        dag = CausalDAG(name=f"CausalBroker_{exe_name}")
        dag.add_node(node_id="node_workspace", name="WorkspaceIsolation", node_type=CausalNodeType.EXOGENOUS, value=1.0)
        dag.add_node(node_id="node_intervention", name=f"do(Execute({exe_name}))", node_type=CausalNodeType.INTERVENTION, value=1.0)
        dag.add_node(node_id="node_output", name="SafeOutput", node_type=CausalNodeType.METRIC, value=0.99)
        dag.add_edge("node_workspace", "node_intervention", weight=1.0)
        dag.add_edge("node_intervention", "node_output", weight=0.99)
        report = dag.evaluate_brittleness(target_metric="node_output")
        return {
            "is_valid": report.overall_brittleness_score < 0.8,
            "brittleness_score": report.overall_brittleness_score,
            "dag": dag.to_dict(),
        }

    def _classify_script(self, executable_path: str) -> tuple[str, dict[str, Any] | None]:
        """Classify an executable and bind a script shebang to an allowlist identity."""
        try:
            descriptor_alias = executable_path.startswith(("/proc/self/fd/", "/dev/fd/"))
            flags = os.O_RDONLY if descriptor_alias else os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(executable_path, flags)
            try:
                header = os.read(fd, 4096)
            finally:
                os.close(fd)
        except OSError as exc:
            raise PermissionError("executable cannot be inspected safely") from exc
        if not header.startswith(b"#!"):
            return "regular-executable", None
        try:
            line = header.splitlines()[0][2:].decode("utf-8", "strict").strip()
            words = shlex.split(line, posix=(os.name != "nt"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PermissionError("script has an invalid shebang") from exc
        # /usr/bin/env introduces a second mutable PATH lookup.  It is never
        # accepted by the broker's locked execution boundary.
        if not words or Path(words[0]).name.lower() == "env":
            raise PermissionError("script shebang interpreter is unpinned")
        if len(words) != 1:
            raise PermissionError("script shebang interpreter arguments are not pinned")
        interpreter = Path(words[0])
        if not interpreter.is_absolute():
            resolved = Path(shutil.which(str(interpreter)) or "")
            if not resolved:
                raise PermissionError("script shebang interpreter is unavailable")
            interpreter = resolved
        try:
            identity = _measure_executable_path(interpreter)
        except (OSError, ValueError, PermissionError) as exc:
            raise PermissionError("script shebang interpreter is unsafe") from exc
        expected = None
        for allowed in self.policy.resolved_executable_identities.values():
            if all(identity.get(key) == allowed.get(key)
                   for key in ("device", "inode", "size", "mode", "sha256")):
                expected = dict(allowed)
                break
        if expected is None:
            raise PermissionError("script shebang interpreter is not allowlisted")
        return "script", expected

    def execute_command(
        self,
        command: Iterable[str],
        cwd: str | None = None,
        timeout_seconds: float = 120.0,
        session_id: str = "broker-session",
        request_id: Any = None,
    ) -> dict[str, Any]:
        """Execute a command and optionally register it for cancellation."""
        active = self._register_request(request_id)
        try:
            return self._execute_command(
                command, cwd=cwd, timeout_seconds=timeout_seconds,
                session_id=session_id, active=active,
            )
        finally:
            self._unregister_request(active)

    def _execute_command(
        self,
        command: Iterable[str],
        cwd: str | None = None,
        timeout_seconds: float = 120.0,
        session_id: str = "broker-session",
        active: _ActiveRequest | None = None,
    ) -> dict[str, Any]:
        argv = tuple(command)
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ValueError("command must be a non-empty sequence of strings")
        # System 3 Pre-Execution Invariant Verification
        kripke_check = self.check_kripke_pre_execution_invariants(argv)
        if not kripke_check["is_satisfied"]:
            raise PermissionError("System 3 Kripke modal safety invariant AG(safe_execution) violated")
        causal_check = self.validate_causal_boundaries(argv, cwd)
        if not causal_check["is_valid"]:
            raise PermissionError("System 3 Causal boundary check failed")

        requested_executable = Path(argv[0])
        executable = requested_executable.name
        executable_key = Path(executable).stem.lower()
        is_interpreter = (
            executable_key in self.READ_LOCKED_INTERPRETERS
            or executable_key.startswith("python")
        )
        registered_path = self.policy.resolved_executables.get(os.path.normcase(executable))
        registered_identity = self.policy.resolved_executable_identities.get(os.path.normcase(executable))
        if not registered_path or not registered_identity:
            raise PermissionError(f"executable is not allowlisted: {executable}")
        # Compare the requested spelling without resolving it through an
        # attacker-controlled link. Relative requests are resolved only by
        # PATH and then checked against the startup-pinned path.
        requested_path = requested_executable if requested_executable.is_absolute() else Path(
            shutil.which(str(requested_executable)) or ""
        )
        if not requested_path or not requested_path.exists():
            raise PermissionError(f"executable cannot be resolved: {argv[0]}")
        if os.path.normcase(str(requested_path.resolve())) != os.path.normcase(registered_path):
            raise PermissionError("executable path does not match its startup registration")
        script_classification, shebang_identity = self._classify_script(registered_path)
        if script_classification == "script" and not self._writes_unlocked:
            # A script is executable code too; only a shebang measured against
            # the broker's startup allowlist may cross the locked boundary.
            raise PermissionError("scripts are blocked while workspace writes are locked")
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
        # Keep only execution essentials. Windows child processes need
        # SystemRoot/PATHEXT and temp roots; do not pass arbitrary user
        # credentials or configuration variables through the broker.
        env: dict[str, str] = {
            key: os.environ[key]
            for key in ("PATH", "PATHEXT")
            if os.environ.get(key)
        }
        if os.name == "nt":
            for win_key in (
                "SYSTEMROOT", "SystemRoot", "WINDIR", "windir",
                "TEMP", "TMP", "temp", "tmp", "SYSTEMDRIVE", "COMSPEC", "ComSpec",
            ):
                val = os.environ.get(win_key)
                if val:
                    env[win_key] = val
                    env[win_key.upper()] = val
        else:
            for posix_key in ("TEMP", "TMP", "TMPDIR"):
                val = os.environ.get(posix_key)
                if val:
                    env[posix_key] = val
        env["PYTHONUNBUFFERED"] = "1"
        # A pathname hash followed by Popen(pathname) is a classic TOCTOU.
        # POSIX can bind execution to the measured descriptor via procfs.  The
        # stdlib has no equivalent Windows handle-relative CreateProcess API;
        # rather than make a false attestation, refuse command execution there.
        exec_fd: int | None = None
        interpreter_fd: int | None = None
        spawn_argv = (registered_path, *argv[1:])
        if os.name == "posix":
            if not hasattr(os, "O_NOFOLLOW"):
                raise PermissionError("safe descriptor-pinned execution is unavailable")
            try:
                exec_fd = os.open(registered_path, os.O_RDONLY | os.O_NOFOLLOW)
                executable_identity = _identity_from_fd(exec_fd, registered_path)
                expected_identity = {k: registered_identity.get(k) for k in
                                     ("device", "inode", "size", "mode", "sha256")}
                actual_identity = {k: executable_identity.get(k) for k in expected_identity}
                if actual_identity != expected_identity:
                    raise PermissionError("allowlisted executable changed since broker startup")
                fd_root = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
                descriptor_path = f"{fd_root}/{exec_fd}"
                if not os.path.exists(descriptor_path):
                    raise PermissionError("descriptor-pinned execution path is unavailable")
                if script_classification == "script":
                    # Re-read the shebang from the same descriptor that will
                    # be executed, closing replacement between initial discovery
                    # and process creation.  A pathname shebang still causes
                    # the kernel to look up its interpreter by name, so execute
                    # the pinned interpreter descriptor explicitly instead.
                    _kind, revalidated_shebang = self._classify_script(descriptor_path)
                    if revalidated_shebang != shebang_identity:
                        raise PermissionError("script interpreter changed before execution")
                    interpreter_path = shebang_identity.get("path") if shebang_identity else None
                    if not isinstance(interpreter_path, str) or not interpreter_path:
                        raise PermissionError("script interpreter cannot be pinned")
                    interpreter_fd = os.open(interpreter_path, os.O_RDONLY | os.O_NOFOLLOW)
                    interpreter_identity = _identity_from_fd(interpreter_fd, interpreter_path)
                    interpreter_expected = {k: shebang_identity.get(k) for k in
                                            ("device", "inode", "size", "mode", "sha256")}
                    interpreter_actual = {k: interpreter_identity.get(k) for k in interpreter_expected}
                    if interpreter_actual != interpreter_expected:
                        raise PermissionError("script interpreter changed before execution")
                    # Recursively interpreted scripts would reintroduce a
                    # pathname shebang lookup.  Reject them rather than claim
                    # descriptor pinning we cannot provide for an arbitrary
                    # interpreter chain.
                    interpreter_header = os.read(interpreter_fd, 4096)
                    if interpreter_header.startswith(b"#!"):
                        raise PermissionError("script interpreter cannot be pinned safely")
                    interpreter_descriptor = f"{fd_root}/{interpreter_fd}"
                    if not os.path.exists(interpreter_descriptor):
                        raise PermissionError("descriptor-pinned interpreter path is unavailable")
                    spawn_argv = (interpreter_descriptor, descriptor_path, *argv[1:])
                else:
                    spawn_argv = (descriptor_path, *argv[1:])
            except Exception:
                if interpreter_fd is not None:
                    try:
                        os.close(interpreter_fd)
                    except OSError:
                        pass
                    interpreter_fd = None
                if exec_fd is not None:
                    try:
                        os.close(exec_fd)
                    except OSError:
                        pass
                    exec_fd = None
                raise
        else:
            raise PermissionError("descriptor-pinned command execution is unavailable on Windows")
        process: subprocess.Popen[bytes] | None = None
        output_limit = self.policy.max_output_bytes
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        output_limited = threading.Event()
        capture_lock = threading.Lock()
        captured_total = [0]
        kill_lock = threading.Lock()

        def stop_process() -> None:
            if process is None:
                return
            with kill_lock:
                self._terminate_process(process)

        def drain(name: str, stream: Any) -> None:
            bucket = captured[name]
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                with capture_lock:
                    remaining = output_limit - captured_total[0]
                    take = max(0, min(len(chunk), remaining))
                    if take:
                        bucket.extend(chunk[:take])
                        captured_total[0] += take
                    exceeded = take < len(chunk) or remaining <= 0
                if exceeded:
                    output_limited.set()
                    stop_process()
                    while stream.read(64 * 1024):
                        pass
                    return

        executed_argv = (registered_path, *argv[1:])
        started_at = utc_now()
        # Both identities are measured from pinned objects. If either cannot be
        # measured, no process is launched and no receipt can be fabricated.
        workspace_identity = _workspace_identity(self.policy.workspace, self._workspace_fd)
        input_hash = canonical_hash({
            "command": list(argv), "cwd": cwd_display,
            "timeout_seconds": timeout_seconds,
        })
        receipt_id = uuid.uuid4().hex
        try:
            process = subprocess.Popen(
                spawn_argv,
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=(os.name == "posix"),
                creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                               if os.name == "nt" else 0),
                pass_fds=tuple(fd for fd in (exec_fd, interpreter_fd)
                                if fd is not None),
            )
            if active is not None:
                # Publish the process while holding the same lock used by
                # cancellation.  The event check closes the registration /
                # Popen race without allowing a cancelled process to escape.
                with self._active_requests_lock:
                    active.process = process
                    cancel_requested = active.cancel_event.is_set()
                if cancel_requested:
                    stop_process()
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
            if active is not None:
                with self._active_requests_lock:
                    active.process = None
                    active.finished = True
        finally:
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            if interpreter_fd is not None:
                try:
                    os.close(interpreter_fd)
                except OSError:
                    pass
            if exec_fd is not None:
                try:
                    os.close(exec_fd)
                except OSError:
                    pass
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

        request_cancelled = active is not None and active.cancel_event.is_set()
        result = {
            "command": list(executed_argv),
            "cwd": cwd_display,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "output_limited": output_limited.is_set(),
            "stdout": truncate(stdout),
            "stderr": truncate(stderr),
            "success": exit_code == 0 and not timed_out and not output_limited.is_set()
                       and not request_cancelled,
        }
        if active is not None:
            result["request_id"] = active.request_id
        finished_at = utc_now()
        cancelled = bool(request_cancelled or timed_out or output_limited.is_set())
        cancellation_status = (
            "cancelled" if request_cancelled else
            "timed_out" if timed_out else
            "output_limit" if output_limited.is_set() else "not_cancelled"
        )
        receipt = BrokerReceipt(
            receipt_id=receipt_id, session_id=str(session_id), action="execute_command",
            capability="execute_command", tool_name=Path(registered_path).name,
            input_hash=input_hash, output_hash=canonical_hash(result),
            executable_identity=executable_identity,
            workspace_identity=workspace_identity, started_at=started_at,
            finished_at=finished_at, success=bool(result["success"]),
            cancelled=cancelled, cancellation_status=cancellation_status,
            timed_out=bool(timed_out), metadata={"argv": list(argv)},
        )
        result["receipt"] = receipt.to_dict()
        # Keep common fields at the top level for simple host adapters.
        result.update({"receipt_id": receipt.receipt_id, "session_id": receipt.session_id,
                       "input_hash": receipt.input_hash, "output_hash": receipt.output_hash,
                       "cancelled": receipt.cancelled,
                       "cancellation_status": receipt.cancellation_status})
        return result

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
                session_id=str(request.get("session_id", "broker-session")),
                request_id=request.get("request_id"),
            )
        if action == "cancel":
            # Cancellation is deliberately a separate control operation.  It
            # never accepts a process handle or token from the model channel;
            # only a currently registered request ID can be cancelled.
            return self._cancel_request(request.get("request_id"))
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


def _valid_rpc_id(value: Any) -> bool:
    """JSON-RPC IDs are strings or finite numbers; booleans are not IDs."""
    return (not isinstance(value, bool) and value is not None
            and isinstance(value, (str, int, float))
            and (not isinstance(value, float) or math.isfinite(value)))


def _rpc_error(msg_id: Any, code: int, message: str,
               data: Mapping[str, Any] | None = None) -> dict[str, Any]:
    # ``ok``/``message`` are harmless extension members and make malformed
    # frames diagnosable to legacy action-protocol callers as well.
    text = _bounded_text(message)
    error: dict[str, Any] = {"code": code, "message": text}
    if data is not None:
        error["data"] = dict(data)
    return {"jsonrpc": "2.0", "id": msg_id, "ok": False, "message": text,
            "error": error}


def _rpc_overload(msg_id: Any, *, active_workers: int,
                  max_workers: int) -> dict[str, Any]:
    """Return a machine-readable, retryable MCP admission failure."""
    return _rpc_error(
        msg_id, MCP_OVERLOAD_ERROR_CODE, "MCP worker capacity exhausted",
        {"type": "overloaded", "reason": "mcp_worker_limit",
         "active_workers": active_workers, "max_workers": max_workers,
         "retryable": True},
    )


@dataclass
class MCPConnectionState:
    """Per-stdio-connection MCP handshake, version, and worker state."""
    initialized: bool = False
    client_ready: bool = False
    negotiated_version: str | None = None
    max_workers: int = DEFAULT_MAX_MCP_WORKERS

    def __post_init__(self) -> None:
        if (isinstance(self.max_workers, bool)
                or not isinstance(self.max_workers, int)
                or not 1 <= self.max_workers <= MAX_MCP_WORKERS):
            raise ValueError(
                f"max_workers must be an integer from 1 to {MAX_MCP_WORKERS}"
            )


def _broker_tools() -> list[dict[str, Any]]:
    actions = ["probe", "probe_capabilities"]
    if os.name != "nt":
        actions += ["inspect_files", "execute_command", "cancel", "write_file"]
    return [{
        "name": action,
        "description": f"Fable execution broker {action} operation.",
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": True},
    } for action in actions]


def _dispatch_jsonrpc(broker: ExecutionBroker, request: dict[str, Any],
                      state: MCPConnectionState | None = None) -> dict[str, Any] | None:
    """Dispatch one MCP request, returning None for notifications.

    ``state`` is deliberately connection-scoped.  Keeping it out of the
    broker object prevents one host connection from inheriting another host's
    handshake or negotiated version.
    """
    state = state or MCPConnectionState()
    has_id = "id" in request
    msg_id = request.get("id")
    is_notification = not has_id
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _rpc_error(msg_id if has_id and _valid_rpc_id(msg_id) else None,
                          -32600, "Invalid Request")
    if has_id and not _valid_rpc_id(msg_id):
        return _rpc_error(None, -32600, "Invalid Request: invalid id")
    if "params" in request and not isinstance(request["params"], dict):
        return None if is_notification else _rpc_error(msg_id, -32600,
                                                         "Invalid Request")
    method = request["method"]
    params = request.get("params", {})

    # MCP notification methods never produce responses, even if a broken peer
    # attaches an ID.  They are accepted only after a successful initialize;
    # in particular, initialized must not be a substitute handshake.
    if method in {"notifications/cancelled", "notifications/initialized"}:
        if not state.initialized:
            return None
        if method == "notifications/cancelled":
            request_id = params.get("requestId")
            if _valid_rpc_id(request_id):
                try:
                    broker.handle({"action": "cancel", "request_id": request_id})
                except (ValueError, PermissionError):
                    pass
        else:
            state.client_ready = True
        return None

    if method == "initialize":
        if not has_id:
            # A notification cannot establish a successful handshake because
            # there is no response that confirms negotiated capabilities.
            return None
        if state.initialized:
            return None if is_notification else _rpc_error(msg_id, -32600,
                                                             "Server already initialized")
        requested = params.get("protocolVersion", SERVER_PROTOCOL_VERSION)
        if not isinstance(requested, str):
            return None if is_notification else _rpc_error(msg_id, -32602,
                                                             "protocolVersion must be a string")
        if requested not in SUPPORTED_PROTOCOL_VERSIONS:
            return None if is_notification else _rpc_error(msg_id, -32602,
                                                             "Unsupported protocol version")
        state.initialized = True
        state.negotiated_version = requested
        result = {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "fable-execution-broker", "version": "2.0"},
        }
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id,
                                               "result": result}

    # All MCP operations other than the handshake are unavailable until the
    # initialize request succeeds.  Notifications remain silent.
    if not state.initialized:
        return None if is_notification else _rpc_error(msg_id, -32002,
                                                         "Server not initialized")
    if method == "ping":
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id,
                                               "result": {}}
    if method == "tools/list":
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id,
                                               "result": {"tools": _broker_tools()}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return None if is_notification else _rpc_error(msg_id, -32602,
                "tools/call requires string name and object arguments")
        if name not in {item["name"] for item in _broker_tools()}:
            return None if is_notification else _rpc_error(msg_id, -32601,
                                                            f"Method not found: {name}")
        action_request = dict(arguments)
        action_request["action"] = name
        # The outer JSON-RPC ID is authoritative.  This closes the old hole
        # where a nested request_id could not be cancelled by the peer.
        if has_id:
            action_request["request_id"] = msg_id
        try:
            result = broker.handle(action_request)
            tool_result = {"content": [{"type": "text",
                "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result, "isError": False}
        except Exception as exc:
            tool_result = {"content": [{"type": "text", "text": _bounded_text(exc)}],
                           "isError": True}
        return None if is_notification else {"jsonrpc": "2.0", "id": msg_id,
                                               "result": tool_result}
    if is_notification:
        return None
    return _rpc_error(msg_id, -32601, f"Method not found: {method}")


def _emit_response(response: dict[str, Any]) -> None:
    """Write one bounded response; never let a huge result escape the pipe."""
    raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        if response.get("jsonrpc") == "2.0":
            response = _rpc_error(response.get("id"), -32003,
                                  "Response exceeds maximum size")
        else:
            response = _protocol_error("ResponseTooLarge", "response exceeds maximum size")
        raw = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()


def serve(broker: ExecutionBroker, admin_fd: int | None = None,
         max_workers: int = DEFAULT_MAX_MCP_WORKERS) -> None:
    """Serve one broker connection with bounded MCP tool-call concurrency.

    ``max_workers`` applies only to this stdio connection.  Calls that arrive
    while all slots are occupied are rejected before starting a thread and
    receive a structured, retryable JSON-RPC overload error.  Finished
    workers remove themselves from the registry; this keeps long-lived
    connections from accumulating thread objects and makes cancellation and
    completion release admission slots promptly.
    """
    state = MCPConnectionState(max_workers=max_workers)
    if admin_fd is not None:
        if os.name == "nt":
            raise ValueError("--admin-fd currently requires a POSIX inherited pipe")
        threading.Thread(target=_serve_admin_fd, args=(broker, admin_fd), daemon=True).start()
    output_lock = threading.Lock()
    workers: dict[object, threading.Thread] = {}
    workers_lock = threading.Lock()

    def dispatch_and_emit(request: dict[str, Any], token: object) -> None:
        try:
            try:
                result = _dispatch_jsonrpc(broker, request, state)
            except Exception:
                result = _rpc_error(
                    request.get("id") if _valid_rpc_id(request.get("id")) else None,
                    -32600, "Invalid Request")
            if result is not None:
                with output_lock:
                    _emit_response(result)
        finally:
            # The worker, rather than the reader loop, performs removal so a
            # completed or cancelled call releases its slot immediately.
            with workers_lock:
                workers.pop(token, None)

    def admit(request: dict[str, Any]) -> bool:
        token = object()
        with workers_lock:
            # Reap any thread that exited before its finally block acquired
            # this lock (normally workers remove themselves immediately).
            for old_token, worker in tuple(workers.items()):
                if not worker.is_alive():
                    workers.pop(old_token, None)
            active = len(workers)
            if active >= state.max_workers:
                # JSON-RPC notifications never receive a response, including
                # on overload. They are dropped rather than bypassing the
                # bound or violating notification semantics.
                response = (_rpc_overload(
                    request.get("id"), active_workers=active,
                    max_workers=state.max_workers) if "id" in request else None)
                admitted = False
            else:
                worker = threading.Thread(
                    target=dispatch_and_emit, args=(request, token), daemon=True)
                # Register before start so a very fast worker cannot be
                # observed as untracked and admission remains atomic.
                workers[token] = worker
                response = None
                admitted = True
        if not admitted:
            if response is not None:
                with output_lock:
                    _emit_response(response)
            return False
        try:
            worker.start()
        except BaseException:
            with workers_lock:
                workers.pop(token, None)
            raise
        return True

    for raw_line, oversized in _bounded_lines(sys.stdin, MAX_FRAME_BYTES):
        if oversized:
            with output_lock:
                _emit_response(_rpc_error(None, -32600, "Invalid Request: frame too large"))
            continue
        if not raw_line.strip():
            continue
        try:
            request = json.loads(raw_line.decode("utf-8", "replace"))
        except (ValueError, json.JSONDecodeError, RecursionError):
            with output_lock:
                _emit_response(_rpc_error(None, -32700, "Parse error"))
            continue
        if not isinstance(request, dict):
            with output_lock:
                _emit_response(_rpc_error(None, -32600, "Invalid Request"))
            continue
        # Every MCP tool call, including a notification, is admitted through
        # the same bound. Notifications have no response by protocol and are
        # simply dropped when overloaded; they must not bypass the limit.
        if request.get("jsonrpc") == "2.0" and request.get("method") == "tools/call":
            try:
                admit(request)
            except Exception:
                # A notification remains response-less even if local worker
                # creation fails; requests get a bounded protocol error.
                if "id" in request:
                    with output_lock:
                        _emit_response(_rpc_error(
                            request.get("id") if _valid_rpc_id(request.get("id")) else None,
                            -32600, "Invalid Request"))
            continue
        try:
            if "jsonrpc" in request or "method" in request:
                # Handshake and control notifications remain synchronous, so
                # initialize/list/cancellation ordering is deterministic.
                dispatch_and_emit(request, object())
            else:
                # Explicit legacy action protocol: no JSON-RPC handshake,
                # no notification semantics, and stable {ok,result} shape.
                try:
                    response = {"ok": True, "result": broker.handle(request)}
                except Exception as exc:
                    response = _protocol_error(type(exc).__name__, exc)
                with output_lock:
                    _emit_response(response)
        except Exception as exc:
            with output_lock:
                _emit_response(_rpc_error(None, -32600, _bounded_text(exc)))
    # EOF does not cancel in-flight calls; give them the same bounded cleanup
    # window as the prior implementation, while avoiding unbounded tracking.
    with workers_lock:
        remaining = tuple(workers.values())
    for worker in remaining:
        worker.join(timeout=MAX_TIMEOUT_SECONDS + 5)

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
    parser.add_argument(
        "--max-mcp-workers", "--max-workers", dest="max_mcp_workers",
        type=int, default=DEFAULT_MAX_MCP_WORKERS,
        help=f"maximum concurrent MCP tool calls for this connection (1-{MAX_MCP_WORKERS})",
    )
    args = parser.parse_args(argv)
    allowed = tuple(args.allow_executable) or BrokerPolicy.allowed_executables
    policy = BrokerPolicy(
        workspace=args.workspace,
        allowed_executables=allowed,
        write_token_digest=_load_write_token_digest(),
    )
    serve(ExecutionBroker(policy), admin_fd=args.admin_fd,
          max_workers=args.max_mcp_workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
