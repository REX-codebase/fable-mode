import copy
import unittest

from fable_engine.session import (
    FableSession,
    RED_TEAM_ATTACK_VECTORS,
    SessionState,
)


class SealingRemediationSecurityTests(unittest.TestCase):
    def _ready_session(self, name="security_regression"):
        session = FableSession(name, "security gate", 5.0)
        session.set_timer(5.0)
        session.log_epistemic_item("PROVEN", "Evidence one", "README.md:L1")
        session.log_epistemic_item("PROVEN", "Evidence two", "README.md:L2")
        session.set_goal_rubric(
            "security gate",
            [{"pointer_id": "P1", "satisfied": True, "score": 1.0, "verifier_command": "unittest"}],
        )
        session.log_refinement_cycle("security", "sealing", "bypass", "receipt gate")
        session.track_file_change("fable_engine/session.py", "modified", "hardened sealing")
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "implementation complete")
        session.transition_to(SessionState.RED_TEAM_GATE, "code written")
        return session

    def _clean_report(self, session, change_id="change-1"):
        report = {
            "report_id": "clean-1",
            "target_name": "system",
            "total_probes": 5,
            "broken_count": 0,
            "passed": True,
            "findings": [{"scenario_id": vector, "vector": vector, "broken": False} for vector in RED_TEAM_ATTACK_VECTORS],
            "report_origin": "red_team_swarm",
            "reviewed_change_id": change_id,
        }
        report["red_team_receipt"] = session.issue_red_team_receipt(report, change_id)
        return report

    def test_clean_report_is_transactional_and_authenticated(self):
        session = self._ready_session("security_transaction")
        session.record_breakage_report({
            "report_id": "broken",
            "total_probes": 1,
            "broken_count": 1,
            "passed": False,
            "findings": [{"scenario_id": "x", "vector": "state_invariant", "broken": True}],
        })
        before_reports = copy.deepcopy(session.breakage_reports)
        before_breakages = copy.deepcopy(session.active_breakages)
        with self.assertRaises(ValueError):
            session.record_breakage_report({"report_id": "clean", "total_probes": 0, "broken_count": 0, "passed": True, "findings": []})
        self.assertEqual(session.breakage_reports, before_reports)
        self.assertEqual(session.active_breakages, before_breakages)

        clean = self._clean_report(session)
        session.record_breakage_report(clean)
        self.assertEqual(session.current_state, SessionState.SEALED)
        self.assertEqual(session.active_breakages, [])

    def test_receipt_binds_all_vectors_and_reviewed_change(self):
        session = self._ready_session("security_receipt")
        clean = self._clean_report(session)
        clean["reviewed_change_id"] = "different-change"
        with self.assertRaises(ValueError):
            session.record_breakage_report(clean)

    def test_remediation_bounds_escalate_with_epistemic_status(self):
        session = FableSession("security_escalation", "bounds", 5.0)
        session.set_timer(5.0)
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "implementation complete")
        session.transition_to(SessionState.RED_TEAM_GATE, "code written")
        for attempt in range(5):
            session.record_breakage_report({
                "report_id": "broken-%d" % attempt,
                "total_probes": 1,
                "broken_count": 1,
                "passed": False,
                "findings": [{"scenario_id": "x", "vector": "state_invariant", "broken": True, "hypothesis": "unsafe state"}],
            })
        self.assertEqual(session.current_state, SessionState.ESCALATION_UNRESOLVED_BREAKAGES)
        self.assertEqual(session.remediation_attempt_count, 5)
        self.assertTrue(session.active_breakages[0]["human_arbitration_required"])
        self.assertIn(session.active_breakages[0]["epistemic_status"], {"UNKNOWN", "HYPOTHESIS"})

    def test_restored_sealed_state_cannot_bypass_authenticated_gate(self):
        session = self._ready_session("security_restore_sealed")
        clean = self._clean_report(session, "restore-change")
        session.record_breakage_report(clean)
        restored = FableSession.from_dict(session.to_dict())
        self.assertEqual(restored.current_state, SessionState.INIT)
        with self.assertRaises(ValueError):
            restored.transition_to(SessionState.SEALED, "stale persisted seal")

    def test_restored_stage_records_are_individually_untrusted(self):
        session = self._ready_session("security_restore")
        restored = FableSession.from_dict(session.to_dict())
        for collection in (restored.epistemic_ledger, restored.refinement_cycles, restored.goal_rubrics, restored.file_changes):
            self.assertTrue(collection)
            self.assertTrue(all(item.get("_restored_untrusted") for item in collection))


if __name__ == "__main__":
    unittest.main()
