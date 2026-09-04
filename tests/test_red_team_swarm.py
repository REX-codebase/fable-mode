"""Comprehensive Unit Test Suite for Modular Fable Part 1: Adversarial Code Review Swarm.

Tests:
- Scenario generation across all 5 attack vectors + custom hypotheses
- Break detection on fragile/broken callables
- Resilience verification on hardened callables
- to_dict() and to_markdown() serialization & GitHub alert formatting
- Full closed-loop ping-pong remediation cycle
- CoderFleetDispatcher routing for all 5 red team actions
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_v2.coder_fleet import (
    AttackVector,
    BreakFinding,
    BreakScenario,
    CoderFleetDispatcher,
    RedTeamBreakageReport,
    RedTeamSwarm,
)


class TestRedTeamSwarmScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.swarm = RedTeamSwarm()

    def test_scenario_generation_all_vectors(self) -> None:
        scenarios = self.swarm.generate_break_scenarios(
            target_name="test_target",
            custom_hypotheses=[
                "What will happen if a concurrent race condition occurs?",
                "What will happen if byzantine payload injections arrive?",
            ],
        )
        self.assertGreaterEqual(len(scenarios), 10)

        vectors_present = {s.vector for s in scenarios}
        self.assertIn(AttackVector.CHAOS_ENVIRONMENT, vectors_present)
        self.assertIn(AttackVector.BYZANTINE_PAYLOAD, vectors_present)
        self.assertIn(AttackVector.CONCURRENCY_RACE, vectors_present)
        self.assertIn(AttackVector.RESOURCE_EXHAUSTION, vectors_present)
        self.assertIn(AttackVector.STATE_INVARIANT, vectors_present)

        custom_scenarios = [s for s in scenarios if s.metadata.get("custom")]
        self.assertEqual(len(custom_scenarios), 2)
        self.assertEqual(custom_scenarios[0].vector, AttackVector.CONCURRENCY_RACE)
        self.assertEqual(custom_scenarios[1].vector, AttackVector.BYZANTINE_PAYLOAD)


class TestRedTeamSwarmExecution(unittest.TestCase):
    def setUp(self) -> None:
        self.swarm = RedTeamSwarm()

    def test_break_detection_fragile_callable(self) -> None:
        def fragile_target(x: Any = None) -> str:
            if x is None:
                raise AttributeError("'NoneType' object has no attribute 'split'")
            if isinstance(x, str) and "\x00" in x:
                raise KeyError("Null byte detected in string dictionary index")
            return "ok"

        report = self.swarm.execute_swarm_attack(fragile_target)
        self.assertFalse(report.passed)
        self.assertGreater(report.broken_count, 0)

        # Ensure broken findings contain rich diagnostics
        broken_findings = [f for f in report.findings if f.broken]
        self.assertTrue(len(broken_findings) > 0)
        first_broken = broken_findings[0]
        self.assertIsNotNone(first_broken.error_message)
        self.assertIsNotNone(first_broken.reproduction_code)
        self.assertIn(first_broken.severity, ("CRITICAL", "HIGH", "MEDIUM"))
        self.assertGreater(len(report.remediation_directives), 0)

    def test_resilience_hardened_callable(self) -> None:
        lock = threading.Lock()
        state = {"calls": 0}

        def hardened_target(payload: Any = None) -> dict[str, Any]:
            with lock:
                state["calls"] += 1
                if payload is None:
                    return {"status": "ok", "data": "default"}
                if isinstance(payload, (int, float)):
                    return {"status": "ok", "data": "number"}
                if isinstance(payload, str):
                    # Defensively sanitize null bytes and bound size
                    sanitized = payload.replace("\x00", "")[:1000]
                    return {"status": "ok", "data": sanitized}
                if isinstance(payload, dict):
                    return {"status": "ok", "data": "dict_received"}
                return {"status": "ok", "data": str(payload)[:100]}

        report = self.swarm.execute_swarm_attack(hardened_target)
        self.assertTrue(report.passed)
        self.assertEqual(report.broken_count, 0)
        self.assertEqual(len([f for f in report.findings if f.broken]), 0)


class TestReportFormattingAndSerialization(unittest.TestCase):
    def setUp(self) -> None:
        self.swarm = RedTeamSwarm()

    def test_report_to_dict_and_from_dict(self) -> None:
        finding = BreakFinding(
            scenario_id="sc_01",
            vector="byzantine_payload",
            hypothesis="What will happen on null byte?",
            broken=True,
            error_message="KeyError: null byte",
            traceback_snippet="Traceback ...",
            reproduction_code="target('\x00')",
            severity="HIGH",
            details={"duration_ms": 1.2},
        )
        report = RedTeamBreakageReport(
            report_id="rep_test_123",
            target_name="AuthService",
            total_probes=1,
            broken_count=1,
            passed=False,
            findings=[finding],
            created_at="2026-09-04T12:00:00Z",
            remediation_directives=["Sanitize input null bytes"],
        )

        data = report.to_dict()
        self.assertEqual(data["report_id"], "rep_test_123")
        self.assertEqual(data["broken_count"], 1)
        self.assertFalse(data["passed"])

        restored = RedTeamBreakageReport.from_dict(data)
        self.assertEqual(restored.report_id, report.report_id)
        self.assertEqual(restored.target_name, report.target_name)
        self.assertEqual(len(restored.findings), 1)
        self.assertTrue(restored.findings[0].broken)

    def test_to_markdown_formatting_failed(self) -> None:
        finding = BreakFinding(
            scenario_id="sc_01",
            vector="byzantine_payload",
            hypothesis="What will happen on null byte?",
            broken=True,
            error_message="ValueError: invalid byte",
            traceback_snippet="Traceback ...",
            reproduction_code="target_fn('\x00')",
            severity="HIGH",
        )
        report = RedTeamBreakageReport(
            report_id="rep_test_fail",
            target_name="payment_processor",
            total_probes=5,
            broken_count=1,
            passed=False,
            findings=[finding],
            created_at="2026-09-04T12:00:00Z",
            remediation_directives=["Strip null bytes before processing"],
        )
        md = report.to_markdown()
        self.assertIn("# 🚨 Adversarial Red Team Breakage Report: `payment_processor`", md)
        self.assertIn("> [!CAUTION]", md)
        self.assertIn("Strip null bytes before processing", md)
        self.assertIn("target_fn('\x00')", md)

    def test_to_markdown_formatting_passed(self) -> None:
        report = RedTeamBreakageReport(
            report_id="rep_test_pass",
            target_name="hardened_crypto",
            total_probes=10,
            broken_count=0,
            passed=True,
            findings=[],
            created_at="2026-09-04T12:00:00Z",
        )
        md = report.to_markdown()
        self.assertIn("# 🛡️ Adversarial Red Team Resilient Attestation: `hardened_crypto`", md)
        self.assertIn("> [!NOTE]", md)
        self.assertIn("🟢 **RESILIENT (PASSED)**", md)

    def test_document_breakage_to_file(self) -> None:
        report = RedTeamBreakageReport(
            report_id="rep_test_doc",
            target_name="doc_target",
            total_probes=2,
            broken_count=0,
            passed=True,
            findings=[],
            created_at="2026-09-04T12:00:00Z",
        )
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            res_md = self.swarm.document_breakage(report, output_path=tmp_path)
            self.assertTrue(os.path.exists(tmp_path))
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(res_md, content)
            self.assertIn("doc_target", content)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestPingPongRemediationCycle(unittest.TestCase):
    def setUp(self) -> None:
        self.swarm = RedTeamSwarm()

    def test_full_ping_pong_hardening_cycle(self) -> None:
        # Stage 1: Fragile initial implementation submitted by subagent
        def candidate_v1(input_data: Any = None) -> str:
            # Fragile: crashes unhandled on None, null bytes, and empty inputs
            if input_data is None:
                raise AttributeError("'NoneType' object has no attribute 'strip'")
            if "\x00" in input_data:
                raise KeyError("Byzantine null byte rejected with raw error")
            return f"processed_{input_data}"

        # Stage 2: Swarm attack breaks candidate_v1
        initial_report = self.swarm.run_full_review_cycle(
            candidate_v1,
            target_name="candidate_service",
        )
        self.assertFalse(initial_report.passed)
        self.assertGreater(initial_report.broken_count, 0)
        self.assertGreater(len(initial_report.remediation_directives), 0)

        # Stage 3: Subagent remediates and hardens implementation
        lock = threading.Lock()

        def candidate_v2(input_data: Any = None) -> str:
            with lock:
                if input_data is None:
                    return "processed_default"
                if isinstance(input_data, str):
                    clean = input_data.replace("\x00", "")[:200]
                    return f"processed_{clean}"
                return f"processed_{str(input_data)[:200]}"

        # Stage 4: Swarm re-attacks and verifies remediation
        all_fixed, new_report = self.swarm.verify_remediation(
            target_callable=candidate_v2,
            prior_report=initial_report,
        )

        self.assertTrue(all_fixed)
        self.assertTrue(new_report.passed)
        self.assertEqual(new_report.broken_count, 0)


class TestCoderFleetDispatcherRedTeamActions(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = CoderFleetDispatcher()

    def test_registered_red_team_actions(self) -> None:
        actions = self.dispatcher.list_actions()
        expected = [
            "red_team_generate_scenarios",
            "red_team_execute_attack",
            "red_team_document_breakage",
            "red_team_verify_remediation",
            "red_team_full_review_cycle",
        ]
        for act in expected:
            self.assertIn(act, actions)

    def test_dispatch_red_team_generate_scenarios(self) -> None:
        res = self.dispatcher.dispatch(
            "red_team_generate_scenarios",
            {"target_name": "AuthModule", "custom_hypotheses": ["What if token is empty?"]},
        )
        self.assertTrue(res["success"])
        scenarios = res["result"]
        self.assertIsInstance(scenarios, list)
        self.assertGreater(len(scenarios), 0)

    def test_dispatch_red_team_full_review_cycle(self) -> None:
        code_snippet = "def safe_fn(x=None):\n    return 'safe'\n"
        res = self.dispatcher.dispatch(
            "red_team_full_review_cycle",
            {"target_callable": code_snippet, "target_name": "safe_fn"},
        )
        self.assertTrue(res["success"])
        report = res["result"]
        self.assertTrue(isinstance(report, RedTeamBreakageReport))
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()
