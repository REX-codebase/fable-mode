import json
import os
import stat
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_mode.adapters import Host, RegistrationError, detect_hosts, register_hosts, run_argv
from fable_mode.installer import InstallError, Installer, verify_installation
from fable_mode.launcher import _smoke


class PackagingSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_top_level_wrapper_is_package_aware(self):
        wrapper = Path(__file__).resolve().parents[1] / "fable_mode_entry.py"
        result = subprocess.run([sys.executable, str(wrapper), "--version"], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "1.2.0")

    def test_unattended_install_requires_confirmation(self):
        wrapper = Path(__file__).resolve().parents[1] / "fable_mode_entry.py"
        result = subprocess.run([sys.executable, str(wrapper), "install", "--install-dir", str(self.root / "i")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "i").exists())

    def test_unmarked_target_and_source_link_are_refused(self):
        target = self.root / "target"
        target.mkdir(); (target / "keep").write_text("keep")
        with self.assertRaises(InstallError):
            Installer(target).install()
        with self.assertRaises(InstallError):
            Installer(target).uninstall()
        source = self.root / "source"
        source.mkdir()
        # An explicit source override cannot smuggle a symlinked canonical file.
        (source / "fable_mode").mkdir()
        os.symlink("/etc/passwd", source / "fable_mode" / "__init__.py")
        with self.assertRaises(InstallError):
            Installer(self.root / "i", source=source).install()

    def test_transaction_rolls_back_previous_install(self):
        target = self.root / "i"
        first = Installer(target).install(); first.transaction.commit()
        marker_before = (target / ".fable-install.json").read_bytes()
        # Make the target look valid but break source before second publish.
        source = self.root / "missing-source"
        with self.assertRaises(InstallError):
            Installer(target, source=source).install()
        self.assertEqual(marker_before, (target / ".fable-install.json").read_bytes())
        self.assertTrue(verify_installation(target)[0])

    def test_dry_run_has_no_changes(self):
        target = self.root / "i"
        result = Installer(target).install(dry_run=True)
        self.assertFalse(target.exists())
        self.assertEqual(result.mode, "source")

    def test_config_preserves_keys_and_rejects_links(self):
        home = self.root / "home"
        config = home / ".gemini/config/mcp_config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"keep": {"x": 1}, "mcpServers": {"old": {}}}))
        exe = self.root / "fable"; exe.write_text(""); exe.chmod(0o700)
        host = Host("antigravity", exe, "cli", True)
        register_hosts({"antigravity": host}, [str(exe), "serve"], home=home)
        value = json.loads(config.read_text())
        self.assertEqual(value["keep"], {"x": 1})
        self.assertNotIn("fable-mode", value["mcpServers"])
        self.assertEqual(value["mcpServers"]["fable-engine"]["args"], ["serve"])
        config.unlink(); os.symlink(config.parent / "elsewhere", config)
        with self.assertRaises(RegistrationError):
            register_hosts({"antigravity": host}, [str(exe), "serve"], home=home)

    def test_only_canonical_host_names_are_probed(self):
        with patch("fable_mode.adapters._which", side_effect=lambda n: None) as which:
            detect_hosts()
            self.assertEqual([c.args[0] for c in which.call_args_list], ["claude", "agy", "codex"])

    def test_output_is_bounded_and_timeout_is_reported(self):
        code, out, err, timed = run_argv([os.environ.get("PYTHON", "python"), "-c", "print('x'*1000000)"], timeout=2)
        self.assertLessEqual(len(out.encode()), 8192)
        self.assertFalse(timed)

    def test_stale_cli_registration_failure_is_not_healthy(self):
        exe = self.root / "claude"; exe.write_text(""); exe.chmod(0o700)
        with patch("fable_mode.adapters.run_argv", return_value=(1, "unexpected failure", "", False)):
            with self.assertRaises(RegistrationError):
                register_hosts({"claude": Host("claude", exe, "cli", True)}, [str(exe), "serve"], home=self.root)

    def test_frozen_like_mcp_smoke(self):
        result = Installer(self.root / "i").install(); result.transaction.commit()
        self.assertEqual(result.executable_argv[-1], "serve")
        self.assertEqual(_smoke(result.executable_argv, self.root / "data")[0], True)


if __name__ == "__main__":
    unittest.main()

class RemediationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()

    def test_verify_requires_runtime_manifest_and_rejects_links(self):
        target = self.root / "install"
        result = Installer(target).install(); result.transaction.commit()
        marker = json.loads((target / ".fable-install.json").read_text())
        marker["files"].pop("fable_engine/server.py")
        (target / ".fable-install.json").write_text(json.dumps(marker))
        self.assertFalse(verify_installation(target)[0])
        with self.assertRaises(InstallError):
            Installer(target).install()
        # A fresh valid installation still refuses a symlink substitution.
        result = Installer(self.root / "fresh-install").install(); result.transaction.commit()
        runtime = result.install_dir / "runtime" / "fable_engine" / "server.py"
        moved = runtime.with_suffix(".real"); runtime.rename(moved); runtime.symlink_to(moved)
        self.assertFalse(verify_installation(target)[0])

    def test_cli_registration_cleanup_requires_exact_match(self):
        from fable_mode.adapters import cleanup_recorded_registrations
        exe = self.root / "host"
        record = {"kind": "cli", "host": "claude", "executable": str(exe),
                  "name": "fable-engine", "command": "fable", "args": ["serve"]}
        with patch("fable_mode.adapters.run_argv", return_value=(0, json.dumps({"fable-engine": {"command": "other", "args": []}}), "", False)) as runner:
            self.assertEqual(cleanup_recorded_registrations([record]), ["claude"])
            self.assertEqual(runner.call_count, 1)
        with patch("fable_mode.adapters.run_argv", side_effect=[(0, json.dumps({"fable-engine": {"command": "fable", "args": ["serve"]}}), "", False), (0, "", "", False)]) as runner:
            self.assertEqual(cleanup_recorded_registrations([record]), [])
            self.assertEqual(runner.call_count, 2)

    def test_file_registration_cleanup_requires_exact_match(self):
        from fable_mode.adapters import cleanup_recorded_registrations
        config = self.root / "mcp.json"; config.write_text(json.dumps({"mcpServers": {
            "fable-engine": {"command": "other", "args": []}, "keep": {"x": 1}}}))
        skipped = cleanup_recorded_registrations([{"kind": "file", "path": str(config),
            "name": "fable-engine", "command": "fable", "args": ["serve"]}])
        self.assertEqual(skipped, [str(config)])
        self.assertIn("keep", json.loads(config.read_text())["mcpServers"])

    def test_release_and_windows_wrapper_regressions_are_static(self):
        workflow = Path(".github/workflows/release.yml").read_text()
        self.assertIn('PATH="$PWD/home/bin:$PATH"', workflow)
        self.assertIn('$env:Path = "$bin;$env:Path"', workflow)
        self.assertIn(".gemini/config/mcp_config.json", workflow)
        self.assertNotIn('home/agy.json', workflow)
        self.assertIn(".gemini\\config\\mcp_config.json", workflow)
        self.assertNotIn('"agy.json"', workflow)
        self.assertIn("-3", Path("install.ps1").read_text())
        self.assertIn("-3", Path("install-antigravity.ps1").read_text())

    @unittest.skipUnless(shutil.which("pip"), "pip unavailable")
    def test_wheel_lifecycle_from_outside_checkout(self):
        checkout = Path(__file__).resolve().parents[1]
        source = self.root / "src"; source.mkdir()
        for name in ("fable_mode", "fable_engine", "fable_v2", "rules", "docs"):
            shutil.copytree(checkout / name, source / name)
        for name in ("fable_mode_entry.py", "LICENSE", "README.md", "pyproject.toml", "setup.py"):
            shutil.copy2(checkout / name, source / name)
        dist, site, outside = self.root / "dist", self.root / "site", self.root / "outside"
        dist.mkdir(); site.mkdir(); outside.mkdir()
        subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(dist)], cwd=source, check=True, capture_output=True)
        env = os.environ.copy(); env["PIP_USER"] = "0"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(site), *map(str, dist.glob("*.whl"))], env=env, check=True, capture_output=True)
        env["PYTHONPATH"] = str(site); env["FABLE_INSTALL_DIR"] = str(self.root / "install")
        probe = subprocess.run([sys.executable, "-c", "from fable_mode.installer import Installer,verify_installation; r=Installer().install(); r.transaction.commit(); assert verify_installation(r.install_dir)[0]"], cwd=outside, env=env, check=True, capture_output=True, text=True)
