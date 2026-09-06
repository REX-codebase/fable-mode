"""
Frontier Uplift Guards and Micro-Engines.
Implements:
- AntiLoopCircuitBreaker: O(1) cyclical loop and oscillation detection
- EpistemicEvidenceValidator: AST/URL/command proof grounded evidence verification
- ModelVelocityProfiler: Real-time throughput profiling and model tier classification
- DelegationContractCompiler: Statically verified subagent contract compilation with System 3 scaffolds
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# DeterministicProofValidator imported lazily in EpistemicEvidenceValidator


class AntiLoopCircuitBreaker:
    """Detects repeated identical failed actions and cyclical oscillations in O(1)."""

    def __init__(self, max_consecutive_repeats: int = 2, window_size: int = 6):
        self.max_consecutive_repeats = max_consecutive_repeats
        self.window_size = window_size
        self.signatures: List[str] = []

    def _compute_action_signature(self, tool_name: str, args: Dict[str, Any]) -> str:
        canonical = json.dumps({"tool": tool_name, "args": args}, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def record_and_evaluate(self, tool_name: str, args: Dict[str, Any], is_error: bool) -> Tuple[bool, str]:
        sig = self._compute_action_signature(tool_name, args)
        self.signatures.append(sig)
        if len(self.signatures) > self.window_size:
            self.signatures.pop(0)

        # Check consecutive identical tool invocations in failing state
        consecutive_count = 0
        for s in reversed(self.signatures):
            if s == sig:
                consecutive_count += 1
            else:
                break

        if consecutive_count >= self.max_consecutive_repeats and is_error:
            return True, (
                f"[CIRCUIT_BREAKER_TRIGGERED]: You have invoked '{tool_name}' with the same arguments "
                f"{consecutive_count} times in a failing state. STOP repeating this action. "
                "Execute the OODA Loop: inspect line numbers with view_file or re-verify preconditions."
            )

        # Check cyclical loop (A -> B -> A -> B) where A != B
        if len(self.signatures) >= 4:
            if (
                self.signatures[-1] != self.signatures[-2]
                and self.signatures[-1] == self.signatures[-3]
                and self.signatures[-2] == self.signatures[-4]
            ):
                return True, (
                    "[CIRCUIT_BREAKER_TRIGGERED]: Cyclical 2-step oscillation detected (Action A <-> Action B). "
                    "Break the loop immediately and reconsider system invariants."
                )

        return False, "OK"


class EpistemicEvidenceValidator:
    """Validates that [PROVEN] evidence strings map to real filesystem files, line ranges, URLs, or CLI stdout."""

    CITATION_PATTERN = re.compile(r"^(.*?)(?::(?:L)?(\d+)(?:-(?:L)?(\d+))?)?$")

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        from fable_v2.proof_engine import DeterministicProofValidator
        self._validator = DeterministicProofValidator(workspace_root=self.workspace_root)

    def parse_evidence_citation(self, evidence_str: str) -> Optional[Dict[str, Any]]:
        return self._validator._parse_file_citation(evidence_str)

    def validate_proven_claim(self, claim: str, evidence: str) -> Tuple[bool, str]:
        valid, msg, _ = self._validator.validate_proven_claim(claim, evidence)
        return valid, msg


class ModelVelocityProfiler:
    """
    Tracks timestamps and character/token volume across incoming tool requests.
    Computes rolling velocity (chars/sec, est. tokens/sec, tool call frequency).
    Classifies model tier:
      - flash (Fast / High Throughput): tokens_per_sec > 80 or rapid successive tool calls. Multiplier = 2.5x
      - pro / heavy (Deep sequential): tokens_per_sec 20-80. Multiplier = 1.0x
      - local / weak: tokens_per_sec < 20. Automatically injects micro-scaffold hints.
    """

    def __init__(self, window_size: int = 20, clock: Optional[Any] = None):
        self.window_size = window_size
        self._clock = clock or time.time
        self.request_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.total_chars: int = 0
        self.total_estimated_tokens: int = 0

    def record_request(self, action: str, raw_payload: Union[str, Dict[str, Any], int], timestamp: Optional[float] = None) -> None:
        """Record an incoming tool request's character/token volume and timestamp."""
        ts = timestamp if timestamp is not None else self._clock()
        if isinstance(raw_payload, int):
            char_count = max(0, raw_payload)
        elif isinstance(raw_payload, str):
            char_count = len(raw_payload)
        elif isinstance(raw_payload, dict):
            try:
                char_count = len(json.dumps(raw_payload))
            except Exception:
                char_count = 100
        else:
            char_count = 100

        est_tokens = max(1, char_count // 4)
        with self._lock:
            self.total_requests += 1
            self.total_chars += char_count
            self.total_estimated_tokens += est_tokens
            self.request_history.append({
                "timestamp": ts,
                "action": action,
                "chars": char_count,
                "tokens": est_tokens,
            })
            if len(self.request_history) > self.window_size * 2:
                self.request_history = self.request_history[-self.window_size:]

    def get_velocity_profile(self) -> Dict[str, Any]:
        """Compute rolling velocity metrics and classify model tier."""
        with self._lock:
            history = list(self.request_history)
            total_reqs = self.total_requests
            tot_chars = self.total_chars
            tot_tokens = self.total_estimated_tokens

        if not history:
            return {
                "chars_per_sec": 0.0,
                "tokens_per_sec": 0.0,
                "tool_call_frequency_cpm": 0.0,
                "avg_interval_seconds": 0.0,
                "model_tier": "pro",
                "tier_multiplier": 1.0,
                "tier_description": "pro / heavy (Deep sequential reasoning tier)",
                "total_requests": total_reqs,
                "total_chars": tot_chars,
                "total_estimated_tokens": tot_tokens,
                "requires_micro_scaffolds": False,
            }

        if len(history) == 1:
            time_span = 1.0
            window_chars = history[0]["chars"]
            window_tokens = history[0]["tokens"]
            call_count = 1
            avg_interval = 5.0
        else:
            recent = history[-self.window_size:]
            time_span = max(0.5, recent[-1]["timestamp"] - recent[0]["timestamp"])
            window_chars = sum(r["chars"] for r in recent)
            window_tokens = sum(r["tokens"] for r in recent)
            call_count = len(recent)
            intervals = [recent[i]["timestamp"] - recent[i-1]["timestamp"] for i in range(1, len(recent))]
            avg_interval = sum(intervals) / max(1, len(intervals))

        chars_per_sec = round(window_chars / time_span, 2)
        tokens_per_sec = round(window_tokens / time_span, 2)
        cpm = round((call_count / time_span) * 60.0, 2)

        if tokens_per_sec > 80.0 or (avg_interval < 2.0 and call_count >= 3) or cpm > 20.0:
            tier = "flash"
            multiplier = 2.5
            desc = "flash (Fast / High Throughput: requires deeper parallel exploration, 5+ mockup concepts, rich coordinate modeling)"
            micro_scaffolds = False
        elif tokens_per_sec >= 20.0:
            tier = "pro"
            multiplier = 1.0
            desc = "pro / heavy (Deep sequential reasoning tier)"
            micro_scaffolds = False
        else:
            tier = "local"
            multiplier = 0.5
            desc = "local / weak (Resource-constrained tier: automatically injects micro-scaffold hints)"
            micro_scaffolds = True

        return {
            "chars_per_sec": chars_per_sec,
            "tokens_per_sec": tokens_per_sec,
            "tool_call_frequency_cpm": cpm,
            "avg_interval_seconds": round(avg_interval, 2),
            "model_tier": tier,
            "tier_multiplier": multiplier,
            "tier_description": desc,
            "total_requests": total_reqs,
            "total_chars": tot_chars,
            "total_estimated_tokens": tot_tokens,
            "requires_micro_scaffolds": micro_scaffolds,
        }


GLOBAL_VELOCITY_PROFILER = ModelVelocityProfiler()


class DelegationContractCompiler:
    """Verifies that subagent delegation prompts/contracts are complete, unambiguous, and statically sound."""

    REQUIRED_SECTIONS = [
        "TargetFile",
        "InterfaceContract",
        "StrictConstraints",
        "VerificationCommand"
    ]

    def __init__(self):
        self.file_regex = re.compile(r"(TargetFile|FileBoundary):\s*[`\"]?([A-Za-z0-9_./\\:-]+)[`\"]?", re.IGNORECASE)
        self.cmd_regex = re.compile(r"(VerificationCommand|TestCommand):\s*[`\"]?([^`\"\n]+)[`\"]?", re.IGNORECASE)

    @staticmethod
    def inject_system3_micro_scaffolds(prompt: str, parsed: Dict[str, str]) -> str:
        """Inject System 3 Micro-Scaffolds into the delegation contract for weak-model frontier uplift."""
        target_file = parsed.get("TargetFile", "src/target.py")
        verif_cmd = parsed.get("VerificationCommand", "python -m unittest")

        scaffold = f"""
### 🛡️ SYSTEM 3 MICRO-SCAFFOLD (WEAK-MODEL FRONTIER UPLIFT)

#### 1. Kripke Safety Invariant Contract ($AG(\\text{{safe}})$):
- $AG(\\text{{NoHallucination}} \\land \\text{{TypeSoundness}})$: Never invent non-existent APIs or variables.
- $AX(\\text{{TargetFileBoundary}})$: Modify ONLY `{target_file}`. Zero modifications outside `{target_file}`.
- $AF(\\text{{VerificationPass}})$: Every execution must satisfy `{verif_cmd}` with exit code 0.

#### 2. Causal Failure Mode Boundaries ($do(\\cdot)$ Sensitivities):
- Invariant under intervention: $P(\\text{{SystemError}} \\mid do(\\text{{Edit}}({target_file}))) = 0$.
- Pre-condition validation: Inspect and verify exact file line bounds before applying replacements.
- Post-condition validation: Run `{verif_cmd}` immediately after edit to confirm 0 regressions.

#### 3. TRIZ Transcendent Resolution Guidelines:
- Avoid lazy compromises (do NOT comment out tests or catch-and-ignore exceptions).
- Apply TRIZ Principle 1 (Segmentation): Decompose complex logic into pure helper functions.
- Apply TRIZ Principle 10 (Preliminary Action): Validate all preconditions before mutating state.

#### 4. Structured Output Regex Acceptance Constraint:
- Your response MUST strictly adhere to atomic execution formatting:
  Pattern: `^```(?:python|json|diff)[\\s\\S]*?```$`
"""
        return prompt.strip() + "\n\n" + scaffold.strip()

    def compile_and_validate(self, prompt: str) -> Tuple[bool, List[str], Dict[str, str]]:
        errors = []
        parsed = {}

        file_match = self.file_regex.search(prompt)
        if not file_match:
            errors.append("Missing explicit 'TargetFile' declaration. Subagents must have bounded file write targets.")
        else:
            parsed["TargetFile"] = file_match.group(2)

        cmd_match = self.cmd_regex.search(prompt)
        if not cmd_match:
            errors.append("Missing explicit 'VerificationCommand'. Subagents must know what test to execute for DoD verification.")
        else:
            parsed["VerificationCommand"] = cmd_match.group(2).strip()

        if not any(k.lower() in prompt.lower() for k in ["interfacecontract", "functionsignature", "typedefinition", "api contract", "interface"]):
            errors.append("Missing 'InterfaceContract' or 'FunctionSignature'. Subagents require explicit types/signatures.")

        if not any(k.lower() in prompt.lower() for k in ["strictconstraints", "invariants", "non-negotiable", "constraints"]):
            errors.append("Missing 'StrictConstraints' or 'Invariants'. Subagents must be constrained against regressions.")

        is_valid = len(errors) == 0
        if is_valid:
            parsed["system3_micro_scaffold"] = self.inject_system3_micro_scaffolds(prompt, parsed)
            parsed["compiled_prompt"] = parsed["system3_micro_scaffold"]
        return is_valid, errors, parsed
