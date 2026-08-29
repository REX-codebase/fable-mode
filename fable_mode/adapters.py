"""Safe, bounded host discovery and transactional MCP registration."""
from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 8192
DEFAULT_TIMEOUT = 5.0
_NAMES = ("fable-engine", "fable-mode")


class RegistrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Host:
    name: str
    executable: Path
    kind: str
    healthy: bool = False
    detail: str = ""
    # Internal override used by tests/explicit transactions.  Discovery hosts
    # leave this unset so real mutations inherit the user's environment.
    registration_home: Path | None = None


def _safe_path(path: Path, *, allow_missing: bool = True) -> None:
    """Reject links, hardlinks, and non-regular files in existing path parts."""
    p = Path(path)
    cur = p
    parts: list[Path] = []
    while True:
        parts.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    for part in reversed(parts):
        try:
            st = os.lstat(part)
        except FileNotFoundError:
            if allow_missing:
                continue
            raise RegistrationError(f"missing path: {part}")
        reparse = bool(getattr(st, "st_file_attributes", 0) & 0x400)
        junction = bool(getattr(part, "is_junction", lambda: False)())
        if reparse or junction or stat.S_ISLNK(st.st_mode) or stat.S_ISSOCK(st.st_mode) or stat.S_ISFIFO(st.st_mode) or stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
            raise RegistrationError(f"unsafe special/link path: {part}")
        if part == p and stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
            raise RegistrationError(f"hardlinked file is unsafe: {part}")


def _clean_output(data: bytes) -> str:
    text = data[:MAX_OUTPUT].decode("utf-8", "replace")
    return "".join(c for c in text if c in "\n\r\t" or ord(c) >= 32).strip()


def _hash_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _file_identity(path: Path) -> tuple[int, int]:
    st = path.lstat()
    return st.st_dev, st.st_ino


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_argv(argv: list[str], timeout: float = DEFAULT_TIMEOUT, *, env: dict[str, str] | None = None) -> tuple[int, str, str, bool]:
    """Run argv without a shell, with bounded output and process-group cleanup.

    POSIX descendants in the new process group are killed on timeout; Windows
    uses the direct-child process-group fallback available in the stdlib, so
    descendant cleanup is best effort there and never escalates to a shell.
    """
    if not argv or any(not isinstance(x, str) or "\x00" in x for x in argv):
        raise ValueError("argv must be a non-empty list of safe strings")
    try:
        timeout = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout must be a finite positive number") from exc
    if not math.isfinite(timeout) or not (0 < timeout <= 300.0):
        raise ValueError("timeout must be finite and between 0 and 300 seconds")
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if env is not None:
        # Environment is caller supplied.  In particular, never interpret a
        # public variable as a recursive-cleanup capability.
        child_env = dict(env)
        child_env.pop("_FABLE_PROBE_HOME", None)
        kwargs["env"] = child_env
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        return 127, "", str(exc), False
    captured: dict[str, bytearray] = {"out": bytearray(), "err": bytearray()}

    def drain(pipe, key: str) -> None:
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    return
                remaining = MAX_OUTPUT - len(captured[key])
                if remaining > 0:
                    captured[key].extend(chunk[:remaining])
        finally:
            pipe.close()

    threads = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True), threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process(proc)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)
    result = (proc.returncode, _clean_output(bytes(captured["out"])),
              _clean_output(bytes(captured["err"])), timed_out)
    return result


def _probe_environment(executable: Path | None = None) -> dict[str, str]:
    """Build a secret-free environment for one host probe.

    Probes never inherit the caller's HOME/USERPROFILE or PATH.  A private
    temporary home is created for each invocation; its owner (detect_hosts)
    removes it after the child exits.  ``/usr/bin/env`` shebangs are resolved *only* from
    the trusted system PATH; falling back to the caller PATH would allow a
    user-private interpreter to run during registration.
    """
    # Include the running interpreter's installation directory as trusted
    # (the launcher itself was resolved before probing), but never caller PATH.
    trusted_path = os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent), os.defpath]))
    paths = [p for p in trusted_path.split(os.pathsep) if p]
    if executable is not None:
        try:
            first = Path(executable).read_bytes()[:512].splitlines()[0].decode("utf-8", "replace")
            if first.startswith("#!"):
                words = shlex.split(first[2:].strip())
                if words and Path(words[0]).name == "env":
                    # Only the system env binary is trusted; a user-provided
                    # ``.../env`` must not become a resolver primitive.
                    env_path = Path(words[0])
                    if not env_path.is_absolute():
                        raise RegistrationError("refusing relative env shebang")
                    try:
                        env_resolved = env_path.resolve()
                        env_candidates = {Path(p).resolve() for p in (
                            shutil.which("env", path=trusted_path),
                        ) if p}
                    except OSError as exc:
                        raise RegistrationError("refusing unavailable env shebang") from exc
                    if env_resolved not in env_candidates:
                        raise RegistrationError("refusing untrusted env interpreter")
                    # Do not accept env options, assignments, or an empty
                    # interpreter: all of those make resolution ambiguous.
                    if len(words) != 2 or not words[1] or "/" in words[1] or "\\" in words[1]:
                        raise RegistrationError("refusing ambiguous /usr/bin/env shebang")
                    interpreter = shutil.which(words[1], path=trusted_path)
                    if not interpreter:
                        raise RegistrationError("refusing unresolved /usr/bin/env shebang")
                    paths.insert(0, str(Path(interpreter).parent))
                elif words and Path(words[0]).is_absolute():
                    if len(words) != 1:
                        raise RegistrationError("refusing absolute shebang with interpreter arguments")
                    interpreter_path = Path(words[0])
                    try:
                        resolved_interpreter = interpreter_path.resolve()
                        st = resolved_interpreter.lstat()
                    except OSError as exc:
                        raise RegistrationError("refusing unavailable absolute shebang interpreter") from exc
                    trusted_interpreters = {Path(sys.executable).resolve()}
                    for candidate_name in (interpreter_path.name, "sh", "bash", "python", "python3"):
                        candidate = shutil.which(candidate_name, path=trusted_path)
                        if candidate:
                            trusted_interpreters.add(Path(candidate).resolve())
                    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                            or resolved_interpreter not in trusted_interpreters):
                        raise RegistrationError("refusing untrusted absolute shebang interpreter")
                    paths.insert(0, str(resolved_interpreter.parent))
        except RegistrationError:
            raise
        except FileNotFoundError:
            # Cleanup of a removed host may still need to inspect its last
            # registration; let run_argv report the unavailable executable.
            pass
        except (OSError, ValueError, IndexError):
            raise RegistrationError("refusing malformed host shebang")
    probe_home = Path(tempfile.mkdtemp(prefix="fable-probe-home-"))
    os.chmod(probe_home, 0o700)
    # Private implementation key is removed before spawning and consumed by
    # run_argv's finally block; it is not exposed to the host process.
    return {"PATH": os.pathsep.join(dict.fromkeys(paths)),
            "HOME": str(probe_home), "USERPROFILE": str(probe_home),
            "XDG_CONFIG_HOME": str(probe_home / ".config"),
            "LC_ALL": "C", "LANG": "C",
            "_FABLE_PROBE_HOME": str(probe_home)}


def _run_probe(argv: list[str], executable: Path) -> tuple[int, str, str, bool]:
    env = _probe_environment(executable)
    probe_home = Path(env["_FABLE_PROBE_HOME"])
    try:
        return run_argv(argv, env=env)
    finally:
        shutil.rmtree(probe_home, ignore_errors=True)


def _registration_environment(home: Path | None = None) -> dict[str, str]:
    """Return the intended user environment for real CLI mutations.

    Unlike health probes, registration must see the user's config location and
    credentials.  ``home`` is an explicit transaction override (used by the
    launcher tests and by callers targeting another profile); it is never used
    for discovery probes.
    """
    env = dict(os.environ)
    env.pop("_FABLE_PROBE_HOME", None)
    if home is not None:
        value = str(Path(home).expanduser())
        env["HOME"] = value
        env["USERPROFILE"] = value
    return env


def _which(name: str) -> Path | None:
    value = shutil.which(name)
    if not value:
        return None
    path = Path(value)
    try:
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            return None
    except OSError:
        return None
    return path


def detect_hosts(*, aliases: bool = False) -> dict[str, Host]:
    names: list[tuple[str, str]] = [("claude", "claude"), ("agy", "agy"), ("codex", "codex")]
    if aliases:
        names += [("cc", "cc"), ("antigravity", "antigravity")]
    result: dict[str, Host] = {}
    for name, binary in names:
        exe = _which(binary)
        if exe is None:
            # Keep absence visible to callers instead of silently omitting a
            # requested host from the registration status report.
            result[name] = Host(name, Path(binary), "cli", False, "host command not found")
            continue
        try:
            code, out, err, timed_out = _run_probe([str(exe), "--version"], exe)
            result[name] = Host(name, exe, "cli", code == 0 and not timed_out, (out or err)[:MAX_OUTPUT])
        except RegistrationError as exc:
            # A malformed/unresolved /usr/bin/env shebang makes this host
            # unhealthy, not the entire discovery/installation transaction.
            result[name] = Host(name, exe, "cli", False, str(exc)[:MAX_OUTPUT])
    return result


def _load_config_snapshot(path: Path) -> tuple[bool, bytes, int, dict]:
    _safe_path(path)
    if not path.exists():
        return False, b"", 0, {}
    if not path.is_file():
        raise RegistrationError(f"config is not a regular file: {path}")
    raw = path.read_bytes()
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise RegistrationError(f"invalid JSON config: {path}") from exc
    if not isinstance(current, dict):
        raise RegistrationError("MCP config root must be an object")
    servers = current.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise RegistrationError("mcpServers must be an object")
    return True, raw, stat.S_IMODE(path.stat().st_mode), current


def _open_directory_nofollow(path: Path, *, create: bool = True) -> int:
    """Open a directory chain and retain its identity across publication."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise RegistrationError("descriptor-relative config writes are unavailable")
    absolute = Path(path).absolute()
    fd = os.open("/", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise RegistrationError(f"missing config directory: {absolute}")
                os.mkdir(component, 0o700, dir_fd=fd)
                child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _atomic_write(path: Path, content: bytes, mode: int | None = 0o600) -> None:
    path = Path(path).absolute()
    _safe_path(path.parent)
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        parent_fd = _open_directory_nofollow(path.parent)
        temp_name = f".{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
        fd = None
        try:
            fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            os.fchmod(fd, 0o600 if mode is None else mode)
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
            os.close(parent_fd)
        return
    # Windows fallback: retain the preflight checks and fail closed if the
    # parent changes before publication rather than silently following links.
    parent_identity = _file_identity(path.parent) if path.parent.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_path(path.parent)
    if parent_identity is not None and _file_identity(path.parent) != parent_identity:
        raise RegistrationError("config parent changed during publication")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600 if mode is None else mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _safe_path(path.parent)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _write_antigravity_config(path: Path, executable: list[str], *, dry_run: bool = False) -> bool:
    """Apply one file registration; transaction orchestration is in register_hosts.

    MCP configuration files can contain credentials or local server commands.
    Every Fable write therefore normalizes the file to owner-only permissions;
    the original mode is retained in the registration record for restoration.
    """
    existed, _raw, _mode, current = _load_config_snapshot(path)
    servers = current.get("mcpServers", {})
    previous = {name: servers[name] for name in _NAMES if name in servers}
    updated = dict(current)
    updated["mcpServers"] = dict(servers)
    updated["mcpServers"].pop("fable-mode", None)
    updated["mcpServers"]["fable-engine"] = {"command": executable[0], "args": executable[1:]}
    if not dry_run:
        _atomic_write(path, (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(), 0o600)
    return "fable-engine" not in previous


def _parse_cli_json(value: object) -> dict[str, dict] | None:
    """Extract the two Fable entries from a machine-readable MCP listing.

    ``None`` means the host returned human-readable/unknown output.  This is
    deliberately distinct from ``{}``: an empty JSON listing is a safe snapshot.
    """
    if not isinstance(value, (dict, list)):
        return None
    found: dict[str, dict] = {}
    valid = True
    max_depth = 64

    def visit(node: object, depth: int = 0) -> None:
        nonlocal valid
        if depth > max_depth:
            valid = False
            return
        if isinstance(node, dict):
            for name in _NAMES:
                item = node.get(name)
                if item is not None:
                    if not isinstance(item, dict) or not isinstance(item.get("command"), str) or not isinstance(item.get("args", []), list) or any(not isinstance(arg, str) for arg in item.get("args", [])):
                        valid = False
                    else:
                        found[name] = {"command": item["command"], "args": list(item.get("args", []))}
            # Support common {name, command, args} list records.
            name = node.get("name")
            if name in _NAMES and "command" in node:
                item = {"command": node.get("command"), "args": node.get("args", [])}
                if not isinstance(item["command"], str) or not isinstance(item["args"], list) or any(not isinstance(arg, str) for arg in item["args"]):
                    valid = False
                else:
                    found[name] = item
            for child in node.values():
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
    visit(value)
    return found if valid else None


def _snapshot_cli_registrations(executable: Path, *, home: Path | None = None) -> dict[str, dict] | None:
    # Cleanup markers may outlive a removed host executable.  Let the bounded
    # argv call report that as an unsupported snapshot instead of raising a
    # state-path traceback; existing paths are still checked for links.
    if executable.exists() or executable.is_symlink():
        _safe_path(executable, allow_missing=False)
    code, out, _err, timed = run_argv(
        [str(executable), "mcp", "list"], env=_registration_environment(home))
    if code != 0 or timed:
        return None
    try:
        return _parse_cli_json(json.loads(out))
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        return None


def _query_cli_registrations(executable: Path) -> dict[str, dict]:
    """Compatibility wrapper: unsupported/human output is represented as empty."""
    return _snapshot_cli_registrations(executable) or {}


def _cli_add(host: Host, name: str, entry: dict) -> tuple[int, str, str, bool]:
    if host.name == "claude":
        argv = [str(host.executable), "mcp", "add", "--transport", "stdio", name, "--", entry["command"], *entry.get("args", [])]
    else:
        argv = [str(host.executable), "mcp", "add", name, "--", entry["command"], *entry.get("args", [])]
    return run_argv(argv, env=_registration_environment(host.registration_home))


def _is_absent_result(result: tuple[int, str, str, bool]) -> bool:
    code, out, err, timed = result
    if timed:
        return False
    if code == 0:
        return True
    text = (out + " " + err).lower()
    return any(token in text for token in ("not found", "does not exist", "doesn't exist", "no such", "unknown server", "not configured", "no mcp server", "already absent", "cannot find"))


def _cli_remove(host: Host, name: str) -> tuple[int, str, str, bool]:
    return run_argv([str(host.executable), "mcp", "remove", name],
                    env=_registration_environment(host.registration_home))


def _restore_cli(host: Host, previous: dict[str, dict]) -> None:
    errors: list[str] = []
    # Do not issue a needless legacy remove when it was absent in the snapshot;
    # importantly, rollback never manufactures or otherwise touches fable-mode.
    names_to_remove = ["fable-engine"] + [name for name in _NAMES if name != "fable-engine" and name in previous]
    for name in names_to_remove:
        if not _is_absent_result(_cli_remove(host, name)):
            errors.append(f"remove {name}")
    for name, entry in previous.items():
        code, _out, _err, timed = _cli_add(host, name, entry)
        if code != 0 or timed:
            errors.append(f"restore {name}")
    if errors:
        raise RegistrationError(f"could not restore {host.name} registration ({', '.join(errors)})")


def _post_entries(previous: dict[str, dict], installed: dict) -> dict[str, dict]:
    # Legacy is intentionally absent after installation.  This map is recorded
    # so uninstall can detect a user-created legacy entry and preserve it.
    return {"fable-engine": installed}


def register_hosts(hosts: dict[str, Host], installed_executable: list[str], *, home: Path | None = None,
                   workspace: Path | None = None, dry_run: bool = False,
                   records: list[dict] | None = None,
                   owned_records: list[dict] | None = None) -> dict[str, str]:
    """Register all hosts as one transaction, with a complete preflight.

    Every healthy host is snapshotted before the first mutation.  CLI hosts
    that expose only human-readable ``mcp list`` output are rejected before any
    host is changed; this avoids deleting an old runtime that cannot be restored.
    """
    if not installed_executable or any(not isinstance(x, str) or "\x00" in x or "\n" in x or "\r" in x for x in installed_executable):
        raise RegistrationError("invalid installed executable argv")
    explicit_home = home is not None
    home = Path(home or Path.home())
    cli_home = home if explicit_home else None
    statuses: dict[str, str] = {}
    file_snaps: dict[Path, tuple[bool, bytes, int, dict]] = {}
    cli_snaps: dict[str, dict[str, dict]] = {}
    # Entries recorded by the immediately prior install are still Fable-owned
    # during a replacement.  Keep the complete record, rather than only the
    # installed command: its previous_entries is the true pre-Fable state and
    # must survive an install -> reinstall -> uninstall cycle.
    prior_cli: dict[str, dict] = {}
    prior_files: dict[str, dict] = {}
    for record in owned_records or []:
        if not isinstance(record, dict):
            continue
        kind = record.get("kind")
        if (kind == "cli" and isinstance(record.get("host"), str)
                and isinstance(record.get("command"), str)
                and isinstance(record.get("args"), list)):
            prior_cli[record["host"]] = record
        elif kind == "file" and isinstance(record.get("path"), str):
            prior_files[record["path"]] = record

    def prior_entry(record: dict) -> dict | None:
        value = {"command": record.get("command"), "args": record.get("args", [])}
        return value if _valid_registration_entry(value) else None

    def prior_state(record: dict) -> dict[str, dict] | None:
        value = record.get("previous_entries")
        validator = (_valid_file_registration_state if record.get("kind") == "file"
                     else _valid_registration_state)
        return value if validator(value) else None
    active_hosts: list[tuple[str, Host]] = []
    # Preflight every path and CLI state, including hosts that occur later.
    for key, host in hosts.items():
        if not host.healthy:
            statuses[key] = "detected but unhealthy; not registered"
            continue
        if key in {"agy", "antigravity"}:
            active_hosts.append((key, host))
        else:
            # Preserve caller-supplied Host objects while binding CLI
            # mutations to this transaction's intended profile, never probe HOME.
            active_hosts.append((key, Host(host.name, host.executable, host.kind,
                                           host.healthy, host.detail, cli_home)))
        if key in {"agy", "antigravity"}:
            paths = [home / ".gemini" / "config" / "mcp_config.json"]
            if workspace is not None:
                paths.append(Path(workspace) / ".agents" / "mcp_config.json")
            for path in paths:
                if path not in file_snaps:
                    file_snaps[path] = _load_config_snapshot(path)
        else:
            snapshot = None if dry_run else _snapshot_cli_registrations(host.executable, home=cli_home)
            if not dry_run and snapshot is None:
                raise RegistrationError(f"{key} mcp list is not machine-readable; registration skipped before mutation")
            snapshot = snapshot or {}
            old_record = prior_cli.get(key) or prior_cli.get(host.name)
            old_entry = prior_entry(old_record) if old_record else None
            if old_record and old_entry and snapshot.get("fable-engine") == old_entry:
                # The current canonical entry belongs to the retired Fable
                # install.  Never snapshot it as user-owned; restore the
                # original complete state recorded by the first installation.
                snapshot = prior_state(old_record) or {}
            cli_snaps[key] = snapshot
    if dry_run:
        for key, host in active_hosts:
            statuses[key] = "would-register"
        return statuses

    original_records_len = len(records) if records is not None else 0
    # Atomic config publication changes the inode.  Rollback may remove or
    # restore only that published inode; if another process replaced it after
    # our write, preserve the replacement and report partial rollback.
    published_file_ids: dict[Path, tuple[int, int]] = {}
    try:
        file_paths_done: set[Path] = set()
        for key, host in active_hosts:
            if key in {"agy", "antigravity"}:
                paths = [home / ".gemini" / "config" / "mcp_config.json"]
                if workspace is not None:
                    paths.append(Path(workspace) / ".agents" / "mcp_config.json")
                for path in paths:
                    if path in file_paths_done:
                        continue
                    file_paths_done.add(path)
                    existed, raw, mode, current = file_snaps[path]
                    servers = current.get("mcpServers", {})
                    previous = {name: servers[name] for name in _NAMES if name in servers}
                    installed = {"command": installed_executable[0], "args": installed_executable[1:]}
                    old_record = prior_files.get(str(path))
                    old_entry = prior_entry(old_record) if old_record else None
                    if old_record and old_entry and previous.get("fable-engine") == old_entry:
                        # A replacement must carry forward the first install's
                        # baseline, including whether this config was created
                        # by Fable and its original private/public mode.
                        baseline = prior_state(old_record)
                        if baseline is not None:
                            previous = baseline
                            if isinstance(old_record.get("existed"), bool):
                                existed = old_record["existed"]
                            old_mode = old_record.get("previous_mode")
                            if isinstance(old_mode, int) and 0 <= old_mode <= 0o777:
                                mode = old_mode
                    updated = dict(current); updated["mcpServers"] = dict(servers)
                    updated["mcpServers"].pop("fable-mode", None); updated["mcpServers"]["fable-engine"] = installed
                    # Never leave credentials or executable commands readable
                    # by another account after a Fable mutation.
                    _atomic_write(path, (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode(), 0o600)
                    try:
                        st = path.lstat()
                        published_file_ids[path] = (st.st_dev, st.st_ino)
                    except OSError as exc:
                        raise RegistrationError(f"could not stat published config: {path}") from exc
                    if records is not None:
                        record_workspace = str(workspace) if workspace is not None and path == Path(workspace) / ".agents" / "mcp_config.json" else None
                        records.append({"kind": "file", "path": str(path), "name": "fable-engine",
                                        "workspace": record_workspace,
                                        "command": installed["command"], "args": installed["args"],
                                        "existed": existed, "previous_mode": (mode if mode is not None else 0o600),
                                        "post_mode": 0o600,
                                        "previous_entries": previous, "previous_entries_hash": _state_hash(previous),
                                        "post_entries": _post_entries(previous, installed),
                                        "post_identity": list(_file_identity(path)),
                                        "post_content_hash": _hash_bytes((json.dumps(updated, indent=2, sort_keys=True) + "\n").encode())})
                statuses[key] = "registered"
                continue
            previous = cli_snaps[key]
            installed = {"command": installed_executable[0], "args": installed_executable[1:]}
            for name in _NAMES:
                if not _is_absent_result(_cli_remove(host, name)):
                    raise RegistrationError(f"{key} {name} removal failed")
            code, out, err, timed = _cli_add(host, "fable-engine", installed)
            if code != 0 or timed:
                raise RegistrationError(f"{key} registration failed: {_clean_output((err or out).encode())}")
            if records is not None:
                records.append({"kind": "cli", "host": key, "executable": str(host.executable), "name": "fable-engine",
                                "command": installed["command"], "args": installed["args"],
                                "previous_entries": previous, "previous_entries_hash": _state_hash(previous),
                                "post_entries": _post_entries(previous, installed),
                                "created": "fable-engine" not in previous,
                                "executable_identity": list(_file_identity(host.executable))})
            statuses[key] = "registered"
        return statuses
    except Exception as exc:
        rollback_errors: list[str] = []
        # Restore all file snapshots byte-for-byte and every CLI snapshot,
        # including hosts that were changed before the failing host.
        for path, (existed, raw, mode, _current) in file_snaps.items():
            try:
                expected = published_file_ids.get(path)
                if expected is None:
                    continue  # this path was never mutated by this transaction
                try:
                    current_st = path.lstat()
                except FileNotFoundError:
                    raise RegistrationError("published config disappeared")
                if (current_st.st_dev, current_st.st_ino) != expected:
                    raise RegistrationError("published config was replaced; replacement retained")
                if existed:
                    _atomic_write(path, raw, mode)
                else:
                    _safe_path(path, allow_missing=False)
                    path.unlink()
            except (OSError, RegistrationError) as restore_exc:
                rollback_errors.append(f"{path}: {restore_exc}")
        for key, host in active_hosts:
            if key not in cli_snaps:
                continue
            try:
                _restore_cli(host, cli_snaps[key])
            except RegistrationError as restore_exc:
                rollback_errors.append(f"{key}: {restore_exc}")
        if records is not None:
            del records[original_records_len:]
        detail = f"host registration rolled back: {exc}"
        if rollback_errors:
            detail += "; partial state may remain: " + "; ".join(rollback_errors)
        raise RegistrationError(detail) from exc


def _record_state(record: dict) -> tuple[dict[str, dict], dict[str, dict]] | None:
    previous = record.get("previous_entries")
    post = record.get("post_entries")
    if not isinstance(previous, dict) or not isinstance(post, dict):
        return None
    return previous, post


def _valid_registration_entry(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {"command", "args"}
            and isinstance(value["command"], str) and bool(value["command"])
            and "\x00" not in value["command"] and isinstance(value["args"], list)
            and len(value["args"]) <= 64 and all(isinstance(arg, str) and "\x00" not in arg for arg in value["args"]))


def _valid_registration_state(value: object) -> bool:
    """Validate machine-readable CLI registration state."""
    return (isinstance(value, dict) and set(value).issubset(_NAMES)
            and all(_valid_registration_entry(entry) for entry in value.values()))


def _valid_file_registration_entry(value: object) -> bool:
    """Validate a file-backed MCP entry without discarding host extensions.

    Antigravity entries commonly carry ``cwd`` or environment metadata in
    addition to command/args.  Those fields are user state and must round-trip
    exactly, while command and argument values remain bounded and string-only.
    """
    if not isinstance(value, dict) or not isinstance(value.get("command"), str) or not value["command"]:
        return False
    if "args" in value and (not isinstance(value["args"], list)
                             or len(value["args"]) > 64
                             or any(not isinstance(arg, str) or "\x00" in arg for arg in value["args"])):
        return False
    return "\x00" not in value["command"]


def _valid_file_registration_state(value: object) -> bool:
    return (isinstance(value, dict) and set(value).issubset(_NAMES)
            and all(_valid_file_registration_entry(entry) for entry in value.values()))


def _state_hash(value: dict) -> str:
    return _hash_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _canonical_registration_path(record: dict, home: Path) -> Path | None:
    if record.get("kind") != "file":
        return None
    path = Path(record.get("path", ""))
    canonical = home / ".gemini" / "config" / "mcp_config.json"
    if path == canonical:
        return path
    workspace = record.get("workspace")
    if isinstance(workspace, str) and workspace:
        candidate = Path(workspace) / ".agents" / "mcp_config.json"
        if path == candidate:
            return path
    return None


def _validate_strict_record(record: object, install_dir: Path, home: Path) -> bool:
    """Validate marker records before they can influence any user config."""
    if not isinstance(record, dict) or record.get("install_dir") != str(install_dir):
        return False
    try:
        install_st = install_dir.lstat()
    except OSError:
        return False
    if record.get("install_identity") != [install_st.st_dev, install_st.st_ino]:
        return False
    common = {"kind", "name", "command", "args", "previous_entries", "previous_entries_hash",
              "post_entries", "install_dir", "install_identity"}
    if record.get("name") != "fable-engine" or not _valid_registration_entry({"command": record.get("command"), "args": record.get("args")}):
        return False
    state_validator = (_valid_file_registration_state if record.get("kind") == "file"
                       else _valid_registration_state)
    if not state_validator(record.get("previous_entries")) or not state_validator(record.get("post_entries")):
        return False
    previous = record["previous_entries"]
    if record.get("previous_entries_hash") != _state_hash(previous):
        return False
    if record.get("post_entries") != {"fable-engine": {"command": record["command"], "args": record["args"]}}:
        return False
    kind = record.get("kind")
    if kind == "file":
        if set(record) - (common | {"path", "workspace", "existed", "previous_mode",
                                    "post_mode", "post_identity", "post_content_hash"}):
            return False
        if not isinstance(record.get("existed"), bool):
            return False
        previous_mode = record.get("previous_mode", 0o600)
        post_mode = record.get("post_mode", 0o600)
        if (not isinstance(previous_mode, int) or not 0 <= previous_mode <= 0o777
                or not isinstance(post_mode, int) or not 0 <= post_mode <= 0o777
                or post_mode & 0o077):
            return False
        if _canonical_registration_path(record, home) is None:
            return False
        ident = record.get("post_identity")
        return (isinstance(ident, list) and len(ident) == 2 and all(isinstance(x, int) and x >= 0 for x in ident)
                and isinstance(record.get("post_content_hash"), str) and len(record["post_content_hash"]) == 64
                and all(c in "0123456789abcdef" for c in record["post_content_hash"]))
    if kind == "cli":
        if set(record) - (common | {"host", "executable", "created", "executable_identity"}):
            return False
        host = record.get("host")
        executable = record.get("executable")
        ident = record.get("executable_identity")
        if host not in {"claude", "agy", "codex", "cc", "antigravity"} or not isinstance(executable, str):
            return False
        p = Path(executable)
        if not p.is_absolute() or p.name.casefold().split(".")[0] != host.casefold():
            return False
        return (isinstance(ident, list) and len(ident) == 2 and all(isinstance(x, int) and x >= 0 for x in ident))
    return False


def cleanup_recorded_registrations(records: list[dict], *, strict: bool = False,
                                   install_dir: Path | None = None, home: Path | None = None) -> list[str]:
    """Remove this install's entries, restoring exact pre-install state.

    Strict mode is used for uninstall marker data.  It accepts only records
    emitted by this installer for canonical config paths and matching inode /
    content identities; malformed or tampered records are skipped fail-closed.

    A changed command/args, unknown CLI format, or changed file is preserved and
    reported rather than being removed.  Legacy ``fable-mode`` is restored only
    when it was present in the recorded pre-install snapshot.
    """
    skipped: list[str] = []
    home = Path(home or Path.home())
    if strict and (install_dir is None or not isinstance(records, list)):
        return ["invalid registration marker"]
    for record in records or []:
        if strict and not _validate_strict_record(record, Path(install_dir), home):
            skipped.append(str(record.get("path", record.get("host", "invalid record"))) if isinstance(record, dict) else "invalid record")
            continue
        state = _record_state(record)
        if record.get("kind") == "file":
            path = Path(record.get("path", ""))
            try:
                _safe_path(path, allow_missing=False)
                if strict:
                    if _file_identity(path) != tuple(record["post_identity"]):
                        skipped.append(str(path)); continue
                    if _hash_bytes(path.read_bytes()) != record["post_content_hash"]:
                        skipped.append(str(path)); continue
                    # New records always publish private configs.  Refuse to
                    # mutate a file whose mode changed unexpectedly.
                    if ("post_mode" in record
                            and stat.S_IMODE(path.stat().st_mode) != record["post_mode"]):
                        skipped.append(str(path)); continue
                data = json.loads(path.read_text(encoding="utf-8"))
                servers = data.get("mcpServers", {})
                expected = {"command": record.get("command"), "args": record.get("args", [])}
                if not isinstance(servers, dict) or servers.get("fable-engine") != expected:
                    skipped.append(str(path)); continue
                if state is not None:
                    _previous, post = state
                    # Check every touched name, including an old legacy name
                    # that should be absent after install.
                    for name in _NAMES:
                        current = servers.get(name)
                        wanted = post.get(name)
                        if (current if name in servers else None) != wanted:
                            raise RegistrationError("registration was modified")
                    restore = dict(servers)
                    for name in _NAMES:
                        restore.pop(name, None)
                    for name, value in _previous.items():
                        restore[name] = value
                    data["mcpServers"] = restore
                else:
                    # Compatibility with markers written by older releases.
                    data["mcpServers"].pop(record.get("name", "fable-engine"), None)
                restored_bytes = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
                restore_mode = record.get("previous_mode", stat.S_IMODE(path.stat().st_mode))
                if not isinstance(restore_mode, int) or not 0 <= restore_mode <= 0o777:
                    skipped.append(str(path)); continue
                _atomic_write(path, restored_bytes, restore_mode)
                # A newly-created Antigravity config is installer-owned.  Once
                # its exact post-install contents have been verified/restored,
                # remove the file rather than leaving an empty artifact.
                if strict and record.get("existed") is False:
                    _safe_path(path, allow_missing=False)
                    path.unlink()
            except (OSError, ValueError, TypeError, RegistrationError, json.JSONDecodeError):
                skipped.append(str(path))
        elif record.get("kind") == "cli":
            executable = Path(record.get("executable", ""))
            try:
                if strict and _file_identity(executable) != tuple(record["executable_identity"]):
                    skipped.append(str(record.get("host", "cli"))); continue
                current = _snapshot_cli_registrations(executable, home=home)
                if current is None:
                    skipped.append(str(record.get("host", "cli"))); continue
                expected = {"command": record.get("command"), "args": record.get("args", [])}
                if current.get("fable-engine") != expected:
                    skipped.append(str(record.get("host", "cli"))); continue
                if state is None:
                    previous = {}
                else:
                    previous, post = state
                    if any((current.get(name) if name in current else None) != post.get(name) for name in _NAMES):
                        skipped.append(str(record.get("host", "cli"))); continue
                host = Host(str(record.get("host", "cli")), executable, "cli", True,
                             registration_home=home)
                _restore_cli(host, previous)
            except (OSError, ValueError, TypeError, RegistrationError):
                skipped.append(str(record.get("host", "cli")))
    return skipped
