# Fable V2: Portable Verifier-Guided Runtime

## Goal

Build a portable, model-agnostic intelligence runtime that works across
Antigravity, Claude Code, Codex, Grok Build, Cursor, Zapia, and other agentic
hosts. Fable V2 should make weak-but-functional models dramatically more
useful on verifiable task classes and make frontier models more reliable,
consistent, and efficient.

The ambitious targets are hypotheses to be measured, not guarantees:

- Up to 10x improvement in system-level effectiveness for frontier models
  (verified success, failure reduction, or successful tasks per cost).
- Up to 50x relative improvement for weak models on selected tasks where the
  baseline has non-zero competence.

A model cannot be made universally 10x more intelligent by a prompt. Fable
scales useful work by coordinating models, tools, evidence, search, repair,
and verification.

## Design principle

> Do not ask an agent to claim that it did good work. Make the runtime collect
> receipts, run checks, and accept only a verified artifact.

MCP is a transport/interface layer. Fable V2 is the runtime around it: a
controller, evidence ledger, model router, candidate manager, verifier broker,
repair loop, and host adapters.

## Architecture

```text
User task
   |
   v
Task compiler: objective, constraints, done conditions, required capabilities
   |
   v
Budget + model router ---- host capability probe
   |
   v
Diverse candidate fleet ---- tools / sandbox / retrieval
   |
   v
Evidence receipts and failure classification
   |
   v
Deterministic verifiers -> independent model verifier -> repair/search loop
   |
   v
Finalization gate: only a passing, evidence-backed artifact is accepted
```

## Portable core and adapters

The core speaks a host-neutral JSON/data contract. Adapters translate native
host tools into capabilities such as `inspect_files`, `execute_command`,
`run_tests`, `search_web`, `edit_files`, and `delegate_agents`.

Supported integrations should be implemented as thin adapters, not forks of
the cognitive engine. MCP is the preferred tool binding, but a CLI or HTTP
adapter is required for hosts that do not expose MCP.

## Execution boundary

`fable_v2.execution_broker` provides the first concrete execution boundary for
V2. `fable-v2-broker` runs as a separate process, allowlists executables,
executes without a shell, constrains working directories and file writes to a
configured workspace, and keeps writes locked until administrative
authorization. General interpreters and shell entry points are also blocked
while writes are locked, because `shell=False` does not stop a command such as
`python -c "open(...)"` from writing files. Hosts must route V2 command
execution and writes through this broker instead of giving the model direct
filesystem access. The administrative unlock is accepted only on a separate
inherited control handle (`--admin-fd` on POSIX), never through the model's
JSON-lines request channel.

This is a process and policy boundary, not a complete operating-system sandbox.
For a hardened deployment, the broker process must run with an OS-enforced
read-only workspace before authorization, then receive a separately controlled
writable layer or remount after authorization.
Hostile workloads still require container/VM isolation and least-privilege OS
controls. The broker resolves each allowlisted executable to a trusted absolute path at
startup and rejects requests whose resolved path differs; a matching basename
is not sufficient. Command stdout/stderr are drained concurrently into bounded
buffers; exceeding `max_output_bytes` terminates the process (and its POSIX
process group) instead of truncating after unbounded `subprocess.run()` capture.
The broker implements every advertised protocol capability, including bounded
`inspect_files` and the `probe_capabilities` alias. It is covered by
child-process, executable-path, output-limit, capability, allowlist,
path-containment, and locked-write tests.

The checked-in `HOST_PROFILES` are explicitly **expected capability
profiles**, not attestations. They are useful defaults for planning and
documentation, but they are not runtime-authoritative. A live adapter must
probe the host at startup and call `HostCapabilities.attest(...)` with the
observed capabilities. Compatibility is authoritative only after that probe;
a host must never receive a full-guarantee status merely because it loaded a
prompt or matched a hard-coded profile.

## Enforcement model

### Invocation is not correctness

A `ToolReceipt` proves only that a host tool was invoked and what output it
returned. For example, a successful `pytest` receipt proves that pytest ran
successfully; it does **not** prove that the candidate is correct. Likewise,
integrity-bound evidence proves provenance and content consistency, not that
its claim is true.

Correctness is established only by the verifier policy: deterministic tests,
machine checks, independent review, hidden tests, or other explicitly
registered checks. A receipt or evidence object must never be treated as a
correctness verdict.

### Receipt and evidence integrity

A model-facing prompt cannot prove that a tool was used. Each host tool must
produce a `ToolReceipt` containing:

- session and tool identity;
- normalized capability;
- hashes of tool input and output;
- success/failure status;
- timestamps and host metadata.

Evidence must be constructed from a successful receipt using
`Evidence.from_receipt(...)`. The receipt retains the actual tool output and
its canonical hash; construction recomputes the content hash, and attachment
rejects any mismatch between evidence content, evidence hash, and the receipt
output hash. A candidate cannot be finalized until the task's declared
capabilities and evidence kinds have been satisfied and its
`VerificationPolicy` has passed.

Verification is policy-enforced, not a free-form boolean. A result supplied
from a model-facing call is rejected. The in-process foundation API runs a
verifier against the exact candidate artifact and runtime-attests that
invocation with the candidate hash. The attestation also includes a candidate
dependency-graph commitment: the candidate state and authenticated object
hashes for every referenced `ToolReceipt` and `Evidence`, including receipt
capability/success fields and evidence provenance. Restore recomputes this
commitment before accepting a stored verdict, so changing receipt/evidence
references or their serialized state invalidates the verdict. This blocks
forged model results, but it is **not** a security boundary against arbitrary
Python application code: an in-process caller can still construct or alter
verifier code. The task policy can require verifier classes such as
`deterministic`, `machine-check`, and `independent`, a minimum number of
passing verifiers, and a minimum trust boundary. The current foundation
supports `in_process`; production-grade `process_attested` results must come
from a separate broker with process isolation and signed/ authenticated
registrations.

Semantic trust in a model judge remains an explicit deployment decision and
should be backed by calibration and hidden tests.

Deterministic verifiers should be executed before independent model judges by
the host orchestrator. The core records the order and rejects missing policy
classes, but it does not pretend that an arbitrary `VerificationResult` proves
anything.

The runtime enforces required capabilities and verifier classes for the task,
not every available tool. Required capabilities are resolved exclusively from
the selected candidate's referenced successful receipts; work performed only
by another candidate cannot satisfy the policy. Requiring irrelevant tools
would create waste and tool theatre.

## Runtime objects

The initial portable contract is implemented in `fable_v2/protocol.py`:

- `TaskSpec`: task contract and definition of done;
- `VerificationPolicy`: required verifier classes and pass thresholds;
- `ToolReceipt`: host-produced invocation receipt with the actual output hash;
- `Evidence`: claim constructed from receipt output and integrity-bound to it;
- `Candidate`: one solution or trajectory;
- `VerificationResult`: runtime-attested verdict bound to one candidate artifact.

`fable_v2/runtime.py` implements the evidence-gated run state machine. It is
intentionally model-agnostic and dependency-free. Hosts can wrap compilers,
test runners, browsers, citation checkers, symbolic tools, or model judges
behind the same verifier contract in `fable_v2/verifiers.py`.

## Quality and safety rules

1. No self-attested `[PROVEN]` claims.
2. Deterministic checks run before model judges.
3. Generator and verifier should be independent for difficult tasks.
4. Failed attempts are classified and reused for targeted repair.
5. Compute is allocated adaptively; a fixed waiting timer is not computation.
6. Finalization is rejected when receipts, evidence, or verification are missing.
7. Execution permissions must ultimately be enforced by a sandbox/broker, not
   only by a model-facing MCP flag.
8. All host adapters run the same conformance tasks and report unsupported
   capabilities honestly.

## Implementation sequence

1. Benchmark harness: compare model-alone, current Fable, and Fable V2 on a
   held-out task set with success, cost, latency, and failure metrics.
2. Task compiler and typed event log.
3. Candidate manager with diverse/parallel trajectories.
4. Verifier broker for tests, citations, schemas, and independent judges.
5. Failure classification and targeted repair loop.
6. Host adapters and capability conformance suite.
7. Persistent experience store, model router, and optional learned verifier.
8. Publish results only after hidden evaluation; do not claim 10x/50x from
   plumbing tests.

## Boundary-test coverage

The foundation test suite covers failure modes that can silently turn a
receipt ledger into a false correctness oracle:

- cross-candidate and mismatched-evidence verification;
- evidence/source hash mismatches;
- duplicate or contradictory verifier results;
- verifier invalidation after a prior pass;
- malformed and reversed timestamps;
- mutable metadata and artifact snapshotting;
- run serialization round-trips;
- concurrent candidate registration;
- expected versus probed capability aliases;
- verifier policy enforcement; and
- tampered event-history detection.

The suite is still a runtime-foundation suite. It does not replace real host
adapters, sandbox tests, hidden task benchmarks, or calibration of model-based
judges.

## Checkpoint trust boundary

`FableRun.to_dict()` and `from_dict()` provide serialization and restoration,
not a generally tamper-proof audit artifact. Each verification attestation now
covers a canonical hash of the complete immutable `VerificationResult` (apart
from the attestation itself), and restoration revalidates every restored
verdict against its candidate, evidence, and attestation before it can affect
finalization. The event hash chain detects edited or reordered events, but the
experimental checkpoint currently stores the HMAC attestation secret in the
same payload. Someone who can rewrite that payload could rewrite state and
recompute the in-process HMAC.

Production checkpoints must keep signing keys outside the serialized state,
ideally in an external key store or isolated broker. The broker should sign
the canonical complete checkpoint, verify a monotonic checkpoint sequence,
and refuse to restore trusted verification state from an unsigned or invalid
checkpoint. The current round-trip test proves serialization correctness only;
it is not a security test.

## Success criteria

For each target domain, publish:

- baseline success rate and confidence interval;
- Fable V2 success rate and confidence interval;
- relative success and error reduction;
- successful tasks per token/dollar;
- latency and tool-call counts;
- verifier false-positive rate;
- performance across at least two hosts and two model sizes.

The weak-model 50x target is meaningful only when the baseline is non-zero
and the absolute result is useful. The frontier-model 10x target should be
reported primarily as reliability, failure reduction, or cost efficiency,
because raw accuracy is bounded by 100%.
