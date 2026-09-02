#!/usr/bin/env python3
"""
Comprehensive Unit and Integration Test Suite for Fable-Engine MCP Server.
Tests:
- Core session data structures & invariants
- Anti-rush execution lockout logic & cognitive gating validation
- Immutable authority time-lock enforcement & host-only emergency overrides
- Continuous rethink-refine cycle tracking & telemetry
- Epistemic ledger tracking (PROVEN, HYPOTHESIS, UNKNOWN)
- Formal invariant modeling
- Immutable authority deadlines and agent-only pacing telemetry
- Persistence, atomic checkpointing, and restoration
- Dispatch handler operations and edge-case handling
- Full JSON-RPC 2.0 stdio MCP server protocol over subprocess
"""

from __future__ import annotations

import sys
import os
import json
import time
import subprocess
import threading
import unittest
import tempfile
import shutil
from pathlib import Path

class FakeClock:
    """Deterministic wall and monotonic clocks for lock tests."""

    def __init__(self):
        self.wall = time.time()
        self.mono = time.monotonic()

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


# Add current directory to path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from server import (
    FableSession,
    ACTIVE_SESSIONS,
    SESSIONS_DIR,
    PHASES,
    PHASE_INDEX_MAP,
    handle_fable_session,
    TOOL_SCHEMA,
    FableCASError,
    IntegrityError,
    CASNotFoundError,
    ThreadSafeLRUCache,
    FableCASStore,
    CompositeFrame,
    AdaptiveChunkAccumulator,
    FableGrammar333,
    CASSliceViewer,
    FableCompress,
    CAS_ENGINE
)


class TestFableSessionCore(unittest.TestCase):
    """Tests core FableSession lifecycle, telemetry, refinement cycles, and anti-rush gates."""

    def setUp(self):
        self.clock = FakeClock()
        self.session_name = f"test_unit_{int(time.time() * 1000)}"
        self.session = FableSession(
            session_name=self.session_name,
            objective="Architect a lock-free multi-producer ring buffer",
            time_budget_minutes=45.0,
            wall_clock=self.clock.time,
            monotonic_clock=self.clock.monotonic
        )

    def tearDown(self):
        # Cleanup test session files if any
        target_file = SESSIONS_DIR / f"{self.session_name}.json"
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]

    def test_initialization_defaults(self):
        """Verifies session initializes in locked state with proper phase, pacing, and refinement structures."""
        self.assertEqual(self.session.session_name, self.session_name)
        self.assertTrue(self.session.execution_locked)
        self.assertFalse(self.session.can_execute_code)
        self.assertEqual(self.session.active_phase, "Phase 1: Epistemic Grounding & Live Research")
        self.assertEqual(self.session.time_budget_minutes, 45.0)
        self.assertEqual(self.session.time_budget_seconds, 2700.0)
        self.assertEqual(len(self.session.epistemic_ledger), 0)
        self.assertEqual(len(self.session.invariants), 0)
        self.assertEqual(len(self.session.refinement_cycles), 0)
        self.assertEqual(len(self.session.phase_history), 1)

        tel = self.session.get_telemetry()
        self.assertEqual(tel["refinement_count"], 0)
        self.assertEqual(tel["refinement_cycles"], [])

    def test_timer_adjustment_is_pacing_only(self):
        """An agent sub-timer cannot shorten the authority deadline."""
        authority_deadline = self.session.deadline_time
        tel = self.session.set_timer(20.0)
        self.assertEqual(self.session.time_budget_minutes, 45.0)
        self.assertEqual(self.session.time_budget_seconds, 2700.0)
        self.assertEqual(self.session.pacing_budget_minutes, 20.0)
        self.assertEqual(self.session.deadline_time, authority_deadline)
        self.assertLess(self.session.pacing_deadline_time, authority_deadline)
        self.assertIn("authority_remaining_formatted", tel)
        self.assertIn("pacing_remaining_formatted", tel)
        self.assertIn("cognitive_gates", tel)

    def test_epistemic_ledger_logging(self):
        """Verifies logging fact, hypothesis, and unknown items."""
        item1 = self.session.log_epistemic_item("PROVEN", "Ring buffer power of 2 size allows bitwise mask", f"{__file__}:L42")
        self.assertEqual(item1["id"], "epi_001")
        self.assertEqual(item1["tag"], "PROVEN")
        self.assertEqual(item1["evidence"], f"{__file__}:L42")

        item2 = self.session.log_epistemic_item("HYPOTHESIS", "Acquire-Release fences suffice for x86 TSO")
        self.assertEqual(item2["id"], "epi_002")
        self.assertEqual(item2["tag"], "HYPOTHESIS")

        item3 = self.session.log_epistemic_item("UNKNOWN", "Cache line size on target ARM64 architecture")
        self.assertEqual(item3["id"], "epi_003")
        self.assertEqual(item3["tag"], "UNKNOWN")

        # Invalid tag test
        with self.assertRaises(ValueError):
            self.session.log_epistemic_item("INVALID_TAG", "Some statement")

        # Empty claim test
        with self.assertRaises(ValueError):
            self.session.log_epistemic_item("PROVEN", "   ")

        tel = self.session.get_telemetry()
        self.assertEqual(tel["epistemic_counts"]["proven"], 1)
        self.assertEqual(tel["epistemic_counts"]["hypothesis"], 1)
        self.assertEqual(tel["epistemic_counts"]["unknown"], 1)
        self.assertEqual(tel["epistemic_counts"]["total"], 3)

    def test_invariant_recording(self):
        """Verifies formal invariant recording across domains."""
        inv = self.session.record_invariant(
            invariant_name="INV-01: Head-Tail Boundedness",
            formal_statement="0 <= (head - tail) <= BUFFER_CAPACITY at all times",
            proof_or_rationale="Enforced via CAS atomic operations with modulo mask",
            domain="architecture"
        )
        self.assertEqual(inv["id"], "inv_001")
        self.assertEqual(inv["name"], "INV-01: Head-Tail Boundedness")
        self.assertEqual(inv["domain"], "architecture")

        # Empty fields validation
        with self.assertRaises(ValueError):
            self.session.record_invariant("", "statement", "rationale")
        with self.assertRaises(ValueError):
            self.session.record_invariant("name", "", "rationale")

    def test_refinement_cycle_logging(self):
        """Verifies logging structured rethink-refine cycles with probes and artifacts."""
        cycle1 = self.session.log_refinement_cycle(
            refinement_type="archetype_exploration",
            focus_area="Memory Partitioning",
            critique_or_bottleneck="Global CAS on tail causes false sharing on multi-socket NUMA",
            architectural_refinement="Partitioned ring buffer into per-core L1 chunks with batch migration",
            terminal_probe_results="10M ops benchmark: 82ns down to 14ns latency",
            artifact_path="C:/Users/test/artifacts/partitioned_buffer.md"
        )
        self.assertEqual(cycle1["cycle_number"], 1)
        self.assertEqual(cycle1["refinement_type"], "archetype_exploration")
        self.assertEqual(cycle1["focus_area"], "Memory Partitioning")
        self.assertIn("Global CAS", cycle1["critique_or_bottleneck"])
        self.assertIn("Partitioned", cycle1["architectural_refinement"])
        self.assertEqual(cycle1["terminal_probe_results"], "10M ops benchmark: 82ns down to 14ns latency")
        self.assertEqual(cycle1["artifact_path"], "C:/Users/test/artifacts/partitioned_buffer.md")
        self.assertEqual(cycle1["phase"], self.session.active_phase)

        cycle2 = self.session.log_refinement_cycle(
            refinement_type="triz_contradiction_resolution",
            focus_area="Queue Full Backpressure",
            critique_or_bottleneck="Spinning burns CPU while yielding increases p99 latency",
            architectural_refinement="Adaptive exponential backoff with futex sleep fallback"
        )
        self.assertEqual(cycle2["cycle_number"], 2)
        self.assertIsNone(cycle2["terminal_probe_results"])
        self.assertIsNone(cycle2["artifact_path"])

        # Validate required field errors
        with self.assertRaises(ValueError):
            self.session.log_refinement_cycle("", "Focus", "Critique", "Refinement")
        with self.assertRaises(ValueError):
            self.session.log_refinement_cycle("Type", "", "Critique", "Refinement")
        with self.assertRaises(ValueError):
            self.session.log_refinement_cycle("Type", "Focus", "", "Refinement")
        with self.assertRaises(ValueError):
            self.session.log_refinement_cycle("Type", "Focus", "Critique", "")

        tel = self.session.get_telemetry()
        self.assertEqual(tel["refinement_count"], 2)
        self.assertEqual(len(tel["refinement_cycles"]), 2)

    def test_phase_transitions(self):
        """Verifies phase advancement and invalid phase handling."""
        self.session.advance_phase(
            "Phase 2: Invariant Specification & Blueprint",
            "Completed grounding and verified CPU memory model"
        )
        self.assertEqual(self.session.active_phase, "Phase 2: Invariant Specification & Blueprint")
        self.assertEqual(len(self.session.phase_history), 2)

        # Invalid phase test
        with self.assertRaises(ValueError):
            self.session.advance_phase("Phase 99: Non-existent", "Should fail")

    def test_hard_time_lock_enforcement(self):
        """
        Verifies Hard Mechanical Time-Lock:
        1. Fails with PermissionError when the immutable authority deadline is active.
        2. A public hard-coded token cannot bypass the lock.
        3. An explicitly configured out-of-band secret can be used for emergency override.
        4. Succeeds normally when the authority deadline has elapsed.
        """
        # Set up satisfying cognitive gates
        self.session.log_epistemic_item("PROVEN", "Fact 1: Lock-free atomic swap verified", f"{__file__}:L201")
        self.session.log_epistemic_item("PROVEN", "Fact 2: Modulo arithmetic holds", f"{__file__}:L202")
        self.session.record_invariant("INV-01", "tail <= head", "CAS inductive proof")
        for i in range(9):
            self.session.log_refinement_cycle(
                refinement_type="triz_refinement",
                focus_area=f"Contention Area {i}",
                critique_or_bottleneck=f"Bottleneck {i}",
                architectural_refinement=f"Refinement {i}"
            )
        self.session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Advanced to Phase 2")
        self.session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "Advanced to Phase 3")

        # 1. Timer has not elapsed -> must throw Hard Time-Lock Violation
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Premature attempt before timer finishes")
        self.assertIn("🛑 HARD TIME-LOCK VIOLATION", str(ctx.exception))
        self.assertIn("immutable 45.0m authority budget has not elapsed yet", str(ctx.exception))
        self.assertIn("internal pacing timer cannot unlock execution", str(ctx.exception))
        self.assertIn("Rethink-Refine Cognitive Loop", str(ctx.exception))

        # 2. The old public hard-coded token must not bypass the lock.
        with self.assertRaises(PermissionError):
            self.session.unlock_execution(
                "Attempted emergency unlock",
                force_override_token="USER_OVERRIDE_FORCE_UNLOCK"
            )

        # 3. An administrative override works only through the direct host API.
        os.environ["FABLE_FORCE_UNLOCK_TOKEN"] = "test-secret"
        try:
            res = self.session.unlock_execution(
                "Emergency unlock ordered by host administrator",
                force_override_token="test-secret"
            )
        finally:
            os.environ.pop("FABLE_FORCE_UNLOCK_TOKEN", None)
        self.assertEqual(res["status"], "UNLOCKED")
        self.assertTrue(self.session.can_execute_code)
        self.assertTrue(self.session.unlock_details["force_override_used"])

        # 3. Test elapsed deadline_time without override token
        new_session = FableSession(
            session_name=f"test_elapsed_{int(time.time() * 1000)}",
            objective="Test elapsed clock",
            time_budget_minutes=10.0,
            wall_clock=self.clock.time,
            monotonic_clock=self.clock.monotonic
        )
        new_session.log_epistemic_item("PROVEN", "Fact 1: Lock-free atomic swap verified", f"{__file__}:L229")
        new_session.log_epistemic_item("PROVEN", "Fact 2: Modulo arithmetic holds", f"{__file__}:L230")
        new_session.record_invariant("INV-01", "tail <= head", "CAS inductive proof")
        for i in range(2):
            new_session.log_refinement_cycle(
                refinement_type="triz_refinement",
                focus_area=f"Area {i}",
                critique_or_bottleneck=f"Critique {i}",
                architectural_refinement=f"Refinement {i}"
            )
        new_session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Phase 2 ready")
        new_session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "Phase 3 ready")
        
        # Simulate time elapsed past deadline
        self.clock.advance(601.0)
        res = new_session.unlock_execution("Timer has naturally elapsed")
        self.assertEqual(res["status"], "UNLOCKED")
        self.assertTrue(new_session.can_execute_code)
        self.assertFalse(new_session.unlock_details["force_override_used"])

    def test_anti_rush_lockout_enforcement(self):
        """
        Rigorous test of Anti-Rush Cognitive Lockout Gates:
        Requires:
        1. >= 2 PROVEN epistemic items
        2. >= 1 formal invariant
        3. Active phase >= Phase 3
        """
        # Simulate an elapsed authority deadline so this test isolates cognitive gates.
        self.clock.advance(2701.0)

        # Attempt 1: In Phase 1 with 0 proven, 0 invariants -> Must fail cognitive gate
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("Anti-Rush Lockout Active", str(ctx.exception))
        self.assertIn("at least 2 [PROVEN]", str(ctx.exception))

        # Attempt 2: Add 1 PROVEN item -> Must still fail
        self.session.log_epistemic_item("PROVEN", "Fact 1: Single producer queue is wait-free", f"{__file__}:L259")
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("at least 2 [PROVEN]", str(ctx.exception))

        # Attempt 3: Add 2nd PROVEN item, but 0 invariants -> Must still fail
        self.session.log_epistemic_item("PROVEN", "Fact 2: Atomic CAS is supported on target CPU", f"{__file__}:L265")
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("at least 1 formal Invariant", str(ctx.exception))

        # Attempt 4: Add invariant, but active phase is Phase 1 -> Must still fail
        self.session.record_invariant(
            "INV-01",
            "tail <= head",
            "Proof by induction",
            "coding"
        )
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("at least Phase 3", str(ctx.exception))

        # Attempt 5: Advance to Phase 2 -> Must still fail
        self.session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Drafted blueprints")
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("at least Phase 3", str(ctx.exception))

        # Log required refinement cycles (9 required for 45m budget)
        for i in range(9):
            self.session.log_refinement_cycle(
                refinement_type="archetype_exploration",
                focus_area=f"Area {i}",
                critique_or_bottleneck=f"Critique {i}",
                architectural_refinement=f"Refinement {i}"
            )

        # Attempt 6: Advance to Phase 3 -> Satisfies ALL gates! Must succeed!
        self.session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "Passed red team fuzzing")
        res = self.session.unlock_execution(
            "All invariants proved and red-team checks passed."
        )

        self.assertEqual(res["status"], "UNLOCKED")
        self.assertFalse(self.session.execution_locked)
        self.assertTrue(self.session.can_execute_code)
        self.assertIsNotNone(self.session.unlock_details)
        self.assertEqual(self.session.unlock_details["proven_count"], 2)
        self.assertEqual(self.session.unlock_details["invariants_count"], 1)

    def test_pacing_expiry_cannot_unlock(self):
        """A completed internal timer never satisfies the authority lock."""
        self.session.set_timer(2.0)
        self.clock.advance(1.0)
        self.session.log_epistemic_item("PROVEN", "Fact 1: Verified property", f"{__file__}:L1")
        self.session.log_epistemic_item("PROVEN", "Fact 2: Validated cache line", f"{__file__}:L2")
        self.session.record_invariant("INV-01", "tail <= head", "CAS monotonic counter guarantee")
        self.session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Phase 2")
        self.session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "Phase 3")
        with self.assertRaises(PermissionError):
            self.session.unlock_execution("Pacing timer expired")

    def test_proven_claims_require_evidence(self):
        """A truth label without an evidence pointer is not an admissible gate input."""
        with self.assertRaises(ValueError):
            self.session.log_epistemic_item("PROVEN", "An unreferenced assertion")

        item = self.session.log_epistemic_item(
            "PROVEN", "A referenced assertion", f"{__file__}:L1"
        )
        self.assertEqual(item["tag"], "PROVEN")

    def test_invalid_budget_and_session_name_are_rejected(self):
        with self.assertRaises(ValueError):
            FableSession("invalid/escape", "test", 10)
        with self.assertRaises(ValueError):
            FableSession("bad_budget", "test", float("nan"))
        with self.assertRaises(ValueError):
            self.session.set_timer(-1)

    def test_serialization_and_atomic_save(self):
        """Verifies session dictionary serialization, deserialization, and disk saving including refinement cycles."""
        self.session.log_epistemic_item("PROVEN", "Proven item 1", f"{__file__}:L303")
        self.session.record_invariant("INV-01", "Statement", "Rationale")
        self.session.log_refinement_cycle(
            refinement_type="archetype_exploration",
            focus_area="Cache coherency",
            critique_or_bottleneck="False sharing",
            architectural_refinement="Padding to 64 bytes"
        )
        saved_path = self.session.save()
        self.assertTrue(saved_path.exists())

        with open(saved_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        restored = FableSession.from_dict(data)
        self.assertEqual(restored.session_name, self.session.session_name)
        self.assertEqual(len(restored.epistemic_ledger), 1)
        self.assertEqual(len(restored.invariants), 1)
        self.assertEqual(len(restored.refinement_cycles), 1)
        self.assertEqual(restored.refinement_cycles[0]["focus_area"], "Cache coherency")


class TestFableHandlerDispatch(unittest.TestCase):
    """Tests high-level handle_fable_session tool dispatcher."""

    def setUp(self):
        self.session_name = f"test_dispatch_{int(time.time() * 1000)}"

    def tearDown(self):
        target_file = SESSIONS_DIR / f"{self.session_name}.json"
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]

    def test_refinement_cycle_dispatch(self):
        """Verifies dispatching log_refinement_cycle and aliases."""
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Design lock-free queue",
            "time_budget_minutes": 30
        })

        # Call log_refinement_cycle
        res = handle_fable_session({
            "action": "log_refinement_cycle",
            "session_name": self.session_name,
            "refinement_type": "archetype_exploration",
            "focus_area": "Atomic memory ordering",
            "critique_or_bottleneck": "SeqCst is unnecessarily heavy on ARM64",
            "architectural_refinement": "Relaxed loads with Acquire-Release fences",
            "terminal_probe_results": "Benchmark: 4.2x speedup on aarch64",
            "artifact_path": "C:/docs/arch_refine.md"
        })
        self.assertIn("Rethink-Refine Cycle #1 Logged", res)
        self.assertIn("ARCHETYPE_EXPLORATION", res)
        self.assertIn("Atomic memory ordering", res)
        self.assertIn("Terminal Probes / Benchmarks", res)
        self.assertIn("Artifact Blueprint", res)
        self.assertIn("Total Refinement Cycles", res)

        # Call alias refine
        res_alias = handle_fable_session({
            "action": "refine",
            "session_name": self.session_name,
            "refinement_type": "adversarial_falsification",
            "focus_area": "ABA Problem",
            "critique_or_bottleneck": "Pointer recycling can fool standard CAS",
            "architectural_refinement": "Tagged pointer with generation counter"
        })
        self.assertIn("Rethink-Refine Cycle #2 Logged", res_alias)
        self.assertIn("ADVERSARIAL_FALSIFICATION", res_alias)

        # Missing required parameter tests
        res_err = handle_fable_session({
            "action": "log_refinement_cycle",
            "session_name": self.session_name,
            "refinement_type": "test",
            "focus_area": "test",
            "critique_or_bottleneck": ""
        })
        self.assertIn("Error: 'critique_or_bottleneck' is required", res_err)

    def test_full_workflow_via_handler(self):
        """Executes full lifecycle through the dispatcher tool interface."""
        # 1. Create session
        res = handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Build zero-copy parser",
            "time_budget_minutes": 2.0
        })
        self.assertIn("Fable Cognitive Session Initialized", res)
        self.assertIn("Anti-Rush Lockout is ACTIVE", res)

        # 2. Get status / telemetry
        res = handle_fable_session({
            "action": "get_status",
            "session_name": self.session_name
        })
        self.assertIn("Fable Session Status & Telemetry", res)
        self.assertIn("LOCKED", res)

        # 3. Log epistemic items
        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "Zero-copy slices borrow from underlying buffer without allocation",
            "evidence": f"{__file__}:L10"
        })
        self.assertIn("Epistemic Item Logged", res)
        self.assertIn("[PROVEN]", res)

        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "Lifetime bounds prevent use-after-free",
            "evidence": "cargo test stdout: rustc verification passed"
        })
        self.assertIn("2 PROVEN", res)

        # 4. Record invariant
        res = handle_fable_session({
            "action": "record_invariant",
            "session_name": self.session_name,
            "invariant_name": "INV-LIFETIME",
            "formal_statement": "SliceLifetime <= BufferLifetime",
            "proof_or_rationale": "Static borrow checker guarantee",
            "domain": "design"
        })
        self.assertIn("Formal Invariant Recorded", res)
        self.assertIn("INV-LIFETIME", res)

        # 5. Log refinement cycles (2 required for 2.0m budget)
        res = handle_fable_session({
            "action": "log_refinement_cycle",
            "session_name": self.session_name,
            "refinement_type": "benchmark_probe",
            "focus_area": "SIMD tokenization",
            "critique_or_bottleneck": "Scalar byte scanning is memory-bound",
            "architectural_refinement": "AVX-512 vectorized delimiter detection",
            "terminal_probe_results": "Throughput increased from 1.2 GB/s to 9.8 GB/s"
        })
        self.assertIn("Rethink-Refine Cycle #1 Logged", res)

        res2 = handle_fable_session({
            "action": "log_refinement_cycle",
            "session_name": self.session_name,
            "refinement_type": "adversarial_falsification",
            "focus_area": "Boundary conditions",
            "critique_or_bottleneck": "Unchecked pointer arithmetic on overflow",
            "architectural_refinement": "Saturating arithmetic bounds with compile-time assertions"
        })
        self.assertIn("Rethink-Refine Cycle #2 Logged", res2)

        # 6. Try premature unlock (Phase 1) -> Must fail Hard Time-Lock (or cognitive gate)
        res = handle_fable_session({
            "action": "unlock_execution",
            "session_name": self.session_name,
            "rationale": "Premature attempt"
        })
        self.assertIn("HARD TIME-LOCK VIOLATION", res)

        # 7. Advance to Phase 2 then Phase 3
        handle_fable_session({
            "action": "advance_phase",
            "session_name": self.session_name,
            "next_phase": "Phase 2: Invariant Specification & Blueprint",
            "phase_summary": "Blueprints created"
        })
        handle_fable_session({
            "action": "advance_phase",
            "session_name": self.session_name,
            "next_phase": "Phase 3: Adversarial Red-Teaming & Falsification",
            "phase_summary": "Passed red-teaming checks"
        })

        # 8. Attempt unlock without elapsed time -> Still hits Hard Time-Lock
        res = handle_fable_session({
            "action": "unlock_execution",
            "session_name": self.session_name,
            "rationale": "Cognitive gates satisfied but timer active"
        })
        self.assertIn("HARD TIME-LOCK VIOLATION", res)

        # 9. Simulate elapsed monotonic time for testing unlock
        session = ACTIVE_SESSIONS[self.session_name]
        session._authority_deadline_monotonic = time.monotonic() - 1.0
        session._authority_deadline_wall = time.time() - 1.0

        res = handle_fable_session({
            "action": "unlock_execution",
            "session_name": self.session_name,
            "rationale": "Cognitive gates satisfied with 2 proven facts, 1 invariant, and 2 refinement cycles"
        })
        self.assertIn("Execution Lock Lifted Successfully", res)
        self.assertIn("🟢 UNLOCKED", res)

        # 10. Adjust internal pacing timer without changing authority budget.
        res = handle_fable_session({
            "action": "set_timer",
            "session_name": self.session_name,
            "time_budget_minutes": 60
        })
        self.assertIn("Pacing Timer", res)
        self.assertIn("Authority Budget", res)
        self.assertIn("2.0", res)

        # 11. Checkpoint and restore
        res = handle_fable_session({
            "action": "checkpoint_session",
            "session_name": self.session_name
        })
        self.assertIn("Fable Session Checkpointed", res)
        self.assertIn("Refinement Cycles", res)

        res = handle_fable_session({
            "action": "restore_session",
            "session_name": self.session_name
        })
        self.assertIn("Fable Session Restored", res)
        self.assertIn("Refinement Cycles", res)

        # 12. List sessions
        res = handle_fable_session({
            "action": "list_sessions"
        })
        self.assertIn(self.session_name, res)

    def test_edge_cases_and_error_handling(self):
        """Tests dispatcher error handling on invalid inputs."""
        # Missing action
        res = handle_fable_session({})
        self.assertIn("Error: Missing required parameter 'action'", res)

        # Unknown action
        res = handle_fable_session({"action": "fly_to_moon"})
        self.assertIn("Error: Unknown action 'fly_to_moon'", res)

        # Missing session_name
        res = handle_fable_session({"action": "get_status"})
        self.assertIn("Error: 'session_name' is required", res)

        # Non-existent session
        res = handle_fable_session({"action": "get_status", "session_name": "ghost_session_xyz"})
        self.assertIn("does not exist", res)


class TestFableMCPStdioServer(unittest.TestCase):
    """End-to-end integration test of the JSON-RPC 2.0 stdio server process."""

    def setUp(self):
        self.python_exe = sys.executable
        self.server_script = str(CURRENT_DIR / "server.py")
        self.proc = subprocess.Popen(
            [self.python_exe, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8"
        )
        # Drain diagnostics continuously: a long-running interactive server
        # must not block on a full stderr pipe while the test reads stdout.
        self._stderr_lines = []
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self.req_id = 0

    def _drain_stderr(self):
        if self.proc.stderr is None:
            return
        try:
            for line in self.proc.stderr:
                if len(self._stderr_lines) < 256:
                    self._stderr_lines.append(line)
        except (OSError, ValueError):
            pass

    def tearDown(self):
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        if self.proc.stdout:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
        if self.proc.stderr:
            try:
                self.proc.stderr.close()
            except Exception:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _rpc_call(self, method: str, params: dict = None) -> dict:
        self.req_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": method
        }
        if params is not None:
            req["params"] = params

        raw_req = json.dumps(req) + "\n"
        self.proc.stdin.write(raw_req)
        self.proc.stdin.flush()

        line = self.proc.stdout.readline()
        self.assertTrue(line, "Server returned empty output")
        return json.loads(line)

    def test_mcp_handshake_and_tool_call(self):
        """Verifies initialize, tools/list, and tools/call over stdio JSON-RPC."""
        # 1. Initialize
        resp = self._rpc_call("initialize")
        self.assertEqual(resp.get("jsonrpc"), "2.0")
        self.assertEqual(resp.get("id"), 1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "fable-engine")

        # 2. Tools List
        resp = self._rpc_call("tools/list")
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "fable_session")
        self.assertIn("log_refinement_cycle", tools[0]["inputSchema"]["properties"]["action"]["enum"])

        # 3. Call fable_session: create_session
        session_name = f"mcp_stdio_test_{int(time.time() * 1000)}"
        resp = self._rpc_call("tools/call", {
            "name": "fable_session",
            "arguments": {
                "action": "create_session",
                "session_name": session_name,
                "objective": "Verify MCP stdio protocol loop",
                "time_budget_minutes": 15
            }
        })
        self.assertFalse(resp["result"].get("isError", True))
        content = resp["result"]["content"][0]["text"]
        self.assertIn("Fable Cognitive Session Initialized", content)

        # 4. Call fable_session: log_refinement_cycle
        resp = self._rpc_call("tools/call", {
            "name": "fable_session",
            "arguments": {
                "action": "log_refinement_cycle",
                "session_name": session_name,
                "refinement_type": "benchmark_probe",
                "focus_area": "Zero-copy buffering",
                "critique_or_bottleneck": "Memory allocation inside hot loop",
                "architectural_refinement": "Preallocated memory arena slab allocator",
                "terminal_probe_results": "0 allocs/op achieved"
            }
        })
        self.assertFalse(resp["result"].get("isError", True))
        content = resp["result"]["content"][0]["text"]
        self.assertIn("Rethink-Refine Cycle #1 Logged", content)

        # 5. Call fable_session: compress_payload & view_slice over stdio
        resp = self._rpc_call("tools/call", {
            "name": "fable_session",
            "arguments": {
                "action": "compress_payload",
                "content": "Line 1: Sample MCP payload\nLine 2: Another line\nLine 3: Third line\n",
                "label": "stdio_test_payload"
            }
        })
        self.assertFalse(resp["result"].get("isError", True))
        content = resp["result"]["content"][0]["text"]
        self.assertIn("Fable CAS Payload Compressed", content)

        # 6. Ping
        resp = self._rpc_call("ping")
        self.assertEqual(resp.get("result"), {})

        # Clean up session file
        sfile = SESSIONS_DIR / f"{session_name}.json"
        if sfile.exists():
            try:
                sfile.unlink()
            except Exception:
                pass


class TestFableTokenCompression(unittest.TestCase):
    """Direct subsystem tests for FableCASStore, AdaptiveChunkAccumulator, FableGrammar333, CASSliceViewer, and FableCompress."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="fable_test_cas_"))
        self.compressor = FableCompress(root_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cas_store_atomic_put_get(self):
        """Verify atomic writes, SHA-256 addresses, and byte-exact retrieval."""
        store = self.compressor.cas_store
        sample = "Fable-Mode Token Compression Subsystem verification payload."
        uri = store.put(sample)
        self.assertTrue(uri.startswith("cas://"))
        self.assertEqual(len(store.normalize_ref(uri)), 64)
        self.assertEqual(store.get_text(uri), sample)
        self.assertEqual(store.get_bytes(uri), sample.encode("utf-8"))
        self.assertTrue(store.verify_integrity(uri))

    def test_cas_corruption_detection(self):
        """Verify integrity verification catches file tampering on disk."""
        store = self.compressor.cas_store
        sample = "Pristine data payload"
        uri = store.put(sample)
        file_path = store.get_file_path(uri)
        store.cache.clear()

        with open(file_path, "r+b") as f:
            f.seek(0)
            f.write(b"Z")

        with self.assertRaises(IntegrityError):
            store.get_bytes(uri, verify=True)
        self.assertFalse(store.verify_integrity(uri))

    def test_lru_cache_bounds_and_eviction(self):
        """Verify LRU cache capacity limits and disk fallback."""
        small_store = FableCASStore(root_dir=self.test_dir / "lru", cache_capacity=2)
        u1 = small_store.put("entry_1")
        u2 = small_store.put("entry_2")
        u3 = small_store.put("entry_3")

        self.assertEqual(len(small_store.cache), 2)
        self.assertEqual(small_store.get_text(u1), "entry_1")

    def test_adaptive_chunk_accumulator_coalescing(self):
        """Verify sub-1000 character micro-payload batching into composite frames."""
        acc = self.compressor.accumulator
        payloads = [f"Log trace entry #{i:03d} for subagent execution step." for i in range(30)]

        flushed_uris = []
        for p in payloads:
            flushed_uris.extend(acc.add(p, metadata={"step": "trace"}))
        flushed_uris.extend(acc.flush())

        self.assertGreater(len(flushed_uris), 0)
        extracted = []
        for uri in flushed_uris:
            frame_json = self.compressor.cas_store.get_text(uri)
            frame = CompositeFrame.deserialize_json(frame_json)
            for idx in range(len(frame.items)):
                item_text, meta = acc.extract_item(uri, idx)
                extracted.append(item_text)
                self.assertEqual(meta.get("step"), "trace")

        self.assertEqual(extracted, payloads)

    def test_grammar333_micro_bytecode_roundtrip(self):
        """Verify bit-exact roundtrip serialization of tool actions."""
        payload = {
            "action_type": "view_file",
            "path": "C:/Projects/module.py",
            "start_line": 10,
            "end_line": 50,
            "content_ref": "cas://abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
        }
        encoded = FableGrammar333.serialize(payload)
        self.assertTrue(encoded.startswith(FableGrammar333.MAGIC_HEADER))
        decoded = FableGrammar333.deserialize(encoded)
        self.assertEqual(decoded, payload)

    def test_cas_slice_viewer_zero_copy(self):
        """Verify windowed line slice extractor with 1-based indexing."""
        lines = [f"Line {i:03d}: Content description here" for i in range(1, 60)]
        doc = "\n".join(lines)
        uri = self.compressor.cas_store.put(doc)

        viewer = self.compressor.slice_viewer
        self.assertEqual(viewer.get_line_count(uri), 58)

        slice_text = viewer.view_slice(uri, 5, 10)
        self.assertEqual(slice_text, "\n".join(lines[4:10]))

        numbered = viewer.view_slice(uri, 1, 2, include_line_numbers=True)
        self.assertIn("     1 | Line 001:", numbered)

    def test_invariant_token_ratio_lte_0_003(self):
        """Verify <= 0.003 tokens/character invariant on large payloads."""
        sizes = [10_000, 50_000, 100_000]
        for size in sizes:
            raw_text = ("function process_data(chunk: Buffer) -> Result {\n    return validate(chunk);\n}\n" * (size // 60 + 1))[:size]
            node = self.compressor.compress_payload_to_cas(raw_text, label="trace_dump")
            repr_str = json.dumps(node, separators=(",", ":"))
            ratio = self.compressor.calculate_token_ratio(raw_text, repr_str)
            self.assertLessEqual(ratio, 0.003, f"Failed invariant for size {size}: ratio {ratio}")
            recovered = self.compressor.decompress_cas_payload(node)
            self.assertEqual(recovered, raw_text)


class TestFableCompressionHandlerDispatch(unittest.TestCase):
    """Tests dispatcher tool actions for Token Compression Subsystem."""

    def test_compress_and_decompress_payload_dispatch(self):
        """Verifies compress_payload and decompress_payload actions."""
        payload = "Structured benchmark probe report for concurrent ring buffer:\n" + ("line output data\n" * 1000)
        res = handle_fable_session({
            "action": "compress_payload",
            "content": payload,
            "label": "benchmark_probe"
        })
        self.assertIn("Fable CAS Payload Compressed", res)
        self.assertIn("cas://", res)
        self.assertIn("PASS (<= 0.003 tokens/char)", res)

        import re
        match = re.search(r"cas://[0-9a-fA-F]{64}", res)
        self.assertIsNotNone(match)
        cas_uri = match.group(0)

        res_decomp = handle_fable_session({
            "action": "decompress_payload",
            "cas_ref": cas_uri
        })
        self.assertIn("Fable CAS Payload Retrieved", res_decomp)
        self.assertIn("Structured benchmark probe report", res_decomp)

    def test_view_slice_dispatch(self):
        """Verifies view_slice action."""
        doc = "\n".join([f"Trace item #{i:02d}" for i in range(1, 30)])
        res_comp = handle_fable_session({
            "action": "compress_payload",
            "content": doc
        })
        import re
        match = re.search(r"cas://[0-9a-fA-F]{64}", res_comp)
        cas_uri = match.group(0)

        res_slice = handle_fable_session({
            "action": "view_slice",
            "cas_ref": cas_uri,
            "start_line": 5,
            "end_line": 8
        })
        self.assertIn("Fable CAS Slice View", res_slice)
        self.assertIn("Trace item #05", res_slice)
        self.assertIn("Trace item #08", res_slice)

    def test_accumulate_and_flush_dispatch(self):
        """Verifies accumulate_payload and flush_accumulator actions."""
        res1 = handle_fable_session({
            "action": "accumulate_payload",
            "payload": "Micro-log entry 1",
            "metadata": {"task": "test"}
        })
        self.assertIn("Micro-Payload Ingested", res1)

        res_flush = handle_fable_session({
            "action": "flush_accumulator"
        })
        self.assertIn("Micro-Payload Accumulator", res_flush)

    def test_compression_stats_dispatch(self):
        """Verifies get_compression_stats action."""
        res = handle_fable_session({
            "action": "get_compression_stats"
        })
        self.assertIn("Fable Token Compression Subsystem Telemetry", res)
        self.assertIn("Token Compression Invariant", res)


class TestFableSystem3ActionsDispatch(unittest.TestCase):
    """Verifies all System 3 MCP actions and session persistence via dispatcher."""

    def setUp(self):
        self.session_name = f"test_sys3_{int(time.time() * 1000)}"
        init_res = handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test System 3 Meta-Cognitive Deliberation",
            "time_budget_minutes": 30.0,
        })
        self.assertIn("Fable Cognitive Session Initialized", init_res)

    def tearDown(self):
        target_file = SESSIONS_DIR / f"{self.session_name}.json"
        if target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]

    def test_system3_dialectical_synthesis_dispatch(self):
        """Verifies system3_dialectical_synthesis action and TRIZ transcendence."""
        res = handle_fable_session({
            "action": "system3_dialectical_synthesis",
            "session_name": self.session_name,
            "thesis_title": "Lock-Free Ring Buffer",
            "thesis_description": "Single-writer CAS ring buffer with bounded queue",
            "antithesis_title": "Contention Bottleneck at Multi-Producer",
            "contradictions": [
                {
                    "improving_parameter": "throughput",
                    "worsening_parameter": "latency",
                    "description": "Multi-producer atomic contention degrades P99 latency",
                    "severity": 0.85
                }
            ],
            "failure_modes": ["Cache line bouncing under 16 concurrent producers"],
            "max_debate_rounds": 3,
        })
        self.assertIn("System 3 Dialectical Synthesis Emerged", res)
        self.assertIn("Transcended TRIZ Inventive Principles", res)
        self.assertIn("Resolved Contradictions", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_syntheses), 1)
        self.assertTrue(len(session.refinement_cycles) > 0)

    def test_system3_causal_simulate_dispatch(self):
        """Verifies system3_causal_simulate action with Pearl do-calculus and brittleness analysis."""
        nodes = [
            {"node_id": "threads", "name": "Worker Threads", "node_type": "exogenous", "value": 4.0},
            {"node_id": "contention", "name": "Lock Contention", "node_type": "endogenous", "value": 0.0},
            {"node_id": "throughput", "name": "Operations/sec", "node_type": "metric", "value": 0.0}
        ]
        edges = [
            {"source": "threads", "target": "contention", "weight": 0.5},
            {"source": "threads", "target": "throughput", "weight": 2.0},
            {"source": "contention", "target": "throughput", "weight": -1.2}
        ]
        interventions = {"contention": 0.1}

        res = handle_fable_session({
            "action": "system3_causal_simulate",
            "session_name": self.session_name,
            "model_name": "ThreadContentionDAG",
            "nodes": nodes,
            "edges": edges,
            "interventions": interventions,
            "target_metric": "throughput"
        })
        self.assertIn("System 3 Pearl's Do-Calculus & Causal Simulation", res)
        self.assertIn("Pearl's Do-Operator Intervention", res)
        self.assertIn("Structural Brittleness Report", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_causal_graphs), 1)

    def test_system3_evolve_paradigms_dispatch(self):
        """Verifies system3_evolve_paradigms action with 10D Pareto frontier selection."""
        res = handle_fable_session({
            "action": "system3_evolve_paradigms",
            "session_name": self.session_name,
            "generations": 2,
            "population_size": 8,
            "mutation_rate": 0.20,
        })
        self.assertIn("System 3 Evolutionary Paradigm Engine", res)
        self.assertIn("Top Rank 1 Non-Dominated Pareto Frontier", res)
        self.assertIn("Winning Gene Allocation", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_gene_pools), 1)

    def test_system3_induce_axioms_dispatch(self):
        """Verifies system3_induce_axioms action and auto-recording into invariants."""
        res = handle_fable_session({
            "action": "system3_induce_axioms",
            "session_name": self.session_name,
            "domain": "architecture"
        })
        self.assertIn("System 3 Neuro-Symbolic Invariant Induction", res)
        self.assertIn("Axioms Induced", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertTrue(len(session.system3_axioms) > 0)
        self.assertTrue(len(session.invariants) > 0)

    def test_system3_meta_reflect_dispatch(self):
        """Verifies system3_meta_reflect action with bias detection and heuristic rewriting."""
        res = handle_fable_session({
            "action": "system3_meta_reflect",
            "session_name": self.session_name,
            "focus_area": "Architecture Deliberation Trace"
        })
        self.assertIn("System 3 Meta-Cognitive Deliberation Audit", res)
        self.assertIn("Recommended Cognitive Gear", res)
        self.assertIn("Cognitive Bias Diagnostics", res)
        self.assertIn("Dynamic Search Heuristics", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_reflections), 1)

    def test_system3_tri_level_orchestrate_dispatch(self):
        """Verifies system3_tri_level_orchestrate action."""
        res = handle_fable_session({
            "action": "system3_tri_level_orchestrate",
            "session_name": self.session_name,
            "task_complexity": 0.95,
            "contradiction_density": 0.85,
            "failure_count": 2,
            "epistemic_uncertainty": 0.60
        })
        self.assertIn("System 3 Tri-Level Cognitive Arbitration", res)
        self.assertIn("SYSTEM_3_META_COGNITIVE", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_orchestrations), 1)

    def test_system3_hyperbolic_embed_dispatch(self):
        """Verifies system3_hyperbolic_embed action with Poincaré tree embedding."""
        tree = {
            "root": ["agent", "runtime"],
            "agent": ["planner", "memory"],
            "runtime": ["broker", "verifier"],
        }
        res = handle_fable_session({
            "action": "system3_hyperbolic_embed",
            "session_name": self.session_name,
            "tree": tree,
            "root_id": "root",
            "dimension": 2,
            "curvature": 1.0,
            "base_step": 1.0,
        })
        self.assertIn("System 3 Poincaré Hyperbolic Manifold Embedding", res)
        self.assertIn("Poincaré Ball", res)
        self.assertIn("Mean Metric Distortion", res)
        self.assertIn("Hyperbolic Volume Expansion Ratio", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_hyperbolic_embeddings), 1)
        self.assertTrue(len(session.refinement_cycles) > 0)

    def test_system3_kripke_verify_dispatch(self):
        """Verifies system3_kripke_verify action with CTL* temporal verification."""
        worlds = [
            {"world_id": "w0", "propositions": ["safe", "init"], "is_initial": True},
            {"world_id": "w1", "propositions": ["safe", "running"]},
            {"world_id": "w2", "propositions": ["safe", "complete"]},
        ]
        transitions = [
            {"source": "w0", "target": "w1"},
            {"source": "w1", "target": "w2"},
            {"source": "w2", "target": "w2"},
        ]
        res = handle_fable_session({
            "action": "system3_kripke_verify",
            "session_name": self.session_name,
            "model_name": "ExecutionWorkflowModel",
            "worlds": worlds,
            "transitions": transitions,
            "formula": "AG(safe)",
            "initial_world": "w0",
        })
        self.assertIn("System 3 Kripke Modal Model Verification", res)
        self.assertIn("SATISFIED", res)
        self.assertIn("AG(safe)", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_kripke_verifications), 1)

    def test_system3_active_inference_dispatch(self):
        """Verifies system3_active_inference action with Variational Free Energy minimization."""
        res = handle_fable_session({
            "action": "system3_active_inference",
            "session_name": self.session_name,
            "observation": "HIGH_THROUGHPUT_CLEAN",
            "gamma": 16.0,
        })
        self.assertIn("System 3 Friston Active Inference & Variational Free Energy", res)
        self.assertIn("Variational Free Energy (F)", res)
        self.assertIn("Selected Policy", res)
        self.assertIn("Evaluated Policy Landscape", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_active_inferences), 1)

    def test_system3_proof_oracle_dispatch(self):
        """Verifies system3_proof_oracle action with Curry-Howard constructive verification."""
        res = handle_fable_session({
            "action": "system3_proof_oracle",
            "session_name": self.session_name,
            "claim": "safe == safe",
        })
        self.assertIn("System 3 Gödelian Auto-Formalizing Proof Oracle", res)
        self.assertIn("DECIDABLE_PROVED", res)
        self.assertIn("Soundness Verified", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.system3_proof_oracle_verifications), 1)
        self.assertTrue(len(session.invariants) > 0)

    def test_system3_session_roundtrip_persistence(self):
        """Verifies full roundtrip serialization & disk saving of all System 3 state fields."""
        # Execute synthesis, causal, hyperbolic, kripke, free energy, and oracle
        handle_fable_session({
            "action": "system3_dialectical_synthesis",
            "session_name": self.session_name,
            "thesis_title": "Thesis A",
            "thesis_description": "Desc A",
            "antithesis_title": "Critique B",
        })
        handle_fable_session({
            "action": "system3_causal_simulate",
            "session_name": self.session_name,
            "nodes": [{"node_id": "X", "value": 1.0}],
            "edges": []
        })
        handle_fable_session({
            "action": "system3_hyperbolic_embed",
            "session_name": self.session_name,
            "tree": {"root": ["a", "b"]},
        })
        handle_fable_session({
            "action": "system3_kripke_verify",
            "session_name": self.session_name,
            "worlds": [{"world_id": "w0", "propositions": ["p"]}],
            "transitions": [{"source": "w0", "target": "w0"}],
            "formula": "p",
        })
        handle_fable_session({
            "action": "system3_active_inference",
            "session_name": self.session_name,
            "observation": "HIGH_THROUGHPUT_CLEAN",
        })
        handle_fable_session({
            "action": "system3_proof_oracle",
            "session_name": self.session_name,
            "claim": "safe == safe",
        })

        session = ACTIVE_SESSIONS[self.session_name]
        d = session.to_dict()
        self.assertEqual(len(d["system3_syntheses"]), 1)
        self.assertEqual(len(d["system3_causal_graphs"]), 1)
        self.assertEqual(len(d["system3_hyperbolic_embeddings"]), 1)
        self.assertEqual(len(d["system3_kripke_verifications"]), 1)
        self.assertEqual(len(d["system3_active_inferences"]), 1)
        self.assertEqual(len(d["system3_proof_oracle_verifications"]), 1)

        # Restore from dict
        restored = FableSession.from_dict(d)
        self.assertEqual(len(restored.system3_syntheses), 1)
        self.assertEqual(len(restored.system3_causal_graphs), 1)
        self.assertEqual(len(restored.system3_hyperbolic_embeddings), 1)
        self.assertEqual(len(restored.system3_kripke_verifications), 1)
        self.assertEqual(len(restored.system3_active_inferences), 1)
        self.assertEqual(len(restored.system3_proof_oracle_verifications), 1)
        self.assertEqual(restored.session_name, self.session_name)


class TestSecondRedTeamRegressions(unittest.TestCase):
    def test_cached_cas_data_is_verified(self):
        root = Path(tempfile.mkdtemp(prefix="fable_cas_regression_"))
        try:
            store = FableCASStore(root_dir=root)
            uri = store.put(b"good")
            digest = store.normalize_ref(uri)
            store.cache.put(digest, b"bad")
            with self.assertRaises(IntegrityError):
                store.get_bytes(uri, verify=True)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_restore_ignores_forged_deadline_phase_and_evidence_authority(self):
        now = time.time()
        payload = {"session_name": "forged_regression", "objective": "x",
                   "time_budget_minutes": 2.0, "start_time": now - 10000,
                   "authority_deadline_time": now + 10**9,
                   "active_phase": PHASES[-1], "execution_locked": False,
                   "can_execute_code": True,
                   "epistemic_ledger": [{"tag": "PROVEN", "evidence": "forged"},
                                        {"tag": "PROVEN", "evidence": "forged"}],
                   "invariants": [{"proof_or_rationale": "forged"}],
                   "phase_history": [{"phase": PHASES[-1]}]}
        restored = FableSession.from_dict(payload)
        self.assertTrue(restored.execution_locked)
        self.assertFalse(restored.can_execute_code)
        self.assertEqual(restored.active_phase, PHASES[0])
        self.assertLessEqual(restored.deadline_time, now + 130)
        self.assertFalse(restored.get_telemetry()["cognitive_gates"]["ready"])

    def test_malformed_rpc_shapes_return_invalid_request(self):
        root = Path(tempfile.mkdtemp(prefix="fable_rpc_regression_"))
        try:
            env = os.environ.copy(); env["FABLE_DATA_DIR"] = str(root / "data")
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "server.py")],
                                        input='[1, 2]\n{"jsonrpc":"2.0","id":4,"method":"ping","params":[]}\n',
                                        capture_output=True, text=True, env=env, timeout=5)
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            first, second = responses
            self.assertEqual(first["error"]["code"], -32600)
            self.assertEqual(second["error"]["code"], -32600)
        finally:
            if 'proc' in locals() and proc.poll() is None: proc.kill()
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
