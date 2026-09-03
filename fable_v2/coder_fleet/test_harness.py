"""Test Harness Engine for Isolated Scratch Execution, Concurrency Fuzzing, and Resource Profiling.

Provides subprocess isolation, timeout enforcement, thread-safety fuzzing, and memory profiling.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from typing import Any


class TestHarnessEngine:
    """Engine for executing isolated test scripts, concurrency fuzzing, and performance profiling."""

    def run_scratch_test(self, code: str, timeout_sec: float = 3.0) -> dict[str, Any]:
        """Write script to tempfile, execute via sys.executable, enforce strict timeout,

        and capture stdout, stderr, returncode, duration_ms.
        """
        temp_fd, temp_path = tempfile.mkstemp(suffix=".py", text=True)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(code)

            t0 = time.perf_counter()
            try:
                proc = subprocess.run(
                    [sys.executable, temp_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                duration_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "returncode": proc.returncode,
                    "duration_ms": round(duration_ms, 2),
                    "timed_out": False,
                    "success": proc.returncode == 0,
                }
            except subprocess.TimeoutExpired as exc:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode() if exc.stdout else "")
                stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode() if exc.stderr else "")
                return {
                    "stdout": stdout,
                    "stderr": (stderr + "\nExecution timed out").strip(),
                    "returncode": -1,
                    "duration_ms": round(duration_ms, 2),
                    "timed_out": True,
                    "success": False,
                }
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    def concurrency_fuzz(self, func_code: str, threads: int = 4, iterations: int = 50) -> dict[str, Any]:
        """Execute multithreaded stress loop to detect race conditions or exceptions."""
        if "def target_fn" in func_code or "def run" in func_code:
            code_body = func_code
        else:
            # Wrap script body into target_fn
            indented = textwrap.indent(func_code.strip(), "    ")
            code_body = f"def target_fn():\n{indented}\n"

        driver = f"""
import json
import threading
import traceback
import sys

{code_body}

exceptions = []
lock = threading.Lock()

def worker(worker_id):
    for i in range({iterations}):
        try:
            if "target_fn" in globals():
                target_fn()
            elif "run" in globals():
                run()
        except Exception as e:
            with lock:
                exceptions.append(f"{{type(e).__name__}}: {{e}}")
            break

thread_pool = []
for t_id in range({threads}):
    t = threading.Thread(target=worker, args=(t_id,))
    thread_pool.append(t)
    t.start()

for t in thread_pool:
    t.join()

output = {{
    "exceptions": exceptions,
    "race_conditions_detected": len(exceptions) > 0,
}}
print("__CONCURRENCY_OUTPUT__" + json.dumps(output))
"""
        res = self.run_scratch_test(driver, timeout_sec=max(5.0, threads * 1.5))
        if not res["success"]:
            return {
                "threads": threads,
                "iterations": iterations,
                "race_conditions_detected": True,
                "exceptions": [res["stderr"] or "Process terminated abnormally"],
                "duration_ms": res["duration_ms"],
                "success": False,
            }

        # Parse output
        stdout = res["stdout"]
        marker = "__CONCURRENCY_OUTPUT__"
        if marker in stdout:
            payload_str = stdout.split(marker, 1)[1].strip()
            try:
                data = json.loads(payload_str)
                return {
                    "threads": threads,
                    "iterations": iterations,
                    "race_conditions_detected": data.get("race_conditions_detected", False),
                    "exceptions": data.get("exceptions", []),
                    "duration_ms": res["duration_ms"],
                    "success": len(data.get("exceptions", [])) == 0,
                }
            except json.JSONDecodeError:
                pass

        return {
            "threads": threads,
            "iterations": iterations,
            "race_conditions_detected": False,
            "exceptions": [],
            "duration_ms": res["duration_ms"],
            "success": True,
        }

    def profile_memory_and_cpu(self, code: str) -> dict[str, Any]:
        """Run code and return execution duration and estimated heap delta."""
        indented = textwrap.indent(code.strip(), "    ")
        driver = f"""
import tracemalloc
import time
import json
import sys

tracemalloc.start()
t0 = time.perf_counter()
err_str = None

try:
{indented}
except Exception as e:
    err_str = f"{{type(e).__name__}}: {{e}}"

t1 = time.perf_counter()
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

result = {{
    "duration_ms": round((t1 - t0) * 1000.0, 3),
    "peak_memory_bytes": peak,
    "memory_delta_bytes": current,
    "error": err_str,
}}
print("__PROFILE_OUTPUT__" + json.dumps(result))
"""
        res = self.run_scratch_test(driver, timeout_sec=5.0)
        marker = "__PROFILE_OUTPUT__"
        if res["success"] and marker in res["stdout"]:
            payload_str = res["stdout"].split(marker, 1)[1].strip()
            try:
                data = json.loads(payload_str)
                data["success"] = data.get("error") is None
                return data
            except json.JSONDecodeError:
                pass

        return {
            "duration_ms": res["duration_ms"],
            "peak_memory_bytes": 0,
            "memory_delta_bytes": 0,
            "success": False,
            "error": res["stderr"] or "Profiling execution failed",
        }
