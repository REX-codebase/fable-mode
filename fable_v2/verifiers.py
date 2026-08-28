"""Composable verifier contracts for Fable V2.

Deterministic verifiers should run before model-based judges.  A verifier may
be backed by tests, a compiler, a citation checker, a schema validator, or an
independent model; the runtime only accepts explicit VerificationResult data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from .protocol import Candidate, VerificationResult


class Verifier(Protocol):
    name: str

    def verify(self, candidate: Candidate) -> VerificationResult:
        ...


@dataclass(frozen=True)
class FunctionVerifier:
    """Adapt a deterministic function into a registered verifier.

    The function returns ``(passed, reasons, score)``.  It is deliberately
    dependency-free so hosts can wrap compilers, tests, schemas, or API calls.
    Trust is assigned by the application registering the verifier, never by a
    model-facing result.
    """

    name: str
    check: Callable[[Candidate], tuple[bool, Iterable[str], float | None]]
    verifier_class: str = "deterministic"
    independent: bool = False
    trusted: bool = True

    def verify(self, candidate: Candidate) -> VerificationResult:
        passed, reasons, score = self.check(candidate)
        return VerificationResult(
            verification_id=f"{self.name}:{candidate.candidate_id}",
            session_id=candidate.session_id,
            candidate_id=candidate.candidate_id,
            verifier=self.name,
            passed=bool(passed),
            reasons=tuple(str(reason) for reason in reasons),
            score=score,
        )


@dataclass(frozen=True)
class CompositeVerifier:
    """Run a list of verifiers and require every one to pass."""

    verifiers: tuple[Verifier, ...]

    @property
    def name(self) -> str:
        return "composite[" + ",".join(v.name for v in self.verifiers) + "]"

    def verify_all(self, candidate: Candidate) -> tuple[VerificationResult, ...]:
        return tuple(verifier.verify(candidate) for verifier in self.verifiers)

    def passed(self, candidate: Candidate) -> bool:
        results = self.verify_all(candidate)
        return bool(results) and all(result.passed for result in results)
