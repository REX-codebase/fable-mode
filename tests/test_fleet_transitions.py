import unittest
from pathlib import Path


class FleetTransitionRegressionTests(unittest.TestCase):
    def test_remediation_and_verification_handlers_use_fsm_transitions(self):
        root = Path(__file__).parents[1]
        fleet_source = root.joinpath("fable_engine/actions/fleet.py").read_text(encoding="utf-8")
        session_source = root.joinpath("fable_engine/session.py").read_text(encoding="utf-8")
        self.assertNotIn("session.current_state = SessionState.REMEDIATION_REQUIRED", fleet_source)
        self.assertNotIn("session.current_state = SessionState.SEALED", fleet_source)
        self.assertIn("session.record_breakage_report", fleet_source)
        self.assertIn("self.transition_to(SessionState.REMEDIATION_REQUIRED", session_source)
        self.assertIn("self.transition_to(SessionState.SEALED", session_source)


if __name__ == "__main__":
    unittest.main()
