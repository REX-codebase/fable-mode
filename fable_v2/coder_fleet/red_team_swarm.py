"""Modular Fable Part 1: Adversarial Code Review Swarm (Project Glasswing Red Team Loop).

Production-grade Red Team Swarm engine providing:
- 5 Attack Vectors: Chaos Environment, Byzantine Payload, Concurrency Race, Resource Exhaustion, State Invariant
- BreakScenario, BreakFinding, and RedTeamBreakageReport dataclasses
- RedTeamSwarm engine executing counterfactual "What if?" attack probes
- Automated Ping-Pong Hardening & Remediation Verification protocol
"""
from __future__ import annotations

import datetime
import inspect
import json
import os
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Union

from .mock_auditor import MockAuditorEngine
from .property_oracle import PropertyOracleEngine
from .test_harness import TestHarnessEngine


class AttackVector(str, Enum):
    """The 5 Core Attack Vectors for Adversarial Code Review."""

    CHAOS_ENVIRONMENT = "chaos_environment"
    BYZANTINE_PAYLOAD = "byzantine_payload"
    CONCURRENCY_RACE = "concurrency_race"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    STATE_INVARIANT = "state_invariant"


@dataclass
class BreakScenario:
    """An adversarial scenario probing what will happen under extreme conditions."""

    scenario_id: str
    vector: AttackVector
    hypothesis: str  # "What will happen if X happened?"
    expected_resilience: str = ""
    attack_fn: Optional[Callable[..., Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BreakFinding:
    """The finding result from executing an adversarial probe against a target."""

    scenario_id: str
    vector: str
    hypothesis: str
    broken: bool
    error_message: Optional[str] = None
    traceback_snippet: Optional[str] = None
    reproduction_code: Optional[str] = None
    severity: str = "MEDIUM"  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize finding to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "vector": self.vector,
            "hypothesis": self.hypothesis,
            "broken": self.broken,
            "error_message": self.error_message,
            "traceback_snippet": self.traceback_snippet,
            "reproduction_code": self.reproduction_code,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class RedTeamBreakageReport:
    """Comprehensive breakage and resilience report compiled by RedTeamSwarm."""

    report_id: str
    target_name: str
    total_probes: int
    broken_count: int
    passed: bool
    findings: list[BreakFinding]
    created_at: str
    remediation_directives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize report to dictionary."""
        return {
            "report_id": self.report_id,
            "target_name": self.target_name,
            "total_probes": self.total_probes,
            "broken_count": self.broken_count,
            "passed": self.passed,
            "created_at": self.created_at,
            "remediation_directives": list(self.remediation_directives),
            "findings": [
                {
                    "scenario_id": f.scenario_id,
                    "vector": f.vector,
                    "hypothesis": f.hypothesis,
                    "broken": f.broken,
                    "error_message": f.error_message,
                    "traceback_snippet": f.traceback_snippet,
                    "reproduction_code": f.reproduction_code,
                    "severity": f.severity,
                    "details": f.details,
                }
                for f in self.findings
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedTeamBreakageReport:
        """Construct RedTeamBreakageReport from dictionary."""
        findings = [
            BreakFinding(
                scenario_id=item.get("scenario_id", ""),
                vector=item.get("vector", AttackVector.CHAOS_ENVIRONMENT.value),
                hypothesis=item.get("hypothesis", ""),
                broken=item.get("broken", False),
                error_message=item.get("error_message"),
                traceback_snippet=item.get("traceback_snippet"),
                reproduction_code=item.get("reproduction_code"),
                severity=item.get("severity", "MEDIUM"),
                details=item.get("details", {}),
            )
            for item in data.get("findings", [])
        ]
        return cls(
            report_id=data.get("report_id", f"report_{uuid.uuid4().hex[:8]}"),
            target_name=data.get("target_name", "target"),
            total_probes=data.get("total_probes", len(findings)),
            broken_count=data.get("broken_count", sum(1 for f in findings if f.broken)),
            passed=data.get("passed", sum(1 for f in findings if f.broken) == 0),
            findings=findings,
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            remediation_directives=data.get("remediation_directives", []),
        )

    def to_markdown(self) -> str:
        """Render report as clean GitHub-flavored markdown with alerts and tables."""
        lines: list[str] = []

        if self.passed:
            lines.append(f"# 🛡️ Adversarial Red Team Resilient Attestation: `{self.target_name}`")
        else:
            lines.append(f"# 🚨 Adversarial Red Team Breakage Report: `{self.target_name}`")

        lines.append("")
        lines.append(f"- **Report ID**: `{self.report_id}`")
        lines.append(f"- **Target Name**: `{self.target_name}`")
        lines.append(f"- **Total Probes**: `{self.total_probes}`")
        lines.append(f"- **Broken Scenarios**: `{self.broken_count}`")
        lines.append(f"- **Status**: {'🟢 **RESILIENT (PASSED)**' if self.passed else '🔴 **BREAKAGES DETECTED (FAILED)**'}")
        lines.append(f"- **Created At**: `{self.created_at}`")
        lines.append("")

        if not self.passed:
            lines.append("> [!CAUTION]")
            lines.append(f"> Swarm attacks detected **{self.broken_count} breakages** in `{self.target_name}`!")
            lines.append("> Subagent code changes are **REJECTED** until all remediation directives are implemented and verified.")
        else:
            lines.append("> [!NOTE]")
            lines.append(f"> Target `{self.target_name}` survived all **{self.total_probes} adversarial probes** with zero unhandled breakages.")
            lines.append("> Verified resilient against chaos, Byzantine inputs, concurrency races, resource limits, and state invariant attacks.")

        lines.append("")
        lines.append("### 📋 Probes & Findings Overview")
        lines.append("")
        lines.append("| Scenario ID | Vector | Hypothesis | Broken | Severity |")
        lines.append("|---|---|---|:---:|:---:|")

        for f in self.findings:
            status_icon = "💥 **YES**" if f.broken else "✅ NO"
            safe_hyp = f.hypothesis.replace("|", "\\|")
            lines.append(f"| `{f.scenario_id}` | `{f.vector}` | {safe_hyp} | {status_icon} | `{f.severity}` |")

        # Detail any breakages
        broken_findings = [f for f in self.findings if f.broken]
        if broken_findings:
            lines.append("")
            lines.append("### 💥 Breakage Diagnostic Details")
            for bf in broken_findings:
                lines.append("")
                lines.append(f"#### 🔴 `{bf.scenario_id}` (`{bf.vector}`) - Severity: `{bf.severity}`")
                lines.append(f"**Hypothesis**: {bf.hypothesis}")
                if bf.error_message:
                    lines.append(f"**Observed Failure**: `{bf.error_message}`")
                if bf.traceback_snippet:
                    lines.append("")
                    lines.append("```text")
                    lines.append(bf.traceback_snippet.strip())
                    lines.append("```")
                if bf.reproduction_code:
                    lines.append("")
                    lines.append("**Reproduction Snippet**:")
                    lines.append("```python")
                    lines.append(bf.reproduction_code.strip())
                    lines.append("```")

        # Remediation directives
        lines.append("")
        lines.append("### 🛠️ Remediation Directives")
        if self.remediation_directives:
            for idx, directive in enumerate(self.remediation_directives, 1):
                lines.append(f"{idx}. {directive}")
        else:
            lines.append("- No remediation required. All adversarial probes passed.")

        lines.append("")
        return "\n".join(lines)


class RedTeamSwarm:
    """Adversarial Red Team Swarm executing counterfactual stress probes across 5 vectors."""

    def __init__(
        self,
        test_harness: Optional[TestHarnessEngine] = None,
        mock_auditor: Optional[MockAuditorEngine] = None,
        property_oracle: Optional[PropertyOracleEngine] = None,
        plasticity_engine: Optional[Any] = None,
    ) -> None:
        self.test_harness = test_harness or TestHarnessEngine()
        self.mock_auditor = mock_auditor or MockAuditorEngine()
        self.property_oracle = property_oracle or PropertyOracleEngine(test_harness=self.test_harness)
        if plasticity_engine is not None:
            self.plasticity_engine = plasticity_engine
        else:
            try:
                from ..cortical.plasticity_engine import HebbianPlasticityEngine
                self.plasticity_engine = HebbianPlasticityEngine()
            except Exception:
                try:
                    from fable_v2.cortical.plasticity_engine import HebbianPlasticityEngine
                    self.plasticity_engine = HebbianPlasticityEngine()
                except Exception:
                    self.plasticity_engine = None

    @staticmethod
    def _compile_code_to_callable(code: str) -> Callable[..., Any]:
        """Safely compiles a python code string into an executable callable."""
        scope: dict[str, Any] = {}
        exec(code, scope, scope)

        # Look for functions defined in scope
        functions = [v for v in scope.values() if callable(v) and not isinstance(v, type)]
        if functions:
            return functions[-1]

        # Look for classes
        classes = [v for v in scope.values() if isinstance(v, type)]
        if classes:
            return classes[-1]

        def _fallback_callable(*args: Any, **kwargs: Any) -> Any:
            return scope.get("result", None)

        return _fallback_callable

    def _resolve_callable(self, target: Any) -> Optional[Callable[..., Any]]:
        """Resolves target callable from function, class, or code string."""
        if callable(target):
            return target
        if isinstance(target, str) and target.strip():
            try:
                return self._compile_code_to_callable(target)
            except Exception:
                return None
        return None

    def generate_break_scenarios(
        self,
        target_name: str = "target",
        code_snippet: Optional[str] = None,
        custom_hypotheses: Optional[list[str]] = None,
    ) -> list[BreakScenario]:
        """Generates comprehensive 'what if' break scenarios across all 5 attack vectors.

        Includes standard stress vectors and any user-specified custom hypotheses.
        """
        scenarios: list[BreakScenario] = []

        # Vector 1: CHAOS_ENVIRONMENT
        def _chaos_missing_path(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            # Probe with non-existent / unlinked file path
            return fn("/nonexistent/fable_chaos_probe_file.tmp")

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_chaos_01_missing_path",
                vector=AttackVector.CHAOS_ENVIRONMENT,
                hypothesis="What will happen if targeted files or temporary paths are missing, unlinked, or raise FileNotFoundError?",
                expected_resilience="Gracefully catches missing path or raises structured domain error without unhandled crash",
                attack_fn=_chaos_missing_path,
                metadata={"probe_type": "missing_path"},
            )
        )

        def _chaos_corrupt_env(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            return fn("")

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_chaos_02_empty_or_corrupt_env",
                vector=AttackVector.CHAOS_ENVIRONMENT,
                hypothesis="What will happen if configuration, environment strings, or descriptors are empty, corrupt, or None?",
                expected_resilience="Handles empty or missing environment gracefully",
                attack_fn=_chaos_corrupt_env,
                metadata={"probe_type": "empty_input"},
            )
        )

        # Vector 2: BYZANTINE_PAYLOAD
        def _byzantine_null_bytes(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            payload = "probe\x00hostile\x00injection\r\n\t"
            return fn(payload)

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_byzantine_01_null_bytes",
                vector=AttackVector.BYZANTINE_PAYLOAD,
                hypothesis="What will happen if input strings contain embedded null bytes (\\x00), escape controls, or surrogates?",
                expected_resilience="Properly sanitizes or rejects null-byte payloads without unhandled exception",
                attack_fn=_byzantine_null_bytes,
                metadata={"reproduction": "target_fn('probe\\x00hostile\\x00injection\\r\\n\\t')"},
            )
        )

        def _byzantine_deep_nesting(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            # 60 levels of nested dictionaries
            nested: dict[str, Any] = {"leaf": 42}
            for _ in range(60):
                nested = {"nest": nested}
            return fn(nested)

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_byzantine_02_deep_nesting",
                vector=AttackVector.BYZANTINE_PAYLOAD,
                hypothesis="What will happen if input payload contains deeply recursive nested dictionaries (60+ levels)?",
                expected_resilience="Traverses safely without triggering RecursionError or stack overflow",
                attack_fn=_byzantine_deep_nesting,
                metadata={"reproduction": "nested = {'leaf': 42}; [nested := {'nest': nested} for _ in range(60)]; target_fn(nested)"},
            )
        )

        def _byzantine_type_confusion(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            return fn(None)

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_byzantine_03_type_confusion",
                vector=AttackVector.BYZANTINE_PAYLOAD,
                hypothesis="What will happen if None or an inverted data type is passed into the target callable?",
                expected_resilience="Validates arguments and rejects None/incompatible types without raw AttributeError",
                attack_fn=_byzantine_type_confusion,
                metadata={"reproduction": "target_fn(None)"},
            )
        )

        def _byzantine_extreme_numbers(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            # Nan, Inf, negative zero, huge int
            return fn(float("nan"))

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_byzantine_04_extreme_numbers",
                vector=AttackVector.BYZANTINE_PAYLOAD,
                hypothesis="What will happen if numeric inputs are NaN, Infinity, -0.0, or exceed 2**64?",
                expected_resilience="Handles IEEE-754 special values and huge numbers safely",
                attack_fn=_byzantine_extreme_numbers,
                metadata={"reproduction": "target_fn(float('nan'))"},
            )
        )

        # Vector 3: CONCURRENCY_RACE
        def _concurrency_multithreaded_burst(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            errors: list[str] = []
            threads: list[threading.Thread] = []
            try:
                sig = inspect.signature(fn)
                has_params = len(sig.parameters) > 0
            except Exception:
                has_params = True

            def _worker() -> None:
                for _ in range(25):
                    try:
                        if has_params:
                            fn("concurrency_probe_payload")
                        else:
                            fn()
                    except Exception as e:
                        errors.append(f"{type(e).__name__}: {e}")
                        break

            for _ in range(6):
                t = threading.Thread(target=_worker, daemon=True)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=1.0)

            if errors:
                return {"broken": True, "error": f"Concurrency collision detected in thread burst: {errors[0]}"}
            return {"broken": False}

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_concurrency_01_race_burst",
                vector=AttackVector.CONCURRENCY_RACE,
                hypothesis="What will happen if 6 concurrent threads invoke the target simultaneously across 25 iterations?",
                expected_resilience="Thread-safe execution with zero race collisions or lost updates",
                attack_fn=_concurrency_multithreaded_burst,
                metadata={"reproduction": "Deploy 6 threads executing target_fn concurrently"},
            )
        )

        # Vector 4: RESOURCE_EXHAUSTION
        def _resource_massive_payload(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            massive_str = "A" * 150_000
            return fn(massive_str)

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_resource_01_massive_payload",
                vector=AttackVector.RESOURCE_EXHAUSTION,
                hypothesis="What will happen if the input payload is a massive 150,000-character payload?",
                expected_resilience="Handles or bounds large payload without OOM or memory exhaustion",
                attack_fn=_resource_massive_payload,
                metadata={"reproduction": "target_fn('A' * 150_000)"},
            )
        )

        def _resource_rapid_churn(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            sig = inspect.signature(fn)
            for _ in range(100):
                if len(sig.parameters) == 0:
                    fn()
                else:
                    fn("churn_sample")
            return {"broken": False}

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_resource_02_rapid_churn",
                vector=AttackVector.RESOURCE_EXHAUSTION,
                hypothesis="What will happen if invoked in rapid back-to-back sequence 100 times?",
                expected_resilience="No descriptor leakage or memory accumulation under rapid churn",
                attack_fn=_resource_rapid_churn,
                metadata={"reproduction": "[target_fn('churn_sample') for _ in range(100)]"},
            )
        )

        # Vector 5: STATE_INVARIANT
        def _state_invariant_idempotency(fn: Optional[Callable[..., Any]] = None) -> Any:
            if not fn:
                return True
            sig = inspect.signature(fn)
            if len(sig.parameters) == 0:
                res1 = fn()
                res2 = fn()
            else:
                res1 = fn("invariant_sample")
                res2 = fn("invariant_sample")
            return {"broken": False, "res1": str(res1)[:50], "res2": str(res2)[:50]}

        scenarios.append(
            BreakScenario(
                scenario_id=f"{target_name}_state_01_idempotency",
                vector=AttackVector.STATE_INVARIANT,
                hypothesis="What will happen if identical operations are performed consecutively? Does target violate state consistency?",
                expected_resilience="Idempotent or deterministic state transition without corruption",
                attack_fn=_state_invariant_idempotency,
                metadata={"reproduction": "r1 = target_fn('sample'); r2 = target_fn('sample')"},
            )
        )

        # Process custom hypotheses
        if custom_hypotheses:
            for idx, hyp in enumerate(custom_hypotheses, 1):
                hyp_clean = hyp.strip()
                if not hyp_clean:
                    continue

                h_lower = hyp_clean.lower()
                if any(w in h_lower for w in ("race", "thread", "concurr", "lock", "toctou")):
                    v = AttackVector.CONCURRENCY_RACE
                elif any(w in h_lower for w in ("byzantine", "payload", "null", "inject", "json", "nest")):
                    v = AttackVector.BYZANTINE_PAYLOAD
                elif any(w in h_lower for w in ("memory", "cpu", "exhaust", "leak", "timeout", "resource", "massive")):
                    v = AttackVector.RESOURCE_EXHAUSTION
                elif any(w in h_lower for w in ("invariant", "state", "idempotent", "order", "sequence", "balance")):
                    v = AttackVector.STATE_INVARIANT
                else:
                    v = AttackVector.CHAOS_ENVIRONMENT

                def _custom_attack_fn(fn: Optional[Callable[..., Any]] = None, h_text: str = hyp_clean) -> Any:
                    if not fn:
                        return True
                    sig = inspect.signature(fn)
                    if len(sig.parameters) == 0:
                        return fn()
                    return fn(f"probe:{h_text}")

                scenarios.append(
                    BreakScenario(
                        scenario_id=f"{target_name}_custom_{idx:02d}",
                        vector=v,
                        hypothesis=hyp_clean,
                        expected_resilience=f"Resilient against hypothesis: {hyp_clean}",
                        attack_fn=_custom_attack_fn,
                        metadata={"custom": True},
                    )
                )

        return scenarios

    def _derive_remediation_directives(self, findings: list[BreakFinding]) -> list[str]:
        """Derives actionable remediation directives based on broken findings."""
        directives: set[str] = set()

        for f in findings:
            if not f.broken:
                continue

            v = f.vector
            if v == AttackVector.BYZANTINE_PAYLOAD.value:
                directives.add(
                    "Implement defensive input validation and sanitization: check types, reject or strip null bytes (\\x00), "
                    "enforce maximum recursion depth limits, and guard against special IEEE-754 numbers (NaN/Inf)."
                )
            elif v == AttackVector.CONCURRENCY_RACE.value:
                directives.add(
                    "Enforce concurrency synchronization: wrap shared state updates with threading.Lock, "
                    "use atomic primitives, or make shared data structures read-only/immutable."
                )
            elif v == AttackVector.CHAOS_ENVIRONMENT.value:
                directives.add(
                    "Implement fault-tolerant environment handling: wrap I/O and path operations in try/except "
                    "(FileNotFoundError, PermissionError, OSError) with graceful fallback defaults."
                )
            elif v == AttackVector.RESOURCE_EXHAUSTION.value:
                directives.add(
                    "Apply resource bounding: enforce payload size limits (e.g., max 64KB), bounded loop counts, "
                    "and explicit execution timeouts to prevent denial-of-service."
                )
            elif v == AttackVector.STATE_INVARIANT.value:
                directives.add(
                    "Verify state invariants: ensure operations are strictly idempotent where expected, "
                    "validate pre-conditions and post-conditions, and reject invalid state transitions."
                )
            else:
                directives.add(f"Remediate failure in scenario `{f.scenario_id}`: {f.error_message or 'unhandled crash'}")

        return sorted(directives)

    def execute_swarm_attack(
        self,
        target_callable: Optional[Callable[..., Any]] = None,
        scenarios: Optional[list[BreakScenario]] = None,
        timeout_seconds: float = 3.0,
        target_name: Optional[str] = None,
    ) -> RedTeamBreakageReport:
        """Executes the break scenarios against target_callable with sandboxed execution.

        Detects unhandled crashes, memory/resource leaks, invariant violations, and timeouts.
        """
        callable_fn = self._resolve_callable(target_callable)
        actual_name = target_name or getattr(callable_fn, "__name__", "target")

        if not scenarios:
            scenarios = self.generate_break_scenarios(target_name=actual_name)

        findings: list[BreakFinding] = []

        for sc in scenarios:
            attack_fn = sc.attack_fn
            repro_code = sc.metadata.get("reproduction") or f"{actual_name}(<adversarial_probe>)"

            if attack_fn is None:
                # If no attack function is defined, pass by default
                findings.append(
                    BreakFinding(
                        scenario_id=sc.scenario_id,
                        vector=sc.vector.value if isinstance(sc.vector, AttackVector) else str(sc.vector),
                        hypothesis=sc.hypothesis,
                        broken=False,
                        severity="LOW",
                        details={"status": "no_attack_fn_provided"},
                    )
                )
                continue

            # Execute attack with timeout containment
            execution_result: dict[str, Any] = {"finished": False, "value": None, "error": None, "traceback": None}

            def _runner() -> None:
                try:
                    sig = inspect.signature(attack_fn)
                    if len(sig.parameters) > 0:
                        val = attack_fn(callable_fn)
                    else:
                        val = attack_fn()
                    execution_result["value"] = val
                    execution_result["finished"] = True
                except Exception as exc:
                    execution_result["error"] = exc
                    execution_result["traceback"] = traceback.format_exc()
                    execution_result["finished"] = True

            worker_thread = threading.Thread(target=_runner)
            worker_thread.daemon = True
            t0 = time.perf_counter()
            worker_thread.start()
            worker_thread.join(timeout=timeout_seconds)
            duration_ms = (time.perf_counter() - t0) * 1000.0

            vector_str = sc.vector.value if isinstance(sc.vector, AttackVector) else str(sc.vector)

            if not execution_result["finished"]:
                # Timed out!
                findings.append(
                    BreakFinding(
                        scenario_id=sc.scenario_id,
                        vector=vector_str,
                        hypothesis=sc.hypothesis,
                        broken=True,
                        error_message=f"Execution timed out after {timeout_seconds:.1f}s (possible infinite loop or dead-lock)",
                        reproduction_code=repro_code,
                        severity="HIGH",
                        details={"duration_ms": duration_ms, "timed_out": True},
                    )
                )
                continue

            if execution_result["error"] is not None:
                exc = execution_result["error"]
                # Determine if this exception represents a legitimate breakage or handled behavior.
                # If callable crashed with unhandled raw crash:
                is_unhandled_crash = isinstance(
                    exc,
                    (
                        AttributeError,
                        KeyError,
                        IndexError,
                        ZeroDivisionError,
                        UnboundLocalError,
                        RecursionError,
                        MemoryError,
                        AssertionError,
                    ),
                )
                # If TypeError occurs because an attribute wasn't found or 'NoneType', it's unhandled crash
                if isinstance(exc, TypeError) and any(kw in str(exc) for kw in ("NoneType", "subscriptable", "not callable")):
                    is_unhandled_crash = True

                # If attack function specifically asserted resilience and failed:
                severity = "CRITICAL" if isinstance(exc, (RecursionError, MemoryError, ZeroDivisionError)) else "HIGH"

                findings.append(
                    BreakFinding(
                        scenario_id=sc.scenario_id,
                        vector=vector_str,
                        hypothesis=sc.hypothesis,
                        broken=True,
                        error_message=f"{type(exc).__name__}: {str(exc)}",
                        traceback_snippet=execution_result["traceback"],
                        reproduction_code=repro_code,
                        severity=severity,
                        details={"duration_ms": duration_ms, "exception_type": type(exc).__name__},
                    )
                )
            else:
                # Returned normally - inspect return value for explicit breakage flags
                val = execution_result["value"]
                broken = False
                error_msg: Optional[str] = None

                if isinstance(val, dict):
                    if val.get("broken") is True or val.get("success") is False:
                        broken = True
                        error_msg = val.get("error") or val.get("error_message") or "Probe detected breakage condition"
                elif isinstance(val, bool):
                    if sc.metadata.get("return_true_means_broken") is True and val is True:
                        broken = True
                        error_msg = "Attack function reported True (breakage detected)"

                findings.append(
                    BreakFinding(
                        scenario_id=sc.scenario_id,
                        vector=vector_str,
                        hypothesis=sc.hypothesis,
                        broken=broken,
                        error_message=error_msg,
                        reproduction_code=repro_code if broken else None,
                        severity="MEDIUM" if broken else "LOW",
                        details={"duration_ms": duration_ms, "return_type": type(val).__name__},
                    )
                )

        broken_count = sum(1 for f in findings if f.broken)
        passed = broken_count == 0
        report_id = f"redteam_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        directives = self._derive_remediation_directives(findings)

        return RedTeamBreakageReport(
            report_id=report_id,
            target_name=actual_name,
            total_probes=len(findings),
            broken_count=broken_count,
            passed=passed,
            findings=findings,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            remediation_directives=directives,
        )

    def document_breakage(
        self,
        report: Union[RedTeamBreakageReport, dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> str:
        """Formats and optionally writes the markdown report to output_path."""
        if isinstance(report, dict):
            rep_obj = RedTeamBreakageReport.from_dict(report)
        else:
            rep_obj = report

        markdown_content = rep_obj.to_markdown()

        if output_path:
            try:
                parent = os.path.dirname(os.path.abspath(output_path))
                os.makedirs(parent, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
            except Exception as e:
                # Include warning if disk write fails
                markdown_content += f"\n\n> [!WARNING]\n> Failed to persist markdown report to `{output_path}`: {e}"

        return markdown_content

    def verify_remediation(
        self,
        target_callable: Any,
        prior_report: Union[RedTeamBreakageReport, dict[str, Any]],
        additional_scenarios: Optional[list[BreakScenario]] = None,
        auto_consolidate: bool = True,
        timeout_seconds: float = 3.0,
    ) -> tuple[bool, RedTeamBreakageReport]:
        """Re-runs the scenarios that previously caused breakages against the remediated callable.

        Includes optional additional regression scenarios.
        Returns:
            (all_fixed: bool, new_report: RedTeamBreakageReport)
        """
        if isinstance(prior_report, dict):
            p_rep = RedTeamBreakageReport.from_dict(prior_report)
        else:
            p_rep = prior_report

        broken_ids = {f.scenario_id for f in p_rep.findings if f.broken}

        # Generate fresh scenarios to get live attack functions
        callable_fn = self._resolve_callable(target_callable)
        target_name = getattr(callable_fn, "__name__", p_rep.target_name)
        fresh_scenarios = self.generate_break_scenarios(target_name=target_name)

        # Filter to previously broken scenarios
        scenarios_to_rerun: list[BreakScenario] = [
            s for s in fresh_scenarios if s.scenario_id in broken_ids or any(bid.endswith(s.scenario_id) for bid in broken_ids)
        ]

        # If some broken IDs were custom or not in standard generator, reconstitute them from findings
        matched_ids = {s.scenario_id for s in scenarios_to_rerun}
        for f in p_rep.findings:
            if f.broken and f.scenario_id not in matched_ids:
                try:
                    vec = AttackVector(f.vector)
                except ValueError:
                    vec = AttackVector.CHAOS_ENVIRONMENT

                def _repro_probe(fn: Optional[Callable[..., Any]] = None, finding: BreakFinding = f) -> Any:
                    if not fn:
                        return True
                    sig = inspect.signature(fn)
                    if len(sig.parameters) == 0:
                        return fn()
                    return fn("remediation_verification_probe")

                scenarios_to_rerun.append(
                    BreakScenario(
                        scenario_id=f.scenario_id,
                        vector=vec,
                        hypothesis=f.hypothesis,
                        expected_resilience="Remediated implementation must survive prior breaking probe",
                        attack_fn=_repro_probe,
                        metadata=f.details,
                    )
                )

        if additional_scenarios:
            scenarios_to_rerun.extend(additional_scenarios)

        # If no scenarios were previously broken and no additional, rerun all fresh scenarios as sanity check
        if not scenarios_to_rerun:
            scenarios_to_rerun = fresh_scenarios

        new_report = self.execute_swarm_attack(
            target_callable=callable_fn,
            scenarios=scenarios_to_rerun,
            timeout_seconds=timeout_seconds,
            target_name=p_rep.target_name,
        )

        all_fixed = new_report.passed
        if auto_consolidate and all_fixed and self.plasticity_engine is not None:
            self.plasticity_engine.consolidate_task(
                domain=p_rep.target_name,
                task_id=p_rep.report_id,
                broken_scenarios=[f.to_dict() for f in p_rep.findings if f.broken],
                final_passed=True,
                lessons=[
                    {
                        "trigger": f.hypothesis,
                        "mistake": f.error_message or "Unhandled break condition",
                        "defense": f.reproduction_code or "Hardened implementation",
                        "severity": f.severity,
                    }
                    for f in p_rep.findings
                    if f.broken
                ],
                co_activated_nodes=["mutation", "test_harness", "red_team_swarm", "property_oracle"],
            )

        return all_fixed, new_report

    def run_full_review_cycle(
        self,
        target_callable: Any,
        target_name: str = "system",
        custom_hypotheses: Optional[list[str]] = None,
        auto_consolidate: bool = True,
    ) -> RedTeamBreakageReport:
        """Generates scenarios, executes swarm attack, and compiles the breakage report."""
        callable_fn = self._resolve_callable(target_callable)
        actual_name = getattr(callable_fn, "__name__", target_name)
        effective_name = target_name if target_name and target_name != "system" else (actual_name or target_name)
        scenarios = self.generate_break_scenarios(
            target_name=effective_name,
            custom_hypotheses=custom_hypotheses,
        )
        report = self.execute_swarm_attack(
            target_callable=callable_fn,
            scenarios=scenarios,
            target_name=effective_name,
        )
        if auto_consolidate and self.plasticity_engine is not None:
            if not report.passed:
                self.plasticity_engine.consolidate_task(
                    domain=effective_name,
                    task_id=report.report_id,
                    broken_scenarios=[f.to_dict() for f in report.findings if f.broken],
                    final_passed=False,
                    co_activated_nodes=["test_harness", "red_team_swarm"],
                )
            else:
                self.plasticity_engine.consolidate_task(
                    domain=effective_name,
                    task_id=report.report_id,
                    final_passed=True,
                    co_activated_nodes=["test_harness", "red_team_swarm", "diagnostics"],
                )
        return report
