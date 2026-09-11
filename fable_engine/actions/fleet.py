"""Fleet quality rubrics, red team swarm review, cortical plasticity, and auto-update handlers."""
from __future__ import annotations

import collections
from dataclasses import asdict
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.actions.fleet")

from fable_engine.session import (
    ACTIVE_SESSIONS,
    PHASES,
    SESSIONS_DIR,
    SILENT_DELIBERATION_REMINDER,
    FableSession,
    SessionState,
    _validate_session_name,
    _validate_time_budget,
    get_or_load_session,
    get_plasticity_engine,
    get_red_team_swarm,
)
from fable_engine.updater import AutoUpdater

def _get_swarm():
    return get_red_team_swarm()

def _get_cortex():
    return get_plasticity_engine()

def _handle_set_goal_rubric(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'set_goal_rubric'."
    task_objective = arguments.get("task_objective") or arguments.get("objective") or ""
    criteria = arguments.get("criteria") or arguments.get("items") or arguments.get("rubric_items")
    if not criteria:
        return "Error: 'criteria' (list of rubric criteria items/pointers) is required for 'set_goal_rubric'."
    target_score = arguments.get("target_score", 0.95)
    rubric_id = arguments.get("rubric_id")
    meta = arguments.get("metadata")

    session = get_or_load_session(session_name)
    rubric = session.set_goal_rubric(
        task_objective=task_objective,
        criteria=criteria,
        target_score=target_score,
        rubric_id=rubric_id,
        metadata=meta
    )
    session.save()

    items_preview = "\n".join([
        f"- `[{it['pointer_id']}]` (wt: {it['weight']:.1f}, score: {it['score']:.2f}, satisfied: {'✅' if it['satisfied'] else '⏳'}): {it['description']}"
        for it in rubric["items"]
    ])

    return (
        f"### 🎯 Goal Rubric Initialized (`{rubric['rubric_id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Objective**: {rubric['task_objective']}\n"
        f"- **Target Goal Score**: `{rubric['target_score'] * 100:.1f}%` (Strict Threshold: >= 95%)\n"
        f"- **Current Composite Score**: `{rubric['current_score'] * 100:.1f}%`\n"
        f"- **Status**: `{rubric['status'].upper()}`\n"
        f"- **Criteria Pointers Count**: `{len(rubric['items'])}`\n\n"
        f"#### 📋 Criteria Pointers Breakdown:\n"
        f"{items_preview}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_evaluate_goal_rubric(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'evaluate_goal_rubric'."
    rubric_id = arguments.get("rubric_id")
    item_evaluations = arguments.get("item_evaluations") or arguments.get("evaluations") or arguments.get("items")

    session = get_or_load_session(session_name)
    rubric = session.evaluate_goal_rubric(
        rubric_id=rubric_id,
        item_evaluations=item_evaluations
    )
    session.save()

    status_badge = "🟢 ACHIEVED (>= 95%)" if rubric["status"] == "achieved" else "🟡 IN_PROGRESS (< 95%)"
    items_preview = "\n".join([
        f"- `[{it['pointer_id']}]` ({it['score']*100:.0f}%, {'✅ SATISFIED' if it['satisfied'] else '⏳ PENDING'}): {it['description']}" +
        (f" [Receipt: `{it['evidence_receipt_id']}`]" if it.get('evidence_receipt_id') else "")
        for it in rubric["items"]
    ])

    return (
        f"### 📈 Goal Rubric Evaluation (`{rubric['rubric_id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Composite Goal Score**: `{rubric['current_score'] * 100:.2f}%`\n"
        f"- **Target Score**: `{rubric['target_score'] * 100:.1f}%`\n"
        f"- **Status**: `{status_badge}`\n\n"
        f"#### 📊 Criteria Pointers Status:\n"
        f"{items_preview}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_get_goal_rubric(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'get_goal_rubric'."
    rubric_id = arguments.get("rubric_id")

    session = get_or_load_session(session_name)
    rubric = session.get_goal_rubric(rubric_id=rubric_id)
    if not rubric:
        return f"### ⚠️ No Goal Rubric Found\n\nSession `{session.session_name}` has no registered goal rubrics."

    status_badge = "🟢 ACHIEVED" if rubric["status"] == "achieved" else "🟡 IN_PROGRESS"
    items_preview = "\n".join([
        f"- `[{it['pointer_id']}]` (wt: {it['weight']:.1f}, score: {it['score']*100:.0f}%, {'✅' if it['satisfied'] else '⏳'}): {it['description']}" +
        (f" (Verifier: `{it['verifier_command']}`)" if it.get('verifier_command') else "")
        for it in rubric["items"]
    ])

    return (
        f"### 📋 Goal Rubric Details (`{rubric['rubric_id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Task Objective**: {rubric['task_objective']}\n"
        f"- **Target Score**: `{rubric['target_score'] * 100:.1f}%`\n"
        f"- **Current Score**: `{rubric['current_score'] * 100:.2f}%`\n"
        f"- **Status**: `{status_badge}`\n\n"
        f"#### 📑 Criteria Breakdown:\n"
        f"{items_preview}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_register_automation_pipeline(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'register_automation_pipeline'."
    name = arguments.get("name") or arguments.get("pipeline_name") or ""
    if not name:
        return "Error: 'name' is required for 'register_automation_pipeline'."
    pipeline_type = arguments.get("pipeline_type", "closed_loop")
    generator_command = arguments.get("generator_command") or arguments.get("generator_cmd") or ""
    evaluator_command = arguments.get("evaluator_command") or arguments.get("evaluator_cmd") or ""
    target_threshold = arguments.get("target_threshold") if arguments.get("target_threshold") is not None else arguments.get("target_score", 0.95)
    max_iterations = arguments.get("max_iterations", 10)
    meta = arguments.get("metadata")

    session = get_or_load_session(session_name)
    pipe = session.register_automation_pipeline(
        name=name,
        pipeline_type=pipeline_type,
        generator_command=generator_command,
        evaluator_command=evaluator_command,
        target_threshold=target_threshold,
        max_iterations=max_iterations,
        metadata=meta
    )
    session.save()

    return (
        f"### ⚙️ Autonomous Pipeline Registered (`{pipe['pipeline_id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Pipeline Name**: `{pipe['name']}`\n"
        f"- **Pipeline Type**: `{pipe['pipeline_type']}`\n"
        f"- **Generator Command**: `{pipe['generator_command'] or 'N/A'}`\n"
        f"- **Evaluator Command**: `{pipe['evaluator_command'] or 'N/A'}`\n"
        f"- **Target Threshold**: `{pipe['target_threshold'] * 100:.1f}%`\n"
        f"- **Max Iterations**: `{pipe['max_iterations']}`\n"
        f"- **Status**: `ACTIVE 🚀`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_red_team_code_review(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    if not session_name:
        return "Error: 'session_name' is required for action 'red_team_code_review'."

    target_name = arguments.get("target_name", "system")
    code_snippet = None
    for k in ("target_code", "code_snippet", "code", "target_callable"):
        if k in arguments and arguments[k] is not None:
            code_snippet = arguments[k]
            break

    if code_snippet is not None and not callable(code_snippet):
        return (
            "Error: Source-code strings cannot be evaluated in-process for security reasons. "
            "Dynamic source-code execution is disabled for public actions until an isolated sandbox executor is configured."
        )

    custom_hypotheses = arguments.get("custom_hypotheses") or arguments.get("hypotheses")
    output_path = arguments.get("output_path")

    session = get_or_load_session(session_name)
    report = _get_swarm().run_full_review_cycle(
        target_callable=code_snippet,
        target_name=target_name,
        custom_hypotheses=custom_hypotheses,
    )
    report_dict = report.to_dict()
    session.record_breakage_report(report_dict)
    session.save()

    md_report = _get_swarm().document_breakage(report, output_path=output_path)
    return (
        f"{md_report}\n\n"
        f"- **Session Recorded**: `{session.session_name}`\n"
        f"- **Total Breakage Reports in Session**: `{len(session.breakage_reports)}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_record_breakage_report(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'record_breakage_report'."
    report_data = arguments.get("report") or arguments.get("report_data") or {}
    if not report_data and (arguments.get("findings") is not None or arguments.get("broken_scenarios") is not None):
        raw_findings = arguments.get("findings") if arguments.get("findings") is not None else arguments.get("broken_scenarios", [])
        broken_cnt = arguments.get("broken_count")
        if broken_cnt is None:
            broken_cnt = sum(1 for f in raw_findings if (f.get("broken", True) if isinstance(f, dict) else getattr(f, "broken", True)))
        report_data = {
            "report_id": arguments.get("report_id", f"report_{int(time.time())}"),
            "target_name": arguments.get("target_name", "system"),
            "total_probes": arguments.get("total_probes", len(raw_findings)),
            "broken_count": int(broken_cnt),
            "passed": arguments.get("passed", int(broken_cnt) == 0),
            "findings": raw_findings,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "remediation_directives": arguments.get("remediation_directives", [])
        }
    if not report_data:
        return "Error: 'report', 'report_data', 'findings', or 'broken_scenarios' is required for 'record_breakage_report'."

    session = get_or_load_session(session_name)
    broken_count = int(report_data.get("broken_count", 0))
    findings = report_data.get("findings", [])

    if broken_count > 0:
        session.current_state = SessionState.REMEDIATION_REQUIRED
        session.iteration_count += 1
        session.active_breakages = [
            {
                "scenario_id": f.get("scenario_id") if isinstance(f, dict) else getattr(f, "scenario_id", ""),
                "hypothesis": f.get("hypothesis") if isinstance(f, dict) else getattr(f, "hypothesis", ""),
                "reproduction_code": f.get("reproduction_code") if isinstance(f, dict) else getattr(f, "reproduction_code", ""),
                "severity": f.get("severity", "MEDIUM") if isinstance(f, dict) else getattr(f, "severity", "MEDIUM"),
                "error_message": f.get("error_message") if isinstance(f, dict) else getattr(f, "error_message", ""),
                "vector": f.get("vector") if isinstance(f, dict) else getattr(f, "vector", ""),
            }
            for f in findings
            if (f.get("broken") if isinstance(f, dict) else getattr(f, "broken", False))
        ]
        directives = report_data.get("remediation_directives") or [
            f"Remediate {b.get('hypothesis', b.get('scenario_id', 'breakage'))}" for b in session.active_breakages
        ]
        session.remediation_history.append({
            "iteration": session.iteration_count,
            "report_id": report_data.get("report_id"),
            "broken_count": broken_count,
            "timestamp": time.time(),
            "breakages": list(session.active_breakages),
            "remediation_directives": directives,
        })
        session.breakage_reports.append(report_data)
        session.save()

        directives_list = "\n".join([f"- {d}" for d in directives])
        order_msg = f"TASK REJECTED: {broken_count} breakages detected. Deploy subagent to fix findings."
        return (
            f"### 🚨 {order_msg}\n\n"
            f"> [!CAUTION]\n"
            f"> **{order_msg}**\n\n"
            f"- **Session**: `{session.session_name}`\n"
            f"- **Current State**: `REMEDIATION_REQUIRED` 🔴\n"
            f"- **Broken Count**: `{broken_count}`\n"
            f"- **Active Breakages Tracked**: `{len(session.active_breakages)}`\n\n"
            f"#### 🛠️ Structured Remediation Directives:\n{directives_list}\n"
            f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
        )
    else:
        # Guard SEALED state behind mandatory-stage evidence verification and provenance checks
        proven_untrusted_free = [
            i for i in session.epistemic_ledger
            if i.get("tag") == "PROVEN"
            and not i.get("_restored_untrusted")
            and str(i.get("evidence", "")).strip()
        ]
        valid_refinements = [
            r for r in session.refinement_cycles
            if not r.get("_restored_untrusted")
        ]
        achieved_rubric = any(
            r.get("status") == "achieved" or float(r.get("current_score", 0.0)) >= float(r.get("target_score", 0.95))
            for r in session.goal_rubrics
        )
        has_current_file_changes = len(session.file_changes) >= 1 and not getattr(session, "_restored_untrusted", False)

        if not (len(proven_untrusted_free) >= 2 and valid_refinements and achieved_rubric and has_current_file_changes):
            return (
                "Error: Cannot SEAL session: Missing current-process mandatory-stage evidence. "
                "Session must have >=2 untrusted-free [PROVEN] epistemic items with evidence, >=1 current-process refinement cycle, "
                ">=1 achieved goal rubric meeting target score, and current-process file changes logged before sealing."
            )

        session.record_breakage_report(report_data)
        session.save()

        completed_msg = "TASK COMPLETED: 0 breakages remain. Code sealed."
        return (
            f"### 🛡️ {completed_msg}\n\n"
            f"🟢 **{completed_msg}**\n\n"
            f"- **Session**: `{session.session_name}`\n"
            f"- **Current State**: `SEALED` 🟢\n"
            f"- **Broken Count**: `0`\n"
            f"- **Status**: Verified resilient. Ready for `evolve_cortex`.\n"
            f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
        )


def _handle_verify_red_team_remediation(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    if not session_name:
        return "Error: 'session_name' is required for action 'verify_red_team_remediation'."

    remediated_code = None
    for k in ("remediated_code", "target_code", "code_snippet", "code", "target_callable"):
        if k in arguments and arguments[k] is not None:
            remediated_code = arguments[k]
            break

    if remediated_code is not None and not callable(remediated_code):
        return (
            "Error: Source-code strings cannot be evaluated in-process for security reasons. "
            "Dynamic source-code execution is disabled for public actions until an isolated sandbox executor is configured."
        )

    session = get_or_load_session(session_name)

    report_id = arguments.get("report_id")
    prior_report = arguments.get("prior_report")

    if not prior_report:
        if report_id:
            prior_report = next((r for r in session.breakage_reports if r.get("report_id") == str(report_id).strip()), None)
        elif session.breakage_reports:
            prior_report = session.breakage_reports[-1]

    if not prior_report:
        return "Error: No prior breakage report found to verify. Provide 'report_id' or 'prior_report'."
    timeout_sec = float(arguments.get("timeout_seconds", 3.0))
    all_fixed, new_report = _get_swarm().verify_remediation(
        target_callable=remediated_code,
        prior_report=prior_report,
        timeout_seconds=timeout_sec,
    )
    session.breakage_reports.append(new_report.to_dict())

    if not all_fixed or new_report.broken_count > 0:
        session.current_state = SessionState.REMEDIATION_REQUIRED
        session.iteration_count += 1
        session.active_breakages = [
            {
                "scenario_id": f.scenario_id,
                "hypothesis": f.hypothesis,
                "reproduction_code": f.reproduction_code,
                "severity": f.severity,
                "error_message": f.error_message,
                "vector": f.vector,
            }
            for f in new_report.findings
            if f.broken
        ]
        session.remediation_history.append({
            "iteration": session.iteration_count,
            "report_id": new_report.report_id,
            "broken_count": new_report.broken_count,
            "timestamp": time.time(),
            "breakages": list(session.active_breakages),
            "remediation_directives": new_report.remediation_directives,
        })
        session.save()

        directives_list = "\n".join([f"- {d}" for d in new_report.remediation_directives])
        order_msg = f"TASK REJECTED: {new_report.broken_count} breakages detected. Deploy subagent to fix findings."
        return (
            f"### 🚨 {order_msg}\n\n"
            f"> [!CAUTION]\n"
            f"> **{order_msg}**\n\n"
            f"- **Session**: `{session.session_name}`\n"
            f"- **Current State**: `REMEDIATION_REQUIRED` 🔴 (Iteration {session.iteration_count})\n"
            f"- **Remaining Breakages**: `{new_report.broken_count}`\n\n"
            f"#### 🛠️ Directives for Next Remediation Cycle:\n{directives_list}\n"
            f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
        )
    else:
        session.current_state = SessionState.SEALED
        session.active_breakages = []
        session.remediation_history.append({
            "iteration": session.iteration_count,
            "report_id": new_report.report_id,
            "broken_count": 0,
            "timestamp": time.time(),
            "status": "ALL_BREAKAGES_FIXED",
        })
        session.save()

        completed_msg = "TASK COMPLETED: 0 breakages remain. Code sealed."
        return (
            f"### 🛡️ {completed_msg}\n\n"
            f"🟢 **{completed_msg}**\n\n"
            f"- **Session**: `{session.session_name}`\n"
            f"- **Current State**: `SEALED` 🟢\n"
            f"- **Broken Count**: `0`\n"
            f"- **Remediation Iterations**: `{session.iteration_count}`\n\n"
            f"> [!NOTE]\n"
            f"> All prior adversarial breakages resolved with zero regressions. Session is in `SEALED` state. Automatically proceed or advance to `EVOLVED` state via `evolve_cortex`."
            f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
        )


def _handle_evolve_cortex(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'evolve_cortex'."
    session = get_or_load_session(session_name)

    if session.current_state not in (SessionState.SEALED, SessionState.EVOLVED):
        return f"Error: evolve_cortex rejected: Session must be in SEALED or EVOLVED state (current state: {session.current_state.value})."

    domain = arguments.get("domain") or "python"
    task_id = arguments.get("task_id") or session.session_id

    neutralized_scenarios = arguments.get("broken_scenarios") or []
    if not neutralized_scenarios:
        for rep in session.breakage_reports:
            for f in rep.get("findings", []):
                if isinstance(f, dict) and f.get("broken"):
                    neutralized_scenarios.append(f)
                elif hasattr(f, "broken") and f.broken:
                    neutralized_scenarios.append(f.to_dict() if hasattr(f, "to_dict") else asdict(f))
        for hist in session.remediation_history:
            for b in hist.get("breakages", []):
                if b not in neutralized_scenarios:
                    neutralized_scenarios.append(b)

    co_activated_nodes = arguments.get("co_activated_nodes") or ["mutation", "test_harness", "red_team_swarm", "property_oracle"]

    evo_receipt = _get_cortex().consolidate_task(
        task_id=task_id,
        success=True,
        domain=domain,
        broken_scenarios=neutralized_scenarios,
        co_activated_nodes=co_activated_nodes,
    )

    session.transition_to(SessionState.EVOLVED, "Cortical evolution consolidation completed")
    session.save()

    antibodies_list = "\n".join([f"- `ab_{domain}_{s.get('scenario_id', 'unknown')}`: {s.get('hypothesis', 'Neutralized breakage')}" for s in neutralized_scenarios]) if neutralized_scenarios else "- Antibodies consolidated into cortical lobe."
    weights_table = "\n".join([f"| `{k}` | `{v:.4f}` | `+0.10 * A_domain * A_node (LTP)` |" for k, v in evo_receipt.get("synaptic_weights", {}).items()])

    return (
        f"### 🧬 Cortical Evolution Receipt: EVOLVED\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Current State**: `EVOLVED` 🌟\n"
        f"- **Domain Lobe**: `{domain}` (`skills/fable-mode/cortex/{domain}.md`)\n"
        f"- **Task ID**: `{task_id}`\n"
        f"- **Plasticity Mode**: `LTP (Long-Term Potentiation)` (Score: +1.0)\n"
        f"- **Antibodies Added**: `{evo_receipt.get('antibodies_added', 0)}`\n"
        f"- **Total Lobe Antibodies**: `{evo_receipt.get('total_antibodies', 0)}`\n"
        f"- **A_domain**: `{evo_receipt.get('A_domain', 0.80)}`\n\n"
        f"#### 🛡️ Synthesized Heuristic Antibodies:\n{antibodies_list}\n\n"
        f"#### ⚡ Potentiated Synaptic Weights:\n"
        f"| Node | Potentiated Weight | Hebbian Rule |\n"
        f"| :--- | :---: | :--- |\n"
        f"{weights_table}\n\n"
        f"> [!TIP]\n"
        f"> Cortical lobe `skills/fable-mode/cortex/{domain}.md` successfully evolved and persisted to disk."
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_cortical_define_lobe(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    name = arguments.get("name") or arguments.get("lobe_name") or ""
    if not name:
        return "Error: 'name' or 'lobe_name' is required for action 'cortical_define_lobe'."
    description = arguments.get("description") or arguments.get("desc") or ""
    initial_heuristics = arguments.get("initial_heuristics") or arguments.get("heuristics") or []
    initial_synaptic_weights = arguments.get("initial_synaptic_weights") or arguments.get("synaptic_weights") or {}

    lobe = _get_cortex().define_cortical_lobe(
        name=str(name),
        description=str(description),
        initial_heuristics=initial_heuristics if isinstance(initial_heuristics, list) else [str(initial_heuristics)],
        initial_synaptic_weights=initial_synaptic_weights if isinstance(initial_synaptic_weights, dict) else {},
    )
    session = get_or_load_session(session_name) if session_name else None

    md_output = (
        f"### 🧠 Cortical Lobe Sprouted: `{lobe.name}`\n\n"
        f"- **Name**: `{lobe.name}`\n"
        f"- **Description**: {lobe.description}\n"
        f"- **Domain**: `{lobe.domain}`\n"
        f"- **Heuristics Initialized**: `{len(lobe.specialized_heuristics)}`\n"
        f"- **Synaptic Nodes**: `{len(lobe.synaptic_weights)}`\n"
        f"- **File Path**: `skills/fable-mode/cortex/{lobe.name}.md`\n"
    )
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_cortical_list_lobes(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    lobes = _get_cortex().list_cortical_lobes()
    session = get_or_load_session(session_name) if session_name else None

    lines = [
        "### 🧠 Available Cortical Lobes",
        "",
        f"Total Lobes: `{len(lobes)}`",
        "",
        "| Lobe Name | Description | Activations | Antibodies | Heuristics |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for l in lobes:
        desc = l['description'][:60] + "..." if len(l['description']) > 60 else (l['description'] or "—")
        lines.append(f"| `{l['name']}` | {desc} | `{l['activation_count']}` | `{l['antibody_count']}` | `{l['heuristic_count']}` |")

    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_check_auto_update(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if AutoUpdater is None:
        return "Error: AutoUpdater module is unavailable."
    updater = AutoUpdater()
    res = updater.check_for_updates()
    session = get_or_load_session(session_name) if session_name else None
    lines = [
        "### 🔄 Fable Autonomous Auto-Updater Status",
        "",
        f"- **Update Available**: `{res.get('update_available', False)}`",
        f"- **Local Commit**: `{res.get('local_commit', 'unknown')}`",
        f"- **Remote Commit**: `{res.get('remote_commit', 'unknown')}`",
        f"- **Offline / Standalone**: `{res.get('offline', False)}`",
        f"- **Status**: {res.get('message', '')}",
    ]
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_apply_auto_update(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if AutoUpdater is None:
        return "Error: AutoUpdater module is unavailable."
    preserve_cortex = arguments.get("preserve_cortex", True)
    if isinstance(preserve_cortex, str):
        preserve_cortex = preserve_cortex.lower() not in ("false", "0", "no")
    updater = AutoUpdater()
    res = updater.apply_update(preserve_cortex=preserve_cortex)
    session = get_or_load_session(session_name) if session_name else None
    status_emoji = "✅" if res.get("success") else "⚠️"
    targets = res.get("synced_targets", [])
    synced_str = ", ".join(f"`{t}`" for t in targets) if targets else "None"
    preserved = res.get("preserved_lobes", [])
    pres_str = ", ".join(f"`{p}`" for p in preserved) if preserved else "None"
    lines = [
        f"### {status_emoji} Fable Autonomous Auto-Updater Applied",
        "",
        f"- **Success**: `{res.get('success', False)}`",
        f"- **Updated**: `{res.get('updated', False)}`",
        f"- **Message**: {res.get('message', '')}",
        f"- **Preserved Cortical Lobes**: {pres_str}",
        f"- **Host Targets Synced**: {synced_str}",
    ]
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


try:
    from fable_v2.coder_fleet.design_engine import (
        AestheticArchetype,
        DesignDials,
        DesignEngine,
        HAUTE_THEMES,
    )
except ImportError:
    DesignEngine = None
    HAUTE_THEMES = {}

_GLOBAL_DESIGN_ENGINE = None

def _get_design_engine():
    global _GLOBAL_DESIGN_ENGINE
    if _GLOBAL_DESIGN_ENGINE is None and DesignEngine is not None:
        _GLOBAL_DESIGN_ENGINE = DesignEngine()
    return _GLOBAL_DESIGN_ENGINE


def _handle_audit_anti_slop(arguments: Dict[str, Any]) -> str:
    code = arguments.get("code") or arguments.get("content") or arguments.get("html") or arguments.get("source") or ""
    file_path = arguments.get("file_path", "")
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    res = engine.audit_anti_slop(code, file_path=file_path)
    status_badge = "🟢 CLEAN (ZERO AI SLOP)" if res["clean"] else f"🔴 FAILED ({res['total_violations']} VIOLATIONS)"
    lines = [
        f"### 🛡️ Anti-Slop Design Audit: {status_badge}",
        "",
        f"- **Anti-Slop Score**: `{res['score'] * 100:.1f}%`",
        f"- **Clean**: `{res['clean']}`",
        f"- **Fatal Violations**: `{res['fatal_count']}`",
        f"- **High Violations**: `{res['high_count']}`",
        f"- **Medium Violations**: `{res['medium_count']}`",
        "",
    ]
    if res["violations"]:
        lines.append("#### ⚠️ Violations Breakdown:")
        for v in res["violations"]:
            lines.append(f"- **[{v['severity']}] `{v['rule_id']}`** (Line {v['line_number'] or 'N/A'}): {v['message']}")
            lines.append(f"  - *Snippet*: `{v['snippet']}`")
            lines.append(f"  - *Remedy*: {v['remedy']}")
    else:
        lines.append("✅ **All Anti-Slop Gates Passed**: Zero purple blobs, zero centered 3-card boilerplates, zero LLM marketing fluff, zero fake div dots, zero viewport instability.")

    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_infer_design_brief(arguments: Dict[str, Any]) -> str:
    prompt = arguments.get("prompt") or arguments.get("user_prompt") or arguments.get("brief") or ""
    dials_override = arguments.get("dials_override") or arguments.get("dials")
    archetype_override = arguments.get("archetype_override") or arguments.get("archetype")
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    res = engine.infer_design_brief(prompt, dials_override=dials_override, archetype_override=archetype_override)
    dials = res["dials"]
    palette = res["palette"]
    typo = res["typography"]
    layout = res["layout_blueprint"]
    lines = [
        "### 🎨 Fable Brief Inference & Design Read",
        "",
        f"> **{res['design_read']}**",
        "",
        f"- **Page Kind**: `{res['page_kind']}`",
        f"- **Target Audience**: {res['target_audience']}",
        f"- **Optimal Archetype**: `{res['archetype_title']}` (`{res['archetype']}`)",
        f"- **Aesthetic Vector**: Variance `{dials['variance']}` / Motion `{dials['motion']}` / Density `{dials['density']}`",
        "",
        "#### 🎨 Curated OKLCH Palette:",
        f"- Background Void: `{palette['bg_void']}`",
        f"- Surface Card: `{palette['surface_card']}`",
        f"- Hairline Border: `{palette['border_hairline']}`",
        f"- Primary Accent: `{palette['accent_primary']}`",
        f"- Primary Text: `{palette['text_primary']}`",
        "",
        "#### 🔤 Typographic Pairings:",
        f"- Display: `{typo['display']}`",
        f"- Body: `{typo['body']}`",
        f"- Monospace: `{typo['mono']}`",
        "",
        "#### 📐 Layout Architecture:",
        f"- Hero Stack: Max {layout['hero_stack_max_elements']} text elements, cap at {layout['hero_top_padding_cap']}",
        f"- Navigation: {layout['navigation_height_cap']}",
        f"- Grid: {layout['bento_grid_structure']}",
        f"- CTA Constraint: {layout['desktop_cta_rule']}",
    ]
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_generate_design_tokens(arguments: Dict[str, Any]) -> str:
    archetype = arguments.get("archetype") or arguments.get("name") or "cyber_obsidian_monolith"
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    data = engine.generate_design_tokens(archetype=archetype)
    lines = [
        f"### 🎛️ Haute Design Tokens: `{data['title']}`",
        "",
        f"> {data['description']}",
        "",
        f"- **Radius Scale**: `{data['border_radius_scale']}`",
        f"- **Spring Physics**: `{data['spring_physics']['name']}` (Stiffness: {data['spring_physics']['stiffness']}, Damping: {data['spring_physics']['damping']}, Mass: {data['spring_physics']['mass']})",
        f"- **WCAG Contrast**: `{data['wcag_aa_contrast']['primary_to_bg_ratio']}:1` ({'✅ Meets AA' if data['wcag_aa_contrast']['meets_wcag_aa'] else '⚠️ Below AA'})",
        "",
        "```css",
        data["tailwind_v4_theme"],
        "```",
    ]
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_generate_awwwards_scaffold(arguments: Dict[str, Any]) -> str:
    prompt = arguments.get("prompt") or arguments.get("user_prompt") or arguments.get("brief") or "Modern software platform"
    archetype = arguments.get("archetype") or arguments.get("archetype_override") or arguments.get("name")
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    res = engine.generate_awwwards_scaffold(prompt=prompt, archetype_override=archetype)
    lines = [
        f"### 🏆 Awwwards-Caliber Zero-Slop Scaffold Generated",
        "",
        f"> **{res['design_read']}**",
        "",
        f"- **Aesthetic Archetype**: `{res['theme_title']}` (`{res['archetype']}`)",
        f"- **Anti-Slop Verified**: `{'✅ 100% CLEAN' if res['anti_slop_verified'] else '⚠️ VIOLATIONS DETECTED'}` (Score: `{res['audit_result']['score'] * 100:.1f}%`)",
        "",
        "#### 🎨 Tailwind CSS v4 Theme:",
        "```css",
        res["tailwind_v4_theme"],
        "```",
        "",
        "#### 🏗️ Semantic 7-Layer HTML/JSX Layout:",
        "```html",
        res["html_layout"][:2000] + "\n... [Full layout available via code export]",
        "```",
    ]
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_validate_preflight_design(arguments: Dict[str, Any]) -> str:
    code = arguments.get("code") or arguments.get("content") or arguments.get("html") or arguments.get("source") or ""
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    res = engine.validate_preflight_design(code)
    status_badge = "🟢 PRE-FLIGHT APPROVED" if res["approved"] else "🔴 PRE-FLIGHT REJECTED"
    lines = [
        f"### 🚦 5-Point Pre-Flight Design Gate: {status_badge}",
        "",
        f"- **Composite Score**: `{res['composite_score'] * 100:.1f}%`",
        f"- **Passed Checks**: `{res['passed_checks']}/{res['total_checks']}`",
        f"- **Approved**: `{res['approved']}`",
        "",
        "#### 📋 5-Point Verification Checklist:",
    ]
    for chk in res["checklist"]:
        mark = "✅ PASSED" if chk["passed"] else "❌ FAILED"
        lines.append(f"- **Point {chk['point']} ({chk['name']})**: {mark} — {chk['details']}")

    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output


def _handle_list_design_archetypes(arguments: Dict[str, Any]) -> str:
    session_name = arguments.get("session_name", "").strip()
    session = get_or_load_session(session_name) if session_name else None
    engine = _get_design_engine()
    if engine is None:
        return "Error: DesignEngine module is unavailable."

    archetypes = engine.list_design_archetypes()
    lines = [
        "### 🏛️ Haute Aesthetic Archetypes (Anti-Slop Universes)",
        "",
        "| Archetype Key | Title | Dials (V/M/D) | Aesthetic Character |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for arch in archetypes:
        d = arch["dials"]
        lines.append(f"| `{arch['archetype']}` | **{arch['title']}** | `{d['variance']}/{d['motion']}/{d['density']}` | {arch['description']} |")

    lines.append("")
    lines.append("Use `action: 'generate_design_tokens'` with `archetype: '<key>'` or `action: 'generate_awwwards_scaffold'` to scaffold.")
    md_output = "\n".join(lines)
    if session and session.execution_locked:
        md_output += SILENT_DELIBERATION_REMINDER
    return md_output
