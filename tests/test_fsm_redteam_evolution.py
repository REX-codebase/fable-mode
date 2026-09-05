"""Unit test suite verifying the MCP-Governed Closed-Loop Red-Team & Evolution Engine Architecture.

Validates:
1. test_fsm_illegal_transitions_blocked
2. test_red_team_gating_and_rejection_order
3. test_closed_loop_ping_pong_remediation_and_sealing
4. test_post_success_cortical_evolution
"""
import copy
import json
import os
import sys
from pathlib import Path
import shutil
import tempfile
import time
import unittest

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_engine.server import (
    FableSession,
    SessionState,
    VALID_TRANSITIONS,
    PHASES,
    handle_fable_session,
    GLOBAL_PLASTICITY_ENGINE,
    ACTIVE_SESSIONS,
    SESSIONS_DIR,
    get_or_load_session,
)
from fable_v2.coder_fleet.red_team_swarm import RedTeamBreakageReport, BreakFinding


class TestFSMRedTeamEvolution(unittest.TestCase):
    def setUp(self):
        ACTIVE_SESSIONS.clear()
        self.test_dir = tempfile.mkdtemp(prefix="fable_fsm_test_")
        for name in ("test_illegal_fsm", "test_red_team_gate", "test_ping_pong_loop", "test_cortical_evo"):
            p = SESSIONS_DIR / f"{name}.json"
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def tearDown(self):
        ACTIVE_SESSIONS.clear()
        for name in ("test_illegal_fsm", "test_red_team_gate", "test_ping_pong_loop", "test_cortical_evo"):
            p = SESSIONS_DIR / f"{name}.json"
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_fsm_illegal_transitions_blocked(self):
        """1. Verify FSM tracks state and strictly blocks illegal leaps (e.g. INIT -> SEALED/EVOLVED)."""
        session_name = "test_illegal_fsm"
        session = FableSession(session_name=session_name, objective="Test FSM invariants", time_budget_minutes=10.0)
        ACTIVE_SESSIONS[session_name] = session

        # Verify initial state
        self.assertEqual(session.current_state, SessionState.INIT)
        self.assertEqual(session.iteration_count, 0)
        self.assertEqual(session.active_breakages, [])
        self.assertEqual(session.remediation_history, [])

        # Direct leap from INIT -> SEALED must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            session.transition_to(SessionState.SEALED, "Attempt premature seal")
        self.assertIn("Illegal state transition from INIT to SEALED", str(ctx.exception))

        # Direct leap from INIT -> EVOLVED must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            session.transition_to(SessionState.EVOLVED, "Attempt premature evolve")
        self.assertIn("Illegal state transition from INIT to EVOLVED", str(ctx.exception))

        # Direct leap from INIT -> RED_TEAM_GATE must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            session.transition_to(SessionState.RED_TEAM_GATE, "Skip implementation")
        self.assertIn("Illegal state transition", str(ctx.exception))

        # Move to DEEPTHINK_TIMELOCK via set_timer
        session.set_timer(10.0)
        self.assertEqual(session.current_state, SessionState.DEEPTHINK_TIMELOCK)

        # Direct leap from DEEPTHINK_TIMELOCK -> SEALED or EVOLVED must raise ValueError
        with self.assertRaises(ValueError):
            session.transition_to(SessionState.SEALED, "Premature seal from timelock")
        with self.assertRaises(ValueError):
            session.transition_to(SessionState.EVOLVED, "Premature evolve from timelock")

        # Attempting jump from Phase 1 to Phase 4 is blocked by phase order
        adv_res_jump = handle_fable_session({
            "action": "advance_phase",
            "session_name": session_name,
            "next_phase": "Phase 4: Subagent Fleet Delegation",
            "phase_summary": "Attempting jump while in Phase 1"
        })
        self.assertIn("Invalid phase transition", adv_res_jump)

        # In Phase 3, advancing to Phase 4 while execution is locked must fail with execution locked
        session.active_phase = PHASES[2]  # Phase 3
        adv_res = handle_fable_session({
            "action": "advance_phase",
            "session_name": session_name,
            "next_phase": "Phase 4: Subagent Fleet Delegation",
            "phase_summary": "Attempting jump while locked"
        })
        self.assertTrue("Execution must be unlocked" in adv_res or "Execution is still locked" in adv_res)

        # advance_phase to Phase 5 or Phase 6 while in DEEPTHINK_TIMELOCK must fail
        adv_res_p5 = handle_fable_session({
            "action": "advance_phase",
            "session_name": session_name,
            "next_phase": "Phase 5: Multi-Tier Verification & Gatekeeping",
            "phase_summary": "Skipping implementation"
        })
        self.assertTrue(
            "Cannot advance to Phase 5" in adv_res_p5 or "Execution is still locked" in adv_res_p5 or "Error" in adv_res_p5
        )

        # Transition to IMPLEMENTATION
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "Execution unlocked")
        self.assertEqual(session.current_state, SessionState.IMPLEMENTATION)

        # From IMPLEMENTATION, jumping directly to SEALED or EVOLVED is illegal
        with self.assertRaises(ValueError):
            session.transition_to(SessionState.SEALED)
        with self.assertRaises(ValueError):
            session.transition_to(SessionState.EVOLVED)

    def test_red_team_gating_and_rejection_order(self):
        """2. Verify Red Team Swarm attack results strictly gate the session, returning TASK REJECTED."""
        session_name = "test_red_team_gate"
        session = FableSession(session_name=session_name, objective="Red team gate test", time_budget_minutes=5.0)
        session.set_timer(5.0)
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "Implementation started")
        session.transition_to(SessionState.RED_TEAM_GATE, "Code submitted for swarm audit")
        session.save()
        ACTIVE_SESSIONS[session_name] = session

        # Record breakage report with 2 broken scenarios
        broken_scenarios = [
            {
                "scenario_id": "auth_byzantine_null_byte",
                "vector": "byzantine_payload",
                "hypothesis": "Null byte injection causes unhandled C-string truncation",
                "broken": True,
                "error_message": "ValueError: embedded null byte",
                "reproduction_code": "authenticate('admin\\x00token')",
                "severity": "CRITICAL",
            },
            {
                "scenario_id": "auth_concurrency_toctou",
                "vector": "concurrency_race",
                "hypothesis": "Concurrent token revocation allows TOCTOU reuse",
                "broken": True,
                "error_message": "AssertionError: token was used after revocation",
                "reproduction_code": "concurrent_revoke_and_use(token)",
                "severity": "HIGH",
            },
        ]

        resp = handle_fable_session({
            "action": "record_breakage_report",
            "session_name": session_name,
            "broken_scenarios": broken_scenarios,
        })
        session = get_or_load_session(session_name)

        # Verify exact machine order string
        expected_machine_order = "TASK REJECTED: 2 breakages detected. Deploy subagent to fix findings."
        self.assertIn(expected_machine_order, resp)

        # Verify session state became REMEDIATION_REQUIRED
        self.assertEqual(session.current_state, SessionState.REMEDIATION_REQUIRED)
        self.assertEqual(len(session.active_breakages), 2)
        self.assertEqual(session.iteration_count, 1)

        # Verify advancing phase is blocked while active breakages exist
        adv_resp = handle_fable_session({
            "action": "advance_phase",
            "session_name": session_name,
            "next_phase": "Phase 5: Multi-Tier Verification & Gatekeeping",
            "phase_summary": "Attempting advance with active breakages"
        })
        self.assertTrue("active breakages" in adv_resp or "REMEDIATION_REQUIRED" in adv_resp or "Error" in adv_resp)

    def test_closed_loop_ping_pong_remediation_and_sealing(self):
        """3. Verify ping-pong while-loop remediation and final SEALED state transition."""
        session_name = "test_ping_pong_loop"
        session = FableSession(session_name=session_name, objective="Ping-pong hardening test", time_budget_minutes=5.0)
        session.set_timer(5.0)
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "Implemented")
        session.transition_to(SessionState.RED_TEAM_GATE, "Code written and ready for audit")
        session.save()
        ACTIVE_SESSIONS[session_name] = session

        # 1. Initial breakage recorded
        initial_breakages = [
            {
                "scenario_id": "sec_01",
                "vector": "byzantine_payload",
                "hypothesis": "Large payload crashes memory",
                "broken": True,
                "error_message": "MemoryError: payload too large",
                "reproduction_code": "process('A' * 1000000)",
                "severity": "HIGH",
            }
        ]
        resp1 = handle_fable_session({
            "action": "record_breakage_report",
            "session_name": session_name,
            "broken_scenarios": initial_breakages,
        })
        session = get_or_load_session(session_name)
        self.assertIn("TASK REJECTED: 1 breakages detected. Deploy subagent to fix findings.", resp1)
        self.assertEqual(session.current_state, SessionState.REMEDIATION_REQUIRED)

        # 2. Subagent submits remediated code, but it still breaks
        broken_report = {
            "report_id": "rep_prior_01",
            "target_name": "process",
            "broken_count": 1,
            "findings": [
                {
                    "scenario_id": "sec_01",
                    "vector": "byzantine_payload",
                    "hypothesis": "Large payload crashes memory",
                    "broken": True,
                    "error_message": "MemoryError",
                }
            ]
        }
        flawed_code = "def process(x):\n    raise MemoryError('Still leaking')"
        resp_flawed = handle_fable_session({
            "action": "verify_red_team_remediation",
            "session_name": session_name,
            "remediated_code": flawed_code,
            "prior_report": broken_report,
        })
        session = get_or_load_session(session_name)
        self.assertIn("TASK REJECTED:", resp_flawed)
        self.assertEqual(session.current_state, SessionState.REMEDIATION_REQUIRED)

        # 3. Subagent submits fully fixed code that survives the prior breaking probe
        fixed_code = "def process(x):\n    return 'clean'"
        resp_fixed = handle_fable_session({
            "action": "verify_red_team_remediation",
            "session_name": session_name,
            "remediated_code": fixed_code,
            "prior_report": broken_report,
        })
        session = get_or_load_session(session_name)

        # Verify exact machine completion string
        expected_completion = "TASK COMPLETED: 0 breakages remain. Code sealed."
        self.assertIn(expected_completion, resp_fixed)
        self.assertEqual(session.current_state, SessionState.SEALED)
        self.assertEqual(len(session.active_breakages), 0)
        self.assertTrue(len(session.remediation_history) >= 1)

    def test_post_success_cortical_evolution(self):
        """4. Verify post-success cortical evolution applies LTP weight updates, antibodies, and disk save."""
        session_name = "test_cortical_evo"
        session = FableSession(session_name=session_name, objective="Cortical evolution test", time_budget_minutes=5.0)
        session.save()
        ACTIVE_SESSIONS[session_name] = session

        # Calling evolve_cortex on an unsealed session (INIT) must be rejected
        unsealed_resp = handle_fable_session({
            "action": "evolve_cortex",
            "session_name": session_name,
            "domain": "security",
            "task_id": "test_task_evo",
        })
        self.assertIn("Error: evolve_cortex rejected: Session must be in SEALED or EVOLVED state", unsealed_resp)

        # Advance session legitimately to SEALED state
        session.set_timer(5.0)
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "Implemented")
        session.transition_to(SessionState.RED_TEAM_GATE, "Code written and ready for audit")
        session.transition_to(SessionState.ARBITRATION, "Arbitration")
        session.transition_to(SessionState.SEALED, "Sealed after 0 breakages")
        session.save()
        ACTIVE_SESSIONS[session_name] = session

        # Record a past breakage that was neutralized
        neutralized_breakages = [
            {
                "scenario_id": "sec_sqli_01",
                "vector": "byzantine_payload",
                "hypothesis": "Unsanitized input in query",
                "error_message": "SQLSyntaxError",
                "reproduction_code": "query(\"' OR 1=1 --\")",
                "severity": "CRITICAL",
                "prescribed_defense": "Enforce parameterized queries with atomic binding",
            }
        ]

        # Call evolve_cortex
        evo_resp = handle_fable_session({
            "action": "evolve_cortex",
            "session_name": session_name,
            "domain": "security",
            "task_id": "task_sec_01",
            "broken_scenarios": neutralized_breakages,
            "co_activated_nodes": ["red_team_swarm", "mutation", "test_harness"],
        })
        session = get_or_load_session(session_name)

        # Verify receipt contents
        self.assertIn("### 🧬 Cortical Evolution Receipt: EVOLVED", evo_resp)
        self.assertIn("LTP (Long-Term Potentiation)", evo_resp)
        self.assertIn("+0.10 * A_domain * A_node (LTP)", evo_resp)
        self.assertIn("ab_security_sec_sqli_01", evo_resp)

        # Verify session state transitioned to EVOLVED
        self.assertEqual(session.current_state, SessionState.EVOLVED)

        # Verify disk persistence in cortex/<domain>.md
        lobe = GLOBAL_PLASTICITY_ENGINE.activate_lobe(domain="security")
        self.assertIsNotNone(lobe)
        lobe_path = GLOBAL_PLASTICITY_ENGINE.cortex_dir / "security.md"
        self.assertTrue(lobe_path.exists())

        lobe_content = lobe_path.read_text(encoding="utf-8")
        self.assertIn("ab_security_sec_sqli_01", lobe_content)
        self.assertIn("Unsanitized input in query", lobe_content)

        # Verify synaptic weights reflect potentiated LTP updates
        self.assertIn("red_team_swarm", lobe.synaptic_weights)
        self.assertGreaterEqual(lobe.synaptic_weights["red_team_swarm"], 0.05)


if __name__ == "__main__":
    unittest.main()
