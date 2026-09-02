import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from fable_v2 import (
    Candidate, Evidence, FableRun, HMACProcessAttestationVerifier, ProcessAttestation, TaskSpec, ToolReceipt, VerificationPolicy,
    VerificationResult, new_run,
)
from fable_v2.execution_broker import BrokerPolicy, ExecutionBroker
from fable_v2.runtime import HMACCheckpointAuthenticator
from fable_v2.protocol import canonical_hash
from fable_v2.system3 import (
    ActiveInferenceEngine, DialecticalSynthesizer, MetaProofInducer,
    HyperbolicGeometryError, HyperbolicTreeEmbedder,
    ThesisCandidate, AntithesisCritique, create_default_architecture_pomdp,
)


class TrustSystem3RegressionTests(unittest.TestCase):
    def _run(self):
        task = TaskSpec(
            "trust", "trust", definition_of_done=("done",),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1, require_independent=False,
            ),
        )
        run = new_run("session", task, compatibility_mode=True)
        receipt = ToolReceipt.from_result(
            receipt_id="receipt", session_id="session", capability="check",
            tool_name="checker", tool_input={"x": 1}, tool_output={"ok": True},
            success=True,
        )
        run.record_receipt(receipt)
        evidence = Evidence.from_receipt(
            receipt, evidence_id="evidence", claim="checked", kind="check", source="checker"
        )
        run.attach_evidence(evidence)
        run.register_candidate(Candidate(
            "candidate", "session", "test", {"value": 1}, ("receipt",), ("evidence",)
        ))
        return run

    def test_finalization_rejects_mutated_dependency(self):
        run = self._run()
        # The map is intentionally mutable for compatibility; the finalization
        # commitment must detect mutation rather than silently trust it.
        run.candidates["candidate"].artifact["value"] = 99
        with self.assertRaises(PermissionError):
            run.finalize("candidate")

    def test_checkpoint_omits_runtime_secret_and_detects_truncation(self):
        run = self._run()
        payload = run.to_dict()
        self.assertNotIn("attestation_secret", payload)
        payload["events"] = payload["events"][:-1]
        with self.assertRaises(ValueError):
            FableRun.from_dict(payload)

    def test_terminal_checkpoint_requires_external_authentication(self):
        run = self._run()
        run.execute_verifier(__import__("fable_v2").FunctionVerifier(
            "det", lambda candidate: (True, ("ok",), 1.0), evidence_ids=("evidence",)
        ), "candidate")
        run.finalize("candidate")
        with self.assertRaises(PermissionError):
            FableRun.from_dict(run.to_dict())
        authenticator = HMACCheckpointAuthenticator(b"x" * 32)
        restored = FableRun.from_dict(run.to_dict(authenticator), authenticator)
        self.assertEqual(restored.state.value, "finalized")

    def test_hyperbolic_cycles_and_non_boolean_success_are_rejected(self):
        with self.assertRaises(HyperbolicGeometryError):
            HyperbolicTreeEmbedder().embed_hierarchy({"a": ["b"], "b": ["a"]}, root_id="a")
        with self.assertRaises(TypeError):
            ToolReceipt.from_result(receipt_id="bad", session_id="session", capability="x",
                tool_name="x", tool_input="x", tool_output="x", success=1)

    def test_process_attestation_fails_closed_without_external_verifier(self):
        run = self._run()
        c = run.candidates["candidate"]
        graph = run._candidate_graph_hash(c)
        result = VerificationResult(
            "v", "session", "candidate", "external", True,
            evidence_ids=("evidence",), verifier_class="deterministic",
            candidate_hash=canonical_hash(c.artifact), candidate_graph_hash=graph,
        )
        attestation = ProcessAttestation(
            "a", "session", "candidate", "external", "deterministic", True,
            result.candidate_hash, graph, ("evidence",), "receipt",
            {"path": "/trusted/checker", "sha256": "abc"}, {"path": "/workspace"},
        )
        with self.assertRaises(PermissionError):
            run.record_process_attested_verification(result, attestation, "material")

    def test_active_inference_has_observe_predict_act_update_and_persists(self):
        engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        cycle = engine.observe_predict_act_update("HIGH_THROUGHPUT_CLEAN")
        self.assertTrue(cycle["predictions"])
        self.assertTrue(cycle["action"])
        restored = ActiveInferenceEngine.from_dict(engine.to_dict())
        self.assertEqual(restored.last_observation, "HIGH_THROUGHPUT_CLEAN")
        self.assertEqual(restored.last_action, cycle["action"])
        self.assertEqual(restored.step_count, 1)

    def test_induced_axiom_is_not_proven_without_evidence(self):
        axiom = MetaProofInducer().induce_axioms_from_session([], [], {"phase_history": []})[0]
        self.assertNotEqual(axiom.status.value, "proven")
        ok, _, _ = MetaProofInducer().verify_axiom_empirically(axiom, [{}, {}, {}])
        self.assertFalse(ok)
        self.assertNotEqual(axiom.status.value, "proven")

    def test_dialectical_output_labels_unmeasured_claims(self):
        synthesis = DialecticalSynthesizer().synthesize(
            ThesisCandidate("t", "T", "proposal"),
            AntithesisCritique("a", "t", "critique"),
        )
        self.assertFalse(synthesis.convergence_achieved)
        self.assertIn("UNMEASURED", synthesis.pareto_improvement_claim)

    def test_broker_emits_structured_measured_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = ExecutionBroker(BrokerPolicy(
                workspace=Path(directory), allowed_executables=("python3",),
                write_token_digest=hashlib.sha256(b"unlock").hexdigest(),
            ))
            broker.unlock_writes("unlock")
            result = broker.execute_command(["python3", "-c", "print('ok')"], session_id="session")
            receipt = result["receipt"]
            self.assertEqual(receipt["session_id"], "session")
            self.assertEqual(receipt["input_hash"], result["input_hash"])
            self.assertIn("executable_identity", receipt)
            self.assertIn("workspace_identity", receipt)
            self.assertIn("cancellation_status", receipt)


if __name__ == "__main__":
    unittest.main()
