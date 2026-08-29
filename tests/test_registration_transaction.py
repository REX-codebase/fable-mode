import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_mode.adapters import Host, RegistrationError, cleanup_recorded_registrations, register_hosts
from fable_mode.installer import Installer


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
        script.write_text("#!/usr/bin/env python3\n" + "HUMAN = " + repr(human) + "\nFAIL_ADD = " + repr(fail_add) + "\n" + textwrap.dedent(code))
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
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        second = []
        register_hosts({"agy": host}, ["runtime-v2", "serve"], home=home,
                       records=second, owned_records=first)
        self.assertEqual(second[0]["previous_entries"], original["mcpServers"])
        self.assertEqual(second[0]["previous_mode"], 0o644)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
        self.assertEqual(cleanup_recorded_registrations(second, home=home), [])
        self.assertEqual(json.loads(config.read_text()), original)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o644)

    def test_cli_mutation_uses_real_home_state_and_persists(self):
        """Discovery may be sandboxed, but add/remove must use the target HOME."""
        home = self.root / "home"
        home.mkdir()
        script = self.root / "home-only-codex"
        state = home / "codex-mcp.json"
        state.write_text(json.dumps({"user": {"command": "keep", "args": []}}))
        script.write_text("#!/usr/bin/env python3\n" + textwrap.dedent("""
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
        """))
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
