import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fable_mode.safety import mark_owned_directory, safe_cleanup


class CleanupRegressionTests(unittest.TestCase):
    def test_cleanup_never_targets_cwd_or_repository(self):
        repo = Path(__file__).resolve().parents[1]
        cwd = Path.cwd().resolve()
        with patch("fable_mode.safety.shutil.rmtree") as rmtree:
            safe_cleanup(None)
            with self.assertRaises(ValueError):
                safe_cleanup(Path("."))
            with self.assertRaises(ValueError):
                safe_cleanup(cwd)
            with self.assertRaises(ValueError):
                safe_cleanup(repo)
        rmtree.assert_not_called()

    def test_cleanup_only_removes_explicit_temp_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            stage = Path(parent) / f".fable-mode.stage-{uuid.uuid4().hex}"
            stage.mkdir()
            (stage / "marker").write_text("x", encoding="utf-8")
            mark_owned_directory(stage)
            safe_cleanup(stage)
            self.assertFalse(stage.exists())

    def test_cleanup_refuses_parent_and_preexisting_backup(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            backup = root / ".fable-mode.previous-preexisting"
            backup.mkdir()
            (backup / "keep").write_text("do not delete", encoding="utf-8")
            for unsafe in (root, root.parent, backup):
                with self.assertRaises(ValueError):
                    safe_cleanup(unsafe)
            self.assertTrue((backup / "keep").exists())


if __name__ == "__main__":
    unittest.main()
