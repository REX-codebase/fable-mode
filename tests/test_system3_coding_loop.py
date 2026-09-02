"""Adversarial and end-to-end coverage for the receipt-bound System 3 coding loop."""
import math
import unittest

from fable_v2 import (Candidate, Evidence, FunctionVerifier, TaskSpec,
                      ToolReceipt, VerificationPolicy, new_run)
from fable_v2.protocol import Outcome


class System3CodingLoopTests(unittest.TestCase):
    def setUp(self):
        task = TaskSpec(
            "loop", "repair code", definition_of_done=("tests pass",),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
            ),
        )
        # Legacy verifier fixture; strict claim-gated runs use the explicit
        # integration tests in test_intelligent_verifier_integration.py.
        self.run = new_run("loop-session", task, compatibility_mode=True)
        receipt = ToolReceipt.from_result(
            receipt_id="tests-receipt", session_id="loop-session",
            capability="run_tests", tool_name="pytest", tool_input="tests",
            tool_output={"passed": True, "count": 3}, success=True,
            trust_boundary="host",
        )
        self.run.record_receipt(receipt)
        self.run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="tests-evidence", claim="tests ran",
            kind="test-result", source="pytest",
        ))
        self.run.register_candidate(Candidate(
            "candidate", "loop-session", "small patch", {"diff": "..."},
            (receipt.receipt_id,), ("tests-evidence",),
        ))

    def test_end_to_end_receipt_bound_loop_and_finalization(self):
        self.run.observe_system3("candidate", {"before": "failing test"})
        prediction = self.run.predict_system3(
            "candidate", "run_tests", {"passed": True, "count": 3}, 0.8,
            "falsified when the test count changes or any test fails",
        )
        self.run.act_system3("candidate", prediction.prediction_id)
        outcome = self.run.record_system3_outcome(
            "candidate", prediction.prediction_id, "tests-receipt",
        )
        update = self.run.update_system3("candidate", outcome.outcome_id)
        self.assertEqual(update["prediction_error"], 0.0)
        self.assertEqual(update["belief_revision"]["posterior_confidence"], 0.8)
        self.run.execute_verifier(FunctionVerifier(
            "tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("tests-evidence",),
        ), "candidate")
        self.run.finalize("candidate")

    def test_action_without_prediction_and_update_without_outcome_rejected(self):
        self.run.observe_system3("candidate", {"before": "unknown"})
        with self.assertRaises(PermissionError):
            self.run.act_system3("candidate", "missing-prediction")
        self.run.predict_system3(
            "candidate", "run_tests", {"passed": True}, 0.5,
            "falsified when the receipt says passed is false",
        )
        with self.assertRaises(PermissionError):
            self.run.update_system3("candidate")

    def test_forged_outcome_boilerplate_and_nonfinite_are_rejected(self):
        self.run.observe_system3("candidate", {"before": "unknown"})
        with self.assertRaises(ValueError):
            self.run.predict_system3("candidate", "run_tests", "ok", .5, "fails on nonzero exit")
        with self.assertRaises(ValueError):
            self.run.predict_system3("candidate", "run_tests", {"passed": True}, math.inf,
                                    "falsified on failed test")
        prediction = self.run.predict_system3(
            "candidate", "run_tests", {"passed": True}, .5,
            "falsified on failed test",
        )
        self.run.act_system3("candidate", prediction.prediction_id)
        with self.assertRaises(PermissionError):
            self.run.record_system3_outcome(
                "candidate", prediction.prediction_id, "tests-receipt", {"passed": False},
            )
        with self.assertRaises(PermissionError):
            Outcome("o", "loop-session", "candidate", prediction.prediction_id,
                    "run_tests", "tests-receipt", {"passed": True}, success=True)

    def test_failed_or_self_minted_receipts_cannot_be_loop_outcomes(self):
        self.run.observe_system3("candidate", {"before": "unknown"})
        prediction = self.run.predict_system3(
            "candidate", "run_tests", {"passed": True, "count": 3}, .5,
            "falsified on failed test",
        )
        self.run.act_system3("candidate", prediction.prediction_id)
        failed = ToolReceipt.from_result(
            receipt_id="failed", session_id="loop-session", capability="run_tests",
            tool_name="pytest", tool_input="tests", tool_output={"passed": False},
            success=False, trust_boundary="host",
        )
        self.run.record_receipt(failed)
        with self.assertRaises(PermissionError):
            self.run.record_system3_outcome("candidate", prediction.prediction_id, "failed")
        self.run.record_receipt(ToolReceipt.from_result(
            receipt_id="self", session_id="loop-session", capability="run_tests",
            tool_name="pytest", tool_input="tests", tool_output={"passed": True},
            success=True,
        ))
        with self.assertRaises(PermissionError):
            self.run.record_system3_outcome("candidate", prediction.prediction_id, "self")

    def test_unsatisfied_event_temporal_projection_rejects_finalization(self):
        failed = ToolReceipt.from_result(
            receipt_id="late-failure", session_id="loop-session", capability="run_tests",
            tool_name="pytest", tool_input="tests", tool_output={"passed": False},
            success=False, trust_boundary="host",
        )
        self.run.record_receipt(failed)
        self.run.execute_verifier(FunctionVerifier(
            "tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("tests-evidence",),
        ), "candidate")
        with self.assertRaises(PermissionError):
            self.run.finalize("candidate")

    def test_loop_action_record_mutation_is_rejected_before_next_transition(self):
        self.run.observe_system3("candidate", {"before": "unknown"})
        prediction = self.run.predict_system3(
            "candidate", "run_tests", {"passed": True}, .5,
            "falsified on failed test",
        )
        action = self.run.act_system3("candidate", prediction.prediction_id)
        self.run.system3_actions[action["action_id"]]["action"] = "forged"
        with self.assertRaises(PermissionError):
            self.run.record_system3_outcome("candidate", prediction.prediction_id, "tests-receipt")

    def test_duplicate_predictions_and_empty_observations_rejected(self):
        with self.assertRaises(ValueError):
            self.run.observe_system3("candidate", {})
        self.run.observe_system3("candidate", {"before": "unknown"})
        kwargs = dict(action="run_tests", predicted_outcome={"passed": True},
                      confidence=.5, falsification_condition="fails on a failed test")
        first = self.run.predict_system3("candidate", **kwargs)
        with self.assertRaises(ValueError):
            self.run.predict_system3("candidate", **kwargs)
        self.assertEqual(first.observation_hash, first.observation_hash)


if __name__ == "__main__":
    unittest.main()
