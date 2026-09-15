"""Agent Code Editor & Agent VM Sandboxed Staging Engine for Fable Mode.

Provides file staging buffers, AST verification, and an isolated sandbox VM runner
that verifies code changes before promoting them to the host user workspace or rolling them back.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path, PureWindowsPath
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from fable_engine.session import get_or_load_session

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on non-POSIX hosts
    resource = None  # type: ignore[assignment]


TRUSTED_HOST_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_TIMEOUT_SECONDS = 30
SANDBOX_CPU_SECONDS = 20
SANDBOX_MEMORY_BYTES = 1_073_741_824
SANDBOX_FILE_BYTES = 67_108_864
SANDBOX_OPEN_FILES = 128
SANDBOX_PROCESSES = 128


def _validate_relative_path(filepath: str) -> Path:
    if not isinstance(filepath, str) or not filepath or "\x00" in filepath:
        raise ValueError("filepath must be a non-empty relative path")
    if filepath.startswith("/") or filepath.startswith("\\"):
        raise ValueError("root-rooted filepaths are not allowed")
    path = Path(filepath)
    windows_path = PureWindowsPath(filepath)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("absolute filepaths are not allowed")
    if ".." in path.parts or ".." in windows_path.parts:
        raise ValueError("filepath traversal segments are not allowed")
    if path == Path("."):
        raise ValueError("filepath must identify a file below the workspace root")
    return path


def _resolve_confined(root: Path, filepath: str) -> Path:
    relative = _validate_relative_path(filepath)
    resolved_root = root.resolve(strict=True)
    destination = (resolved_root / relative).resolve(strict=False)
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"filepath escapes its workspace root: {filepath}") from exc
    if destination == resolved_root:
        raise ValueError("filepath must identify a file below the workspace root")
    return destination


_SANDBOX_LAUNCHER = r"""
rootfs=$1
workspace=$2
test_command=$3
python_prefix=$4
python_base_prefix=$5

mount -t tmpfs -o size=64m,nosuid,nodev tmpfs "$rootfs"

bind_readonly() {
    source_path=$1
    [ -e "$source_path" ] || return 0
    target_path="$rootfs$source_path"
    if [ -d "$source_path" ]; then
        mkdir -p "$target_path"
        mount --rbind "$source_path" "$target_path"
    else
        mkdir -p "$(dirname "$target_path")"
        : > "$target_path"
        mount --bind "$source_path" "$target_path"
    fi
    mount -o remount,bind,ro,nosuid,nodev "$target_path"
}

for system_path in /usr /bin /lib /lib64 /etc; do
    bind_readonly "$system_path"
done
bind_readonly "$python_prefix"
if [ "$python_base_prefix" != "$python_prefix" ]; then
    bind_readonly "$python_base_prefix"
fi

mkdir -p "$rootfs/workspace" "$rootfs/tmp" "$rootfs/dev"
mount --bind "$workspace" "$rootfs/workspace"
mount -t tmpfs -o size=64m,nosuid,nodev tmpfs "$rootfs/tmp"
for device in null zero random urandom; do
    : > "$rootfs/dev/$device"
    mount --bind "/dev/$device" "$rootfs/dev/$device"
done

cd "$rootfs/workspace"
exec chroot "$rootfs" /bin/sh -c 'cd /workspace && exec /bin/sh -c "$1"' sandbox-command "$test_command"
"""


class AgentCodeEditor:
    """Manages staged file buffers before committing to host workspace."""

    def __init__(self) -> None:
        self.staged_buffers: Dict[str, str] = {}

    def stage_file(self, filepath: str, content: str) -> Dict[str, Any]:
        """Stages file content in buffer and performs basic syntax inspection."""
        _validate_relative_path(filepath)
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
    """Isolated execution sandbox VM for testing staged code changes."""

    @classmethod
    def is_available(cls) -> bool:
        """Checks if unshare user namespace isolation is available on the current OS."""
        if os.name != "posix" or resource is None or not Path("/usr/bin/unshare").is_file():
            return False
        try:
            res = subprocess.run(
                ["/usr/bin/unshare", "--user", "--map-root-user", "/bin/true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return res.returncode == 0
        except Exception:
            return False

    def run_tests_and_promote(
        self,
        staged_files: Dict[str, str],
        test_command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes tests in an isolated temporary sandbox directory.

        If tests pass, promotes staged files to the host user workspace.
        If tests fail, aborts and cleans up sandbox without affecting host files.
        """
        if not staged_files:
            return {"status": "error", "message": "No staged files to test in VM."}

        if test_command is not None and not isinstance(test_command, str):
            return {"status": "error", "message": "test_command must be a string when provided."}
        if not self.is_available():
            return {"status": "error", "message": "A supported isolated sandbox executor is not available."}

        host_root = TRUSTED_HOST_ROOT.resolve(strict=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="agent_vm_project_"))
        sandbox_root = Path(tempfile.mkdtemp(prefix="agent_vm_root_"))

        try:
            # Copy the complete baseline before overlaying staged files so existing
            # project directories (especially tests/) cannot be hidden or skipped.
            shutil.copytree(
                host_root,
                temp_dir,
                dirs_exist_ok=True,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )

            confined_files: List[Tuple[str, str, Path, Path]] = []
            for rel_path, content in staged_files.items():
                sandbox_dest = _resolve_confined(temp_dir, rel_path)
                host_dest = _resolve_confined(host_root, rel_path)
                confined_files.append((rel_path, content, sandbox_dest, host_dest))

            # Overlay staged files only after every path is known to be confined.
            for rel_path, content, sandbox_dest, _ in confined_files:
                if _resolve_confined(temp_dir, rel_path) != sandbox_dest:
                    raise ValueError(f"sandbox destination changed during validation: {rel_path}")
                sandbox_dest.parent.mkdir(parents=True, exist_ok=True)
                with sandbox_dest.open("w", encoding="utf-8") as f:
                    f.write(content)

            cmd = test_command or f"{shlex.quote(sys.executable)} -m unittest discover -s tests -p 'test_*.py'"
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
                mode="w+", encoding="utf-8"
            ) as stderr_file:
                proc = subprocess.Popen(
                    [
                        "/usr/bin/unshare",
                        "--user",
                        "--map-root-user",
                        "--mount",
                        "--net",
                        "--pid",
                        "--fork",
                        "/bin/sh",
                        "-ceu",
                        _SANDBOX_LAUNCHER,
                        "sandbox-launcher",
                        str(sandbox_root),
                        str(temp_dir),
                        cmd,
                        sys.prefix,
                        sys.base_prefix,
                    ],
                    cwd=host_root,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    start_new_session=True,
                    preexec_fn=self._set_resource_limits,
                )
                try:
                    proc.communicate(timeout=SANDBOX_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                    stdout = self._read_output_tail(stdout_file)
                    stderr = self._read_output_tail(stderr_file)
                    return {
                        "status": "error",
                        "message": f"VM Sandbox execution timed out after {SANDBOX_TIMEOUT_SECONDS} seconds.",
                        "stdout": stdout,
                        "stderr": stderr,
                    }
                stdout = self._read_output_tail(stdout_file)
                stderr = self._read_output_tail(stderr_file)

            test_passed = proc.returncode == 0

            if test_passed:
                promoted_files = self._promote_atomically(host_root, confined_files)

                return {
                    "status": "promoted",
                    "message": "VM tests passed! Staged changes successfully promoted to user machine.",
                    "promoted_files": promoted_files,
                    "stdout": stdout,
                    "stderr": stderr,
                }
            else:
                return {
                    "status": "rolled_back",
                    "message": "VM tests failed! Staged changes were isolated and rolled back without touching user machine.",
                    "exit_code": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }

        except Exception as ex:
            return {
                "status": "error",
                "message": f"VM Sandbox execution error: {str(ex)}",
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            shutil.rmtree(sandbox_root, ignore_errors=True)

    @staticmethod
    def _set_resource_limits() -> None:
        if resource is None:
            raise RuntimeError("POSIX resource limits are unavailable")
        resource.setrlimit(resource.RLIMIT_CPU, (SANDBOX_CPU_SECONDS, SANDBOX_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (SANDBOX_MEMORY_BYTES, SANDBOX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (SANDBOX_FILE_BYTES, SANDBOX_FILE_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (SANDBOX_OPEN_FILES, SANDBOX_OPEN_FILES))
        resource.setrlimit(resource.RLIMIT_NPROC, (SANDBOX_PROCESSES, SANDBOX_PROCESSES))

    @staticmethod
    def _read_output_tail(output_file: Any) -> str:
        output_file.flush()
        size = output_file.tell()
        output_file.seek(max(0, size - 1000))
        return output_file.read()

    @staticmethod
    def _promote_atomically(
        host_root: Path,
        confined_files: List[Tuple[str, str, Path, Path]],
    ) -> List[str]:
        prepared: List[Tuple[str, Path, Path, Optional[Path]]] = []
        created_dirs: List[Path] = []
        replaced: List[Tuple[Path, Optional[Path]]] = []
        cleanup_paths: set[Path] = set()

        # Validate every destination before making any host-side change.
        for rel_path, _, _, expected_host_dest in confined_files:
            host_dest = _resolve_confined(host_root, rel_path)
            if host_dest != expected_host_dest or host_dest.is_symlink():
                raise ValueError(f"unsafe host destination: {rel_path}")
            if host_dest.exists() and not host_dest.is_file():
                raise ValueError(f"host destination is not a regular file: {rel_path}")

        try:
            for rel_path, content, _, expected_host_dest in confined_files:
                missing_dirs: List[Path] = []
                parent = expected_host_dest.parent
                while parent != host_root and not parent.exists():
                    missing_dirs.append(parent)
                    parent = parent.parent
                for directory in reversed(missing_dirs):
                    directory.mkdir()
                    created_dirs.append(directory)

                host_dest = _resolve_confined(host_root, rel_path)
                if host_dest != expected_host_dest:
                    raise ValueError(f"host destination changed during preparation: {rel_path}")

                temp_fd, temp_name = tempfile.mkstemp(prefix=f".{host_dest.name}.stage-", dir=host_dest.parent)
                temp_path = Path(temp_name)
                cleanup_paths.add(temp_path)
                with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_file:
                    temp_file.write(content)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.chmod(temp_path, stat.S_IMODE(host_dest.stat().st_mode) if host_dest.exists() else 0o644)

                backup_path: Optional[Path] = None
                if host_dest.exists():
                    backup_fd, backup_name = tempfile.mkstemp(prefix=f".{host_dest.name}.backup-", dir=host_dest.parent)
                    os.close(backup_fd)
                    backup_path = Path(backup_name)
                    cleanup_paths.add(backup_path)
                    shutil.copy2(host_dest, backup_path)
                prepared.append((rel_path, host_dest, temp_path, backup_path))

            for rel_path, expected_host_dest, temp_path, backup_path in prepared:
                host_dest = _resolve_confined(host_root, rel_path)
                if host_dest != expected_host_dest:
                    raise ValueError(f"host destination changed during promotion: {rel_path}")
                os.replace(temp_path, host_dest)
                cleanup_paths.discard(temp_path)
                replaced.append((host_dest, backup_path))

            for _, _, _, backup_path in prepared:
                if backup_path is not None:
                    backup_path.unlink(missing_ok=True)
                    cleanup_paths.discard(backup_path)
            return [rel_path for rel_path, _, _, _ in prepared]
        except Exception as promotion_error:
            rollback_errors: List[str] = []
            for host_dest, backup_path in reversed(replaced):
                try:
                    if backup_path is None:
                        host_dest.unlink(missing_ok=True)
                    else:
                        os.replace(backup_path, host_dest)
                        cleanup_paths.discard(backup_path)
                except OSError as rollback_error:
                    rollback_errors.append(f"{host_dest}: {rollback_error}")
                    if backup_path is not None:
                        cleanup_paths.discard(backup_path)
            if rollback_errors:
                raise RuntimeError(
                    "promotion failed and rollback could not restore every destination; backups were preserved: "
                    + "; ".join(rollback_errors)
                ) from promotion_error
            raise
        finally:
            for cleanup_path in cleanup_paths:
                cleanup_path.unlink(missing_ok=True)
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass


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

    elif action in ("view_staged", "get"):
        staged = GLOBAL_AGENT_EDITOR.get_staged(filepath)
        if staged is None:
            return json.dumps({"status": "not_found", "filepath": filepath})
        return json.dumps({"status": "found", "filepath": filepath, "content": staged})

    elif action in ("clear", "reset"):
        GLOBAL_AGENT_EDITOR.clear_stage(filepath if filepath else None)
        return json.dumps({"status": "cleared", "filepath": filepath or "all"})

    else:
        return f"Error: Unknown editor_action '{action}'. Supported: stage, view_staged, clear."


def _handle_vm_test_and_commit(arguments: Dict[str, Any]) -> str:
    """Action handler for Agent VM Sandbox testing & promotion tool."""
    session_name = arguments.get("session_name")
    if not isinstance(session_name, str) or not session_name.strip():
        return "Error: 'session_name' is required for action 'vm_test_and_commit'."
    try:
        session = get_or_load_session(session_name.strip())
    except (ValueError, RuntimeError) as exc:
        return f"Error: {str(exc)}"
    if session.execution_locked or not session.can_execute_code:
        return "Error: Session execution is locked; unlock execution before running VM tests."
    if "host_root" in arguments:
        return "Error: 'host_root' is fixed by the server and cannot be supplied by callers."

    test_command = arguments.get("test_command")
    staged = GLOBAL_AGENT_EDITOR.staged_buffers

    res = GLOBAL_AGENT_VM.run_tests_and_promote(staged, test_command)
    if res.get("status") == "promoted":
        GLOBAL_AGENT_EDITOR.clear_stage()
    return json.dumps(res)
