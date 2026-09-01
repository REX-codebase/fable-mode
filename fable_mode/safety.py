"""Filesystem safety primitives shared by installer and registration."""
from __future__ import annotations

import os
import shutil
import stat
import threading
from pathlib import Path

# A directory is eligible for recursive removal only after this process created
# it (or moved an installer-owned install into it).  Ownership includes the
# inode identity, so replacing the path after publication cannot turn cleanup
# into deletion of an unrelated directory.
_owned: dict[tuple[int, str], tuple[int, int]] = {}
_lock = threading.Lock()


def mark_owned_directory(path: Path) -> tuple[int, int]:
    p = Path(path)
    st = p.lstat()
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError("owned path is not a directory")
    identity = (st.st_dev, st.st_ino)
    with _lock:
        _owned[(os.getpid(), os.path.abspath(os.fspath(p)))] = identity
    return identity


def _is_owned(path: Path, st: os.stat_result) -> bool:
    with _lock:
        identity = _owned.get((os.getpid(), os.path.abspath(os.fspath(path))))
    return identity == (st.st_dev, st.st_ino)


def _forget(path: Path) -> None:
    with _lock:
        _owned.pop((os.getpid(), os.path.abspath(os.fspath(path))), None)


def _unsafe_node(path: Path, st: os.stat_result) -> bool:
    attrs = int(getattr(st, "st_file_attributes", 0))
    return bool(attrs & 0x400) or stat.S_ISLNK(st.st_mode) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode)


def safe_cleanup(stage_dir: Path | None, *, expected_identity: tuple[int, ...] | None = None) -> None:
    """Remove one freshly-created, process-owned private directory.

    No path is resolved before lstat, and ownership is an in-memory capability,
    not a pathname convention.  Thus a pre-existing ``.previous-*`` directory,
    the cwd, a repository, a parent, or a symlink can never become a recursive
    deletion target merely by having a plausible name.
    """
    if stage_dir is None:
        return
    p = Path(stage_dir)
    if not p.is_absolute() or p in {Path("/"), Path.cwd().absolute()}:
        raise ValueError("unsafe staging directory")
    try:
        st = p.lstat()
    except FileNotFoundError:
        _forget(p)
        return
    if expected_identity is None:
        identity_ok = _is_owned(p, st)
    else:
        # A four-field capability additionally binds ownership.  The original
        # two-field form remains supported for legacy callers/markers.
        identity_ok = tuple(expected_identity[:2]) == (st.st_dev, st.st_ino)
        if len(expected_identity) >= 4:
            identity_ok = identity_ok and tuple(expected_identity[2:4]) == (st.st_uid, st.st_gid)
    if identity_ok:
        pass
    else:
        raise ValueError("unsafe or unowned staging directory")
    if _unsafe_node(p, st) or not stat.S_ISDIR(st.st_mode):
        raise ValueError("unsafe or unowned staging directory")
    # Validate the complete tree without following links before removing it.
    for root, dirs, files in os.walk(p, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in (*dirs, *files):
            child = root_path / name
            child_st = child.lstat()
            if _unsafe_node(child, child_st):
                raise ValueError("unsafe node in staging directory")
            if stat.S_ISREG(child_st.st_mode) and child_st.st_nlink != 1:
                raise ValueError("hardlinked node in staging directory")
    # Last pathname check immediately before recursive deletion.  This is a
    # best-effort race mitigation (Python lacks portable descriptor-relative
    # recursive delete), not a descriptor-perfect guarantee.
    try:
        final_st = p.lstat()
    except FileNotFoundError:
        _forget(p)
        return
    final_identity = (final_st.st_dev, final_st.st_ino)
    expected = tuple(expected_identity[:2]) if expected_identity is not None else (st.st_dev, st.st_ino)
    final_capability_ok = final_identity == expected
    if expected_identity is not None and len(expected_identity) >= 4:
        final_capability_ok = final_capability_ok and tuple(expected_identity[2:4]) == (final_st.st_uid, final_st.st_gid)
    if not final_capability_ok or _unsafe_node(p, final_st) or not stat.S_ISDIR(final_st.st_mode):
        raise ValueError("cleanup target changed before deletion")
    shutil.rmtree(p)
    _forget(p)
