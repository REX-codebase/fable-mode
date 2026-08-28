import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import DelegationContractCompiler


class TestDelegationContractCompiler(unittest.TestCase):
    def setUp(self):
        self.compiler = DelegationContractCompiler()

    def test_vague_prompt_fails_all_checks(self):
        prompt = "Hey please implement the payment gateway and test it."
        valid, errors, parsed = self.compiler.compile_and_validate(prompt)
        self.assertFalse(valid)
        self.assertEqual(len(errors), 4)
        self.assertTrue(any("TargetFile" in e for e in errors))
        self.assertTrue(any("VerificationCommand" in e for e in errors))
        self.assertTrue(any("InterfaceContract" in e for e in errors))
        self.assertTrue(any("StrictConstraints" in e for e in errors))

    def test_valid_delegation_contract_passes(self):
        prompt = """
        ### SUBAGENT DELEGATION CONTRACT
        - TargetFile: src/payment/gateway.py
        - InterfaceContract: def process_charge(amount_cents: int, token: str) -> PaymentResult
        - StrictConstraints: Zero-alloc hot path, no network blocking, idempotent retry key
        - VerificationCommand: pytest tests/test_payment.py -v
        """
        valid, errors, parsed = self.compiler.compile_and_validate(prompt)
        self.assertTrue(valid, f"Unexpected errors: {errors}")
        self.assertEqual(len(errors), 0)
        self.assertEqual(parsed.get("TargetFile"), "src/payment/gateway.py")
        self.assertEqual(parsed.get("VerificationCommand"), "pytest tests/test_payment.py -v")

    def test_missing_verification_command_fails(self):
        prompt = """
        ### SUBAGENT DELEGATION CONTRACT
        - TargetFile: src/utils/math.py
        - InterfaceContract: def add(a: int, b: int) -> int
        - StrictConstraints: Pure function, zero side-effects
        """
        valid, errors, parsed = self.compiler.compile_and_validate(prompt)
        self.assertFalse(valid)
        self.assertTrue(any("VerificationCommand" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
