import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_engine.server import FableCASStore, IntegrityError, MAX_RPC_LINE_BYTES, main
from fable_mode.adapters import Host, RegistrationError, register_hosts
from fable_mode.installer import InstallError, Installer
from fable_mode.adapters import _probe_environment, run_argv
from fable_v2 import BrokerPolicy, ExecutionBroker


class RedTeamRemediationTests(unittest.TestCase):
    def test_broker_rejects_nonfinite_and_excessive_timeouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = ExecutionBroker(BrokerPolicy(Path(tmp), (Path(sys.executable).name,),
                                                   write_token_digest=hashlib.sha256(b"x").hexdigest()))
            broker.unlock_writes("x")
            for value in (float("nan"), float("inf"), -float("inf"), 3601):
                with self.assertRaises(ValueError):
                    broker.execute_command([sys.executable, "-c", ""], timeout_seconds=value)

    def test_cas_bytearray_and_corrupt_existing_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FableCASStore(Path(tmp))
            ref = store.put(bytearray(b"bytes"))
            self.assertEqual(store.get_bytes(ref), b"bytes")
            store.get_file_path(ref).write_bytes(b"corrupt")
            with self.assertRaises(IntegrityError):
                store.put(b"bytes")

    def test_replacement_rejects_tampered_prior_install_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "install"
            result = Installer(target).install(); result.transaction.commit()
            (target / "unexpected.txt").write_text("preserve")
            with self.assertRaises(InstallError):
                Installer(target).install()
            self.assertEqual((target / "unexpected.txt").read_text(), "preserve")

    def test_uninstall_rejects_extra_install_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "install"
            result = Installer(target).install(); result.transaction.commit()
            (target / "unexpected.txt").write_text("do not absorb")
            with self.assertRaises(InstallError):
                Installer(target).uninstall()
            self.assertTrue(target.exists())

    def test_uninstall_rejects_tampered_arbitrary_registration_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / "install"; unrelated = root / "unrelated.json"
            unrelated.write_text('{"keep": true}')
            result = Installer(target).install(); result.transaction.commit()
            marker_path = target / ".fable-install.json"
            marker = json.loads(marker_path.read_text())
            marker["registrations"] = [{"kind": "file", "path": str(unrelated),
                "name": "fable-engine", "command": "x", "args": [],
                "previous_entries": {"fable-engine": {"command": "rm", "args": []}},
                "post_entries": {"fable-engine": {"command": "x", "args": []}}}]
            marker_path.write_text(json.dumps(marker))
            Installer(target).uninstall()
            self.assertEqual(unrelated.read_text(), '{"keep": true}')

    def test_registration_replacement_inode_is_retained_on_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root / "home"; config = home / ".gemini/config/mcp_config.json"
            config.parent.mkdir(parents=True); config.write_text(json.dumps({"mcpServers": {}}))
            exe = root / "host"; exe.write_text("x"); exe.chmod(0o700)
            replacement = {"mcpServers": {"user": {"command": "keep", "args": []}}}
            def add(host, name, entry):
                replacement_path = root / "replacement.json"
                replacement_path.write_text(json.dumps(replacement))
                replacement_path.replace(config)
                return (9, "", "failed", False)
            with patch("fable_mode.adapters._snapshot_cli_registrations", return_value={}), \
                 patch("fable_mode.adapters._cli_remove", return_value=(0, "", "", False)), \
                 patch("fable_mode.adapters._cli_add", side_effect=add):
                with self.assertRaises(RegistrationError) as raised:
                    register_hosts({"antigravity": Host("antigravity", exe, "cli", True),
                                    "codex": Host("codex", exe, "cli", True)},
                                   ["runtime", "serve"], home=home)
            self.assertIn("partial state", str(raised.exception))
            self.assertEqual(json.loads(config.read_text()), replacement)

    def test_cas_slice_apis_reject_tampered_objects_and_bad_cache_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FableCASStore(Path(tmp))
            ref = store.put("one\\ntwo\\n")
            path = store.get_file_path(ref)
            path.write_bytes(b"tampered\\n")
            # The slice viewer is reached through the server's canonical store.
            from fable_engine.server import CASSliceViewer
            viewer = CASSliceViewer(store)
            for operation in (
                lambda: store.get_file_path(ref),
                lambda: store.get_bytes(ref, verify=True),
                lambda: viewer.get_line_count(ref),
            ):
                with self.assertRaises(IntegrityError):
                    operation()
            for operation in (
                lambda: viewer.view_slice(ref, 1, 2),
                lambda: viewer.iter_slice(ref, 1, 2),
            ):
                with self.assertRaises(IntegrityError):
                    operation()
            clean_ref = store.put("clean")
            store.cache.put(store.normalize_ref(clean_ref), object())
            with self.assertRaises(IntegrityError):
                store.get_bytes(clean_ref)

    def test_broker_inspection_rejects_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"; source.write_text("secret")
            linked = root / "linked.txt"; os.link(source, linked)
            broker = ExecutionBroker(BrokerPolicy(root, (Path(sys.executable).name,)))
            with self.assertRaises(PermissionError):
                broker.inspect_files("linked.txt")

    def test_public_probe_home_env_cannot_trigger_recursive_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "victim"; victim.mkdir(); (victim / "keep").write_text("x")
            run_argv([sys.executable, "-c", ""], env={"_FABLE_PROBE_HOME": str(victim)})
            self.assertTrue((victim / "keep").exists())

    def test_probe_rejects_untrusted_absolute_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "host"
            script.write_text("#!/bin/sh\\nexit 0\\n")
            script.chmod(0o700)
            # A regular executable outside the trusted interpreter set cannot
            # be used as a shebang interpreter during discovery.
            evil = Path(tmp) / "evil"
            evil.write_text("#!/bin/sh\\nexit 0\\n"); evil.chmod(0o700)
            script.write_text(f"#!{evil}\\nexit 0\\n")
            with self.assertRaises(RegistrationError):
                _probe_environment(script)

    def test_rpc_reader_does_not_use_readline_and_preserves_next_frame(self):
        class NoReadline(io.StringIO):
            def readline(self, *args, **kwargs):
                raise AssertionError("unbounded readline used")
        stream = NoReadline(" " * (MAX_RPC_LINE_BYTES + 1) + "\n" +
                            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}) + "\n")
        output = io.StringIO()
        with patch("sys.stdin", stream), patch("sys.stdout", output):
            main()
        responses = [json.loads(line) for line in output.getvalue().splitlines() if line]
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1]["id"], 2)


if __name__ == "__main__":
    unittest.main()
