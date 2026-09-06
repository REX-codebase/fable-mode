"""Session lifecycle, timer pacing, and state transition action handlers."""
from __future__ import annotations

import collections
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.actions.lifecycle")

from fable_engine.session import (
    ACTIVE_SESSIONS,
    PHASES,
    SESSIONS_DIR,
    SILENT_DELIBERATION_REMINDER,
    FableSession,
    SessionState,
    _validate_session_name,
    _validate_time_budget,
    _safe_session_file,
    get_or_load_session,
)

def _handle_create_session(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'create_session'."
    session_name = _validate_session_name(session_name)
    objective = arguments.get("objective", "").strip()
    if not objective:
        return "Error: 'objective' is required for action 'create_session'."
    
    time_budget = arguments.get("time_budget_minutes", 60.0)
    try:
        time_budget_min = float(time_budget)
    except (ValueError, TypeError):
        return f"Error: Invalid 'time_budget_minutes': {time_budget}."

    session = FableSession(session_name, objective, time_budget_min)
    ACTIVE_SESSIONS[session_name] = session
    session.save()

    tel = session.get_telemetry()
    return (
        f"### 🛡️ Fable Cognitive Session Initialized\n\n"
        f"- **Session Name**: `{session.session_name}`\n"
        f"- **Session ID**: `{session.session_id}`\n"
        f"- **Objective**: {session.objective}\n"
        f"- **Time Budget**: `{session.time_budget_minutes}` minutes ({tel['remaining_formatted']})\n"
        f"- **Active Phase**: `{session.active_phase}`\n"
        f"- **Execution Lock**: `LOCKED (can_execute_code: False)` 🛑\n"
        f"- **Cognitive Gates**: 0/2 [PROVEN] items, 0/1 Invariant recorded\n\n"
        f"> [!IMPORTANT]\n"
        f"> Anti-Rush Lockout is ACTIVE. Proceed with epistemic grounding, research, and invariant modeling before requesting execution unlock."
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_set_timer(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'set_timer'."
    time_budget = arguments.get("time_budget_minutes")
    if time_budget is None:
        return "Error: 'time_budget_minutes' is required for action 'set_timer'."
    try:
        time_budget_min = float(time_budget)
    except (ValueError, TypeError):
        return f"Error: Invalid 'time_budget_minutes': {time_budget}."

    session = get_or_load_session(session_name)
    tel = session.set_timer(time_budget_min)
    session.save()

    return (
        f"### ⏱️ Fable Session Timer Updated\n\n"
        f"- **Session Name**: `{session.session_name}`\n"
        f"- **Pacing Timer**: `{session.pacing_budget_minutes}` minutes\n"
        f"- **Authority Budget**: `{session.time_budget_minutes}` minutes (immutable)\n"
        f"- **Elapsed Time**: `{tel['elapsed_formatted']}`\n"
        f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}`\n"
        f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`\n"
        f"- **Pacing Ratio**: `{tel['pacing_percentage']}`\n"
        f"- **Authority Deadline**: `{time.ctime(session.deadline_time)}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_get_status(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'get_status'."

    session = get_or_load_session(session_name)
    tel = session.get_telemetry()

    lock_badge = "🔴 LOCKED (`can_execute_code: False`)" if session.execution_locked else "🟢 UNLOCKED (`can_execute_code: True`)"
    
    # Format ledger breakdown
    counts = tel["epistemic_counts"]
    ledger_lines = []
    for item in session.epistemic_ledger[-5:]:  # show recent 5
        ev_str = f" (Evidence: {item['evidence']})" if item.get('evidence') else ""
        ledger_lines.append(f"- `[{item['tag']}]` **{item['id']}**: {item['claim']}{ev_str}")
    ledger_preview = "\n".join(ledger_lines) if ledger_lines else "- No items logged yet."

    # Format invariants preview
    inv_lines = []
    for inv in session.invariants[-5:]:
        inv_lines.append(f"- **{inv['name']}** `[{inv['domain']}]`: {inv['formal_statement']}")
    inv_preview = "\n".join(inv_lines) if inv_lines else "- No invariants recorded yet."

    # Format refinement preview
    ref_lines = []
    for ref in session.refinement_cycles[-3:]:
        ref_lines.append(f"- **Cycle #{ref['cycle_number']}** `[{ref['refinement_type'].upper()}]` ({ref['focus_area']}): {ref['architectural_refinement']}")
    ref_preview = "\n".join(ref_lines) if ref_lines else "- No refinement cycles recorded yet."

    cog_state = tel.get("system3_cognitive_state", {})
    return (
        f"### 📊 Fable Session Status & Telemetry (`{session.session_name}`)\n\n"
        f"- **Objective**: {session.objective}\n"
        f"- **Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
        f"- **Execution Lock**: {lock_badge}\n"
        f"- **Pacing**: `{tel['elapsed_formatted']}` elapsed / `{tel['pacing_remaining_formatted']}` remaining (`{tel['pacing_percentage']}` budget used)\n"
        f"- **Authority**: `{tel['authority_remaining_formatted']}` remaining (immutable outer deadline)\n"
        f"- **Epistemic Breakdown**: `{counts['proven']} PROVEN`, `{counts['hypothesis']} HYPOTHESIS`, `{counts['unknown']} UNKNOWN` (Total: `{counts['total']}`)\n"
        f"- **Invariants Recorded**: `{tel['invariants_count']}`\n"
        f"- **Refinement Cycles**: `{tel['refinement_count']}`\n\n"
        f"#### 🧠 System 3 Meta-Cognitive State:\n"
        f"- **Variational Free Energy $F$**: `{cog_state.get('free_energy_f', 'N/A')}` "
        f"(Complexity $D_{{KL}}$: `{cog_state.get('complexity_kl', 'N/A')}`, Accuracy: `{cog_state.get('accuracy_log_likelihood', 'N/A')}`)\n"
        f"- **Kripke Safety Invariant**: `{cog_state.get('kripke_safety_invariant', 'AG(safe) -> True')}`\n"
        f"- **Active Biases Tracked**: `{cog_state.get('active_biases_count', 0)}`\n"
        f"- **Contradiction Density**: `{cog_state.get('contradiction_density', 0.0)}`\n"
        f"- **Hyperbolic Metric**: `{cog_state.get('hyperbolic_metric', {}).get('status', 'INITIALIZED')}`\n\n"
        f"#### 🔍 Recent Epistemic Ledger Items:\n{ledger_preview}\n\n"
        f"#### 📐 Invariants Specification:\n{inv_preview}\n\n"
        f"#### 🔄 Recent Refinement Cycles:\n{ref_preview}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_advance_phase(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'advance_phase'."
    next_phase = arguments.get("next_phase", "").strip()
    if not next_phase:
        return "Error: 'next_phase' is required for action 'advance_phase'."
    phase_summary = arguments.get("phase_summary", "").strip() or "Advanced phase transition."

    session = get_or_load_session(session_name)
    tel = session.advance_phase(next_phase, phase_summary)
    session.save()

    cog_state = tel.get("system3_cognitive_state", {})
    bias_lines = ""
    if session.active_biases:
        bias_items = "\n".join([f"  * ⚠️ **{b['bias_type']}** ({b['severity']}): {b['description']} -> *{b['mitigation_recommendation']}*" for b in session.active_biases])
        bias_lines = f"\n- **Active Biases Intercepted** ({len(session.active_biases)}):\n{bias_items}"

    sys3_advisory = (
        f"\n\n### 🧠 System 3 Meta-Cognitive Advisory & Active Inference\n"
        f"- **Live Free Energy $F$**: `{cog_state.get('free_energy_f', 'N/A')}` "
        f"(Complexity $D_{{KL}}$: `{cog_state.get('complexity_kl', 'N/A')}`, Accuracy: `{cog_state.get('accuracy_log_likelihood', 'N/A')}`)\n"
        f"- **Kripke Safety Invariant**: `{cog_state.get('kripke_safety_invariant', 'AG(safe) -> True')}`\n"
        f"- **Contradiction Density**: `{cog_state.get('contradiction_density', 0.0)}`"
        f"{bias_lines}"
    )

    return (
        f"### 🚀 Fable Phase Advanced Successfully\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **New Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
        f"- **Phase Summary**: {phase_summary}\n"
        f"- **Execution Status**: `{'LOCKED 🛑' if session.execution_locked else 'UNLOCKED 🟢'}`\n"
        f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}` (`{tel['pacing_percentage']}` used)\n"
        f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`"
        f"{sys3_advisory}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_unlock_execution(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'unlock_execution'."
    rationale = arguments.get("rationale", "").strip()
    if not rationale:
        return "Error: 'rationale' is required for action 'unlock_execution'."
    # No model-provided override is accepted. Administrative callers
    # must use the direct host API with an out-of-band secret.
    session = get_or_load_session(session_name)
    try:
        res = session.unlock_execution(rationale)
        session.save()
        override_msg = " ⚠️ *(Out-of-band emergency override)*" if session.unlock_details.get("force_override_used") else ""
        return (
            f"### 🔓 Execution Lock Lifted Successfully{override_msg}\n\n"
            f"- **Session**: `{session.session_name}`\n"
            f"- **Status**: `🟢 UNLOCKED`\n"
            f"- **`can_execute_code`**: `True`\n"
            f"- **Phase at Unlock**: `{session.active_phase}`\n"
            f"- **Rationale**: {rationale}\n"
            f"- **Validated Gates**: `{len(session.epistemic_ledger)}` epistemic items ({session.unlock_details['proven_count']} PROVEN), `{len(session.invariants)}` Invariants, `{len(session.refinement_cycles)}` Refinement Cycles\n\n"
            f"> [!TIP]\n"
            f"> Implementer subagents may now execute code and run automated tests."
        )
    except PermissionError as pe:
        return str(pe)


def _handle_checkpoint_session(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'checkpoint_session'."
    session = get_or_load_session(session_name)
    saved_path = session.save()
    return (
        f"### 💾 Fable Session Checkpointed\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Path**: `{saved_path}`\n"
        f"- **Phase**: `{session.active_phase}`\n"
        f"- **Epistemic Items**: `{len(session.epistemic_ledger)}`\n"
        f"- **Invariants**: `{len(session.invariants)}`\n"
        f"- **Refinement Cycles**: `{len(session.refinement_cycles)}`\n"
        f"- **Execution Lock**: `{'LOCKED' if session.execution_locked else 'UNLOCKED'}`"
    )


def _handle_restore_session(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'restore_session'."
    session = get_or_load_session(session_name)
    tel = session.get_telemetry()
    return (
        f"### 📂 Fable Session Restored\n\n"
        f"- **Session**: `{session.session_name}` (`{session.session_id}`)\n"
        f"- **Objective**: {session.objective}\n"
        f"- **Active Phase**: `{session.active_phase}`\n"
        f"- **Pacing Remaining**: `{tel['remaining_formatted']}`\n"
        f"- **Execution Lock**: `{'LOCKED' if session.execution_locked else 'UNLOCKED'}`\n"
        f"- **Ledger**: `{tel['epistemic_counts']['proven']} PROVEN`, `{tel['epistemic_counts']['hypothesis']} HYPOTHESIS`\n"
        f"- **Invariants**: `{tel['invariants_count']}`\n"
        f"- **Refinement Cycles**: `{tel['refinement_count']}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_list_sessions(arguments: Dict[str, Any]) -> str:
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    files = list(SESSIONS_DIR.glob("*.json"))
    session_entries = []
    for f in files:
        try:
            _safe_session_file(f)
            with open(f, "r", encoding="utf-8") as s_file:
                s_data = json.load(s_file)
            status_icon = "🟢" if not s_data.get("execution_locked", True) else "🛑"
            session_entries.append(
                f"- `{s_data.get('session_name', f.stem)}` {status_icon} | "
                f"**Phase**: {s_data.get('active_phase', 'Unknown')} | "
                f"**Budget**: {s_data.get('time_budget_minutes', 0)}m | "
                f"**File**: `{f.name}`"
            )
        except Exception:
            session_entries.append(f"- `{f.stem}` (Unreadable session file)")

    listing = "\n".join(session_entries) if session_entries else "- No saved sessions found."
    return (
        f"### 🗂️ Available Fable Sessions in `{SESSIONS_DIR}`\n\n"
        f"{listing}"
    )


