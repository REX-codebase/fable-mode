"""Focused adversarial tests for the first intelligent-verifier slice."""

import math
import unittest

from fable_v2 import Candidate, TaskSpec
from fable_v2.protocol import VerificationStatus, canonical_hash
from fable_v2.verifiers import (
    Adjudication,
    Claim,
    ClaimGraph,
    Counterexample,
    CounterexampleStore,
    FunctionVerifier,
    MetamorphicVerifier,
    MutationVerifier,
    RiskLevel,
    ThreeValuedAdjudicator,
    VerificationDecision,
    VerifierPlanner,
    VerifierPortfolio,
)


class IntelligentVerifierTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskSpec(
            "intelligent", "produce a result",
            constraints=("do not delete data",),
            definition_of_done=("tests pass",),
        )
        self.candidate = Candidate("candidate", "session", "test", {"result": 1})
        self.graph = ClaimGraph.from_task(self.task, self.candidate)

    def _result(self, name, status, claims, *, evidence=("e",), provenance=("p",), independent=False,
                counterexamples=()):
        return FunctionVerifier(
            name,
            lambda _: VerificationDecision(status, evidence_ids=evidence,
                                           claim_ids=claims, provenance_ids=provenance,
                                           counterexample_ids=counterexamples),
            claim_ids=claims, provenance_ids=provenance, independent=independent,
        ).verify(self.candidate)

    def test_all_pass_does_not_overclaim_unmentioned_claims(self):
        result = self._result("one-claim", VerificationStatus.PASS, (self.graph.claims[0].claim_id,))
        adjudication = ThreeValuedAdjudicator(require_independent=False).adjudicate(
            self.graph, (result,))
        self.assertFalse(adjudication.finalizable)
        self.assertTrue(adjudication.blocking_claim_ids)
        self.assertIn("UNKNOWN", " ".join(adjudication.reasons))

    def test_critical_unknown_blocks(self):
        critical = Claim("critical", "do not lose data", "satisfies(do not lose data)",
                          RiskLevel.CRITICAL, "candidate:candidate", "observe data loss")
        graph = ClaimGraph((critical,))
        result = self._result("uncertain", VerificationStatus.UNKNOWN, ("critical",))
        adjudication = ThreeValuedAdjudicator(require_independent=False).adjudicate(graph, (result,))
        self.assertEqual(adjudication.status, VerificationStatus.UNKNOWN)
        self.assertFalse(adjudication.can_finalize)

    def test_allow_noncritical_unknown_never_covers_uncovered_claim(self):
        adjudication = ThreeValuedAdjudicator(
            require_independent=False, allow_noncritical_unknown=True,
        ).adjudicate(self.graph, ())
        self.assertNotEqual(adjudication.status, VerificationStatus.PASS)
        self.assertFalse(adjudication.finalizable)
        self.assertTrue(adjudication.blocking_claim_ids)

    def test_standalone_registry_identity_and_content_hash_are_verified(self):
        task = TaskSpec("registry", "check", definition_of_done=("done",))
        candidate = Candidate("candidate", "session", "test", {"result": 1})
        graph = ClaimGraph.from_task(task, candidate)
        receipt = __import__("fable_v2").ToolReceipt.from_result(
            receipt_id="receipt", session_id="session", capability="check",
            tool_name="checker", tool_input="x", tool_output={"ok": True}, success=True,
        )
        evidence = __import__("fable_v2").Evidence.from_receipt(
            receipt, evidence_id="evidence", claim="done", kind="check", source="checker",
        )
        result = self._result("registry", VerificationStatus.PASS, graph.claim_ids,
                              evidence=("evidence",), provenance=("evidence",))
        adjudicator = ThreeValuedAdjudicator(require_independent=False)
        valid = adjudicator.adjudicate(
            graph, (result,), evidence_registry={"evidence": evidence},
            receipt_registry={"receipt": receipt},
        )
        self.assertEqual(valid.status, VerificationStatus.PASS)
        alias = evidence.to_dict(); alias["evidence_id"] = "other"
        rejected = adjudicator.adjudicate(
            graph, (result,), evidence_registry={"evidence": alias},
            receipt_registry={"receipt": receipt},
        )
        self.assertEqual(rejected.status, VerificationStatus.FAIL)
        altered = evidence.to_dict(); altered["content"] = {"ok": False}
        rejected = adjudicator.adjudicate(
            graph, (result,), evidence_registry={"evidence": altered},
            receipt_registry={"receipt": receipt},
        )
        self.assertEqual(rejected.status, VerificationStatus.FAIL)

    def test_counterexample_is_stored_and_propagated(self):
        ce = Counterexample("ce-1", (self.graph.claims[0].claim_id,), {"bad": True},
                            "bad output", verifier="property", evidence_ids=("e",), provenance_ids=("p",))
        store = CounterexampleStore()
        store.add(ce)
        failure = self._result("property", VerificationStatus.FAIL,
                               (self.graph.claims[0].claim_id,), counterexamples=("ce-1",))
        adjudication = ThreeValuedAdjudicator(require_independent=False).adjudicate(
            self.graph, (failure,), store)
        self.assertEqual(adjudication.counterexamples[0].counterexample_id, "ce-1")
        self.assertFalse(adjudication.finalizable)

    def test_claim_decomposition_is_atomic_and_falsifiable(self):
        self.assertGreaterEqual(len(self.graph.claims), 3)
        for claim in self.graph.claims:
            self.assertTrue(claim.predicate)
            self.assertTrue(claim.scope)
            self.assertTrue(claim.falsification)
        self.assertTrue(any(c.source == "constraints" for c in self.graph.claims))

    def test_planner_prefers_high_risk_information_gain_per_cost(self):
        high = next(claim for claim in self.graph.claims if claim.source == "constraints")
        low = next(claim for claim in self.graph.claims if claim.source == "objective")
        expensive_high = FunctionVerifier(
            "high-risk", lambda _: (False, ("not run",), None), claim_ids=(high.claim_id,),
            uncertainty=.9, expected_information_gain=1.0, cost=1.0,
        )
        cheap_low = FunctionVerifier(
            "low-risk", lambda _: (True, ("ok",), 1.0), claim_ids=(low.claim_id,),
            uncertainty=.1, expected_information_gain=.2, cost=2.0,
        )
        plan = VerifierPlanner().plan(self.graph, (expensive_high, cheap_low))
        self.assertEqual(plan.checks[0].verifier.name, "high-risk")
        self.assertIn(high.claim_id, plan.checks[0].covered_claim_ids)

    def test_pass_requires_evidence_and_provenance(self):
        result = self._result("unproven", VerificationStatus.PASS, self.graph.claim_ids,
                              evidence=(), provenance=())
        adjudication = ThreeValuedAdjudicator(require_independent=False).adjudicate(
            self.graph, (result,))
        self.assertFalse(adjudication.finalizable)
        self.assertTrue(any("provenance" in reason for reason in adjudication.reasons))

    def test_independent_verifiers_need_disjoint_provenance(self):
        claims = self.graph.claim_ids
        first = self._result("deterministic", VerificationStatus.PASS, claims,
                             provenance=("producer-a",))
        same_producer = self._result("independent", VerificationStatus.PASS, claims,
                                     provenance=("producer-a",), independent=True)
        blocked = ThreeValuedAdjudicator().adjudicate(self.graph, (first, same_producer))
        self.assertFalse(blocked.finalizable)
        distinct = self._result("independent-2", VerificationStatus.PASS, claims,
                                provenance=("producer-b",), independent=True)
        allowed = ThreeValuedAdjudicator().adjudicate(self.graph, (first, distinct))
        self.assertTrue(allowed.finalizable)

    def test_metadata_cannot_downgrade_intrinsic_critical_risk(self):
        task = TaskSpec("risk", "delete financial records", definition_of_done=("done",),
                        metadata={"risk": "LOW"})
        graph = ClaimGraph.from_task(task)
        self.assertEqual(graph.claims[0].risk_level, RiskLevel.CRITICAL)

    def test_intrinsic_destructive_and_security_phrases_are_critical(self):
        for phrase in ("erase backups", "revoke credentials", "disable the firewall",
                       "exfiltrate private data", "run arbitrary code"):
            task = TaskSpec("risk-" + phrase.split()[0], phrase,
                            definition_of_done=("done",), metadata={"risk": "LOW"})
            self.assertEqual(ClaimGraph.from_task(task).claims[0].risk_level, RiskLevel.CRITICAL)

    def test_counterexample_rehash_catches_base_class_mutator_bypass(self):
        counterexample = Counterexample("bypass", ("claim",), {"nested": [1]}, "bad")
        dict.__setitem__(counterexample.observation, "nested", [2])
        with self.assertRaises(ValueError):
            CounterexampleStore((counterexample,))

    def test_compound_decomposition_rejects_missing_clause(self):
        task = TaskSpec("compound", "first and", definition_of_done=("done",))
        with self.assertRaises(ValueError):
            ClaimGraph.from_task(task)

    def test_claim_dependencies_are_known_and_acyclic(self):
        first = Claim("first", "first", "p", RiskLevel.LOW, "s", "f")
        dependent = Claim("dependent", "dependent", "p", RiskLevel.LOW, "s", "f",
                          dependencies=("first",))
        graph = ClaimGraph((dependent, first))
        self.assertEqual(graph.edges, (("first", "dependent"),))
        with self.assertRaises(ValueError):
            ClaimGraph((dependent,))
        with self.assertRaises(ValueError):
            ClaimGraph((Claim("a", "a", "p", RiskLevel.LOW, "s", "f",
                              dependencies=("b",)),
                        Claim("b", "b", "p", RiskLevel.LOW, "s", "f",
                              dependencies=("a",))))

    def test_planner_rejects_nonfinite_metrics_and_honors_cost_floor(self):
        with self.assertRaises(ValueError):
            FunctionVerifier("nan", lambda _: True, uncertainty=math.nan)
        with self.assertRaises(ValueError):
            FunctionVerifier("too-much", lambda _: True, information_gain=2)
        verifier = FunctionVerifier("cheap", lambda _: True, cost=.1,
                                    claim_ids=(self.graph.claims[0].claim_id,))
        low = VerifierPlanner(minimum_cost=.01)._score(verifier, self.graph, (self.graph.claims[0],))
        high = VerifierPlanner(minimum_cost=1)._score(verifier, self.graph, (self.graph.claims[0],))
        self.assertGreater(low, high)

    def test_hooks_require_changed_inputs(self):
        mutation = MutationVerifier("mutation", mutate=lambda _: ({"result": 1},),
                                     detect=lambda _: True,
                                     claim_ids=(self.graph.claims[0].claim_id,))
        self.assertEqual(mutation.verify(self.candidate).status, VerificationStatus.UNKNOWN)
        transformed = MetamorphicVerifier("meta", transform=lambda c: c.artifact,
                                           compare=lambda *_: True,
                                           claim_ids=(self.graph.claims[0].claim_id,))
        self.assertEqual(transformed.verify(self.candidate).status, VerificationStatus.UNKNOWN)

    def test_counterexample_observation_is_deeply_frozen_and_hashed(self):
        observation = {"nested": {"items": [1]}}
        counterexample = Counterexample("frozen", ("claim",), observation, "bad")
        observation["nested"]["items"].append(2)
        self.assertEqual(counterexample.observation_hash, canonical_hash(counterexample.observation))
        with self.assertRaises((AttributeError, TypeError)):
            counterexample.observation["nested"]["items"].append(3)

    def test_replayed_verifier_record_counts_once(self):
        result = self._result("independent", VerificationStatus.PASS, self.graph.claim_ids,
                              provenance=("producer",), independent=True)
        adjudication = ThreeValuedAdjudicator(minimum_independent_verifiers=2).adjudicate(
            self.graph, (result, result))
        self.assertFalse(adjudication.finalizable)
        self.assertEqual(len(adjudication.independent_verifier_ids), 1)

    def test_legacy_boolean_verifier_shape_remains_supported(self):
        result = FunctionVerifier("legacy", lambda _: (True, ("ok",), 1.0)).verify(self.candidate)
        self.assertEqual(result.status, VerificationStatus.PASS)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
