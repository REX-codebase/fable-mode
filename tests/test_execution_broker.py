import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fable_v2 import BrokerPolicy, ExecutionBroker


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
        self.broker.write_file("authorized.txt", "unlock", "admin-token")
        result = self.broker.execute_command([
            sys.executable, "-c", "print('broker-ok')"
        ])
        self.assertTrue(result["success"])
        self.assertIn("broker-ok", result["stdout"])

    def test_same_basename_from_different_path_is_rejected(self):
        fake = self.workspace / self.executable
        fake.write_text("not the registered executable")
        with self.assertRaises(PermissionError):
            self.broker.execute_command([str(fake), "-c", "print('wrong')"])

    def test_paths_cannot_escape_workspace(self):
        with self.assertRaises(PermissionError):
            self.broker.write_file("../outside.txt", "blocked", "admin-token")

    def test_writes_are_locked_until_admin_authorization(self):
        with self.assertRaises(PermissionError):
            self.broker.write_file("result.txt", "blocked")
        with self.assertRaises(PermissionError):
            self.broker.write_file("result.txt", "blocked", "wrong-token")
        result = self.broker.write_file("result.txt", "accepted", "admin-token")
        self.assertTrue(result["writes_enabled"])
        self.assertEqual((self.workspace / "result.txt").read_text(), "accepted")

    def test_broker_is_available_as_a_json_lines_child_process(self):
        env = os.environ.copy()
        env["FABLE_BROKER_WRITE_TOKEN_DIGEST"] = hashlib.sha256(
            b"admin-token"
        ).hexdigest()
        process = subprocess.Popen(
            [sys.executable, "-m", "fable_v2.execution_broker",
             "--workspace", str(self.workspace),
             "--allow-executable", self.executable],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            process.stdin.write(json.dumps({"action": "probe"}) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertTrue(response["ok"])
            self.assertIn("execute_command", response["result"]["capabilities"])
            process.stdin.write(json.dumps({
                "action": "write_file", "path": "cli.txt",
                "content": "cli-authorized", "token": "admin-token",
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
