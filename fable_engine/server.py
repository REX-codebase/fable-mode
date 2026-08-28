#!/usr/bin/env python3
"""
Fable-Engine MCP Server for MCP-compatible agent hosts.
Implements the fable_session tool for deep cognitive session management,
epistemic tracking, invariant recording, anti-rush lockout enforcement,
user-controlled time-budgeted pacing telemetry, and session persistence.
"""

import sys
import os
import json
import time
import math
import logging
import hmac
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Reconfigure UTF-8 for Windows stdio
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stdin.encoding != 'utf-8':
    try:
        sys.stdin.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure logging exclusively to stderr so stdout remains pure JSON-RPC
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Fable-Engine] %(message)s"
)
logger = logging.getLogger("fable-engine")

# Base and sessions directories
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Standard Fable Phases
PHASES = [
    "Phase 1: Epistemic Grounding & Live Research",
    "Phase 2: Invariant Specification & Blueprint",
    "Phase 3: Adversarial Red-Teaming & Falsification",
    "Phase 4: Subagent Fleet Delegation",
    "Phase 5: Multi-Tier Verification & Gatekeeping",
    "Phase 6: Final Walkthrough & Reporting"
]

PHASE_INDEX_MAP = {phase: i + 1 for i, phase in enumerate(PHASES)}

MIN_TIME_BUDGET_MINUTES = 0.1
MAX_TIME_BUDGET_MINUTES = 7 * 24 * 60
FORCE_UNLOCK_ENV = "FABLE_FORCE_UNLOCK_TOKEN"
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _validate_time_budget(value: Any, field_name: str = "time_budget_minutes") -> float:
    """Validate a duration before it can influence an execution deadline."""
    try:
        minutes = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}: expected a finite number of minutes.") from exc
    if not math.isfinite(minutes) or not (MIN_TIME_BUDGET_MINUTES <= minutes <= MAX_TIME_BUDGET_MINUTES):
        raise ValueError(
            f"Invalid {field_name}: must be between {MIN_TIME_BUDGET_MINUTES} and "
            f"{MAX_TIME_BUDGET_MINUTES} finite minutes."
        )
    return minutes


def _validate_session_name(name: str) -> str:
    """Keep session persistence inside SESSIONS_DIR and make identifiers portable."""
    clean_name = (name or "").strip()
    if not SESSION_NAME_PATTERN.fullmatch(clean_name):
        raise ValueError(
            "Invalid session_name: use 1-128 letters, numbers, '.', '_' or '-' "
            "and do not include path separators."
        )
    return clean_name


class FableSession:
    """Represents an active Fable reasoning & pacing session."""

    def __init__(
        self,
        session_name: str,
        objective: str,
        time_budget_minutes: float,
        session_id: Optional[str] = None,
        start_time: Optional[float] = None,
        wall_clock: Optional[Any] = None,
        monotonic_clock: Optional[Any] = None
    ):
        self.session_name = _validate_session_name(session_name)
        self.objective = objective
        self._wall_clock = wall_clock or time.time
        self._monotonic_clock = monotonic_clock or time.monotonic
        self.start_time = start_time if start_time is not None else self._wall_clock()
        self.session_id = session_id or f"fable_{session_name}_{int(self.start_time)}"
        
        # The authority budget is immutable after session creation.  A separate
        # pacing timer may be shortened by the agent, but it can never grant
        # execution permission or move this outer deadline earlier.
        self.time_budget_minutes = _validate_time_budget(time_budget_minutes)
        self.time_budget_seconds = self.time_budget_minutes * 60.0
        self._authority_deadline_wall = self.start_time + self.time_budget_seconds
        self._authority_deadline_monotonic = self._monotonic_clock() + self.time_budget_seconds

        self.pacing_budget_minutes = self.time_budget_minutes
        self.pacing_budget_seconds = self.time_budget_seconds
        self._pacing_started_wall = self.start_time
        self._pacing_started_monotonic = self._authority_deadline_monotonic - self.time_budget_seconds
        self._pacing_deadline_wall = self._authority_deadline_wall
        self._pacing_deadline_monotonic = self._authority_deadline_monotonic
        
        self.active_phase = PHASES[0]
        self.execution_locked = True
        self.can_execute_code = False
        
        self.epistemic_ledger: List[Dict[str, Any]] = []
        self.invariants: List[Dict[str, Any]] = []
        self.refinement_cycles: List[Dict[str, Any]] = []
        self.phase_history: List[Dict[str, Any]] = [
            {
                "phase": self.active_phase,
                "entered_at": self.start_time,
                "summary": "Session initialized"
            }
        ]
        self.unlock_details: Optional[Dict[str, Any]] = None

    @property
    def pacing_deadline_time(self) -> float:
        """Wall-clock representation of the internal pacing deadline."""
        return self._pacing_deadline_wall

    @property
    def deadline_time(self) -> float:
        """Read-only wall-clock representation of the authority deadline."""
        return self._authority_deadline_wall

    def set_timer(self, time_budget_minutes: float) -> Dict[str, Any]:
        """Set an agent pacing timer without changing the authority deadline.

        This is deliberately a sub-timer: an agent may choose to pace itself
        for 20 minutes inside an 80-minute session, but expiry of this timer
        never unlocks execution. Only the immutable outer deadline can do that.
        """
        pacing_minutes = _validate_time_budget(time_budget_minutes)
        self.pacing_budget_minutes = pacing_minutes
        self.pacing_budget_seconds = pacing_minutes * 60.0
        now_wall = self._wall_clock()
        now_monotonic = self._monotonic_clock()
        self._pacing_started_wall = now_wall
        self._pacing_started_monotonic = now_monotonic
        self._pacing_deadline_wall = min(
            self.deadline_time,
            now_wall + self.pacing_budget_seconds
        )
        self._pacing_deadline_monotonic = min(
            self._authority_deadline_monotonic,
            now_monotonic + self.pacing_budget_seconds
        )
        return self.get_telemetry()

    def _authority_remaining_seconds(self) -> float:
        """Use monotonic time while the process is alive to resist clock rollback."""
        return self._authority_deadline_monotonic - self._monotonic_clock()

    def _pacing_remaining_seconds(self) -> float:
        return self._pacing_deadline_monotonic - self._monotonic_clock()

    def _gate_report(self) -> Dict[str, Any]:
        """Return auditable gate state instead of relying on raw item counts."""
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN"]
        proven_with_evidence = [i for i in proven_items if str(i.get("evidence", "")).strip()]
        invariants_with_proof = [
            inv for inv in self.invariants if str(inv.get("proof_or_rationale", "")).strip()
        ]
        phase_index = PHASE_INDEX_MAP.get(self.active_phase, 1)
        checks = {
            "two_proven_evidence_items": len(proven_with_evidence) >= 2,
            "one_proved_invariant": len(invariants_with_proof) >= 1,
            "adversarial_phase_reached": phase_index >= 3,
        }
        return {
            "ready": all(checks.values()),
            "checks": checks,
            "proven_with_evidence": len(proven_with_evidence),
            "invariants_with_proof": len(invariants_with_proof),
        }

    def get_telemetry(self) -> Dict[str, Any]:
        """Calculates runtime authority, pacing, and cognitive-gate telemetry."""
        now = self._wall_clock()
        now_monotonic = self._monotonic_clock()
        elapsed_seconds = max(0.0, now - self.start_time)
        pacing_elapsed_seconds = max(0.0, now_monotonic - self._pacing_started_monotonic)
        authority_remaining = self._authority_remaining_seconds()
        pacing_remaining = self._pacing_remaining_seconds()
        pacing_ratio = pacing_elapsed_seconds / self.pacing_budget_seconds

        proven_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "PROVEN")
        hypothesis_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "HYPOTHESIS")
        unknown_count = sum(1 for item in self.epistemic_ledger if item.get("tag") == "UNKNOWN")

        return {
            "session_name": self.session_name,
            "session_id": self.session_id,
            "objective": self.objective,
            "start_time": self.start_time,
            "time_budget_minutes": self.time_budget_minutes,
            "time_budget_seconds": self.time_budget_seconds,
            "deadline_time": self.deadline_time,
            "authority_deadline_time": self.deadline_time,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "remaining_seconds": round(authority_remaining, 2),
            "elapsed_formatted": self._format_duration(elapsed_seconds),
            "remaining_formatted": self._format_duration(max(0.0, authority_remaining)),
            "authority_remaining_seconds": round(authority_remaining, 2),
            "authority_remaining_formatted": self._format_duration(max(0.0, authority_remaining)),
            "pacing_budget_minutes": self.pacing_budget_minutes,
            "pacing_started_time": self._pacing_started_wall,
            "pacing_deadline_time": self._pacing_deadline_wall,
            "pacing_remaining_seconds": round(pacing_remaining, 2),
            "pacing_remaining_formatted": self._format_duration(max(0.0, pacing_remaining)),
            "pacing_ratio": round(pacing_ratio, 4),
            "pacing_percentage": f"{pacing_ratio * 100.0:.1f}%",
            "active_phase": self.active_phase,
            "phase_index": PHASE_INDEX_MAP.get(self.active_phase, 1),
            "total_phases": len(PHASES),
            "execution_locked": self.execution_locked,
            "can_execute_code": self.can_execute_code,
            "epistemic_counts": {
                "proven": proven_count,
                "hypothesis": hypothesis_count,
                "unknown": unknown_count,
                "total": len(self.epistemic_ledger)
            },
            "invariants_count": len(self.invariants),
            "refinement_count": len(self.refinement_cycles),
            "refinement_cycles": self.refinement_cycles,
            "cognitive_gates": self._gate_report(),
            "unlock_details": self.unlock_details
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        sec = int(abs(seconds))
        hours = sec // 3600
        mins = (sec % 3600) // 60
        s = sec % 60
        if hours > 0:
            return f"{hours}h {mins}m {s}s"
        elif mins > 0:
            return f"{mins}m {s}s"
        else:
            return f"{s}s"

    def advance_phase(self, next_phase: str, phase_summary: str) -> Dict[str, Any]:
        """Advances the session to the requested phase and records history."""
        matched_phase = None
        for p in PHASES:
            if next_phase.strip().lower() == p.lower() or next_phase.strip().lower() in p.lower():
                matched_phase = p
                break

        if not matched_phase:
            valid_list = "\n".join([f"- {p}" for p in PHASES])
            raise ValueError(
                f"Invalid phase '{next_phase}'. Must be one of:\n{valid_list}"
            )

        current_phase_idx = PHASE_INDEX_MAP.get(self.active_phase, 1)
        target_phase_idx = PHASE_INDEX_MAP[matched_phase]
        if target_phase_idx != current_phase_idx + 1:
            raise ValueError(
                f"Invalid phase transition: move one phase at a time from "
                f"Phase {current_phase_idx} to Phase {current_phase_idx + 1}."
            )

        now = self._wall_clock()
        self.active_phase = matched_phase
        self.phase_history.append({
            "phase": matched_phase,
            "entered_at": now,
            "summary": phase_summary
        })
        return self.get_telemetry()

    def log_epistemic_item(self, tag: str, claim: str, evidence: Optional[str] = None) -> Dict[str, Any]:
        """Logs an epistemic fact/hypothesis/unknown with structured tracking."""
        tag_upper = tag.strip().upper()
        if tag_upper not in ("PROVEN", "HYPOTHESIS", "UNKNOWN"):
            raise ValueError(f"Invalid epistemic tag '{tag}'. Must be 'PROVEN', 'HYPOTHESIS', or 'UNKNOWN'.")

        if not claim or not claim.strip():
            raise ValueError("Claim description cannot be empty.")
        if tag_upper == "PROVEN" and not str(evidence or "").strip():
            raise ValueError("PROVEN claims require concrete evidence (file, command output, test, or URL).")

        item_id = f"epi_{len(self.epistemic_ledger) + 1:03d}"
        item = {
            "id": item_id,
            "tag": tag_upper,
            "claim": claim.strip(),
            "evidence": (evidence or "").strip(),
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.epistemic_ledger.append(item)
        return item

    def record_invariant(
        self,
        invariant_name: str,
        formal_statement: str,
        proof_or_rationale: str,
        domain: str = "architecture"
    ) -> Dict[str, Any]:
        """Records a domain invariant with formal statement and proof."""
        dom_clean = domain.strip().lower()
        if dom_clean not in ("architecture", "design", "coding"):
            dom_clean = "architecture"

        if not invariant_name or not invariant_name.strip():
            raise ValueError("Invariant name cannot be empty.")
        if not formal_statement or not formal_statement.strip():
            raise ValueError("Formal statement cannot be empty.")
        if not proof_or_rationale or not proof_or_rationale.strip():
            raise ValueError("Invariant proof or rationale cannot be empty.")

        inv_id = f"inv_{len(self.invariants) + 1:03d}"
        inv = {
            "id": inv_id,
            "name": invariant_name.strip(),
            "domain": dom_clean,
            "formal_statement": formal_statement.strip(),
            "proof_or_rationale": (proof_or_rationale or "").strip(),
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.invariants.append(inv)
        return inv

    def log_refinement_cycle(
        self,
        refinement_type: str,
        focus_area: str,
        critique_or_bottleneck: str,
        architectural_refinement: str,
        terminal_probe_results: Optional[str] = None,
        artifact_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Logs a structured rethink-refine cycle to continuously deepen cognitive quality."""
        if not refinement_type or not str(refinement_type).strip():
            raise ValueError("Refinement type cannot be empty.")
        if not focus_area or not str(focus_area).strip():
            raise ValueError("Focus area cannot be empty.")
        if not critique_or_bottleneck or not str(critique_or_bottleneck).strip():
            raise ValueError("Critique or bottleneck cannot be empty.")
        if not architectural_refinement or not str(architectural_refinement).strip():
            raise ValueError("Architectural refinement cannot be empty.")

        cycle_num = len(self.refinement_cycles) + 1
        entry = {
            "cycle_number": cycle_num,
            "refinement_type": str(refinement_type).strip(),
            "focus_area": str(focus_area).strip(),
            "critique_or_bottleneck": str(critique_or_bottleneck).strip(),
            "architectural_refinement": str(architectural_refinement).strip(),
            "terminal_probe_results": (terminal_probe_results or "").strip() if terminal_probe_results else None,
            "artifact_path": (artifact_path or "").strip() if artifact_path else None,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        self.refinement_cycles.append(entry)
        return entry

    @staticmethod
    def _force_override_authorized(token: Optional[str]) -> bool:
        """Allow emergency override only through an out-of-band secret.

        The old implementation accepted a public hard-coded string, which
        allowed any model with tool access to self-authorize an early unlock.
        """
        configured = os.environ.get(FORCE_UNLOCK_ENV)
        if not configured or not token:
            return False
        try:
            return hmac.compare_digest(str(token), configured)
        except TypeError:
            return False

    def unlock_execution(self, rationale: str, force_override_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Anti-Rush Lockout & Hard Time-Lock Validator:
        Ensures cognitive rigor and pacing compliance before code execution is permitted:
        1. Immutable authority deadline has elapsed. An internal pacing timer is never sufficient.
        2. At least 2 evidence-backed PROVEN items are recorded.
        3. At least 1 formal invariant includes a proof or rationale.
        4. Active phase is at least Phase 3 (Phase 3, 4, 5, or 6).

        Emergency overrides are intentionally not exposed through the MCP
        tool schema. A host application may configure an out-of-band secret
        for direct administrative use, but the model cannot self-authorize it.
        """
        now = self._wall_clock()
        force_override_used = self._force_override_authorized(force_override_token)
        remaining_sec = self._authority_remaining_seconds()
        if remaining_sec > 0 and not force_override_used:
            rem_formatted = self._format_duration(remaining_sec)
            raise PermissionError(
                f"🛑 HARD TIME-LOCK VIOLATION: Execution unlock rejected! The immutable "
                f"{self.time_budget_minutes}m authority budget has not elapsed yet "
                f"(Remaining: {rem_formatted} / {remaining_sec:.1f}s). An internal pacing "
                f"timer cannot unlock execution. Continue the Rethink-Refine Cognitive Loop."
            )

        gate_report = self._gate_report()
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN"]
        errors: List[str] = []
        if not gate_report["checks"]["two_proven_evidence_items"]:
            errors.append(
                f"Requires at least 2 [PROVEN] items with evidence "
                f"(currently {gate_report['proven_with_evidence']})."
            )
        if not gate_report["checks"]["one_proved_invariant"]:
            errors.append("Requires at least 1 formal Invariant with a proof or rationale.")
        if not gate_report["checks"]["adversarial_phase_reached"]:
            errors.append(
                f"Requires phase progression to at least Phase 3: Adversarial Red-Teaming & Falsification "
                f"(currently in {self.active_phase})."
            )

        if errors:
            reasons = "\n".join([f"  - {e}" for e in errors])
            raise PermissionError(
                f"🛑 Anti-Rush Lockout Active! Execution unlock denied due to missing cognitive gates:\n{reasons}\n\n"
                f"Please log required proven facts, formal invariants, and advance to Phase 3+ before unlocking."
            )

        self.execution_locked = False
        self.can_execute_code = True
        self.unlock_details = {
            "unlocked_at": now,
            "rationale": rationale.strip(),
            "proven_count": len(proven_items),
            "invariants_count": len(self.invariants),
            "refinement_cycles_count": len(self.refinement_cycles),
            "phase": self.active_phase,
            "force_override_used": force_override_used,
            "authority_deadline_elapsed": remaining_sec <= 0
        }

        return {
            "status": "UNLOCKED",
            "execution_locked": False,
            "can_execute_code": True,
            "unlock_details": self.unlock_details
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializes session to dictionary."""
        return {
            "version": "1.1.0",
            "session_name": self.session_name,
            "session_id": self.session_id,
            "objective": self.objective,
            "start_time": self.start_time,
            "time_budget_minutes": self.time_budget_minutes,
            "time_budget_seconds": self.time_budget_seconds,
            "authority_deadline_time": self.deadline_time,
            "deadline_time": self.deadline_time,
            "pacing_budget_minutes": self.pacing_budget_minutes,
            "pacing_budget_seconds": self.pacing_budget_seconds,
            "pacing_started_time": self._pacing_started_wall,
            "pacing_deadline_time": self._pacing_deadline_wall,
            "active_phase": self.active_phase,
            "execution_locked": self.execution_locked,
            "can_execute_code": self.can_execute_code,
            "epistemic_ledger": self.epistemic_ledger,
            "invariants": self.invariants,
            "refinement_cycles": self.refinement_cycles,
            "phase_history": self.phase_history,
            "unlock_details": self.unlock_details
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FableSession":
        """Deserializes session from dictionary."""
        session = cls(
            session_name=data["session_name"],
            objective=data.get("objective", ""),
            time_budget_minutes=data.get("time_budget_minutes", 60.0),
            session_id=data.get("session_id"),
            start_time=data.get("start_time")
        )
        session.time_budget_seconds = session.time_budget_minutes * 60.0
        session._authority_deadline_wall = float(data.get(
            "authority_deadline_time",
            data.get("deadline_time", session.start_time + session.time_budget_seconds)
        ))
        now_wall = session._wall_clock()
        now_monotonic = session._monotonic_clock()
        session._authority_deadline_monotonic = now_monotonic + max(
            0.0, session._authority_deadline_wall - now_wall
        )
        pacing_minutes = data.get("pacing_budget_minutes", session.time_budget_minutes)
        session.pacing_budget_minutes = _validate_time_budget(pacing_minutes, "pacing_budget_minutes")
        session.pacing_budget_seconds = session.pacing_budget_minutes * 60.0
        session._pacing_started_wall = float(data.get("pacing_started_time", session.start_time))
        session._pacing_started_monotonic = now_monotonic - max(0.0, now_wall - session._pacing_started_wall)
        session._pacing_deadline_wall = min(
            float(data.get("pacing_deadline_time", session.start_time + session.pacing_budget_seconds)),
            session.deadline_time
        )
        session._pacing_deadline_monotonic = now_monotonic + max(
            0.0, session._pacing_deadline_wall - now_wall
        )
        session.active_phase = data.get("active_phase", PHASES[0])
        session.execution_locked = data.get("execution_locked", True)
        session.can_execute_code = data.get("can_execute_code", False)
        session.epistemic_ledger = data.get("epistemic_ledger", [])
        session.invariants = data.get("invariants", [])
        session.refinement_cycles = data.get("refinement_cycles", [])
        session.phase_history = data.get("phase_history", [])
        session.unlock_details = data.get("unlock_details")
        return session

    def save(self, target_path: Optional[Path] = None) -> Path:
        """Atomically saves session to JSON file."""
        path = target_path or (SESSIONS_DIR / f"{self.session_name}.json")
        temp_path = path.with_suffix(".tmp")
        
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        
        for attempt in range(5):
            try:
                temp_path.replace(path)
                break
            except OSError:
                if attempt == 4:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(self.to_dict(), f, indent=2)
                    try:
                        if temp_path.exists():
                            temp_path.unlink()
                    except Exception:
                        pass
                else:
                    time.sleep(0.02 * (attempt + 1))
        logger.info(f"Fable session '{self.session_name}' saved to {path}")
        return path


# In-Memory Active Sessions Table
ACTIVE_SESSIONS: Dict[str, FableSession] = {}


def get_or_load_session(session_name: str) -> FableSession:
    """Retrieves session from memory or loads from disk if exists."""
    clean_name = _validate_session_name(session_name)
    if clean_name in ACTIVE_SESSIONS:
        return ACTIVE_SESSIONS[clean_name]

    file_path = SESSIONS_DIR / f"{clean_name}.json"
    if file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = FableSession.from_dict(data)
            ACTIVE_SESSIONS[clean_name] = session
            return session
        except Exception as e:
            logger.error(f"Failed to load session file {file_path}: {e}")
            raise RuntimeError(f"Corrupt or unreadable session file for '{clean_name}': {e}")

    raise ValueError(f"Session '{clean_name}' does not exist. Call 'create_session' first.")


def handle_fable_session(arguments: Dict[str, Any]) -> str:
    """Main dispatch handler for fable_session tool actions."""
    try:
        action = arguments.get("action", "").strip().lower()
        session_name = arguments.get("session_name", "").strip()

        if not action:
            return "Error: Missing required parameter 'action'."

        # 1. CREATE SESSION
        if action in ("create_session", "init", "create"):
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
            )

        # 2. SET TIMER
        elif action in ("set_timer", "update_timer", "timer"):
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
            )

        # 3. GET STATUS / TELEMETRY
        elif action in ("get_status", "telemetry", "status"):
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
                f"#### 🔍 Recent Epistemic Ledger Items:\n{ledger_preview}\n\n"
                f"#### 📐 Invariants Specification:\n{inv_preview}\n\n"
                f"#### 🔄 Recent Refinement Cycles:\n{ref_preview}"
            )

        # 4. ADVANCE PHASE
        elif action in ("advance_phase", "next_phase", "advance"):
            if not session_name:
                return "Error: 'session_name' is required for action 'advance_phase'."
            next_phase = arguments.get("next_phase", "").strip()
            if not next_phase:
                return "Error: 'next_phase' is required for action 'advance_phase'."
            phase_summary = arguments.get("phase_summary", "").strip() or "Advanced phase transition."

            session = get_or_load_session(session_name)
            tel = session.advance_phase(next_phase, phase_summary)
            session.save()

            return (
                f"### 🚀 Fable Phase Advanced Successfully\n\n"
                f"- **Session**: `{session.session_name}`\n"
                f"- **New Active Phase**: `{session.active_phase}` (Phase {tel['phase_index']}/{tel['total_phases']})\n"
                f"- **Phase Summary**: {phase_summary}\n"
                f"- **Execution Status**: `{'LOCKED 🛑' if session.execution_locked else 'UNLOCKED 🟢'}`\n"
                f"- **Pacing Remaining**: `{tel['pacing_remaining_formatted']}` (`{tel['pacing_percentage']}` used)\n"
                f"- **Authority Remaining**: `{tel['authority_remaining_formatted']}`"
            )

        # 5. LOG EPISTEMIC ITEM
        elif action in ("log_epistemic_item", "log_item", "epistemic_log"):
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
            )

        # 6. RECORD INVARIANT
        elif action in ("record_invariant", "add_invariant", "invariant"):
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
            )

        # 7. LOG REFINEMENT CYCLE
        elif action in ("log_refinement_cycle", "record_refinement", "refine"):
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
            )

        # 8. UNLOCK EXECUTION
        elif action in ("unlock_execution", "unlock"):
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

        # 9. CHECKPOINT SESSION
        elif action in ("checkpoint_session", "save_session", "checkpoint", "save"):
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

        # 10. RESTORE SESSION
        elif action in ("restore_session", "load_session", "restore", "load"):
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
            )

        # 11. LIST SESSIONS
        elif action in ("list_sessions", "list"):
            files = list(SESSIONS_DIR.glob("*.json"))
            session_entries = []
            for f in files:
                try:
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

        else:
            return (
                f"Error: Unknown action '{action}'. Supported actions: "
                f"'create_session', 'set_timer', 'get_status', 'telemetry', 'advance_phase', "
                f"'log_epistemic_item', 'record_invariant', 'log_refinement_cycle', 'unlock_execution', "
                f"'checkpoint_session', 'restore_session', 'list_sessions'."
            )
    except Exception as ex:
        return f"Error: {str(ex)}"


# --------------------------------------------------------------------------------
# JSON-RPC 2.0 MCP Protocol Stdio Loop
# --------------------------------------------------------------------------------

TOOL_SCHEMA = {
    "name": "fable_session",
    "description": (
        "Fable Cognitive Engine Session & Telemetry Manager for MCP-compatible agent hosts.\n"
        "Enforces DeepThink cognitive rigor, hard mechanical time-lock, anti-rush execution lockout, epistemic truth logging (PROVEN/HYPOTHESIS/UNKNOWN),\n"
        "formal domain invariant modeling, continuous rethink-refine cycles, phased progression gating, and live user-controlled time-budgeted pacing telemetry."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_session",
                    "set_timer",
                    "get_status",
                    "telemetry",
                    "advance_phase",
                    "log_epistemic_item",
                    "record_invariant",
                    "log_refinement_cycle",
                    "unlock_execution",
                    "checkpoint_session",
                    "restore_session",
                    "list_sessions"
                ],
                "description": "The Fable session action to perform."
            },
            "session_name": {
                "type": "string",
                "description": "Unique identifier / name for the Fable session."
            },
            "objective": {
                "type": "string",
                "description": "High-level goal or problem statement for the reasoning session."
            },
            "time_budget_minutes": {
                "type": "number",
                "description": "Immutable outer authority budget in minutes. set_timer can only change the internal pacing timer."
            },
            "next_phase": {
                "type": "string",
                "enum": PHASES,
                "description": "Target phase to advance the session into."
            },
            "phase_summary": {
                "type": "string",
                "description": "Concise summary of findings or deliverables completed in the previous phase."
            },
            "tag": {
                "type": "string",
                "enum": ["PROVEN", "HYPOTHESIS", "UNKNOWN"],
                "description": "Epistemic classification tag for truth calibration."
            },
            "claim": {
                "type": "string",
                "description": "Fact, hypothesis statement, or unknown parameter to track in epistemic ledger."
            },
            "evidence": {
                "type": "string",
                "description": "Source file, command output, line number, or URL supporting the claim."
            },
            "invariant_name": {
                "type": "string",
                "description": "Identifier or title of the formal invariant (e.g., 'INV-01: Zero-Deadlock Ring Buffer')."
            },
            "formal_statement": {
                "type": "string",
                "description": "Mathematical or formal contract specification that must never be violated."
            },
            "proof_or_rationale": {
                "type": "string",
                "description": "Proof sketch, rationale, or inductive argument establishing the invariant."
            },
            "domain": {
                "type": "string",
                "enum": ["architecture", "design", "coding"],
                "description": "Domain boundary for the invariant."
            },
            "refinement_type": {
                "type": "string",
                "description": "Type of rethink-refine cycle (e.g. 'archetype_exploration', 'triz_resolution', 'adversarial_falsification', 'benchmark_probe', 'failure_mode_analysis')."
            },
            "focus_area": {
                "type": "string",
                "description": "Specific subsystem, component, algorithm, or interface being critically re-evaluated."
            },
            "critique_or_bottleneck": {
                "type": "string",
                "description": "Critical flaw, vulnerability, edge case, memory/latency bottleneck, or assumption scrutinized."
            },
            "architectural_refinement": {
                "type": "string",
                "description": "Concrete architectural evolution, optimization, or algorithm change derived from the critique."
            },
            "terminal_probe_results": {
                "type": "string",
                "description": "Live empirical probe output, benchmark figures, latency numbers, or profiling stats supporting the refinement."
            },
            "artifact_path": {
                "type": "string",
                "description": "Absolute filesystem path to blueprint artifact, proof, or benchmark script documenting the refinement."
            },
            "rationale": {
                "type": "string",
                "description": "Justification for unlocking code execution after satisfying cognitive gates."
            },
        },
        "required": ["action"]
    }
}


def send_response(response_dict: Dict[str, Any]):
    """Writes a JSON-RPC response to stdout followed by newline and flushes."""
    encoded = json.dumps(response_dict)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def main():
    logger.info("Starting Fable-Engine MCP Server on stdio...")
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception as e:
            logger.error(f"Failed to parse incoming JSON line: {e}")
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "fable-engine",
                        "version": "1.1.0"
                    }
                }
            })

        elif method == "notifications/initialized":
            logger.info("Fable client handshake complete.")

        elif method == "ping":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {}
            })

        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [TOOL_SCHEMA]
                }
            })

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name == "fable_session":
                try:
                    result_text = handle_fable_session(arguments)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result_text
                                }
                            ],
                            "isError": False
                        }
                    })
                except Exception as ex:
                    logger.error(f"Error handling fable_session: {ex}", exc_info=True)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Fable Engine Error: {str(ex)}"
                                }
                            ],
                            "isError": True
                        }
                    })
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method / Tool '{tool_name}' not found."
                    }
                })

        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unrecognized JSON-RPC method: {method}"
                    }
                })


if __name__ == "__main__":
    main()

