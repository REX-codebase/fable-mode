"""Agent Code Editor & sandboxed staging engine for Fable Mode.

Provides syntax-checked file staging and an OS-isolated test runner that promotes
changes to a trusted host workspace only after tests pass.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from fable_engine.session import get_or_load_session


MAX_TEST_COMMAND_CHARS = 16_384
MAX_SANDBOX_OUTPUT_BYTES = 16 * 1024 * 1024
TRUSTED_AGENT_HOST_ROOT = Path(
    os.environ.get("FABLE_AGENT_HOST_ROOT", os.getcwd())
).resolve()


def _relative_parts(filepath: str) -> Tuple[str, ...]:
    """Return normalized path components for a confined workspace path."""
    if not isinstance(filepath, str) or not filepath:
        raise ValueError("filepath must be a non-empty relative path")
    normalized = filepath.replace("\\", "/")
    raw_parts = normalized.split("/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in raw_parts):
        raise PermissionError("filepath must be a normalized relative path without traversal")
    if any("\x00" in part or ":" in part for part in raw_parts):
        raise PermissionError("filepath contains an unsafe path component")
    return tuple(raw_parts)


def _resolve_confined(root: Path, filepath: str) -> Path:
    """Resolve a relative path and reject links or escapes from ``root``."""
    root = root.resolve(strict=True)
    parts = _relative_parts(filepath)
    current = root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise PermissionError("filepath contains a link or special filesystem entry")
    resolved = current.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError("filepath escapes its trusted workspace root") from exc
    return resolved


class AgentCodeEditor:
    """Manages staged file buffers before committing to the host workspace."""

    def __init__(self) -> None:
        self.staged_buffers: Dict[str, str] = {}

    def stage_file(self, filepath: str, content: str) -> Dict[str, Any]:
        """Validate and stage text content without retaining invalid Python."""
        _relative_parts(filepath)
        if not isinstance(content, str):
            raise ValueError("content must be text")
        syntax_valid = True
        error_msg = None

        if filepath.endswith(".py"):
            try:
                ast.parse(content, filename=filepath)
            except SyntaxError as ex:
                syntax_valid = False
                error_msg = f"SyntaxError line {ex.lineno}: {ex.msg}"

        if syntax_valid:
            self.staged_buffers[filepath] = content

        return {
            "status": "staged",
            "filepath": filepath,
            "char_count": len(content),
            "line_count": len(content.splitlines()),
            "syntax_valid": syntax_valid,
            "syntax_error": error_msg,
        }

    def get_staged(self, filepath: str) -> Optional[str]:
        return self.staged_buffers.get(filepath)

    def clear_stage(self, filepath: Optional[str] = None) -> None:
        if filepath:
            self.staged_buffers.pop(filepath, None)
        else:
            self.staged_buffers.clear()


class AgentVMSandbox:
    """Copies a project into an OS sandbox, tests it, and promotes atomically."""

    def __init__(self, host_root: Optional[os.PathLike[str] | str] = None) -> None:
        configured_root = Path(host_root) if host_root is not None else TRUSTED_AGENT_HOST_ROOT
        self.host_root = configured_root.resolve()

    @staticmethod
    def _resource_limits() -> None:
        """Apply resource ceilings inherited by the sandbox and its children."""
        if os.name != "posix":
            return
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SANDBOX_OUTPUT_BYTES, MAX_SANDBOX_OUTPUT_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))

    @staticmethod
    def _runtime_mounts() -> List[Path]:
        candidates = [Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")]
        candidates.extend([Path(sys.prefix), Path(sys.base_prefix)])
        mounts: List[Path] = []
        for candidate in candidates:
            if not candidate.exists():
                continue
            if candidate not in mounts:
                mounts.append(candidate)
        return mounts

    def _sandbox_command(self, workspace: Path, test_command: Optional[str]) -> List[str]:
        sandbox_executable = shutil.which("bwrap")
        if sandbox_executable is None:
            raise RuntimeError("bubblewrap is required for isolated VM test execution")
        if test_command is not None:
            if not isinstance(test_command, str) or not test_command.strip():
                raise ValueError("test_command must be a non-empty string")
            if len(test_command) > MAX_TEST_COMMAND_CHARS:
                raise ValueError("test_command is too long")
            child_command = ["/bin/sh", "-c", test_command]
        else:
            child_command = [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
            ]

        command = [
            sandbox_executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            os.pathsep.join((str(Path(sys.executable).parent), "/usr/bin", "/bin")),
            "--setenv",
            "PYTHONUNBUFFERED",
            "1",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        for mount in self._runtime_mounts():
            command.extend(("--ro-bind", str(mount), str(mount)))
        for system_file in (Path("/etc/ld.so.cache"), Path("/etc/localtime")):
            if system_file.exists():
                command.extend(("--ro-bind", str(system_file), str(system_file)))
        command.extend(("--bind", str(workspace), "/workspace", "--chdir", "/workspace", "--"))
        command.extend(child_command)
        return command

    def _run_tests(self, workspace: Path, test_command: Optional[str]) -> Dict[str, Any]:
        command = self._sandbox_command(workspace, test_command)
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                proc = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    timeout=35,
                    preexec_fn=self._resource_limits if os.name == "posix" else None,
                )
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                exit_code = -1
            stdout_file.seek(0, os.SEEK_END)
            stdout_size = stdout_file.tell()
            stdout_file.seek(max(0, stdout_size - 1000))
            stderr_file.seek(0, os.SEEK_END)
            stderr_size = stderr_file.tell()
            stderr_file.seek(max(0, stderr_size - 1000))
            return {
                "exit_code": exit_code,
                "stdout": stdout_file.read().decode("utf-8", errors="replace"),
                "stderr": stderr_file.read().decode("utf-8", errors="replace"),
            }

    @staticmethod
    def _check_path_conflicts(paths: List[Tuple[str, Tuple[str, ...]]]) -> None:
        ordered = sorted(paths, key=lambda item: item[1])
        for index, (_, parts) in enumerate(ordered[:-1]):
            next_parts = ordered[index + 1][1]
            if len(parts) < len(next_parts) and next_parts[:len(parts)] == parts:
                raise ValueError("staged file paths cannot contain one another")

    @staticmethod
    def _ensure_parents(root: Path, destination: Path, created: List[Path]) -> None:
        relative_parent = destination.parent.relative_to(root)
        current = root
        for part in relative_parent.parts:
            current = current / part
            if current.exists():
                if current.is_symlink() or not current.is_dir():
                    raise PermissionError("destination parent is not a safe directory")
            else:
                current.mkdir()
                created.append(current)

    def _promote_atomically(self, files: List[Tuple[str, str, Path]]) -> List[str]:
        """Replace every host destination as one rollback-capable transaction."""
        validated: List[Tuple[str, str, Path]] = []
        path_parts: List[Tuple[str, Tuple[str, ...]]] = []
        for relative_path, content, expected_destination in files:
            destination = _resolve_confined(self.host_root, relative_path)
            if destination != expected_destination:
                raise PermissionError("host destination changed during sandbox execution")
            if destination.exists() and not destination.is_file():
                raise PermissionError("host destination must be a regular file")
            validated.append((relative_path, content, destination))
            path_parts.append((relative_path, _relative_parts(relative_path)))
        self._check_path_conflicts(path_parts)

        created_directories: List[Path] = []
        new_files: Dict[Path, Path] = {}
        backups: Dict[Path, Optional[Path]] = {}
        replaced: List[Path] = []
        try:
            for _, content, destination in validated:
                self._ensure_parents(self.host_root, destination, created_directories)
                fd, temporary_name = tempfile.mkstemp(prefix=".fable-new-", dir=destination.parent)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
                if destination.exists():
                    shutil.copystat(destination, temporary)
                new_files[destination] = temporary

                if destination.exists():
                    backup_fd, backup_name = tempfile.mkstemp(prefix=".fable-backup-", dir=destination.parent)
                    os.close(backup_fd)
                    backup = Path(backup_name)
                    shutil.copy2(destination, backup)
                    backups[destination] = backup
                else:
                    backups[destination] = None

            for relative_path, _, destination in validated:
                if _resolve_confined(self.host_root, relative_path) != destination:
                    raise PermissionError("host destination changed before promotion")
                os.replace(new_files[destination], destination)
                replaced.append(destination)

            return [relative_path for relative_path, _, _ in validated]
        except Exception:
            restoration_errors: List[str] = []
            for destination in reversed(replaced):
                backup = backups.get(destination)
                try:
                    if backup is None:
                        destination.unlink(missing_ok=True)
                    else:
                        os.replace(backup, destination)
                except OSError as exc:
                    restoration_errors.append(f"{destination.name}: {exc}")
            if restoration_errors:
                raise RuntimeError("atomic promotion rollback failed: " + "; ".join(restoration_errors))
            raise
        finally:
            temporaries = list(new_files.values())
            temporaries.extend(item for item in backups.values() if item is not None)
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)
            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def run_tests_and_promote(
        self,
        staged_files: Dict[str, str],
        test_command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Test a complete project copy and promote staged files only on success."""
        if not staged_files:
            return {"status": "error", "message": "No staged files to test in VM."}
        if not self.host_root.is_dir():
            return {"status": "error", "message": "Trusted host workspace is unavailable."}

        try:
            validated_inputs: List[Tuple[str, str, Path]] = []
            for relative_path, content in staged_files.items():
                if not isinstance(content, str):
                    raise ValueError("staged file content must be text")
                host_destination = _resolve_confined(self.host_root, relative_path)
                validated_inputs.append((relative_path, content, host_destination))
            self._check_path_conflicts([
                (relative_path, _relative_parts(relative_path))
                for relative_path, _, _ in validated_inputs
            ])

            with tempfile.TemporaryDirectory(prefix="agent_vm_sandbox_") as temp_dir:
                workspace = Path(temp_dir) / "workspace"
                shutil.copytree(self.host_root, workspace, symlinks=True)

                staged: List[Tuple[str, str, Path]] = []
                for relative_path, content, host_destination in validated_inputs:
                    sandbox_destination = _resolve_confined(workspace, relative_path)
                    sandbox_destination.parent.mkdir(parents=True, exist_ok=True)
                    fd, overlay_name = tempfile.mkstemp(
                        prefix=".fable-overlay-", dir=sandbox_destination.parent
                    )
                    overlay = Path(overlay_name)
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                            handle.write(content)
                        os.replace(overlay, sandbox_destination)
                    finally:
                        overlay.unlink(missing_ok=True)
                    staged.append((relative_path, content, host_destination))

                test_result = self._run_tests(workspace, test_command)
                if test_result["exit_code"] != 0:
                    return {
                        "status": "rolled_back",
                        "message": "VM tests failed; staged changes were not promoted.",
                        **test_result,
                    }

                promoted_files = self._promote_atomically(staged)
                return {
                    "status": "promoted",
                    "message": "VM tests passed; staged changes were promoted atomically.",
                    "promoted_files": promoted_files,
                    "stdout": test_result["stdout"],
                    "stderr": test_result["stderr"],
                }
        except Exception as ex:
            return {"status": "error", "message": f"VM Sandbox execution error: {ex}"}


GLOBAL_AGENT_EDITOR = AgentCodeEditor()
GLOBAL_AGENT_VM = AgentVMSandbox()


def _handle_editor_stage_diff(arguments: Dict[str, Any]) -> str:
    """Action handler for Agent Code Editor tool."""
    action = arguments.get("editor_action", "stage")
    filepath = arguments.get("filepath", "")
    content = arguments.get("content", "")

    if action in ("stage", "write_buffer"):
        if not filepath:
            return "Error: Missing required parameter 'filepath'."
        res = GLOBAL_AGENT_EDITOR.stage_file(filepath, content)
        return json.dumps(res)
    if action in ("view_staged", "get"):
        staged = GLOBAL_AGENT_EDITOR.get_staged(filepath)
        if staged is None:
            return json.dumps({"status": "not_found", "filepath": filepath})
        return json.dumps({"status": "found", "filepath": filepath, "content": staged})
    if action in ("clear", "reset"):
        GLOBAL_AGENT_EDITOR.clear_stage(filepath if filepath else None)
        return json.dumps({"status": "cleared", "filepath": filepath or "all"})
    return f"Error: Unknown editor_action '{action}'. Supported: stage, view_staged, clear."


def _handle_vm_test_and_commit(arguments: Dict[str, Any]) -> str:
    """Authorize, sandbox-test, and atomically promote the staged buffers."""
    session_name = arguments.get("session_name", "")
    if not isinstance(session_name, str) or not session_name.strip():
        return "Error: 'session_name' is required for action 'vm_test_and_commit'."
    if "host_root" in arguments:
        return "Error: 'host_root' is configured by the trusted host and cannot be supplied to this action."

    session = get_or_load_session(session_name.strip())
    if session.execution_locked or not session.can_execute_code:
        return "Error: Session execution is locked; unlock execution before running VM tests."

    res = GLOBAL_AGENT_VM.run_tests_and_promote(
        GLOBAL_AGENT_EDITOR.staged_buffers,
        arguments.get("test_command"),
    )
    if res.get("status") == "promoted":
        GLOBAL_AGENT_EDITOR.clear_stage()
    return json.dumps(res)
