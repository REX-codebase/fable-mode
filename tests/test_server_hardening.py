import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_engine.server import (
    CompositeFrame,
    FableCompress,
    FableSession,
    ACTIVE_SESSIONS,
    CANCEL_TOMBSTONE_TTL_SECONDS,
    MAX_CANCEL_REQUEST_ID_BYTES,
    MAX_CANCEL_TOMBSTONE_BYTES,
    MAX_CANCEL_TOMBSTONES,
    RequestCancellationRegistry,
    SESSIONS_DIR,
    _canonical_hash,
    main,
)


class ServerHardeningTests(unittest.TestCase):
    def _run(self, messages):
        output = io.StringIO()
        wire = "".join(json.dumps(message) + "\n" for message in messages)
        with patch("sys.stdin", io.StringIO(wire)), patch("sys.stdout", output):
            main()
        return [json.loads(line) for line in output.getvalue().splitlines() if line]

    def test_forged_evidence_cannot_satisfy_proven_gate(self):
        session = FableSession("hardening_%d" % int(time.time() * 1000000), "test", 1)
        output = {"passed": True}
        receipt = {
            "receipt_id": "receipt-%s" % session.session_id,
            "session_id": session.session_id,
            "capability": "run_tests",
            "tool_name": "pytest",
            "input_hash": "0" * 64,
            "output_hash": _canonical_hash(output),
            "success": True,
            "output": output,
        }
        session.register_host_receipt(receipt)
        forged = {"receipt_id": receipt["receipt_id"], "content": {"passed": False},
                  "content_hash": _canonical_hash({"passed": False})}
        with self.assertRaises(ValueError):
            session.log_epistemic_item("PROVEN", "tests pass", forged)
        # Legacy text remains readable for old clients but is not authority.
        session.log_epistemic_item("PROVEN", "legacy", "pytest output: 1 passed")
        self.assertEqual(session.get_telemetry()["cognitive_gates"]["proven_with_evidence"], 0)

    def test_notification_has_no_response(self):
        name = "notify_%d" % int(time.time() * 1000000)
        try:
            responses = self._run([
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "tools/call", "params": {
                    "name": "fable_session", "arguments": {
                        "action": "create_session", "session_name": name,
                        "objective": "notification", "time_budget_minutes": 1,
                    }}},
                {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
            ])
            self.assertEqual([item["id"] for item in responses], [1, 2])
        finally:
            ACTIVE_SESSIONS.pop(name, None)
            path = SESSIONS_DIR / (name + ".json")
            if path.exists():
                path.unlink()

    def test_invalid_action_is_structured_tool_failure(self):
        responses = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "fable_session", "arguments": {"action": 4}}},
        ])
        result = responses[1]["result"]
        self.assertTrue(result["isError"])
        self.assertTrue(result["structuredContent"]["error"])

    def test_initialize_state_and_version_negotiation(self):
        responses = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        ])
        self.assertEqual(responses[0]["error"]["code"], -32002)
        self.assertEqual(responses[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", responses[2]["result"])

    def test_scoped_cas_accepts_three_shards_and_session_flush(self):
        """Shard directories are layout, not quota objects."""
        with tempfile.TemporaryDirectory() as tmp:
            session = FableSession("cas_flush_%d" % int(time.time() * 1000000), "compression", 1,
                                   session_id="cas-flush-session")
            engine = FableCompress(Path(tmp), namespace=session.cas_namespace)
            refs = [engine.cas_store.put(value) for value in ("object one", "object two", "object three")]
            self.assertEqual(len(set(refs)), 3)
            self.assertEqual(engine.cas_store.quota_stats()["objects"], 3)
            self.assertEqual([engine.cas_store.get_text(ref) for ref in refs],
                             ["object one", "object two", "object three"])

            engine.accumulator.add("a" * 400)
            engine.accumulator.add("b" * 400)
            flushed = engine.accumulator.flush()
            self.assertEqual(len(flushed), 1)
            stats = engine.cas_store.quota_stats()
            self.assertEqual(stats["objects"], 4)
            frame = CompositeFrame.deserialize_json(engine.cas_store.get_text(flushed[0]))
            self.assertEqual(frame.items[0]["payload"], "a" * 400)
            self.assertEqual(frame.items[1]["payload"], "b" * 400)

    def test_v1_cancellation_registry_is_bounded_and_reaped(self):
        registry = RequestCancellationRegistry()
        with self.assertRaises(ValueError):
            registry.cancel("x" * (MAX_CANCEL_REQUEST_ID_BYTES + 1))

        with patch("fable_engine.server.MAX_CANCEL_TOMBSTONES", 2), \
             patch("fable_engine.server.MAX_CANCEL_TOMBSTONE_BYTES", 32):
            registry.cancel("first")
            registry.cancel("second")
            registry.cancel("third")
            self.assertLessEqual(len(registry._cancelled), 2)
            self.assertLessEqual(registry._cancelled_bytes, 32)

        registry.cancel("completed")
        self.assertTrue(registry.consume("completed"))
        self.assertFalse(registry.is_cancelled("completed"))

        ttl_registry = RequestCancellationRegistry()
        with patch("fable_engine.server.time.monotonic", return_value=10.0):
            ttl_registry.cancel("expired")
        with patch("fable_engine.server.time.monotonic",
                   return_value=10.0 + CANCEL_TOMBSTONE_TTL_SECONDS + 1):
            self.assertFalse(ttl_registry.is_cancelled("expired"))
        self.assertEqual(ttl_registry._cancelled_bytes, 0)
        self.assertLessEqual(registry._cancelled_bytes, MAX_CANCEL_TOMBSTONE_BYTES)

    def test_v1_cancellation_notification_is_one_shot(self):
        responses = self._run([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/cancelled",
             "params": {"requestId": 2}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "fable_session", "arguments": {"action": "list_sessions"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "fable_session", "arguments": {"action": "list_sessions"}}},
        ])
        self.assertEqual([item["id"] for item in responses], [1, 2, 2])
        self.assertEqual(responses[1]["error"]["code"], -32800)
        self.assertIn("result", responses[2])


if __name__ == "__main__":
    unittest.main()
