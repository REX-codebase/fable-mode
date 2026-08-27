# Prompt Scaffolds & Mental Frameworks

This reference contains reusable cognitive scaffolds, Deterministic System 2 deliberation traces, the **Continuous Rethink-Refine Refinement Cycle Trace**, `fable_session` working memory ledgers, time-budget trackers, and self-prompting templates. When executing complex tasks or solving hard problems, inject these frameworks into your internal reasoning process.

--------------------------------------------------------------------------------

## 1. Deterministic System 2 Deliberation & Epistemic Trace Scaffold

Inject this template during architectural, algorithmic, or systems reasoning to structure your deliberation and feed data into `fable_session`:

```markdown
### 🌲 DETERMINISTIC SYSTEM 2 DELIBERATION TRACE (`[ARCHITECTURE | DESIGN | CODING]`)
**Session Name**: `session_name_01` (WAL Enabled | Mechanical Time-Lock: ACTIVE)
**Domain Focus**: `Architecture | Design | Coding`
**Time Budget**: `Allocated: 2400s (40 min)` | `Time-Lock Deadline: t_deadline`

#### 1. Epistemic Calibration & Grounding
- **[PROVEN]**: <Fact 1 verified via live tool execution (view_file / run_command)>
- **[PROVEN]**: <Fact 2 verified via compiler / AST dump>
- **[HYPOTHESIS]**: <Assumption undergoing verification>
- **[UNKNOWN]**: <Parameter to probe via terminal or web>
*(Logged to session via fable_session: log_epistemic_item)*

#### 2. Axiomatic Lower Bounds & Limits
- Minimum memory allocations: `0-alloc in hot path`
- Cache line alignment: `64 bytes, false-sharing padded`
- Synchronization barriers: `Acquire-Release fences only, no SeqCst locks`

#### 3. Multi-Archetype Pareto Exploration (Zero-Rush)
- **Archetype A (Conservative)**: <Battle-tested pattern description>
- **Archetype B (Zero-Overhead)**: <Lock-free / zero-alloc candidate>
- **Archetype C (Asymmetric / Event-Driven)**: <Channel / actor pipeline>
- **Counter-Example / Stress Challenge**: <Hostile edge-case attack>

#### 4. Dialectical TRIZ Synthesis
- **Contradiction**: <Metric X vs Metric Y (e.g. Throughput vs Consistency)>
- **Operator Applied**: <Separation in Time / Space / Asymmetry / Inversion>
- **Breakthrough Hybrid**: <Non-compromising architectural synthesis>

#### 5. Formal Invariant Verification
- **Invariant 1**: <Mathematical / Concurrency Invariant Statement>
  - *Proof / Safety*: <Formal Acquire-Release / Linearizability Proof>
  - *Status*: `VERIFIED` *(Recorded via fable_session: record_invariant)*

#### 6. Multi-Criteria Vector Evaluation
- Correctness & Invariants (35%): `0.98`
- Performance & Scale (25%): `0.96`
- Blast Radius & Fault Tolerance (25%): `0.94`
- Maintainability & Ergonomics (15%): `0.92`

#### 7. Continuous Refinement & Quality Gate
- **Refinement Loop**: If time remains before deadline, enter `RETHINK-REFINE` cycle.
- **DoD Checklist**: `All Invariants Proven [✓], Interfaces Locked [✓], Test Suite Specified [✓]`
- **fable_session Action**: `unlock_execution` (invoked only after time-lock expires) -> Transition to Phase 4.
```

--------------------------------------------------------------------------------

## 2. Continuous Rethink-Refine Refinement Cycle Trace Scaffold

Inject this template when executing iterative refinement passes while time remains on the budget clock:

```markdown
### 🔁 RETHINK-REFINE REFINEMENT CYCLE TRACE (Cycle #<Index>)
- **Session Reference**: `session_name_01`
- **Time-Lock Status**: `ACTIVE` | `Remaining Time: 1120s (46.6%)`
- **Focus Area**: `[archetype_mutation | falsification_probe | cache_line_alignment | invariant_stress_test | terminal_probe | proof_tightening]`

#### 1. Hypothesis Under Stress
- **Target Component**: `<Module / Trait / Atomic State Machine>`
- **Current Assumption**: `<Baseline pattern or invariant currently assumed>`
- **Vulnerability / Inefficiency Probed**: `<False sharing, thread preemption, lock contention, excessive copies>`

#### 2. Empirical Terminal Probe / Scratch Benchmark (run_command)
- **CLI Command Run**: `<cargo bench / ast dump / python micro-benchmark>`
- **Observed Result**: `<Empirical throughput, latency, cache misses, or assembly output>`

#### 3. Refinement Mutation & Proof Delta
- **Structural Delta**: `<What was mutated: e.g. added #[repr(align(64))], changed SeqCst to Acquire/Release>`
- **Mathematical / Invariant Proof Delta**: `<How the proof became tighter or invariant expanded>`
- **Trade-off Impact**: `<Measured or theoretical delta: e.g. eliminated 12ns L1 line bounce>`

#### 4. Session MCP Logging
- **MCP Action**: `log_refinement_cycle`
  ```json
  {
    "action": "log_refinement_cycle",
    "session_name": "session_name_01",
    "cycle_index": 2,
    "focus_area": "cache_line_alignment",
    "delta_improvement": "Isolated head and tail atomic pointers across distinct 64-byte cache lines; eliminated false sharing.",
    "telemetry_notes": "Verified via assembly inspection in scratch probe."
  }
  ```
```

--------------------------------------------------------------------------------

## 3. Live Run Telemetry & Time-Budgeted Working Memory Ledger

Inject this template during long-horizon tasks and time-budgeted sessions (e.g. 30 min, 40 min, 4 hr, 24 hr) to maintain live run self-awareness and pacing:

```markdown
### 📋 LIVE RUN TELEMETRY & TIME LEDGER
- **Primary Mission**: <Overarching Goal Description>
- **fable_session**: `session_name_01` | **Active Phase**: `Phase 4: Orchestrated Subagent Implementation`
- **Mechanical Time-Lock**: `ELAPSED & UNLOCKED` (DoD Verified)
- **Refinement Cycles Completed**: `4 cycles logged (log_refinement_cycle)`
- **Role Execution**: Main Agent (Architect) | Subagent Coder `subagent_01` (Implementer)
- **Brain Artifacts Generated**:
  - Implementation Plan: `brain/<conversation-id>/implementation_plan.md`
  - Architectural Blueprint: `brain/<conversation-id>/architecture_blueprint.md`
- **Time Budget & Pacing**:
  - Allocated Target ($T_{\text{budget}}$): `2400s (40 min)`
  - Elapsed Time ($t_{\text{elapsed}}$): `2415s (100.6%)`
  - Remaining Time ($t_{\text{remaining}}$): `0s (Time-lock elapsed)`
  - Active Phase Budget: `Phase 4: Implementation (allocated 840s, spent 320s)`
- **Current Milestone**: Milestone `3` of `5` (<Short description>)
- **Verified Invariants / Completed**:
  - [✓] <Task / Invariant 1>
  - [✓] <Task / Invariant 2>
- **Current Blocker / In-Flight Work**: <Active investigation or component modification>
- **Next Tactical Action**: <Dispatch self subagent with exact file targets & test commands>
```

--------------------------------------------------------------------------------

## 4. The 8-Pass Maximum-Depth Recursive `<thinking>` Scaffold

Inject this template inside your internal `<thinking>` block during complex architectural, algorithmic, or high-stakes system design:

```markdown
### 🧠 8-PASS MAXIMUM-DEPTH RECURSIVE <THINKING> CHAIN

#### [PASS 1: EPISTEMIC CALIBRATION & INVARIANT EXTRACTION]
- **Time Target & Depth Allocation**: <$T_{\text{budget}}$ e.g. 40 min / 2400s>
- **[PROVEN FACTS]**: <Hard verified facts, compiler requirements, verified APIs>
- **[HYPOTHESES]**: <Assumptions needing validation>
- **[UNKNOWN & RISKS]**: <Ambiguities, unchecked edge limits>
- **Binary Invariants**: <Invariants that must hold 100% across all states>

#### [PASS 2: AXIOMATIC LOWER BOUNDS & HARDWARE TOPOLOGY]
- **Memory Allocations**: <Theoretical minimum copies/allocations (e.g. 0-alloc in hot path)>
- **Cache Line Boundaries**: <64-byte alignment, padding to avoid false sharing>
- **Synchronization Barriers**: <Minimal acquire-release fences, lock-freedom bounds>

#### [PASS 3: MULTI-ARCHETYPE PARETO EXPLORATION]
- **Archetype A (Conservative / Battle-tested)**: <Design description>
- **Archetype B (Zero-Overhead / Performance-maximal)**: <Design description>
- **Archetype C (Asymmetric / Event-driven / Decoupled)**: <Design description>
- **Archetype D (Adversarial stress challenge)**: <Falsification probe candidate>

#### [PASS 4: DIALECTICAL TRIZ CONTRADICTION RESOLUTION]
- **Core Contradiction**: <Metric X vs Metric Y (e.g. Latency vs Consistency)>
- **Applied TRIZ Operator**: <Time / Space / Asymmetry / Inversion>
- **Breakthrough Synthesis**: <Synthesized model eliminating compromise>

#### [PASS 5: ADVERSARIAL RED-TEAMING & FALSIFICATION PROBING]
- **Concurrency & Memory Races**: <Thread preemption, ABA hazard, lost wakeups>
- **Resource Exhaustion**: <OOM, disk full, connection saturation, Byzantine faults>
- **Falsification Verdict**: <PASS / REVISE>

#### [PASS 6: CONCURRENCY, MEMORY MODEL & FORMAL PROOFS]
- **Memory Ordering Model**: <Explicit Acquire-Release / SeqCst ordering proof>
- **Progress Guarantee**: <Wait-free / Lock-free / Obstruction-free formal proof>

#### [PASS 7: MULTI-CRITERIA VECTOR EVALUATION & EPISTEMIC AUDIT]
- **Domain Criteria Scores**:
  - Invariants / Correctness (35%): `0.98`
  - Performance / Cache Efficiency (25%): `0.96`
  - Blast Radius / Fault Tolerance (25%): `0.95`
  - Ergonomics & Maintainability (15%): `0.92`
- **Epistemic Hygiene Audit**: `Zero unverified hypotheses remaining [✓]`

#### [PASS 8: BLUEPRINT SYNTHESIS & SUBAGENT DELEGATION CONTRACT]
- **Main Agent Verdict**: Architecture locked & invariants proven.
- **Continuous Refinement Trigger**: If $t_{\text{current}} < t_{\text{deadline}}$, launch Continuous Rethink-Refine Cycles (`log_refinement_cycle`).
- **Coder Subagent Mandate (`type: self`)**:
  - Target file paths, interface signatures, and unit tests to create.
  - Definition of Done (DoD) binary acceptance gate.
```

--------------------------------------------------------------------------------

## 5. Subagent Dispatch Specification Scaffold

Inject this template when formulating subagent instructions:

```markdown
### 🚀 SUBAGENT DISPATCH SPECIFICATION
- **Target Subagent Role**: `Coder Implementer` | `Research Scout` | `Adversarial Critic`
- **Session Reference**: `session_name_01`
- **Objective / Task**: Exact description of function/module to create or verify
- **File Boundaries**: Explicit list of files allowed to be created or edited
- **Strict Invariants**: Types, concurrency constraints, error handling rules
- **Verification Command**: Exact CLI command subagent must run (`pytest`, `cargo test`, `npm test`)
- **Required Report Output**: Git diff summary, test pass/fail counts, and invariant proof
```

--------------------------------------------------------------------------------

## 6. The OODA Self-Healing Error Scaffold

Inject this template when encountering unexpected compilation errors, test failures, or runtime crashes:

```markdown
### 🩺 OODA SELF-HEALING LOOP
1. **OBSERVE**: Full error output: `<Exception/Panic/Stderr>`
2. **ORIENT**: Invariant breached: `<Contract/Type/Path that failed>`
3. **DECIDE**: Root cause vs Symptom: `<Why it failed at first principles>`
4. **ACT**: Surgical fix: `<Target file & modification>`
5. **VERIFY**: Deterministic validation command: `<cargo check / pytest / build>`
```

--------------------------------------------------------------------------------

## 7. The Interleaved Reflection Scaffold

Inject this micro-template after executing terminal commands or file edits:

```markdown
### 🔄 POST-ACTION REFLECTION GATE
- **State Delta**: <What actually changed in disk/memory/process state?>
- **Observation vs Expectation**: <Did output match prediction 100%>?
- **Invariant Health**: <Any warning, unexpected exit code, or side effect?>
- **Next Tactical Step**: <Refined next action based on reality>
```


