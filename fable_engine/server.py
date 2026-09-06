#!/usr/bin/env python3
"""
Fable-Engine MCP Server for MCP-compatible agent hosts.
Implements the fable_session tool for deep cognitive session management,
epistemic tracking, invariant recording, anti-rush lockout enforcement,
user-controlled time-budgeted pacing telemetry, and session persistence.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Reconfigure UTF-8 for Windows stdio
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdin, "reconfigure") and sys.stdin.encoding != "utf-8":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure logging exclusively to stderr so stdout remains pure JSON-RPC
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Fable-Engine] %(message)s",
)
logger = logging.getLogger("fable-engine")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

# Re-export all symbols from modular subsystems for 100% backward compatibility
from fable_engine.cas import (
    DATA_DIR,
    FABLE_CAS_DIR,
    MAX_CAS_OBJECT_BYTES,
    MAX_SLICE_RESPONSE_BYTES,
    AdaptiveChunkAccumulator,
    CASNotFoundError,
    CASSliceViewer,
    CAS_ENGINE,
    CompositeFrame,
    FableCASError,
    FableCASStore,
    FableCompress,
    FableGrammar333,
    IntegrityError,
    ThreadSafeLRUCache,
    _assert_private_path,
    _open_directory_nofollow,
    _safe_cas_node,
)
from fable_engine.guards import (
    GLOBAL_VELOCITY_PROFILER,
    AntiLoopCircuitBreaker,
    DelegationContractCompiler,
    EpistemicEvidenceValidator,
    ModelVelocityProfiler,
)
from fable_engine.schema import TOOL_SCHEMA
from fable_engine.session import (
    ACTIVE_SESSIONS,
    FORCE_UNLOCK_ENV,
    MAX_TIME_BUDGET_MINUTES,
    MIN_TIME_BUDGET_MINUTES,
    PHASE_INDEX_MAP,
    PHASES,
    SESSIONS_DIR,
    SESSION_NAME_PATTERN,
    SILENT_DELIBERATION_REMINDER,
    VALID_TRANSITIONS,
    FableSession,
    SessionState,
    _safe_session_file,
    _validate_session_name,
    _validate_time_budget,
    get_or_load_session,
    session_file_lock,
)

def __getattr__(name: str) -> Any:
    if name in ("GLOBAL_PLASTICITY_ENGINE", "GLOBAL_RED_TEAM_SWARM"):
        from fable_engine import session
        return getattr(session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from fable_engine.actions import (
    ACTION_DISPATCH,
    handle_fable_session,
)

try:
    from fable_engine.updater import AutoUpdater
except ImportError:
    try:
        from updater import AutoUpdater
    except ImportError:
        AutoUpdater = None

MAX_RPC_LINE_BYTES = 1 * 1024 * 1024
MAX_RPC_RESPONSE_BYTES = 2 * 1024 * 1024


def send_response(response_dict: Dict[str, Any]):
    """Writes a bounded JSON-RPC response to stdout with UTF-8 safety."""
    encoded = json.dumps(response_dict, ensure_ascii=False)
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) > MAX_RPC_RESPONSE_BYTES:
        response_dict = {
            "jsonrpc": "2.0",
            "id": response_dict.get("id") if isinstance(response_dict, dict) else None,
            "error": {"code": -32000, "message": "Response exceeds maximum size"},
        }
        encoded = json.dumps(response_dict, ensure_ascii=False)
        encoded_bytes = encoded.encode("utf-8")
    payload = encoded_bytes + b"\n"
    if hasattr(sys.stdout, "buffer") and sys.stdout.buffer is not None:
        try:
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
            return
        except Exception:
            pass
    try:
        sys.stdout.write(encoded + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.write(payload.decode("utf-8", errors="replace"))
        sys.stdout.flush()


def _bounded_lines(stream, limit: int):
    """Yield newline-delimited frames without waiting for EOF or calling stream.readline()."""
    raw_stream = getattr(stream, "buffer", None)
    if raw_stream is None or not hasattr(raw_stream, "read"):
        raw_stream = stream
    read_fn = getattr(raw_stream, "read1", raw_stream.read)
    pending = bytearray()
    oversized = False
    while True:
        chunk = read_fn(4096)
        if not chunk:
            if pending or oversized:
                yield bytes(pending).decode("utf-8", "replace"), oversized
            return
        if isinstance(chunk, str):
            encoded = chunk.encode("utf-8", "replace")
        else:
            encoded = bytes(chunk)
        for byte in encoded:
            if byte == 0x0A:
                yield bytes(pending).decode("utf-8", "replace"), oversized
                pending.clear()
                oversized = False
            elif not oversized:
                pending.append(byte)
                if len(pending) > limit:
                    oversized = True
                    del pending[limit:]


def main():
    logger.info("Starting Fable-Engine MCP Server on stdio...")
    if AutoUpdater is not None:
        try:
            AutoUpdater().trigger_silent_background_update()
        except Exception as e:
            logger.debug(f"Silent auto-updater background trigger failed in main: {e}")
    for line, oversized in _bounded_lines(sys.stdin, MAX_RPC_LINE_BYTES):
        if oversized:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        # Count the raw frame before trimming whitespace; otherwise an attacker
        # can bypass the line limit with an oversized whitespace prefix/suffix.
        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        line = line.strip()
        if not line:
            continue

        if len(line.encode("utf-8", "replace")) > MAX_RPC_LINE_BYTES:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        try:
            req = json.loads(line)
        except Exception:
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        # JSON-RPC requests are objects; arrays and scalar values must not
        # reach req.get() and crash the stdio server.
        if not isinstance(req, dict):
            send_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            send_response({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        if "params" in req and not isinstance(req["params"], dict):
            send_response({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32600, "message": "Invalid Request"}})
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "fable-engine",
                        "version": "1.3.0"
                    }
                }
            })

        elif method == "notifications/initialized":
            logger.info("Fable client handshake complete.")

        elif method == "ping":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {}
            })

        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [TOOL_SCHEMA]
                }
            })

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(tool_name, str) or not isinstance(arguments, dict):
                send_response({"jsonrpc": "2.0", "id": msg_id,
                               "error": {"code": -32600, "message": "Invalid Request"}})
                continue

            if tool_name == "fable_session":
                try:
                    result_text = handle_fable_session(arguments)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result_text
                                }
                            ],
                            "isError": False
                        }
                    })
                except Exception as ex:
                    logger.error(f"Error handling fable_session: {ex}", exc_info=True)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Fable Engine Error: {str(ex)}"
                                }
                            ],
                            "isError": True
                        }
                    })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method / Tool '{tool_name}' not found."
                    }
                })

        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unrecognized JSON-RPC method: {method}"
                    }
                })


if __name__ == "__main__":
    main()
