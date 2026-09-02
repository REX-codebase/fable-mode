"""Regression test for the repository documentation and API drift checks."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


CANONICAL_V1_COMMAND = "python -m unittest discover -s tests -p 'test_server*.py' -v"


ROOT = Path(__file__).resolve().parents[1]


class DocumentationChecks(unittest.TestCase):
    def test_documentation_checker_passes(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "docs" / "check_docs.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Documentation checks passed", result.stdout)

    def test_readme_command_and_manifest_match_ci_and_source(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertEqual(readme.count(CANONICAL_V1_COMMAND), 1)
        self.assertIn(CANONICAL_V1_COMMAND, workflow)
        self.assertNotIn("python fable_engine/test_server.py", readme)

        manifest = json.loads((ROOT / "fable_mode" / "resources.json").read_text(encoding="utf-8"))
        from fable_mode.manifest import ALLOWED_FILES
        self.assertEqual(manifest["files"], list(ALLOWED_FILES))
        self.assertTrue({
            "fable_v2/system3/__init__.py",
            "fable_v2/system3/causal.py",
            "fable_v2/system3/dialectical.py",
            "fable_v2/system3/evolution.py",
            "fable_v2/system3/executive.py",
            "fable_v2/system3/free_energy.py",
            "fable_v2/system3/hyperbolic.py",
            "fable_v2/system3/induction.py",
            "fable_v2/system3/kripke.py",
            "fable_v2/system3/oracle.py",
        } <= set(manifest["files"]), "manifest must ship the complete System 3 package")


if __name__ == "__main__":
    unittest.main()
