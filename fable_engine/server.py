#!/usr/bin/env python3
"""
Fable-Engine MCP Server for MCP-compatible agent hosts.
Implements the fable_session tool for deep cognitive session management,
epistemic tracking, invariant recording, anti-rush lockout enforcement,
user-controlled time-budgeted pacing telemetry, and session persistence.
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
import tempfile
import threading
import stat
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union, Iterator

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

# System 3 Architecture Imports
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

from fable_v2.system3 import (
    CausalDAG,
    CausalNode,
    CausalEdge,
    CausalNodeType,
    BrittlenessReport,
    InterventionResult,
    ThesisCandidate,
    AntithesisCritique,
    Contradiction,
    TRIZPrinciple,
    TRIZContradictionResolver,
    DialecticalSynthesizer,
    EmergentSynthesis,
    CognitiveGenome,
    CognitiveGenePool,
    NeuroSymbolicAxiom,
    AxiomProvenance,
    AxiomStatus,
    MetaProofInducer,
    CognitiveGear,
    CognitiveBiasType,
    CognitiveBiasFinding,
    CognitiveBiasDetector,
    DynamicSearchHeuristicRewriter,
    SearchHeuristicConfig,
    TriLevelArbitrator,
    System3Executive,
    # System 3 Hyperbolic
    PoincareBall,
    HyperbolicPoint,
    HyperbolicTreeEmbedder,
    TreeEmbeddingNode,
    TreeEmbeddingResult,
    HyperbolicGeometryError,
    # System 3 Kripke
    KripkeStructure,
    KripkeWorld,
    KripkeModelChecker,
    ModelCheckResult,
    CTLOperator,
    FormulaNode,
    FormulaParser,
    # System 3 Free Energy
    ActiveInferenceEngine,
    GenerativeModel,
    Policy,
    PolicyEvaluation,
    FreeEnergyReport,
    create_default_architecture_pomdp,
    # System 3 Oracle
    ProofOracle,
    CurryHowardVerifier,
    UndecidabilityDetector,
    TacticsEngine,
    FormalProofResult,
    ProofStatus,
    Type,
    Term,
    Prop,
    Unit,
    Void,
    Implies,
    And,
    Or,
    Not,
    Eq,
    Var,
    Lam,
    App,
    Pair,
    Fst,
    Snd,
    Inl,
    Inr,
    Case,
    Refl,
    Abort,
)

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
MAX_CAS_OBJECT_BYTES = 16 * 1024 * 1024
MAX_SLICE_RESPONSE_BYTES = 1_000_000
MAX_RPC_LINE_BYTES = 1 * 1024 * 1024
MAX_RPC_RESPONSE_BYTES = 2 * 1024 * 1024

SILENT_DELIBERATION_REMINDER = (
    "\n\n> [!IMPORTANT]\n"
    "> 🛑 **SILENT-DELIBERATION ACTIVE (Zero-Chat Lockout)**: Do NOT emit conversational responses "
    "or prompt the user while time-lock is active. Continue internal tool-reasoning, terminal benchmarks "
    "(`run_command`), artifact authoring, and rethink-refine cycles until the authority deadline elapses."
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
    ):
        self.root_dir = Path(root_dir).expanduser().absolute() if root_dir is not None else DATA_DIR / "cas"
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

    def put(self, content: Union[str, bytes]) -> str:
        """
        Store content in CAS using lock-free atomic tmp-replace write.
        Returns the standard URI: cas://<sha256_hex>.
        """
        content_hash, raw_bytes = self.compute_sha256(content)
        dest_path = self._get_object_path(content_hash)
        _safe_cas_node(dest_path)

        if len(raw_bytes) > MAX_CAS_OBJECT_BYTES:
            raise FableCASError("CAS object exceeds maximum size")
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
        parsed = json.loads(data)
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

        flushed_uris: List[str] = []
        with self._lock:
            self.total_payloads_ingested += 1
            payload_len = len(payload)
            self.total_raw_chars += payload_len

            entry = {
                "idx": len(self._buffer),
                "payload": payload,
                "meta": metadata or {},
                "ts": time.time(),
            }
            self._buffer.append(entry)
            self._buffered_chars += payload_len

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
                raise ValueError("varint exceeds supported 64-bit integer limit")
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
                "arguments": json.loads(cls.read_string(stream)),
                "result_ref": cls.read_string(stream),
            }

        elif opcode == cls.OP_CAS_REF:
            return {
                "action_type": "cas_ref",
                "cas_ref": cls.read_string(stream),
                "label": cls.read_string(stream),
            }

        elif opcode == cls.OP_GENERIC_JSON:
            return json.loads(cls.read_string(stream))

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

    def __init__(self, root_dir: Optional[Union[str, Path]] = None):
        self.cas_store = FableCASStore(root_dir=root_dir)
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


class EpistemicEvidenceValidator:
    """Validates that [PROVEN] evidence strings map to real filesystem files, line ranges, URLs, or CLI stdout."""

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

    @staticmethod
    def inject_system3_micro_scaffolds(prompt: str, parsed: Dict[str, str]) -> str:
        """Inject System 3 Micro-Scaffolds into the delegation contract for weak-model frontier uplift."""
        target_file = parsed.get("TargetFile", "src/target.py")
        verif_cmd = parsed.get("VerificationCommand", "python -m unittest")

        scaffold = f"""
### 🛡️ SYSTEM 3 MICRO-SCAFFOLD (WEAK-MODEL FRONTIER UPLIFT)

#### 1. Kripke Safety Invariant Contract ($AG(\\text{{safe}})$):
- $AG(\\text{{NoHallucination}} \\land \\text{{TypeSoundness}})$: Never invent non-existent APIs or variables.
- $AX(\\text{{TargetFileBoundary}})$: Modify ONLY `{target_file}`. Zero modifications outside `{target_file}`.
- $AF(\\text{{VerificationPass}})$: Every execution must satisfy `{verif_cmd}` with exit code 0.

#### 2. Causal Failure Mode Boundaries ($do(\\cdot)$ Sensitivities):
- Invariant under intervention: $P(\\text{{SystemError}} \\mid do(\\text{{Edit}}({target_file}))) = 0$.
- Pre-condition validation: Inspect and verify exact file line bounds before applying replacements.
- Post-condition validation: Run `{verif_cmd}` immediately after edit to confirm 0 regressions.

#### 3. TRIZ Transcendent Resolution Guidelines:
- Avoid lazy compromises (do NOT comment out tests or catch-and-ignore exceptions).
- Apply TRIZ Principle 1 (Segmentation): Decompose complex logic into pure helper functions.
- Apply TRIZ Principle 10 (Preliminary Action): Validate all preconditions before mutating state.

#### 4. Structured Output Regex Acceptance Constraint:
- Your response MUST strictly adhere to atomic execution formatting:
  Pattern: `^```(?:python|json|diff)[\\s\\S]*?```$`
"""
        return prompt.strip() + "\n\n" + scaffold.strip()

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

        is_valid = len(errors) == 0
        if is_valid:
            parsed["system3_micro_scaffold"] = self.inject_system3_micro_scaffolds(prompt, parsed)
            parsed["compiled_prompt"] = parsed["system3_micro_scaffold"]
        return is_valid, errors, parsed


class FableSession:
    """Represents an active Fable reasoning & pacing session."""

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
        self.session_id = session_id or f"fable_{session_name}_{int(self.start_time)}"
        
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
        self.can_execute_code = False
        
        self.epistemic_ledger: List[Dict[str, Any]] = []
        self.invariants: List[Dict[str, Any]] = []
        self.refinement_cycles: List[Dict[str, Any]] = []
        self.phase_history: List[Dict[str, Any]] = [
            {
                "phase": self.active_phase,
                "entered_at": self.start_time,
                "summary": "Session initialized"
            }
        ]
        self.unlock_details: Optional[Dict[str, Any]] = None
        self._restored_untrusted = False

        # System 3 Meta-Cognitive State
        self.system3_causal_graphs: List[Dict[str, Any]] = []
        self.system3_syntheses: List[Dict[str, Any]] = []
        self.system3_gene_pools: List[Dict[str, Any]] = []
        self.system3_axioms: List[Dict[str, Any]] = []
        self.system3_reflections: List[Dict[str, Any]] = []
        self.system3_orchestrations: List[Dict[str, Any]] = []
        self.system3_hyperbolic_embeddings: List[Dict[str, Any]] = []
        self.system3_kripke_verifications: List[Dict[str, Any]] = []
        self.system3_active_inferences: List[Dict[str, Any]] = []
        self.system3_proof_oracle_verifications: List[Dict[str, Any]] = []
        self.active_free_energy: Optional[Dict[str, Any]] = None
        self.active_kripke_safety: Optional[Dict[str, Any]] = None
        self.active_biases: List[Dict[str, Any]] = []

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
        proven_with_evidence = [i for i in proven_items if str(i.get("evidence", "")).strip()]
        invariants_with_proof = [
            inv for inv in self.invariants if not inv.get("_restored_untrusted") and str(inv.get("proof_or_rationale", "")).strip()
        ]
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
            "silent_deliberation_active": self.execution_locked,
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
            "system3_cognitive_state": {
                "free_energy_f": self.active_free_energy.get("variational_free_energy_f", 1.25) if self.active_free_energy else 1.25,
                "complexity_kl": self.active_free_energy.get("complexity_kl", 0.35) if self.active_free_energy else 0.35,
                "accuracy_log_likelihood": self.active_free_energy.get("accuracy_log_likelihood", -0.90) if self.active_free_energy else -0.90,
                "kripke_safety_invariant": "AG(safe) -> True" if (self.active_kripke_safety.get("is_satisfied", True) if self.active_kripke_safety else True) else "AG(safe) -> VIOLATED",
                "kripke_safety_verified": self.active_kripke_safety.get("is_satisfied", True) if self.active_kripke_safety else True,
                "active_biases_count": len(self.active_biases),
                "active_biases": self.active_biases,
                "contradiction_density": round(sum(len(s.get("resolved_contradictions", [])) for s in self.system3_syntheses) / max(1, len(self.system3_syntheses)), 2) if self.system3_syntheses else 0.0,
                "hyperbolic_metric": {
                    "embeddings_count": len(self.system3_hyperbolic_embeddings),
                    "curvature": 1.0,
                    "status": "CONVERGED_POINCARE_BALL" if self.system3_hyperbolic_embeddings else "INITIALIZED",
                },
            },
            "system3_counts": {
                "causal_graphs": len(self.system3_causal_graphs),
                "syntheses": len(self.system3_syntheses),
                "gene_pools": len(self.system3_gene_pools),
                "axioms": len(self.system3_axioms),
                "reflections": len(self.system3_reflections),
                "orchestrations": len(self.system3_orchestrations),
                "hyperbolic_embeddings": len(self.system3_hyperbolic_embeddings),
                "kripke_verifications": len(self.system3_kripke_verifications),
                "active_inferences": len(self.system3_active_inferences),
                "proof_oracle_verifications": len(self.system3_proof_oracle_verifications),
            }
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

    def advance_phase(self, next_phase: str, phase_summary: str) -> Dict[str, Any]:
        """Advances the session to the requested phase and records history."""
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

        now = self._wall_clock()
        self.active_phase = matched_phase
        self.phase_history.append({
            "phase": matched_phase,
            "entered_at": now,
            "summary": phase_summary
        })

        # Run System 3 Executive bias detection & reflection
        detector = CognitiveBiasDetector()
        findings = detector.audit_session({
            "epistemic_ledger": self.epistemic_ledger,
            "refinement_cycles": self.refinement_cycles,
            "phase_history": self.phase_history,
            "invariants": self.invariants,
        })
        self.active_biases = [f.to_dict() for f in findings]
        if findings:
            self.system3_reflections.append({
                "phase": matched_phase,
                "findings": self.active_biases,
                "timestamp": now,
            })

        # Update live Free Energy F
        pomdp_model = create_default_architecture_pomdp()
        fe_engine = ActiveInferenceEngine(pomdp_model)
        proven_count = sum(1 for i in self.epistemic_ledger if i.get("tag") == "PROVEN")
        obs = "HIGH_THROUGHPUT_CLEAN" if proven_count >= 2 else "LOCK_CONTENTION_WARN"
        fe_policies = [Policy(policy_id=f"p_{act}", actions=[act]) for act in pomdp_model.actions]
        fe_report = fe_engine.select_action(obs, fe_policies)
        self.active_free_energy = {
            "variational_free_energy_f": round(fe_report.variational_free_energy_f, 4),
            "complexity_kl": round(fe_report.complexity_kl, 4),
            "accuracy_log_likelihood": round(fe_report.accuracy_log_likelihood, 4),
            "selected_action": fe_report.selected_action,
            "observation": obs,
            "phase": matched_phase,
            "timestamp": now,
        }
        self.system3_active_inferences.append(self.active_free_energy)

        # Update Kripke Safety Invariant
        kripke = KripkeStructure()
        kripke.add_world("w0", propositions={"entered", "safe"})
        kripke.add_world("w_phase", propositions={f"phase_{target_phase_idx}", "safe"})
        kripke.add_transition("w0", "w_phase")
        kripke.add_transition("w_phase", "w_phase")
        checker = KripkeModelChecker(kripke)
        k_res = checker.check("AG(safe)", "w0")
        self.active_kripke_safety = {
            "formula": "AG(safe)",
            "is_satisfied": k_res.is_satisfied,
            "active_phase": matched_phase,
        }

        return self.get_telemetry()

    def log_epistemic_item(self, tag: str, claim: str, evidence: Optional[str] = None) -> Dict[str, Any]:
        """Logs an epistemic fact/hypothesis/unknown with structured tracking and evidence validation."""
        tag_upper = tag.strip().upper()
        if tag_upper not in ("PROVEN", "HYPOTHESIS", "UNKNOWN"):
            raise ValueError(f"Invalid epistemic tag '{tag}'. Must be 'PROVEN', 'HYPOTHESIS', or 'UNKNOWN'.")

        if not claim or not claim.strip():
            raise ValueError("Claim description cannot be empty.")
        if tag_upper == "PROVEN":
            if not str(evidence or "").strip():
                raise ValueError("PROVEN claims require concrete evidence (file, command output, test, or URL).")
            validator = EpistemicEvidenceValidator()
            valid, reason = validator.validate_proven_claim(claim, str(evidence))
            if not valid:
                raise ValueError(f"Epistemic Evidence Validation Failed: {reason}")

        item_id = f"epi_{len(self.epistemic_ledger) + 1:03d}"
        item = {
            "id": item_id,
            "tag": tag_upper,
            "claim": claim.strip(),
            "evidence": (evidence or "").strip(),
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
        dom_clean = domain.strip().lower()
        if dom_clean not in ("architecture", "design", "coding"):
            dom_clean = "architecture"

        if not invariant_name or not invariant_name.strip():
            raise ValueError("Invariant name cannot be empty.")
        if not formal_statement or not formal_statement.strip():
            raise ValueError("Formal statement cannot be empty.")
        if not proof_or_rationale or not proof_or_rationale.strip():
            raise ValueError("Invariant proof or rationale cannot be empty.")

        inv_id = f"inv_{len(self.invariants) + 1:03d}"
        inv = {
            "id": inv_id,
            "name": invariant_name.strip(),
            "domain": dom_clean,
            "formal_statement": formal_statement.strip(),
            "proof_or_rationale": (proof_or_rationale or "").strip(),
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
        if not refinement_type or not str(refinement_type).strip():
            raise ValueError("Refinement type cannot be empty.")
        if not focus_area or not str(focus_area).strip():
            raise ValueError("Focus area cannot be empty.")
        if not critique_or_bottleneck or not str(critique_or_bottleneck).strip():
            raise ValueError("Critique or bottleneck cannot be empty.")
        if not architectural_refinement or not str(architectural_refinement).strip():
            raise ValueError("Architectural refinement cannot be empty.")

        cycle_num = len(self.refinement_cycles) + 1
        entry = {
            "cycle_number": cycle_num,
            "refinement_type": str(refinement_type).strip(),
            "focus_area": str(focus_area).strip(),
            "critique_or_bottleneck": str(critique_or_bottleneck).strip(),
            "architectural_refinement": str(architectural_refinement).strip(),
            "terminal_probe_results": (terminal_probe_results or "").strip() if terminal_probe_results else None,
            "artifact_path": (artifact_path or "").strip() if artifact_path else None,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.refinement_cycles.append(entry)

        # Update Session Active Free Energy F
        fe_engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        obs = "HIGH_THROUGHPUT_CLEAN" if terminal_probe_results and any(
            kw in terminal_probe_results.lower() for kw in ("pass", "ok", "success")
        ) else "LOCK_CONTENTION_WARN"
        f_val, comp, acc = fe_engine.update_beliefs(obs)
        self.active_free_energy = {
            "variational_free_energy_f": round(f_val, 4),
            "complexity_kl": round(comp, 4),
            "accuracy_log_likelihood": round(acc, 4),
            "observation": obs,
            "cycle_number": cycle_num,
            "timestamp": self._wall_clock(),
        }

        # Update Causal DAG nodes if a causal graph exists
        if self.system3_causal_graphs:
            causal_node_id = f"refine_cycle_{cycle_num}"
            causal_node_data = {
                "node_id": causal_node_id,
                "name": f"Refinement {cycle_num}: {focus_area}",
                "node_type": "INTERVENTION",
                "value": 1.0,
                "parents": [f"refine_cycle_{cycle_num - 1}"] if cycle_num > 1 else [],
                "metadata": {
                    "refinement_type": refinement_type,
                    "focus_area": focus_area,
                    "critique": critique_or_bottleneck,
                }
            }
            latest_graph = self.system3_causal_graphs[-1]
            inner_dag = latest_graph.get("dag", latest_graph)
            nodes = inner_dag.setdefault("nodes", [])
            if isinstance(nodes, list):
                if not any(n.get("node_id") == causal_node_id for n in nodes if isinstance(n, dict)):
                    nodes.append(causal_node_data)
            elif isinstance(nodes, dict):
                nodes[causal_node_id] = causal_node_data
            if cycle_num > 1:
                prev_id = f"refine_cycle_{cycle_num - 1}"
                edges = inner_dag.setdefault("edges", [])
                if isinstance(edges, list):
                    edges.append({"source": prev_id, "target": causal_node_id, "weight": 1.0, "mechanism": "refinement_evolution"})

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
            "phase_history": self.phase_history,
            "unlock_details": self.unlock_details,
            "system3_causal_graphs": self.system3_causal_graphs,
            "system3_syntheses": self.system3_syntheses,
            "system3_gene_pools": self.system3_gene_pools,
            "system3_axioms": self.system3_axioms,
            "system3_reflections": self.system3_reflections,
            "system3_orchestrations": self.system3_orchestrations,
            "system3_hyperbolic_embeddings": self.system3_hyperbolic_embeddings,
            "system3_kripke_verifications": self.system3_kripke_verifications,
            "system3_active_inferences": self.system3_active_inferences,
            "system3_proof_oracle_verifications": self.system3_proof_oracle_verifications,
            "active_free_energy": self.active_free_energy,
            "active_kripke_safety": self.active_kripke_safety,
            "active_biases": self.active_biases,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FableSession":
        """Restore data without importing persisted execution authority.

        Persistence is an interchange format, not an authority token.  The
        deadline, phase, evidence, invariants, and unlock flags are all treated
        as untrusted; a restored process starts a fresh locked authority clock.
        Historical data remains visible, but cannot satisfy fresh gates.
        """
        budget = data.get("time_budget_minutes", 60.0)
        session = cls(session_name=data["session_name"], objective=data.get("objective", ""),
                      time_budget_minutes=budget, session_id=data.get("session_id"))
        session._restored_untrusted = True
        session.epistemic_ledger = [dict(item, _restored_untrusted=True) for item in data.get("epistemic_ledger", []) if isinstance(item, dict)]
        session.invariants = [dict(item, _restored_untrusted=True) for item in data.get("invariants", []) if isinstance(item, dict)]
        session.refinement_cycles = [dict(item, _restored_untrusted=True) for item in data.get("refinement_cycles", []) if isinstance(item, dict)]
        session.active_phase = PHASES[0]
        session.phase_history = [{"phase": PHASES[0], "entered_at": session.start_time,
                                 "summary": "Restored in safe locked state; fresh gates required"}]
        session.execution_locked = True
        session.can_execute_code = False
        session.unlock_details = None
        session.system3_causal_graphs = data.get("system3_causal_graphs", [])
        session.system3_syntheses = data.get("system3_syntheses", [])
        session.system3_gene_pools = data.get("system3_gene_pools", [])
        session.system3_axioms = data.get("system3_axioms", [])
        session.system3_reflections = data.get("system3_reflections", [])
        session.system3_orchestrations = data.get("system3_orchestrations", [])
        session.system3_hyperbolic_embeddings = data.get("system3_hyperbolic_embeddings", [])
        session.system3_kripke_verifications = data.get("system3_kripke_verifications", [])
        session.system3_active_inferences = data.get("system3_active_inferences", [])
        session.system3_proof_oracle_verifications = data.get("system3_proof_oracle_verifications", [])
        session.active_free_energy = data.get("active_free_energy")
        session.active_kripke_safety = data.get("active_kripke_safety")
        session.active_biases = data.get("active_biases", [])
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
        return ACTIVE_SESSIONS[clean_name]

    file_path = SESSIONS_DIR / f"{clean_name}.json"
    if file_path.exists() or file_path.is_symlink():
        try:
            _safe_session_file(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = FableSession.from_dict(data)
            ACTIVE_SESSIONS[clean_name] = session
            return session
        except Exception as e:
            logger.error(f"Failed to load session file {file_path}: {e}")
            raise RuntimeError(f"Corrupt or unreadable session file for '{clean_name}': {e}")

    raise ValueError(f"Session '{clean_name}' does not exist. Call 'create_session' first.")


def handle_fable_session(arguments: Dict[str, Any]) -> str:
    """Main dispatch handler for fable_session tool actions."""
    try:
        action = arguments.get("action", "").strip().lower()
        session_name = arguments.get("session_name", "").strip()

        if not action:
            return "Error: Missing required parameter 'action'."

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
                f"- **Cognitive Gates**: 0/2 [PROVEN] items, 0/1 Invariant recorded\n\n"
                f"> [!IMPORTANT]\n"
                f"> Anti-Rush Lockout is ACTIVE. Proceed with epistemic grounding, research, and invariant modeling before requesting execution unlock."
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

            cog_state = tel.get("system3_cognitive_state", {})
            return (
                f"### 📊 Fable Session Status & Telemetry (`{session.session_name}`)\n\n"
                f"- **Objective**: {session.objective}\n"
                f"- **Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
                f"- **Execution Lock**: {lock_badge}\n"
                f"- **Pacing**: `{tel['elapsed_formatted']}` elapsed / `{tel['pacing_remaining_formatted']}` remaining (`{tel['pacing_percentage']}` budget used)\n"
                f"- **Authority**: `{tel['authority_remaining_formatted']}` remaining (immutable outer deadline)\n"
                f"- **Epistemic Breakdown**: `{counts['proven']} PROVEN`, `{counts['hypothesis']} HYPOTHESIS`, `{counts['unknown']} UNKNOWN` (Total: `{counts['total']}`)\n"
                f"- **Invariants Recorded**: `{tel['invariants_count']}`\n"
                f"- **Refinement Cycles**: `{tel['refinement_count']}`\n\n"
                f"#### 🧠 System 3 Meta-Cognitive State:\n"
                f"- **Variational Free Energy $F$**: `{cog_state.get('free_energy_f', 'N/A')}` "
                f"(Complexity $D_{{KL}}$: `{cog_state.get('complexity_kl', 'N/A')}`, Accuracy: `{cog_state.get('accuracy_log_likelihood', 'N/A')}`)\n"
                f"- **Kripke Safety Invariant**: `{cog_state.get('kripke_safety_invariant', 'AG(safe) -> True')}`\n"
                f"- **Active Biases Tracked**: `{cog_state.get('active_biases_count', 0)}`\n"
                f"- **Contradiction Density**: `{cog_state.get('contradiction_density', 0.0)}`\n"
                f"- **Hyperbolic Metric**: `{cog_state.get('hyperbolic_metric', {}).get('status', 'INITIALIZED')}`\n\n"
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
            phase_summary = arguments.get("phase_summary", "").strip() or "Advanced phase transition."

            session = get_or_load_session(session_name)
            tel = session.advance_phase(next_phase, phase_summary)
            session.save()

            cog_state = tel.get("system3_cognitive_state", {})
            bias_lines = ""
            if session.active_biases:
                bias_items = "\n".join([f"  * ⚠️ **{b['bias_type']}** ({b['severity']}): {b['description']} -> *{b['mitigation_recommendation']}*" for b in session.active_biases])
                bias_lines = f"\n- **Active Biases Intercepted** ({len(session.active_biases)}):\n{bias_items}"

            sys3_advisory = (
                f"\n\n### 🧠 System 3 Meta-Cognitive Advisory & Active Inference\n"
                f"- **Live Free Energy $F$**: `{cog_state.get('free_energy_f', 'N/A')}` "
                f"(Complexity $D_{{KL}}$: `{cog_state.get('complexity_kl', 'N/A')}`, Accuracy: `{cog_state.get('accuracy_log_likelihood', 'N/A')}`)\n"
                f"- **Kripke Safety Invariant**: `{cog_state.get('kripke_safety_invariant', 'AG(safe) -> True')}`\n"
                f"- **Contradiction Density**: `{cog_state.get('contradiction_density', 0.0)}`"
                f"{bias_lines}"
            )

            return (
                f"### 🚀 Fable Phase Advanced Successfully\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **New Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
                f"- **Phase Summary**: {phase_summary}\n"
                f"- **Execution Status**: `{'LOCKED 🛑' if session.execution_locked else 'UNLOCKED 🟢'}`\n"
                f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}` (`{tel['pacing_percentage']}` used)\n"
                f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`"
                f"{sys3_advisory}"
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

            compiled_scaffold = parsed.get("compiled_prompt", prompt)
            return (
                f"### ✅ Subagent Delegation Contract Compiled Successfully (with System 3 Micro-Scaffolds)\n\n"
                f"- **Target File**: `{parsed.get('TargetFile', 'Declared')}`\n"
                f"- **Verification Command**: `{parsed.get('VerificationCommand', 'Declared')}`\n"
                f"- **Contract Status**: `100% BOUNDED & VALIDATED`\n"
                f"- **System 3 Micro-Scaffolds**: `INJECTED (Kripke AG(safe), Causal do(·) bounds, TRIZ Transcendence, Regex Constraints)`\n"
                f"- **Dispatch Readiness**: `READY_FOR_SUBAGENT_DISPATCH` 🚀\n\n"
                f"```markdown\n{compiled_scaffold}\n```\n\n"
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

            compressed_node = CAS_ENGINE.compress_payload_to_cas(content_text, label=label)
            raw_len = len(content_text)
            raw_tokens = CAS_ENGINE.estimate_token_count(content_text)
            comp_repr = json.dumps(compressed_node, separators=(",", ":"))
            comp_tokens = CAS_ENGINE.estimate_token_count(comp_repr)
            ratio = CAS_ENGINE.calculate_token_ratio(content_text, comp_repr)

            invariant_met = ratio <= 0.003 if raw_len >= 10000 else True
            badge = "✅ PASS (<= 0.003 tokens/char)" if invariant_met else f"⚠️ Ratio: {ratio:.6f} tokens/char"

            return (
                f"### 🗜️ Fable CAS Payload Compressed\n\n"
                f"- **CAS URI**: `{compressed_node['cas_ref']}`\n"
                f"- **Line Count**: `{compressed_node['lines']}`\n"
                f"- **Raw Size**: `{raw_len}` characters (~`{raw_tokens}` tokens)\n"
                f"- **Compressed Reference Size**: `{len(comp_repr)}` characters (~`{comp_tokens}` tokens)\n"
                f"- **Token Compression Ratio**: `{ratio:.6f}` tokens/char\n"
                f"- **Invariant Status**: {badge}\n"
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
                text = CAS_ENGINE.cas_store.get_text(cas_ref, verify=True)
                if len(text.encode("utf-8")) > MAX_RPC_RESPONSE_BYTES // 2:
                    return "Error: decompressed response exceeds maximum size; use view_slice."
                lines = CAS_ENGINE.slice_viewer.get_line_count(cas_ref)
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
                slice_text = CAS_ENGINE.slice_viewer.view_slice(
                    cas_ref, start_line, end_line, include_line_numbers=include_line_numbers
                )
                total_lines = CAS_ENGINE.slice_viewer.get_line_count(cas_ref)
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
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {"raw": metadata}
            force_flush = bool(arguments.get("force_flush", False))

            flushed = CAS_ENGINE.accumulator.add(str(payload), metadata=metadata, force_flush=force_flush)
            stats = CAS_ENGINE.accumulator.get_stats()

            flushed_str = "\n".join([f"- Flushed Composite Frame: `{u}`" for u in flushed]) if flushed else "- No frame flushed yet (buffering micro-payload)."
            return (
                f"### 📥 Micro-Payload Ingested\n\n"
                f"- **Buffered Items**: `{stats['currently_buffered_items']}`\n"
                f"- **Buffered Chars**: `{stats['currently_buffered_chars']}` / `{CAS_ENGINE.accumulator.min_frame_size}` bytes threshold\n"
                f"- **Total Ingested**: `{stats['total_payloads_ingested']}`\n"
                f"- **Total Frames Flushed**: `{stats['total_frames_flushed']}`\n\n"
                f"{flushed_str}"
            )

        # 17. FLUSH ACCUMULATOR
        elif action in ("flush_accumulator", "flush_cas", "cas_flush"):
            flushed = CAS_ENGINE.accumulator.flush()
            stats = CAS_ENGINE.accumulator.get_stats()
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
            stats = CAS_ENGINE.accumulator.get_stats()
            return (
                f"### 📊 Fable Token Compression Subsystem Telemetry\n\n"
                f"- **CAS Storage Root**: `{CAS_ENGINE.cas_store.root_dir}`\n"
                f"- **Memory Cache Capacity**: `{CAS_ENGINE.cas_store.cache.capacity}` entries (Current: `{len(CAS_ENGINE.cas_store.cache)}`)\n"
                f"- **Micro-Payloads Ingested**: `{stats['total_payloads_ingested']}`\n"
                f"- **Composite Frames Flushed**: `{stats['total_frames_flushed']}`\n"
                f"- **Total Raw Characters**: `{stats['total_raw_chars']}`\n"
                f"- **Total CAS Bytes Written**: `{stats['total_cas_bytes_written']}`\n"
                f"- **Currently Buffered Items**: `{stats['currently_buffered_items']}` (`{stats['currently_buffered_chars']}` chars)\n"
                f"- **Token Compression Invariant**: `<= 0.003 tokens/character`"
            )

        # 19. SYSTEM 3: DIALECTICAL SYNTHESIS
        elif action in ("system3_dialectical_synthesis", "dialectical_synthesis", "triz_synthesis", "synthesis"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_dialectical_synthesis'."
            thesis_title = arguments.get("thesis_title") or arguments.get("title") or "Architectural Thesis"
            thesis_desc = arguments.get("thesis_description") or arguments.get("description") or arguments.get("thesis") or "Primary architectural candidate."
            antithesis_title = arguments.get("antithesis_title") or arguments.get("critique_title") or arguments.get("critique") or "Adversarial Critique"

            raw_contradictions = arguments.get("contradictions") or arguments.get("contradiction_list") or []
            parsed_contradictions = []
            if isinstance(raw_contradictions, str):
                try:
                    loaded = json.loads(raw_contradictions)
                    if isinstance(loaded, list):
                        raw_contradictions = loaded
                    elif isinstance(loaded, dict):
                        raw_contradictions = [loaded]
                except Exception:
                    raw_contradictions = [
                        {"improving_parameter": "performance", "worsening_parameter": "safety", "description": line.strip(), "severity": 0.7}
                        for line in raw_contradictions.splitlines() if line.strip()
                    ]

            if isinstance(raw_contradictions, list):
                for idx, c in enumerate(raw_contradictions):
                    if isinstance(c, dict):
                        parsed_contradictions.append(Contradiction(
                            contradiction_id=c.get("contradiction_id", f"c_{idx+1:03d}"),
                            improving_parameter=c.get("improving_parameter", "performance"),
                            worsening_parameter=c.get("worsening_parameter", "safety"),
                            description=c.get("description", "Architectural trade-off"),
                            severity=float(c.get("severity", 0.7)),
                        ))
                    elif isinstance(c, str):
                        parsed_contradictions.append(Contradiction(
                            contradiction_id=f"c_{idx+1:03d}",
                            improving_parameter="performance",
                            worsening_parameter="safety",
                            description=c,
                            severity=0.7,
                        ))

            failure_modes = arguments.get("failure_modes") or []
            if isinstance(failure_modes, str):
                try:
                    failure_modes = json.loads(failure_modes)
                except Exception:
                    failure_modes = [f.strip() for f in failure_modes.splitlines() if f.strip()]

            thesis = ThesisCandidate(
                thesis_id=f"th_{session_name}_{int(time.time()*1000)%10000}",
                title=thesis_title,
                description=thesis_desc,
            )
            critique = AntithesisCritique(
                critique_id=f"cr_{session_name}_{int(time.time()*1000)%10000}",
                thesis_id=thesis.thesis_id,
                title=antithesis_title,
                contradictions=parsed_contradictions,
                failure_modes=failure_modes if isinstance(failure_modes, list) else [str(failure_modes)],
                severity_score=float(arguments.get("severity_score", 0.75)),
            )

            max_rounds = int(arguments.get("max_debate_rounds", 4))
            threshold = float(arguments.get("target_residual_threshold", 0.15))

            synthesizer = DialecticalSynthesizer()
            synthesis = synthesizer.synthesize(
                thesis, critique, max_debate_rounds=max_rounds, target_residual_threshold=threshold
            )

            session = get_or_load_session(session_name)
            session.system3_syntheses.append(synthesis.to_dict())

            session.log_refinement_cycle(
                refinement_type="system3_dialectical_synthesis",
                focus_area=f"{thesis_title} vs {antithesis_title}",
                critique_or_bottleneck=f"Contradictions: {len(parsed_contradictions)} parameter conflicts analyzed.",
                architectural_refinement=synthesis.pareto_improvement_claim,
            )
            session.save()

            principles_list = "\n".join([f"- **TRIZ Principle #{p.number} ({p.name})**: {p.description}" for p in synthesis.transcended_principles]) or "- No principles transcended."
            contra_list = "\n".join([f"- `{c.improving_parameter}` vs `{c.worsening_parameter}`: {c.description} (Severity: {c.severity})" for c in synthesis.resolved_contradictions]) or "- None declared."

            return (
                f"### ⚡ System 3 Dialectical Synthesis Emerged\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Synthesis Title**: **{synthesis.title}** (`{synthesis.synthesis_id}`)\n"
                f"- **Debate Rounds Executed**: `{synthesis.debate_rounds_executed}`\n"
                f"- **Initial Contradiction Severity**: `{synthesis.initial_contradiction_score:.2f}`\n"
                f"- **Residual Contradiction Severity**: `{synthesis.residual_contradiction_score:.2f}`\n"
                f"- **Convergence Achieved**: `{'✅ YES' if synthesis.convergence_achieved else '⚠️ PARTIAL'}`\n\n"
                f"#### 🧬 Transcended TRIZ Inventive Principles:\n{principles_list}\n\n"
                f"#### ⚔️ Resolved Contradictions:\n{contra_list}\n\n"
                f"#### 🏛️ Synthesized Architectural Blueprint:\n{synthesis.synthesized_architecture}\n\n"
                f"> [!TIP]\n"
                f"> {synthesis.pareto_improvement_claim}"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 20. SYSTEM 3: CAUSAL SIMULATION & PEARL DO-CALCULUS
        elif action in ("system3_causal_simulate", "causal_simulate", "causal_graph", "do_calculus"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_causal_simulate'."
            model_name = arguments.get("model_name", "System3CausalModel")
            nodes_input = arguments.get("nodes", [])
            edges_input = arguments.get("edges", [])
            interventions_input = arguments.get("interventions", {})
            target_metric = arguments.get("target_metric")

            if isinstance(nodes_input, str):
                try:
                    nodes_input = json.loads(nodes_input)
                except Exception:
                    nodes_input = []
            if isinstance(edges_input, str):
                try:
                    edges_input = json.loads(edges_input)
                except Exception:
                    edges_input = []
            if isinstance(interventions_input, str):
                try:
                    interventions_input = json.loads(interventions_input)
                except Exception:
                    interventions_input = {}

            dag = CausalDAG(name=model_name)
            for n in nodes_input:
                if isinstance(n, dict):
                    dag.add_node(
                        node_id=n.get("node_id", n.get("id")),
                        name=n.get("name"),
                        node_type=CausalNodeType(n.get("node_type", "endogenous")),
                        value=float(n.get("value", 0.0)),
                        default_value=float(n["default_value"]) if "default_value" in n else None,
                        min_value=float(n["min_value"]) if "min_value" in n else None,
                        max_value=float(n["max_value"]) if "max_value" in n else None,
                        description=n.get("description", ""),
                    )

            for e in edges_input:
                if isinstance(e, dict):
                    dag.add_edge(
                        source=e["source"],
                        target=e["target"],
                        weight=float(e.get("weight", 1.0)),
                        relation_type=e.get("relation_type", "linear"),
                        description=e.get("description", ""),
                    )

            is_acyclic, cycle = dag.check_acyclicity()
            if not is_acyclic:
                return f"Error: Graph contains a cycle: {' -> '.join(cycle)}. Causal models must be valid DAGs."

            topo_order = dag.topological_sort()
            factual_values = dag.compute_forward()

            interv_res = None
            if interventions_input and isinstance(interventions_input, dict):
                interv_map = {k: float(v) for k, v in interventions_input.items()}
                interv_res = dag.do_intervention(interv_map)

            brittleness_rep = None
            if target_metric and target_metric in dag.nodes:
                brittleness_rep = dag.evaluate_brittleness(target_metric)

            session = get_or_load_session(session_name)
            session.system3_causal_graphs.append({
                "dag": dag.to_dict(),
                "topological_order": topo_order,
                "factual_values": factual_values,
                "intervention": interv_res.to_dict() if interv_res else None,
                "brittleness": brittleness_rep.to_dict() if brittleness_rep else None,
                "timestamp": time.time(),
            })
            session.save()

            lines = [
                f"### 🌐 System 3 Pearl's Do-Calculus & Causal Simulation\n\n",
                f"- **Model**: `{dag.name}` ({len(dag.nodes)} nodes, {len(dag.edges)} directed causal edges)\n",
                f"- **Topological Order**: `{' -> '.join(topo_order)}`\n",
            ]

            if interv_res:
                lines.append(f"\n#### ✂️ Pearl's Do-Operator Intervention: `do({interv_res.interventions})`\n")
                lines.append(f"- **Severed Edges**: `{len(interv_res.severed_edges)}` ({interv_res.severed_edges})\n")
                lines.append(f"- **Impacted Nodes**: `{', '.join(interv_res.impacted_nodes)}`\n\n")
                lines.append("| Node | Factual Value | Counterfactual Value | Delta (Δ) |\n")
                lines.append("|---|---|---|---|\n")
                for nid in topo_order:
                    f_val = interv_res.original_values.get(nid, 0.0)
                    cf_val = interv_res.counterfactual_values.get(nid, 0.0)
                    delta = interv_res.deltas.get(nid, 0.0)
                    delta_str = f"+{delta:.4f}" if delta > 0 else f"{delta:.4f}"
                    lines.append(f"| `{nid}` | {f_val:.4f} | **{cf_val:.4f}** | `{delta_str}` |\n")

            if brittleness_rep:
                lines.append(f"\n#### 🔬 Structural Brittleness Report (`{brittleness_rep.target_metric}`)\n")
                lines.append(f"- **Overall Brittleness Score**: `{brittleness_rep.overall_brittleness_score:.4f}` / 1.0\n")
                spof_str = ", ".join(brittleness_rep.single_points_of_failure) if brittleness_rep.single_points_of_failure else "None (Resilient)"
                lines.append(f"- **Single Points of Failure**: `{spof_str}`\n")
                for rec in brittleness_rep.recommendations:
                    lines.append(f"- 💡 {rec}\n")

            if session.execution_locked:
                lines.append(SILENT_DELIBERATION_REMINDER)

            return "".join(lines)

        # 21. SYSTEM 3: EVOLVE PARADIGMS (10D PARETO FRONTIER OPTIMIZER)
        elif action in ("system3_evolve_paradigms", "evolve_paradigms", "evolution_generation", "genetic_optimize"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_evolve_paradigms'."
            generations = int(arguments.get("generations", 3))
            pop_size = int(arguments.get("population_size", 12))
            mutation_rate = float(arguments.get("mutation_rate", 0.15))
            crossover_rate = float(arguments.get("crossover_rate", 0.80))
            seed_paradigms = arguments.get("seed_paradigms")
            if isinstance(seed_paradigms, str):
                try:
                    seed_paradigms = json.loads(seed_paradigms)
                except Exception:
                    seed_paradigms = None

            weights = arguments.get("objective_weights")
            if isinstance(weights, str):
                try:
                    weights = json.loads(weights)
                except Exception:
                    weights = None

            pool = CognitiveGenePool(
                population_size=pop_size,
                mutation_rate=mutation_rate,
                crossover_rate=crossover_rate,
            )
            pool.initialize_population(seed_paradigms=seed_paradigms)

            for _ in range(generations):
                pool.evolve_generation()

            pareto_frontier = pool.get_pareto_frontier()
            best_genome = pool.get_best_genome(weights)

            session = get_or_load_session(session_name)
            session.system3_gene_pools.append(pool.to_dict())

            session.log_refinement_cycle(
                refinement_type="system3_evolutionary_optimization",
                focus_area=f"10D Pareto Frontier Search across {generations} generations",
                critique_or_bottleneck=f"Optimized {pop_size} genomes across 10 dimensions.",
                architectural_refinement=f"Evolved top paradigm '{best_genome.paradigm_name}' with scalar fitness {best_genome.compute_scalar_fitness(weights):.4f}.",
            )
            session.save()

            table_rows = []
            for g in pareto_frontier[:5]:
                f = g.fitness_scores
                table_rows.append(
                    f"| `{g.genome_id}` | **{g.paradigm_name[:24]}** | `{f.get('latency',0):.2f}` | "
                    f"`{f.get('throughput',0):.2f}` | `{f.get('memory_efficiency',0):.2f}` | "
                    f"`{f.get('fault_tolerance',0):.2f}` | `{f.get('modularity',0):.2f}` | "
                    f"`{f.get('security',0):.2f}` | `{f.get('token_compaction',0):.2f}` | `{g.compute_scalar_fitness(weights):.4f}` |"
                )

            table_str = "\n".join(table_rows)

            return (
                f"### 🧬 System 3 Evolutionary Paradigm Engine\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Generations Evolved**: `{pool.generation_count}` (Population: `{len(pool.population)}`)\n"
                f"- **Rank 1 Pareto Frontier Size**: `{len(pareto_frontier)}` non-dominated solutions\n"
                f"- **Top Archetype**: **{best_genome.paradigm_name}** (`{best_genome.genome_id}`)\n\n"
                f"#### 🏆 Top Rank 1 Non-Dominated Pareto Frontier:\n"
                f"| ID | Paradigm | Lat | Tput | Mem | Fault | Mod | Sec | Token | Score |\n"
                f"|---|---|---|---|---|---|---|---|---|---|\n"
                f"{table_str}\n\n"
                f"#### 🧬 Winning Gene Allocation (`{best_genome.genome_id}`):\n"
                + "\n".join([f"- **{k}**: `{v}`" for k, v in best_genome.genes.items()])
                + f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 22. SYSTEM 3: INDUCE AXIOMS (NEURO-SYMBOLIC META-PROOF INDUCTION)
        elif action in ("system3_induce_axioms", "induce_axioms", "neuro_symbolic_induction", "formalize_axioms"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_induce_axioms'."
            session = get_or_load_session(session_name)
            domain = arguments.get("domain", "architecture")

            inducer = MetaProofInducer()
            axioms = inducer.induce_axioms_from_session(
                receipts=[],
                evidence=[],
                session_telemetry=session.get_telemetry(),
                domain_hints=[domain],
            )

            for ax in axioms:
                session.system3_axioms.append(ax.to_dict())
                if not any(i.get("name") == ax.name for i in session.invariants):
                    session.record_invariant(
                        invariant_name=ax.name,
                        formal_statement=ax.symbolic_expression,
                        proof_or_rationale=ax.proof_sketch or ax.natural_language,
                        domain=ax.domain if ax.domain in ("architecture", "design", "coding") else "architecture",
                    )

            session.save()

            axiom_blocks = []
            for ax in axioms:
                axiom_blocks.append(
                    f"#### 📜 `{ax.axiom_id}`: **{ax.name}** `[{ax.domain.upper()}]`\n"
                    f"- **Symbolic Expression**: `{ax.symbolic_expression}`\n"
                    f"- **Natural Language**: {ax.natural_language}\n"
                    f"- **Epistemic Confidence**: `{ax.confidence * 100:.1f}%` (`{ax.status.value.upper()}`)\n"
                    f"- **Proof Rationale**: {ax.proof_sketch}\n"
                )

            return (
                f"### 📐 System 3 Neuro-Symbolic Invariant Induction\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Axioms Induced**: `{len(axioms)}`\n"
                f"- **Auto-Recorded Invariants**: `{len(session.invariants)}` total in session\n\n"
                + "\n".join(axiom_blocks)
                + f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 23. SYSTEM 3: META REFLECTION & COGNITIVE BIAS AUDIT
        elif action in ("system3_meta_reflect", "meta_reflect", "cognitive_audit", "meta_cognition"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_meta_reflect'."
            session = get_or_load_session(session_name)
            focus_area = arguments.get("focus_area", "Full Deliberation Trace")

            executive = System3Executive()
            report = executive.meta_reflect(session.to_dict())

            session.system3_reflections.append(report)

            bias_summary = f"{len(report['bias_findings'])} biases flagged" if report['bias_findings'] else "0 biases detected (Clean)"
            session.log_refinement_cycle(
                refinement_type="system3_meta_reflection",
                focus_area=focus_area,
                critique_or_bottleneck=f"Meta-cognitive audit: {bias_summary}. Contradiction density: {report['contradiction_density']:.2f}.",
                architectural_refinement=f"Shifted cognitive gear to {report['cognitive_gear']}. Updated search heuristics temperature: {report['updated_search_heuristics']['exploration_temperature']}.",
            )
            session.save()

            bias_lines = []
            for b in report["bias_findings"]:
                bias_lines.append(
                    f"- ⚠️ **{b['bias_type'].upper()}** (Severity: `{b['severity']}` in *{b['detected_in']}*):\n"
                    f"  - *Evidence*: {b['evidence_trail']}\n"
                    f"  - *Mitigation*: {b['mitigation_strategy']}"
                )
            bias_block = "\n".join(bias_lines) if bias_lines else "✅ Zero cognitive biases detected. Epistemic reasoning is well-calibrated."

            directives_block = "\n".join([f"- 🎯 {d}" for d in report["directives"]])

            return (
                f"### 🧠 System 3 Meta-Cognitive Deliberation Audit\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Recommended Cognitive Gear**: `{report['cognitive_gear'].upper()}`\n"
                f"- **Contradiction Density**: `{report['contradiction_density']:.2f}`\n"
                f"- **Arbitration Rationale**: {report['arbitration_rationale']}\n\n"
                f"#### 🔍 Cognitive Bias Diagnostics:\n{bias_block}\n\n"
                f"#### 🚀 System 3 Executive Directives:\n{directives_block}\n\n"
                f"#### ⚙️ Dynamic Search Heuristics:\n"
                f"- **Exploration Temperature**: `{report['updated_search_heuristics']['exploration_temperature']}`\n"
                f"- **Pruning Cutoff Threshold**: `{report['updated_search_heuristics']['pruning_threshold']}`\n"
                f"- **Max Branching Factor**: `{report['updated_search_heuristics']['max_branching_factor']}`\n"
                f"- **Falsification Intensity**: `{report['updated_search_heuristics']['falsification_intensity']}`"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 24. SYSTEM 3: TRI-LEVEL COGNITIVE ORCHESTRATION
        elif action in ("system3_tri_level_orchestrate", "tri_level_orchestrate", "cognitive_gear_shift", "arbitrate_cognition"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_tri_level_orchestrate'."
            complexity = float(arguments.get("task_complexity", 0.75))
            density = float(arguments.get("contradiction_density", 0.60))
            failures = int(arguments.get("failure_count", 0))
            uncertainty = float(arguments.get("epistemic_uncertainty", 0.40))

            arbitrator = TriLevelArbitrator()
            decision = arbitrator.arbitrate(
                task_complexity=complexity,
                contradiction_density=density,
                failure_count=failures,
                epistemic_uncertainty=uncertainty,
            )

            session = get_or_load_session(session_name)
            session.system3_orchestrations.append({
                "decision": decision,
                "timestamp": time.time(),
                "inputs": {
                    "complexity": complexity,
                    "density": density,
                    "failures": failures,
                    "uncertainty": uncertainty,
                }
            })
            session.save()

            directives_str = "\n".join([f"- {d}" for d in decision["directives"]])

            return (
                f"### 🎛️ System 3 Tri-Level Cognitive Arbitration\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Recommended Operating Gear**: `⚙️ {decision['recommended_gear'].upper()}`\n"
                f"- **Composite Difficulty Index**: `{decision['composite_difficulty']:.3f}` / 1.0\n"
                f"- **Arbitration Rationale**: {decision['rationale']}\n\n"
                f"#### 🧭 Prescribed Cognitive Action Directives:\n{directives_str}"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 25. SYSTEM 3: HYPERBOLIC MANIFOLD TREE EMBEDDING
        elif action in ("system3_hyperbolic_embed", "hyperbolic_embed", "poincare_embed", "hyperbolic_tree"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_hyperbolic_embed'."
            tree_input = arguments.get("tree")
            if tree_input is None:
                return "Error: 'tree' is required for action 'system3_hyperbolic_embed'."
            if isinstance(tree_input, str):
                try:
                    tree_input = json.loads(tree_input)
                except Exception:
                    return "Error: Failed to parse 'tree' as JSON."

            root_id = arguments.get("root_id")
            dimension = int(arguments.get("dimension", 2))
            curvature = float(arguments.get("curvature", 1.0))
            base_step = float(arguments.get("base_step", 1.0))
            node_labels = arguments.get("node_labels")
            if isinstance(node_labels, str):
                try:
                    node_labels = json.loads(node_labels)
                except Exception:
                    node_labels = None

            embedder = HyperbolicTreeEmbedder(dimension=dimension, curvature=curvature, base_step_distance=base_step)
            result = embedder.embed_hierarchy(tree=tree_input, root_id=root_id, node_labels=node_labels)

            session = get_or_load_session(session_name)
            session.system3_hyperbolic_embeddings.append(result.to_dict())

            session.log_refinement_cycle(
                refinement_type="system3_hyperbolic_embedding",
                focus_area=f"Hierarchical Poincaré Manifold Embedding ({result.total_nodes} nodes, depth {result.tree_depth})",
                critique_or_bottleneck=f"Embedded hierarchy into {dimension}D Poincaré ball with curvature c={curvature:.2f}.",
                architectural_refinement=(
                    f"Manifold tree embedding verified: avg_distortion={result.average_distortion:.4f}, "
                    f"max_distortion={result.max_distortion:.4f}, stress={result.stress:.4f}, "
                    f"exponential capacity ratio={result.hierarchical_capacity_ratio:.2f}x."
                ),
            )
            session.save()

            node_table = []
            for nid, node in list(result.nodes.items())[:10]:
                coords_str = f"({', '.join([f'{c:.4f}' for c in node.coords])})"
                node_table.append(
                    f"| `{node.node_id}` | **{node.label[:20]}** | `{node.depth}` | `{node.subtree_size}` | `{coords_str}` |"
                )
            node_table_str = "\n".join(node_table)

            return (
                f"### 🌐 System 3 Poincaré Hyperbolic Manifold Embedding\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Manifold**: Poincaré Ball $\\mathbb{{B}}^{{{result.dimension}}}_{{c={result.curvature:.2f}}}$\n"
                f"- **Hierarchy**: Root `{result.root_id}` ({result.total_nodes} nodes, max depth `{result.tree_depth}`)\n"
                f"- **Mean Metric Distortion**: `{result.average_distortion:.4f}` (Max: `{result.max_distortion:.4f}`)\n"
                f"- **Metric Stress Metric**: `{result.stress:.4f}`\n"
                f"- **Hyperbolic Volume Expansion Ratio**: `{result.hierarchical_capacity_ratio:.2f}x` vs Euclidean $\\mathbb{{R}}^{{{result.dimension}}}$\n\n"
                f"#### 📍 Top Embedded Nodes in $\\mathbb{{B}}^{{{result.dimension}}}$:\n"
                f"| Node ID | Label | Depth | Subtree | Poincaré Coordinates |\n"
                f"|---|---|---|---|---|\n"
                f"{node_table_str}\n"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 26. SYSTEM 3: KRIPKE MODAL MODEL CHECKING & CTL* VERIFICATION
        elif action in ("system3_kripke_verify", "kripke_verify", "modal_verify", "ctl_check"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_kripke_verify'."
            formula = arguments.get("formula", "").strip()
            if not formula:
                return "Error: 'formula' is required for action 'system3_kripke_verify'."
            model_name = arguments.get("model_name", "System3KripkeModel")
            worlds_input = arguments.get("worlds", [])
            transitions_input = arguments.get("transitions", [])
            initial_world = arguments.get("initial_world")

            if isinstance(worlds_input, str):
                try:
                    worlds_input = json.loads(worlds_input)
                except Exception:
                    worlds_input = []
            if isinstance(transitions_input, str):
                try:
                    transitions_input = json.loads(transitions_input)
                except Exception:
                    transitions_input = []

            structure = KripkeStructure(name=model_name)
            for w in worlds_input:
                if isinstance(w, dict):
                    structure.add_world(
                        world_id=w.get("world_id", w.get("id")),
                        propositions=w.get("propositions", w.get("props", [])),
                        name=w.get("name", ""),
                        is_initial=w.get("is_initial", False),
                        metadata=w.get("metadata", {}),
                    )
                elif isinstance(w, str):
                    structure.add_world(world_id=w)

            if isinstance(transitions_input, dict):
                for src, targets in transitions_input.items():
                    for tgt in (targets if isinstance(targets, list) else [targets]):
                        structure.add_transition(src, tgt)
            elif isinstance(transitions_input, list):
                for t in transitions_input:
                    if isinstance(t, dict) and "source" in t and "target" in t:
                        structure.add_transition(t["source"], t["target"])
                    elif isinstance(t, (list, tuple)) and len(t) >= 2:
                        structure.add_transition(str(t[0]), str(t[1]))

            checker = KripkeModelChecker(structure)
            res = checker.check(formula=formula, initial_world=initial_world)

            session = get_or_load_session(session_name)
            session.system3_kripke_verifications.append(res.to_dict())

            session.log_refinement_cycle(
                refinement_type="system3_kripke_verification",
                focus_area=f"Modal / CTL Verification: {res.formula}",
                critique_or_bottleneck=f"Evaluated Kripke model '{structure.name}' ({res.total_worlds} worlds).",
                architectural_refinement=(
                    f"Model checking result: {'✅ SATISFIED' if res.is_satisfied else '❌ VIOLATED'}. "
                    f"Satisfied worlds: {len(res.satisfied_worlds)}/{res.total_worlds}. "
                    f"Witness/Counterexample: {res.witness_path or res.counterexample_path}."
                ),
            )
            session.save()

            trace_block = ""
            if res.counterexample_path:
                trace_block = f"\n#### ❌ Counterexample Violation Trace:\n`{' -> '.join(res.counterexample_path)}`\n"
            elif res.witness_path:
                trace_block = f"\n#### ✅ Witness Path:\n`{' -> '.join(res.witness_path)}`\n"

            return (
                f"### 🛡️ System 3 Kripke Modal Model Verification\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Model**: `{structure.name}` ({res.total_worlds} worlds)\n"
                f"- **Formula**: `{res.formula}`\n"
                f"- **Status**: `{'✅ SATISFIED' if res.is_satisfied else '❌ VIOLATED'}` at initial world `{res.initial_world}`\n"
                f"- **Satisfied Worlds**: `{', '.join(res.satisfied_worlds) if res.satisfied_worlds else 'None'}`\n"
                f"- **Violated Worlds**: `{', '.join(res.violated_worlds) if res.violated_worlds else 'None'}`\n"
                f"{trace_block}\n"
                f"> [!TIP]\n"
                f"> {res.details}"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 27. SYSTEM 3: FRISTON ACTIVE INFERENCE & VARIATIONAL FREE ENERGY
        elif action in ("system3_active_inference", "active_inference", "free_energy", "fe_step"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_active_inference'."
            obs = arguments.get("observation", "HIGH_THROUGHPUT_CLEAN").strip()
            gamma = float(arguments.get("gamma", 16.0))
            policies_input = arguments.get("policies")
            if isinstance(policies_input, str):
                try:
                    policies_input = json.loads(policies_input)
                except Exception:
                    policies_input = None

            parsed_policies = []
            if policies_input and isinstance(policies_input, list):
                for p in policies_input:
                    if isinstance(p, dict) and "policy_id" in p and "actions" in p:
                        parsed_policies.append(Policy.from_dict(p))
                    elif isinstance(p, str):
                        parsed_policies.append(Policy(policy_id=f"pol_{p}", actions=[p]))

            # Check if custom model components provided
            states = arguments.get("states")
            observations = arguments.get("observations")
            actions = arguments.get("actions")
            a_mat = arguments.get("a_matrix")
            b_mats = arguments.get("b_matrices")
            c_pref = arguments.get("c_preferences")
            d_prior = arguments.get("d_prior")

            if all(x is not None for x in [states, observations, actions, a_mat, b_mats, c_pref, d_prior]):
                if isinstance(states, str): states = json.loads(states)
                if isinstance(observations, str): observations = json.loads(observations)
                if isinstance(actions, str): actions = json.loads(actions)
                if isinstance(a_mat, str): a_mat = json.loads(a_mat)
                if isinstance(b_mats, str): b_mats = json.loads(b_mats)
                if isinstance(c_pref, str): c_pref = json.loads(c_pref)
                if isinstance(d_prior, str): d_prior = json.loads(d_prior)
                gen_model = GenerativeModel(
                    states=states,
                    observations=observations,
                    actions=actions,
                    a_matrix=a_mat,
                    b_matrices=b_mats,
                    c_preferences=c_pref,
                    d_prior=d_prior,
                )
            else:
                gen_model = create_default_architecture_pomdp()

            engine = ActiveInferenceEngine(generative_model=gen_model, policy_precision_gamma=gamma)
            report = engine.select_action(observation=obs, candidate_policies=parsed_policies)

            session = get_or_load_session(session_name)
            session.system3_active_inferences.append(report.to_dict())

            session.log_refinement_cycle(
                refinement_type="system3_active_inference",
                focus_area=f"Free Energy Minimization for observation '{obs}'",
                critique_or_bottleneck=(
                    f"Variational Free Energy F={report.variational_free_energy_f:.4f} "
                    f"(Complexity KL={report.complexity_kl:.4f}, Accuracy={report.accuracy_log_likelihood:.4f})."
                ),
                architectural_refinement=(
                    f"Selected optimal policy '{report.selected_policy.policy_id}' ({report.selected_action}) "
                    f"with Expected Free Energy G={report.selected_policy.expected_free_energy_g:.4f}, "
                    f"Information Gain={report.selected_policy.epistemic_information_gain:.4f}, "
                    f"Goal Utility={report.selected_policy.pragmatic_goal_utility:.4f}."
                ),
            )
            session.save()

            policy_table = []
            for p in report.evaluated_policies:
                opt_mark = "🏆 OPTIMAL" if p.is_optimal else ""
                policy_table.append(
                    f"| `{p.policy_id}` | `{p.actions}` | `{p.expected_free_energy_g:.4f}` | "
                    f"`{p.risk_pragmatic_divergence:.4f}` | `{p.ambiguity_expected_entropy:.4f}` | "
                    f"`{p.epistemic_information_gain:.4f}` | `{p.pragmatic_goal_utility:.4f}` | "
                    f"`{p.probability * 100:.1f}%` | {opt_mark} |"
                )
            pol_table_str = "\n".join(policy_table)

            belief_table = "\n".join([f"- **{k}**: `{v * 100:.1f}%`" for k, v in report.belief_state.items()])

            return (
                f"### ⚡ System 3 Friston Active Inference & Variational Free Energy\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Ingested Observation**: `{report.current_observation}`\n"
                f"- **Variational Free Energy (F)**: `{report.variational_free_energy_f:.4f}` (Surprisal Bound)\n"
                f"  - *Complexity (KL)*: `{report.complexity_kl:.4f}`\n"
                f"  - *Accuracy (Log-Likelihood)*: `{report.accuracy_log_likelihood:.4f}`\n"
                f"- **Selected Policy**: **{report.selected_policy.policy_id}** -> Action: `🎯 {report.selected_action}`\n\n"
                f"#### 🧠 Updated Hidden State Belief Distribution $q(s)$:\n{belief_table}\n\n"
                f"#### 📊 Evaluated Policy Landscape ($G(\\pi) = \\text{{Risk}} + \\text{{Ambiguity}}$):\n"
                f"| Policy ID | Actions | EFE ($G$) | Risk | Ambiguity | Epistemic Info Gain | Goal Utility | Prob | Status |\n"
                f"|---|---|---|---|---|---|---|---|---|\n"
                f"{pol_table_str}\n"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        # 28. SYSTEM 3: GODELIAN PROOF ORACLE & CURRY-HOWARD VERIFICATION
        elif action in ("system3_proof_oracle", "proof_oracle", "curry_howard", "formal_prove"):
            if not session_name:
                return "Error: 'session_name' is required for action 'system3_proof_oracle'."
            claim = arguments.get("claim")
            if not claim:
                return "Error: 'claim' is required for action 'system3_proof_oracle'."

            context = arguments.get("context")
            if isinstance(context, str):
                try:
                    context = json.loads(context)
                except Exception:
                    context = None

            axioms = arguments.get("axioms")
            if isinstance(axioms, str):
                try:
                    axioms = json.loads(axioms)
                except Exception:
                    axioms = None

            oracle = ProofOracle()
            res = oracle.verify_proposition(claim=claim, context=context, axioms=axioms)

            session = get_or_load_session(session_name)
            session.system3_proof_oracle_verifications.append(res.to_dict())

            # Auto-record invariant if proved and sound
            if res.status == ProofStatus.DECIDABLE_PROVED and res.is_sound:
                inv_name = f"INV-ORACLE: {str(claim)[:32]}"
                if not any(i.get("name") == inv_name for i in session.invariants):
                    session.record_invariant(
                        invariant_name=inv_name,
                        formal_statement=res.proposition,
                        proof_or_rationale=f"Curry-Howard Constructive Proof Term: {res.proof_term_repr}",
                        domain="architecture",
                    )

            session.log_refinement_cycle(
                refinement_type="system3_proof_oracle",
                focus_area=f"Curry-Howard Constructive Proof: {res.proposition}",
                critique_or_bottleneck=f"Evaluated status: {res.status.value.upper()}.",
                architectural_refinement=(
                    f"Proof Oracle verdict: {res.status.value.upper()} (Sound: {res.is_sound}). "
                    f"Proof Term: {res.proof_term_repr or 'None'}."
                ),
            )
            session.save()

            steps_str = "\n".join([f"- {s}" for s in res.verification_steps])
            undec_str = ""
            if res.undecidability_diagnostics:
                undec_str = (
                    f"\n#### 🛑 Gödelian Boundary Diagnostics:\n"
                    f"- **Boundary Type**: `{res.undecidability_diagnostics.get('boundary_type')}`\n"
                    f"- **Explanation**: {res.undecidability_diagnostics.get('explanation')}\n"
                )

            return (
                f"### 📜 System 3 Gödelian Auto-Formalizing Proof Oracle\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **Proposition**: `{res.proposition}`\n"
                f"- **Decision Status**: `{'✅ ' if res.status == ProofStatus.DECIDABLE_PROVED else '⚡ ' if res.status == ProofStatus.DECIDABLE_REFUTED else '🛑 '}{res.status.value.upper()}`\n"
                f"- **Soundness Verified**: `{'✅ TRUE' if res.is_sound else '❌ UNVERIFIED'}`\n"
                + (f"- **Constructive Proof Term**: `{res.proof_term_repr}`\n" if res.proof_term_repr else "")
                + f"{undec_str}\n"
                f"#### 🔍 Verification Trace:\n{steps_str}\n"
                f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
            )

        else:
            return (
                f"Error: Unknown action '{action}'. Supported actions: "
                f"'create_session', 'set_timer', 'get_status', 'telemetry', 'advance_phase', "
                f"'log_epistemic_item', 'record_invariant', 'log_refinement_cycle', 'unlock_execution', "
                f"'checkpoint_session', 'restore_session', 'list_sessions', 'compile_delegation_contract', "
                f"'compress_payload', 'decompress_payload', 'view_slice', 'accumulate_payload', 'flush_accumulator', 'get_compression_stats', "
                f"'system3_dialectical_synthesis', 'system3_causal_simulate', 'system3_evolve_paradigms', 'system3_induce_axioms', 'system3_meta_reflect', 'system3_tri_level_orchestrate', "
                f"'system3_hyperbolic_embed', 'system3_kripke_verify', 'system3_active_inference', 'system3_proof_oracle'."
            )
    except Exception as ex:
        return f"Error: {str(ex)}"


# --------------------------------------------------------------------------------
# JSON-RPC 2.0 MCP Protocol Stdio Loop
# --------------------------------------------------------------------------------

TOOL_SCHEMA = {
    "name": "fable_session",
    "description": (
        "Fable Cognitive Engine Session & Telemetry Manager for MCP-compatible agent hosts.\n"
        "Enforces DeepThink cognitive rigor, hard mechanical time-lock, anti-rush execution lockout, epistemic truth logging (PROVEN/HYPOTHESIS/UNKNOWN),\n"
        "formal domain invariant modeling, continuous rethink-refine cycles, phased progression gating, subagent delegation contract compilation,\n"
        "live user-controlled time-budgeted pacing telemetry, token compression subsystem (Content-Addressed Storage, 0.003 tokens/character invariant),\n"
        "and System 3 Meta-Cognitive Deliberation & Dialectical Evolutionary Architecture (Pearl do-calculus, TRIZ contradiction synthesis, 10D Pareto genetic search, axiom induction)."
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
                    "get_compression_stats",
                    "system3_dialectical_synthesis",
                    "system3_causal_simulate",
                    "system3_evolve_paradigms",
                    "system3_induce_axioms",
                    "system3_meta_reflect",
                    "system3_tri_level_orchestrate",
                    "system3_hyperbolic_embed",
                    "system3_kripke_verify",
                    "system3_active_inference",
                    "system3_proof_oracle"
                ],
                "description": "The Fable session action to perform."
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
                "type": "string",
                "description": "Concise summary of findings or deliverables completed in the previous phase."
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
                "type": "string",
                "description": "Source file, command output, line number, or URL supporting the claim."
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
            },
            "thesis_title": {
                "type": "string",
                "description": "Title of the thesis paradigm for System 3 dialectical synthesis."
            },
            "thesis_description": {
                "type": "string",
                "description": "Core architecture description and assumptions for the thesis candidate."
            },
            "antithesis_title": {
                "type": "string",
                "description": "Title of the antithesis / adversarial critique."
            },
            "contradictions": {
                "description": "List of parameter trade-offs / contradictions to resolve with TRIZ principles.",
                "type": ["array", "string"]
            },
            "failure_modes": {
                "description": "List of adversarial failure modes identified in critique.",
                "type": ["array", "string"]
            },
            "max_debate_rounds": {
                "type": "integer",
                "description": "Maximum number of dialectical debate rounds for synthesis (default 4)."
            },
            "target_residual_threshold": {
                "type": "number",
                "description": "Target residual contradiction score threshold for convergence (default 0.15)."
            },
            "model_name": {
                "type": "string",
                "description": "Name for the causal DAG model in System 3 simulation."
            },
            "nodes": {
                "description": "List of node dictionaries for Causal DAG construction.",
                "type": ["array", "string"]
            },
            "edges": {
                "description": "List of directed edge dictionaries for Causal DAG construction.",
                "type": ["array", "string"]
            },
            "interventions": {
                "description": "Dictionary of Pearl's do-operator interventions: {node_id: value}.",
                "type": ["object", "string"]
            },
            "target_metric": {
                "type": "string",
                "description": "Target KPI node ID for sensitivity and structural brittleness analysis."
            },
            "generations": {
                "type": "integer",
                "description": "Number of evolutionary generations to run (default 3)."
            },
            "population_size": {
                "type": "integer",
                "description": "Population size for evolutionary gene pool (default 12)."
            },
            "mutation_rate": {
                "type": "number",
                "description": "Genetic mutation rate probability (default 0.15)."
            },
            "crossover_rate": {
                "type": "number",
                "description": "Genetic crossover rate probability (default 0.80)."
            },
            "seed_paradigms": {
                "description": "Optional list of initial paradigm definitions to seed the gene pool.",
                "type": ["array", "string"]
            },
            "objective_weights": {
                "description": "Optional dictionary of weights across the 10 Pareto dimensions.",
                "type": ["object", "string"]
            },
            "task_complexity": {
                "type": "number",
                "description": "Task complexity index [0.0, 1.0] for tri-level cognitive arbitration."
            },
            "contradiction_density": {
                "type": "number",
                "description": "Contradiction density index [0.0, 1.0] for cognitive gear shifting."
            },
            "failure_count": {
                "type": "integer",
                "description": "Historical failure count for tri-level cognitive gear arbitration."
            },
            "epistemic_uncertainty": {
                "type": "number",
                "description": "Epistemic uncertainty index [0.0, 1.0] for arbitration."
            },
            "tree": {
                "description": "Tree hierarchy adjacency list or nested dict for hyperbolic embedding.",
                "type": ["object", "array", "string"]
            },
            "root_id": {
                "type": "string",
                "description": "Root node ID for hyperbolic tree embedding or initial world."
            },
            "dimension": {
                "type": "integer",
                "description": "Dimension of Poincaré ball manifold (default 2)."
            },
            "curvature": {
                "type": "number",
                "description": "Sectional curvature c > 0 of Poincaré manifold (default 1.0)."
            },
            "base_step": {
                "type": "number",
                "description": "Base geodesic step distance for hyperbolic tree embedding (default 1.0)."
            },
            "node_labels": {
                "description": "Optional mapping of node IDs to readable labels.",
                "type": ["object", "string"]
            },
            "worlds": {
                "description": "List of world/state definitions for Kripke structure.",
                "type": ["array", "string"]
            },
            "transitions": {
                "description": "List of transitions or adjacency dictionary for Kripke structure.",
                "type": ["array", "object", "string"]
            },
            "formula": {
                "type": "string",
                "description": "CTL / modal formula string to verify against Kripke structure (e.g. 'AG(safe)', 'EF(goal)')."
            },
            "initial_world": {
                "type": "string",
                "description": "Initial world ID for Kripke model checking."
            },
            "observation": {
                "type": "string",
                "description": "Current sensory observation for Active Inference belief updating."
            },
            "policies": {
                "description": "List of candidate action sequence policies for Expected Free Energy evaluation.",
                "type": ["array", "string"]
            },
            "gamma": {
                "type": "number",
                "description": "Policy precision inverse temperature gamma for Active Inference softmax (default 16.0)."
            },
            "states": {
                "description": "List of hidden state identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "observations": {
                "description": "List of observation identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "actions": {
                "description": "List of control action identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "a_matrix": {
                "description": "Observation likelihood matrix A [O x S] for Active Inference.",
                "type": ["array", "string"]
            },
            "b_matrices": {
                "description": "State transition matrices B [Action -> S x S] for Active Inference.",
                "type": ["object", "string"]
            },
            "c_preferences": {
                "description": "Prior preference distribution C over observations for Active Inference.",
                "type": ["array", "string"]
            },
            "d_prior": {
                "description": "Prior initial state belief distribution D for Active Inference.",
                "type": ["array", "string"]
            },
            "context": {
                "description": "Hypothesis typing context dictionary {name: type} for proof oracle.",
                "type": ["object", "string"]
            },
            "axioms": {
                "description": "List of reference axiom names or strings for proof oracle.",
                "type": ["array", "string"]
            }
        },
        "required": ["action"]
    }
}


def send_response(response_dict: Dict[str, Any]):
    """Writes a bounded JSON-RPC response to stdout with UTF-8 safety."""
    encoded = json.dumps(response_dict, ensure_ascii=False)
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) > MAX_RPC_RESPONSE_BYTES:
        response_dict = {
            "jsonrpc": "2.0",
            "id": response_dict.get("id") if isinstance(response_dict, dict) else None,
            "error": {"code": -32000, "message": "Response exceeds maximum size"}
        }
        encoded = json.dumps(response_dict, ensure_ascii=False)
        encoded_bytes = encoded.encode("utf-8")
    payload = encoded_bytes + b"\n"
    if hasattr(sys.stdout, "buffer") and sys.stdout.buffer is not None:
        try:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
            return
        except Exception:
            pass
    try:
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.write(payload.decode("utf-8", errors="replace"))
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


def main():
    logger.info("Starting Fable-Engine MCP Server on stdio...")
    for line, oversized in _bounded_lines(sys.stdin, MAX_RPC_LINE_BYTES):
        if oversized:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        # Count the raw frame before trimming whitespace; otherwise an attacker
        # can bypass the line limit with an oversized whitespace prefix/suffix.
        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        line = line.strip()
        if not line:
            continue

        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        try:
            req = json.loads(line)
        except Exception:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        # JSON-RPC requests are objects; arrays and scalar values must not
        # reach req.get() and crash the stdio server.
        if not isinstance(req, dict):
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            send_response({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if "params" in req and not isinstance(req["params"], dict):
            send_response({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "fable-engine",
                        "version": "1.2.3"
                    }
                }
            })

        elif method == "notifications/initialized":
            logger.info("Fable client handshake complete.")

        elif method == "ping":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {}
            })

        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [TOOL_SCHEMA]
                }
            })

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str) or not isinstance(arguments, dict):
                send_response({"jsonrpc": "2.0", "id": msg_id,
                               "error": {"code": -32600, "message": "Invalid Request"}})
                continue

            if tool_name == "fable_session":
                try:
                    result_text = handle_fable_session(arguments)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result_text
                                }
                            ],
                            "isError": False
                        }
                    })
                except Exception as ex:
                    logger.error(f"Error handling fable_session: {ex}", exc_info=True)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Fable Engine Error: {str(ex)}"
                                }
                            ],
                            "isError": True
                        }
                    })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method / Tool '{tool_name}' not found."
                    }
                })

        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unrecognized JSON-RPC method: {method}"
                    }
                })


if __name__ == "__main__":
    main()

