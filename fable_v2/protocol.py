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
import math
from typing import Any, Mapping
from enum import Enum


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


CANONICAL_SERIALIZATION_VERSION = "fable-json-c14n-v1"
MAX_TEXT_FIELD = 16_384
MAX_COLLECTION_ITEMS = 10_000
CANONICAL_HASH_VECTORS = (
    {"value": {"a": 1, "b": "é"}, "canonical": '{"a":1,"b":"é"}',
     "sha256": "09ad9fd2fb648cb2f62141215828ea00a62c299db05d20aa9ade2f527a301cc6"},
    {"value": {"array": [1, True, None], "nested": {"a": "x"}},
     "canonical": '{"array":[1,true,null],"nested":{"a":"x"}}',
     "sha256": "e7ca8c5b02ccfc4bb763dc948bbd95f984138477d708ab6f77582f0380d3c7cc"},
)

def _validate_json_value(value: Any, field_name: str = "value") -> None:
    """Reject values that Python's permissive JSON encoder would normalize.

    JSON objects have string keys and JSON has no representation for sets,
    bytes, or non-finite IEEE-754 values.  Keeping this check recursive is
    important: a hostile value can otherwise hide several levels down in
    receipt/candidate metadata or System 3 telemetry.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field_name} contains a non-string JSON object key")
            _validate_json_value(child, f"{field_name}.{key}")
        return
    # Tuples are retained for the protocol's typed collection fields and are
    # encoded as arrays by json.dumps. Sets/bytes/custom objects are not JSON.
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{field_name}[{index}]")
        return
    raise TypeError(f"{field_name} contains a non-standard JSON value: {type(value).__name__}")


def canonical_dumps(value: Any) -> str:
    _validate_json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()

def _strict_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")
    return value

def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be a finite number")
    return float(value)


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    value = value.strip()
    if len(value) > MAX_TEXT_FIELD:
        raise ValueError(f"{field_name} exceeds the maximum length")
    return value


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


class VerificationStatus(str, Enum):
    """The three outcomes a verifier may honestly report.

    ``UNKNOWN`` is intentionally distinct from failure: it means the check
    could not establish either truth or falsity and must not be upgraded to a
    pass by aggregation code.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


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
    require_evidence_diversity: bool = False
    minimum_evidence_sources: int = 2

    TRUST_BOUNDARY_RANK = {"in_process": 0, "process_attested": 1}

    def __post_init__(self) -> None:
        if self.minimum_trust_boundary not in self.TRUST_BOUNDARY_RANK:
            raise ValueError("unsupported minimum_trust_boundary")
        if not self.required_verifier_classes:
            raise ValueError("verification policy must require at least one verifier class")
        _strict_bool(self.require_independent, "require_independent")
        _strict_bool(self.require_evidence_diversity, "require_evidence_diversity")
        if self.minimum_evidence_sources < 1 or self.minimum_evidence_sources > MAX_COLLECTION_ITEMS:
            raise ValueError("minimum_evidence_sources is out of bounds")
        if self.minimum_passing_verifiers < 1:
            raise ValueError("minimum_passing_verifiers must be at least 1")
        for item in self.required_verifier_classes:
            _required_text(item, "verifier class")
        if len(set(self.required_verifier_classes)) != len(self.required_verifier_classes):
            raise ValueError("verification policy contains duplicate verifier classes")

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


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
        for collection in (self.constraints, self.definition_of_done, self.required_capabilities, self.required_evidence):
            if len(collection) > MAX_COLLECTION_ITEMS:
                raise ValueError("task contract contains too many items")
            for item in collection:
                _required_text(item, "task contract item")
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(metadata_copy, "task.metadata")
        object.__setattr__(self, "metadata", metadata_copy)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


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
    canonicalization: str = CANONICAL_SERIALIZATION_VERSION
    executable_identity: Mapping[str, Any] = field(default_factory=dict)
    workspace_identity: Mapping[str, Any] = field(default_factory=dict)
    # Receipt provenance is deliberately explicit.  ``self_minted`` is the
    # safe default for objects constructed by application code; only a host or
    # external boundary may mark a receipt as trusted.  This is a provenance
    # classification, not a cryptographic signature.
    trust_boundary: str = "self_minted"

    TRUSTED_BOUNDARIES = frozenset({"host", "external", "process_attested"})
    ALL_BOUNDARIES = TRUSTED_BOUNDARIES | {"self_minted"}

    def __post_init__(self) -> None:
        for name in ("receipt_id", "session_id", "capability", "tool_name",
                     "input_hash", "output_hash", "started_at", "finished_at"):
            _required_text(getattr(self, name), name)
        if self.canonicalization != CANONICAL_SERIALIZATION_VERSION:
            raise ValueError("unsupported canonicalization policy")
        if self.trust_boundary not in self.ALL_BOUNDARIES:
            raise ValueError("unsupported receipt trust boundary")
        _strict_bool(self.success, "success")
        started = _parse_timestamp(self.started_at, "started_at")
        finished = _parse_timestamp(self.finished_at, "finished_at")
        if finished < started:
            raise ValueError("finished_at cannot be earlier than started_at")
        # Snapshot mutable host payloads so later caller mutation cannot change
        # what the receipt hashes or what evidence derives from it.
        output_copy = copy.deepcopy(self.output)
        metadata_copy = copy.deepcopy(dict(self.metadata))
        executable_copy = copy.deepcopy(dict(self.executable_identity))
        workspace_copy = copy.deepcopy(dict(self.workspace_identity))
        _validate_json_value(output_copy, "receipt.output")
        _validate_json_value(metadata_copy, "receipt.metadata")
        _validate_json_value(executable_copy, "receipt.executable_identity")
        _validate_json_value(workspace_copy, "receipt.workspace_identity")
        object.__setattr__(self, "output", output_copy)
        object.__setattr__(self, "metadata", metadata_copy)
        object.__setattr__(self, "executable_identity", executable_copy)
        object.__setattr__(self, "workspace_identity", workspace_copy)
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
        executable_identity: Mapping[str, Any] | None = None,
        workspace_identity: Mapping[str, Any] | None = None,
        trust_boundary: str = "self_minted",
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
            success=_strict_bool(success, "success"),
            started_at=start,
            finished_at=finish,
            metadata=metadata or {},
            output=tool_output,
            executable_identity=executable_identity or {},
            workspace_identity=workspace_identity or {},
            trust_boundary=trust_boundary,
        )

    @property
    def trusted(self) -> bool:
        return self.trust_boundary in self.TRUSTED_BOUNDARIES

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


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
        content_copy = copy.deepcopy(self.content)
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(content_copy, "evidence.content")
        _validate_json_value(metadata_copy, "evidence.metadata")
        object.__setattr__(self, "content", content_copy)
        object.__setattr__(self, "metadata", metadata_copy)
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
        return copy.deepcopy(asdict(self))


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
        artifact_copy = copy.deepcopy(self.artifact)
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(artifact_copy, "candidate.artifact")
        _validate_json_value(metadata_copy, "candidate.metadata")
        object.__setattr__(self, "artifact", artifact_copy)
        if len(self.receipt_ids) > MAX_COLLECTION_ITEMS or len(self.evidence_ids) > MAX_COLLECTION_ITEMS:
            raise ValueError("candidate references too many objects")
        object.__setattr__(self, "receipt_ids", tuple(_required_text(x, "receipt_id") for x in self.receipt_ids))
        object.__setattr__(self, "evidence_ids", tuple(_required_text(x, "evidence_id") for x in self.evidence_ids))
        object.__setattr__(self, "metadata", metadata_copy)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


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
    # New verifier-slice fields are appended to preserve positional
    # compatibility with V1/V2 callers that construct this record directly.
    status: VerificationStatus | str = ""
    claim_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    counterexample_ids: tuple[str, ...] = ()
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    mutation_detection_rate: float | None = None
    # Scope and claim/provenance commitments are part of the verdict identity.
    # They are appended to preserve positional compatibility with older callers.
    scope: str = ""

    def __post_init__(self) -> None:
        for name in ("verification_id", "session_id", "candidate_id", "verifier"):
            _required_text(getattr(self, name), name)
        if self.scope:
            _required_text(self.scope, "scope")
        elif not isinstance(self.scope, str):
            raise TypeError("scope must be a string")
        if self.score is not None:
            score = _finite_number(self.score, "score")
            if not 0 <= score <= 1:
                raise ValueError("score must be between 0 and 1")
        _strict_bool(self.passed, "passed")
        # Empty status is the legacy representation; normalize it so every
        # newly-created record has an explicit three-valued interpretation.
        raw_status = self.status.value if isinstance(self.status, VerificationStatus) else self.status
        raw_status = raw_status or (VerificationStatus.PASS.value if self.passed else VerificationStatus.FAIL.value)
        try:
            normalized_status = VerificationStatus(str(raw_status).upper())
        except ValueError as exc:
            raise ValueError("status must be PASS, FAIL, or UNKNOWN") from exc
        if (normalized_status is VerificationStatus.PASS) != self.passed:
            # PermissionError preserves the runtime's existing tamper/error
            # contract when a serialized verdict is edited before restore.
            raise PermissionError("passed must agree with status")
        object.__setattr__(self, "status", normalized_status)
        for field_name in ("false_positive_rate", "false_negative_rate", "mutation_detection_rate"):
            value = getattr(self, field_name)
            if value is not None:
                rate = _finite_number(value, field_name)
                if not 0 <= rate <= 1:
                    raise ValueError(f"{field_name} must be between 0 and 1")
        claim_ids = tuple(_required_text(x, "claim_id") for x in self.claim_ids)
        provenance_ids = tuple(_required_text(x, "provenance_id") for x in self.provenance_ids)
        counterexample_ids = tuple(_required_text(x, "counterexample_id") for x in self.counterexample_ids)
        if len(claim_ids) > MAX_COLLECTION_ITEMS or len(provenance_ids) > MAX_COLLECTION_ITEMS:
            raise ValueError("verification references too many objects")
        object.__setattr__(self, "claim_ids", claim_ids)
        object.__setattr__(self, "provenance_ids", provenance_ids)
        object.__setattr__(self, "counterexample_ids", counterexample_ids)
        reasons_copy = tuple(self.reasons)
        _validate_json_value(reasons_copy, "verification.reasons")
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(metadata_copy, "verification.metadata")
        object.__setattr__(self, "reasons", reasons_copy)
        object.__setattr__(self, "evidence_ids", tuple(_required_text(x, "evidence_id") for x in self.evidence_ids))
        object.__setattr__(self, "metadata", metadata_copy)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

# Typed System 3 lifecycle records.  These are intentionally separate from
# ToolReceipt: hypotheses cannot masquerade as actual execution outcomes.
_BOILERPLATE_PREDICTION_TEXT = {
    "ok", "done", "success", "it works", "should work", "looks good",
    "no issues", "pass", "passed", "works", "true", "yes",
}


def _meaningful(value: Any, field_name: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name} must be a non-empty observation")
    if isinstance(value, (Mapping, list, tuple, set)) and not value:
        raise ValueError(f"{field_name} must be a non-empty observation")
    canonical_hash(value)  # rejects non-finite and non-JSON values early
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Prediction:
    """A hash-bound, falsifiable System 3 prediction for one action."""
    prediction_id: str
    run_id: str = ""
    candidate_id: str = ""
    action: str = ""
    observation: Any = None
    predicted_outcome: Any = None
    confidence: float = 0.0
    falsification_condition: str = ""
    created_at: str = field(default_factory=utc_now)
    observation_hash: str = ""
    predicted_outcome_hash: str = ""
    policy_id: str = ""
    belief_revision: str = ""
    record_hash: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    session_id: str = ""

    def __post_init__(self) -> None:
        run_id = self.run_id or self.session_id
        object.__setattr__(self, "run_id", run_id)
        for name in ("prediction_id", "run_id", "candidate_id", "action", "falsification_condition"):
            _required_text(getattr(self, name), name)
        if self.session_id and self.session_id != self.run_id:
            raise ValueError("session_id and run_id must agree")
        _parse_timestamp(self.created_at, "created_at")
        confidence = _finite_number(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.falsification_condition.strip().lower() in _BOILERPLATE_PREDICTION_TEXT:
            raise ValueError("falsification_condition must be specific and falsifiable")
        observation = _meaningful(self.observation, "observation")
        predicted = _meaningful(self.predicted_outcome, "predicted_outcome")
        if isinstance(predicted, str) and predicted.strip().lower() in _BOILERPLATE_PREDICTION_TEXT:
            raise ValueError("predicted_outcome must be specific, not boilerplate")
        obs_hash, pred_hash = canonical_hash(observation), canonical_hash(predicted)
        if self.observation_hash and self.observation_hash != obs_hash:
            raise ValueError("observation_hash does not match observation")
        if self.predicted_outcome_hash and self.predicted_outcome_hash != pred_hash:
            raise ValueError("predicted_outcome_hash does not match predicted_outcome")
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "predicted_outcome", predicted)
        object.__setattr__(self, "observation_hash", obs_hash)
        object.__setattr__(self, "predicted_outcome_hash", pred_hash)
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(metadata_copy, "prediction.metadata")
        if "success" in metadata_copy:
            raise PermissionError("prediction success must be tested by an actual receipt")
        object.__setattr__(self, "metadata", metadata_copy)
        object.__setattr__(self, "session_id", self.run_id)
        payload = self.to_dict(); payload["record_hash"] = ""
        expected = canonical_hash(payload)
        if self.record_hash and self.record_hash != expected:
            raise ValueError("prediction record_hash does not match record")
        object.__setattr__(self, "record_hash", expected)
        object.__setattr__(self, "session_id", self.run_id)

    @property
    def timestamp(self) -> str:
        return self.created_at

    @property
    def predicted_value(self) -> Any:
        return self.predicted_outcome

    @property
    def falsification(self) -> str:
        return self.falsification_condition

    @property
    def hash(self) -> str:
        return self.record_hash

    @property
    def prediction_hash(self) -> str:
        return self.record_hash

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Prediction":
        return cls(**dict(data))


@dataclass(frozen=True)
class Outcome:
    """An actual receipt-bound observation used to update a prediction."""
    outcome_id: str
    run_id: str = ""
    candidate_id: str = ""
    prediction_id: str = ""
    action: str = ""
    receipt_id: str = ""
    observed_outcome: Any = None
    observed_at: str = field(default_factory=utc_now)
    outcome_hash: str = ""
    receipt_output_hash: str = ""
    record_hash: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    success: Any = None
    session_id: str = ""

    def __post_init__(self) -> None:
        run_id = self.run_id or self.session_id
        object.__setattr__(self, "run_id", run_id)
        for name in ("outcome_id", "run_id", "candidate_id", "prediction_id", "action", "receipt_id"):
            _required_text(getattr(self, name), name)
        if self.session_id and self.session_id != self.run_id:
            raise ValueError("session_id and run_id must agree")
        _parse_timestamp(self.observed_at, "observed_at")
        metadata_copy = copy.deepcopy(dict(self.metadata))
        _validate_json_value(metadata_copy, "outcome.metadata")
        if self.success is not None or "success" in metadata_copy:
            raise PermissionError("Outcome success must come from the actual ToolReceipt")
        observed = _meaningful(self.observed_outcome, "observed_outcome")
        observed_hash = canonical_hash(observed)
        if self.outcome_hash and self.outcome_hash != observed_hash:
            raise ValueError("outcome_hash does not match observed_outcome")
        if self.receipt_output_hash and self.receipt_output_hash != observed_hash:
            raise ValueError("receipt_output_hash does not match observed_outcome")
        object.__setattr__(self, "observed_outcome", observed)
        object.__setattr__(self, "outcome_hash", observed_hash)
        object.__setattr__(self, "receipt_output_hash", observed_hash)
        object.__setattr__(self, "metadata", metadata_copy)
        object.__setattr__(self, "session_id", self.run_id)
        payload = self.to_dict(); payload["record_hash"] = ""
        expected = canonical_hash(payload)
        if self.record_hash and self.record_hash != expected:
            raise ValueError("outcome record_hash does not match record")
        object.__setattr__(self, "record_hash", expected)
        object.__setattr__(self, "session_id", self.run_id)

    @property
    def timestamp(self) -> str:
        return self.observed_at

    @property
    def actual_outcome(self) -> Any:
        return self.observed_outcome

    @property
    def hash(self) -> str:
        return self.record_hash

    @property
    def integrity_hash(self) -> str:
        return self.record_hash

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Outcome":
        return cls(**dict(data))
