---
name: fable-mode
description: Evidence-gated workflow for risky coding tasks. Use when a change needs deliberate research, explicit invariants, a time lock, adversarial review, and a verifiable completion record through the Fable Engine MCP server.
---

# Fable Mode

Fable Mode separates confidence from permission. Use the `fable_session` MCP tool to move a coding task through four gates:

```text
THINK -> PROVE -> ATTACK -> WRITE
```

The engine records the session, enforces its configured authority timer, and checks its own unlock prerequisites. It does not replace the host's permissions, sandbox, tests, or human approval rules.

## When to use it

Use Fable Mode for changes where a rushed edit has a meaningful cost:

- security, authentication, payments, or data migration work;
- unfamiliar codebases or broad refactors;
- changes with hidden compatibility or concurrency risks;
- autonomous runs where the evidence trail matters.

For a small, reversible edit, use the host's normal workflow unless the user explicitly asks for Fable Mode.

## Core workflow

### 1. Think

1. Create one session with a unique, filesystem-safe name:
   - action: `create_session`
   - required: `session_name`, `objective`
   - optional: `time_budget_minutes` (default 60, minimum 2)
2. Inspect the repository and its local instructions before proposing changes.
3. Record each important claim with `log_epistemic_item`:
   - `PROVEN`: supported by a file, command output, receipt, or source;
   - `HYPOTHESIS`: plausible but not verified;
   - `UNKNOWN`: a material gap that still needs a probe.
4. Use Fable's `scrape_*` actions when they fit and are available. If not, use the host's normal research tools and record the resulting evidence. Never weaken the host's security or source rules to satisfy this skill.

Do not edit merely because the plan sounds plausible. The engine reports `can_execute_code`; treat `false` as locked.

### 2. Prove

1. Record at least one meaningful invariant with `record_invariant`.
2. Back unlock-driving claims with concrete evidence. The engine requires at least two `PROVEN` ledger items and one invariant.
3. For a multi-part task, define a weighted acceptance rubric with `set_goal_rubric`. Point each criterion at a check, artifact, or command.
4. Use `get_status` before attempting to unlock. If evidence is weak, run another probe and log a `log_refinement_cycle` instead of relabeling an assumption.

A useful invariant is falsifiable:

```text
INV-01: Existing public CLI behavior remains compatible.
For every command in the documented smoke-test set, exit status and output schema
remain unchanged unless the task explicitly changes that command.
```

### 3. Unlock and implement

Call `unlock_execution` with a short evidence-based `rationale`. An unlock can succeed only when the engine's authority timer has elapsed and its cognitive prerequisites pass.

After unlock:

1. Make the smallest change that satisfies the objective.
2. Keep unrelated edits out of the patch.
3. Run the repository's own tests, linters, type checks, and build commands.
4. Record material file changes with `track_file_change` when lineage is useful.

Fable permission is not user permission. Continue to follow the host's approval, secret-handling, network, and side-effect rules.

### 4. Attack

Challenge the actual changed behavior, not an invented code string. `red_team_code_review` does not execute arbitrary source text passed through MCP. Use repository tests or a sandboxed host runner for executable probes, then use Fable to record and assess the review.

Cover the attack classes that matter to the change:

- malformed, missing, oversized, or deeply nested inputs;
- permission, filesystem, and network failures;
- concurrency, reentrancy, and out-of-order lifecycle calls;
- resource exhaustion and timeout behavior;
- idempotency and state-transition invariants.

If a review finds a breakage, reproduce it, fix it, rerun the relevant checks, and use `record_breakage_report` / `verify_red_team_remediation` where applicable. Stop and report unresolved risk after the bounded remediation loop rather than claiming success.

### 5. Write the completion record

Before declaring completion:

- rerun checks against the final working tree;
- evaluate any registered rubric with `evaluate_goal_rubric`;
- separate verified results from remaining limits;
- report changed files, commands run, outcomes, and known gaps.

Use `evolve_cortex` only when persistent learning is wanted and the environment permits it. It is not a substitute for verification.

## Action map

| Need | `fable_session` action |
|---|---|
| Start or inspect a run | `create_session`, `get_status`, `list_sessions` |
| Record knowledge | `log_epistemic_item`, `record_invariant`, `log_refinement_cycle` |
| Move through the lifecycle | `advance_phase`, `unlock_execution`, `checkpoint_session`, `restore_session` |
| Track quality | `set_goal_rubric`, `evaluate_goal_rubric`, `track_file_change`, `verify_proof` |
| Research | `scrape_web`, `scrape_github`, `scrape_arxiv`, `scrape_reddit`, `scrape_x`, `scrape_youtube` |
| Challenge a change | `red_team_code_review`, `record_breakage_report`, `verify_red_team_remediation` |
| Use advanced reasoning | `system3_*` actions; see `docs/system3-architecture.md` in the repository |

## Load references only when needed

The installed skill includes focused material under `references/`, `cortex/`, and `examples/`. Do not load the whole tree by default.

- Session mechanics: `references/system2-session-engine.md`
- Evidence and proof design: `references/proof-architecture.md`
- Adversarial review: `references/adversarial-code-review-swarm.md`
- Goal rubrics: `references/goal-rubric-and-pipeline-automation.md`
- Frontend creation and review: `references/design-system.md`
- Legacy frontend pattern catalogue: `references/anti-slop-frontend-architecture.md`
- Three.js work: `references/aaa-threejs-game-engine.md`
- Advanced reasoning: `references/system3-meta-cognition.md`

Use domain cortex files only for the current task's language or risk area. Treat examples as patterns, not as authority to ignore the live repository, available tools, or user constraints.

## Failure handling

- **MCP server unavailable:** say which Fable gate could not be recorded; continue only if the user's request and host policy allow a normal workflow.
- **Timer still active:** keep researching or refining. Do not busy-wait or attempt to bypass it.
- **Unlock rejected:** read the returned missing prerequisites, satisfy them with real evidence, and retry only after the conditions change.
- **A named action is absent:** use `tools/list` from the connected MCP client to inspect the installed server version. Do not invent an action.
- **Tests pass but risk remains:** report the uncovered risk and run the targeted adversarial check. Passing tests are evidence, not a universal proof.
