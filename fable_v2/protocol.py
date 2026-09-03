"""Portable, host-neutral objects used by the Fable V2 runtime.

The protocol deliberately stores structured facts and tool receipts instead of
asking a model to self-report that it performed work.  Hosts can bind their
native tools to these objects through an adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import copy
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


def _parse_timestamp(value: str, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


@dataclass(frozen=True)
class VerificationPolicy:
    """Acceptance policy declared by the task, not by the model."""

    # The default policy requires both an objective/deterministic check and a
    # separately registered independent check. Tasks may explicitly choose a
    # narrower policy when no independent check is meaningful.
    required_verifier_classes: tuple[str, ...] = ("deterministic", "independent")
    minimum_passing_verifiers: int = 2
    require_independent: bool = True
    # ``in_process`` is an application convention, not a security boundary.
    # Production deployments should require ``process_attested`` and supply
    # results from an isolated broker.
    minimum_trust_boundary: str = "in_process"

    TRUST_BOUNDARY_RANK = {"in_process": 0, "process_attested": 1}

    def __post_init__(self) -> None:
        if self.minimum_trust_boundary not in self.TRUST_BOUNDARY_RANK:
            raise ValueError("unsupported minimum_trust_boundary")
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
    """A host-produced receipt proving invocation and captured output.

    ``success`` means the tool call completed successfully. It is not a claim
    that the output is correct or that the candidate is correct.
    """

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
        started = _parse_timestamp(self.started_at, "started_at")
        finished = _parse_timestamp(self.finished_at, "finished_at")
        if finished < started:
            raise ValueError("finished_at cannot be earlier than started_at")
        # Snapshot mutable host payloads so later caller mutation cannot change
        # what the receipt hashes or what evidence derives from it.
        object.__setattr__(self, "output", copy.deepcopy(self.output))
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))
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
    """Captured evidence integrity-bound to one successful receipt.

    Integrity binding proves provenance and content consistency only. It does
    not prove that the claim is true; a verifier must establish that.
    """

    evidence_id: str
    session_id: str
    claim: str
    kind: str
    source: str
    receipt_id: str
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content: Any = None
    source_output_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_id", "session_id", "claim", "kind", "source",
                     "receipt_id", "content_hash", "source_output_hash"):
            _required_text(getattr(self, name), name)
        object.__setattr__(self, "content", copy.deepcopy(self.content))
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))
        if canonical_hash(self.content) != self.content_hash:
            raise ValueError("content_hash does not match the evidence content")

    @property
    def integrity_bound(self) -> bool:
        """Whether provenance and content hashes agree; not claim truth."""
        return (
            canonical_hash(self.content) == self.content_hash
            and self.content_hash == self.source_output_hash
        )

    @classmethod
    def from_receipt(
        cls,
        receipt: ToolReceipt,
        *,
        evidence_id: str,
        claim: str,
        kind: str,
        source: str,
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
    # ``in_process`` describes where the result came from; it is not proof of
    # trust. Only an external broker may issue ``process_attested`` results.
    trust_boundary: str = ""
    # Commitment to the candidate plus every referenced receipt/evidence object.
    # The runtime populates this before computing ``runtime_attestation``.
    candidate_graph_hash: str = ""
    runtime_attestation: str = ""

    def __post_init__(self) -> None:
        for name in ("verification_id", "session_id", "candidate_id", "verifier"):
            _required_text(getattr(self, name), name)
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("score must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProofReceipt:
    """A deterministic proof receipt verifying an invariant or grounded claim."""

    receipt_id: str
    claim: str
    proof_type: str
    target_resource: str
    sha256_digest: str
    verified_at: str
    verifier_details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("receipt_id", "claim", "proof_type", "target_resource",
                     "sha256_digest", "verified_at"):
            _required_text(getattr(self, name), name)
        object.__setattr__(self, "verifier_details", copy.deepcopy(dict(self.verifier_details)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileChangeRecord:
    """Record of a file modification, creation, or deletion with hash tracking."""

    file_path: str
    change_type: str
    before_hash: str | None = None
    after_hash: str | None = None
    diff_summary: str = ""
    rationale: str = ""
    affected_invariants: tuple[str, ...] = ()
    timestamp: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_text(self.file_path, "file_path")
        _required_text(self.change_type, "change_type")
        for inv in self.affected_invariants:
            _required_text(inv, "affected_invariant")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualMockupSpec:
    """Specification for visual design mockups, coordinate bounds, and UI typography."""

    mockup_id: str
    concept_name: str
    aesthetic_archetype: str
    prompt: str
    image_url: str | None = None
    coordinates_data: Mapping[str, Any] = field(default_factory=dict)
    palette: tuple[str, ...] = ()
    typography: Mapping[str, str] = field(default_factory=dict)
    status: str = "draft"
    selected_by_user: bool = False
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("mockup_id", "concept_name", "aesthetic_archetype", "prompt"):
            _required_text(getattr(self, name), name)
        object.__setattr__(self, "coordinates_data", copy.deepcopy(dict(self.coordinates_data)))
        object.__setattr__(self, "typography", copy.deepcopy(dict(self.typography)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelVelocityProfile:
    """Telemetry profile tracking token throughput, tool latency, and exploration multiplier."""

    model_tier: str
    tokens_per_sec: float = 0.0
    avg_tool_latency_sec: float = 0.0
    sample_count: int = 0
    high_throughput_mode: bool = False
    exploration_multiplier: float = 1.0
    last_updated: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_text(self.model_tier, "model_tier")
        if self.tokens_per_sec < 0:
            raise ValueError("tokens_per_sec cannot be negative")
        if self.avg_tool_latency_sec < 0:
            raise ValueError("avg_tool_latency_sec cannot be negative")
        if self.sample_count < 0:
            raise ValueError("sample_count cannot be negative")
        if self.exploration_multiplier <= 0:
            raise ValueError("exploration_multiplier must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalRubricItem:
    """A granular rubric item or verification criteria pointer with target weight."""

    pointer_id: str
    description: str
    weight: float = 1.0
    verifier_command: str = ""
    satisfied: bool = False
    score: float = 0.0
    evidence_receipt_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text(self.pointer_id, "pointer_id")
        _required_text(self.description, "description")
        if self.weight < 0:
            raise ValueError("weight cannot be negative")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalRubric:
    """Pre-flight goal scoring rubric contract with target threshold (default >= 0.95)."""

    rubric_id: str
    session_id: str
    task_objective: str
    target_score: float = 0.95
    items: tuple[GoalRubricItem, ...] = ()
    current_score: float = 0.0
    status: str = "pending"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_text(self.rubric_id, "rubric_id")
        _required_text(self.session_id, "session_id")
        _required_text(self.task_objective, "task_objective")
        if not 0.0 <= self.target_score <= 1.0:
            raise ValueError("target_score must be between 0.0 and 1.0")
        if not 0.0 <= self.current_score <= 1.0:
            raise ValueError("current_score must be between 0.0 and 1.0")
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutomationPipelineSpec:
    """Specification for an autonomous generator-evaluator closed-loop pipeline."""

    pipeline_id: str
    session_id: str
    name: str
    pipeline_type: str = "closed_loop"
    generator_command: str = ""
    evaluator_command: str = ""
    target_threshold: float = 0.95
    max_iterations: int = 10
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _required_text(self.pipeline_id, "pipeline_id")
        _required_text(self.session_id, "session_id")
        _required_text(self.name, "name")
        if not 0.0 <= self.target_threshold <= 1.0:
            raise ValueError("target_threshold must be between 0.0 and 1.0")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

