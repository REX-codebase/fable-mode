"""Portable, host-neutral objects used by the Fable V2 runtime.

The protocol deliberately stores structured facts and tool receipts instead of
asking a model to self-report that it performed work.  Hosts can bind their
native tools to these objects through an adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 hash for a JSON-compatible value."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class VerificationPolicy:
    """Acceptance policy declared by the task, not by the model."""

    # The default policy requires both an objective/deterministic check and a
    # separately registered independent check. Tasks may explicitly choose a
    # narrower policy when no independent check is meaningful.
    required_verifier_classes: tuple[str, ...] = ("deterministic", "independent")
    minimum_passing_verifiers: int = 2
    require_independent: bool = True

    def __post_init__(self) -> None:
        if not self.required_verifier_classes:
            raise ValueError("verification policy must require at least one verifier class")
        if self.minimum_passing_verifiers < 1:
            raise ValueError("minimum_passing_verifiers must be at least 1")
        for item in self.required_verifier_classes:
            _required_text(item, "verifier class")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskSpec:
    """The contract that defines what a run must accomplish."""

    task_id: str
    objective: str
    constraints: tuple[str, ...] = ()
    definition_of_done: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    verification_policy: VerificationPolicy = field(default_factory=VerificationPolicy)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text(self.task_id, "task_id")
        _required_text(self.objective, "objective")
        if not self.definition_of_done:
            raise ValueError("definition_of_done must contain at least one condition")
        for item in (*self.constraints, *self.definition_of_done,
                     *self.required_capabilities, *self.required_evidence):
            _required_text(item, "task contract item")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolReceipt:
    """A host-produced receipt proving that a capability was invoked."""

    receipt_id: str
    session_id: str
    capability: str
    tool_name: str
    input_hash: str
    output_hash: str
    success: bool
    started_at: str
    finished_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    output: Any = None

    def __post_init__(self) -> None:
        for name in ("receipt_id", "session_id", "capability", "tool_name",
                     "input_hash", "output_hash", "started_at", "finished_at"):
            _required_text(getattr(self, name), name)
        if canonical_hash(self.output) != self.output_hash:
            raise ValueError("output_hash does not match the actual receipt output")

    @classmethod
    def from_result(
        cls,
        *,
        receipt_id: str,
        session_id: str,
        capability: str,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        success: bool,
        started_at: str | None = None,
        finished_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolReceipt":
        start = started_at or utc_now()
        finish = finished_at or start
        return cls(
            receipt_id=receipt_id,
            session_id=session_id,
            capability=capability,
            tool_name=tool_name,
            input_hash=canonical_hash(tool_input),
            output_hash=canonical_hash(tool_output),
            success=bool(success),
            started_at=start,
            finished_at=finish,
            metadata=metadata or {},
            output=tool_output,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    """Evidence whose content is integrity-bound to one successful receipt."""

    evidence_id: str
    session_id: str
    claim: str
    kind: str
    source: str
    receipt_id: str
    content_hash: str
    verified: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content: Any = None
    source_output_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "session_id", "claim", "kind", "source",
                     "receipt_id", "content_hash", "source_output_hash"):
            _required_text(getattr(self, name), name)
        if canonical_hash(self.content) != self.content_hash:
            raise ValueError("content_hash does not match the evidence content")

    @classmethod
    def from_receipt(
        cls,
        receipt: ToolReceipt,
        *,
        evidence_id: str,
        claim: str,
        kind: str,
        source: str,
        verified: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Evidence":
        """Create full-output evidence directly from a host receipt.

        Keeping the receipt output in the content-addressed evidence object
        makes the integrity relationship checkable. Large-output adapters can
        replace ``content`` with a content-addressed blob in a later version.
        """
        if not receipt.success:
            raise ValueError("evidence must be derived from a successful receipt")
        return cls(
            evidence_id=evidence_id,
            session_id=receipt.session_id,
            claim=claim,
            kind=kind,
            source=source,
            receipt_id=receipt.receipt_id,
            content_hash=receipt.output_hash,
            verified=verified,
            metadata=metadata or {},
            content=receipt.output,
            source_output_hash=receipt.output_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    """One independently generated solution or trajectory."""

    candidate_id: str
    session_id: str
    approach: str
    artifact: Any
    receipt_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("candidate_id", "session_id", "approach"):
            _required_text(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    """A runtime-attested verifier result.

    The attestation and candidate hash are populated by ``FableRun`` after a
    registered verifier is executed. Callers must not construct a passing
    result and submit it directly to the run.
    """

    verification_id: str
    session_id: str
    candidate_id: str
    verifier: str
    passed: bool
    reasons: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    verifier_class: str = ""
    candidate_hash: str = ""
    inspected_candidate: bool = False
    independent: bool = False
    trusted: bool = False
    runtime_attestation: str = ""

    def __post_init__(self) -> None:
        for name in ("verification_id", "session_id", "candidate_id", "verifier"):
            _required_text(getattr(self, name), name)
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("score must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
