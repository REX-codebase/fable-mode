import unittest
from pathlib import Path


class FleetTransitionRegressionTests(unittest.TestCase):
    def test_remediation_and_verification_handlers_use_fsm_transitions(self):
        source = Path(__file__).parents[1].joinpath("fable_engine/actions/fleet.py").read_text(encoding="utf-8")
        self.assertNotIn("session.current_state = SessionState.REMEDIATION_REQUIRED", source)
        self.assertNotIn("session.current_state = SessionState.SEALED", source)
        self.assertGreaterEqual(
            source.count("session.transition_to(SessionState.REMEDIATION_REQUIRED"), 2
        )
        self.assertGreaterEqual(
            source.count("session.transition_to(SessionState.SEALED"), 1
        )


if __name__ == "__main__":
    unittest.main()
