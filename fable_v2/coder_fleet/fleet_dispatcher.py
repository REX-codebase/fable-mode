"""Coder Fleet Dispatcher for Unified Routing to All 10 Coder Subagent Engines.

Provides centralized dispatch(action, params) mapping with error containment,
telemetry, and action discovery.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from ..cortical import HebbianPlasticityEngine
from .ast_tools import TreeSitterCodemodEngine
from .compute import ComputeOrchestratorEngine
from .diagnostics import DiagnosticsEngine
from .mock_auditor import MockAuditorEngine
from .mutation import MutationVerifierEngine
from .property_oracle import PropertyOracleEngine
from .receipt_attestor import ReceiptAttestorEngine
from .red_team_swarm import RedTeamSwarm
from .test_harness import TestHarnessEngine
from .vector_engine import FableVectorCompiler, VLayoutSolver, VNode
from .visual import VisualGroundingEngine
from .workspace import AtomicWorkspaceEngine


class CoderFleetDispatcher:
    """Unified dispatcher for the 10-Tool Coder Subagent MCP Fleet and Cortical Engine."""

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
        red_team_swarm: RedTeamSwarm | None = None,
        plasticity_engine: HebbianPlasticityEngine | None = None,
        vector_compiler: FableVectorCompiler | None = None,
        layout_solver: VLayoutSolver | None = None,
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
        self.plasticity_engine = plasticity_engine or HebbianPlasticityEngine()
        self.vector_compiler = vector_compiler or FableVectorCompiler()
        self.layout_solver = layout_solver or VLayoutSolver()
        self.red_team_swarm = red_team_swarm or RedTeamSwarm(
            test_harness=self.test_harness,
            mock_auditor=self.mock_auditor,
            property_oracle=self.property_oracle,
            plasticity_engine=self.plasticity_engine,
        )

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
            # 11. Red Team Swarm Engine (Modular Fable Part 1: Adversarial Code Review)
            "red_team_generate_scenarios": self.red_team_swarm.generate_break_scenarios,
            "red_team_execute_attack": self.red_team_swarm.execute_swarm_attack,
            "red_team_document_breakage": self.red_team_swarm.document_breakage,
            "red_team_verify_remediation": self.red_team_swarm.verify_remediation,
            "red_team_full_review_cycle": self.red_team_swarm.run_full_review_cycle,
            "red_team_code_review": self.red_team_swarm.run_full_review_cycle,
            "record_breakage_report": self.red_team_swarm.document_breakage,
            "verify_red_team_remediation": self.red_team_swarm.verify_remediation,
            # 12. Cortical Plasticity Engine (Modular Fable Part 2: Hebbian Learning & Domain Lobes)
            "cortical_define_lobe": self.plasticity_engine.define_cortical_lobe,
            "cortical_list_lobes": self.plasticity_engine.list_cortical_lobes,
            "cortical_activate_lobe": self.plasticity_engine.activate_lobe,
            "cortical_consolidate_task": self.plasticity_engine.consolidate_task,
            "cortical_recall_context": self.plasticity_engine.recall_cortical_context,
            "cortical_inspect_matrix": self.plasticity_engine.get_synaptic_matrix,
            "evolve_cortex": self.plasticity_engine.consolidate_task,
            # 13. Fable-Vector Neuro-Symbolic Vector Engine
            "compile_vector": self.compile_vector,
            "solve_layout": self.solve_layout,
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

    def compile_vector(
        self,
        node: VNode | dict[str, Any] | None = None,
        tree: VNode | dict[str, Any] | None = None,
        root: VNode | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compile a VNode tree or dictionary definition into production SVG."""
        target = node if node is not None else (tree if tree is not None else root)
        if target is None:
            raise ValueError("No node, tree, or root provided to compile_vector")
        svg_code = self.vector_compiler.compile(target, options=options)
        return {
            "svg": svg_code,
            "valid": True,
        }

    def solve_layout(
        self,
        root: VNode | dict[str, Any] | None = None,
        node: VNode | dict[str, Any] | None = None,
        tree: VNode | dict[str, Any] | None = None,
        viewport_width: float = 1920.0,
        viewport_height: float = 1080.0,
    ) -> dict[str, Any]:
        """Solve layout constraints and return computed coordinates and bounding boxes."""
        target = root if root is not None else (node if node is not None else tree)
        if target is None:
            raise ValueError("No root, node, or tree provided to solve_layout")
        return self.layout_solver.solve_layout(
            target,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
