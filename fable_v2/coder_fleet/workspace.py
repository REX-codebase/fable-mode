"""Atomic Workspace Engine for In-Memory File Checkpoints, Diffs, and Rollbacks.

Provides atomic snapshotting, diff telemetry, rollback facilities, and SHA-256 milestone receipts.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import time
import uuid
from typing import Any


class AtomicWorkspaceEngine:
    """Engine for atomic file snapshotting, patch inspection, rollbacks, and milestone commits."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, dict[str, str]] = {}
        self._milestones: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    def create_checkpoint(self, task_id: str, files: dict[str, str]) -> str:
        """Snapshot files into in-memory storage with a unique checkpoint_id."""
        chk_id = f"chk_{task_id}_{uuid.uuid4().hex[:8]}"
        self._checkpoints[chk_id] = copy.deepcopy(files)
        self._metadata[chk_id] = {
            "task_id": task_id,
            "created_at": time.time(),
            "file_count": len(files),
            "status": "active",
        }
        return chk_id

    def inspect_patch(self, checkpoint_id: str, current_files: dict[str, str]) -> dict[str, Any]:
        """Generate diff statistics (added, modified, deleted lines) between checkpoint and current files."""
        if checkpoint_id not in self._checkpoints:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found")

        snapshot = self._checkpoints[checkpoint_id]
        all_keys = sorted(set(snapshot.keys()) | set(current_files.keys()))

        files_changed = 0
        total_added = 0
        total_deleted = 0
        details: dict[str, Any] = {}

        for path in all_keys:
            old_content = snapshot.get(path)
            new_content = current_files.get(path)

            if old_content is None:
                # Newly added file
                new_lines = (new_content or "").splitlines(keepends=True)
                added = len(new_lines)
                deleted = 0
                diff_text = "".join(difflib.unified_diff([], new_lines, fromfile="/dev/null", tofile=path))
                details[path] = {
                    "status": "added",
                    "added": added,
                    "deleted": deleted,
                    "diff": diff_text,
                }
                files_changed += 1
                total_added += added

            elif new_content is None:
                # Deleted file
                old_lines = old_content.splitlines(keepends=True)
                added = 0
                deleted = len(old_lines)
                diff_text = "".join(difflib.unified_diff(old_lines, [], fromfile=path, tofile="/dev/null"))
                details[path] = {
                    "status": "deleted",
                    "added": added,
                    "deleted": deleted,
                    "diff": diff_text,
                }
                files_changed += 1
                total_deleted += deleted

            elif old_content != new_content:
                # Modified file
                old_lines = old_content.splitlines(keepends=True)
                new_lines = new_content.splitlines(keepends=True)
                diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}"))
                added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
                deleted = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
                diff_text = "".join(diff_lines)
                details[path] = {
                    "status": "modified",
                    "added": added,
                    "deleted": deleted,
                    "diff": diff_text,
                }
                files_changed += 1
                total_added += added
                total_deleted += deleted

            else:
                # Unchanged
                details[path] = {
                    "status": "unchanged",
                    "added": 0,
                    "deleted": 0,
                    "diff": "",
                }

        return {
            "checkpoint_id": checkpoint_id,
            "files_changed": files_changed,
            "lines_added": total_added,
            "lines_deleted": total_deleted,
            "details": details,
        }

    def rollback(self, checkpoint_id: str) -> dict[str, str]:
        """Return snapshot files cleanly."""
        if checkpoint_id not in self._checkpoints:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found")
        return copy.deepcopy(self._checkpoints[checkpoint_id])

    def commit_milestone(self, checkpoint_id: str, message: str) -> dict[str, Any]:
        """Mark checkpoint as committed with SHA-256 digest."""
        if checkpoint_id not in self._checkpoints:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found")

        snapshot = self._checkpoints[checkpoint_id]
        hasher = hashlib.sha256()

        for path in sorted(snapshot.keys()):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(snapshot[path].encode("utf-8"))
            hasher.update(b"\x00")

        digest = hasher.hexdigest()
        committed_at = time.time()

        milestone = {
            "checkpoint_id": checkpoint_id,
            "message": message,
            "digest": digest,
            "committed_at": committed_at,
            "file_count": len(snapshot),
            "status": "committed",
        }
        self._milestones[checkpoint_id] = milestone
        if checkpoint_id in self._metadata:
            self._metadata[checkpoint_id]["status"] = "committed"
            self._metadata[checkpoint_id]["milestone"] = milestone

        return milestone
