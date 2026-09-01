"""Package-aware command line entry point for the portable Fable runtime."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .adapters import (RegistrationError, cleanup_recorded_registrations,
                       detect_hosts, register_hosts, validate_registration_record)
from .installer import Installer, InstallError, verify_installation
from .manifest import ALLOWED_FILES, validate_manifest
from . import __version__


def _assert_private_path(path: Path) -> None:
    cur = path
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
            continue
        attrs = int(getattr(st, "st_file_attributes", 0))
        reparse = bool(attrs & 0x400)
        junction = bool(getattr(part, "is_junction", lambda: False)())
        trusted_macos_alias = (
            sys.platform == "darwin" and str(part) in {"/var", "/tmp"}
            and str(part.resolve()) in {"/private/var", "/private/tmp"}
        )
        if ((reparse or junction or stat.S_ISLNK(st.st_mode)) and not trusted_macos_alias) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
            raise RuntimeError("state path contains a symlink, reparse point, or special file")


def _data_dir(state_dir: str | None) -> Path:
    if state_dir:
        path = Path(state_dir).expanduser().absolute()
    elif os.environ.get("FABLE_DATA_DIR"):
        path = Path(os.environ["FABLE_DATA_DIR"]).expanduser().absolute()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        path = Path(os.environ["LOCALAPPDATA"]) / "FableMode" / "data"
    else:
        path = Path.home() / ".local" / "share" / "fable-mode" / "data"
    # Do not follow an attacker-controlled final directory or parent.
    _assert_private_path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        _assert_private_path(path)
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError("state directory must be a real directory")
        os.chmod(path, 0o700)
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("could not create the state directory") from exc
    return path


def serve(state_dir: str | None = None) -> int:
    data = _data_dir(state_dir)
    os.environ["FABLE_DATA_DIR"] = str(data)
    server = importlib.import_module("fable_engine.server")
    server.main()
    return 0


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            # CREATE_NEW_PROCESS_GROUP is used below.  Terminate the direct
            # child; Windows Job Objects are not available in stdlib, so this
            # fallback deliberately fails safe rather than invoking a shell.
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _smoke(argv: list[str], data_dir: Path) -> tuple[bool, str]:
    """Bounded MCP initialize/tools-list probe with a sanitized environment."""
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        return False, "MCP smoke check received invalid argv"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    probe_home = Path(tempfile.mkdtemp(prefix="fable-mcp-home-"))
    os.chmod(probe_home, 0o700)
    def finish(value: tuple[bool, str]) -> tuple[bool, str]:
        import shutil
        shutil.rmtree(probe_home, ignore_errors=True)
        return value
    env = {
        "PATH": os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent), os.defpath])),
        "HOME": str(probe_home),
        "USERPROFILE": str(probe_home),
        "XDG_CONFIG_HOME": str(probe_home / ".config"),
        "FABLE_DATA_DIR": str(data_dir),
        "PYTHONIOENCODING": "utf-8",
    }
    if os.name == "nt":
        for var in ("SystemRoot", "SYSTEMROOT", "windir", "PATHEXT", "TEMP", "TMP"):
            if var in os.environ:
                env[var] = os.environ[var]
    kwargs: dict = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": env, "cwd": str(data_dir)}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc: subprocess.Popen[bytes] | None = None
    captured = {"out": bytearray(), "err": bytearray()}
    def drain(pipe, key: str) -> None:
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    return
                remaining = 32768 - len(captured[key])
                if remaining > 0:
                    captured[key].extend(chunk[:remaining])
        finally:
            pipe.close()
    try:
        proc = subprocess.Popen(argv, **kwargs)
        request = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n" +
                   json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n").encode()
        assert proc.stdin is not None
        proc.stdin.write(request)
        proc.stdin.flush()
        proc.stdin.close()
        readers = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
        for reader in readers:
            reader.start()

        def _has_responses() -> bool:
            lines = bytes(captured["out"]).splitlines()[:8]
            seen_ids = set()
            for line in lines:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict) and "id" in item:
                        seen_ids.add(item["id"])
                except Exception:
                    pass
            return {1, 2}.issubset(seen_ids)

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if _has_responses() or proc.poll() is not None:
                break
            time.sleep(0.05)

        if proc.poll() is None:
            _kill_process(proc)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        for reader in readers:
            reader.join(timeout=2)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if proc is not None:
            _kill_process(proc)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        return finish((False, "MCP smoke check failed: bounded process probe did not complete"))
    # Never echo untrusted process output.  JSON parsing is intentionally capped.
    lines = bytes(captured["out"]).splitlines()[:8]
    messages = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return finish((False, "MCP smoke check returned invalid JSON"))
        if not isinstance(item, dict) or item.get("jsonrpc") != "2.0" or "id" not in item:
            return finish((False, "MCP smoke check returned an invalid JSON-RPC envelope"))
        if "result" not in item or not isinstance(item["result"], dict) or "error" in item:
            return finish((False, "MCP smoke check returned no valid result"))
        messages.append(item)
    ids = {m.get("id") for m in messages}
    if {1, 2} - ids:
        return finish((False, "MCP smoke check did not receive initialize/tools-list responses"))
    by_id = {m["id"]: m for m in messages}
    if not isinstance(by_id[1]["result"].get("protocolVersion"), str):
        return finish((False, "MCP initialize response is missing protocolVersion"))
    if not isinstance(by_id[2]["result"].get("tools"), list):
        return finish((False, "MCP tools/list response is missing tools"))
    return finish((True, "ok"))


def _verify_packaged_manifest() -> tuple[bool, str]:
    try:
        from importlib.resources import files
        payload = json.loads((files("fable_mode") / "resources.json").read_text(encoding="utf-8"))
        validate_manifest(payload)
        return True, "ok"
    except Exception as exc:
        return False, f"packaged resource manifest unavailable: {exc}"


def verify(installer: Installer) -> int:
    packaged_ok, packaged_detail = _verify_packaged_manifest()
    if not packaged_ok:
        print(f"verify: {packaged_detail}", file=sys.stderr)
        return 1
    ok, detail = verify_installation(installer.install_dir)
    if not ok:
        print(f"verify: {detail}", file=sys.stderr)
        return 1
    marker = json.loads((installer.install_dir / ".fable-install.json").read_text(encoding="utf-8"))
    if marker.get("mode") == "source":
        argv = [sys.executable, str(installer.install_dir / "runtime" / "fable_mode_entry.py"), "serve"]
    else:
        name = "fable-mode.exe" if os.name == "nt" else "fable-mode"
        argv = [str(installer.install_dir / name), "serve"]
    with tempfile.TemporaryDirectory(prefix="fable-verify-") as tmp:
        ok, detail = _smoke(argv, Path(tmp) / "data")
    if not ok:
        print(f"verify: {detail}", file=sys.stderr)
        return 1
    print("Fable installation verified (manifest + MCP initialize/tools-list).")
    return 0


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fable-mode")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("mode", nargs="?", choices=("install", "serve", "verify", "version", "uninstall"), default="install")
    p.add_argument("--yes", action="store_true", help="confirm unattended installation")
    p.add_argument("--register-hosts", action="store_true")
    p.add_argument("--aliases", action="store_true", help="also probe legacy cc/antigravity aliases")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--state-dir")
    p.add_argument("--install-dir")
    p.add_argument("--workspace")
    return p


def _bind_registration_records(records: list[dict], install_dir: Path,
                               workspace: Path | None) -> None:
    """Bind host snapshots to this exact published install before persistence."""
    install_st = install_dir.lstat()
    if not stat.S_ISDIR(install_st.st_mode):
        raise RuntimeError("published installation is not a directory")
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("host registration produced an invalid recovery record")
        record["install_dir"] = str(install_dir)
        record["install_identity"] = [install_st.st_dev, install_st.st_ino]
        if record.get("kind") == "file" and Path(record.get("path", "")).parent.name == ".agents":
            record["workspace"] = str(workspace) if workspace else ""
        if not validate_registration_record(record, install_dir, Path.home(), transaction=True):
            raise RuntimeError("host registration produced an invalid recovery record")


def _records_for_marker(install_dir: Path, records: list[dict]) -> list[dict]:
    """Merge new records with still-owned records already in the marker."""
    marker_data = json.loads((install_dir / ".fable-install.json").read_text(encoding="utf-8"))
    prior_records = [record for record in marker_data.get("registrations", [])
                     if isinstance(record, dict)]
    new_keys = {(record.get("kind"), record.get("host", record.get("path")))
                for record in records}
    retained = [record for record in prior_records
                if (record.get("kind"), record.get("host", record.get("path"))) not in new_keys]
    return retained + records


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.mode == "version":
        print(__version__)
        return 0
    if args.mode == "serve":
        try:
            return serve(args.state_dir)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"serve: {exc}", file=sys.stderr)
            return 1
    installer = Installer(Path(args.install_dir) if args.install_dir else None)
    if args.mode == "verify":
        return verify(installer)
    if args.mode == "uninstall":
        if not args.dry_run and not args.yes and not sys.stdin.isatty():
            print("uninstall requires --yes in unattended mode", file=sys.stderr)
            return 2
        try:
            installer.uninstall(dry_run=args.dry_run)
            print("Fable installation removed." if not args.dry_run else "Would remove Fable installation.")
            return 0
        except InstallError as exc:
            print(f"uninstall: {exc}", file=sys.stderr)
            return 1
    if not args.dry_run and not (args.yes or args.register_hosts) and not sys.stdin.isatty():
        print("install requires --yes or --register-hosts in unattended mode", file=sys.stderr)
        return 2
    if not args.dry_run and sys.stdin.isatty() and not (args.yes or args.register_hosts):
        if input(f"Install Fable to {installer.install_dir}? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Installation cancelled.")
            return 0
    registration_workspace: Path | None = None
    try:
        frozen = Path(sys.executable) if _is_frozen() else None
        result = installer.install(frozen_executable=frozen, dry_run=args.dry_run)
        if args.dry_run:
            print(f"Would install Fable to {result.install_dir}; hosts are not probed.")
            return 0
        statuses = {}
        registration_records: list[dict] = []
        if args.register_hosts:
            hosts = detect_hosts(aliases=args.aliases)
            if sys.stdin.isatty() and not args.yes:
                found = ", ".join(sorted(hosts)) or "none"
                print(f"Detected host commands: {found}")
                if input("Register Fable with these hosts? [y/N] ").strip().lower() not in {"y", "yes"}:
                    if result.transaction:
                        result.transaction.rollback()
                    print("Host registration cancelled.")
                    return 0
            registration_workspace = Path(args.workspace).absolute() if args.workspace else None
            statuses = register_hosts(hosts, result.executable_argv, workspace=registration_workspace,
                                      records=registration_records,
                                      owned_records=installer.previous_registrations)
            if registration_records:
                # Bind and validate marker records against this exact
                # installation.  Workspace config paths are also recorded
                # explicitly so uninstall never accepts an arbitrary path from
                # a marker.
                _bind_registration_records(registration_records, result.install_dir,
                                           registration_workspace)
                # Keep ownership records for previously registered hosts that
                # are now absent/unhealthy; otherwise a reinstall would orphan
                # those old entries.  Records for hosts touched successfully by
                # this transaction are replaced by the new exact snapshots.
                installer.record_registrations(
                    _records_for_marker(result.install_dir, registration_records))
        if result.transaction:
            result.transaction.commit()
        print(f"Fable installed at {result.install_dir}")
        if statuses:
            print(json.dumps(statuses, sort_keys=True))
        return 0
    except Exception as exc:
        # Host mutation and installation publication form one transaction.  A
        # marker write or backup commit can fail *after* register_hosts has
        # successfully changed one or more hosts, so restore those hosts before
        # removing the runtime they now reference.  If restoration is not
        # complete, deliberately retain the new installation and its marker so
        # the registration remains usable/recoverable rather than leaving a
        # silently stale host entry.
        cleanup_errors: list[str] = []
        persistence_error: Exception | None = None
        preserve_install = False
        if ('result' in locals() and result.transaction
                and 'registration_records' in locals() and registration_records):
            try:
                cleanup_errors = cleanup_recorded_registrations(
                    registration_records, strict=True,
                    install_dir=result.install_dir, home=Path.home(),
                    _transaction=True)
            except Exception as cleanup_exc:
                cleanup_errors = [f"cleanup failed: {cleanup_exc}"]
            preserve_install = bool(cleanup_errors)
            if preserve_install:
                # The first marker write may itself have failed after the
                # hosts were changed.  Keep the new install genuinely
                # recoverable: persist the bound snapshots before returning
                # the failure, even though the normal transaction rollback is
                # being skipped.  Rebinding also protects this recovery path
                # if the original failure happened during record preparation.
                try:
                    _bind_registration_records(
                        registration_records, result.install_dir,
                        registration_workspace)
                    installer.record_registrations(
                        _records_for_marker(result.install_dir, registration_records))
                except Exception as persist_exc:
                    persistence_error = persist_exc
        rollback_error: Exception | None = None
        if not preserve_install and 'result' in locals() and result.transaction:
            try:
                result.transaction.rollback()
            except Exception as rollback_exc:
                rollback_error = rollback_exc
        details = [str(exc)]
        if cleanup_errors:
            details.append("host registration cleanup incomplete; installation preserved for recovery: "
                           + ", ".join(cleanup_errors))
            if persistence_error:
                details.append("could not persist registration recovery records; host state and installation were preserved: "
                               + str(persistence_error))
        if rollback_error:
            details.append("installation rollback incomplete; partial state preserved")
        print("install: " + "; ".join(details), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

