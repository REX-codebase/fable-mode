"""Unit tests for Modular Fable Part 2: Hebbian Cortical Plasticity & Lifelong Neuro-Evolutionary Engine."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_v2.coder_fleet import CoderFleetDispatcher
from fable_v2.cortical import (
    CorticalDomain,
    CorticalLobe,
    HebbianPlasticityEngine,
    HeuristicAntibody,
)


class TestHebbianCorticalPlasticity(unittest.TestCase):
    """Exhaustive test suite for HebbianPlasticityEngine and cortical domain lobes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cortex_path = Path(self.temp_dir.name)
        self.engine = HebbianPlasticityEngine(cortex_dir=self.cortex_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cortical_domain_enum(self) -> None:
        """Verify CorticalDomain defines all 5 specialized domains."""
        self.assertEqual(CorticalDomain.RUST.value, "rust")
        self.assertEqual(CorticalDomain.PYTHON.value, "python")
        self.assertEqual(CorticalDomain.DESIGN_3D.value, "design_3d")
        self.assertEqual(CorticalDomain.RESEARCH.value, "research")
        self.assertEqual(CorticalDomain.CONCURRENCY.value, "concurrency")
        self.assertEqual(len(CorticalDomain), 5)

    def test_heuristic_antibody_dataclass_and_serialization(self) -> None:
        """Verify HeuristicAntibody serialization and formatting."""
        ab = HeuristicAntibody(
            antibody_id="ab_rust_deadlock_1",
            domain="rust",
            trigger_condition="Holding std::sync::Mutex across await",
            lethal_anti_pattern="let g = mutex.lock().unwrap(); async_call().await;",
            prescribed_defense="Use tokio::sync::Mutex or scope guard",
            severity="CRITICAL",
            source_task_id="task_100",
            created_at="2026-09-04T12:00:00Z",
            verified_counterfactual="Deadlock test verified 0 stalls",
        )
        d = ab.to_dict()
        self.assertEqual(d["antibody_id"], "ab_rust_deadlock_1")
        self.assertEqual(d["severity"], "CRITICAL")

        ab_restored = HeuristicAntibody.from_dict(d)
        self.assertEqual(ab_restored.antibody_id, ab.antibody_id)
        self.assertEqual(ab_restored.prescribed_defense, ab.prescribed_defense)

        md = ab.to_markdown()
        self.assertIn("#### Antibody `ab_rust_deadlock_1` [CRITICAL]", md)
        self.assertIn("Holding std::sync::Mutex across await", md)
        self.assertIn("Verified Counterfactual", md)

    def test_cortical_lobe_dataclass_and_disk_roundtrip(self) -> None:
        """Verify CorticalLobe serialization, markdown formatting, and disk save/load."""
        ab = HeuristicAntibody(
            antibody_id="ab_py_mut",
            domain="python",
            trigger_condition="Mutable default parameter",
            lethal_anti_pattern="def f(x=[])",
            prescribed_defense="Use None sentinel",
            severity="HIGH",
        )
        lobe = CorticalLobe(
            domain=CorticalDomain.PYTHON,
            activation_count=7,
            synaptic_weights={"asyncio": 0.85, "typing": 0.72},
            antibodies=[ab],
            specialized_heuristics=["Always use __slots__ for memory efficiency"],
            last_consolidated_at="2026-09-04T12:00:00Z",
        )

        lobe_file = self.cortex_path / "python_test.md"
        lobe.save_to_disk(lobe_file)
        self.assertTrue(lobe_file.exists())

        loaded_lobe = CorticalLobe.load_from_disk(lobe_file)
        self.assertEqual(loaded_lobe.domain, CorticalDomain.PYTHON)
        self.assertEqual(loaded_lobe.activation_count, 7)
        self.assertAlmostEqual(loaded_lobe.synaptic_weights["asyncio"], 0.85, places=2)
        self.assertEqual(len(loaded_lobe.antibodies), 1)
        self.assertEqual(loaded_lobe.antibodies[0].antibody_id, "ab_py_mut")
        self.assertEqual(len(loaded_lobe.specialized_heuristics), 1)

    def test_lobe_activation(self) -> None:
        """Verify activating a lobe increments its counter and primes nodes."""
        lobe = self.engine.activate_lobe("rust", co_activated_nodes=["tokio", "pin_project"])
        self.assertEqual(lobe.domain, CorticalDomain.RUST)
        self.assertEqual(lobe.activation_count, 1)
        self.assertIn("tokio", lobe.synaptic_weights)
        self.assertIn("pin_project", lobe.synaptic_weights)
        self.assertGreaterEqual(lobe.synaptic_weights["tokio"], 0.05)

        # Second activation
        lobe2 = self.engine.activate_lobe(CorticalDomain.RUST, co_activated_nodes=["tokio"])
        self.assertEqual(lobe2.activation_count, 2)
        self.assertGreater(lobe2.synaptic_weights["tokio"], 0.20)

    def test_task_consolidation_hebbian_rule(self) -> None:
        """Verify Hebbian rule delta updates: ΔW_ij = η * Score * (A_i * A_j)."""
        # Baseline activation
        self.engine.activate_lobe("concurrency", co_activated_nodes=["atomic_cas", "hazard_ptrs"])
        initial_lobe = self.engine._load_or_create_lobe(CorticalDomain.CONCURRENCY)
        initial_w = initial_lobe.synaptic_weights["atomic_cas"]

        # Successful consolidation (Score = 1.0, η = 0.1)
        receipt = self.engine.consolidate_task(
            domain="concurrency",
            task_id="task_cas_test_1",
            final_passed=True,
            co_activated_nodes=["atomic_cas", "hazard_ptrs"],
        )
        self.assertEqual(receipt["status"], "CONSOLIDATED")
        self.assertTrue(receipt["final_passed"])
        self.assertEqual(receipt["learning_rate"], 0.10)
        self.assertEqual(receipt["score"], 1.0)

        # Verify weight increased by exactly ~0.10
        updated_w = receipt["synaptic_weights"]["atomic_cas"]
        self.assertAlmostEqual(updated_w, initial_w + 0.10, places=2)

        # Verify global synaptic matrix pair co-activation was recorded
        matrix = self.engine.get_synaptic_matrix()
        self.assertIn("atomic_cas", matrix)
        self.assertIn("hazard_ptrs", matrix["atomic_cas"])
        self.assertGreaterEqual(matrix["atomic_cas"]["hazard_ptrs"], 0.15)

    def test_homeostatic_weight_bounding(self) -> None:
        """Verify synaptic weights remain strictly bounded within [0.05, 1.0]."""
        domain = CorticalDomain.RESEARCH

        # Run 20 consolidations to push weight towards maximum
        for i in range(20):
            receipt = self.engine.consolidate_task(
                domain=domain,
                task_id=f"iter_{i}",
                final_passed=True,
                co_activated_nodes=["citation_verifier", "causal_dag"],
            )

        weights = receipt["synaptic_weights"]
        for node, w in weights.items():
            self.assertLessEqual(w, 1.0, f"Weight for {node} exceeded 1.0: {w}")
            self.assertGreaterEqual(w, 0.05, f"Weight for {node} fell below 0.05: {w}")

    def test_antibody_synthesis_from_red_team_breakages(self) -> None:
        """Verify broken scenarios synthesize persistent HeuristicAntibodies."""
        broken_scenarios = [
            {
                "scenario_id": "toctou_race_burst",
                "vector": "concurrency_race",
                "hypothesis": "What will happen if 16 threads mutate the file descriptor concurrently?",
                "broken": True,
                "error_message": "FileExistsError: Cannot create file that already exists",
                "reproduction_code": "race_harness.run(threads=16)",
                "severity": "CRITICAL",
                "prescribed_defense": "Use atomic O_CREAT | O_EXCL flags",
            },
            {
                "scenario_id": "null_byte_injection",
                "vector": "byzantine_payload",
                "hypothesis": "What will happen if payload contains \\x00 byte?",
                "broken": True,
                "error_message": "ValueError: embedded null byte",
                "severity": "HIGH",
                "remediation_directives": ["Sanitize input using null-byte strip filter"],
            },
        ]

        receipt = self.engine.consolidate_task(
            domain="concurrency",
            task_id="task_red_team_harden_01",
            broken_scenarios=broken_scenarios,
            final_passed=True,
        )

        self.assertEqual(receipt["antibodies_added"], 2)
        self.assertEqual(receipt["total_antibodies"], 2)

        lobe = self.engine._load_or_create_lobe(CorticalDomain.CONCURRENCY)
        self.assertEqual(len(lobe.antibodies), 2)
        ab_ids = [a.antibody_id for a in lobe.antibodies]
        self.assertIn("ab_concurrency_toctou_race_burst", ab_ids)
        self.assertIn("ab_concurrency_null_byte_injection", ab_ids)

        # Test deduplication: running same broken scenario does not duplicate antibody
        receipt2 = self.engine.consolidate_task(
            domain="concurrency",
            task_id="task_red_team_harden_02",
            broken_scenarios=broken_scenarios,
            final_passed=True,
        )
        self.assertEqual(receipt2["antibodies_added"], 0)
        self.assertEqual(receipt2["total_antibodies"], 2)

    def test_specialized_heuristics_from_lessons(self) -> None:
        """Verify lessons are extracted into specialized domain heuristics."""
        lessons = [
            "Always enforce WebGPU fallback to WebGL2 for headless CI environments",
            {"heuristic": "Pre-calculate APCA Lc >= 75 contrast before rendering text"},
        ]
        receipt = self.engine.consolidate_task(
            domain="design_3d",
            task_id="task_design_lessons_01",
            lessons=lessons,
            final_passed=True,
        )
        self.assertEqual(receipt["heuristics_added"], 2)
        self.assertEqual(receipt["total_heuristics"], 2)

        lobe = self.engine._load_or_create_lobe(CorticalDomain.DESIGN_3D)
        self.assertIn("Always enforce WebGPU fallback to WebGL2 for headless CI environments", lobe.specialized_heuristics)
        self.assertIn("Pre-calculate APCA Lc >= 75 contrast before rendering text", lobe.specialized_heuristics)

    def test_recall_cortical_context(self) -> None:
        """Verify recall_cortical_context formats a high-signal markdown block."""
        # Add an antibody and activate
        self.engine.consolidate_task(
            domain="rust",
            task_id="task_recall_test",
            broken_scenarios=[
                {
                    "scenario_id": "unbounded_channel",
                    "hypothesis": "What happens under 1M msgs?",
                    "error_message": "OutOfMemoryError",
                    "prescribed_defense": "Enforce bounded channel with permit backpressure",
                    "severity": "HIGH",
                }
            ],
            lessons=["Zero-cost abstractions must compile to 0 heap allocations"],
            co_activated_nodes=["tokio", "concurrency_fuzz"],
            final_passed=True,
        )

        memory_block = self.engine.recall_cortical_context("rust", max_antibodies=3)
        self.assertIn("### 🧠 Cortical Lobe Memory: `RUST`", memory_block)
        self.assertIn("🛡️ Immunological Heuristic Antibodies", memory_block)
        self.assertIn("Enforce bounded channel with permit backpressure", memory_block)
        self.assertIn("Zero-cost abstractions must compile to 0 heap allocations", memory_block)
        self.assertIn("Strongly-Wired Synaptic Companion Tools", memory_block)
        self.assertIn("tokio", memory_block)

    def test_coder_fleet_dispatcher_routing(self) -> None:
        """Verify CoderFleetDispatcher correctly dispatches all 4 cortical actions."""
        dispatcher = CoderFleetDispatcher(plasticity_engine=self.engine)

        # 1. cortical_activate_lobe
        res_act = dispatcher.dispatch("cortical_activate_lobe", {"domain": "python", "co_activated_nodes": ["asyncio"]})
        self.assertTrue(res_act["success"])
        self.assertEqual(res_act["action"], "cortical_activate_lobe")
        self.assertIsInstance(res_act["result"], CorticalLobe)

        # 2. cortical_consolidate_task
        res_cons = dispatcher.dispatch(
            "cortical_consolidate_task",
            {
                "domain": "python",
                "task_id": "task_fleet_01",
                "final_passed": True,
                "co_activated_nodes": ["asyncio", "typing"],
            },
        )
        self.assertTrue(res_cons["success"])
        self.assertEqual(res_cons["result"]["status"], "CONSOLIDATED")

        # 3. cortical_recall_context
        res_rec = dispatcher.dispatch("cortical_recall_context", {"domain": "python", "max_antibodies": 2})
        self.assertTrue(res_rec["success"])
        self.assertIn("Cortical Lobe Memory: `PYTHON`", res_rec["result"])

        # 4. cortical_inspect_matrix
        res_mat = dispatcher.dispatch("cortical_inspect_matrix", {})
        self.assertTrue(res_mat["success"])
        self.assertIsInstance(res_mat["result"], dict)

    def test_production_baseline_lobes_integrity(self) -> None:
        """Verify the repository's 5 production baseline lobes in skills/fable-mode/cortex/ are fully valid."""
        repo_engine = HebbianPlasticityEngine()  # Resolves to repo cortex dir
        for domain in CorticalDomain:
            lobe = repo_engine.activate_lobe(domain)
            self.assertEqual(lobe.domain, domain)
            self.assertGreaterEqual(len(lobe.antibodies), 3, f"Lobe {domain.value} has fewer than 3 antibodies")
            self.assertGreaterEqual(len(lobe.specialized_heuristics), 5, f"Lobe {domain.value} has fewer than 5 heuristics")
            self.assertGreaterEqual(len(lobe.synaptic_weights), 5, f"Lobe {domain.value} has fewer than 5 synaptic weights")


if __name__ == "__main__":
    unittest.main()
