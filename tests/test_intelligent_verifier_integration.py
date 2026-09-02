"""Adversarial integration coverage for the strict intelligent-verifier gate."""
import unittest

from fable_v2 import Candidate, Evidence, FableRun, FunctionVerifier, TaskSpec, ToolReceipt, VerificationPolicy, new_run
from fable_v2.protocol import VerificationStatus
from fable_v2.verifiers import ClaimGraph, Counterexample, CounterexampleStore, ThreeValuedAdjudicator, VerificationDecision


class IntelligentVerifierIntegrationTests(unittest.TestCase):
    def _run(self, *, strict_system3=False, compatibility_mode=False):
        task = TaskSpec(
            "gate", "produce answer", definition_of_done=("answer is checked",),
            metadata={"require_system3_loop": strict_system3},
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
            ),
        )
        run = new_run("gate-session", task, compatibility_mode=compatibility_mode)
        receipt = ToolReceipt.from_result(
            receipt_id="receipt", session_id=run.session_id, capability="check",
            tool_name="checker", tool_input="in", tool_output={"ok": True}, success=True,
            trust_boundary="host",
        )
        run.record_receipt(receipt)
        run.attach_evidence(Evidence.from_receipt(
            receipt, evidence_id="evidence", claim="checked", kind="check", source="checker",
        ))
        candidate = Candidate("candidate", run.session_id, "approach", {"answer": 1},
                              ("receipt",), ("evidence",))
        run.register_candidate(candidate)
        return run, candidate, ClaimGraph.from_task(task, candidate)

    def test_default_finalization_rejects_uncovered_claims(self):
        run, _, _ = self._run()
        run.execute_verifier(FunctionVerifier("legacy-shaped", lambda _: (True, ("ok",), 1), evidence_ids=("evidence",)), "candidate")
        with self.assertRaises(PermissionError):
            run.finalize("candidate")

    def test_explicit_compatibility_mode_preserves_legacy_finalization(self):
        run, candidate, _ = self._run(compatibility_mode=True)
        # This is an explicit mode, not inference from omitted claim IDs.
        run.execute_verifier(FunctionVerifier("legacy-shaped", lambda _: (True, ("ok",), 1), evidence_ids=("evidence",)), candidate.candidate_id)
        self.assertEqual(run.finalize(candidate.candidate_id).candidate_id, candidate.candidate_id)

    def test_counterexample_forces_fail_even_with_pass(self):
        _, candidate, graph = self._run()
        result = VerificationDecision(VerificationStatus.PASS, claim_ids=graph.claim_ids,
                                      evidence_ids=("evidence",), provenance_ids=("receipt",),
                                      counterexample_ids=("ce",))
        from fable_v2.verifiers import FunctionVerifier
        result = FunctionVerifier("check", lambda _: result, claim_ids=graph.claim_ids).verify(candidate)
        adjudication = ThreeValuedAdjudicator(require_independent=False).adjudicate(
            graph, (result,), CounterexampleStore([Counterexample("ce", graph.claim_ids, {"bad": True}, "bad")]))
        self.assertEqual(adjudication.status, VerificationStatus.FAIL)
        self.assertFalse(adjudication.finalizable)

    def test_policy_quorum_deduplicates_verifier_ids(self):
        _, candidate, graph = self._run()
        def make(status, vid):
            return FunctionVerifier(vid, lambda _: VerificationDecision(status, claim_ids=graph.claim_ids,
                evidence_ids=("evidence",), provenance_ids=("receipt",)), claim_ids=graph.claim_ids).verify(candidate)
        first = make(VerificationStatus.PASS, "same")
        duplicate = make(VerificationStatus.PASS, "same")
        policy = VerificationPolicy(required_verifier_classes=("deterministic",), minimum_passing_verifiers=2, require_independent=False)
        adjudication = ThreeValuedAdjudicator(policy=policy, require_independent=False).adjudicate(graph, (first, duplicate), policy=policy)
        self.assertFalse(adjudication.finalizable)
        self.assertTrue(any("2 passing" in reason for reason in adjudication.reasons))

    def test_strict_system3_rejects_self_minted_host_receipt(self):
        run, _, _ = self._run(strict_system3=True)
        run.observe_system3("candidate", {"before": "unknown"})
        prediction = run.predict_system3("candidate", "check", {"ok": True}, .5, "fails when ok is false")
        run.act_system3("candidate", prediction.prediction_id)
        with self.assertRaises(PermissionError):
            run.record_system3_outcome("candidate", prediction.prediction_id, "receipt")


if __name__ == "__main__":
    unittest.main()
