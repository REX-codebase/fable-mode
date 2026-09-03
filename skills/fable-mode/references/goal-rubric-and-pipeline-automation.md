# Pre-Flight Goal Score Rubric Pointers & Autonomous Tool & Pipeline Synthesis
## Deterministic Goal Attestation ($S_{\text{target}} \ge 95\%$) & Closed-Loop Autonomous Pipeline Architecture

In high-stakes software engineering, systems design, and algorithmic innovation, relying solely on unverified LLM generation is an anti-pattern that leads to subtle regressions, hallucinations, and unverified edge cases. 

`fable-mode` enforces two foundational paradigms:
1. **Pre-Flight Goal Score & Rubric Pointers ($S_{\text{target}} \ge 95\%$)**: Before writing or modifying workspace code, the agent must declare an explicit mathematical evaluation rubric composed of weighted criteria pointers ($p_i$). No objective can be marked complete until verifiable receipts attest that the composite score satisfies $S \ge 0.95$.
2. **Autonomous Tool & Pipeline Synthesis ("Automate What Can Be Automated")**: For any non-trivial generation, transformation, or verification task (e.g. converting an image to an SVG, fuzzing concurrent data structures, property verification, AST refactoring), the agent must construct automated tools, scratch test harnesses, generator-evaluator loops, and perceptual comparators rather than producing ungrounded code in a single prompt.

---

## 1. Architectural Philosophy: "Automate What Can Be Automated"

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                         THE AUTOMATION PARADIGM IN FABLE                                 │
└──────────────────────────────────────────────────────────────────────────────────────────┘

  ❌ ANTI-PATTERN: PURE LLM GENERATION           ✅ FABLE PARADIGM: SYNTHESIZED PIPELINE
  ┌─────────────────────────────────────┐         ┌─────────────────────────────────────┐
  │ Human / Agent Prompt                │         │ Goal Rubric Defined (S_target >= 95)│
  │               │                     │         │               │                     │
  │               ▼                     │         │               ▼                     │
  │ LLM generates monolithic code       │         │ Register Automation Pipeline Spec   │
  │               │                     │         │               │                     │
  │               ▼                     │         │               ▼                     │
  │ Hope code works; no empirical metric│         │ ┌─────────────────────────────────┐ │
  │               │                     │         │ │ 1. Generator Script executes    │ │
  │               ▼                     │         │ │ 2. Evaluator measures metric F  │ │
  │ Output delivered (Silent Failures)  │         │ │ 3. Automated loop until F >= 0.95│ │
  └─────────────────────────────────────┘         │ └─────────────────────────────────┘ │
                                                  │               │                     │
                                                  │               ▼                     │
                                                  │ Evaluated Rubric: S >= 0.95 Attested│
                                                  └─────────────────────────────────────┘
```

### 1.1 The Failure Modes of Raw LLM Generation
When an AI agent generates complex code, vector art, or distributed algorithms in a single forward pass without externalized validation tools:
- **Spatial / Perceptual Blindness**: LLMs cannot see pixel distributions or vector curve control points; emitting raw SVG coordinates without a headless rendering and image-comparison loop results in broken shapes and visual glitches.
- **Concurrency & Race Condition Amnesia**: Statically reasoning about 16-thread lock-free race conditions cannot replace active ThreadSanitizer or stress fuzzing under chaotic OS scheduling.
- **Compounding Hallucinations**: In multi-file refactoring, errors in early function interfaces cascade through downstream modules unless verified by continuous compiler and type-checker feedback loops.

### 1.2 The Closed-Loop Synthesis Mandate
Under Fable Mode, the agent operates as a **System 2 Orchestrator** whose core capability is synthesizing purpose-built automation pipelines:
- **Scratch Tools & Test Harnesses**: Write self-contained Python scripts in `<appDataDir>\brain\<conversation-id>/scratch/` to parse ASTs, execute benchmark probes, or simulate mathematical models.
- **Generator-Evaluator Pairs**: Separate the generator (candidate producer) from the evaluator (impartial verifier), establishing an objective fitness metric $F \in [0.0, 1.0]$.
- **Bounded Autonomous Iteration**: Allow the pipeline to iterate autonomously up to $K_{\max}$ iterations until the target score threshold is met, eliminating manual trial-and-error.

---

## 2. Mathematical Framework: Pre-Flight Goal Scoring Rubrics

A **Goal Scoring Rubric** $R$ is a formal contract registered with the Fable Engine prior to implementation:

$$R = \langle \mathcal{O}, \mathcal{P}, S_{\text{target}}, S_{\text{current}}, \Sigma \rangle$$

Where:
- $\mathcal{O}$: Task objective statement.
- $\mathcal{P} = \{p_1, p_2, \dots, p_n\}$: Set of criteria pointers ($n \ge 1$).
- $S_{\text{target}} \in [0.0, 1.0]$: Strict target goal attainment threshold (default $S_{\text{target}} = 0.95$).
- $S_{\text{current}} \in [0.0, 1.0]$: Current weighted composite score.
- $\Sigma \in \{\text{pending}, \text{in\_progress}, \text{achieved}\}$: Formal rubric state.

### 2.1 Criteria Pointer Specification
Each criterion pointer $p_i \in \mathcal{P}$ is defined by the 7-tuple:

$$p_i = \langle \text{id}_i, d_i, w_i, s_i, v_i, \rho_i, \mu_i \rangle$$

1. $\text{id}_i$: Unique identifier string (e.g. `PTR-01`, `CRIT-PERF`).
2. $d_i$: Unambiguous, testable criterion description.
3. $w_i \in \mathbb{R}^+$: Positive weight signifying relative importance ($w_i > 0$, default $1.0$).
4. $s_i \in [0.0, 1.0]$: Individual normalized satisfaction score ($0.0 = \text{unmet}$, $1.0 = \text{fully satisfied}$).
5. $v_i$: Verification shell command or script (e.g. `pytest tests/test_queue.py -k test_fifo`).
6. $\rho_i$: Cryptographic `ToolReceipt` identifier or command execution attestation ID (e.g. `rcpt_a1b2c3d4`).
7. $\mu_i$: Associated metadata dictionary (e.g. latency targets, memory boundaries, AST symbol offsets).

### 2.2 Composite Goal Score Formula
The composite goal score $S_{\text{current}}$ is the normalized weighted sum across all criteria:

$$S_{\text{current}} = \frac{\sum_{i=1}^n w_i \cdot s_i}{\sum_{i=1}^n w_i}$$

The rubric status $\Sigma$ transitions deterministically:

$$\Sigma = \begin{cases} 
\text{achieved} & \text{if } S_{\text{current}} \ge S_{\text{target}} \\ 
\text{in\_progress} & \text{if } 0 < S_{\text{current}} < S_{\text{target}} \\ 
\text{pending} & \text{if } S_{\text{current}} = 0.0 
\end{cases}$$

### 2.3 Strict Invariant Invalidation & Receipt Binding
- **The $S_{\text{target}} \ge 0.95$ Rule**: Deliverables and pull requests cannot be finalized while $\Sigma \neq \text{achieved}$. The engine strictly enforces $S_{\text{target}} \ge 0.95$.
- **Anti-Tautology Verification**: Scores cannot be marked $s_i = 1.0$ by fiat. The agent must link an evidence receipt $\rho_i$ or verifiable output snippet demonstrating that $v_i$ executed cleanly with exit code 0.

---

## 3. Closed-Loop Autonomous Pipeline Architecture

When confronting complex multi-step generative tasks, the AI synthesizes and registers an **Automation Pipeline Spec**:

```
+─────────────────────────────────────────────────────────────────────────────+
|                         CLOSED-LOOP PIPELINE LIFECYCLE                      |
+─────────────────────────────────────────────────────────────────────────────+
|                                                                             |
|      ┌─────────────────────────┐                                            |
|      │ 1. Parameter / Input    │                                            |
|      └────────────┬────────────┘                                            |
|                   │                                                         |
|                   ▼                                                         |
|      ┌─────────────────────────┐                                            |
|  ┌──>│ 2. Candidate Generator  │  (Executes generator_command: e.g. python  |
|  │   │    (Iteration k)        │   scratch/gen_candidate.py --epoch k)      |
|  │   └────────────┬────────────┘                                            |
|  │                │ Output Artifact A_k                                     |
|  │                ▼                                                         |
|  │   ┌─────────────────────────┐                                            |
|  │   │ 3. Objective Evaluator  │  (Executes evaluator_command: e.g. python  |
|  │   │    (Deterministic)      │   scratch/eval_fidelity.py --artifact A_k) |
|  │   └────────────┬────────────┘                                            |
|  │                │ Score F_k in [0.0, 1.0] + Diagnostics                   |
|  │                ▼                                                         |
|  │         Is F_k >= 0.95?                                                  |
|  │          ├── YES ──► [CONVERGED] ──► Update Goal Rubric (s_i = 1.0)      |
|  │          └── NO                                                          |
|  │               │                                                          |
|  │               ▼                                                         |
|  │         k < Max_Iterations?                                              |
|  │          ├── YES ──► Compute Error Delta & Adjust Hyperparameters ───────┘
|  │          └── NO  ──► [HALTED_CEILING] ──► Surface Diagnostics & Escalation
+─────────────────────────────────────────────────────────────────────────────+
```

### 3.1 Pipeline Specification Schema
A registered pipeline contains:
- `pipeline_id`: Unique identifier (e.g. `pipeline_task_123_1`).
- `name`: Semantic name (e.g. `svg_perceptual_refiner`).
- `pipeline_type`: Classification (`closed_loop`, `fuzzing`, `property_verification`, `codemod`).
- `generator_command`: Shell command or script invocation producing candidate artifacts.
- `evaluator_command`: Objective verification program outputting a scalar score in $[0.0, 1.0]$.
- `target_threshold`: Minimum metric threshold for success (default $0.95$).
- `max_iterations`: Maximum iteration ceiling $K_{\max}$ (default 10) to guard against unbounded runaway loops.
- `status`: Execution state (`active`, `converged`, `failed`).

---

## 4. Real-World Engineering Exemplars

### 4.1 Exemplar 1: High-Fidelity Raster-to-SVG Conversion
**Task**: Reconstruct a raster PNG icon as a crisp, optimized, scalable SVG vector asset.

#### Step 1: Initialize Goal Rubric
```json
{
  "action": "set_goal_rubric",
  "session_name": "svg_vector_synthesis",
  "task_objective": "Generate bit-exact scalable SVG vector from raster asset with SSIM >= 0.96",
  "target_score": 0.95,
  "criteria": [
    {
      "pointer_id": "PTR-SSIM",
      "description": "Perceptual structural similarity (SSIM) >= 0.96 between raster and rendered SVG",
      "weight": 3.0,
      "verifier_command": "python scratch/compare_perceptual_ssim.py assets/logo.png assets/logo.svg"
    },
    {
      "pointer_id": "PTR-CLEAN-SVG",
      "description": "SVG passes XML validation, contains zero raster embeddings, size < 25KB",
      "weight": 1.0,
      "verifier_command": "python scratch/validate_svg_structure.py assets/logo.svg"
    },
    {
      "pointer_id": "PTR-OKLCH-PALETTE",
      "description": "All SVG gradients and color fills conform to OKLCH perceptual standards",
      "weight": 1.0,
      "verifier_command": "python scratch/check_svg_colors.py assets/logo.svg"
    }
  ]
}
```

#### Step 2: Register Autonomous Closed-Loop Pipeline
```json
{
  "action": "register_automation_pipeline",
  "session_name": "svg_vector_synthesis",
  "pipeline_name": "raster_to_svg_loop",
  "pipeline_type": "closed_loop",
  "generator_cmd": "python scratch/synthesize_svg_curves.py --input assets/logo.png --output assets/logo.svg",
  "evaluator_cmd": "python scratch/compare_perceptual_ssim.py assets/logo.png assets/logo.svg",
  "target_score": 0.96,
  "max_iterations": 8
}
```

#### Step 3: Evaluator and Convergence Loop
The evaluator renders the SVG onto a headless bitmap canvas and computes normalized SSIM:
```python
# scratch/compare_perceptual_ssim.py
import sys, json

def evaluate(png_path: str, svg_path: str) -> float:
    # 1. Render svg_path to temp PNG at identical resolution
    # 2. Compute structural similarity index (SSIM) in [0.0, 1.0]
    # 3. Output JSON receipt: {"score": 0.972, "satisfied": true}
    ...
```

#### Step 4: Evaluate Rubric After Convergence
```json
{
  "action": "evaluate_goal_rubric",
  "session_name": "svg_vector_synthesis",
  "evaluations": [
    {"pointer_id": "PTR-SSIM", "score": 0.98, "satisfied": true, "evidence_receipt_id": "rcpt_ssim_982"},
    {"pointer_id": "PTR-CLEAN-SVG", "score": 1.0, "satisfied": true, "evidence_receipt_id": "rcpt_xml_ok"},
    {"pointer_id": "PTR-OKLCH-PALETTE", "score": 1.0, "satisfied": true, "evidence_receipt_id": "rcpt_oklch_ok"}
  ]
}
```
*Result*: Composite score $S = \frac{3(0.98) + 1(1.0) + 1(1.0)}{5} = 0.988 \ge 0.95 \implies \text{Status: ACHIEVED}$.

---

### 4.2 Exemplar 2: Lock-Free Data Structure Concurrency Fuzzing
**Task**: Prove thread safety and zero lost items on a lock-free Single-Producer Multi-Consumer (SPMC) queue.

#### Step 1: Pre-Flight Goal Rubric
```json
{
  "action": "set_goal_rubric",
  "session_name": "lockfree_spmc_queue",
  "task_objective": "Verify lock-free SPMC ring buffer with 0 deadlocks, 0 lost items, throughput >= 20M ops/s",
  "target_score": 0.95,
  "criteria": [
    {
      "pointer_id": "PTR-TSAN",
      "description": "Zero data races under ThreadSanitizer (-fsanitize=thread) across 10M operations",
      "weight": 4.0,
      "verifier_command": "pytest -s tests/test_spmc_tsan.py"
    },
    {
      "pointer_id": "PTR-LINEARIZABILITY",
      "description": "Deterministic linearizability verification (zero dropped, zero duplicate sequence IDs)",
      "weight": 3.0,
      "verifier_command": "python scratch/verify_spmc_linearizability.py"
    },
    {
      "pointer_id": "PTR-THROUGHPUT",
      "description": "Sustained throughput exceeds 20,000,000 operations/sec on 8 cores",
      "weight": 2.0,
      "verifier_command": "python scratch/benchmark_throughput.py"
    }
  ]
}
```

#### Step 2: Register Autonomous Fuzzing Pipeline
```json
{
  "action": "register_automation_pipeline",
  "session_name": "lockfree_spmc_queue",
  "pipeline_name": "spmc_concurrency_fuzzer",
  "pipeline_type": "fuzzing",
  "generator_cmd": "python scratch/gen_chaotic_schedule_harness.py",
  "evaluator_cmd": "python scratch/run_concurrency_evaluator.py",
  "target_score": 0.95,
  "max_iterations": 10
}
```

---

## 5. Fable Engine MCP Protocol Reference

### 5.1 `set_goal_rubric`
Registers a goal rubric contract for the session.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_name` | string | Yes | The target active Fable session. |
| `task_objective` | string | No | High-level objective statement. Falls back to session objective. |
| `criteria` | array / string | Yes | List of criteria dicts, pointer strings, or JSON-encoded criteria. |
| `target_score` | number | No | Target attainment threshold $\in [0.0, 1.0]$. Default: `0.95`. |
| `rubric_id` | string | No | Custom identifier. If omitted, auto-generated (`rubric_<session>_<idx>`). |
| `metadata` | object | No | Custom metadata (e.g. environment, SLA requirements). |

### 5.2 `evaluate_goal_rubric`
Updates criteria scores and recomputes the weighted composite score.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_name` | string | Yes | The target active Fable session. |
| `rubric_id` | string | No | Target rubric identifier. Defaults to the latest active rubric. |
| `evaluations` / `item_evaluations` | array / object / string | Yes | List or map of updates: `[{"pointer_id": "PTR-01", "score": 1.0, "satisfied": true, "evidence_receipt_id": "rcpt_123"}]`. |

### 5.3 `get_goal_rubric`
Inspects the current state, individual pointer scores, and status of a rubric.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_name` | string | Yes | The target active Fable session. |
| `rubric_id` | string | No | Specific rubric identifier. Defaults to the latest active rubric. |

### 5.4 `register_automation_pipeline`
Registers an autonomous generation/evaluation loop specification.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_name` | string | Yes | The target active Fable session. |
| `name` / `pipeline_name` | string | Yes | Identifier for the pipeline specification. |
| `pipeline_type` | string | No | Pipeline taxonomy (`closed_loop`, `fuzzing`, `verification`). Default: `closed_loop`. |
| `generator_cmd` / `generator_command` | string | No | Command that synthesizes the candidate artifact. |
| `evaluator_cmd` / `evaluator_command` | string | No | Command that measures fidelity score and produces diagnostics. |
| `target_score` / `target_threshold` | number | No | Target metric for loop termination. Default: `0.95`. |
| `max_iterations` | integer | No | Bounded iteration limit. Default: `10`. |

---

## 6. Lifecycle Phase Integration

```
Phase 1: Epistemic Grounding ───────────────► set_goal_rubric (S_target >= 0.95)
                                              (Define measurable criteria & verifier commands)

Phase 2: Axiomatic Bounds & Pipelines ──────► register_automation_pipeline
                                              (Register closed-loop generator/evaluator specs)

Phase 3: System 2 Invariants & Proofs ─────► Synthesize scratch tools & harnesses
                                              (Write scripts in brain/<conv-id>/scratch/)

Phase 4: Subagent Fleet Execution ─────────► Dispatch coder subagents
                                              (Run generator/evaluator iteration loops)

Phase 5: Multi-Tier Verification ──────────► evaluate_goal_rubric
                                              (Attest composite score S >= 0.95 with receipts)
```

---

## 7. Operational Best Practices & Anti-Patterns

### ❌ What NOT To Do:
1. **Never declare completion on "vibes"**: Announcing "The code looks complete and correct" without evaluating the goal rubric violates the Fable cognitive protocol.
2. **Never set unweighted monolithic criteria**: Avoid single catch-all criteria like "Make the system work". Decompose into 3–6 granular pointers covering correctness, performance, edge cases, and type safety.
3. **Never omit verifier commands**: Every criterion pointer should have an associated shell command (`v_i`) or test target so any reviewer or subagent can re-verify the claim on demand.
4. **Never run unbounded while-loops in chat**: Do not ask the user to manually run 10 test iterations. Register an automation pipeline with a clean termination threshold and bounded ceiling.

### ✅ What ALWAYS To Do:
1. **Declare rubric before modifying workspace code**: Initialize `set_goal_rubric` in Phase 1 before unlocking code execution.
2. **Automate complex transformations with scratch tools**: Save scripts into `<appDataDir>\brain\<conversation-id>/scratch/` and execute them via `run_command`.
3. **Bind satisfaction to evidence receipts**: Provide `evidence_receipt_id` or test command exit code 0 when updating scores in `evaluate_goal_rubric`.
4. **Demand $S_{\text{target}} \ge 0.95$**: Hold the final deliverables to the strict 95% mathematical standard.
