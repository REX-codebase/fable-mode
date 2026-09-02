# Migrate from Fable V1 to V2

V1 and V2 are intentionally separate entry points. Migration is an adapter
deployment exercise, not a package upgrade that silently changes an existing
MCP registration.

## Entry points

| Command or module | Version | What it does |
|---|---|---|
| `fable-engine` | V1 | Runs `fable_engine.server`, the legacy `fable_session` MCP server |
| `fable-v1` | V1 | Explicit alias for `fable-engine` |
| `fable-mode serve` | V1 | Package-aware launcher for the same MCP server |
| `fable-v2-broker --workspace PATH` | V2 | Runs the separate broker's JSON-lines execution boundary |
| `fable_v2.runtime` | V2 | In-process runtime library; no MCP server entry point |

The source helpers `install.sh` and `install.ps1` register V1 for backward
compatibility, while their private `runtime/` copy includes the complete V2
package (including `fable_v2/system3`). Installing the package does not replace
an existing host registration with V2. A source-helper V2 broker can be run
with `python -m fable_v2.execution_broker` using that runtime directory on
`PYTHONPATH`; V2 is never registered automatically.

## Suggested migration sequence

1. Keep the V1 registration and record its current host configuration.
2. Install the package in an isolated environment and run the V2 unit tests.
3. Start a broker against a dedicated, least-privilege workspace.
4. Build an adapter that probes the live host and calls `HostCapabilities.attest`.
5. Translate host tool calls into canonical capabilities and host-produced
   `ToolReceipt` objects.
6. Create `TaskSpec` and `VerificationPolicy` objects before generating a
   candidate; attach only evidence derived from successful receipts.
7. Run deterministic and independent verifiers, then inspect the finalization
   result. The independent verifier must cite measured provenance from a
   distinct producer (a same-receipt self-declaration is rejected). Require
   `process_attested` results when the deployment's trust model needs process
   isolation.
8. Exercise rollback and failure paths on the target OS and host.
9. Enable V2 for a small, non-sensitive workload while leaving V1 available.
10. Remove V1 only after the V2 adapter has passed conformance tests and users
    have a documented rollback path.

## Broker setup on POSIX

```sh
mkdir -p /absolute/path/to/fable-workspace
export FABLE_BROKER_WRITE_TOKEN_DIGEST="$(python3 -c 'import hashlib; print(hashlib.sha256(b"admin-secret").hexdigest())')"
fable-v2-broker --workspace /absolute/path/to/fable-workspace --admin-fd 3 3<>/path/to/private-admin-pipe
```

The example shows the boundary, not a recommended secret-management system.
Use a protected secret store or file with appropriate permissions. Do not put
the token, its cleartext, or the admin file descriptor in a model-facing tool
schema. The exact process-supervision and pipe setup belongs to the host
adapter.

When the source helper is given `--register-hosts --workspace PATH`,
Antigravity registration updates both its global
`~/.gemini/config/mcp_config.json` and `PATH/.agents/mcp_config.json`. Existing
unrelated keys are preserved, but both are real configuration side effects;
inspect them before allowing a host to use the registration.

## Compatibility caveats

- The broker's `--admin-fd` is POSIX-only in this implementation. Windows
  needs a separate protected control-handle adapter before V2 writes can be
  unlocked through this interface.
- A host profile is not proof of support; only live attestation is
  authoritative.
- V2's in-process verifier API is not a security boundary.
- V1 checkpoints restored by the server should be treated as untrusted input.
- Keep V1 and V2 data directories and workspaces separate while evaluating
  migration behavior.

See [`fable-v2-architecture.md`](fable-v2-architecture.md),
[`host-compatibility.md`](host-compatibility.md), and
[`security-and-trust.md`](security-and-trust.md) for the component and trust
boundaries.
