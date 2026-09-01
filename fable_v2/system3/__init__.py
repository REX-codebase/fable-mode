"""System 3 Meta-Cognitive Deliberation & Dialectical Evolutionary Architecture."""

from .causal import (
    BrittlenessReport,
    CausalCycleError,
    CausalDAG,
    CausalEdge,
    CausalNode,
    CausalNodeNotFoundError,
    CausalNodeType,
    InterventionResult,
)
from .dialectical import (
    AntithesisCritique,
    Contradiction,
    DialecticalSynthesizer,
    EmergentSynthesis,
    ThesisCandidate,
    TRIZContradictionResolver,
    TRIZPrinciple,
    TRIZResolutionRecommendation,
    TRIZ_PRINCIPLES_CATALOG,
)
from .evolution import (
    GENE_ALLELE_OPTIONS,
    PARETO_DIMENSIONS,
    CognitiveGenePool,
    CognitiveGenome,
    create_random_genome,
)
from .executive import (
    CognitiveBiasDetector,
    CognitiveBiasFinding,
    CognitiveBiasType,
    CognitiveGear,
    DynamicSearchHeuristicRewriter,
    SearchHeuristicConfig,
    System3Executive,
    TriLevelArbitrator,
)
from .induction import (
    AxiomProvenance,
    AxiomStatus,
    MetaProofInducer,
    NeuroSymbolicAxiom,
)

__all__ = [
    # Causal
    "BrittlenessReport",
    "CausalCycleError",
    "CausalDAG",
    "CausalEdge",
    "CausalNode",
    "CausalNodeNotFoundError",
    "CausalNodeType",
    "InterventionResult",
    # Dialectical
    "AntithesisCritique",
    "Contradiction",
    "DialecticalSynthesizer",
    "EmergentSynthesis",
    "ThesisCandidate",
    "TRIZContradictionResolver",
    "TRIZPrinciple",
    "TRIZResolutionRecommendation",
    "TRIZ_PRINCIPLES_CATALOG",
    # Evolution
    "CognitiveGenePool",
    "CognitiveGenome",
    "GENE_ALLELE_OPTIONS",
    "PARETO_DIMENSIONS",
    "create_random_genome",
    # Induction
    "AxiomProvenance",
    "AxiomStatus",
    "MetaProofInducer",
    "NeuroSymbolicAxiom",
    # Executive
    "CognitiveBiasDetector",
    "CognitiveBiasFinding",
    "CognitiveBiasType",
    "CognitiveGear",
    "DynamicSearchHeuristicRewriter",
    "SearchHeuristicConfig",
    "System3Executive",
    "TriLevelArbitrator",
]
