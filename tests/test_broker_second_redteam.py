"""Adversarial regression coverage for the broker/transport boundary."""
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fable_mode.adapters import GenericMCPHostAdapter
from fable_v2 import BrokerPolicy, ExecutionBroker
from fable_v2.execution_broker import MAX_RESPONSE_BYTES, serve


class BrokerSecondRedTeamTests(unittest.TestCase):
    def test_allowlist_rejects_explicit_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            real = root / "real"
            real.write_bytes(b"not an executable")
            real.chmod(0o755)
            link = root / "link"
            os.symlink(real, link)
            with self.assertRaises(ValueError):
                BrokerPolicy(root, (str(link),))
            hard = root / "hard"
            os.link(real, hard)
            with self.assertRaises(ValueError):
                BrokerPolicy(root, (str(hard),))

    @unittest.skipIf(os.name == "nt", "Windows broker execution is deliberately fail-closed")
    def test_receipt_identity_is_measured_and_workspace_is_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            policy = BrokerPolicy(root, (pathlib.Path(sys.executable).name,),
                                  write_token_digest=hashlib.sha256(b"x").hexdigest())
            broker = ExecutionBroker(policy)
            broker.unlock_writes("x")
            result = broker.execute_command([sys.executable, "-c", "print('ok')"])
            ident = result["receipt"]["executable_identity"]
            self.assertIn("sha256", ident)
            self.assertIn("inode", ident)
            self.assertEqual(result["receipt"]["workspace_identity"]["inode"],
                             root.stat().st_ino)

    @unittest.skipIf(os.name == "nt", "Windows broker execution is deliberately fail-closed")
    def test_mcp_handshake_id_propagation_and_notification_cancellation(self):
        with tempfile.TemporaryDirectory() as d:
            broker = ExecutionBroker(BrokerPolicy(
                pathlib.Path(d), (pathlib.Path(sys.executable).name,),
                write_token_digest=hashlib.sha256(b"x").hexdigest()))
            broker.unlock_writes("x")
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": "outer", "method": "tools/call",
                 "params": {"name": "execute_command", "arguments": {
                     "command": [sys.executable, "-c", "import time; time.sleep(2)"],
                     "timeout_seconds": 10}}},
                {"jsonrpc": "2.0", "method": "notifications/cancelled",
                 "params": {"requestId": "outer"}},
            ]
            output = io.StringIO()
            import fable_v2.execution_broker as module
            with patch.object(module.sys, "stdin", io.StringIO(
                    "".join(json.dumps(item) + "\n" for item in requests))), \
                 patch.object(module.sys, "stdout", output):
                serve(broker)
            replies = [json.loads(line) for line in output.getvalue().splitlines()]
            call = next(item for item in replies if item.get("id") == "outer")
            self.assertEqual(call["result"]["structuredContent"]["request_id"], "outer")
            self.assertTrue(call["result"]["structuredContent"]["cancelled"])

    def test_adapter_generates_correlated_ids_and_standard_cancel(self):
        adapter = GenericMCPHostAdapter()
        init = adapter.initialize()
        call = adapter.route_tool("probe")
        self.assertTrue(init["id"])
        self.assertTrue(call["id"])
        self.assertNotEqual(init["id"], call["id"])
        cancellation = adapter.cancel(call["id"])
        self.assertEqual(cancellation["method"], "notifications/cancelled")
        self.assertEqual(cancellation["params"]["requestId"], call["id"])

    @unittest.skipIf(os.name == "nt", "Windows broker execution is deliberately fail-closed")
    def test_cancellation_overtaking_registration_is_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            broker = ExecutionBroker(BrokerPolicy(
                pathlib.Path(d), (pathlib.Path(sys.executable).name,),
                write_token_digest=hashlib.sha256(b"x").hexdigest()))
            broker.unlock_writes("x")
            self.assertFalse(broker.handle({"action": "cancel", "request_id": "early"})["cancelled"])
            result = broker.execute_command([sys.executable, "-c", "print('must not run')"],
                                            request_id="early")
            self.assertTrue(result["cancelled"])
            self.assertFalse(result["success"])

    @unittest.skipIf(os.name == "nt", "Windows broker execution is deliberately fail-closed")
    def test_command_output_quota_is_combined_across_streams(self):
        with tempfile.TemporaryDirectory() as d:
            broker = ExecutionBroker(BrokerPolicy(
                pathlib.Path(d), (pathlib.Path(sys.executable).name,),
                max_output_bytes=100,
                write_token_digest=hashlib.sha256(b"x").hexdigest()))
            broker.unlock_writes("x")
            result = broker.execute_command([sys.executable, "-c",
                "import sys; sys.stdout.write('a'*80); sys.stderr.write('b'*80)"])
            self.assertTrue(result["output_limited"])
            self.assertLessEqual(len(result["stdout"].encode()) +
                                 len(result["stderr"].encode()), 100)


if __name__ == "__main__":
    unittest.main()
