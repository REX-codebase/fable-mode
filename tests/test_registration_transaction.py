import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_mode.adapters import Host, RegistrationError, cleanup_recorded_registrations, register_hosts
from fable_mode.installer import InstallError, Installer
from fable_mode import launcher


class RegistrationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _host(self, name, *, human=False, fail_add=False):
        script = self.root / name
        state = self.root / f"{name}.json"
        state.write_text(json.dumps({"fable-engine": {"command": "old", "args": ["--old"]},
                                     "fable-mode": {"command": "legacy", "args": ["serve"]}}))
        code = """
import json, pathlib, sys
p = pathlib.Path(__file__).with_suffix('.json')
s = json.loads(p.read_text())
if sys.argv[1:2] == ['--version']:
    print('fake'); raise SystemExit(0)
if sys.argv[1:3] == ['mcp', 'list']:
    HUMAN = HUMAN
    if HUMAN: print('Configured MCP servers: fable-engine'); raise SystemExit(0)
    print(json.dumps(s)); raise SystemExit(0)
if sys.argv[1:3] == ['mcp', 'remove']:
    name = sys.argv[3]
    if name not in s:
        print('No MCP server named ' + name, file=sys.stderr); raise SystemExit(2)
    del s[name]; p.write_text(json.dumps(s)); raise SystemExit(0)
if sys.argv[1:3] == ['mcp', 'add']:
    marker = sys.argv.index('--')
    if FAIL_ADD and sys.argv[marker + 1] == 'new-runtime': raise SystemExit(9)
    name = sys.argv[3]
    s[name] = {'command': sys.argv[marker + 1], 'args': sys.argv[marker + 2:]}
    p.write_text(json.dumps(s)); raise SystemExit(0)
raise SystemExit(4)
"""
        script_body = "#!/usr/bin/env python3\n" + "HUMAN = " + repr(human) + "\nFAIL_ADD = " + repr(fail_add) + "\n" + textwrap.dedent(code)
        if os.name == "nt":
            py_script = script.with_suffix(".py")
            py_script.write_text(script_body)
            script = script.with_suffix(".cmd")
            script.write_text(f'@echo off\n"{os.fspath(Path(sys.executable))}" "{os.fspath(py_script)}" %*\n')
        else:
            script.write_text(script_body)
            script.chmod(stat.S_IRWXU)
        return Host(name, script, "cli", True), state

    def test_existing_canonical_and_legacy_are_restored_on_uninstall(self):
        host, state = self._host("host")
        before = state.read_bytes()
        records = []
        register_hosts({"codex": host}, ["new-runtime", "serve"], records=records)
        installed = json.loads(state.read_text())
        self.assertEqual(installed["fable-engine"], {"command": "new-runtime", "args": ["serve"]})
        self.assertNotIn("fable-mode", installed)
        self.assertEqual(cleanup_recorded_registrations(records), [])
        self.assertEqual(state.read_bytes(), before)

    def test_later_host_failure_rolls_back_earlier_host(self):
        first, first_state = self._host("first")
        second, second_state = self._host("second", fail_add=True)
        before = (first_state.read_bytes(), second_state.read_bytes())
        with self.assertRaises(RegistrationError):
            register_hosts({"codex": first, "claude": second}, ["new-runtime", "serve"])
        self.assertEqual((first_state.read_bytes(), second_state.read_bytes()), before)

    def test_human_readable_list_fails_before_mutation(self):
        host, state = self._host("human", human=True)
        before = state.read_bytes()
        with self.assertRaises(RegistrationError):
            register_hosts({"codex": host}, ["new-runtime", "serve"])
        self.assertEqual(state.read_bytes(), before)

    def test_absent_remove_output_is_benign(self):
        host, state = self._host("empty")
        state.write_text("{}")
        register_hosts({"codex": host}, ["new-runtime", "serve"])
        self.assertEqual(json.loads(state.read_text())["fable-engine"]["args"], ["serve"])

    def test_reinstall_preserves_first_user_baseline_and_uninstall_cleans_new_runtime(self):
        """A retired Fable entry must not become user-owned on replacement."""
        host, state = self._host("codex")
        home = self.root
        target = self.root / "install"

        def install_and_register(installer, owned=None):
            result = installer.install()
            records = []
            if owned is None:
                owned = installer.previous_registrations
            register_hosts({"codex": host}, result.executable_argv, home=home,
                           records=records, owned_records=owned)
            install_st = result.install_dir.lstat()
            for record in records:
                record["install_dir"] = str(result.install_dir)
                record["install_identity"] = [install_st.st_dev, install_st.st_ino]
            installer.record_registrations(records)
            result.transaction.commit()
            return records

        original = state.read_bytes()
        first = Installer(target)
        install_and_register(first)
        # Replace without registration: ownership records must be migrated.
        second = Installer(target)
        replacement = second.install()
        replacement.transaction.commit()
        third = Installer(target)
        records = install_and_register(third)
        self.assertEqual(records[0]["previous_entries"], {
            "fable-engine": {"command": "old", "args": ["--old"]},
            "fable-mode": {"command": "legacy", "args": ["serve"]},
        })
        with patch("pathlib.Path.home", return_value=home):
            third.uninstall()
        self.assertEqual(state.read_bytes(), original)

    def test_file_registration_is_private_and_reinstall_restores_mode_and_state(self):
        home = self.root / "home"
        config = home / ".gemini" / "config" / "mcp_config.json"
        config.parent.mkdir(parents=True)
        original = {"keep": {"x": 1}, "mcpServers": {
            "fable-engine": {"command": "user", "args": ["u"], "cwd": "/user/work"},
            "fable-mode": {"command": "legacy", "args": ["l"], "env": {"PROFILE": "user"}},
        }}
        config.write_text(json.dumps(original))
        config.chmod(0o644)
        exe = self.root / "agy"
        exe.write_text("")
        exe.chmod(0o700)
        host = Host("agy", exe, "cli", True)
        first = []
        register_hosts({"agy": host}, ["runtime-v1", "serve"], home=home, records=first)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        second = []
        register_hosts({"agy": host}, ["runtime-v2", "serve"], home=home,
                       records=second, owned_records=first)
        self.assertEqual(second[0]["previous_entries"], original["mcpServers"])
        if os.name != "nt":
            self.assertEqual(second[0]["previous_mode"], 0o644)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(cleanup_recorded_registrations(second, home=home), [])
        self.assertEqual(json.loads(config.read_text()), original)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o644)

    def test_windows_created_antigravity_config_is_unlinked_without_mode_zero(self):
        """A frozen Windows install must remove an initially absent config.

        ``previous_mode`` is zero when the Antigravity config did not exist.
        Restoring that mode before unlinking maps to Windows' read-only
        attribute and makes cleanup fail, even though the post-install file is
        still the exact inode and byte sequence Fable published.
        """
        home = self.root / "home"
        exe = self.root / "agy"
        exe.write_text("")
        exe.chmod(0o700)
        target = self.root / "install"
        target.mkdir()
        host = Host("agy", exe, "cli", True)
        records = []
        register_hosts({"agy": host}, [str(target / "fable-mode.exe"), "serve"],
                       home=home, records=records)
        install_st = target.lstat()
        for record in records:
            record["install_dir"] = str(target)
            record["install_identity"] = [install_st.st_dev, install_st.st_ino]
        self.assertFalse(records[0]["existed"])
        self.assertEqual(records[0]["previous_mode"], 0)
        with patch("fable_mode.adapters._atomic_write",
                   side_effect=AssertionError("must not restore mode 0")):
            self.assertEqual(cleanup_recorded_registrations(
                records, strict=True, install_dir=target, home=home), [])
        self.assertFalse(home.joinpath(".gemini", "config", "mcp_config.json").exists())

    def test_cli_mutation_environment_does_not_forward_secrets(self):
        """Automatic host mutations receive only the documented safe env."""
        script = self.root / "observing-codex"
        state = self.root / "observing-codex.json"
        observed = self.root / "observed-env.json"
        state.write_text("{}")
        script_body = "#!/usr/bin/env python3\n" + textwrap.dedent(f"""
            import json, os, pathlib, sys
            pathlib.Path({str(observed)!r}).write_text(json.dumps({{
                "secret": os.environ.get("FABLE_TEST_SECRET"),
                "path": os.environ.get("PATH"),
                "home": os.environ.get("HOME"),
                "xdg": os.environ.get("XDG_CONFIG_HOME"),
            }}))
            p = pathlib.Path({str(state)!r})
            s = json.loads(p.read_text())
            if sys.argv[1:3] == ["mcp", "list"]:
                print(json.dumps(s)); raise SystemExit(0)
            if sys.argv[1:3] == ["mcp", "remove"]:
                s.pop(sys.argv[3], None); p.write_text(json.dumps(s)); raise SystemExit(0)
            if sys.argv[1:3] == ["mcp", "add"]:
                marker = sys.argv.index("--")
                s[sys.argv[3]] = {{"command": sys.argv[marker + 1], "args": sys.argv[marker + 2:]}}
                p.write_text(json.dumps(s)); raise SystemExit(0)
            raise SystemExit(0)
        """)
        if os.name == "nt":
            py_script = script.with_suffix(".py")
            py_script.write_text(script_body)
            script = script.with_suffix(".cmd")
            script.write_text(f'@echo off\n"{os.fspath(Path(sys.executable))}" "{os.fspath(py_script)}" %*\n')
        else:
            script.write_text(script_body)
            script.chmod(stat.S_IRWXU)
        with patch.dict(os.environ, {"FABLE_TEST_SECRET": "must-not-leak"}):
            register_hosts({"codex": Host("codex", script, "cli", True)},
                           ["new-runtime", "serve"])
        env_seen = json.loads(observed.read_text())
        self.assertIsNone(env_seen["secret"])
        self.assertTrue(env_seen["path"])
        self.assertTrue(env_seen["home"])
        self.assertTrue(env_seen["xdg"])

    def test_launcher_cleans_hosts_before_rollback_when_marker_persistence_fails(self):
        host, state = self._host("marker-failure")
        original = state.read_bytes()
        target = self.root / "install-marker-failure"
        with patch("fable_mode.launcher.detect_hosts", return_value={"codex": host}), \
             patch.object(Installer, "record_registrations", side_effect=RuntimeError("marker write failed")):
            self.assertEqual(launcher.main(["install", "--yes", "--register-hosts",
                                            "--install-dir", str(target)]), 1)
        self.assertEqual(state.read_bytes(), original)
        self.assertFalse(target.exists())

    def test_failed_marker_write_and_cleanup_preserve_recoverable_record(self):
        """A failed first marker write must not strand a live host entry."""
        host, state = self._host("codex")
        original = state.read_bytes()
        target = self.root / "install-recovery-record"
        calls = {"count": 0}
        real_record_registrations = Installer.record_registrations

        def fail_once(installer, records):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("marker write failed")
            return real_record_registrations(installer, records)

        with patch("fable_mode.launcher.detect_hosts", return_value={"codex": host}), \
             patch("fable_mode.launcher.cleanup_recorded_registrations", return_value=["codex"]), \
             patch.object(Installer, "record_registrations", new=fail_once):
            self.assertEqual(launcher.main(["install", "--yes", "--register-hosts",
                                            "--install-dir", str(target)]), 1)

        marker = json.loads((target / ".fable-install.json").read_text())
        self.assertEqual(len(marker["registrations"]), 1)
        self.assertEqual(marker["registrations"][0]["host"], "codex")
        self.assertEqual(json.loads(state.read_text())["fable-engine"],
                         {"command": sys.executable,
                          "args": [str(target / "runtime" / "fable_mode_entry.py"), "serve"]})

        # A later process can use the persisted record to restore the host and
        # remove the preserved installation without the original transaction.
        with patch("pathlib.Path.home", return_value=Path.home()):
            Installer(target).uninstall()
        self.assertEqual(state.read_bytes(), original)
        self.assertFalse(target.exists())

    def test_commit_failure_leaves_replacement_transaction_rollbackable(self):
        target = self.root / "commit-rollbackable"
        first = Installer(target).install()
        first.transaction.commit()
        replacement = Installer(target).install()
        with patch.object(replacement.transaction, "_verify_backup",
                          side_effect=InstallError("backup check failed")):
            with self.assertRaises(InstallError):
                replacement.transaction.commit()
        self.assertFalse(replacement.transaction.done)
        replacement.transaction.rollback()
        self.assertTrue(target.exists())

    def test_launcher_cleans_hosts_before_rollback_when_commit_fails(self):
        host, state = self._host("commit-failure")
        original = state.read_bytes()
        target = self.root / "install-commit-failure"
        old = Installer(target).install()
        old.transaction.commit()
        with patch("fable_mode.launcher.detect_hosts", return_value={"codex": host}), \
             patch("fable_mode.installer.InstallTransaction._verify_backup",
                   side_effect=[InstallError("commit failed"), None]):
            self.assertEqual(launcher.main(["install", "--yes", "--register-hosts",
                                            "--install-dir", str(target)]), 1)
        self.assertEqual(state.read_bytes(), original)
        self.assertTrue(target.exists())
        self.assertEqual(json.loads((target / ".fable-install.json").read_text())["registrations"], [])

    def test_uninstall_preserves_marker_when_host_executable_disappears(self):
        host, state = self._host("codex")
        target = self.root / "install-vanished-host"
        installer = Installer(target)
        result = installer.install()
        records = []
        register_hosts({"codex": host}, result.executable_argv, records=records)
        install_st = target.lstat()
        for record in records:
            record["install_dir"] = str(target)
            record["install_identity"] = [install_st.st_dev, install_st.st_ino]
        installer.record_registrations(records)
        result.transaction.commit()
        host.executable.unlink()
        with self.assertRaises(InstallError):
            Installer(target).uninstall()
        self.assertTrue(target.exists())
        self.assertEqual(json.loads((target / ".fable-install.json").read_text())["registrations"], records)

    def test_cli_mutation_uses_real_home_state_and_persists(self):
        """Discovery may be sandboxed, but add/remove must use the target HOME."""
        home = self.root / "home"
        home.mkdir()
        script = self.root / "home-only-codex"
        state = home / "codex-mcp.json"
        state.write_text(json.dumps({"user": {"command": "keep", "args": []}}))
        script_body = "#!/usr/bin/env python3\n" + textwrap.dedent("""
            import json, os, pathlib, sys
            p = pathlib.Path(os.environ["HOME"]) / "codex-mcp.json"
            s = json.loads(p.read_text())
            if sys.argv[1:2] == ["--version"]:
                print("fake"); raise SystemExit(0)
            if sys.argv[1:3] == ["mcp", "list"]:
                print(json.dumps(s)); raise SystemExit(0)
            if sys.argv[1:3] == ["mcp", "remove"]:
                name = sys.argv[3]
                if name not in s:
                    print("No MCP server named " + name, file=sys.stderr); raise SystemExit(2)
                del s[name]; p.write_text(json.dumps(s)); raise SystemExit(0)
            if sys.argv[1:3] == ["mcp", "add"]:
                marker = sys.argv.index("--"); name = sys.argv[3]
                s[name] = {"command": sys.argv[marker + 1], "args": sys.argv[marker + 2:]}
                p.write_text(json.dumps(s)); raise SystemExit(0)
            raise SystemExit(4)
        """)
        if os.name == "nt":
            py_script = script.with_suffix(".py")
            py_script.write_text(script_body)
            script = script.with_suffix(".cmd")
            script.write_text(f'@echo off\n"{os.fspath(Path(sys.executable))}" "{os.fspath(py_script)}" %*\n')
        else:
            script.write_text(script_body)
            script.chmod(stat.S_IRWXU)
        records = []
        register_hosts({"codex": Host("codex", script, "cli", True)},
                       ["new-runtime", "serve"], home=home, records=records)
        changed = json.loads(state.read_text())
        self.assertEqual(changed["fable-engine"], {"command": "new-runtime", "args": ["serve"]})
        self.assertIn("user", changed)
        self.assertEqual(cleanup_recorded_registrations(records, home=home), [])
        self.assertEqual(json.loads(state.read_text()), {"user": {"command": "keep", "args": []}})


if __name__ == "__main__":
    unittest.main()

