import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_v2 import BrokerPolicy, ExecutionBroker
from fable_v2.execution_broker import MAX_ERROR_TEXT, MAX_FRAME_BYTES, serve


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

    def test_interpreters_are_blocked_before_write_authorization(self):
        # shell=False does not stop Python from opening files directly.
        with self.assertRaises(PermissionError):
            self.broker.execute_command([
                sys.executable, "-c", "open('unauthorized.txt', 'w').write('bypass')"
            ])
        self.assertFalse((self.workspace / "unauthorized.txt").exists())

    def test_command_is_allowlisted_and_runs_after_authorization(self):
        with self.assertRaises(PermissionError):
            self.broker.execute_command(["sh", "-c", "echo escaped"])
        self.broker.unlock_writes("admin-token")
        result = self.broker.execute_command([
            sys.executable, "-c", "print('broker-ok')"
        ])
        self.assertTrue(result["success"])
        self.assertIn("broker-ok", result["stdout"])

    def test_inspect_files_is_implemented_and_bounded(self):
        target = self.workspace / "input.txt"
        target.write_text("hello world", encoding="utf-8")
        result = self.broker.handle({"action": "inspect_files", "path": "input.txt"})
        self.assertEqual(result["content"], "hello world")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["content_hash"], hashlib.sha256(b"hello world").hexdigest())
        self.assertEqual(self.broker.handle({"action": "probe_capabilities"}), self.broker.probe())

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
        self.assertIn("execute_command", responses[1]["result"]["capabilities"])

    def test_malformed_json_is_a_bounded_controlled_error(self):
        output = io.StringIO()
        import fable_v2.execution_broker as module
        with patch.object(module.sys, "stdin", io.StringIO("{" + "x" * 20000 + "\n")), \
             patch.object(module.sys, "stdout", output):
            serve(self.broker)
        response = json.loads(output.getvalue())
        self.assertFalse(response["ok"])
        self.assertLessEqual(len(response["message"].encode()), MAX_ERROR_TEXT + 20)

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
