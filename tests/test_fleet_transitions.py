import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fable_engine.actions.fleet import (
    _handle_evolve_cortex,
    _handle_record_breakage_report,
    _handle_verify_red_team_remediation,
)
from fable_engine.session import FableSession, SessionState
from fable_v2.cortical import HebbianPlasticityEngine


class FleetTransitionRegressionTests(unittest.TestCase):
    @staticmethod
    def _red_team_session(name: str) -> FableSession:
        session = FableSession(name, "Fleet transition regression", 5.0)
        session.set_timer(5.0)
        session.execution_locked = False
        session.can_execute_code = True
        session.transition_to(SessionState.IMPLEMENTATION, "Execution unlocked")
        session.track_file_change("sample.py", "modified", "Exercise fleet transition")
        session.transition_to(SessionState.RED_TEAM_GATE, "Code submitted for review")
        return session

    def test_record_breakage_report_handler_transitions_to_remediation(self) -> None:
        session = self._red_team_session("record_handler_transition")
        with (
            patch("fable_engine.actions.fleet.get_or_load_session", return_value=session),
            patch.object(session, "save"),
        ):
            response = _handle_record_breakage_report({
                "session_name": session.session_name,
                "findings": [{"scenario_id": "missing-broken-is-active"}],
            })

        self.assertIn("TASK REJECTED", response)
        self.assertEqual(session.current_state, SessionState.REMEDIATION_REQUIRED)
        self.assertEqual(len(session.active_breakages), 1)

    def test_verify_remediation_handler_keeps_failed_session_unsealed(self) -> None:
        session = self._red_team_session("verify_handler_transition")
        session.record_breakage_report({
            "report_id": "prior",
            "total_probes": 1,
            "broken_count": 1,
            "passed": False,
            "findings": [{"scenario_id": "still-broken", "broken": True}],
        })
        failed_report = {
            "report_id": "verification",
            "total_probes": 1,
            "broken_count": 1,
            "passed": False,
            "findings": [{"scenario_id": "still-broken", "broken": True}],
        }
        swarm = SimpleNamespace(
            verify_remediation=lambda **_kwargs: (
                False,
                SimpleNamespace(broken_count=1, to_dict=lambda: failed_report),
            )
        )

        with (
            patch("fable_engine.actions.fleet.get_or_load_session", return_value=session),
            patch("fable_engine.actions.fleet._get_swarm", return_value=swarm),
            patch.object(session, "save"),
        ):
            response = _handle_verify_red_team_remediation({
                "session_name": session.session_name,
                "prior_report": session.breakage_reports[-1],
                "remediated_code": lambda: None,
            })

        self.assertIn("TASK REJECTED", response)
        self.assertEqual(session.current_state, SessionState.REMEDIATION_REQUIRED)
        self.assertEqual(session.remediation_attempt_count, 2)

    def test_direct_seal_requires_validated_clean_report(self) -> None:
        session = self._red_team_session("direct_seal_guard")
        session.transition_to(SessionState.ARBITRATION, "Review complete")

        with self.assertRaisesRegex(ValueError, "requires a clean report"):
            session.transition_to(SessionState.SEALED, "Direct seal probe")

    def test_evolve_cortex_reports_effective_storage_path(self) -> None:
        session = self._red_team_session("effective_cortex_path")
        session.transition_to(SessionState.ARBITRATION, "Review complete")
        session._sealing_authorized = True
        try:
            session.transition_to(SessionState.SEALED, "Validated test seal")
        finally:
            session._sealing_authorized = False

        with tempfile.TemporaryDirectory() as temp_dir:
            engine = HebbianPlasticityEngine(cortex_dir=Path(temp_dir) / "cortex")
            expected_path = engine._get_lobe_path("python").resolve()
            with (
                patch("fable_engine.actions.fleet.get_or_load_session", return_value=session),
                patch("fable_engine.actions.fleet._get_cortex", return_value=engine),
                patch.object(session, "save"),
            ):
                response = _handle_evolve_cortex({
                    "session_name": session.session_name,
                    "domain": "python",
                })

        self.assertEqual(session.current_state, SessionState.EVOLVED)
        self.assertEqual(response.count(f"`{expected_path}`"), 2)
        self.assertNotIn("skills/fable-mode/cortex", response)


if __name__ == "__main__":
    unittest.main()
