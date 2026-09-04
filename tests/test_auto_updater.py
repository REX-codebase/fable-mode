"""Unit and Integration Test Suite for Fable-Mode Autonomous Silent Self-Updater.

Tests:
- Initialization and host directory discovery
- Upstream check with mock git results
- Offline and timeout fail-safe behavior
- Non-blocking daemon background update trigger
- Non-destructive cortical experience preservation (antibodies, weights, custom lobes)
- Host skill and rule hot-syncing
- MCP server handler integration (check_auto_update and apply_auto_update)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fable_engine.updater import AutoUpdater, BASELINE_LOBES
from fable_v2.cortical.plasticity_engine import CorticalLobe, HeuristicAntibody
from fable_engine.server import handle_fable_session


class TestAutoUpdaterCore(unittest.TestCase):
    """Core tests for AutoUpdater initialization and discovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initialization_defaults(self) -> None:
        updater = AutoUpdater()
        self.assertTrue(updater.repo_root.exists())
        self.assertEqual(updater.remote_url, "https://github.com/REX-codebase/fable-mode.git")
        self.assertIsInstance(updater.host_targets, list)

    def test_explicit_repo_root_and_skills_dir(self) -> None:
        fake_skills = self.root / "fake_skills"
        updater = AutoUpdater(repo_root=self.root, skills_dir=fake_skills)
        self.assertEqual(updater.repo_root, self.root)
        self.assertEqual(updater.skills_dir, fake_skills)
        self.assertIn(fake_skills, updater.host_targets)

    def test_discover_host_targets_env_override(self) -> None:
        env_skills = self.root / "env_skills"
        with patch.dict(os.environ, {"FABLE_SKILLS_DIR": str(env_skills)}):
            updater = AutoUpdater(repo_root=self.root)
            self.assertIn(env_skills, updater.host_targets)


class TestAutoUpdaterChecks(unittest.TestCase):
    """Tests for safe upstream checking, timeouts, and offline handling."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.updater = AutoUpdater(repo_root=self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_check_non_git_repo_fails_safe(self) -> None:
        # self.root has no .git directory
        result = self.updater.check_for_updates()
        self.assertFalse(result["update_available"])
        self.assertTrue(result["offline"])
        self.assertIn("not a git repository", result["message"].lower())

    def test_check_up_to_date(self) -> None:
        (self.root / ".git").mkdir()
        fake_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=fake_sha, stderr="")
            if "ls-remote" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=f"{fake_sha}\trefs/heads/main\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unknown cmd")

        with patch("subprocess.run", side_effect=fake_run):
            result = self.updater.check_for_updates()
            self.assertFalse(result["update_available"])
            self.assertFalse(result["offline"])
            self.assertEqual(result["local_commit"], fake_sha)
            self.assertEqual(result["remote_commit"], fake_sha)
            self.assertIn("up to date", result["message"].lower())

    def test_check_update_available(self) -> None:
        (self.root / ".git").mkdir()
        local_sha = "1111111111111111111111111111111111111111"
        remote_sha = "2222222222222222222222222222222222222222"

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=local_sha, stderr="")
            if "ls-remote" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=f"{remote_sha}\trefs/heads/main\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = self.updater.check_for_updates()
            self.assertTrue(result["update_available"])
            self.assertFalse(result["offline"])
            self.assertEqual(result["local_commit"], local_sha)
            self.assertEqual(result["remote_commit"], remote_sha)
            self.assertIn("update available", result["message"].lower())

    def test_check_timeout_fails_safe(self) -> None:
        (self.root / ".git").mkdir()

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="localsha", stderr="")
            if "ls-remote" in cmd:
                raise subprocess.TimeoutExpired(cmd, 3.0)
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = self.updater.check_for_updates(timeout_seconds=3.0)
            self.assertFalse(result["update_available"])
            self.assertTrue(result["offline"])
            self.assertIn("timed out", result["message"].lower())

    def test_check_network_failure_fails_safe(self) -> None:
        (self.root / ".git").mkdir()

        def fake_run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="localsha", stderr="")
            if "ls-remote" in cmd:
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="Could not resolve host")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = self.updater.check_for_updates()
            self.assertFalse(result["update_available"])
            self.assertTrue(result["offline"])
            self.assertIn("offline", result["message"].lower())


class TestAutoUpdaterBackgroundThread(unittest.TestCase):
    """Tests for non-blocking daemon background update invocation."""

    def test_trigger_silent_background_update_is_daemon_and_returns_instantly(self) -> None:
        updater = AutoUpdater()
        start = time.perf_counter()
        thread = updater.trigger_silent_background_update()
        duration_ms = (time.perf_counter() - start) * 1000

        self.assertIsInstance(thread, threading.Thread)
        self.assertTrue(thread.daemon)
        # Verify 0ms startup delay (under 50ms)
        self.assertLess(duration_ms, 50.0)


class TestCortexPreservationLogic(unittest.TestCase):
    """Tests for non-destructive cortical experience preservation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.updater = AutoUpdater(repo_root=self.root)
        self.cortex_dir = self.root / "skills" / "fable-mode" / "cortex"
        self.cortex_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_custom_lobe_preservation(self) -> None:
        # Create a custom user-sprouted lobe
        custom_lobe = CorticalLobe(
            name="zig_systems",
            description="Low-level memory safety and comptime metaprogramming",
            activation_count=18,
            synaptic_weights={"comptime": 0.95, "allocator": 0.92},
            antibodies=[
                HeuristicAntibody(
                    antibody_id="ab_zig_alloc_leak",
                    domain="zig_systems",
                    trigger_condition="Missing defer allocator.free(buf)",
                    lethal_anti_pattern="var buf = try alloc.alloc(u8, 1024);",
                    prescribed_defense="Always defer dealloc immediately after allocation.",
                )
            ],
            specialized_heuristics=["Comptime assertions over runtime assertions."],
        )
        custom_path = self.cortex_dir / "zig_systems.md"
        custom_lobe.save_to_disk(custom_path)

        # Snapshot cortex
        snapshot = self.updater._snapshot_cortex()
        self.assertIn("zig_systems", snapshot["raw_text"])

        # Simulate git checkout or removal of untracked custom lobe during a pull
        custom_path.unlink()
        self.assertFalse(custom_path.exists())

        # Restore from snapshot
        preserved = self.updater._merge_and_restore_cortex(snapshot)
        self.assertIn("zig_systems", preserved)
        self.assertTrue(custom_path.exists())

        restored_lobe = CorticalLobe.load_from_disk(custom_path)
        self.assertEqual(restored_lobe.name, "zig_systems")
        self.assertEqual(len(restored_lobe.antibodies), 1)
        self.assertEqual(restored_lobe.antibodies[0].antibody_id, "ab_zig_alloc_leak")
        self.assertAlmostEqual(restored_lobe.synaptic_weights["comptime"], 0.95)

    def test_baseline_lobe_antibody_and_weight_merge(self) -> None:
        # 1. Local baseline lobe with locally evolved antibody and high synaptic weight
        local_ab = HeuristicAntibody(
            antibody_id="ab_python_local_evolved_bug",
            domain="python",
            trigger_condition="Local thread safety violation",
            lethal_anti_pattern="shared_state.append(x)",
            prescribed_defense="Use queue.Queue or threading.Lock",
            verified_counterfactual="100-thread stress test passed",
        )
        local_lobe = CorticalLobe(
            name="python",
            description="Python lobe with local learning",
            activation_count=25,
            synaptic_weights={"asyncio_event_loop": 0.99, "local_tool": 0.85},
            antibodies=[local_ab],
            specialized_heuristics=["Local heuristic: prefer fast paths."],
        )
        python_path = self.cortex_dir / "python.md"
        local_lobe.save_to_disk(python_path)

        # Snapshot before pull
        snapshot = self.updater._snapshot_cortex()

        # 2. Simulate upstream git pull overwriting python.md with upstream default version
        upstream_ab = HeuristicAntibody(
            antibody_id="ab_python_upstream_new_bug",
            domain="python",
            trigger_condition="Upstream newly discovered flaw",
            lethal_anti_pattern="bad_pattern()",
            prescribed_defense="safe_pattern()",
        )
        upstream_lobe = CorticalLobe(
            name="python",
            description="Upstream Python lobe",
            activation_count=10,
            synaptic_weights={"asyncio_event_loop": 0.80, "upstream_tool": 0.75},
            antibodies=[upstream_ab],
            specialized_heuristics=["Upstream heuristic: use TaskGroup."],
        )
        upstream_lobe.save_to_disk(python_path)

        # 3. Perform non-destructive merge and restore
        preserved = self.updater._merge_and_restore_cortex(snapshot)
        self.assertIn("python", preserved)

        merged_lobe = CorticalLobe.load_from_disk(python_path)

        # Verify BOTH antibodies exist (non-destructive union)
        ab_ids = {ab.antibody_id for ab in merged_lobe.antibodies}
        self.assertIn("ab_python_local_evolved_bug", ab_ids)
        self.assertIn("ab_python_upstream_new_bug", ab_ids)

        # Verify synaptic weights kept maximum values (did not overwrite local training)
        self.assertAlmostEqual(merged_lobe.synaptic_weights["asyncio_event_loop"], 0.99)
        self.assertAlmostEqual(merged_lobe.synaptic_weights["local_tool"], 0.85)
        self.assertAlmostEqual(merged_lobe.synaptic_weights["upstream_tool"], 0.75)

        # Verify activation count kept maximum (25)
        self.assertEqual(merged_lobe.activation_count, 25)

        # Verify both heuristics preserved
        self.assertTrue(any("Local heuristic" in h for h in merged_lobe.specialized_heuristics))
        self.assertTrue(any("Upstream heuristic" in h for h in merged_lobe.specialized_heuristics))

    def test_synaptic_matrix_merge(self) -> None:
        matrix_path = self.cortex_dir / "synaptic_matrix.json"
        local_matrix = {
            "local_node": {"tool_a": 0.95},
            "shared_node": {"tool_b": 0.90},
        }
        matrix_path.write_text(json.dumps(local_matrix), encoding="utf-8")

        snapshot = self.updater._snapshot_cortex()

        # Upstream has a different matrix
        upstream_matrix = {
            "upstream_node": {"tool_c": 0.80},
            "shared_node": {"tool_b": 0.60},
        }
        matrix_path.write_text(json.dumps(upstream_matrix), encoding="utf-8")

        self.updater._merge_and_restore_cortex(snapshot)

        merged_matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        self.assertIn("local_node", merged_matrix)
        self.assertIn("upstream_node", merged_matrix)
        # Shared node retains max weight (0.90)
        self.assertAlmostEqual(merged_matrix["shared_node"]["tool_b"], 0.90)


class TestHostSync(unittest.TestCase):
    """Tests for hot-syncing skills, rules, and MCP definitions into host paths."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

        # Setup source files
        self.skill_src = self.root / "skills" / "fable-mode"
        self.skill_src.mkdir(parents=True, exist_ok=True)
        (self.skill_src / "SKILL.md").write_text("# Fable Skill v2", encoding="utf-8")

        self.rules_src = self.root / "rules"
        self.rules_src.mkdir(parents=True, exist_ok=True)
        (self.rules_src / "fable-mode.md").write_text("# Fable Rules", encoding="utf-8")

        self.target_dir = self.root / "target_skills" / "fable-mode"
        self.updater = AutoUpdater(repo_root=self.root, skills_dir=self.target_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sync_host_targets(self) -> None:
        synced = self.updater._sync_host_targets()
        self.assertIn(str(self.target_dir), synced)
        self.assertTrue((self.target_dir / "SKILL.md").exists())
        self.assertEqual((self.target_dir / "SKILL.md").read_text(encoding="utf-8"), "# Fable Skill v2")


class TestMCPServerAutoUpdateActions(unittest.TestCase):
    """Tests for handle_fable_session auto-update actions."""

    def test_check_auto_update_dispatch(self) -> None:
        res = handle_fable_session({"action": "check_auto_update"})
        self.assertIn("Fable Autonomous Auto-Updater Status", res)
        self.assertIn("Update Available", res)
        self.assertIn("Local Commit", res)

    def test_apply_auto_update_dispatch(self) -> None:
        res = handle_fable_session({"action": "apply_auto_update", "preserve_cortex": True})
        self.assertIn("Fable Autonomous Auto-Updater Applied", res)
        self.assertIn("Success", res)


if __name__ == "__main__":
    unittest.main()
