import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

from fable_engine.server import (
    FableCASStore, FableCASError, FableSession, AdaptiveChunkAccumulator,
    _cas_namespace_for_session,
)
from fable_mode.adapters import Host, RegistrationError, detect_hosts, register_hosts
from fable_v2 import BrokerPolicy, ExecutionBroker
from fable_v2.execution_broker import serve, MAX_CANCEL_REQUEST_ID_BYTES


class ThirdRedTeamTransportTests(unittest.TestCase):
    def test_persisted_session_filename_and_namespace_are_bound(self):
        session = FableSession("bound", "objective", 1, session_id="bound-id")
        payload = session.to_dict()
        with self.assertRaises(ValueError):
            FableSession.from_dict(dict(payload, session_name="other"), expected_name="bound")
        with self.assertRaises(ValueError):
            FableSession.from_dict(dict(payload, cas_namespace="s_wrong"), expected_name="bound")
        restored = FableSession.from_dict(payload, expected_name="bound",
                                          expected_namespace=_cas_namespace_for_session("bound-id"))
        self.assertEqual(restored.cas_namespace, payload["cas_namespace"])

    def test_cas_quota_is_shared_by_store_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = FableCASStore(tmp, namespace="shared", max_namespace_bytes=4, max_namespace_objects=1)
            b = FableCASStore(tmp, namespace="shared", max_namespace_bytes=4, max_namespace_objects=1)
            a.put(b"1234")
            with self.assertRaises(FableCASError):
                b.put(b"5678")

    def test_accumulator_charges_metadata_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FableCASStore(tmp)
            acc = AdaptiveChunkAccumulator(store, min_frame_size=1024)
            # Metadata is bounded and charged even when the payload is tiny.
            with self.assertRaises(FableCASError):
                acc.add("x", {"metadata": "m" * (512 * 1024 + 1)})
            stats = acc.get_stats()
            self.assertEqual(stats["currently_buffered_metadata_bytes"], 0)

    def test_cancel_ids_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = ExecutionBroker(BrokerPolicy(pathlib.Path(tmp), (pathlib.Path(sys.executable).name,)))
            with self.assertRaises(ValueError):
                broker.handle({"action": "cancel", "request_id": "x" * (MAX_CANCEL_REQUEST_ID_BYTES + 1)})

    def test_mcp_initialized_notification_cannot_replace_initialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = ExecutionBroker(BrokerPolicy(pathlib.Path(tmp), (pathlib.Path(sys.executable).name,)))
            output = io.StringIO()
            wire = (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n" +
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}) + "\n")
            import fable_v2.execution_broker as module
            with patch.object(module.sys, "stdin", io.StringIO(wire)), patch.object(module.sys, "stdout", output):
                serve(broker)
            response = json.loads(output.getvalue())
            self.assertEqual(response["error"]["code"], -32002)

    @unittest.skipIf(os.name == "nt", "shebang test uses POSIX executable semantics")
    def test_locked_broker_rejects_script_even_with_unpinned_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            script = root / "runner"
            script.write_text("#!/bin/sh\nexit 0\n")
            script.chmod(0o700)
            broker = ExecutionBroker(BrokerPolicy(root, (str(script),)))
            with self.assertRaises(PermissionError):
                broker.execute_command([str(script)])

    def test_host_identity_is_revalidated_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            exe = root / "claude"
            exe.write_text("#!/bin/sh\n")
            exe.chmod(0o700)
            with patch("fable_mode.adapters._which", return_value=exe), \
                 patch("fable_mode.adapters._run_probe", return_value=(0, "ok", "", False)):
                host = detect_hosts()["claude"]
            exe.write_text("#!/bin/sh\nchanged\n")
            with self.assertRaises(RegistrationError):
                register_hosts({"claude": host}, ["fable"] , home=root)


if __name__ == "__main__":
    unittest.main()
