---
domain: python
activation_count: 12
synaptic_weights:
  asyncio_event_loop: 0.94
  typing_protocols: 0.91
  cpython_313_nogil: 0.86
  slot_optimizations: 0.89
  test_harness: 0.92
  diagnostics: 0.88
antibodies:
- antibody_id: ab_python_mutable_default_arg
  domain: python
  trigger_condition: Using mutable objects (list, dict, set) as default parameter
    values in function signatures
  lethal_anti_pattern: 'def append_item(val, accumulator=[]): accumulator.append(val);
    return accumulator'
  prescribed_defense: Always specify default as None and initialize accumulator =
    [] inside function body if None.
  severity: HIGH
  source_task_id: task_python_static_lint
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: AST codemod verified zero shared instance mutations across
    1,000 function invocations
- antibody_id: ab_python_async_shield_cancellation_leak
  domain: python
  trigger_condition: Assuming asyncio.shield prevents the outer task cancellation
    from reaching the shielded task without awaiting it
  lethal_anti_pattern: 'res = await asyncio.shield(critical_task); # If outer task
    is cancelled, critical_task keeps running in background untracked'
  prescribed_defense: Wrap shielded tasks in TaskGroup or explicitly attach done_callbacks
    to log and clean up orphaned background tasks.
  severity: CRITICAL
  source_task_id: task_python_async_hardening
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Fuzz harness confirmed zero orphaned background tasks upon
    forced cancellation
- antibody_id: ab_python_bare_except_cancellation_swallow
  domain: python
  trigger_condition: Catching BaseException or broad Exception without re-raising
    asyncio.CancelledError
  lethal_anti_pattern: 'try: await operation() except Exception: pass'
  prescribed_defense: Explicitly catch asyncio.CancelledError first and re-raise,
    or only catch specific operational exceptions.
  severity: CRITICAL
  source_task_id: task_python_exception_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Asyncio test harness verified proper propagation of cancellation
    signals
specialized_heuristics:
- 'High-Performance CPython: Utilize __slots__ in performance-critical data structures
  to eliminate __dict__ heap overhead and enable flat memory layout.'
- 'Asyncio Event Loop Invariants: Always use asyncio.TaskGroup (Python 3.11+) or explicit
  exception groups; never fire unawaited coroutines into the ether.'
- 'Free-Threaded CPython 3.13: In nogil builds, shared mutable state requires thread-safe
  collections or threading.Lock; do not rely on bytecode GIL atomicity.'
- 'Structural Typing Protocols: Prefer typing.Protocol and @runtime_checkable over
  rigid class inheritance trees to decouple subsystems.'
- 'Zero-Copy Data Handling: Utilize memoryview and struct.unpack_from for binary wire
  formats rather than byte slicing string allocations.'
last_consolidated_at: '2026-09-04T12:00:00+00:00'
---

# Cortical Lobe: `python`

> [!NOTE]
> Living cortical memory lobe for specialized domain reasoning. Activation count: 12.

## Metadata & Telemetry
- **Domain**: `python`
- **Activation Count**: `12`
- **Total Antibodies**: `3`
- **Specialized Heuristics**: `5`
- **Last Consolidated**: `2026-09-04T12:00:00+00:00`

## Specialized Domain Heuristics
1. High-Performance CPython: Utilize __slots__ in performance-critical data structures to eliminate __dict__ heap overhead and enable flat memory layout.
2. Asyncio Event Loop Invariants: Always use asyncio.TaskGroup (Python 3.11+) or explicit exception groups; never fire unawaited coroutines into the ether.
3. Free-Threaded CPython 3.13: In nogil builds, shared mutable state requires thread-safe collections or threading.Lock; do not rely on bytecode GIL atomicity.
4. Structural Typing Protocols: Prefer typing.Protocol and @runtime_checkable over rigid class inheritance trees to decouple subsystems.
5. Zero-Copy Data Handling: Utilize memoryview and struct.unpack_from for binary wire formats rather than byte slicing string allocations.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `asyncio_event_loop` | `0.9400` | 🟢 Strong |
| `test_harness` | `0.9200` | 🟢 Strong |
| `typing_protocols` | `0.9100` | 🟢 Strong |
| `slot_optimizations` | `0.8900` | 🟢 Strong |
| `diagnostics` | `0.8800` | 🟢 Strong |
| `cpython_313_nogil` | `0.8600` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_python_mutable_default_arg` [HIGH]
- **Domain**: `python`
- **Trigger Condition**: Using mutable objects (list, dict, set) as default parameter values in function signatures
- **Lethal Anti-Pattern**: def append_item(val, accumulator=[]): accumulator.append(val); return accumulator
- **Prescribed Defense**: Always specify default as None and initialize accumulator = [] inside function body if None.
- **Verified Counterfactual**: `AST codemod verified zero shared instance mutations across 1,000 function invocations`
- **Source Task ID**: `task_python_static_lint`

#### Antibody `ab_python_async_shield_cancellation_leak` [CRITICAL]
- **Domain**: `python`
- **Trigger Condition**: Assuming asyncio.shield prevents the outer task cancellation from reaching the shielded task without awaiting it
- **Lethal Anti-Pattern**: res = await asyncio.shield(critical_task); # If outer task is cancelled, critical_task keeps running in background untracked
- **Prescribed Defense**: Wrap shielded tasks in TaskGroup or explicitly attach done_callbacks to log and clean up orphaned background tasks.
- **Verified Counterfactual**: `Fuzz harness confirmed zero orphaned background tasks upon forced cancellation`
- **Source Task ID**: `task_python_async_hardening`

#### Antibody `ab_python_bare_except_cancellation_swallow` [CRITICAL]
- **Domain**: `python`
- **Trigger Condition**: Catching BaseException or broad Exception without re-raising asyncio.CancelledError
- **Lethal Anti-Pattern**: try: await operation() except Exception: pass
- **Prescribed Defense**: Explicitly catch asyncio.CancelledError first and re-raise, or only catch specific operational exceptions.
- **Verified Counterfactual**: `Asyncio test harness verified proper propagation of cancellation signals`
- **Source Task ID**: `task_python_exception_audit`

