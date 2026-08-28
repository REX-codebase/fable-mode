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

import sys
import os
import json
import time
import subprocess
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
    TOOL_SCHEMA
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
        item1 = self.session.log_epistemic_item("PROVEN", "Ring buffer power of 2 size allows bitwise mask", "lib.rs:42")
        self.assertEqual(item1["id"], "epi_001")
        self.assertEqual(item1["tag"], "PROVEN")
        self.assertEqual(item1["evidence"], "lib.rs:42")

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
        self.session.log_epistemic_item("PROVEN", "Fact 1: Lock-free atomic swap verified", "test_server.py:201")
        self.session.log_epistemic_item("PROVEN", "Fact 2: Modulo arithmetic holds", "test_server.py:202")
        self.session.record_invariant("INV-01", "tail <= head", "CAS inductive proof")
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
        new_session.log_epistemic_item("PROVEN", "Fact 1: Lock-free atomic swap verified", "test_server.py:229")
        new_session.log_epistemic_item("PROVEN", "Fact 2: Modulo arithmetic holds", "test_server.py:230")
        new_session.record_invariant("INV-01", "tail <= head", "CAS inductive proof")
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
        self.session.log_epistemic_item("PROVEN", "Fact 1: Single producer queue is wait-free", "test_server.py:259")
        with self.assertRaises(PermissionError) as ctx:
            self.session.unlock_execution("Let me code")
        self.assertIn("at least 2 [PROVEN]", str(ctx.exception))

        # Attempt 3: Add 2nd PROVEN item, but 0 invariants -> Must still fail
        self.session.log_epistemic_item("PROVEN", "Fact 2: Atomic CAS is supported on target CPU", "test_server.py:265")
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
        self.session.set_timer(0.1)
        self.clock.advance(1.0)
        self.session.log_epistemic_item("PROVEN", "Fact 1", "test_server.py:1")
        self.session.log_epistemic_item("PROVEN", "Fact 2", "test_server.py:2")
        self.session.record_invariant("INV-01", "x == x", "Reflexivity")
        self.session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Phase 2")
        self.session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "Phase 3")
        with self.assertRaises(PermissionError):
            self.session.unlock_execution("Pacing timer expired")

    def test_proven_claims_require_evidence(self):
        """A truth label without an evidence pointer is not an admissible gate input."""
        with self.assertRaises(ValueError):
            self.session.log_epistemic_item("PROVEN", "An unreferenced assertion")

        item = self.session.log_epistemic_item(
            "PROVEN", "A referenced assertion", "tests/test_server.py:1"
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
        self.session.log_epistemic_item("PROVEN", "Proven item 1", "test_server.py:303")
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
            "time_budget_minutes": 0.1
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
            "evidence": "specs.md#L10"
        })
        self.assertIn("Epistemic Item Logged", res)
        self.assertIn("[PROVEN]", res)

        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "Lifetime bounds prevent use-after-free",
            "evidence": "rustc verification"
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

        # 5. Log refinement cycle
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

        # 8. Attempt unlock without override token -> Still hits Hard Time-Lock
        res = handle_fable_session({
            "action": "unlock_execution",
            "session_name": self.session_name,
            "rationale": "Cognitive gates satisfied but timer active"
        })
        self.assertIn("HARD TIME-LOCK VIOLATION", res)

        # 9. The immutable authority deadline, not the internal pacing timer, unlocks.
        time.sleep(6.3)
        res = handle_fable_session({
            "action": "unlock_execution",
            "session_name": self.session_name,
            "rationale": "Cognitive gates satisfied with 2 proven facts, 1 invariant, and 1 refinement cycle"
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
        self.assertIn("0.1", res)

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
        self.req_id = 0

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

        # 5. Ping
        resp = self._rpc_call("ping")
        self.assertEqual(resp.get("result"), {})

        # Clean up session file
        sfile = SESSIONS_DIR / f"{session_name}.json"
        if sfile.exists():
            try:
                sfile.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)


