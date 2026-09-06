"""Fable-Mode Modular Action Dispatch Registry and Facade."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict

logger = logging.getLogger("fable-engine.actions")

from fable_engine.guards import GLOBAL_VELOCITY_PROFILER

from fable_engine.actions.lifecycle import (
    _handle_create_session,
    _handle_set_timer,
    _handle_get_status,
    _handle_advance_phase,
    _handle_unlock_execution,
    _handle_checkpoint_session,
    _handle_restore_session,
    _handle_list_sessions,
)
from fable_engine.actions.deliberation import (
    _handle_log_epistemic_item,
    _handle_record_invariant,
    _handle_log_refinement_cycle,
    _handle_compile_delegation_contract,
    _handle_track_file_change,
    _handle_get_session_lineage,
    _handle_inspect_plan,
    _handle_verify_proof,
    _handle_record_visual_mockups,
    _handle_validate_event_history,
)
from fable_engine.actions.cas import (
    _handle_compress_payload,
    _handle_decompress_payload,
    _handle_view_slice,
    _handle_accumulate_payload,
    _handle_flush_accumulator,
    _handle_get_compression_stats,
)
from fable_engine.actions.system3 import (
    _handle_system3_dialectical_synthesis,
    _handle_system3_causal_simulate,
    _handle_system3_evolve_paradigms,
    _handle_system3_induce_axioms,
    _handle_system3_meta_reflect,
    _handle_system3_tri_level_orchestrate,
    _handle_system3_hyperbolic_embed,
    _handle_system3_kripke_verify,
    _handle_system3_active_inference,
    _handle_system3_proof_oracle,
)
from fable_engine.actions.fleet import (
    _handle_set_goal_rubric,
    _handle_evaluate_goal_rubric,
    _handle_get_goal_rubric,
    _handle_register_automation_pipeline,
    _handle_red_team_code_review,
    _handle_record_breakage_report,
    _handle_verify_red_team_remediation,
    _handle_evolve_cortex,
    _handle_cortical_define_lobe,
    _handle_cortical_list_lobes,
    _handle_check_auto_update,
    _handle_apply_auto_update,
)

ACTION_DISPATCH: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "create_session": _handle_create_session,
    "init": _handle_create_session,
    "create": _handle_create_session,
    "set_timer": _handle_set_timer,
    "update_timer": _handle_set_timer,
    "timer": _handle_set_timer,
    "get_status": _handle_get_status,
    "telemetry": _handle_get_status,
    "status": _handle_get_status,
    "advance_phase": _handle_advance_phase,
    "next_phase": _handle_advance_phase,
    "advance": _handle_advance_phase,
    "log_epistemic_item": _handle_log_epistemic_item,
    "log_item": _handle_log_epistemic_item,
    "epistemic_log": _handle_log_epistemic_item,
    "record_invariant": _handle_record_invariant,
    "add_invariant": _handle_record_invariant,
    "invariant": _handle_record_invariant,
    "log_refinement_cycle": _handle_log_refinement_cycle,
    "record_refinement": _handle_log_refinement_cycle,
    "refine": _handle_log_refinement_cycle,
    "unlock_execution": _handle_unlock_execution,
    "unlock": _handle_unlock_execution,
    "checkpoint_session": _handle_checkpoint_session,
    "save_session": _handle_checkpoint_session,
    "checkpoint": _handle_checkpoint_session,
    "save": _handle_checkpoint_session,
    "restore_session": _handle_restore_session,
    "load_session": _handle_restore_session,
    "restore": _handle_restore_session,
    "load": _handle_restore_session,
    "list_sessions": _handle_list_sessions,
    "list": _handle_list_sessions,
    "compile_delegation_contract": _handle_compile_delegation_contract,
    "compile_contract": _handle_compile_delegation_contract,
    "validate_contract": _handle_compile_delegation_contract,
    "compress_payload": _handle_compress_payload,
    "compress": _handle_compress_payload,
    "cas_put": _handle_compress_payload,
    "cas_store": _handle_compress_payload,
    "decompress_payload": _handle_decompress_payload,
    "decompress": _handle_decompress_payload,
    "cas_get": _handle_decompress_payload,
    "cas_read": _handle_decompress_payload,
    "view_slice": _handle_view_slice,
    "cas_slice": _handle_view_slice,
    "slice": _handle_view_slice,
    "accumulate_payload": _handle_accumulate_payload,
    "accumulate": _handle_accumulate_payload,
    "cas_accumulate": _handle_accumulate_payload,
    "flush_accumulator": _handle_flush_accumulator,
    "flush_cas": _handle_flush_accumulator,
    "cas_flush": _handle_flush_accumulator,
    "get_compression_stats": _handle_get_compression_stats,
    "compression_stats": _handle_get_compression_stats,
    "cas_stats": _handle_get_compression_stats,
    "system3_dialectical_synthesis": _handle_system3_dialectical_synthesis,
    "dialectical_synthesis": _handle_system3_dialectical_synthesis,
    "triz_synthesis": _handle_system3_dialectical_synthesis,
    "synthesis": _handle_system3_dialectical_synthesis,
    "system3_causal_simulate": _handle_system3_causal_simulate,
    "causal_simulate": _handle_system3_causal_simulate,
    "causal_graph": _handle_system3_causal_simulate,
    "do_calculus": _handle_system3_causal_simulate,
    "system3_evolve_paradigms": _handle_system3_evolve_paradigms,
    "evolve_paradigms": _handle_system3_evolve_paradigms,
    "evolution_generation": _handle_system3_evolve_paradigms,
    "genetic_optimize": _handle_system3_evolve_paradigms,
    "system3_induce_axioms": _handle_system3_induce_axioms,
    "induce_axioms": _handle_system3_induce_axioms,
    "neuro_symbolic_induction": _handle_system3_induce_axioms,
    "formalize_axioms": _handle_system3_induce_axioms,
    "system3_meta_reflect": _handle_system3_meta_reflect,
    "meta_reflect": _handle_system3_meta_reflect,
    "cognitive_audit": _handle_system3_meta_reflect,
    "meta_cognition": _handle_system3_meta_reflect,
    "system3_tri_level_orchestrate": _handle_system3_tri_level_orchestrate,
    "tri_level_orchestrate": _handle_system3_tri_level_orchestrate,
    "cognitive_gear_shift": _handle_system3_tri_level_orchestrate,
    "arbitrate_cognition": _handle_system3_tri_level_orchestrate,
    "system3_hyperbolic_embed": _handle_system3_hyperbolic_embed,
    "hyperbolic_embed": _handle_system3_hyperbolic_embed,
    "poincare_embed": _handle_system3_hyperbolic_embed,
    "hyperbolic_tree": _handle_system3_hyperbolic_embed,
    "system3_kripke_verify": _handle_system3_kripke_verify,
    "kripke_verify": _handle_system3_kripke_verify,
    "modal_verify": _handle_system3_kripke_verify,
    "ctl_check": _handle_system3_kripke_verify,
    "system3_active_inference": _handle_system3_active_inference,
    "active_inference": _handle_system3_active_inference,
    "free_energy": _handle_system3_active_inference,
    "fe_step": _handle_system3_active_inference,
    "system3_proof_oracle": _handle_system3_proof_oracle,
    "proof_oracle": _handle_system3_proof_oracle,
    "curry_howard": _handle_system3_proof_oracle,
    "formal_prove": _handle_system3_proof_oracle,
    "track_file_change": _handle_track_file_change,
    "track_file": _handle_track_file_change,
    "record_file_change": _handle_track_file_change,
    "get_session_lineage": _handle_get_session_lineage,
    "lineage": _handle_get_session_lineage,
    "session_lineage": _handle_get_session_lineage,
    "inspect_plan": _handle_inspect_plan,
    "plan": _handle_inspect_plan,
    "inspect_blueprint": _handle_inspect_plan,
    "verify_proof": _handle_verify_proof,
    "validate_proof": _handle_verify_proof,
    "check_proof": _handle_verify_proof,
    "record_visual_mockups": _handle_record_visual_mockups,
    "visual_mockups": _handle_record_visual_mockups,
    "record_mockups": _handle_record_visual_mockups,
    "validate_event_history": _handle_validate_event_history,
    "validate_event_chain": _handle_validate_event_history,
    "audit_events": _handle_validate_event_history,
    "set_goal_rubric": _handle_set_goal_rubric,
    "register_goal_rubric": _handle_set_goal_rubric,
    "goal_rubric": _handle_set_goal_rubric,
    "evaluate_goal_rubric": _handle_evaluate_goal_rubric,
    "eval_goal_rubric": _handle_evaluate_goal_rubric,
    "evaluate_rubric": _handle_evaluate_goal_rubric,
    "score_rubric": _handle_evaluate_goal_rubric,
    "get_goal_rubric": _handle_get_goal_rubric,
    "get_rubric": _handle_get_goal_rubric,
    "inspect_rubric": _handle_get_goal_rubric,
    "register_automation_pipeline": _handle_register_automation_pipeline,
    "register_pipeline": _handle_register_automation_pipeline,
    "automation_pipeline": _handle_register_automation_pipeline,
    "red_team_code_review": _handle_red_team_code_review,
    "red_team_review": _handle_red_team_code_review,
    "code_review_swarm": _handle_red_team_code_review,
    "adversarial_review": _handle_red_team_code_review,
    "record_breakage_report": _handle_record_breakage_report,
    "log_breakage_report": _handle_record_breakage_report,
    "breakage_report": _handle_record_breakage_report,
    "verify_red_team_remediation": _handle_verify_red_team_remediation,
    "verify_remediation": _handle_verify_red_team_remediation,
    "red_team_verify": _handle_verify_red_team_remediation,
    "evolve_cortex": _handle_evolve_cortex,
    "cortical_evolve": _handle_evolve_cortex,
    "evolve": _handle_evolve_cortex,
    "cortical_define_lobe": _handle_cortical_define_lobe,
    "define_cortical_lobe": _handle_cortical_define_lobe,
    "sprout_cortical_lobe": _handle_cortical_define_lobe,
    "cortical_list_lobes": _handle_cortical_list_lobes,
    "list_cortical_lobes": _handle_cortical_list_lobes,
    "list_lobes": _handle_cortical_list_lobes,
    "check_auto_update": _handle_check_auto_update,
    "auto_update_check": _handle_check_auto_update,
    "apply_auto_update": _handle_apply_auto_update,
    "auto_update_apply": _handle_apply_auto_update,
}


def handle_fable_session(arguments: Dict[str, Any]) -> str:
    """Main dispatch handler for fable_session tool actions."""
    try:
        action = arguments.get("action", "").strip().lower()
        if not action:
            return "Error: Missing required parameter 'action'."
        GLOBAL_VELOCITY_PROFILER.record_request(action, arguments)

        handler = ACTION_DISPATCH.get(action)
        if handler is not None:
            return handler(arguments)
        else:
            return (
                f"Error: Unknown action '{action}'. Supported actions: "
                f"'create_session', 'set_timer', 'get_status', 'telemetry', 'advance_phase', "
                f"'log_epistemic_item', 'record_invariant', 'log_refinement_cycle', 'unlock_execution', "
                f"'checkpoint_session', 'restore_session', 'list_sessions', 'compile_delegation_contract', "
                f"'compress_payload', 'decompress_payload', 'view_slice', 'accumulate_payload', 'flush_accumulator', 'get_compression_stats', "
                f"'system3_dialectical_synthesis', 'system3_causal_simulate', 'system3_evolve_paradigms', 'system3_induce_axioms', 'system3_meta_reflect', 'system3_tri_level_orchestrate', "
                f"'system3_hyperbolic_embed', 'system3_kripke_verify', 'system3_active_inference', 'system3_proof_oracle', "
                f"'track_file_change', 'get_session_lineage', 'inspect_plan', 'verify_proof', 'record_visual_mockups', 'validate_event_history', "
                f"'set_goal_rubric', 'evaluate_goal_rubric', 'get_goal_rubric', 'register_automation_pipeline', "
                f"'red_team_code_review', 'record_breakage_report', 'verify_red_team_remediation', "
                f"'cortical_define_lobe', 'cortical_list_lobes', 'check_auto_update', 'apply_auto_update', 'evolve_cortex'."
            )
    except Exception as ex:
        return f"Error: {str(ex)}"

