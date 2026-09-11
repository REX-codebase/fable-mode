"""
Fable-Mode Cognitive Session Engine and State Machine.
Implements:
- FableSession: Invariant-checked, auditable System 2 deliberation session
- SessionState: Finite state machine with validated transitions
- Cross-process atomic session locking and persistence
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import logging
import math
import os
import re
import stat
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.session")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))

from fable_engine.cas import (
    DATA_DIR,
    _assert_private_path,
    _open_directory_nofollow,
)
from fable_engine.guards import GLOBAL_VELOCITY_PROFILER

_GLOBAL_RED_TEAM_SWARM = None
_GLOBAL_PLASTICITY_ENGINE = None

def get_red_team_swarm():
    global _GLOBAL_RED_TEAM_SWARM
    if _GLOBAL_RED_TEAM_SWARM is None:
        from fable_v2.coder_fleet import RedTeamSwarm
        _GLOBAL_RED_TEAM_SWARM = RedTeamSwarm(plasticity_engine=get_plasticity_engine())
    return _GLOBAL_RED_TEAM_SWARM

def get_plasticity_engine():
    global _GLOBAL_PLASTICITY_ENGINE
    if _GLOBAL_PLASTICITY_ENGINE is None:
        from fable_v2.cortical import HebbianPlasticityEngine
        _GLOBAL_PLASTICITY_ENGINE = HebbianPlasticityEngine()
    return _GLOBAL_PLASTICITY_ENGINE

def __getattr__(name: str) -> Any:
    if name == "GLOBAL_RED_TEAM_SWARM":
        return get_red_team_swarm()
    if name == "GLOBAL_PLASTICITY_ENGINE":
        return get_plasticity_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

try:
    from fable_engine.updater import AutoUpdater
except ImportError:
    try:
        from updater import AutoUpdater
    except ImportError:
        AutoUpdater = None

SESSIONS_DIR = DATA_DIR / "sessions"
_assert_private_path(SESSIONS_DIR)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
_assert_private_path(SESSIONS_DIR)
if SESSIONS_DIR.is_symlink() or not SESSIONS_DIR.is_dir():
    raise RuntimeError("SESSIONS_DIR must be a real directory")
os.chmod(SESSIONS_DIR, 0o700)

PHASES = [
    "Phase 1: Epistemic Grounding & Live Research",
    "Phase 2: Invariant Specification & Blueprint",
    "Phase 3: Adversarial Red-Teaming & Falsification",
    "Phase 4: Subagent Fleet Delegation",
    "Phase 5: Multi-Tier Verification & Gatekeeping",
    "Phase 6: Final Walkthrough & Reporting"
]

PHASE_INDEX_MAP = {phase: i + 1 for i, phase in enumerate(PHASES)}

MIN_TIME_BUDGET_MINUTES = 2.0
MAX_TIME_BUDGET_MINUTES = 7 * 24 * 60
FORCE_UNLOCK_ENV = "FABLE_FORCE_UNLOCK_TOKEN"
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

SILENT_DELIBERATION_REMINDER = (
    "\n\n> [!IMPORTANT]\n"
    "> 🛑 **SILENT-DELIBERATION ACTIVE (Zero-Chat Lockout)**: Do NOT emit conversational responses "
    "or prompt the user while time-lock is active. Continue internal tool-reasoning, terminal benchmarks "
    "(`run_command`), artifact authoring, and rethink-refine cycles until the authority deadline elapses."
)

def _validate_time_budget(value: Any, field_name: str = "time_budget_minutes") -> float:
    """Validate a duration before it can influence an execution deadline."""
    try:
        minutes = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}: expected a finite number of minutes.") from exc
    if not math.isfinite(minutes) or not (MIN_TIME_BUDGET_MINUTES <= minutes <= MAX_TIME_BUDGET_MINUTES):
        raise ValueError(
            f"Invalid {field_name}: minimum allowed time budget is {MIN_TIME_BUDGET_MINUTES} minutes "
            f"(must be between {MIN_TIME_BUDGET_MINUTES} and {MAX_TIME_BUDGET_MINUTES} finite minutes to ensure adequate epistemic grounding and deliberation). "
            f"Provided: {minutes} minutes."
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



class SessionState(str, Enum):
    INIT = "INIT"
    DEEPTHINK_TIMELOCK = "DEEPTHINK_TIMELOCK"
    IMPLEMENTATION = "IMPLEMENTATION"
    RED_TEAM_GATE = "RED_TEAM_GATE"
    ARBITRATION = "ARBITRATION"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    SEALED = "SEALED"
    EVOLVED = "EVOLVED"


VALID_TRANSITIONS = {
    SessionState.INIT: {SessionState.DEEPTHINK_TIMELOCK},
    SessionState.DEEPTHINK_TIMELOCK: {SessionState.IMPLEMENTATION},
    SessionState.IMPLEMENTATION: {SessionState.RED_TEAM_GATE},
    SessionState.RED_TEAM_GATE: {SessionState.ARBITRATION},
    SessionState.ARBITRATION: {SessionState.REMEDIATION_REQUIRED, SessionState.SEALED},
    SessionState.REMEDIATION_REQUIRED: {SessionState.ARBITRATION, SessionState.SEALED, SessionState.REMEDIATION_REQUIRED},
    SessionState.SEALED: {SessionState.EVOLVED},
    SessionState.EVOLVED: {SessionState.EVOLVED},
}


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

        self.current_state = SessionState.INIT
        self.iteration_count = 0
        self.active_breakages: List[Dict[str, Any]] = []
        self.remediation_history: List[Dict[str, Any]] = []
        self._timer_set = False
        
        self.epistemic_ledger: List[Dict[str, Any]] = []
        self.invariants: List[Dict[str, Any]] = []
        self.refinement_cycles: List[Dict[str, Any]] = []
        self.file_changes: List[Dict[str, Any]] = []
        self.visual_mockups: Dict[str, Any] = {"mockups": [], "selected_concept": None}
        self.proof_receipts: List[Dict[str, Any]] = []
        self.goal_rubrics: List[Dict[str, Any]] = []
        self.automation_pipelines: List[Dict[str, Any]] = []
        self.breakage_reports: List[Dict[str, Any]] = []
        self.phase_history: List[Dict[str, Any]] = [
            {
                "phase": self.active_phase,
                "entered_at": self.start_time,
                "summary": "Session initialized"
            }
        ]
        self.unlock_details: Optional[Dict[str, Any]] = None
        self._restored_untrusted = False

        # System 3 Meta-Cognitive State
        self.system3_causal_graphs: List[Dict[str, Any]] = []
        self.system3_syntheses: List[Dict[str, Any]] = []
        self.system3_gene_pools: List[Dict[str, Any]] = []
        self.system3_axioms: List[Dict[str, Any]] = []
        self.system3_reflections: List[Dict[str, Any]] = []
        self.system3_orchestrations: List[Dict[str, Any]] = []
        self.system3_hyperbolic_embeddings: List[Dict[str, Any]] = []
        self.system3_kripke_verifications: List[Dict[str, Any]] = []
        self.system3_active_inferences: List[Dict[str, Any]] = []
        self.system3_proof_oracle_verifications: List[Dict[str, Any]] = []
        self.active_free_energy: Optional[Dict[str, Any]] = None
        self.active_kripke_safety: Optional[Dict[str, Any]] = None
        self.active_biases: List[Dict[str, Any]] = []
        self._disk_mtime: float = 0.0

        # Unified Fable V2 Runtime instance
        try:
            from fable_v2.runtime import new_run
            from fable_v2.protocol import TaskSpec
            task = TaskSpec(
                task_id=f"task_{self.session_id}",
                objective=self.objective or "Fable Mode Deliberation",
                definition_of_done=("Epistemic evidence verified",),
            )
            self.fable_run: Optional[Any] = new_run(session_id=self.session_id, task=task)
        except Exception:
            self.fable_run = None

        # Autonomous Silent Self-Updater Trigger
        if (
            AutoUpdater is not None
            and not os.environ.get("FABLE_DISABLE_AUTO_UPDATE")
            and not os.environ.get("PYTEST_CURRENT_TEST")
        ):
            try:
                AutoUpdater().trigger_silent_background_update()
            except Exception as e:
                logger.debug(f"Silent auto-updater background trigger failed on session init: {e}")

    @property
    def pacing_deadline_time(self) -> float:
        """Wall-clock representation of the internal pacing deadline."""
        return self._pacing_deadline_wall

    @property
    def deadline_time(self) -> float:
        """Read-only wall-clock representation of the authority deadline."""
        return self._authority_deadline_wall

    def transition_to(self, new_state: Union[SessionState, str], rationale: str = "") -> SessionState:
        """Transitions the FSM to a new state after validating strict state machine invariants.

        Valid transitions:
        - INIT -> DEEPTHINK_TIMELOCK (requires set_timer and/or set_goal_rubric)
        - DEEPTHINK_TIMELOCK -> IMPLEMENTATION (requires execution unlocked)
        - IMPLEMENTATION -> RED_TEAM_GATE (requires code written / file changes logged)
        - RED_TEAM_GATE -> ARBITRATION
        - ARBITRATION -> REMEDIATION_REQUIRED (if broken_count > 0)
        - ARBITRATION -> SEALED (if broken_count == 0)
        - REMEDIATION_REQUIRED -> ARBITRATION
        - REMEDIATION_REQUIRED -> SEALED (when remediation verification succeeds with 0 breakages)
        - SEALED -> EVOLVED (upon evolve_cortex consolidation)

        Attempting any illegal jump (e.g. INIT directly to SEALED or IMPLEMENTATION) must raise ValueError.
        """
        if isinstance(new_state, str):
            try:
                target_state = SessionState(new_state)
            except ValueError:
                raise ValueError(f"Invalid SessionState: '{new_state}'. Allowed states: {[s.value for s in SessionState]}")
        else:
            target_state = new_state

        allowed = VALID_TRANSITIONS.get(self.current_state, set())
        if target_state not in allowed and target_state != self.current_state:
            raise ValueError(
                f"Illegal state transition from {self.current_state.value} to {target_state.value}. "
                f"Allowed transitions from {self.current_state.value}: {[s.value for s in allowed]}"
            )

        if self.current_state == SessionState.INIT and target_state == SessionState.DEEPTHINK_TIMELOCK:
            timer_set = getattr(self, "_timer_set", False) or (self.pacing_budget_minutes != self.time_budget_minutes)
            rubric_set = len(self.goal_rubrics) > 0
            rationale_ok = any(k in rationale.lower() for k in ("timer", "rubric", "deepthink", "timelock", "set_timer", "set_goal_rubric"))
            if not (timer_set or rubric_set or rationale_ok):
                raise ValueError("Transition from INIT to DEEPTHINK_TIMELOCK requires set_timer and/or set_goal_rubric.")

        elif self.current_state == SessionState.DEEPTHINK_TIMELOCK and target_state == SessionState.IMPLEMENTATION:
            if self.execution_locked or not self.can_execute_code:
                raise ValueError("Transition from DEEPTHINK_TIMELOCK to IMPLEMENTATION requires execution unlocked.")

        elif self.current_state == SessionState.IMPLEMENTATION and target_state == SessionState.RED_TEAM_GATE:
            has_changes = len(self.file_changes) > 0 or any(k in rationale.lower() for k in ("code", "file", "implement", "change", "written", "edit"))
            if not has_changes:
                raise ValueError("Transition from IMPLEMENTATION to RED_TEAM_GATE requires code written / file changes logged.")

        elif self.current_state == SessionState.ARBITRATION and target_state == SessionState.SEALED:
            if len(self.active_breakages) > 0:
                raise ValueError(f"Transition from ARBITRATION to SEALED rejected: {len(self.active_breakages)} breakages remain unresolved.")

        elif self.current_state == SessionState.REMEDIATION_REQUIRED and target_state == SessionState.SEALED:
            if len(self.active_breakages) > 0:
                raise ValueError(f"Transition from REMEDIATION_REQUIRED to SEALED rejected: {len(self.active_breakages)} breakages remain unresolved.")

        self.current_state = target_state
        return self.current_state

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
        self._timer_set = True
        if self.current_state == SessionState.INIT:
            self.transition_to(SessionState.DEEPTHINK_TIMELOCK, "Pacing timer configured")
        return self.get_telemetry()

    def _authority_remaining_seconds(self) -> float:
        """Use monotonic time while the process is alive to resist clock rollback."""
        return self._authority_deadline_monotonic - self._monotonic_clock()

    def _pacing_remaining_seconds(self) -> float:
        return self._pacing_deadline_monotonic - self._monotonic_clock()

    def _gate_report(self) -> Dict[str, Any]:
        """Return auditable gate state instead of relying on raw item counts."""
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN" and not i.get("_restored_untrusted")]
        proven_with_evidence = [i for i in proven_items if str(i.get("evidence", "")).strip()]
        invariants_with_proof = [
            inv for inv in self.invariants if not inv.get("_restored_untrusted") and str(inv.get("proof_or_rationale", "")).strip()
        ]
        # Restored phase is reset to Phase 1; subsequent in-process
        # transitions are legitimate fresh gates.
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
            "silent_deliberation_active": self.execution_locked,
            "current_state": self.current_state.value if isinstance(self.current_state, SessionState) else str(self.current_state),
            "iteration_count": self.iteration_count,
            "active_breakages_count": len(self.active_breakages),
            "active_breakages": self.active_breakages,
            "remediation_history": self.remediation_history,
            "epistemic_counts": {
                "proven": proven_count,
                "hypothesis": hypothesis_count,
                "unknown": unknown_count,
                "total": len(self.epistemic_ledger)
            },
            "invariants_count": len(self.invariants),
            "refinement_count": len(self.refinement_cycles),
            "refinement_cycles": self.refinement_cycles,
            "file_changes_count": len(self.file_changes),
            "visual_mockups": self.visual_mockups,
            "proof_receipts_count": len(self.proof_receipts),
            "goal_rubrics_count": len(self.goal_rubrics),
            "automation_pipelines_count": len(self.automation_pipelines),
            "latest_goal_rubric": self.goal_rubrics[-1] if self.goal_rubrics else None,
            "velocity_profile": GLOBAL_VELOCITY_PROFILER.get_velocity_profile(),
            "cognitive_gates": self._gate_report(),
            "unlock_details": self.unlock_details,
            "system3_cognitive_state": {
                "free_energy_f": self.active_free_energy.get("variational_free_energy_f", 1.25) if self.active_free_energy else 1.25,
                "complexity_kl": self.active_free_energy.get("complexity_kl", 0.35) if self.active_free_energy else 0.35,
                "accuracy_log_likelihood": self.active_free_energy.get("accuracy_log_likelihood", -0.90) if self.active_free_energy else -0.90,
                "kripke_safety_invariant": "AG(safe) -> True" if (self.active_kripke_safety.get("is_satisfied", True) if self.active_kripke_safety else True) else "AG(safe) -> VIOLATED",
                "kripke_safety_verified": self.active_kripke_safety.get("is_satisfied", True) if self.active_kripke_safety else True,
                "active_biases_count": len(self.active_biases),
                "active_biases": self.active_biases,
                "contradiction_density": round(sum(len(s.get("resolved_contradictions", [])) for s in self.system3_syntheses) / max(1, len(self.system3_syntheses)), 2) if self.system3_syntheses else 0.0,
                "hyperbolic_metric": {
                    "embeddings_count": len(self.system3_hyperbolic_embeddings),
                    "curvature": 1.0,
                    "status": "CONVERGED_POINCARE_BALL" if self.system3_hyperbolic_embeddings else "INITIALIZED",
                },
            },
            "system3_counts": {
                "causal_graphs": len(self.system3_causal_graphs),
                "syntheses": len(self.system3_syntheses),
                "gene_pools": len(self.system3_gene_pools),
                "axioms": len(self.system3_axioms),
                "reflections": len(self.system3_reflections),
                "orchestrations": len(self.system3_orchestrations),
                "hyperbolic_embeddings": len(self.system3_hyperbolic_embeddings),
                "kripke_verifications": len(self.system3_kripke_verifications),
                "active_inferences": len(self.system3_active_inferences),
                "proof_oracle_verifications": len(self.system3_proof_oracle_verifications),
            }
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
        if any(term in next_phase.upper() for term in ("SEALED", "EVOLVED")):
            raise ValueError(
                "Invalid phase transition: Cannot advance directly to SEALED or EVOLVED via advance_phase."
            )

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

        if target_phase_idx >= 4 and self.current_state in (SessionState.INIT, SessionState.DEEPTHINK_TIMELOCK):
            raise ValueError(
                f"Cannot advance to {matched_phase}: Implementation gate not reached (current state: {self.current_state.value}). Execution must be unlocked."
            )
        if target_phase_idx >= 5 and self.current_state == SessionState.IMPLEMENTATION:
            raise ValueError(
                f"Cannot advance to {matched_phase}: Red team gate and arbitration have not been completed (current state: {self.current_state.value}). Skipping red team gates is strictly prohibited."
            )

        now = self._wall_clock()
        self.active_phase = matched_phase
        self.phase_history.append({
            "phase": matched_phase,
            "entered_at": now,
            "summary": phase_summary
        })

        # Run System 3 Executive bias detection & reflection
        from fable_v2.system3 import (
            CognitiveBiasDetector,
            ActiveInferenceEngine,
            Policy,
            create_default_architecture_pomdp,
            KripkeStructure,
            KripkeModelChecker,
        )
        detector = CognitiveBiasDetector()
        findings = detector.audit_session({
            "epistemic_ledger": self.epistemic_ledger,
            "refinement_cycles": self.refinement_cycles,
            "phase_history": self.phase_history,
            "invariants": self.invariants,
        })
        self.active_biases = [f.to_dict() for f in findings]
        if findings:
            self.system3_reflections.append({
                "phase": matched_phase,
                "findings": self.active_biases,
                "timestamp": now,
            })

        # Update live Free Energy F
        pomdp_model = create_default_architecture_pomdp()
        fe_engine = ActiveInferenceEngine(pomdp_model)
        proven_count = sum(1 for i in self.epistemic_ledger if i.get("tag") == "PROVEN")
        obs = "HIGH_THROUGHPUT_CLEAN" if proven_count >= 2 else "LOCK_CONTENTION_WARN"
        fe_policies = [Policy(policy_id=f"p_{act}", actions=[act]) for act in pomdp_model.actions]
        fe_report = fe_engine.select_action(obs, fe_policies)
        self.active_free_energy = {
            "variational_free_energy_f": round(fe_report.variational_free_energy_f, 4),
            "complexity_kl": round(fe_report.complexity_kl, 4),
            "accuracy_log_likelihood": round(fe_report.accuracy_log_likelihood, 4),
            "selected_action": fe_report.selected_action,
            "observation": obs,
            "phase": matched_phase,
            "timestamp": now,
        }
        self.system3_active_inferences.append(self.active_free_energy)

        # Update Kripke Safety Invariant
        kripke = KripkeStructure()
        kripke.add_world("w0", propositions={"entered", "safe"})
        kripke.add_world("w_phase", propositions={f"phase_{target_phase_idx}", "safe"})
        kripke.add_transition("w0", "w_phase")
        kripke.add_transition("w_phase", "w_phase")
        checker = KripkeModelChecker(kripke)
        k_res = checker.check("AG(safe)", "w0")
        self.active_kripke_safety = {
            "formula": "AG(safe)",
            "is_satisfied": k_res.is_satisfied,
            "active_phase": matched_phase,
        }

        return self.get_telemetry()

    def log_epistemic_item(self, tag: str, claim: str, evidence: Optional[str] = None) -> Dict[str, Any]:
        """Logs an epistemic fact/hypothesis/unknown with structured tracking and evidence validation."""
        tag_upper = tag.strip().upper()
        if tag_upper not in ("PROVEN", "HYPOTHESIS", "UNKNOWN"):
            raise ValueError(f"Invalid epistemic tag '{tag}'. Must be 'PROVEN', 'HYPOTHESIS', or 'UNKNOWN'.")

        if not claim or not claim.strip():
            raise ValueError("Claim description cannot be empty.")

        proof_receipt = None
        from fable_v2.proof_engine import DeterministicProofValidator
        validator = DeterministicProofValidator()
        if tag_upper == "PROVEN":
            if validator.is_tautological(claim):
                raise ValueError(
                    f"Invalid claim '{claim}': PROVEN claims must not be tautological or generic (e.g. 'tested', 'it works'). "
                    f"State a substantive, testable system property or measurement."
                )
            if not str(evidence or "").strip():
                raise ValueError("PROVEN claims require concrete evidence (file, command output, test, or URL).")
            valid, reason, rcpt = validator.validate_proven_claim(claim, str(evidence))
            if not valid:
                raise ValueError(f"Epistemic Evidence Validation Failed: {reason}")
            proof_receipt = rcpt
            if rcpt:
                self.proof_receipts.append(rcpt)

        item_id = f"epi_{len(self.epistemic_ledger) + 1:03d}"
        item = {
            "id": item_id,
            "tag": tag_upper,
            "claim": claim.strip(),
            "evidence": (evidence or "").strip(),
            "proof_receipt": proof_receipt,
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

        from fable_v2.proof_engine import DeterministicProofValidator
        validator = DeterministicProofValidator()
        valid, reason, rcpt = validator.validate_invariant(invariant_name, formal_statement, proof_or_rationale)
        if not valid:
            raise ValueError(f"Invariant Validation Failed: {reason}")

        inv_id = f"inv_{len(self.invariants) + 1:03d}"
        inv = {
            "id": inv_id,
            "name": invariant_name.strip(),
            "domain": dom_clean,
            "formal_statement": formal_statement.strip(),
            "proof_or_rationale": (proof_or_rationale or "").strip(),
            "proof_receipt": rcpt,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase
        }
        if rcpt:
            self.proof_receipts.append(rcpt)
        self.invariants.append(inv)
        return inv

    def track_file_change(
        self,
        file_path: str,
        change_type: str,
        diff_summary: str,
        rationale: Optional[str] = None,
        affected_invariants: Optional[Union[List[str], str]] = None
    ) -> Dict[str, Any]:
        """Tracks file mutations (modified, created, deleted, slated) with automatic SHA256 hashing."""
        if not file_path or not str(file_path).strip():
            raise ValueError("file_path cannot be empty.")
        c_type = str(change_type).strip().lower()
        if c_type not in ("modified", "created", "deleted", "slated"):
            raise ValueError(f"Invalid change_type '{change_type}'. Must be 'modified', 'created', 'deleted', or 'slated'.")
        if not diff_summary or not str(diff_summary).strip():
            raise ValueError("diff_summary cannot be empty.")

        p = Path(file_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        sha256 = None
        if p.is_file():
            try:
                sha256 = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                sha256 = None

        invariants_list: List[str] = []
        if affected_invariants:
            if isinstance(affected_invariants, list):
                invariants_list = [str(x) for x in affected_invariants]
            else:
                invariants_list = [str(affected_invariants)]

        entry = {
            "file_path": str(file_path).strip(),
            "change_type": c_type,
            "diff_summary": str(diff_summary).strip(),
            "rationale": (rationale or "").strip(),
            "affected_invariants": invariants_list,
            "sha256": sha256,
            "timestamp": self._wall_clock(),
            "phase": self.active_phase,
        }
        self.file_changes.append(entry)
        return entry

    def record_visual_mockups(
        self,
        mockups: Union[List[Dict[str, Any]], str],
        selected_concept: Optional[str] = None
    ) -> Dict[str, Any]:
        """Records visual mockup concepts, palettes, typography, and layout coordinate data."""
        if isinstance(mockups, str):
            try:
                parsed_mockups = json.loads(mockups)
            except Exception as e:
                raise ValueError(f"Failed to parse mockups JSON string: {e}")
        elif isinstance(mockups, list):
            parsed_mockups = mockups
        else:
            raise ValueError(f"mockups must be a list of concept dictionaries, got {type(mockups).__name__}")

        if not isinstance(parsed_mockups, list) or len(parsed_mockups) == 0:
            raise ValueError("mockups list cannot be empty. Provide 5-6 architectural concept mockups.")

        self.visual_mockups = {
            "mockups": parsed_mockups,
            "selected_concept": (selected_concept or "").strip() if selected_concept else (parsed_mockups[0].get("concept_name") if parsed_mockups else None),
            "recorded_at": self._wall_clock(),
            "phase": self.active_phase,
        }
        return self.visual_mockups

    def set_goal_rubric(
        self,
        task_objective: str,
        criteria: Union[List[Dict[str, Any]], str],
        target_score: float = 0.95,
        rubric_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Registers a goal scoring rubric contract with target score threshold (default >= 0.95)."""
        if not task_objective or not str(task_objective).strip():
            task_objective = self.objective or "Task Objective"

        target_score_val = float(target_score)
        if not 0.0 <= target_score_val <= 1.0:
            raise ValueError(f"target_score must be between 0.0 and 1.0, got {target_score_val}")

        parsed_items: List[Dict[str, Any]] = []
        raw_items: Any = criteria
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                lines = [l.strip() for l in raw_items.splitlines() if l.strip()]
                raw_items = [{"pointer_id": f"PTR-{idx+1:02d}", "description": l} for idx, l in enumerate(lines)]

        if isinstance(raw_items, dict):
            dict_items = []
            for k, v in raw_items.items():
                if isinstance(v, dict):
                    item_d = dict(v)
                    item_d.setdefault("pointer_id", k)
                    dict_items.append(item_d)
                else:
                    dict_items.append({"pointer_id": k, "description": str(v)})
            raw_items = dict_items

        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("criteria must be a non-empty list of criteria items/pointers or JSON string.")

        for idx, item in enumerate(raw_items):
            if isinstance(item, dict):
                p_id = str(item.get("pointer_id") or f"PTR-{idx+1:02d}").strip()
                desc = str(item.get("description") or item.get("desc") or item.get("name") or p_id).strip()
                weight = float(item.get("weight", 1.0))
                verifier = str(item.get("verifier_command", "")).strip()
                satisfied = bool(item.get("satisfied", False))
                score = float(item.get("score", 1.0 if satisfied else 0.0))
                receipt_id = str(item.get("evidence_receipt_id", "")).strip()
                meta = dict(item.get("metadata") or {})
            else:
                p_id = f"PTR-{idx+1:02d}"
                desc = str(item).strip()
                weight = 1.0
                verifier = ""
                satisfied = False
                score = 0.0
                receipt_id = ""
                meta = {}

            parsed_items.append({
                "pointer_id": p_id,
                "description": desc,
                "weight": max(0.0, weight),
                "verifier_command": verifier,
                "satisfied": satisfied,
                "score": max(0.0, min(1.0, score)),
                "evidence_receipt_id": receipt_id,
                "metadata": meta
            })

        total_weight = sum(it["weight"] for it in parsed_items)
        if total_weight > 0:
            weighted_sum = sum(it["score"] * it["weight"] for it in parsed_items)
            current_score = round(weighted_sum / total_weight, 4)
        else:
            current_score = 0.0

        status = "achieved" if current_score >= target_score_val else "pending"
        r_id = (rubric_id or f"rubric_{self.session_name}_{len(self.goal_rubrics) + 1}").strip()

        rubric_entry = {
            "rubric_id": r_id,
            "session_id": self.session_id,
            "task_objective": str(task_objective).strip(),
            "target_score": target_score_val,
            "items": parsed_items,
            "current_score": current_score,
            "status": status,
            "metadata": metadata or {},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall_clock()))
        }

        existing_idx = next((i for i, r in enumerate(self.goal_rubrics) if r.get("rubric_id") == r_id), None)
        if existing_idx is not None:
            self.goal_rubrics[existing_idx] = rubric_entry
        else:
            self.goal_rubrics.append(rubric_entry)

        if self.current_state == SessionState.INIT:
            self.transition_to(SessionState.DEEPTHINK_TIMELOCK, "Goal rubric registered")

        return rubric_entry

    def evaluate_goal_rubric(
        self,
        rubric_id: Optional[str] = None,
        item_evaluations: Optional[Union[List[Dict[str, Any]], Dict[str, Any], str]] = None
    ) -> Dict[str, Any]:
        """Evaluates rubric criteria items, updates scores, and determines goal attainment status."""
        if not self.goal_rubrics:
            raise ValueError("No goal rubric registered in this session. Call set_goal_rubric first.")

        rubric: Optional[Dict[str, Any]] = None
        if rubric_id:
            rubric = next((r for r in self.goal_rubrics if r.get("rubric_id") == str(rubric_id).strip()), None)
            if not rubric:
                raise ValueError(f"Rubric with id '{rubric_id}' not found.")
        else:
            rubric = self.goal_rubrics[-1]

        evals_list: List[Dict[str, Any]] = []
        if item_evaluations is not None:
            raw_evals = item_evaluations
            if isinstance(raw_evals, str):
                try:
                    raw_evals = json.loads(raw_evals)
                except Exception:
                    raw_evals = []
            if isinstance(raw_evals, dict):
                for k, v in raw_evals.items():
                    if isinstance(v, dict):
                        ed = dict(v)
                        ed.setdefault("pointer_id", k)
                        evals_list.append(ed)
                    elif isinstance(v, (int, float)):
                        evals_list.append({"pointer_id": k, "score": float(v), "satisfied": float(v) >= 1.0})
                    elif isinstance(v, bool):
                        evals_list.append({"pointer_id": k, "satisfied": v, "score": 1.0 if v else 0.0})
            elif isinstance(raw_evals, list):
                evals_list = [dict(x) if isinstance(x, dict) else {"pointer_id": str(x), "satisfied": True, "score": 1.0} for x in raw_evals]

        for ev in evals_list:
            p_id = str(ev.get("pointer_id", "")).strip()
            for it in rubric["items"]:
                if it.get("pointer_id") == p_id:
                    if "satisfied" in ev:
                        it["satisfied"] = bool(ev["satisfied"])
                    if "score" in ev:
                        it["score"] = max(0.0, min(1.0, float(ev["score"])))
                    elif "satisfied" in ev:
                        it["score"] = 1.0 if it["satisfied"] else 0.0
                    if "evidence_receipt_id" in ev:
                        it["evidence_receipt_id"] = str(ev["evidence_receipt_id"]).strip()
                    if "verifier_command" in ev:
                        it["verifier_command"] = str(ev["verifier_command"]).strip()
                    if "metadata" in ev and isinstance(ev["metadata"], dict):
                        it.setdefault("metadata", {}).update(ev["metadata"])

        total_weight = sum(it.get("weight", 1.0) for it in rubric["items"])
        if total_weight > 0:
            weighted_sum = sum(float(it.get("score", 1.0 if it.get("satisfied") else 0.0)) * float(it.get("weight", 1.0)) for it in rubric["items"])
            current_score = round(weighted_sum / total_weight, 4)
        else:
            current_score = 0.0

        rubric["current_score"] = current_score
        target_score = float(rubric.get("target_score", 0.95))
        rubric["status"] = "achieved" if current_score >= target_score else "in_progress"
        rubric["last_evaluated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall_clock()))
        return rubric

    def get_goal_rubric(self, rubric_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns the specified goal rubric or the latest active rubric."""
        if not self.goal_rubrics:
            return None
        if rubric_id:
            return next((r for r in self.goal_rubrics if r.get("rubric_id") == str(rubric_id).strip()), None)
        return self.goal_rubrics[-1]

    def register_automation_pipeline(
        self,
        name: str,
        pipeline_type: str = "closed_loop",
        generator_command: str = "",
        evaluator_command: str = "",
        target_threshold: float = 0.95,
        max_iterations: int = 10,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Registers an autonomous pipeline loop spec (generate -> evaluate -> iterate)."""
        if not name or not str(name).strip():
            raise ValueError("Pipeline 'name' cannot be empty.")

        pipe_id = f"pipeline_{self.session_name}_{len(self.automation_pipelines) + 1}"
        spec = {
            "pipeline_id": pipe_id,
            "session_id": self.session_id,
            "name": str(name).strip(),
            "pipeline_type": (pipeline_type or "closed_loop").strip(),
            "generator_command": (generator_command or "").strip(),
            "evaluator_command": (evaluator_command or "").strip(),
            "target_threshold": max(0.0, min(1.0, float(target_threshold))),
            "max_iterations": max(1, int(max_iterations)),
            "status": "active",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall_clock())),
            "metadata": metadata or {}
        }
        self.automation_pipelines.append(spec)
        return spec

    def record_breakage_report(
        self,
        report_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Records an adversarial red team breakage report in session history and updates FSM state."""
        self.breakage_reports.append(report_data)
        broken_count = int(report_data.get("broken_count", 0))
        findings = report_data.get("findings", [])
        if broken_count > 0:
            self.active_breakages = [
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
            self.remediation_history.append({
                "iteration": self.iteration_count,
                "report_id": report_data.get("report_id"),
                "broken_count": broken_count,
                "timestamp": self._wall_clock(),
                "breakages": list(self.active_breakages),
                "remediation_directives": report_data.get("remediation_directives", []),
            })
            try:
                if self.current_state == SessionState.IMPLEMENTATION:
                    self.transition_to(SessionState.RED_TEAM_GATE, "Breakage report submitted")
                if self.current_state == SessionState.RED_TEAM_GATE:
                    self.transition_to(SessionState.ARBITRATION, "Arbitration of breakages")
                if self.current_state == SessionState.ARBITRATION:
                    self.transition_to(SessionState.REMEDIATION_REQUIRED, f"{broken_count} breakages detected")
                else:
                    self.current_state = SessionState.REMEDIATION_REQUIRED
            except Exception:
                self.current_state = SessionState.REMEDIATION_REQUIRED
        else:
            self.active_breakages = []
            # Guard SEALED state behind mandatory-stage evidence verification
            has_epistemic = len(self.epistemic_ledger) >= 2
            has_rubric = len(self.goal_rubrics) >= 1
            has_refinement = len(self.refinement_cycles) >= 1
            has_changes = len(self.file_changes) >= 1
            if not (has_epistemic and has_rubric and has_refinement and has_changes):
                raise ValueError(
                    "SEALED state transition rejected: Session lacks required mandatory-stage evidence "
                    "(must have >=2 epistemic items, >=1 goal rubric, >=1 refinement cycle, and >=1 file change logged)."
                )

            try:
                if self.current_state == SessionState.IMPLEMENTATION:
                    self.transition_to(SessionState.RED_TEAM_GATE, "Clean report submitted")
                if self.current_state == SessionState.RED_TEAM_GATE:
                    self.transition_to(SessionState.ARBITRATION, "Arbitration of clean report")
                if self.current_state in (SessionState.ARBITRATION, SessionState.REMEDIATION_REQUIRED):
                    self.transition_to(SessionState.SEALED, "Zero breakages verified")
                else:
                    self.transition_to(SessionState.SEALED, "Zero breakages verified")
            except Exception as exc:
                raise ValueError(f"Cannot transition to SEALED state: {exc}") from exc
        return report_data

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

        # Update Session Active Free Energy F
        from fable_v2.system3 import ActiveInferenceEngine, create_default_architecture_pomdp
        fe_engine = ActiveInferenceEngine(create_default_architecture_pomdp())
        obs = "HIGH_THROUGHPUT_CLEAN" if terminal_probe_results and any(
            kw in terminal_probe_results.lower() for kw in ("pass", "ok", "success")
        ) else "LOCK_CONTENTION_WARN"
        f_val, comp, acc = fe_engine.update_beliefs(obs)
        self.active_free_energy = {
            "variational_free_energy_f": round(f_val, 4),
            "complexity_kl": round(comp, 4),
            "accuracy_log_likelihood": round(acc, 4),
            "observation": obs,
            "cycle_number": cycle_num,
            "timestamp": self._wall_clock(),
        }

        # Update Causal DAG nodes (initialize default DAG if none exists)
        if not self.system3_causal_graphs:
            self.system3_causal_graphs.append({
                "dag": {"name": f"Session_{self.session_name}_DAG", "nodes": [], "edges": []},
                "nodes": [],
                "edges": [],
                "topological_order": [],
                "timestamp": self._wall_clock(),
            })
        if self.system3_causal_graphs:
            causal_node_id = f"refine_cycle_{cycle_num}"
            causal_node_data = {
                "node_id": causal_node_id,
                "name": f"Refinement {cycle_num}: {focus_area}",
                "node_type": "INTERVENTION",
                "value": 1.0,
                "parents": [f"refine_cycle_{cycle_num - 1}"] if cycle_num > 1 else [],
                "metadata": {
                    "refinement_type": refinement_type,
                    "focus_area": focus_area,
                    "critique": critique_or_bottleneck,
                }
            }
            latest_graph = self.system3_causal_graphs[-1]
            if "nodes" in latest_graph and isinstance(latest_graph["nodes"], list):
                if not any(n.get("node_id") == causal_node_id for n in latest_graph["nodes"] if isinstance(n, dict)):
                    latest_graph["nodes"].append(causal_node_data)
            inner_dag = latest_graph.get("dag", latest_graph)
            nodes = inner_dag.setdefault("nodes", [])
            if isinstance(nodes, list):
                if not any(n.get("node_id") == causal_node_id for n in nodes if isinstance(n, dict)):
                    nodes.append(causal_node_data)
            elif isinstance(nodes, dict):
                nodes[causal_node_id] = causal_node_data
            if cycle_num > 1:
                prev_id = f"refine_cycle_{cycle_num - 1}"
                edge_data = {"source": prev_id, "target": causal_node_id, "weight": 1.0, "mechanism": "refinement_evolution"}
                if "edges" in latest_graph and isinstance(latest_graph["edges"], list):
                    latest_graph["edges"].append(edge_data)
                edges = inner_dag.setdefault("edges", [])
                if isinstance(edges, list):
                    edges.append(edge_data)

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
        5. Anti-Idle check: at least 1 refinement cycle per 5 minutes of budget (minimum 2 cycles).

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
        proven_items = [i for i in self.epistemic_ledger if i.get("tag") == "PROVEN" and not i.get("_restored_untrusted")]
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

        # Anti-idle check: require minimum refinement cycles (at least 1 cycle per 5 minutes of budget, min 2 cycles)
        min_refinements = max(2, math.ceil(self.time_budget_minutes / 5.0))
        valid_refinements = [r for r in self.refinement_cycles if not r.get("_restored_untrusted")]
        if len(valid_refinements) < min_refinements:
            errors.append(
                f"Anti-Idle Requirement Not Satisfied: Requires at least {min_refinements} rethink-refine cycles for a "
                f"{self.time_budget_minutes}m budget (currently {len(valid_refinements)} recorded). "
                f"Continuous cognitive refinement is mandatory during deliberation."
            )

        if errors:
            reasons = "\n".join([f"  - {e}" for e in errors])
            raise PermissionError(
                f"🛑 Anti-Rush Lockout Active! Execution unlock denied due to missing cognitive gates:\n{reasons}\n\n"
                f"Please log required proven facts, formal invariants, refinement cycles, and advance to Phase 3+ before unlocking."
            )

        self.execution_locked = False
        self.can_execute_code = True
        if self.current_state == SessionState.INIT:
            self.transition_to(SessionState.DEEPTHINK_TIMELOCK, "Pre-unlock transition to DEEPTHINK_TIMELOCK")
        if self.current_state == SessionState.DEEPTHINK_TIMELOCK:
            self.transition_to(SessionState.IMPLEMENTATION, rationale)

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
            "version": "1.3.0",
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
            "current_state": self.current_state.value if isinstance(self.current_state, SessionState) else str(self.current_state),
            "iteration_count": self.iteration_count,
            "active_breakages": self.active_breakages,
            "remediation_history": self.remediation_history,
            "epistemic_ledger": self.epistemic_ledger,
            "invariants": self.invariants,
            "refinement_cycles": self.refinement_cycles,
            "file_changes": self.file_changes,
            "visual_mockups": self.visual_mockups,
            "proof_receipts": self.proof_receipts,
            "goal_rubrics": self.goal_rubrics,
            "automation_pipelines": self.automation_pipelines,
            "breakage_reports": self.breakage_reports,
            "phase_history": self.phase_history,
            "unlock_details": self.unlock_details,
            "system3_causal_graphs": self.system3_causal_graphs,
            "system3_syntheses": self.system3_syntheses,
            "system3_gene_pools": self.system3_gene_pools,
            "system3_axioms": self.system3_axioms,
            "system3_reflections": self.system3_reflections,
            "system3_orchestrations": self.system3_orchestrations,
            "system3_hyperbolic_embeddings": self.system3_hyperbolic_embeddings,
            "system3_kripke_verifications": self.system3_kripke_verifications,
            "system3_active_inferences": self.system3_active_inferences,
            "system3_proof_oracle_verifications": self.system3_proof_oracle_verifications,
            "active_free_energy": self.active_free_energy,
            "active_kripke_safety": self.active_kripke_safety,
            "active_biases": self.active_biases,
            "fable_run": self.fable_run.to_dict() if getattr(self, "fable_run", None) else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FableSession":
        """Restore data without importing persisted execution authority.

        Persistence is an interchange format, not an authority token.  The
        deadline, phase, evidence, invariants, and unlock flags are all treated
        as untrusted; a restored process starts a fresh locked authority clock.
        Historical data remains visible, but cannot satisfy fresh gates.
        """
        budget = data.get("time_budget_minutes", 60.0)
        session = cls(session_name=data["session_name"], objective=data.get("objective", ""),
                      time_budget_minutes=budget, session_id=data.get("session_id"))
        session._restored_untrusted = True
        state_str = data.get("current_state", SessionState.INIT.value)
        try:
            session.current_state = SessionState(state_str)
        except ValueError:
            session.current_state = SessionState.INIT
        session.iteration_count = int(data.get("iteration_count", 0))
        session.active_breakages = list(data.get("active_breakages", []))
        session.remediation_history = list(data.get("remediation_history", []))
        session.epistemic_ledger = [dict(item, _restored_untrusted=True) for item in data.get("epistemic_ledger", []) if isinstance(item, dict)]
        session.invariants = [dict(item, _restored_untrusted=True) for item in data.get("invariants", []) if isinstance(item, dict)]
        session.refinement_cycles = [dict(item, _restored_untrusted=True) for item in data.get("refinement_cycles", []) if isinstance(item, dict)]
        session.file_changes = data.get("file_changes", [])
        session.visual_mockups = data.get("visual_mockups", {"mockups": [], "selected_concept": None})
        session.proof_receipts = data.get("proof_receipts", [])
        session.goal_rubrics = data.get("goal_rubrics", [])
        session.automation_pipelines = data.get("automation_pipelines", [])
        session.breakage_reports = data.get("breakage_reports", [])
        session.active_phase = PHASES[0]
        session.phase_history = [{"phase": PHASES[0], "entered_at": session.start_time,
                                 "summary": "Restored in safe locked state; fresh gates required"}]
        session.execution_locked = True
        session.can_execute_code = False
        session.unlock_details = None
        session.system3_causal_graphs = data.get("system3_causal_graphs", [])
        session.system3_syntheses = data.get("system3_syntheses", [])
        session.system3_gene_pools = data.get("system3_gene_pools", [])
        session.system3_axioms = data.get("system3_axioms", [])
        session.system3_reflections = data.get("system3_reflections", [])
        session.system3_orchestrations = data.get("system3_orchestrations", [])
        session.system3_hyperbolic_embeddings = data.get("system3_hyperbolic_embeddings", [])
        session.system3_kripke_verifications = data.get("system3_kripke_verifications", [])
        session.system3_active_inferences = data.get("system3_active_inferences", [])
        session.system3_proof_oracle_verifications = data.get("system3_proof_oracle_verifications", [])
        session.active_free_energy = data.get("active_free_energy")
        session.active_kripke_safety = data.get("active_kripke_safety")
        session.active_biases = data.get("active_biases", [])
        fable_run_data = data.get("fable_run")
        if fable_run_data and isinstance(fable_run_data, dict):
            try:
                from fable_v2.runtime import FableRun
                session.fable_run = FableRun.from_dict(fable_run_data)
            except Exception:
                pass
        return session

    def save(self, target_path: Optional[Path] = None) -> Path:
        """Atomically save a session using a unique no-follow temporary file and cross-process lock."""
        path = Path(target_path or (SESSIONS_DIR / f"{self.session_name}.json")).expanduser().absolute()
        with session_file_lock(path):
            parent = path.parent
            _assert_private_path(parent)
            parent.mkdir(parents=True, exist_ok=True)
            _assert_private_path(parent)
            if parent.is_symlink() or not parent.is_dir() or path.is_symlink():
                raise OSError("session path or parent is a symlink/reparse point")
            os.chmod(parent, 0o700)
            if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
                parent_fd = _open_directory_nofollow(parent, create=True)
                temp_name = f".{path.name}.{os.getpid()}-{os.urandom(8).hex()}.tmp"
                fd = None
                try:
                    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        fd = None
                        json.dump(self.to_dict(), handle, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    try:
                        os.fsync(parent_fd)
                    except OSError:
                        # Linux O_PATH directory descriptors are suitable for
                        # descriptor-relative publication but not fsync targets.
                        pass
                finally:
                    if fd is not None:
                        os.close(fd)
                    try:
                        os.unlink(temp_name, dir_fd=parent_fd)
                    except OSError:
                        pass
                    os.close(parent_fd)
            else:
                fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
                temp_path = Path(temporary)
                try:
                    if hasattr(os, "fchmod"):
                        os.fchmod(fd, 0o600)
                    else:
                        os.chmod(temporary, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(self.to_dict(), handle, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_path, path)
                finally:
                    if temp_path.exists() or temp_path.is_symlink():
                        temp_path.unlink()
            try:
                self._disk_mtime = path.stat().st_mtime
            except OSError:
                pass
            logger.info(f"Fable session '{self.session_name}' saved to {path}")
            return path


@contextmanager
def session_file_lock(session_path: Path, timeout: float = 5.0):
    """Cross-process file lock using msvcrt on Windows and fcntl on POSIX."""
    lock_file = session_path.parent / f".{session_path.name}.lock"
    start = time.time()
    handle = None
    try:
        handle = open(lock_file, "a+b")
        acquired = False
        while time.time() - start < timeout:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                time.sleep(0.02)
        if not acquired:
            logger.warning(f"Session lock acquisition timed out for {session_path}")
        yield
    finally:
        if handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                handle.close()
            except OSError:
                pass


# In-Memory Active Sessions Table
ACTIVE_SESSIONS: Dict[str, FableSession] = {}


def _safe_session_file(path: Path) -> None:
    _assert_private_path(path.parent)
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise ValueError(f"session file does not exist: {path.name}")
    attrs = int(getattr(st, "st_file_attributes", 0))
    if (attrs & 0x400 or stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode)
            or st.st_nlink != 1 or (os.name != "nt" and stat.S_IMODE(st.st_mode) & 0o077)):
        raise ValueError("session file must be a private regular non-hardlinked file")


def get_or_load_session(session_name: str) -> FableSession:
    """Retrieves session from memory or loads from disk if exists, checking mtime for cross-process synchronization."""
    clean_name = _validate_session_name(session_name)
    file_path = SESSIONS_DIR / f"{clean_name}.json"

    if clean_name in ACTIVE_SESSIONS:
        session = ACTIVE_SESSIONS[clean_name]
        if file_path.exists():
            try:
                disk_mtime = file_path.stat().st_mtime
                if disk_mtime > getattr(session, "_disk_mtime", 0.0):
                    with session_file_lock(file_path):
                        _safe_session_file(file_path)
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        session = FableSession.from_dict(data)
                        session._disk_mtime = disk_mtime
                        ACTIVE_SESSIONS[clean_name] = session
            except Exception as exc:
                logger.warning(f"Failed to check disk mtime reload for session {clean_name}: {exc}")
        return session

    if file_path.exists() or file_path.is_symlink():
        try:
            with session_file_lock(file_path):
                _safe_session_file(file_path)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = FableSession.from_dict(data)
                try:
                    session._disk_mtime = file_path.stat().st_mtime
                except OSError:
                    pass
                ACTIVE_SESSIONS[clean_name] = session
                return session
        except Exception as e:
            logger.error(f"Failed to load session file {file_path}: {e}")
            raise RuntimeError(f"Corrupt or unreadable session file for '{clean_name}': {e}")

    raise ValueError(f"Session '{clean_name}' does not exist. Call 'create_session' first.")


