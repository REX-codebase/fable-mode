"""Focused adversarial probes for the final integrity remediation."""
import math
import unittest

from fable_engine.server import _deadline_seconds
from fable_v2 import Candidate, Evidence, FunctionVerifier, TaskSpec, ToolReceipt, VerificationPolicy, new_run
from fable_v2.protocol import canonical_hash


class FinalIntegrityRedTeamTests(unittest.TestCase):
    def _run(self):
        task = TaskSpec(
            "integrity", "integrity objective", definition_of_done=("done",),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
            ),
        )
        run = new_run("integrity-session", task)
        receipt = ToolReceipt.from_result(
            receipt_id="receipt", session_id=run.session_id, capability="check",
            tool_name="checker", tool_input="input", tool_output={"ok": True}, success=True,
        )
        run.record_receipt(receipt)
        run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="evidence", claim="measured check", kind="check", source="source",
        ))
        run.register_candidate(Candidate(
            "candidate", run.session_id, "approach", {"answer": 1}, ("receipt",), ("evidence",),
        ))
        run.execute_verifier(FunctionVerifier(
            "verifier", lambda candidate: (True, ("checked",), 1), evidence_ids=("evidence",),
        ), "candidate")
        return run

    def test_revocation_event_survives_direct_map_clear(self):
        run = self._run()
        run.invalidate_verifier("verifier", "compromised")
        run.invalidated_verifiers.clear()
        self.assertEqual(run.passed_verifications("candidate"), [])
        with self.assertRaises(PermissionError):
            run.finalize("candidate")

    def test_each_candidate_keyed_telemetry_map_is_closed(self):
        for field_name in (
            "system3_free_energy", "system3_active_inference",
            "system3_kripke_invariants", "system3_hyperbolic_embeddings",
        ):
            run = self._run()
            getattr(run, field_name).pop("candidate")
            with self.assertRaises(PermissionError):
                run.finalize("candidate")

    def test_correctly_rehashed_fabricated_meta_event_has_no_backing(self):
        run = self._run()
        event = {
            "type": "system3_meta_cycle_completed", "at": "2026-01-01T00:00:00+00:00",
            "candidate_id": "candidate", "cycle_hash": canonical_hash({"fake": True}),
            "prev_hash": run.events[-1]["event_hash"],
        }
        event["event_hash"] = canonical_hash(event)
        run.events.append(event)
        with self.assertRaises(PermissionError):
            run.finalize("candidate")

    def test_recursive_nonfinite_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            Candidate("c", "s", "approach", {"nested": [{"value": math.nan}]})
        run = self._run()
        run.candidates["candidate"].metadata["caller"] = {"nested": math.inf}
        with self.assertRaises(PermissionError):
            run.finalize("candidate")

    def test_nested_legacy_deadline_is_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            _deadline_seconds({"_meta": {"request": {"deadline_seconds": 1}}})
        with self.assertRaises(ValueError):
            _deadline_seconds({"arguments": {"deadline": 1}})


if __name__ == "__main__":
    unittest.main()
