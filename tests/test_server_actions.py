import unittest
import json
import time
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import handle_fable_session, ACTIVE_SESSIONS, SESSIONS_DIR, FableSession


class TestServerActions(unittest.TestCase):
    def setUp(self):
        self.session_name = f"test_session_{int(time.time() * 1000)}"

    def tearDown(self):
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]
        session_file = SESSIONS_DIR / f"{self.session_name}.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except Exception:
                pass

    def test_session_lifecycle_with_silent_deliberation(self):
        # 1. Create Session
        res = handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Verify frontier uplift protocol",
            "time_budget_minutes": 30.0
        })
        self.assertIn("Fable Cognitive Session Initialized", res)
        self.assertIn("SILENT-DELIBERATION ACTIVE", res)

        session = ACTIVE_SESSIONS[self.session_name]
        tel = session.get_telemetry()
        self.assertTrue(tel["silent_deliberation_active"])
        self.assertTrue(tel["execution_locked"])

        # 2. Log Proven Item with valid command evidence
        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "Python 3 installed",
            "evidence": "python --version stdout: Python 3.12"
        })
        self.assertIn("Epistemic Item Logged", res)
        self.assertIn("SILENT-DELIBERATION ACTIVE", res)

        # 3. Log Proven Item with invalid file evidence -> Expect error
        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "Bogus claim",
            "evidence": "non_existent_file_xyz_123.py:L10"
        })
        self.assertIn("Error:", res)
        self.assertIn("Epistemic Evidence Validation Failed", res)

        # 4. Compile Delegation Contract
        valid_contract = """
        ### SUBAGENT DELEGATION CONTRACT
        - TargetFile: src/core/engine.py
        - InterfaceContract: def process_event(event: Event) -> bool
        - StrictConstraints: Lock-free, zero heap allocation in loop
        - VerificationCommand: pytest tests/test_engine.py
        """
        res = handle_fable_session({
            "action": "compile_delegation_contract",
            "session_name": self.session_name,
            "subagent_prompt": valid_contract
        })
        self.assertIn("Subagent Delegation Contract Compiled Successfully", res)
        self.assertIn("READY_FOR_SUBAGENT_DISPATCH", res)

        # 5. Compile Invalid Contract
        res = handle_fable_session({
            "action": "compile_delegation_contract",
            "session_name": self.session_name,
            "subagent_prompt": "Please write the code"
        })
        self.assertIn("Subagent Delegation Contract Compilation Failed", res)


if __name__ == "__main__":
    unittest.main()
