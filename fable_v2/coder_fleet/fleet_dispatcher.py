"""Coder Fleet Dispatcher for Unified Routing to All 10 Coder Subagent Engines.

Provides centralized dispatch(action, params) mapping with error containment,
telemetry, and action discovery.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from .ast_tools import TreeSitterCodemodEngine
from .compute import ComputeOrchestratorEngine
from .diagnostics import DiagnosticsEngine
from .mock_auditor import MockAuditorEngine
from .mutation import MutationVerifierEngine
from .property_oracle import PropertyOracleEngine
from .receipt_attestor import ReceiptAttestorEngine
from .test_harness import TestHarnessEngine
from .visual import VisualGroundingEngine
from .workspace import AtomicWorkspaceEngine


class CoderFleetDispatcher:
    """Unified dispatcher for the 10-Tool Coder Subagent MCP Fleet."""

    def __init__(
        self,
        visual: VisualGroundingEngine | None = None,
        diagnostics: DiagnosticsEngine | None = None,
        ast_tools: TreeSitterCodemodEngine | None = None,
        workspace: AtomicWorkspaceEngine | None = None,
        test_harness: TestHarnessEngine | None = None,
        mutation: MutationVerifierEngine | None = None,
        mock_auditor: MockAuditorEngine | None = None,
        property_oracle: PropertyOracleEngine | None = None,
        receipt_attestor: ReceiptAttestorEngine | None = None,
        compute: ComputeOrchestratorEngine | None = None,
    ) -> None:
        self.visual = visual or VisualGroundingEngine()
        self.diagnostics = diagnostics or DiagnosticsEngine()
        self.ast_tools = ast_tools or TreeSitterCodemodEngine()
        self.workspace = workspace or AtomicWorkspaceEngine()
        self.test_harness = test_harness or TestHarnessEngine()
        self.mutation = mutation or MutationVerifierEngine(test_harness=self.test_harness)
        self.mock_auditor = mock_auditor or MockAuditorEngine()
        self.property_oracle = property_oracle or PropertyOracleEngine(test_harness=self.test_harness)
        self.receipt_attestor = receipt_attestor or ReceiptAttestorEngine()
        self.compute = compute or ComputeOrchestratorEngine()

        self._actions: dict[str, Callable[..., Any]] = {
            # 1. Visual Grounding Engine
            "render_vector": self.visual.render_vector,
            "perceptual_diff": self.visual.perceptual_diff,
            "extract_palette_and_boxes": self.visual.extract_palette_and_boxes,
            # 2. Diagnostics Engine
            "run_diagnostics": self.diagnostics.run_diagnostics,
            "apply_quick_fix": self.diagnostics.apply_quick_fix,
            # 3. TreeSitter / AST Codemod Engine
            "query_ast": self.ast_tools.query_ast,
            "rename_symbol": self.ast_tools.rename_symbol,
            "verify_syntax": self.ast_tools.verify_syntax,
            # 4. Atomic Workspace Engine
            "create_checkpoint": self.workspace.create_checkpoint,
            "inspect_patch": self.workspace.inspect_patch,
            "rollback": self.workspace.rollback,
            "commit_milestone": self.workspace.commit_milestone,
            # 5. Test Harness Engine
            "run_scratch_test": self.test_harness.run_scratch_test,
            "concurrency_fuzz": self.test_harness.concurrency_fuzz,
            "profile_memory_and_cpu": self.test_harness.profile_memory_and_cpu,
            # 6. Mutation Verifier Engine
            "inject_mutants": self.mutation.inject_mutants,
            "audit_test_strength": self.mutation.audit_test_strength,
            # 7. Mock Auditor Engine
            "audit_assertions": self.mock_auditor.audit_assertions,
            "detect_mock_leakage": self.mock_auditor.detect_mock_leakage,
            "enforce_negative_paths": self.mock_auditor.enforce_negative_paths,
            # 8. Property Oracle Engine
            "generate_property_matrix": self.property_oracle.generate_property_matrix,
            "verify_algebraic_invariants": self.property_oracle.verify_algebraic_invariants,
            # 9. Receipt Attestor Engine
            "attest_execution": self.receipt_attestor.attest_execution,
            "verify_receipt": self.receipt_attestor.verify_receipt,
            # 10. Compute Orchestrator Engine
            "calculate_thinking_budget": self.compute.calculate_thinking_budget,
            "mcts_explore": self.compute.mcts_explore,
            "best_of_n_consensus": self.compute.best_of_n_consensus,
        }

    def list_actions(self) -> list[str]:
        """Return list of all registered action names."""
        return sorted(self._actions.keys())

    def dispatch(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch an action with parameter dictionary to the corresponding fleet engine."""
        if action not in self._actions:
            return {
                "success": False,
                "action": action,
                "error": f"Unknown fleet action '{action}'. Available actions: {', '.join(self.list_actions())}",
            }

        target_fn = self._actions[action]
        kwargs = dict(params or {})

        try:
            sig = inspect.signature(target_fn)
            # Filter kwargs to only accepted parameters if not accepting **kwargs
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not has_var_keyword:
                valid_params = set(sig.parameters.keys())
                filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}
            else:
                filtered_kwargs = kwargs

            result = target_fn(**filtered_kwargs)
            return {
                "success": True,
                "action": action,
                "result": result,
            }
        except TypeError as type_err:
            return {
                "success": False,
                "action": action,
                "error": f"Invalid arguments for action '{action}': {type_err}",
            }
        except Exception as exc:
            return {
                "success": False,
                "action": action,
                "error": f"Execution error in action '{action}': {exc}",
            }
