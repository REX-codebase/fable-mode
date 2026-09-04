"""10-Tool Coder Subagent MCP Fleet for Fable V2.

Modular, pure-Python engines with zero mandatory external C-dependencies:
- VisualGroundingEngine: Vector/SVG rendering validation, perceptual diffing, palette & bounding box extraction
- DiagnosticsEngine: AST syntax & semantic diagnostics, automated quick fixes
- TreeSitterCodemodEngine: AST structural queries, safe identifier renaming, syntax verification
- AtomicWorkspaceEngine: File checkpointing, patch inspection, rollbacks, and SHA-256 milestone commits
- TestHarnessEngine: Subprocess scratch test execution, timeout enforcement, concurrency fuzzing, memory profiling
- MutationVerifierEngine: AST mutant injection, test suite kill rate auditing, fake test detection
- MockAuditorEngine: Trivial assertion detection, tautology flagging, mock leakage detection, negative path auditing
- PropertyOracleEngine: Extreme boundary matrix generation, algebraic roundtrip invariant verification
- ReceiptAttestorEngine: Subprocess execution attestation, HMAC-SHA256 tamper-evident ToolReceipt generation and verification
- ComputeOrchestratorEngine: Thinking token budget calculation, Monte Carlo Tree Search, Best-of-N consensus selection
- CoderFleetDispatcher: Centralized router dispatching actions to all 10 engines
"""
from __future__ import annotations

from .ast_tools import TreeSitterCodemodEngine
from .compute import ComputeOrchestratorEngine
from .diagnostics import DiagnosticsEngine
from .fleet_dispatcher import CoderFleetDispatcher
from .mock_auditor import MockAuditorEngine
from .mutation import MutationVerifierEngine
from .property_oracle import PropertyOracleEngine
from .receipt_attestor import ReceiptAttestorEngine
from .red_team_swarm import (
    AttackVector,
    BreakFinding,
    BreakScenario,
    RedTeamBreakageReport,
    RedTeamSwarm,
)
from .test_harness import TestHarnessEngine
from .visual import VisualGroundingEngine
from .workspace import AtomicWorkspaceEngine

__all__ = [
    "VisualGroundingEngine",
    "DiagnosticsEngine",
    "TreeSitterCodemodEngine",
    "AtomicWorkspaceEngine",
    "TestHarnessEngine",
    "MutationVerifierEngine",
    "MockAuditorEngine",
    "PropertyOracleEngine",
    "ReceiptAttestorEngine",
    "ComputeOrchestratorEngine",
    "CoderFleetDispatcher",
    "AttackVector",
    "BreakScenario",
    "BreakFinding",
    "RedTeamBreakageReport",
    "RedTeamSwarm",
]
