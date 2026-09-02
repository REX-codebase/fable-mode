# V1 design notes and theory

This document keeps the useful reasoning behind Fable V1 without presenting
hypotheses as measured results or workflow checks as proofs of correctness.

## What V1 is trying to change

V1 is a session manager for an AI host. It makes a host record observations,
open questions, proposed invariants, and refinement work before the host asks
the server to unlock its workflow. The intended benefit is less premature
execution on tasks where explicit planning and verification are useful. That
benefit is a hypothesis to measure per host and task set; it is not an
accuracy, quality, or speed guarantee.

The design draws on dual-process vocabulary and adversarial review patterns.
Those are organizing metaphors, not a claim that the server implements a human
mind, formal cognition, or a universally valid reasoning method.

## Evidence labels

The V1 ledger accepts three labels:

| Label | Meaning in the session | What it does not mean |
|---|---|---|
| `PROVEN` | The caller supplied a non-empty evidence pointer, such as a file path, command output, test result, or URL | The server has independently established that the claim is true |
| `HYPOTHESIS` | A proposed explanation or design assumption | A fact safe to use without checking |
| `UNKNOWN` | A missing value, constraint, or question to probe | A failure or a negative result |

The server checks the shape of a `PROVEN` entry and records the supplied
pointer. A model can still provide misleading evidence. Treat the label as a
ledger status, not as a correctness verdict.

## Phases and unlock gates

The six phases are sequential:

1. Epistemic Grounding and Live Research
2. Invariant Specification and Blueprint
3. Adversarial Red-Teaming and Falsification
4. Subagent Fleet Delegation
5. Multi-Tier Verification and Gatekeeping
6. Final Walkthrough and Reporting

`unlock_execution` requires the authority deadline to have elapsed, at least
two evidence-bearing `PROVEN` entries, at least one invariant with a proof or
rationale, and Phase 3 or later. `set_timer` changes only the internal pacing
timer. These are admission conditions in the V1 session state; they do not
compile, test, or authorize arbitrary filesystem operations.

The outer budget is created with `create_session` and is immutable for that
session. The default is 60 minutes; the accepted range is 0.1 minutes through
seven days. A session may be saved and restored, but restored ledger entries
are marked untrusted and do not satisfy the unlock evidence gate on their own.
An administrator can configure an out-of-band emergency token for direct host
use; the token is intentionally absent from the MCP schema. Do not put it in a
model prompt or tool request.

## Why not probabilistic scoring?

A language model's self-reported score is not independent evidence. V1 instead
asks a host to collect concrete observations and to name checks. This does not
make the observations correct, and it does not replace deterministic tests,
independent review, or hidden evaluation. The design should therefore be
judged by held-out task results rather than by the number of ledger entries or
time spent waiting.

## Refinement and role separation

`log_refinement_cycle` records a critique, a proposed refinement, and optional
probe output or an artifact path. It is an audit-friendly record, not a proof
that the refinement improved a system. A host may use the record to structure
an architect/implementer workflow, but V1 does not create or supervise an
actual subagent fleet. `compile_delegation_contract` validates required fields
in a prompt; it does not dispatch a worker or verify the worker's output.

## CAS and payload helpers

The payload helpers provide content-addressed storage and bounded reads; they
do not promise that every payload becomes smaller or saves a fixed number of
tokens. Displayed token counts and the optional `<= 0.003 tokens/character`
check are rough character-based estimates for diagnostics, not measured
model-token usage or guarantees. A `cas://` reference is an
integrity/addressing mechanism: normal reads
verify the SHA-256 named by the reference. It is not encryption, access control,
authenticity, or a claim that a payload is safe. The optional low-level
`verify=False` API is a maintenance escape hatch and must not be used for
model-visible content.

## Limitations to keep visible

- V1's lock state lives in the Python server and is not an OS permission.
- Host tools, shells, direct filesystem access, and subagent behavior remain
  under the host's control unless that host adds its own boundary.
- The stdio protocol is local-process IPC; it does not provide network
  authentication or multi-tenant isolation.
- Checkpoints are useful persistence, not signed audit artifacts. Keep keys
  and stronger authorization outside serialized state when deploying a
  higher-trust system.
- Runtime tests exercise implementation paths; they are not evidence of
  universal security or model effectiveness.
