"""Focused regression tests for the strict MCP control-plane profile."""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from fable_engine.server import (
    ACTIVE_SESSIONS,
    SESSIONS_DIR,
    _canonical_hash,
    handle_fable_control_plane,
    register_host_verification,
    FableSession,
)


class StrictControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.name = "cp_test_%d" % int(time.time() * 1000000)
        self.profile = "strict-mcp-v1"
        self._created = False

    def tearDown(self):
        ACTIVE_SESSIONS.pop(self.name, None)
        (SESSIONS_DIR / (self.name + ".json")).unlink(missing_ok=True)

    def call(self, **kwargs):
        kwargs.setdefault("profile", self.profile)
        return handle_fable_control_plane(kwargs)

    def observe(self):
        result = self.call(action="observe", session_name=self.name,
                           objective="Validate strict control plane transitions",
                           observation="The repository was observed before mutation",
                           idempotency_key="observe-1")
        self.assertTrue(result["ok"])
        self._created = True
        return result

    def test_skip_observe_is_rejected(self):
        result = self.call(action="record_prediction", session_id="missing-session",
                           prediction="A substantive prediction", idempotency_key="predict-1")
        self.assertFalse(result["ok"])
        self.assertIn(result["error"]["code"], {"unknown_session", "session_binding_required"})

    def test_skip_prediction_and_boilerplate_are_rejected(self):
        observed = self.observe()
        sid = observed["session_id"]
        skipped = self.call(action="propose_action", session_id=sid,
                            action_name="write file", mutating=True,
                            prediction_id="missing", idempotency_key="action-1")
        self.assertFalse(skipped["ok"])
        self.assertEqual(skipped["error"]["code"], "prediction_required_before_action")
        boilerplate = self.call(action="record_prediction", session_id=sid,
                                prediction="TODO", idempotency_key="predict-1")
        self.assertFalse(boilerplate["ok"])
        self.assertEqual(boilerplate["error"]["code"], "invalid_arguments")

    def test_outcome_and_verification_require_host_attestation(self):
        observed = self.observe(); sid = observed["session_id"]
        predicted = self.call(action="record_prediction", session_id=sid,
                              prediction="The bounded write should produce a successful receipt",
                              idempotency_key="predict-1")
        proposed = self.call(action="propose_action", session_id=sid,
                             prediction_id=predicted["result"]["id"], action_name="write file",
                             mutating=True, arguments={}, idempotency_key="action-1")
        missing_receipt = self.call(action="record_outcome", session_id=sid,
                                    action_id=proposed["result"]["id"], outcome={"ok": True},
                                    receipt_id="not-host-registered", idempotency_key="outcome-1")
        self.assertFalse(missing_receipt["ok"])
        self.assertEqual(missing_receipt["error"]["code"], "host_receipt_required")

    def test_valid_flow_is_accepted_and_final_authorization_is_external(self):
        observed = self.observe(); sid = observed["session_id"]
        predicted = self.call(action="record_prediction", session_id=sid,
                              prediction="The bounded write should produce a successful receipt",
                              idempotency_key="predict-1")
        proposed = self.call(action="propose_action", session_id=sid,
                             prediction_id=predicted["result"]["id"], action_name="write file",
                             mutating=True, arguments={}, idempotency_key="action-1")
        session = ACTIVE_SESSIONS[self.name]
        output = {"ok": True, "changed": 1}
        receipt = {"receipt_id": "tool-receipt", "session_id": sid,
                   "capability": "broker", "tool_name": "write_file",
                   "input_hash": _canonical_hash({}), "output_hash": _canonical_hash(output),
                   "success": True, "output": output}
        session.register_host_receipt(receipt)
        outcome = self.call(action="record_outcome", session_id=sid,
                            action_id=proposed["result"]["id"], outcome=output,
                            receipt_id=receipt["receipt_id"], idempotency_key="outcome-1")
        verification = self.call(action="request_verification", session_id=sid,
                                 outcome_id=outcome["result"]["id"], checks=["receipt"],
                                 idempotency_key="verify-1")
        denied = self.call(action="finalize", session_id=sid,
                           verification_id=verification["result"]["id"],
                           final_authorized=True, idempotency_key="final-1")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "model_authorization_forbidden")
        verification_output = {"verified": True, "checks": ["receipt"]}
        verification_receipt = {"receipt_id": "verification-receipt", "session_id": sid,
                                "capability": "broker", "tool_name": "verify",
                                "input_hash": _canonical_hash({"verification_id": verification["result"]["id"]}),
                                "output_hash": _canonical_hash(verification_output),
                                "success": True, "output": verification_output}
        register_host_verification(self.name, verification["result"]["id"], verification_receipt)
        finalized = self.call(action="finalize", session_id=sid,
                              verification_id=verification["result"]["id"], idempotency_key="final-1")
        self.assertTrue(finalized["ok"])
        self.assertEqual(finalized["state"], "finalized")
        replay = self.call(action="finalize", session_id=sid,
                           verification_id=verification["result"]["id"], idempotency_key="final-1")
        self.assertTrue(replay["ok"])
        self.assertTrue(replay["idempotent_replay"])

    def test_capabilities_are_explicit_and_honest(self):
        result = handle_fable_control_plane({"action": "capabilities", "profile": self.profile})
        self.assertTrue(result["ok"])
        self.assertEqual(result["capabilities"]["profile"], self.profile)
        self.assertEqual(result["enforcement"]["native_tools"], "not_controlled_unless_routed_through_broker")

    def test_capabilities_reject_unknown_and_authorization_fields(self):
        unknown = handle_fable_control_plane({"action": "capabilities", "future": True})
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error"]["code"], "unknown_field")
        forbidden = handle_fable_control_plane({"action": "capabilities", "approval": True})
        self.assertFalse(forbidden["ok"])
        self.assertEqual(forbidden["error"]["code"], "model_authorization_forbidden")

    def test_canonical_and_strict_payloads_reject_non_finite_numbers(self):
        with self.assertRaises(ValueError):
            _canonical_hash({"value": float("nan")})
        result = self.call(action="observe", session_name=self.name,
                           objective="Validate strict control plane transitions",
                           observation={"value": float("inf")}, idempotency_key="observe-nan")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_arguments")

    def test_proposed_action_and_outcome_are_receipt_bound(self):
        observed = self.observe(); sid = observed["session_id"]
        predicted = self.call(action="record_prediction", session_id=sid,
                              prediction="The concrete operation should complete successfully", idempotency_key="predict-1")
        proposed = self.call(action="propose_action", session_id=sid,
                             prediction_id=predicted["result"]["id"], action_name="write_file",
                             capability="filesystem.write", mutating=True, arguments={"path": "out.txt"}, idempotency_key="action-1")
        session = ACTIVE_SESSIONS[self.name]
        output = {"ok": True}
        receipt = {"receipt_id": "bound-receipt", "session_id": sid,
                   "capability": "filesystem.write", "tool_name": "write_file",
                   "tool_input": {"path": "out.txt"}, "input_hash": _canonical_hash({"path": "out.txt"}),
                   "output_hash": _canonical_hash(output), "success": True, "output": output}
        session.register_host_receipt(receipt)
        wrong = self.call(action="record_outcome", session_id=sid, action_id=proposed["result"]["id"],
                          outcome={"ok": False}, receipt_id=receipt["receipt_id"], idempotency_key="outcome-wrong")
        self.assertFalse(wrong["ok"])
        self.assertEqual(wrong["error"]["code"], "outcome_receipt_binding_mismatch")
        good = self.call(action="record_outcome", session_id=sid, action_id=proposed["result"]["id"],
                         outcome=output, receipt_id=receipt["receipt_id"], idempotency_key="outcome-good")
        self.assertTrue(good["ok"])

    def test_verifier_receipt_must_bind_requested_outcome_and_checks(self):
        observed = self.observe(); sid = observed["session_id"]
        predicted = self.call(action="record_prediction", session_id=sid,
                              prediction="The concrete operation should complete successfully", idempotency_key="predict-1")
        proposed = self.call(action="propose_action", session_id=sid,
                             prediction_id=predicted["result"]["id"], action_name="write_file",
                             capability="filesystem.write", mutating=True, arguments={}, idempotency_key="action-1")
        session = ACTIVE_SESSIONS[self.name]; output = {"ok": True}
        receipt = {"receipt_id": "out-receipt", "session_id": sid, "capability": "filesystem.write",
                   "tool_name": "write_file", "input_hash": _canonical_hash({}),
                   "output_hash": _canonical_hash(output), "success": True, "output": output}
        session.register_host_receipt(receipt)
        outcome = self.call(action="record_outcome", session_id=sid, action_id=proposed["result"]["id"],
                            outcome=output, receipt_id=receipt["receipt_id"], idempotency_key="outcome-1")
        verification = self.call(action="request_verification", session_id=sid, outcome_id=outcome["result"]["id"],
                                 checks=["receipt", "schema"], idempotency_key="verify-1")
        vid = verification["result"]["id"]
        unrelated = {"receipt_id": "unrelated", "session_id": sid, "capability": "broker",
                     "tool_name": "run_command", "input_hash": _canonical_hash({"verification_id": vid}),
                     "output_hash": _canonical_hash({"verified": True, "checks": ["other"]}),
                     "success": True, "output": {"verified": True, "checks": ["other"]}}
        with self.assertRaises(ValueError):
            register_host_verification(self.name, vid, unrelated)

    def test_authority_deadline_is_sealed_after_construction(self):
        session = FableSession("sealed_deadline", "test objective", 1)
        with self.assertRaises(AttributeError):
            session._authority_deadline_monotonic = 0
        with self.assertRaises(AttributeError):
            session.time_budget_minutes = 0.1

    def test_generic_boilerplate_action_names_are_rejected(self):
        observed = self.observe(); sid = observed["session_id"]
        predicted = self.call(action="record_prediction", session_id=sid,
                              prediction="The concrete operation should complete successfully", idempotency_key="predict-1")
        result = self.call(action="propose_action", session_id=sid,
                           prediction_id=predicted["result"]["id"], action_name="perform the operation",
                           mutating=True, arguments={}, idempotency_key="action-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_action")


if __name__ == "__main__":
    unittest.main()
