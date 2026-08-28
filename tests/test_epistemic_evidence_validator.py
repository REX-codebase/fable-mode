import unittest
import tempfile
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import EpistemicEvidenceValidator


class TestEpistemicEvidenceValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temp_dir.name)
        self.validator = EpistemicEvidenceValidator(workspace_root=self.workspace_root)

        # Create dummy file with 5 lines
        self.test_file = self.workspace_root / "sample.py"
        self.test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_evidence_rejected(self):
        valid, msg = self.validator.validate_proven_claim("Some claim", "")
        self.assertFalse(valid)
        self.assertIn("explicit evidence string", msg)

    def test_command_output_evidence_accepted(self):
        evidence_samples = [
            "python --version stdout: Python 3.12.4",
            "pytest output: 15 passed, 0 failed",
            "exit code 0 from cargo test --all",
            "benchmark output: 1.2 us latency"
        ]
        for ev in evidence_samples:
            valid, msg = self.validator.validate_proven_claim("System property", ev)
            self.assertTrue(valid, f"Failed for {ev}: {msg}")

    def test_url_citation_accepted(self):
        valid, msg = self.validator.validate_proven_claim("Docs link", "https://docs.python.org/3/library/asyncio.html")
        self.assertTrue(valid)

    def test_existing_file_valid_line_accepted(self):
        ev = f"{self.test_file}:L3"
        valid, msg = self.validator.validate_proven_claim("Code invariant", ev)
        self.assertTrue(valid, msg)

    def test_existing_file_out_of_bounds_line_rejected(self):
        ev = f"{self.test_file}:L99"
        valid, msg = self.validator.validate_proven_claim("Code invariant", ev)
        self.assertFalse(valid)
        self.assertIn("exceeds total lines", msg)

    def test_non_existent_file_rejected(self):
        ev = str(self.workspace_root / "does_not_exist.py:L1")
        valid, msg = self.validator.validate_proven_claim("Fake file", ev)
        self.assertFalse(valid)
        self.assertIn("does not exist on disk", msg)


if __name__ == "__main__":
    unittest.main()
