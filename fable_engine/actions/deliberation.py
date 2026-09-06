"""Deliberation, epistemic ledger, invariants, refinement, and proof action handlers."""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.actions.deliberation")

from fable_engine.guards import (
    GLOBAL_VELOCITY_PROFILER,
    DelegationContractCompiler,
)
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
)
# DeterministicProofValidator imported lazily

def _handle_log_epistemic_item(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'log_epistemic_item'."
    tag = arguments.get("tag", "").strip()
    if not tag:
        return "Error: 'tag' (PROVEN, HYPOTHESIS, UNKNOWN) is required for 'log_epistemic_item'."
    claim = arguments.get("claim", "").strip()
    if not claim:
        return "Error: 'claim' is required for 'log_epistemic_item'."
    evidence = arguments.get("evidence")

    session = get_or_load_session(session_name)
    item = session.log_epistemic_item(tag, claim, evidence)
    session.save()

    tel = session.get_telemetry()
    counts = tel["epistemic_counts"]

    ev_display = f"\n- **Evidence**: `{item['evidence']}`" if item.get("evidence") else ""
    return (
        f"### 📝 Epistemic Item Logged (`{item['id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Classification**: `[{item['tag']}]`\n"
        f"- **Claim**: {item['claim']}{ev_display}\n"
        f"- **Logged in**: `{item['phase']}`\n"
        f"- **Ledger Total**: `{counts['proven']} PROVEN`, `{counts['hypothesis']} HYPOTHESIS`, `{counts['unknown']} UNKNOWN`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_record_invariant(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'record_invariant'."
    invariant_name = arguments.get("invariant_name", "").strip()
    if not invariant_name:
        return "Error: 'invariant_name' is required for 'record_invariant'."
    formal_statement = arguments.get("formal_statement", "").strip()
    if not formal_statement:
        return "Error: 'formal_statement' is required for 'record_invariant'."
    proof_or_rationale = arguments.get("proof_or_rationale", "").strip()
    domain = arguments.get("domain", "architecture").strip()

    session = get_or_load_session(session_name)
    inv = session.record_invariant(invariant_name, formal_statement, proof_or_rationale, domain)
    session.save()

    return (
        f"### 📐 Formal Invariant Recorded (`{inv['id']}`)\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Invariant Name**: **{inv['name']}**\n"
        f"- **Domain**: `{inv['domain'].upper()}`\n"
        f"- **Formal Statement**: `{inv['formal_statement']}`\n"
        f"- **Proof / Rationale**: {inv['proof_or_rationale']}\n"
        f"- **Total Invariants**: `{len(session.invariants)}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_log_refinement_cycle(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'log_refinement_cycle'."
    refinement_type = arguments.get("refinement_type", "").strip()
    if not refinement_type:
        return "Error: 'refinement_type' is required for 'log_refinement_cycle'."
    focus_area = arguments.get("focus_area", "").strip()
    if not focus_area:
        return "Error: 'focus_area' is required for 'log_refinement_cycle'."
    critique_or_bottleneck = arguments.get("critique_or_bottleneck", "").strip()
    if not critique_or_bottleneck:
        return "Error: 'critique_or_bottleneck' is required for 'log_refinement_cycle'."
    architectural_refinement = arguments.get("architectural_refinement", "").strip()
    if not architectural_refinement:
        return "Error: 'architectural_refinement' is required for 'log_refinement_cycle'."
    
    terminal_probe_results = arguments.get("terminal_probe_results")
    artifact_path = arguments.get("artifact_path")

    session = get_or_load_session(session_name)
    cycle = session.log_refinement_cycle(
        refinement_type=refinement_type,
        focus_area=focus_area,
        critique_or_bottleneck=critique_or_bottleneck,
        architectural_refinement=architectural_refinement,
        terminal_probe_results=terminal_probe_results,
        artifact_path=artifact_path
    )
    session.save()

    tel = session.get_telemetry()
    probe_display = f"\n- **Terminal Probes / Benchmarks**: `{cycle['terminal_probe_results']}`" if cycle.get("terminal_probe_results") else ""
    artifact_display = f"\n- **Artifact Blueprint**: `{cycle['artifact_path']}`" if cycle.get("artifact_path") else ""

    return (
        f"### 🔄 Rethink-Refine Cycle #{cycle['cycle_number']} Logged\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Refinement Type**: `{cycle['refinement_type'].upper()}`\n"
        f"- **Focus Area**: {cycle['focus_area']}\n"
        f"- **Critique / Bottleneck**: {cycle['critique_or_bottleneck']}\n"
        f"- **Architectural Refinement**: {cycle['architectural_refinement']}{probe_display}{artifact_display}\n"
        f"- **Phase**: `{cycle['phase']}`\n"
        f"- **Pacing Remaining**: `{tel['remaining_formatted']}` ({tel['pacing_percentage']} budget used)\n"
        f"- **Total Refinement Cycles**: `{len(session.refinement_cycles)}`\n\n"
        f"> [!TIP]\n"
        f"> Rethink-Refine Cognitive Loop active. Continue exploring alternative archetypes, falsifications, and terminal benchmarks until the time budget is fulfilled."
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_compile_delegation_contract(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    prompt = arguments.get("subagent_prompt") or arguments.get("prompt") or arguments.get("contract") or ""
    if not str(prompt).strip():
        return "Error: 'subagent_prompt' (or 'prompt') is required for action 'compile_delegation_contract'."

    compiler = DelegationContractCompiler()
    is_valid, errors, parsed = compiler.compile_and_validate(prompt)

    if not is_valid:
        err_list = "\n".join([f"- ❌ {e}" for e in errors])
        return (
            f"### 🛑 Subagent Delegation Contract Compilation Failed\n\n"
            f"The subagent prompt does not satisfy the strict Fable-Mode delegation boundaries:\n\n"
            f"{err_list}\n\n"
            f"> [!WARNING]\n"
            f"> Worker subagents must receive 100% bounded, unambiguous contracts before dispatch.\n"
            f"> Ensure your prompt contains:\n"
            f"> 1. `TargetFile: <file path>`\n"
            f"> 2. `InterfaceContract: <type/function signature>`\n"
            f"> 3. `StrictConstraints: <invariants / bounds>`\n"
            f"> 4. `VerificationCommand: <exact CLI test command>`"
        )

    compiled_scaffold = parsed.get("compiled_prompt", prompt)
    return (
        f"### ✅ Subagent Delegation Contract Compiled Successfully (with System 3 Micro-Scaffolds)\n\n"
        f"- **Target File**: `{parsed.get('TargetFile', 'Declared')}`\n"
        f"- **Verification Command**: `{parsed.get('VerificationCommand', 'Declared')}`\n"
        f"- **Contract Status**: `100% BOUNDED & VALIDATED`\n"
        f"- **System 3 Micro-Scaffolds**: `INJECTED (Kripke AG(safe), Causal do(·) bounds, TRIZ Transcendence, Regex Constraints)`\n"
        f"- **Dispatch Readiness**: `READY_FOR_SUBAGENT_DISPATCH` 🚀\n\n"
        f"```markdown\n{compiled_scaffold}\n```\n\n"
        f"> [!TIP]\n"
        f"> You may now dispatch a worker subagent (`type: self`) with this validated contract once execution is unlocked."
    )


def _handle_track_file_change(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'track_file_change'."
    file_path = arguments.get("file_path", "").strip()
    if not file_path:
        return "Error: 'file_path' is required for action 'track_file_change'."
    change_type = arguments.get("change_type", "").strip().lower()
    if not change_type:
        return "Error: 'change_type' ('modified', 'created', 'deleted', 'slated') is required for action 'track_file_change'."
    diff_summary = arguments.get("diff_summary", "").strip()
    if not diff_summary:
        return "Error: 'diff_summary' is required for action 'track_file_change'."
    rationale = arguments.get("rationale", "").strip()
    affected_invariants = arguments.get("affected_invariants")

    session = get_or_load_session(session_name)
    entry = session.track_file_change(file_path, change_type, diff_summary, rationale, affected_invariants)
    if getattr(session, "fable_run", None):
        try:
            from fable_v2.protocol import FileChangeRecord
            session.fable_run.record_file_change(
                FileChangeRecord(
                    file_path=file_path,
                    change_type=change_type,
                    before_hash=entry.get("before_hash"),
                    after_hash=entry.get("after_hash", ""),
                    diff_summary=diff_summary,
                    rationale=rationale or "",
                    affected_invariants=tuple(affected_invariants or []),
                )
            )
        except Exception:
            pass
    session.save()

    inv_str = f"\n- **Affected Invariants**: `{', '.join(entry['affected_invariants'])}`" if entry.get("affected_invariants") else ""
    sha_str = f"\n- **File SHA256**: `{entry['sha256']}`" if entry.get("sha256") else ""
    return (
        f"### 📂 File Change Tracked\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Target File**: `{entry['file_path']}`\n"
        f"- **Change Type**: `{entry['change_type'].upper()}`\n"
        f"- **Diff Summary**: {entry['diff_summary']}\n"
        f"- **Rationale**: {entry['rationale'] or 'N/A'}"
        f"{sha_str}"
        f"{inv_str}\n"
        f"- **Total Tracked Changes**: `{len(session.file_changes)}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_get_session_lineage(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'get_session_lineage'."
    session = get_or_load_session(session_name)
    tel = session.get_telemetry()
    v_prof = tel.get("velocity_profile", {})

    # 1. Past files modified/created/deleted
    past_files = [fc for fc in session.file_changes if fc.get("change_type") != "slated"]
    past_lines = []
    for pf in past_files:
        sha = f" (`{pf['sha256'][:8]}`)" if pf.get("sha256") else ""
        past_lines.append(f"- `[{pf['change_type'].upper()}]` `{pf['file_path']}`{sha}: {pf['diff_summary']}")
    past_str = "\n".join(past_lines) if past_lines else "- No files modified or created yet."

    # 2. Slated files
    slated_files = [fc for fc in session.file_changes if fc.get("change_type") == "slated"]
    slated_lines = []
    for sf in slated_files:
        slated_lines.append(f"- `[SLATED]` `{sf['file_path']}`: {sf['diff_summary']} (Rationale: {sf.get('rationale', 'N/A')})")
    slated_str = "\n".join(slated_lines) if slated_lines else "- No upcoming files slated."

    # 3. Roadmap & Phase History
    phase_lines = []
    for ph in session.phase_history:
        phase_lines.append(f"- **{ph['phase']}**: {ph.get('summary', 'Entered')}")
    roadmap_str = "\n".join(phase_lines)

    # 4. Epistemic ledger
    epi_lines = []
    for item in session.epistemic_ledger:
        rcpt = f" (Receipt: `{item['proof_receipt']['receipt_id']}`)" if item.get("proof_receipt") else ""
        epi_lines.append(f"- `[{item['tag']}]` **{item['id']}**: {item['claim']}{rcpt}")
    epi_str = "\n".join(epi_lines) if epi_lines else "- No epistemic items logged."

    # 5. Invariants
    inv_lines = []
    for inv in session.invariants:
        rcpt = f" (Receipt: `{inv['proof_receipt']['receipt_id']}`)" if inv.get("proof_receipt") else ""
        inv_lines.append(f"- **{inv['name']}** `[{inv['domain']}]`: `{inv['formal_statement']}`{rcpt}")
    inv_str = "\n".join(inv_lines) if inv_lines else "- No formal invariants recorded."

    # 6. Visual mockups
    vm = session.visual_mockups if isinstance(session.visual_mockups, dict) else {}
    mockups_list = vm.get("mockups", [])
    vm_lines = []
    for m in mockups_list:
        sel = " 🌟 *(SELECTED)*" if m.get("concept_name") == vm.get("selected_concept") else ""
        vm_lines.append(f"- **{m.get('concept_name', 'Concept')}** `[{m.get('aesthetic_archetype', 'N/A')}]`{sel}: Palette: {m.get('palette', 'N/A')}, Typography: {m.get('typography', 'N/A')}")
    vm_str = "\n".join(vm_lines) if vm_lines else "- No visual mockups recorded."

    return (
        f"### 🌐 Omniscient Session Lineage (`{session.session_name}`)\n\n"
        f"#### 🎯 Mission Objective & Roadmap:\n"
        f"- **Goal**: {session.objective}\n"
        f"- **Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
        f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}` / Authority: `{tel['authority_remaining_formatted']}`\n\n"
        f"#### 🛣️ Phase Progression History:\n{roadmap_str}\n\n"
        f"#### 📝 Completed File Mutations ({len(past_files)}):\n{past_str}\n\n"
        f"#### 📋 Slated File Modifications ({len(slated_files)}):\n{slated_str}\n\n"
        f"#### 🔬 Epistemic Grounding Ledger ({len(session.epistemic_ledger)} items):\n{epi_str}\n\n"
        f"#### 📐 Formal Invariants & Contract Verification ({len(session.invariants)} items):\n{inv_str}\n\n"
        f"#### 🎨 Visual Mockup Concepts & Spatial Spec:\n{vm_str}\n\n"
        f"#### ⚡ Model Velocity & Capability Telemetry:\n"
        f"- **Tier**: `{v_prof.get('model_tier', 'pro').upper()}` (Multiplier: `{v_prof.get('tier_multiplier', 1.0)}x`)\n"
        f"- **Velocity**: `{v_prof.get('tokens_per_sec', 0.0)} est. tokens/sec` (`{v_prof.get('chars_per_sec', 0.0)} chars/sec`)\n"
        f"- **Call Frequency**: `{v_prof.get('tool_call_frequency_cpm', 0.0)} calls/min` (Avg Interval: `{v_prof.get('avg_interval_seconds', 0.0)}s`)\n"
        f"- **Total Ingested**: `{v_prof.get('total_requests', 0)} calls` / `{v_prof.get('total_estimated_tokens', 0)} est. tokens`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_inspect_plan(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'inspect_plan'."
    session = get_or_load_session(session_name)
    tel = session.get_telemetry()
    gate_report = session._gate_report()

    min_refinements = max(2, math.ceil(session.time_budget_minutes / 5.0))
    current_refinements = len(session.refinement_cycles)
    refinement_ok = current_refinements >= min_refinements

    # Refinement history
    ref_lines = []
    for ref in session.refinement_cycles:
        ref_lines.append(f"- **Cycle #{ref['cycle_number']}** `[{ref['refinement_type'].upper()}]` ({ref['focus_area']}): {ref['architectural_refinement']}")
    ref_str = "\n".join(ref_lines) if ref_lines else "- No rethink-refine cycles logged yet."

    # Slated files
    slated_files = [fc for fc in session.file_changes if fc.get("change_type") == "slated"]
    slated_lines = []
    for sf in slated_files:
        slated_lines.append(f"- `{sf['file_path']}`: {sf['diff_summary']}")
    slated_str = "\n".join(slated_lines) if slated_lines else "- None declared yet."

    # Gate checklist
    c = gate_report["checks"]
    gate_checklist = (
        f"- [{'x' if c['two_proven_evidence_items'] else ' '}] At least 2 [PROVEN] facts with evidence ({gate_report['proven_with_evidence']}/2)\n"
        f"- [{'x' if c['one_proved_invariant'] else ' '}] At least 1 formal Invariant with proof/rationale ({gate_report['invariants_with_proof']}/1)\n"
        f"- [{'x' if c['adversarial_phase_reached'] else ' '}] Active Phase >= Phase 3 (Current: Phase {tel['phase_index']})\n"
        f"- [{'x' if refinement_ok else ' '}] Anti-Idle Refinement Cycles ({current_refinements}/{min_refinements} required)\n"
        f"- [{'x' if not session.execution_locked else ' '}] Immutable Authority Deadline Elapsed ({tel['authority_remaining_formatted']} remaining)"
    )

    delegation_guidelines = (
        "1. Verify execution is unlocked (`can_execute_code: True`).\n"
        "2. Compile Subagent Delegation Contracts with explicit `TargetFile`, `InterfaceContract`, `StrictConstraints`, and `VerificationCommand`.\n"
        "3. Dispatch subagents to perform atomic codebase changes.\n"
        "4. Enforce DoD validation via automated test suite execution."
    )

    return (
        f"### 📋 Fable Execution Plan & Cognitive Blueprint (`{session.session_name}`)\n\n"
        f"- **Objective**: {session.objective}\n"
        f"- **Active Phase**: `{session.active_phase}`\n"
        f"- **Execution Lock**: `{'🔴 LOCKED' if session.execution_locked else '🟢 UNLOCKED'}`\n\n"
        f"#### 🚦 Cognitive Gate Status:\n{gate_checklist}\n\n"
        f"#### 🔄 Rethink-Refine History ({current_refinements} cycles):\n{ref_str}\n\n"
        f"#### 🛠️ Slated File Implementations:\n{slated_str}\n\n"
        f"#### 🤖 Subagent Delegation & Implementer Instructions:\n{delegation_guidelines}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_verify_proof(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    claim = arguments.get("claim", "").strip()
    if not claim:
        return "Error: 'claim' is required for action 'verify_proof'."
    proof_type = arguments.get("proof_type", "").strip().lower()
    if not proof_type:
        return "Error: 'proof_type' ('ast', 'receipt', 'file_sha256', 'formal_logic', 'vector_coordinates') is required for 'verify_proof'."
    evidence = arguments.get("evidence", "")
    target_resource = arguments.get("target_resource")

    from fable_v2.proof_engine import DeterministicProofValidator
    validator = DeterministicProofValidator()
    result = validator.verify_proof(claim=claim, proof_type=proof_type, evidence=str(evidence), target_resource=target_resource)

    if session_name:
        try:
            session = get_or_load_session(session_name)
            session.proof_receipts.append(result)
            if getattr(session, "fable_run", None):
                try:
                    from fable_v2.protocol import ToolReceipt
                    session.fable_run.record_receipt(
                        ToolReceipt(
                            tool_name=f"proof_{proof_type}",
                            args={"claim": claim, "target_resource": target_resource},
                            output=result,
                            success=bool(result.get("verified")),
                            session_id=session.session_id,
                        )
                    )
                except Exception:
                    pass
            session.save()
        except Exception:
            pass

    status_badge = "✅ VERIFIED" if result.get("verified") else "❌ FAILED"
    err_msg = f"\n- **Error**: {result['error']}" if result.get("error") else ""
    details_msg = f"\n- **Details**: {result['details']}" if result.get("details") else ""
    return (
        f"### ⚖️ Deterministic Proof Verification\n\n"
        f"- **Status**: `{status_badge}`\n"
        f"- **Receipt ID**: `{result.get('receipt_id')}`\n"
        f"- **Proof Type**: `{result.get('proof_type')}`\n"
        f"- **Claim**: {result.get('claim')}\n"
        f"- **Timestamp**: `{time.ctime(result.get('timestamp', time.time()))}`"
        f"{err_msg}"
        f"{details_msg}"
    )


def _handle_record_visual_mockups(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'record_visual_mockups'."
    mockups = arguments.get("mockups")
    if not mockups:
        return "Error: 'mockups' is required for action 'record_visual_mockups'."
    selected_concept = arguments.get("selected_concept")

    session = get_or_load_session(session_name)
    vm = session.record_visual_mockups(mockups, selected_concept)
    if getattr(session, "fable_run", None):
        try:
            from fable_v2.protocol import VisualMockupSpec
            mockups_list = mockups if isinstance(mockups, list) else [mockups]
            for idx, m in enumerate(mockups_list):
                if isinstance(m, dict):
                    spec = VisualMockupSpec(
                        mockup_id=m.get("mockup_id", f"mockup_{len(session.fable_run.visual_mockups)+1}"),
                        concept_name=m.get("concept_name", f"Concept {idx+1}"),
                        aesthetic_archetype=m.get("aesthetic_archetype", "editorial"),
                        prompt=m.get("prompt", ""),
                        image_url=m.get("image_url"),
                        coordinates_data=m.get("coordinates_data"),
                        palette=tuple(m.get("palette", [])) if isinstance(m.get("palette"), (list, tuple)) else (),
                        typography=m.get("typography", {}) if isinstance(m.get("typography"), dict) else {},
                        status=m.get("status", "draft"),
                        selected_by_user=bool(selected_concept and m.get("concept_name") == selected_concept),
                    )
                    session.fable_run.record_visual_mockup(spec)
        except Exception:
            pass
    session.save()

    concept_lines = []
    for m in vm.get("mockups", []):
        sel = " 🌟 *(SELECTED)*" if m.get("concept_name") == vm.get("selected_concept") else ""
        palette = m.get("palette", "N/A")
        typo = m.get("typography", "N/A")
        concept_lines.append(
            f"- **{m.get('concept_name', 'Concept')}** `[{m.get('aesthetic_archetype', 'N/A')}]`{sel}\n"
            f"  * Prompt: {m.get('prompt', 'N/A')}\n"
            f"  * Palette: `{palette}` | Typography: `{typo}`\n"
            f"  * Coordinates: `{m.get('coordinates_data', 'N/A')}`"
        )
    concept_str = "\n".join(concept_lines)

    return (
        f"### 🎨 Visual Architectural Mockups Recorded\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Total Concepts**: `{len(vm.get('mockups', []))}`\n"
        f"- **Selected Archetype**: `{vm.get('selected_concept')}`\n\n"
        f"#### 🖼️ Concept Specifications:\n"
        f"{concept_str}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_validate_event_history(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'validate_event_history'."
    session = get_or_load_session(session_name)
    if not getattr(session, "fable_run", None):
        return f"### ⚠️ Fable V2 Event History\n\nSession `{session.session_name}` does not have an active FableRun instance."
    try:
        session.fable_run.validate_event_history()
        valid = True
        details = "Cryptographic event chain is intact and verified against genesis root."
    except Exception as ex:
        valid = False
        details = str(ex)

    status_badge = "✅ VALID & INTACT" if valid else "❌ COMPROMISED / INVALID"
    events = getattr(session.fable_run, "events", [])
    genesis_hash = events[0].get("event_hash", "0"*64) if events else "None"
    terminal_hash = events[-1].get("event_hash", "0"*64) if events else "None"
    return (
        f"### 🔗 Fable V2 Cryptographic Event Chain Audit\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Chain Status**: `{status_badge}`\n"
        f"- **Total Events**: `{len(events)}`\n"
        f"- **Genesis Hash**: `{str(genesis_hash)[:16]}...`\n"
        f"- **Terminal Chain Hash**: `{str(terminal_hash)[:16]}...`\n"
        f"- **Audit Summary**: {details}"
    )


