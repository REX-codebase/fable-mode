import copy
import unittest
from concurrent.futures import ThreadPoolExecutor

from fable_v2 import (
    Candidate,
    Evidence,
    FableRun,
    FunctionVerifier,
    TaskSpec,
    ToolReceipt,
    VerificationPolicy,
    VerificationResult,
    get_profile,
    new_run,
)


class FableV2RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskSpec(
            task_id="coding-001",
            objective="Repair the failing feature",
            definition_of_done=("tests pass",),
            required_capabilities=("inspect_files", "run_tests"),
            required_evidence=("test-result",),
        )
        self.run = new_run("session-001", self.task)
        self.inspect = ToolReceipt.from_result(
            receipt_id="r-inspect", session_id="session-001",
            capability="inspect_files", tool_name="grep",
            tool_input={"query": "bug"}, tool_output={"matches": 2}, success=True,
        )
        self.tests = ToolReceipt.from_result(
            receipt_id="r-tests", session_id="session-001",
            capability="run_tests", tool_name="pytest",
            tool_input={"target": "tests"}, tool_output={"passed": True}, success=True,
        )
        self.run.record_receipt(self.inspect)
        self.run.record_receipt(self.tests)
        self.evidence = Evidence.from_receipt(
            self.tests,
            evidence_id="e-tests",
            claim="The regression tests pass",
            kind="test-result",
            source="pytest: tests",
        )
        self.run.attach_evidence(self.evidence)
        self.candidate = Candidate(
            candidate_id="candidate-001", session_id="session-001",
            approach="minimal patch", artifact={"diff": "..."},
            receipt_ids=("r-inspect", "r-tests"), evidence_ids=("e-tests",),
        )
        self.run.register_candidate(self.candidate)

    def test_task_contract_requires_definition_of_done(self):
        with self.assertRaises(ValueError):
            TaskSpec(task_id="x", objective="y")

    def test_receipts_are_hashed_and_recorded(self):
        self.assertEqual(len(self.run.receipts), 2)
        self.assertNotEqual(self.inspect.input_hash, self.inspect.output_hash)
        self.assertTrue(self.evidence.integrity_bound)
        self.assertEqual(self.run.successful_capabilities(), {"inspect_files", "run_tests"})

    def test_direct_model_supplied_verification_is_rejected(self):
        forged = VerificationResult("v", "session-001", "candidate-001", "model", True)
        with self.assertRaises(PermissionError):
            self.run.record_verification(forged)
        with self.assertRaises(PermissionError):
            self.run.finalize("candidate-001")

    def test_required_capabilities_are_candidate_scoped(self):
        task = TaskSpec(
            task_id="scoped-capabilities", objective="x", definition_of_done=("done",),
            required_capabilities=("inspect_files", "run_tests"),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1,
                require_independent=False,
            ),
        )
        run = new_run("session-scoped", task)
        inspect = ToolReceipt.from_result(
            receipt_id="r-scope-inspect", session_id="session-scoped",
            capability="inspect_files", tool_name="grep", tool_input="x",
            tool_output="inspection", success=True,
        )
        tests = ToolReceipt.from_result(
            receipt_id="r-scope-tests", session_id="session-scoped",
            capability="run_tests", tool_name="pytest", tool_input="x",
            tool_output="tests", success=True,
        )
        run.record_receipt(inspect)
        run.record_receipt(tests)
        run.register_candidate(Candidate(
            "inspect-only", "session-scoped", "inspection", "a", (inspect.receipt_id,)
        ))
        run.register_candidate(Candidate(
            "tests-only", "session-scoped", "tests", "b", (tests.receipt_id,)
        ))
        self.assertEqual(run.successful_capabilities(), {"inspect_files", "run_tests"})
        self.assertIn("run_tests", " ".join(run.missing_requirements("inspect-only")))
        self.assertIn("inspect_files", " ".join(run.missing_requirements("tests-only")))

    def test_finalization_requires_every_declared_capability(self):
        task = TaskSpec(
            task_id="missing", objective="x", definition_of_done=("done",),
            required_capabilities=("inspect_files", "search_web"),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1,
                require_independent=False,
            ),
        )
        run = new_run("session-002", task)
        run.record_receipt(ToolReceipt.from_result(
            receipt_id="r", session_id="session-002", capability="inspect_files",
            tool_name="grep", tool_input="x", tool_output="y", success=True,
        ))
        run.attach_evidence(Evidence.from_receipt(
            run.receipts["r"],
            evidence_id="e", claim="inspection completed", kind="inspection",
            source="grep",
        ))
        candidate = Candidate("c", "session-002", "approach", "artifact", ("r",), ("e",))
        run.register_candidate(candidate)
        run.execute_verifier(FunctionVerifier(
            "tests", lambda candidate: (True, ("checked",), 1.0), evidence_ids=("e",)
        ), "c")
        with self.assertRaises(PermissionError) as error:
            run.finalize("c")
        self.assertIn("search_web", str(error.exception))

    def test_deterministic_verifier_must_run_before_independent(self):
        with self.assertRaises(PermissionError) as error:
            self.run.execute_verifier(FunctionVerifier(
                "independent-first", lambda candidate: (True, ("reviewed",), 1.0),
                verifier_class="independent", independent=True, evidence_ids=("e-tests",),
            ), "candidate-001")
        self.assertIn("after passing deterministic", str(error.exception))

    def test_policy_requires_independent_verifier_class(self):
        self.run.execute_verifier(FunctionVerifier(
            "deterministic-tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("e-tests",),
        ), "candidate-001")
        with self.assertRaises(PermissionError) as error:
            self.run.finalize("candidate-001")
        self.assertIn("independent", str(error.exception))

    def test_verified_candidate_can_finalize(self):
        self.run.execute_verifier(FunctionVerifier(
            "deterministic-tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("e-tests",),
        ), "candidate-001")
        self.run.execute_verifier(FunctionVerifier(
            "independent-review", lambda candidate: (True, ("review passed",), 1.0),
            verifier_class="independent", independent=True, evidence_ids=("e-tests",),
        ), "candidate-001")
        result = self.run.finalize("candidate-001")
        self.assertEqual(result.candidate_id, "candidate-001")
        self.assertEqual(self.run.state.value, "finalized")

    def test_failed_tool_cannot_anchor_evidence(self):
        failed = ToolReceipt.from_result(
            receipt_id="r-failed", session_id="session-001", capability="run_tests",
            tool_name="pytest", tool_input="x", tool_output="failure", success=False,
        )
        self.run.record_receipt(failed)
        with self.assertRaises(ValueError):
            Evidence.from_receipt(
                failed, evidence_id="e-failed", claim="it passed",
                kind="test-result", source="pytest",
            )

    def test_evidence_hash_must_match_actual_content(self):
        with self.assertRaises(ValueError):
            Evidence(
                "e-tampered", "session-001", "claim", "test-result", "pytest",
                "r-tests", "not-the-output-hash", source_output_hash=self.tests.output_hash,
                content=self.tests.output,
            )

    def test_in_process_verifier_cannot_claim_process_attestation(self):
        verifier = FunctionVerifier(
            "forged-boundary", lambda candidate: (True, ("claimed",), 1.0),
            trust_boundary="process_attested",
        )
        with self.assertRaises(PermissionError):
            self.run.execute_verifier(verifier, "candidate-001")

    def test_process_attested_policy_rejects_in_process_results(self):
        task = TaskSpec(
            task_id="isolated", objective="x", definition_of_done=("done",),
            required_capabilities=("inspect_files",),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1,
                require_independent=False,
                minimum_trust_boundary="process_attested",
            ),
        )
        run = new_run("session-isolated", task)
        receipt = ToolReceipt.from_result(
            receipt_id="r-isolated", session_id="session-isolated",
            capability="inspect_files", tool_name="grep", tool_input="x",
            tool_output="y", success=True,
        )
        run.record_receipt(receipt)
        evidence = Evidence.from_receipt(
            receipt, evidence_id="e-isolated", claim="inspected", kind="inspection",
            source="grep",
        )
        run.attach_evidence(evidence)
        run.register_candidate(Candidate(
            "c-isolated", "session-isolated", "approach", "artifact",
            ("r-isolated",), ("e-isolated",),
        ))
        run.execute_verifier(FunctionVerifier(
            "local", lambda candidate: (True, ("checked",), 1.0),
            evidence_ids=("e-isolated",),
        ), "c-isolated")
        with self.assertRaises(PermissionError):
            run.finalize("c-isolated")

    def test_verifier_function_is_composable(self):
        verifier = FunctionVerifier("always-pass", lambda candidate: (True, ["ok"], 1.0))
        result = verifier.verify(self.candidate)
        self.assertTrue(result.passed)
        self.assertEqual(result.verifier, "always-pass")

    def test_verifier_cannot_return_a_result_for_another_candidate(self):
        class WrongCandidateVerifier:
            name = "wrong-candidate"
            verifier_class = "deterministic"
            independent = False
            trust_boundary = "in_process"

            def verify(self, candidate):
                return VerificationResult(
                    "wrong", candidate.session_id, "another-candidate", self.name, True,
                    evidence_ids=("e-tests",),
                )

        with self.assertRaises(ValueError):
            self.run.execute_verifier(WrongCandidateVerifier(), "candidate-001")

    def test_verifier_evidence_must_belong_to_candidate(self):
        candidate = Candidate(
            "candidate-002", "session-001", "second approach", "other artifact",
            ("r-inspect",), (),
        )
        self.run.register_candidate(candidate)
        with self.assertRaises(PermissionError):
            self.run.execute_verifier(FunctionVerifier(
                "wrong-evidence", lambda candidate: (True, ("checked",), 1.0),
                evidence_ids=("e-tests",),
            ), "candidate-002")

    def test_duplicate_or_contradictory_verification_is_rejected(self):
        verifier = FunctionVerifier(
            "single-use", lambda candidate: (True, ("checked",), 1.0),
            evidence_ids=("e-tests",),
        )
        self.run.execute_verifier(verifier, "candidate-001")
        with self.assertRaises(ValueError):
            self.run.execute_verifier(verifier, "candidate-001")
        with self.assertRaises(ValueError):
            self.run.execute_verifier(FunctionVerifier(
                "single-use", lambda candidate: (False, ("contradiction",), 0.0),
                evidence_ids=("e-tests",),
            ), "candidate-001")

    def test_finalization_rechecks_verifier_validity(self):
        self.run.execute_verifier(FunctionVerifier(
            "deterministic-tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("e-tests",),
        ), "candidate-001")
        self.run.execute_verifier(FunctionVerifier(
            "independent-review", lambda candidate: (True, ("review passed",), 1.0),
            verifier_class="independent", independent=True, evidence_ids=("e-tests",),
        ), "candidate-001")
        self.run.invalidate_verifier("independent-review", "calibration drift")
        with self.assertRaises(PermissionError) as error:
            self.run.finalize("candidate-001")
        self.assertIn("independent", str(error.exception))

    def test_malformed_or_reversed_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            ToolReceipt.from_result(
                receipt_id="bad-time", session_id="session-001", capability="x",
                tool_name="x", tool_input="x", tool_output="x", success=True,
                started_at="not-a-time", finished_at="not-a-time",
            )
        with self.assertRaises(ValueError):
            ToolReceipt.from_result(
                receipt_id="reversed", session_id="session-001", capability="x",
                tool_name="x", tool_input="x", tool_output="x", success=True,
                started_at="2026-08-28T12:00:00+00:00",
                finished_at="2026-08-28T11:00:00+00:00",
            )

    def test_mutable_payloads_are_snapshotted(self):
        output = {"passed": True}
        metadata = {"host": {"name": "test"}}
        receipt = ToolReceipt.from_result(
            receipt_id="snapshot", session_id="session-001", capability="x",
            tool_name="x", tool_input="x", tool_output=output, success=True,
            metadata=metadata,
        )
        output["passed"] = False
        metadata["host"]["name"] = "mutated"
        self.assertTrue(receipt.output["passed"])
        self.assertEqual(receipt.metadata["host"]["name"], "test")

        artifact = {"items": [1]}
        candidate = Candidate("snapshot-candidate", "session-001", "approach", artifact)
        self.run.register_candidate(candidate)
        artifact["items"].append(2)
        self.assertEqual(self.run.candidates["snapshot-candidate"].artifact, {"items": [1]})

    def test_run_serialization_round_trip(self):
        restored = FableRun.from_dict(self.run.to_dict())
        self.assertEqual(restored.status(), self.run.status())
        restored.validate_event_history()
        self.assertEqual(restored.evidence["e-tests"].content_hash, self.evidence.content_hash)

    def test_parallel_candidate_registration_is_safe(self):
        candidates = [
            Candidate(f"parallel-{i}", "session-001", "parallel approach", {"i": i})
            for i in range(32)
        ]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.run.register_candidate, candidates))
        self.assertEqual(len(self.run.candidates), 33)
        self.run.validate_event_history()

    def test_restored_verdict_is_checked_against_complete_attestation(self):
        self.run.execute_verifier(FunctionVerifier(
            "deterministic-tests", lambda candidate: (True, ("tests pass",), 1.0),
            evidence_ids=("e-tests",),
        ), "candidate-001")
        self.run.execute_verifier(FunctionVerifier(
            "independent-review", lambda candidate: (True, ("review passed",), 1.0),
            verifier_class="independent", independent=True, evidence_ids=("e-tests",),
        ), "candidate-001")
        payload = self.run.to_dict()
        self.assertEqual(FableRun.from_dict(payload).status()["verifications"], 2)
        mutations = {
            "passed": False,
            "reasons": ["tampered"],
            "evidence_ids": [],
            "score": 0.0,
            "independent": True,
            "inspected_candidate": False,
        }
        for field, value in mutations.items():
            tampered = copy.deepcopy(payload)
            tampered["verifications"][0][field] = value
            with self.assertRaises(PermissionError, msg=field):
                FableRun.from_dict(tampered)

    def test_tampered_event_history_is_rejected_on_restore(self):
        payload = self.run.to_dict()
        payload["events"][0]["type"] = "tampered"
        with self.assertRaises(ValueError):
            FableRun.from_dict(payload)

    def test_host_profiles_are_expected_until_probed(self):
        profile = get_profile("antigravity")
        self.assertFalse(profile.is_attested)
        self.assertTrue(profile.supports("run_tests"))
        self.assertFalse(profile.supports("run_tests", authoritative=True))
        self.assertEqual(profile.normalize("run_command"), "execute_command")
        self.assertFalse(profile.compatibility_report(["run_tests"])["compatible"])
        attested = profile.attest(["run_tests"])
        self.assertTrue(attested.is_attested)
        self.assertTrue(attested.compatibility_report(["run_tests"])["compatible"])
        unknown = get_profile("unknown-host")
        self.assertFalse(unknown.compatibility_report(["run_tests"])["compatible"])


if __name__ == "__main__":
    unittest.main()
