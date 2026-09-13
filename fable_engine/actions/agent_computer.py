"""Agent Code Editor & Agent VM Sandboxed Staging Engine for Fable Mode.

Provides file staging buffers, AST verification, and an isolated sandbox VM runner
that verifies code changes before promoting them to the host user workspace or rolling them back.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional


class AgentCodeEditor:
    """Manages staged file buffers before committing to host workspace."""

    def __init__(self) -> None:
        self.staged_buffers: Dict[str, str] = {}

    def stage_file(self, filepath: str, content: str) -> Dict[str, Any]:
        """Stages file content in buffer and performs basic syntax inspection."""
        self.staged_buffers[filepath] = content
        syntax_valid = True
        error_msg = None

        if filepath.endswith(".py"):
            try:
                ast.parse(content, filename=filepath)
            except SyntaxError as ex:
                syntax_valid = False
                error_msg = f"SyntaxError line {ex.lineno}: {ex.msg}"

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

    def run_tests_and_promote(
        self,
        staged_files: Dict[str, str],
        test_command: Optional[str] = None,
        host_root: str = ".",
    ) -> Dict[str, Any]:
        """Executes tests in an isolated temporary sandbox directory.

        If tests pass, promotes staged files to the host user workspace.
        If tests fail, aborts and cleans up sandbox without affecting host files.
        """
        if not staged_files:
            return {"status": "error", "message": "No staged files to test in VM."}

        # 1. Create temporary isolated sandbox directory
        temp_dir = tempfile.mkdtemp(prefix="agent_vm_sandbox_")
        promoted_files: List[str] = []

        try:
            # 2. Write staged files into sandbox directory
            for rel_path, content in staged_files.items():
                dest = os.path.join(temp_dir, rel_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(content)

            # 3. Copy essential project files (like run_tests.py, tests/) into sandbox for testing
            for item in ["run_tests.py", "tests", "fable_engine", "fable_v2"]:
                src = os.path.join(host_root, item)
                if os.path.exists(src):
                    dst = os.path.join(temp_dir, item)
                    if os.path.isdir(src):
                        if not os.path.exists(dst):
                            shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)

            # 4. Run test command in sandbox VM
            cmd = test_command or f"{sys.executable} -m unittest discover -s tests -p 'test_*.py'"
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=temp_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )

            test_passed = proc.returncode == 0

            # 5. If tests pass, promote staged files to host machine workspace
            if test_passed:
                for rel_path, content in staged_files.items():
                    host_dest = os.path.join(host_root, rel_path)
                    os.makedirs(os.path.dirname(host_dest), exist_ok=True)
                    with open(host_dest, "w", encoding="utf-8") as f:
                        f.write(content)
                    promoted_files.append(rel_path)

                return {
                    "status": "promoted",
                    "message": "VM tests passed! Staged changes successfully promoted to user machine.",
                    "promoted_files": promoted_files,
                    "stdout": proc.stdout[-1000:],
                    "stderr": proc.stderr[-1000:],
                }
            else:
                return {
                    "status": "rolled_back",
                    "message": "VM tests failed! Staged changes were isolated and rolled back without touching user machine.",
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[-1000:],
                    "stderr": proc.stderr[-1000:],
                }

        except Exception as ex:
            return {
                "status": "error",
                "message": f"VM Sandbox execution error: {str(ex)}",
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


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
    test_command = arguments.get("test_command")
    host_root = arguments.get("host_root", ".")
    staged = GLOBAL_AGENT_EDITOR.staged_buffers

    res = GLOBAL_AGENT_VM.run_tests_and_promote(staged, test_command, host_root)
    if res.get("status") == "promoted":
        GLOBAL_AGENT_EDITOR.clear_stage()
    return json.dumps(res)
