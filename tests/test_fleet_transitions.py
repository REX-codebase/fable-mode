import unittest
from pathlib import Path


class FleetTransitionRegressionTests(unittest.TestCase):
    def test_remediation_and_verification_handlers_use_fsm_transitions(self):
        source = Path(__file__).parents[1].joinpath("fable_engine/actions/fleet.py").read_text(encoding="utf-8")
        self.assertNotIn("session.current_state = SessionState.REMEDIATION_REQUIRED", source)
        self.assertNotIn("session.current_state = SessionState.SEALED", source)
        # State transitions are centralized in FableSession.record_breakage_report
        # so handlers cannot bypass receipt validation or partially mutate FSM state.
        self.assertNotIn("session.transition_to(SessionState.REMEDIATION_REQUIRED", source)
        self.assertNotIn("session.transition_to(SessionState.SEALED", source)
        self.assertIn("session.record_breakage_report", source)


if __name__ == "__main__":
    unittest.main()
