"""Focused adversarial coverage for the final System 3 trust boundary fixes."""
import copy
import math
import unittest

from fable_v2 import Candidate, Evidence, FunctionVerifier, TaskSpec, ToolReceipt, VerificationPolicy, VerificationDecision, new_run
from fable_v2.protocol import VerificationStatus, canonical_hash
from fable_v2.runtime import FableRun, HMACCheckpointAuthenticator
from fable_v2.system3 import ActiveInferenceEngine, AntithesisCritique, DialecticalSynthesizer, MetaProofInducer, ThesisCandidate, create_default_architecture_pomdp
from fable_v2.system3.dialectical import DialecticalMeasurement
from fable_v2.system3.induction import AxiomStatus


class FinalSystem3RedTeamTests(unittest.TestCase):
    def _run(self, diversity=False):
        task = TaskSpec("final", "final", definition_of_done=("done",),
                        verification_policy=VerificationPolicy(
                            required_verifier_classes=("deterministic", "independent"),
                            minimum_passing_verifiers=2, require_independent=True,
                            require_evidence_diversity=diversity,
                            minimum_evidence_sources=2))
        run = new_run("session", task)
        receipts = []
        for n, output in ((1, {"ok": True}), (2, {"ok": False})):
            receipt = ToolReceipt.from_result(
                receipt_id=f"r{n}", session_id="session", capability="check",
                tool_name="checker", tool_input=n, tool_output=output, success=True,
                executable_identity={"digest": "same-executable"},
                workspace_identity={"digest": "same-workspace"})
            run.record_receipt(receipt)
            run.attach_evidence(Evidence.from_receipt(
                receipt, evidence_id=f"e{n}", claim="checked", kind="check", source=f"label-{n}"))
            receipts.append(receipt)
        run.register_candidate(Candidate("c", "session", "a", {"x": 1}, ("r1", "r2"), ("e1", "e2")))
        return run, receipts

    def _strict_checkpoint_run(self):
        task = TaskSpec(
            "checkpoint", "done", definition_of_done=("done",),
            metadata={"require_system3_loop": True},
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
            ),
        )
        run = new_run("checkpoint-session", task)
        receipt = ToolReceipt.from_result(
            receipt_id="receipt", session_id=run.session_id, capability="check",
            tool_name="checker", tool_input="input", tool_output={"ok": True},
            success=True, trust_boundary="host",
        )
        run.record_receipt(receipt, authenticated_boundary=lambda item: True)
        run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="evidence", claim="done", kind="check", source="checker",
        ))
        candidate = Candidate("candidate", run.session_id, "approach", "artifact",
                              (receipt.receipt_id,), ("evidence",))
        run.register_candidate(candidate)
        graph = run._claim_graph(candidate.candidate_id)
        verifier = FunctionVerifier(
            "checker", lambda _: VerificationDecision(
                VerificationStatus.PASS, claim_ids=graph.claim_ids,
                evidence_ids=("evidence",), provenance_ids=("evidence",),
            ), claim_ids=graph.claim_ids, evidence_ids=("evidence",),
            provenance_ids=("evidence",),
        )
        run.execute_verifier(verifier, candidate.candidate_id)
        run.observe_system3(candidate.candidate_id, {"before": "check"})
        prediction = run.predict_system3(
            candidate.candidate_id, "check", {"ok": True}, .5, "fails when check is not ok",
        )
        run.act_system3(candidate.candidate_id, prediction.prediction_id)
        outcome = run.record_system3_outcome(
            candidate.candidate_id, prediction.prediction_id, receipt.receipt_id,
        )
        run.update_system3(candidate.candidate_id, outcome.outcome_id)
        return run

    def test_signed_strict_system3_active_checkpoint_round_trip(self):
        run = self._strict_checkpoint_run()
        authenticator = HMACCheckpointAuthenticator(b"checkpoint-key" * 2)
        payload = run.to_dict(authenticator)
        restored = FableRun.from_dict(payload, authenticator)
        self.assertEqual(restored._authenticated_receipt_ids, {"receipt"})
        restored.finalize("candidate")
        self.assertEqual(restored.state.value, "finalized")

    def test_signed_strict_system3_finalized_checkpoint_round_trip_and_tamper_rejection(self):
        run = self._strict_checkpoint_run()
        run.finalize("candidate")
        authenticator = HMACCheckpointAuthenticator(b"checkpoint-key" * 2)
        payload = run.to_dict(authenticator)
        restored = FableRun.from_dict(payload, authenticator)
        self.assertEqual(restored.state.value, "finalized")
        tampered = dict(payload)
        tampered["authenticated_receipt_ids"] = []
        with self.assertRaises(PermissionError):
            FableRun.from_dict(tampered, authenticator)
        # Authorization copied into an unsigned checkpoint is not trusted.
        unsigned = dict(payload)
        unsigned.pop("checkpoint_signature")
        with self.assertRaises(PermissionError):
            FableRun.from_dict(unsigned)

    def test_self_declared_independent_is_observable_but_not_trusted(self):
        run, _ = self._run()
        run.execute_verifier(FunctionVerifier("d", lambda c: (True, ("ok",), 1), evidence_ids=("e1",)), "c")
        run.execute_verifier(FunctionVerifier("i", lambda c: (True, ("ok",), 1), verifier_class="independent", independent=True, evidence_ids=("e1",)), "c")
        self.assertEqual(run.verifications["i:c"].metadata["independence_status"], "self_declared_untrusted")
        with self.assertRaises(PermissionError):
            run.finalize("c")

    def test_axiom_seal_and_empirical_input_requirements(self):
        inducer = MetaProofInducer()
        axiom = inducer.induce_axioms_from_session([], [], {})[0]
        axiom.status = AxiomStatus.PROVEN
        with self.assertRaises(PermissionError):
            inducer.formalize_to_proof_sketch(axiom)

    def test_measured_scores_must_match_evidence_or_be_typed(self):
        run, receipts = self._run()
        thesis, critique = ThesisCandidate("t", "t", "t"), AntithesisCritique("a", "t", "a")
        with self.assertRaises(ValueError):
            DialecticalSynthesizer().synthesize(thesis, critique, measured_round_scores=[.8, .2], measured_receipts=receipts, measured_evidence=[run.evidence["e1"]])
        with self.assertRaises(ValueError):
            DialecticalSynthesizer().synthesize(thesis, critique, measured_round_scores=[math.inf], measured_receipts=receipts, measured_evidence=list(run.evidence.values()))
        records = [DialecticalMeasurement(i, score, canonical_hash(score), f"r{i+1}", f"e{i+1}") for i, score in enumerate((.8, .2))]
        result = DialecticalSynthesizer().synthesize(thesis, critique, measured_round_scores=records, measured_receipts=receipts, measured_evidence=list(run.evidence.values()))
        self.assertTrue(result.metadata["measurement_provenance_resolved"])

    def test_diversity_counts_measured_producers_not_output_hashes(self):
        run, _ = self._run(diversity=True)
        run.register_candidate  # keep the candidate graph explicit
        run.execute_verifier(FunctionVerifier("d", lambda c: (True, ("ok",), 1), evidence_ids=("e1", "e2")), "c")
        with self.assertRaises(PermissionError):
            run.finalize("c")

    def test_active_restore_recomputes_metrics(self):
        engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        engine.observe_predict_act_update("HIGH_THROUGHPUT_CLEAN")
        payload = engine.to_dict()
        payload["history"][0]["update"]["complexity_kl"] += 1
        with self.assertRaises(ValueError):
            ActiveInferenceEngine.from_dict(payload)

    def test_active_engine_rejects_unbound_or_mutated_loop_inputs(self):
        engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        engine.observe("HIGH_THROUGHPUT_CLEAN")
        with self.assertRaises(PermissionError):
            engine.update()
        predictions = engine.predict()
        predictions[0].actions[0] = "NOT_AN_ACTION"
        with self.assertRaises((PermissionError, ValueError)):
            engine.act(predictions)
        # The update path also rejects a caller-mutated environment value.
        engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        engine.observe_predict_act_update("HIGH_THROUGHPUT_CLEAN")
        engine.last_observation = "CHECKSUM_FAIL"
        with self.assertRaises(PermissionError):
            engine.update()

    def test_system3_candidate_telemetry_is_revalidated(self):
        run, _ = self._run()
        run.candidates["c"].metadata["system3_free_energy"]["complexity_kl"] = 999
        run.execute_verifier(FunctionVerifier("d", lambda c: (True, ("ok",), 1), evidence_ids=("e1",)), "c")
        with self.assertRaises(PermissionError):
            run.finalize("c")


if __name__ == "__main__":
    unittest.main()
