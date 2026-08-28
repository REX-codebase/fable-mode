"""Evidence-gated, host-neutral Fable V2 runtime.

This module is intentionally model-agnostic.  It does not pretend that a
prompt or MCP call makes a result correct; it provides the state machine and
acceptance gates that a host adapter and verifier must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import hmac
import secrets
from typing import Any, Callable, Iterable, Protocol

from .protocol import (
    Candidate,
    Evidence,
    TaskSpec,
    ToolReceipt,
    VerificationResult,
    canonical_hash,
    utc_now,
)


class RegisteredVerifier(Protocol):
    """A verifier registered by trusted runtime code.

    ``verify`` must inspect the supplied candidate and return an un-attested
    result. The runtime stamps its identity and candidate hash afterwards.
    """

    name: str
    verifier_class: str
    independent: bool
    trusted: bool

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
    _attestation_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32),
                                       repr=False)

    def _event(self, event_type: str, **data: Any) -> None:
        self.events.append({"type": event_type, "at": utc_now(), **data})

    def start(self) -> None:
        if self.state is not RunState.CREATED:
            raise RuntimeError(f"run is already {self.state.value}")
        self.state = RunState.ACTIVE
        self._event("run_started", session_id=self.session_id)

    def record_receipt(self, receipt: ToolReceipt) -> None:
        if receipt.session_id != self.session_id:
            raise ValueError("tool receipt belongs to a different session")
        if receipt.receipt_id in self.receipts:
            raise ValueError(f"duplicate receipt: {receipt.receipt_id}")
        self.receipts[receipt.receipt_id] = receipt
        self._event("tool_receipt", receipt_id=receipt.receipt_id,
                    capability=receipt.capability, success=receipt.success)

    def register_candidate(self, candidate: Candidate) -> None:
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
        self.candidates[candidate.candidate_id] = candidate
        self._event("candidate_registered", candidate_id=candidate.candidate_id)

    def attach_evidence(self, evidence: Evidence) -> None:
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
        if evidence.evidence_id in self.evidence:
            raise ValueError(f"duplicate evidence: {evidence.evidence_id}")
        self.evidence[evidence.evidence_id] = evidence
        self._event("evidence_attached", evidence_id=evidence.evidence_id,
                    receipt_id=evidence.receipt_id)

    def _record_attested_verification(self, result: VerificationResult) -> None:
        """Store a result after ``execute_verifier`` has attested it."""
        if result.session_id != self.session_id:
            raise ValueError("verification belongs to a different session")
        candidate = self.candidates.get(result.candidate_id)
        if candidate is None:
            raise ValueError("verification references an unknown candidate")
        if result.verification_id in self.verifications:
            raise ValueError(f"duplicate verification: {result.verification_id}")
        if not result.trusted or not result.inspected_candidate:
            raise PermissionError("verification must be produced by a trusted registered verifier")
        if result.candidate_hash != canonical_hash(candidate.artifact):
            raise PermissionError("verification was not produced for the current candidate artifact")
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
        self.state = RunState.VERIFYING
        self.verifications[result.verification_id] = result
        self._event("verification_recorded", verification_id=result.verification_id,
                    candidate_id=result.candidate_id, verifier=result.verifier,
                    verifier_class=result.verifier_class, passed=result.passed)

    def record_verification(self, result: VerificationResult) -> None:
        """Reject untrusted/model-supplied results.

        Results must come from ``execute_verifier`` so the runtime can bind the
        verdict to a registered verifier and the exact candidate artifact.
        """
        raise PermissionError(
            "direct verification recording is disabled; execute a registered verifier"
        )

    def _attestation(self, result: VerificationResult) -> str:
        payload = "|".join((result.verification_id, result.candidate_id,
                             result.candidate_hash, result.verifier,
                             result.verifier_class))
        return hmac.new(self._attestation_secret, payload.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def execute_verifier(self, verifier: RegisteredVerifier, candidate_id: str) -> VerificationResult:
        """Run and attest a registered verifier against one exact candidate.

        Trust and independence are properties of runtime registration, never
        free-form fields supplied by a model-facing result.
        """
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        if not getattr(verifier, "trusted", False):
            raise PermissionError(f"verifier is not trusted: {getattr(verifier, 'name', '')}")
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
        result = replace(
            raw,
            verifier=getattr(verifier, "name", raw.verifier),
            verifier_class=verifier_class,
            candidate_hash=canonical_hash(candidate.artifact),
            inspected_candidate=True,
            independent=bool(getattr(verifier, "independent", False)),
            trusted=True,
        )
        result = replace(result, runtime_attestation=self._attestation(result))
        self._record_attested_verification(result)
        return result

    def successful_capabilities(self) -> set[str]:
        return {r.capability for r in self.receipts.values() if r.success}

    def missing_requirements(self, candidate_id: str | None = None) -> list[str]:
        missing: list[str] = []
        used = self.successful_capabilities()
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
                if v.candidate_id == candidate_id and v.passed and v.trusted
                and v.inspected_candidate]

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
        return missing

    def finalize(self, candidate_id: str) -> Candidate:
        if candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate: {candidate_id}")
        missing = self.missing_requirements(candidate_id) + self.verification_requirements(candidate_id)
        if missing:
            self.state = RunState.REJECTED
            self._event("finalization_rejected", candidate_id=candidate_id, missing=missing)
            raise PermissionError("finalization rejected: " + "; ".join(missing))
        self.final_candidate_id = candidate_id
        self.state = RunState.FINALIZED
        self._event("run_finalized", candidate_id=candidate_id)
        return self.candidates[candidate_id]

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
        }


def new_run(session_id: str, task: TaskSpec) -> FableRun:
    run = FableRun(session_id=session_id, task=task)
    run.start()
    return run
