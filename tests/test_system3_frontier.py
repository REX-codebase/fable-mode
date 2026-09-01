"""Comprehensive Unit & Verification Test Suite for Frontier System 3 Transcendence Engine.

Tests:
1. Poincaré Hyperbolic Manifold (Metric tensor, Möbius addition, Exp/Log maps, Tree embeddings, Distortion)
2. Kripke Modal Model Checker (CTL* temporal operators: AG, EF, AF, AX, EX, EG, EU, AU; Box/Diamond; Witness & Counterexample traces)
3. Friston Active Inference Engine (Variational Free Energy F = Complexity - Accuracy, Expected Free Energy G, Policy Selection)
4. Gödelian Proof Oracle (Curry-Howard Isomorphism, Constructive Type Checking, Tactic Synthesis, Incompleteness / Paradox boundaries)
"""

from __future__ import annotations

import unittest
import math
import json

from fable_v2.system3 import (
    # Hyperbolic
    PoincareBall,
    HyperbolicPoint,
    HyperbolicTreeEmbedder,
    TreeEmbeddingNode,
    TreeEmbeddingResult,
    HyperbolicGeometryError,
    # Kripke
    KripkeStructure,
    KripkeWorld,
    KripkeModelChecker,
    ModelCheckResult,
    CTLOperator,
    FormulaNode,
    FormulaParser,
    # Free Energy
    ActiveInferenceEngine,
    GenerativeModel,
    Policy,
    PolicyEvaluation,
    FreeEnergyReport,
    create_default_architecture_pomdp,
    # Oracle
    ProofOracle,
    CurryHowardVerifier,
    UndecidabilityDetector,
    TacticsEngine,
    FormalProofResult,
    ProofStatus,
    Type,
    Term,
    Prop,
    Unit,
    Void,
    Implies,
    And,
    Or,
    Not,
    Eq,
    Var,
    Lam,
    App,
    Pair,
    Fst,
    Snd,
    Inl,
    Inr,
    Case,
    Refl,
    Abort,
)


class TestPoincareHyperbolicManifold(unittest.TestCase):
    """Unit tests for Poincaré Ball hyperbolic geometry and tree embeddings."""

    def setUp(self):
        self.manifold = PoincareBall(dimension=2, curvature=1.0)

    def test_point_creation_and_clamping(self):
        p1 = HyperbolicPoint(coords=(0.2, 0.3), curvature=1.0)
        self.assertEqual(p1.dimension, 2)
        self.assertAlmostEqual(p1.norm, math.sqrt(0.04 + 0.09), places=5)

        # Out-of-bounds point should be automatically clamped inside unit disk
        p_out = HyperbolicPoint(coords=(1.5, 0.0), curvature=1.0)
        self.assertLess(p_out.norm, 1.0)

        # Invalid curvature should raise
        with self.assertRaises(ValueError):
            HyperbolicPoint(coords=(0.1, 0.1), curvature=-1.0)

    def test_conformal_factor_and_metric_tensor(self):
        origin = (0.0, 0.0)
        lam_0 = self.manifold.conformal_factor(origin)
        self.assertAlmostEqual(lam_0, 2.0, places=5)

        tensor_0 = self.manifold.metric_tensor(origin)
        self.assertEqual(tensor_0, [[4.0, 0.0], [0.0, 4.0]])

        # Near boundary, conformal factor grows to infinity
        p_near = (0.9, 0.0)
        lam_near = self.manifold.conformal_factor(p_near)
        self.assertAlmostEqual(lam_near, 2.0 / (1.0 - 0.81), places=4)
        self.assertGreater(lam_near, 10.0)

    def test_mobius_addition_algebra(self):
        x = (0.3, 0.2)
        y = (-0.1, 0.4)
        zero = (0.0, 0.0)

        # Identity: x (+) 0 = x
        x_plus_zero = self.manifold.mobius_add(x, zero)
        self.assertAlmostEqual(x_plus_zero[0], x[0], places=5)
        self.assertAlmostEqual(x_plus_zero[1], x[1], places=5)

        # Inverse: x (+) (-x) = 0
        neg_x = (-x[0], -x[1])
        x_plus_neg_x = self.manifold.mobius_add(x, neg_x)
        self.assertAlmostEqual(x_plus_neg_x[0], 0.0, places=5)
        self.assertAlmostEqual(x_plus_neg_x[1], 0.0, places=5)

        # Subtraction: x (-) x = 0
        x_sub_x = self.manifold.mobius_sub(x, x)
        self.assertAlmostEqual(x_sub_x[0], 0.0, places=5)
        self.assertAlmostEqual(x_sub_x[1], 0.0, places=5)

    def test_distance_and_geodesic_properties(self):
        x = (0.0, 0.0)
        y = (0.5, 0.0)
        d_xy = self.manifold.distance(x, y)
        # Distance from origin in Poincare disk: 2 * artanh(||y||) = 2 * artanh(0.5) = ln(3) ~ 1.0986
        expected_d = 2.0 * math.atanh(0.5)
        self.assertAlmostEqual(d_xy, expected_d, places=5)

        # Symmetry: d(x, y) == d(y, x)
        d_yx = self.manifold.distance(y, x)
        self.assertAlmostEqual(d_xy, d_yx, places=5)

        # Triangle Inequality: d(x, z) <= d(x, y) + d(y, z)
        z = (0.2, 0.6)
        d_xz = self.manifold.distance(x, z)
        d_yz = self.manifold.distance(y, z)
        self.assertLessEqual(d_xz, d_xy + d_yz + 1e-6)

    def test_exp_and_log_maps_roundtrip(self):
        x = (0.2, -0.1)
        v = (0.3, 0.4)

        # Exponential map maps tangent vector to manifold
        y = self.manifold.exp_map(x, v)
        self.assertLess(math.sqrt(y[0]**2 + y[1]**2), 1.0)

        # Logarithmic map recovers original tangent vector
        v_recovered = self.manifold.log_map(x, y)
        self.assertAlmostEqual(v_recovered[0], v[0], places=4)
        self.assertAlmostEqual(v_recovered[1], v[1], places=4)

    def test_geodesic_interpolation(self):
        x = (-0.4, 0.2)
        y = (0.3, -0.5)

        # Midpoint gamma(0.5)
        mid = self.manifold.geodesic_interpolate(x, y, 0.5)
        d_total = self.manifold.distance(x, y)
        d_x_mid = self.manifold.distance(x, mid)
        d_mid_y = self.manifold.distance(mid, y)

        self.assertAlmostEqual(d_x_mid, d_total / 2.0, places=4)
        self.assertAlmostEqual(d_mid_y, d_total / 2.0, places=4)

    def test_hyperbolic_tree_embedder(self):
        embedder = HyperbolicTreeEmbedder(dimension=2, curvature=1.0, base_step_distance=1.0)

        # Construct tree hierarchy
        tree = {
            "root": ["arch", "broker", "verifier"],
            "arch": ["causal", "dialectical"],
            "broker": ["policy", "runtime"],
            "verifier": ["function", "composite"],
        }
        labels = {"root": "FableMode", "arch": "System3", "broker": "Broker", "verifier": "Verifiers"}

        res = embedder.embed_hierarchy(tree, root_id="root", node_labels=labels)
        self.assertEqual(res.total_nodes, 10)
        self.assertEqual(res.tree_depth, 2)
        self.assertEqual(res.root_id, "root")

        # Root at origin
        self.assertEqual(res.nodes["root"].coords, (0.0, 0.0))

        # Children are strictly within Poincaré open disk
        for nid, node in res.nodes.items():
            norm = math.sqrt(sum(c * c for c in node.coords))
            self.assertLess(norm, 1.0)

        # Stress and distortion should be reasonably bounded
        self.assertGreaterEqual(res.average_distortion, 0.0)
        self.assertGreaterEqual(res.hierarchical_capacity_ratio, 1.0)

        # Serialization roundtrip
        d = res.to_dict()
        restored = TreeEmbeddingResult.from_dict(d)
        self.assertEqual(restored.total_nodes, res.total_nodes)
        self.assertEqual(restored.root_id, res.root_id)


class TestKripkeModalModelChecker(unittest.TestCase):
    """Unit tests for Kripke Structure, Multi-World Semantics, and CTL Model Checking."""

    def setUp(self):
        self.ks = KripkeStructure(name="System3SafetyProtocol")
        # Worlds
        self.ks.add_world("s0_init", ["ready", "safe"], is_initial=True)
        self.ks.add_world("s1_deliberating", ["safe", "locked"])
        self.ks.add_world("s2_unlocked", ["safe", "can_execute"])
        self.ks.add_world("s3_done", ["safe", "complete"])
        self.ks.add_world("s_error", ["error"])

        # Transitions (Safe path: s0 -> s1 -> s2 -> s3 -> s3; Error branch: s1 -> s_error)
        self.ks.add_transition("s0_init", "s1_deliberating")
        self.ks.add_transition("s1_deliberating", "s2_unlocked")
        self.ks.add_transition("s2_unlocked", "s3_done")
        self.ks.add_transition("s3_done", "s3_done") # Self loop
        self.ks.add_transition("s_error", "s_error")

        self.checker = KripkeModelChecker(self.ks)

    def test_formula_parser(self):
        f1 = FormulaParser.parse("AG(safe)")
        self.assertEqual(f1.op, CTLOperator.AG)
        self.assertEqual(f1.left.op, CTLOperator.ATOM)
        self.assertEqual(f1.left.name, "safe")

        f2 = FormulaParser.parse("and(ready, safe)")
        self.assertEqual(f2.op, CTLOperator.AND)
        self.assertEqual(f2.left.name, "ready")
        self.assertEqual(f2.right.name, "safe")

        f3 = FormulaParser.parse("E[safe U complete]")
        self.assertEqual(f3.op, CTLOperator.EU)
        self.assertEqual(f3.left.name, "safe")
        self.assertEqual(f3.right.name, "complete")

        f4 = FormulaParser.parse("box(safe)")
        self.assertEqual(f4.op, CTLOperator.BOX)

    def test_modal_operators_box_and_diamond(self):
        # In s0_init, all successors (s1_deliberating) have 'safe' -> Box(safe) holds
        res_box = self.checker.check("box(safe)", initial_world="s0_init")
        self.assertTrue(res_box.is_satisfied)

        # In s0_init, diamond(locked) holds because s1_deliberating has 'locked'
        res_dia = self.checker.check("diamond(locked)", initial_world="s0_init")
        self.assertTrue(res_dia.is_satisfied)

    def test_ctl_temporal_invariants(self):
        # 1. AG(safe) from s0_init should be TRUE (s_error is unreachable from s0_init)
        res_ag = self.checker.check("AG(safe)", initial_world="s0_init")
        self.assertTrue(res_ag.is_satisfied)

        # 2. EF(complete) from s0_init should be TRUE (s0 -> s1 -> s2 -> s3)
        res_ef = self.checker.check("EF(complete)", initial_world="s0_init")
        self.assertTrue(res_ef.is_satisfied)
        self.assertIsNotNone(res_ef.witness_path)
        self.assertEqual(res_ef.witness_path[0], "s0_init")
        self.assertEqual(res_ef.witness_path[-1], "s3_done")

        # 3. AF(complete) from s0_init should be TRUE
        res_af = self.checker.check("AF(complete)", initial_world="s0_init")
        self.assertTrue(res_af.is_satisfied)

        # 4. AX(locked) from s0_init should be TRUE (next state is s1_deliberating)
        res_ax = self.checker.check("AX(locked)", initial_world="s0_init")
        self.assertTrue(res_ax.is_satisfied)

        # 5. E[safe U complete] from s0_init should be TRUE
        res_eu = self.checker.check("E[safe U complete]", initial_world="s0_init")
        self.assertTrue(res_eu.is_satisfied)

    def test_violation_and_counterexample_trace(self):
        # Add transition from s1_deliberating to s_error
        self.ks.add_transition("s1_deliberating", "s_error")

        # Now AG(safe) fails because s_error is reachable
        res_ag_fail = self.checker.check("AG(safe)", initial_world="s0_init")
        self.assertFalse(res_ag_fail.is_satisfied)
        self.assertIsNotNone(res_ag_fail.counterexample_path)
        self.assertEqual(res_ag_fail.counterexample_path, ["s0_init", "s1_deliberating", "s_error"])

        # Serialization
        d = res_ag_fail.to_dict()
        restored = ModelCheckResult.from_dict(d)
        self.assertFalse(restored.is_satisfied)
        self.assertEqual(restored.counterexample_path, ["s0_init", "s1_deliberating", "s_error"])


class TestFristonActiveInferenceEngine(unittest.TestCase):
    """Unit tests for Karl Friston's Active Inference & Variational Free Energy."""

    def setUp(self):
        self.model = create_default_architecture_pomdp()
        self.engine = ActiveInferenceEngine(generative_model=self.model, policy_precision_gamma=16.0)

    def test_model_initialization_and_normalization(self):
        self.assertEqual(len(self.model.states), 4)
        self.assertEqual(len(self.model.observations), 4)
        self.assertEqual(len(self.model.actions), 4)

        # Column sums of A matrix must be 1.0
        for s_idx in range(len(self.model.states)):
            col_sum = sum(self.model.a_matrix[o_idx][s_idx] for o_idx in range(len(self.model.observations)))
            self.assertAlmostEqual(col_sum, 1.0, places=5)

    def test_perception_free_energy_calculation(self):
        # Ingest clean high throughput observation
        f_val, comp_kl, acc_ll = self.engine.update_beliefs("HIGH_THROUGHPUT_CLEAN")

        # Variational Free Energy F = Complexity - Accuracy
        self.assertAlmostEqual(f_val, comp_kl - acc_ll, places=5)

        # Belief for OPTIMAL_DECOUPLED should dominate
        opt_idx = self.model.states.index("OPTIMAL_DECOUPLED")
        self.assertGreater(self.engine.current_beliefs[opt_idx], 0.70)

    def test_action_selection_and_policy_ranking(self):
        # Inject lock contention warning observation
        report = self.engine.select_action(
            observation="LOCK_CONTENTION_WARN",
            candidate_policies=[
                Policy(policy_id="p_shard", actions=["SHARD_WORKERS"]),
                Policy(policy_id="p_refactor", actions=["REFACTOR_MUTEX"]),
                Policy(policy_id="p_cas", actions=["APPLY_CAS_ISOLATION"]),
                Policy(policy_id="p_benchmark", actions=["RUN_BENCHMARK"]),
            ]
        )

        self.assertEqual(report.current_observation, "LOCK_CONTENTION_WARN")
        self.assertEqual(len(report.evaluated_policies), 4)

        # Expected Free Energy should favor corrective action
        self.assertIn(report.selected_action, ["SHARD_WORKERS", "REFACTOR_MUTEX", "APPLY_CAS_ISOLATION"])
        self.assertIsNotNone(report.selected_policy)
        self.assertTrue(report.selected_policy.is_optimal)

        # Probabilities sum to 1.0
        prob_sum = sum(p.probability for p in report.evaluated_policies)
        self.assertAlmostEqual(prob_sum, 1.0, places=5)

        # Serialization
        d = report.to_dict()
        restored = FreeEnergyReport.from_dict(d)
        self.assertEqual(restored.current_observation, report.current_observation)
        self.assertEqual(restored.selected_action, report.selected_action)


class TestGodelianProofOracle(unittest.TestCase):
    """Unit tests for Gödelian Proof Oracle and Curry-Howard Constructive Type Checker."""

    def setUp(self):
        self.oracle = ProofOracle(max_search_depth=6)

    def test_curry_howard_tautologies(self):
        A = Prop("A")
        B = Prop("B")

        # 1. Identity / Modus Ponens Base: A -> A
        # Proof: \x: A. x
        proof_id = Lam("x", A, Var("x"))
        self.assertTrue(CurryHowardVerifier.check_type(proof_id, Implies(A, A)))

        # 2. Conjunction Commutativity: (A /\ B) -> (B /\ A)
        # Proof: \p: (A /\ B). <snd p, fst p>
        p_type = And(A, B)
        proof_comm = Lam("p", p_type, Pair(Snd(Var("p")), Fst(Var("p"))))
        self.assertTrue(CurryHowardVerifier.check_type(proof_comm, Implies(p_type, And(B, A))))

        # 3. Disjunction Commutativity: (A \/ B) -> (B \/ A)
        # Proof: \s: (A \/ B). case s of inl a => inr a | inr b => inl b
        s_type = Or(A, B)
        target_sum = Or(B, A)
        proof_or_comm = Lam(
            "s", s_type,
            Case(
                Var("s"),
                "a", Inr(Var("a"), target_sum),
                "b", Inl(Var("b"), target_sum),
            )
        )
        self.assertTrue(CurryHowardVerifier.check_type(proof_or_comm, Implies(s_type, target_sum)))

    def test_automatic_tactic_synthesis(self):
        # Auto-prove A -> (B -> A)
        A = Prop("A")
        B = Prop("B")
        goal = Implies(A, Implies(B, A))

        res = self.oracle.verify_proposition(goal)
        self.assertEqual(res.status, ProofStatus.DECIDABLE_PROVED)
        self.assertTrue(res.is_sound)
        self.assertIsNotNone(res.proof_term)

        # Auto-prove equality: safe == safe
        eq_goal = Eq("safe", "safe")
        res_eq = self.oracle.verify_proposition(eq_goal)
        self.assertEqual(res_eq.status, ProofStatus.DECIDABLE_PROVED)
        self.assertTrue(res_eq.is_sound)

    def test_refutation_of_contradictory_claims(self):
        A = Prop("A")
        # Context has A and ~A (A -> Void)
        # Claim: Void -> goal should succeed or refuting A
        ctx = {"h1": A, "h2": Not(A)}
        res = self.oracle.verify_proposition(claim="P", context=ctx)
        self.assertEqual(res.status, ProofStatus.DECIDABLE_PROVED) # Proved via ex falso quodlibet from context contradiction

    def test_godelian_undecidability_and_paradox_detection(self):
        # 1. Liar Paradox claim
        res_liar = self.oracle.verify_proposition("Liar_Self_Negation_Paradox")
        self.assertEqual(res_liar.status, ProofStatus.INDEPENDENT_UNDECIDABLE)
        self.assertFalse(res_liar.is_sound)
        self.assertIsNotNone(res_liar.undecidability_diagnostics)

        # 2. Gödel sentence claim
        res_godel = self.oracle.verify_proposition("Godel_Unprovable_Sentence")
        self.assertEqual(res_godel.status, ProofStatus.INDEPENDENT_UNDECIDABLE)
        self.assertIn("GODELIAN", res_godel.undecidability_diagnostics.get("boundary_type", ""))

        # 3. Halting problem reduction
        res_halt = self.oracle.verify_proposition("Turing_Diagonal_Halts_Predicate")
        self.assertEqual(res_halt.status, ProofStatus.INDEPENDENT_UNDECIDABLE)

        # Serialization
        d = res_godel.to_dict()
        restored = FormalProofResult.from_dict(d)
        self.assertEqual(restored.status, ProofStatus.INDEPENDENT_UNDECIDABLE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
