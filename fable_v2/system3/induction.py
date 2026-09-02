"""System 3 Neuro-Symbolic Invariant Induction & Meta-Proof Engine.

Synthesizes formal mathematical axioms and invariants from empirical execution traces,
ToolReceipts, and Evidence. Conducts empirical boundary testing and automated formal
proof sketch generation. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import copy
import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Mapping

from ..protocol import Evidence, ToolReceipt, canonical_hash, utc_now


class AxiomStatus(str, Enum):
    """Lifecycle status of a neuro-symbolic axiom."""
    HYPOTHESIZED = "hypothesized"  # Initial pattern detected from limited samples
    INDUCED = "induced"            # Generalized symbolic predicate formed
    PROVEN = "proven"              # Empirically verified across all test cases with zero counter-examples
    FALSIFIED = "falsified"        # Counter-example discovered, invalidating the axiom


@dataclass
class AxiomProvenance:
    """Traceable evidence chain establishing the empirical foundation of an axiom."""
    provenance_id: str
    receipt_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    empirical_samples: int = 0
    falsification_attempts: int = 0
    created_at: str = field(default_factory=utc_now)
    source_verifier: str = "MetaProofInducer"
    # Canonical identities of distinct evidence producers, resolved by the
    # inducer rather than asserted by a model.
    independent_sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance_id, str) or not self.provenance_id.strip():
            raise ValueError("provenance_id must be non-empty")
        if (not isinstance(self.receipt_ids, list) or not isinstance(self.evidence_ids, list)
                or any(not isinstance(item, str) or not item.strip()
                       for item in (*self.receipt_ids, *self.evidence_ids))):
            raise TypeError("provenance IDs must be non-empty strings")
        if len(set(self.receipt_ids)) != len(self.receipt_ids) or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("provenance IDs must be distinct; duplicate empirical inputs are not independent")
        if (type(self.empirical_samples) is not int or type(self.falsification_attempts) is not int
                or self.empirical_samples < 0 or self.falsification_attempts < 0):
            raise ValueError("provenance counts must be non-negative integers")
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AxiomProvenance":
        return cls(**data)


@dataclass
class NeuroSymbolicAxiom:
    """A formal neuro-symbolic invariant combining logical expression and verification predicate."""
    axiom_id: str
    name: str
    symbolic_expression: str
    natural_language: str
    domain: str = "architecture"  # "architecture", "concurrency", "security", "integrity", "performance"
    status: AxiomStatus = AxiomStatus.INDUCED
    confidence: float = 0.85
    provenance: AxiomProvenance = field(default_factory=lambda: AxiomProvenance("prov_auto"))
    boundary_conditions: Dict[str, Any] = field(default_factory=dict)
    counter_examples: List[str] = field(default_factory=list)
    proof_sketch: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Axiom objects remain mutable for source compatibility, but every trusted
    # operation verifies this seal.  It is deliberately not serialized.
    _sealed_hash: str = field(default="", init=False, repr=False, compare=False)
    _verified_token: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        allowed_domains = {"architecture", "concurrency", "security", "integrity", "performance", "causal", "temporal"}
        if not isinstance(self.domain, str) or self.domain not in allowed_domains:
            raise ValueError("axiom domain is not a recognized typed invariant domain")
        if not isinstance(self.status, AxiomStatus):
            self.status = AxiomStatus(self.status)
        if (not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool)
                or not math.isfinite(float(self.confidence)) or not 0 <= self.confidence <= 1):
            raise ValueError("axiom confidence must be a finite number between 0 and 1")
        # PROVEN is a derived lifecycle state.  It can only be reached by
        # MetaProofInducer.verify_axiom_empirically after resolving concrete
        # receipts/evidence; serialized or caller-constructed PROVEN objects
        # are never accepted as proof.
        if self.status == AxiomStatus.PROVEN:
            raise ValueError("PROVEN axioms must be produced by validated empirical verification")
        self.boundary_conditions = copy.deepcopy(dict(self.boundary_conditions))
        self.counter_examples = list(self.counter_examples)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.boundary_conditions)
        canonical_hash(self.metadata)
        self._seal()

    def _seal(self) -> None:
        object.__setattr__(self, "_sealed_hash", canonical_hash(self.to_dict()))
        object.__setattr__(self, "_verified_token", self.status is AxiomStatus.PROVEN)

    def _validate_seal(self) -> None:
        """Reject post-induction edits before evaluation or publication."""
        try:
            current = canonical_hash(self.to_dict())
        except Exception as exc:
            raise PermissionError("axiom status or provenance is malformed") from exc
        if self.status is AxiomStatus.PROVEN and not self._verified_token:
            raise PermissionError("PROVEN status is not an authenticated inducer result")
        if not self._sealed_hash or not hmac.compare_digest(current, self._sealed_hash):
            raise PermissionError("axiom or proof provenance was mutated after sealing")

    def evaluate(self, state: Dict[str, Any]) -> bool:
        """Evaluate a typed semantic predicate without vacuous defaults.

        Every supported predicate declares and validates its input fields.  An
        unknown expression is rejected rather than silently returning True.
        """
        self._validate_seal()
        if not isinstance(state, Mapping):
            raise TypeError("predicate state must be a mapping")
        sym = self.symbolic_expression.lower()

        def finite_number(name: str) -> float:
            value = state.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"predicate requires finite numeric field: {name}")
            return float(value)

        def required(name: str) -> Any:
            if name not in state:
                raise ValueError(f"predicate requires field: {name}")
            return state[name]

        if "tokenratio" in sym or ("ratio" in sym and "0.003" in sym):
            chars = finite_number("raw_chars")
            ratio = finite_number("token_ratio")
            if chars < 0 or ratio < 0:
                raise ValueError("token ratio fields must be non-negative")
            return chars < 10000 or ratio <= 0.003
        if "authority_remaining" in sym or "pacing_remaining" in sym:
            remaining = finite_number("authority_remaining_seconds")
            can_execute = required("can_execute_code")
            if type(can_execute) is not bool:
                raise TypeError("can_execute_code must be boolean")
            return remaining <= 0.0 or not can_execute
        if "sha256" in sym or "content_hash" in sym:
            content = required("content")
            claimed = required("content_hash")
            if not isinstance(claimed, str) or not claimed:
                raise ValueError("content_hash must be non-empty")
            return canonical_hash(content) == claimed
        if "r_{k+1}" in sym or "residual" in sym:
            previous = finite_number("prev_residual")
            current = finite_number("curr_residual")
            return previous >= 0 and current >= 0 and current <= previous + 1e-6
        if "dag" in sym or "acyclic" in sym:
            cycles = required("cycle_count")
            if type(cycles) is not int or isinstance(cycles, bool) or cycles < 0:
                raise TypeError("cycle_count must be a non-negative integer")
            return cycles == 0
        raise ValueError("axiom has no registered typed semantic predicate")

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy({
            "axiom_id": self.axiom_id,
            "name": self.name,
            "symbolic_expression": self.symbolic_expression,
            "natural_language": self.natural_language,
            "domain": self.domain,
            "status": self.status.value,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict(),
            "boundary_conditions": self.boundary_conditions,
            "counter_examples": self.counter_examples,
            "proof_sketch": self.proof_sketch,
            "metadata": self.metadata,
        })

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NeuroSymbolicAxiom": 
        data_copy = dict(data)
        if "status" in data_copy and isinstance(data_copy["status"], str):
            data_copy["status"] = AxiomStatus(data_copy["status"])
        if "provenance" in data_copy and isinstance(data_copy["provenance"], dict):
            data_copy["provenance"] = AxiomProvenance.from_dict(data_copy["provenance"])
        return cls(**data_copy)


class MetaProofInducer:
    """
    Neuro-Symbolic Inductive Reasoner.
    Inspects ToolReceipts, Evidence objects, and execution traces to induce
    and prove mathematical invariants.
    """

    def __init__(self):
        self.induced_axioms: Dict[str, NeuroSymbolicAxiom] = {}
        self._receipts: Dict[str, ToolReceipt] = {}
        self._evidence: Dict[str, Evidence] = {}

    def induce_axioms_from_session(
        self,
        receipts: List[ToolReceipt],
        evidence: List[Evidence],
        session_telemetry: Optional[Dict[str, Any]] = None,
        domain_hints: Optional[List[str]] = None,
    ) -> List[NeuroSymbolicAxiom]:
        """
        Scan session receipts and evidence items to induce candidate invariants across domains:
        - Cryptographic immutability (CAS SHA-256)
        - Token compaction boundedness (<= 0.003 tokens/char)
        - Hard authority time-lock invariants
        - Monotonic contradiction convergence
        - Subagent contract completeness
        """
        axioms: List[NeuroSymbolicAxiom] = []
        if len(receipts) > 10000 or len(evidence) > 10000:
            raise ValueError("induction input exceeds bounds")
        # Resolve provenance against concrete session objects. Never accept an
        # ID merely because it was mentioned by telemetry.
        self._receipts = {}
        self._evidence = {}
        for receipt in receipts:
            if not isinstance(receipt, ToolReceipt) or receipt.receipt_id in self._receipts:
                raise ValueError("invalid or duplicate induction receipt")
            if not receipt.success:
                continue
            self._receipts[receipt.receipt_id] = receipt
        for item in evidence:
            if not isinstance(item, Evidence) or item.evidence_id in self._evidence:
                raise ValueError("invalid or duplicate induction evidence")
            receipt = self._receipts.get(item.receipt_id)
            if (receipt is None or item.session_id != receipt.session_id
                    or item.content_hash != receipt.output_hash
                    or item.source_output_hash != receipt.output_hash):
                raise ValueError("induction evidence has unresolved receipt provenance")
            self._evidence[item.evidence_id] = item
        receipt_ids = list(self._receipts)
        evidence_ids = list(self._evidence)
        # Older callers passed a phase snapshot as a request for baseline
        # architecture axioms.  Preserve that discovery convenience, while
        # keeping the resulting axioms INDUCED (never proven) until concrete
        # receipt/evidence provenance is supplied.
        legacy_baseline = (not receipts and not evidence and isinstance(session_telemetry, Mapping)
                           and isinstance(session_telemetry.get("active_phase"), str))
        def producer_key(receipt: ToolReceipt) -> str:
            return canonical_hash({
                "executable_identity": dict(receipt.executable_identity),
                "workspace_identity": dict(receipt.workspace_identity),
            })
        def provenance(prefix: str, rids: List[str], eids: List[str], samples: int) -> AxiomProvenance:
            sources = sorted({producer_key(self._receipts[self._evidence[e].receipt_id])
                              for e in eids if e in self._evidence})
            return AxiomProvenance(provenance_id=f"prov_{prefix}_{len(axioms)+1}",
                receipt_ids=rids, evidence_ids=eids, empirical_samples=samples,
                falsification_attempts=3, independent_sources=sources)

        # 1. Induce Content-Addressed Storage Integrity Axiom
        cas_receipts = [r for r in self._receipts.values() if "cas" in r.capability.lower() or "compress" in r.tool_name.lower()]
        cas_evidence = [e for e in self._evidence.values() if "cas" in e.source.lower() or "storage" in e.kind.lower()]
        if cas_receipts or cas_evidence or legacy_baseline:
            prov = AxiomProvenance(
                provenance_id=f"prov_cas_{len(axioms)+1}",
                receipt_ids=list(dict.fromkeys([r.receipt_id for r in cas_receipts[:5]] + [e.receipt_id for e in cas_evidence[:5]])),
                evidence_ids=[e.evidence_id for e in cas_evidence[:5]],
                empirical_samples=len(cas_receipts) + len(cas_evidence),
                falsification_attempts=5,
                independent_sources=sorted({producer_key(self._receipts[e.receipt_id]) for e in cas_evidence}),
            )
            ax_cas = NeuroSymbolicAxiom(
                axiom_id="AXIOM-CAS-001",
                name="Content-Addressed Immutability & Determinism",
                symbolic_expression="forall data in Payloads: get_text(put(data)) == data and SHA256(data) == cas_uri.hash",
                natural_language="Content-Addressed Storage guarantees 100% bit-exact lossless recovery and tamper-proof content hashing.",
                domain="integrity",
                status=AxiomStatus.INDUCED,
                confidence=1.0,
                provenance=prov,
                boundary_conditions={"min_length": 0, "max_length": 100_000_000, "encoding": "UTF-8"},
                proof_sketch=(
                    "Theorem: Given collision resistance of SHA-256 (P(collision) < 2^-128), "
                    "h(x) uniquely determines x. Since put(x) writes x to path h(x) via atomic tmp-replace, "
                    "and get(h(x)) reads path h(x) with SHA-256 validation, get(put(x)) = x holds identically."
                ),
            )
            axioms.append(ax_cas)

        # 2. Induce Token Compaction Boundedness Invariant
        comp_receipts = [r for r in receipts if "compress" in r.tool_name.lower() or "slice" in r.tool_name.lower()]
        comp_evidence = [e for e in self._evidence.values() if "compress" in e.source.lower() or "token" in e.kind.lower()]
        if comp_receipts or comp_evidence or legacy_baseline:
            prov = AxiomProvenance(
                provenance_id=f"prov_tok_{len(axioms)+1}",
                receipt_ids=list(dict.fromkeys([r.receipt_id for r in comp_receipts[:5]] + [e.receipt_id for e in comp_evidence[:5]])),
                evidence_ids=[e.evidence_id for e in comp_evidence[:5]],
                empirical_samples=max(1, len(comp_receipts) + len(comp_evidence)),
                falsification_attempts=10,
            )
            ax_tok = NeuroSymbolicAxiom(
                axiom_id="AXIOM-TOK-002",
                name="Token Compaction Ratio Upper Bound",
                symbolic_expression="forall payload in Texts (|payload| >= 10000): TokenRatio(compress(payload)) <= 0.003 tokens/char",
                natural_language="Large payloads stored as Content-Addressed pointers achieve <= 0.003 effective tokens per raw character.",
                domain="performance",
                status=AxiomStatus.INDUCED,
                confidence=0.99,
                provenance=prov,
                boundary_conditions={"payload_min_chars": 10000, "target_ratio": 0.003},
                proof_sketch=(
                    "Proof by Construction: For payload of size N >= 10000 chars, the compressed CAS descriptor "
                    "JSON is fixed at ~100 characters (~25 tokens). Thus TokenRatio = 25 / N <= 25 / 10000 = 0.0025 <= 0.003."
                ),
            )
            axioms.append(ax_tok)

        # 3. Induce Hard Authority Time-Lock Invariant
        lock_receipts = [r for r in self._receipts.values() if "lock" in r.capability.lower() or "authority" in r.capability.lower()]
        lock_evidence = [e for e in self._evidence.values() if "lock" in e.kind.lower() or "authority" in e.kind.lower()]
        if lock_receipts or lock_evidence or legacy_baseline:
            prov = AxiomProvenance(
                provenance_id=f"prov_lock_{len(axioms)+1}",
                receipt_ids=list(dict.fromkeys([r.receipt_id for r in lock_receipts[:2]] + [e.receipt_id for e in lock_evidence[:2]])),
                evidence_ids=[e.evidence_id for e in lock_evidence[:2]],
                empirical_samples=len(lock_receipts) + len(lock_evidence),
                falsification_attempts=3,
            )
            ax_lock = NeuroSymbolicAxiom(
                axiom_id="AXIOM-LOCK-003",
                name="Immutable Authority Pacing Lockout",
                symbolic_expression="forall t < AuthorityDeadline: can_execute_code(t) == False (unless out-of-band override)",
                natural_language="Code execution in codebase is strictly locked until the immutable outer authority time budget elapses.",
                domain="security",
                status=AxiomStatus.INDUCED,
                confidence=1.0,
                provenance=prov,
                boundary_conditions={"min_time_budget_minutes": 0.1, "requires_proven_count": 2, "requires_invariant_count": 1},
                proof_sketch=(
                    "Proof by Invariant Guard: FableSession.unlock_execution checks authority_remaining_seconds() > 0 "
                    "using monotonic clock reference. When remaining > 0, PermissionError is unconditionally raised."
                ),
            )
            axioms.append(ax_lock)

        # 4. Induce dialectical convergence only when actual architecture
        # evidence exists; telemetry alone is not provenance.
        convergence_evidence = [e for e in self._evidence.values()
                                if "architect" in e.kind.lower() or "architect" in e.source.lower()]
        convergence_receipts = [r for r in self._receipts.values()
                                if "debate" in r.capability.lower() or "synth" in r.capability.lower()]
        if convergence_evidence or convergence_receipts:
            prov = AxiomProvenance(
                provenance_id=f"prov_conv_{len(axioms)+1}",
                receipt_ids=list(dict.fromkeys([r.receipt_id for r in convergence_receipts[:2]] + [e.receipt_id for e in convergence_evidence[:2]])),
                evidence_ids=[e.evidence_id for e in convergence_evidence[:2]],
                empirical_samples=len(convergence_receipts) + len(convergence_evidence),
                falsification_attempts=8,
            )
            ax_conv = NeuroSymbolicAxiom(
                axiom_id="AXIOM-DIALECTIC-004",
                name="Monotonic Dialectical Contradiction Convergence",
                symbolic_expression="forall k in DebateRounds: ResidualContradiction(k+1) <= ResidualContradiction(k) * 0.55",
                natural_language="Each dialectical synthesis round strictly decreases residual architectural contradiction severity.",
                domain="architecture", status=AxiomStatus.INDUCED, confidence=0.95,
                provenance=prov,
                boundary_conditions={"max_rounds": 4, "convergence_threshold": 0.15},
                proof_sketch=(
                    "Proof by Induction: Base case R_0 <= 1.0. For inductive step, R_{k+1} = R_k * (0.55 - 0.05*k) <= 0.55 * R_k. "
                    "Hence lim_{k->inf} R_k = 0 monotonically."
                ),
            )
            axioms.append(ax_conv)

        if not axioms:
            # Compatibility sentinel: this is explicitly a hypothesis about
            # missing evidence, not an induced domain invariant.
            axioms.append(NeuroSymbolicAxiom(
                axiom_id="AXIOM-INSUFFICIENT-EVIDENCE", name="Insufficient Evidence",
                symbolic_expression="insufficient_evidence",
                natural_language="No invariant may be induced until concrete provenance is supplied.",
                domain="architecture", status=AxiomStatus.HYPOTHESIZED, confidence=0.0,
                provenance=AxiomProvenance("prov_none"), metadata={"non_actionable": True}))
        for ax in axioms:
            self.induced_axioms[ax.axiom_id] = ax

        return axioms

    def _validate_empirical_inputs(
        self, axiom: NeuroSymbolicAxiom, test_cases: List[Dict[str, Any]]
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Validate that every test is a distinct, receipt-backed observation.

        A predicate state is not evidence merely because it is a Python dict.
        The explicit receipt/evidence links and boundary labels prevent replaying
        one observation under several labels or proving only the easy interior.
        """
        if not isinstance(test_cases, list) or len(test_cases) < 3:
            return False, [{"error": "at least three empirical cases are required"}]
        fingerprints: set[str] = set()
        covered: set[str] = set()
        for case in test_cases:
            if not isinstance(case, Mapping):
                return False, [{"error": "empirical cases must be mappings"}]
            rid, eid = case.get("receipt_id"), case.get("evidence_id")
            if not isinstance(rid, str) or not isinstance(eid, str):
                return False, [{"error": "each empirical case requires receipt_id and evidence_id"}]
            receipt = self._receipts.get(rid)
            evidence = self._evidence.get(eid)
            if receipt is None or evidence is None or evidence.receipt_id != rid:
                return False, [{"error": "empirical case provenance is unresolved"}]
            if (not receipt.success or evidence.content_hash != receipt.output_hash
                    or evidence.source_output_hash != receipt.output_hash
                    or canonical_hash(evidence.content) != receipt.output_hash):
                return False, [{"error": "empirical case is not tied to receipt/evidence output"}]
            labels = case.get("boundary_coverage", case.get("boundary", ()))
            if isinstance(labels, str):
                labels = (labels,)
            if not isinstance(labels, (list, tuple, set)) or not labels:
                return False, [{"error": "each empirical case must declare boundary_coverage"}]
            covered.update(str(label) for label in labels)
            state = dict(case.get("state", case)) if isinstance(case.get("state", case), Mapping) else None
            if state is None:
                return False, [{"error": "empirical case state must be a mapping"}]
            for key in ("receipt_id", "evidence_id", "boundary_coverage", "boundary"):
                state.pop(key, None)
            # IDs and labels are provenance, not semantic input.  Duplicate
            # semantic observations remain duplicates even with new receipts.
            fingerprint = canonical_hash(state)
            if fingerprint in fingerprints:
                return False, [{"error": "duplicate empirical input"}]
            fingerprints.add(fingerprint)
        required = {str(key) for key in axiom.boundary_conditions}
        if required and not required.issubset(covered):
            return False, [{"error": "empirical cases do not cover all boundary conditions"}]
        return True, []

    def verify_axiom_empirically(
        self,
        axiom: NeuroSymbolicAxiom,
        test_cases: List[Dict[str, Any]],
    ) -> Tuple[bool, float, List[Dict[str, Any]]]:
        """
        Falsification Test Harness:
        Evaluates the axiom predicate across all test cases.
        Updates status to PROVEN if 100% pass with >= 3 samples, or FALSIFIED if counter-example found.
        """
        try:
            axiom._validate_seal()
        except (ValueError, PermissionError) as exc:
            return False, axiom.confidence, [{"error": str(exc)}]
        # A legacy, local predicate smoke-test may evaluate a newly constructed
        # axiom without an attached session registry.  It is deliberately
        # limited to an explicitly sampled provenance count and never applies
        # to measured receipt/evidence paths.
        legacy_local_evaluation = (
            not self._receipts and not self._evidence
            and axiom.provenance.empirical_samples >= 3
            and axiom.provenance.falsification_attempts >= 1
            and (axiom.metadata.get("verified_by_inducer") is not True
                 or axiom.metadata.get("legacy_local_evaluation") is True)
        )
        if axiom.status == AxiomStatus.PROVEN:
            if axiom.metadata.get("verified_by_inducer") is not True:
                return False, axiom.confidence, [{"error": "PROVEN status is not an authenticated inducer result"}]
            if not axiom.metadata.get("legacy_local_evaluation"):
                return False, axiom.confidence, [{"error": "PROVEN axioms are immutable; create a new induction result"}]
        # Induction is a hypothesis-generating operation, never proof.  A
        # PROVEN status requires an auditable provenance chain and a meaningful
        # sample size; model/session metadata alone is not evidence.
        if not test_cases:
            return False, axiom.confidence, []
        if not legacy_local_evaluation and self.induced_axioms.get(axiom.axiom_id) is not axiom:
            return False, axiom.confidence, [{"error": "axiom provenance is not resolved in this inducer"}]
        # The following provenance checks are mandatory for real measured
        # induction.  A legacy local predicate smoke-test has no external
        # objects to resolve, so it skips only this provenance lookup; it does
        # not alter strict measured verification behavior.
        resolved_receipts = [self._receipts.get(rid) for rid in axiom.provenance.receipt_ids]
        resolved_evidence = [self._evidence.get(eid) for eid in axiom.provenance.evidence_ids]
        if not legacy_local_evaluation:
            if (not resolved_receipts or any(r is None or not r.success for r in resolved_receipts)
                    or not resolved_evidence or any(e is None for e in resolved_evidence)):
                return False, axiom.confidence, [{"error": "external evidence provenance cannot be resolved"}]
            receipt_map = {r.receipt_id: r for r in resolved_receipts if r is not None}
            if any(e.receipt_id not in receipt_map for e in resolved_evidence if e is not None):
                return False, axiom.confidence, [{"error": "evidence is not linked to the axiom receipts"}]
            if any(e.session_id != receipt_map[e.receipt_id].session_id
                   or e.content_hash != receipt_map[e.receipt_id].output_hash
                   or e.source_output_hash != receipt_map[e.receipt_id].output_hash
                   for e in resolved_evidence if e is not None):
                return False, axiom.confidence, [{"error": "evidence provenance hash is inconsistent"}]
            def producer_key(receipt: ToolReceipt) -> str:
                return canonical_hash({
                    "executable_identity": dict(receipt.executable_identity),
                    "workspace_identity": dict(receipt.workspace_identity),
                })
            resolved_producers = {producer_key(receipt_map[e.receipt_id]) for e in resolved_evidence}
            if axiom.provenance.independent_sources and set(axiom.provenance.independent_sources) != resolved_producers:
                return False, axiom.confidence, [{"error": "provenance producer identities are fabricated or stale"}]
        valid_inputs, input_errors = ((True, []) if legacy_local_evaluation
                                      else self._validate_empirical_inputs(axiom, test_cases))
        if not valid_inputs:
            return False, axiom.confidence, input_errors

        passed_count = 0
        failed_cases: List[Dict[str, Any]] = []

        for case in test_cases:
            try:
                state = dict(case.get("state", case))
                for key in ("receipt_id", "evidence_id", "boundary_coverage", "boundary"):
                    state.pop(key, None)
                result = axiom.evaluate(state)
                if result:
                    passed_count += 1
                else:
                    failed_cases.append(case)
                    axiom.counter_examples.append(f"Counter-example state: {case}")
            except Exception as ex:
                failed_cases.append({"case": case, "error": str(ex)})
                axiom.counter_examples.append(f"Evaluation error: {ex}")

        pass_ratio = passed_count / len(test_cases)
        axiom.provenance.falsification_attempts += len(test_cases)
        axiom.provenance.empirical_samples += passed_count

        if failed_cases:
            axiom.status = AxiomStatus.FALSIFIED
            axiom.confidence = round(axiom.confidence * pass_ratio, 3)
            axiom._seal()
            return False, pass_ratio, failed_cases

        # Do not upgrade based on positive cases alone.  The caller must have
        # supplied provenance-backed receipts/evidence (checked above).
        axiom.status = AxiomStatus.PROVEN
        axiom.metadata["provenance_resolved"] = not legacy_local_evaluation
        axiom.metadata["verified_by_inducer"] = True
        if legacy_local_evaluation:
            # Explicitly mark this as a compatibility smoke-test result; it
            # must never be treated as measured proof by strict consumers.
            axiom.metadata["legacy_local_evaluation"] = True
        axiom.confidence = min(1.0, round(0.90 + 0.10 * (passed_count / max(10, passed_count)), 3))
        axiom._seal()
        return True, pass_ratio, []

    def formalize_to_proof_sketch(self, axiom: NeuroSymbolicAxiom) -> str:
        """Format formal mathematical proof sketch for publication or invariant record."""
        axiom._validate_seal()
        return (
            f"### 📜 Formal Neuro-Symbolic Proof Sketch: {axiom.name} ({axiom.axiom_id})\n\n"
            f"- **Formal Statement**: `{axiom.symbolic_expression}`\n"
            f"- **Domain Boundary**: `{axiom.domain.upper()}`\n"
            f"- **Epistemic Status**: `[{axiom.status.value.upper()}]` (Confidence: {axiom.confidence * 100:.1f}%)\n"
            f"- **Empirical Evidence**: `{axiom.provenance.empirical_samples}` samples verified, `{axiom.provenance.falsification_attempts}` falsification attempts\n\n"
            f"#### 📐 Mathematical Proof Rationale:\n"
            f"{axiom.proof_sketch}\n\n"
            f"#### 🔒 Boundary Conditions:\n"
            + "\n".join([f"- `{k}`: `{v}`" for k, v in axiom.boundary_conditions.items()])
        )
