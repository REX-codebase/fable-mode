"""Experimental portable Fable V2 runtime with System 3 Meta-Cognitive Architecture."""

from .adapters import HOST_PROFILES, HostCapabilities, get_profile
from .execution_broker import BrokerPolicy, ExecutionBroker
from .protocol import (
    Candidate,
    Evidence,
    TaskSpec,
    ToolReceipt,
    VerificationPolicy,
    VerificationResult,
)
from .runtime import FableRun, RunState, new_run
from .verifiers import CompositeVerifier, FunctionVerifier
from . import system3
from .system3 import (
    # System 3 Causal
    CausalDAG,
    CausalNode,
    CausalEdge,
    CausalNodeType,
    BrittlenessReport,
    InterventionResult,
    # System 3 Dialectical
    ThesisCandidate,
    AntithesisCritique,
    Contradiction,
    TRIZPrinciple,
    TRIZContradictionResolver,
    DialecticalSynthesizer,
    EmergentSynthesis,
    # System 3 Evolution
    CognitiveGenome,
    CognitiveGenePool,
    # System 3 Induction
    NeuroSymbolicAxiom,
    AxiomProvenance,
    AxiomStatus,
    MetaProofInducer,
    # System 3 Executive
    CognitiveGear,
    CognitiveBiasType,
    CognitiveBiasFinding,
    CognitiveBiasDetector,
    DynamicSearchHeuristicRewriter,
    SearchHeuristicConfig,
    TriLevelArbitrator,
    System3Executive,
    # System 3 Hyperbolic
    PoincareBall,
    HyperbolicPoint,
    HyperbolicTreeEmbedder,
    TreeEmbeddingNode,
    TreeEmbeddingResult,
    HyperbolicGeometryError,
    # System 3 Kripke
    KripkeStructure,
    KripkeWorld,
    KripkeModelChecker,
    ModelCheckResult,
    CTLOperator,
    FormulaNode,
    FormulaParser,
    # System 3 Free Energy
    ActiveInferenceEngine,
    GenerativeModel,
    Policy,
    PolicyEvaluation,
    FreeEnergyReport,
    create_default_architecture_pomdp,
    # System 3 Oracle
    ProofOracle,
    CurryHowardVerifier,
    UndecidabilityDetector,
    TacticsEngine,
    FormalProofResult,
    ProofStatus,
    Type,
    Term,
    Prop,
    Unit,
    Void,
    Implies,
    And,
    Or,
    Not,
    Eq,
    Forall,
    Exists,
    Var,
    Lam,
    App,
    Pair,
    Fst,
    Snd,
    Inl,
    Inr,
    Case,
    Refl,
    Abort,
)

__all__ = [
    "BrokerPolicy", "Candidate", "CompositeVerifier", "Evidence", "ExecutionBroker", "FableRun",
    "FunctionVerifier", "HOST_PROFILES", "HostCapabilities", "RunState",
    "TaskSpec", "ToolReceipt", "VerificationPolicy", "VerificationResult",
    "get_profile", "new_run",
    "system3",
    # System 3 Causal
    "CausalDAG", "CausalNode", "CausalEdge", "CausalNodeType", "BrittlenessReport", "InterventionResult",
    # System 3 Dialectical
    "ThesisCandidate", "AntithesisCritique", "Contradiction", "TRIZPrinciple", "TRIZContradictionResolver",
    "DialecticalSynthesizer", "EmergentSynthesis",
    # System 3 Evolution
    "CognitiveGenome", "CognitiveGenePool",
    # System 3 Induction
    "NeuroSymbolicAxiom", "AxiomProvenance", "AxiomStatus", "MetaProofInducer",
    # System 3 Executive
    "CognitiveGear", "CognitiveBiasType", "CognitiveBiasFinding", "CognitiveBiasDetector",
    "DynamicSearchHeuristicRewriter", "SearchHeuristicConfig", "TriLevelArbitrator", "System3Executive",
    # System 3 Hyperbolic
    "PoincareBall", "HyperbolicPoint", "HyperbolicTreeEmbedder", "TreeEmbeddingNode", "TreeEmbeddingResult", "HyperbolicGeometryError",
    # System 3 Kripke
    "KripkeStructure", "KripkeWorld", "KripkeModelChecker", "ModelCheckResult", "CTLOperator", "FormulaNode", "FormulaParser",
    # System 3 Free Energy
    "ActiveInferenceEngine", "GenerativeModel", "Policy", "PolicyEvaluation", "FreeEnergyReport", "create_default_architecture_pomdp",
    # System 3 Oracle
    "ProofOracle", "CurryHowardVerifier", "UndecidabilityDetector", "TacticsEngine", "FormalProofResult", "ProofStatus",
    "Type", "Term", "Prop", "Unit", "Void", "Implies", "And", "Or", "Not", "Eq", "Forall", "Exists",
    "Var", "Lam", "App", "Pair", "Fst", "Snd", "Inl", "Inr", "Case", "Refl", "Abort",
]
