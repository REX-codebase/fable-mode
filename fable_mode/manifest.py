"""Explicit allowlist for portable release contents.

This list is deliberately boring and reviewable: no recursive source-tree copy is
performed by the installer or release build.
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_FILES: tuple[str, ...] = (
    "fable_mode/__init__.py",
    "fable_mode/__main__.py",
    "fable_mode/adapters.py",
    "fable_mode/installer.py",
    "fable_mode/launcher.py",
    "fable_mode/manifest.py",
    "fable_mode/safety.py",
    "fable_mode/resources.json",
    "fable_engine/__init__.py",
    "fable_engine/server.py",
    "fable_engine/fable_session.json",
    "fable_v2/__init__.py",
    "fable_v2/adapters.py",
    "fable_v2/execution_broker.py",
    "fable_v2/protocol.py",
    "fable_v2/runtime.py",
    "fable_v2/system3/__init__.py",
    "fable_v2/system3/causal.py",
    "fable_v2/system3/dialectical.py",
    "fable_v2/system3/evolution.py",
    "fable_v2/system3/executive.py",
    "fable_v2/system3/induction.py",
    "fable_v2/verifiers.py",
    "rules/AGENTS.md",
    "rules/GEMINI.md",
    "rules/fable-mode.md",
    "docs/fable-v2-architecture.md",
    "docs/fable-v1-v2-migration.md",
    "LICENSE",
)


def validate_manifest(payload: object) -> None:
    """Validate the packaged manifest as a strict, case-insensitive allowlist."""
    if not isinstance(payload, dict) or payload.get("format") != 1:
        raise ValueError("resource manifest format is unsupported")
    files = payload.get("files")
    if not isinstance(files, list) or set(files) != set(ALLOWED_FILES) or len(files) != len(ALLOWED_FILES):
        raise ValueError("resource manifest does not match the canonical allowlist")
    folded = [Path(str(item)).as_posix().casefold() for item in files]
    if any(Path(str(item)).is_absolute() or ".." in Path(str(item)).parts for item in files) or len(set(folded)) != len(folded):
        raise ValueError("resource manifest contains unsafe or colliding paths")


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def allowed_source_paths(root: Path | None = None) -> list[Path]:
    root = Path(root or source_root())
    return [root / rel for rel in ALLOWED_FILES]
