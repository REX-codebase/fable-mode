"""Unit and Integration Tests for Deep System 3 Integration in Fable Mode."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_v2.protocol import (
    Candidate,
    Evidence,
    TaskSpec,
    ToolReceipt,
    VerificationPolicy,
    VerificationResult,
    canonical_hash,
)
from fable_v2.runtime import FableRun, RunState, new_run
from fable_v2.adapters import HostCapabilities
from fable_v2.execution_broker import ExecutionBroker, BrokerPolicy
from fable_engine.server import (
    DelegationContractCompiler,
    FableSession,
    handle_fable_session,
)


class MockFailingVerifier:
    name = "mock_failing_verifier"
    verifier_class = "deterministic"
    independent = False
    trust_boundary = "in_process"

    def verify(self, candidate: Candidate) -> VerificationResult:
        return VerificationResult(
            verification_id=f"v_fail_{candidate.candidate_id}",
            session_id=candidate.session_id,
            candidate_id=candidate.candidate_id,
            verifier="mock_failing_verifier",
            passed=False,
            reasons=("AssertionError: expected 42 but got 0", "Timeout in unit test"),
            trust_boundary="in_process",
        )


class MockPassingVerifier:
    name = "mock_passing_verifier"
    verifier_class = "deterministic"
    independent = False
    trust_boundary = "in_process"

    def verify(self, candidate: Candidate) -> VerificationResult:
        return VerificationResult(
            verification_id=f"v_pass_{candidate.candidate_id}",
            session_id=candidate.session_id,
            candidate_id=candidate.candidate_id,
            verifier="mock_passing_verifier",
            passed=True,
            reasons=(),
            trust_boundary="in_process",
        )


class TestSystem3RuntimeDeepIntegration(unittest.TestCase):
    """Test System 3 integration in fable_v2/runtime.py."""

    def setUp(self):
        self.task = TaskSpec(
            task_id="task_deep_sys3_001",
            objective="Implement System 3 deep integration with mathematical bounds",
            required_capabilities=("read_file", "write_file"),
            required_evidence=("file_check",),
            definition_of_done=("Pass all unit tests", "Zero invariant violations"),
            verification_policy=VerificationPolicy(
                required_verifier_classes=("deterministic",),
                minimum_passing_verifiers=1,
            ),
        )
        self.run = new_run(session_id="session_sys3_test", task=self.task)

    def test_candidate_registration_evaluates_system3(self):
        """Candidate registration must evaluate Free Energy F, Kripke AG(safe), and Hyperbolic embeddings."""
        r1 = ToolReceipt.from_result(
            receipt_id="rec_1",
            session_id="session_sys3_test",
            capability="read_file",
            tool_name="read_file",
            tool_input={"path": "test.txt"},
            tool_output="content",
            success=True,
        )
        r2 = ToolReceipt.from_result(
            receipt_id="rec_2",
            session_id="session_sys3_test",
            capability="write_file",
            tool_name="write_file",
            tool_input={"path": "out.txt"},
            tool_output="ok",
            success=True,
        )
        self.run.record_receipt(r1)
        self.run.record_receipt(r2)

        ev = Evidence.from_receipt(
            receipt=r1,
            evidence_id="ev_1",
            claim="File content matches expectation",
            kind="file_check",
            source="test_runner",
        )
        self.run.attach_evidence(ev)

        cand = Candidate(
            candidate_id="cand_sys3_01",
            session_id="session_sys3_test",
            approach="system3_pareto_architecture",
            artifact={"title": "System 3 Core Implementation", "version": "1.0"},
            receipt_ids=("rec_1", "rec_2"),
            evidence_ids=("ev_1",),
        )
        self.run.register_candidate(cand)

        stored = self.run.candidates["cand_sys3_01"]
        # Check Free Energy F
        self.assertIn("system3_free_energy", stored.metadata)
        fe = stored.metadata["system3_free_energy"]
        self.assertIn("variational_free_energy_f", fe)
        self.assertIn("complexity_kl", fe)
        self.assertIn("accuracy_log_likelihood", fe)

        # Check Kripke Invariants
        self.assertIn("system3_kripke", stored.metadata)
        kripke = stored.metadata["system3_kripke"]
        self.assertEqual(kripke["formula"], "AG(safe)")
        self.assertTrue(kripke["is_satisfied"])

        # Check Hyperbolic Tree Embedding
        self.assertIn("system3_hyperbolic", stored.metadata)
        hyp = stored.metadata["system3_hyperbolic"]
        self.assertEqual(hyp["root_id"], "cand_sys3_01")
        self.assertGreater(hyp["total_nodes"], 0)

    def test_verification_failure_triggers_triz_repair(self):
        """Verifier failure must automatically synthesize TRIZ repair recommendations and attach to candidate."""
        r1 = ToolReceipt.from_result(
            receipt_id="rec_1",
            session_id="session_sys3_test",
            capability="read_file",
            tool_name="read_file",
            tool_input={"path": "test.txt"},
            tool_output="content",
            success=True,
        )
        self.run.record_receipt(r1)
        ev = Evidence.from_receipt(
            receipt=r1,
            evidence_id="ev_1",
            claim="File test ok",
            kind="file_check",
            source="test_runner",
        )
        self.run.attach_evidence(ev)

        cand = Candidate(
            candidate_id="cand_failing_01",
            session_id="session_sys3_test",
            approach="failing_architecture_candidate",
            artifact={"title": "Failing Microservice"},
            receipt_ids=("rec_1",),
            evidence_ids=("ev_1",),
        )
        self.run.register_candidate(cand)

        verifier = MockFailingVerifier()
        result = self.run.execute_verifier(verifier, "cand_failing_01")
        self.assertFalse(result.passed)

        # Verify TRIZ recommendations were generated and stored
        stored = self.run.candidates["cand_failing_01"]
        self.assertIn("triz_repair_recommendation", stored.metadata)
        triz_rec = stored.metadata["triz_repair_recommendation"]
        self.assertEqual(triz_rec["candidate_id"], "cand_failing_01")
        self.assertIn("synthesized_architecture", triz_rec)
        self.assertIn("recommendations", triz_rec)
        self.assertGreater(len(triz_rec["recommendations"]), 0)
        self.assertEqual(len(self.run.triz_repair_recommendations), 1)

    def test_run_system3_meta_cycle(self):
        """run_system3_meta_cycle must execute full reflection and return structured dictionary."""
        r1 = ToolReceipt.from_result(
            receipt_id="rec_1",
            session_id="session_sys3_test",
            capability="read_file",
            tool_name="read_file",
            tool_input={"path": "test.txt"},
            tool_output="content",
            success=True,
        )
        self.run.record_receipt(r1)
        cand = Candidate(
            candidate_id="cand_meta_01",
            session_id="session_sys3_test",
            approach="meta_cycle_candidate",
            artifact={"title": "Meta Cycle Candidate"},
            receipt_ids=("rec_1",),
            evidence_ids=(),
        )
        self.run.register_candidate(cand)

        meta_report = self.run.run_system3_meta_cycle("cand_meta_01")
        self.assertIn("free_energy", meta_report)
        self.assertIn("kripke_invariants", meta_report)
        self.assertIn("hyperbolic_embedding", meta_report)
        self.assertIn("bias_findings", meta_report)
        self.assertIn("arbitration", meta_report)
        self.assertIn("dialectical_synthesis", meta_report)
        self.assertEqual(len(self.run.system3_meta_cycles), 1)

    def test_serialization_roundtrip_preserves_system3_fields(self):
        """to_dict and from_dict must preserve all System 3 state fields without loss."""
        r1 = ToolReceipt.from_result(
            receipt_id="rec_1",
            session_id="session_sys3_test",
            capability="read_file",
            tool_name="read_file",
            tool_input={"path": "test.txt"},
            tool_output="content",
            success=True,
        )
        self.run.record_receipt(r1)
        cand = Candidate(
            candidate_id="cand_serial_01",
            session_id="session_sys3_test",
            approach="serial_candidate",
            artifact={"title": "Serial Candidate"},
            receipt_ids=("rec_1",),
            evidence_ids=(),
        )
        self.run.register_candidate(cand)
        self.run.run_system3_meta_cycle("cand_serial_01")

        data = self.run.to_dict()
        self.assertIn("system3_free_energy", data)
        self.assertIn("system3_kripke_invariants", data)
        self.assertIn("system3_hyperbolic_embeddings", data)
        self.assertIn("system3_meta_cycles", data)
        self.assertIn("triz_repair_recommendations", data)

        restored = FableRun.from_dict(data)
        self.assertEqual(len(restored.system3_meta_cycles), 1)
        self.assertEqual(len(restored.system3_free_energy), 1)
        self.assertEqual(restored.system3_meta_cycles[0]["candidate_id"], "cand_serial_01")


class TestSystem3ServerDeepIntegration(unittest.TestCase):
    """Test System 3 integration in fable_engine/server.py."""

    def setUp(self):
        self.session = FableSession(
            session_name="test_sys3_session",
            objective="Evaluate System 3 Server Integration",
            time_budget_minutes=30.0,
        )

    def test_advance_phase_runs_system3_bias_and_free_energy(self):
        """advance_phase must run bias detection, update active Free Energy and Kripke safety."""
        tel = self.session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Explored 3 archetypes")
        self.assertIn("system3_cognitive_state", tel)
        cog = tel["system3_cognitive_state"]
        self.assertIn("free_energy_f", cog)
        self.assertIn("kripke_safety_invariant", cog)
        self.assertIn("active_biases_count", cog)
        self.assertTrue(cog["kripke_safety_verified"])
        self.assertEqual(len(self.session.system3_active_inferences), 1)

    def test_log_refinement_cycle_updates_causal_dag_and_free_energy(self):
        """log_refinement_cycle must update active Free Energy and causal DAG nodes."""
        entry = self.session.log_refinement_cycle(
            refinement_type="architectural",
            focus_area="Memory Model",
            critique_or_bottleneck="Contention on spinlock",
            architectural_refinement="Converted to ticket lock",
            terminal_probe_results="Benchmark: 15% latency reduction PASS",
        )
        self.assertEqual(entry["cycle_number"], 1)
        self.assertIsNotNone(self.session.active_free_energy)
        self.assertEqual(len(self.session.system3_causal_graphs), 1)
        dag_dict = self.session.system3_causal_graphs[0]
        self.assertTrue(any(n["node_id"] == "refine_cycle_1" for n in dag_dict["nodes"]))

    def test_delegation_contract_compiler_injects_micro_scaffolds(self):
        """DelegationContractCompiler must inject formal mathematical micro-scaffolds for weak models."""
        compiler = DelegationContractCompiler()
        prompt = """
TargetFile: src/pipeline.py
InterfaceContract: def process_data(records: list[dict]) -> tuple[int, int]: ...
StrictConstraints: Zero-alloc in hot path; thread-safe under GIL.
VerificationCommand: pytest tests/test_pipeline.py -v
"""
        is_valid, errors, parsed = compiler.compile_and_validate(prompt)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
        self.assertIn("system3_micro_scaffold", parsed)
        scaffold = parsed["system3_micro_scaffold"]
        self.assertIn("SYSTEM 3 MICRO-SCAFFOLD", scaffold)
        self.assertIn("AG(\\text{safe})", scaffold)
        self.assertIn("do(\\cdot)", scaffold)
        self.assertIn("TRIZ Transcendent Resolution", scaffold)
        self.assertIn("Structured Output Regex Acceptance Constraint", scaffold)

    def test_handle_fable_session_advance_and_compile(self):
        """handle_fable_session must return rich System 3 telemetry in advance_phase and compile_delegation_contract."""
        init_res = handle_fable_session({
            "action": "create_session",
            "session_name": "sys3_rpc_session",
            "objective": "Test RPC Integration",
            "time_budget_minutes": 20.0,
        })
        self.assertIn("Fable Cognitive Session Initialized", init_res)

        adv_res = handle_fable_session({
            "action": "advance_phase",
            "session_name": "sys3_rpc_session",
            "next_phase": "Phase 2: Invariant Specification & Blueprint",
            "phase_summary": "Synthesized 3 distinct paradigms",
        })
        self.assertIn("System 3 Meta-Cognitive Advisory", adv_res)
        self.assertIn("Live Free Energy", adv_res)

        compile_res = handle_fable_session({
            "action": "compile_delegation_contract",
            "subagent_prompt": """
TargetFile: src/core.py
InterfaceContract: class CoreEngine: def run(self) -> bool: ...
StrictConstraints: Safe execution bounds
VerificationCommand: python -m unittest
""",
        })
        self.assertIn("System 3 Micro-Scaffolds", compile_res)
        self.assertIn("INJECTED", compile_res)


class TestSystem3BrokerAndAdapters(unittest.TestCase):
    """Test System 3 checks in execution broker and host adapters."""

    def test_host_capabilities_system3_methods(self):
        caps = HostCapabilities(
            host="gemini-cli",
            capabilities=frozenset({"run_command", "view_file", "write_to_file"}),
        )
        # Temporal invariant check
        k_res = caps.verify_temporal_capability_invariants("AG(capable)")
        self.assertIn("is_satisfied", k_res)

        # Causal capability contract validation
        c_res = caps.validate_causal_capability_contract(["run_command", "view_file"])
        self.assertTrue(c_res["is_valid"])
        self.assertEqual(len(c_res["missing"]), 0)

        c_missing = caps.validate_causal_capability_contract(["run_command", "gpu_compute"])
        self.assertFalse(c_missing["is_valid"])
        self.assertIn("gpu_compute", c_missing["missing"])

    def test_execution_broker_system3_pre_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy = BrokerPolicy(
                workspace=Path(tmpdir),
                allowed_executables=("python",),
            )
            broker = ExecutionBroker(policy)
            k_res = broker.check_kripke_pre_execution_invariants(["python", "-c", "print(1)"])
            self.assertTrue(k_res["is_satisfied"])
            self.assertEqual(k_res["formula"], "AG(safe_execution)")

            c_res = broker.validate_causal_boundaries(["python", "-c", "print(1)"])
            self.assertTrue(c_res["is_valid"])
            self.assertIn("dag", c_res)


if __name__ == "__main__":
    unittest.main()
