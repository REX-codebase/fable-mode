"""Explicit, opt-in installation of the bundled Fable Mode Agent Skill.

The MCP server and the Agent Skill are separate artifacts: connecting the
server never installs or activates skill instructions.  The canonical
``skills/fable-mode`` tree ships inside the wheel as package data, and this
module copies it into a caller-chosen skills directory - by default the
cross-client ``.agents/skills/fable-mode`` convention - only when explicitly
asked through ``fable-mode install-skill``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import __version__
from .installer import InstallError, _reject_path
from .manifest import source_root

SKILL_NAME = "fable-mode"
SKILL_MARKER = ".fable-skill-install.json"
SKILL_REL = Path("skills") / SKILL_NAME


def bundled_skill_root() -> Path:
    """Locate the canonical skill tree in a source checkout or an installed wheel."""
    checkout = source_root() / SKILL_REL
    try:
        if checkout.is_dir() and not checkout.is_symlink():
            return checkout
    except OSError:
        pass
    try:
        candidate = Path(resources.files("fable_mode").joinpath(SKILL_REL.as_posix()))
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    except (FileNotFoundError, OSError, TypeError, ValueError):
        pass
    raise InstallError("the bundled Fable Mode Agent Skill is unavailable in this installation")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skill_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        parts = Path(rel)
        if parts.is_absolute() or ".." in parts.parts:
            raise InstallError(f"unsafe bundled skill path: {rel}")
        if path.is_symlink() or not path.is_file():
            raise InstallError(f"unsafe bundled skill entry: {rel}")
        files[rel] = path
    if "SKILL.md" not in files:
        raise InstallError("the bundled skill tree is incomplete: SKILL.md is missing")
    return files


def _read_marker(target: Path) -> dict | None:
    marker = target / SKILL_MARKER
    try:
        if not marker.is_file() or marker.is_symlink():
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != 1 or data.get("product") != SKILL_NAME:
        return None
    if not isinstance(data.get("files"), dict):
        return None
    return data


@dataclass
class SkillInstallResult:
    target: Path
    dry_run: bool
    installed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def planned(self) -> int:
        return len(self.installed) + len(self.updated) + len(self.unchanged)


def install_skill(target: Path, *, force: bool = False, dry_run: bool = False) -> SkillInstallResult:
    """Copy the bundled skill tree into ``target`` with ownership tracking.

    Idempotent: byte-identical files are left untouched.  Files this installer
    previously wrote are upgraded in place; anything else (a foreign directory
    or local edits) requires ``force`` so a skill install can never silently
    overwrite user content.
    """
    source = bundled_skill_root()
    files = _skill_files(source)
    target = Path(target).expanduser().absolute()
    _reject_path(target, allow_missing=True)
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise InstallError("skill target is not a real directory")
    marker = _read_marker(target) if target.is_dir() else None
    if target.is_dir() and marker is None and any(target.iterdir()) and not force:
        raise InstallError(
            f"{target} exists and was not installed by fable-mode; pass --force to adopt it")
    recorded = (marker or {}).get("files", {})
    result = SkillInstallResult(target=target, dry_run=dry_run)
    conflicts: list[str] = []
    for rel, src in files.items():
        dst = target / Path(rel)
        if not dst.exists():
            result.installed.append(rel)
            continue
        if dst.is_symlink() or not dst.is_file():
            raise InstallError(f"unsafe existing path in skill target: {rel}")
        new_hash, current_hash = _hash(src), _hash(dst)
        if current_hash == new_hash:
            result.unchanged.append(rel)
        elif (marker is not None and recorded.get(rel) == current_hash) or force:
            result.updated.append(rel)
        else:
            conflicts.append(rel)
    if conflicts:
        listing = ", ".join(conflicts[:5]) + (", ..." if len(conflicts) > 5 else "")
        raise InstallError(f"local modifications would be overwritten ({listing}); pass --force to overwrite")
    if dry_run:
        return result
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for rel in result.installed + result.updated:
        src = files[rel]
        dst = target / Path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            cursor = dst.parent
            while cursor != target and cursor != cursor.parent:
                os.chmod(cursor, 0o700)
                cursor = cursor.parent
        shutil.copyfile(src, dst, follow_symlinks=False)
        os.chmod(dst, 0o600)
        written[rel] = _hash(dst)
    for rel in result.unchanged:
        written[rel] = _hash(target / Path(rel))
    if os.name != "nt":
        os.chmod(target, 0o700)
    marker_path = target / SKILL_MARKER
    marker_path.write_text(json.dumps(
        {"format": 1, "product": SKILL_NAME, "version": __version__, "files": written},
        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(marker_path, 0o600)
    return result
