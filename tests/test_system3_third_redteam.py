"""Focused adversarial coverage for the third System 3 red-team findings."""
import copy
import math
import unittest

from fable_v2 import Candidate, Evidence, FunctionVerifier, TaskSpec, ToolReceipt, VerificationPolicy, new_run
from fable_v2.runtime import RunState
from fable_v2.system3 import (
    ActiveInferenceEngine, AxiomStatus, AntithesisCritique, DialecticalSynthesizer,
    MetaProofInducer, ThesisCandidate, create_default_architecture_pomdp,
)


class ThirdSystem3RedTeamTests(unittest.TestCase):
    def _run(self, diversity=False):
        task = TaskSpec(
            "third", "third", definition_of_done=("done",),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
                require_evidence_diversity=diversity, minimum_evidence_sources=2,
            ),
        )
        run = new_run("s", task, compatibility_mode=True)
        receipt = ToolReceipt.from_result(
            receipt_id="r", session_id="s", capability="check", tool_name="checker",
            tool_input="x", tool_output={"ok": True}, success=True,
        )
        run.record_receipt(receipt)
        run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="e", claim="checked", kind="check", source="label-one",
        ))
        return run, receipt

    def test_candidate_graph_requires_evidence_receipt_membership(self):
        run, receipt = self._run()
        other = ToolReceipt.from_result(
            receipt_id="r2", session_id="s", capability="check", tool_name="checker",
            tool_input="y", tool_output={"ok": True}, success=True,
        )
        run.record_receipt(other)
        run.attach_evidence(Evidence.from_receipt(
            other, evidence_id="e2", claim="checked", kind="check", source="label-two",
        ))
        with self.assertRaises(PermissionError):
            run.register_candidate(Candidate("c", "s", "a", "x", (receipt.receipt_id,), ("e2",)))

    def test_terminal_public_state_is_deeply_immutable(self):
        run, _ = self._run()
        run.register_candidate(Candidate("c", "s", "a", {"nested": {"x": 1}}, ("r",), ("e",)))
        run.execute_verifier(FunctionVerifier("v", lambda c: (True, ("ok",), 1), evidence_ids=("e",)), "c")
        run.finalize("c")
        with self.assertRaises(TypeError):
            run.candidates["c"].artifact["nested"]["x"] = 2
        with self.assertRaises(RuntimeError):
            run.state = RunState.ACTIVE

    def test_unsigned_restored_active_run_cannot_finalize(self):
        run, _ = self._run()
        run.register_candidate(Candidate("c", "s", "a", "x", ("r",), ("e",)))
        restored = type(run).from_dict(run.to_dict())
        restored.execute_verifier(FunctionVerifier("v", lambda c: (True, ("ok",), 1), evidence_ids=("e",)), "c")
        with self.assertRaises(PermissionError):
            restored.finalize("c")

    def test_diversity_ignores_source_labels_for_duplicate_output(self):
        run, receipt = self._run(diversity=True)
        # A second label over the same underlying receipt/output is not a source.
        run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="e2", claim="another label", kind="check", source="label-two",
        ))
        run.register_candidate(Candidate("c", "s", "a", "x", ("r",), ("e", "e2")))
        run.execute_verifier(FunctionVerifier("v", lambda c: (True, ("ok",), 1), evidence_ids=("e", "e2")), "c")
        with self.assertRaises(PermissionError):
            run.finalize("c")

    def test_event_map_reconciliation_rejects_injected_receipt(self):
        run, _ = self._run()
        run.receipts["injected"] = run.receipts["r"]
        with self.assertRaises(ValueError):
            run.validate_event_history()

    def test_proven_constructor_and_vacuous_predicate_rejected(self):
        with self.assertRaises(ValueError):
            from fable_v2.system3 import NeuroSymbolicAxiom
            NeuroSymbolicAxiom("a", "a", "acyclic", "a", status=AxiomStatus.PROVEN)
        run, _ = self._run()
        inducer = MetaProofInducer()
        axiom = inducer.induce_axioms_from_session([], [], {})[0]
        ok, _, _ = inducer.verify_axiom_empirically(axiom, [{}, {}, {}])
        self.assertFalse(ok)

    def test_measured_dialectic_requires_provenance_and_rejects_nonfinite(self):
        thesis = ThesisCandidate("t", "t", "t")
        critique = AntithesisCritique("c", "t", "c")
        with self.assertRaises(ValueError):
            DialecticalSynthesizer().synthesize(thesis, critique, measured_round_scores=[.5, .2])
        with self.assertRaises(ValueError):
            DialecticalSynthesizer().synthesize(thesis, critique, measured_round_scores=[math.nan])

    def test_active_restore_rejects_history_step_and_policy_tampering(self):
        engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        engine.observe_predict_act_update("HIGH_THROUGHPUT_CLEAN")
        payload = engine.to_dict()
        payload["step_count"] = 2
        with self.assertRaises(ValueError):
            ActiveInferenceEngine.from_dict(payload)
        payload = engine.to_dict()
        payload["history"][0]["predictions"] = []
        with self.assertRaises(ValueError):
            ActiveInferenceEngine.from_dict(payload)

    def test_cross_session_adaptation_is_explicitly_disabled(self):
        run, _ = self._run()
        self.assertFalse(run.status()["cross_session_adaptation"]["implemented"])
        self.assertFalse(run.to_dict()["cross_session_adaptation_implemented"])


if __name__ == "__main__":
    unittest.main()
