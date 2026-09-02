import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_v2 import BrokerPolicy, ExecutionBroker
from fable_v2.execution_broker import (
    BROKER_PROBE_FIELDS, MAX_ERROR_TEXT, MAX_FRAME_BYTES, serve,
)


class ExecutionBrokerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)
        self.executable = Path(sys.executable).name
        self.broker = ExecutionBroker(BrokerPolicy(
            workspace=self.workspace,
            allowed_executables=(self.executable,),
            write_token_digest=hashlib.sha256(b"admin-token").hexdigest(),
        ))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_probe_has_the_stable_contract_fields(self):
        expected = {
            "host", "capabilities", "available_executables", "executable_identities",
            "execution_binding", "writes_enabled", "read_locked_interpreters",
            "workspace", "workspace_identity",
        }
        probe = self.broker.probe()
        self.assertEqual(set(BROKER_PROBE_FIELDS), expected)
        self.assertEqual(set(probe), expected)

    def test_default_probe_skips_optional_missing_pytest(self):
        """The documented default must work without the optional pytest command."""
        import fable_v2.execution_broker as module
        real_which = shutil.which

        def which_without_pytest(name):
            return None if name == "pytest" else real_which(name)

        with patch.object(module.shutil, "which", side_effect=which_without_pytest):
            broker = ExecutionBroker(BrokerPolicy(self.workspace))
        self.assertIn("python", broker.probe()["available_executables"])
        self.assertNotIn("pytest", broker.probe()["available_executables"])

    @unittest.skipIf(os.name == "nt", "descriptor-pinned interpreter test is POSIX-only")
    def test_default_probe_subprocess_works_without_pytest_on_path(self):
        """Exercise the documented default CLI in a deliberately minimal PATH."""
        env = {"PATH": str(Path(sys.executable).parent),
               "PYTHONPATH": os.getcwd()}
        request = json.dumps({"action": "probe"}) + "\n"
        completed = subprocess.run(
            [sys.executable, "-m", "fable_v2.execution_broker",
             "--workspace", str(self.workspace)],
            input=request, text=True, capture_output=True, env=env, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"])
        self.assertIn("python", response["result"]["available_executables"])
        self.assertNotIn("pytest", response["result"]["available_executables"])

    @unittest.skipIf(os.name == "nt" or sys.platform == "darwin", "descriptor-pinned interpreter test requires Linux procfs")
    def test_script_uses_pinned_interpreter_after_path_replacement(self):
        """Replacing a shebang path between validation and Popen cannot alter execution."""
        import fable_v2.execution_broker as module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "interpreter"
            shutil.copyfile("/bin/sh", interpreter)
            interpreter.chmod(0o700)
            script = root / "runner"
            script.write_text(f"#!{interpreter}\necho pinned\n", encoding="utf-8")
            script.chmod(0o700)
            replacement = root / "replacement"
            replacement.write_text("#!/bin/sh\necho replaced\n", encoding="utf-8")
            replacement.chmod(0o700)
            # The replacement is visibly distinguishable: an unpinned kernel
            # shebang lookup would run this file instead of the original shell.
            broker = ExecutionBroker(BrokerPolicy(
                root, (str(script), str(interpreter)),
                write_token_digest=hashlib.sha256(b"admin-token").hexdigest(),
            ))
            broker.unlock_writes("admin-token")
            original_popen = module.subprocess.Popen

            def replace_before_spawn(*args, **kwargs):
                os.replace(replacement, interpreter)
                return original_popen(*args, **kwargs)

            with patch.object(module.subprocess, "Popen", side_effect=replace_before_spawn):
                result = broker.execute_command([str(script)])
            self.assertTrue(result["success"])
            self.assertIn("pinned", result["stdout"])

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem/process capabilities are fail-closed")
    def test_attempted_write_quota_is_shared_and_persistent(self):
        """Fresh broker instances observe prior replacement attempts via the ledger."""
        token_digest = hashlib.sha256(b"admin-token").hexdigest()
        first = ExecutionBroker(BrokerPolicy(
            self.workspace, (self.executable,), max_file_write_bytes=4,
            max_workspace_write_bytes=8, write_token_digest=token_digest,
        ))
        second = ExecutionBroker(BrokerPolicy(
            self.workspace, (self.executable,), max_file_write_bytes=4,
            max_workspace_write_bytes=8, write_token_digest=token_digest,
        ))
        first.unlock_writes("admin-token")
        second.unlock_writes("admin-token")
        first.write_file("replaced.txt", "ab")
        second.write_file("replaced.txt", "cd")
        with self.assertRaises(PermissionError):
            first.write_file("replaced.txt", "e")
        ledger = json.loads((self.workspace / ".fable-workspace-quota.json").read_text())
        self.assertEqual(ledger["attempted_bytes"], 4)
        self.assertEqual(ledger["files"]["replaced.txt"], 4)

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem/process capabilities are fail-closed")
    def test_attempted_write_ledger_has_bounded_entries(self):
        import fable_v2.execution_broker as module
        token_digest = hashlib.sha256(b"admin-token").hexdigest()
        broker = ExecutionBroker(BrokerPolicy(
            self.workspace, (self.executable,), max_file_write_bytes=4,
            max_workspace_write_bytes=8, write_token_digest=token_digest,
        ))
        broker.unlock_writes("admin-token")
        with patch.object(module, "MAX_WORKSPACE_QUOTA_LEDGER_ENTRIES", 1):
            broker.write_file("first.txt", "")
            with self.assertRaises(PermissionError):
                broker.write_file("second.txt", "")

    def test_interpreters_are_blocked_before_write_authorization(self):
        # shell=False does not stop Python from opening files directly.
        with self.assertRaises(PermissionError):
            self.broker.execute_command([
                sys.executable, "-c", "open('unauthorized.txt', 'w').write('bypass')"
            ])
        self.assertFalse((self.workspace / "unauthorized.txt").exists())

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem/process capabilities are fail-closed")
    def test_command_is_allowlisted_and_runs_after_authorization(self):
        with self.assertRaises(PermissionError):
            self.broker.execute_command(["sh", "-c", "echo escaped"])
        self.broker.unlock_writes("admin-token")
        result = self.broker.execute_command([
            sys.executable, "-c", "print('broker-ok')"
        ])
        self.assertTrue(result["success"])
        self.assertIn("broker-ok", result["stdout"])

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem/process capabilities are fail-closed")
    def test_inspect_files_is_implemented_and_bounded(self):
        target = self.workspace / "input.txt"
        target.write_text("hello world", encoding="utf-8")
        result = self.broker.handle({"action": "inspect_files", "path": "input.txt"})
        self.assertEqual(result["content"], "hello world")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["content_hash"], hashlib.sha256(b"hello world").hexdigest())
        self.assertEqual(self.broker.handle({"action": "probe_capabilities"}), self.broker.probe())

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem/process capabilities are fail-closed")
    def test_subprocess_output_is_bounded_before_capture(self):
        limited = ExecutionBroker(BrokerPolicy(
            workspace=self.workspace,
            allowed_executables=(self.executable,),
            max_output_bytes=4096,
            write_token_digest=hashlib.sha256(b"admin-token").hexdigest(),
        ))
        limited.unlock_writes("admin-token")
        result = limited.execute_command([
            sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000000)"
        ])
        self.assertTrue(result["output_limited"])
        self.assertFalse(result["success"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 4096)

    def test_same_basename_from_different_path_is_rejected(self):
        fake = self.workspace / self.executable
        fake.write_text("not the registered executable")
        with self.assertRaises(PermissionError):
            self.broker.execute_command([str(fake), "-c", "print('wrong')"])

    def test_paths_cannot_escape_workspace(self):
        self.broker.unlock_writes("admin-token")
        with self.assertRaises(PermissionError):
            self.broker.write_file("../outside.txt", "blocked")

    def test_json_lines_frames_are_bounded_and_continue_after_oversize(self):
        """The model pipe can stay open; one bad frame cannot desynchronize it."""
        output = io.StringIO()
        import fable_v2.execution_broker as module
        with patch.object(module.sys, "stdin", io.StringIO(
                "x" * (MAX_FRAME_BYTES + 1) + "\n"
                + json.dumps({"action": "probe"}) + "\n")), \
             patch.object(module.sys, "stdout", output):
            serve(self.broker)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertFalse(responses[0]["ok"])
        self.assertLessEqual(len(responses[0]["message"].encode()), MAX_ERROR_TEXT)
        self.assertTrue(responses[1]["ok"])
        if os.name == "nt":
            self.assertNotIn("execute_command", responses[1]["result"]["capabilities"])
        else:
            self.assertIn("execute_command", responses[1]["result"]["capabilities"])

    def test_mcp_worker_admission_is_bounded_and_completed_workers_release_slots(self):
        """A connection rejects overload and admits a call after cleanup."""
        import fable_v2.execution_broker as module

        first = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "probe", "arguments": {}},
        }).encode() + b"\n"
        second = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "probe", "arguments": {}},
        }).encode() + b"\n"
        third = json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "probe", "arguments": {}},
        }).encode() + b"\n"
        started = threading.Event()
        release = threading.Event()
        first_done = threading.Event()

        def fake_dispatch(_broker, request, _state):
            if request.get("id") == 1:
                started.set()
                release.wait(2)
                first_done.set()
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}

        class ControlledInput:
            def __init__(self):
                self.frames = (first, second, third)
                self.frame = 0
                self.offset = 0

            def read(self, _size=1):
                if self.frame == 0 and self.offset == len(self.frames[0]):
                    self.frame = 1
                    self.offset = 0
                    self.assert_started = started.wait(2)
                if self.frame == 1 and self.offset == len(self.frames[1]):
                    release.set()
                    self.assert_first_done = first_done.wait(2)
                    self.frame = 2
                    self.offset = 0
                if self.frame == 2 and self.offset == len(self.frames[2]):
                    return b""
                if self.frame >= len(self.frames):
                    return b""
                frame = self.frames[self.frame]
                value = frame[self.offset:self.offset + 1]
                self.offset += 1
                return value

        output = io.StringIO()
        source = ControlledInput()
        with patch.object(module, "_dispatch_jsonrpc", side_effect=fake_dispatch), \
             patch.object(module.sys, "stdin", source), \
             patch.object(module.sys, "stdout", output):
            module.serve(self.broker, max_workers=1)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        by_id = {response["id"]: response for response in responses}
        self.assertEqual(set(by_id), {1, 2, 3})
        self.assertEqual(by_id[1]["result"], {})
        overload = by_id[2]["error"]
        self.assertEqual(overload["code"], module.MCP_OVERLOAD_ERROR_CODE)
        self.assertEqual(overload["data"]["type"], "overloaded")
        self.assertEqual(overload["data"]["max_workers"], 1)
        self.assertTrue(overload["data"]["retryable"])
        self.assertEqual(by_id[3]["result"], {})

    def test_mcp_worker_limit_is_validated(self):
        import fable_v2.execution_broker as module
        with self.assertRaises(ValueError):
            module.MCPConnectionState(max_workers=0)
        with self.assertRaises(ValueError):
            module.MCPConnectionState(max_workers=module.MAX_MCP_WORKERS + 1)

    def test_malformed_json_is_a_bounded_controlled_error(self):
        output = io.StringIO()
        import fable_v2.execution_broker as module
        with patch.object(module.sys, "stdin", io.StringIO("{" + "x" * 20000 + "\n")), \
             patch.object(module.sys, "stdout", output):
            serve(self.broker)
        response = json.loads(output.getvalue())
        self.assertFalse(response["ok"])
        self.assertLessEqual(len(response["message"].encode()), MAX_ERROR_TEXT + 20)

    @unittest.skipIf(os.name == "nt", "Windows broker filesystem writes are fail-closed")
    def test_writes_are_locked_until_admin_authorization(self):
        with self.assertRaises(PermissionError):
            self.broker.write_file("result.txt", "blocked")
        with self.assertRaises(PermissionError):
            self.broker.unlock_writes("wrong-token")
        self.broker.unlock_writes("admin-token")
        result = self.broker.write_file("result.txt", "accepted")
        self.assertTrue(result["writes_enabled"])
        self.assertEqual((self.workspace / "result.txt").read_text(), "accepted")

    @unittest.skipUnless(os.name != "nt", "inherited admin FD test is POSIX-only")
    def test_broker_is_available_as_a_json_lines_child_process(self):
        admin_read, admin_write = os.pipe()
        env = os.environ.copy()
        env["FABLE_BROKER_WRITE_TOKEN_DIGEST"] = hashlib.sha256(
            b"admin-token"
        ).hexdigest()
        process = subprocess.Popen(
            [sys.executable, "-m", "fable_v2.execution_broker",
             "--workspace", str(self.workspace),
             "--allow-executable", self.executable,
             "--admin-fd", str(admin_read)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env,
            pass_fds=(admin_read,),
        )
        os.close(admin_read)
        try:
            os.write(admin_write, (json.dumps({
                "action": "unlock_writes", "token": "admin-token",
            }) + "\n").encode("utf-8"))
            os.close(admin_write)
            response = None
            for _ in range(50):
                process.stdin.write(json.dumps({"action": "probe"}) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                if response["result"].get("writes_enabled"):
                    break
                time.sleep(0.01)
            self.assertTrue(response["ok"])
            self.assertIn("execute_command", response["result"]["capabilities"])
            self.assertTrue(response["result"]["writes_enabled"])
            process.stdin.write(json.dumps({
                "action": "write_file", "path": "cli.txt",
                "content": "cli-authorized",
            }) + "\n")
            process.stdin.flush()
            write_response = json.loads(process.stdout.readline())
            self.assertTrue(write_response["ok"])
            self.assertEqual((self.workspace / "cli.txt").read_text(), "cli-authorized")
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
