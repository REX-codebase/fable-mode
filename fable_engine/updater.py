"""Autonomous Silent Self-Updater for Fable-Mode across client machines.

Enables silent upstream synchronization, non-destructive cortical experience
preservation (antibodies, synaptic weights, custom lobes), and hot-syncing
into active host skill and rule directories.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Optional

logger = logging.getLogger("fable-engine.updater")

BASELINE_LOBES: frozenset[str] = frozenset(
    {"rust", "python", "design_3d", "research", "concurrency"}
)

_BG_LOCK = threading.Lock()
_BG_RUNNING = False


class AutoUpdater:
    """Autonomous Silent Self-Updater and Hot-Sync Manager for Fable-Mode."""

    def __init__(
        self,
        repo_root: Optional[Path] = None,
        remote_url: str = "https://github.com/REX-codebase/fable-mode.git",
        skills_dir: Optional[Path] = None,
    ) -> None:
        if repo_root is not None:
            self.repo_root = Path(repo_root).resolve()
        else:
            # Default to repo root (parent directory of fable_engine)
            self.repo_root = Path(__file__).resolve().parent.parent

        self.remote_url = remote_url
        self.skills_dir = Path(skills_dir).resolve() if skills_dir else None
        self.host_targets = self.discover_host_targets()

    def discover_host_targets(self) -> list[Path]:
        """Detect active host skill paths across client environments."""
        candidates: list[Path] = []
        home = Path.home()

        # 1. Explicit skills_dir if provided
        if self.skills_dir:
            candidates.append(self.skills_dir)

        # 2. Environment override
        env_skills = os.environ.get("FABLE_SKILLS_DIR")
        if env_skills:
            candidates.append(Path(env_skills).resolve())

        # 3. Gemini / Antigravity skill directory
        candidates.append(home / ".gemini" / "config" / "skills" / "fable-mode")

        # 4. Claude Code / desktop skill directory
        candidates.append(home / ".claude" / "skills" / "fable-mode")

        # 5. Cursor skills directory (workspace and user home)
        candidates.append(self.repo_root / ".cursor" / "skills" / "fable-mode")
        candidates.append(home / ".cursor" / "skills" / "fable-mode")

        # 6. Windsurf / Codeium skill directory
        candidates.append(home / ".codeium" / "windsurf" / "skills" / "fable-mode")

        # Return all candidate paths that either already exist or whose parent exists
        discovered: list[Path] = []
        for path in candidates:
            try:
                resolved = path.resolve()
                if resolved not in discovered:
                    discovered.append(resolved)
            except Exception:
                pass

        return discovered

    def check_for_updates(self, timeout_seconds: float = 3.0) -> dict[str, Any]:
        """Run a quick, safe check against remote upstream for new commits.

        Fail-safe: if offline, timeout, or non-git, returns an informative dict
        with zero unhandled exceptions.
        """
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            return {
                "update_available": False,
                "local_commit": "",
                "remote_commit": "",
                "offline": True,
                "message": f"Directory '{self.repo_root}' is not a git repository.",
            }

        local_commit = ""
        try:
            # 1. Query local HEAD commit
            res_local = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if res_local.returncode != 0:
                return {
                    "update_available": False,
                    "local_commit": "",
                    "remote_commit": "",
                    "offline": True,
                    "message": f"git rev-parse HEAD failed: {res_local.stderr.strip()}",
                }
            local_commit = res_local.stdout.strip()

            # 2. Query remote main branch commit
            remote_commit = ""
            # Try origin first, fallback to remote_url
            for target in ("origin", self.remote_url):
                try:
                    res_remote = subprocess.run(
                        ["git", "ls-remote", target, "refs/heads/main"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                    )
                    if res_remote.returncode == 0 and res_remote.stdout.strip():
                        parts = res_remote.stdout.strip().split()
                        if parts:
                            remote_commit = parts[0].strip()
                            break
                except subprocess.TimeoutExpired:
                    raise
                except Exception:
                    continue

            if not remote_commit:
                return {
                    "update_available": False,
                    "local_commit": local_commit,
                    "remote_commit": "",
                    "offline": True,
                    "message": "Unable to query upstream remote (offline or unreachable).",
                }

            update_available = (local_commit != remote_commit)
            msg = (
                f"Update available: {local_commit[:8]} -> {remote_commit[:8]}"
                if update_available
                else "Fable-Mode is up to date."
            )
            return {
                "update_available": update_available,
                "local_commit": local_commit,
                "remote_commit": remote_commit,
                "offline": False,
                "message": msg,
            }

        except subprocess.TimeoutExpired:
            return {
                "update_available": False,
                "local_commit": local_commit,
                "remote_commit": "",
                "offline": True,
                "message": f"Upstream check timed out after {timeout_seconds}s.",
            }
        except Exception as exc:
            return {
                "update_available": False,
                "local_commit": local_commit,
                "remote_commit": "",
                "offline": True,
                "message": f"Check failed safely: {exc}",
            }

    def _snapshot_cortex(self) -> dict[str, Any]:
        """Snapshot all local cortical lobes and synaptic weights before pull."""
        cortex_dir = self.repo_root / "skills" / "fable-mode" / "cortex"
        snapshot: dict[str, Any] = {
            "lobes": {},
            "raw_text": {},
            "synaptic_matrix": None,
        }
        if not cortex_dir.exists():
            return snapshot

        # Try to import CorticalLobe
        CorticalLobe = None
        try:
            from fable_v2.cortical.plasticity_engine import CorticalLobe as CL
            CorticalLobe = CL
        except Exception:
            pass

        for md_file in cortex_dir.glob("*.md"):
            name = md_file.stem
            try:
                raw = md_file.read_text(encoding="utf-8")
                snapshot["raw_text"][name] = raw
                if CorticalLobe:
                    lobe_obj = CorticalLobe.load_from_disk(md_file)
                    snapshot["lobes"][name] = lobe_obj
            except Exception as e:
                logger.debug(f"Failed snapshotting lobe {name}: {e}")

        matrix_file = cortex_dir / "synaptic_matrix.json"
        if matrix_file.exists():
            try:
                snapshot["synaptic_matrix"] = json.loads(matrix_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        return snapshot

    def _merge_and_restore_cortex(self, snapshot: dict[str, Any]) -> list[str]:
        """Non-destructively merge preserved antibodies, synaptic weights, and custom lobes."""
        cortex_dir = self.repo_root / "skills" / "fable-mode" / "cortex"
        cortex_dir.mkdir(parents=True, exist_ok=True)
        preserved_names: list[str] = []

        CorticalLobe = None
        try:
            from fable_v2.cortical.plasticity_engine import CorticalLobe as CL
            CorticalLobe = CL
        except Exception:
            pass

        local_raw = snapshot.get("raw_text", {})
        local_lobes = snapshot.get("lobes", {})

        # 1. Restore Custom Lobes (non-baseline)
        for name, raw in local_raw.items():
            if name not in BASELINE_LOBES:
                lobe_file = cortex_dir / f"{name}.md"
                if not lobe_file.exists():
                    lobe_file.write_text(raw, encoding="utf-8")
                    preserved_names.append(name)
                elif CorticalLobe and name in local_lobes:
                    # Lobe file exists after pull; merge antibodies and weights
                    try:
                        pulled = CorticalLobe.load_from_disk(lobe_file)
                        local = local_lobes[name]
                        self._merge_lobe_data(pulled, local)
                        pulled.save_to_disk(lobe_file)
                        preserved_names.append(name)
                    except Exception as e:
                        logger.debug(f"Error merging custom lobe {name}: {e}")

        # 2. Merge Baseline Lobes (non-destructive antibody and weight union)
        for base_name in BASELINE_LOBES:
            if base_name in local_lobes and CorticalLobe:
                lobe_file = cortex_dir / f"{base_name}.md"
                if lobe_file.exists():
                    try:
                        pulled = CorticalLobe.load_from_disk(lobe_file)
                        local = local_lobes[base_name]
                        self._merge_lobe_data(pulled, local)
                        pulled.save_to_disk(lobe_file)
                        preserved_names.append(base_name)
                    except Exception as e:
                        logger.debug(f"Error merging baseline lobe {base_name}: {e}")

        # 3. Merge Synaptic Matrix
        local_matrix = snapshot.get("synaptic_matrix")
        if local_matrix and isinstance(local_matrix, dict):
            matrix_file = cortex_dir / "synaptic_matrix.json"
            pulled_matrix: dict[str, Any] = {}
            if matrix_file.exists():
                try:
                    pulled_matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
                except Exception:
                    pulled_matrix = {}
            # Non-destructively union local matrix weights with pulled matrix
            for src, targets in local_matrix.items():
                if src not in pulled_matrix:
                    pulled_matrix[src] = targets
                elif isinstance(targets, dict) and isinstance(pulled_matrix.get(src), dict):
                    for tgt, weight in targets.items():
                        if tgt not in pulled_matrix[src]:
                            pulled_matrix[src][tgt] = weight
                        else:
                            try:
                                pulled_matrix[src][tgt] = max(
                                    float(weight), float(pulled_matrix[src][tgt])
                                )
                            except (ValueError, TypeError):
                                pass
            try:
                matrix_file.write_text(json.dumps(pulled_matrix, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Error writing synaptic matrix: {e}")

        return preserved_names

    def _merge_lobe_data(self, target_lobe: Any, source_lobe: Any) -> None:
        """Merge source antibodies, synaptic weights, and heuristics into target."""
        # 1. Merge Antibodies by antibody_id
        target_ids = {ab.antibody_id for ab in getattr(target_lobe, "antibodies", [])}
        for ab in getattr(source_lobe, "antibodies", []):
            if ab.antibody_id not in target_ids:
                target_lobe.antibodies.append(ab)
                target_ids.add(ab.antibody_id)
            else:
                # If both have antibody, adopt source counterfactual/defense if target is missing it
                for idx, t_ab in enumerate(target_lobe.antibodies):
                    if t_ab.antibody_id == ab.antibody_id:
                        if getattr(ab, "verified_counterfactual", "") and not getattr(
                            t_ab, "verified_counterfactual", ""
                        ):
                            target_lobe.antibodies[idx] = ab
                        break

        # 2. Merge Synaptic Weights (max retention)
        source_weights = getattr(source_lobe, "synaptic_weights", {})
        target_weights = getattr(target_lobe, "synaptic_weights", {})
        for node, weight in source_weights.items():
            if node not in target_weights:
                target_weights[node] = weight
            else:
                try:
                    target_weights[node] = max(float(weight), float(target_weights[node]))
                except (ValueError, TypeError):
                    pass

        # 3. Merge Activation Count
        target_lobe.activation_count = max(
            getattr(target_lobe, "activation_count", 0),
            getattr(source_lobe, "activation_count", 0),
        )

        # 4. Merge Specialized Heuristics
        target_heuristics = set(getattr(target_lobe, "specialized_heuristics", []))
        for h in getattr(source_lobe, "specialized_heuristics", []):
            if h not in target_heuristics:
                target_lobe.specialized_heuristics.append(h)
                target_heuristics.add(h)

    def _sync_host_targets(self) -> list[str]:
        """Hot-sync skills, rules, and MCP session manifests into host environments."""
        synced: list[str] = []
        source_skill = self.repo_root / "skills" / "fable-mode"
        source_rule = self.repo_root / "rules" / "fable-mode.md"
        source_mcp_json = self.repo_root / "fable_engine" / "fable_session.json"

        # 1. Sync skills into discovered host paths
        for target_skill_dir in self.discover_host_targets():
            try:
                is_explicit = bool(self.skills_dir and target_skill_dir == self.skills_dir.resolve())
                target_parent = target_skill_dir.parent
                if is_explicit or target_parent.exists() or target_skill_dir.exists():
                    target_skill_dir.mkdir(parents=True, exist_ok=True)
                    if source_skill.exists():
                        for root, _, files in os.walk(source_skill):
                            rel = Path(root).relative_to(source_skill)
                            dest_dir = target_skill_dir / rel
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            for f in files:
                                s_file = Path(root) / f
                                d_file = dest_dir / f
                                shutil.copy2(s_file, d_file)
                        synced.append(str(target_skill_dir))
            except Exception as e:
                logger.debug(f"Failed syncing skill target {target_skill_dir}: {e}")

        # 2. Sync rule file into host rules directories (e.g. ~/.gemini/config/rules)
        gemini_rules = Path.home() / ".gemini" / "config" / "rules"
        claude_rules = Path.home() / ".claude" / "rules"
        cursor_rules = self.repo_root / ".cursor" / "rules"
        for rule_dir in (gemini_rules, claude_rules, cursor_rules):
            try:
                if rule_dir.exists() and source_rule.exists():
                    dest_rule = rule_dir / "fable-mode.md"
                    shutil.copy2(source_rule, dest_rule)
                    synced.append(str(dest_rule))
            except Exception as e:
                logger.debug(f"Failed syncing rule to {rule_dir}: {e}")

        # 3. Sync MCP tool schema into antigravity MCP dir if present
        mcp_dest = Path.home() / ".gemini" / "antigravity" / "mcp" / "fable-engine"
        try:
            if mcp_dest.exists() and source_mcp_json.exists():
                shutil.copy2(source_mcp_json, mcp_dest / "fable_session.json")
                synced.append(str(mcp_dest / "fable_session.json"))
        except Exception as e:
            logger.debug(f"Failed syncing MCP schema: {e}")

        return synced

    def apply_update(self, preserve_cortex: bool = True) -> dict[str, Any]:
        """Pull latest upstream changes via git --ff-only, preserve cortex, and hot-sync."""
        git_dir = self.repo_root / ".git"
        if not git_dir.exists():
            # If not git repo, still attempt hot-sync
            synced = self._sync_host_targets()
            return {
                "success": True,
                "updated": False,
                "message": "Standalone non-git installation. Host skills hot-synced successfully.",
                "preserved_lobes": [],
                "synced_targets": synced,
            }

        # 1. Snapshot cortex if requested
        snapshot = self._snapshot_cortex() if preserve_cortex else {}

        # 2. Revert any local test-run modifications in cortex to allow ff-only git pull
        try:
            cortex_rel = "skills/fable-mode/cortex"
            subprocess.run(
                ["git", "checkout", "--", cortex_rel],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except Exception:
            pass

        # 3. Run git pull --ff-only
        pull_successful = False
        pull_output = ""
        try:
            pull_res = subprocess.run(
                ["git", "pull", "--ff-only", "origin", "main"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            pull_successful = (pull_res.returncode == 0)
            pull_output = pull_res.stdout.strip() or pull_res.stderr.strip()

            if not pull_successful and self.remote_url:
                # Try fetching directly from remote_url
                fetch_res = subprocess.run(
                    ["git", "fetch", self.remote_url, "main"],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
                if fetch_res.returncode == 0:
                    merge_res = subprocess.run(
                        ["git", "merge", "--ff-only", "FETCH_HEAD"],
                        cwd=str(self.repo_root),
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                    )
                    pull_successful = (merge_res.returncode == 0)
                    pull_output = merge_res.stdout.strip() or merge_res.stderr.strip()
        except Exception as e:
            pull_output = f"Git pull error: {e}"

        # 4. Merge & restore preserved cortex experience
        preserved: list[str] = []
        if preserve_cortex and snapshot:
            try:
                preserved = self._merge_and_restore_cortex(snapshot)
            except Exception as e:
                logger.error(f"Error restoring cortex: {e}")

        # 5. Hot-sync to host skill targets
        synced = self._sync_host_targets()

        updated = pull_successful and "Already up to date" not in pull_output
        msg = f"Update applied: {pull_output}." if pull_successful else f"Update check/pull note: {pull_output}."

        return {
            "success": pull_successful or (len(synced) > 0),
            "updated": updated,
            "message": msg,
            "preserved_lobes": preserved,
            "synced_targets": synced,
        }

    def _background_worker(self) -> None:
        """Background thread worker running silent update check and hot-sync."""
        global _BG_RUNNING
        with _BG_LOCK:
            _BG_RUNNING = True
        try:
            status = self.check_for_updates(timeout_seconds=4.0)
            if status.get("update_available"):
                logger.info(
                    f"Auto-update: detected upstream commit {status.get('remote_commit')[:8]}. Silently updating..."
                )
                res = self.apply_update(preserve_cortex=True)
                logger.info(f"Auto-update completed: {res.get('message')}")
            else:
                logger.debug(f"Auto-update check: {status.get('message')}")
        except Exception as e:
            logger.debug(f"Silent auto-update worker non-fatal exception: {e}")
        finally:
            with _BG_LOCK:
                _BG_RUNNING = False

    def trigger_silent_background_update(self) -> threading.Thread:
        """Spawn a non-blocking daemon thread to silently check and hot-sync updates."""
        global _BG_RUNNING
        with _BG_LOCK:
            if _BG_RUNNING:
                # Already running in background
                dummy = threading.Thread(target=lambda: None)
                dummy.start()
                return dummy

        thread = threading.Thread(
            target=self._background_worker,
            name="FableAutoUpdaterDaemon",
            daemon=True,
        )
        thread.start()
        return thread
