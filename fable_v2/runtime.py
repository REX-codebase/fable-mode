"""Evidence-gated, host-neutral Fable V2 runtime.

This module is intentionally model-agnostic.  It does not pretend that a
prompt or MCP call makes a result correct; it provides the state machine and
acceptance gates that a host adapter and verifier must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
import copy
import hashlib
import hmac
import secrets
import threading
from typing import Any, Iterable, Mapping, Protocol, Callable


class _FrozenDict(dict):
    """Deeply immutable dict used for terminal public snapshots."""
    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        return {copy.deepcopy(k, memo): copy.deepcopy(v, memo) for k, v in self.items()}
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("terminal run snapshot is immutable")
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


class _FrozenList(list):
    """Deeply immutable list used for terminal public snapshots."""
    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        return [copy.deepcopy(v, memo) for v in self]
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("terminal run snapshot is immutable")
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = reverse = sort = _immutable


def _freeze_snapshot(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        clone = copy.copy(value)
        for item in fields(value):
            object.__setattr__(clone, item.name, _freeze_snapshot(getattr(value, item.name)))
        return clone
    if isinstance(value, dict):
        return _FrozenDict({k: _freeze_snapshot(v) for k, v in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_snapshot(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze_snapshot(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze_snapshot(v) for v in value)
    return value

from .protocol import (
    Candidate,
    Evidence,
    Prediction,
    Outcome,
    TaskSpec,
    ToolReceipt,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
    canonical_hash,
    utc_now,
    _parse_timestamp,
)
from .verifiers import (
    ClaimGraph, Counterexample, CounterexampleStore, ThreeValuedAdjudicator,
    VerifierPlanner, Adjudication,
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
from .system3.free_energy import prediction_error, revise_belief, policy_revision


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


class _VerifierResultAdapter:
    """Planner view of an already executed, runtime-attested result."""
    def __init__(self, result: VerificationResult) -> None:
        self.result = result
        self.name = result.verifier
        self.verifier_class = result.verifier_class
        self.independent = result.independent
        self.trust_boundary = result.trust_boundary
        self.claim_ids = result.claim_ids
        self.claims_supported = result.claim_ids
        self.uncertainty = 0.0
        self.expected_information_gain = 1.0
        self.cost = 1.0

    def verify(self, candidate: Candidate) -> VerificationResult:
        return self.result


# Deliberately explicit: no authenticated persisted self-model is currently
# implemented, so state is never adapted or trusted across sessions.
CROSS_SESSION_ADAPTATION_IMPLEMENTED = False


class RunState(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    VERIFYING = "verifying"
    FINALIZED = "finalized"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ProcessAttestation:
    """Externally supplied statement binding a verdict to a measured process.

    This object is intentionally not self-authenticating.  ``record_...``
    requires a separately configured verifier and verification material from a
    trusted channel; absent that verifier the runtime fails closed.
    """
    attestation_id: str
    session_id: str
    candidate_id: str
    verifier: str
    verifier_class: str
    passed: bool
    candidate_hash: str
    candidate_graph_hash: str
    evidence_ids: tuple[str, ...] = ()
    receipt_id: str = ""
    executable_identity: Mapping[str, Any] = field(default_factory=dict)
    workspace_identity: Mapping[str, Any] = field(default_factory=dict)
    input_hash: str = ""
    output_hash: str = ""
    issued_at: str = field(default_factory=utc_now)
    signature: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # These fields are signed as part of payload(); a signature over only the
    # candidate hash is insufficient to bind the adjudicated statement.
    claim_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    counterexample_ids: tuple[str, ...] = ()
    independent: bool = False
    scope: str = ""

    def __post_init__(self) -> None:
        for name in ("attestation_id", "session_id", "candidate_id", "verifier",
                     "verifier_class", "candidate_hash", "candidate_graph_hash",
                     "receipt_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if type(self.passed) is not bool:
            raise TypeError("passed must be a boolean")
        if type(self.independent) is not bool:
            raise TypeError("independent must be a boolean")
        if self.scope and (not isinstance(self.scope, str) or not self.scope.strip()):
            raise ValueError("scope must be a non-empty string when supplied")
        if any(len(getattr(self, field_name)) > 10000
               for field_name in ("evidence_ids", "claim_ids", "provenance_ids", "counterexample_ids")):
            raise ValueError("attestation contains too many references")
        object.__setattr__(self, "evidence_ids", tuple(str(x) for x in self.evidence_ids))
        object.__setattr__(self, "claim_ids", tuple(str(x) for x in self.claim_ids))
        object.__setattr__(self, "provenance_ids", tuple(str(x) for x in self.provenance_ids))
        object.__setattr__(self, "counterexample_ids", tuple(str(x) for x in self.counterexample_ids))
        for field_name in ("claim_ids", "provenance_ids", "counterexample_ids"):
            if any(not item.strip() for item in getattr(self, field_name)):
                raise ValueError(f"{field_name} cannot contain empty IDs")
        object.__setattr__(self, "executable_identity", copy.deepcopy(dict(self.executable_identity)))
        object.__setattr__(self, "workspace_identity", copy.deepcopy(dict(self.workspace_identity)))
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def payload(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("signature", None)
        return data

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "attestation_id": self.attestation_id, "session_id": self.session_id,
            "candidate_id": self.candidate_id, "verifier": self.verifier,
            "verifier_class": self.verifier_class, "passed": self.passed,
            "candidate_hash": self.candidate_hash,
            "candidate_graph_hash": self.candidate_graph_hash,
            "evidence_ids": list(self.evidence_ids), "receipt_id": self.receipt_id,
            "executable_identity": dict(self.executable_identity),
            "workspace_identity": dict(self.workspace_identity),
            "input_hash": self.input_hash, "output_hash": self.output_hash,
            "issued_at": self.issued_at, "signature": self.signature,
            "metadata": dict(self.metadata),
            "claim_ids": list(self.claim_ids),
            "provenance_ids": list(self.provenance_ids),
            "counterexample_ids": list(self.counterexample_ids),
            "independent": self.independent,
            "scope": self.scope,
        })

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProcessAttestation":
        values = dict(data)
        values["evidence_ids"] = tuple(values.get("evidence_ids", ()))
        return cls(**values)


class ProcessAttestationVerifier(Protocol):
    def verify(self, attestation: ProcessAttestation, verification_material: Any) -> bool:
        """Verify externally supplied process identity/signature material."""


class CheckpointAuthenticator(Protocol):
    def sign(self, payload: Mapping[str, Any]) -> str:
        ...

    def verify(self, payload: Mapping[str, Any], signature: str) -> bool:
        ...


class HMACCheckpointAuthenticator:
    """External checkpoint authenticator; its key is never part of a checkpoint."""
    def __init__(self, key: bytes):
        if not isinstance(key, bytes) or len(key) < 16:
            raise ValueError("checkpoint key must be at least 128 bits")
        self._key = bytes(key)

    def sign(self, payload: Mapping[str, Any]) -> str:
        return hmac.new(self._key, canonical_hash(payload).encode("ascii"), hashlib.sha256).hexdigest()

    def verify(self, payload: Mapping[str, Any], signature: str) -> bool:
        if not isinstance(signature, str):
            return False
        expected = self.sign(payload)
        return hmac.compare_digest(signature, expected)


class HMACProcessAttestationVerifier:
    """Reference verifier for a host-controlled signed attestation channel."""
    def __init__(self, key: bytes):
        if not isinstance(key, bytes) or len(key) < 16:
            raise ValueError("attestation key must be at least 128 bits")
        self._key = bytes(key)

    def verify(self, attestation: ProcessAttestation, verification_material: Any) -> bool:
        supplied = verification_material
        if isinstance(supplied, Mapping):
            supplied = supplied.get("signature")
        supplied = supplied or attestation.signature
        if not isinstance(supplied, str):
            return False
        expected = hmac.new(self._key, canonical_hash(attestation.payload()).encode("ascii"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)


@dataclass
class FableRun:
    """A single auditable task run."""

    session_id: str
    task: TaskSpec
    state: RunState = RunState.CREATED
    started_at: str = field(default_factory=utc_now)
    # Legacy tuple/boolean verifier adapters remain available only when this
    # explicit compatibility switch is enabled. Strict claim adjudication is
    # the default and cannot be inferred from a verifier's output shape.
    compatibility_mode: bool = False
    receipts: dict[str, ToolReceipt] = field(default_factory=dict)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    verifications: dict[str, VerificationResult] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    final_candidate_id: str | None = None
    invalidated_verifiers: dict[str, str] = field(default_factory=dict)
    # System 3 Meta-Cognitive Deliberation & Invariant Tracking
    system3_free_energy: dict[str, Any] = field(default_factory=dict)
    system3_active_inference: dict[str, Any] = field(default_factory=dict)
    system3_kripke_invariants: dict[str, Any] = field(default_factory=dict)
    system3_hyperbolic_embeddings: dict[str, Any] = field(default_factory=dict)
    system3_meta_cycles: list[dict[str, Any]] = field(default_factory=list)
    # Auditable observe -> predict -> act -> outcome -> update records.
    system3_observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    predictions: dict[str, Prediction] = field(default_factory=dict)
    system3_actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    system3_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    system3_beliefs: dict[str, dict[str, Any]] = field(default_factory=dict)
    system3_policy_revisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    triz_repair_recommendations: list[dict[str, Any]] = field(default_factory=list)
    # Configured only by the host that owns the external attestation channel.
    process_attestation_verifier: ProcessAttestationVerifier | None = field(
        default=None, repr=False, compare=False
    )
    _artifact_commits: dict[str, tuple[str, str]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _system3_commits: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    # Process-local monotonic revocation ledger. It complements the committed
    # event chain so deleting either the public map or an event cannot restore
    # a verifier during this run.
    _revocation_ledger: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    _system3_loop_commits: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    _process_attestation_materials: dict[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    _attestation_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32),
                                       repr=False)
    # A deserialized run is observationally useful but not trusted unless the
    # complete checkpoint was authenticated by an external key.
    _checkpoint_trusted: bool = field(default=True, repr=False, compare=False)
    _lock: threading.RLock = field(default_factory=threading.RLock,
                                    repr=False, compare=False)
    # A restored active checkpoint is deliberately untrusted unless its whole
    # payload was authenticated by the host.  New runs are trusted locally;
    # this flag distinguishes the two cases without claiming that local code
    # is an isolated security boundary.
    _restored_from_checkpoint: bool = field(default=False, repr=False, compare=False)
    _task_commitment: str = field(default="", repr=False, compare=False)
    _compatibility_commitment: str = field(default="", repr=False, compare=False)
    _executed_verifiers: dict[str, RegisteredVerifier] = field(default_factory=dict, repr=False, compare=False)
    _authenticated_receipt_ids: set[str] = field(default_factory=set, repr=False, compare=False)
    # A signed checkpoint authenticates the serialized verdict commitments,
    # but cannot carry the process-local HMAC secret used by live runs.
    _checkpoint_verification_commitments: dict[str, str] = field(
        default_factory=dict, repr=False, compare=False
    )
    _last_adjudication: Adjudication | None = field(default=None, repr=False, compare=False)

    _SNAPSHOT_FIELDS = frozenset({
        "task", "receipts", "candidates", "evidence", "verifications", "events",
        "final_candidate_id", "invalidated_verifiers", "system3_free_energy",
        "system3_active_inference", "system3_kripke_invariants",
        "system3_hyperbolic_embeddings", "system3_meta_cycles",
        "system3_observations", "predictions", "system3_actions", "outcomes",
        "system3_updates", "system3_beliefs", "system3_policy_revisions",
        "triz_repair_recommendations",
    })

    def __setattr__(self, name: str, value: Any) -> None:
        # Terminal runs have a one-way public state boundary.  Internal
        # bookkeeping (underscore names) remains usable for serialization, but
        # callers cannot replace state or a public collection after finality.
        if name == "compatibility_mode" and "compatibility_mode" in self.__dict__:
            if self.__dict__["compatibility_mode"] != value and not self.__dict__.get("_restoring", False):
                raise RuntimeError("compatibility mode is immutable after run creation")
        if name == "state" and "state" in self.__dict__:
            old = self.__dict__["state"]
            if ("_lock" in self.__dict__ and
                    old in (RunState.FINALIZED, RunState.REJECTED) and
                    not self.__dict__.get("_restoring", False)):
                raise RuntimeError(f"{old.value} runs are immutable; create a new run")
        elif name in self._SNAPSHOT_FIELDS and "state" in self.__dict__:
            if ("_lock" in self.__dict__ and
                    self.__dict__["state"] in (RunState.FINALIZED, RunState.REJECTED) and
                    not self.__dict__.get("_restoring", False)):
                raise RuntimeError(f"{self.__dict__['state'].value} runs are immutable; create a new run")
        object.__setattr__(self, name, value)

    def __getattribute__(self, name: str) -> Any:
        # Expose defensive deep snapshots for all mutable public state after a
        # terminal transition.  Thus nested writes cannot mutate the run even
        # if a caller obtains a dict/list several levels down.
        if name != "_SNAPSHOT_FIELDS":
            try:
                state = object.__getattribute__(self, "__dict__").get("state")
                fields = object.__getattribute__(self, "_SNAPSHOT_FIELDS")
                if (state in (RunState.FINALIZED, RunState.REJECTED) and name in fields
                        and not object.__getattribute__(self, "__dict__").get("_restoring", False)):
                    return _freeze_snapshot(copy.deepcopy(object.__getattribute__(self, name)))
            except (AttributeError, TypeError):
                pass
        return object.__getattribute__(self, name)

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip() or len(self.session_id) > 16384:
            raise ValueError("session_id must be a bounded non-empty string")
        if not isinstance(self.task, TaskSpec):
            raise TypeError("task must be TaskSpec")
        object.__setattr__(self, "_task_commitment", canonical_hash(self.task.to_dict()))
        object.__setattr__(self, "_compatibility_commitment", canonical_hash(self.compatibility_mode))

    def _ensure_mutable(self) -> None:
        if self.state in (RunState.FINALIZED, RunState.REJECTED):
            raise RuntimeError(f"{self.state.value} runs are immutable; create a new run")

    def _event(self, event_type: str, **data: Any) -> None:
        with self._lock:
            if self.state in (RunState.FINALIZED, RunState.REJECTED):
                raise RuntimeError(f"{self.state.value} runs are immutable")
            event = {"type": event_type, "at": utc_now(), **data}
            event["prev_hash"] = self.events[-1].get("event_hash", "0" * 64) if self.events else "0" * 64
            event["event_hash"] = canonical_hash(event)
            self.events.append(event)

    def validate_event_history(self, *, expected_count: int | None = None,
                               expected_terminal_commitment: str | None = None,
                               validate_auxiliary: bool = True) -> None:
        """Reject edited, reordered, or truncated event history."""
        if len(self.events) > 100_000:
            raise ValueError("event history exceeds the maximum length")
        if expected_count is not None and (not isinstance(expected_count, int) or expected_count < 0):
            raise ValueError("invalid event count commitment")
        if expected_count is not None and len(self.events) != expected_count:
            raise ValueError("event history is truncated or has extra events")
        previous = "0" * 64
        for event in self.events:
            if event.get("prev_hash") != previous:
                raise ValueError("event history chain is broken")
            supplied_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if supplied_hash != canonical_hash(body):
                raise ValueError("event history contains a tampered event")
            previous = supplied_hash
        if expected_terminal_commitment is not None:
            actual = canonical_hash({"count": len(self.events), "terminal_hash": previous})
            if not hmac.compare_digest(str(expected_terminal_commitment), actual):
                raise ValueError("event terminal commitment mismatch")
        # History validity is meaningful only when it agrees with the object
        # maps that the history is supposed to commit.
        self._reconcile_event_state()
        if validate_auxiliary:
            self._validate_auxiliary_telemetry()

    def start(self) -> None:
        if self.state is not RunState.CREATED:
            raise RuntimeError(f"run is already {self.state.value}")
        self.state = RunState.ACTIVE
        self._event("run_started", session_id=self.session_id)

    def record_receipt(
        self, receipt: ToolReceipt, *, trusted_boundary: str | None = None,
        authenticated_boundary: Callable[[ToolReceipt], bool] | None = None,
    ) -> None:
        """Record a host result without allowing application code to mint trust.

        Receipts constructed locally are retained for diagnostics but are
        ``self_minted`` and cannot satisfy the receipt-backed System 3 loop.
        A host adapter must explicitly classify the receipt at this boundary
        (or construct it with a trusted boundary); the classification is still
        only provenance metadata and must not be confused with a signature.
        """
        with self._lock:
            self._ensure_mutable()
            if not isinstance(receipt, ToolReceipt):
                raise TypeError("receipt must be a ToolReceipt")
            if trusted_boundary is not None:
                if trusted_boundary not in ToolReceipt.TRUSTED_BOUNDARIES:
                    raise PermissionError("receipt trust may only be supplied by a host/external boundary")
                receipt = replace(receipt, trust_boundary=trusted_boundary)
            if receipt.session_id != self.session_id:
                raise ValueError("tool receipt belongs to a different session")
            if receipt.receipt_id in self.receipts:
                raise ValueError(f"duplicate receipt: {receipt.receipt_id}")
            if authenticated_boundary is not None:
                if not callable(authenticated_boundary):
                    raise TypeError("authenticated_boundary must be a callable receipt authenticator")
                try:
                    authenticated = authenticated_boundary(receipt) is True
                except Exception as exc:
                    raise PermissionError("receipt boundary authentication failed") from exc
                if not authenticated:
                    raise PermissionError("receipt boundary authentication failed")
            stored = copy.deepcopy(receipt)
            self.receipts[receipt.receipt_id] = stored
            if authenticated_boundary is not None:
                self._authenticated_receipt_ids.add(receipt.receipt_id)
            self._event("tool_receipt", receipt_id=receipt.receipt_id,
                        capability=receipt.capability, success=receipt.success,
                        trust_boundary=receipt.trust_boundary)

    def _event_temporal_report(self) -> dict[str, Any]:
        """Rebuild temporal safety solely from the authenticated event chain."""
        self.validate_event_history(validate_auxiliary=False)
        self._reconcile_event_state()
        if not self.events:
            raise RuntimeError("cannot evaluate temporal model without run events")
        kripke = KripkeStructure()
        for index, event in enumerate(self.events):
            world_id = f"event_{index}"
            event_type = str(event.get("type", ""))
            props = {"safe", event_type}
            if event_type == "tool_receipt" and type(event.get("success")) is not bool:
                raise ValueError("tool receipt event has non-boolean success")
            if event_type == "tool_receipt" and not event.get("success"):
                props.discard("safe")
            kripke.add_world(world_id, propositions=props,
                             metadata={"event_hash": event.get("event_hash"),
                                       "event_type": event_type},
                             is_initial=index == 0)
            kripke.add_transition(world_id, world_id)
            if index:
                kripke.add_transition(f"event_{index-1}", world_id)
        result = KripkeModelChecker(kripke).check("AG(safe)", "event_0")
        return {
            "formula": "AG(safe)", "is_satisfied": result.is_satisfied,
            # This is a projection of local event labels only.  It is not a
            # broker guarantee, security proof, or proof that the artifact is
            # safe in the real world.
            "claim_status": "telemetry_projection_not_safety_proof",
            "is_safety_proof": False,
            "safety_claim_scope": "runtime_event_labels_only",
            "initial_world": "event_0",
            "satisfying_worlds": sorted(list(result.satisfied_worlds)),
            "event_hashes": [e.get("event_hash") for e in self.events],
            "event_count": len(self.events),
            "terminal_event_hash": self.events[-1].get("event_hash"),
        }

    def _evaluate_system3_for_candidate(self, candidate: Candidate) -> None:
        """Compute and track Friston Free Energy F, Kripke state invariants, and Hyperbolic tree embeddings."""
        try:
            # Registration records only an unstarted inference state.  It must
            # not manufacture an observation, prediction, action, or update
            # from already-present receipts.  The receipt-bound lifecycle is
            # started explicitly by observe_system3/predict_system3/act_system3.
            fe_engine = ActiveInferenceEngine(create_default_architecture_pomdp())
            if bool(self.task.metadata.get("require_system3_loop", False)):
                # Strict candidates expose only an unstarted state.  No
                # registration-time projection may stand in for the host-bound
                # observe/predict/act/outcome/update lifecycle.
                fe_data = {"status": "awaiting_receipt_bound_system3_loop",
                           "loop_required_for_update": True}
            else:
                # Legacy registration callers expect useful baseline telemetry.
                # This is an estimate from the fixed generative model, not a
                # receipt, observation, or authorization and cannot satisfy a
                # strict loop/finalization gate.
                telemetry_engine = ActiveInferenceEngine(create_default_architecture_pomdp())
                f_val, complexity, accuracy = telemetry_engine.update_beliefs("HIGH_THROUGHPUT_CLEAN")
                fe_data = {
                    "status": "legacy_telemetry_only",
                    "claim_status": "estimated_model_projection_not_measurement",
                    "observation": "HIGH_THROUGHPUT_CLEAN",
                    "variational_free_energy_f": f_val,
                    "complexity_kl": complexity,
                    "accuracy_log_likelihood": accuracy,
                    "loop_required_for_update": False,
                }
            candidate.metadata["system3_free_energy"] = fe_data
            self.system3_free_energy[candidate.candidate_id] = fe_data
            active_data = fe_engine.to_dict()
            candidate.metadata["system3_active_inference"] = copy.deepcopy(active_data)
            self.system3_active_inference[candidate.candidate_id] = active_data

            # 2. Event-bound temporal safety model.
            kripke_data = self._event_temporal_report()
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
        except Exception as exc:
            # System 3 telemetry is a trust input, not decorative logging.
            # Never register a candidate while its safety/model checks failed.
            raise RuntimeError("System 3 candidate evaluation failed closed") from exc

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
                record_hash=canonical_hash(triz_payload),
            )
        return triz_payload

    def register_candidate(self, candidate: Candidate) -> None:
        with self._lock:
            self._ensure_mutable()
            if candidate.session_id != self.session_id:
                raise ValueError("candidate belongs to a different session")
            if candidate.candidate_id in self.candidates:
                raise ValueError(f"duplicate candidate: {candidate.candidate_id}")
            self._validate_candidate_graph(candidate)
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
            self._artifact_commits[candidate.candidate_id] = (
                canonical_hash(stored.artifact), self._dependency_hash(stored)
            )
            self._system3_commits[candidate.candidate_id] = self._system3_metadata_hash(stored)
            self._event("candidate_registered", candidate_id=candidate.candidate_id)

    def _dependency_hash(self, candidate: Candidate) -> str:
        """Hash referenced receipt/evidence objects without mutable metadata."""
        return canonical_hash({
            "receipts": [canonical_hash(self.receipts[r].to_dict()) for r in candidate.receipt_ids],
            "evidence": [canonical_hash(self.evidence[e].to_dict()) for e in candidate.evidence_ids],
        })

    def _system3_metadata_hash(self, candidate: Candidate) -> str:
        """Commit every System 3 metadata value attached to a candidate."""
        return canonical_hash({
            key: value for key, value in candidate.metadata.items()
            if str(key).startswith("system3_")
        })

    def _validate_system3_metadata(self, candidate: Candidate) -> None:
        committed = self._system3_commits.get(candidate.candidate_id)
        if committed is None or not hmac.compare_digest(committed, self._system3_metadata_hash(candidate)):
            raise PermissionError("System 3 candidate telemetry changed after commitment")
        # Each derived map is also checked against the candidate's committed
        # metadata; a public map reference must not silently alter trusted data.
        pairs = (("system3_free_energy", self.system3_free_energy),
                 ("system3_active_inference", self.system3_active_inference),
                 ("system3_kripke", self.system3_kripke_invariants),
                 ("system3_hyperbolic", self.system3_hyperbolic_embeddings),
                 ("system3_loop", {k: self.candidates[k].metadata.get("system3_loop")
                                   for k in self.candidates if "system3_loop" in self.candidates[k].metadata}))
        for key, store in pairs:
            if key in candidate.metadata and candidate.candidate_id in store:
                if canonical_hash(candidate.metadata[key]) != canonical_hash(store[candidate.candidate_id]):
                    raise PermissionError("System 3 telemetry store disagrees with candidate metadata")

    def attach_evidence(self, evidence: Evidence) -> None:
        with self._lock:
            self._ensure_mutable()
            self._validate_evidence(evidence)
            if evidence.evidence_id in self.evidence:
                raise ValueError(f"duplicate evidence: {evidence.evidence_id}")
            self.evidence[evidence.evidence_id] = copy.deepcopy(evidence)
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

    def _validate_candidate_graph(self, candidate: Candidate) -> None:
        """Require a closed candidate graph, not merely individually known IDs."""
        if len(set(candidate.receipt_ids)) != len(candidate.receipt_ids):
            raise ValueError("candidate contains duplicate receipt references")
        if len(set(candidate.evidence_ids)) != len(candidate.evidence_ids):
            raise ValueError("candidate contains duplicate evidence references")
        for receipt_id in candidate.receipt_ids:
            receipt = self.receipts.get(receipt_id)
            if receipt is None:
                raise ValueError(f"candidate references unknown receipt: {receipt_id}")
            if receipt.session_id != self.session_id:
                raise PermissionError("candidate receipt has the wrong session")
        for evidence_id in candidate.evidence_ids:
            evidence = self.evidence.get(evidence_id)
            if evidence is None:
                raise ValueError(f"candidate references unknown evidence: {evidence_id}")
            self._validate_evidence(evidence)
            if evidence.receipt_id not in set(candidate.receipt_ids):
                raise PermissionError(
                    f"candidate evidence {evidence_id} is not anchored to a candidate receipt"
                )

    _EVENT_FIELDS = {
        "run_started": {"type", "at", "session_id", "prev_hash", "event_hash"},
        "tool_receipt": {"type", "at", "receipt_id", "capability", "success", "trust_boundary", "prev_hash", "event_hash"},
        "evidence_attached": {"type", "at", "evidence_id", "receipt_id", "prev_hash", "event_hash"},
        "candidate_registered": {"type", "at", "candidate_id", "prev_hash", "event_hash"},
        "verification_recorded": {"type", "at", "verification_id", "candidate_id", "verifier", "verifier_class", "passed", "prev_hash", "event_hash"},
        "verifier_invalidated": {"type", "at", "verifier", "reason", "prev_hash", "event_hash"},
        "triz_repair_recommendation": {"type", "at", "candidate_id", "synthesis_id", "residual_score", "record_hash", "prev_hash", "event_hash"},
        "finalization_rejected": {"type", "at", "candidate_id", "missing", "prev_hash", "event_hash"},
        "run_finalized": {"type", "at", "candidate_id", "prev_hash", "event_hash"},
        "system3_meta_cycle_completed": {"type", "at", "candidate_id", "cycle_hash", "prev_hash", "event_hash"},
        "system3_observation": {"type", "at", "candidate_id", "observation_id", "observation_hash", "record_hash", "prev_hash", "event_hash"},
        "system3_prediction": {"type", "at", "prediction_id", "candidate_id", "action", "observation_hash", "record_hash", "prev_hash", "event_hash"},
        "system3_action": {"type", "at", "action_id", "candidate_id", "prediction_id", "action", "prediction_hash", "action_hash", "prev_hash", "event_hash"},
        "system3_outcome": {"type", "at", "outcome_id", "candidate_id", "prediction_id", "receipt_id", "receipt_output_hash", "record_hash", "prev_hash", "event_hash"},
        "system3_update": {"type", "at", "update_id", "candidate_id", "outcome_id", "prediction_id", "prediction_error", "update_hash", "prev_hash", "event_hash"},
    }

    def _revoked_verifiers_from_events(self) -> dict[str, str]:
        """Return the append-only revocation ledger, never the mutable map."""
        revoked: dict[str, str] = {}
        for event in self.events:
            if event.get("type") == "verifier_invalidated":
                verifier, reason = event.get("verifier"), event.get("reason")
                if (not isinstance(verifier, str) or not verifier.strip()
                        or not isinstance(reason, str) or not reason.strip()):
                    raise ValueError("verifier revocation event is malformed")
                # Revocation is monotonic. A later event cannot clear it or
                # replace its reason with a mutable-map edit.
                revoked.setdefault(verifier.strip(), reason.strip())
        return revoked

    def _revoked(self, verifier: str) -> bool:
        # The event ledger is authoritative after restore; the private
        # process-local ledger protects against in-memory event deletion, and
        # the public map is a conservative fallback (never an authority that
        # can clear either committed source).
        return (verifier in self._revoked_verifiers_from_events()
                or verifier in self._revocation_ledger
                or verifier in self.invalidated_verifiers)

    def _validate_auxiliary_telemetry(self) -> None:
        """Require complete, candidate-keyed System 3 telemetry projections."""
        candidate_ids = set(self.candidates)
        allowed_candidate_telemetry = {
            "system3_free_energy", "system3_active_inference", "system3_kripke",
            "system3_hyperbolic", "system3_loop", "system3_meta_cycle",
        }
        for candidate in self.candidates.values():
            unknown = {str(key) for key in candidate.metadata
                       if str(key).startswith("system3_")} - allowed_candidate_telemetry
            if unknown:
                raise ValueError("candidate contains unsupported System 3 telemetry keys")
            if "triz_repair_recommendation" in candidate.metadata:
                canonical_hash(candidate.metadata["triz_repair_recommendation"])
        keyed = {
            "free_energy": self.system3_free_energy,
            "active_inference": self.system3_active_inference,
            "kripke": self.system3_kripke_invariants,
            "hyperbolic": self.system3_hyperbolic_embeddings,
        }
        for label, store in keyed.items():
            if not isinstance(store, Mapping) or set(store) != candidate_ids:
                raise ValueError(f"System 3 {label} map is incomplete or contains extra candidates")
            for candidate_id, value in store.items():
                canonical_hash(value)
                candidate = self.candidates[candidate_id]
                metadata_key = "system3_" + label
                if metadata_key not in candidate.metadata or canonical_hash(value) != canonical_hash(candidate.metadata[metadata_key]):
                    raise ValueError(f"System 3 {label} telemetry has no matching candidate commitment")

        loop_candidates = {
            candidate_id for candidate_id, candidate in self.candidates.items()
            if "system3_loop" in candidate.metadata
        }
        loop_map = {
            candidate_id: candidate.metadata.get("system3_loop")
            for candidate_id, candidate in self.candidates.items()
            if "system3_loop" in candidate.metadata
        }
        # The loop is candidate metadata rather than a separate global map;
        # nevertheless its candidate key set must be closed and canonical.
        if set(loop_map) != loop_candidates:
            raise ValueError("System 3 loop telemetry candidate keys are inconsistent")
        for value in loop_map.values():
            canonical_hash(value)

        update_candidates = {u.get("candidate_id") for u in self.system3_updates.values()}
        if set(self.system3_beliefs) != update_candidates or set(self.system3_policy_revisions) != update_candidates:
            raise ValueError("System 3 belief/policy maps are incomplete or contain extra candidates")
        for store in (self.system3_beliefs, self.system3_policy_revisions):
            for value in store.values():
                canonical_hash(value)

        # Revalidate every candidate's loop, not merely the candidate selected
        # for finalization; a forged auxiliary record for another candidate
        # must not hide in an otherwise valid run.
        record_candidates = set(self.system3_observations)
        record_candidates.update(p.candidate_id for p in self.predictions.values())
        record_candidates.update(a.get("candidate_id") for a in self.system3_actions.values())
        record_candidates.update(o.candidate_id for o in self.outcomes.values())
        record_candidates.update(u.get("candidate_id") for u in self.system3_updates.values())
        for candidate_id in record_candidates:
            if candidate_id not in candidate_ids:
                raise ValueError("System 3 record has no candidate backing")
            self._validate_system3_record_integrity(candidate_id)

        # Meta-cycle and TRIZ records are global projections, but are trusted
        # only when each record is backed by a candidate and a committed event.
        meta_events = [e for e in self.events if e.get("type") == "system3_meta_cycle_completed"]
        if len(meta_events) != len(self.system3_meta_cycles):
            raise ValueError("System 3 meta-cycle list does not reconcile with events")
        seen_meta_candidates: set[str] = set()
        for event, cycle in zip(meta_events, self.system3_meta_cycles):
            if not isinstance(cycle, Mapping) or cycle.get("candidate_id") not in candidate_ids:
                raise ValueError("System 3 meta-cycle entry has no candidate backing")
            if cycle.get("candidate_id") in seen_meta_candidates:
                raise ValueError("duplicate System 3 meta-cycle candidate entry")
            seen_meta_candidates.add(cycle.get("candidate_id"))
            if not isinstance(cycle, Mapping) or cycle.get("candidate_id") not in candidate_ids:
                raise ValueError("System 3 meta-cycle entry has no candidate backing")
            if event.get("candidate_id") != cycle.get("candidate_id"):
                raise ValueError("System 3 meta-cycle event does not match its record")
            if event.get("cycle_hash") != canonical_hash(cycle):
                raise ValueError("System 3 meta-cycle event has no matching commitment")
            candidate = self.candidates[cycle["candidate_id"]]
            if candidate.metadata.get("system3_meta_cycle") is not cycle and canonical_hash(candidate.metadata.get("system3_meta_cycle")) != canonical_hash(cycle):
                raise ValueError("System 3 meta-cycle candidate metadata is stale")
            canonical_hash(cycle)

        meta_candidate_ids = {cycle.get("candidate_id") for cycle in self.system3_meta_cycles}
        metadata_meta_ids = {candidate_id for candidate_id, candidate in self.candidates.items()
                             if "system3_meta_cycle" in candidate.metadata}
        if metadata_meta_ids != meta_candidate_ids:
            raise ValueError("System 3 meta-cycle candidate metadata keys do not reconcile")

        triz_events = [e for e in self.events if e.get("type") == "triz_repair_recommendation"]
        if len(triz_events) != len(self.triz_repair_recommendations):
            raise ValueError("TRIZ recommendation list does not reconcile with events")
        for event, record in zip(triz_events, self.triz_repair_recommendations):
            if not isinstance(record, Mapping) or record.get("candidate_id") not in candidate_ids:
                raise ValueError("TRIZ recommendation has no candidate backing")
            if (event.get("candidate_id") != record.get("candidate_id")
                    or event.get("synthesis_id") != record.get("synthesis_id")
                    or event.get("residual_score") != record.get("residual_contradiction_score")
                    or event.get("record_hash") != canonical_hash(record)):
                raise ValueError("TRIZ recommendation event does not match its record")
            canonical_hash(record)
        latest_triz: dict[str, Mapping[str, Any]] = {}
        for record in self.triz_repair_recommendations:
            latest_triz[str(record["candidate_id"])] = record
        for candidate_id, candidate in self.candidates.items():
            has_metadata = "triz_repair_recommendation" in candidate.metadata
            if has_metadata != (candidate_id in latest_triz):
                raise ValueError("TRIZ candidate metadata does not reconcile with recommendations")
            if has_metadata and canonical_hash(candidate.metadata["triz_repair_recommendation"]) != canonical_hash(latest_triz[candidate_id]):
                raise ValueError("TRIZ candidate metadata is stale")

    def _reconcile_event_state(self) -> None:
        """Reconcile object maps with the authenticated append-only event model."""
        # Every mutable object entering a run must have exactly one corresponding
        # event.  This catches map injection/removal even when object hashes are
        # otherwise internally self-consistent.
        event_receipts = [e.get("receipt_id") for e in self.events if e.get("type") == "tool_receipt"]
        event_evidence = [e.get("evidence_id") for e in self.events if e.get("type") == "evidence_attached"]
        event_candidates = [e.get("candidate_id") for e in self.events if e.get("type") == "candidate_registered"]
        event_verifications = [e.get("verification_id") for e in self.events if e.get("type") == "verification_recorded"]
        event_predictions = [e.get("prediction_id") for e in self.events if e.get("type") == "system3_prediction"]
        event_actions = [e.get("action_id") for e in self.events if e.get("type") == "system3_action"]
        event_outcomes = [e.get("outcome_id") for e in self.events if e.get("type") == "system3_outcome"]
        event_updates = [e.get("update_id") for e in self.events if e.get("type") == "system3_update"]
        event_observations = [e.get("candidate_id") for e in self.events if e.get("type") == "system3_observation"]
        event_started = [e for e in self.events if e.get("type") == "run_started"]
        if not self.events or len(event_started) != 1 or self.events[0].get("type") != "run_started":
            raise ValueError("event history must contain exactly one initial run-start event")
        allowed_events = set(self._EVENT_FIELDS)
        if any(not isinstance(e, Mapping) or e.get("type") not in allowed_events for e in self.events):
            raise ValueError("event history contains an unsupported event type")
        for event in self.events:
            if set(event) != self._EVENT_FIELDS[event["type"]]:
                raise ValueError(f"{event['type']} event has unexpected or missing fields")
            # This also recursively rejects non-finite and non-JSON event data.
            canonical_hash(event)
        if len(event_receipts) != len(set(event_receipts)) or set(event_receipts) != set(self.receipts):
            raise ValueError("receipt map does not reconcile with committed events")
        if len(event_evidence) != len(set(event_evidence)) or set(event_evidence) != set(self.evidence):
            raise ValueError("evidence map does not reconcile with committed events")
        if len(event_candidates) != len(set(event_candidates)) or set(event_candidates) != set(self.candidates):
            raise ValueError("candidate map does not reconcile with committed events")
        if len(event_verifications) != len(set(event_verifications)) or set(event_verifications) != set(self.verifications):
            raise ValueError("verification map does not reconcile with committed events")
        if set(event_observations) != set(self.system3_observations) or len(event_observations) != len(set(event_observations)):
            raise ValueError("observation map does not reconcile with committed events")
        if set(event_predictions) != set(self.predictions) or len(event_predictions) != len(set(event_predictions)):
            raise ValueError("prediction map does not reconcile with committed events")
        if set(event_actions) != set(self.system3_actions) or len(event_actions) != len(set(event_actions)):
            raise ValueError("action map does not reconcile with committed events")
        if set(event_outcomes) != set(self.outcomes) or len(event_outcomes) != len(set(event_outcomes)):
            raise ValueError("outcome map does not reconcile with committed events")
        expected_updates = {v.get("update_id") for v in self.system3_updates.values()}
        if set(event_updates) != expected_updates or len(event_updates) != len(set(event_updates)):
            raise ValueError("System 3 update map does not reconcile with committed events")
        if set(self.system3_updates) != set(self.outcomes):
            raise ValueError("System 3 update keys do not reconcile with outcome keys")
        for event in self.events:
            kind = event.get("type")
            if kind == "run_started":
                if event.get("session_id") != self.session_id:
                    raise ValueError("run-start event does not match session")
            elif kind == "tool_receipt":
                item = self.receipts.get(event.get("receipt_id"))
                if (item is None or event.get("capability") != item.capability
                        or event.get("success") is not item.success
                        or event.get("trust_boundary") != item.trust_boundary):
                    raise ValueError("receipt event does not match receipt map")
            elif kind == "evidence_attached":
                item = self.evidence.get(event.get("evidence_id"))
                if item is None or event.get("receipt_id") != item.receipt_id:
                    raise ValueError("evidence event does not match evidence map")
            elif kind == "candidate_registered":
                item = self.candidates.get(event.get("candidate_id"))
                if item is None or item.session_id != self.session_id:
                    raise ValueError("candidate event does not match candidate map")
            elif kind == "system3_observation":
                item = self.system3_observations.get(event.get("candidate_id"))
                if (item is None or event.get("candidate_id") not in self.candidates
                        or item.get("observation_hash") != event.get("observation_hash")
                        or item.get("observation_id") != event.get("observation_id")
                        or item.get("record_hash") != event.get("record_hash")):
                    raise ValueError("observation event does not match System 3 state")
            elif kind == "system3_prediction":
                item = self.predictions.get(event.get("prediction_id"))
                if (item is None or item.candidate_id not in self.candidates
                        or item.candidate_id != event.get("candidate_id")
                        or item.action != event.get("action")
                        or item.observation_hash != event.get("observation_hash")
                        or item.record_hash != event.get("record_hash")):
                    raise ValueError("prediction event does not match prediction map")
            elif kind == "system3_action":
                item = self.system3_actions.get(event.get("action_id"))
                if (item is None or item.get("candidate_id") not in self.candidates
                        or item.get("candidate_id") != event.get("candidate_id")
                        or item.get("prediction_id") != event.get("prediction_id")
                        or item.get("action") != event.get("action")
                        or item.get("prediction_hash") != event.get("prediction_hash")
                        or item.get("action_hash") != event.get("action_hash")):
                    raise ValueError("action event does not match action map")
            elif kind == "system3_outcome":
                item = self.outcomes.get(event.get("outcome_id"))
                if (item is None or item.candidate_id not in self.candidates
                        or item.candidate_id != event.get("candidate_id")
                        or item.prediction_id != event.get("prediction_id")
                        or item.receipt_id != event.get("receipt_id")
                        or item.receipt_output_hash != event.get("receipt_output_hash")
                        or item.record_hash != event.get("record_hash")):
                    raise ValueError("outcome event does not match outcome map")
            elif kind == "system3_update":
                item = next((u for u in self.system3_updates.values() if u.get("update_id") == event.get("update_id")), None)
                if (item is None or item.get("candidate_id") not in self.candidates
                        or item.get("candidate_id") != event.get("candidate_id")
                        or item.get("outcome_id") != event.get("outcome_id")
                        or item.get("prediction_error") != event.get("prediction_error")
                        or item.get("update_hash") != event.get("update_hash")):
                    raise ValueError("update event does not match update map")
            elif kind == "verification_recorded":
                item = self.verifications.get(event.get("verification_id"))
                if (item is None or event.get("candidate_id") != item.candidate_id
                        or event.get("verifier") != item.verifier
                        or event.get("verifier_class") != item.verifier_class
                        or event.get("passed") is not item.passed):
                    raise ValueError("verification event does not match verification map")
            elif kind == "verifier_invalidated":
                # The map is checked against this immutable event-derived
                # ledger below; a correctly rehashed forged event cannot grant
                # a revoked verifier authority.
                if event.get("verifier") not in self._revoked_verifiers_from_events():
                    raise ValueError("invalid verifier revocation event")
            elif kind == "system3_meta_cycle_completed":
                # Full record/hash reconciliation is performed below.
                pass
            elif kind == "triz_repair_recommendation":
                pass
            elif kind == "finalization_rejected":
                if (event.get("candidate_id") not in self.candidates
                        or not isinstance(event.get("missing"), list)):
                    raise ValueError("finalization rejection event has no candidate backing")
            elif kind == "run_finalized":
                if event.get("candidate_id") not in self.candidates:
                    raise ValueError("finalization event has no candidate backing")
        expected_revocations = self._revoked_verifiers_from_events()
        if dict(self.invalidated_verifiers) != expected_revocations:
            raise ValueError("verifier revocation map does not match its committed event ledger")

    def _candidate_graph_hash(self, candidate: Candidate) -> str:
        """Commit to a candidate and every receipt/evidence object it references."""
        self._validate_candidate_graph(candidate)
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
        candidate_payload = candidate.to_dict()
        # System 3 telemetry is derived and may be refreshed as events append;
        # it is not an input to verifier identity. Core candidate fields and
        # every referenced receipt/evidence object remain committed.
        candidate_payload.pop("metadata", None)
        return canonical_hash({
            "candidate": candidate_payload,
            "receipts": receipts,
            "evidence": evidence,
        })

    def _validate_attested_verification(self, result: VerificationResult, *, check_runtime: bool = True) -> None:
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
        if check_runtime:
            expected = self._attestation(result)
            if not hmac.compare_digest(result.runtime_attestation, expected):
                # The live HMAC secret is intentionally never serialized.
                # For a trusted restored checkpoint, the external checkpoint
                # signature authenticates this immutable result commitment;
                # require that commitment to match before accepting it.  An
                # unsigned/restored or subsequently-mutated result still
                # fails the original runtime-attestation gate.
                committed = self._checkpoint_verification_commitments.get(result.verification_id)
                if not (self._checkpoint_trusted and self._restored_from_checkpoint
                        and isinstance(committed, str)
                        and hmac.compare_digest(committed, canonical_hash(result.to_dict()))):
                    raise PermissionError("verification has no valid runtime attestation")
        expected_scope = f"task:{self.task.task_id};candidate:{candidate.candidate_id}"
        if not result.scope or result.scope != expected_scope:
            raise PermissionError("verification scope is missing or not bound to this task/candidate")
        claim_graph = ClaimGraph.from_task(self.task, candidate)
        unknown_claims = [claim_id for claim_id in result.claim_ids if claim_id not in set(claim_graph.claim_ids)]
        if unknown_claims:
            raise PermissionError("verification claims are outside the candidate claim graph: "
                                  + ", ".join(unknown_claims))
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
        # Provenance references are not free-form labels in a runtime
        # verdict. They must resolve to the candidate's receipt/evidence graph
        # (an evidence ID also resolves transitively to its receipt).
        candidate_receipts = set(candidate.receipt_ids)
        candidate_evidence = set(candidate.evidence_ids)
        unknown_provenance = [pid for pid in result.provenance_ids
                              if pid not in candidate_receipts and pid not in candidate_evidence]
        if unknown_provenance:
            raise PermissionError("verification provenance is not in the candidate receipt/evidence graph: "
                                  + ", ".join(unknown_provenance))
        invalid_provenance = []
        for provenance_id in result.provenance_ids:
            receipt = self.receipts.get(provenance_id)
            if receipt is None and provenance_id in self.evidence:
                receipt = self.receipts.get(self.evidence[provenance_id].receipt_id)
            if receipt is None or receipt.success is not True:
                invalid_provenance.append(provenance_id)
        if invalid_provenance:
            raise PermissionError("verification provenance is not bound to a successful receipt: "
                                  + ", ".join(invalid_provenance))
        if result.passed and not result.evidence_ids:
            raise PermissionError("a passing verification must cite candidate evidence")
        # A self-declared independent result is retained with an explicit
        # untrusted status for auditability, but cannot satisfy a policy gate.

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
        self._ensure_mutable()
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        verifier_name = str(getattr(verifier, "name", "")).strip()
        if not verifier_name:
            raise ValueError("registered verifier must declare a name")
        if self._revoked(verifier_name):
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
            scope=f"task:{self.task.task_id};candidate:{candidate.candidate_id}",
            candidate_graph_hash=self._candidate_graph_hash(candidate),
            metadata={**dict(raw.metadata), "independence_status": (
                "self_declared_untrusted" if bool(getattr(verifier, "independent", False))
                else "not_claimed")},
        )
        if result.independent and not result.passed:
            # Failed independent checks do not establish provenance and are
            # retained only as failures when they carry ordinary attestation.
            pass
        # Keep legacy in-process declarations observable, but never count them
        # as independent policy evidence until measured provenance is present.
        result = replace(result, runtime_attestation=self._attestation(result))
        self._executed_verifiers[verifier_name] = verifier
        self._record_attested_verification(result)
        return result

    def configure_process_attestation(self, verifier: ProcessAttestationVerifier) -> None:
        """Install the host's external process-attestation verifier.

        There is deliberately no default verifier.  In-process code cannot
        elevate itself to ``process_attested``.
        """
        if verifier is None or not callable(getattr(verifier, "verify", None)):
            raise ValueError("process attestation verifier must implement verify")
        with self._lock:
            self.process_attestation_verifier = verifier

    def record_process_attested_verification(
        self,
        result: VerificationResult,
        attestation: ProcessAttestation | Mapping[str, Any],
        verification_material: Any = None,
    ) -> VerificationResult:
        """Accept a verdict only after external process identity verification."""
        with self._lock:
            self._ensure_mutable()
            if self.process_attestation_verifier is None:
                raise PermissionError("external process attestation verifier is unavailable")
            if self._revoked(result.verifier):
                raise PermissionError(f"verifier is invalidated: {result.verifier}")
            att = (ProcessAttestation.from_dict(attestation)
                   if isinstance(attestation, Mapping) else attestation)
            if not isinstance(att, ProcessAttestation):
                raise TypeError("attestation must be ProcessAttestation or mapping")
            if not att.signature:
                raise PermissionError("process attestation signature is required")
            if not result.scope or not att.scope:
                raise PermissionError("process attestation scope is required")
            if att.session_id != self.session_id or result.session_id != self.session_id:
                raise PermissionError("process attestation session identity mismatch")
            expected = {
                "candidate_id": result.candidate_id, "verifier": result.verifier,
                "verifier_class": result.verifier_class, "passed": result.passed,
                "candidate_hash": result.candidate_hash,
                "candidate_graph_hash": result.candidate_graph_hash,
                "evidence_ids": tuple(result.evidence_ids),
                "claim_ids": tuple(result.claim_ids),
                "provenance_ids": tuple(result.provenance_ids),
                "counterexample_ids": tuple(result.counterexample_ids),
                "independent": result.independent,
                "scope": result.scope,
            }
            actual = {
                "candidate_id": att.candidate_id, "verifier": att.verifier,
                "verifier_class": att.verifier_class, "passed": att.passed,
                "candidate_hash": att.candidate_hash,
                "candidate_graph_hash": att.candidate_graph_hash,
                "evidence_ids": tuple(att.evidence_ids),
                "claim_ids": tuple(att.claim_ids),
                "provenance_ids": tuple(att.provenance_ids),
                "counterexample_ids": tuple(att.counterexample_ids),
                "independent": att.independent,
                "scope": att.scope,
            }
            candidate = self.candidates.get(result.candidate_id)
            receipt = self.receipts.get(att.receipt_id)
            if (expected != actual or candidate is None or receipt is None
                    or receipt.session_id != self.session_id or receipt.success is not True
                    or not receipt.trusted
                    or att.receipt_id not in candidate.receipt_ids
                    or not att.executable_identity or not att.workspace_identity
                    or not att.input_hash or not att.output_hash):
                raise PermissionError("process attestation is not bound to a successful candidate receipt")
            receipt_exec = dict(receipt.executable_identity)
            receipt_workspace = dict(receipt.workspace_identity)
            if receipt_exec != dict(att.executable_identity):
                raise PermissionError("process attestation executable identity mismatch")
            if receipt_workspace != dict(att.workspace_identity):
                raise PermissionError("process attestation workspace identity mismatch")
            if not hmac.compare_digest(att.input_hash, receipt.input_hash):
                raise PermissionError("process attestation input hash mismatch")
            if not hmac.compare_digest(att.output_hash, receipt.output_hash):
                raise PermissionError("process attestation output hash mismatch")
            try:
                verified = self.process_attestation_verifier.verify(att, verification_material)
            except Exception as exc:
                raise PermissionError("external process attestation verification failed") from exc
            if verified is not True:
                raise PermissionError("external process attestation was not verified")
            stamped = replace(
                result, inspected_candidate=True, trust_boundary="process_attested",
                metadata={**dict(result.metadata), "process_attestation": att.to_dict(),
                          "independence_status": ("process_attested" if result.independent
                                                  else "not_claimed")},
            )
            stamped = replace(stamped, runtime_attestation=self._attestation(stamped))
            self._process_attestation_materials[stamped.verification_id] = copy.deepcopy(
                verification_material
            )
            self._record_attested_verification(stamped)
            return copy.deepcopy(stamped)

    def invalidate_verifier(self, verifier: str, reason: str) -> None:
        """Revoke a verifier's authority for future finalization decisions."""
        if not verifier or not verifier.strip() or not reason or not reason.strip():
            raise ValueError("verifier and reason must be non-empty")
        with self._lock:
            self._ensure_mutable()
            verifier_name, clean_reason = verifier.strip(), reason.strip()
            self.invalidated_verifiers[verifier_name] = clean_reason
            self._revocation_ledger[verifier_name] = clean_reason
            self._event("verifier_invalidated", verifier=verifier_name,
                        reason=clean_reason)

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

    def _raw_passed_verifications(self, candidate_id: str) -> list[VerificationResult]:
        return [v for v in self.verifications.values()
                if v.candidate_id == candidate_id and v.passed
                and v.inspected_candidate
                and v.trust_boundary in VerificationPolicy.TRUST_BOUNDARY_RANK
                and not self._revoked(v.verifier)]

    def passed_verifications(self, candidate_id: str) -> list[VerificationResult]:
        results = self._raw_passed_verifications(candidate_id)
        # A verdict that calls itself independent is retained in the raw map,
        # but is not an eligible passing verifier until its provenance is
        # measured and distinct (or process-attested).
        return [v for v in results if v.verifier_class != "independent"
                or (v.independent and self._independent_verification_qualified(v))]

    def _verification_producer_keys(self, result: VerificationResult) -> set[str]:
        keys: set[str] = set()
        attestation = result.metadata.get("process_attestation")
        if isinstance(attestation, Mapping):
            executable = dict(attestation.get("executable_identity", {}))
            workspace = dict(attestation.get("workspace_identity", {}))
            if executable or workspace:
                keys.add(canonical_hash({"executable_identity": executable,
                                         "workspace_identity": workspace}))
        for evidence_id in result.evidence_ids:
            item = self.evidence.get(evidence_id)
            receipt = self.receipts.get(item.receipt_id) if item else None
            if receipt is None:
                continue
            executable = dict(receipt.executable_identity)
            workspace = dict(receipt.workspace_identity)
            if executable or workspace:
                keys.add(canonical_hash({"executable_identity": executable,
                                         "workspace_identity": workspace}))
        return keys

    def _independent_verification_qualified(self, result: VerificationResult) -> bool:
        """Independent is a measured relationship, never a verifier's label."""
        own = self._verification_producer_keys(result)
        if not own:
            return False
        peer_results = [prior for prior in self._raw_passed_verifications(result.candidate_id)
                        if prior.verification_id != result.verification_id]
        # If a peer exists but has no measured identity, disjointness cannot be
        # established; an unmeasured producer is not evidence of independence.
        if peer_results and any(not self._verification_producer_keys(prior)
                                for prior in peer_results):
            return False
        peers = set()
        for prior in peer_results:
            peers.update(self._verification_producer_keys(prior))
        # Every measured producer used by this claim must be disjoint from
        # every measured producer used by another passing claim.  ``own -
        # peers`` was too weak: a multi-source claim could smuggle in one
        # shared producer and one unrelated producer.
        return not own.intersection(peers)

    def _evidence_diversity_keys(self, evidence_ids: Iterable[str]) -> set[str]:
        """Return distinct *measured* producer identities, not output hashes."""
        keys: set[str] = set()
        for evidence_id in evidence_ids:
            item = self.evidence.get(evidence_id)
            if item is None:
                continue
            receipt = self.receipts.get(item.receipt_id)
            if receipt is None:
                continue
            executable = dict(receipt.executable_identity)
            workspace = dict(receipt.workspace_identity)
            # Labels, tool names, output hashes, and caller metadata are not
            # measurements. An absent measured identity contributes nothing.
            if executable or workspace:
                keys.add(canonical_hash({"executable_identity": executable,
                                         "workspace_identity": workspace}))
        return keys

    def _claim_graph(self, candidate_id: str) -> ClaimGraph:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        return ClaimGraph.from_task(self.task, candidate)

    def _adjudicate_candidate(self, candidate_id: str) -> Adjudication:
        """Run the one strict claim/policy adjudicator for a candidate."""
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        graph = self._claim_graph(candidate_id)
        results = tuple(v for v in self.verifications.values()
                        if v.candidate_id == candidate_id and not self._revoked(v.verifier))
        # Planner output is advisory but auditable: an uncovered plan claim is
        # never allowed to disappear from the adjudicator's final decision.
        plan = VerifierPlanner().plan(graph, tuple(
            self._executed_verifiers.get(v.verifier, _VerifierResultAdapter(v))
            for v in results
        ))
        adjudicator = ThreeValuedAdjudicator(policy=self.task.verification_policy)
        adjudication = adjudicator.adjudicate(
            graph, results,
            policy=self.task.verification_policy,
            evidence_registry=self.evidence,
            receipt_registry=self.receipts,
            candidate_evidence_ids=candidate.evidence_ids,
            candidate_receipt_ids=candidate.receipt_ids,
        )
        if plan.uncovered_claim_ids:
            # A planner cannot certify coverage; this diagnostic makes the
            # uncovered set explicit even when a malformed result omitted IDs.
            reasons = tuple(dict.fromkeys(adjudication.reasons + (
                "verifier plan leaves claims uncovered: " + ", ".join(plan.uncovered_claim_ids),)))
            adjudication = replace(adjudication, finalizable=False,
                                   status=(VerificationStatus.FAIL if adjudication.status is VerificationStatus.FAIL
                                           else VerificationStatus.UNKNOWN),
                                   blocking_claim_ids=tuple(dict.fromkeys(
                                       adjudication.blocking_claim_ids + plan.uncovered_claim_ids)),
                                   reasons=reasons)
        self._last_adjudication = adjudication
        return adjudication

    def verification_requirements(self, candidate_id: str) -> list[str]:
        """Return requirements reported by the same adjudicator used to finalize."""
        if self.compatibility_mode:
            # Compatibility changes only claim-coverage semantics; ordinary
            # receipt, diversity, class, quorum, independence, and boundary
            # policy gates remain fail-closed.
            passed = self.passed_verifications(candidate_id)
            policy = self.task.verification_policy
            classes = {v.verifier_class for v in passed}
            missing = [f"required verifier class not passed: {kind}" for kind in policy.required_verifier_classes if kind not in classes]
            if len(passed) < policy.minimum_passing_verifiers:
                missing.append(f"requires {policy.minimum_passing_verifiers} passing verifiers (currently {len(passed)})")
            if policy.require_independent and not any(v.independent and self._independent_verification_qualified(v) for v in passed):
                missing.append("requires a passing independently measured verifier provenance")
            if policy.require_evidence_diversity:
                producers = self._evidence_diversity_keys(eid for v in passed for eid in v.evidence_ids)
                if len(producers) < policy.minimum_evidence_sources:
                    missing.append("requires independent measured evidence producers from at least " + str(policy.minimum_evidence_sources) + " sources")
            boundary_rank = VerificationPolicy.TRUST_BOUNDARY_RANK[policy.minimum_trust_boundary]
            if not any(VerificationPolicy.TRUST_BOUNDARY_RANK[v.trust_boundary] >= boundary_rank for v in passed):
                missing.append("requires a passing verifier at trust boundary " + policy.minimum_trust_boundary)
            return missing
        adjudication = self._adjudicate_candidate(candidate_id)
        return list(adjudication.reasons) if not adjudication.finalizable else []

    def _revalidate_for_finalization(self, candidate_id: str) -> None:
        """Re-check all mutable/hash-bound inputs while the run lock is held."""
        candidate = self.candidates.get(candidate_id)
        if candidate is None or candidate.candidate_id != candidate_id:
            raise PermissionError("candidate identity changed")
        if candidate.session_id != self.session_id:
            raise PermissionError("candidate session identity changed")
        committed = self._artifact_commits.get(candidate_id)
        if committed is None or not hmac.compare_digest(committed[0], canonical_hash(candidate.artifact)):
            raise PermissionError("candidate artifact changed after registration")
        if not hmac.compare_digest(committed[1], self._dependency_hash(candidate)):
            raise PermissionError("candidate dependency graph changed after registration")
        if any(event.get("type") in {"run_finalized", "finalization_rejected"}
               for event in self.events):
            raise PermissionError("finalization history contains an unexpected prior terminal decision")
        self._reconcile_event_state()
        for receipt in self.receipts.values():
            if receipt.session_id != self.session_id:
                raise PermissionError("receipt session identity changed")
            try:
                canonical_hash(receipt.to_dict())
            except (TypeError, ValueError) as exc:
                raise PermissionError("receipt contains non-standard JSON metadata") from exc
            if canonical_hash(receipt.output) != receipt.output_hash:
                raise PermissionError("receipt output hash no longer matches output")
        for evidence in self.evidence.values():
            try:
                canonical_hash(evidence.to_dict())
            except (TypeError, ValueError) as exc:
                raise PermissionError("evidence contains non-standard JSON metadata") from exc
            self._validate_evidence(evidence)
        try:
            canonical_hash(candidate.to_dict())
        except (TypeError, ValueError) as exc:
            raise PermissionError("candidate contains non-standard JSON metadata") from exc
        for result in self.verifications.values():
            if result.candidate_id == candidate_id:
                self._validate_attested_verification(result)
                if result.trust_boundary == "process_attested":
                    if self.process_attestation_verifier is None:
                        raise PermissionError("external process attestation verifier is unavailable")
                    raw_attestation = result.metadata.get("process_attestation")
                    material = self._process_attestation_materials.get(result.verification_id)
                    if not raw_attestation or result.verification_id not in self._process_attestation_materials:
                        raise PermissionError("process attestation material is unavailable at finalization")
                    attestation = ProcessAttestation.from_dict(raw_attestation)
                    try:
                        verified_again = self.process_attestation_verifier.verify(attestation, material)
                    except Exception as exc:
                        raise PermissionError("process attestation could not be revalidated") from exc
                    if verified_again is not True:
                        raise PermissionError("process attestation could not be revalidated")
        # A started System 3 loop cannot be finalized half-way through.
        self._validate_system3_loop(candidate_id)
        # Validate all non-temporal telemetry before refreshing the event-bound
        # temporal projection.  This catches edits before the legitimate refresh.
        self._validate_system3_metadata(candidate)
        # Validate every auxiliary projection before refreshing the derived
        # event-grounded temporal map. This prevents a deleted map entry from
        # being silently recreated during finalization.
        self._validate_auxiliary_telemetry()
        # Temporal claims are derived data. Recompute them from the current
        # event chain and reject stale/fabricated candidate metadata.
        expected_temporal = self._event_temporal_report()
        if expected_temporal.get("is_satisfied") is not True:
            raise PermissionError("event-grounded temporal safety projection is unsatisfied")
        stored_temporal = candidate.metadata.get("system3_kripke")
        expected_hashes = expected_temporal["event_hashes"]
        stored_hashes = stored_temporal.get("event_hashes") if isinstance(stored_temporal, Mapping) else None
        # A verifier may append events after candidate registration. In that
        # case the old result must be an authentic prefix and is recomputed;
        # arbitrary/fabricated event claims are not accepted.
        if (not isinstance(stored_hashes, list) or
                expected_hashes[:len(stored_hashes)] != stored_hashes):
            raise PermissionError("event-grounded temporal result is stale or fabricated")
        candidate.metadata["system3_kripke"] = expected_temporal
        self.system3_kripke_invariants[candidate.candidate_id] = expected_temporal
        self._system3_commits[candidate.candidate_id] = self._system3_metadata_hash(candidate)
        self._validate_system3_metadata(candidate)
        self._validate_auxiliary_telemetry()

    def _validate_system3_record_candidate(self, candidate_id: str) -> Candidate:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown candidate: {candidate_id}")
        if candidate.session_id != self.session_id:
            raise PermissionError("System 3 candidate belongs to a different run")
        return candidate

    def observe_system3(self, candidate_id: str, observation: Any,
                        observation_id: str | None = None) -> dict[str, Any]:
        """Record a non-empty environment observation before prediction."""
        with self._lock:
            self._ensure_mutable(); self._validate_system3_record_candidate(candidate_id)
            if (candidate_id in self.system3_observations
                    or any(p.candidate_id == candidate_id for p in self.predictions.values())
                    or any(a.get("candidate_id") == candidate_id for a in self.system3_actions.values())):
                self._validate_system3_record_integrity(candidate_id)
            if observation is None or (isinstance(observation, str) and not observation.strip()):
                raise ValueError("System 3 observation must be non-empty")
            if isinstance(observation, (Mapping, list, tuple, set)) and not observation:
                raise ValueError("System 3 observation must be non-empty")
            obs_hash = canonical_hash(observation)
            if candidate_id in self.system3_observations:
                prior = self.system3_observations[candidate_id]
                if prior.get("observation_hash") == obs_hash:
                    raise ValueError("duplicate System 3 observation")
                raise ValueError("one observation is required per System 3 action")
            record = {"observation_id": observation_id or f"{candidate_id}:observation:1",
                      "run_id": self.session_id, "candidate_id": candidate_id,
                      "observation": copy.deepcopy(observation), "observation_hash": obs_hash,
                      "observed_at": utc_now()}
            record["record_hash"] = self._record_hash(record, "record_hash")
            self.system3_observations[candidate_id] = record
            self._event("system3_observation", candidate_id=candidate_id,
                        observation_hash=obs_hash, observation_id=record["observation_id"],
                        record_hash=record["record_hash"])
            self._commit_system3_loop(candidate_id)
            return copy.deepcopy(record)

    def predict_system3(self, candidate_id: str, action: str, predicted_outcome: Any,
                        confidence: float, falsification_condition: str,
                        *, prediction_id: str | None = None, policy_id: str = "",
                        observation: Any = None) -> Prediction:
        """Create the falsifiable hypothesis required before acting."""
        with self._lock:
            self._ensure_mutable(); self._validate_system3_record_candidate(candidate_id)
            if (candidate_id in self.system3_observations
                    or any(p.candidate_id == candidate_id for p in self.predictions.values())
                    or any(a.get("candidate_id") == candidate_id for a in self.system3_actions.values())):
                self._validate_system3_record_integrity(candidate_id)
            if observation is not None:
                if candidate_id in self.system3_observations:
                    if canonical_hash(observation) != self.system3_observations[candidate_id]["observation_hash"]:
                        raise ValueError("prediction observation differs from recorded observation")
                else:
                    self.observe_system3(candidate_id, observation)
            if candidate_id not in self.system3_observations:
                raise PermissionError("prediction requires an observation first")
            pid = prediction_id or f"{candidate_id}:prediction:{len(self.predictions) + 1}"
            prediction = Prediction(pid, self.session_id, candidate_id, action,
                                    self.system3_observations[candidate_id]["observation"],
                                    predicted_outcome, confidence, falsification_condition,
                                    policy_id=policy_id)
            if pid in self.predictions:
                raise ValueError("duplicate System 3 prediction")
            semantic = canonical_hash({"run_id": prediction.run_id, "candidate_id": candidate_id,
                                       "action": prediction.action,
                                       "observation_hash": prediction.observation_hash,
                                       "predicted_outcome_hash": prediction.predicted_outcome_hash,
                                       "confidence": prediction.confidence,
                                       "falsification_condition": prediction.falsification_condition})
            if any(canonical_hash({"run_id": p.run_id, "candidate_id": p.candidate_id,
                                   "action": p.action, "observation_hash": p.observation_hash,
                                   "predicted_outcome_hash": p.predicted_outcome_hash,
                                   "confidence": p.confidence,
                                   "falsification_condition": p.falsification_condition}) == semantic
                       for p in self.predictions.values()):
                raise ValueError("duplicate System 3 prediction")
            self.predictions[pid] = prediction
            self._event("system3_prediction", prediction_id=pid, candidate_id=candidate_id,
                        action=prediction.action, observation_hash=prediction.observation_hash,
                        record_hash=prediction.record_hash)
            self._commit_system3_loop(candidate_id)
            return copy.deepcopy(prediction)

    def act_system3(self, candidate_id: str, prediction_id: str,
                    *, action: str | None = None) -> dict[str, Any]:
        """Commit an action only from an existing prediction."""
        with self._lock:
            self._ensure_mutable(); self._validate_system3_record_candidate(candidate_id)
            self._validate_system3_record_integrity(candidate_id)
            prediction = self.predictions.get(prediction_id)
            if prediction is None or prediction.candidate_id != candidate_id or prediction.run_id != self.session_id:
                raise PermissionError("action requires a prediction bound to this candidate and run")
            chosen = action or prediction.action
            if chosen != prediction.action:
                raise PermissionError("action does not match prediction")
            if any(item.get("prediction_id") == prediction_id for item in self.system3_actions.values()):
                raise ValueError("prediction has already been acted on")
            action_id = f"{candidate_id}:action:{len(self.system3_actions) + 1}"
            record = {"action_id": action_id, "run_id": self.session_id,
                      "candidate_id": candidate_id, "prediction_id": prediction_id,
                      "action": chosen, "acted_at": utc_now(),
                      "prediction_hash": prediction.record_hash}
            record["action_hash"] = self._record_hash(record, "action_hash")
            self.system3_actions[action_id] = record
            self._event("system3_action", action_id=action_id, candidate_id=candidate_id,
                        prediction_id=prediction_id, action=chosen,
                        prediction_hash=prediction.record_hash, action_hash=record["action_hash"])
            self._commit_system3_loop(candidate_id)
            return copy.deepcopy(record)

    def record_system3_outcome(self, candidate_id: str, prediction_id: str,
                               receipt_id: str, observed_outcome: Any = None,
                               *, outcome_id: str | None = None,
                               observed_at: str | None = None,
                               _legacy_compatibility: bool = False) -> Outcome:
        """Bind an actual ToolReceipt to an acted prediction."""
        with self._lock:
            self._ensure_mutable(); candidate = self._validate_system3_record_candidate(candidate_id)
            legacy_allowed = (_legacy_compatibility
                              and not bool(self.task.metadata.get("require_system3_loop", False)))
            self._validate_system3_record_integrity(candidate_id,
                                                    allow_legacy_untrusted=legacy_allowed)
            prediction = self.predictions.get(prediction_id)
            receipt = self.receipts.get(receipt_id)
            if prediction is None or prediction.candidate_id != candidate_id or prediction.run_id != self.session_id:
                raise PermissionError("outcome prediction binding is invalid")
            if receipt is None or receipt.session_id != self.session_id:
                raise PermissionError("outcome requires a receipt from this run")
            if receipt.success is not True:
                raise PermissionError("outcome requires a successful tool receipt")
            if not receipt.trusted and not legacy_allowed:
                raise PermissionError("outcome requires a host/external-bound receipt")
            if (bool(self.task.metadata.get("require_system3_loop", False))
                    and not self._system3_receipt_authenticated(receipt)):
                raise PermissionError("strict System 3 outcome requires an authenticated receipt boundary")
            if receipt_id not in candidate.receipt_ids:
                raise PermissionError("outcome receipt is not attached to the candidate")
            if not any(item.get("prediction_id") == prediction_id and item.get("candidate_id") == candidate_id
                       for item in self.system3_actions.values()):
                raise PermissionError("outcome requires the predicted action to be committed first")
            actual = copy.deepcopy(receipt.output if observed_outcome is None else observed_outcome)
            if canonical_hash(actual) != receipt.output_hash:
                raise PermissionError("outcome is fabricated or not bound to receipt output")
            if prediction.action != receipt.capability and receipt.metadata.get("action") != prediction.action:
                raise PermissionError("receipt capability does not match predicted action")
            supplied_observed_at = observed_at or utc_now()
            if _parse_timestamp(supplied_observed_at, "observed_at") < _parse_timestamp(prediction.created_at, "created_at"):
                raise ValueError("outcome timestamp cannot precede its prediction")
            oid = outcome_id or f"{candidate_id}:outcome:{len(self.outcomes) + 1}"
            outcome = Outcome(oid, self.session_id, candidate_id, prediction_id,
                              prediction.action, receipt_id, actual,
                              observed_at=supplied_observed_at,
                              receipt_output_hash=receipt.output_hash)
            if oid in self.outcomes:
                raise ValueError("duplicate System 3 outcome")
            self.outcomes[oid] = outcome
            self._event("system3_outcome", outcome_id=oid, candidate_id=candidate_id,
                        prediction_id=prediction_id, receipt_id=receipt_id,
                        receipt_output_hash=outcome.receipt_output_hash,
                        record_hash=outcome.record_hash)
            self._commit_system3_loop(candidate_id)
            return copy.deepcopy(outcome)

    def update_system3(self, candidate_id: str, outcome_id: str | None = None) -> dict[str, Any]:
        """Update beliefs and policy from a receipt-backed outcome only."""
        with self._lock:
            self._ensure_mutable(); candidate = self._validate_system3_record_candidate(candidate_id)
            legacy_allowed = (
                not bool(self.task.metadata.get("require_system3_loop", False))
                and (getattr(self, "_legacy_cycle_in_progress", False)
                     or (isinstance(candidate.metadata.get("system3_loop"), Mapping)
                         and candidate.metadata["system3_loop"].get("_legacy_compatibility") is True))
            )
            if legacy_allowed and "system3_loop" not in candidate.metadata:
                # Stage the explicit compatibility marker before integrity
                # validation; it is committed and then included in the final
                # loop metadata below.
                candidate.metadata["system3_loop"] = {"_legacy_compatibility": True}
                self._system3_commits[candidate_id] = self._system3_metadata_hash(candidate)
            self._validate_system3_record_integrity(candidate_id,
                                                    allow_legacy_untrusted=legacy_allowed)
            eligible = [o for o in self.outcomes.values() if o.candidate_id == candidate_id]
            if outcome_id:
                outcome = self.outcomes.get(outcome_id)
                if outcome not in eligible:
                    raise PermissionError("update outcome is not bound to this candidate")
            elif eligible:
                outcome = eligible[-1]
            else:
                raise PermissionError("update requires an actual receipt-bound outcome")
            if outcome.outcome_id in self.system3_updates:
                raise ValueError("outcome has already been used for update")
            prediction = self.predictions.get(outcome.prediction_id)
            if prediction is None:
                raise PermissionError("update prediction is missing")
            error = prediction_error(prediction.predicted_outcome, outcome.observed_outcome)
            beliefs = revise_belief(prediction.confidence, error)
            revision = policy_revision(prediction.action, error,
                                       sum(1 for x in self.system3_policy_revisions.values()
                                           if x.get("candidate_id") == candidate_id) + 1)
            revision["candidate_id"] = candidate_id; revision["prediction_id"] = prediction.prediction_id
            update = {"update_id": f"{candidate_id}:update:{len(self.system3_updates) + 1}",
                      "run_id": self.session_id, "candidate_id": candidate_id,
                      "prediction_id": prediction.prediction_id, "outcome_id": outcome.outcome_id,
                      "prediction_error": error, "belief_revision": beliefs,
                      "policy_revision": revision, "updated_at": utc_now()}
            update["update_hash"] = self._record_hash(update, "update_hash")
            self.system3_updates[outcome.outcome_id] = update
            self.system3_beliefs[candidate_id] = copy.deepcopy(beliefs)
            self.system3_policy_revisions[candidate_id] = copy.deepcopy(revision)
            candidate = self.candidates[candidate_id]
            candidate.metadata["system3_loop"] = {"observation": copy.deepcopy(self.system3_observations[candidate_id]),
                # This marker records that only the legacy convenience wrapper
                # permitted an untrusted local receipt.  It is never accepted
                # for strict System 3 tasks.
                **({"_legacy_compatibility": True} if getattr(self, "_legacy_cycle_in_progress", False) else {}),
                "prediction_ids": [p.prediction_id for p in self.predictions.values() if p.candidate_id == candidate_id],
                "action_ids": [a["action_id"] for a in self.system3_actions.values() if a["candidate_id"] == candidate_id],
                "outcome_ids": [o.outcome_id for o in eligible], "updates": [copy.deepcopy(update)],
                "belief": copy.deepcopy(beliefs), "policy_revision": copy.deepcopy(revision)}
            self._event("system3_update", update_id=update["update_id"], candidate_id=candidate_id,
                        outcome_id=outcome.outcome_id, prediction_id=prediction.prediction_id,
                        prediction_error=error, update_hash=update["update_hash"])
            self._commit_system3_loop(candidate_id)
            self._system3_commits[candidate_id] = self._system3_metadata_hash(candidate)
            return copy.deepcopy(update)

    # Concise aliases are useful to adapters while keeping the explicit names
    # discoverable in the public runtime API.
    observe = observe_system3
    predict = predict_system3
    act = act_system3
    record_observation = observe_system3
    record_prediction = predict_system3
    record_action = act_system3
    record_outcome = record_system3_outcome
    update = update_system3
    record_update = update_system3

    @staticmethod
    def _record_hash(record: Mapping[str, Any], field: str, *, protocol_style: bool = False) -> str:
        payload = dict(record)
        if protocol_style:
            payload[field] = ""
        else:
            payload.pop(field, None)
        return canonical_hash(payload)

    def _system3_receipt_authenticated(self, receipt: ToolReceipt) -> bool:
        """Return whether a receipt crossed an authenticated host boundary.

        ``ToolReceipt.trust_boundary`` is descriptive metadata and can be
        self-minted by application code. Strict System 3 therefore additionally
        requires a receipt ID authenticated by ``record_receipt``'s explicit
        boundary verifier. Restored checkpoints intentionally lose this
        process-local authorization until the host re-supplies it.
        """
        return receipt.receipt_id in self._authenticated_receipt_ids

    def _validate_system3_record_integrity(self, candidate_id: str, *, complete: bool = False,
                                           allow_legacy_untrusted: bool = False) -> None:
        """Revalidate every live coding-loop record and all semantic bindings.

        The public maps intentionally remain ordinary Python containers for
        compatibility.  Consequently every transition rechecks their hashes,
        identities, and cross-links instead of trusting a caller-held reference.
        """
        candidate = self._validate_system3_record_candidate(candidate_id)
        self._validate_system3_metadata(candidate)
        obs = self.system3_observations.get(candidate_id)
        if obs is not None:
            if not isinstance(obs, Mapping) or obs.get("run_id") != self.session_id or obs.get("candidate_id") != candidate_id:
                raise PermissionError("System 3 observation binding is invalid")
            if obs.get("observation_hash") != canonical_hash(obs.get("observation")):
                raise PermissionError("System 3 observation hash is stale")
            if obs.get("record_hash") != self._record_hash(obs, "record_hash"):
                raise PermissionError("System 3 observation record was modified")
            _parse_timestamp(obs.get("observed_at"), "observed_at")

        predictions = [p for p in self.predictions.values() if p.candidate_id == candidate_id]
        for prediction in predictions:
            if prediction.run_id != self.session_id:
                raise PermissionError("System 3 prediction session binding is invalid")
            # Prediction's frozen constructor checks all value hashes and its
            # record_hash; reconstructing is the strongest check after restore.
            try:
                Prediction.from_dict(prediction.to_dict())
            except Exception as exc:
                raise PermissionError("System 3 prediction record was modified") from exc
            if obs is None or prediction.observation_hash != obs.get("observation_hash"):
                raise PermissionError("System 3 prediction is not bound to the observation")

        actions = [a for a in self.system3_actions.values() if a.get("candidate_id") == candidate_id]
        action_by_prediction: dict[str, Mapping[str, Any]] = {}
        for action in actions:
            if (action.get("run_id") != self.session_id or action.get("candidate_id") != candidate_id
                    or action.get("action_id") in (None, "")
                    or action.get("prediction_id") in action_by_prediction):
                raise PermissionError("System 3 action binding is invalid")
            prediction = self.predictions.get(action.get("prediction_id"))
            if prediction is None or prediction.candidate_id != candidate_id:
                raise PermissionError("System 3 action references an invalid prediction")
            if action.get("action") != prediction.action or action.get("prediction_hash") != prediction.record_hash:
                raise PermissionError("System 3 action is not semantically bound to its prediction")
            if action.get("action_hash") != self._record_hash(action, "action_hash"):
                raise PermissionError("System 3 action record was modified")
            action_by_prediction[prediction.prediction_id] = action

        outcomes = [o for o in self.outcomes.values() if o.candidate_id == candidate_id]
        outcome_by_prediction: dict[str, Outcome] = {}
        for outcome in outcomes:
            if outcome.run_id != self.session_id:
                raise PermissionError("System 3 outcome session binding is invalid")
            prediction = self.predictions.get(outcome.prediction_id)
            receipt = self.receipts.get(outcome.receipt_id)
            if (prediction is None or prediction.candidate_id != candidate_id
                    or outcome.action != prediction.action
                    or outcome.prediction_id not in action_by_prediction
                    or receipt is None or receipt.session_id != self.session_id
                    or receipt.success is not True
                    or (not receipt.trusted and not (
                        allow_legacy_untrusted
                        or (not bool(self.task.metadata.get("require_system3_loop", False))
                            and isinstance(candidate.metadata.get("system3_loop"), Mapping)
                            and candidate.metadata["system3_loop"].get("_legacy_compatibility") is True)))
                    or (bool(self.task.metadata.get("require_system3_loop", False))
                        and not self._system3_receipt_authenticated(receipt))
                    or outcome.receipt_id not in candidate.receipt_ids
                    or outcome.receipt_output_hash != receipt.output_hash
                    or outcome.outcome_hash != canonical_hash(outcome.observed_outcome)
                    or outcome.outcome_hash != receipt.output_hash
                    or outcome.record_hash != self._record_hash(outcome.to_dict(), "record_hash", protocol_style=True)):
                raise PermissionError("System 3 outcome is not bound to a successful current receipt")
            if _parse_timestamp(outcome.observed_at, "observed_at") < _parse_timestamp(prediction.created_at, "created_at"):
                raise PermissionError("System 3 outcome precedes its prediction")
            if prediction.prediction_id in outcome_by_prediction:
                raise PermissionError("System 3 prediction has multiple outcomes")
            outcome_by_prediction[prediction.prediction_id] = outcome

        updates = [u for u in self.system3_updates.values() if u.get("candidate_id") == candidate_id]
        seen_update_ids: set[str] = set()
        for update_key, update in ((key, value) for key, value in self.system3_updates.items()
                                    if value.get("candidate_id") == candidate_id):
            if (update_key != update.get("outcome_id")
                    or update.get("run_id") != self.session_id or update.get("update_id") in seen_update_ids
                    or update.get("outcome_id") not in self.outcomes):
                raise PermissionError("System 3 update binding is invalid")
            outcome = self.outcomes.get(update.get("outcome_id"))
            prediction = self.predictions.get(update.get("prediction_id")) if outcome else None
            if (outcome is None or prediction is None or outcome.candidate_id != candidate_id
                    or update.get("prediction_id") != outcome.prediction_id
                    or update.get("prediction_id") != prediction.prediction_id):
                raise PermissionError("System 3 update is not bound to its outcome and prediction")
            error = prediction_error(prediction.predicted_outcome, outcome.observed_outcome)
            expected_belief = revise_belief(prediction.confidence, error)
            expected_index = next((i for i, item in enumerate(updates, 1)
                                   if item.get("update_id") == update.get("update_id")), 0)
            if expected_index < 1:
                raise PermissionError("System 3 update ordering is invalid")
            expected_policy = policy_revision(prediction.action, error, expected_index)
            if (update.get("prediction_error") != error
                    or update.get("belief_revision") != expected_belief
                    or update.get("policy_revision") != {**expected_policy, "candidate_id": candidate_id,
                                                          "prediction_id": prediction.prediction_id}
                    or update.get("update_hash") != self._record_hash(update, "update_hash")):
                raise PermissionError("System 3 update telemetry was modified")
            seen_update_ids.add(update.get("update_id"))
        if updates:
            latest = updates[-1]
            if (self.system3_beliefs.get(candidate_id) != latest.get("belief_revision")
                    or self.system3_policy_revisions.get(candidate_id) != latest.get("policy_revision")):
                raise PermissionError("System 3 belief or policy revision is stale")
        elif candidate_id in self.system3_beliefs or candidate_id in self.system3_policy_revisions:
            raise PermissionError("System 3 belief or policy revision has no update")

        # A started strict loop must have exactly one complete chain per
        # prediction.  Partial validation is used before each transition.
        if complete:
            if not predictions or len(actions) != len(predictions) or len(outcomes) != len(predictions) or len(updates) != len(outcomes):
                raise PermissionError("System 3 loop requires prediction, action, actual outcome, and update")
            if obs is None or any(p.prediction_id not in action_by_prediction for p in predictions):
                raise PermissionError("System 3 prediction has no committed action")
            if any(p.prediction_id not in outcome_by_prediction for p in predictions):
                raise PermissionError("System 3 action has no actual outcome")
            if any(o.outcome_id not in self.system3_updates for o in outcomes):
                raise PermissionError("System 3 outcome has no update")
            loop_metadata = candidate.metadata.get("system3_loop")
            expected_metadata = {
                "observation": copy.deepcopy(obs),
                **({"_legacy_compatibility": True}
                   if (not bool(self.task.metadata.get("require_system3_loop", False))
                       and any(not self.receipts[o.receipt_id].trusted for o in outcomes)) else {}),
                "prediction_ids": [p.prediction_id for p in predictions],
                "action_ids": [a["action_id"] for a in actions],
                "outcome_ids": [o.outcome_id for o in outcomes],
                "updates": [copy.deepcopy(u) for u in updates],
                "belief": copy.deepcopy(self.system3_beliefs.get(candidate_id)),
                "policy_revision": copy.deepcopy(self.system3_policy_revisions.get(candidate_id)),
            }
            if not isinstance(loop_metadata, Mapping) or canonical_hash(loop_metadata) != canonical_hash(expected_metadata):
                raise PermissionError("System 3 candidate loop telemetry is stale")

    def _commit_system3_loop(self, candidate_id: str) -> None:
        self._system3_loop_commits[candidate_id] = self._system3_loop_hash(candidate_id)

    def _system3_loop_hash(self, candidate_id: str) -> str:
        return canonical_hash({
            "observations": {k: v for k, v in self.system3_observations.items()
                              if v.get("candidate_id") == candidate_id},
            "predictions": {k: v.to_dict() for k, v in self.predictions.items()
                             if v.candidate_id == candidate_id},
            "actions": {k: v for k, v in self.system3_actions.items()
                        if v.get("candidate_id") == candidate_id},
            "outcomes": {k: v.to_dict() for k, v in self.outcomes.items()
                         if v.candidate_id == candidate_id},
            "updates": {k: v for k, v in self.system3_updates.items()
                        if v.get("candidate_id") == candidate_id},
            "beliefs": self.system3_beliefs.get(candidate_id),
            "policy": self.system3_policy_revisions.get(candidate_id),
        })

    def _validate_system3_loop(self, candidate_id: str) -> None:
        """Require and fully revalidate a complete receipt-backed loop."""
        has_records = (candidate_id in self.system3_observations
                       or any(p.candidate_id == candidate_id for p in self.predictions.values())
                       or any(a.get("candidate_id") == candidate_id for a in self.system3_actions.values())
                       or any(o.candidate_id == candidate_id for o in self.outcomes.values())
                       or any(u.get("candidate_id") == candidate_id for u in self.system3_updates.values()))
        if not has_records:
            if bool(self.task.metadata.get("require_system3_loop", False)):
                raise PermissionError("System 3 loop is required before finalization")
            return
        self._validate_system3_record_integrity(candidate_id, complete=True)
        if candidate_id not in self._system3_loop_commits or not hmac.compare_digest(
                self._system3_loop_commits[candidate_id], self._system3_loop_hash(candidate_id)):
            raise PermissionError("System 3 loop telemetry commitment is missing or stale")

    def _validate_state_invariants(self) -> None:
        """Validate lifecycle consistency before accepting or restoring state."""
        self.validate_event_history()
        self._reconcile_event_state()
        self._validate_auxiliary_telemetry()
        finalized_events = [e for e in self.events if e.get("type") == "run_finalized"]
        if self.state is RunState.FINALIZED:
            if not self._checkpoint_trusted:
                raise PermissionError("finalized state is not trusted without an external checkpoint signature")
            if not self.final_candidate_id or self.final_candidate_id not in self.candidates:
                raise ValueError("finalized run has no valid final candidate")
            if len(finalized_events) != 1 or finalized_events[0].get("candidate_id") != self.final_candidate_id:
                raise ValueError("finalized run has an impossible finalization history")
            if self.missing_requirements(self.final_candidate_id) or self.verification_requirements(self.final_candidate_id):
                raise ValueError("finalized run does not satisfy its declared acceptance gates")
            self._validate_system3_loop(self.final_candidate_id)
            expected_temporal = self._event_temporal_report()
            stored_temporal = self.candidates[self.final_candidate_id].metadata.get("system3_kripke")
            if not isinstance(stored_temporal, Mapping) or canonical_hash(stored_temporal) != canonical_hash(expected_temporal):
                raise ValueError("finalized run has stale event-grounded temporal state")
        elif self.state is RunState.REJECTED:
            if self.final_candidate_id is not None:
                raise ValueError("rejected run cannot retain a final candidate")
            if finalized_events:
                raise ValueError("rejected run cannot contain a finalization event")
        elif finalized_events:
            raise ValueError("non-finalized run contains a finalization event")

    def finalize(self, candidate_id: str) -> Candidate:
        with self._lock:
            self._ensure_mutable()
            if self._restored_from_checkpoint and not self._checkpoint_trusted:
                raise PermissionError(
                    "restored active runs remain untrusted; supply an authenticated checkpoint"
                )
            if not hmac.compare_digest(self._task_commitment, canonical_hash(self.task.to_dict())):
                raise PermissionError("task contract changed after run creation")
            if candidate_id not in self.candidates:
                raise ValueError(f"unknown candidate: {candidate_id}")
            try:
                self._revalidate_for_finalization(candidate_id)
            except (ValueError, PermissionError) as exc:
                self._event("finalization_rejected", candidate_id=candidate_id,
                            missing=[str(exc)])
                self.state = RunState.REJECTED
                raise PermissionError("finalization rejected: " + str(exc)) from exc
            missing = self.missing_requirements(candidate_id) + self.verification_requirements(candidate_id)
            if missing:
                self._generate_triz_repair_recommendation(candidate_id, missing)
                self._event("finalization_rejected", candidate_id=candidate_id, missing=missing)
                self.state = RunState.REJECTED
                raise PermissionError("finalization rejected: " + "; ".join(missing))
            self.final_candidate_id = candidate_id
            # Append the terminal event before crossing the one-way boundary.
            self._event("run_finalized", candidate_id=candidate_id)
            final_temporal = self._event_temporal_report()
            if final_temporal.get("is_satisfied") is not True:
                raise PermissionError("event-grounded temporal safety projection is unsatisfied")
            self.candidates[candidate_id].metadata["system3_kripke"] = final_temporal
            self.system3_kripke_invariants[candidate_id] = final_temporal
            self._system3_commits[candidate_id] = self._system3_metadata_hash(self.candidates[candidate_id])
            self.state = RunState.FINALIZED
            self._checkpoint_trusted = True
            self._validate_state_invariants()
            return copy.deepcopy(object.__getattribute__(self, "candidates")[candidate_id])

    def reattest_restored_checkpoint(
        self, authenticator: CheckpointAuthenticator, signature: str
    ) -> None:
        """Explicitly authenticate an untrusted restored active run.

        The authenticator must cover the current complete checkpoint payload,
        including task/requirements, receipts, graph, and event commitments.
        This does not implement cross-session adaptation or transfer trust.
        """
        with self._lock:
            if not self._restored_from_checkpoint:
                raise ValueError("only restored checkpoints require re-attestation")
            if not callable(getattr(authenticator, "verify", None)):
                raise TypeError("checkpoint authenticator must implement verify")
            payload = self.to_dict()
            if authenticator.verify(payload, signature) is not True:
                raise PermissionError("restored checkpoint re-attestation failed")
            # The external signature now authenticates the current result
            # commitments as well.  Use them as the safe replacement for the
            # process-local HMAC secret; receipt authorizations remain empty
            # unless they were present in the authenticated checkpoint itself.
            self._checkpoint_verification_commitments = {
                str(key): str(value)
                for key, value in payload.get("verification_commitments", {}).items()
            }
            self._checkpoint_trusted = True

    def run_system3_meta_cycle(self, candidate_id: str) -> dict[str, Any]:
        """Execute a full System 3 meta-cognitive reflection cycle for a candidate."""
        with self._lock:
            self._ensure_mutable()
            candidate = self.candidates.get(candidate_id)
            if candidate is None:
                raise ValueError(f"unknown candidate: {candidate_id}")

            # Establish the auditable coding loop from a real candidate receipt.
            # Explicit callers can use the five public primitives themselves;
            # this convenience path never invents an outcome or success flag.
            if not any(p.candidate_id == candidate_id for p in self.predictions.values()):
                if not candidate.receipt_ids:
                    raise PermissionError("System 3 coding cycle requires an actual tool receipt")
                receipt = self.receipts[candidate.receipt_ids[0]]
                if bool(self.task.metadata.get("require_system3_loop", False)) and (
                        receipt.success is not True or not receipt.trusted
                        or not self._system3_receipt_authenticated(receipt)):
                    raise PermissionError(
                        "strict System 3 convenience cycle requires an authenticated host receipt"
                    )
                self.observe_system3(candidate_id, {
                    "candidate_artifact_hash": canonical_hash(candidate.artifact),
                    "receipt_id": receipt.receipt_id,
                })
                prediction = self.predict_system3(
                    candidate_id, receipt.capability,
                    {"expected_receipt_success": True}, 0.5,
                    "falsified when the bound tool receipt is unsuccessful",
                    policy_id=f"system3:{candidate_id}",
                )
                self.act_system3(candidate_id, prediction.prediction_id)
                # Explicitly scoped compatibility switch: only this legacy
                # convenience wrapper may use a self-minted diagnostic receipt.
                # The public outcome primitive and all strict tasks remain
                # receipt-bound and authenticated.
                self._legacy_cycle_in_progress = not bool(self.task.metadata.get("require_system3_loop", False))
                try:
                    outcome = self.record_system3_outcome(
                        candidate_id, prediction.prediction_id, receipt.receipt_id,
                        _legacy_compatibility=self._legacy_cycle_in_progress,
                    )
                    self.update_system3(candidate_id, outcome.outcome_id)
                finally:
                    self._legacy_cycle_in_progress = False

            # 1. Active Inference telemetry is grounded in the completed
            # receipt-bound update above.  Do not run a second synthetic
            # observe/predict/act/update cycle over a guessed observation.
            loop_update = next(u for u in reversed(list(self.system3_updates.values()))
                               if u.get("candidate_id") == candidate_id)
            loop_prediction = self.predictions[loop_update["prediction_id"]]
            observation = self.system3_observations[candidate_id]["observation"]
            fe_report = {
                "prediction_error": loop_update["prediction_error"],
                "belief_revision": copy.deepcopy(loop_update["belief_revision"]),
                "policy_revision": copy.deepcopy(loop_update["policy_revision"]),
                "observation_hash": self.system3_observations[candidate_id]["observation_hash"],
                "selected_policy": loop_prediction.action,
                "evaluated_policies_count": len([p for p in self.predictions.values() if p.candidate_id == candidate_id]),
            }

            # 2. Kripke model is a projection of actual append-only events.
            kripke_report = self._event_temporal_report()
            kripke_report["satisfied"] = kripke_report["is_satisfied"]

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
                    # Registration is an observed event, not proof of safety or
                    # correctness; never feed a synthetic PROVEN claim to bias
                    # analysis.
                    "epistemic_ledger": [{"tag": "OBSERVED", "claim": f"Candidate {candidate_id} registered"}],
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
                epistemic_uncertainty=round(loop_update["prediction_error"], 3),
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

            committed_cycle = copy.deepcopy(cycle_record)
            self.system3_meta_cycles.append(committed_cycle)
            candidate.metadata["system3_meta_cycle"] = copy.deepcopy(committed_cycle)
            self._event("system3_meta_cycle_completed", candidate_id=candidate_id,
                        cycle_hash=canonical_hash(committed_cycle))
            self._system3_commits[candidate_id] = self._system3_metadata_hash(candidate)
            self._validate_system3_metadata(candidate)
            return copy.deepcopy(cycle_record)

    def to_dict(self, authenticator: CheckpointAuthenticator | None = None) -> dict[str, Any]:
        """Serialize a checkpoint without secrets.

        A signature is optional for compatibility with active, local
        checkpoints.  Finalized/trusted checkpoints must be signed by an
        authenticator held outside the serialized payload.
        """
        system3_payload = {
            "free_energy": self.system3_free_energy,
            "active_inference": self.system3_active_inference,
            "kripke": self.system3_kripke_invariants,
            "hyperbolic": self.system3_hyperbolic_embeddings,
            "meta_cycles": self.system3_meta_cycles,
            "observations": self.system3_observations, "predictions": {k: v.to_dict() for k, v in self.predictions.items()},
            "actions": self.system3_actions, "outcomes": {k: v.to_dict() for k, v in self.outcomes.items()},
            "updates": self.system3_updates, "beliefs": self.system3_beliefs,
            "policy_revisions": self.system3_policy_revisions,
            "triz": self.triz_repair_recommendations,
        }
        events = copy.deepcopy(self.events)
        terminal_hash = events[-1].get("event_hash", "0" * 64) if events else "0" * 64
        # Authentication performed by record_receipt is process-local, so a
        # checkpoint must carry a signed, receipt-bound projection of it.  The
        # IDs alone are useful for compatibility; commitments bind each ID to
        # the exact serialized receipt restored below.
        authenticated_receipt_ids = sorted(self._authenticated_receipt_ids)
        authenticated_receipt_commitments = {
            receipt_id: canonical_hash(self.receipts[receipt_id].to_dict())
            for receipt_id in authenticated_receipt_ids
            if receipt_id in self.receipts
        }
        payload = {
            "version": "2.1", "session_id": self.session_id,
            "compatibility_mode": self.compatibility_mode,
            "cross_session_adaptation_implemented": CROSS_SESSION_ADAPTATION_IMPLEMENTED,
            "task": self.task.to_dict(),
            "task_commitment": self._task_commitment,
            "compatibility_commitment": self._compatibility_commitment,
            "state": self.state.value,
            "started_at": self.started_at,
            "receipts": [receipt.to_dict() for receipt in self.receipts.values()],
            "authenticated_receipt_ids": authenticated_receipt_ids,
            "authenticated_receipt_commitments": authenticated_receipt_commitments,
            "candidates": [candidate.to_dict() for candidate in self.candidates.values()],
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "verifications": [item.to_dict() for item in self.verifications.values()],
            # Public integrity commitments detect accidental/tampering edits;
            # they do not replace an external checkpoint signature.
            "verification_commitments": {
                item.verification_id: canonical_hash(item.to_dict())
                for item in self.verifications.values()
            },
            "events": events, "event_count": len(events),
            "event_terminal_commitment": canonical_hash({"count": len(events), "terminal_hash": terminal_hash}),
            "final_candidate_id": self.final_candidate_id,
            "invalidated_verifiers": dict(self.invalidated_verifiers),
            "revocation_commitments": dict(self._revocation_ledger),
            "system3_free_energy": copy.deepcopy(self.system3_free_energy),
            "system3_active_inference": copy.deepcopy(self.system3_active_inference),
            "system3_kripke_invariants": copy.deepcopy(self.system3_kripke_invariants),
            "system3_hyperbolic_embeddings": copy.deepcopy(self.system3_hyperbolic_embeddings),
            "system3_meta_cycles": copy.deepcopy(self.system3_meta_cycles),
            "system3_observations": copy.deepcopy(self.system3_observations),
            "predictions": [v.to_dict() for v in self.predictions.values()],
            "system3_actions": copy.deepcopy(self.system3_actions),
            "outcomes": [v.to_dict() for v in self.outcomes.values()],
            "system3_updates": copy.deepcopy(self.system3_updates),
            "system3_beliefs": copy.deepcopy(self.system3_beliefs),
            "system3_policy_revisions": copy.deepcopy(self.system3_policy_revisions),
            "system3_loop_commits": copy.deepcopy(self._system3_loop_commits),
            "triz_repair_recommendations": copy.deepcopy(self.triz_repair_recommendations),
            "artifact_commits": copy.deepcopy(self._artifact_commits),
            "system3_commits": copy.deepcopy(self._system3_commits),
            "system3_state_hash": canonical_hash(system3_payload),
        }
        if authenticator is not None:
            if not callable(getattr(authenticator, "sign", None)):
                raise TypeError("checkpoint authenticator must implement sign")
            payload["checkpoint_signature"] = authenticator.sign(payload)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any], authenticator: CheckpointAuthenticator | None = None) -> "FableRun":
        """Restore a run; trusted terminal state requires external authenticity."""
        if not isinstance(data, Mapping):
            raise TypeError("checkpoint must be a mapping")
        checkpoint_signature = data.get("checkpoint_signature")
        if data.get("cross_session_adaptation_implemented", False) is not False:
            raise ValueError("cross-session adaptation is not implemented")
        if str(data.get("version", "2.0")) == "2.1" and ("event_count" not in data or "event_terminal_commitment" not in data):
            raise ValueError("version 2.1 checkpoint lacks event terminal commitment")
        signed_payload = {k: copy.deepcopy(v) for k, v in data.items() if k != "checkpoint_signature"}
        checkpoint_trusted = False
        if authenticator is not None:
            if not callable(getattr(authenticator, "verify", None)):
                raise TypeError("checkpoint authenticator must implement verify")
            if not checkpoint_signature or authenticator.verify(signed_payload, checkpoint_signature) is not True:
                raise PermissionError("checkpoint authenticity verification failed")
            checkpoint_trusted = True
        elif data.get("state") in (RunState.FINALIZED.value, RunState.REJECTED.value) or checkpoint_signature:
            if data.get("state") in (RunState.FINALIZED.value, RunState.REJECTED.value):
                raise PermissionError("restored terminal state requires external checkpoint authenticity")
            if checkpoint_signature:
                raise PermissionError("checkpoint signature requires its external authenticator")
        task_data = dict(data["task"])
        policy_data = dict(task_data.pop("verification_policy", {}))
        task_data["constraints"] = tuple(task_data.get("constraints", ()))
        task_data["definition_of_done"] = tuple(task_data.get("definition_of_done", ()))
        task_data["required_capabilities"] = tuple(task_data.get("required_capabilities", ()))
        task_data["required_evidence"] = tuple(task_data.get("required_evidence", ()))
        task_data["verification_policy"] = VerificationPolicy(**policy_data)
        compatibility_mode = data.get("compatibility_mode", False)
        if type(compatibility_mode) is not bool:
            raise TypeError("compatibility_mode must be a boolean")
        run = cls(
            session_id=data["session_id"],
            task=TaskSpec(**task_data),
            state=RunState(data.get("state", RunState.CREATED.value)),
            compatibility_mode=compatibility_mode,
            started_at=data.get("started_at", utc_now()),
        )
        run._restoring = True
        supplied_task_commitment = data.get("task_commitment")
        if supplied_task_commitment is not None and not hmac.compare_digest(
                str(supplied_task_commitment), run._task_commitment):
            raise PermissionError("restored task contract commitment does not match payload")
        supplied_mode_commitment = data.get("compatibility_commitment")
        if supplied_mode_commitment is not None and not hmac.compare_digest(
                str(supplied_mode_commitment), run._compatibility_commitment):
            raise PermissionError("restored compatibility mode commitment does not match payload")
        # Attestation keys are process-local and intentionally never restored.
        run._checkpoint_trusted = checkpoint_trusted
        run._restored_from_checkpoint = True
        run.receipts = {}
        for item in data.get("receipts", []):
            receipt = ToolReceipt(**item)
            if receipt.session_id != run.session_id:
                raise ValueError("restored tool receipt belongs to a different session")
            if receipt.receipt_id in run.receipts:
                raise ValueError("duplicate restored tool receipt")
            run.receipts[receipt.receipt_id] = receipt
        # ``_authenticated_receipt_ids`` is intentionally not restored from
        # an unsigned checkpoint: the field is only meaningful when the whole
        # checkpoint was authenticated by the external checkpoint authority.
        # For an authenticated checkpoint, bind every restored authorization
        # to the exact receipt bytes and reject aliases, unknown IDs, and
        # self-minted receipts.  This prevents a model-supplied flag or a
        # replayed receipt from manufacturing strict System 3 trust.
        run._authenticated_receipt_ids = set()
        if checkpoint_trusted:
            raw_ids = data.get("authenticated_receipt_ids", ())
            if not isinstance(raw_ids, (list, tuple)) or any(not isinstance(item, str) for item in raw_ids):
                raise PermissionError("authenticated receipt authorization state is malformed")
            if len(set(raw_ids)) != len(raw_ids):
                raise PermissionError("authenticated receipt authorization state contains duplicates")
            raw_commitments = data.get("authenticated_receipt_commitments", {})
            if (not isinstance(raw_commitments, Mapping)
                    or any(not isinstance(key, str) for key in raw_commitments)):
                raise PermissionError("authenticated receipt commitments are malformed")
            commitments = dict(raw_commitments)
            if set(commitments) != set(raw_ids):
                raise PermissionError("authenticated receipt commitments are incomplete")
            for receipt_id in raw_ids:
                receipt = run.receipts.get(receipt_id)
                commitment = commitments.get(receipt_id)
                if (receipt is None or not receipt.trusted
                        or not isinstance(commitment, str)
                        or not hmac.compare_digest(commitment, canonical_hash(receipt.to_dict()))):
                    raise PermissionError("authenticated receipt authorization is not bound to its receipt")
            run._authenticated_receipt_ids = set(raw_ids)
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
            run._validate_candidate_graph(candidate)
        for candidate in run.candidates.values():
            run._artifact_commits[candidate.candidate_id] = (
                canonical_hash(candidate.artifact), run._dependency_hash(candidate)
            )
        run.verifications = {}
        supplied_verification_commits = {str(k): str(v) for k, v in dict(data.get("verification_commitments", {})).items()}
        seen_verifier_candidates: set[tuple[str, str]] = set()
        for item in data.get("verifications", []):
            result = VerificationResult(
                **{**item,
                   "reasons": tuple(item.get("reasons", ())),
                   "evidence_ids": tuple(item.get("evidence_ids", ()))})
            pair = (result.verifier, result.candidate_id)
            expected_commit = supplied_verification_commits.get(result.verification_id)
            if expected_commit is not None and not hmac.compare_digest(expected_commit, canonical_hash(result.to_dict())):
                raise PermissionError("restored verification commitment does not match payload")
            if pair in seen_verifier_candidates:
                raise ValueError("duplicate restored verifier verdict")
            run._validate_attested_verification(result, check_runtime=False)
            run.verifications[result.verification_id] = result
            seen_verifier_candidates.add(pair)
        if supplied_verification_commits and set(supplied_verification_commits) != set(run.verifications):
            raise PermissionError("restored verification commitments are incomplete")
        # Retain the already checked public commitments as the replacement for
        # the process-local runtime HMAC when (and only when) the enclosing
        # checkpoint was externally authenticated.
        if checkpoint_trusted:
            run._checkpoint_verification_commitments = dict(supplied_verification_commits)
        run.events = copy.deepcopy(data.get("events", []))
        run.final_candidate_id = data.get("final_candidate_id")
        run.invalidated_verifiers = dict(data.get("invalidated_verifiers", {}))
        # Reconstruct the monotonic private ledger from committed events; a
        # checkpoint field cannot introduce a revocation that has no event.
        run._revocation_ledger = run._revoked_verifiers_from_events()
        supplied_revocations = data.get("revocation_commitments")
        if supplied_revocations is not None and dict(supplied_revocations) != run._revocation_ledger:
            raise PermissionError("restored verifier revocation commitment does not match events")
        run.system3_free_energy = copy.deepcopy(data.get("system3_free_energy", {}))
        run.system3_active_inference = copy.deepcopy(data.get("system3_active_inference", {}))
        run.system3_kripke_invariants = copy.deepcopy(data.get("system3_kripke_invariants", {}))
        run.system3_hyperbolic_embeddings = copy.deepcopy(data.get("system3_hyperbolic_embeddings", {}))
        run.system3_meta_cycles = copy.deepcopy(data.get("system3_meta_cycles", []))
        run.system3_observations = copy.deepcopy(data.get("system3_observations", {}))
        run.predictions = {}
        for item in data.get("predictions", []):
            prediction = Prediction.from_dict(item)
            if prediction.run_id != run.session_id or prediction.prediction_id in run.predictions:
                raise ValueError("invalid restored System 3 prediction")
            run.predictions[prediction.prediction_id] = prediction
        run.system3_actions = copy.deepcopy(data.get("system3_actions", {}))
        run.outcomes = {}
        for item in data.get("outcomes", []):
            outcome = Outcome.from_dict(item)
            if outcome.run_id != run.session_id or outcome.outcome_id in run.outcomes:
                raise ValueError("invalid restored System 3 outcome")
            run.outcomes[outcome.outcome_id] = outcome
        run.system3_updates = copy.deepcopy(data.get("system3_updates", {}))
        run.system3_beliefs = copy.deepcopy(data.get("system3_beliefs", {}))
        run.system3_policy_revisions = copy.deepcopy(data.get("system3_policy_revisions", {}))
        run._system3_loop_commits = {str(k): str(v) for k, v in dict(data.get("system3_loop_commits", {})).items()}
        run.triz_repair_recommendations = copy.deepcopy(data.get("triz_repair_recommendations", []))
        # Restore active-inference telemetry through its semantic revalidator;
        # hashes alone would allow a self-consistent but numerically fabricated
        # prediction history.
        for inference_state in run.system3_active_inference.values():
            ActiveInferenceEngine.from_dict(inference_state)
        supplied_system3_hash = data.get("system3_state_hash")
        if supplied_system3_hash:
            actual_system3_hash = canonical_hash({
                "free_energy": run.system3_free_energy,
                "active_inference": run.system3_active_inference,
                "kripke": run.system3_kripke_invariants,
                "hyperbolic": run.system3_hyperbolic_embeddings,
                "meta_cycles": run.system3_meta_cycles,
                "observations": run.system3_observations, "predictions": {k: v.to_dict() for k, v in run.predictions.items()},
                "actions": run.system3_actions, "outcomes": {k: v.to_dict() for k, v in run.outcomes.items()},
                "updates": run.system3_updates, "beliefs": run.system3_beliefs,
                "policy_revisions": run.system3_policy_revisions,
                "triz": run.triz_repair_recommendations,
            })
            if not hmac.compare_digest(str(supplied_system3_hash), actual_system3_hash):
                raise PermissionError("restored System 3 state hash mismatch")
        supplied_commits = data.get("artifact_commits")
        if supplied_commits is not None:
            normalized = {str(k): tuple(v) for k, v in dict(supplied_commits).items()}
            if normalized != run._artifact_commits:
                raise PermissionError("restored artifact commitment does not match payload")
        supplied_system3_commits = data.get("system3_commits")
        run._system3_commits = ({str(k): str(v) for k, v in dict(supplied_system3_commits).items()}
                                if supplied_system3_commits is not None else {
                                    c.candidate_id: run._system3_metadata_hash(c)
                                    for c in run.candidates.values()
                                })
        if set(run._system3_commits) != set(run.candidates):
            raise PermissionError("restored System 3 telemetry commitments are incomplete")
        for candidate in run.candidates.values():
            run._validate_system3_metadata(candidate)
            if candidate.candidate_id in run._system3_loop_commits:
                run._validate_system3_loop(candidate.candidate_id)
        run.validate_event_history(
            expected_count=data.get("event_count") if "event_count" in data else None,
            expected_terminal_commitment=data.get("event_terminal_commitment")
            if "event_terminal_commitment" in data else None,
        )
        run._validate_state_invariants()
        run._restoring = False
        return run

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_id": self.task.task_id,
            "state": self.state.value,
            "compatibility_mode": self.compatibility_mode,
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
            "cross_session_adaptation": {
                "implemented": False,
                "status": "not_implemented; no authenticated persisted self-model is transferred",
            },
            "system3_state": {
                "free_energy_tracked": len(self.system3_free_energy),
                "kripke_invariants_tracked": len(self.system3_kripke_invariants),
                "hyperbolic_embeddings_tracked": len(self.system3_hyperbolic_embeddings),
                "meta_cycles_count": len(self.system3_meta_cycles),
                "triz_repairs_count": len(self.triz_repair_recommendations),
                "predictions": len(self.predictions), "outcomes": len(self.outcomes),
                "updates": len(self.system3_updates),
            },
        }


def new_run(session_id: str, task: TaskSpec, *, compatibility_mode: bool = False) -> FableRun:
    """Create an active run; strict claim adjudication is the default.

    ``compatibility_mode`` is an explicit escape hatch for legacy callers
    that only provide tuple/boolean verifier results and have no claim graph.
    It must never be inferred from missing fields in a purported strict run.
    """
    if type(compatibility_mode) is not bool:
        raise TypeError("compatibility_mode must be a boolean")
    run = FableRun(session_id=session_id, task=task, compatibility_mode=compatibility_mode)
    run.start()
    return run
