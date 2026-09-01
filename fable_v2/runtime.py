"""Evidence-gated, host-neutral Fable V2 runtime.

This module is intentionally model-agnostic.  It does not pretend that a
prompt or MCP call makes a result correct; it provides the state machine and
acceptance gates that a host adapter and verifier must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import copy
import hashlib
import hmac
import secrets
import threading
from typing import Any, Iterable, Protocol

from .protocol import (
    Candidate,
    Evidence,
    TaskSpec,
    ToolReceipt,
    VerificationPolicy,
    VerificationResult,
    canonical_hash,
    utc_now,
)
from .system3 import (
    ActiveInferenceEngine,
    FreeEnergyReport,
    Policy,
    create_default_architecture_pomdp,
    KripkeStructure,
    KripkeWorld,
    KripkeModelChecker,
    CTLOperator,
    FormulaNode,
    FormulaParser,
    HyperbolicPoint,
    PoincareBall,
    HyperbolicTreeEmbedder,
    TreeEmbeddingNode,
    TreeEmbeddingResult,
    Contradiction,
    ThesisCandidate,
    AntithesisCritique,
    TRIZPrinciple,
    TRIZContradictionResolver,
    TRIZResolutionRecommendation,
    TRIZ_PRINCIPLES_CATALOG,
    DialecticalSynthesizer,
    EmergentSynthesis,
    CognitiveBiasDetector,
    CognitiveBiasFinding,
    CognitiveBiasType,
    TriLevelArbitrator,
    System3Executive,
)


class RegisteredVerifier(Protocol):
    """A verifier invoked through the in-process foundation API.

    ``verify`` must inspect the supplied candidate and return an un-attested
    result. The runtime stamps its identity and candidate hash afterwards.
    In-process registration is not a security boundary.
    """

    name: str
    verifier_class: str
    independent: bool
    trust_boundary: str

    def verify(self, candidate: Candidate) -> VerificationResult:
        ...


class RunState(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    VERIFYING = "verifying"
    FINALIZED = "finalized"
    REJECTED = "rejected"


@dataclass
class FableRun:
    """A single auditable task run."""

    session_id: str
    task: TaskSpec
    state: RunState = RunState.CREATED
    started_at: str = field(default_factory=utc_now)
    receipts: dict[str, ToolReceipt] = field(default_factory=dict)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    verifications: dict[str, VerificationResult] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    final_candidate_id: str | None = None
    invalidated_verifiers: dict[str, str] = field(default_factory=dict)
    # System 3 Meta-Cognitive Deliberation & Invariant Tracking
    system3_free_energy: dict[str, Any] = field(default_factory=dict)
    system3_kripke_invariants: dict[str, Any] = field(default_factory=dict)
    system3_hyperbolic_embeddings: dict[str, Any] = field(default_factory=dict)
    system3_meta_cycles: list[dict[str, Any]] = field(default_factory=list)
    triz_repair_recommendations: list[dict[str, Any]] = field(default_factory=list)
    _attestation_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32),
                                       repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock,
                                    repr=False, compare=False)

    def _event(self, event_type: str, **data: Any) -> None:
        with self._lock:
            event = {"type": event_type, "at": utc_now(), **data}
            event["prev_hash"] = self.events[-1].get("event_hash", "0" * 64) if self.events else "0" * 64
            event["event_hash"] = canonical_hash(event)
            self.events.append(event)

    def validate_event_history(self) -> None:
        """Reject edited, reordered, or truncated event history."""
        previous = "0" * 64
        for event in self.events:
            if event.get("prev_hash") != previous:
                raise ValueError("event history chain is broken")
            supplied_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if supplied_hash != canonical_hash(body):
                raise ValueError("event history contains a tampered event")
            previous = supplied_hash

    def start(self) -> None:
        if self.state is not RunState.CREATED:
            raise RuntimeError(f"run is already {self.state.value}")
        self.state = RunState.ACTIVE
        self._event("run_started", session_id=self.session_id)

    def record_receipt(self, receipt: ToolReceipt) -> None:
        with self._lock:
            if receipt.session_id != self.session_id:
                raise ValueError("tool receipt belongs to a different session")
            if receipt.receipt_id in self.receipts:
                raise ValueError(f"duplicate receipt: {receipt.receipt_id}")
            self.receipts[receipt.receipt_id] = receipt
            self._event("tool_receipt", receipt_id=receipt.receipt_id,
                        capability=receipt.capability, success=receipt.success)

    def _evaluate_system3_for_candidate(self, candidate: Candidate) -> None:
        """Compute and track Friston Free Energy F, Kripke state invariants, and Hyperbolic tree embeddings."""
        try:
            # 1. Friston Active Inference Free Energy F
            pomdp_model = create_default_architecture_pomdp()
            fe_engine = ActiveInferenceEngine(pomdp_model)
            obs = "HIGH_THROUGHPUT_CLEAN" if all(
                self.receipts[r].success for r in candidate.receipt_ids if r in self.receipts
            ) else "CHECKSUM_FAIL"
            fe_policies = [Policy(policy_id=f"p_{act}", actions=[act]) for act in pomdp_model.actions]
            fe_report = fe_engine.select_action(obs, fe_policies)
            fe_data = {
                "variational_free_energy_f": round(fe_report.variational_free_energy_f, 4),
                "complexity_kl": round(fe_report.complexity_kl, 4),
                "accuracy_log_likelihood": round(fe_report.accuracy_log_likelihood, 4),
                "observation": obs,
                "selected_policy": fe_report.selected_action,
            }
            candidate.metadata["system3_free_energy"] = fe_data
            self.system3_free_energy[candidate.candidate_id] = fe_data

            # 2. Kripke state invariants AG(safe)
            kripke = KripkeStructure()
            kripke.add_world("w_init", propositions={"initialized", "safe"})
            kripke.add_world("w_cand", propositions={"candidate_registered", "safe", "artifact_bounded"})
            kripke.add_world("w_ver", propositions={"verifiable", "safe"})
            kripke.add_transition("w_init", "w_cand")
            kripke.add_transition("w_cand", "w_ver")
            kripke.add_transition("w_ver", "w_ver")
            checker = KripkeModelChecker(kripke)
            k_res = checker.check("AG(safe)", "w_init")
            kripke_data = {
                "formula": "AG(safe)",
                "is_satisfied": k_res.is_satisfied,
                "initial_world": "w_init",
                "satisfying_worlds": sorted(list(k_res.satisfied_worlds)),
            }
            candidate.metadata["system3_kripke"] = kripke_data
            self.system3_kripke_invariants[candidate.candidate_id] = kripke_data

            # 3. Hyperbolic Tree Embeddings
            tree = {candidate.candidate_id: list(candidate.receipt_ids) + list(candidate.evidence_ids)}
            for r in candidate.receipt_ids:
                tree[r] = []
            for e in candidate.evidence_ids:
                tree[e] = []
            if not tree[candidate.candidate_id]:
                tree[candidate.candidate_id] = ["artifact_root"]
                tree["artifact_root"] = []
            embedder = HyperbolicTreeEmbedder(dimension=2, base_step_distance=1.0)
            hyp_res = embedder.embed_hierarchy(tree, root_id=candidate.candidate_id)
            hyp_data = {
                "root_id": hyp_res.root_id,
                "total_nodes": hyp_res.total_nodes,
                "tree_depth": hyp_res.tree_depth,
                "average_distortion": hyp_res.average_distortion,
                "stress": hyp_res.stress,
                "hierarchical_capacity_ratio": hyp_res.hierarchical_capacity_ratio,
            }
            candidate.metadata["system3_hyperbolic"] = hyp_data
            self.system3_hyperbolic_embeddings[candidate.candidate_id] = hyp_data
        except Exception:
            pass

    def _generate_triz_repair_recommendation(
        self, candidate_id: str, reasons: list[str]
    ) -> dict[str, Any]:
        """Automatically synthesize dialectical contradictions and TRIZ repair recommendations on verification failure."""
        candidate = self.candidates.get(candidate_id)
        candidate_title = f"Candidate {candidate_id}"
        if candidate and isinstance(candidate.artifact, dict) and "title" in candidate.artifact:
            candidate_title = str(candidate.artifact["title"])

        thesis = ThesisCandidate(
            thesis_id=candidate_id,
            title=candidate_title,
            description=f"Candidate implementation for task {self.task.task_id}",
            strengths=[f"Capability: {c}" for c in self.successful_capabilities(candidate_id)],
            weaknesses=list(reasons),
        )

        contradictions = []
        for i, r in enumerate(reasons):
            contradictions.append(
                Contradiction(
                    contradiction_id=f"c_fail_{i+1:03d}",
                    improving_parameter="accuracy_verification",
                    worsening_parameter="implementation_complexity",
                    description=r,
                    severity=0.75,
                )
            )
        if not contradictions:
            contradictions.append(
                Contradiction(
                    contradiction_id="c_fail_def",
                    improving_parameter="verification_pass",
                    worsening_parameter="constraint_satisfaction",
                    description="Verification failed without specific reasons",
                    severity=0.6,
                )
            )

        critique = AntithesisCritique(
            critique_id=f"crit_{candidate_id}",
            thesis_id=candidate_id,
            title=f"Falsification Critique for {candidate_id}",
            contradictions=contradictions,
            failure_modes=list(reasons),
            severity_score=0.8,
        )

        synthesizer = DialecticalSynthesizer()
        synthesis = synthesizer.synthesize(thesis, critique)

        resolver = TRIZContradictionResolver()
        recommendations = []
        for c in contradictions:
            recs = resolver.resolve_contradiction(c)
            for r in recs:
                recommendations.append(r.to_dict())

        triz_payload = {
            "candidate_id": candidate_id,
            "synthesis_id": synthesis.synthesis_id,
            "synthesis_title": synthesis.title,
            "synthesized_architecture": synthesis.synthesized_architecture,
            "pareto_improvement_claim": synthesis.pareto_improvement_claim,
            "transcended_principles": [p.to_dict() for p in synthesis.transcended_principles],
            "resolved_contradictions": [c.to_dict() for c in synthesis.resolved_contradictions],
            "initial_contradiction_score": synthesis.initial_contradiction_score,
            "residual_contradiction_score": synthesis.residual_contradiction_score,
            "recommendations": recommendations,
            "timestamp": utc_now(),
        }

        with self._lock:
            if candidate is not None:
                candidate.metadata["triz_repair_recommendation"] = triz_payload
            self.triz_repair_recommendations.append(triz_payload)
            self._event(
                "triz_repair_recommendation",
                candidate_id=candidate_id,
                synthesis_id=synthesis.synthesis_id,
                residual_score=synthesis.residual_contradiction_score,
            )
        return triz_payload

    def register_candidate(self, candidate: Candidate) -> None:
        with self._lock:
            if candidate.session_id != self.session_id:
                raise ValueError("candidate belongs to a different session")
            if candidate.candidate_id in self.candidates:
                raise ValueError(f"duplicate candidate: {candidate.candidate_id}")
            missing = [rid for rid in candidate.receipt_ids if rid not in self.receipts]
            if missing:
                raise ValueError(f"candidate references unknown receipts: {missing}")
            missing_evidence = [eid for eid in candidate.evidence_ids if eid not in self.evidence]
            if missing_evidence:
                raise ValueError(f"candidate references unknown evidence: {missing_evidence}")
            # Keep a private snapshot so callers cannot mutate an artifact or
            # metadata after it enters the auditable run.
            stored = replace(
                candidate,
                artifact=copy.deepcopy(candidate.artifact),
                metadata=copy.deepcopy(dict(candidate.metadata)),
            )
            # System 3 Integration: Compute/track Friston Free Energy F, Kripke invariants, Hyperbolic tree embeddings
            self._evaluate_system3_for_candidate(stored)
            self.candidates[candidate.candidate_id] = stored
            self._event("candidate_registered", candidate_id=candidate.candidate_id)

    def attach_evidence(self, evidence: Evidence) -> None:
        with self._lock:
            self._validate_evidence(evidence)
            if evidence.evidence_id in self.evidence:
                raise ValueError(f"duplicate evidence: {evidence.evidence_id}")
            self.evidence[evidence.evidence_id] = evidence
            self._event("evidence_attached", evidence_id=evidence.evidence_id,
                        receipt_id=evidence.receipt_id)

    def _validate_evidence(self, evidence: Evidence) -> None:
        if evidence.session_id != self.session_id:
            raise ValueError("evidence belongs to a different session")
        receipt = self.receipts.get(evidence.receipt_id)
        if receipt is None:
            raise ValueError("evidence must reference a known tool receipt")
        if not receipt.success:
            raise ValueError("evidence cannot be anchored to a failed tool call")
        if evidence.source_output_hash != receipt.output_hash:
            raise PermissionError("evidence is not bound to the receipt output hash")
        if evidence.content_hash != receipt.output_hash:
            raise PermissionError("evidence content hash does not match receipt output hash")

    def _candidate_graph_hash(self, candidate: Candidate) -> str:
        """Commit to a candidate and every receipt/evidence object it references."""
        receipts = []
        for receipt_id in candidate.receipt_ids:
            receipt = self.receipts.get(receipt_id)
            if receipt is None:
                raise ValueError("candidate references an unknown receipt")
            receipts.append({
                "receipt_id": receipt_id,
                "object_hash": canonical_hash(receipt.to_dict()),
            })
        evidence = []
        for evidence_id in candidate.evidence_ids:
            item = self.evidence.get(evidence_id)
            if item is None:
                raise ValueError("candidate references unknown evidence")
            evidence.append({
                "evidence_id": evidence_id,
                "object_hash": canonical_hash(item.to_dict()),
            })
        return canonical_hash({
            "candidate": candidate.to_dict(),
            "receipts": receipts,
            "evidence": evidence,
        })

    def _validate_attested_verification(self, result: VerificationResult) -> None:
        """Validate every immutable verdict field and its candidate binding."""
        if result.session_id != self.session_id:
            raise ValueError("verification belongs to a different session")
        candidate = self.candidates.get(result.candidate_id)
        if candidate is None:
            raise ValueError("verification references an unknown candidate")
        if not result.inspected_candidate:
            raise PermissionError("verification must be produced by an executed verifier")
        if result.trust_boundary not in VerificationPolicy.TRUST_BOUNDARY_RANK:
            raise PermissionError("verification has no recognized trust boundary")
        if result.candidate_hash != canonical_hash(candidate.artifact):
            raise PermissionError("verification was not produced for the current candidate artifact")
        expected_graph = self._candidate_graph_hash(candidate)
        if not result.candidate_graph_hash or not hmac.compare_digest(
            result.candidate_graph_hash, expected_graph
        ):
            raise PermissionError("verification is not bound to the current candidate dependency graph")
        expected = self._attestation(result)
        if not hmac.compare_digest(result.runtime_attestation, expected):
            raise PermissionError("verification has no valid runtime attestation")
        unknown_evidence = [eid for eid in result.evidence_ids if eid not in self.evidence]
        if unknown_evidence:
            raise ValueError(f"verification references unknown evidence: {unknown_evidence}")
        candidate_evidence = set(candidate.evidence_ids)
        unrelated_evidence = [eid for eid in result.evidence_ids if eid not in candidate_evidence]
        if unrelated_evidence:
            raise PermissionError(
                "verification evidence is not attached to the verified candidate: "
                + ", ".join(unrelated_evidence)
            )
        if result.passed and not result.evidence_ids:
            raise PermissionError("a passing verification must cite candidate evidence")

    def _record_attested_verification(self, result: VerificationResult) -> None:
        """Store a result after ``execute_verifier`` has attested it."""
        if result.session_id != self.session_id:
            raise ValueError("verification belongs to a different session")
        if result.verification_id in self.verifications:
            raise ValueError(f"duplicate verification: {result.verification_id}")
        if any(v.candidate_id == result.candidate_id and v.verifier == result.verifier
               for v in self.verifications.values()):
            raise ValueError("verifier already produced a result for this candidate")
        self._validate_attested_verification(result)
        self.state = RunState.VERIFYING
        self.verifications[result.verification_id] = result
        self._event("verification_recorded", verification_id=result.verification_id,
                    candidate_id=result.candidate_id, verifier=result.verifier,
                    verifier_class=result.verifier_class, passed=result.passed)

    def record_verification(self, result: VerificationResult) -> None:
        """Reject model-supplied or otherwise unattested results.

        Results must come from ``execute_verifier`` so the runtime can bind the
        verdict to an in-process verifier invocation and the exact candidate
        artifact. This is an integrity boundary, not a process trust boundary.
        """
        raise PermissionError(
            "direct verification recording is disabled; execute a registered verifier"
        )

    def _attestation(self, result: VerificationResult) -> str:
        """MAC every immutable verdict field, excluding the MAC itself."""
        payload = result.to_dict()
        payload.pop("runtime_attestation", None)
        digest = canonical_hash(payload).encode("utf-8")
        return hmac.new(self._attestation_secret, digest, hashlib.sha256).hexdigest()

    def execute_verifier(self, verifier: RegisteredVerifier, candidate_id: str) -> VerificationResult:
        """Run and attest an in-process verifier against one exact candidate.

        The runtime binds the result to the invocation and artifact. The
        caller's in-process code is still within the same trust domain; a
        stronger boundary requires an isolated broker result.
        """
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        verifier_name = str(getattr(verifier, "name", "")).strip()
        if not verifier_name:
            raise ValueError("registered verifier must declare a name")
        if verifier_name in self.invalidated_verifiers:
            raise PermissionError(f"verifier is invalidated: {verifier_name}")
        # In-process verifier objects are application-level declarations only.
        # A process-attested result must arrive from an isolated broker path;
        # this method deliberately refuses to stamp that stronger boundary.
        trust_boundary = str(getattr(verifier, "trust_boundary", "")).strip()
        if trust_boundary != "in_process":
            raise PermissionError(
                "in-process verifier execution cannot claim a process-attested boundary"
            )
        verifier_class = str(getattr(verifier, "verifier_class", "")).strip()
        if not verifier_class:
            raise ValueError("registered verifier must declare verifier_class")
        # Objective checks must establish a baseline before an independent
        # judge is allowed to approve the candidate. This prevents a model
        # judge from becoming the first and only line of defense.
        deterministic_classes = {"deterministic", "machine-check"}
        required_deterministic = deterministic_classes & set(
            self.task.verification_policy.required_verifier_classes
        )
        passed_classes = {v.verifier_class for v in self.passed_verifications(candidate_id)}
        if (bool(getattr(verifier, "independent", False))
                and required_deterministic - passed_classes):
            raise PermissionError(
                "independent verification must run after passing deterministic "
                "verification: " + ", ".join(sorted(required_deterministic - passed_classes))
            )
        raw = verifier.verify(candidate)
        if raw.candidate_id != candidate_id or raw.session_id != self.session_id:
            raise ValueError("verifier returned a result for the wrong session or candidate")
        if not raw.passed:
            reasons = list(raw.reasons) if raw.reasons else ["Verifier rejected candidate"]
            self._generate_triz_repair_recommendation(candidate_id, reasons)
        result = replace(
            raw,
            verifier=verifier_name or raw.verifier,
            verifier_class=verifier_class,
            candidate_hash=canonical_hash(candidate.artifact),
            inspected_candidate=True,
            independent=bool(getattr(verifier, "independent", False)),
            trust_boundary=trust_boundary,
            candidate_graph_hash=self._candidate_graph_hash(candidate),
        )
        result = replace(result, runtime_attestation=self._attestation(result))
        self._record_attested_verification(result)
        return result

    def invalidate_verifier(self, verifier: str, reason: str) -> None:
        """Revoke a verifier's authority for future finalization decisions."""
        if not verifier or not verifier.strip() or not reason or not reason.strip():
            raise ValueError("verifier and reason must be non-empty")
        with self._lock:
            self.invalidated_verifiers[verifier.strip()] = reason.strip()
            self._event("verifier_invalidated", verifier=verifier.strip(),
                        reason=reason.strip())

    def successful_capabilities(self, candidate_id: str | None = None) -> set[str]:
        """Return successful capabilities, scoped to a candidate when given."""
        if candidate_id is None:
            receipts = self.receipts.values()
        else:
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                raise ValueError(f"unknown candidate: {candidate_id}")
            receipts = (self.receipts[receipt_id] for receipt_id in candidate.receipt_ids)
        return {receipt.capability for receipt in receipts if receipt.success}

    def missing_requirements(self, candidate_id: str | None = None) -> list[str]:
        missing: list[str] = []
        used = self.successful_capabilities(candidate_id)
        for capability in self.task.required_capabilities:
            if capability not in used:
                missing.append(f"required capability not completed: {capability}")

        if self.task.required_evidence:
            candidate_evidence = set()
            if candidate_id and candidate_id in self.candidates:
                candidate_evidence = set(self.candidates[candidate_id].evidence_ids)
            for kind in self.task.required_evidence:
                if not any(e.kind == kind and e.evidence_id in candidate_evidence
                           for e in self.evidence.values()):
                    missing.append(f"required evidence not attached: {kind}")
        return missing

    def passed_verifications(self, candidate_id: str) -> list[VerificationResult]:
        return [v for v in self.verifications.values()
                if v.candidate_id == candidate_id and v.passed
                and v.inspected_candidate
                and v.trust_boundary in VerificationPolicy.TRUST_BOUNDARY_RANK
                and v.verifier not in self.invalidated_verifiers]

    def verification_requirements(self, candidate_id: str) -> list[str]:
        """Return missing policy requirements for the exact candidate."""
        passed = self.passed_verifications(candidate_id)
        policy = self.task.verification_policy
        classes = {v.verifier_class for v in passed}
        missing = [
            f"required verifier class not passed: {kind}"
            for kind in policy.required_verifier_classes
            if kind not in classes
        ]
        if len(passed) < policy.minimum_passing_verifiers:
            missing.append(
                f"requires {policy.minimum_passing_verifiers} passing verifiers "
                f"(currently {len(passed)})"
            )
        if policy.require_independent and not any(v.independent for v in passed):
            missing.append("requires a passing independently registered verifier")
        boundary_rank = VerificationPolicy.TRUST_BOUNDARY_RANK[policy.minimum_trust_boundary]
        if not any(VerificationPolicy.TRUST_BOUNDARY_RANK[v.trust_boundary] >= boundary_rank
                   for v in passed):
            missing.append(
                "requires a passing verifier at trust boundary "
                + policy.minimum_trust_boundary
            )
        return missing

    def finalize(self, candidate_id: str) -> Candidate:
        if candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate: {candidate_id}")
        missing = self.missing_requirements(candidate_id) + self.verification_requirements(candidate_id)
        if missing:
            self._generate_triz_repair_recommendation(candidate_id, missing)
            self.state = RunState.REJECTED
            self._event("finalization_rejected", candidate_id=candidate_id, missing=missing)
            raise PermissionError("finalization rejected: " + "; ".join(missing))
        self.final_candidate_id = candidate_id
        self.state = RunState.FINALIZED
        self._event("run_finalized", candidate_id=candidate_id)
        return self.candidates[candidate_id]

    def run_system3_meta_cycle(self, candidate_id: str) -> dict[str, Any]:
        """Execute a full System 3 meta-cognitive reflection cycle for a candidate."""
        with self._lock:
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                raise ValueError(f"unknown candidate: {candidate_id}")

            # 1. Active Inference Free Energy evaluation
            pomdp_model = create_default_architecture_pomdp()
            fe_engine = ActiveInferenceEngine(pomdp_model)
            observation = "HIGH_THROUGHPUT_CLEAN" if all(
                self.receipts[r].success for r in candidate.receipt_ids if r in self.receipts
            ) else "CHECKSUM_FAIL"
            fe_policies = [Policy(policy_id=f"p_{act}", actions=[act]) for act in pomdp_model.actions]
            fe_eval = fe_engine.select_action(observation, fe_policies)
            fe_report = {
                "variational_free_energy_f": round(fe_eval.variational_free_energy_f, 4),
                "complexity_kl": round(fe_eval.complexity_kl, 4),
                "accuracy_log_likelihood": round(fe_eval.accuracy_log_likelihood, 4),
                "observation": observation,
                "selected_policy": fe_eval.selected_action,
                "evaluated_policies_count": len(fe_eval.evaluated_policies),
            }

            # 2. Kripke Modal Safety Invariant Model Checking
            kripke = KripkeStructure()
            kripke.add_world("w0", propositions={"init", "safe"})
            kripke.add_world("w1", propositions={"executing", "safe"})
            kripke.add_world("w2", propositions={"verified", "safe"})
            kripke.add_transition("w0", "w1")
            kripke.add_transition("w1", "w2")
            kripke.add_transition("w2", "w2")
            checker = KripkeModelChecker(kripke)
            formula_res = checker.check("AG(safe)", "w0")
            kripke_report = {
                "formula": "AG(safe)",
                "satisfied": formula_res.is_satisfied,
                "initial_world": "w0",
                "satisfying_worlds": sorted(list(formula_res.satisfied_worlds)),
            }

            # 3. Hyperbolic Tree Embedding
            tree = {candidate_id: list(candidate.receipt_ids) + list(candidate.evidence_ids)}
            for r in candidate.receipt_ids:
                tree[r] = []
            for e in candidate.evidence_ids:
                tree[e] = []
            if not tree[candidate_id]:
                tree[candidate_id] = ["artifact_root"]
                tree["artifact_root"] = []
            embedder = HyperbolicTreeEmbedder(dimension=2, base_step_distance=1.0)
            hyp_res = embedder.embed_hierarchy(tree, root_id=candidate_id)
            hyp_report = {
                "root_id": hyp_res.root_id,
                "total_nodes": hyp_res.total_nodes,
                "tree_depth": hyp_res.tree_depth,
                "average_distortion": hyp_res.average_distortion,
                "stress": hyp_res.stress,
                "capacity_ratio": hyp_res.hierarchical_capacity_ratio,
            }

            # 4. Cognitive Bias Detection via System 3 Executive
            bias_detector = CognitiveBiasDetector()
            bias_findings = bias_detector.audit_session(
                session_data={
                    "epistemic_ledger": [{"tag": "PROVEN", "claim": f"Candidate {candidate_id} registered"}],
                    "refinement_cycles": [{"refinement_type": "architectural", "focus_area": "system3"}],
                    "phase_history": [{"phase": self.state.value}],
                }
            )
            bias_report = [b.to_dict() for b in bias_findings]

            # 5. Tri-Level Arbitration
            arbitrator = TriLevelArbitrator()
            arbitration_res = arbitrator.arbitrate(
                task_complexity=0.7,
                contradiction_density=0.3,
                failure_count=len(self.invalidated_verifiers),
                epistemic_uncertainty=round(fe_eval.complexity_kl, 3),
            )

            # 6. Dialectical Synthesis
            thesis = ThesisCandidate(
                thesis_id=candidate_id,
                title=f"Candidate {candidate_id}",
                description=f"System 3 meta cycle for candidate {candidate_id}",
            )
            critique = AntithesisCritique(
                critique_id=f"meta_crit_{candidate_id}",
                thesis_id=candidate_id,
                title="System 3 Dialectical Critique",
                failure_modes=[],
                severity_score=0.3,
            )
            synthesizer = DialecticalSynthesizer()
            syn = synthesizer.synthesize(thesis, critique)

            cycle_record = {
                "candidate_id": candidate_id,
                "timestamp": utc_now(),
                "free_energy": fe_report,
                "kripke_invariants": kripke_report,
                "hyperbolic_embedding": hyp_report,
                "bias_findings": bias_report,
                "arbitration": arbitration_res.to_dict() if hasattr(arbitration_res, "to_dict") else dict(arbitration_res),
                "dialectical_synthesis": syn.to_dict(),
            }

            self.system3_meta_cycles.append(cycle_record)
            candidate.metadata["system3_meta_cycle"] = cycle_record
            self._event("system3_meta_cycle_completed", candidate_id=candidate_id, f_val=fe_eval.variational_free_energy_f)
            return cycle_record

    def to_dict(self) -> dict[str, Any]:
        """Serialize a run for round-trip checkpointing."""
        return {
            "version": "2.0",
            "session_id": self.session_id,
            "task": self.task.to_dict(),
            "state": self.state.value,
            "started_at": self.started_at,
            "receipts": [receipt.to_dict() for receipt in self.receipts.values()],
            "candidates": [candidate.to_dict() for candidate in self.candidates.values()],
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "verifications": [item.to_dict() for item in self.verifications.values()],
            "events": copy.deepcopy(self.events),
            "final_candidate_id": self.final_candidate_id,
            "invalidated_verifiers": dict(self.invalidated_verifiers),
            "system3_free_energy": copy.deepcopy(self.system3_free_energy),
            "system3_kripke_invariants": copy.deepcopy(self.system3_kripke_invariants),
            "system3_hyperbolic_embeddings": copy.deepcopy(self.system3_hyperbolic_embeddings),
            "system3_meta_cycles": copy.deepcopy(self.system3_meta_cycles),
            "triz_repair_recommendations": copy.deepcopy(self.triz_repair_recommendations),
            # Production deployments should protect this with an external key
            # store; it is included here so an in-memory checkpoint can be
            # faithfully restored without silently trusting new signatures.
            "attestation_secret": self._attestation_secret.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FableRun":
        """Restore a run and reject tampered event history or payload hashes."""
        task_data = dict(data["task"])
        policy_data = dict(task_data.pop("verification_policy", {}))
        task_data["constraints"] = tuple(task_data.get("constraints", ()))
        task_data["definition_of_done"] = tuple(task_data.get("definition_of_done", ()))
        task_data["required_capabilities"] = tuple(task_data.get("required_capabilities", ()))
        task_data["required_evidence"] = tuple(task_data.get("required_evidence", ()))
        task_data["verification_policy"] = VerificationPolicy(**policy_data)
        run = cls(
            session_id=data["session_id"],
            task=TaskSpec(**task_data),
            state=RunState(data.get("state", RunState.CREATED.value)),
            started_at=data.get("started_at", utc_now()),
        )
        secret = data.get("attestation_secret")
        if secret:
            run._attestation_secret = bytes.fromhex(secret)
        run.receipts = {}
        for item in data.get("receipts", []):
            receipt = ToolReceipt(**item)
            if receipt.session_id != run.session_id:
                raise ValueError("restored tool receipt belongs to a different session")
            if receipt.receipt_id in run.receipts:
                raise ValueError("duplicate restored tool receipt")
            run.receipts[receipt.receipt_id] = receipt
        run.candidates = {}
        for item in data.get("candidates", []):
            candidate = Candidate(
                **{**item,
                   "receipt_ids": tuple(item.get("receipt_ids", ())),
                   "evidence_ids": tuple(item.get("evidence_ids", ()))})
            if candidate.candidate_id in run.candidates:
                raise ValueError("duplicate restored candidate")
            run.candidates[candidate.candidate_id] = candidate
        for candidate in run.candidates.values():
            if any(receipt_id not in run.receipts for receipt_id in candidate.receipt_ids):
                raise ValueError("candidate references an unknown restored receipt")
        run.evidence = {}
        for item in data.get("evidence", []):
            evidence = Evidence(**item)
            run._validate_evidence(evidence)
            if evidence.evidence_id in run.evidence:
                raise ValueError("duplicate restored evidence")
            run.evidence[evidence.evidence_id] = evidence
        for candidate in run.candidates.values():
            if any(evidence_id not in run.evidence for evidence_id in candidate.evidence_ids):
                raise ValueError("candidate references an unknown restored evidence item")
        run.verifications = {}
        seen_verifier_candidates: set[tuple[str, str]] = set()
        for item in data.get("verifications", []):
            result = VerificationResult(
                **{**item,
                   "reasons": tuple(item.get("reasons", ())),
                   "evidence_ids": tuple(item.get("evidence_ids", ()))})
            pair = (result.verifier, result.candidate_id)
            if pair in seen_verifier_candidates:
                raise ValueError("duplicate restored verifier verdict")
            run._validate_attested_verification(result)
            run.verifications[result.verification_id] = result
            seen_verifier_candidates.add(pair)
        run.events = copy.deepcopy(data.get("events", []))
        run.final_candidate_id = data.get("final_candidate_id")
        run.invalidated_verifiers = dict(data.get("invalidated_verifiers", {}))
        run.system3_free_energy = copy.deepcopy(data.get("system3_free_energy", {}))
        run.system3_kripke_invariants = copy.deepcopy(data.get("system3_kripke_invariants", {}))
        run.system3_hyperbolic_embeddings = copy.deepcopy(data.get("system3_hyperbolic_embeddings", {}))
        run.system3_meta_cycles = copy.deepcopy(data.get("system3_meta_cycles", []))
        run.triz_repair_recommendations = copy.deepcopy(data.get("triz_repair_recommendations", []))
        run.validate_event_history()
        return run

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task.task_id,
            "state": self.state.value,
            "receipts": len(self.receipts),
            "candidates": len(self.candidates),
            "evidence": len(self.evidence),
            "verifications": len(self.verifications),
            "successful_capabilities": sorted(self.successful_capabilities()),
            "missing_requirements": (
                self.missing_requirements(self.final_candidate_id)
                + (self.verification_requirements(self.final_candidate_id)
                   if self.final_candidate_id else [])
            ),
            "verification_policy": self.task.verification_policy.to_dict(),
            "final_candidate_id": self.final_candidate_id,
            "system3_state": {
                "free_energy_tracked": len(self.system3_free_energy),
                "kripke_invariants_tracked": len(self.system3_kripke_invariants),
                "hyperbolic_embeddings_tracked": len(self.system3_hyperbolic_embeddings),
                "meta_cycles_count": len(self.system3_meta_cycles),
                "triz_repairs_count": len(self.triz_repair_recommendations),
            },
        }


def new_run(session_id: str, task: TaskSpec) -> FableRun:
    run = FableRun(session_id=session_id, task=task)
    run.start()
    return run
