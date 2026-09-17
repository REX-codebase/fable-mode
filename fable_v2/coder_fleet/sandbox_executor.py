"""Isolated subprocess executor for red-team target source strings.

The red-team swarm needs a real Python callable to probe, but MCP clients
can only transport source text. This module loads that source into a
dedicated worker subprocess and exposes a thread-safe callable proxy, so
public actions such as ``red_team_code_review`` and
``verify_red_team_remediation`` can execute dynamic targets without
running them in the server process.

Containment provided here:
- separate OS process (target crashes cannot take down the MCP server),
- POSIX resource limits (CPU seconds, address space) when available,
- per-call timeout enforced by the parent; a hung target is killed,
- target stdout/stderr redirected to devnull so it cannot corrupt the
  control channel.

This is a process boundary with time and memory limits, not a security
guarantee against deliberately hostile code. Only review source the
operator intended to execute.
"""

from __future__ import annotations

import builtins
import inspect
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

_PROTOCOL_INIT_TIMEOUT = 15.0
_DEFAULT_CALL_TIMEOUT = 5.0


class SandboxError(RuntimeError):
    """Raised when the sandbox worker cannot start or the target cannot load."""


_BUILTIN_EXCEPTIONS: Dict[str, type] = {
    name: cls
    for name, cls in vars(builtins).items()
    if isinstance(cls, type) and issubclass(cls, BaseException)
}


def _rebuild_exception(type_name: str, message: str) -> BaseException:
    """Rebuild an exception raised inside the worker as a local instance."""
    cls = _BUILTIN_EXCEPTIONS.get(type_name)
    if cls is None:
        return RuntimeError(f"{type_name}: {message}")
    try:
        return cls(message)
    except Exception:
        return RuntimeError(f"{type_name}: {message}")


class SandboxedTarget:
    """Thread-safe callable proxy for a function living in a worker subprocess."""

    def __init__(self, source: str, entrypoint: Optional[str] = None,
                 call_timeout: float = _DEFAULT_CALL_TIMEOUT):
        if not source or not source.strip():
            raise SandboxError("target source is empty")
        self._source = source
        self._entrypoint = entrypoint
        self._call_timeout = float(call_timeout)
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self.__name__ = entrypoint or "sandboxed_target"
        self._spawn()
        self._handshake()

    # -- worker lifecycle -------------------------------------------------
    def _spawn(self) -> None:
        self.close()
        env = os.environ.copy()
        # The worker must import this package regardless of the caller's cwd.
        pkg_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "fable_v2.coder_fleet.sandbox_executor", "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )

    def _readline(self, timeout: float) -> str:
        """Read one protocol line with a timeout (POSIX select, thread fallback)."""
        assert self._proc is not None and self._proc.stdout is not None
        fd = self._proc.stdout.fileno()
        try:
            import select
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                raise TimeoutError(f"sandbox worker did not respond within {timeout:.1f}s")
            line = self._proc.stdout.readline()
        except (ImportError, AttributeError):
            result: Dict[str, Any] = {}

            def _reader() -> None:
                try:
                    result["line"] = self._proc.stdout.readline()  # type: ignore[union-attr]
                except Exception as exc:  # pragma: no cover - defensive
                    result["error"] = exc

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()
            reader.join(timeout)
            if reader.is_alive():
                raise TimeoutError(f"sandbox worker did not respond within {timeout:.1f}s")
            if "error" in result:
                raise SandboxError(f"sandbox worker read failed: {result['error']}")
            line = result.get("line", "")
        if not line:
            raise SandboxError("sandbox worker terminated unexpectedly")
        return line

    def _handshake(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        init = json.dumps({"source": self._source, "entrypoint": self._entrypoint})
        try:
            self._proc.stdin.write(init + "\n")
            self._proc.stdin.flush()
            reply = json.loads(self._readline(_PROTOCOL_INIT_TIMEOUT))
        except (TimeoutError, SandboxError):
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise SandboxError(f"sandbox handshake failed: {exc}") from exc
        if not reply.get("ready"):
            self.close()
            raise SandboxError(str(reply.get("error", "target failed to load in sandbox")))
        self.__name__ = str(reply.get("entrypoint") or self.__name__)
        self._install_signature(reply.get("signature"))

    def _install_signature(self, info: Any) -> None:
        """Give probes a real inspect.Signature view of the remote target."""
        if not isinstance(info, dict):
            return
        try:
            count = max(0, int(info.get("n", 1)))
            params = [
                inspect.Parameter(f"p{i}", inspect.Parameter.POSITIONAL_OR_KEYWORD)
                for i in range(count)
            ]
            if info.get("var"):
                params.append(inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL))
            self.__signature__ = inspect.Signature(params)
        except Exception:
            pass

    # -- callable surface ---------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                # Worker died (crash or prior timeout): restart and reload.
                self._spawn()
                self._handshake()
            assert self._proc.stdin is not None
            try:
                payload = json.dumps({"args": list(args), "kwargs": dict(kwargs)})
            except (TypeError, ValueError) as exc:
                raise TypeError(f"sandbox call arguments are not JSON-serializable: {exc}")
            try:
                self._proc.stdin.write(payload + "\n")
                self._proc.stdin.flush()
                reply = json.loads(self._readline(self._call_timeout))
            except TimeoutError:
                # Hung target: kill the worker; the next call respawns it.
                self.close()
                raise
            except SandboxError:
                self.close()
                raise
            if reply.get("ok"):
                if "result" in reply:
                    return reply["result"]
                return reply.get("result_repr")
            raise _rebuild_exception(str(reply.get("type", "RuntimeError")),
                                     str(reply.get("message", "")))

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass


def load_sandboxed_target(source: str, entrypoint: Optional[str] = None,
                          call_timeout: float = _DEFAULT_CALL_TIMEOUT) -> SandboxedTarget:
    """Load target source into a worker subprocess and return its callable proxy."""
    return SandboxedTarget(source, entrypoint=entrypoint, call_timeout=call_timeout)


# --------------------------------------------------------------------------
# Worker side (runs inside the child process)
# --------------------------------------------------------------------------

def _apply_resource_limits() -> None:
    try:
        import resource
        limits = [
            (resource.RLIMIT_CPU, (60, 60)),
            (resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024)),
        ]
        for res, value in limits:
            try:
                resource.setrlimit(res, value)
            except (ValueError, OSError):
                pass
    except ImportError:
        pass  # Non-POSIX platform: limits unavailable.


def _resolve_entrypoint(namespace: Dict[str, Any], entrypoint: Optional[str]) -> Callable[..., Any]:
    if entrypoint:
        fn = namespace.get(entrypoint)
        if not callable(fn):
            raise SandboxError(
                f"entrypoint '{entrypoint}' not found or not callable in target source")
        return fn
    module_name = namespace.get("__name__", "")
    candidates = {
        name: value
        for name, value in namespace.items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        and getattr(value, "__module__", "") == module_name
    }
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if "main" in candidates:
        return candidates["main"]
    names = ", ".join(sorted(candidates)) or "none"
    raise SandboxError(
        f"cannot determine target entrypoint (candidates: {names}); pass 'entrypoint'")


def _worker_main() -> int:
    _apply_resource_limits()
    protocol_out = os.dup(1)
    init_line = sys.stdin.readline()
    try:
        init = json.loads(init_line)
    except Exception as exc:
        os.write(protocol_out, (json.dumps({"ready": False, "error": f"bad init: {exc}"}) + "\n").encode())
        return 1

    namespace: Dict[str, Any] = {"__name__": "__fable_sandbox__"}
    try:
        exec(compile(str(init.get("source", "")), "<fable-sandbox-target>", "exec"), namespace)
        target = _resolve_entrypoint(namespace, init.get("entrypoint"))
    except Exception as exc:
        os.write(protocol_out, (json.dumps({"ready": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n").encode())
        return 1

    # From here on the target may print; keep it off the protocol channel.
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    entry_name = getattr(target, "__name__", init.get("entrypoint") or "target")
    try:
        sig_params = list(inspect.signature(target).parameters.values())
        sig_info = {
            "n": len(sig_params),
            "var": any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in sig_params),
        }
    except (TypeError, ValueError):
        sig_info = {"n": 1, "var": True}
    os.write(protocol_out, (json.dumps({
        "ready": True, "entrypoint": entry_name, "signature": sig_info,
    }) + "\n").encode())

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            request = json.loads(line)
            args = request.get("args", [])
            kwargs = request.get("kwargs", {})
            result = target(*args, **kwargs)
            try:
                json.dumps(result)
                reply = {"ok": True, "result": result}
            except (TypeError, ValueError):
                reply = {"ok": True, "result_repr": repr(result)}
        except Exception as exc:
            reply = {"ok": False, "type": type(exc).__name__, "message": str(exc)}
        try:
            os.write(protocol_out, (json.dumps(reply) + "\n").encode())
        except Exception:
            break
    return 0


if __name__ == "__main__":
    if "--worker" in sys.argv:
        sys.exit(_worker_main())
    print("fable sandbox executor: run with --worker (spawned by the red-team swarm)")
