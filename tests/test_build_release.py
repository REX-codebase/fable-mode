import os
import unittest
from unittest.mock import patch

from build_scripts.build_release import validate_tag_version


class ReleaseVersionTests(unittest.TestCase):
    def test_tag_matches_package_version_with_v_prefix(self):
        self.assertEqual(validate_tag_version("v1.2.0"), "1.2.0")

    def test_mismatched_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_tag_version("v9.9.9")

    def test_environment_tag_is_validated(self):
        with patch.dict(os.environ, {"FABLE_VERSION": "1.2.0"}, clear=False):
            self.assertEqual(validate_tag_version(), "1.2.0")
        with patch.dict(os.environ, {"FABLE_VERSION": "1.2.1"}, clear=False):
            with self.assertRaises(ValueError):
                validate_tag_version()


if __name__ == "__main__":
    unittest.main()
