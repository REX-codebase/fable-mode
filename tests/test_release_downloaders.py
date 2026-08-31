import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDownloaderStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.macos = (ROOT / "download-macos.sh").read_text(encoding="utf-8")
        cls.windows = (ROOT / "download-windows.ps1").read_text(encoding="utf-8")
        cls.workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_macos_is_network_free_of_python_and_shell_eval(self):
        self.assertIn("set -eu", self.macos)
        self.assertIn("plutil", self.macos)
        self.assertIn("shasum -a 256 -c", self.macos)
        self.assertNotRegex(self.macos, r"\bpython(?:3)?\b")
        self.assertNotRegex(self.macos, r"\beval\b|\bsource\b|\bexec\b")
        self.assertIn("trap cleanup EXIT HUP INT TERM", self.macos)

    def test_downloaders_verify_before_extract_and_use_expected_names(self):
        self.assertLess(self.macos.index("shasum -a 256 -c"), self.macos.index("unzip -q \"$ARCHIVE_FILE\""))
        self.assertLess(self.windows.index("Get-FileHash"), self.windows.index("Expand-Archive"))
        self.assertIn("fable-mode-${TAG}-macos-${ARCH}", self.macos)
        self.assertIn('fable-mode-$tag-windows-x86_64.zip', self.windows)
        self.assertIn("SHA256SUMS", self.macos)
        self.assertIn("SHA256SUMS", self.windows)
        self.assertNotRegex(self.windows, r"Invoke-Expression|\bIEX\b")

    def test_workflow_and_readme_list_the_same_release_targets(self):
        for artifact in (
            "windows-x86_64",
            "macos-x86_64",
            "macos-arm64",
            "linux-x86_64",
        ):
            self.assertIn(f"artifact: {artifact}", self.workflow)
            self.assertIn(artifact, self.readme)
        self.assertIn("os: macos-14", self.workflow)
        self.assertIn("fable-mode-vX.Y.Z-macos-arm64.zip", self.readme)
        self.assertIn("SHA256SUMS", self.readme)
        self.assertIn("unsigned binaries", self.readme)
        self.assertIn("notarization", self.readme)

    def test_scripts_have_no_unquoted_download_path_as_shell_code(self):
        # API and asset values must be quoted when passed to curl; this is a
        # deliberately small regression guard for shell-injection mistakes.
        self.assertNotRegex(self.macos, r"curl[^\n]*\$asset_url[^\n]*[^\"]\$asset_url")
        self.assertIn('"$archive_url"', self.macos)
        self.assertIn('"$sums_url"', self.macos)


if __name__ == "__main__":
    unittest.main()
