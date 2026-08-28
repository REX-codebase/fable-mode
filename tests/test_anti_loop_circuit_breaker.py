import unittest
from pathlib import Path
import sys

# Ensure fable-engine directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import AntiLoopCircuitBreaker


class TestAntiLoopCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.breaker = AntiLoopCircuitBreaker(max_consecutive_repeats=2, window_size=6)

    def test_single_failure_does_not_trip(self):
        tripped, msg = self.breaker.record_and_evaluate(
            "replace_file_content",
            {"TargetFile": "src/main.py", "StartLine": 10},
            is_error=True
        )
        self.assertFalse(tripped)
        self.assertEqual(msg, "OK")

    def test_consecutive_identical_failures_trip(self):
        tool = "replace_file_content"
        args = {"TargetFile": "src/main.py", "StartLine": 10}
        
        # 1st fail
        tripped, _ = self.breaker.record_and_evaluate(tool, args, is_error=True)
        self.assertFalse(tripped)
        
        # 2nd consecutive identical fail -> Trips
        tripped, msg = self.breaker.record_and_evaluate(tool, args, is_error=True)
        self.assertTrue(tripped)
        self.assertIn("CIRCUIT_BREAKER_TRIGGERED", msg)
        self.assertIn("replace_file_content", msg)

    def test_identical_successful_invocations_do_not_trip(self):
        tool = "view_file"
        args = {"AbsolutePath": "src/main.py"}
        for _ in range(5):
            tripped, msg = self.breaker.record_and_evaluate(tool, args, is_error=False)
            self.assertFalse(tripped)
            self.assertEqual(msg, "OK")

    def test_cyclical_oscillation_trips(self):
        args_a = {"command": "cargo test --bin server"}
        args_b = {"command": "cargo test --bin client"}

        # Sequence: A -> B -> A -> B
        self.breaker.record_and_evaluate("run_command", args_a, is_error=True)
        self.breaker.record_and_evaluate("run_command", args_b, is_error=True)
        self.breaker.record_and_evaluate("run_command", args_a, is_error=True)
        tripped, msg = self.breaker.record_and_evaluate("run_command", args_b, is_error=True)

        self.assertTrue(tripped)
        self.assertIn("Cyclical 2-step oscillation detected", msg)


if __name__ == "__main__":
    unittest.main()
