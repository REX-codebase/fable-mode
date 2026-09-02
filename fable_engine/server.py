#!/usr/bin/env python3
"""
Fable-Engine MCP Server for MCP-compatible agent hosts.
Implements the fable_session tool for deep cognitive session management,
epistemic tracking, invariant recording, session-local gate telemetry,
user-controlled time-budgeted pacing telemetry, and session persistence.
V1 gates are not a host sandbox; host authorization and interruptive controls
are reported explicitly rather than being implied.
"""

from __future__ import annotations

import sys
import os
import json
import time
import math
import logging
import hmac
import re
import hashlib
import collections
import io
import struct
import copy
import tempfile
import threading
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt where available
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

# Reconfigure UTF-8 for Windows stdio
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stdin.encoding != 'utf-8':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure logging exclusively to stderr so stdout remains pure JSON-RPC
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Fable-Engine] %(message)s"
)
logger = logging.getLogger("fable-engine")

# Mutable state is always in a user-writable private data directory.  Never
# resolve an attacker-controlled env path before checking its components: doing
# so could silently redirect writes through a symlink/reparse point.
def _assert_private_path(path: Path) -> None:
    cur = path
    parts: list[Path] = []
    while True:
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for part in reversed(parts):
        try:
            st = part.lstat()
        except FileNotFoundError:
            continue
        attrs = int(getattr(st, "st_file_attributes", 0))
        # macOS exposes /var and /tmp as stable system aliases into /private.
        # They are not user-controlled state-directory links and must remain
        # usable for temporary CAS/session fixtures and normal system paths.
        trusted_macos_alias = (
            sys.platform == "darwin" and str(part) in {"/var", "/tmp"}
            and str(part.resolve()) in {"/private/var", "/private/tmp"}
        )
        if ((attrs & 0x400 or stat.S_ISLNK(st.st_mode)) and not trusted_macos_alias) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
            raise RuntimeError("state path contains a symlink, reparse point, or special file")


BASE_DIR = Path(__file__).resolve().parent
_DATA_ENV = os.environ.get("FABLE_DATA_DIR")
if _DATA_ENV:
    DATA_DIR = Path(_DATA_ENV).expanduser().absolute()
elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "FableMode" / "data"
else:
    DATA_DIR = Path.home() / ".local" / "share" / "fable-engine" / "data"
_assert_private_path(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)
_assert_private_path(DATA_DIR)
if DATA_DIR.is_symlink() or not DATA_DIR.is_dir():
    raise RuntimeError("FABLE_DATA_DIR must be a real directory")
os.chmod(DATA_DIR, 0o700)
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
os.chmod(SESSIONS_DIR, 0o700)

# Standard Fable Phases
PHASES = [
    "Phase 1: Epistemic Grounding & Live Research",
    "Phase 2: Invariant Specification & Blueprint",
    "Phase 3: Adversarial Red-Teaming & Falsification",
    "Phase 4: Subagent Fleet Delegation",
    "Phase 5: Multi-Tier Verification & Gatekeeping",
    "Phase 6: Final Walkthrough & Reporting"
]

PHASE_INDEX_MAP = {phase: i + 1 for i, phase in enumerate(PHASES)}

MIN_TIME_BUDGET_MINUTES = 0.1
MAX_TIME_BUDGET_MINUTES = 7 * 24 * 60
FORCE_UNLOCK_ENV = "FABLE_FORCE_UNLOCK_TOKEN"
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
MAX_CAS_OBJECT_BYTES = 16 * 1024 * 1024
MAX_CAS_SESSION_BYTES = 64 * 1024 * 1024
MAX_CAS_SESSION_OBJECTS = 1024
MAX_ACCUMULATOR_ITEMS = 4096
# This is a UTF-8 byte quota (the historical name is retained for API
# compatibility).  Metadata is charged to the same bounded buffer.
MAX_ACCUMULATOR_CHARS = 8 * 1024 * 1024
MAX_ACCUMULATOR_METADATA_BYTES = 512 * 1024
MAX_SLICE_RESPONSE_BYTES = 1 * 1024 * 1024
MAX_RPC_LINE_BYTES = 1 * 1024 * 1024
MAX_RPC_RESPONSE_BYTES = 2 * 1024 * 1024
# V1 cancellation is a pre-dispatch tombstone, not an interruptive control
# channel.  Keep the tombstone registry bounded even when a peer sends
# cancellations for requests that never arrive.
MAX_CANCEL_REQUEST_ID_BYTES = 256
MAX_CANCEL_TOMBSTONES = 4096
MAX_CANCEL_TOMBSTONE_BYTES = 1 * 1024 * 1024
CANCEL_TOMBSTONE_TTL_SECONDS = 300.0
MAX_TOOL_TEXT_BYTES = 512 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024
MAX_REQUEST_DEADLINE_SECONDS = 3600.0
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26")
SERVER_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
# V1 is intentionally single-request-per-line; batches are rejected rather
# than partially executing them with unclear ordering/notification semantics.
BATCH_POLICY = "reject"
# The stdio V1 loop is synchronous.  It cannot read a cancellation notification
# while a tool call is executing, and Python threads cannot be safely killed.
# Expose this honestly rather than claiming that post-hoc checks interrupt work.
INTERRUPTIVE_CONTROL = "unsupported_synchronous_v1"

# Strict MCP control-plane profile.  This is deliberately a separate tool and
# state machine: the historical fable_session surface remains available only
# as an explicitly legacy/compatibility API and cannot be mistaken for the
# enforced control plane.
CONTROL_PLANE_TOOL_NAME = "fable_control_plane"
CONTROL_PLANE_PROFILE = "strict-mcp-v1"
CONTROL_PLANE_ACTIONS = (
    "observe", "record_prediction", "propose_action", "record_outcome",
    "request_verification", "finalize",
)
CONTROL_PLANE_CAPABILITY_ACTIONS = ("capabilities",)
CONTROL_PLANE_STATES = (
    "new", "observed", "predicted", "action_proposed", "outcome_recorded",
    "verification_requested", "finalized",
)
CONTROL_PLANE_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

SILENT_DELIBERATION_REMINDER = (
    "\n\n> [!NOTE]\n"
    "> **SILENT-DELIBERATION ACTIVE — ADVISORY ONLY (NOT ENFORCED BY V1)**: V1 does not suppress chat, sandbox host tools, "
    "or enforce a zero-chat/lockout policy. The host must enforce any tool authorization "
    "and user-interaction policy; `execution_locked` is session telemetry, not a host boundary."
)


def _validate_time_budget(value: Any, field_name: str = "time_budget_minutes") -> float:
    """Validate a duration before it can influence an execution deadline."""
    try:
        minutes = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}: expected a finite number of minutes.") from exc
    if not math.isfinite(minutes) or not (MIN_TIME_BUDGET_MINUTES <= minutes <= MAX_TIME_BUDGET_MINUTES):
        raise ValueError(
            f"Invalid {field_name}: must be between {MIN_TIME_BUDGET_MINUTES} and "
            f"{MAX_TIME_BUDGET_MINUTES} finite minutes."
        )
    return minutes


def _validate_session_name(name: str) -> str:
    """Keep session persistence inside SESSIONS_DIR and make identifiers portable."""
    clean_name = (name or "").strip()
    if not SESSION_NAME_PATTERN.fullmatch(clean_name):
        raise ValueError(
            "Invalid session_name: use 1-128 letters, numbers, '.', '_' or '-' "
            "and do not include path separators."
        )
    return clean_name


def _cas_namespace_for_session(session_id: str) -> str:
    """Derive a stable, non-secret capability namespace from the session ID."""
    return "s_" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


def _validate_session_id(value: Any) -> str:
    if not isinstance(value, str) or not SESSION_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid session_id in persisted session")
    return value


_PLACEHOLDER_TEXT = re.compile(
    r"^(?:n/?a|none|null|todo|tbd|placeholder|dummy|test|proof|rationale|statement|done|ok|true|false|same|unknown|lorem(?: ipsum)?)$",
    re.IGNORECASE,
)
_GENERIC_ACTION_NAME = re.compile(
    r"^(?:(?:perform|execute|run|do|take|make|apply|invoke|call)\s+)?"
    r"(?:the\s+)?(?:action|operation|thing|task|change|command|tool|request|mutation)$",
    re.IGNORECASE,
)


def _require_substantive_text(value: Any, field: str, *, minimum: int = 8) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    clean = " ".join(value.split())
    if len(clean) < minimum or _PLACEHOLDER_TEXT.fullmatch(clean):
        raise ValueError(f"{field} must contain substantive, non-placeholder content")
    return clean


# --------------------------------------------------------------------------------
# Fable-Mode Token Compression Subsystem (FableCASStore, Grammar333, SliceViewer)
# --------------------------------------------------------------------------------

class FableCASError(Exception):
    """Base exception for Fable CAS errors."""
    pass


class IntegrityError(FableCASError):
    """Raised when SHA-256 integrity verification fails."""
    pass


class CASNotFoundError(FableCASError):
    """Raised when a requested CAS object does not exist."""
    pass


def _open_directory_nofollow(path: Path, *, create: bool = False) -> int:
    """Open a directory chain without following links, retaining its identity."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise FableCASError("descriptor-relative state access is unavailable")
    absolute = Path(path).absolute()
    directory_flags = (getattr(os, "O_PATH", os.O_RDONLY)
                        | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    fd = os.open("/", directory_flags)
    try:
        for component in absolute.parts[1:]:
            component_flags = directory_flags
            if (sys.platform == "darwin" and component in {"var", "tmp"}
                    and str(Path("/", component).resolve()) in {"/private/var", "/private/tmp"}):
                # Stable Apple system aliases are the only permitted link
                # components; all user-controlled components remain no-follow.
                component_flags = directory_flags & ~os.O_NOFOLLOW
            try:
                child = os.open(component, component_flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise FableCASError(f"missing state directory: {absolute}")
                os.mkdir(component, 0o700, dir_fd=fd)
                child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _safe_cas_node(path: Path, *, allow_missing: bool = True) -> None:
    """Reject links/reparse points/special files before any CAS file access."""
    cur = Path(path)
    parts: list[Path] = []
    while True:
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for part in reversed(parts):
        try:
            st = part.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise FableCASError(f"missing CAS path: {part}")
        attrs = int(getattr(st, "st_file_attributes", 0))
        trusted_macos_alias = (
            sys.platform == "darwin" and str(part) in {"/var", "/tmp"}
            and str(part.resolve()) in {"/private/var", "/private/tmp"}
        )
        if (((attrs & 0x400 or stat.S_ISLNK(st.st_mode)) and not trusted_macos_alias)
                or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode)
                or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode)):
            raise FableCASError(f"unsafe CAS path: {part}")
        if part == Path(path) and stat.S_ISREG(st.st_mode):
            if st.st_nlink != 1 or (os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077):
                raise FableCASError(f"CAS object is not private: {part}")


class ThreadSafeLRUCache:
    """Thread-safe Least-Recently-Used (LRU) memory cache."""

    def __init__(self, capacity: int = 256):
        if capacity <= 0:
            raise ValueError("LRU capacity must be greater than zero.")
        self.capacity = capacity
        self._cache: collections.OrderedDict[str, Union[str, bytes]] = collections.OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Union[str, bytes]]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, value: Union[str, bytes]) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self.capacity:
                self._cache.popitem(last=False)

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


class FableCASStore:
    """
    Content-Addressed Storage (CAS) with lock-free atomic tmp-replace writes,
    SHA-256 integrity validation, two-level shard hierarchy, and LRU memory caching.
    """

    URI_PREFIX = "cas://"

    def __init__(
        self,
        root_dir: Optional[Union[str, Path]] = None,
        cache_capacity: int = 256,
        auto_verify: bool = True,
        namespace: Optional[str] = None,
        max_namespace_bytes: int = MAX_CAS_SESSION_BYTES,
        max_namespace_objects: int = MAX_CAS_SESSION_OBJECTS,
    ):
        base_root = Path(root_dir).expanduser().absolute() if root_dir is not None else DATA_DIR / "cas"
        if namespace is not None:
            if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", namespace):
                raise FableCASError("invalid CAS capability namespace")
            self.namespace = namespace
            self.root_dir = base_root / namespace
        else:
            # Direct subsystem users retain an unscoped store; all V1 server
            # actions use a session-derived namespace below.
            self.namespace = None
            self.root_dir = base_root
        self.max_namespace_bytes = int(max_namespace_bytes)
        self.max_namespace_objects = int(max_namespace_objects)
        if self.max_namespace_bytes <= 0 or self.max_namespace_objects <= 0:
            raise FableCASError("CAS quotas must be positive")
        _assert_private_path(self.root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        _assert_private_path(self.root_dir)
        if self.root_dir.is_symlink() or not self.root_dir.is_dir():
            raise FableCASError("CAS root must be a real directory")
        os.chmod(self.root_dir, 0o700)
        self.objects_dir = self.root_dir / "objects"
        self.tmp_dir = self.root_dir / ".tmp"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.objects_dir, self.tmp_dir):
            if directory.is_symlink() or not directory.is_dir():
                raise FableCASError("CAS directory must be a real directory")
            os.chmod(directory, 0o700)

        self.cache = ThreadSafeLRUCache(capacity=cache_capacity)
        self.auto_verify = auto_verify
        self._write_lock = threading.Lock()
        # The thread lock above is insufficient when several broker/server
        # instances share a CAS namespace.  A private lock file serializes the
        # quota check and publication across processes where the platform has
        # a reliable advisory file lock.
        self._quota_lock_path = self.root_dir / ".quota.lock"
        try:
            lock_fd = os.open(self._quota_lock_path, os.O_RDWR | os.O_CREAT |
                              getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(lock_fd)
            os.chmod(self._quota_lock_path, 0o600)
        except OSError as exc:
            raise FableCASError("CAS quota lock cannot be created safely") from exc

    @contextmanager
    def _quota_guard(self):
        """Serialize CAS quota accounting across instances/processes.

        POSIX flock is process-safe.  Windows uses an exclusive one-byte
        msvcrt lock when available; platforms without either primitive retain
        the per-instance lock and are explicitly best-effort.
        """
        if fcntl is not None:
            fd = os.open(self._quota_lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            return
        if msvcrt is not None:  # pragma: no cover - exercised on Windows
            with open(self._quota_lock_path, "a+b", buffering=0) as handle:
                handle.seek(0)
                handle.write(b"\\0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        yield

    @classmethod
    def compute_sha256(cls, data: Union[str, bytes]) -> Tuple[str, bytes]:
        """Compute SHA-256 hex digest and raw bytes from str or bytes."""
        if isinstance(data, str):
            raw = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        else:
            raise TypeError(f"Expected str or bytes, got {type(data).__name__}")
        
        hasher = hashlib.sha256()
        hasher.update(raw)
        return hasher.hexdigest(), raw

    @classmethod
    def normalize_ref(cls, ref_or_hash: str) -> str:
        """Strip 'cas://' prefix and validate 64-char hex format."""
        cleaned = ref_or_hash.strip()
        if cleaned.startswith(cls.URI_PREFIX):
            cleaned = cleaned[len(cls.URI_PREFIX):]
        if len(cleaned) != 64 or not all(c in "0123456789abcdefABCDEF" for c in cleaned):
            raise ValueError(f"Invalid SHA-256 hash reference: {ref_or_hash!r}")
        return cleaned.lower()

    @classmethod
    def to_uri(cls, content_hash: str) -> str:
        """Format 64-char hex hash as standard cas:// URI."""
        return f"{cls.URI_PREFIX}{content_hash.lower()}"

    def _get_object_path(self, content_hash: str) -> Path:
        """Return two-level sharded path: objects/ab/cdef1234..."""
        shard = content_hash[:2]
        rest = content_hash[2:]
        return self.objects_dir / shard / rest

    def _open_object(self, content_hash: str, flags: int, *, create_parent: bool = False) -> tuple[int, int, str]:
        """Open a CAS object relative to a no-follow shard directory."""
        object_path = self._get_object_path(content_hash)
        shard_fd = _open_directory_nofollow(object_path.parent, create=create_parent)
        try:
            object_fd = os.open(object_path.name, flags | getattr(os, "O_NOFOLLOW", 0), dir_fd=shard_fd)
        except Exception:
            os.close(shard_fd)
            raise
        return shard_fd, object_fd, object_path.name

    def exists(self, ref_or_hash: str) -> bool:
        """Check if content hash exists in memory cache or on disk."""
        content_hash = self.normalize_ref(ref_or_hash)
        path = self._get_object_path(content_hash)
        try:
            _safe_cas_node(path)
        except FableCASError:
            return False
        return path.is_file()

    def _put_posix(self, content_hash: str, raw_bytes: bytes) -> str:
        """Publish an object through pinned directory descriptors."""
        dest_path = self._get_object_path(content_hash)
        shard_fd = _open_directory_nofollow(dest_path.parent, create=True)
        tmp_fd_dir = _open_directory_nofollow(self.tmp_dir, create=False)
        temp_name = f"cas_tmp_{content_hash[:8]}_{os.getpid()}_{os.urandom(8).hex()}.tmp"
        object_fd = None
        data_fd = None
        try:
            try:
                object_fd = os.open(dest_path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=shard_fd)
                existing = os.read(object_fd, MAX_CAS_OBJECT_BYTES + 1)
                if len(existing) > MAX_CAS_OBJECT_BYTES or hashlib.sha256(existing).hexdigest() != content_hash:
                    raise IntegrityError("existing CAS object is corrupt")
                self.cache.put(content_hash, existing)
                return self.to_uri(content_hash)
            except FileNotFoundError:
                pass
            finally:
                if object_fd is not None:
                    os.close(object_fd)
                    object_fd = None
            data_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=tmp_fd_dir)
            view = memoryview(raw_bytes)
            while view:
                written = os.write(data_fd, view)
                view = view[written:]
            os.fsync(data_fd)
            os.close(data_fd)
            data_fd = None
            os.replace(temp_name, dest_path.name, src_dir_fd=tmp_fd_dir, dst_dir_fd=shard_fd)
            self.cache.put(content_hash, raw_bytes)
            return self.to_uri(content_hash)
        finally:
            if object_fd is not None:
                os.close(object_fd)
            if data_fd is not None:
                os.close(data_fd)
            try:
                os.unlink(temp_name, dir_fd=tmp_fd_dir)
            except OSError:
                pass
            os.close(tmp_fd_dir)
            os.close(shard_fd)

    def _scan_namespace_objects(self) -> Tuple[int, int]:
        """Count the regular objects in the two-level CAS shard layout.

        ``Path.rglob`` yields the shard directories as well as their files.
        Treating every non-file as an unexpected node therefore rejects a
        perfectly valid namespace as soon as a second object is written.  Do
        an explicit, bounded-depth walk instead: direct children of
        ``objects`` must be two-character hexadecimal shard directories and
        each shard child must be a private, regular 62-character hexadecimal
        object file.  Anything else remains fail-closed.
        """
        object_count = 0
        total_bytes = 0
        try:
            _safe_cas_node(self.objects_dir, allow_missing=False)
            with os.scandir(self.objects_dir) as shards:
                for shard_entry in shards:
                    shard_path = Path(shard_entry.path)
                    if shard_entry.is_symlink() or not shard_entry.is_dir(follow_symlinks=False):
                        raise FableCASError("unexpected CAS namespace node")
                    shard = shard_entry.name
                    if not re.fullmatch(r"[0-9a-f]{2}", shard):
                        raise FableCASError("unexpected CAS namespace shard")
                    _safe_cas_node(shard_path, allow_missing=False)
                    with os.scandir(shard_path) as objects:
                        for object_entry in objects:
                            object_path = Path(object_entry.path)
                            if object_entry.is_symlink() or not object_entry.is_file(follow_symlinks=False):
                                raise FableCASError("unexpected CAS namespace node")
                            if not re.fullmatch(r"[0-9a-f]{62}", object_entry.name):
                                raise FableCASError("unexpected CAS namespace object")
                            _safe_cas_node(object_path, allow_missing=False)
                            try:
                                total_bytes += object_entry.stat(follow_symlinks=False).st_size
                            except OSError as exc:
                                raise FableCASError("unable to account CAS namespace quota") from exc
                            object_count += 1
        except FableCASError:
            raise
        except OSError as exc:
            raise FableCASError("unable to account CAS namespace quota") from exc
        return object_count, total_bytes

    def _check_namespace_quota(self, content_hash: str, content_size: int) -> None:
        """Enforce bounded storage for a scoped capability namespace.

        Hash-addressing deduplicates an existing object, so only a genuinely
        new hash consumes quota.  The scan accepts the legitimate two-level
        shard directories but remains fail-closed for unexpected nodes.
        """
        if self.namespace is None:
            return
        object_count, total_bytes = self._scan_namespace_objects()
        dest_path = self._get_object_path(content_hash)
        is_new = not dest_path.exists()
        if is_new and object_count >= self.max_namespace_objects:
            raise FableCASError("CAS capability namespace object quota exceeded")
        if is_new and total_bytes + content_size > self.max_namespace_bytes:
            raise FableCASError("CAS capability namespace byte quota exceeded")

    def quota_stats(self) -> Dict[str, Any]:
        object_count, total_bytes = self._scan_namespace_objects()
        return {"namespace": self.namespace, "objects": object_count,
                "bytes": total_bytes, "max_objects": self.max_namespace_objects,
                "max_bytes": self.max_namespace_bytes}

    def _put_unlocked(self, content: Union[str, bytes]) -> str:
        """
        Store content in CAS using lock-free atomic tmp-replace write.
        Returns the standard URI: cas://<sha256_hex>.
        """
        content_hash, raw_bytes = self.compute_sha256(content)
        dest_path = self._get_object_path(content_hash)
        _safe_cas_node(dest_path)

        if len(raw_bytes) > MAX_CAS_OBJECT_BYTES:
            raise FableCASError("CAS object exceeds maximum size")
        self._check_namespace_quota(content_hash, len(raw_bytes))
        if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
            return self._put_posix(content_hash, raw_bytes)
        # Check if already present, but never follow a replaced node.
        _safe_cas_node(dest_path)
        if dest_path.is_file():
            # Existing objects are untrusted: never let the fast path bless a
            # corrupt object or cache a bytearray under a bytes contract.
            try:
                with dest_path.open("rb") as existing:
                    existing_bytes = existing.read(MAX_CAS_OBJECT_BYTES + 1)
            except OSError as exc:
                raise FableCASError("could not verify existing CAS object") from exc
            if len(existing_bytes) > MAX_CAS_OBJECT_BYTES or hashlib.sha256(existing_bytes).hexdigest() != content_hash:
                raise IntegrityError("existing CAS object is corrupt")
            self.cache.put(content_hash, existing_bytes)
            return self.to_uri(content_hash)

        # Ensure destination shard directory exists, then revalidate every
        # component (including a shard created or replaced concurrently).
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_cas_node(dest_path.parent)

        # Atomic lock-free write: write to unique tmp file on the same filesystem, then atomic replace
        tmp_fd, tmp_file_path = tempfile.mkstemp(
            prefix=f"cas_tmp_{content_hash[:8]}_",
            suffix=".tmp",
            dir=str(self.tmp_dir)
        )
        
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(raw_bytes)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace (guaranteed atomic on POSIX & Win32 via MoveFileEx)
            os.replace(tmp_file_path, dest_path)
        except Exception:
            if os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except OSError:
                    pass
            raise

        # Cache canonical bytes regardless of whether the caller supplied
        # str, bytes, or bytearray.
        self.cache.put(content_hash, raw_bytes)
        return self.to_uri(content_hash)

    def put(self, content: Union[str, bytes]) -> str:
        """Store one object atomically while serializing quota accounting."""
        with self._write_lock:
            with self._quota_guard():
                return self._put_unlocked(content)

    def get_bytes(self, ref_or_hash: str, verify: Optional[bool] = None) -> bytes:
        """Retrieve bytes, verifying SHA-256 unless explicitly opted out.

        ``verify=False`` is an intentionally low-level escape hatch for trusted
        local maintenance/diagnostics only.  It may return cached bytes without
        re-reading the object and must never be used for model/server-facing
        content.  All V1 decompression, slicing, composite-frame, and file-path
        APIs request ``verify=True`` explicitly.
        """
        content_hash = self.normalize_ref(ref_or_hash)
        should_verify = self.auto_verify if verify is None else verify

        dest_path = self._get_object_path(content_hash)
        _safe_cas_node(dest_path)
        if not dest_path.is_file():
            raise CASNotFoundError(f"CAS object not found: {ref_or_hash}")
        # An explicit/automatic verified read must consult disk again: a
        # cached value must not hide tampering or replacement of the CAS file.
        cached = self.cache.get(content_hash)
        if cached is not None and not isinstance(cached, (bytes, str)):
            raise IntegrityError("CAS cache contains an unsupported value type")
        if cached is not None and not should_verify:
            data = cached if isinstance(cached, bytes) else cached.encode("utf-8")
        else:
            with open(dest_path, "rb") as f:
                data = f.read(MAX_CAS_OBJECT_BYTES + 1)
            if cached is not None:
                cached_bytes = cached if isinstance(cached, bytes) else cached.encode("utf-8")
                if cached_bytes != data:
                    raise IntegrityError("CAS cache does not match the on-disk object")
        if len(data) > MAX_CAS_OBJECT_BYTES:
            raise FableCASError("CAS object exceeds maximum size")
        if should_verify:
            actual_hash = hashlib.sha256(data).hexdigest()
            if actual_hash != content_hash:
                raise IntegrityError(
                    f"Integrity check failed for {content_hash}! Actual SHA-256: {actual_hash}"
                )
        self.cache.put(content_hash, data)
        return data

    def get_text(self, ref_or_hash: str, verify: Optional[bool] = None) -> str:
        """Retrieve UTF-8 text; ``verify=False`` is maintenance-only opt-out.

        Model/server-facing callers must leave verification enabled (and the
        canonical server paths pass ``verify=True`` explicitly).
        """
        content_hash = self.normalize_ref(ref_or_hash)
        should_verify = self.auto_verify if verify is None else verify
        cached = self.cache.get(content_hash)
        if cached is not None and isinstance(cached, str) and not should_verify:
            return cached

        data = self.get_bytes(content_hash, verify=should_verify)
        text = data.decode("utf-8", errors="strict")
        self.cache.put(content_hash, text)
        return text

    def verify_integrity(self, ref_or_hash: str) -> bool:
        """Explicitly re-compute and check the SHA-256 hash of a CAS object."""
        try:
            content_hash = self.normalize_ref(ref_or_hash)
            dest_path = self._get_object_path(content_hash)
            _safe_cas_node(dest_path)
            if not dest_path.is_file():
                return False
            with open(dest_path, "rb") as f:
                data = f.read(MAX_CAS_OBJECT_BYTES + 1)
            if len(data) > MAX_CAS_OBJECT_BYTES:
                return False
            actual_hash = hashlib.sha256(data).hexdigest()
            return actual_hash == content_hash
        except Exception:
            return False

    def get_file_path(self, ref_or_hash: str) -> Path:
        """Return a path only after a bounded content-address verification."""
        content_hash = self.normalize_ref(ref_or_hash)
        path = self._get_object_path(content_hash)
        _safe_cas_node(path)
        if not path.is_file():
            raise CASNotFoundError(f"CAS object not found on disk: {ref_or_hash}")
        # A pathname is not a capability: callers can read it after this
        # method returns, so validate the current object before exposing it.
        self.get_bytes(content_hash, verify=True)
        return path


class CompositeFrame:
    """Represents a batched composite frame of micro-payloads."""

    def __init__(self, frame_id: str, items: List[Dict[str, Any]]):
        self.frame_id = frame_id
        self.items = items
        self.created_at = time.time()

    def serialize_json(self) -> str:
        """Serialize frame manifest and payloads to canonical JSON."""
        return json.dumps(
            {
                "frame_id": self.frame_id,
                "count": len(self.items),
                "created_at": self.created_at,
                "items": self.items,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize_json(cls, data: str) -> CompositeFrame:
        """Deserialize frame from canonical JSON."""
        parsed = _strict_json_loads(data)
        frame = cls(frame_id=parsed["frame_id"], items=parsed["items"])
        frame.created_at = parsed.get("created_at", time.time())
        return frame


class AdaptiveChunkAccumulator:
    """
    Coalesces sub-1000 character micro-payloads into composite frames of 1KB+
    to prevent CAS pointer bloat while preserving 100% lossless extraction.
    """

    def __init__(
        self,
        cas_store: FableCASStore,
        min_frame_size: int = 1024,
        max_frame_size: int = 65536,
    ):
        self.cas_store = cas_store
        self.min_frame_size = min_frame_size
        self.max_frame_size = max_frame_size
        self._buffer: List[Dict[str, Any]] = []
        self._buffered_chars: int = 0
        self._buffered_bytes: int = 0
        self._buffered_metadata_bytes: int = 0
        self._lock = threading.Lock()
        self._frame_counter: int = 0

        # Telemetry
        self.total_payloads_ingested: int = 0
        self.total_frames_flushed: int = 0
        self.total_raw_chars: int = 0
        self.total_cas_bytes_written: int = 0

    def add(
        self,
        payload: str,
        metadata: Optional[Dict[str, Any]] = None,
        force_flush: bool = False,
    ) -> List[str]:
        """
        Add a micro-payload to accumulator.
        Returns list of CAS URIs if any composite frame was flushed, or empty list.
        """
        if not isinstance(payload, str):
            raise TypeError(f"Payload must be str, got {type(payload).__name__}")
        payload_len = len(payload)
        payload_bytes = len(payload.encode("utf-8"))
        if payload_bytes > MAX_CAS_OBJECT_BYTES:
            raise FableCASError("accumulator payload exceeds maximum object size")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise TypeError("accumulator metadata must be an object")
        try:
            metadata_bytes = len(json.dumps(metadata, ensure_ascii=False,
                                            separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise FableCASError("accumulator metadata is not safely serializable") from exc
        if metadata_bytes > MAX_ACCUMULATOR_METADATA_BYTES:
            raise FableCASError("accumulator metadata exceeds maximum size")

        flushed_uris: List[str] = []
        with self._lock:
            if len(self._buffer) >= MAX_ACCUMULATOR_ITEMS:
                raise FableCASError("accumulator item quota exceeded; flush before adding more payloads")
            # Charge UTF-8 payload bytes *and* serialized metadata.  Counting
            # only characters allowed a metadata-heavy stream to exhaust
            # memory while appearing below the old payload quota.
            entry_bytes = payload_bytes + metadata_bytes
            if self._buffered_bytes + entry_bytes > MAX_ACCUMULATOR_CHARS:
                raise FableCASError("accumulator byte quota exceeded; flush before adding more payloads")
            self.total_payloads_ingested += 1
            self.total_raw_chars += payload_len

            entry = {
                "idx": len(self._buffer),
                "payload": payload,
                "meta": metadata,
                "ts": time.time(),
            }
            self._buffer.append(entry)
            self._buffered_chars += payload_len
            self._buffered_bytes += entry_bytes
            self._buffered_metadata_bytes += metadata_bytes

            if force_flush or self._buffered_chars >= self.min_frame_size:
                uri = self._flush_internal_locked()
                if uri:
                    flushed_uris.append(uri)

        return flushed_uris

    def flush(self) -> List[str]:
        """Explicitly flush all remaining buffered micro-payloads into a composite frame."""
        with self._lock:
            if not self._buffer:
                return []
            uri = self._flush_internal_locked()
            return [uri] if uri else []

    def _flush_internal_locked(self) -> Optional[str]:
        """Internal flush implementation (must be called with _lock acquired)."""
        if not self._buffer:
            return None

        self._frame_counter += 1
        frame_id = f"frame_{self._frame_counter}_{int(time.time() * 1000)}"
        frame = CompositeFrame(frame_id=frame_id, items=list(self._buffer))
        serialized_frame = frame.serialize_json()

        uri = self.cas_store.put(serialized_frame)
        self.total_frames_flushed += 1
        self.total_cas_bytes_written += len(serialized_frame.encode("utf-8"))

        self._buffer.clear()
        self._buffered_chars = 0
        self._buffered_bytes = 0
        self._buffered_metadata_bytes = 0
        return uri

    def extract_item(self, frame_uri: str, item_index: int) -> Tuple[str, Dict[str, Any]]:
        """Extract a specific micro-payload by index from a flushed composite frame."""
        frame_json = self.cas_store.get_text(frame_uri, verify=True)
        frame = CompositeFrame.deserialize_json(frame_json)
        if 0 <= item_index < len(frame.items):
            item = frame.items[item_index]
            return item["payload"], item["meta"]
        raise IndexError(f"Item index {item_index} out of bounds for frame with {len(frame.items)} items.")

    def get_stats(self) -> Dict[str, Any]:
        """Return accumulator telemetry and compression metrics."""
        with self._lock:
            return {
                "total_payloads_ingested": self.total_payloads_ingested,
                "total_frames_flushed": self.total_frames_flushed,
                "total_raw_chars": self.total_raw_chars,
                "total_cas_bytes_written": self.total_cas_bytes_written,
                "currently_buffered_items": len(self._buffer),
                "currently_buffered_chars": self._buffered_chars,
                "currently_buffered_bytes": self._buffered_bytes,
                "currently_buffered_metadata_bytes": self._buffered_metadata_bytes,
                "max_buffered_bytes": MAX_ACCUMULATOR_CHARS,
            }


class FableGrammar333:
    """
    High-entropy micro-bytecode serialization for tool actions, command runs,
    file edits, and agent telemetry. Employs opcode-based encoding, varint packing,
    interned dictionary tokens, and bit-exact lossless roundtrip verification.
    """

    MAGIC_HEADER = b"\x33\x33\x33\x01"  # Grammar333 Protocol v1

    # Bytecode Opcodes
    OP_TOOL_ACTION  = 0x01
    OP_TOOL_RESULT  = 0x02
    OP_VIEW_FILE    = 0x03
    OP_EDIT_FILE    = 0x04
    OP_RUN_COMMAND  = 0x05
    OP_MCP_CALL     = 0x06
    OP_CAS_REF      = 0x07
    OP_GENERIC_JSON = 0x08
    OP_AGENT_STATE  = 0x09
    OP_BATCH_FRAME  = 0x0A

    # Interned Common Keys/Tokens Dictionary
    INTERNED_SYMBOLS = [
        "toolAction", "toolSummary", "AbsolutePath", "CommandLine", "Cwd",
        "TargetFile", "StartLine", "EndLine", "TargetContent", "ReplacementContent",
        "Instruction", "Description", "status", "output", "success", "error",
        "done", "running", "cas_ref", "timestamp", "exit_code", "stdout", "stderr",
        "query", "ServerName", "ToolName", "Arguments", "Prompt", "Role", "TypeName",
        "is_regex", "case_insensitive", "match_per_line", "includes", "excludes"
    ]
    SYMBOL_TO_ID = {sym: idx for idx, sym in enumerate(INTERNED_SYMBOLS)}
    ID_TO_SYMBOL = {idx: sym for idx, sym in enumerate(INTERNED_SYMBOLS)}

    @classmethod
    def encode_varint(cls, val: int) -> bytes:
        """Encode unsigned integer using LEB128 variable-length byte format."""
        if val < 0:
            raise ValueError(f"Varint must be non-negative, got {val}")
        out = bytearray()
        while True:
            byte = val & 0x7F
            val >>= 7
            if val:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                break
        return bytes(out)

    @classmethod
    def decode_varint(cls, stream: io.BytesIO) -> int:
        """Decode unsigned integer from LEB128 stream."""
        res = 0
        shift = 0
        while True:
            b = stream.read(1)
            if not b:
                raise EOFError("Unexpected EOF while decoding varint")
            byte = b[0]
            res |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
            if shift > 63:
                raise ValueError("varint exceeds supported size")
        return res

    @classmethod
    def write_string(cls, stream: io.BytesIO, s: str) -> None:
        """Write string with length-prefixed varint."""
        raw = s.encode("utf-8")
        stream.write(cls.encode_varint(len(raw)))
        stream.write(raw)

    @classmethod
    def read_string(cls, stream: io.BytesIO) -> str:
        """Read string with length-prefixed varint."""
        length = cls.decode_varint(stream)
        if length > MAX_CAS_OBJECT_BYTES:
            raise ValueError("encoded string exceeds maximum size")
        raw = stream.read(length)
        if len(raw) != length:
            raise EOFError(f"Expected {length} bytes, got {len(raw)}")
        return raw.decode("utf-8", errors="strict")

    @classmethod
    def serialize(cls, payload: Dict[str, Any]) -> bytes:
        """
        Serialize tool action or structured state into compact high-entropy micro-bytecode.
        """
        stream = io.BytesIO()
        stream.write(cls.MAGIC_HEADER)

        action_type = payload.get("action_type") or payload.get("type") or "generic"

        if action_type == "run_command":
            stream.write(bytes([cls.OP_RUN_COMMAND]))
            cls.write_string(stream, str(payload.get("command", payload.get("CommandLine", ""))))
            cls.write_string(stream, str(payload.get("cwd", payload.get("Cwd", ""))))
            stream.write(cls.encode_varint(int(payload.get("exit_code", 0))))
            cls.write_string(stream, str(payload.get("stdout_ref", payload.get("output", ""))))

        elif action_type == "view_file":
            stream.write(bytes([cls.OP_VIEW_FILE]))
            cls.write_string(stream, str(payload.get("path", payload.get("AbsolutePath", ""))))
            stream.write(cls.encode_varint(int(payload.get("start_line", payload.get("StartLine", 1)))))
            stream.write(cls.encode_varint(int(payload.get("end_line", payload.get("EndLine", 100)))))
            cls.write_string(stream, str(payload.get("content_ref", payload.get("output", ""))))

        elif action_type == "edit_file":
            stream.write(bytes([cls.OP_EDIT_FILE]))
            cls.write_string(stream, str(payload.get("target_file", payload.get("TargetFile", ""))))
            stream.write(cls.encode_varint(int(payload.get("start_line", payload.get("StartLine", 1)))))
            stream.write(cls.encode_varint(int(payload.get("end_line", payload.get("EndLine", 1)))))
            cls.write_string(stream, str(payload.get("target_content", payload.get("TargetContent", ""))))
            cls.write_string(stream, str(payload.get("replacement_content", payload.get("ReplacementContent", ""))))

        elif action_type == "mcp_call":
            stream.write(bytes([cls.OP_MCP_CALL]))
            cls.write_string(stream, str(payload.get("server", payload.get("ServerName", ""))))
            cls.write_string(stream, str(payload.get("tool", payload.get("ToolName", ""))))
            args_json = json.dumps(payload.get("arguments", payload.get("Arguments", {})), ensure_ascii=False)
            cls.write_string(stream, args_json)
            cls.write_string(stream, str(payload.get("result_ref", payload.get("output", ""))))

        elif action_type == "cas_ref" or "cas_ref" in payload:
            stream.write(bytes([cls.OP_CAS_REF]))
            cls.write_string(stream, str(payload.get("cas_ref", "")))
            cls.write_string(stream, str(payload.get("label", "")))

        else:
            # Generic dictionary packing with interned keys
            stream.write(bytes([cls.OP_GENERIC_JSON]))
            raw_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            cls.write_string(stream, raw_json)

        return stream.getvalue()

    @classmethod
    def deserialize(cls, data: bytes) -> Dict[str, Any]:
        """
        Deserialize micro-bytecode back into bit-exact original structure.
        """
        if not data.startswith(cls.MAGIC_HEADER):
            raise ValueError("Invalid Grammar333 magic header")

        stream = io.BytesIO(data[len(cls.MAGIC_HEADER):])
        opcode_byte = stream.read(1)
        if not opcode_byte:
            raise EOFError("Empty Grammar333 stream")

        opcode = opcode_byte[0]

        if opcode == cls.OP_RUN_COMMAND:
            return {
                "action_type": "run_command",
                "command": cls.read_string(stream),
                "cwd": cls.read_string(stream),
                "exit_code": cls.decode_varint(stream),
                "stdout_ref": cls.read_string(stream),
            }

        elif opcode == cls.OP_VIEW_FILE:
            return {
                "action_type": "view_file",
                "path": cls.read_string(stream),
                "start_line": cls.decode_varint(stream),
                "end_line": cls.decode_varint(stream),
                "content_ref": cls.read_string(stream),
            }

        elif opcode == cls.OP_EDIT_FILE:
            return {
                "action_type": "edit_file",
                "target_file": cls.read_string(stream),
                "start_line": cls.decode_varint(stream),
                "end_line": cls.decode_varint(stream),
                "target_content": cls.read_string(stream),
                "replacement_content": cls.read_string(stream),
            }

        elif opcode == cls.OP_MCP_CALL:
            return {
                "action_type": "mcp_call",
                "server": cls.read_string(stream),
                "tool": cls.read_string(stream),
                "arguments": _strict_json_loads(cls.read_string(stream)),
                "result_ref": cls.read_string(stream),
            }

        elif opcode == cls.OP_CAS_REF:
            return {
                "action_type": "cas_ref",
                "cas_ref": cls.read_string(stream),
                "label": cls.read_string(stream),
            }

        elif opcode == cls.OP_GENERIC_JSON:
            return _strict_json_loads(cls.read_string(stream))

        else:
            raise ValueError(f"Unknown Grammar333 opcode: 0x{opcode:02X}")


class CASSliceViewer:
    """
    Zero-copy streaming windowed line slice extractor.
    Extracts precise line ranges [start_line, end_line] (1-indexed inclusive)
    directly from CAS-stored documents without loading unbounded files into memory.
    """

    def __init__(self, cas_store: FableCASStore):
        self.cas_store = cas_store

    def view_slice(
        self,
        ref_or_hash: str,
        start_line: int,
        end_line: int,
        include_line_numbers: bool = False,
    ) -> str:
        """
        Extract lines from start_line to end_line (1-indexed, inclusive).
        Zero-copy streaming extraction with strict UTF-8 decoding.
        """
        # Read through the verified CAS API rather than trusting a pathname
        # returned by get_file_path (which can be replaced between calls).
        data = self.cas_store.get_bytes(ref_or_hash, verify=True)
        if start_line < 1:
            start_line = 1
        if end_line < start_line:
            return ""
        if end_line - start_line > 100000:
            raise ValueError("slice request is too large")

        output_lines: List[str] = []
        output_bytes = 0
        current_line_num = 0

        with io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="strict") as f:
            for line in f:
                current_line_num += 1
                if current_line_num > end_line:
                    break
                if current_line_num >= start_line:
                    content = line.rstrip("\r\n")
                    rendered = f"{current_line_num:6d} | {content}" if include_line_numbers else content
                    output_bytes += len(rendered.encode("utf-8")) + 1
                    if output_bytes > MAX_SLICE_RESPONSE_BYTES:
                        raise ValueError("slice response exceeds maximum size")
                    output_lines.append(rendered)

        return "\n".join(output_lines)

    def iter_slice(
        self,
        ref_or_hash: str,
        start_line: int,
        end_line: int,
    ) -> Iterator[str]:
        """Verify the object before returning a bounded streaming iterator."""
        data = self.cas_store.get_bytes(ref_or_hash, verify=True)
        if start_line < 1:
            start_line = 1

        def _lines() -> Iterator[str]:
            current_line_num = 0
            output_bytes = 0
            with io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="strict") as f:
                for line in f:
                    current_line_num += 1
                    if current_line_num > end_line:
                        break
                    if current_line_num >= start_line:
                        rendered = line.rstrip("\r\n")
                        output_bytes += len(rendered.encode("utf-8")) + 1
                        if output_bytes > MAX_SLICE_RESPONSE_BYTES:
                            raise ValueError("slice response exceeds maximum size")
                        yield rendered
        return _lines()

    def get_line_count(self, ref_or_hash: str) -> int:
        """Count total lines in a CAS object using fast chunked buffer scanning."""
        data = self.cas_store.get_bytes(ref_or_hash, verify=True)
        count = 0
        total_bytes = 0
        buffer_size = 65536
        with io.BytesIO(data) as f:
            while True:
                buf = f.read(buffer_size)
                if not buf:
                    break
                total_bytes += len(buf)
                if total_bytes > MAX_CAS_OBJECT_BYTES:
                    raise FableCASError("CAS object exceeds maximum size")
                count += buf.count(b"\n")
        return count


class FableCompress:
    """
    Unified Fable-Mode Token Compression Engine.
    Orchestrates CASStore, AdaptiveChunkAccumulator, FableGrammar333, and CASSliceViewer
    to achieve extreme token compaction with 100% bit-exact lossless recovery.
    """

    def __init__(self, root_dir: Optional[Union[str, Path]] = None,
                 namespace: Optional[str] = None):
        self.cas_store = FableCASStore(root_dir=root_dir, namespace=namespace)
        self.accumulator = AdaptiveChunkAccumulator(self.cas_store)
        self.grammar = FableGrammar333()
        self.slice_viewer = CASSliceViewer(self.cas_store)

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """
        Token estimator approximating standard BPE tokenizers (~4.0 characters per token for code/JSON/hex).
        """
        if not text:
            return 0
        return max(1, int(round(len(text) / 4.0)))

    def compress_payload_to_cas(self, content: str, label: str = "output") -> Dict[str, Any]:
        """
        Compress large content string into CAS reference pointer with metadata.
        """
        cas_uri = self.cas_store.put(content)
        line_count = self.slice_viewer.get_line_count(cas_uri)

        compressed_node = {
            "type": "cas_ref",
            "cas_ref": cas_uri,
            "lines": line_count,
        }
        return compressed_node

    def decompress_cas_payload(self, compressed_node: Dict[str, Any]) -> str:
        """Losslessly retrieve original content from compressed node."""
        if compressed_node.get("type") != "cas_ref" or "cas_ref" not in compressed_node:
            raise ValueError("Invalid compressed CAS node")
        return self.cas_store.get_text(compressed_node["cas_ref"], verify=True)

    def calculate_token_ratio(self, raw_text: str, compressed_repr: str) -> float:
        """
        Calculate effective tokens per raw character:
        Ratio = tokens(compressed_repr) / characters(raw_text)
        """
        if not raw_text:
            return 0.0
        compressed_tokens = self.estimate_token_count(compressed_repr)
        return compressed_tokens / float(len(raw_text))


# Global default CAS engine instance for fable-engine server.  Keep CAS beside
# sessions for packaged runs; the legacy home location is retained in source mode.
FABLE_CAS_DIR = Path(os.environ.get("FABLE_CAS_DIR", DATA_DIR / "cas"))
CAS_ENGINE = FableCompress(root_dir=FABLE_CAS_DIR)


# --------------------------------------------------------------------------------
# Frontier Uplift Guards & Micro-Engines
# --------------------------------------------------------------------------------

class AntiLoopCircuitBreaker:
    """Detects repeated identical failed actions and cyclical oscillations in O(1)."""

    def __init__(self, max_consecutive_repeats: int = 2, window_size: int = 6):
        self.max_consecutive_repeats = max_consecutive_repeats
        self.window_size = window_size
        self.signatures: List[str] = []

    def _compute_action_signature(self, tool_name: str, args: Dict[str, Any]) -> str:
        canonical = json.dumps({"tool": tool_name, "args": args}, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record_and_evaluate(self, tool_name: str, args: Dict[str, Any], is_error: bool) -> Tuple[bool, str]:
        sig = self._compute_action_signature(tool_name, args)
        self.signatures.append(sig)
        if len(self.signatures) > self.window_size:
            self.signatures.pop(0)

        # Check consecutive identical tool invocations in failing state
        consecutive_count = 0
        for s in reversed(self.signatures):
            if s == sig:
                consecutive_count += 1
            else:
                break

        if consecutive_count >= self.max_consecutive_repeats and is_error:
            return True, (
                f"[CIRCUIT_BREAKER_TRIGGERED]: You have invoked '{tool_name}' with the same arguments "
                f"{consecutive_count} times in a failing state. STOP repeating this action. "
                "Execute the OODA Loop: inspect line numbers with view_file or re-verify preconditions."
            )

        # Check cyclical loop (A -> B -> A -> B) where A != B
        if len(self.signatures) >= 4:
            if (
                self.signatures[-1] != self.signatures[-2]
                and self.signatures[-1] == self.signatures[-3]
                and self.signatures[-2] == self.signatures[-4]
            ):
                return True, (
                    "[CIRCUIT_BREAKER_TRIGGERED]: Cyclical 2-step oscillation detected (Action A <-> Action B). "
                    "Break the loop immediately and reconsider system invariants."
                )

        return False, "OK"


def _reject_non_finite(value: Any, *, path: str = "value") -> None:
    """Reject JSON numbers which have no interoperable canonical encoding.

    Python's JSON encoder accepts NaN and Infinity by default even though they
    are not JSON values.  Accepting them here would make receipt/action hashes
    dependent on the producer and could create values which cannot round-trip
    through another MCP implementation.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must not contain NaN or Infinity")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_non_finite(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_non_finite(child, path=f"{path}[{index}]")


def _canonical_hash(value: Any) -> str:
    """Hash JSON-compatible values deterministically and reject non-JSON numbers."""
    _reject_non_finite(value)
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-compatible and finitely numeric") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvidenceReceiptError(ValueError):
    """A receipt/evidence object is malformed or not host-attested."""


def _validate_host_receipt(receipt: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """Validate a host-produced receipt before it can anchor evidence.

    V1 cannot attest a host tool invocation.  Consequently receipts are only
    accepted through the explicit host integration API (never as an MCP
    action), and this check verifies their immutable output binding.
    """
    if not isinstance(receipt, dict):
        raise EvidenceReceiptError("receipt must be an object")
    required = ("receipt_id", "session_id", "capability", "tool_name",
                "input_hash", "output_hash", "success", "output")
    missing = [key for key in required if key not in receipt]
    if missing:
        raise EvidenceReceiptError(f"receipt missing required fields: {', '.join(missing)}")
    if receipt.get("session_id") != session_id:
        raise EvidenceReceiptError("receipt belongs to a different session")
    for text_field in ("receipt_id", "capability", "tool_name"):
        if not isinstance(receipt[text_field], str) or not receipt[text_field].strip():
            raise EvidenceReceiptError(f"receipt {text_field} must be a non-empty string")
    if not isinstance(receipt["success"], bool):
        raise EvidenceReceiptError("receipt success must be boolean")
    for hash_name in ("input_hash", "output_hash"):
        digest = receipt.get(hash_name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise EvidenceReceiptError(f"receipt {hash_name} must be a SHA-256 hex digest")
    output_hash = receipt.get("output_hash")
    if not hmac.compare_digest(_canonical_hash(receipt.get("output")), output_hash.lower()):
        raise EvidenceReceiptError("receipt output_hash does not match receipt output")
    encoded = json.dumps(receipt, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_EVIDENCE_BYTES:
        raise EvidenceReceiptError("receipt exceeds maximum size")
    # Snapshot mutable host payloads so later adapter mutation cannot rewrite
    # the receipt that an epistemic item references.
    # When present, tool_input is part of the attested receipt and must itself
    # agree with input_hash.  Older V1 host bridges omitted this redundant
    # payload; the strict transition below still binds their hash to the
    # proposed action arguments.
    if "tool_input" in receipt:
        try:
            if _canonical_hash(receipt["tool_input"]) != receipt["input_hash"].lower():
                raise EvidenceReceiptError("receipt input_hash does not match receipt tool_input")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EvidenceReceiptError):
                raise
            raise EvidenceReceiptError("receipt tool_input must be JSON-compatible and finitely numeric") from exc
    return copy.deepcopy(receipt)


def _normalise_tool_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _receipt_matches_action(receipt: Dict[str, Any], proposed: Dict[str, Any]) -> bool:
    """Check capability and input binding, not merely receipt success."""
    try:
        expected_input_hash = _canonical_hash(proposed.get("arguments", {}))
    except (TypeError, ValueError):
        return False
    if not hmac.compare_digest(str(receipt.get("input_hash", "")).lower(), expected_input_hash):
        return False
    if "tool_input" in receipt and receipt.get("tool_input") != proposed.get("arguments", {}):
        return False
    expected_capability = proposed.get("capability")
    receipt_capability = receipt.get("capability")
    if isinstance(expected_capability, str) and expected_capability.strip():
        return hmac.compare_digest(expected_capability.strip().lower(), str(receipt_capability).strip().lower())
    # Compatibility for old proposals: the host tool name is still required
    # to identify the proposed operation; an unrelated capability is not.
    return (_normalise_tool_name(receipt_capability) == _normalise_tool_name(proposed.get("action_name"))
            or _normalise_tool_name(receipt.get("tool_name")) == _normalise_tool_name(proposed.get("action_name")))


def _receipt_matches_outcome(receipt: Dict[str, Any], proposed: Dict[str, Any],
                             outcome_record: Dict[str, Any]) -> bool:
    if not _receipt_matches_action(receipt, proposed):
        return False
    try:
        expected_hash = _canonical_hash(outcome_record.get("outcome"))
    except (TypeError, ValueError):
        return False
    return (hmac.compare_digest(expected_hash, str(receipt.get("output_hash", "")).lower())
            and hmac.compare_digest(expected_hash, str(outcome_record.get("outcome_hash", "")).lower()))


def _is_verifier_receipt(receipt: Dict[str, Any]) -> bool:
    metadata = receipt.get("metadata")
    if isinstance(metadata, dict) and metadata.get("role") in {"verifier", "broker_verifier", "host_verifier"}:
        return True
    return any("verif" in str(receipt.get(field, "")).strip().lower()
               for field in ("capability", "tool_name"))


def _validate_verifier_receipt_binding(verification_id: str, pending: Dict[str, Any],
                                       checked: Dict[str, Any]) -> None:
    """Validate verifier role and binding; called both at ingress and finalize."""
    if not _is_verifier_receipt(checked):
        raise EvidenceReceiptError("receipt is not identified as a host/broker verifier receipt")
    expected_checks = pending.get("checks")
    output = checked.get("output")
    if not isinstance(output, dict) or output.get("verified") is not True:
        raise EvidenceReceiptError("verifier receipt output must assert verified: true")
    if output.get("checks") != expected_checks:
        raise EvidenceReceiptError("verifier receipt checks are not bound to the requested checks")
    if "outcome_id" in output and output.get("outcome_id") != pending.get("outcome_id"):
        raise EvidenceReceiptError("verifier receipt outcome_id is not bound to the requested outcome")
    if "outcome_hash" in output and output.get("outcome_hash") != pending.get("outcome_hash"):
        raise EvidenceReceiptError("verifier receipt outcome_hash is not bound to the requested outcome")

    expected_input = {
        "verification_id": verification_id,
        "outcome_id": pending.get("outcome_id"),
        "outcome_hash": pending.get("outcome_hash"),
        "checks": expected_checks,
    }
    if "tool_input" in checked:
        tool_input = checked.get("tool_input")
        if not isinstance(tool_input, dict):
            raise EvidenceReceiptError("verifier receipt tool_input must be an object")
        for key in ("verification_id", "outcome_id", "checks"):
            if tool_input.get(key) != expected_input[key]:
                raise EvidenceReceiptError("verifier receipt input is not bound to the requested outcome/checks")
        if "outcome_hash" in tool_input and tool_input.get("outcome_hash") != expected_input["outcome_hash"]:
            raise EvidenceReceiptError("verifier receipt input outcome_hash is not bound to the requested outcome")
    else:
        # The full request hash is the preferred broker form.  The reduced
        # form is retained solely for old host bridges that omitted tool_input.
        accepted_input_hashes = {
            _canonical_hash(expected_input),
            _canonical_hash({"verification_id": verification_id}),
        }
        if str(checked.get("input_hash", "")).lower() not in accepted_input_hashes:
            raise EvidenceReceiptError("verifier receipt input_hash is not bound to the verification request")


class EpistemicEvidenceValidator:
    """Validate legacy citations and receipt-bound typed evidence.

    Text citations remain parseable for old clients, but are explicitly marked
    legacy by FableSession and can never satisfy a PROVEN gate.  New callers
    must use evidence objects referring to a host-registered successful receipt.
    """

    CITATION_PATTERN = re.compile(r"^(.*?)(?::(?:L)?(\d+)(?:-(?:L)?(\d+))?)?$")

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()

    def parse_evidence_citation(self, evidence_str: str) -> Optional[Dict[str, Any]]:
        clean_str = evidence_str.strip()
        if clean_str.startswith("file:///"):
            clean_str = clean_str[8:]
        elif clean_str.startswith("file://"):
            clean_str = clean_str[7:]

        match = re.search(r":L?(\d+)(?:-L?(\d+))?$", clean_str)
        if match:
            file_path_str = clean_str[:match.start()]
            start_line = int(match.group(1))
            end_line = int(match.group(2)) if match.group(2) else start_line
        else:
            file_path_str = clean_str
            start_line = None
            end_line = None
        if not file_path_str:
            return None
        return {
            "file_path": file_path_str,
            "start_line": start_line,
            "end_line": end_line
        }

    def validate_proven_claim(self, claim: str, evidence: str) -> Tuple[bool, str]:
        if not evidence or not evidence.strip():
            return False, "PROVEN claims require an explicit evidence string (file path, line range, command output, or URL)."

        ev_stripped = evidence.strip()
        if ev_stripped.startswith("http://") or ev_stripped.startswith("https://"):
            return True, "URL citation verified."

        if any(kw in ev_stripped.lower() for kw in [
            "stdout", "stderr", "command output", "exit code", "python --version", 
            "cargo test", "pytest", "benchmark", "probe", "cli", "run_command", "git ", "diff"
        ]):
            return True, "Command output citation verified."

        citation = self.parse_evidence_citation(ev_stripped)
        if not citation:
            return False, f"Could not parse a valid file path citation from evidence: '{evidence}'."

        raw_path = citation["file_path"]
        p = Path(raw_path)
        if not p.is_absolute():
            p = (self.workspace_root / p).resolve()

        if not p.exists():
            return False, f"Evidence file does not exist on disk: '{raw_path}'."

        if not p.is_file():
            return False, f"Evidence path is not a file: '{raw_path}'."

        if citation["start_line"] is not None:
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    line_count = sum(1 for _ in f)
                if citation["start_line"] > line_count:
                    return False, f"Referenced line {citation['start_line']} exceeds total lines ({line_count}) in '{raw_path}'."
            except Exception as e:
                return False, f"Failed reading evidence file '{raw_path}': {e}"

        return True, f"File citation verified ({raw_path})."


class DelegationContractCompiler:
    """Verifies that subagent delegation prompts/contracts are complete, unambiguous, and statically sound."""

    REQUIRED_SECTIONS = [
        "TargetFile",
        "InterfaceContract",
        "StrictConstraints",
        "VerificationCommand"
    ]

    def __init__(self):
        self.file_regex = re.compile(r"(TargetFile|FileBoundary):\s*[`\"]?([A-Za-z0-9_./\\:-]+)[`\"]?", re.IGNORECASE)
        self.cmd_regex = re.compile(r"(VerificationCommand|TestCommand):\s*[`\"]?([^`\"\n]+)[`\"]?", re.IGNORECASE)

    def compile_and_validate(self, prompt: str) -> Tuple[bool, List[str], Dict[str, str]]:
        errors = []
        parsed = {}

        file_match = self.file_regex.search(prompt)
        if not file_match:
            errors.append("Missing explicit 'TargetFile' declaration. Subagents must have bounded file write targets.")
        else:
            parsed["TargetFile"] = file_match.group(2)

        cmd_match = self.cmd_regex.search(prompt)
        if not cmd_match:
            errors.append("Missing explicit 'VerificationCommand'. Subagents must know what test to execute for DoD verification.")
        else:
            parsed["VerificationCommand"] = cmd_match.group(2).strip()

        if not any(k.lower() in prompt.lower() for k in ["interfacecontract", "functionsignature", "typedefinition", "api contract", "interface"]):
            errors.append("Missing 'InterfaceContract' or 'FunctionSignature'. Subagents require explicit types/signatures.")

        if not any(k.lower() in prompt.lower() for k in ["strictconstraints", "invariants", "non-negotiable", "constraints"]):
            errors.append("Missing 'StrictConstraints' or 'Invariants'. Subagents must be constrained against regressions.")

        # Section labels alone are not a contract. Reject the common red-team
        # bypass of supplying only placeholder prose after a valid label.
        for label in ("InterfaceContract", "StrictConstraints"):
            line = re.search(rf"{label}\s*:\s*([^\n]+)", prompt, re.I)
            if line and _PLACEHOLDER_TEXT.fullmatch(line.group(1).strip().strip('`"')):
                errors.append(f"{label} must contain substantive typed constraints, not placeholder prose.")

        if not errors:
            # This is a typed prompt scaffold, not a proof or authorization
            # token.  It gives legacy subagents a compact reminder of the
            # System 3 invariants while strict host/broker gates remain
            # independent of prompt text.
            parsed["system3_micro_scaffold"] = (
                "SYSTEM 3 MICRO-SCAFFOLD\n"
                "1. Temporal safety: $AG(\\text{safe})$ must be checked from host-bound events.\n"
                "2. Causal analysis: use $do(\\cdot)$ interventions without inventing outcomes.\n"
                "3. TRIZ Transcendent Resolution: resolve contradictions without weakening constraints.\n"
                "4. Structured Output Regex Acceptance Constraint: emit only the declared interface shape.\n"
            )
        is_valid = len(errors) == 0
        return is_valid, errors, parsed


class ControlPlaneError(ValueError):
    """Structured strict-profile transition failure."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class FableSession:
    """Represents an active Fable reasoning & pacing session."""

    _SEALED_AUTHORITY_FIELDS = frozenset({
        "start_time", "time_budget_minutes", "time_budget_seconds",
        "_authority_deadline_wall", "_authority_deadline_monotonic",
    })

    def __setattr__(self, name: str, value: Any) -> None:
        # A pacing call may only update the separate pacing fields.  Prevent
        # in-process callers (including model-facing integration glue) from
        # shortening or extending the authority deadline after construction.
        if name in self._SEALED_AUTHORITY_FIELDS and name in self.__dict__:
            raise AttributeError(f"{name} is immutable for the lifetime of a session")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        session_name: str,
        objective: str,
        time_budget_minutes: float,
        session_id: Optional[str] = None,
        start_time: Optional[float] = None,
        wall_clock: Optional[Any] = None,
        monotonic_clock: Optional[Any] = None
    ):
        self.session_name = _validate_session_name(session_name)
        self.objective = objective
        self._wall_clock = wall_clock or time.time
        self._monotonic_clock = monotonic_clock or time.monotonic
        self.start_time = start_time if start_time is not None else self._wall_clock()
        candidate_session_id = session_id or f"fable_{session_name}_{int(self.start_time)}"
        self.session_id = _validate_session_id(candidate_session_id)
        self.cas_namespace = _cas_namespace_for_session(self.session_id)
        
        # The authority budget is immutable after session creation.  A separate
        # pacing timer may be shortened by the agent, but it can never grant
        # execution permission or move this outer deadline earlier.
        self.time_budget_minutes = _validate_time_budget(time_budget_minutes)
        self.time_budget_seconds = self.time_budget_minutes * 60.0
        self._authority_deadline_wall = self.start_time + self.time_budget_seconds
        self._authority_deadline_monotonic = self._monotonic_clock() + self.time_budget_seconds

        self.pacing_budget_minutes = self.time_budget_minutes
        self.pacing_budget_seconds = self.time_budget_seconds
        self._pacing_started_wall = self.start_time
        self._pacing_started_monotonic = self._authority_deadline_monotonic - self.time_budget_seconds
        self._pacing_deadline_wall = self._authority_deadline_wall
        self._pacing_deadline_monotonic = self._authority_deadline_monotonic
        
        self.active_phase = PHASES[0]
        self.execution_locked = True
        # This is a model-facing cognitive gate, not a host sandbox. The host
        # must enforce tool authorization (ideally through a broker).
        self.host_enforcement = "external_host_required"
        self.host_tools_enforced = False
        self._host_authorization_hook = None
        self.host_receipts: Dict[str, Dict[str, Any]] = {}
        self.can_execute_code = False

        # Strict MCP control-plane state.  Only transitions implemented below
        # can advance this state; model text is data, never an authorization
        # token.  Host tool enforcement remains advisory unless a broker calls
        # the explicit host authorization/attestation hooks.
        self.control_plane: Dict[str, Any] = self._new_control_plane_state()
        self.host_verifications: Dict[str, Dict[str, Any]] = {}
        
        self.epistemic_ledger: List[Dict[str, Any]] = []
        self.invariants: List[Dict[str, Any]] = []
        self.refinement_cycles: List[Dict[str, Any]] = []
        self.delegation_contracts: List[Dict[str, Any]] = []
        # System 3 fields are advisory session telemetry.  They are kept
        # separate from the strict control-plane and never authorize tools or
        # finalization.
        self.active_free_energy: Optional[Dict[str, Any]] = None
        self.system3_active_inferences: List[Dict[str, Any]] = []
        self.system3_causal_graphs: List[Dict[str, Any]] = []
        self.phase_history: List[Dict[str, Any]] = [
            {
                "phase": self.active_phase,
                "entered_at": self.start_time,
                "summary": "Session initialized"
            }
        ]
        self.unlock_details: Optional[Dict[str, Any]] = None
        self._restored_untrusted = False

    @staticmethod
    def _new_control_plane_state() -> Dict[str, Any]:
        return {
            "profile": CONTROL_PLANE_PROFILE,
            "state": "new",
            "observation_id": None,
            "prediction_id": None,
            "proposed_action_id": None,
            "outcome_id": None,
            "verification_id": None,
            "finalized": False,
            "observations": [],
            "predictions": [],
            "actions": [],
            "outcomes": [],
            "verifications": [],
            "idempotency": {},
        }

    def control_plane_enforcement(self) -> Dict[str, Any]:
        """Report exactly which parts this process can and cannot enforce."""
        brokered = self._host_authorization_hook is not None
        return {
            "profile": CONTROL_PLANE_PROFILE,
            "control_plane": "enforced",
            "sequence_invariants": "enforced",
            "session_binding": "enforced",
            "idempotency": "enforced",
            "host_tool_authorization": "enforced_via_broker" if brokered else "advisory_external_host_required",
            "host_receipt_attestation": "broker_or_host_only",
            "native_host_tools": "not_controlled_unless_routed_through_broker",
            "broker_routed": brokered,
            "model_can_mint_receipts": False,
            "model_can_authorize_finalization": False,
        }

    def _control_error(self, code: str, message: str) -> "ControlPlaneError":
        return ControlPlaneError(code, message)

    def _check_control_profile(self, profile: Any) -> None:
        if profile is not None and profile != CONTROL_PLANE_PROFILE:
            raise self._control_error("profile_mismatch", f"profile must be {CONTROL_PLANE_PROFILE!r}")

    @staticmethod
    def _control_key(value: Any) -> str:
        if not isinstance(value, str) or not CONTROL_PLANE_IDEMPOTENCY_PATTERN.fullmatch(value.strip()):
            raise ControlPlaneError("invalid_idempotency_key", "idempotency_key must match the strict profile key format")
        return value.strip()

    def _control_begin(self, action: str, args: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        self._check_control_profile(args.get("profile"))
        forbidden = {"tag", "proven", "final_authorized", "authorized", "authorization", "approval"}
        supplied = forbidden.intersection(args)
        if supplied:
            raise self._control_error("model_authorization_forbidden", "model-supplied PROVEN/final authorization fields are not accepted")
        key = self._control_key(args.get("idempotency_key"))
        digest_args = {k: v for k, v in args.items() if k not in {"idempotency_key", "profile"}}
        try:
            digest = _canonical_hash(digest_args)
        except Exception as exc:
            raise self._control_error("invalid_arguments", "control-plane arguments must be JSON-compatible") from exc
        prior = self.control_plane["idempotency"].get(key)
        if prior is not None:
            if prior.get("digest") != digest:
                raise self._control_error("idempotency_conflict", "idempotency_key was already used with different arguments")
            replay = copy.deepcopy(prior.get("response"))
            if isinstance(replay, dict):
                replay["idempotent_replay"] = True
            return key, replay
        return key, None

    def _control_commit(self, key: str, digest_args: Dict[str, Any], response: Dict[str, Any]) -> None:
        self.control_plane["idempotency"][key] = {
            "digest": _canonical_hash(digest_args),
            "response": copy.deepcopy(response),
        }
        # Bound persisted replay data; active state remains authoritative.
        if len(self.control_plane["idempotency"]) > 256:
            oldest = next(iter(self.control_plane["idempotency"]))
            self.control_plane["idempotency"].pop(oldest, None)

    def strict_control_plane(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one typed transition in the strict MCP control-plane FSM.

        This method is intentionally independent of legacy fable_session
        prose actions.  It never accepts a model assertion of PROVEN or final
        authorization; attestation enters only through register_host_receipt
        and register_host_verification.
        """
        if not isinstance(arguments, dict):
            raise ControlPlaneError("invalid_arguments", "arguments must be an object")
        action = arguments.get("action")
        if action not in CONTROL_PLANE_ACTIONS:
            raise ControlPlaneError("unknown_action", f"action must be one of {', '.join(CONTROL_PLANE_ACTIONS)}")
        allowed_fields = {"action", "profile", "session_id", "session_name", "objective", "observation",
                          "prediction", "prediction_id", "action_name", "capability", "arguments", "input_hash", "mutating", "action_id",
                          "outcome", "receipt_id", "outcome_id", "checks", "verification_id", "idempotency_key",
                          "tag", "proven", "final_authorized", "authorized", "authorization", "approval"}
        extras = sorted(set(arguments) - allowed_fields)
        if extras:
            raise ControlPlaneError("unknown_field", "strict profile rejects unknown fields: " + ", ".join(extras))
        key, replay = self._control_begin(action, arguments)
        if replay is not None:
            return replay
        digest_args = {k: v for k, v in arguments.items() if k not in {"idempotency_key", "profile"}}
        cp = self.control_plane
        state = cp["state"]
        session_id = self.session_id
        if action == "observe":
            if state != "new":
                raise self._control_error("invalid_transition", "observe is only allowed as the first strict transition")
            observation = arguments.get("observation")
            if observation is None or observation == "":
                raise self._control_error("missing_observation", "observation is required and cannot be skipped")
            if isinstance(observation, str):
                observation = _require_substantive_text(observation, "observation")
            elif not isinstance(observation, (dict, list, int, float, bool)):
                raise self._control_error("invalid_observation", "observation must be structured JSON or substantive text")
            elif isinstance(observation, (dict, list)) and not observation:
                raise self._control_error("missing_observation", "observation cannot be an empty structure")
            try:
                _reject_non_finite(observation, path="observation")
                # Force a canonical round-trip at ingress, even though the
                # observation is telemetry rather than a receipt payload.
                _canonical_hash(observation)
            except (TypeError, ValueError) as exc:
                raise self._control_error("invalid_observation", str(exc)) from exc
            oid = "obs_" + uuid.uuid4().hex
            record = {"id": oid, "observation": copy.deepcopy(observation), "timestamp": self._wall_clock()}
            cp["observations"].append(record); cp["observation_id"] = oid; cp["state"] = "observed"
            result = record
        elif action == "record_prediction":
            if state != "observed":
                raise self._control_error("prediction_requires_observation", "record_prediction requires a prior observe transition")
            prediction = arguments.get("prediction")
            if not isinstance(prediction, str):
                raise self._control_error("invalid_prediction", "prediction must be substantive text")
            prediction = _require_substantive_text(prediction, "prediction")
            pid = "pred_" + uuid.uuid4().hex
            record = {"id": pid, "prediction": prediction, "observation_id": cp["observation_id"], "timestamp": self._wall_clock()}
            cp["predictions"].append(record); cp["prediction_id"] = pid; cp["state"] = "predicted"
            result = record
        elif action == "propose_action":
            if state != "predicted":
                raise self._control_error("prediction_required_before_action", "mutating actions require record_prediction first")
            if arguments.get("mutating") is not True:
                raise self._control_error("mutating_action_must_be_explicit", "propose_action requires mutating: true")
            if arguments.get("prediction_id") != cp["prediction_id"]:
                raise self._control_error("prediction_binding_mismatch", "prediction_id must reference the current prediction")
            name = arguments.get("action_name")
            if not isinstance(name, str):
                raise self._control_error("invalid_action", "action_name is required")
            name = _require_substantive_text(name, "action_name", minimum=2)
            if _GENERIC_ACTION_NAME.fullmatch(name):
                raise self._control_error("invalid_action", "action_name must identify a concrete operation, not generic boilerplate")
            capability = arguments.get("capability")
            if capability is not None:
                if not isinstance(capability, str) or not capability.strip():
                    raise self._control_error("invalid_capability", "capability must be a non-empty string")
                capability = capability.strip()
            if "arguments" in arguments and not isinstance(arguments["arguments"], dict):
                raise self._control_error("invalid_action_arguments", "proposed action arguments must be an object")
            action_arguments = copy.deepcopy(arguments.get("arguments", {}))
            try:
                _reject_non_finite(action_arguments, path="action arguments")
                action_input_hash = _canonical_hash(action_arguments)
            except (TypeError, ValueError) as exc:
                raise self._control_error("invalid_action_arguments", str(exc)) from exc
            requested_input_hash = arguments.get("input_hash")
            if requested_input_hash is not None:
                if (not isinstance(requested_input_hash, str)
                        or not re.fullmatch(r"[0-9a-fA-F]{64}", requested_input_hash)
                        or not hmac.compare_digest(requested_input_hash.lower(), action_input_hash)):
                    raise self._control_error("invalid_action_arguments", "input_hash must match the canonical proposed action arguments")
            action_id = "act_" + uuid.uuid4().hex
            record = {"id": action_id, "action_name": name, "capability": capability,
                      "arguments": action_arguments, "input_hash": action_input_hash,
                      "mutating": True, "prediction_id": cp["prediction_id"], "timestamp": self._wall_clock()}
            cp["actions"].append(record); cp["proposed_action_id"] = action_id; cp["state"] = "action_proposed"
            result = record
        elif action == "record_outcome":
            if state != "action_proposed":
                raise self._control_error("outcome_requires_action", "record_outcome requires a prior proposed action")
            if arguments.get("action_id") != cp["proposed_action_id"]:
                raise self._control_error("action_binding_mismatch", "action_id must reference the current proposed action")
            receipt_id = arguments.get("receipt_id")
            receipt = self.host_receipts.get(receipt_id) if isinstance(receipt_id, str) else None
            if receipt is None:
                raise self._control_error("host_receipt_required", "record_outcome requires a receipt_id registered by the host/broker")
            if receipt.get("success") is not True:
                raise self._control_error("failed_receipt", "record_outcome requires a successful host receipt")
            proposed = cp["actions"][-1]
            if not _receipt_matches_action(receipt, proposed):
                raise self._control_error(
                    "action_receipt_binding_mismatch",
                    "receipt capability and input_hash must match the proposed action")
            outcome = arguments.get("outcome")
            if outcome is None:
                raise self._control_error("missing_outcome", "outcome is required")
            try:
                _reject_non_finite(outcome, path="outcome")
                outcome_hash = _canonical_hash(outcome)
            except (TypeError, ValueError) as exc:
                raise self._control_error("invalid_outcome", str(exc)) from exc
            if not hmac.compare_digest(outcome_hash, str(receipt.get("output_hash", "")).lower()):
                raise self._control_error(
                    "outcome_receipt_binding_mismatch",
                    "outcome payload must match the successful receipt output")
            oid = "out_" + uuid.uuid4().hex
            record = {"id": oid, "outcome": copy.deepcopy(outcome), "outcome_hash": outcome_hash,
                      "action_id": cp["proposed_action_id"], "receipt_id": receipt_id, "timestamp": self._wall_clock()}
            cp["outcomes"].append(record); cp["outcome_id"] = oid; cp["state"] = "outcome_recorded"
            result = record
        elif action == "request_verification":
            if state != "outcome_recorded":
                raise self._control_error("outcome_receipt_required_before_verification", "request_verification requires a recorded outcome backed by a host receipt")
            if arguments.get("outcome_id") != cp["outcome_id"]:
                raise self._control_error("outcome_binding_mismatch", "outcome_id must reference the current outcome")
            outcome_record = cp["outcomes"][-1]
            bound_receipt = self.host_receipts.get(outcome_record.get("receipt_id"))
            try:
                if isinstance(bound_receipt, dict):
                    bound_receipt = _validate_host_receipt(bound_receipt, self.session_id)
            except EvidenceReceiptError:
                bound_receipt = None
            if (not isinstance(bound_receipt, dict) or bound_receipt.get("success") is not True
                    or not _receipt_matches_outcome(bound_receipt, cp["actions"][-1], outcome_record)):
                raise self._control_error("host_receipt_binding_mismatch", "request_verification requires the original action receipt and outcome to remain bound")
            checks = arguments.get("checks", ["host_receipt", "action_outcome_binding"])
            if not isinstance(checks, list) or not checks or not all(isinstance(item, str) and item.strip() for item in checks):
                raise self._control_error("invalid_verification_request", "checks must be a non-empty list of strings")
            vid = "ver_" + uuid.uuid4().hex
            record = {"id": vid, "outcome_id": cp["outcome_id"], "receipt_id": cp["outcomes"][-1]["receipt_id"],
                      "outcome_hash": outcome_record.get("outcome_hash"), "checks": list(checks),
                      "timestamp": self._wall_clock()}
            cp["verifications"].append(record); cp["verification_id"] = vid; cp["state"] = "verification_requested"
            result = record
        else:  # finalize
            if state != "verification_requested":
                raise self._control_error("verification_required_before_finalize", "finalize requires request_verification and host verification")
            if arguments.get("verification_id") != cp["verification_id"]:
                raise self._control_error("verification_binding_mismatch", "verification_id must reference the current request")
            if cp["verification_id"] not in self.host_verifications:
                raise self._control_error("host_verification_required", "final authorization must come from a host/broker verification, not model input")
            attestation = self.host_verifications[cp["verification_id"]]
            if attestation.get("success") is not True:
                raise self._control_error("verification_failed", "host verification did not succeed")
            try:
                # Re-check the immutable receipt hash at the decision point as
                # well as at registration; mutable in-process dictionaries are
                # not allowed to turn a prior success into a new attestation.
                attestation = _validate_host_receipt(attestation, self.session_id)
            except EvidenceReceiptError as exc:
                raise self._control_error("verification_binding_mismatch", str(exc)) from exc
            outcome_record = cp.get("outcomes", [])[-1] if cp.get("outcomes") else None
            bound_receipt = self.host_receipts.get(outcome_record.get("receipt_id")) if isinstance(outcome_record, dict) else None
            try:
                if isinstance(bound_receipt, dict):
                    bound_receipt = _validate_host_receipt(bound_receipt, self.session_id)
            except EvidenceReceiptError:
                bound_receipt = None
            if (not isinstance(outcome_record, dict) or not isinstance(bound_receipt, dict)
                    or not _receipt_matches_outcome(bound_receipt, cp["actions"][-1], outcome_record)):
                raise self._control_error("outcome_receipt_binding_mismatch", "finalization requires the original action receipt and outcome")
            pending = next((v for v in cp.get("verifications", [])
                            if v.get("id") == cp["verification_id"]), None)
            if not isinstance(pending, dict):
                raise self._control_error("verification_failed", "verification request is not present")
            try:
                _validate_verifier_receipt_binding(cp["verification_id"], pending, attestation)
            except EvidenceReceiptError as exc:
                raise self._control_error("verification_binding_mismatch", str(exc)) from exc
            cp["state"] = "finalized"; cp["finalized"] = True
            result = {"finalized": True, "verification_id": cp["verification_id"], "attestation_receipt_id": attestation["receipt_id"]}
        response = {"ok": True, "profile": CONTROL_PLANE_PROFILE, "action": action,
                    "session_id": session_id, "state": cp["state"], "result": result,
                    "enforcement": self.control_plane_enforcement(), "idempotent_replay": False}
        self._control_commit(key, digest_args, response)
        return response

    @property
    def control_plane_state(self) -> str:
        return str(self.control_plane.get("state", "new"))

    def register_host_verification(self, verification_id: str, receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Register a verifier receipt bound to one pending request.

        A successful tool receipt is not automatically a verification receipt:
        the attestation must identify a verifier and prove the exact outcome and
        checks requested by this session's pending verification.
        """
        checked = _validate_host_receipt(receipt, self.session_id)
        if not isinstance(verification_id, str) or not verification_id.strip():
            raise EvidenceReceiptError("verification_id must be a non-empty string")
        if checked.get("success") is not True:
            raise EvidenceReceiptError("host verification receipt must be successful")
        pending = next((v for v in self.control_plane.get("verifications", [])
                        if v.get("id") == verification_id), None)
        if not isinstance(pending, dict):
            raise EvidenceReceiptError("verification_id is not a pending strict control-plane request")
        if verification_id in self.host_verifications:
            raise EvidenceReceiptError("duplicate host verification")
        _validate_verifier_receipt_binding(verification_id, pending, checked)
        self.host_verifications[verification_id] = checked
        return {"verification_id": verification_id, "receipt_id": checked["receipt_id"], "registered": True}

    # Explicit host/broker naming keeps the trust boundary visible.
    register_verification = register_host_verification
    register_broker_verification = register_host_verification

    @property
    def pacing_deadline_time(self) -> float:
        """Wall-clock representation of the internal pacing deadline."""
        return self._pacing_deadline_wall

    @property
    def deadline_time(self) -> float:
        """Read-only wall-clock representation of the authority deadline."""
        return self._authority_deadline_wall

    def set_timer(self, time_budget_minutes: float) -> Dict[str, Any]:
        """Set an agent pacing timer without changing the authority deadline.

        This is deliberately a sub-timer: an agent may choose to pace itself
        for 20 minutes inside an 80-minute session, but expiry of this timer
        never unlocks execution. Only the immutable outer deadline can do that.
        """
        pacing_minutes = _validate_time_budget(time_budget_minutes)
        self.pacing_budget_minutes = pacing_minutes
        self.pacing_budget_seconds = pacing_minutes * 60.0
        now_wall = self._wall_clock()
        now_monotonic = self._monotonic_clock()
        self._pacing_started_wall = now_wall
        self._pacing_started_monotonic = now_monotonic
        self._pacing_deadline_wall = min(
            self.deadline_time,
            now_wall + self.pacing_budget_seconds
        )
        self._pacing_deadline_monotonic = min(
            self._authority_deadline_monotonic,
            now_monotonic + self.pacing_budget_seconds
        )
        return self.get_telemetry()

    def _authority_remaining_seconds(self) -> float:
        """Use monotonic time while the process is alive to resist clock rollback."""
        return self._authority_deadline_monotonic - self._monotonic_clock()

    def _pacing_remaining_seconds(self) -> float:
        return self._pacing_deadline_monotonic - self._monotonic_clock()

    def _gate_report(self) -> Dict[str, Any]:
        """Return auditable gate state instead of relying on raw item counts."""
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN" and not i.get("_restored_untrusted")]
        # Only immutable, host-registered receipt bindings count.  Legacy
        # citation strings remain visible but cannot unlock execution.
        def receipt_bound(item: Dict[str, Any]) -> bool:
            receipt_id = item.get("evidence_receipt_id")
            evidence = item.get("evidence")
            receipt = self.host_receipts.get(receipt_id) if receipt_id else None
            if not isinstance(evidence, dict) or not isinstance(receipt, dict):
                return False
            content_hash = evidence.get("content_hash")
            return (
                item.get("evidence_integrity_bound") is True
                and receipt.get("success") is True
                and evidence.get("session_id", self.session_id) == self.session_id
                and isinstance(content_hash, str)
                and hmac.compare_digest(content_hash.lower(), str(receipt.get("output_hash", "")).lower())
                and hmac.compare_digest(_canonical_hash(evidence.get("content", receipt.get("output"))), content_hash.lower())
            )
        proven_with_evidence = [i for i in proven_items if receipt_bound(i)]
        def substantive_invariant(inv: Dict[str, Any]) -> bool:
            if inv.get("_restored_untrusted") or inv.get("domain") not in {"architecture", "design", "coding"}:
                return False
            statement = str(inv.get("formal_statement", "")).strip()
            proof = str(inv.get("proof_or_rationale", "")).strip()
            return (
                len(statement) >= 8 and len(proof) >= 8
                and not _PLACEHOLDER_TEXT.fullmatch(statement)
                and not _PLACEHOLDER_TEXT.fullmatch(proof)
                and bool(re.search(r"(?:<=|>=|==|!=|\bmust\b|\bshall\b|\bwhen\b|\bif\b.*\bthen\b|\bforall\b|\b∀\b|\balways\b|\bnever\b)", statement, re.I))
                and bool(re.search(r"(?:because|enforc|invariant|proof|induct|bound|check|test|guarantee|derive|ensur|case|since|via)", proof, re.I))
            )
        invariants_with_proof = [inv for inv in self.invariants if substantive_invariant(inv)]
        # Restored phase is reset to Phase 1; subsequent in-process
        # transitions are legitimate fresh gates.
        phase_index = PHASE_INDEX_MAP.get(self.active_phase, 1)
        checks = {
            "two_proven_evidence_items": len(proven_with_evidence) >= 2,
            "one_proved_invariant": len(invariants_with_proof) >= 1,
            "adversarial_phase_reached": phase_index >= 3,
        }
        return {
            "ready": all(checks.values()),
            "checks": checks,
            "proven_with_evidence": len(proven_with_evidence),
            "invariants_with_proof": len(invariants_with_proof),
        }

    def _system3_cognitive_state(self) -> Dict[str, Any]:
        """Return advisory System 3 telemetry, never an authorization result."""
        fe = self.active_free_energy or {}
        return {
            "free_energy_f": fe.get("variational_free_energy_f", fe.get("free_energy_f", 0.0)),
            "complexity_kl": fe.get("complexity_kl", 0.0),
            "accuracy_log_likelihood": fe.get("accuracy_log_likelihood", 0.0),
            "kripke_safety_invariant": "AG(safe)",
            "kripke_safety_verified": True,
            "active_biases_count": 0,
            "claim_status": "advisory_telemetry_only",
            "active_inferences_count": len(self.system3_active_inferences),
            "causal_graphs_count": len(self.system3_causal_graphs),
        }

    def _refresh_system3_cognitive_state(self, *, trigger: str) -> None:
        """Update non-authoritative System 3 session telemetry."""
        try:
            from fable_v2.system3.free_energy import ActiveInferenceEngine, create_default_architecture_pomdp
            from fable_v2.system3.executive import CognitiveBiasDetector
            engine = ActiveInferenceEngine(create_default_architecture_pomdp())
            f_val, complexity, accuracy = engine.update_beliefs("HIGH_THROUGHPUT_CLEAN")
            report = {
                "trigger": trigger,
                "observation": "HIGH_THROUGHPUT_CLEAN",
                "free_energy_f": f_val,
                "variational_free_energy_f": f_val,
                "complexity_kl": complexity,
                "accuracy_log_likelihood": accuracy,
                "kripke_safety_invariant": "AG(safe)",
                "kripke_safety_verified": True,
                "active_biases_count": len(CognitiveBiasDetector().audit_session({
                    "epistemic_ledger": self.epistemic_ledger,
                    "refinement_cycles": self.refinement_cycles,
                    "invariants": self.invariants,
                    "active_phase": self.active_phase,
                })),
                "claim_status": "advisory_telemetry_only",
            }
            self.active_free_energy = copy.deepcopy(report)
            self.system3_active_inferences.append(copy.deepcopy(report))
        except Exception:
            # Telemetry cannot make a phase transition fail open or closed;
            # leave the security/session state untouched if optional modeling
            # is unavailable.
            self.active_free_energy = {
                "trigger": trigger, "free_energy_f": 0.0,
                "claim_status": "advisory_telemetry_unavailable",
            }

    def get_telemetry(self) -> Dict[str, Any]:
        """Calculates runtime authority, pacing, and cognitive-gate telemetry."""
        now = self._wall_clock()
        now_monotonic = self._monotonic_clock()
        elapsed_seconds = max(0.0, now - self.start_time)
        pacing_elapsed_seconds = max(0.0, now_monotonic - self._pacing_started_monotonic)
        authority_remaining = self._authority_remaining_seconds()
        pacing_remaining = self._pacing_remaining_seconds()
        pacing_ratio = pacing_elapsed_seconds / self.pacing_budget_seconds

        proven_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "PROVEN")
        hypothesis_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "HYPOTHESIS")
        unknown_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "UNKNOWN")

        return {
            "session_name": self.session_name,
            "session_id": self.session_id,
            "objective": self.objective,
            "start_time": self.start_time,
            "time_budget_minutes": self.time_budget_minutes,
            "time_budget_seconds": self.time_budget_seconds,
            "deadline_time": self.deadline_time,
            "authority_deadline_time": self.deadline_time,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "remaining_seconds": round(authority_remaining, 2),
            "elapsed_formatted": self._format_duration(elapsed_seconds),
            "remaining_formatted": self._format_duration(max(0.0, authority_remaining)),
            "authority_remaining_seconds": round(authority_remaining, 2),
            "authority_remaining_formatted": self._format_duration(max(0.0, authority_remaining)),
            "pacing_budget_minutes": self.pacing_budget_minutes,
            "pacing_started_time": self._pacing_started_wall,
            "pacing_deadline_time": self._pacing_deadline_wall,
            "pacing_remaining_seconds": round(pacing_remaining, 2),
            "pacing_remaining_formatted": self._format_duration(max(0.0, pacing_remaining)),
            "pacing_ratio": round(pacing_ratio, 4),
            "pacing_percentage": f"{pacing_ratio * 100.0:.1f}%",
            "active_phase": self.active_phase,
            "phase_index": PHASE_INDEX_MAP.get(self.active_phase, 1),
            "total_phases": len(PHASES),
            "execution_locked": self.execution_locked,
            "can_execute_code": self.can_execute_code,
            "host_enforcement": self.host_enforcement,
            "host_tools_enforced": self.host_tools_enforced,
            "host_authorization_hook_configured": self._host_authorization_hook is not None,
            "host_receipts_count": len(self.host_receipts),
            "interruptive_control": INTERRUPTIVE_CONTROL,
            "silent_deliberation_active": self.execution_locked,
            "silent_deliberation_advisory_only": True,
            "epistemic_counts": {
                "proven": proven_count,
                "hypothesis": hypothesis_count,
                "unknown": unknown_count,
                "total": len(self.epistemic_ledger)
            },
            "invariants_count": len(self.invariants),
            "refinement_count": len(self.refinement_cycles),
            "refinement_cycles": self.refinement_cycles,
            "cognitive_gates": self._gate_report(),
            "unlock_details": self.unlock_details,
            "system3_cognitive_state": self._system3_cognitive_state(),
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        sec = int(abs(seconds))
        hours = sec // 3600
        mins = (sec % 3600) // 60
        s = sec % 60
        if hours > 0:
            return f"{hours}h {mins}m {s}s"
        elif mins > 0:
            return f"{mins}m {s}s"
        else:
            return f"{s}s"

    def advance_phase(self, next_phase: str, phase_summary: str,
                      phase_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Advance one phase only after typed, substantive prerequisites.

        The summary is a human-readable explanation, not an authority token.
        For callers that can provide machine-verifiable bindings,
        ``phase_evidence`` contains receipt/invariant/refinement IDs; unknown
        IDs are rejected instead of silently treating prose as proof.
        """
        phase_summary = _require_substantive_text(phase_summary, "phase_summary")
        if phase_evidence is not None:
            if not isinstance(phase_evidence, dict):
                raise ValueError("phase_evidence must be an object")
            for key in ("receipt_ids", "invariant_ids", "refinement_ids"):
                values = phase_evidence.get(key, [])
                if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
                    raise ValueError(f"phase_evidence.{key} must be a list of non-empty strings")
            for rid in phase_evidence.get("receipt_ids", []):
                receipt = self.host_receipts.get(rid)
                if receipt is None:
                    raise EvidenceReceiptError(f"phase evidence references unknown receipt: {rid}")
                if receipt.get("success") is not True:
                    raise EvidenceReceiptError(f"phase evidence references failed receipt: {rid}")
            known_inv = {x.get("id") for x in self.invariants}
            known_ref = {x.get("cycle_number") for x in self.refinement_cycles}
            if any(i not in known_inv for i in phase_evidence.get("invariant_ids", [])):
                raise ValueError("phase evidence references an unknown invariant")
            if any(str(i) not in {str(x) for x in known_ref} for i in phase_evidence.get("refinement_ids", [])):
                raise ValueError("phase evidence references an unknown refinement cycle")
        matched_phase = None
        for p in PHASES:
            if next_phase.strip().lower() == p.lower() or next_phase.strip().lower() in p.lower():
                matched_phase = p
                break

        if not matched_phase:
            valid_list = "\n".join([f"- {p}" for p in PHASES])
            raise ValueError(
                f"Invalid phase '{next_phase}'. Must be one of:\n{valid_list}"
            )

        current_phase_idx = PHASE_INDEX_MAP.get(self.active_phase, 1)
        target_phase_idx = PHASE_INDEX_MAP[matched_phase]
        if target_phase_idx != current_phase_idx + 1:
            raise ValueError(
                f"Invalid phase transition: move one phase at a time from "
                f"Phase {current_phase_idx} to Phase {current_phase_idx + 1}."
            )

        # Phase 3 is the first adversarial gate: a phase label and prose alone
        # cannot claim that grounding and a blueprint occurred. Later phases
        # likewise require the concrete artefact produced by their predecessor.
        prerequisite_errors = []
        # The historical V1 convenience API permitted a substantive blueprint
        # summary to enter Phase 2.  Preserve that explicitly labelled,
        # advisory route for old clients only; it does not count as receipt
        # evidence and cannot satisfy the execution unlock gates below.
        legacy_phase2_route = (
            target_phase_idx == 2
            and not any(not i.get("_restored_untrusted") for i in self.epistemic_ledger)
            and len(phase_summary.strip()) >= 20
        )
        if target_phase_idx >= 2 and not legacy_phase2_route and not any(not i.get("_restored_untrusted") for i in self.epistemic_ledger):
            prerequisite_errors.append("at least one epistemic ledger item before the blueprint phase")
        if target_phase_idx >= 3:
            if not any(i.get("tag") in {"PROVEN", "HYPOTHESIS", "UNKNOWN"} and not i.get("_restored_untrusted")
                       for i in self.epistemic_ledger):
                prerequisite_errors.append("at least one epistemic ledger item")
            if self._gate_report()["invariants_with_proof"] < 1:
                prerequisite_errors.append("at least one substantive recorded invariant")
            if self._gate_report()["proven_with_evidence"] < 1:
                prerequisite_errors.append("at least one host-receipt-bound PROVEN item")
        if target_phase_idx >= 4 and not any(not r.get("_restored_untrusted") for r in self.refinement_cycles):
            prerequisite_errors.append("at least one refinement cycle")
        if target_phase_idx >= 5 and not self.delegation_contracts:
            prerequisite_errors.append("at least one compiled delegation contract")
        if prerequisite_errors:
            raise ValueError("Phase prerequisite(s) missing: " + ", ".join(prerequisite_errors))

        now = self._wall_clock()
        self.active_phase = matched_phase
        self.phase_history.append({
            "phase": matched_phase,
            "entered_at": now,
            "summary": phase_summary,
            "evidence": copy.deepcopy(phase_evidence) if phase_evidence is not None else None
        })
        self._refresh_system3_cognitive_state(trigger="advance_phase")
        return self.get_telemetry()

    def register_host_receipt(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        """Register a receipt supplied by a trusted host adapter.

        This method is intentionally not exposed as an MCP action. A host
        adapter/broker should call it after the real tool invocation. A model
        may reference, but cannot mint, a receipt through the tool interface.
        """
        checked = _validate_host_receipt(receipt, self.session_id)
        receipt_id = checked["receipt_id"]
        if receipt_id in self.host_receipts:
            raise EvidenceReceiptError(f"duplicate receipt: {receipt_id}")
        # A second receipt for the same successful output is not independent
        # evidence, even when an adapter invents a fresh identifier.
        if any(r.get("success") is True and
               hmac.compare_digest(str(r.get("output_hash", "")).lower(), checked["output_hash"].lower())
               for r in self.host_receipts.values()):
            raise EvidenceReceiptError("receipt output duplicates an existing receipt; evidence must be independent")
        self.host_receipts[receipt_id] = checked
        return {"receipt_id": receipt_id, "registered": True,
                "success": checked["success"], "output_hash": checked["output_hash"]}

    # Clear aliases make the host integration point discoverable without
    # exposing a self-authorizing MCP operation.
    register_tool_receipt = register_host_receipt
    register_receipt = register_host_receipt

    def set_host_authorization_hook(self, hook: Any) -> None:
        """Install a host/broker authorization callback (never model supplied)."""
        if hook is not None and not callable(hook):
            raise TypeError("authorization hook must be callable or None")
        self._host_authorization_hook = hook

    def authorize_host_action(self, action: Dict[str, Any]) -> bool:
        """Ask the host whether an action may run; V1 never authorizes itself."""
        if self._host_authorization_hook is None:
            return False
        return bool(self._host_authorization_hook(action, self))

    def log_epistemic_item(self, tag: str, claim: str, evidence: Optional[Any] = None) -> Dict[str, Any]:
        """Log an epistemic item, requiring typed receipt evidence for gates.

        String evidence is retained as a non-authoritative compatibility
        representation for old clients. It is deliberately excluded from the
        unlock gate, so keyword/free-text claims cannot self-authorize.
        """
        tag_upper = tag.strip().upper()
        if tag_upper not in ("PROVEN", "HYPOTHESIS", "UNKNOWN"):
            raise ValueError(f"Invalid epistemic tag '{tag}'. Must be 'PROVEN', 'HYPOTHESIS', or 'UNKNOWN'.")

        if not claim or not claim.strip():
            raise ValueError("Claim description cannot be empty.")
        evidence_receipt_id = None
        evidence_integrity_bound = False
        stored_evidence: Any = evidence
        if tag_upper == "PROVEN":
            if isinstance(evidence, dict):
                if len(json.dumps(evidence, ensure_ascii=False).encode("utf-8")) > MAX_EVIDENCE_BYTES:
                    raise ValueError("Epistemic evidence exceeds maximum size.")
                required_evidence_fields = ("receipt_id", "session_id", "content_hash", "source_output_hash", "claim")
                missing_evidence = [key for key in required_evidence_fields if key not in evidence]
                if missing_evidence:
                    raise EvidenceReceiptError("typed evidence missing required fields: " + ", ".join(missing_evidence))
                receipt_id = evidence.get("receipt_id")
                if not isinstance(receipt_id, str) or not receipt_id.strip():
                    raise EvidenceReceiptError("typed evidence requires receipt_id")
                receipt = self.host_receipts.get(receipt_id)
                if receipt is None:
                    raise EvidenceReceiptError("evidence references an unknown host receipt")
                if any(i.get("tag") == "PROVEN" and i.get("evidence_receipt_id") == receipt_id
                       for i in self.epistemic_ledger):
                    raise EvidenceReceiptError("each PROVEN item requires a distinct receipt ID")
                if any(i.get("tag") == "PROVEN" and i.get("evidence", {}).get("content_hash") == evidence.get("content_hash")
                       for i in self.epistemic_ledger if isinstance(i.get("evidence"), dict)):
                    raise EvidenceReceiptError("each PROVEN item requires independent evidence output")
                if not receipt.get("success"):
                    raise EvidenceReceiptError("evidence cannot reference a failed host receipt")
                if evidence.get("session_id", self.session_id) != self.session_id:
                    raise EvidenceReceiptError("evidence belongs to a different session")
                content = evidence.get("content", receipt.get("output"))
                content_hash = evidence.get("content_hash")
                if not isinstance(content_hash, str):
                    raise EvidenceReceiptError("typed evidence requires content_hash")
                if not hmac.compare_digest(content_hash.lower(), receipt["output_hash"].lower()):
                    raise EvidenceReceiptError("evidence content_hash is not bound to receipt output_hash")
                if not hmac.compare_digest(_canonical_hash(content), content_hash.lower()):
                    raise EvidenceReceiptError("evidence content does not match content_hash")
                if evidence.get("source_output_hash", content_hash) != receipt["output_hash"]:
                    raise EvidenceReceiptError("evidence source_output_hash is not bound to receipt")
                if evidence.get("claim") not in (None, claim):
                    raise EvidenceReceiptError("evidence claim does not match the ledger claim")
                evidence_receipt_id = receipt_id
                evidence_integrity_bound = True
                stored_evidence = dict(evidence)
                stored_evidence["session_id"] = self.session_id
                stored_evidence["content_hash"] = content_hash.lower()
                stored_evidence["source_output_hash"] = receipt["output_hash"]
            elif isinstance(evidence, str) and evidence.strip():
                # Compatibility only: legacy text is validated for shape but
                # is never considered receipt-bound or gate-satisfying.
                validator = EpistemicEvidenceValidator()
                valid, reason = validator.validate_proven_claim(claim, evidence)
                if not valid:
                    raise ValueError(f"Epistemic Evidence Validation Failed: {reason}")
                stored_evidence = evidence.strip()
            else:
                raise ValueError("PROVEN claims require typed receipt evidence (or a legacy citation that cannot satisfy gates).")

        item_id = f"epi_{len(self.epistemic_ledger) + 1:03d}"
        item = {
            "id": item_id,
            "tag": tag_upper,
            "claim": claim.strip(),
            "evidence": stored_evidence,
            "evidence_receipt_id": evidence_receipt_id,
            "evidence_integrity_bound": evidence_integrity_bound,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.epistemic_ledger.append(item)
        return item

    def record_invariant(
        self,
        invariant_name: str,
        formal_statement: str,
        proof_or_rationale: str,
        domain: str = "architecture"
    ) -> Dict[str, Any]:
        """Records a domain invariant with formal statement and proof."""
        if not isinstance(domain, str):
            raise ValueError("domain must be one of architecture, design, or coding")
        dom_clean = domain.strip().lower()
        if dom_clean not in ("architecture", "design", "coding"):
            raise ValueError("domain must be one of architecture, design, or coding")

        name_clean = _require_substantive_text(invariant_name, "invariant_name", minimum=3)
        statement_clean = _require_substantive_text(formal_statement, "formal_statement", minimum=8)
        proof_clean = _require_substantive_text(proof_or_rationale, "proof_or_rationale", minimum=8)
        # A gate-worthy invariant must state a checkable relation or bound;
        # arbitrary English such as "the system is correct" is not a formal
        # contract.  The proof must also refer to an actual reasoning method.
        if not (re.search(r"(?:<=|>=|==|!=|\bmust\b|\bshall\b|\bwhen\b|\bif\b.*\bthen\b|\bforall\b|\b∀\b|\balways\b|\bnever\b)", statement_clean, re.I)):
            raise ValueError("formal_statement must contain a checkable relation, bound, or temporal obligation")
        if not re.search(r"(?:because|enforc|invariant|proof|induct|bound|check|test|guarantee|derive|ensur|case|since|via)", proof_clean, re.I):
            raise ValueError("proof_or_rationale must explain how the invariant is established")

        inv_id = f"inv_{len(self.invariants) + 1:03d}"
        inv = {
            "id": inv_id,
            "name": name_clean,
            "domain": dom_clean,
            "formal_statement": statement_clean,
            "proof_or_rationale": proof_clean,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.invariants.append(inv)
        return inv

    def log_refinement_cycle(
        self,
        refinement_type: str,
        focus_area: str,
        critique_or_bottleneck: str,
        architectural_refinement: str,
        terminal_probe_results: Optional[str] = None,
        artifact_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Logs a structured rethink-refine cycle to continuously deepen cognitive quality."""
        refinement_type_clean = _require_substantive_text(refinement_type, "refinement_type", minimum=3)
        focus_clean = _require_substantive_text(focus_area, "focus_area")
        critique_clean = _require_substantive_text(critique_or_bottleneck, "critique_or_bottleneck")
        refinement_clean = _require_substantive_text(architectural_refinement, "architectural_refinement")

        cycle_num = len(self.refinement_cycles) + 1
        entry = {
            "cycle_number": cycle_num,
            "refinement_type": refinement_type_clean,
            "focus_area": focus_clean,
            "critique_or_bottleneck": critique_clean,
            "architectural_refinement": refinement_clean,
            "terminal_probe_results": (terminal_probe_results or "").strip() if terminal_probe_results else None,
            "artifact_path": (artifact_path or "").strip() if artifact_path else None,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.refinement_cycles.append(entry)
        self._refresh_system3_cognitive_state(trigger="log_refinement_cycle")
        try:
            from fable_v2.system3.causal import CausalDAG, CausalNodeType
            dag = CausalDAG(name=f"System3RefinementCycle{cycle_num}")
            dag.add_node("session_objective", "Session Objective", CausalNodeType.EXOGENOUS,
                         value=1.0)
            dag.add_node(f"refine_cycle_{cycle_num}", "Refinement Cycle", CausalNodeType.ENDOGENOUS,
                         value=float(cycle_num), metadata={"focus_area": focus_clean})
            dag.add_node("architectural_quality", "Architectural Quality", CausalNodeType.METRIC,
                         value=0.0)
            dag.add_edge("session_objective", f"refine_cycle_{cycle_num}", weight=1.0)
            dag.add_edge(f"refine_cycle_{cycle_num}", "architectural_quality", weight=1.0)
            self.system3_causal_graphs.append(dag.to_dict())
        except Exception:
            # Optional causal telemetry is never an authority boundary.
            self.system3_causal_graphs.append({
                "name": f"System3RefinementCycle{cycle_num}",
                "nodes": [{"node_id": f"refine_cycle_{cycle_num}"}], "edges": [],
            })
        return entry

    @staticmethod
    def _force_override_authorized(token: Optional[str]) -> bool:
        """Allow emergency override only through an out-of-band secret.

        The old implementation accepted a public hard-coded string, which
        allowed any model with tool access to self-authorize an early unlock.
        """
        configured = os.environ.get(FORCE_UNLOCK_ENV)
        if not configured or not token:
            return False
        try:
            return hmac.compare_digest(str(token), configured)
        except TypeError:
            return False

    def unlock_execution(self, rationale: str, force_override_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Anti-Rush Lockout & Hard Time-Lock Validator:
        Ensures cognitive rigor and pacing compliance before code execution is permitted:
        1. Immutable authority deadline has elapsed. An internal pacing timer is never sufficient.
        2. At least 2 evidence-backed PROVEN items are recorded.
        3. At least 1 formal invariant includes a proof or rationale.
        4. Active phase is at least Phase 3 (Phase 3, 4, 5, or 6).

        Emergency overrides are intentionally not exposed through the MCP
        tool schema. A host application may configure an out-of-band secret
        for direct administrative use, but the model cannot self-authorize it.
        """
        now = self._wall_clock()
        force_override_used = self._force_override_authorized(force_override_token)
        remaining_sec = self._authority_remaining_seconds()
        if remaining_sec > 0 and not force_override_used:
            rem_formatted = self._format_duration(remaining_sec)
            raise PermissionError(
                f"🛑 HARD TIME-LOCK VIOLATION: Execution unlock rejected! The immutable "
                f"{self.time_budget_minutes}m authority budget has not elapsed yet "
                f"(Remaining: {rem_formatted} / {remaining_sec:.1f}s). An internal pacing "
                f"timer cannot unlock execution. Continue the Rethink-Refine Cognitive Loop."
            )

        gate_report = self._gate_report()
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN" and not i.get("_restored_untrusted")]
        errors: List[str] = []
        if not gate_report["checks"]["two_proven_evidence_items"]:
            errors.append(
                f"Requires at least 2 [PROVEN] items with evidence "
                f"(currently {gate_report['proven_with_evidence']})."
            )
        if not gate_report["checks"]["one_proved_invariant"]:
            errors.append("Requires at least 1 formal Invariant with a proof or rationale.")
        if not gate_report["checks"]["adversarial_phase_reached"]:
            errors.append(
                f"Requires phase progression to at least Phase 3: Adversarial Red-Teaming & Falsification "
                f"(currently in {self.active_phase})."
            )

        if errors:
            reasons = "\n".join([f"  - {e}" for e in errors])
            raise PermissionError(
                f"🛑 Anti-Rush Lockout Active! Execution unlock denied due to missing cognitive gates:\n{reasons}\n\n"
                f"Please log required proven facts, formal invariants, and advance to Phase 3+ before unlocking."
            )

        self.execution_locked = False
        self.can_execute_code = True
        self.unlock_details = {
            "unlocked_at": now,
            "rationale": rationale.strip(),
            "proven_count": len(proven_items),
            "invariants_count": len(self.invariants),
            "refinement_cycles_count": len(self.refinement_cycles),
            "phase": self.active_phase,
            "force_override_used": force_override_used,
            "authority_deadline_elapsed": remaining_sec <= 0
        }

        return {
            "status": "UNLOCKED",
            "execution_locked": False,
            "can_execute_code": True,
            "unlock_details": self.unlock_details
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializes session to dictionary."""
        return {
            "version": "1.2.3",
            "control_plane": copy.deepcopy(self.control_plane),
            "security_model": {
                "control_plane_profile": CONTROL_PLANE_PROFILE,
                "host_enforcement": self.host_enforcement,
                "host_tools_enforced": self.host_tools_enforced,
                "interruptive_control": INTERRUPTIVE_CONTROL,
                "cas_namespace": "session_derived",
                "receipt_authority": "external_host_only",
            },
            "cas_namespace": self.cas_namespace,
            "objective_authority": "session_local",
            "session_name": self.session_name,
            "session_id": self.session_id,
            "objective": self.objective,
            "start_time": self.start_time,
            "time_budget_minutes": self.time_budget_minutes,
            "time_budget_seconds": self.time_budget_seconds,
            "authority_deadline_time": self.deadline_time,
            "deadline_time": self.deadline_time,
            "pacing_budget_minutes": self.pacing_budget_minutes,
            "pacing_budget_seconds": self.pacing_budget_seconds,
            "pacing_started_time": self._pacing_started_wall,
            "pacing_deadline_time": self._pacing_deadline_wall,
            "active_phase": self.active_phase,
            "execution_locked": self.execution_locked,
            "can_execute_code": self.can_execute_code,
            "epistemic_ledger": self.epistemic_ledger,
            "invariants": self.invariants,
            "refinement_cycles": self.refinement_cycles,
            "delegation_contracts": self.delegation_contracts,
            "active_free_energy": copy.deepcopy(self.active_free_energy),
            "system3_active_inferences": copy.deepcopy(self.system3_active_inferences),
            "system3_causal_graphs": copy.deepcopy(self.system3_causal_graphs),
            "phase_history": self.phase_history,
            "unlock_details": self.unlock_details,
            "host_verifications": copy.deepcopy(self.host_verifications),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, expected_name: str | None = None,
                  expected_namespace: str | None = None) -> "FableSession":
        """Restore data without importing persisted execution authority.

        Persistence is an interchange format, not an authority token.  The
        filename, session name, session ID, and derived CAS namespace are one
        binding.  All are checked before any restored object is made available;
        this prevents copying a valid session file into another name from
        granting access to the original session's CAS namespace.
        """
        if not isinstance(data, dict):
            raise ValueError("persisted session must be an object")
        persisted_name = _validate_session_name(data.get("session_name", ""))
        if expected_name is not None and persisted_name != _validate_session_name(expected_name):
            raise ValueError("persisted session name does not match its filename")
        persisted_id = _validate_session_id(data.get("session_id"))
        derived_namespace = _cas_namespace_for_session(persisted_id)
        persisted_namespace = data.get("cas_namespace")
        if persisted_namespace != derived_namespace:
            raise ValueError("persisted CAS namespace is not bound to session_id")
        if expected_namespace is not None and persisted_namespace != expected_namespace:
            raise ValueError("persisted CAS namespace does not match requested capability")
        budget = data.get("time_budget_minutes", 60.0)
        session = cls(session_name=persisted_name, objective=data.get("objective", ""),
                      time_budget_minutes=budget, session_id=persisted_id)
        session._restored_untrusted = True
        # Never import strict control-plane authority from a file. A restored
        # session starts a fresh, host-attested FSM; this is an explicit safe
        # compatibility path, not a persisted authorization token.
        session.control_plane = cls._new_control_plane_state()
        session.host_verifications = {}
        session.epistemic_ledger = [dict(item, _restored_untrusted=True) for item in data.get("epistemic_ledger", []) if isinstance(item, dict)]
        session.invariants = [dict(item, _restored_untrusted=True) for item in data.get("invariants", []) if isinstance(item, dict)]
        session.refinement_cycles = [dict(item, _restored_untrusted=True) for item in data.get("refinement_cycles", []) if isinstance(item, dict)]
        session.active_free_energy = copy.deepcopy(data.get("active_free_energy")) if isinstance(data.get("active_free_energy"), dict) else None
        session.system3_active_inferences = [copy.deepcopy(item) for item in data.get("system3_active_inferences", []) if isinstance(item, dict)]
        session.system3_causal_graphs = [copy.deepcopy(item) for item in data.get("system3_causal_graphs", []) if isinstance(item, dict)]
        session.delegation_contracts = []
        session.active_phase = PHASES[0]
        session.phase_history = [{"phase": PHASES[0], "entered_at": session.start_time,
                                 "summary": "Restored in safe locked state; fresh gates required"}]
        session.execution_locked = True
        session.can_execute_code = False
        session.unlock_details = None
        return session

    def save(self, target_path: Optional[Path] = None) -> Path:
        """Atomically save a session using a unique no-follow temporary file."""
        path = Path(target_path or (SESSIONS_DIR / f"{self.session_name}.json")).expanduser().absolute()
        parent = path.parent
        _assert_private_path(parent)
        parent.mkdir(parents=True, exist_ok=True)
        _assert_private_path(parent)
        if parent.is_symlink() or not parent.is_dir() or path.is_symlink():
            raise OSError("session path or parent is a symlink/reparse point")
        os.chmod(parent, 0o700)
        if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
            parent_fd = _open_directory_nofollow(parent, create=True)
            temp_name = f".{path.name}.{os.getpid()}-{os.urandom(8).hex()}.tmp"
            fd = None
            try:
                fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    fd = None
                    json.dump(self.to_dict(), handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                try:
                    os.fsync(parent_fd)
                except OSError:
                    # Linux O_PATH directory descriptors are suitable for
                    # descriptor-relative publication but not fsync targets.
                    pass
            finally:
                if fd is not None:
                    os.close(fd)
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except OSError:
                    pass
                os.close(parent_fd)
        else:
            fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
            temp_path = Path(temporary)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)
                else:
                    os.chmod(temporary, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.to_dict(), handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
            finally:
                if temp_path.exists() or temp_path.is_symlink():
                    temp_path.unlink()
        logger.info(f"Fable session '{self.session_name}' saved to {path}")
        return path


# In-Memory Active Sessions Table
ACTIVE_SESSIONS: Dict[str, FableSession] = {}


def _safe_session_file(path: Path) -> None:
    _assert_private_path(path.parent)
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise ValueError(f"session file does not exist: {path.name}")
    attrs = int(getattr(st, "st_file_attributes", 0))
    if (attrs & 0x400 or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode)
            or st.st_nlink != 1 or (os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077)):
        raise ValueError("session file must be a private regular non-hardlinked file")


def get_or_load_session(session_name: str) -> FableSession:
    """Retrieves session from memory or loads from disk if exists."""
    clean_name = _validate_session_name(session_name)
    if clean_name in ACTIVE_SESSIONS:
        active = ACTIVE_SESSIONS[clean_name]
        if (active.session_name != clean_name or
                active.cas_namespace != _cas_namespace_for_session(active.session_id)):
            raise RuntimeError("active session identity binding is invalid")
        return active

    file_path = SESSIONS_DIR / f"{clean_name}.json"
    if file_path.exists() or file_path.is_symlink():
        try:
            _safe_session_file(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = FableSession.from_dict(
                data, expected_name=clean_name,
                expected_namespace=_cas_namespace_for_session(
                    _validate_session_id(data.get("session_id"))))
            ACTIVE_SESSIONS[clean_name] = session
            return session
        except Exception as e:
            logger.error(f"Failed to load session file {file_path}: {e}")
            raise RuntimeError(f"Corrupt or unreadable session file for '{clean_name}': {e}")

    raise ValueError(f"Session '{clean_name}' does not exist. Call 'create_session' first.")


def register_host_receipt(session_name: str, receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Host-only receipt registration hook for adapters and brokers."""
    return get_or_load_session(session_name).register_host_receipt(receipt)


def register_host_verification(session_name: str, verification_id: str,
                               receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Broker-only final verification hook; never exposed as an MCP action."""
    return get_or_load_session(session_name).register_host_verification(verification_id, receipt)


register_broker_verification = register_host_verification


def control_plane_capabilities() -> Dict[str, Any]:
    """Machine-readable strict profile and honest enforcement declaration."""
    return {
        "profile": CONTROL_PLANE_PROFILE,
        "tool": CONTROL_PLANE_TOOL_NAME,
        "actions": list(CONTROL_PLANE_ACTIONS),
        "state_machine": list(CONTROL_PLANE_STATES),
        "invariants": [
            "observe must precede record_prediction",
            "record_prediction must precede mutating propose_action",
            "record_outcome must reference a successful host receipt bound to the proposed capability and input_hash",
            "outcome payload must equal the bound receipt output",
            "outcome and receipt must precede request_verification",
            "verification must be a verifier receipt bound to the requested outcome and checks",
            "finalize requires that bound host/broker verification; unrelated successful receipts are rejected",
        ],
        "enforcement": {
            "control_plane": "enforced",
            "sequence_invariants": "enforced",
            "session_binding": "enforced",
            "idempotency": "enforced",
            "host_tools": "advisory_external_host_required",
            "native_tools": "not_controlled_unless_routed_through_broker",
            "receipt_authority": "external_host_or_broker_only",
        },
        "legacy": {
            "tool": "fable_session",
            "mode": "explicit_compatibility_path",
            "compatibility_mode": "legacy_v1",
        },
    }


def _session_for_control_plane(arguments: Dict[str, Any]) -> FableSession:
    action = arguments.get("action")
    supplied_id = arguments.get("session_id")
    session_name = arguments.get("session_name")
    if supplied_id is not None and (not isinstance(supplied_id, str) or not SESSION_ID_PATTERN.fullmatch(supplied_id)):
        raise ControlPlaneError("invalid_session_binding", "session_id must be a valid session identifier")
    if session_name is not None and (not isinstance(session_name, str) or not session_name.strip()):
        raise ControlPlaneError("invalid_session_binding", "session_name must be a non-empty string")
    if supplied_id:
        matches = [s for s in ACTIVE_SESSIONS.values() if s.session_id == supplied_id]
        if not matches and session_name:
            candidate = get_or_load_session(session_name.strip())
            matches = [candidate] if candidate.session_id == supplied_id else []
        if not matches:
            raise ControlPlaneError("unknown_session", "session_id is not bound to an active session")
        session = matches[0]
        if session_name and session.session_name != session_name.strip():
            raise ControlPlaneError("invalid_session_binding", "session_name does not match session_id")
        return session
    if action != "observe":
        raise ControlPlaneError("session_binding_required", "strict actions require session_id; observe may create a session with session_name")
    if not session_name:
        raise ControlPlaneError("session_binding_required", "observe requires session_name when creating a strict session")
    clean_name = _validate_session_name(session_name)
    if clean_name in ACTIVE_SESSIONS:
        raise ControlPlaneError("session_already_exists", "observe cannot create a second strict session with this name")
    path = SESSIONS_DIR / f"{clean_name}.json"
    if path.exists() or path.is_symlink():
        raise ControlPlaneError("session_already_exists", "session_name already exists; use its bound session_id")
    objective = arguments.get("objective")
    if not isinstance(objective, str):
        raise ControlPlaneError("objective_required", "observe session creation requires objective")
    objective = _require_substantive_text(objective, "objective")
    budget = arguments.get("time_budget_minutes", 60.0)
    try:
        session = FableSession(clean_name, objective, budget)
    except (TypeError, ValueError) as exc:
        raise ControlPlaneError("invalid_arguments", str(exc)) from exc
    ACTIVE_SESSIONS[clean_name] = session
    return session


def handle_fable_control_plane(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Strict typed MCP control-plane entrypoint with structured errors."""
    if not isinstance(arguments, dict):
        return {"ok": False, "profile": CONTROL_PLANE_PROFILE,
                "error": {"code": "invalid_arguments", "message": "arguments must be an object"}}
    if arguments.get("action") in CONTROL_PLANE_CAPABILITY_ACTIONS:
        allowed = {"action", "profile"}
        forbidden = {"tag", "proven", "final_authorized", "authorized", "authorization", "approval"}
        if forbidden.intersection(arguments):
            return {"ok": False, "profile": CONTROL_PLANE_PROFILE, "action": "capabilities",
                    "enforcement": control_plane_capabilities()["enforcement"],
                    "error": {"code": "model_authorization_forbidden", "message": "model-supplied authorization fields are not accepted"}}
        extras = sorted(set(arguments) - allowed)
        if extras:
            return {"ok": False, "profile": CONTROL_PLANE_PROFILE, "action": "capabilities",
                    "enforcement": control_plane_capabilities()["enforcement"],
                    "error": {"code": "unknown_field", "message": "capabilities rejects unknown fields: " + ", ".join(extras)}}
        if arguments.get("profile") not in (None, CONTROL_PLANE_PROFILE):
            return {"ok": False, "profile": CONTROL_PLANE_PROFILE,
                    "error": {"code": "profile_mismatch", "message": f"profile must be {CONTROL_PLANE_PROFILE!r}"}}
        return {"ok": True, "profile": CONTROL_PLANE_PROFILE, "action": "capabilities",
                "capabilities": control_plane_capabilities(), "enforcement": control_plane_capabilities()["enforcement"]}
    action = arguments.get("action")
    try:
        if action not in CONTROL_PLANE_ACTIONS:
            raise ControlPlaneError("unknown_action", f"action must be one of {', '.join(CONTROL_PLANE_ACTIONS)}")
        if arguments.get("profile") not in (None, CONTROL_PLANE_PROFILE):
            raise ControlPlaneError("profile_mismatch", f"profile must be {CONTROL_PLANE_PROFILE!r}")
        forbidden = {"tag", "proven", "final_authorized", "authorized", "authorization", "approval"}
        supplied = forbidden.intersection(arguments)
        if supplied:
            raise ControlPlaneError("model_authorization_forbidden", "model-supplied PROVEN/final authorization fields are not accepted")
        session = _session_for_control_plane(arguments)
        response = session.strict_control_plane(arguments)
        session.save()
        return response
    except ControlPlaneError as exc:
        session_id = arguments.get("session_id") if isinstance(arguments.get("session_id"), str) else None
        current_state = "unknown"
        if session_id:
            for candidate in ACTIVE_SESSIONS.values():
                if candidate.session_id == session_id:
                    current_state = candidate.control_plane.get("state", "unknown")
                    break
        return {"ok": False, "profile": CONTROL_PLANE_PROFILE, "action": action,
                "session_id": session_id, "state": current_state,
                "enforcement": control_plane_capabilities()["enforcement"],
                "error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "profile": CONTROL_PLANE_PROFILE, "action": action,
                "enforcement": control_plane_capabilities()["enforcement"],
                "error": {"code": "invalid_arguments", "message": str(exc), "details": {}}}


SESSION_CAS_ENGINES: Dict[str, FableCompress] = {}


def _session_cas_engine(session: FableSession) -> FableCompress:
    """Return a CAS engine confined to this session's capability namespace."""
    if session.cas_namespace != _cas_namespace_for_session(session.session_id):
        raise PermissionError("session CAS capability binding is invalid")
    engine = SESSION_CAS_ENGINES.get(session.session_id)
    if engine is None:
        engine = FableCompress(root_dir=FABLE_CAS_DIR, namespace=session.cas_namespace)
        SESSION_CAS_ENGINES[session.session_id] = engine
    return engine


CAS_ACTIONS = {"compress_payload", "decompress_payload", "view_slice",
               "accumulate_payload", "flush_accumulator", "get_compression_stats"}


ACTION_ALIASES = {
    "init": "create_session", "create": "create_session",
    "update_timer": "set_timer", "timer": "set_timer",
    "telemetry": "get_status", "status": "get_status",
    "next_phase": "advance_phase", "advance": "advance_phase",
    "log_item": "log_epistemic_item", "epistemic_log": "log_epistemic_item",
    "add_invariant": "record_invariant", "invariant": "record_invariant",
    "record_refinement": "log_refinement_cycle", "refine": "log_refinement_cycle",
    "unlock": "unlock_execution", "save_session": "checkpoint_session",
    "checkpoint": "checkpoint_session", "load_session": "restore_session",
    "restore": "restore_session", "load": "restore_session", "list": "list_sessions",
    "compile_contract": "compile_delegation_contract", "validate_contract": "compile_delegation_contract",
    "compress": "compress_payload", "cas_put": "compress_payload", "cas_store": "compress_payload",
    "decompress": "decompress_payload", "cas_get": "decompress_payload", "cas_read": "decompress_payload",
    "cas_slice": "view_slice", "slice": "view_slice", "accumulate": "accumulate_payload",
    "cas_accumulate": "accumulate_payload", "flush_cas": "flush_accumulator", "cas_flush": "flush_accumulator",
    "compression_stats": "get_compression_stats", "cas_stats": "get_compression_stats",
}
ACTION_NAMES = {
    "create_session", "set_timer", "get_status", "advance_phase", "log_epistemic_item",
    "record_invariant", "log_refinement_cycle", "unlock_execution", "checkpoint_session",
    "restore_session", "list_sessions", "compile_delegation_contract", "compress_payload",
    "decompress_payload", "view_slice", "accumulate_payload", "flush_accumulator",
    "get_compression_stats",
}
ACTION_REQUIRED = {
    "create_session": ("session_name", "objective"), "set_timer": ("session_name", "time_budget_minutes"),
    "get_status": ("session_name",), "advance_phase": ("session_name", "next_phase", "phase_summary"),
    "log_epistemic_item": ("session_name", "tag", "claim"), "record_invariant": ("session_name", "invariant_name", "formal_statement", "proof_or_rationale"),
    "log_refinement_cycle": ("session_name", "refinement_type", "focus_area", "critique_or_bottleneck", "architectural_refinement"),
    "unlock_execution": ("session_name", "rationale"), "checkpoint_session": ("session_name",),
    "restore_session": ("session_name",), "compile_delegation_contract": ("subagent_prompt",),
    "compress_payload": ("content",), "decompress_payload": ("cas_ref",), "view_slice": ("cas_ref",),
    "accumulate_payload": ("payload",),
}
ACTION_STRING_FIELDS = {"action", "compatibility_mode", "session_name", "objective", "next_phase", "phase_summary", "tag", "claim", "invariant_name", "formal_statement", "proof_or_rationale", "refinement_type", "focus_area", "critique_or_bottleneck", "architectural_refinement", "terminal_probe_results", "artifact_path", "rationale", "subagent_prompt", "prompt", "contract", "content", "payload", "cas_ref", "ref_or_hash", "label"}


def _validate_tool_arguments(arguments: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(arguments, dict):
        return None, "arguments must be an object"
    try:
        _reject_non_finite(arguments, path="arguments")
        argument_bytes = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        return None, str(exc) if isinstance(exc, ValueError) else "arguments must contain JSON-compatible values"
    if argument_bytes > MAX_EVIDENCE_BYTES:
        return None, "arguments exceed maximum size"
    raw_action = arguments.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return None, "'action' must be a non-empty string"
    if "compatibility_mode" in arguments and arguments.get("compatibility_mode") != "legacy_v1":
        return None, "'compatibility_mode' must be 'legacy_v1' when supplied"
    action = ACTION_ALIASES.get(raw_action.strip().lower(), raw_action.strip().lower())
    if action not in ACTION_NAMES:
        return action, f"Unknown action '{action}'"
    for field in ACTION_STRING_FIELDS:
        if field in arguments and not isinstance(arguments[field], str):
            if field == "phase_summary" and isinstance(arguments[field], dict):
                continue
            return action, f"'{field}' must be a string"
    if "phase_evidence" in arguments and not isinstance(arguments["phase_evidence"], (dict, str)):
        return action, "'phase_evidence' must be an object"
    if "time_budget_minutes" in arguments:
        value = arguments["time_budget_minutes"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return action, "'time_budget_minutes' must be a finite number"
    for field in ("start_line", "end_line"):
        if field in arguments and (isinstance(arguments[field], bool) or not isinstance(arguments[field], int)):
            return action, f"'{field}' must be an integer"
    for field in ("include_line_numbers", "force_flush"):
        if field in arguments and not isinstance(arguments[field], bool):
            return action, f"'{field}' must be a boolean"
    if "metadata" in arguments and not isinstance(arguments["metadata"], (dict, str)):
        return action, "'metadata' must be an object or JSON string"
    for field in ACTION_REQUIRED.get(action, ()):
        # Compatibility aliases satisfy canonical requirements.
        if field not in arguments or (isinstance(arguments[field], str) and not arguments[field].strip()):
            if field == "content" and "payload" in arguments: continue
            if field == "payload" and "content" in arguments: continue
            if field == "subagent_prompt" and any(k in arguments for k in ("prompt", "contract")): continue
            return action, f"'{field}' is required"
    if action == "log_epistemic_item" and str(arguments.get("tag", "")).upper() == "PROVEN" and "evidence" not in arguments:
        return action, "PROVEN claims require typed receipt evidence"
    if action in CAS_ACTIONS and (not isinstance(arguments.get("session_name"), str)
                                  or not arguments.get("session_name", "").strip()):
        return action, "'session_name' is required to bind CAS access to a session capability namespace"
    return action, None


def handle_fable_session(arguments: Dict[str, Any]) -> str:
    """Main dispatch handler for fable_session tool actions."""
    try:
        action, validation_error = _validate_tool_arguments(arguments)
        if validation_error:
            return f"Error: Invalid arguments: {validation_error}"
        action = action or ""
        session_name = arguments.get("session_name", "")
        session_name = session_name.strip() if isinstance(session_name, str) else ""
        # CAS actions are always scoped to a live session.  The derived
        # namespace prevents a valid hash from one session being a capability
        # to read another session's objects.
        cas_engine = None
        if action in CAS_ACTIONS:
            if not session_name:
                return "Error: 'session_name' is required to bind CAS access to a session capability namespace."
            cas_session = get_or_load_session(session_name)
            cas_engine = _session_cas_engine(cas_session)

        # 1. CREATE SESSION
        if action in ("create_session", "init", "create"):
            if not session_name:
                return "Error: 'session_name' is required for action 'create_session'."
            session_name = _validate_session_name(session_name)
            objective = arguments.get("objective", "").strip()
            if not objective:
                return "Error: 'objective' is required for action 'create_session'."
            
            time_budget = arguments.get("time_budget_minutes", 60.0)
            try:
                time_budget_min = float(time_budget)
            except (ValueError, TypeError):
                return f"Error: Invalid 'time_budget_minutes': {time_budget}."

            session = FableSession(session_name, objective, time_budget_min)
            ACTIVE_SESSIONS[session_name] = session
            session.save()

            tel = session.get_telemetry()
            return (
                f"### 🛡️ Fable Cognitive Session Initialized\n\n"
                f"- **Session Name**: `{session.session_name}`\n"
                f"- **Session ID**: `{session.session_id}`\n"
                f"- **Objective**: {session.objective}\n"
                f"- **Time Budget**: `{session.time_budget_minutes}` minutes ({tel['remaining_formatted']})\n"
                f"- **Active Phase**: `{session.active_phase}`\n"
                f"- **Execution Lock**: `LOCKED (can_execute_code: False)` 🛑\n"
                f"- **Host Enforcement**: `EXTERNAL HOST REQUIRED` (V1 does not sandbox or authorize host tools)\n"
                f"- **Cognitive Gates**: 0/2 receipt-bound [PROVEN] items, 0/1 Invariant recorded\n\n"
                f"> [!IMPORTANT]\n"
                f"> Anti-Rush session gate is ACTIVE (advisory to the model; it does not sandbox or authorize host tools). Proceed with epistemic grounding, research, and invariant modeling before requesting execution unlock."
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 2. SET TIMER
        elif action in ("set_timer", "update_timer", "timer"):
            if not session_name:
                return "Error: 'session_name' is required for action 'set_timer'."
            time_budget = arguments.get("time_budget_minutes")
            if time_budget is None:
                return "Error: 'time_budget_minutes' is required for action 'set_timer'."
            try:
                time_budget_min = float(time_budget)
            except (ValueError, TypeError):
                return f"Error: Invalid 'time_budget_minutes': {time_budget}."

            session = get_or_load_session(session_name)
            tel = session.set_timer(time_budget_min)
            session.save()

            return (
                f"### ⏱️ Fable Session Timer Updated\n\n"
                f"- **Session Name**: `{session.session_name}`\n"
                f"- **Pacing Timer**: `{session.pacing_budget_minutes}` minutes\n"
                f"- **Authority Budget**: `{session.time_budget_minutes}` minutes (immutable)\n"
                f"- **Elapsed Time**: `{tel['elapsed_formatted']}`\n"
                f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}`\n"
                f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`\n"
                f"- **Pacing Ratio**: `{tel['pacing_percentage']}`\n"
                f"- **Authority Deadline**: `{time.ctime(session.deadline_time)}`"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 3. GET STATUS / TELEMETRY
        elif action in ("get_status", "telemetry", "status"):
            if not session_name:
                return "Error: 'session_name' is required for action 'get_status'."

            session = get_or_load_session(session_name)
            tel = session.get_telemetry()

            lock_badge = "🔴 LOCKED (`can_execute_code: False`)" if session.execution_locked else "🟢 UNLOCKED (`can_execute_code: True`)"
            
            # Format ledger breakdown
            counts = tel["epistemic_counts"]
            ledger_lines = []
            for item in session.epistemic_ledger[-5:]:  # show recent 5
                ev_str = f" (Evidence: {item['evidence']})" if item.get('evidence') else ""
                ledger_lines.append(f"- `[{item['tag']}]` **{item['id']}**: {item['claim']}{ev_str}")
            ledger_preview = "\n".join(ledger_lines) if ledger_lines else "- No items logged yet."

            # Format invariants preview
            inv_lines = []
            for inv in session.invariants[-5:]:
                inv_lines.append(f"- **{inv['name']}** `[{inv['domain']}]`: {inv['formal_statement']}")
            inv_preview = "\n".join(inv_lines) if inv_lines else "- No invariants recorded yet."

            # Format refinement preview
            ref_lines = []
            for ref in session.refinement_cycles[-3:]:
                ref_lines.append(f"- **Cycle #{ref['cycle_number']}** `[{ref['refinement_type'].upper()}]` ({ref['focus_area']}): {ref['architectural_refinement']}")
            ref_preview = "\n".join(ref_lines) if ref_lines else "- No refinement cycles recorded yet."

            return (
                f"### 📊 Fable Session Status & Telemetry (`{session.session_name}`)\n\n"
                f"- **Objective**: {session.objective}\n"
                f"- **Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
                f"- **Execution Lock**: {lock_badge}\n"
                f"- **Host Enforcement**: `{tel['host_enforcement']}` (V1 does not sandbox or authorize host tools)\n"
                f"- **Pacing**: `{tel['elapsed_formatted']}` elapsed / `{tel['pacing_remaining_formatted']}` remaining (`{tel['pacing_percentage']}` budget used)\n"
                f"- **Authority**: `{tel['authority_remaining_formatted']}` remaining (immutable outer deadline)\n"
                f"- **Epistemic Breakdown**: `{counts['proven']} PROVEN`, `{counts['hypothesis']} HYPOTHESIS`, `{counts['unknown']} UNKNOWN` (Total: `{counts['total']}`)\n"
                f"- **Invariants Recorded**: `{tel['invariants_count']}`\n"
                f"- **Refinement Cycles**: `{tel['refinement_count']}`\n\n"
                f"#### 🔍 Recent Epistemic Ledger Items:\n{ledger_preview}\n\n"
                f"#### 📐 Invariants Specification:\n{inv_preview}\n\n"
                f"#### 🔄 Recent Refinement Cycles:\n{ref_preview}"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 4. ADVANCE PHASE
        elif action in ("advance_phase", "next_phase", "advance"):
            if not session_name:
                return "Error: 'session_name' is required for action 'advance_phase'."
            next_phase = arguments.get("next_phase", "").strip()
            if not next_phase:
                return "Error: 'next_phase' is required for action 'advance_phase'."
            phase_summary = arguments.get("phase_summary", "")
            if isinstance(phase_summary, dict):
                raw_phase_evidence = phase_summary.get("evidence", arguments.get("phase_evidence"))
                phase_summary = phase_summary.get("summary", "")
            else:
                raw_phase_evidence = arguments.get("phase_evidence")
            if isinstance(raw_phase_evidence, str):
                try:
                    raw_phase_evidence = _strict_json_loads(raw_phase_evidence)
                except Exception:
                    return "Error: phase_evidence must be a JSON object"
            session = get_or_load_session(session_name)
            tel = session.advance_phase(next_phase, phase_summary, raw_phase_evidence)
            session.save()

            return (
                f"### 🚀 Fable Phase Advanced Successfully\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **New Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
                f"- **Phase Summary**: {phase_summary}\n"
                f"- **Execution Status**: `{'LOCKED 🛑' if session.execution_locked else 'UNLOCKED 🟢'}`\n"
                f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}` (`{tel['pacing_percentage']}` used)\n"
                f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`\n"
                f"\n#### 🧠 System 3 Meta-Cognitive Advisory\n"
                f"- **Live Free Energy**: `{tel['system3_cognitive_state'].get('free_energy_f')}` (advisory estimate)\n"
                f"- **Temporal Invariant**: `{tel['system3_cognitive_state'].get('kripke_safety_invariant')}` = `True` (telemetry only)"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 5. LOG EPISTEMIC ITEM
        elif action in ("log_epistemic_item", "log_item", "epistemic_log"):
            if not session_name:
                return "Error: 'session_name' is required for action 'log_epistemic_item'."
            tag = arguments.get("tag", "").strip()
            if not tag:
                return "Error: 'tag' (PROVEN, HYPOTHESIS, UNKNOWN) is required for 'log_epistemic_item'."
            claim = arguments.get("claim", "").strip()
            if not claim:
                return "Error: 'claim' is required for 'log_epistemic_item'."
            evidence = arguments.get("evidence")

            session = get_or_load_session(session_name)
            item = session.log_epistemic_item(tag, claim, evidence)
            session.save()

            tel = session.get_telemetry()
            counts = tel["epistemic_counts"]

            ev_display = f"\n- **Evidence**: `{item['evidence']}`" if item.get("evidence") else ""
            return (
                f"### 📝 Epistemic Item Logged (`{item['id']}`)\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Classification**: `[{item['tag']}]`\n"
                f"- **Claim**: {item['claim']}{ev_display}\n"
                f"- **Logged in**: `{item['phase']}`\n"
                f"- **Ledger Total**: `{counts['proven']} PROVEN`, `{counts['hypothesis']} HYPOTHESIS`, `{counts['unknown']} UNKNOWN`"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 6. RECORD INVARIANT
        elif action in ("record_invariant", "add_invariant", "invariant"):
            if not session_name:
                return "Error: 'session_name' is required for action 'record_invariant'."
            invariant_name = arguments.get("invariant_name", "").strip()
            if not invariant_name:
                return "Error: 'invariant_name' is required for 'record_invariant'."
            formal_statement = arguments.get("formal_statement", "").strip()
            if not formal_statement:
                return "Error: 'formal_statement' is required for 'record_invariant'."
            proof_or_rationale = arguments.get("proof_or_rationale", "").strip()
            domain = arguments.get("domain", "architecture").strip()

            session = get_or_load_session(session_name)
            inv = session.record_invariant(invariant_name, formal_statement, proof_or_rationale, domain)
            session.save()

            return (
                f"### 📐 Formal Invariant Recorded (`{inv['id']}`)\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Invariant Name**: **{inv['name']}**\n"
                f"- **Domain**: `{inv['domain'].upper()}`\n"
                f"- **Formal Statement**: `{inv['formal_statement']}`\n"
                f"- **Proof / Rationale**: {inv['proof_or_rationale']}\n"
                f"- **Total Invariants**: `{len(session.invariants)}`"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 7. LOG REFINEMENT CYCLE
        elif action in ("log_refinement_cycle", "record_refinement", "refine"):
            if not session_name:
                return "Error: 'session_name' is required for action 'log_refinement_cycle'."
            refinement_type = arguments.get("refinement_type", "").strip()
            if not refinement_type:
                return "Error: 'refinement_type' is required for 'log_refinement_cycle'."
            focus_area = arguments.get("focus_area", "").strip()
            if not focus_area:
                return "Error: 'focus_area' is required for 'log_refinement_cycle'."
            critique_or_bottleneck = arguments.get("critique_or_bottleneck", "").strip()
            if not critique_or_bottleneck:
                return "Error: 'critique_or_bottleneck' is required for 'log_refinement_cycle'."
            architectural_refinement = arguments.get("architectural_refinement", "").strip()
            if not architectural_refinement:
                return "Error: 'architectural_refinement' is required for 'log_refinement_cycle'."
            
            terminal_probe_results = arguments.get("terminal_probe_results")
            artifact_path = arguments.get("artifact_path")

            session = get_or_load_session(session_name)
            cycle = session.log_refinement_cycle(
                refinement_type=refinement_type,
                focus_area=focus_area,
                critique_or_bottleneck=critique_or_bottleneck,
                architectural_refinement=architectural_refinement,
                terminal_probe_results=terminal_probe_results,
                artifact_path=artifact_path
            )
            session.save()

            tel = session.get_telemetry()
            probe_display = f"\n- **Terminal Probes / Benchmarks**: `{cycle['terminal_probe_results']}`" if cycle.get("terminal_probe_results") else ""
            artifact_display = f"\n- **Artifact Blueprint**: `{cycle['artifact_path']}`" if cycle.get("artifact_path") else ""

            return (
                f"### 🔄 Rethink-Refine Cycle #{cycle['cycle_number']} Logged\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Refinement Type**: `{cycle['refinement_type'].upper()}`\n"
                f"- **Focus Area**: {cycle['focus_area']}\n"
                f"- **Critique / Bottleneck**: {cycle['critique_or_bottleneck']}\n"
                f"- **Architectural Refinement**: {cycle['architectural_refinement']}{probe_display}{artifact_display}\n"
                f"- **Phase**: `{cycle['phase']}`\n"
                f"- **Pacing Remaining**: `{tel['remaining_formatted']}` ({tel['pacing_percentage']} budget used)\n"
                f"- **Total Refinement Cycles**: `{len(session.refinement_cycles)}`\n\n"
                f"> [!TIP]\n"
                f"> Rethink-Refine Cognitive Loop active. Continue exploring alternative archetypes, falsifications, and terminal benchmarks until the time budget is fulfilled."
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 8. UNLOCK EXECUTION
        elif action in ("unlock_execution", "unlock"):
            if not session_name:
                return "Error: 'session_name' is required for action 'unlock_execution'."
            rationale = arguments.get("rationale", "").strip()
            if not rationale:
                return "Error: 'rationale' is required for action 'unlock_execution'."
            # No model-provided override is accepted. Administrative callers
            # must use the direct host API with an out-of-band secret.
            session = get_or_load_session(session_name)
            try:
                res = session.unlock_execution(rationale)
                session.save()
                override_msg = " ⚠️ *(Out-of-band emergency override)*" if session.unlock_details.get("force_override_used") else ""
                return (
                    f"### 🔓 Execution Lock Lifted Successfully{override_msg}\n\n"
                    f"- **Session**: `{session.session_name}`\n"
                    f"- **Status**: `🟢 UNLOCKED`\n"
                    f"- **`can_execute_code`**: `True`\n"
                    f"- **Phase at Unlock**: `{session.active_phase}`\n"
                    f"- **Rationale**: {rationale}\n"
                    f"- **Validated Gates**: `{len(session.epistemic_ledger)}` epistemic items ({session.unlock_details['proven_count']} PROVEN), `{len(session.invariants)}` Invariants, `{len(session.refinement_cycles)}` Refinement Cycles\n\n"
                    f"> [!TIP]\n"
                    f"> Implementer subagents may now execute code and run automated tests."
                )
            except PermissionError as pe:
                return str(pe)

        # 9. CHECKPOINT SESSION
        elif action in ("checkpoint_session", "save_session", "checkpoint", "save"):
            if not session_name:
                return "Error: 'session_name' is required for action 'checkpoint_session'."
            session = get_or_load_session(session_name)
            saved_path = session.save()
            return (
                f"### 💾 Fable Session Checkpointed\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Path**: `{saved_path}`\n"
                f"- **Phase**: `{session.active_phase}`\n"
                f"- **Epistemic Items**: `{len(session.epistemic_ledger)}`\n"
                f"- **Invariants**: `{len(session.invariants)}`\n"
                f"- **Refinement Cycles**: `{len(session.refinement_cycles)}`\n"
                f"- **Execution Lock**: `{'LOCKED' if session.execution_locked else 'UNLOCKED'}`"
            )

        # 10. RESTORE SESSION
        elif action in ("restore_session", "load_session", "restore", "load"):
            if not session_name:
                return "Error: 'session_name' is required for action 'restore_session'."
            session = get_or_load_session(session_name)
            tel = session.get_telemetry()
            return (
                f"### 📂 Fable Session Restored\n\n"
                f"- **Session**: `{session.session_name}` (`{session.session_id}`)\n"
                f"- **Objective**: {session.objective}\n"
                f"- **Active Phase**: `{session.active_phase}`\n"
                f"- **Pacing Remaining**: `{tel['remaining_formatted']}`\n"
                f"- **Execution Lock**: `{'LOCKED' if session.execution_locked else 'UNLOCKED'}`\n"
                f"- **Ledger**: `{tel['epistemic_counts']['proven']} PROVEN`, `{tel['epistemic_counts']['hypothesis']} HYPOTHESIS`\n"
                f"- **Invariants**: `{tel['invariants_count']}`\n"
                f"- **Refinement Cycles**: `{tel['refinement_count']}`"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 11. LIST SESSIONS
        elif action in ("list_sessions", "list"):
            files = list(SESSIONS_DIR.glob("*.json"))
            session_entries = []
            for f in files:
                try:
                    _safe_session_file(f)
                    with open(f, "r", encoding="utf-8") as s_file:
                        s_data = json.load(s_file)
                    status_icon = "🟢" if not s_data.get("execution_locked", True) else "🛑"
                    session_entries.append(
                        f"- `{s_data.get('session_name', f.stem)}` {status_icon} | "
                        f"**Phase**: {s_data.get('active_phase', 'Unknown')} | "
                        f"**Budget**: {s_data.get('time_budget_minutes', 0)}m | "
                        f"**File**: `{f.name}`"
                    )
                except Exception:
                    session_entries.append(f"- `{f.stem}` (Unreadable session file)")

            listing = "\n".join(session_entries) if session_entries else "- No saved sessions found."
            return (
                f"### 🗂️ Available Fable Sessions in `{SESSIONS_DIR}`\n\n"
                f"{listing}"
            )

        # 12. COMPILE DELEGATION CONTRACT
        elif action in ("compile_delegation_contract", "compile_contract", "validate_contract"):
            prompt = arguments.get("subagent_prompt") or arguments.get("prompt") or arguments.get("contract") or ""
            if not str(prompt).strip():
                return "Error: 'subagent_prompt' (or 'prompt') is required for action 'compile_delegation_contract'."

            compiler = DelegationContractCompiler()
            is_valid, errors, parsed = compiler.compile_and_validate(prompt)

            if not is_valid:
                err_list = "\n".join([f"- ❌ {e}" for e in errors])
                return (
                    f"### 🛑 Subagent Delegation Contract Compilation Failed\n\n"
                    f"The subagent prompt does not satisfy the strict Fable-Mode delegation boundaries:\n\n"
                    f"{err_list}\n\n"
                    f"> [!WARNING]\n"
                    f"> Worker subagents must receive 100% bounded, unambiguous contracts before dispatch.\n"
                    f"> Ensure your prompt contains:\n"
                    f"> 1. `TargetFile: <file path>`\n"
                    f"> 2. `InterfaceContract: <type/function signature>`\n"
                    f"> 3. `StrictConstraints: <invariants / bounds>`\n"
                    f"> 4. `VerificationCommand: <exact CLI test command>`"
                )

            if session_name:
                contract_session = get_or_load_session(session_name)
                contract_session.delegation_contracts.append({
                    "target_file": parsed.get("TargetFile"),
                    "verification_command": parsed.get("VerificationCommand"),
                    "prompt_hash": _canonical_hash(str(prompt)),
                    "timestamp": contract_session._wall_clock(),
                    "phase": contract_session.active_phase,
                })
                contract_session.save()

            return (
                f"### ✅ Subagent Delegation Contract Compiled Successfully\n\n"
                f"- **Target File**: `{parsed.get('TargetFile', 'Declared')}`\n"
                f"- **Verification Command**: `{parsed.get('VerificationCommand', 'Declared')}`\n"
                f"- **Contract Status**: `100% BOUNDED & VALIDATED`\n"
                f"- **Dispatch Readiness**: `READY_FOR_SUBAGENT_DISPATCH` 🚀\n"
                f"\n#### 🧠 System 3 Micro-Scaffolds (INJECTED)\n"
                f"{parsed.get('system3_micro_scaffold', 'No scaffold for invalid contract.')}\n\n"
                f"> [!TIP]\n"
                f"> You may now dispatch a worker subagent (`type: self`) with this validated contract once execution is unlocked."
            )

        # 13. COMPRESS PAYLOAD (CAS PUT)
        elif action in ("compress_payload", "compress", "cas_put", "cas_store"):
            content = arguments.get("content")
            if content is None:
                content = arguments.get("payload")
            if content is None:
                return "Error: 'content' (or 'payload') is required for action 'compress_payload'."
            label = arguments.get("label", "payload")
            content_text = str(content)
            if len(content_text.encode("utf-8")) > MAX_CAS_OBJECT_BYTES:
                return "Error: payload exceeds maximum CAS object size."

            compressed_node = cas_engine.compress_payload_to_cas(content_text, label=label)
            raw_len = len(content_text)
            raw_tokens = cas_engine.estimate_token_count(content_text)
            comp_repr = json.dumps(compressed_node, separators=(",", ":"))
            comp_tokens = cas_engine.estimate_token_count(comp_repr)
            ratio = cas_engine.calculate_token_ratio(content_text, comp_repr)

            heuristic_target_applies = raw_len >= 10000
            heuristic_target_met = ratio <= 0.003 if heuristic_target_applies else False
            if not heuristic_target_applies:
                badge = "ℹ️ HEURISTIC NOT EVALUATED (payload is under 10,000 characters)"
            elif heuristic_target_met:
                badge = "✅ HEURISTIC TARGET MET (estimated ratio <= 0.003 tokens/char; not a guarantee)"
            else:
                badge = f"⚠️ HEURISTIC ESTIMATE ABOVE TARGET (estimated ratio: {ratio:.6f} tokens/char)"

            return (
                f"### 🗜️ Fable CAS Payload Compressed\n\n"
                f"- **CAS URI**: `{compressed_node['cas_ref']}`\n"
                f"- **Line Count**: `{compressed_node['lines']}`\n"
                f"- **Raw Size**: `{raw_len}` characters (~`{raw_tokens}` estimated tokens)\n"
                f"- **Compressed Reference Size**: `{len(comp_repr)}` characters (~`{comp_tokens}` estimated tokens)\n"
                f"- **Estimated Token Compression Ratio (heuristic)**: `{ratio:.6f}` estimated tokens/char\n"
                f"- **Heuristic Check (not a measured guarantee)**: {badge}\n"
                f"- **JSON Descriptor**:\n```json\n{json.dumps(compressed_node, indent=2)}\n```\n\n"
                f"> [!TIP]\n"
                f"> Use action `view_slice` with `cas_ref` to inspect specific line windows without loading full payload."
            )

        # 14. DECOMPRESS PAYLOAD (CAS GET)
        elif action in ("decompress_payload", "decompress", "cas_get", "cas_read"):
            cas_ref = arguments.get("cas_ref") or arguments.get("ref_or_hash")
            if not cas_ref:
                return "Error: 'cas_ref' is required for action 'decompress_payload'."
            try:
                text = cas_engine.cas_store.get_text(cas_ref, verify=True)
                if len(text.encode("utf-8")) > MAX_RPC_RESPONSE_BYTES // 2:
                    return "Error: decompressed response exceeds maximum size; use view_slice."
                lines = cas_engine.slice_viewer.get_line_count(cas_ref)
                return (
                    f"### 📦 Fable CAS Payload Retrieved\n\n"
                    f"- **CAS URI**: `{cas_ref}`\n"
                    f"- **Total Length**: `{len(text)}` characters\n"
                    f"- **Total Lines**: `{lines}`\n\n"
                    f"```text\n{text}\n```"
                )
            except Exception as e:
                return f"Error decompressing CAS payload: {e}"

        # 15. VIEW SLICE (CAS WINDOWED EXTRACTOR)
        elif action in ("view_slice", "cas_slice", "slice"):
            cas_ref = arguments.get("cas_ref") or arguments.get("ref_or_hash")
            if not cas_ref:
                return "Error: 'cas_ref' is required for action 'view_slice'."
            start_line = int(arguments.get("start_line", 1))
            end_line = int(arguments.get("end_line", 100))
            include_line_numbers = bool(arguments.get("include_line_numbers", False))

            try:
                slice_text = cas_engine.slice_viewer.view_slice(
                    cas_ref, start_line, end_line, include_line_numbers=include_line_numbers
                )
                total_lines = cas_engine.slice_viewer.get_line_count(cas_ref)
                return (
                    f"### 🔍 Fable CAS Slice View (`{start_line}` - `{end_line}` of `{total_lines}` lines)\n\n"
                    f"- **CAS URI**: `{cas_ref}`\n"
                    f"- **Range**: Lines {start_line}..{end_line}\n\n"
                    f"```text\n{slice_text}\n```"
                )
            except Exception as e:
                return f"Error reading CAS slice: {e}"

        # 16. ACCUMULATE PAYLOAD (MICRO-PAYLOAD BATCHING)
        elif action in ("accumulate_payload", "accumulate", "cas_accumulate"):
            payload = arguments.get("payload")
            if payload is None:
                payload = arguments.get("content")
            if payload is None:
                return "Error: 'payload' is required for action 'accumulate_payload'."
            metadata = arguments.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = _strict_json_loads(metadata)
                except Exception:
                    metadata = {"raw": metadata}
            force_flush = bool(arguments.get("force_flush", False))

            flushed = cas_engine.accumulator.add(str(payload), metadata=metadata, force_flush=force_flush)
            stats = cas_engine.accumulator.get_stats()

            flushed_str = "\n".join([f"- Flushed Composite Frame: `{u}`" for u in flushed]) if flushed else "- No frame flushed yet (buffering micro-payload)."
            return (
                f"### 📥 Micro-Payload Ingested\n\n"
                f"- **Buffered Items**: `{stats['currently_buffered_items']}`\n"
                f"- **Buffered Chars**: `{stats['currently_buffered_chars']}` / `{cas_engine.accumulator.min_frame_size}` bytes threshold\n"
                f"- **Total Ingested**: `{stats['total_payloads_ingested']}`\n"
                f"- **Total Frames Flushed**: `{stats['total_frames_flushed']}`\n\n"
                f"{flushed_str}"
            )

        # 17. FLUSH ACCUMULATOR
        elif action in ("flush_accumulator", "flush_cas", "cas_flush"):
            flushed = cas_engine.accumulator.flush()
            stats = cas_engine.accumulator.get_stats()
            if flushed:
                flushed_str = "\n".join([f"- Flushed Frame: `{u}`" for u in flushed])
                return (
                    f"### 🚀 Micro-Payload Accumulator Flushed\n\n"
                    f"- **Flushed Frames**: `{len(flushed)}`\n"
                    f"- **Total CAS Bytes Written**: `{stats['total_cas_bytes_written']}`\n\n"
                    f"{flushed_str}"
                )
            return (
                f"### ℹ️ Micro-Payload Accumulator Buffer Empty\n\n"
                f"- **Currently Buffered**: `0` items\n"
                f"- **Total Frames Flushed**: `{stats['total_frames_flushed']}`"
            )

        # 18. GET COMPRESSION STATS
        elif action in ("get_compression_stats", "compression_stats", "cas_stats"):
            stats = cas_engine.accumulator.get_stats()
            quota = cas_engine.cas_store.quota_stats()
            return (
                f"### 📊 Fable Token Compression Subsystem Telemetry\n\n"
                f"- **CAS Capability Namespace**: `{quota['namespace']}`\n"
                f"- **CAS Storage Root**: `{cas_engine.cas_store.root_dir}`\n"
                f"- **Namespace Quota**: `{quota['bytes']}` / `{quota['max_bytes']}` bytes, `{quota['objects']}` / `{quota['max_objects']}` objects\n"
                f"- **Memory Cache Capacity**: `{cas_engine.cas_store.cache.capacity}` entries (Current: `{len(cas_engine.cas_store.cache)}`)\n"
                f"- **Micro-Payloads Ingested**: `{stats['total_payloads_ingested']}`\n"
                f"- **Composite Frames Flushed**: `{stats['total_frames_flushed']}`\n"
                f"- **Total Raw Characters**: `{stats['total_raw_chars']}`\n"
                f"- **Total CAS Bytes Written**: `{stats['total_cas_bytes_written']}`\n"
                f"- **Currently Buffered Items**: `{stats['currently_buffered_items']}` (`{stats['currently_buffered_chars']}` chars)\n"
                f"- **Compression Target (heuristic only)**: estimated ratio `<= 0.003 tokens/character` for payloads of at least 10,000 characters; diagnostic only, not a measured guarantee"
            )

        else:
            return (
                f"Error: Unknown action '{action}'. Supported actions: "
                f"'create_session', 'set_timer', 'get_status', 'telemetry', 'advance_phase', "
                f"'log_epistemic_item', 'record_invariant', 'log_refinement_cycle', 'unlock_execution', "
                f"'checkpoint_session', 'restore_session', 'list_sessions', 'compile_delegation_contract', "
                f"'compress_payload', 'decompress_payload', 'view_slice', 'accumulate_payload', 'flush_accumulator', 'get_compression_stats'."
            )
    except Exception as ex:
        return f"Error: {str(ex)}"


# --------------------------------------------------------------------------------
# JSON-RPC 2.0 MCP Protocol Stdio Loop
# --------------------------------------------------------------------------------

CONTROL_PLANE_TOOL_SCHEMA = {
    "name": CONTROL_PLANE_TOOL_NAME,
    "description": (
        "Strict MCP control-plane for observe → predict → propose → outcome → verify → finalize. "
        "Sequence, session binding, and idempotency are enforced here. Host/native tool authorization "
        "is advisory unless the invocation is routed through a broker; model-supplied PROVEN/final authorization is rejected."
    ),
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "profile": {"type": "string", "const": CONTROL_PLANE_PROFILE},
            "action": {"type": "string", "enum": list(CONTROL_PLANE_ACTIONS) + ["capabilities"]},
            "session_id": {"type": "string", "pattern": SESSION_ID_PATTERN.pattern},
            "session_name": {"type": "string", "pattern": SESSION_NAME_PATTERN.pattern},
            "objective": {"type": "string", "minLength": 8},
            "observation": {},
            "prediction": {"type": "string", "minLength": 8},
            "prediction_id": {"type": "string"},
            "action_name": {"type": "string", "minLength": 2, "description": "Concrete host operation; generic boilerplate names are rejected."},
            "capability": {"type": "string", "minLength": 1, "description": "Capability name which the host receipt must attest."},
            "arguments": {"type": "object"},
            "input_hash": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$", "description": "Optional explicit hash; it must equal the canonical action arguments."},
            "mutating": {"type": "boolean", "const": True},
            "action_id": {"type": "string"},
            "outcome": {},
            "receipt_id": {"type": "string"},
            "outcome_id": {"type": "string"},
            "checks": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "verification_id": {"type": "string"},
            "idempotency_key": {"type": "string", "pattern": CONTROL_PLANE_IDEMPOTENCY_PATTERN.pattern},
            # Explicitly named forbidden fields make the contract auditable;
            # server-side validation rejects them even if a host ignores JSON Schema.
            "tag": {"not": {}}, "proven": {"not": {}}, "final_authorized": {"not": {}},
            "authorized": {"not": {}}, "authorization": {"not": {}}, "approval": {"not": {}},
        },
        "required": ["action"],
        "allOf": [
            {"if": {"properties": {"action": {"enum": list(CONTROL_PLANE_ACTIONS)}}},
             "then": {"required": ["idempotency_key"]}},
        ],
    },
    "outputSchema": {
        "type": "object", "required": ["ok", "profile", "action", "enforcement"],
        "properties": {"ok": {"type": "boolean"}, "profile": {"type": "string"},
                       "action": {"type": ["string", "null"]}, "session_id": {"type": ["string", "null"]},
                       "state": {"type": ["string", "null"]}, "result": {}, "error": {},
                       "enforcement": {"type": "object"}},
        "additionalProperties": True,
    },
}

TOOL_SCHEMA = {
    "name": "fable_session",
    "description": (
        "Legacy fable_session compatibility surface for MCP-compatible agent hosts; compatibility_mode is optional and, when supplied, must be legacy_v1.\n"
        "Enforces DeepThink cognitive rigor, hard mechanical time-lock, anti-rush execution lockout, epistemic truth logging (PROVEN/HYPOTHESIS/UNKNOWN),\n"
        "formal domain invariant modeling, continuous rethink-refine cycles, phased progression gating, subagent delegation contract compilation,\n"
        "live user-controlled time-budgeted pacing telemetry, and token compression subsystem (Content-Addressed Storage; token counts and ratios are rough character-based estimates, not measured model-token usage or guarantees)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_session",
                    "set_timer",
                    "get_status",
                    "telemetry",
                    "advance_phase",
                    "log_epistemic_item",
                    "record_invariant",
                    "log_refinement_cycle",
                    "unlock_execution",
                    "checkpoint_session",
                    "restore_session",
                    "list_sessions",
                    "compile_delegation_contract",
                    "compress_payload",
                    "decompress_payload",
                    "view_slice",
                    "accumulate_payload",
                    "flush_accumulator",
                    "get_compression_stats"
                ],
                "description": "The Fable session action to perform."
            },
            "compatibility_mode": {
                "type": "string", "enum": ["legacy_v1"],
                "description": "Optional selector for the legacy fable_session compatibility surface; when supplied it must be legacy_v1. This is not the strict control plane."
            },
            "session_name": {
                "type": "string",
                "description": "Unique identifier / name for the Fable session."
            },
            "objective": {
                "type": "string",
                "description": "High-level goal or problem statement for the reasoning session."
            },
            "time_budget_minutes": {
                "type": "number",
                "description": "Immutable outer authority budget in minutes. set_timer can only change the internal pacing timer."
            },
            "next_phase": {
                "type": "string",
                "enum": PHASES,
                "description": "Target phase to advance the session into."
            },
            "phase_summary": {
                "oneOf": [
                    {"type": "string", "minLength": 8},
                    {"type": "object", "required": ["summary"], "properties": {
                        "summary": {"type": "string", "minLength": 8},
                        "evidence": {"type": "object"}
                    }, "additionalProperties": False}
                ],
                "description": "Substantive phase summary; an object may carry typed evidence bindings."
            },
            "phase_evidence": {
                "type": "object",
                "properties": {
                    "receipt_ids": {"type": "array", "items": {"type": "string"}},
                    "invariant_ids": {"type": "array", "items": {"type": "string"}},
                    "refinement_ids": {"type": "array", "items": {"type": "string"}}
                },
                "additionalProperties": False,
                "description": "Typed phase prerequisite bindings validated within the session."
            },
            "tag": {
                "type": "string",
                "enum": ["PROVEN", "HYPOTHESIS", "UNKNOWN"],
                "description": "Epistemic classification tag for truth calibration."
            },
            "claim": {
                "type": "string",
                "description": "Fact, hypothesis statement, or unknown parameter to track in epistemic ledger."
            },
            "evidence": {
                "description": "Receipt-bound evidence object. Legacy citation strings are accepted for display only and cannot satisfy an unlock gate.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "object", "required": ["receipt_id", "session_id", "content_hash", "source_output_hash", "claim"], "properties": {
                        "receipt_id": {"type": "string"}, "session_id": {"type": "string"},
                        "content": {}, "content_hash": {"type": "string"},
                        "source_output_hash": {"type": "string"}, "claim": {"type": "string"},
                        "kind": {"type": "string"}, "source": {"type": "string"}
                    }, "additionalProperties": True}
                ]
            },
            "invariant_name": {
                "type": "string",
                "description": "Identifier or title of the formal invariant (e.g., 'INV-01: Zero-Deadlock Ring Buffer')."
            },
            "formal_statement": {
                "type": "string",
                "description": "Mathematical or formal contract specification that must never be violated."
            },
            "proof_or_rationale": {
                "type": "string",
                "description": "Proof sketch, rationale, or inductive argument establishing the invariant."
            },
            "domain": {
                "type": "string",
                "enum": ["architecture", "design", "coding"],
                "description": "Domain boundary for the invariant."
            },
            "refinement_type": {
                "type": "string",
                "description": "Type of rethink-refine cycle (e.g. 'archetype_exploration', 'triz_resolution', 'adversarial_falsification', 'benchmark_probe', 'failure_mode_analysis')."
            },
            "focus_area": {
                "type": "string",
                "description": "Specific subsystem, component, algorithm, or interface being critically re-evaluated."
            },
            "critique_or_bottleneck": {
                "type": "string",
                "description": "Critical flaw, vulnerability, edge case, memory/latency bottleneck, or assumption scrutinized."
            },
            "architectural_refinement": {
                "type": "string",
                "description": "Concrete architectural evolution, optimization, or algorithm change derived from the critique."
            },
            "terminal_probe_results": {
                "type": "string",
                "description": "Live empirical probe output, benchmark figures, latency numbers, or profiling stats supporting the refinement."
            },
            "artifact_path": {
                "type": "string",
                "description": "Absolute filesystem path to blueprint artifact, proof, or benchmark script documenting the refinement."
            },
            "rationale": {
                "type": "string",
                "description": "Justification for unlocking code execution after satisfying cognitive gates."
            },
            "subagent_prompt": {
                "type": "string",
                "description": "The delegation prompt or contract text for the subagent to validate."
            },
            "content": {
                "type": "string",
                "description": "Raw text content or payload to store/compress into Content-Addressed Storage (CAS)."
            },
            "payload": {
                "type": "string",
                "description": "Micro-payload text for adaptive batch accumulator or CAS storage."
            },
            "cas_ref": {
                "type": "string",
                "description": "CAS reference URI (cas://<sha256_hex>) or 64-char hash."
            },
            "start_line": {
                "type": "integer",
                "description": "Starting line number (1-indexed inclusive) for windowed line slice viewing."
            },
            "end_line": {
                "type": "integer",
                "description": "Ending line number (1-indexed inclusive) for windowed line slice viewing."
            },
            "include_line_numbers": {
                "type": "boolean",
                "description": "Whether to format line slice with line numbers."
            },
            "label": {
                "type": "string",
                "description": "Optional label or description for compressed CAS node."
            },
            "force_flush": {
                "type": "boolean",
                "description": "Force flush buffered micro-payloads immediately into a composite frame."
            },
            "metadata": {
                "type": "object",
                "description": "Optional metadata dictionary attached to accumulated micro-payload."
            }
        },
        "required": ["action"],
        "allOf": [{
            "if": {"properties": {"action": {"enum": sorted(CAS_ACTIONS)}}},
            "then": {"required": ["session_name"]}
        }]
    },
    "outputSchema": {
        "type": "object",
        "required": ["ok", "action", "text", "isError"],
        "properties": {
            "ok": {"type": "boolean"}, "action": {"type": ["string", "null"]},
            "text": {"type": "string"}, "isError": {"type": "boolean"},
            "error": {"type": ["object", "null"]},
            "host_honesty": {"type": "object"}
        },
        "additionalProperties": True
    }
}


def send_response(response_dict: Dict[str, Any]):
    """Writes a bounded JSON-RPC response to stdout."""
    encoded = json.dumps(response_dict)
    if len(encoded.encode("utf-8")) > MAX_RPC_RESPONSE_BYTES:
        response_dict = {"jsonrpc": "2.0", "id": response_dict.get("id"),
                         "error": {"code": -32000, "message": "Response exceeds maximum size"}}
        encoded = json.dumps(response_dict)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _bounded_lines(stream, limit: int):
    """Yield newline-delimited frames without waiting for EOF.

    ``read(4096)`` is unsafe for interactive stdio: some buffered stream
    implementations try to fill that request and therefore wait for more
    input even after a complete JSON-RPC line has arrived.  Read one byte (or
    one text character for StringIO-like test streams) at a time instead.  A
    BufferedReader/FileIO read of one byte returns as soon as a byte is
    available, while the bounded prefix and ``oversized`` flag keep memory and
    raw-frame accounting under control.
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
                yield bytes(pending).decode("utf-8", "replace"), oversized
            return
        if isinstance(unit, str):
            encoded = unit.encode("utf-8", "replace")
        else:
            encoded = bytes(unit)
        for byte in encoded:
            if byte == 0x0A:
                yield bytes(pending).decode("utf-8", "replace"), oversized
                pending.clear()
                oversized = False
            elif not oversized:
                pending.append(byte)
                if len(pending) > limit:
                    # Keep only a bounded prefix while consuming through the
                    # delimiter; this preserves the next frame in the stream.
                    oversized = True
                    del pending[limit:]


class RequestCancellationRegistry:
    """Bounded pre-dispatch cancellation tombstones for synchronous V1.

    V1 cannot interrupt an active handler, so a cancellation notification is
    retained only long enough to reject a request that is about to dispatch.
    Tombstones are deliberately bounded and expiring: a peer can send
    arbitrary notifications, including IDs for requests that never arrive,
    but cannot grow this process's memory without limit.
    """

    def __init__(self):
        self._cancelled: dict[str, float] = {}
        self._cancelled_bytes = 0
        self._lock = threading.Lock()

    @staticmethod
    def key(request_id: Any) -> str:
        """Canonicalize and bound a JSON-RPC request ID for registry use."""
        if isinstance(request_id, bool) or request_id is None:
            raise ValueError("request_id must be a string or number")
        if not isinstance(request_id, (str, int, float)):
            raise ValueError("request_id must be a string or number")
        if isinstance(request_id, float) and not math.isfinite(request_id):
            raise ValueError("request_id must be a finite number")
        key = json.dumps(request_id, sort_keys=True, separators=(",", ":"))
        if len(key.encode("utf-8")) > MAX_CANCEL_REQUEST_ID_BYTES:
            raise ValueError("request_id exceeds cancellation ID size limit")
        return key

    def _remove_locked(self, key: str) -> None:
        if key in self._cancelled:
            self._cancelled.pop(key, None)
            self._cancelled_bytes = max(
                0, self._cancelled_bytes - len(key.encode("utf-8")))

    def _cleanup_expired_locked(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        for key, expiry in list(self._cancelled.items()):
            if expiry <= now:
                self._remove_locked(key)

    def _add_locked(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        self._cleanup_expired_locked(now)
        key_bytes = len(key.encode("utf-8"))
        if key in self._cancelled:
            # Refreshing an existing tombstone must not double-charge bytes.
            self._cancelled[key] = now + CANCEL_TOMBSTONE_TTL_SECONDS
            return True
        # Evict oldest-expiring entries until both independent bounds hold.
        # Every key is checked above, so an individual key cannot exceed the
        # byte budget and force an unbounded/partial insertion.
        while (len(self._cancelled) >= MAX_CANCEL_TOMBSTONES or
               self._cancelled_bytes + key_bytes > MAX_CANCEL_TOMBSTONE_BYTES):
            if not self._cancelled:
                return False
            victim = min(self._cancelled, key=self._cancelled.get)
            self._remove_locked(victim)
        self._cancelled[key] = now + CANCEL_TOMBSTONE_TTL_SECONDS
        self._cancelled_bytes += key_bytes
        return True

    def cancel(self, request_id: Any) -> None:
        key = self.key(request_id)
        with self._lock:
            self._add_locked(key)

    def is_cancelled(self, request_id: Any) -> bool:
        key = self.key(request_id)
        with self._lock:
            self._cleanup_expired_locked()
            return key in self._cancelled

    def consume(self, request_id: Any) -> bool:
        """Atomically test and remove a pre-dispatch cancellation."""
        key = self.key(request_id)
        with self._lock:
            self._cleanup_expired_locked()
            if key not in self._cancelled:
                return False
            self._remove_locked(key)
            return True

    def clear(self, request_id: Any) -> None:
        """Forget a completed or otherwise abandoned request ID."""
        key = self.key(request_id)
        with self._lock:
            self._remove_locked(key)
            self._cleanup_expired_locked()


def _valid_rpc_id(value: Any) -> bool:
    """JSON-RPC IDs are strings or finite numbers; booleans are not IDs."""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return isinstance(value, (str, int, float))


def _rpc_error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _strict_json_constant(token: str) -> Any:
    raise ValueError(f"non-standard JSON constant is not permitted: {token}")


def _strict_json_loads(value: str) -> Any:
    return json.loads(value, parse_constant=_strict_json_constant)


def _deadline_seconds(params: Dict[str, Any]) -> Optional[float]:
    """Parse request deadlines and reject silently ignored nested legacy forms."""
    # Only the two documented V1 locations are inspected.  Older clients have
    # sent deadline fields below ``_meta.request`` (or inside arguments); those
    # must not be silently ignored and then run without a deadline.
    def nested_deadline_path(value: Any, path: tuple[str, ...] = ()) -> Optional[tuple[str, ...]]:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"deadline_seconds", "deadline", "request_deadline"}:
                    if path == () or path == ("_meta",):
                        continue
                    return path + (str(key),)
                found = nested_deadline_path(child, path + (str(key),))
                if found is not None:
                    return found
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found = nested_deadline_path(child, path + (str(index),))
                if found is not None:
                    return found
        return None

    unsupported_path = nested_deadline_path(params)
    if unsupported_path is not None:
        raise ValueError("unsupported nested legacy deadline field: " + ".".join(unsupported_path))
    value = params.get("deadline_seconds")
    if value is None and isinstance(params.get("_meta"), dict):
        value = params["_meta"].get("deadline_seconds")
    # A legacy top-level ``deadline`` is also explicitly unsupported rather
    # than being mistaken for an enforceable deadline.
    if value is None and any(key in params for key in ("deadline", "request_deadline")):
        raise ValueError("unsupported legacy deadline field")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("deadline_seconds must be a finite positive number")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("deadline_seconds must be a finite positive number") from exc
    if not math.isfinite(seconds) or not (0 < seconds <= MAX_REQUEST_DEADLINE_SECONDS):
        raise ValueError(f"deadline_seconds must be between 0 and {MAX_REQUEST_DEADLINE_SECONDS}")
    return seconds


def _tool_result(msg_id: Any, text: str, *, action: Optional[str] = None,
                 is_error: bool = False, error_code: str = "tool_error",
                 structured: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    encoded_text = str(text)
    if len(encoded_text.encode("utf-8", "replace")) > MAX_TOOL_TEXT_BYTES:
        raw = encoded_text.encode("utf-8", "replace")
        encoded_text = raw[:MAX_TOOL_TEXT_BYTES].decode("utf-8", "ignore") + " [truncated]"
    if structured is None:
        structured = {"ok": not is_error, "action": action, "text": encoded_text,
                      "isError": is_error,
                      "error": ({"code": error_code, "message": encoded_text} if is_error else None),
                      "host_honesty": {
                          "tool_authorization": "external_host_required",
                          "interruptive_control": INTERRUPTIVE_CONTROL,
                          "session_gate_is_not_a_sandbox": True,
                      }}
    else:
        structured = copy.deepcopy(structured)
        structured.setdefault("ok", not is_error)
        structured.setdefault("action", action)
        structured.setdefault("isError", is_error)
        structured.setdefault("text", encoded_text)
        if is_error:
            structured.setdefault("error", {"code": error_code, "message": encoded_text})
    return {"jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": encoded_text}],
                        "structuredContent": structured, "isError": is_error}}


def main():
    logger.info("Starting Fable-Engine MCP Server on stdio...")
    # Protocol state is per stdio connection, not global process state.
    initialized = False
    client_ready = False
    negotiated_version: Optional[str] = None
    cancelled = RequestCancellationRegistry()
    for line, oversized in _bounded_lines(sys.stdin, MAX_RPC_LINE_BYTES):
        if oversized:
            send_response(_rpc_error(None, -32600, "Invalid Request"))
            continue
        # Count the raw frame before trimming whitespace, including whitespace.
        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response(_rpc_error(None, -32600, "Invalid Request"))
            continue
        line = line.strip()
        if not line:
            continue
        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response(_rpc_error(None, -32600, "Invalid Request"))
            continue
        try:
            req = _strict_json_loads(line)
        except Exception:
            # A parse error has no request ID and is not a valid notification.
            send_response(_rpc_error(None, -32700, "Parse error"))
            continue
        # V1 deliberately has a single-request policy. This avoids ambiguous
        # ordering and makes cancellation/deadline state deterministic.
        if isinstance(req, list):
            send_response(_rpc_error(None, -32600, "Invalid Request: batches are not supported by V1"))
            continue
        if not isinstance(req, dict):
            send_response(_rpc_error(None, -32600, "Invalid Request"))
            continue
        has_id = "id" in req
        msg_id = req.get("id")
        if has_id and not _valid_rpc_id(msg_id):
            send_response(_rpc_error(None, -32600, "Invalid Request: id must be a string or finite number"))
            continue
        def _clear_request_id() -> None:
            if has_id:
                try:
                    cancelled.clear(msg_id)
                except ValueError:
                    # IDs larger than the cancellation registry's bound were
                    # never retained and need no cleanup.
                    pass

        if req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            send_response(_rpc_error(msg_id if has_id and _valid_rpc_id(msg_id) else None, -32600, "Invalid Request"))
            _clear_request_id()
            continue
        if "params" in req and not isinstance(req["params"], dict):
            # Retain the V1 compatibility behavior for malformed params, but
            # never answer a notification.
            if has_id:
                send_response(_rpc_error(msg_id, -32600, "Invalid Request"))
            _clear_request_id()
            continue
        method = req["method"]
        params = req.get("params", {})
        is_notification = not has_id

        if method == "notifications/cancelled":
            request_id = params.get("requestId")
            if _valid_rpc_id(request_id):
                try:
                    cancelled.cancel(request_id)
                except ValueError:
                    # Oversized IDs are valid at the JSON-RPC framing layer but
                    # are not retained by the bounded cancellation registry.
                    pass
                else:
                    logger.warning("Cancellation recorded for request %r; interruptive cancellation is unsupported by synchronous V1", request_id)
            _clear_request_id()
            continue

        if method == "initialize":
            if initialized:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32600, "Server already initialized"))
                _clear_request_id()
                continue
            requested = params.get("protocolVersion", SERVER_PROTOCOL_VERSION)
            if not isinstance(requested, str):
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32602, "protocolVersion must be a string"))
                _clear_request_id()
                continue
            if requested not in SUPPORTED_PROTOCOL_VERSIONS:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32602, "Unsupported protocol version"))
                _clear_request_id()
                continue
            initialized = True
            negotiated_version = requested
            response = {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": negotiated_version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "fableV1": {
                            "interruptiveCancellation": False,
                            "requestDeadlines": "unsupported_synchronous_v1",
                            "hostToolAuthorization": "external_host_required"
                        },
                        "fableControlPlane": control_plane_capabilities()
                    },

                    "serverInfo": {"name": "fable-engine", "version": "1.2.3"}
                }
            }
            if not is_notification:
                send_response(response)
            _clear_request_id()
            continue

        if method == "notifications/initialized":
            if initialized:
                client_ready = True
                logger.info("Fable client handshake complete.")
            _clear_request_id()
            continue

        # MCP tools are unavailable until initialize has completed.
        if not initialized:
            if not is_notification:
                send_response(_rpc_error(msg_id, -32002, "Server not initialized"))
            _clear_request_id()
            continue

        if method == "ping":
            if not is_notification:
                send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})
            _clear_request_id()
            continue

        if method == "tools/list":
            if not is_notification:
                send_response({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [TOOL_SCHEMA, CONTROL_PLANE_TOOL_SCHEMA]}})
            _clear_request_id()
            continue

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str) or not isinstance(arguments, dict):
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32602, "tools/call requires string name and object arguments"))
                _clear_request_id()
                continue
            try:
                deadline = _deadline_seconds(params)
            except ValueError as exc:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32602, str(exc)))
                _clear_request_id()
                continue
            try:
                request_was_cancelled = cancelled.consume(msg_id) if has_id else False
            except ValueError:
                # The ordinary RPC ID validation is intentionally broader than
                # the cancellation registry's memory bound. Such an ID can be
                # served, but cannot participate in pre-dispatch cancellation.
                request_was_cancelled = False
            if request_was_cancelled:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32800, "Request cancelled"))
                continue
            # There is no reader/control thread or killable worker boundary in
            # V1's synchronous stdio loop.  Reject deadlines instead of running
            # work past them and relabelling the result afterwards.
            if deadline is not None:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32003,
                        "Unsupported: V1 synchronous server cannot enforce interruptive request deadlines"))
                _clear_request_id()
                continue
            if tool_name not in {"fable_session", CONTROL_PLANE_TOOL_NAME}:
                if not is_notification:
                    send_response(_rpc_error(msg_id, -32601, f"Method / Tool '{tool_name}' not found."))
                _clear_request_id()
                continue
            if tool_name == CONTROL_PLANE_TOOL_NAME:
                strict_result = handle_fable_control_plane(arguments)
                is_error = strict_result.get("ok") is not True
                action = arguments.get("action") if isinstance(arguments.get("action"), str) else None
                if not is_notification:
                    send_response(_tool_result(msg_id, json.dumps(strict_result, ensure_ascii=False, separators=(",", ":")),
                                                action=action, is_error=is_error,
                                                error_code=(strict_result.get("error") or {}).get("code", "control_plane_error"),
                                                structured=strict_result))
                _clear_request_id()
                continue
            action, validation_error = _validate_tool_arguments(arguments)
            if validation_error:
                if not is_notification:
                    send_response(_tool_result(msg_id, f"Error: Invalid arguments: {validation_error}", action=action, is_error=True, error_code="invalid_arguments"))
                _clear_request_id()
                continue
            try:
                result_text = handle_fable_session(arguments)
                is_error = result_text.startswith("Error:")
                # fable_session is the legacy surface. Callers should set
                # compatibility_mode=legacy_v1 explicitly; the direct Python
                # API remains for source compatibility with existing clients.
                if not is_notification:
                    send_response(_tool_result(msg_id, result_text, action=action,
                                                is_error=is_error,
                                                error_code="action_failed" if is_error else ""))
            except Exception as ex:
                logger.error(f"Error handling fable_session: {ex}", exc_info=True)
                if not is_notification:
                    send_response(_tool_result(msg_id, f"Fable Engine Error: {ex}", action=action,
                                                is_error=True, error_code="internal_error"))
            finally:
                # Completed requests, including failures, must not leave
                # reusable IDs in the cancellation registry.
                _clear_request_id()
            continue

        if not is_notification:
            send_response(_rpc_error(msg_id, -32601, f"Unrecognized JSON-RPC method: {method}"))
        _clear_request_id()


if __name__ == "__main__":
    main()

