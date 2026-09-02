import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from build_scripts.build_release import archive_name, validate_tag_version
from fable_mode import __version__


class ReleaseVersionTests(unittest.TestCase):
    def test_tag_matches_package_version_with_v_prefix(self):
        self.assertEqual(validate_tag_version(f"v{__version__}"), __version__)

    def test_mismatched_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_tag_version("v9.9.9")

    def test_environment_tag_is_validated(self):
        with patch.dict(os.environ, {"FABLE_VERSION": __version__}, clear=False):
            self.assertEqual(validate_tag_version(), __version__)
        with patch.dict(os.environ, {"FABLE_VERSION": "9.9.9"}, clear=False):
            with self.assertRaises(ValueError):
                validate_tag_version()

    def test_server_runtime_metadata_matches_package_version(self):
        source = Path(__file__).resolve().parents[1] / "fable_engine" / "server.py"
        versions = re.findall(r'"version"\s*:\s*"([^"]+)"', source.read_text(encoding="utf-8"))
        self.assertEqual(versions, [__version__, __version__])

    def test_archive_names_use_bare_package_version(self):
        with patch.dict(os.environ, {"FABLE_VERSION": f"v{__version__}"}, clear=False):
            name = archive_name()
        self.assertIn(f"fable-mode-{__version__}-", name)
        self.assertNotIn(f"fable-mode-v{__version__}-", name)


if __name__ == "__main__":
    unittest.main()
