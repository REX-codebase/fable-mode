# Fable V2: Portable Verifier-Guided Runtime

## Goal

Fable V2 is a portable, model-agnostic intelligence runtime designed to work across AI agent hosts such as Antigravity, Claude Code, Cursor, OpenAI Codex, and others. Fable V2 aims to make coding models more reliable, consistent, and effective on verifiable software engineering tasks.

Rather than relying on unverified model assertions, Fable V2 coordinates models, tools, evidence receipts, search strategies, and verification policies.

## Design Principle

> Do not rely on an agent's unverified claim that work was performed correctly. Require the runtime to collect execution receipts, run verification checks, and accept only evidence-backed artifacts.

MCP serves as an interface and transport layer. Fable V2 provides the runtime around it: execution broker, evidence ledger, model router, candidate manager, verifier broker, and repair loops.

## Architecture

```text
User task
   |
   v
TaskSpec: objective, constraints, done conditions, required capabilities
   |
   v
Budget + model router ---- host capability probe
   |
   v
Diverse candidate fleet ---- tools / sandbox / execution broker
   |
   v
ToolReceipts & Evidence integrity ledger
   |
   v
Deterministic verifiers -> independent model verifiers -> repair/search loop
   |
   v
Finalization gate: accepts only passing, evidence-backed candidates
```

## Portable Core and Adapters

The core speaks a host-neutral JSON data contract (`fable_v2/protocol.py`). Adapters translate native host tools into standard capabilities such as `inspect_files`, `execute_command`, `run_tests`, `search_web`, `edit_files`, and `delegate_agents`.

Supported integrations are implemented as thin adapters. MCP is the primary tool binding, while CLI or HTTP interfaces accommodate hosts without native MCP support.

## Execution Boundary (`fable-v2-broker`)

`fable_v2.execution_broker` provides an isolated execution boundary for V2:
- Runs as a separate process (`fable-v2-broker`).
- Restricts executables via allowlists and runs commands without shell invocation.
- Constrains file operations and workspace paths.
- Keeps workspace file writes locked until administrative authorization.
- Blocks interactive interpreter bypasses while writes are locked.
- Accepts administrative unlock commands over a separate control handle (`--admin-fd` on POSIX) that is isolated from model input channels.

> **Security Note:** The broker is a process and policy boundary. Hostile or untrusted workloads should be executed within container or OS-level virtualized sandboxes with restricted permissions.

## Enforcement Model

### 1. Invocation Is Not Correctness
A `ToolReceipt` confirms that a tool was executed and captures its raw output hash. A successful `pytest` receipt proves test execution, but does not inherently guarantee overall solution correctness. Correctness is established by the configured `VerificationPolicy`.

### 2. Receipt and Evidence Integrity
Each tool execution generates a `ToolReceipt` containing:
- Session and tool identifiers
- Capability classification
- Hashes of tool input and output
- Execution status and timestamps

`Evidence` is constructed from receipts using `Evidence.from_receipt(...)`. Content hashes are verified to prevent tampering or mismatched output claims.

### 3. Policy-Enforced Verification
Finalization requires satisfying the `VerificationPolicy`:
- Verification verdicts are runtime-attested and bound to specific candidate artifact hashes.
- Verification commitments include candidate state and referenced receipt/evidence hashes.
- Deterministic checks (linters, test runners, type checkers) execute prior to model-based judges.

## Runtime Objects (`fable_v2/protocol.py`)

- `TaskSpec`: Task contract, objectives, required capabilities, and definition of done.
- `VerificationPolicy`: Required verifier classes and passing thresholds.
- `ToolReceipt`: Invocation receipt containing input/output hashes and execution metadata.
- `Evidence`: Provenance-backed claim constructed from a valid `ToolReceipt`.
- `Candidate`: A specific solution trajectory or artifact.
- `VerificationResult`: Runtime-attested verdict bound to a candidate artifact.

## Quality & Verification Rules

1. **No Self-Attested Verification:** Claims must be backed by tool execution receipts.
2. **Deterministic Before Model Verification:** Machine checks run prior to model judges.
3. **Independent Review:** Generator and verifier components remain separate for complex tasks.
4. **Targeted Repair:** Failed verification attempts yield structured failure classifications for targeted iteration.
5. **Gated Finalization:** Candidate finalization requires complete receipt and policy satisfaction.
6. **Isolated Permission Enforcer:** Workspace permissions are enforced by the execution broker/sandbox boundary.
