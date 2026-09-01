"""Comprehensive Unit Tests for System 3 Meta-Cognitive Deliberation & Dialectical Architecture."""

from __future__ import annotations

import unittest
import math

from fable_v2.system3 import (
    CausalDAG,
    CausalNode,
    CausalEdge,
    CausalNodeType,
    CausalCycleError,
    CausalNodeNotFoundError,
    BrittlenessReport,
    InterventionResult,
    ThesisCandidate,
    AntithesisCritique,
    Contradiction,
    TRIZPrinciple,
    TRIZContradictionResolver,
    TRIZ_PRINCIPLES_CATALOG,
    DialecticalSynthesizer,
    EmergentSynthesis,
    CognitiveGenome,
    CognitiveGenePool,
    PARETO_DIMENSIONS,
    create_random_genome,
    NeuroSymbolicAxiom,
    AxiomProvenance,
    AxiomStatus,
    MetaProofInducer,
    CognitiveGear,
    CognitiveBiasType,
    CognitiveBiasFinding,
    CognitiveBiasDetector,
    DynamicSearchHeuristicRewriter,
    SearchHeuristicConfig,
    TriLevelArbitrator,
    System3Executive,
)
from fable_v2.protocol import ToolReceipt, Evidence, canonical_hash


class TestSystem3CausalDAG(unittest.TestCase):
    """Unit tests for Causal DAG, Pearl's Do-Calculus, and Brittleness Analysis."""

    def test_dag_creation_and_topological_sort(self):
        dag = CausalDAG(name="ThroughputLatencyModel")
        n1 = dag.add_node("threads", "Worker Threads", CausalNodeType.EXOGENOUS, value=4.0)
        n2 = dag.add_node("contention", "Lock Contention", CausalNodeType.ENDOGENOUS, value=0.0)
        n3 = dag.add_node("throughput", "System Throughput", CausalNodeType.METRIC, value=0.0)

        dag.add_edge("threads", "contention", weight=0.5)
        dag.add_edge("threads", "throughput", weight=2.0)
        dag.add_edge("contention", "throughput", weight=-1.5)

        is_acyclic, cycle = dag.check_acyclicity()
        self.assertTrue(is_acyclic)
        self.assertEqual(len(cycle), 0)

        order = dag.topological_sort()
        self.assertEqual(order[0], "threads")
        self.assertIn("contention", order[1:])
        self.assertEqual(order[-1], "throughput")

    def test_cycle_detection_and_rejection(self):
        dag = CausalDAG(name="CycleTest")
        dag.add_node("A", value=1.0)
        dag.add_node("B", value=2.0)
        dag.add_node("C", value=3.0)

        dag.add_edge("A", "B")
        dag.add_edge("B", "C")

        # Attempting to add C -> A should raise CausalCycleError and rollback
        with self.assertRaises(CausalCycleError):
            dag.add_edge("C", "A")

        # Verify DAG remains valid after rejected edge
        is_dag, _ = dag.check_acyclicity()
        self.assertTrue(is_dag)
        self.assertEqual(len(dag.edges), 2)

    def test_self_loop_rejection(self):
        dag = CausalDAG(name="SelfLoopTest")
        dag.add_node("A", value=1.0)
        with self.assertRaises(CausalCycleError):
            dag.add_edge("A", "A")

    def test_pearl_do_calculus_intervention(self):
        """Verify Pearl's do-operator severs incoming edges and calculates counterfactual deltas."""
        dag = CausalDAG(name="InterventionTest")
        dag.add_node("workers", value=2.0)
        dag.add_node("cache_hits", value=100.0)
        dag.add_node("latency", value=0.0)

        dag.add_edge("workers", "cache_hits", weight=-10.0)
        dag.add_edge("cache_hits", "latency", weight=-0.5)

        # Baseline factual computation
        f_vals = dag.compute_forward()
        self.assertEqual(f_vals["workers"], 2.0)
        self.assertEqual(f_vals["cache_hits"], -20.0)
        self.assertEqual(f_vals["latency"], 10.0)

        # Apply do(cache_hits = 50.0) -> graph surgery cuts workers -> cache_hits edge
        res = dag.do_intervention({"cache_hits": 50.0})
        self.assertEqual(res.counterfactual_values["cache_hits"], 50.0)
        self.assertEqual(res.counterfactual_values["latency"], -25.0)
        self.assertEqual(res.deltas["latency"], -35.0)
        self.assertIn(("workers", "cache_hits"), res.severed_edges)

    def test_structural_brittleness_evaluation(self):
        dag = CausalDAG(name="BrittlenessTest")
        dag.add_node("gateway", value=1.0)
        dag.add_node("auth_service", value=1.0)
        dag.add_node("api_latency", value=0.0)

        dag.add_edge("gateway", "auth_service", weight=2.0)
        dag.add_edge("auth_service", "api_latency", weight=3.0)

        report = dag.evaluate_brittleness("api_latency", critical_sensitivity_threshold=1.5)
        self.assertIsInstance(report, BrittlenessReport)
        self.assertGreater(report.overall_brittleness_score, 0.0)
        self.assertIn("auth_service", report.single_points_of_failure)
        self.assertIn("gateway", report.single_points_of_failure)
        self.assertTrue(len(report.critical_paths) > 0)

    def test_custom_evaluator_and_serialization(self):
        dag = CausalDAG(name="CustomEval")
        dag.add_node("x", value=3.0)
        dag.add_node("y", value=4.0)
        dag.add_node("hypotenuse", value=0.0)

        dag.add_edge("x", "hypotenuse")
        dag.add_edge("y", "hypotenuse")
        dag.register_evaluator("hypotenuse", lambda vals: math.sqrt(vals["x"]**2 + vals["y"]**2))

        vals = dag.compute_forward()
        self.assertAlmostEqual(vals["hypotenuse"], 5.0)

        # Test dictionary roundtrip
        d = dag.to_dict()
        restored = CausalDAG.from_dict(d)
        self.assertEqual(restored.name, "CustomEval")
        self.assertEqual(len(restored.nodes), 3)
        self.assertEqual(len(restored.edges), 2)


class TestSystem3DialecticalSynthesis(unittest.TestCase):
    """Unit tests for TRIZ Contradiction Matrix and Dialectical Synthesizer."""

    def test_triz_catalog_completeness(self):
        self.assertEqual(len(TRIZ_PRINCIPLES_CATALOG), 40)
        p1 = TRIZ_PRINCIPLES_CATALOG[1]
        self.assertEqual(p1.name, "Segmentation")
        self.assertTrue(len(p1.software_analogs) > 0)

    def test_triz_contradiction_resolver(self):
        resolver = TRIZContradictionResolver()
        contra = Contradiction(
            contradiction_id="c1",
            improving_parameter="throughput",
            worsening_parameter="latency",
            description="Batching increases throughput but adds pipeline latency",
            severity=0.85,
        )
        recs = resolver.resolve_contradiction(contra)
        self.assertTrue(len(recs) > 0)
        principle_numbers = [r.principle.number for r in recs]
        # Should include Segmentation (1), Dynamics (15), Prior Action (10), or Intermediary (24)
        self.assertTrue(any(p in [1, 15, 10, 24, 21] for p in principle_numbers))

    def test_dialectical_synthesizer_monotonic_convergence(self):
        thesis = ThesisCandidate(
            thesis_id="th_1",
            title="Monolithic In-Memory Cache",
            description="Fast direct access but high single-point-of-failure risk",
            metrics={"throughput": 0.9, "safety": 0.3},
        )
        critique = AntithesisCritique(
            critique_id="cr_1",
            thesis_id="th_1",
            title="Red-Team Memory Corruptibility",
            contradictions=[
                Contradiction(
                    contradiction_id="c_01",
                    improving_parameter="speed",
                    worsening_parameter="memory",
                    description="Unbounded cache causes OOM risk",
                    severity=0.8,
                )
            ],
            failure_modes=["Process crash loses all uncommitted writes"],
            severity_score=0.75,
        )

        synthesizer = DialecticalSynthesizer()
        synthesis = synthesizer.synthesize(thesis, critique, max_debate_rounds=3, target_residual_threshold=0.20)

        self.assertIsInstance(synthesis, EmergentSynthesis)
        self.assertLess(synthesis.residual_contradiction_score, synthesis.initial_contradiction_score)
        self.assertTrue(synthesis.convergence_achieved)
        self.assertTrue(len(synthesis.transcended_principles) > 0)

        # Check serialization
        d = synthesis.to_dict()
        restored = EmergentSynthesis.from_dict(d)
        self.assertEqual(restored.synthesis_id, synthesis.synthesis_id)
        self.assertEqual(restored.residual_contradiction_score, synthesis.residual_contradiction_score)


class TestSystem3EvolutionaryEngine(unittest.TestCase):
    """Unit tests for CognitiveGenome, NSGA-II 10D Pareto optimization, and GenePool."""

    def test_genome_pareto_dominance(self):
        g1 = CognitiveGenome(
            genome_id="g1",
            paradigm_name="Candidate 1",
            fitness_scores={dim: 0.8 for dim in PARETO_DIMENSIONS},
        )
        g2 = CognitiveGenome(
            genome_id="g2",
            paradigm_name="Candidate 2",
            fitness_scores={dim: 0.7 for dim in PARETO_DIMENSIONS},
        )
        # g1 strictly dominates g2
        self.assertTrue(g1.dominates(g2))
        self.assertFalse(g2.dominates(g1))

        # Incomparable genomes (trade-off)
        g3 = CognitiveGenome(
            genome_id="g3",
            paradigm_name="Candidate 3",
            fitness_scores={dim: 0.8 for dim in PARETO_DIMENSIONS},
        )
        g3.fitness_scores["latency"] = 0.95
        g3.fitness_scores["simplicity"] = 0.60
        self.assertFalse(g1.dominates(g3))
        self.assertFalse(g3.dominates(g1))

    def test_gene_pool_evolution_generations(self):
        pool = CognitiveGenePool(population_size=10, mutation_rate=0.2, crossover_rate=0.8, random_seed=123)
        pool.initialize_population()
        self.assertEqual(len(pool.population), 10)

        frontier_gen0 = pool.get_pareto_frontier()
        self.assertTrue(len(frontier_gen0) > 0)

        # Evolve 3 generations
        for _ in range(3):
            pool.evolve_generation()

        self.assertEqual(pool.generation_count, 3)
        self.assertEqual(len(pool.population), 10)
        best = pool.get_best_genome()
        self.assertIsInstance(best, CognitiveGenome)
        self.assertGreaterEqual(best.compute_scalar_fitness(), 0.5)

        # Check serialization round-trip
        d = pool.to_dict()
        restored = CognitiveGenePool.from_dict(d)
        self.assertEqual(restored.generation_count, 3)
        self.assertEqual(len(restored.population), 10)


class TestSystem3NeuroSymbolicInduction(unittest.TestCase):
    """Unit tests for Neuro-Symbolic Axiom Induction and empirical verification."""

    def test_axiom_evaluation_and_verification(self):
        prov = AxiomProvenance(provenance_id="prov_test", empirical_samples=5, falsification_attempts=5)
        axiom = NeuroSymbolicAxiom(
            axiom_id="AXIOM-TEST-001",
            name="Token Ratio Boundedness",
            symbolic_expression="forall data: TokenRatio(data) <= 0.003",
            natural_language="Token ratio must not exceed 0.003 for large payloads",
            domain="performance",
            provenance=prov,
        )

        test_cases_pass = [
            {"token_ratio": 0.0025, "raw_chars": 15000},
            {"token_ratio": 0.0018, "raw_chars": 20000},
            {"token_ratio": 0.0029, "raw_chars": 12000},
        ]
        inducer = MetaProofInducer()
        success, ratio, failures = inducer.verify_axiom_empirically(axiom, test_cases_pass)
        self.assertTrue(success)
        self.assertEqual(ratio, 1.0)
        self.assertEqual(len(failures), 0)
        self.assertEqual(axiom.status, AxiomStatus.PROVEN)

        # Test falsification
        test_cases_fail = [
            {"token_ratio": 0.0080, "raw_chars": 15000},
        ]
        success_fail, ratio_fail, failures_fail = inducer.verify_axiom_empirically(axiom, test_cases_fail)
        self.assertFalse(success_fail)
        self.assertEqual(axiom.status, AxiomStatus.FALSIFIED)
        self.assertEqual(len(failures_fail), 1)

    def test_axiom_induction_from_session(self):
        inducer = MetaProofInducer()
        axioms = inducer.induce_axioms_from_session(
            receipts=[],
            evidence=[],
            session_telemetry={"active_phase": "Phase 1", "phase_history": [{"phase": "Phase 1"}]},
        )
        self.assertTrue(len(axioms) >= 3)
        names = [a.name for a in axioms]
        self.assertIn("Content-Addressed Immutability & Determinism", names)
        self.assertIn("Token Compaction Ratio Upper Bound", names)
        self.assertIn("Immutable Authority Pacing Lockout", names)

        # Check proof sketch formatting
        sketch = inducer.formalize_to_proof_sketch(axioms[0])
        self.assertIn("Formal Neuro-Symbolic Proof Sketch", sketch)


class TestSystem3ExecutiveAndArbitration(unittest.TestCase):
    """Unit tests for CognitiveBiasDetector, TriLevelArbitrator, and System3Executive."""

    def test_cognitive_bias_detector(self):
        detector = CognitiveBiasDetector()

        # State with confirmation bias: 4 hypotheses, 0 proven, 0 unknown
        session_biased = {
            "epistemic_ledger": [
                {"id": "e1", "tag": "HYPOTHESIS", "claim": "H1"},
                {"id": "e2", "tag": "HYPOTHESIS", "claim": "H2"},
                {"id": "e3", "tag": "HYPOTHESIS", "claim": "H3"},
                {"id": "e4", "tag": "HYPOTHESIS", "claim": "H4"},
            ],
            "refinement_cycles": [],
            "invariants": [],
            "active_phase": "Phase 1: Epistemic Grounding & Live Research",
        }
        findings = detector.audit_session(session_biased)
        self.assertTrue(any(f.bias_type == CognitiveBiasType.CONFIRMATION_BIAS for f in findings))

    def test_tri_level_arbitrator(self):
        arbitrator = TriLevelArbitrator()

        # High complexity & high contradiction density -> SYSTEM_3
        res_s3 = arbitrator.arbitrate(task_complexity=0.9, contradiction_density=0.85, failure_count=2)
        self.assertEqual(res_s3["recommended_gear"], CognitiveGear.SYSTEM_3_META_COGNITIVE.value)
        self.assertTrue(len(res_s3["directives"]) >= 3)

        # Low complexity -> SYSTEM_1
        res_s1 = arbitrator.arbitrate(task_complexity=0.2, contradiction_density=0.1, failure_count=0, epistemic_uncertainty=0.1)
        self.assertEqual(res_s1["recommended_gear"], CognitiveGear.SYSTEM_1_INTUITIVE.value)

    def test_dynamic_heuristic_rewriting(self):
        rewriter = DynamicSearchHeuristicRewriter()
        base_config = SearchHeuristicConfig(exploration_temperature=0.7)

        # Rewriting under high contradiction density increases temperature
        updated = rewriter.rewrite_heuristics(base_config, contradiction_density=0.85, bias_findings=[])
        self.assertGreater(updated.exploration_temperature, base_config.exploration_temperature)

    def test_system3_executive_meta_reflection(self):
        executive = System3Executive()
        session_data = {
            "session_name": "test_exec_session",
            "epistemic_ledger": [
                {"id": "e1", "tag": "PROVEN", "claim": "Verified file exists", "evidence": "server.py:10"},
                {"id": "e2", "tag": "HYPOTHESIS", "claim": "Cache will improve latency"},
            ],
            "refinement_cycles": [],
            "invariants": [],
            "active_phase": "Phase 3: Adversarial Red-Teaming & Falsification",
        }
        report = executive.meta_reflect(session_data)
        self.assertIn("cognitive_gear", report)
        self.assertIn("updated_search_heuristics", report)
        self.assertIn("directives", report)


if __name__ == "__main__":
    unittest.main()
