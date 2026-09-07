# Fable V1 to V2 Migration & Integration Guide

## Overview of Entry Points

| Entry Point | Version | Purpose |
|---|---|---|
| `fable-engine` | V1 | Main `fable_session` MCP server from `fable_engine.server` |
| `fable-v1` | V1 | Explicit alias for `fable-engine` |
| `fable-v2-broker` | V2 | Out-of-process workspace execution broker from `fable_v2.execution_broker` |

The `install.sh` and `install.ps1` scripts register the V1 `fable-engine` MCP server by default for backward compatibility with existing MCP clients. Installing the Python package (`pip install -e .`) registers the `fable-v2-broker` executable without replacing the V1 MCP server.

---

## V2 Execution Broker Setup

Start the V2 execution broker specifying its managed workspace:

```bash
fable-v2-broker --workspace /path/to/workspace
```

### Authorization & Control Pipe
- The broker loads write authorization digest from the `FABLE_BROKER_WRITE_TOKEN_DIGEST` environment variable or `FABLE_BROKER_WRITE_TOKEN_DIGEST_FILE` file. This value is a SHA-256 digest of an administrative token.
- Unlocking write permissions requires communicating over a dedicated administrative control descriptor (`--admin-fd` on POSIX). The model-facing JSON-lines channel cannot issue unlock commands directly.
- Host integration adapters should keep administrative file descriptors isolated from model tool definitions.

### Process & Path Restrictions
- The broker allowlists permitted executables and runs commands without shell invocation (`shell=False`).
- Working directories and file writes are constrained to the designated workspace.
- Interpreter execution is restricted while writes are locked to prevent inline write bypasses.

> **Security Note:** The broker operates as a process and policy boundary. For untrusted code execution, run the broker inside a container or sandboxed OS environment with restricted permissions.

---

## Migration Sequence for Hosts & Adapters

1. **Keep V1 MCP Enabled:** Maintain the `fable-engine` MCP server active during initial adapter testing.
2. **Launch V2 Broker:** Start `fable-v2-broker` with its dedicated workspace directory.
3. **Probe Host Capabilities:** Query host capabilities at runtime and verify attested features.
4. **Issue Tool Receipts:** Route V2 command executions and file operations through the broker to generate `ToolReceipt` objects.
5. **Enforce Verification Policies:** Enable candidate finalization once verifier checks pass.
6. **Final Transition:** Disable legacy V1 tools only after validating V2 execution broker flows in your environment.
