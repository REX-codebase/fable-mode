"""Transactional, allowlisted installation for source and frozen Fable runtimes."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from importlib import metadata, resources
from dataclasses import dataclass
from pathlib import Path

from .manifest import ALLOWED_FILES, allowed_source_paths, source_root, validate_manifest
from .safety import mark_owned_directory, safe_cleanup

PRODUCT = "fable-mode"
MARKER = ".fable-install.json"


class InstallError(RuntimeError):
    pass


def _reject_path(path: Path, *, allow_missing: bool = True) -> None:
    """Reject links, reparse points, special files, and hardlinked leaf files."""
    target = Path(path)
    cur = target
    parts = []
    while True:
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for part in reversed(parts):
        try:
            st = part.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise InstallError(f"missing path: {part}")
        reparse = bool(getattr(st, "st_file_attributes", 0) & 0x400)
        junction = bool(getattr(part, "is_junction", lambda: False)())
        trusted_macos_alias = (
            sys.platform == "darwin" and str(part) in {"/var", "/tmp"}
            and str(part.resolve()) in {"/private/var", "/private/tmp"}
        )
        if ((reparse or junction or stat.S_ISLNK(st.st_mode)) and not trusted_macos_alias) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
            raise InstallError(f"unsafe path component: {part}")
        if part == target and stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
            raise InstallError(f"hardlinked path: {part}")


def _regular_file(path: Path) -> None:
    _reject_path(path, allow_missing=False)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise InstallError(f"not a private regular file: {path}")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capability(path: Path) -> tuple[int, int, int, int]:
    """Capture inode plus ownership for a path that may be renamed later."""
    st = path.lstat()
    return (st.st_dev, st.st_ino, st.st_uid, st.st_gid)


def _matches_capability(path: Path, expected: tuple[int, ...], *, directory: bool = True) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    if directory and not stat.S_ISDIR(st.st_mode):
        return False
    return ((st.st_dev, st.st_ino) == tuple(expected[:2])
            and (len(expected) < 4 or (st.st_uid, st.st_gid) == tuple(expected[2:4])))


# Documentation is intentionally optional in a wheel, but all executable
# runtime resources and the license are mandatory in source-mode installs.
_OPTIONAL_SOURCE_FILES = {"rules/AGENTS.md", "rules/GEMINI.md", "rules/fable-mode.md",
                         "docs/fable-v2-architecture.md", "docs/fable-v1-v2-migration.md"}
_REQUIRED_SOURCE_FILES = tuple(rel for rel in ALLOWED_FILES if rel not in _OPTIONAL_SOURCE_FILES)


def _license_path() -> Path:
    """Locate LICENSE in a checkout, wheel package data, or dist-info.

    Wheels do not have a repository parent, and setuptools commonly stores the
    license under ``*.dist-info/licenses/LICENSE``.  Keep this lookup resource
    based and never derive a path from the process cwd.
    """
    try:
        candidate = resources.files("fable_mode").joinpath("LICENSE")
        if candidate.is_file():
            return Path(candidate)
    except (FileNotFoundError, OSError, TypeError):
        pass
    try:
        dist = metadata.distribution("fable-engine")
        for item in dist.files or ():
            if str(item).replace("\\", "/").lower().endswith("/license") or str(item).lower() == "license":
                candidate = Path(dist.locate_file(item))
                if candidate.is_file():
                    return candidate
    except (metadata.PackageNotFoundError, OSError):
        pass
    raise InstallError("packaged LICENSE resource is unavailable")


def _source_path(root: Path, rel: str) -> Path:
    if rel == "LICENSE":
        checkout = root / rel
        if checkout.is_file():
            return checkout
        return _license_path()
    return root / rel


@dataclass
class InstallResult:
    install_dir: Path
    executable_argv: list[str]
    mode: str
    transaction: "InstallTransaction | None" = None


class InstallTransaction:
    def __init__(self, install_dir: Path, backup_dir: Path | None,
                 install_identity: tuple[int, ...] | None = None,
                 backup_identity: tuple[int, ...] | None = None):
        self.install_dir = install_dir
        self.backup_dir = backup_dir
        self.install_identity = install_identity
        self.backup_identity = backup_identity
        self.done = False

    def _verify_backup(self) -> None:
        if self.backup_dir is None or self.backup_identity is None:
            return
        if not _matches_capability(self.backup_dir, self.backup_identity):
            raise InstallError("previous installation backup was replaced; preserved (partial state)")

    def commit(self) -> None:
        if self.done:
            return
        if self.backup_dir and self.backup_identity is not None:
            try:
                # Never trust a predictable backup pathname: bind cleanup to
                # the inode and owner captured when the old install moved.
                self._verify_backup()
                safe_cleanup(self.backup_dir, expected_identity=self.backup_identity)
            except (OSError, ValueError, InstallError) as exc:
                self.done = True
                raise InstallError("previous installation backup is unsafe; preserved") from exc
        self.done = True

    def rollback(self) -> None:
        if self.done:
            return
        # If the published replacement was itself replaced, do not delete it.
        if (self.install_dir.exists() or self.install_dir.is_symlink()) and not _matches_capability(
                self.install_dir, self.install_identity or (), directory=True):
            self.done = True
            raise InstallError("rollback refused: replacement install path changed; partial state preserved")
        try:
            self._verify_backup()
        except InstallError:
            self.done = True
            raise
        if self.install_identity is not None and self.install_dir.exists():
            try:
                safe_cleanup(self.install_dir, expected_identity=self.install_identity)
            except (OSError, ValueError) as exc:
                self.done = True
                raise InstallError("rollback could not remove published install; partial state preserved") from exc
        if self.backup_dir and self.backup_identity is not None:
            # Revalidate both path capabilities immediately before publication.
            if not _matches_capability(self.backup_dir, self.backup_identity) or self.install_dir.exists():
                self.done = True
                raise InstallError("rollback refused changed backup/install path; partial state preserved")
            try:
                os.replace(self.backup_dir, self.install_dir)
            except OSError as exc:
                self.done = True
                raise InstallError("rollback failed; partial state preserved") from exc
        self.done = True


class Installer:
    def __init__(self, install_dir: Path | None = None, *, source: Path | None = None):
        default = (Path(os.environ["LOCALAPPDATA"]) / "FableMode" if os.name == "nt" and os.environ.get("LOCALAPPDATA")
                   else Path.home() / ".local" / "share" / "fable-mode")
        self.install_dir = Path(install_dir or os.environ.get("FABLE_INSTALL_DIR", default)).expanduser().absolute()
        self.source = Path(source or source_root()).absolute()
        self.previous_registrations: list[dict] = []

    def _assert_install_target(self) -> tuple[int, int, int, int] | None:
        _reject_path(self.install_dir.parent)
        if not self.install_dir.exists() and not self.install_dir.is_symlink():
            return None
        if self.install_dir.is_symlink() or not self.install_dir.is_dir():
            raise InstallError("installation target is not a directory")
        initial_cap = _capability(self.install_dir)
        marker = self.install_dir / MARKER
        _regular_file(marker)
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except Exception as exc:
            raise InstallError("installation marker is invalid") from exc
        if (not isinstance(data, dict) or data.get("product") != PRODUCT
                or data.get("format") != 1 or not isinstance(data.get("files"), dict)):
            raise InstallError("refusing to replace an unmarked directory")
        registrations = data.get("registrations", [])
        self.previous_registrations = registrations if isinstance(registrations, list) else []
        if not _matches_capability(self.install_dir, initial_cap):
            raise InstallError("installation target changed while validating")
        valid, detail = verify_installation(self.install_dir)
        if not valid:
            raise InstallError(f"existing installation is invalid: {detail}")
        if not _matches_capability(self.install_dir, initial_cap):
            raise InstallError("installation target changed while validating")
        return initial_cap

    def _copy_source(self, stage: Path) -> dict[str, str]:
        # Validate the checked-in manifest before copying anything.  This keeps
        # the source and wheel/frozen manifests reviewable and prevents a source
        # override from silently changing the allowlist.
        try:
            manifest_path = self.source / "fable_mode" / "resources.json"
            _regular_file(manifest_path)
            validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise InstallError(f"invalid packaged resource manifest: {exc}") from exc
        seen_casefold: set[str] = set()
        files: dict[str, str] = {}
        for rel in ALLOWED_FILES:
            src = _source_path(self.source, rel)
            rel_path = Path(rel)
            normalized = rel_path.as_posix().casefold()
            if rel_path.is_absolute() or ".." in rel_path.parts or normalized in seen_casefold:
                raise InstallError(f"unsafe or colliding manifest path: {rel}")
            seen_casefold.add(normalized)
            try:
                source_stat = src.lstat()
            except FileNotFoundError:
                if rel.startswith("docs/") or rel.startswith("rules/"):
                    # Documentation is optional in a wheel; runtime files are not.
                    continue
                raise InstallError(f"missing canonical source file: {rel}")
            if stat.S_ISLNK(source_stat.st_mode):
                raise InstallError(f"symlink source entry: {rel}")
            _regular_file(src)
            dst = stage / rel_path
            _reject_path(dst.parent)
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Keep every installer-created subdirectory private even when the
            # process umask is permissive (notably for wheel/frozen installs).
            if os.name != "nt":
                os.chmod(dst.parent, 0o700)
            shutil.copyfile(src, dst, follow_symlinks=False)
            os.chmod(dst, 0o700 if rel == "fable_mode_entry.py" else 0o600)
            files[rel] = _hash(dst)
        wrapper = self.source / "fable_mode_entry.py"
        _regular_file(wrapper)
        dst = stage / "fable_mode_entry.py"
        shutil.copyfile(wrapper, dst, follow_symlinks=False)
        os.chmod(dst, 0o700)
        files["fable_mode_entry.py"] = _hash(dst)
        return files

    def _copy_frozen(self, stage: Path, executable: Path) -> dict[str, str]:
        _regular_file(executable)
        name = "fable-mode.exe" if os.name == "nt" else "fable-mode"
        dst = stage / name
        shutil.copyfile(executable, dst, follow_symlinks=False)
        os.chmod(dst, 0o700)
        return {name: _hash(dst)}

    def install(self, *, frozen_executable: Path | None = None, dry_run: bool = False) -> InstallResult:
        """Publish an installation transactionally; caller may rollback registration."""
        mode = "frozen" if frozen_executable is not None else "source"
        # Dry-run must not inspect or reject an existing application/data
        # directory: platform runtimes may already have created the parent.
        # It performs no filesystem or host operation beyond computing paths.
        if dry_run:
            if frozen_executable:
                argv = [str(frozen_executable), "serve"]
            else:
                argv = [sys.executable, str(self.install_dir / "runtime" / "fable_mode_entry.py"), "serve"]
            return InstallResult(self.install_dir, argv, mode, None)
        original_identity = self._assert_install_target()
        parent = self.install_dir.parent
        _reject_path(parent)
        parent.mkdir(parents=True, exist_ok=True)
        _reject_path(parent)
        stage_dir: Path | None = None
        backup: Path | None = None
        try:
            stage_dir = Path(tempfile.mkdtemp(prefix=f".{PRODUCT}.stage-", dir=str(parent)))
            mark_owned_directory(stage_dir)
            os.chmod(stage_dir, 0o700)
            runtime = stage_dir / "runtime" if mode == "source" else stage_dir
            if mode == "source":
                runtime.mkdir(mode=0o700)
            files = self._copy_frozen(runtime, Path(frozen_executable)) if frozen_executable else self._copy_source(runtime)
            # Carry prior registration ownership across replacement.  This
            # prevents install-without-registration from orphaning an entry
            # that still points at the retired runtime.
            stage_identity = _capability(stage_dir)
            migrated_records: list[dict] = []
            for prior in self.previous_registrations:
                if isinstance(prior, dict):
                    record = dict(prior)
                    record["install_dir"] = str(self.install_dir)
                    # Marker records historically bind the install directory
                    # to its device/inode pair (not uid/gid capability fields).
                    record["install_identity"] = [stage_identity[0], stage_identity[1]]
                    migrated_records.append(record)
            marker = {"product": PRODUCT, "format": 1, "mode": mode, "files": files,
                      "registrations": migrated_records}
            marker_path = stage_dir / MARKER
            fd = os.open(marker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(marker, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if original_identity is not None:
                # Revalidate the preflight capability immediately before the
                # destructive rename.  In particular, never mark/own whatever
                # happens to occupy the current pathname at this point.
                if not _matches_capability(self.install_dir, original_identity):
                    raise InstallError("installation target changed; replacement preserved")
                for _ in range(10):
                    candidate = parent / f".{PRODUCT}.previous-{uuid.uuid4().hex}"
                    if not candidate.exists() and not candidate.is_symlink():
                        backup = candidate
                        break
                if backup is None:
                    raise InstallError("could not allocate a unique backup path")
                os.replace(self.install_dir, backup)
                if not _matches_capability(backup, original_identity):
                    raise InstallError("backup identity changed; replacement not published")
            else:
                # A target that appeared after preflight must not be silently
                # overwritten by the staged replacement.
                if self.install_dir.exists() or self.install_dir.is_symlink():
                    raise InstallError("installation target appeared; replacement preserved")
            os.replace(stage_dir, self.install_dir)
            # The stage inode is the cleanup capability.  Do not mark/own the
            # current pathname afresh after publication.
            if not _matches_capability(self.install_dir, stage_identity):
                raise InstallError("published installation identity changed")
            install_identity = stage_identity
            backup_identity = original_identity
            stage_dir = None
            if mode == "frozen":
                exe = self.install_dir / ("fable-mode.exe" if os.name == "nt" else "fable-mode")
                argv = [str(exe), "serve"]
            else:
                argv = [sys.executable, str(self.install_dir / "runtime" / "fable_mode_entry.py"), "serve"]
            return InstallResult(self.install_dir, argv, mode,
                                 InstallTransaction(self.install_dir, backup, install_identity, backup_identity))
        except Exception as exc:
            if stage_dir is not None:
                try:
                    safe_cleanup(stage_dir)
                except (OSError, ValueError):
                    pass
            if backup and backup.exists() and not self.install_dir.exists():
                if original_identity is not None and _matches_capability(backup, original_identity):
                    try:
                        os.replace(backup, self.install_dir)
                    except OSError as restore_exc:
                        raise InstallError("installation failed; old install could not be restored (partial state)") from restore_exc
                elif original_identity is not None:
                    raise InstallError("installation failed; backup was replaced and old install is preserved as partial state") from exc
            if isinstance(exc, InstallError):
                raise
            raise InstallError(f"installation failed: {exc}") from exc

    def record_registrations(self, records: list[dict]) -> None:
        """Persist registrations created by this install for guarded cleanup."""
        marker = self.install_dir / MARKER
        _regular_file(marker)
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["registrations"] = records
        fd, temp_name = tempfile.mkstemp(prefix=f".{MARKER}.", dir=str(self.install_dir))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, marker)
        finally:
            if temp.exists(): temp.unlink()

    def uninstall(self, *, dry_run: bool = False) -> bool:
        identity = self._assert_install_target()
        if dry_run:
            return True
        if identity is None:
            return True
        valid, detail = verify_installation(self.install_dir)
        if not valid:
            raise InstallError(f"installation manifest/tree is invalid: {detail}")
        try:
            try:
                marker_data = json.loads((self.install_dir / MARKER).read_text(encoding="utf-8"))
                from .adapters import cleanup_recorded_registrations
                skipped = cleanup_recorded_registrations(
                    marker_data.get("registrations", []), strict=True,
                    install_dir=self.install_dir, home=Path.home())
                if skipped:
                    # A host/config mismatch is intentionally non-fatal: the
                    # install tree can still be removed, but user changes are
                    # retained and made visible to an interactive caller.
                    print("uninstall: registration mismatch; preserved " + ", ".join(skipped), file=sys.stderr)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            safe_cleanup(self.install_dir, expected_identity=identity)
        except (OSError, ValueError) as exc:
            raise InstallError("refusing to remove an unsafe installation directory") from exc
        return True


def verify_installation(install_dir: Path) -> tuple[bool, str]:
    """Verify marker hashes and reject links/extra path traversal in the manifest."""
    install_dir = Path(install_dir)
    marker = install_dir / MARKER
    try:
        _regular_file(marker)
        data = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("product") != PRODUCT or data.get("format") != 1:
            return False, "wrong installation marker"
        files = data.get("files")
        if not isinstance(files, dict):
            return False, "invalid file manifest"
        mode = data.get("mode")
        if mode == "source":
            expected_names = set(_REQUIRED_SOURCE_FILES) | {"fable_mode_entry.py"}
            # Optional docs/rules are included when present in a source tree,
            # but are never allowed to replace or omit runtime resources.
            expected_names.update(name for name in files if name in _OPTIONAL_SOURCE_FILES)
        elif mode == "frozen":
            expected_names = {"fable-mode.exe" if os.name == "nt" else "fable-mode"}
        else:
            return False, "unknown installation mode"
        if set(files) != expected_names:
            return False, "installation manifest does not match the canonical mode manifest"
        names: set[str] = set()
        if os.name != "nt" and stat.S_IMODE(install_dir.stat().st_mode) & 0o077:
            return False, "installation directory is not private"
        for rel, expected in files.items():
            rel_path = Path(rel)
            folded = rel_path.as_posix().casefold()
            if rel_path.is_absolute() or ".." in rel_path.parts or folded in names:
                return False, "unsafe or colliding path in manifest"
            names.add(folded)
            p = install_dir / ("runtime" / rel_path if mode == "source" else rel_path)
            _regular_file(p)
            if not isinstance(expected, str) or _hash(p) != expected:
                return False, f"hash mismatch: {rel}"
        # Enumerate the complete install tree.  Hashing listed files alone
        # would allow an attacker to leave executable/configuration extras
        # beside an otherwise valid installation.
        expected_files = {MARKER}
        expected_files.update(("runtime/" + name) if mode == "source" else name for name in files)
        expected_dirs = set()
        for rel in expected_files:
            parent = Path(rel).parent
            while str(parent) not in {"", "."}:
                expected_dirs.add(parent.as_posix())
                parent = parent.parent
        seen_files: set[str] = set()
        seen_dirs: set[str] = set()
        for root, dirs, names in os.walk(install_dir, topdown=True, followlinks=False):
            root_path = Path(root)
            for name in dirs:
                child = root_path / name
                st = child.lstat()
                if (stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode)
                        or (os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077)):
                    return False, "unsafe installation tree node"
                seen_dirs.add(child.relative_to(install_dir).as_posix())
            for name in names:
                child = root_path / name
                _regular_file(child)
                seen_files.add(child.relative_to(install_dir).as_posix())
        if seen_files != expected_files or seen_dirs != expected_dirs:
            return False, "installation tree contains unexpected or missing entries"
        if mode == "source":
            resources_path = install_dir / "runtime" / "fable_mode" / "resources.json"
            _regular_file(resources_path)
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
            validate_manifest(resources)
        return True, "ok"
    except (OSError, ValueError, TypeError, InstallError, json.JSONDecodeError) as exc:
        return False, str(exc)
