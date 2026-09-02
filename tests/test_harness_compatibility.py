"""Portable harness compatibility fixtures; these do not certify real hosts."""
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fable_mode.adapters import (
    HOST_IDENTITY_REGISTRY, GenericMCPHostAdapter, canonical_host_id,
    detect_hosts,
)
from fable_v2.execution_broker import BrokerPolicy, ExecutionBroker, serve


class HarnessCompatibilityTests(unittest.TestCase):
    def test_canonical_host_aliases_and_fixture_configs(self):
        self.assertEqual(canonical_host_id("claude"), "claude-code")
        self.assertEqual(canonical_host_id("claude-code"), "claude-code")
        self.assertEqual(canonical_host_id("agy"), "antigravity")
        self.assertEqual(set(HOST_IDENTITY_REGISTRY), {"claude-code", "codex", "antigravity"})
        root = pathlib.Path(__file__).parent / "fixtures" / "hosts"
        for name in ("claude", "codex", "antigravity"):
            data = json.loads((root / f"{name}-config.json").read_text())
            self.assertIsInstance(data["mcpServers"], dict)

    def test_discovery_pins_documented_machine_readable_listing(self):
        exe = pathlib.Path(sys.executable)
        with patch("fable_mode.adapters._which", return_value=exe), \
             patch("fable_mode.adapters._run_probe", return_value=(0, "ok", "", False)):
            hosts = detect_hosts()
        self.assertEqual(hosts["claude"].canonical_name, "claude-code")
        self.assertEqual(HOST_IDENTITY_REGISTRY["codex"].list_argv[-1], "--json")

    def test_generic_mcp_surface_and_receipt(self):
        adapter = GenericMCPHostAdapter()
        self.assertEqual(adapter.initialize()["method"], "initialize")
        self.assertEqual(adapter.route_tool("tools" )["method"], "tools/call")
        receipt = adapter.receipt(tool_input={"x": 1}, tool_output={"ok": True}, success=True)
        self.assertTrue(receipt.success)

    def test_jsonrpc_notification_schema_and_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = ExecutionBroker(BrokerPolicy(pathlib.Path(tmp), allowed_executables=(pathlib.Path(sys.executable).name,)))
            output = io.StringIO()
            payload = (
                json.dumps({"jsonrpc": "2.0", "id": 6, "method": "initialize",
                            "params": {"protocolVersion": "2024-11-05"}}) + "\n"
                + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                + json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}) + "\n"
                + json.dumps({"jsonrpc": "2.0", "id": 8, "method": "not-a-method"}) + "\n"
            )
            import fable_v2.execution_broker as module
            with patch.object(module.sys, "stdin", io.StringIO(payload)), patch.object(module.sys, "stdout", output):
                serve(broker)
            responses = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(responses), 3)
            self.assertEqual(responses[0]["id"], 6)
            self.assertEqual(responses[0]["result"]["protocolVersion"], "2024-11-05")
            self.assertEqual(responses[1]["id"], 7)
            self.assertIn("tools", responses[1]["result"])
            self.assertIsInstance(responses[2]["error"], dict)
            self.assertEqual(responses[2]["error"]["code"], -32601)

    def test_request_id_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = ExecutionBroker(BrokerPolicy(pathlib.Path(tmp), allowed_executables=(pathlib.Path(sys.executable).name,), write_token_digest=hashlib.sha256(b"x").hexdigest()))
            broker.unlock_writes("x")
            result = []
            worker = threading.Thread(target=lambda: result.append(broker.handle({
                "action": "execute_command", "request_id": "run-1",
                "command": [sys.executable, "-c", "import time; time.sleep(3)"],
                "timeout_seconds": 10,
            })))
            worker.start(); time.sleep(.1)
            self.assertTrue(broker.handle({"action": "cancel", "request_id": "run-1"})["cancelled"])
            worker.join(5)
            self.assertTrue(result and result[0]["cancelled"])
            self.assertEqual(result[0]["request_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
