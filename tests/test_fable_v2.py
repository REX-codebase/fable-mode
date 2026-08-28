import unittest

from fable_v2 import (
    Candidate,
    Evidence,
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
        self.evidence = Evidence(
            evidence_id="e-tests", session_id="session-001",
            claim="The regression tests pass", kind="test-result",
            source="pytest: tests", receipt_id="r-tests", content_hash="abc",
            verified=True,
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
        self.assertEqual(self.run.successful_capabilities(), {"inspect_files", "run_tests"})

    def test_direct_model_supplied_verification_is_rejected(self):
        forged = VerificationResult("v", "session-001", "candidate-001", "model", True)
        with self.assertRaises(PermissionError):
            self.run.record_verification(forged)
        with self.assertRaises(PermissionError):
            self.run.finalize("candidate-001")

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
        run.attach_evidence(Evidence(
            "e", "session-002", "inspection completed", "inspection", "grep",
            "r", "hash", verified=True,
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
            self.run.attach_evidence(Evidence(
                "e-failed", "session-001", "it passed", "test-result", "pytest",
                "r-failed", "hash",
            ))

    def test_untrusted_verifier_cannot_finalize(self):
        verifier = FunctionVerifier(
            "untrusted", lambda candidate: (True, ("claimed",), 1.0), trusted=False
        )
        with self.assertRaises(PermissionError):
            self.run.execute_verifier(verifier, "candidate-001")

    def test_verifier_function_is_composable(self):
        verifier = FunctionVerifier("always-pass", lambda candidate: (True, ["ok"], 1.0))
        result = verifier.verify(self.candidate)
        self.assertTrue(result.passed)
        self.assertEqual(result.verifier, "always-pass")

    def test_host_profiles_are_conservative_and_normalize_aliases(self):
        profile = get_profile("antigravity")
        self.assertTrue(profile.supports("run_tests"))
        self.assertEqual(profile.normalize("run_command"), "execute_command")
        unknown = get_profile("unknown-host")
        self.assertFalse(unknown.compatibility_report(["run_tests"])["compatible"])


if __name__ == "__main__":
    unittest.main()
