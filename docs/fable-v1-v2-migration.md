# Fable V1 to V2 entry points

## Current entry points

| Entry point | Version | Purpose |
|---|---|---|
| `fable-engine` | V1 (legacy) | Existing `fable_session` MCP server from `fable_engine.server` |
| `fable-v1` | V1 (legacy alias) | Explicit alias for `fable-engine` |
| `fable-v2-broker` | V2 | Process execution broker from `fable_v2.execution_broker` |

The existing `install.sh` and `install.ps1` scripts intentionally install and
register the V1 MCP server for backward compatibility. They now print that
fact explicitly. Installing the V2 Python package adds the `fable-v2-broker`
entry point; it does not silently replace the old MCP server.

## V2 execution boundary

Start the broker with a workspace it owns:

```bash
fable-v2-broker --workspace /path/to/workspace
```

The CLI loads write authorization from an administrator-controlled
`FABLE_BROKER_WRITE_TOKEN_DIGEST` environment variable or
`FABLE_BROKER_WRITE_TOKEN_DIGEST_FILE` protected file. The value is a SHA-256
hex digest of the administrative token; it is never returned by the broker's
probe response and must not be added to a model-facing tool schema.

Hosts should communicate with the broker over its JSON-lines stdin/stdout
protocol and route command execution and file writes through it. The broker
allowlists executables, constrains paths to the workspace, keeps writes locked
until administrative authorization, blocks general interpreters while writes
are locked, and runs commands without a shell. This prevents the common
`python -c "open(...)"` bypass at the broker policy layer.

This is a process/policy boundary, not a complete operating-system sandbox.
For hostile workloads, run the broker inside a container or equivalent OS
sandbox with least-privilege filesystem and network permissions.

## Migration order

1. Keep the V1 MCP server enabled while the host adapter is being tested.
2. Install the package and start `fable-v2-broker` in a dedicated workspace.
3. Probe the host and broker capabilities; treat expected profiles as
   non-authoritative until attested.
4. Route V2 tool calls through the broker and create candidate-scoped receipts.
5. Enable V2 finalization only after verifier and broker conformance tests pass.
6. Remove or disable the V1 MCP registration only after the host adapter has
   been validated on the target environment.
