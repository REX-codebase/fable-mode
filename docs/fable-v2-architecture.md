# Fable V2 architecture (experimental)

Fable V2 is a portable, model-agnostic runtime foundation. It is separate
from the V1 MCP server and is not yet a drop-in replacement. The package
contains contracts and enforcement code; a host adapter still has to connect
those contracts to a model host, tools, and a deployment's verifier services.

## Design goal

Instead of accepting a model's statement that work is complete, a V2 adapter
can collect tool receipts, bind evidence to those receipts, run declared
verifiers, and accept only a candidate that meets the task policy. This can
improve auditability and may improve reliability on verifiable tasks. The
magnitude and direction of any improvement are empirical questions. No fixed
effectiveness, accuracy, cost, or latency claim is made by the runtime.

## Components

```text
Host adapter
    | translates native tools and model events
    v
TaskSpec + VerificationPolicy
    |
    v
FableRun: state machine and event history
    |-- Candidate artifacts
    |-- ToolReceipt objects (host-produced invocation records)
    |-- Evidence objects bound to successful receipts
    `-- Registered verifiers
             |
             v
       attested VerificationResult objects
             |
             v
       finalization gate

Separate execution path:
Host adapter --> fable-v2-broker (child process)
                    |-- probe capabilities
                    |-- inspect files
                    |-- execute an allowlisted argv
                    `-- write a workspace file (locked by default)
             administrator control handle -- unlock writes
```

`FableRun` is in-process Python code. `fable-v2-broker` is a separate process
and communicates with a bounded JSON-lines protocol. It retains its native
`action` envelopes and also accepts the small MCP JSON-RPC compatibility
surface (`initialize`, `tools/list`, `tools/call`, and `ping`) for generic
harnesses. The broker should be the only component granted workspace write
access in a deployment;
the broker itself is still a policy boundary rather than a complete OS
sandbox. Use containers, VMs, OS mandatory access controls, job objects, or
similar controls for hostile workloads.

## Protocol objects

The public foundation types are in `fable_v2/protocol.py`:

- `TaskSpec`: objective, constraints, definition of done, capabilities, and
  required evidence.
- `VerificationPolicy`: required verifier classes, passing threshold,
  independence requirement, and minimum trust boundary.
- `ToolReceipt`: host-produced input/output hashes and captured output.
  `success` means invocation completed; it does not mean the candidate is
  correct.
- `Evidence`: content and claim integrity-bound to one successful receipt.
  Integrity binding proves provenance and consistency, not truth.
- `Candidate`: one artifact/trajectory and its receipt/evidence references.
- `VerificationResult`: runtime-attested result bound to the candidate artifact
  and its dependency graph.

`fable_v2/runtime.py` supplies `FableRun` and the states `created`, `active`,
`verifying`, `finalized`, and `rejected`. The runtime rejects missing
receipts/evidence, mismatched hashes, unrelated evidence, and un-attested
passing results. Its default verifier trust boundary is `in_process`, which is
an application convention, not a security boundary. A production deployment
should use an isolated process and an authenticated registration for
`process_attested` results.

## Intelligent verification pipeline

The intelligent-verifier layer is deterministic orchestration, not an
additional source of authority. Its public API is exported from
`fable_v2`: `Claim`, `ClaimGraph`, `RiskLevel`, `Counterexample`,
`CounterexampleStore`, `VerificationDecision`, `VerifierDecision`, `VerifierStatus`,
`Verdict`, `FunctionVerifier`, `CompositeVerifier`, `PropertyVerifier`,
`MetamorphicVerifier`, `MutationVerifier`, `VerifierPortfolio`,
`PortfolioResult`, `VerifierPlanner`, `VerifierPlan`, `PlannedCheck`,
`ThreeValuedAdjudicator`, and `Adjudication` (plus the `Verifier`,
`MutationOperator`, `MetamorphicRelation`, and `PropertyCheck` protocols and
`CalibrationMetrics`).

`ClaimGraph.from_task(task, candidate)` decomposes the objective, constraints,
definition of done, required capabilities, and required evidence into atomic,
scoped, falsifiable `Claim` objects. Stable claim IDs and dependency edges
make coverage auditable; decomposition does not prove any claim. A
`VerifierPlanner` uses risk, declared uncertainty, expected information gain,
calibration, and cost to produce an auditable `VerifierPlan`. This is a
selection heuristic: it may leave claims uncovered and cannot make an
unverified claim true.

Verifier checks and `VerifierPortfolio` use three-valued outcomes:
`PASS` establishes only the check's declared, evidenced claims; `FAIL` is a
blocking falsification; and `UNKNOWN` means that the check did not establish a
verdict. The portfolio propagates `FAIL` over `UNKNOWN` over `PASS`, while
`ThreeValuedAdjudicator` marks missing coverage and (by default) critical
unknowns as blocking. `Counterexample` records observations that falsify a
claim, and `CounterexampleStore` preserves and propagates those observations
to the affected claims. A counterexample or a failing check cannot be hidden
by a later pass.

Every verification result must be integrated with the same `FableRun` that
owns the candidate: register the candidate, execute the registered verifier
through `FableRun.execute_verifier(...)`, and let the run record the resulting
`VerificationResult` before calling its finalization gate. Directly fabricating
or recording a passing result is rejected; an independent result also needs
measured, disjoint provenance. A planner or model may propose checks, but the
run and adjudicator remain mandatory acceptance gates. The layer does not
supply truth, generate evidence, isolate untrusted verifier code, or replace a
host's process-attestation service. In-process verifiers are therefore useful
for deterministic application checks but are not a security boundary, and an
UNKNOWN or uncovered claim must remain unresolved rather than being promoted
to PASS.

## Adapter contract and host profiles

`fable_v2/adapters.py` contains conservative expected profiles for
Antigravity, Claude Code, Codex, Cursor, Grok Build, and Zapia. Profiles are
planning defaults only. An adapter must probe the live host and call
`HostCapabilities.attest(...)`; only an attested profile is authoritative in
`compatibility_report`. Unknown hosts start with no expected capabilities.

Canonical capability names include `inspect_files`, `execute_command`,
`edit_files`, `run_tests`, `search_web`, and `delegate_agents`. Adapters may
normalize host names such as `run_command`, `shell`, or `terminal`, but should
not claim a capability merely because a host has a similarly named tool.

## Execution broker

Start the broker with an existing workspace:

```sh
fable-v2-broker --workspace /absolute/path/to/workspace
```

Optional repeated `--allow-executable NAME` arguments replace the default
allowlist (`python`, `python3`, and `pytest`). The broker resolves allowlisted
executables at startup and runs commands without a shell. It bounds request
frames, diagnostics, output, timeouts, and workspace paths. While writes are
locked, it also blocks general interpreters and shell entry points because
`shell=False` alone would not stop an interpreter from writing files.

On POSIX, an administrator may provide an inherited control pipe with
`--admin-fd FD`. Configure either `FABLE_BROKER_WRITE_TOKEN_DIGEST` or
`FABLE_BROKER_WRITE_TOKEN_DIGEST_FILE` with a SHA-256 digest, never both. The
admin channel receives the unlock token; the model-facing request channel has
no unlock action or token field. The current implementation rejects
`--admin-fd` on Windows, so an equivalent Windows control-handle adapter is
not supplied by this repository yet.

The broker prevents common policy bypasses and constrains paths, but it does
not provide a complete OS sandbox, network isolation, or protection from a
privileged process. Review [`docs/security-and-trust.md`](security-and-trust.md)
and [`docs/mcp-reference.md`](mcp-reference.md) before deployment.

## Verification order and benchmark discipline

A host should run deterministic checks before independent model judges, bind
all results to the exact candidate artifact, and classify failed attempts for
repair. The default policy does not trust an independent label by itself: an
independent result must cite measured provenance from a distinct producer, or
come through an externally process-attested verifier. A same-receipt,
in-process self-declaration therefore cannot satisfy the independent gate. A
receipt proves invocation and output capture only. Results should be reported
using the benchmark template in
[`docs/benchmark-methodology.md`](benchmark-methodology.md), with a held-out
task set, baselines, confidence intervals where appropriate, cost, latency,
tool counts, and verifier false-positive/negative analysis. Do not publish
uplift multipliers from plumbing tests or from a task set used to tune the
system.

## Current scope

Implemented foundation: protocol dataclasses, evidence/hash validation, run
state transitions, event history checks, in-process verifier execution, host
capability profiles, and the broker. Not implemented as a complete product:
model routing, a production verifier service, universal host adapters, signed
checkpoints, network authorization, or a benchmark result demonstrating model
improvement.
