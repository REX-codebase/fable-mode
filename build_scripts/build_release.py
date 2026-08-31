"""Build one truthful, architecture-specific self-contained Fable artifact."""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Running this file directly puts ``build_scripts`` (not the project root) on
# sys.path.  Make version validation and the PyInstaller spec import the
# checkout's packages exactly as they do in a clean CI runner.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_VERSION_RE = re.compile(r"^version\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_SETUP_VERSION_RE = re.compile(r"version\s*=\s*[\"']([^\"']+)[\"']")


def _machine() -> str:
    machine = platform.machine().lower().replace(" ", "-")
    return {"amd64": "x86_64", "x64": "x86_64", "x86-64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def _package_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    match = _VERSION_RE.search(pyproject)
    setup_match = _SETUP_VERSION_RE.search(setup)
    if not match or not setup_match:
        raise ValueError("could not determine package version from pyproject.toml/setup.py")
    pyproject_version = match.group(1)
    setup_version = setup_match.group(1)
    try:
        from fable_mode import __version__
    except ImportError as exc:
        raise ValueError("could not determine fable_mode.__version__") from exc
    if len({pyproject_version, setup_version, __version__}) != 1:
        raise ValueError("package version mismatch between pyproject.toml, setup.py, and fable_mode.__version__")
    return pyproject_version


def _tag_version(tag: str) -> str:
    value = tag.strip()
    if value.startswith("v"):
        value = value[1:]
    if not value or any(c in value for c in "/\\ \t\r\n"):
        raise ValueError(f"invalid release tag: {tag!r}")
    return value


def validate_tag_version(tag: str | None = None) -> str:
    """Require an optional release tag/version to equal the package version."""
    package_version = _package_version()
    supplied = tag if tag is not None else (os.environ.get("FABLE_VERSION") or os.environ.get("GITHUB_REF_NAME"))
    if supplied:
        if _tag_version(supplied) != package_version:
            raise ValueError(f"release tag/version {supplied!r} does not match package version {package_version!r}")
    return package_version


def archive_name() -> str:
    supplied = os.environ.get("FABLE_VERSION", os.environ.get("GITHUB_REF_NAME"))
    version = supplied.replace("/", "-") if supplied else "dev"
    system = platform.system().lower()
    machine = _machine()
    if system == "windows":
        return f"fable-mode-{version}-windows-{machine}.zip"
    if system == "darwin":
        return f"fable-mode-{version}-macos-{machine}.zip"
    return f"fable-mode-{version}-linux-{machine}.tar.gz"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "pyinstaller")
    args = ap.parse_args()
    # Validate before creating output or invoking PyInstaller.  CI tags include
    # their leading ``v`` while package metadata uses the bare semver.
    try:
        validate_tag_version()
    except (OSError, ValueError) as exc:
        print(f"release build: {exc}", file=sys.stderr)
        return 2
    args.dist = args.dist.absolute()
    args.work = args.work.absolute()
    args.dist.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    spec = ROOT / "packaging" / "fable_mode.spec"
    subprocess.run(["pyinstaller", "--noconfirm", "--clean", "--distpath", str(args.dist), "--workpath", str(args.work), str(spec)], cwd=ROOT, check=True)
    exe = args.dist / ("fable-mode.exe" if os.name == "nt" else "fable-mode")
    if not exe.is_file():
        raise SystemExit(f"PyInstaller did not produce {exe}")
    archive = args.dist / archive_name()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, exe.name)
    else:
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(exe, arcname=exe.name, recursive=False)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.dist / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
