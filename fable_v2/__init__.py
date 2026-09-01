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
    CausalDAG,
    CausalNode,
    CausalEdge,
    CausalNodeType,
    BrittlenessReport,
    InterventionResult,
    ThesisCandidate,
    AntithesisCritique,
    Contradiction,
    TRIZPrinciple,
    TRIZContradictionResolver,
    DialecticalSynthesizer,
    EmergentSynthesis,
    CognitiveGenome,
    CognitiveGenePool,
    NeuroSymbolicAxiom,
    AxiomProvenance,
    AxiomStatus,
    MetaProofInducer,
    CognitiveGear,
    CognitiveBiasType,
    CognitiveBiasFinding,
    CognitiveBiasDetector,
    DynamicSearchHeuristicRewriter,
    SearchHeuristicConfig,
    TriLevelArbitrator,
    System3Executive,
)

__all__ = [
    "BrokerPolicy", "Candidate", "CompositeVerifier", "Evidence", "ExecutionBroker", "FableRun",
    "FunctionVerifier", "HOST_PROFILES", "HostCapabilities", "RunState",
    "TaskSpec", "ToolReceipt", "VerificationPolicy", "VerificationResult",
    "get_profile", "new_run",
    "system3",
    # System 3 symbols
    "CausalDAG", "CausalNode", "CausalEdge", "CausalNodeType", "BrittlenessReport", "InterventionResult",
    "ThesisCandidate", "AntithesisCritique", "Contradiction", "TRIZPrinciple", "TRIZContradictionResolver",
    "DialecticalSynthesizer", "EmergentSynthesis",
    "CognitiveGenome", "CognitiveGenePool",
    "NeuroSymbolicAxiom", "AxiomProvenance", "AxiomStatus", "MetaProofInducer",
    "CognitiveGear", "CognitiveBiasType", "CognitiveBiasFinding", "CognitiveBiasDetector",
    "DynamicSearchHeuristicRewriter", "SearchHeuristicConfig", "TriLevelArbitrator", "System3Executive",
]
