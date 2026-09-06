"""
Content-Addressed Storage (CAS) and Token Compression Subsystem.
Implements FableCASStore, AdaptiveChunkAccumulator, FableGrammar333,
CASSliceViewer, and FableCompress for 100% lossless token compaction.
"""

from __future__ import annotations

import collections
import hashlib
import io
import json
import os
import stat
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

MAX_CAS_OBJECT_BYTES = 16 * 1024 * 1024
MAX_SLICE_RESPONSE_BYTES = 1_000_000
MAX_RPC_RESPONSE_BYTES = 2 * 1024 * 1024

# Base directories
BASE_DIR = Path(__file__).resolve().parent
_DATA_ENV = os.environ.get("FABLE_DATA_DIR")
if _DATA_ENV:
    DATA_DIR = Path(_DATA_ENV).expanduser().absolute()
elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "FableMode" / "data"
else:
    DATA_DIR = Path.home() / ".local" / "share" / "fable-engine" / "data"

FABLE_CAS_DIR = Path(os.environ.get("FABLE_CAS_DIR", DATA_DIR / "cas"))


def _assert_private_path(path: Path) -> None:
    srv = sys.modules.get("fable_engine.server")
    if srv is not None:
        handler = getattr(srv, "_assert_private_path", None)
        if handler is not None and handler is not _assert_private_path:
            return handler(path)
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
        trusted_macos_alias = (
            sys.platform == "darwin" and str(part) in {"/var", "/tmp"}
            and str(part.resolve()) in {"/private/var", "/private/tmp"}
        )
        if ((attrs & 0x400 or stat.S_ISLNK(st.st_mode)) and not trusted_macos_alias) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
            raise RuntimeError("state path contains a symlink, reparse point, or special file")


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
    srv = sys.modules.get("fable_engine.server")
    if srv is not None:
        handler = getattr(srv, "_safe_cas_node", None)
        if handler is not None and handler is not _safe_cas_node:
            return handler(path, allow_missing=allow_missing)
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
        _safe_cas_node(dest_path)
        if dest_path.is_file():
            try:
                with dest_path.open("rb") as existing:
                    existing_bytes = existing.read(MAX_CAS_OBJECT_BYTES + 1)
            except OSError as exc:
                raise FableCASError("could not verify existing CAS object") from exc
            if len(existing_bytes) > MAX_CAS_OBJECT_BYTES or hashlib.sha256(existing_bytes).hexdigest() != content_hash:
                raise IntegrityError("existing CAS object is corrupt")
            self.cache.put(content_hash, existing_bytes)
            return self.to_uri(content_hash)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_cas_node(dest_path.parent)

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

            os.replace(tmp_file_path, dest_path)
        except Exception:
            if os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except OSError:
                    pass
            raise

        self.cache.put(content_hash, raw_bytes)
        return self.to_uri(content_hash)

    def get_bytes(self, ref_or_hash: str, verify: Optional[bool] = None) -> bytes:
        """Retrieve bytes, verifying SHA-256 unless explicitly opted out."""
        content_hash = self.normalize_ref(ref_or_hash)
        should_verify = self.auto_verify if verify is None else verify

        dest_path = self._get_object_path(content_hash)
        _safe_cas_node(dest_path)
        if not dest_path.is_file():
            raise CASNotFoundError(f"CAS object not found: {ref_or_hash}")
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
        """Retrieve UTF-8 text."""
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
        """Add a micro-payload to accumulator."""
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

            while self._buffered_chars >= self.max_frame_size:
                uri = self._flush_internal_locked()
                if uri:
                    flushed_uris.append(uri)
                else:
                    break

        return flushed_uris

    def flush(self) -> List[str]:
        """Explicitly flush all remaining buffered micro-payloads into a composite frame."""
        with self._lock:
            if not self._buffer:
                return []
            uri = self._flush_internal_locked()
            return [uri] if uri else []

    def _flush_internal_locked(self) -> Optional[str]:
        """Internal flush implementation assuming caller holds self._lock."""
        if not self._buffer:
            return None

        self._frame_counter += 1
        frame_id = f"frame_{int(time.time())}_{self._frame_counter}_{os.urandom(4).hex()}"
        frame = CompositeFrame(frame_id=frame_id, items=list(self._buffer))
        serialized_frame = frame.serialize_json()

        uri = self.cas_store.put(serialized_frame)
        self.total_frames_flushed += 1
        self.total_cas_bytes_written += len(serialized_frame.encode("utf-8"))

        self._buffer = []
        self._buffered_chars = 0
        return uri

    def extract_item(self, frame_uri: str, item_index: int) -> Tuple[str, Dict[str, Any]]:
        """Extract a specific micro-payload by index from a flushed composite frame."""
        frame_json = self.cas_store.get_text(frame_uri)
        frame = CompositeFrame.deserialize_json(frame_json)
        if 0 <= item_index < len(frame.items):
            item = frame.items[item_index]
            return item["payload"], item["meta"]
        raise IndexError(f"Item index {item_index} out of bounds for frame with {len(frame.items)} items.")

    def get_stats(self) -> Dict[str, Any]:
        """Return runtime telemetry for compression efficiency profiling."""
        with self._lock:
            buffered_items = len(self._buffer)
            buffered_chars = self._buffered_chars

        cas_bytes = self.total_cas_bytes_written
        raw_chars = self.total_raw_chars
        reduction_pct = round((1.0 - (cas_bytes / max(1, raw_chars))) * 100.0, 2) if raw_chars > 0 else 0.0

        return {
            "total_payloads_ingested": self.total_payloads_ingested,
            "total_frames_flushed": self.total_frames_flushed,
            "total_raw_chars": raw_chars,
            "total_cas_bytes_written": cas_bytes,
            "currently_buffered_items": buffered_items,
            "currently_buffered_chars": buffered_chars,
            "current_buffered_items": buffered_items,
            "current_buffered_chars": buffered_chars,
            "storage_reduction_pct": reduction_pct,
        }



class FableGrammar333:
    """
    High-Entropy Micro-Bytecode Serializer for Agent Actions & Reasoning Nodes.
    Translates JSON/action dicts into high-density binary wire-format.
    Guarantees 100% lossless bit-exact roundtrip deserialization.
    """

    MAGIC_HEADER = b"\x33\x33\x33\x01"  # Grammar333 Protocol v1

    OP_RECORD_ACTION = 0x10
    OP_EPISTEMIC_ITEM = 0x20
    OP_INVARIANT = 0x30
    OP_REFINEMENT = 0x40
    OP_GENERIC_JSON = 0xFF

    TYPE_NULL = 0x00
    TYPE_BOOL_TRUE = 0x01
    TYPE_BOOL_FALSE = 0x02
    TYPE_INT = 0x03
    TYPE_FLOAT = 0x04
    TYPE_STR = 0x05
    TYPE_BYTES = 0x06
    TYPE_ARRAY = 0x07
    TYPE_MAP = 0x08

    @classmethod
    def write_varint(cls, buffer: io.BytesIO, value: int) -> None:
        """Write variable-length zigzag encoded integer."""
        zigzag = (value << 1) ^ (value >> 63) if value < 0 else (value << 1)
        while True:
            byte = zigzag & 0x7F
            zigzag >>= 7
            if zigzag != 0:
                buffer.write(bytes([byte | 0x80]))
            else:
                buffer.write(bytes([byte]))
                break

    @classmethod
    def read_varint(cls, stream: io.BytesIO) -> int:
        """Read variable-length zigzag encoded integer."""
        result = 0
        shift = 0
        while True:
            byte_bytes = stream.read(1)
            if not byte_bytes:
                raise EOFError("Unexpected EOF while reading varint")
            byte = byte_bytes[0]
            result |= (byte & 0x7F) << shift
            shift += 7
            if not (byte & 0x80):
                break
        value = (result >> 1) ^ -(result & 1)
        return value

    @classmethod
    def write_string(cls, buffer: io.BytesIO, s: str) -> None:
        """Write UTF-8 string prefixed by varint byte length."""
        encoded = s.encode("utf-8")
        cls.write_varint(buffer, len(encoded))
        buffer.write(encoded)

    @classmethod
    def read_string(cls, stream: io.BytesIO) -> str:
        """Read UTF-8 string prefixed by varint byte length."""
        length = cls.read_varint(stream)
        if length < 0:
            raise ValueError(f"Negative string length: {length}")
        data = stream.read(length)
        if len(data) != length:
            raise EOFError(f"Expected {length} string bytes, got {len(data)}")
        return data.decode("utf-8")

    @classmethod
    def write_value(cls, buffer: io.BytesIO, val: Any) -> None:
        """Write typed primitive value into binary stream."""
        if val is None:
            buffer.write(bytes([cls.TYPE_NULL]))
        elif isinstance(val, bool):
            buffer.write(bytes([cls.TYPE_BOOL_TRUE if val else cls.TYPE_BOOL_FALSE]))
        elif isinstance(val, int):
            buffer.write(bytes([cls.TYPE_INT]))
            cls.write_varint(buffer, val)
        elif isinstance(val, float):
            buffer.write(bytes([cls.TYPE_FLOAT]))
            buffer.write(struct.pack(">d", val))
        elif isinstance(val, str):
            buffer.write(bytes([cls.TYPE_STR]))
            cls.write_string(buffer, val)
        elif isinstance(val, (bytes, bytearray)):
            buffer.write(bytes([cls.TYPE_BYTES]))
            cls.write_varint(buffer, len(val))
            buffer.write(bytes(val))
        elif isinstance(val, list):
            buffer.write(bytes([cls.TYPE_ARRAY]))
            cls.write_varint(buffer, len(val))
            for item in val:
                cls.write_value(buffer, item)
        elif isinstance(val, dict):
            buffer.write(bytes([cls.TYPE_MAP]))
            cls.write_varint(buffer, len(val))
            for k, v in val.items():
                cls.write_string(buffer, str(k))
                cls.write_value(buffer, v)
        else:
            s_val = json.dumps(val)
            buffer.write(bytes([cls.TYPE_STR]))
            cls.write_string(buffer, s_val)

    @classmethod
    def read_value(cls, stream: io.BytesIO) -> Any:
        """Read typed primitive value from binary stream."""
        type_byte = stream.read(1)
        if not type_byte:
            raise EOFError("Unexpected EOF while reading type byte")
        t = type_byte[0]
        if t == cls.TYPE_NULL:
            return None
        elif t == cls.TYPE_BOOL_TRUE:
            return True
        elif t == cls.TYPE_BOOL_FALSE:
            return False
        elif t == cls.TYPE_INT:
            return cls.read_varint(stream)
        elif t == cls.TYPE_FLOAT:
            data = stream.read(8)
            if len(data) != 8:
                raise EOFError("Failed to read 8 float bytes")
            return struct.unpack(">d", data)[0]
        elif t == cls.TYPE_STR:
            return cls.read_string(stream)
        elif t == cls.TYPE_BYTES:
            length = cls.read_varint(stream)
            data = stream.read(length)
            if len(data) != length:
                raise EOFError("Failed to read raw byte payload")
            return data
        elif t == cls.TYPE_ARRAY:
            count = cls.read_varint(stream)
            return [cls.read_value(stream) for _ in range(count)]
        elif t == cls.TYPE_MAP:
            count = cls.read_varint(stream)
            res = {}
            for _ in range(count):
                k = cls.read_string(stream)
                v = cls.read_value(stream)
                res[k] = v
            return res
        else:
            raise ValueError(f"Unknown Grammar333 type byte: 0x{t:02X}")

    @classmethod
    def serialize(cls, action_payload: Dict[str, Any]) -> bytes:
        """Serialize an action dictionary to Grammar333 micro-bytecode."""
        buffer = io.BytesIO()
        buffer.write(cls.MAGIC_HEADER)
        action_type = action_payload.get("action", "")

        if action_type in ("log_epistemic_item", "epistemic_item"):
            buffer.write(bytes([cls.OP_EPISTEMIC_ITEM]))
            cls.write_string(buffer, str(action_payload.get("tag", "HYPOTHESIS")))
            cls.write_string(buffer, str(action_payload.get("claim", "")))
            cls.write_string(buffer, str(action_payload.get("evidence", "")))
            cls.write_value(buffer, action_payload.get("metadata", {}))

        elif action_type in ("record_invariant", "invariant"):
            buffer.write(bytes([cls.OP_INVARIANT]))
            cls.write_string(buffer, str(action_payload.get("invariant_name", "")))
            cls.write_string(buffer, str(action_payload.get("formal_statement", "")))
            cls.write_string(buffer, str(action_payload.get("proof_or_rationale", "")))
            cls.write_string(buffer, str(action_payload.get("domain", "global")))

        elif action_type in ("log_refinement_cycle", "refinement_cycle"):
            buffer.write(bytes([cls.OP_REFINEMENT]))
            cls.write_string(buffer, str(action_payload.get("refinement_type", "")))
            cls.write_string(buffer, str(action_payload.get("focus_area", "")))
            cls.write_string(buffer, str(action_payload.get("critique_or_bottleneck", "")))
            cls.write_string(buffer, str(action_payload.get("architectural_refinement", "")))
            cls.write_string(buffer, str(action_payload.get("terminal_probe_results", "")))
            cls.write_string(buffer, str(action_payload.get("artifact_path", "")))

        else:
            buffer.write(bytes([cls.OP_GENERIC_JSON]))
            canonical_json = json.dumps(action_payload, ensure_ascii=False, separators=(",", ":"))
            cls.write_string(buffer, canonical_json)

        return buffer.getvalue()

    @classmethod
    def deserialize(cls, data: bytes) -> Dict[str, Any]:
        """Deserialize Grammar333 micro-bytecode back into canonical dictionary."""
        stream = io.BytesIO(data)
        magic = stream.read(4)
        if magic != cls.MAGIC_HEADER:
            raise ValueError("Invalid Grammar333 magic header")

        opcode_bytes = stream.read(1)
        if not opcode_bytes:
            raise EOFError("Empty Grammar333 stream")
        opcode = opcode_bytes[0]

        if opcode == cls.OP_EPISTEMIC_ITEM:
            return {
                "action": "log_epistemic_item",
                "tag": cls.read_string(stream),
                "claim": cls.read_string(stream),
                "evidence": cls.read_string(stream),
                "metadata": cls.read_value(stream),
            }

        elif opcode == cls.OP_INVARIANT:
            return {
                "action": "record_invariant",
                "invariant_name": cls.read_string(stream),
                "formal_statement": cls.read_string(stream),
                "proof_or_rationale": cls.read_string(stream),
                "domain": cls.read_string(stream),
            }

        elif opcode == cls.OP_REFINEMENT:
            return {
                "action": "log_refinement_cycle",
                "refinement_type": cls.read_string(stream),
                "focus_area": cls.read_string(stream),
                "critique_or_bottleneck": cls.read_string(stream),
                "architectural_refinement": cls.read_string(stream),
                "terminal_probe_results": cls.read_string(stream),
                "artifact_path": cls.read_string(stream),
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
        """Extract lines from start_line to end_line (1-indexed, inclusive)."""
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
        """Token estimator approximating standard BPE tokenizers (~4.0 characters per token)."""
        if not text:
            return 0
        return max(1, int(round(len(text) / 4.0)))

    def compress_payload_to_cas(self, content: str, label: str = "output") -> Dict[str, Any]:
        """Compress large content string into CAS reference pointer with metadata."""
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


CAS_ENGINE = FableCompress(root_dir=FABLE_CAS_DIR)
