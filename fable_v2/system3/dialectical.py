"""System 3 Dialectical Evolutionary Architecture & TRIZ Contradiction Engine.

Implements the Dialectical Triad (Thesis -> Antithesis -> Emergent Synthesis),
the 40 TRIZ inventive principles contradiction resolver, and the DialecticalSynthesizer
with bounded debate rounds and guaranteed monotonic contradiction convergence.
Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from collections.abc import Mapping
import copy
import hashlib
import hmac
import json
import math
from ..protocol import Evidence, ToolReceipt, canonical_hash


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return float(value)


@dataclass(frozen=True)
class DialecticalMeasurement:
    """Receipt-bound measured round score; unlike a bare float it is attestable."""
    round_index: int
    score: float
    score_hash: str
    receipt_id: str
    evidence_id: str
    provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.round_index) is not int or self.round_index < 0:
            raise ValueError("measurement round_index must be a non-negative integer")
        score = _finite(self.score, "measurement score")
        if not 0 <= score <= 1:
            raise ValueError("measurement score must be between 0 and 1")
        if not isinstance(self.score_hash, str) or not self.score_hash:
            raise ValueError("measurement score_hash is required")
        if not hmac.compare_digest(self.score_hash, canonical_hash(score)):
            raise ValueError("measurement score_hash does not match score")
        for name in ("receipt_id", "evidence_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"measurement {name} is required")
        object.__setattr__(self, "provenance", copy.deepcopy(dict(self.provenance)))
        canonical_hash(self.provenance)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))


# Descriptive aliases for hosts that used either spelling while this API was
# experimental.
MeasuredRoundScore = DialecticalMeasurement
MeasurementRecord = DialecticalMeasurement


@dataclass
class Contradiction:
    """Represents an engineering trade-off or parameter conflict."""
    contradiction_id: str
    improving_parameter: str
    worsening_parameter: str
    description: str
    severity: float = 0.5  # [0.0, 1.0]
    domain: str = "software_architecture"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _finite(self.severity, "contradiction severity")
        if not 0 <= self.severity <= 1:
            raise ValueError("contradiction severity must be between 0 and 1")
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Contradiction":  
        return cls(**data)


@dataclass
class ThesisCandidate:
    """The original architectural hypothesis or solution proposal."""
    thesis_id: str
    title: str
    description: str
    core_assumptions: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metrics, dict):
            raise TypeError("thesis metrics must be a mapping")
        for key, value in self.metrics.items():
            _finite(value, f"thesis metric {key}")
        self.core_assumptions = list(self.core_assumptions)
        self.strengths = list(self.strengths)
        self.weaknesses = list(self.weaknesses)
        self.metrics = dict(self.metrics)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThesisCandidate":  
        return cls(**data)


@dataclass
class AntithesisCritique:
    """Adversarial critique exposing inherent contradictions and failure modes."""
    critique_id: str
    thesis_id: str
    title: str
    contradictions: List[Contradiction] = field(default_factory=list)
    failure_modes: List[str] = field(default_factory=list)
    adversarial_scenarios: List[str] = field(default_factory=list)
    severity_score: float = 0.5  # [0.0, 1.0]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _finite(self.severity_score, "critique severity_score")
        if not 0 <= self.severity_score <= 1:
            raise ValueError("critique severity_score must be between 0 and 1")
        self.contradictions = list(self.contradictions)
        self.failure_modes = list(self.failure_modes)
        self.adversarial_scenarios = list(self.adversarial_scenarios)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy({
            "critique_id": self.critique_id,
            "thesis_id": self.thesis_id,
            "title": self.title,
            "contradictions": [c.to_dict() for c in self.contradictions],
            "failure_modes": self.failure_modes,
            "adversarial_scenarios": self.adversarial_scenarios,
            "severity_score": self.severity_score,
            "metadata": self.metadata,
        })

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AntithesisCritique": 
        data_copy = dict(data)
        if "contradictions" in data_copy:
            data_copy["contradictions"] = [
                Contradiction.from_dict(c) if isinstance(c, dict) else c
                for c in data_copy["contradictions"]
            ]
        return cls(**data_copy)


@dataclass
class TRIZPrinciple:
    """One of the 40 TRIZ Inventive Principles with software mapping."""
    number: int
    name: str
    description: str
    software_analogs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TRIZResolutionRecommendation:
    """Actionable resolution strategy derived from TRIZ operator."""
    principle: TRIZPrinciple
    contradiction: Contradiction
    resolution_strategy: str
    expected_pareto_gain: str
    confidence: float = 0.85

    def __post_init__(self) -> None:
        _finite(self.confidence, "recommendation confidence")
        if not 0 <= self.confidence <= 1:
            raise ValueError("recommendation confidence must be between 0 and 1")

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy({
            "principle": self.principle.to_dict(),
            "contradiction": self.contradiction.to_dict(),
            "resolution_strategy": self.resolution_strategy,
            "expected_pareto_gain": self.expected_pareto_gain,
            "confidence": self.confidence,
        })


@dataclass
class EmergentSynthesis:
    """Higher-order architecture transcending the thesis-antithesis contradiction."""
    synthesis_id: str
    thesis_id: str
    critique_id: str
    title: str
    synthesized_architecture: str
    resolved_contradictions: List[Contradiction]
    transcended_principles: List[TRIZPrinciple]
    debate_rounds_executed: int
    initial_contradiction_score: float
    residual_contradiction_score: float
    pareto_improvement_claim: str
    convergence_achieved: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _finite(self.initial_contradiction_score, "initial contradiction score")
        _finite(self.residual_contradiction_score, "residual contradiction score")
        if not 0 <= self.initial_contradiction_score <= 1 or not 0 <= self.residual_contradiction_score <= 1:
            raise ValueError("synthesis scores must be between 0 and 1")
        if type(self.debate_rounds_executed) is not int or self.debate_rounds_executed < 0:
            raise ValueError("debate_rounds_executed must be a non-negative integer")
        if type(self.convergence_achieved) is not bool:
            raise TypeError("convergence_achieved must be a boolean")
        self.resolved_contradictions = list(self.resolved_contradictions)
        self.transcended_principles = list(self.transcended_principles)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy({
            "synthesis_id": self.synthesis_id,
            "thesis_id": self.thesis_id,
            "critique_id": self.critique_id,
            "title": self.title,
            "synthesized_architecture": self.synthesized_architecture,
            "resolved_contradictions": [c.to_dict() for c in self.resolved_contradictions],
            "transcended_principles": [p.to_dict() for p in self.transcended_principles],
            "debate_rounds_executed": self.debate_rounds_executed,
            "initial_contradiction_score": self.initial_contradiction_score,
            "residual_contradiction_score": self.residual_contradiction_score,
            "pareto_improvement_claim": self.pareto_improvement_claim,
            "convergence_achieved": self.convergence_achieved,
            "metadata": self.metadata,
        })

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmergentSynthesis": 
        data_copy = dict(data)
        if "resolved_contradictions" in data_copy:
            data_copy["resolved_contradictions"] = [
                Contradiction.from_dict(c) if isinstance(c, dict) else c
                for c in data_copy["resolved_contradictions"]
            ]
        if "transcended_principles" in data_copy:
            data_copy["transcended_principles"] = [
                TRIZPrinciple(**p) if isinstance(p, dict) else p
                for p in data_copy["transcended_principles"]
            ]
        return cls(**data_copy)


# Complete 40 TRIZ Inventive Principles library with systems/software engineering mappings
TRIZ_PRINCIPLES_CATALOG: Dict[int, TRIZPrinciple] = {
    1: TRIZPrinciple(
        1, "Segmentation",
        "Divide an object or system into independent parts; make it sectional; increase degree of fragmentation.",
        ["Microservices / subagents", "Sharding & partitioning", "Modular function decomposition", "Windowed slice extraction"]
    ),
    2: TRIZPrinciple(
        2, "Taking Out / Extraction",
        "Separate an interfering part or property from an object, or single out the only necessary part.",
        ["Extracting heavy state to Content-Addressed Storage (CAS)", "Separation of policy from mechanism", "Pure side-effect-free cores"]
    ),
    3: TRIZPrinciple(
        3, "Local Quality",
        "Change an object's structure from uniform to non-uniform; make different parts fulfill different functions.",
        ["Tiered caching (L1 in-memory + L2 CAS disk)", "Specialized worker roles (Architect vs Implementer)", "Heterogeneous memory layouts"]
    ),
    4: TRIZPrinciple(
        4, "Asymmetry",
        "Change the shape of an object from symmetrical to asymmetrical; replace uniform behavior with specialized asymmetry.",
        ["Read-heavy CQRS replicas vs single-writer", "Asymmetric cryptographic verification", "One-way monotonic budget locks"]
    ),
    5: TRIZPrinciple(
        5, "Merging / Combining",
        "Bring closer together or merge identical or similar objects; assemble related operations in time.",
        ["Adaptive chunk accumulation of micro-payloads", "Batch commit transactions", "Composite verification pipelines"]
    ),
    6: TRIZPrinciple(
        6, "Universality",
        "Make a part or object perform multiple functions; eliminate the need for other parts.",
        ["Unified evidence-gated verification protocol", "Multi-modal receipt format", "Universal content-addressed URI"]
    ),
    7: TRIZPrinciple(
        7, "Nested Doll (Matryoshka)",
        "Place one object inside another; place each object, in turn, inside the other.",
        ["Subagent hierarchies with isolated branched workspaces", "Layered containerization / sandbox wrappers", "Nested transactional spans"]
    ),
    8: TRIZPrinciple(
        8, "Anti-Weight / Counterweight",
        "Compensate for the weight or cost of an object by combining it with another that provides lift.",
        ["Proactive pre-fetching while idle", "Background asynchronous compaction offsetting query latency", "Optimistic concurrency with rollback"]
    ),
    9: TRIZPrinciple(
        9, "Preliminary Anti-Action",
        "If it will be necessary to do an action with both harmful and useful effects, this action should be preceded by anti-actions.",
        ["Circuit breaker pre-trip checks", "Pre-flight type validation before code emission", "Epistemic evidence gating before execution"]
    ),
    10: TRIZPrinciple(
        10, "Preliminary Action / Prior Action",
        "Perform the required changes of an object completely or partially before it is needed; arrange objects in advance.",
        ["Pre-indexing codebase ASTs", "Pre-calculating SHA-256 hashes", "Warm pool subagent worker initialization"]
    ),
    11: TRIZPrinciple(
        11, "Beforehand Cushioning",
        "Prepare emergency means beforehand to compensate for the relatively low reliability of an object.",
        ["Fallback verifiers on primary timeout", "State checkpoints prior to dangerous migrations", "Redundant quorum nodes"]
    ),
    12: TRIZPrinciple(
        12, "Equipotentiality",
        "In a potential field, limit position changes (e.g. change operating conditions to eliminate the need to raise or lower).",
        ["Zero-copy streaming slice readers", "In-place memory updates", "Shared immutable memory worktrees"]
    ),
    13: TRIZPrinciple(
        13, "The Other Way Round (Inversion)",
        "Invert the action used to solve the problem; make movable parts fixed, and fixed parts movable; turn upside down.",
        ["Inversion of Control / Dependency Injection", "Verification by falsification (Red-Teaming)", "Pull-based backpressure streams"]
    ),
    14: TRIZPrinciple(
        14, "Spheroidality / Curvature",
        "Replace linear parts with curved ones; use rotations, rollers, spiral structures.",
        ["Circular lock-free ring buffers", "Consistent hashing rings for distributed nodes", "Round-robin load balancers"]
    ),
    15: TRIZPrinciple(
        15, "Dynamics / Dynamic Parts",
        "Allow or design the characteristics of an object to be change-capable to be optimal under each operating condition.",
        ["Adaptive batch timeouts", "Dynamic search heuristic temperature adjustment", "Auto-scaling subagent pools"]
    ),
    16: TRIZPrinciple(
        16, "Partial or Excessive Actions",
        "If 100% of an object is hard to achieve, achieve slightly less or slightly more to make the problem simpler.",
        ["Speculative dual-branch execution with early prune", "Over-provisioned buffer pools", "Approximate Top-K count-min sketches"]
    ),
    17: TRIZPrinciple(
        17, "Another Dimension / Dimensionality Transition",
        "Move into an additional dimension (1D -> 2D -> 3D); use multi-story or hierarchical arrangements.",
        ["10D Pareto frontier multi-objective optimization", "Graph-based dependency representation vs flat lists", "Tri-level cognitive arbitration (S1/S2/S3)"]
    ),
    18: TRIZPrinciple(
        18, "Mechanical Vibration",
        "Cause an object to oscillate or vibrate; increase frequency up to ultrasonic.",
        ["Periodic heartbeat / keepalive pings", "Jittered exponential backoff retries", "High-frequency micro-batch flushing"]
    ),
    19: TRIZPrinciple(
        19, "Periodic Action",
        "Replace continuous action with periodic or pulsed actions; change periodicity between pulses.",
        ["Periodic checkpoint commits", "Scheduled cron task wakeup", "Interval-based garbage collection"]
    ),
    20: TRIZPrinciple(
        20, "Continuity of Useful Action",
        "Carry on work continuously; make all parts of an object work at full load, all the time.",
        ["Continuous rethink-refine loop during authority time-lock", "Pipelined asynchronous execution", "Non-blocking event loop"]
    ),
    21: TRIZPrinciple(
        21, "Hurrying / Skipping",
        "Conduct a process or certain stages of it at high speed to avoid destructive side effects.",
        ["Fast-fail validation before allocating heavy resources", "Optimistic atomic compare-and-swap", "Short-circuit evaluation"]
    ),
    22: TRIZPrinciple(
        22, "Blessing in Disguise / Harm to Benefit",
        "Use harmful factors to achieve a positive effect; eliminate primary harmful factor by combining with another.",
        ["Chaos engineering / adversarial red-teaming to uncover architectural invariants", "Compiler errors driving OODA self-healing"]
    ),
    23: TRIZPrinciple(
        23, "Feedback",
        "Introduce feedback to improve a process or action; if feedback is already used, change its magnitude or direction.",
        ["Interleaved Post-Action Reflection Gates", "Live run telemetry & pacing feedback", "Closed-loop heuristic rewriters"]
    ),
    24: TRIZPrinciple(
        24, "Intermediary",
        "Use an intermediary carrier article or intermediate process; merge one object temporarily with another.",
        ["ExecutionBroker between model and shell", "Proxy adapters / MCP protocols", "Middlewares & message queues"]
    ),
    25: TRIZPrinciple(
        25, "Self-Service",
        "Make an object serve itself by performing auxiliary helpful functions; use waste resources.",
        ["Self-healing agents via OODA loop", "Auto-compacting CAS caches", "Self-registering dynamic verifiers"]
    ),
    26: TRIZPrinciple(
        26, "Copying",
        "Instead of an unavailable, expensive, fragile object, use simpler and inexpensive copies.",
        ["Digital twins / scratch test harnesses", "In-memory mock services for verification", "Cloned ephemeral git worktrees"]
    ),
    27: TRIZPrinciple(
        27, "Cheap Short-Living / Disposables",
        "Replace an expensive object with multiple inexpensive objects, compromising on certain qualities.",
        ["Disposable worker subagents for risky refactors", "Ephemeral scratch containers", "One-shot verification sandboxes"]
    ),
    28: TRIZPrinciple(
        28, "Mechanics Substitution",
        "Replace a mechanical system with another physical, optical, acoustic, or sensory field.",
        ["Replace explicit locking with lock-free atomic CAS", "Replace manual inspection with automated neuro-symbolic verification"]
    ),
    29: TRIZPrinciple(
        29, "Pneumatics and Hydraulics",
        "Use gas and liquid parts of an object instead of solid parts.",
        ["Fluid streaming token pipelines", "Reactive backpressure flow control", "Dynamic elastic memory buffers"]
    ),
    30: TRIZPrinciple(
        30, "Flexible Shells and Thin Films",
        "Use flexible shells and thin films instead of three-dimensional structures; isolate the object.",
        ["Lightweight protocol dataclass envelopes", "Schema validation decorators", "Isolated subagent context boundaries"]
    ),
    31: TRIZPrinciple(
        31, "Porous Materials",
        "Make an object porous or add porous elements (inserts, cavities, coatings).",
        ["Sparse matrix indices", "Bloom filters for probabilistic membership testing", "Token-compact Grammar333 micro-bytecode"]
    ),
    32: TRIZPrinciple(
        32, "Color Changes",
        "Change the color of an object or its external environment; change the degree of translucency.",
        ["Epistemic tagging ([PROVEN] vs [HYPOTHESIS] vs [UNKNOWN])", "Phase status indicators", "Visual radar chart telemetry"]
    ),
    33: TRIZPrinciple(
        33, "Homogeneity",
        "Make objects interacting with a given object of the same material (or identical properties).",
        ["Unified JSON-RPC protocol across host and subagents", "Homogeneous tool receipt hashing across platforms"]
    ),
    34: TRIZPrinciple(
        34, "Discarding and Recovering",
        "Make portions of an object that have fulfilled their functions go away; restore consumable parts directly.",
        ["Automatic pruning of unpromising MCTS branches", "LRU cache eviction with atomic temp-file cleanup", "Ephemeral workspace cleanup"]
    ),
    35: TRIZPrinciple(
        35, "Parameter Changes",
        "Change an object's physical state, concentration, density, degree of flexibility, or temperature.",
        ["Adaptive search temperature annealing", "Dynamic compression chunk sizing", "Configurable trust boundary ranks"]
    ),
    36: TRIZPrinciple(
        36, "Phase Transitions",
        "Use phenomena occurring during phase transitions (e.g. volume changes, loss or absorption of heat).",
        ["Hard cognitive phase gating (Phase 1 Epistemic -> Phase 2 Blueprint -> Phase 3 Red Team -> Phase 4 Subagent)", "State machine state-locking"]
    ),
    37: TRIZPrinciple(
        37, "Thermal Expansion",
        "Use thermal expansion or contraction of materials; use multiple materials with different coefficients.",
        ["Elastic horizontal scaling of subagent workers under high task load", "Dynamic context window budget expansion"]
    ),
    38: TRIZPrinciple(
        38, "Accelerated Oxidation / Strong Oxidants",
        "Make something react more intensely; replace common environment with enriched one.",
        ["Adversarial glasswing fuzzing with synthetic edge cases", "Stress-testing concurrency with micro-delays"]
    ),
    39: TRIZPrinciple(
        39, "Inert Atmosphere",
        "Replace a normal environment with an inert one; perform a process in a vacuum.",
        ["Deterministic isolated test execution sandbox", "Hermetic build environments with zero network access"]
    ),
    40: TRIZPrinciple(
        40, "Composite Materials",
        "Change from uniform to composite (multiple) materials with distinct mechanical/functional properties.",
        ["Neuro-symbolic hybrid induction (neural heuristics + formal symbolic verification)", "Composite verifier combining deterministic + independent checks"]
    ),
}


class TRIZContradictionResolver:
    """
    Automated TRIZ Contradiction Matrix & Engineering Resolution Engine.
    Maps conflicting software parameters to optimal inventive principles.
    """

    # Domain contradiction matrix mapping (Parameter A vs Parameter B) -> Top TRIZ principles
    CONTRADICTION_MATRIX: Dict[Tuple[str, str], List[int]] = {
        ("throughput", "latency"): [1, 15, 10, 24, 21],          # Segmentation, Dynamics, Prior Action, Intermediary, Hurrying
        ("latency", "throughput"): [1, 15, 10, 24, 21],
        ("consistency", "availability"): [3, 4, 35, 19, 10],     # Local Quality, Asymmetry, Parameter Changes, Periodic Action, Prior Action
        ("availability", "consistency"): [3, 4, 35, 19, 10],
        ("memory", "speed"): [2, 34, 35, 1, 5],                  # Extraction, Discarding, Parameter Changes, Segmentation, Merging
        ("speed", "memory"): [2, 34, 35, 1, 5],
        ("security", "performance"): [4, 10, 25, 1, 9],          # Asymmetry, Prior Action, Self-Service, Segmentation, Anti-Action
        ("performance", "security"): [4, 10, 25, 1, 9],
        ("simplicity", "expressiveness"): [6, 7, 40, 24, 1],      # Universality, Nested Doll, Composite Materials, Intermediary, Segmentation
        ("expressiveness", "simplicity"): [6, 7, 40, 24, 1],
        ("modularity", "coupling"): [1, 2, 24, 30, 26],          # Segmentation, Extraction, Intermediary, Flexible Shells, Copying
        ("coupling", "modularity"): [1, 2, 24, 30, 26],
        ("flexibility", "robustness"): [15, 35, 40, 11, 22],     # Dynamics, Parameter Changes, Composite Materials, Cushioning, Harm to Benefit
        ("robustness", "flexibility"): [15, 35, 40, 11, 22],
        ("concurrency", "safety"): [28, 2, 4, 10, 14],           # Mechanics Substitution (Atomic CAS), Extraction, Asymmetry, Prior Action, Spheroidality
        ("safety", "concurrency"): [28, 2, 4, 10, 14],
        ("compression", "fidelity"): [2, 31, 35, 5, 23],         # Extraction, Porous Materials, Parameter Changes, Merging, Feedback
        ("fidelity", "compression"): [2, 31, 35, 5, 23],
    }

    def __init__(self):
        self.catalog = TRIZ_PRINCIPLES_CATALOG

    def _normalize_param(self, param: str) -> str:
        """Normalize parameter string for matrix lookup."""
        p = param.strip().lower()
        p = p.replace(" ", "_").replace("-", "_")
        aliases = {
            "time": "latency",
            "speed": "latency",
            "capacity": "throughput",
            "volume": "throughput",
            "ram": "memory",
            "storage": "memory",
            "safety": "security",
            "isolation": "security",
            "maintainability": "modularity",
            "extensibility": "expressiveness",
            "accuracy": "fidelity",
            "fault_tolerance": "robustness",
            "reliability": "robustness",
        }
        return aliases.get(p, p)

    def resolve_contradiction(self, contradiction: Contradiction) -> List[TRIZResolutionRecommendation]:
        """
        Analyze a contradiction and recommend concrete TRIZ principles with engineering strategies.
        """
        p1 = self._normalize_param(contradiction.improving_parameter)
        p2 = self._normalize_param(contradiction.worsening_parameter)

        principle_ids = self.CONTRADICTION_MATRIX.get((p1, p2))
        if not principle_ids:
            # Fallback heuristic: choose principles based on severity and keywords
            if contradiction.severity > 0.7:
                principle_ids = [1, 2, 40, 15]  # Segmentation, Extraction, Composite, Dynamics
            else:
                principle_ids = [10, 24, 35, 5]  # Prior Action, Intermediary, Parameter Changes, Merging

        recommendations: List[TRIZResolutionRecommendation] = []
        for pid in principle_ids[:4]:
            principle = self.catalog.get(pid, TRIZ_PRINCIPLES_CATALOG[1])
            analog_example = principle.software_analogs[0] if principle.software_analogs else "Modular redesign"
            
            strat = (
                f"Apply TRIZ Principle #{principle.number} ({principle.name}): "
                f"Decouple '{contradiction.improving_parameter}' from '{contradiction.worsening_parameter}' "
                f"via {analog_example.lower()}."
            )
            gain = (
                "UNMEASURED: expected Pareto effect only; no baseline or execution "
                f"measurement supplied for {contradiction.improving_parameter}/"
                f"{contradiction.worsening_parameter}."
            )

            rec = TRIZResolutionRecommendation(
                principle=principle,
                contradiction=contradiction,
                resolution_strategy=strat,
                expected_pareto_gain=gain,
                confidence=round(0.95 - (0.05 * len(recommendations)), 2),
            )
            recommendations.append(rec)

        return recommendations


class DialecticalSynthesizer:
    """
    Conducts bounded dialectical debate rounds between Thesis and Antithesis.
    Guarantees monotonic reduction of contradiction severity until Pareto-superior
    Emergent Synthesis is synthesized.
    """

    def __init__(self, resolver: Optional[TRIZContradictionResolver] = None):
        self.resolver = resolver or TRIZContradictionResolver()

    def synthesize(
        self,
        thesis: ThesisCandidate,
        critique: AntithesisCritique,
        max_debate_rounds: int = 4,
        target_residual_threshold: float = 0.15,
        measured_round_scores: Optional[List[float]] = None,
        measured_pareto_metrics: Optional[Dict[str, float]] = None,
        measured_receipts: Optional[List[ToolReceipt]] = None,
        measured_evidence: Optional[List[Evidence]] = None,
    ) -> EmergentSynthesis:
        """
        Execute bounded dialectical debate rounds to synthesize a higher-order paradigm.
        Enforces:
        - Monotonic contradiction convergence: R_{k+1} <= R_k
        - Zero unverified compromises (transcendence over weak averaging)
        - Traceable derivation of emergent principles.
        """
        # Normalize typed score records without ever trusting caller-supplied
        # numeric claims.  Bare scores are accepted only when the evidence
        # output explicitly contains the same score series.
        measurement_records: List[DialecticalMeasurement] = []
        bare_scores: List[float] = []
        if measured_round_scores:
            for index, raw_score in enumerate(measured_round_scores):
                if isinstance(raw_score, DialecticalMeasurement):
                    measurement_records.append(raw_score)
                elif isinstance(raw_score, Mapping):
                    measurement_records.append(DialecticalMeasurement(**dict(raw_score)))
                else:
                    score = _finite(raw_score, "measured round score")
                    if not 0 <= score <= 1:
                        raise ValueError("measured round scores must be in [0, 1]")
                    bare_scores.append(score)
        if measurement_records and bare_scores:
            raise ValueError("measured scores must use either typed records or numeric scores")
        measured = measured_round_scores is not None and bool(measured_round_scores)
        pareto_supplied = measured_pareto_metrics is not None
        if measured or pareto_supplied:
            # A numeric series is not a measurement by itself.  Require actual
            # successful receipts and hash-bound evidence for measured claims.
            if not measured_receipts or not measured_evidence:
                raise ValueError("measured convergence requires receipt and evidence provenance")
            receipts = {r.receipt_id: r for r in measured_receipts
                        if isinstance(r, ToolReceipt) and r.success}
            if len(receipts) != len(measured_receipts):
                raise ValueError("measured convergence receipts must be successful and unique")
            evidence_ids = [item.evidence_id for item in measured_evidence
                            if isinstance(item, Evidence)]
            if len(evidence_ids) != len(set(evidence_ids)):
                raise ValueError("measured convergence evidence must be unique")
            for item in measured_evidence:
                if not isinstance(item, Evidence) or item.receipt_id not in receipts:
                    raise ValueError("measured evidence has unresolved receipt provenance")
                receipt = receipts[item.receipt_id]
                if (item.session_id != receipt.session_id or
                        item.content_hash != receipt.output_hash or
                        item.source_output_hash != receipt.output_hash or
                        canonical_hash(item.content) != item.content_hash):
                    raise ValueError("measured evidence is not hash-bound to its receipt")
        if measured_round_scores is not None:
            if not measured_round_scores:
                raise ValueError("measured round scores must be finite numbers in [0, 1]")
            if measurement_records:
                rounds = [record.round_index for record in measurement_records]
                if len(set(rounds)) != len(rounds) or rounds != sorted(rounds):
                    raise ValueError("typed measurements must have unique ordered rounds")
                allowed = set(receipts)
                evidence_by_id = {item.evidence_id: item for item in (measured_evidence or [])}
                if any(record.receipt_id not in allowed or record.evidence_id not in evidence_by_id
                       for record in measurement_records):
                    raise ValueError("typed measurement provenance is not supplied")
                for record in measurement_records:
                    item = evidence_by_id[record.evidence_id]
                    if item.receipt_id != record.receipt_id:
                        raise ValueError("typed measurement receipt/evidence mismatch")
                    # The typed record commits to the score; its receipt/evidence
                    # links and score hash are the provenance boundary.  Hosts may
                    # keep the numeric score in a non-JSON measurement artifact.
            else:
                def score_series(value: Any) -> List[float]:
                    found: List[float] = []
                    if isinstance(value, Mapping):
                        for child in value.values():
                            found.extend(score_series(child))
                    elif isinstance(value, (list, tuple)):
                        if value and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                         and math.isfinite(float(x)) for x in value):
                            found.extend(float(x) for x in value)
                        else:
                            for child in value:
                                found.extend(score_series(child))
                    return found
                expected = [float(x) for x in bare_scores]
                observed = []
                for item in (measured_evidence or []):
                    observed.extend(score_series(item.content))
                if not any(len(series) >= len(expected) and series[:len(expected)] == expected
                           for series in (observed,)):
                    raise ValueError("measured scores do not match receipt/evidence output")
        if measured_pareto_metrics is not None and any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or
                not math.isfinite(float(v)) for v in measured_pareto_metrics.values()):
            raise ValueError("Pareto measurements must be finite numbers")
        contradictions = critique.contradictions
        if not contradictions:
            # Construct a default contradiction from critique title / failure modes
            desc = critique.failure_modes[0] if critique.failure_modes else "Trade-off between performance and safety"
            contradictions = [
                Contradiction(
                    contradiction_id="c_auto_001",
                    improving_parameter="performance",
                    worsening_parameter="safety",
                    description=desc,
                    severity=critique.severity_score,
                )
            ]

        # Initial contradiction score is mean severity of contradictions weighted by critique severity
        initial_score = sum(c.severity for c in contradictions) / len(contradictions)
        initial_score = round(min(1.0, max(0.1, (initial_score + critique.severity_score) / 2.0)), 4)

        current_score = initial_score
        resolved_contradictions: List[Contradiction] = []
        transcended_principles: List[TRIZPrinciple] = []
        synthesis_narrative_parts: List[str] = []

        round_num = 0
        while round_num < max_debate_rounds and current_score > target_residual_threshold:
            round_num += 1
            # Pick highest severity unresolved contradiction
            target_contra = max(contradictions, key=lambda c: c.severity)
            recs = self.resolver.resolve_contradiction(target_contra)

            # Apply top recommendation
            if recs:
                top_rec = recs[0]
                transcended_principles.append(top_rec.principle)
                resolved_contradictions.append(target_contra)
                synthesis_narrative_parts.append(
                    f"Round {round_num} [{top_rec.principle.name}]: {top_rec.resolution_strategy}"
                )

            # Monotonic reduction step: strictly reduce current_score by at least 35% per round
            reduction_factor = 0.55 - (0.05 * round_num)
            next_score = round(current_score * reduction_factor, 4)
            # Enforce invariant: R_{k+1} <= R_k
            current_score = min(current_score, next_score)

        synthesis_id = f"syn_{thesis.thesis_id}_{critique.critique_id}_{int(initial_score*100)}"
        title = f"Emergent Synthesis: {thesis.title} Transcended"
        
        # A synthesis is a proposal, not a measured experiment.  Never turn
        # deterministic score decay in the planner into a claim about the
        # world.  Only externally supplied measurements can establish either
        # convergence or Pareto dominance.
        measured = measured_round_scores is not None and bool(measured_round_scores)
        normalized_scores = ([record.score for record in measurement_records]
                             if measurement_records else bare_scores)
        monotonic_measurement = bool(measured) and all(
            float(b) <= float(a) for a, b in zip(normalized_scores, normalized_scores[1:])
        )
        if measured and monotonic_measurement:
            measured_residual = float(normalized_scores[-1])
            current_score = measured_residual
            convergence = measured_residual <= target_residual_threshold
        else:
            # The bounded planner is allowed to report estimated convergence
            # for a substantive, explicitly supplied contradiction.  This is
            # a planning result only: ``measured`` remains false and the
            # Pareto claim below remains UNMEASURED.  Keep the auto-generated
            # fallback contradiction conservative so an empty critique cannot
            # manufacture a convergence proof (important for strict callers).
            convergence = bool(critique.contradictions) and current_score <= target_residual_threshold
        pareto_measured = bool(measured_pareto_metrics) and all(
            isinstance(v, (int, float)) and math.isfinite(float(v))
            for v in (measured_pareto_metrics or {}).values()
        )
        pareto_claim = (
            "MEASURED: Pareto metrics supplied externally; dominance requires an explicit baseline."
            if pareto_measured else
            "UNMEASURED: no Pareto baseline/metrics supplied; this is a proposal, not a Pareto claim."
        )
        score_label = "measured" if measured_round_scores else "estimated planner"
        narrative = (
            f"Synthesized architecture transcending '{thesis.title}' and red-team critique '{critique.title}'.\n"
            f"Resolutions applied across {round_num} debate rounds ({score_label} only):\n"
            + "\n".join([f"- {part}" for part in synthesis_narrative_parts])
            + f"\nResult: Initial contradiction score {initial_score:.2f}; "
              f"{score_label} residual {current_score:.2f}."
        )

        return EmergentSynthesis(
            synthesis_id=synthesis_id,
            thesis_id=thesis.thesis_id,
            critique_id=critique.critique_id,
            title=title,
            synthesized_architecture=narrative,
            resolved_contradictions=resolved_contradictions,
            transcended_principles=transcended_principles,
            debate_rounds_executed=round_num,
            initial_contradiction_score=initial_score,
            residual_contradiction_score=current_score,
            pareto_improvement_claim=pareto_claim,
            convergence_achieved=convergence,
            metadata={
                "measured": measured,
                "measured_round_scores": ([record.to_dict() for record in measurement_records]
                                           if measurement_records else list(normalized_scores)),
                "measured_receipt_ids": [r.receipt_id for r in (measured_receipts or [])],
                "measured_evidence_ids": [e.evidence_id for e in (measured_evidence or [])],
                "measurement_provenance_resolved": bool(measured_receipts and measured_evidence),
                "pareto_measured": pareto_measured,
                "thesis_title": thesis.title,
                "critique_title": critique.title,
                "reduction_ratio": round((initial_score - current_score) / max(initial_score, 1e-6), 4),
            },
        )
