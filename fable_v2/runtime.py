"""Evidence-gated, host-neutral Fable V2 runtime.

This module is intentionally model-agnostic.  It does not pretend that a
prompt or MCP call makes a result correct; it provides the state machine and
acceptance gates that a host adapter and verifier must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from .protocol import Candidate, Evidence, TaskSpec, ToolReceipt, VerificationResult, utc_now


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
        if evidence.evidence_id in self.evidence:
            raise ValueError(f"duplicate evidence: {evidence.evidence_id}")
        self.evidence[evidence.evidence_id] = evidence
        self._event("evidence_attached", evidence_id=evidence.evidence_id,
                    receipt_id=evidence.receipt_id)

    def record_verification(self, result: VerificationResult) -> None:
        if result.session_id != self.session_id:
            raise ValueError("verification belongs to a different session")
        if result.candidate_id not in self.candidates:
            raise ValueError("verification references an unknown candidate")
        if result.verification_id in self.verifications:
            raise ValueError(f"duplicate verification: {result.verification_id}")
        unknown_evidence = [eid for eid in result.evidence_ids if eid not in self.evidence]
        if unknown_evidence:
            raise ValueError(f"verification references unknown evidence: {unknown_evidence}")
        self.state = RunState.VERIFYING
        self.verifications[result.verification_id] = result
        self._event("verification_recorded", verification_id=result.verification_id,
                    candidate_id=result.candidate_id, passed=result.passed)

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
                if v.candidate_id == candidate_id and v.passed]

    def finalize(self, candidate_id: str) -> Candidate:
        if candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate: {candidate_id}")
        missing = self.missing_requirements(candidate_id)
        if missing:
            self.state = RunState.REJECTED
            self._event("finalization_rejected", candidate_id=candidate_id, missing=missing)
            raise PermissionError("finalization rejected: " + "; ".join(missing))
        if not self.passed_verifications(candidate_id):
            self.state = RunState.REJECTED
            self._event("finalization_rejected", candidate_id=candidate_id,
                        missing=["a passing independent verification"])
            raise PermissionError("finalization rejected: no passing verification")
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
            "missing_requirements": self.missing_requirements(self.final_candidate_id),
            "final_candidate_id": self.final_candidate_id,
        }


def new_run(session_id: str, task: TaskSpec) -> FableRun:
    run = FableRun(session_id=session_id, task=task)
    run.start()
    return run
