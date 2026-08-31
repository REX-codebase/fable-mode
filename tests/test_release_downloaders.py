import re
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
        self.assertIn("os: macos-15-intel", self.workflow)
        self.assertNotIn("os: macos-13", self.workflow)
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

    def test_windows_smoke_test_avoids_powershell_automatic_home_variable(self):
        # PowerShell variable names are case-insensitive; assigning $home
        # attempts to overwrite the runner's read-only $HOME automatic variable.
        start = self.workflow.index("Frozen executable smoke test (Windows)")
        end = self.workflow.index("Publish per-artifact archive", start)
        windows = self.workflow[start:end]
        self.assertNotRegex(windows, r"(?im)^\s*\$home\s*=")
        self.assertRegex(windows, r"(?im)^\s*\$smokeHome\s*=")
        self.assertNotIn("$home", windows)

    def test_quick_download_links_are_explicit_and_match_workflow_aliases(self):
        # Read the links as plain text only: this test deliberately performs no
        # HTTP requests and must remain safe to run offline.
        links = set(re.findall(r"https://[^)\s]+", self.readme))
        script_urls = {
            "https://raw.githubusercontent.com/REX-codebase/fable-mode/main/download-windows.ps1",
            "https://raw.githubusercontent.com/REX-codebase/fable-mode/main/download-macos.sh",
        }
        release_urls = {
            "https://github.com/REX-codebase/fable-mode/releases/latest/download/fable-mode-windows-x86_64.zip",
            "https://github.com/REX-codebase/fable-mode/releases/latest/download/fable-mode-macos-x86_64.zip",
            "https://github.com/REX-codebase/fable-mode/releases/latest/download/fable-mode-macos-arm64.zip",
            "https://github.com/REX-codebase/fable-mode/releases/latest/download/fable-mode-linux-x86_64.tar.gz",
            "https://github.com/REX-codebase/fable-mode/releases/latest/download/SHA256SUMS",
        }
        self.assertTrue(script_urls <= links)
        self.assertTrue(release_urls <= links)
        self.assertIn("available from the `main` branch now", self.readme)
        self.assertIn("only after a tagged release has completed successfully", self.readme)

        aliases = (
            "fable-mode-windows-x86_64.zip",
            "fable-mode-macos-x86_64.zip",
            "fable-mode-macos-arm64.zip",
            "fable-mode-linux-x86_64.tar.gz",
        )
        for alias in aliases:
            self.assertIn(f"|{alias}", self.workflow)
        self.assertIn("sha256sum -- *.zip *.tar.gz > SHA256SUMS", self.workflow)
        self.assertNotIn("cat release/*/SHA256SUMS", self.workflow)


if __name__ == "__main__":
    unittest.main()
