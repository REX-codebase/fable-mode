"""Skill distribution: manifest coverage, wheel packaging, and install-skill."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from fable_mode import __version__
from fable_mode.installer import InstallError
from fable_mode.manifest import ALLOWED_FILES, validate_manifest
from fable_mode.skill_bundle import SKILL_MARKER, SKILL_NAME, bundled_skill_root, install_skill

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_TREE = REPO_ROOT / "skills" / SKILL_NAME


def _tree_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


class SkillManifestTests(unittest.TestCase):
    def test_manifest_covers_every_skill_file(self):
        on_disk = {f"skills/{SKILL_NAME}/{rel}" for rel in _tree_files(SKILL_TREE)}
        missing = on_disk - set(ALLOWED_FILES)
        self.assertEqual(missing, set(), f"manifest.py omits skill files: {sorted(missing)}")

    def test_resources_json_matches_manifest(self):
        payload = json.loads((REPO_ROOT / "fable_mode" / "resources.json").read_text(encoding="utf-8"))
        validate_manifest(payload)

    def test_version_is_consistent_across_artifacts(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        setup_py = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
        server = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertIn(f'version = "{__version__}"', pyproject)
        self.assertIn(f'version="{__version__}"', setup_py)
        self.assertEqual(server["version"], __version__)
        self.assertEqual(server["packages"][0]["version"], __version__)


class WheelBuildMixin:
    """Build the wheel once, from a hermetic copy of the source tree."""

    @classmethod
    def setUpClass(cls):
        super_setup = getattr(super(), "setUpClass", None)
        if super_setup:
            super_setup()
        cls._tmp = tempfile.TemporaryDirectory()
        work = Path(cls._tmp.name)
        cls.source_copy = work / "src"
        shutil.copytree(
            REPO_ROOT, cls.source_copy,
            ignore=shutil.ignore_patterns(".git", "build", "dist", "*.egg-info", "__pycache__", "sessions"))
        cls.wheel_dir = work / "wheel"
        cls.wheel_dir.mkdir()
        previous = Path.cwd()
        os.chdir(cls.source_copy)
        try:
            from setuptools import build_meta
            cls.wheel_name = build_meta.build_wheel(str(cls.wheel_dir))
        finally:
            os.chdir(previous)
        cls.wheel_path = cls.wheel_dir / cls.wheel_name

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        super_teardown = getattr(super(), "tearDownClass", None)
        if super_teardown:
            super_teardown()


class WheelSkillPackagingTests(WheelBuildMixin, unittest.TestCase):
    def test_wheel_contains_complete_skill_tree_as_package_data(self):
        expected = _tree_files(SKILL_TREE)
        self.assertIn("SKILL.md", expected)
        with zipfile.ZipFile(self.wheel_path) as wheel:
            names = wheel.namelist()
            bundled = {
                name[len(f"fable_mode/skills/{SKILL_NAME}/"):]
                for name in names if name.startswith(f"fable_mode/skills/{SKILL_NAME}/")
            }
            self.assertEqual(bundled, expected)
            for rel in expected:
                packaged = wheel.read(f"fable_mode/skills/{SKILL_NAME}/{rel}")
                original = (SKILL_TREE / rel).read_bytes()
                self.assertEqual(packaged, original, f"wheel content diverges for {rel}")

    def test_wheel_has_no_top_level_skills_directory(self):
        with zipfile.ZipFile(self.wheel_path) as wheel:
            strays = [name for name in wheel.namelist()
                      if name == "skills" or name.startswith("skills/")]
        self.assertEqual(strays, [], "skill tree must live inside the package, not at site-packages root")

    def test_wheel_metadata_version(self):
        self.assertIn(f"-{__version__}-", self.wheel_name)


class InstallSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / ".agents" / "skills" / SKILL_NAME

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundled_skill_root_prefers_checkout(self):
        self.assertEqual(bundled_skill_root(), SKILL_TREE)

    def test_install_copies_complete_tree_with_marker(self):
        result = install_skill(self.target)
        self.assertEqual(set(result.installed), _tree_files(SKILL_TREE))
        self.assertEqual(result.updated, [])
        for rel in result.installed:
            self.assertEqual((self.target / rel).read_bytes(), (SKILL_TREE / rel).read_bytes())
        marker = json.loads((self.target / SKILL_MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["product"], SKILL_NAME)
        self.assertEqual(marker["version"], __version__)
        self.assertEqual(set(marker["files"]), _tree_files(SKILL_TREE))

    def test_second_install_is_a_noop(self):
        install_skill(self.target)
        result = install_skill(self.target)
        self.assertEqual(result.installed, [])
        self.assertEqual(result.updated, [])
        self.assertEqual(set(result.unchanged), _tree_files(SKILL_TREE))

    def test_local_edits_require_force(self):
        install_skill(self.target)
        edited = self.target / "SKILL.md"
        edited.write_bytes(b"local edit")
        with self.assertRaises(InstallError):
            install_skill(self.target)
        result = install_skill(self.target, force=True)
        self.assertEqual(result.updated, ["SKILL.md"])
        self.assertEqual(edited.read_bytes(), (SKILL_TREE / "SKILL.md").read_bytes())

    def test_foreign_directory_requires_force_and_preserves_extras(self):
        self.target.mkdir(parents=True)
        (self.target / "mine.md").write_text("keep me", encoding="utf-8")
        with self.assertRaises(InstallError):
            install_skill(self.target)
        result = install_skill(self.target, force=True)
        self.assertEqual(set(result.installed), _tree_files(SKILL_TREE))
        self.assertEqual((self.target / "mine.md").read_text(encoding="utf-8"), "keep me")

    def test_dry_run_writes_nothing(self):
        result = install_skill(self.target, dry_run=True)
        self.assertEqual(set(result.installed), _tree_files(SKILL_TREE))
        self.assertFalse(self.target.exists())

    def test_symlink_target_is_refused(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        try:
            os.symlink(real, link)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314 or isinstance(exc, (PermissionError, NotImplementedError)):
                self.skipTest("Symlink creation requires elevated privilege on Windows")
            raise
        with self.assertRaises(InstallError):
            install_skill(link)


class InstallSkillCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_cli(self, *argv, cwd):
        return subprocess.run(
            [sys.executable, "-m", "fable_mode", *argv],
            cwd=cwd, capture_output=True, text=True,
            env={**os.environ, "FABLE_DISABLE_AUTO_UPDATE": "1"})

    def test_cli_install_skill_with_yes(self):
        result = self._run_cli("install-skill", "--yes", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.root / ".agents" / "skills" / SKILL_NAME
        self.assertEqual(_tree_files(target) - {SKILL_MARKER}, _tree_files(SKILL_TREE))
        self.assertIn("Installed the Fable Mode Agent Skill", result.stdout)

    def test_cli_install_skill_requires_confirmation_unattended(self):
        result = self._run_cli("install-skill", cwd=self.root)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / ".agents").exists())

    def test_cli_install_skill_dry_run(self):
        result = self._run_cli("install-skill", "--dry-run", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would install", result.stdout)
        self.assertFalse((self.root / ".agents").exists())

    def test_cli_setup_installs_skill_and_prints_both_routes(self):
        result = self._run_cli("setup", "--yes", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.root / ".agents" / "skills" / SKILL_NAME
        self.assertEqual(_tree_files(target) - {SKILL_MARKER}, _tree_files(SKILL_TREE))
        self.assertIn("Native MCP", result.stdout)
        self.assertIn("Shell sandbox", result.stdout)


class WheelInstallEndToEndTests(WheelBuildMixin, unittest.TestCase):
    """The real path: install the wheel, then install the skill from it."""

    def test_install_skill_from_installed_wheel(self):
        site = Path(self._tmp.name) / "site"
        # A wheel is laid out exactly as site-packages; extracting it keeps
        # this test independent of pip availability in the test interpreter.
        with zipfile.ZipFile(self.wheel_path) as wheel:
            wheel.extractall(site)
        workspace = Path(self._tmp.name) / "workspace"
        workspace.mkdir()
        env = {**os.environ, "PYTHONPATH": str(site), "FABLE_DISABLE_AUTO_UPDATE": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "fable_mode", "install-skill", "--yes"],
            cwd=workspace, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = workspace / ".agents" / "skills" / SKILL_NAME
        installed = _tree_files(target) - {SKILL_MARKER}
        self.assertEqual(installed, _tree_files(SKILL_TREE))
        for rel in installed:
            self.assertEqual((target / rel).read_bytes(), (SKILL_TREE / rel).read_bytes())

    def test_shell_call_from_installed_wheel(self):
        site = Path(self._tmp.name) / "shell-site"
        with zipfile.ZipFile(self.wheel_path) as wheel:
            wheel.extractall(site)
        workspace = Path(self._tmp.name) / "shell-workspace"
        workspace.mkdir()
        env = {**os.environ, "PYTHONPATH": str(site), "FABLE_DISABLE_AUTO_UPDATE": "1",
               "FABLE_DATA_DIR": str(workspace / "data")}
        request = json.dumps({"action": "list_sessions"}) + "\n"
        result = subprocess.run(
            [sys.executable, "-m", "fable_mode", "call"], input=request,
            cwd=workspace, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("Available Fable Sessions", payload["result"])


if __name__ == "__main__":
    unittest.main()
