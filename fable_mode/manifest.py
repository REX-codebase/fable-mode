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
    "fable_v2/system3/free_energy.py",
    "fable_v2/system3/hyperbolic.py",
    "fable_v2/system3/induction.py",
    "fable_v2/system3/kripke.py",
    "fable_v2/system3/oracle.py",
    "fable_v2/verifiers.py",
    "fable_v2/proof_engine.py",
    "fable_v2/coder_fleet/__init__.py",
    "fable_v2/coder_fleet/ast_tools.py",
    "fable_v2/coder_fleet/compute.py",
    "fable_v2/coder_fleet/diagnostics.py",
    "fable_v2/coder_fleet/fleet_dispatcher.py",
    "fable_v2/coder_fleet/mock_auditor.py",
    "fable_v2/coder_fleet/mutation.py",
    "fable_v2/coder_fleet/property_oracle.py",
    "fable_v2/coder_fleet/receipt_attestor.py",
    "fable_v2/coder_fleet/test_harness.py",
    "fable_v2/coder_fleet/visual.py",
    "fable_v2/coder_fleet/workspace.py",
    "fable_v2/coder_fleet/red_team_swarm.py",
    "fable_compressor.py",
    "rules/AGENTS.md",
    "rules/GEMINI.md",
    "rules/fable-mode.md",
    "docs/fable-v2-architecture.md",
    "docs/fable-v1-v2-migration.md",
    "docs/system3-architecture.md",
    "skills/fable-mode/SKILL.md",
    "skills/fable-mode/examples/autonomous-agentic-migration.md",
    "skills/fable-mode/examples/breakthrough-algorithm-synthesis.md",
    "skills/fable-mode/examples/deepthink-analysis-proof.md",
    "skills/fable-mode/examples/distributed-system-design.md",
    "skills/fable-mode/examples/swe-bench-pro-debugging.md",
    "skills/fable-mode/examples/weak_model_ollama_setup.md",
    "skills/fable-mode/references/aaa-threejs-game-engine.md",
    "skills/fable-mode/references/agentic-execution.md",
    "skills/fable-mode/references/architectural-blueprinting.md",
    "skills/fable-mode/references/cinematic-design-engine.md",
    "skills/fable-mode/references/cognitive-protocol.md",
    "skills/fable-mode/references/deepthink-mode.md",
    "skills/fable-mode/references/design-tokens-and-typographies.md",
    "skills/fable-mode/references/goal-rubric-and-pipeline-automation.md",
    "skills/fable-mode/references/innovation-engine.md",
    "skills/fable-mode/references/interleaved-verification.md",
    "skills/fable-mode/references/model-velocity-calibration.md",
    "skills/fable-mode/references/prompt-scaffolds.md",
    "skills/fable-mode/references/proof-architecture.md",
    "skills/fable-mode/references/svg-craft-and-vector-design.md",
    "skills/fable-mode/references/system2-session-engine.md",
    "skills/fable-mode/references/system3-meta-cognition.md",
    "skills/fable-mode/references/visual-imagination-engine.md",
    "skills/fable-mode/references/weak-model-frontier-uplift.md",
    "skills/fable-mode/references/adversarial-code-review-swarm.md",
    "LICENSE",
)


def validate_manifest(payload: object, allowed_files: tuple[str, ...] | list[str] | None = None) -> None:
    """Validate the packaged manifest as a strict, case-insensitive allowlist."""
    if not isinstance(payload, dict) or payload.get("format") != 1:
        raise ValueError("resource manifest format is unsupported")
    files = payload.get("files")
    target_allowed = ALLOWED_FILES if allowed_files is None else tuple(allowed_files)
    if not isinstance(files, list) or set(files) != set(target_allowed) or len(files) != len(target_allowed):
        raise ValueError("resource manifest does not match the canonical allowlist")
    folded = [Path(str(item)).as_posix().casefold() for item in files]
    if any(Path(str(item)).is_absolute() or ".." in Path(str(item)).parts for item in files) or len(set(folded)) != len(folded):
        raise ValueError("resource manifest contains unsafe or colliding paths")


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def allowed_source_paths(root: Path | None = None) -> list[Path]:
    root = Path(root or source_root())
    return [root / rel for rel in ALLOWED_FILES]
