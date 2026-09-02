"""Typed, fail-closed verifier primitives for Fable V2.

The objects in this module are deliberately deterministic orchestration
contracts.  A model may suggest a claim or a check, but it cannot turn an
UNKNOWN into a PASS and it is never the final authority for adjudication.
The original :class:`FunctionVerifier` and :class:`CompositeVerifier` APIs are
kept intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import copy
import hashlib
import math
import re
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .protocol import (
    Candidate,
    TaskSpec,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
    canonical_hash,
)


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2,
                RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}[self]


@dataclass(frozen=True)
class Claim:
    """One atomic, scoped and falsifiable assertion in a task."""

    claim_id: str
    text: str
    predicate: str
    risk: RiskLevel | str
    scope: str
    falsification: str
    source: str = ""
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("claim_id", "text", "predicate", "scope", "falsification"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        try:
            risk = self.risk if isinstance(self.risk, RiskLevel) else RiskLevel(str(self.risk).upper())
        except ValueError as exc:
            raise ValueError("risk must be LOW, MEDIUM, HIGH, or CRITICAL") from exc
        object.__setattr__(self, "risk", risk)
        object.__setattr__(self, "dependencies", tuple(str(x) for x in self.dependencies))

    @property
    def risk_level(self) -> RiskLevel:
        return self.risk  # type: ignore[return-value]


_ATOMIC_SPLIT = re.compile(r"(?:\r?\n|\s*;\s*|\s+(?:&&|and)\s+)", re.IGNORECASE)
# Phrases here describe operations whose failure can cause material, security,
# privacy, or irreversible harm.  This is deliberately an intrinsic floor: a
# task's metadata may raise the risk classification, but never lower it.
_CRITICAL_WORDS = re.compile(
    r"(?:\b(?:safety|security|secure(?:ly)?|privacy|financial|money|irreversible|"
    r"delete|deletion|deleted|destructive|destroy|destroyed|erase|erasure|"
    r"remove|removed|wipe|wiped|overwrite|overwritten|drop|truncate|purge|"
    r"revoke|revocation|credential|credentials|password|secret|token|"
    r"authentication|authorization|permission|permissions|firewall|malware|"
    r"ransomware|exfiltrat(?:e|ion)|encrypt(?:ed|ion)?|decrypt(?:ed|ion)?|"
    r"disclos(?:e|ure)|leak|steal|privilege|root|shell|command|execute|"
    r"execution|compliance|harm|unsafe|untrusted|vulnerability|exploit|"
    r"tamper|integrity|sensitive|private|personal|incident)\b"
    r"|\b(?:rm\s+-rf|format\s+(?:the\s+)?disk|drop\s+(?:the\s+)?database|"
    r"disable\s+(?:the\s+)?(?:firewall|security)|bypass\s+(?:auth|authentication|authorization|access\s+control)|"
    r"run\s+(?:arbitrary|untrusted)\s+code|expose\s+(?:private|personal|sensitive)\s+data)\b)",
    re.I,
)


def _atomic_fragments(text: str) -> tuple[str, ...]:
    """Split contract prose conservatively; never silently drop a clause.

    ``re.split`` normally discards the empty tail of ``"a and"`` when the
    caller filters empty strings.  That is unsafe for a contract: an
    apparently covered objective can then lose its final conjunct.  Keep the
    split result long enough to reject leading, trailing, and repeated
    conjunctions (as well as empty semicolon/newline clauses).
    """
    raw = str(text).strip()
    if not raw:
        raise ValueError("claim text must contain a clause")
    # The separator intentionally requires whitespace on both sides for
    # ordinary prose, so explicitly catch a connector at either boundary
    # (including punctuation such as ``"first and."``).
    if re.search(r"(?:^|\s)(?:&&|and)(?:\s|[.!?,;:]*)*$", raw, re.IGNORECASE):
        raise ValueError("compound contract text contains a missing clause")
    if re.match(r"^(?:and|&&)(?:\s|[.!?,;:]|$)", raw, re.IGNORECASE):
        raise ValueError("compound contract text contains a missing clause")
    pieces = _ATOMIC_SPLIT.split(raw)
    fragments: list[str] = []
    for piece in pieces:
        fragment = piece.strip(" .")
        if not fragment or re.fullmatch(r"(?:&&|and)", fragment, re.IGNORECASE):
            raise ValueError("compound contract text contains a missing clause")
        fragments.append(fragment)
    return tuple(fragments)


def _claim_risk(text: str, source: str, task: TaskSpec) -> RiskLevel:
    """Infer risk while treating intrinsic danger as a non-downgradable floor."""
    if _CRITICAL_WORDS.search(text):
        intrinsic = RiskLevel.CRITICAL
    elif source in {"definition_of_done", "required_evidence"} or "must" in text.lower() or "required" in text.lower():
        intrinsic = RiskLevel.HIGH
    elif source == "constraints":
        intrinsic = RiskLevel.MEDIUM
    else:
        intrinsic = RiskLevel.LOW

    configured = task.metadata.get("risk")
    if isinstance(configured, str):
        try:
            configured_level = RiskLevel(configured.upper())
        except ValueError:
            configured_level = intrinsic
        # Metadata is allowed to make a claim stricter, never safer than its
        # words and origin warrant.  In particular ``risk=LOW`` cannot turn a
        # destructive/security claim (or a required HIGH claim) into LOW.
        return configured_level if configured_level.rank >= intrinsic.rank else intrinsic
    return intrinsic


@dataclass(frozen=True)
class ClaimGraph:
    """A deterministic graph of atomic claims and their dependencies.

    ``ClaimGraph.from_task`` is the normal entry point.  Every task objective,
    constraint, done condition, capability, and evidence requirement becomes
    an explicit claim.  Missing coverage is therefore observable rather than
    silently treated as a successful whole-candidate check.
    """

    claims: tuple[Claim, ...]
    edges: tuple[tuple[str, str], ...] = ()
    candidate_id: str = ""
    task_id: str = ""

    def __post_init__(self) -> None:
        claims = tuple(self.claims)
        ids = [claim.claim_id for claim in claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim graph contains duplicate claim ids")
        known = set(ids)

        # Dependencies are part of each claim's declaration, while ``edges``
        # is the graph-level representation used by planners and audit code.
        # Materialize both here so constructing a graph directly cannot silently
        # erase dependency information (the post-merge regression did exactly
        # that by accepting the dataclass default ``edges=()``).
        raw_edges: list[tuple[str, str]] = []
        for claim in claims:
            for dependency in claim.dependencies:
                dependency_id = str(dependency)
                if dependency_id not in known:
                    raise ValueError("claim dependency references an unknown claim")
                raw_edges.append((dependency_id, claim.claim_id))
        raw_edges.extend((str(a), str(b)) for a, b in self.edges)
        edges: list[tuple[str, str]] = []
        seen_edges: set[tuple[str, str]] = set()
        for edge in raw_edges:
            if edge[0] not in known or edge[1] not in known:
                raise ValueError("claim graph edge references an unknown claim")
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)

        # A dependency cycle makes the contract ordering ambiguous and can
        # cause an adjudicator/planner to recurse forever.  Validate the full
        # graph, including explicitly supplied graph-level edges.
        outgoing: dict[str, list[str]] = {claim_id: [] for claim_id in ids}
        for source, target in edges:
            outgoing[source].append(target)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("claim graph dependencies must be acyclic")
            if node in visited:
                return
            visiting.add(node)
            for child in outgoing[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for claim_id in ids:
            visit(claim_id)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "edges", tuple(edges))

    @classmethod
    def from_task(cls, task: TaskSpec, candidate: Candidate | None = None) -> "ClaimGraph":
        if not isinstance(task, TaskSpec):
            raise TypeError("from_task expects a TaskSpec")
        entries: list[tuple[str, str]] = [("objective", task.objective)]
        entries.extend(("constraints", value) for value in task.constraints)
        entries.extend(("definition_of_done", value) for value in task.definition_of_done)
        entries.extend(("required_capability", value) for value in task.required_capabilities)
        entries.extend(("required_evidence", value) for value in task.required_evidence)
        claims: list[Claim] = []
        for source, value in entries:
            for index, fragment in enumerate(_atomic_fragments(value)):
                # IDs are stable across processes and do not depend on object
                # identity, making plans and audit records reproducible.
                digest = hashlib.sha256(f"{task.task_id}|{source}|{index}|{fragment}".encode()).hexdigest()[:16]
                claim_id = f"claim-{digest}"
                claims.append(Claim(
                    claim_id=claim_id,
                    text=fragment,
                    predicate=f"satisfies({fragment})",
                    risk=_claim_risk(fragment, source, task),
                    scope=f"candidate:{candidate.candidate_id}" if candidate else f"task:{task.task_id}",
                    falsification=f"An observation showing that '{fragment}' is not true.",
                    source=source,
                ))
        edges = tuple((claims[i - 1].claim_id, claim.claim_id)
                      for i, claim in enumerate(claims) if i > 0)
        return cls(tuple(claims), edges, candidate.candidate_id if candidate else "", task.task_id)

    @classmethod
    def from_candidate(cls, candidate: Candidate, task: TaskSpec) -> "ClaimGraph":
        return cls.from_task(task, candidate)

    @classmethod
    def decompose(cls, candidate: Candidate | TaskSpec, task: TaskSpec | Candidate) -> "ClaimGraph":
        # Accept both natural call orders (candidate, task) and (task,
        # candidate) so adapters can migrate without a compatibility shim.
        if isinstance(candidate, TaskSpec) and isinstance(task, Candidate):
            return cls.from_task(candidate, task)
        if isinstance(candidate, Candidate) and isinstance(task, TaskSpec):
            return cls.from_task(task, candidate)
        raise TypeError("decompose expects a Candidate and a TaskSpec")

    build = from_task

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.claims)

    @property
    def critical_claims(self) -> tuple[Claim, ...]:
        return tuple(claim for claim in self.claims if claim.risk_level is RiskLevel.CRITICAL)

    def get(self, claim_id: str) -> Claim:
        for claim in self.claims:
            if claim.claim_id == claim_id:
                return claim
        raise KeyError(claim_id)


@dataclass(frozen=True)
class CalibrationMetrics:
    """Empirical rates retained for selecting, auditing, and recalibrating checks."""

    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0
    mutation_detection_rate: float = 0.0

    def __post_init__(self) -> None:
        for name in ("false_positive_rate", "false_negative_rate", "mutation_detection_rate"):
            value = getattr(self, name)
            if isinstance(value, bool) or not 0 <= float(value) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


class _FrozenDict(dict):
    """A JSON-compatible dict that rejects mutation at every nesting level."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("counterexample observation is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        # ``dataclasses.asdict`` and callers serializing a counterexample need
        # deepcopy to work; the returned copy is detached and mutable, while
        # the observation held by the record remains frozen.
        return {copy.deepcopy(key, memo): copy.deepcopy(value, memo)
                for key, value in self.items()}


class _FrozenList(list):
    """A JSON-compatible list that rejects all mutating operations."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("counterexample observation is immutable")

    __setitem__ = __delitem__ = append = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        return [copy.deepcopy(value, memo) for value in self]


def _freeze_observation(value: Any) -> Any:
    """Deep-copy a JSON observation into an immutable, hashable-by-content tree."""
    if isinstance(value, Mapping):
        return _FrozenDict({copy.deepcopy(key): _freeze_observation(child)
                            for key, child in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_observation(child) for child in value)
    if isinstance(value, tuple):
        return tuple(_freeze_observation(child) for child in value)
    # canonical_hash validates JSON-compatible values and rejects sets, bytes,
    # non-finite floats, and custom objects below.
    return copy.deepcopy(value)


@dataclass(frozen=True)
class Counterexample:
    """A concrete observation that falsifies one or more claims."""

    counterexample_id: str
    claim_ids: tuple[str, ...]
    observation: Any
    falsifies: str
    verifier: str = ""
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    # Appended for positional compatibility with older counterexample records.
    observation_hash: str = ""

    def __post_init__(self) -> None:
        if not self.counterexample_id or not self.falsifies:
            raise ValueError("counterexample id and falsification are required")
        object.__setattr__(self, "claim_ids", tuple(str(x) for x in self.claim_ids))
        object.__setattr__(self, "evidence_ids", tuple(str(x) for x in self.evidence_ids))
        object.__setattr__(self, "provenance_ids", tuple(str(x) for x in self.provenance_ids))
        observation = _freeze_observation(self.observation)
        expected_hash = canonical_hash(observation)
        if self.observation_hash and self.observation_hash != expected_hash:
            raise ValueError("observation_hash does not match observation")
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "observation_hash", expected_hash)

    def validate_integrity(self) -> None:
        """Re-hash the live observation before using this record.

        The frozen JSON-compatible wrappers protect ordinary callers, but a
        determined caller can invoke ``dict.__setitem__``/``list.append`` on
        their base classes (or use ``object.__setattr__`` on this dataclass).
        Counterexamples are security-relevant hard FAIL inputs, so their hash
        is checked at every trust boundary rather than treated as immutable by
        convention.
        """
        try:
            actual = canonical_hash(self.observation)
        except (TypeError, ValueError) as exc:
            raise ValueError("counterexample observation is not canonical JSON") from exc
        if not isinstance(self.observation_hash, str) or actual != self.observation_hash:
            raise ValueError("counterexample observation hash is stale")

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable representation after validation."""
        self.validate_integrity()
        return {
            "counterexample_id": self.counterexample_id,
            "claim_ids": list(self.claim_ids),
            "observation": copy.deepcopy(self.observation),
            "falsifies": self.falsifies,
            "verifier": self.verifier,
            "evidence_ids": list(self.evidence_ids),
            "provenance_ids": list(self.provenance_ids),
            "observation_hash": self.observation_hash,
        }


class CounterexampleStore:
    """Small explicit store that preserves and propagates counterexamples."""

    def __init__(self, counterexamples: Iterable[Counterexample] = ()) -> None:
        self._items: dict[str, Counterexample] = {}
        for item in counterexamples:
            self.add(item)

    def add(self, counterexample: Counterexample) -> Counterexample:
        if not isinstance(counterexample, Counterexample):
            raise TypeError("counterexample must be a Counterexample")
        counterexample.validate_integrity()
        prior = self._items.get(counterexample.counterexample_id)
        if prior is not None:
            prior.validate_integrity()
            if prior != counterexample:
                raise ValueError("counterexample id already contains different data")
        self._items[counterexample.counterexample_id] = counterexample
        return counterexample

    def add_many(self, counterexamples: Iterable[Counterexample]) -> tuple[Counterexample, ...]:
        return tuple(self.add(item) for item in counterexamples)

    record = add

    def get(self, counterexample_id: str) -> Counterexample:
        item = self._items[counterexample_id]
        item.validate_integrity()
        return item

    def for_claim(self, claim_id: str) -> tuple[Counterexample, ...]:
        items = tuple(item for item in self._items.values() if claim_id in item.claim_ids)
        for item in items:
            item.validate_integrity()
        return items

    def propagate(self, claim_ids: Iterable[str] | Any) -> tuple[Counterexample, ...]:
        if hasattr(claim_ids, "claim_ids"):
            claim_ids = getattr(claim_ids, "claim_ids")
        wanted = set(claim_ids)
        items = tuple(item for item in self._items.values() if wanted.intersection(item.claim_ids))
        for item in items:
            item.validate_integrity()
        return items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        for item in self._items.values():
            item.validate_integrity()
            yield item


class Verifier(Protocol):
    name: str

    def verify(self, candidate: Candidate) -> VerificationResult:
        ...


@dataclass(frozen=True)
class VerificationDecision:
    """Dependency-free result returned by new tri-valued check functions."""

    status: VerificationStatus | str
    reasons: tuple[str, ...] = ()
    score: float | None = None
    evidence_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    counterexample_ids: tuple[str, ...] = ()
    calibration: CalibrationMetrics = field(default_factory=CalibrationMetrics)

    def __post_init__(self) -> None:
        normalized = self.status if isinstance(self.status, VerificationStatus) else VerificationStatus(str(self.status).upper())
        object.__setattr__(self, "status", normalized)
        object.__setattr__(self, "reasons", tuple(str(x) for x in self.reasons))

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASS


# Short aliases are convenient for adapter authors and leave the existing
# VerificationResult name untouched.
VerifierDecision = VerificationDecision
Verdict = VerificationStatus
VerifierStatus = VerificationStatus


def _coerce_decision(raw: Any) -> VerificationDecision | VerificationResult:
    if isinstance(raw, bool):
        return VerificationDecision(VerificationStatus.PASS if raw else VerificationStatus.FAIL)
    if isinstance(raw, (VerificationDecision, VerificationResult)):
        return raw
    if isinstance(raw, Mapping):
        return VerificationDecision(**dict(raw))
    if isinstance(raw, tuple) or isinstance(raw, list):
        if len(raw) < 2:
            raise ValueError("verifier tuple must contain status and reasons")
        status, reasons = raw[0], raw[1]
        score = raw[2] if len(raw) > 2 else None
        if isinstance(status, bool):
            status = VerificationStatus.PASS if status else VerificationStatus.FAIL
        return VerificationDecision(status, tuple(reasons), score)
    raise TypeError("verifier must return VerificationResult, VerificationDecision, mapping, or tuple")


@dataclass(frozen=True)
class FunctionVerifier:
    """Adapt a deterministic function into a registered verifier.

    The legacy ``(passed, reasons, score)`` return shape remains supported;
    new checks may return :class:`VerificationDecision` for PASS/FAIL/UNKNOWN.
    """

    name: str
    check: Callable[[Candidate], Any] = lambda candidate: False
    verifier_class: str = "deterministic"
    independent: bool = False
    trust_boundary: str = "in_process"
    evidence_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    # ``claims_supported`` is an adapter-friendly alias for claim_ids.
    claims_supported: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    uncertainty: float = 0.5
    expected_information_gain: float = 0.5
    information_gain: float | None = None
    cost: float = 1.0
    calibration: CalibrationMetrics = field(default_factory=CalibrationMetrics)

    def __post_init__(self) -> None:
        """Validate planner metrics at registration time, before scoring.

        NaN and infinity are especially dangerous here: comparisons and
        ``max`` can make them appear harmless while corrupting ranking or
        serializable audit rationale.  Information and uncertainty metrics
        are normalized probabilities; cost is positive and is floored by the
        planner rather than accepted as a free/infinite check.
        """
        for name in ("uncertainty", "expected_information_gain"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.information_gain is not None:
            value = self.information_gain
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("information_gain must be a finite number")
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("information_gain must be between 0 and 1")
        if isinstance(self.cost, bool) or not isinstance(self.cost, (int, float)) or not math.isfinite(float(self.cost)):
            raise ValueError("cost must be a finite number")
        if float(self.cost) < 0.0:
            raise ValueError("cost must not be negative")

    def verify(self, candidate: Candidate) -> VerificationResult:
        decision = _coerce_decision(self.check(candidate))
        if isinstance(decision, VerificationResult):
            return decision
        reasons = decision.reasons or (("Verifier passed" if decision.passed else "Verifier did not establish the claim"),)
        evidence = decision.evidence_ids or self.evidence_ids
        claims = decision.claim_ids or self.claim_ids or self.claims_supported
        provenance = decision.provenance_ids or self.provenance_ids
        metrics = self.calibration if decision.calibration == CalibrationMetrics() else decision.calibration
        return VerificationResult(
            verification_id=f"{self.name}:{candidate.candidate_id}",
            session_id=candidate.session_id,
            candidate_id=candidate.candidate_id,
            verifier=self.name,
            passed=decision.passed,
            status=decision.status,
            reasons=tuple(reasons),
            score=decision.score,
            evidence_ids=tuple(evidence),
            claim_ids=tuple(claims),
            provenance_ids=tuple(provenance),
            counterexample_ids=decision.counterexample_ids,
            verifier_class=self.verifier_class,
            independent=self.independent,
            trust_boundary=self.trust_boundary,
            false_positive_rate=metrics.false_positive_rate,
            false_negative_rate=metrics.false_negative_rate,
            mutation_detection_rate=metrics.mutation_detection_rate,
        )


@dataclass(frozen=True)
class CompositeVerifier:
    """Run a list of verifiers and require every one to pass."""

    verifiers: tuple[Verifier, ...]

    @property
    def name(self) -> str:
        return "composite[" + ",".join(v.name for v in self.verifiers) + "]"

    def verify_all(self, candidate: Candidate) -> tuple[VerificationResult, ...]:
        return tuple(verifier.verify(candidate) for verifier in self.verifiers)

    def passed(self, candidate: Candidate) -> bool:
        results = self.verify_all(candidate)
        return bool(results) and all(result.passed for result in results)


@dataclass(frozen=True)
class PortfolioResult:
    results: tuple[VerificationResult, ...]
    status: VerificationStatus
    counterexamples: tuple[Counterexample, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASS

    @property
    def verdict(self) -> VerificationStatus:
        return self.status

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(eid for result in self.results for eid in result.evidence_ids))

    @property
    def provenance_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(pid for result in self.results for pid in result.provenance_ids))


class VerifierPortfolio:
    """Execute a portfolio and aggregate with strict three-valued semantics."""

    def __init__(self, verifiers: Iterable[Verifier] = ()) -> None:
        self.verifiers = tuple(verifiers)

    def verify(self, candidate: Candidate, selected: Iterable[Verifier] | None = None) -> PortfolioResult:
        verifiers = tuple(selected) if selected is not None else self.verifiers
        results = tuple(verifier.verify(candidate) for verifier in verifiers)
        if any(result.status is VerificationStatus.FAIL for result in results):
            status = VerificationStatus.FAIL
        elif any(result.status is VerificationStatus.UNKNOWN for result in results):
            status = VerificationStatus.UNKNOWN
        elif results:
            status = VerificationStatus.PASS
        else:
            status = VerificationStatus.UNKNOWN
        return PortfolioResult(results, status, reasons=tuple(
            reason for result in results for reason in result.reasons
        ))

    def verify_all(self, candidate: Candidate) -> tuple[VerificationResult, ...]:
        """Compatibility-shaped execution method."""
        return self.verify(candidate).results

    def passed(self, candidate: Candidate) -> bool:
        return self.verify(candidate).passed

    run = verify
    execute = verify


# Alternate spelling used by some hosts.
VerifierPortfolio = VerifierPortfolio


@dataclass(frozen=True)
class PlannedCheck:
    verifier: Verifier
    score: float
    covered_claim_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class VerifierPlan:
    checks: tuple[PlannedCheck, ...]
    uncovered_claim_ids: tuple[str, ...] = ()

    @property
    def verifiers(self) -> tuple[Verifier, ...]:
        return tuple(item.verifier for item in self.checks)

    @property
    def selected(self) -> tuple[Verifier, ...]:
        return self.verifiers


class VerifierPlanner:
    """Greedy, auditable selection using risk, uncertainty, gain, and cost."""

    def __init__(self, *, minimum_cost: float = 0.01) -> None:
        if isinstance(minimum_cost, bool) or not isinstance(minimum_cost, (int, float)) \
                or not math.isfinite(float(minimum_cost)) or float(minimum_cost) <= 0:
            raise ValueError("minimum_cost must be a finite positive number")
        self.minimum_cost = float(minimum_cost)

    def _score(self, verifier: Verifier, claim_graph: ClaimGraph, coverage: Sequence[Claim]) -> float:
        risk = max((claim.risk_level.rank for claim in coverage), default=1) / 4
        uncertainty = float(getattr(verifier, "uncertainty", 0.5))
        configured_gain = getattr(verifier, "information_gain", None)
        gain = float(configured_gain if configured_gain is not None
                     else getattr(verifier, "expected_information_gain", 0.5))
        cost = float(getattr(verifier, "cost", 1.0))
        if (not math.isfinite(uncertainty) or not 0.0 <= uncertainty <= 1.0
                or not math.isfinite(gain) or not 0.0 <= gain <= 1.0
                or not math.isfinite(cost) or cost < 0.0):
            raise ValueError("verifier metrics must be finite and within their allowed ranges")
        cost = max(cost, self.minimum_cost)
        # Calibration penalizes checks with known false negatives/positives;
        # it never turns a failing check into a pass.
        calibration = getattr(verifier, "calibration", CalibrationMetrics())
        calibration_rates = (float(getattr(calibration, "false_positive_rate", 0.0)),
                             float(getattr(calibration, "false_negative_rate", 0.0)))
        if any(not math.isfinite(rate) or not 0.0 <= rate <= 1.0 for rate in calibration_rates):
            raise ValueError("verifier calibration metrics must be finite and between 0 and 1")
        penalty = 1.0 - sum(calibration_rates) / 2
        return max(0.0, (0.5 + risk) * (0.5 + uncertainty) * max(gain, 0.0) * penalty / cost)

    @staticmethod
    def _coverage(verifier: Verifier, graph: ClaimGraph, uncovered: set[str]) -> tuple[Claim, ...]:
        # In strict mode an undeclared verifier covers nothing. Treating an
        # empty declaration as "all claims" is precisely the overclaim that
        # the claim graph is intended to expose.
        declared = set(getattr(verifier, "claim_ids", ()) or getattr(verifier, "claims_supported", ()))
        return tuple(claim for claim in graph.claims
                     if claim.claim_id in uncovered and claim.claim_id in declared)

    def plan(self, claim_graph: ClaimGraph, portfolio: VerifierPortfolio | Iterable[Verifier]) -> VerifierPlan:
        verifiers = tuple(portfolio.verifiers if isinstance(portfolio, VerifierPortfolio) else portfolio)
        remaining = set(claim_graph.claim_ids)
        chosen: list[PlannedCheck] = []
        available = list(verifiers)
        while remaining and available:
            scored = []
            for verifier in available:
                coverage = self._coverage(verifier, claim_graph, remaining)
                if coverage:
                    scored.append((self._score(verifier, claim_graph, coverage), verifier, coverage))
            if not scored:
                break
            score, verifier, coverage = max(scored, key=lambda item: (item[0], len(item[2])))
            chosen.append(PlannedCheck(
                verifier, score, tuple(claim.claim_id for claim in coverage),
                f"risk={max(claim.risk_level.value for claim in coverage)}; "
                f"uncertainty={getattr(verifier, 'uncertainty', 0.5):.3f}; "
                f"information_gain={getattr(verifier, 'expected_information_gain', 0.5):.3f}; "
                f"cost={getattr(verifier, 'cost', 1.0):.3f}",
            ))
            remaining.difference_update(claim.claim_id for claim in coverage)
            available.remove(verifier)
        return VerifierPlan(tuple(chosen), tuple(sorted(remaining)))

    def plan_for(self, candidate: Candidate, task: TaskSpec, verifiers: Iterable[Verifier]) -> VerifierPlan:
        return self.plan(ClaimGraph.from_task(task, candidate), verifiers)

    select = plan


@dataclass(frozen=True)
class Adjudication:
    status: VerificationStatus
    finalizable: bool
    blocking_claim_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    counterexamples: tuple[Counterexample, ...] = ()
    independent_verifier_ids: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.finalizable and self.status is VerificationStatus.PASS

    @property
    def can_finalize(self) -> bool:
        return self.finalizable


class ThreeValuedAdjudicator:
    """Mechanical finalization gate; no model judgment is consulted.

    The adjudicator is intentionally usable both standalone and by
    :class:`FableRun`.  When a ``VerificationPolicy`` and object registries are
    supplied, it is the single authority for policy counts and reference
    resolution; callers must not separately "interpret" a passing portfolio.
    """

    def __init__(self, *, require_independent: bool = True,
                 minimum_independent_verifiers: int = 1,
                 allow_noncritical_unknown: bool = False,
                 policy: VerificationPolicy | None = None) -> None:
        self.policy = policy
        self.require_independent = (policy.require_independent if policy is not None
                                    else require_independent)
        self.minimum_independent_verifiers = minimum_independent_verifiers
        self.allow_noncritical_unknown = allow_noncritical_unknown

    @staticmethod
    def _field(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, Mapping):
            return item.get(name, default)
        return getattr(item, name, default)

    @staticmethod
    def _verifier_id(result: VerificationResult) -> str:
        # A verifier ID, rather than a result record ID, is the independence
        # unit. Duplicate records from one verifier cannot satisfy a quorum.
        return str(result.verifier or result.verification_id)

    @staticmethod
    def _registry_item(registry: Mapping[str, Any], key: str,
                       object_id: str) -> Any | None:
        """Resolve a registry reference only when key and object ID agree."""
        item = registry.get(key)
        if item is None or ThreeValuedAdjudicator._field(item, object_id, "") != key:
            return None
        return item

    @staticmethod
    def _evidence_matches_receipt(evidence: Any, receipt: Any) -> bool:
        """Require content-addressed evidence to equal its receipt output."""
        if evidence is None or receipt is None:
            return False
        try:
            content = ThreeValuedAdjudicator._field(evidence, "content")
            content_hash = ThreeValuedAdjudicator._field(evidence, "content_hash", "")
            source_hash = ThreeValuedAdjudicator._field(evidence, "source_output_hash", "")
            output_hash = ThreeValuedAdjudicator._field(receipt, "output_hash", "")
            return (isinstance(content_hash, str) and isinstance(source_hash, str)
                    and isinstance(output_hash, str) and bool(content_hash)
                    and canonical_hash(content) == content_hash
                    and content_hash == source_hash == output_hash)
        except (TypeError, ValueError):
            return False

    def adjudicate(self, claim_graph: ClaimGraph,
                   portfolio: PortfolioResult | Iterable[VerificationResult],
                   counterexample_store: CounterexampleStore | None = None,
                   *, policy: VerificationPolicy | None = None,
                   evidence_registry: Mapping[str, Any] | None = None,
                   receipt_registry: Mapping[str, Any] | None = None,
                   candidate_evidence_ids: Iterable[str] | None = None,
                   candidate_receipt_ids: Iterable[str] | None = None) -> Adjudication:
        # Also accept adjudicate(portfolio, claim_graph), a common pipeline
        # ordering when the portfolio is produced before decomposition.
        if isinstance(portfolio, ClaimGraph) and not isinstance(claim_graph, ClaimGraph):
            claim_graph, portfolio = portfolio, claim_graph  # type: ignore[assignment]
        active_policy = policy or self.policy
        if isinstance(portfolio, PortfolioResult):
            results = portfolio.results
            portfolio_counterexamples = portfolio.counterexamples
        else:
            results = tuple(portfolio)
            portfolio_counterexamples = ()

        by_claim: dict[str, list[VerificationResult]] = {claim.claim_id: [] for claim in claim_graph.claims}
        blocking: list[str] = []
        reasons: list[str] = []
        malformed_reference = False
        graph_ids = set(by_claim)
        candidate_evidence = (None if candidate_evidence_ids is None else set(candidate_evidence_ids))
        candidate_receipts = (None if candidate_receipt_ids is None else set(candidate_receipt_ids))
        for result in results:
            if (claim_graph.candidate_id and result.candidate_id != claim_graph.candidate_id):
                malformed_reference = True
                reasons.append(f"verifier {result.verifier} is outside the candidate claim graph")
            expected_scope = f"task:{claim_graph.task_id};candidate:{claim_graph.candidate_id}" if claim_graph.candidate_id else ""
            if expected_scope and result.scope and result.scope != expected_scope:
                malformed_reference = True
                reasons.append(f"verifier {result.verifier} has a scope outside this task/candidate")
            metadata = result.metadata if isinstance(result.metadata, Mapping) else {}
            target_ids = tuple(result.claim_ids or metadata.get("claim_ids", ()))
            if not target_ids and metadata.get("claim_id"):
                target_ids = (str(metadata["claim_id"]),)
            # Even a one-claim graph requires an explicit claim binding in
            # strict adjudication; an omitted declaration is uncovered, not
            # implicit coverage.
            unknown_claims = [claim_id for claim_id in target_ids if claim_id not in graph_ids]
            if unknown_claims:
                malformed_reference = True
                reasons.append(f"verifier {result.verifier} references claims outside the graph: {unknown_claims}")
            if evidence_registry is not None:
                for evidence_id in result.evidence_ids:
                    # Do not let a registry alias an object under a different
                    # ID. This matters for standalone adjudication where the
                    # runtime's own map reconciliation is not available.
                    item = self._registry_item(evidence_registry, evidence_id, "evidence_id")
                    valid = (item is not None and
                             (candidate_evidence is None or evidence_id in candidate_evidence) and
                             self._field(item, "session_id", result.session_id) == result.session_id and
                             self._field(item, "integrity_bound", True) is not False)
                    receipt_id = self._field(item, "receipt_id") if item is not None else None
                    if receipt_registry is not None:
                        receipt = (self._registry_item(receipt_registry, str(receipt_id), "receipt_id")
                                   if receipt_id else None)
                        valid = (valid and receipt is not None
                                 and self._field(receipt, "session_id", result.session_id) == result.session_id
                                 and self._evidence_matches_receipt(item, receipt))
                    if not valid:
                        malformed_reference = True
                        reasons.append(f"verifier {result.verifier} references unresolved or unrelated evidence: {evidence_id}")
            if receipt_registry is not None:
                for provenance_id in result.provenance_ids:
                    evidence_item = (self._registry_item(evidence_registry, provenance_id, "evidence_id")
                                     if evidence_registry is not None else None)
                    receipt_item = self._registry_item(receipt_registry, provenance_id, "receipt_id")
                    valid = receipt_item is not None or evidence_item is not None
                    if receipt_item is not None:
                        valid = valid and self._field(receipt_item, "session_id", result.session_id) == result.session_id
                    if evidence_item is not None:
                        linked_id = self._field(evidence_item, "receipt_id", "")
                        linked_receipt = (self._registry_item(receipt_registry, str(linked_id), "receipt_id")
                                          if linked_id else None)
                        valid = (valid and self._field(evidence_item, "session_id", result.session_id) == result.session_id
                                 and linked_receipt is not None
                                 and self._evidence_matches_receipt(evidence_item, linked_receipt))
                    if candidate_receipts is not None or candidate_evidence is not None:
                        valid = valid and ((candidate_receipts is not None and provenance_id in candidate_receipts)
                                           or (candidate_evidence is not None and provenance_id in candidate_evidence))
                    if not valid:
                        malformed_reference = True
                        reasons.append(f"verifier {result.verifier} references unresolved or unrelated provenance: {provenance_id}")
            for claim_id in target_ids:
                if claim_id in by_claim:
                    by_claim[claim_id].append(result)

        pass_results: list[VerificationResult] = []
        for claim in claim_graph.claims:
            claim_results = by_claim[claim.claim_id]
            if any(result.status is VerificationStatus.FAIL for result in claim_results):
                blocking.append(claim.claim_id)
                reasons.append(f"claim {claim.claim_id} has a FAIL")
                continue
            if not claim_results:
                # ``allow_noncritical_unknown`` only affects an explicit
                # UNKNOWN result.  Absence of a verifier is uncovered data,
                # never an implicit PASS, regardless of claim risk.
                blocking.append(claim.claim_id)
                reasons.append(f"claim {claim.claim_id} is UNKNOWN or uncovered")
                continue
            if any(result.status is VerificationStatus.UNKNOWN for result in claim_results):
                if not self.allow_noncritical_unknown or claim.risk_level is RiskLevel.CRITICAL:
                    blocking.append(claim.claim_id)
                reasons.append(f"claim {claim.claim_id} is UNKNOWN or uncovered")
                continue
            passing = [result for result in claim_results if result.status is VerificationStatus.PASS]
            if not passing:
                blocking.append(claim.claim_id)
                reasons.append(f"claim {claim.claim_id} has no PASS")
                continue
            pass_results.extend(passing)
            for result in passing:
                if not result.evidence_ids:
                    blocking.append(claim.claim_id)
                    reasons.append(f"claim {claim.claim_id} PASS lacks evidence provenance")
                if not result.provenance_ids:
                    blocking.append(claim.claim_id)
                    reasons.append(f"claim {claim.claim_id} PASS lacks verifier provenance")

        # Deduplicate by verifier ID before all quorum/independence counting.
        unique_pass: dict[str, VerificationResult] = {}
        for result in pass_results:
            unique_pass.setdefault(self._verifier_id(result), result)
        independent = [result for result in unique_pass.values() if result.independent]
        qualified_independent: list[VerificationResult] = []
        for result in independent:
            own = set(result.provenance_ids)
            if own and all(own.isdisjoint(set(peer.provenance_ids))
                           for peer in unique_pass.values()
                           if self._verifier_id(peer) != self._verifier_id(result)):
                qualified_independent.append(result)
        if self.require_independent and len(qualified_independent) < self.minimum_independent_verifiers:
            reasons.append("requires independently-provenanced passing verifier(s)")
            blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)

        # Apply declared class and minimum-count requirements here, alongside
        # claim semantics. This prevents a second, weaker runtime policy path.
        if active_policy is not None:
            classes = {result.verifier_class for result in unique_pass.values()}
            for required_class in active_policy.required_verifier_classes:
                if required_class not in classes:
                    reasons.append(f"required verifier class not passed: {required_class}")
                    blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)
            if len(unique_pass) < active_policy.minimum_passing_verifiers:
                reasons.append(f"requires {active_policy.minimum_passing_verifiers} passing verifiers (currently {len(unique_pass)})")
                blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)
            if active_policy.require_independent and not qualified_independent:
                # The constructor already applies this requirement, but keep
                # this explicit for policies passed per-call.
                if "requires independently-provenanced passing verifier(s)" not in reasons:
                    reasons.append("requires independently-provenanced passing verifier(s)")
                blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)
            try:
                boundary_rank = VerificationPolicy.TRUST_BOUNDARY_RANK[active_policy.minimum_trust_boundary]
            except KeyError:
                boundary_rank = 0
            if not any(VerificationPolicy.TRUST_BOUNDARY_RANK.get(result.trust_boundary, -1) >= boundary_rank
                       for result in unique_pass.values()):
                reasons.append("requires a passing verifier at trust boundary " + active_policy.minimum_trust_boundary)
                blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)
            if active_policy.require_evidence_diversity and evidence_registry is not None and receipt_registry is not None:
                producers: set[str] = set()
                for result in unique_pass.values():
                    for evidence_id in result.evidence_ids:
                        evidence = evidence_registry.get(evidence_id)
                        receipt = receipt_registry.get(self._field(evidence, "receipt_id", "")) if evidence is not None else None
                        if receipt is not None:
                            executable = self._field(receipt, "executable_identity", {})
                            workspace = self._field(receipt, "workspace_identity", {})
                            if executable or workspace:
                                producers.add(canonical_hash({"executable_identity": dict(executable), "workspace_identity": dict(workspace)}))
                if len(producers) < active_policy.minimum_evidence_sources:
                    reasons.append("requires independent measured evidence producers from at least " + str(active_policy.minimum_evidence_sources) + " sources")
                    blocking.extend(claim.claim_id for claim in claim_graph.claims if claim.claim_id not in blocking)

        all_counterexamples = list(portfolio_counterexamples)
        for item in all_counterexamples:
            if not isinstance(item, Counterexample):
                raise TypeError("portfolio counterexamples must be Counterexample objects")
            item.validate_integrity()
        if counterexample_store is not None:
            all_counterexamples.extend(counterexample_store.propagate(claim_graph.claim_ids))
        for result in results:
            for counterexample_id in result.counterexample_ids:
                item = None
                if counterexample_store is not None:
                    try:
                        item = counterexample_store.get(counterexample_id)
                    except KeyError:
                        item = None
                if item is None:
                    item = Counterexample(
                        counterexample_id=counterexample_id,
                        claim_ids=result.claim_ids,
                        observation={"source": result.verifier},
                        falsifies="reported by verifier",
                        verifier=result.verifier,
                        evidence_ids=result.evidence_ids,
                        provenance_ids=result.provenance_ids,
                    )
                all_counterexamples.append(item)
        # Any counterexample is a hard falsification. It cannot be neutralized
        # by another PASS, and malformed/unknown targets fail closed as well.
        counterexample_claims: set[str] = set()
        for item in all_counterexamples:
            targets = set(item.claim_ids)
            if not targets or not targets.issubset(graph_ids):
                malformed_reference = True
                reasons.append(f"counterexample {item.counterexample_id} is outside the claim graph")
            counterexample_claims.update(targets & graph_ids)
            reasons.append(f"counterexample {item.counterexample_id} forces FAIL")
        blocking.extend(counterexample_claims)
        if all_counterexamples:
            blocking.extend(claim_graph.claim_ids if not counterexample_claims else ())

        unique_blocking = tuple(dict.fromkeys(blocking))
        hard_fail = (any(result.status is VerificationStatus.FAIL for result in results)
                     or bool(all_counterexamples) or malformed_reference
                     or any("has a FAIL" in reason for reason in reasons))
        status = VerificationStatus.FAIL if hard_fail else (
            VerificationStatus.UNKNOWN if unique_blocking or any(
                result.status is VerificationStatus.UNKNOWN for result in results
            ) else VerificationStatus.PASS
        )
        evidence_ids = tuple(dict.fromkeys(eid for result in pass_results for eid in result.evidence_ids))
        provenance_ids = tuple(dict.fromkeys(pid for result in pass_results for pid in result.provenance_ids))
        return Adjudication(
            status=status,
            finalizable=(status is VerificationStatus.PASS and not unique_blocking),
            blocking_claim_ids=unique_blocking,
            reasons=tuple(dict.fromkeys(reasons)),
            evidence_ids=evidence_ids,
            provenance_ids=provenance_ids,
            counterexamples=tuple({item.counterexample_id: item for item in all_counterexamples}.values()),
            independent_verifier_ids=tuple(self._verifier_id(result) for result in qualified_independent),
        )

    evaluate = adjudicate
    finalize = adjudicate


# Safe deterministic extension hooks.  Adapters can implement these protocols
# without giving an LLM authority over the final verdict.
class MutationOperator(Protocol):
    def mutate(self, candidate: Candidate) -> Iterable[Any]: ...


class MetamorphicRelation(Protocol):
    def transform(self, candidate: Candidate) -> Any: ...
    def compare(self, original: Candidate, transformed: Any) -> Any: ...


class PropertyCheck(Protocol):
    def check(self, artifact: Any) -> Any: ...


@dataclass(frozen=True)
class PropertyVerifier(FunctionVerifier):
    """Run a deterministic property over the candidate artifact."""

    property_check: Callable[[Any], Any] = lambda artifact: False

    def verify(self, candidate: Candidate) -> VerificationResult:
        # Explicitly bypass a placeholder ``check`` while retaining all
        # standard result, evidence, calibration, and compatibility behavior.
        return FunctionVerifier(
            name=self.name, check=lambda _: self.property_check(candidate.artifact),
            verifier_class=self.verifier_class, independent=self.independent,
            trust_boundary=self.trust_boundary, evidence_ids=self.evidence_ids,
            claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
            uncertainty=self.uncertainty, expected_information_gain=self.expected_information_gain,
            information_gain=self.information_gain, cost=self.cost, calibration=self.calibration,
        ).verify(candidate)


@dataclass(frozen=True)
class MetamorphicVerifier(FunctionVerifier):
    transform: Callable[[Candidate], Any] = lambda candidate: candidate.artifact
    compare: Callable[[Candidate, Any], Any] = lambda candidate, transformed: False

    def verify(self, candidate: Candidate) -> VerificationResult:
        transformed = self.transform(candidate)
        try:
            unchanged = canonical_hash(transformed) == canonical_hash(candidate.artifact)
        except (TypeError, ValueError):
            # A transform that cannot be represented in the protocol's
            # canonical form cannot establish a metamorphic relation.
            unchanged = False
        if unchanged:
            check: Callable[[Candidate], Any] = lambda _: VerificationDecision(
                VerificationStatus.UNKNOWN, ("metamorphic transform did not change the artifact",))
        else:
            check = lambda _: self.compare(candidate, transformed)
        return FunctionVerifier(
            name=self.name, check=check,
            verifier_class="metamorphic", independent=self.independent,
            trust_boundary=self.trust_boundary, evidence_ids=self.evidence_ids,
            claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
            uncertainty=self.uncertainty, expected_information_gain=self.expected_information_gain,
            information_gain=self.information_gain, cost=self.cost, calibration=self.calibration,
        ).verify(candidate)


@dataclass(frozen=True)
class MutationVerifier(FunctionVerifier):
    """Deterministically require a predicate to detect every generated mutation."""

    mutate: Callable[[Candidate], Iterable[Any]] = lambda candidate: ()
    detect: Callable[[Any], Any] = lambda mutated: False

    def verify(self, candidate: Candidate) -> VerificationResult:
        mutations = tuple(self.mutate(candidate))
        if not mutations:
            return FunctionVerifier(
                name=self.name, check=lambda _: VerificationDecision(VerificationStatus.UNKNOWN, ("no mutations generated",)),
                verifier_class="mutation", independent=self.independent,
                trust_boundary=self.trust_boundary, evidence_ids=self.evidence_ids,
                claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
                uncertainty=self.uncertainty, expected_information_gain=self.expected_information_gain,
                information_gain=self.information_gain, cost=self.cost, calibration=self.calibration,
            ).verify(candidate)

        changed: list[Any] = []
        unchanged_count = 0
        for mutation in mutations:
            try:
                is_unchanged = canonical_hash(mutation) == canonical_hash(candidate.artifact)
            except (TypeError, ValueError):
                is_unchanged = False
            if is_unchanged:
                unchanged_count += 1
            else:
                changed.append(mutation)

        # A no-op is not a mutation and a detector saying "true" for it is not
        # evidence that the artifact survives a changed-input test.  Crucially,
        # this is UNKNOWN rather than a synthetic counterexample/FAIL.
        if not changed:
            reason = ("no changed mutations generated" if unchanged_count
                      else "no mutations generated")
            return FunctionVerifier(
                name=self.name,
                check=lambda _: VerificationDecision(VerificationStatus.UNKNOWN, (reason,)),
                verifier_class="mutation", independent=self.independent,
                trust_boundary=self.trust_boundary, evidence_ids=self.evidence_ids,
                claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
                uncertainty=self.uncertainty, expected_information_gain=self.expected_information_gain,
                information_gain=self.information_gain, cost=self.cost, calibration=self.calibration,
            ).verify(candidate)

        decisions = [_coerce_decision(self.detect(item)) for item in changed]
        statuses = [item.status for item in decisions
                    if isinstance(item, (VerificationDecision, VerificationResult))]
        detected = sum(status is VerificationStatus.PASS for status in statuses)
        status = (VerificationStatus.FAIL if any(status is VerificationStatus.FAIL for status in statuses)
                  else VerificationStatus.UNKNOWN if any(status is VerificationStatus.UNKNOWN for status in statuses)
                  else VerificationStatus.PASS)
        ids = tuple(f"mutation-{canonical_hash(item)[:16]}" for item in changed)
        reasons = [f"detected {detected}/{len(changed)} changed mutations"]
        if unchanged_count:
            reasons.append(f"ignored {unchanged_count} unchanged mutation(s)")
        return FunctionVerifier(
            name=self.name, check=lambda _: VerificationDecision(
                status=status, reasons=tuple(reasons),
                evidence_ids=self.evidence_ids, claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
                # Only a concrete FAIL is a counterexample. UNKNOWN must remain
                # unresolved and must not be converted into a hard falsification.
                counterexample_ids=ids if status is VerificationStatus.FAIL else (),
                calibration=CalibrationMetrics(
                    self.calibration.false_positive_rate,
                    self.calibration.false_negative_rate,
                    detected / len(changed),
                ),
            ), verifier_class="mutation", independent=self.independent,
            trust_boundary=self.trust_boundary, evidence_ids=self.evidence_ids,
            claim_ids=self.claim_ids, provenance_ids=self.provenance_ids,
            uncertainty=self.uncertainty, expected_information_gain=self.expected_information_gain,
            information_gain=self.information_gain, cost=self.cost, calibration=self.calibration,
        ).verify(candidate)
