"""Unit tests for Modular Fable Part 2: Hebbian Cortical Plasticity & Lifelong Neuro-Evolutionary Engine."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_v2.coder_fleet import CoderFleetDispatcher, RedTeamSwarm
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
        self.assertEqual(receipt["plasticity_mode"], "LTP")

        # Verify weight increased via BCM LTP (delta_w = learning_rate * A_domain * A_node)
        # A_domain = min(1.0, max(0.30, 0.40 + 0.10 * 2)) = 0.60
        # A_node = max(0.75, min(0.90, 0.90 - 0 * 0.03)) = 0.90
        # delta_w = 0.10 * 0.60 * 0.90 = 0.054
        expected_delta = 0.10 * (0.40 + 0.10 * 2) * 0.90
        updated_w = receipt["synaptic_weights"]["atomic_cas"]
        self.assertAlmostEqual(updated_w, initial_w + expected_delta, places=2)
        self.assertGreater(updated_w, initial_w)

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

        # 5. cortical_define_lobe
        res_def = dispatcher.dispatch(
            "cortical_define_lobe",
            {
                "name": "solidity_evm",
                "description": "Smart contract reentrancy defenses and EVM gas profiling",
                "initial_heuristics": ["Follow Checks-Effects-Interactions pattern strictly"],
                "initial_synaptic_weights": {"reentrancy_guard": 0.95},
            },
        )
        self.assertTrue(res_def["success"])
        self.assertEqual(res_def["action"], "cortical_define_lobe")
        self.assertIsInstance(res_def["result"], CorticalLobe)
        self.assertEqual(res_def["result"].name, "solidity_evm")

        # 6. cortical_list_lobes
        res_list = dispatcher.dispatch("cortical_list_lobes", {})
        self.assertTrue(res_list["success"])
        self.assertEqual(res_list["action"], "cortical_list_lobes")
        self.assertIsInstance(res_list["result"], list)
        names = [l["name"] for l in res_list["result"]]
        self.assertIn("solidity_evm", names)

    def test_define_cortical_lobe_custom_sprouting(self) -> None:
        """Verify dynamic open-ended sprouting of a customizable cortical lobe from scratch."""
        heuristics = [
            "Always pass an explicit Allocator; never hide heap allocation inside structs",
            "Use comptime assertions to eliminate invalid type configurations at build time",
        ]
        weights = {"std_mem": 0.88, "comptime": 0.95, "c_interop": 0.70}
        lobe = self.engine.define_cortical_lobe(
            name="zig_systems",
            description="Low-level Zig memory management, comptime, and C-interop",
            initial_heuristics=heuristics,
            initial_synaptic_weights=weights,
        )

        self.assertEqual(lobe.name, "zig_systems")
        self.assertEqual(lobe.description, "Low-level Zig memory management, comptime, and C-interop")
        self.assertEqual(lobe.domain, "zig_systems")
        self.assertEqual(lobe.activation_count, 1)
        self.assertEqual(len(lobe.specialized_heuristics), 2)
        self.assertAlmostEqual(lobe.synaptic_weights["comptime"], 0.95, places=2)

        # Verify disk persistence
        lobe_file = self.cortex_path / "zig_systems.md"
        self.assertTrue(lobe_file.exists())
        loaded = CorticalLobe.load_from_disk(lobe_file)
        self.assertEqual(loaded.name, "zig_systems")
        self.assertEqual(loaded.description, "Low-level Zig memory management, comptime, and C-interop")
        self.assertEqual(len(loaded.specialized_heuristics), 2)
        self.assertAlmostEqual(loaded.synaptic_weights["comptime"], 0.95, places=2)

        # Verify matrix integration
        matrix = self.engine.get_synaptic_matrix()
        self.assertIn("zig_systems", matrix)
        self.assertIn("comptime", matrix["zig_systems"])
        self.assertAlmostEqual(matrix["zig_systems"]["comptime"], 0.95, places=2)

    def test_activate_lobe_auto_sprouting(self) -> None:
        """Verify activate_lobe automatically sprouts a novel lobe when it does not exist."""
        lobe_file = self.cortex_path / "elixir_otp.md"
        self.assertFalse(lobe_file.exists())

        # Auto-sprout with explicit description
        lobe = self.engine.activate_lobe(
            domain_or_name="elixir_otp",
            description="Actor-model concurrency, supervision trees, and GenServer invariants",
            co_activated_nodes=["gen_server", "supervision_tree"],
        )
        self.assertTrue(lobe_file.exists())
        self.assertEqual(lobe.name, "elixir_otp")
        self.assertEqual(lobe.description, "Actor-model concurrency, supervision trees, and GenServer invariants")
        self.assertEqual(lobe.activation_count, 1)
        self.assertIn("gen_server", lobe.synaptic_weights)

        # Auto-sprout with default description fallback
        lobe_bio = self.engine.activate_lobe("bioinformatics_genomics")
        self.assertEqual(lobe_bio.name, "bioinformatics_genomics")
        self.assertIn("Custom cortical lobe for bioinformatics_genomics", lobe_bio.description)

        # Subsequent activation increments count
        lobe2 = self.engine.activate_lobe("elixir_otp", co_activated_nodes=["gen_server"])
        self.assertEqual(lobe2.activation_count, 2)

    def test_list_cortical_lobes(self) -> None:
        """Verify list_cortical_lobes discovers and returns metadata for all available lobes."""
        # Create baseline and custom lobes
        self.engine.activate_lobe("rust")
        self.engine.define_cortical_lobe(
            name="kubernetes_operators",
            description="Reconciliation loop invariants and CRD controllers",
            initial_heuristics=["Always use idempotent reconcile loops"],
        )

        lobes = self.engine.list_cortical_lobes()
        self.assertIsInstance(lobes, list)
        names = [l["name"] for l in lobes]
        self.assertIn("rust", names)
        self.assertIn("kubernetes_operators", names)

        k8s_meta = next(l for l in lobes if l["name"] == "kubernetes_operators")
        self.assertEqual(k8s_meta["description"], "Reconciliation loop invariants and CRD controllers")
        self.assertEqual(k8s_meta["heuristic_count"], 1)
        self.assertTrue(Path(k8s_meta["file_path"]).exists())

    def test_task_consolidation_and_antibodies_custom_lobe(self) -> None:
        """Verify task consolidation, Hebbian weight updating, and antibody synthesis in a custom lobe."""
        broken_scenarios = [
            {
                "scenario_id": "simd_tile_misalignment",
                "hypothesis": "What happens if SIMD vector width does not evenly divide tensor shape?",
                "error_message": "AlignmentError: unaligned memory access in vector register load",
                "reproduction_code": "mojo_kernel.execute(tensor_shape=(13, 17))",
                "prescribed_defense": "Enforce dynamic tail padding and vectorized mask loading",
                "severity": "CRITICAL",
            }
        ]

        receipt = self.engine.consolidate_task(
            domain="mojo_kernels",
            task_id="task_mojo_vectorization_01",
            broken_scenarios=broken_scenarios,
            final_passed=True,
            lessons=["Always utilize compile-time SIMD width querying via sys.info.simdwidthof"],
            co_activated_nodes=["autotune", "vectorize"],
        )

        self.assertEqual(receipt["status"], "CONSOLIDATED")
        self.assertEqual(receipt["domain"], "mojo_kernels")
        self.assertEqual(receipt["name"], "mojo_kernels")
        self.assertEqual(receipt["antibodies_added"], 1)
        self.assertEqual(receipt["heuristics_added"], 1)

        lobe = self.engine._load_or_create_lobe("mojo_kernels")
        self.assertEqual(len(lobe.antibodies), 1)
        self.assertEqual(lobe.antibodies[0].antibody_id, "ab_mojo_kernels_simd_tile_misalignment")
        self.assertEqual(lobe.antibodies[0].domain, "mojo_kernels")

        # Verify recall reflects custom lobe
        context = self.engine.recall_cortical_context("mojo_kernels")
        self.assertIn("### 🧠 Cortical Lobe Memory: `MOJO_KERNELS`", context)
        self.assertIn("What happens if SIMD vector width", context)
        self.assertIn("Enforce dynamic tail padding and vectorized mask loading", context)
        self.assertIn("compile-time SIMD width querying", context)

    def test_continuous_activity_dependent_activation_metrics(self) -> None:
        """Verify continuous A_j scaling with activation_metrics and A_domain computation."""
        receipt = self.engine.consolidate_task(
            domain="python",
            task_id="task_metrics_01",
            final_passed=True,
            co_activated_nodes=["asyncio", "typing", "celery"],
            activation_metrics={"asyncio": 100.0, "typing": 50.0, "celery": 5.0},
        )
        signals = receipt["activation_signals"]
        # Max metric is 100.0, denom is 100.0
        # asyncio: 100/100 = 1.0 -> min(1.0, max(0.15, 1.0)) = 1.0
        # typing: 50/100 = 0.50 -> min(1.0, max(0.15, 0.50)) = 0.50
        # celery: 5/100 = 0.05 -> min(1.0, max(0.15, 0.05)) = 0.15 (floored at 0.15)
        self.assertAlmostEqual(signals["asyncio"], 1.0, places=3)
        self.assertAlmostEqual(signals["typing"], 0.50, places=3)
        self.assertAlmostEqual(signals["celery"], 0.15, places=3)

        # Domain activation with 3 nodes: min(1.0, max(0.30, 0.40 + 0.10 * 3)) = 0.70
        self.assertAlmostEqual(receipt["A_domain"], 0.70, places=3)

    def test_bcm_asymmetric_plasticity_ltd_vs_ltp(self) -> None:
        """Verify BCM plasticity: LTD on failure (ΔW < 0) vs LTP on success (ΔW > 0)."""
        # Set up an initial node weight in concurrency lobe
        lobe = self.engine._load_or_create_lobe("concurrency")
        lobe.synaptic_weights["broken_pathway"] = 0.60
        initial_w = lobe.synaptic_weights["broken_pathway"]

        # 1. Synaptic Depression (LTD) on final_passed=False: strictly decreases weight
        receipt_fail = self.engine.consolidate_task(
            domain="concurrency",
            task_id="task_ltd_01",
            final_passed=False,
            co_activated_nodes=["broken_pathway"],
        )
        self.assertEqual(receipt_fail["plasticity_mode"], "LTD")
        w_after_fail = receipt_fail["synaptic_weights"]["broken_pathway"]
        self.assertLess(w_after_fail, initial_w, f"LTD must decrease weight: {w_after_fail} >= {initial_w}")
        # Expected LTD delta: -0.15 * A_domain (0.50) * A_node (0.90) = -0.0675
        expected_ltd_delta = - 0.15 * 0.50 * 0.90
        self.assertAlmostEqual(w_after_fail, initial_w + expected_ltd_delta, places=2)

        # 2. Synaptic Potentiation (LTP) on final_passed=True: strictly increases weight
        receipt_pass = self.engine.consolidate_task(
            domain="concurrency",
            task_id="task_ltp_01",
            final_passed=True,
            co_activated_nodes=["broken_pathway"],
        )
        self.assertEqual(receipt_pass["plasticity_mode"], "LTP")
        w_after_pass = receipt_pass["synaptic_weights"]["broken_pathway"]
        self.assertGreater(w_after_pass, w_after_fail, f"LTP must increase weight: {w_after_pass} <= {w_after_fail}")
        # Expected LTP delta: +0.10 * A_domain (0.50) * A_node (0.90) = +0.045
        expected_ltp_delta = 0.10 * 0.50 * 0.90
        self.assertAlmostEqual(w_after_pass, w_after_fail + expected_ltp_delta, places=2)

    def test_homeostatic_weight_bounding_ltd_floor(self) -> None:
        """Verify synaptic depression (LTD) strictly respects the [0.05, 1.00] homeostatic floor."""
        lobe = self.engine._load_or_create_lobe("research")
        lobe.synaptic_weights["failing_path"] = 0.10

        for i in range(15):
            receipt = self.engine.consolidate_task(
                domain="research",
                task_id=f"fail_burst_{i}",
                final_passed=False,
                co_activated_nodes=["failing_path"],
            )

        final_w = receipt["synaptic_weights"]["failing_path"]
        self.assertGreaterEqual(final_w, 0.05)
        self.assertEqual(final_w, 0.05)

    def test_automated_closed_loop_red_team_to_cortical_consolidation(self) -> None:
        """Verify full automated closed-loop RedTeam -> Remediation -> Cortical Consolidation."""
        swarm = RedTeamSwarm(plasticity_engine=self.engine)

        # Fragile target that breaks under adversarial probe
        def fragile_target(payload: Any = None) -> str:
            if payload is None or (isinstance(payload, str) and "\x00" in payload):
                raise ValueError("Fatal unhandled payload corruption")
            return "ok"

        # 1. Swarm attack breaks fragile target -> auto-consolidates with LTD
        report_break = swarm.run_full_review_cycle(
            fragile_target,
            target_name="crypto_service",
        )
        self.assertFalse(report_break.passed)
        self.assertGreater(report_break.broken_count, 0)

        # Verify LTD was automatically applied to crypto_service lobe
        lobe = self.engine._load_or_create_lobe("crypto_service")
        self.assertIn("test_harness", lobe.synaptic_weights)
        self.assertIn("red_team_swarm", lobe.synaptic_weights)
        # 0.30 baseline depressed by -0.15 * A_domain * A_node
        self.assertLess(lobe.synaptic_weights["test_harness"], 0.30)
        self.assertGreaterEqual(len(lobe.antibodies), 1)

        # 2. Subagent remediates and hardens target
        def hardened_target(payload: Any = None) -> str:
            if payload is None:
                return "ok_default"
            if isinstance(payload, str):
                return "ok_" + payload.replace("\x00", "")[:100]
            return "ok_" + str(payload)[:100]

        # 3. Swarm verifies remediation -> auto-consolidates with LTP and synthesizes verified antibody
        all_fixed, report_fixed = swarm.verify_remediation(
            target_callable=hardened_target,
            prior_report=report_break,
        )
        self.assertTrue(all_fixed)
        self.assertTrue(report_fixed.passed)
        self.assertEqual(report_fixed.broken_count, 0)

        # Verify LTP was automatically applied to remediating pathway
        lobe_after = self.engine._load_or_create_lobe("crypto_service")
        self.assertIn("mutation", lobe_after.synaptic_weights)
        # 0.30 baseline potentiated by +0.10 * A_domain * A_node
        self.assertGreater(lobe_after.synaptic_weights["mutation"], 0.30)
        self.assertGreater(len(lobe_after.antibodies), 0)
        self.assertGreater(len(lobe_after.specialized_heuristics), 0)

        # Verify disk persistence
        lobe_file = self.cortex_path / "crypto_service.md"
        self.assertTrue(lobe_file.exists())
        loaded_lobe = CorticalLobe.load_from_disk(lobe_file)
        self.assertEqual(loaded_lobe.name, "crypto_service")
        self.assertGreater(len(loaded_lobe.antibodies), 0)

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
