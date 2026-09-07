# System 3 Meta-Cognitive Deliberation Architecture (Experimental)

## 1. Executive Summary & Overview

Fable Mode includes an experimental **System 3 Meta-Cognitive Deliberation Engine** (`fable_v2/system3/`), designed as a research extension to dual-process agent architectures (System 1 intuitive heuristics and System 2 deliberative search).

System 3 operates above the solution generation loop. It provides tools for modeling structural causal dependencies (Pearl's do-calculus), embedding architectural tree structures into Poincaré hyperbolic space, checking modal properties across state transition models (Kripke structures), evaluating policy uncertainty via Active Inference (Variational Free Energy), checking constructive proofs (Curry-Howard isomorphism), resolving parameter trade-offs via TRIZ principles, and searching architectural trade-off spaces.

> **Note on status:** System 3 capabilities in `fable_v2/system3/` are experimental research modules. They provide specialized mathematical and logical tools accessible through the `fable_session` MCP interface or direct Python APIs.

---

## 2. Tri-Level Cognitive Hierarchy

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│                   SYSTEM 3: META-COGNITIVE & LOGICAL REASONING                 │
│  - Pearl Do-Calculus Causal Models (DAG, Interventions, Brittleness Analysis) │
│  - Poincaré Hyperbolic Manifold Embeddings (Exact Metric, Möbius Gyrovectors) │
│  - Kripke Modal Model Checker (CTL Temporal Logic: AG, EF, AF, AX, EU, AU)     │
│  - Friston Active Inference (Variational F = Complexity - Accuracy, EFE G)   │
│  - Gödelian Proof Oracle & Curry-Howard Constructive Type Verification        │
│  - Dialectical Triad & 40 TRIZ Inventive Contradiction Resolution             │
│  - Evolutionary Paradigm Engine (10D Pareto Frontier NSGA-II Optimization)    │
│  - Neuro-Symbolic Invariant Induction (Empirical Falsification)               │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │ (Gear Arbitration)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM 2: DELIBERATIVE REASONING                       │
│  - Structured Deliberation Chains & Time-Locked Execution                     │
│  - Adversarial Red-Teaming & Falsification Probes                             │
│  - Formal Invariant Modeling & Domain Specification                           │
│  - Continuous Rethink-Refine Loop                                             │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │ (Execution Delegation)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                       SYSTEM 1: INTUITIVE & PROCEDURAL EXECUTION               │
│  - Fast Pattern Matching & Code Generation via Subagent Fleet                  │
│  - Deterministic Machine Verification & Tool Receipts                          │
│  - Local Error Recovery & Repair Loops                                         │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Cognitive Gear Arbitration

The `TriLevelArbitrator` evaluates task complexity, contradiction metrics, failure counts, and epistemic uncertainty to suggest operating gears:

1. **`SYSTEM_1_INTUITIVE`**: Selected for low-complexity, procedural, non-conflicting tasks.
2. **`SYSTEM_2_DELIBERATIVE`**: Selected for medium-complexity tasks requiring deep decomposition, formal invariants, and red-team review.
3. **`SYSTEM_3_META_COGNITIVE`**: Engaged when high contradiction density or repeated test failures occur, engaging causal simulation, hyperbolic embeddings, modal checking, or proof oracles.

---

## 3. Hyperbolic Geometry (`fable_v2.system3.hyperbolic`)

Tree hierarchies and software dependency graphs can suffer distortion when embedded into Euclidean spaces. System 3 provides Poincaré Ball embeddings ($\mathbb{B}^n_c = \{x \in \mathbb{R}^n : c \|x\|^2 < 1\}$) to represent deep hierarchical tree structures with bounded distance metric distortion.

---

## 4. Kripke Modal Model Checker (`fable_v2.system3.kripke`)

System 3 implements verification of state machines and concurrent transitions using **Kripke Structures** $M = \langle W, R, L, W_0 \rangle$ and **Computation Tree Logic (CTL)**:

- **Safety Invariants ($AG \phi$):** Checks if property $\phi$ holds across all reachable states. Generates counterexample trace paths when violated.
- **Reachability ($EF \phi$):** Verifies if a desired state $\phi$ is reachable from initial states. Generates witness paths upon success.

---

## 5. Active Inference & Free Energy (`fable_v2.system3.free_energy`)

Implements Karl Friston's **Free Energy Principle** to model agent perception and action selection under uncertainty:

- **Variational Free Energy ($F$):** Evaluates complexity vs. accuracy metrics over hidden architectural states.
- **Expected Free Energy ($G$):** Balances pragmatic cost (goal divergence) and epistemic value (information gain) for policy selection.

---

## 6. Curry-Howard Proof Oracle (`fable_v2.system3.oracle`)

Bridges logical assertions and type checking via the **Curry-Howard Isomorphism** (Propositions-as-Types):

- **Type Checker:** Evaluates bidirectional type checking ($\Gamma \vdash t : T$) for constructive propositions.
- **Undecidability Detector:** Identifies circular references, cyclical negations, and self-referential paradoxes, returning classifications (`DECIDABLE_PROVED`, `DECIDABLE_REFUTED`, `INDEPENDENT_UNDECIDABLE`, `COMPLEXITY_EXCEEDED`).

---

## 7. Causal Simulation & Pearl's Do-Calculus (`fable_v2.system3.causal`)

- **Graph Interventions (`do(X = x)`):** Simulates structural causal graph modifications and measures counterfactual deltas.
- **Sensitivity Analysis:** Identifies single points of failure (SPOFs) and fragile nodes in dependency graphs.

---

## 8. Dialectical Synthesis & TRIZ Matrix (`fable_v2.system3.dialectical`)

- Maps parameter trade-offs (e.g., speed vs. safety) to TRIZ inventive principles (Segmentation, Extraction, Local Quality, Prior Action, Inversion).
- `DialecticalSynthesizer` runs bounded debate iterations to resolve contradictions.

---

## 9. Evolutionary Paradigm Engine (`fable_v2.system3.evolution`)

Optimizes candidate architectures across up to 10 quality dimensions (Latency, Throughput, Memory, Fault Tolerance, Modularity, Simplicity, Testability, Security, Determinism, Token Efficiency) using non-dominated sorting.

---

## 10. MCP Tool Integration (`fable_session`)

System 3 capabilities are exposed through `fable_session` MCP actions:

| Action | Description | Parameters |
|---|---|---|
| `system3_hyperbolic_embed` | Poincaré ball tree embedding | `tree`, `root_id`, `dimension`, `curvature` |
| `system3_kripke_verify` | Kripke model checking with CTL formulas | `worlds`, `transitions`, `formula`, `initial_world` |
| `system3_active_inference` | Variational Free Energy $F$ & EFE $G$ | `observation`, `policies`, `gamma`, `states` |
| `system3_proof_oracle` | Curry-Howard proof verification | `claim`, `context`, `axioms` |
| `system3_dialectical_synthesis` | Dialectical debate & TRIZ resolution | `thesis_title`, `antithesis_title`, `contradictions` |
| `system3_causal_simulate` | Causal DAG intervention & sensitivity | `nodes`, `edges`, `interventions`, `target_metric` |
| `system3_evolve_paradigms` | Pareto frontier genetic optimization | `generations`, `population_size`, `mutation_rate` |
| `system3_tri_level_orchestrate` | Cognitive gear arbitration | `task_complexity`, `contradiction_density`, `failure_count` |
