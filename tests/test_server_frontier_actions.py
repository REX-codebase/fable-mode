import unittest
import json
import time
import tempfile
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import (
    handle_fable_session,
    ACTIVE_SESSIONS,
    SESSIONS_DIR,
    FableSession,
    MIN_TIME_BUDGET_MINUTES,
    GLOBAL_VELOCITY_PROFILER,
    ModelVelocityProfiler,
)
from fable_v2.proof_engine import DeterministicProofValidator, ProofType


class TestServerFrontierActions(unittest.TestCase):
    def setUp(self):
        self.session_name = f"test_frontier_{int(time.time() * 1000)}"

    def tearDown(self):
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]
        session_file = SESSIONS_DIR / f"{self.session_name}.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except Exception:
                pass

    def test_min_time_budget_enforcement(self):
        # 1. Reject time budget < 2.0
        res = handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test budget rejection",
            "time_budget_minutes": 1.5
        })
        self.assertIn("Error:", res)
        self.assertIn("minimum allowed time budget is 2.0 minutes", res)

        # 2. Accept valid time budget >= 2.0
        res_ok = handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test valid budget",
            "time_budget_minutes": 5.0
        })
        self.assertIn("Fable Cognitive Session Initialized", res_ok)

        # 3. Reject set_timer < 2.0
        res_timer_fail = handle_fable_session({
            "action": "set_timer",
            "session_name": self.session_name,
            "time_budget_minutes": 0.5
        })
        self.assertIn("Error:", res_timer_fail)
        self.assertIn("minimum allowed time budget is 2.0 minutes", res_timer_fail)

    def test_model_velocity_profiler(self):
        profiler = ModelVelocityProfiler(window_size=10)
        # Record rapid high-throughput requests
        t0 = time.time()
        for i in range(5):
            profiler.record_request("test_action", "x" * 2000, timestamp=t0 + i * 0.1)

        prof = profiler.get_velocity_profile()
        self.assertEqual(prof["model_tier"], "flash")
        self.assertEqual(prof["tier_multiplier"], 2.5)
        self.assertGreater(prof["tokens_per_sec"], 80.0)

    def test_track_file_change_action(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test file tracking",
            "time_budget_minutes": 10.0
        })

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as tf:
            tf.write("print('hello')\n")
            tf_path = tf.name

        try:
            res = handle_fable_session({
                "action": "track_file_change",
                "session_name": self.session_name,
                "file_path": tf_path,
                "change_type": "modified",
                "diff_summary": "Added hello print statement",
                "rationale": "Bootstrap entrypoint",
                "affected_invariants": ["INV-01"]
            })
            self.assertIn("File Change Tracked", res)
            self.assertIn("MODIFIED", res)
            self.assertIn("File SHA256", res)

            session = ACTIVE_SESSIONS[self.session_name]
            self.assertEqual(len(session.file_changes), 1)
            self.assertEqual(session.file_changes[0]["change_type"], "modified")
            self.assertIsNotNone(session.file_changes[0]["sha256"])
        finally:
            Path(tf_path).unlink(missing_ok=True)

    def test_record_visual_mockups_action(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test visual mockups",
            "time_budget_minutes": 10.0
        })

        mockups = [
            {
                "concept_name": "Kinetic Glassmorphism",
                "aesthetic_archetype": "glassmorphic_modern",
                "prompt": "Futuristic UI with frosted glass cards",
                "palette": "oklch(0.95 0.02 240) / oklch(0.2 0.05 260)",
                "typography": "Geist, Geist Mono",
                "coordinates_data": {"grid": "12-col", "gap": "16px"}
            },
            {
                "concept_name": "Monochrome Minimal",
                "aesthetic_archetype": "swiss_high_contrast",
                "prompt": "Clean monochrome Swiss typography",
                "palette": "#000000 / #FFFFFF",
                "typography": "Inter, JetBrains Mono",
                "coordinates_data": {"grid": "bento-3x3"}
            }
        ]

        res = handle_fable_session({
            "action": "record_visual_mockups",
            "session_name": self.session_name,
            "mockups": mockups,
            "selected_concept": "Kinetic Glassmorphism"
        })
        self.assertIn("Visual Architectural Mockups Recorded", res)
        self.assertIn("Kinetic Glassmorphism", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.visual_mockups["mockups"]), 2)
        self.assertEqual(session.visual_mockups["selected_concept"], "Kinetic Glassmorphism")

    def test_verify_proof_action(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test proof verification",
            "time_budget_minutes": 10.0
        })

        res = handle_fable_session({
            "action": "verify_proof",
            "session_name": self.session_name,
            "claim": "Cargo test passes cleanly with 0 failures",
            "proof_type": "receipt",
            "evidence": "cargo test --all: exit code 0, 42 passed"
        })
        self.assertIn("Deterministic Proof Verification", res)
        self.assertIn("VERIFIED", res)
        self.assertIn("rcpt_", res)

    def test_get_session_lineage_and_inspect_plan(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Full lineage and blueprint inspection",
            "time_budget_minutes": 10.0
        })

        handle_fable_session({
            "action": "track_file_change",
            "session_name": self.session_name,
            "file_path": "src/core/router.py",
            "change_type": "slated",
            "diff_summary": "Implement atomic lock-free queue"
        })

        plan_res = handle_fable_session({
            "action": "inspect_plan",
            "session_name": self.session_name
        })
        self.assertIn("Fable Execution Plan & Cognitive Blueprint", plan_res)
        self.assertIn("Cognitive Gate Status", plan_res)
        self.assertIn("src/core/router.py", plan_res)

        lineage_res = handle_fable_session({
            "action": "get_session_lineage",
            "session_name": self.session_name
        })
        self.assertIn("Omniscient Session Lineage", lineage_res)
        self.assertIn("Slated File Modifications", lineage_res)
        self.assertIn("Model Velocity & Capability Telemetry", lineage_res)

    def test_tautology_rejection_in_proven_claim(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test tautology rejection",
            "time_budget_minutes": 10.0
        })

        # Tautological claim should be rejected
        res = handle_fable_session({
            "action": "log_epistemic_item",
            "session_name": self.session_name,
            "tag": "PROVEN",
            "claim": "it works tested verified",
            "evidence": "stdout: ok"
        })
        self.assertIn("Error:", res)
        self.assertIn("must not be tautological or generic", res)

    def test_validate_event_history_action(self):
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Test event history audit",
            "time_budget_minutes": 10.0
        })

        handle_fable_session({
            "action": "track_file_change",
            "session_name": self.session_name,
            "file_path": "src/unified.py",
            "change_type": "modified",
            "diff_summary": "+ unified event tracking",
        })

        audit_res = handle_fable_session({
            "action": "validate_event_history",
            "session_name": self.session_name,
        })
        self.assertIn("Cryptographic Event Chain Audit", audit_res)
        self.assertIn("VALID & INTACT", audit_res)

    def test_cross_process_session_mtime_synchronization(self):
        from fable_engine.server import get_or_load_session, SESSIONS_DIR
        handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": "Concurrency test",
            "time_budget_minutes": 10.0
        })
        session1 = get_or_load_session(self.session_name)
        file_path = SESSIONS_DIR / f"{self.session_name}.json"
        
        # Simulate external process update by loading, modifying, and saving to disk
        data = json.loads(file_path.read_text(encoding="utf-8"))
        data["objective"] = "Updated by external worker process"
        time.sleep(0.02)
        file_path.write_text(json.dumps(data), encoding="utf-8")

        # get_or_load_session should detect disk mtime delta and refresh in-memory session
        session2 = get_or_load_session(self.session_name)
        self.assertEqual(session2.objective, "Updated by external worker process")


if __name__ == "__main__":
    unittest.main()