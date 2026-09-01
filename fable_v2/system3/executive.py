"""System 3 Executive Director & Tri-Level Cognitive Orchestrator.

Implements Tri-Level Cognitive Arbitration (System 1 Fast / System 2 Deliberative / System 3 Meta),
Cognitive Bias Detection (confirmation, anchoring, sunk cost, circularity),
and Dynamic Search Heuristic Rewriting for MCTS and Pareto optimization.
Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import copy
import hashlib
import json
import math

from .causal import CausalDAG
from .dialectical import DialecticalSynthesizer, ThesisCandidate, AntithesisCritique, Contradiction
from .evolution import CognitiveGenePool, CognitiveGenome, PARETO_DIMENSIONS
from .induction import MetaProofInducer, NeuroSymbolicAxiom


class CognitiveGear(str, Enum):
    """Tri-level cognitive operating gear."""
    SYSTEM_1_INTUITIVE = "system_1_intuitive"        # Fast heuristics, pattern matching, lightweight scratch
    SYSTEM_2_DELIBERATIVE = "system_2_deliberative"    # 8-Pass deliberation, MCTS search, red-teaming, formal proof
    SYSTEM_3_META_COGNITIVE = "system_3_meta_cognitive" # Meta-reflection, causal Pearl do-calculus, TRIZ evolution, axiom induction


class CognitiveBiasType(str, Enum):
    """Recognized cognitive biases in reasoning deliberation."""
    CONFIRMATION_BIAS = "confirmation_bias"        # Selectively ignoring red-team critiques or failing tests
    ANCHORING_BIAS = "anchoring_bias"              # Over-committing to the first candidate archetype
    AVAILABILITY_HEURISTIC = "availability_heuristic" # Defaulting to generic tropes without probing constraints
    SUNK_COST_FALLACY = "sunk_cost_fallacy"        # Persisting in failing design despite high contradiction density
    CIRCULAR_REASONING = "circular_reasoning"      # Self-justifying claims without external tool receipts


@dataclass
class CognitiveBiasFinding:
    """Diagnostic report of a detected cognitive bias during deliberation."""
    bias_type: CognitiveBiasType
    severity: float  # [0.0, 1.0]
    detected_in: str
    evidence_trail: str
    mitigation_strategy: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["bias_type"] = self.bias_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveBiasFinding":
        data_copy = dict(data)
        if "bias_type" in data_copy and isinstance(data_copy["bias_type"], str):
            data_copy["bias_type"] = CognitiveBiasType(data_copy["bias_type"])
        return cls(**data_copy)


@dataclass
class SearchHeuristicConfig:
    """Dynamic hyperparameters governing MCTS exploration, branch pruning, and verification."""
    exploration_temperature: float = 0.75
    pruning_threshold: float = 0.35
    max_branching_factor: int = 4
    pareto_dimension_weights: Dict[str, float] = field(
        default_factory=lambda: {dim: 1.0 / len(PARETO_DIMENSIONS) for dim in PARETO_DIMENSIONS}
    )
    falsification_intensity: float = 0.80
    min_verification_depth: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchHeuristicConfig":
        return cls(**data)


class CognitiveBiasDetector:
    """
    Automated diagnostic auditor inspecting epistemic ledgers, candidate histories,
    and refinement cycles to prevent cognitive biases and logical traps.
    """

    def audit_session(self, session_data: Dict[str, Any]) -> List[CognitiveBiasFinding]:
        """Audit session state and return list of detected bias findings with mitigations."""
        findings: List[CognitiveBiasFinding] = []

        epistemic = session_data.get("epistemic_ledger", [])
        refinements = session_data.get("refinement_cycles", [])
        invariants = session_data.get("invariants", [])
        phase = session_data.get("active_phase", "")
        pacing_used = float(session_data.get("pacing_ratio", 0.0))

        proven_items = [i for i in epistemic if i.get("tag") == "PROVEN"]
        hypotheses = [i for i in epistemic if i.get("tag") == "HYPOTHESIS"]
        unknowns = [i for i in epistemic if i.get("tag") == "UNKNOWN"]

        # 1. Check for Confirmation Bias: Only hypotheses or zero unknowns probed
        if len(hypotheses) > 3 and len(unknowns) == 0 and len(proven_items) == 0:
            findings.append(
                CognitiveBiasFinding(
                    bias_type=CognitiveBiasType.CONFIRMATION_BIAS,
                    severity=0.75,
                    detected_in="Epistemic Ledger",
                    evidence_trail=f"Found {len(hypotheses)} hypotheses but 0 [UNKNOWN] parameters and 0 [PROVEN] facts probed.",
                    mitigation_strategy="Formulate adversarial falsification tests and probe edge cases using run_command terminal tests.",
                )
            )

        # 2. Check for Anchoring Bias: Advanced past Phase 2 with 0 refinement cycles or 1 candidate
        if "Phase 3" in phase or "Phase 4" in phase:
            if len(refinements) == 0:
                findings.append(
                    CognitiveBiasFinding(
                        bias_type=CognitiveBiasType.ANCHORING_BIAS,
                        severity=0.85,
                        detected_in="Phase Progression",
                        evidence_trail=f"Session reached '{phase}' without logging any rethink-refine cycles.",
                        mitigation_strategy="Execute Multi-Archetype Exploration (Zero-Rush Rule): Evaluate 3-5 distinct paradigms across 10D matrix.",
                    )
                )

        # 3. Check for Sunk Cost Fallacy: Repeating same refinement focus area > 3 times with low progress
        focus_counts: Dict[str, int] = {}
        for r in refinements:
            fa = str(r.get("focus_area", "")).strip().lower()
            if fa:
                focus_counts[fa] = focus_counts.get(fa, 0) + 1

        for fa, count in focus_counts.items():
            if count >= 3:
                findings.append(
                    CognitiveBiasFinding(
                        bias_type=CognitiveBiasType.SUNK_COST_FALLACY,
                        severity=0.65,
                        detected_in=f"Refinement Focus '{fa}'",
                        evidence_trail=f"Area '{fa}' scrutinized {count} times consecutively without breakthrough.",
                        mitigation_strategy="Shift to System 3 Dialectical Synthesis: apply TRIZ Inversion (Principle 13) or Mechanics Substitution (Principle 28).",
                    )
                )

        # 4. Check for Circular Reasoning: Invariants with tautological proof sketches
        for inv in invariants:
            stmt = str(inv.get("formal_statement", "")).lower()
            proof = str(inv.get("proof_or_rationale", "")).lower()
            if len(proof) > 0 and (stmt == proof or (len(proof) < 20 and stmt in proof)):
                findings.append(
                    CognitiveBiasFinding(
                        bias_type=CognitiveBiasType.CIRCULAR_REASONING,
                        severity=0.80,
                        detected_in=f"Invariant '{inv.get('name')}'",
                        evidence_trail="Invariant proof simply restates the formal statement without deductive justification or tool receipt.",
                        mitigation_strategy="Anchor invariant to concrete ToolReceipt output hash or construct inductive proof sketch via MetaProofInducer.",
                    )
                )

        return findings


class DynamicSearchHeuristicRewriter:
    """
    Dynamically adjusts search exploration temperature, pruning cutoffs,
    and multi-objective Pareto weights based on meta-cognitive feedback.
    """

    def rewrite_heuristics(
        self,
        current_config: SearchHeuristicConfig,
        contradiction_density: float,
        bias_findings: List[CognitiveBiasFinding],
        brittleness_score: float = 0.0,
    ) -> SearchHeuristicConfig:
        """Calculate updated search heuristic parameters."""
        new_config = copy.deepcopy(current_config)

        # If high contradiction density or high brittleness, increase exploration temperature
        if contradiction_density > 0.6 or brittleness_score > 0.5:
            new_config.exploration_temperature = min(1.2, round(new_config.exploration_temperature + 0.20, 2))
            new_config.max_branching_factor = min(8, new_config.max_branching_factor + 2)
            new_config.falsification_intensity = min(1.0, round(new_config.falsification_intensity + 0.15, 2))
        else:
            # Settle into focused exploitation
            new_config.exploration_temperature = max(0.3, round(new_config.exploration_temperature - 0.10, 2))
            new_config.pruning_threshold = min(0.6, round(new_config.pruning_threshold + 0.05, 2))

        # Adjust weights if biases detected
        has_anchoring = any(b.bias_type == CognitiveBiasType.ANCHORING_BIAS for b in bias_findings)
        if has_anchoring:
            # Overweight simplicity, modularity, and testability to force refactoring
            w = dict(new_config.pareto_dimension_weights)
            w["simplicity"] = 1.5
            w["modularity"] = 1.5
            w["testability"] = 1.5
            new_config.pareto_dimension_weights = w

        return new_config


class TriLevelArbitrator:
    """
    Arbitrates cognitive control among:
    - System 1 (Fast Intuitive / Scratch Heuristics)
    - System 2 (8-Pass Deliberative MCTS & Invariant Proofs)
    - System 3 (Meta-Cognitive Dialectical Evolution & Pearl Do-Calculus)
    """

    def arbitrate(
        self,
        task_complexity: float,       # [0.0, 1.0]
        contradiction_density: float, # [0.0, 1.0]
        failure_count: int = 0,
        epistemic_uncertainty: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Evaluate task parameters and arbitrate optimal cognitive gear.
        """
        composite_difficulty = (
            0.35 * task_complexity +
            0.35 * contradiction_density +
            0.15 * min(1.0, failure_count / 3.0) +
            0.15 * epistemic_uncertainty
        )

        if composite_difficulty >= 0.65 or failure_count >= 2 or contradiction_density >= 0.70:
            gear = CognitiveGear.SYSTEM_3_META_COGNITIVE
            rationale = (
                f"High contradiction density ({contradiction_density:.2f}) and composite difficulty ({composite_difficulty:.2f}). "
                "Engaging System 3 Meta-Cognition: TRIZ Dialectical Synthesis, Pearl Causal Interventions, and Evolutionary Pareto Optimization."
            )
            directives = [
                "Execute System 3 Dialectical Synthesizer across thesis and red-team antithesis.",
                "Construct Pearl Causal DAG and perform counterfactual do(X=x) simulations.",
                "Run Evolutionary Paradigm Engine across 10D Pareto frontier.",
                "Induce formal Neuro-Symbolic Axioms from tool receipts.",
            ]
        elif composite_difficulty >= 0.35:
            gear = CognitiveGear.SYSTEM_2_DELIBERATIVE
            rationale = (
                f"Moderate task complexity ({task_complexity:.2f}) and uncertainty ({epistemic_uncertainty:.2f}). "
                "Engaging System 2 Deliberative Reasoning: 8-Pass deepthink, invariant modeling, and adversarial red-teaming."
            )
            directives = [
                "Execute 8-Pass System 2 deliberation chain.",
                "Model formal invariants in architecture domain.",
                "Conduct adversarial glasswing red-teaming.",
                "Perform continuous rethink-refine logging.",
            ]
        else:
            gear = CognitiveGear.SYSTEM_1_INTUITIVE
            rationale = (
                f"Low composite complexity ({composite_difficulty:.2f}). "
                "Engaging System 1 Fast Heuristics for straightforward procedural operations."
            )
            directives = [
                "Direct pattern-matching and linear execution plan.",
                "Immediate scratch test validation.",
            ]

        return {
            "recommended_gear": gear.value,
            "composite_difficulty": round(composite_difficulty, 3),
            "rationale": rationale,
            "directives": directives,
        }


class System3Executive:
    """
    Unified System 3 Meta-Cognitive Orchestrator.
    Coordinates Causal DAGs, Dialectical Synthesizers, Evolutionary Gene Pools,
    Neuro-Symbolic Axioms, and Cognitive Bias Detection.
    """

    def __init__(self):
        self.bias_detector = CognitiveBiasDetector()
        self.heuristic_rewriter = DynamicSearchHeuristicRewriter()
        self.arbitrator = TriLevelArbitrator()
        self.synthesizer = DialecticalSynthesizer()
        self.inducer = MetaProofInducer()
        self.search_config = SearchHeuristicConfig()

    def meta_reflect(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Conduct a comprehensive System 3 Meta-Cognitive Audit:
        1. Run cognitive bias detection.
        2. Evaluate tri-level cognitive gear requirements.
        3. Dynamically tune search heuristics.
        4. Produce actionable meta-reflection report.
        """
        findings = self.bias_detector.audit_session(session_data)

        # Estimate contradiction density from epistemic counts and refinements
        epistemic = session_data.get("epistemic_ledger", [])
        hypo_count = sum(1 for i in epistemic if i.get("tag") == "HYPOTHESIS")
        unknown_count = sum(1 for i in epistemic if i.get("tag") == "UNKNOWN")
        contra_density = min(1.0, (hypo_count + unknown_count) / max(5, len(epistemic) or 1))

        # Arbitrate gear
        arb_res = self.arbitrator.arbitrate(
            task_complexity=0.80,
            contradiction_density=contra_density,
            failure_count=len(findings),
            epistemic_uncertainty=0.50,
        )

        # Update heuristics
        self.search_config = self.heuristic_rewriter.rewrite_heuristics(
            self.search_config,
            contradiction_density=contra_density,
            bias_findings=findings,
        )

        return {
            "session_name": session_data.get("session_name", "active_session"),
            "cognitive_gear": arb_res["recommended_gear"],
            "arbitration_rationale": arb_res["rationale"],
            "directives": arb_res["directives"],
            "bias_findings": [f.to_dict() for f in findings],
            "contradiction_density": round(contra_density, 3),
            "updated_search_heuristics": self.search_config.to_dict(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "search_config": self.search_config.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "System3Executive":
        exec_instance = cls()
        if "search_config" in data:
            exec_instance.search_config = SearchHeuristicConfig.from_dict(data["search_config"])
        return exec_instance
