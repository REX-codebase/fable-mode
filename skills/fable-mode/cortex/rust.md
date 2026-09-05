---
name: rust
description: Systems invariants, borrow checker mechanics, and zero-cost abstractions
domain: rust
activation_count: 16
synaptic_weights:
  tokio: 0.92
  pin_project: 0.88
  concurrency_fuzz: 0.85
  unsafe_audit: 0.79
  borrow_checker: 0.95
  zero_cost_abstractions: 0.9
antibodies:
- antibody_id: ab_rust_mutex_await_deadlock
  domain: rust
  trigger_condition: Holding std::sync::MutexGuard across an .await suspension point
    in asynchronous Tokio tasks
  lethal_anti_pattern: let guard = std_mutex.lock().unwrap(); some_async_fn().await;
    drop(guard);
  prescribed_defense: Use tokio::sync::Mutex if the lock must span across await points,
    or strictly scope std::sync::MutexGuard within a synchronous block before the
    await point.
  severity: CRITICAL
  source_task_id: task_rust_concurrency_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: tokio-deadlock-detector verified zero thread starvation
    under 100 concurrent async tasks
- antibody_id: ab_rust_unsound_raw_pointer_aliasing
  domain: rust
  trigger_condition: Creating mutable references &mut T from raw pointers *mut T while
    existing references to the same memory are alive
  lethal_anti_pattern: let ref1 = unsafe { &mut *raw_ptr }; let ref2 = unsafe { &mut
    *raw_ptr };
  prescribed_defense: Strictly utilize std::ptr::NonNull with provenance invariants
    and verify with cargo miri run under stacked borrows.
  severity: CRITICAL
  source_task_id: task_rust_unsafe_validation
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Miri test harness executed with zero stacked borrow violations
- antibody_id: ab_rust_unbounded_channel_oom
  domain: rust
  trigger_condition: Using tokio::sync::mpsc::unbounded_channel in high-throughput
    ingestion pipelines
  lethal_anti_pattern: let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
  prescribed_defense: Always use bounded channels with backpressure tokio::sync::mpsc::channel(capacity)
    and handle permit acquisition.
  severity: HIGH
  source_task_id: task_rust_stream_backpressure
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Memory profile confirmed steady-state RSS under 64MB at
    1M events/sec
specialized_heuristics:
- 'Zero-Cost Abstractions: Iterator chains and monomorphized generics compile to equivalent
  or superior assembly compared to manual C-style loops; avoid unnecessary heap allocations.'
- 'Borrow Checker Invariants: Enforce strict single-writer or multiple-reader ownership
  across module boundaries without using RefCell or Arc<Mutex<T>> as an architectural
  crutch.'
- 'Pin & Unpin Projections: In async state machines and self-referential futures,
  pin-projection must never expose structural &mut T without unsafe pin-projection
  macros or pin_project.'
- 'Tokio Thread Boundaries: All tasks spawned on tokio runtime must satisfy Send +
  ''static; never hold std::sync::MutexGuard across an await point.'
- 'Unsafe Preconditions: Any unsafe block must be accompanied by a formal // SAFETY:
  invariant comment justifying pointer validity, alignment, provenance, and non-aliasing.'
last_consolidated_at: '2026-09-04T12:00:00+00:00'
---

# Cortical Lobe: `rust`

> [!NOTE]
> Systems invariants, borrow checker mechanics, and zero-cost abstractions
> Activation count: 16.

## Metadata & Telemetry
- **Name**: `rust`
- **Description**: Systems invariants, borrow checker mechanics, and zero-cost abstractions
- **Domain**: `rust`
- **Activation Count**: `16`
- **Total Antibodies**: `3`
- **Specialized Heuristics**: `5`
- **Last Consolidated**: `2026-09-04T12:00:00+00:00`

## Specialized Domain Heuristics
1. Zero-Cost Abstractions: Iterator chains and monomorphized generics compile to equivalent or superior assembly compared to manual C-style loops; avoid unnecessary heap allocations.
2. Borrow Checker Invariants: Enforce strict single-writer or multiple-reader ownership across module boundaries without using RefCell or Arc<Mutex<T>> as an architectural crutch.
3. Pin & Unpin Projections: In async state machines and self-referential futures, pin-projection must never expose structural &mut T without unsafe pin-projection macros or pin_project.
4. Tokio Thread Boundaries: All tasks spawned on tokio runtime must satisfy Send + 'static; never hold std::sync::MutexGuard across an await point.
5. Unsafe Preconditions: Any unsafe block must be accompanied by a formal // SAFETY: invariant comment justifying pointer validity, alignment, provenance, and non-aliasing.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `borrow_checker` | `0.9500` | 🟢 Strong |
| `tokio` | `0.9200` | 🟢 Strong |
| `zero_cost_abstractions` | `0.9000` | 🟢 Strong |
| `pin_project` | `0.8800` | 🟢 Strong |
| `concurrency_fuzz` | `0.8500` | 🟢 Strong |
| `unsafe_audit` | `0.7900` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_rust_mutex_await_deadlock` [CRITICAL]
- **Domain**: `rust`
- **Trigger Condition**: Holding std::sync::MutexGuard across an .await suspension point in asynchronous Tokio tasks
- **Lethal Anti-Pattern**: let guard = std_mutex.lock().unwrap(); some_async_fn().await; drop(guard);
- **Prescribed Defense**: Use tokio::sync::Mutex if the lock must span across await points, or strictly scope std::sync::MutexGuard within a synchronous block before the await point.
- **Verified Counterfactual**: `tokio-deadlock-detector verified zero thread starvation under 100 concurrent async tasks`
- **Source Task ID**: `task_rust_concurrency_audit`

#### Antibody `ab_rust_unsound_raw_pointer_aliasing` [CRITICAL]
- **Domain**: `rust`
- **Trigger Condition**: Creating mutable references &mut T from raw pointers *mut T while existing references to the same memory are alive
- **Lethal Anti-Pattern**: let ref1 = unsafe { &mut *raw_ptr }; let ref2 = unsafe { &mut *raw_ptr };
- **Prescribed Defense**: Strictly utilize std::ptr::NonNull with provenance invariants and verify with cargo miri run under stacked borrows.
- **Verified Counterfactual**: `Miri test harness executed with zero stacked borrow violations`
- **Source Task ID**: `task_rust_unsafe_validation`

#### Antibody `ab_rust_unbounded_channel_oom` [HIGH]
- **Domain**: `rust`
- **Trigger Condition**: Using tokio::sync::mpsc::unbounded_channel in high-throughput ingestion pipelines
- **Lethal Anti-Pattern**: let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
- **Prescribed Defense**: Always use bounded channels with backpressure tokio::sync::mpsc::channel(capacity) and handle permit acquisition.
- **Verified Counterfactual**: `Memory profile confirmed steady-state RSS under 64MB at 1M events/sec`
- **Source Task ID**: `task_rust_stream_backpressure`

