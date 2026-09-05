---
name: concurrency
description: Lock-free synchronization, atomic memory ordering, and race hardening
domain: concurrency
activation_count: 17
synaptic_weights:
  concurrency_fuzz: 0.96
  atomic_cas_loop: 0.94
  memory_ordering: 0.92
  hazard_pointers: 0.88
  toctou_prevention: 0.95
  test_harness: 0.9
antibodies:
- antibody_id: ab_concurrency_toctou_file_race
  domain: concurrency
  trigger_condition: Checking file or resource existence before performing operations
    in non-isolated threads
  lethal_anti_pattern: 'if os.path.exists(path): open(path, ''w'') # Attacker modifies
    path between check and open'
  prescribed_defense: Use atomic file creation flags (e.g. os.O_CREAT | os.O_EXCL)
    or file descriptor locks (fcntl/flock).
  severity: CRITICAL
  source_task_id: task_toctou_hardening
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Adversarial race probe with 16 threads verified zero TOCTOU
    corruption
- antibody_id: ab_concurrency_double_checked_locking_reorder
  domain: concurrency
  trigger_condition: Implementing double-checked locking singleton without acquire/release
    memory fences
  lethal_anti_pattern: 'if instance == null: synchronized(lock): if instance == null:
    instance = new Object()'
  prescribed_defense: Ensure instance pointer is declared volatile/atomic with acquire-release
    barriers to prevent publishing half-initialized objects.
  severity: CRITICAL
  source_task_id: task_dcl_memory_barrier_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: ThreadSanitizer (TSan) verified zero data races under 100,000
    parallel reads
- antibody_id: ab_concurrency_condition_variable_spurious_wakeup
  domain: concurrency
  trigger_condition: Evaluating condition variable wait predicate using an if statement
    instead of a while loop
  lethal_anti_pattern: 'if (!queue.has_items()) cv.wait(lock); # Spurious wakeup causes
    queue.pop() on empty queue'
  prescribed_defense: 'Always enclose cv.wait within a while loop: while (!queue.has_items())
    cv.wait(lock);'
  severity: HIGH
  source_task_id: task_spurious_wakeup_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Chaos stress test injected 1,000 spurious wakeups with
    zero out-of-order execution
specialized_heuristics:
- 'Atomic CAS Loops: Always use compare_exchange_weak in retry loops to handle spurious
  LL/SC failures on ARM architectures, falling back to compare_exchange_strong only
  for single attempts.'
- 'Memory Ordering Discipline: Use Acquire on loads paired with Release on stores
  for synchronized handoffs; never default blindly to SeqCst when Acquire-Release
  suffices.'
- 'ABA Hazard Prevention: Prevent recycled pointer hazards in lock-free stacks using
  tagged atomic pointers (pointer + 64-bit generation counter) or hazard pointer epochs.'
- 'TOCTOU Eradication: In concurrent state checks and transitions, the validation
  and state mutation must occur within a single atomic primitive or critical section.'
- 'Hierarchical Lock Ordering: Prevent distributed deadlocks by establishing a strict
  total order (L1 < L2 < L3) across all mutex acquisitions.'
last_consolidated_at: '2026-09-04T12:00:00+00:00'
---

# Cortical Lobe: `concurrency`

> [!NOTE]
> Lock-free synchronization, atomic memory ordering, and race hardening
> Activation count: 17.

## Metadata & Telemetry
- **Name**: `concurrency`
- **Description**: Lock-free synchronization, atomic memory ordering, and race hardening
- **Domain**: `concurrency`
- **Activation Count**: `17`
- **Total Antibodies**: `3`
- **Specialized Heuristics**: `5`
- **Last Consolidated**: `2026-09-04T12:00:00+00:00`

## Specialized Domain Heuristics
1. Atomic CAS Loops: Always use compare_exchange_weak in retry loops to handle spurious LL/SC failures on ARM architectures, falling back to compare_exchange_strong only for single attempts.
2. Memory Ordering Discipline: Use Acquire on loads paired with Release on stores for synchronized handoffs; never default blindly to SeqCst when Acquire-Release suffices.
3. ABA Hazard Prevention: Prevent recycled pointer hazards in lock-free stacks using tagged atomic pointers (pointer + 64-bit generation counter) or hazard pointer epochs.
4. TOCTOU Eradication: In concurrent state checks and transitions, the validation and state mutation must occur within a single atomic primitive or critical section.
5. Hierarchical Lock Ordering: Prevent distributed deadlocks by establishing a strict total order (L1 < L2 < L3) across all mutex acquisitions.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `concurrency_fuzz` | `0.9600` | 🟢 Strong |
| `toctou_prevention` | `0.9500` | 🟢 Strong |
| `atomic_cas_loop` | `0.9400` | 🟢 Strong |
| `memory_ordering` | `0.9200` | 🟢 Strong |
| `test_harness` | `0.9000` | 🟢 Strong |
| `hazard_pointers` | `0.8800` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_concurrency_toctou_file_race` [CRITICAL]
- **Domain**: `concurrency`
- **Trigger Condition**: Checking file or resource existence before performing operations in non-isolated threads
- **Lethal Anti-Pattern**: if os.path.exists(path): open(path, 'w') # Attacker modifies path between check and open
- **Prescribed Defense**: Use atomic file creation flags (e.g. os.O_CREAT | os.O_EXCL) or file descriptor locks (fcntl/flock).
- **Verified Counterfactual**: `Adversarial race probe with 16 threads verified zero TOCTOU corruption`
- **Source Task ID**: `task_toctou_hardening`

#### Antibody `ab_concurrency_double_checked_locking_reorder` [CRITICAL]
- **Domain**: `concurrency`
- **Trigger Condition**: Implementing double-checked locking singleton without acquire/release memory fences
- **Lethal Anti-Pattern**: if instance == null: synchronized(lock): if instance == null: instance = new Object()
- **Prescribed Defense**: Ensure instance pointer is declared volatile/atomic with acquire-release barriers to prevent publishing half-initialized objects.
- **Verified Counterfactual**: `ThreadSanitizer (TSan) verified zero data races under 100,000 parallel reads`
- **Source Task ID**: `task_dcl_memory_barrier_audit`

#### Antibody `ab_concurrency_condition_variable_spurious_wakeup` [HIGH]
- **Domain**: `concurrency`
- **Trigger Condition**: Evaluating condition variable wait predicate using an if statement instead of a while loop
- **Lethal Anti-Pattern**: if (!queue.has_items()) cv.wait(lock); # Spurious wakeup causes queue.pop() on empty queue
- **Prescribed Defense**: Always enclose cv.wait within a while loop: while (!queue.has_items()) cv.wait(lock);
- **Verified Counterfactual**: `Chaos stress test injected 1,000 spurious wakeups with zero out-of-order execution`
- **Source Task ID**: `task_spurious_wakeup_audit`

