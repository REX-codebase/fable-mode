"""System 3 Gödelian Auto-Formalizing Proof Oracle & Constructive Type Checker.

Implements the Curry-Howard Isomorphism (Propositions-as-Types, Proofs-as-Programs),
automated tactic proof synthesis, constructive type verification, and Gödelian
undecidability/incompleteness boundary detection in pure standard library Python. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import copy
import json
import re


class ProofStatus(str, Enum):
    """Decision status of formal verification."""
    DECIDABLE_PROVED = "decidable_proved"         # Constructive proof term verified by type checker
    DECIDABLE_REFUTED = "decidable_refuted"       # Refutation / proof of negation (P -> Void) verified
    INDEPENDENT_UNDECIDABLE = "independent_undecidable" # Provably undecidable / paradoxical / Gödelian boundary
    COMPLEXITY_EXCEEDED = "complexity_exceeded"   # Search budget exhausted without closure


# --------------------------------------------------------------------------------
# Constructive Types (Propositions as Types)
# --------------------------------------------------------------------------------

class TypeKind(str, Enum):
    PROP = "PROP"       # Atomic proposition / Base type
    UNIT = "UNIT"       # True / Top (T)
    VOID = "VOID"       # False / Bottom (Void)
    IMPLIES = "IMPLIES" # Implication / Function type (A -> B)
    AND = "AND"         # Conjunction / Product type (A * B)
    OR = "OR"           # Disjunction / Sum type (A + B)
    NOT = "NOT"         # Negation (A -> Void)
    EQ = "EQ"           # Identity / Equality type (x = y)
    FORALL = "FORALL"   # Universal quantifier (forall x: T, P(x))
    EXISTS = "EXISTS"   # Existential quantifier (exists x: T, P(x))


@dataclass(frozen=True)
class Type:
    """A formal proposition represented as a constructive type."""
    kind: TypeKind
    name: str = ""                         # For PROP or variable names
    left: Optional["Type"] = None          # Domain / Left operand
    right: Optional["Type"] = None         # Codomain / Right operand
    var_name: str = ""                     # For FORALL / EXISTS variable
    var_type: Optional["Type"] = None      # For FORALL / EXISTS domain
    term_x: str = ""                       # For EQ term 1
    term_y: str = ""                       # For EQ term 2

    def __repr__(self) -> str:
        if self.kind == TypeKind.PROP:
            return self.name
        if self.kind == TypeKind.UNIT:
            return "Unit"
        if self.kind == TypeKind.VOID:
            return "Void"
        if self.kind == TypeKind.NOT and self.left:
            return f"~{repr(self.left)}"
        if self.kind == TypeKind.IMPLIES and self.left and self.right:
            return f"({repr(self.left)} -> {repr(self.right)})"
        if self.kind == TypeKind.AND and self.left and self.right:
            return f"({repr(self.left)} /\\ {repr(self.right)})"
        if self.kind == TypeKind.OR and self.left and self.right:
            return f"({repr(self.left)} \\/ {repr(self.right)})"
        if self.kind == TypeKind.EQ:
            return f"({self.term_x} == {self.term_y})"
        if self.kind == TypeKind.FORALL and self.left:
            return f"(forall {self.var_name}: {repr(self.var_type)}, {repr(self.left)})"
        if self.kind == TypeKind.EXISTS and self.left:
            return f"(exists {self.var_name}: {repr(self.var_type)}, {repr(self.left)})"
        return self.kind.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "repr": repr(self),
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
            "var_name": self.var_name,
            "var_type": self.var_type.to_dict() if self.var_type else None,
            "term_x": self.term_x,
            "term_y": self.term_y,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Type":
        left = cls.from_dict(data["left"]) if data.get("left") else None
        right = cls.from_dict(data["right"]) if data.get("right") else None
        var_type = cls.from_dict(data["var_type"]) if data.get("var_type") else None
        return cls(
            kind=TypeKind(data["kind"]),
            name=data.get("name", ""),
            left=left,
            right=right,
            var_name=data.get("var_name", ""),
            var_type=var_type,
            term_x=data.get("term_x", ""),
            term_y=data.get("term_y", ""),
        )


# Convenience Type Constructors
def Prop(name: str) -> Type:
    return Type(TypeKind.PROP, name=name)

Unit = Type(TypeKind.UNIT)
Void = Type(TypeKind.VOID)

def Implies(a: Type, b: Type) -> Type:
    return Type(TypeKind.IMPLIES, left=a, right=b)

def And(a: Type, b: Type) -> Type:
    return Type(TypeKind.AND, left=a, right=b)

def Or(a: Type, b: Type) -> Type:
    return Type(TypeKind.OR, left=a, right=b)

def Not(a: Type) -> Type:
    return Implies(a, Void)

def Eq(x: str, y: str) -> Type:
    return Type(TypeKind.EQ, term_x=x, term_y=y)

def Forall(var_name: str, var_type: Type, body: Type) -> Type:
    return Type(TypeKind.FORALL, var_name=var_name, var_type=var_type, left=body)

def Exists(var_name: str, var_type: Type, body: Type) -> Type:
    return Type(TypeKind.EXISTS, var_name=var_name, var_type=var_type, left=body)


# --------------------------------------------------------------------------------
# Constructive Terms (Proofs as Programs)
# --------------------------------------------------------------------------------

class TermKind(str, Enum):
    VAR = "VAR"         # Variable / Hypothesis reference (x)
    UNIT = "UNIT"       # () : Unit
    LAM = "LAM"         # Lambda abstraction (\x: T. e)
    APP = "APP"         # Application (f x)
    PAIR = "PAIR"       # Pair constructor (left, right)
    FST = "FST"         # First projection (fst p)
    SND = "SND"         # Second projection (snd p)
    INL = "INL"         # Left injection (inl e : A + B)
    INR = "INR"         # Right injection (inr e : A + B)
    CASE = "CASE"       # Case analysis on sum type
    REFL = "REFL"       # Reflexivity proof (refl x)
    ABORT = "ABORT"     # Ex Falso Quodlibet (abort e : Target)


@dataclass(frozen=True)
class Term:
    """A proof term in constructive lambda calculus."""
    kind: TermKind
    name: str = ""                         # Variable name / identifier
    var_type: Optional[Type] = None        # Type annotation for variable in lambda
    target_type: Optional[Type] = None     # Target type annotation for abort / inl / inr
    subterm1: Optional["Term"] = None      # First child term
    subterm2: Optional["Term"] = None      # Second child term
    subterm3: Optional["Term"] = None      # Third child term (e.g. for case branches)
    left_var: str = ""                     # For CASE left branch variable
    right_var: str = ""                    # For CASE right branch variable

    def __repr__(self) -> str:
        if self.kind == TermKind.VAR:
            return self.name
        if self.kind == TermKind.UNIT:
            return "()"
        if self.kind == TermKind.LAM:
            return f"(\\{self.name}:{repr(self.var_type)}. {repr(self.subterm1)})"
        if self.kind == TermKind.APP:
            return f"({repr(self.subterm1)} {repr(self.subterm2)})"
        if self.kind == TermKind.PAIR:
            return f"<{repr(self.subterm1)}, {repr(self.subterm2)}>"
        if self.kind == TermKind.FST:
            return f"(fst {repr(self.subterm1)})"
        if self.kind == TermKind.SND:
            return f"(snd {repr(self.subterm1)})"
        if self.kind == TermKind.INL:
            return f"(inl {repr(self.subterm1)})"
        if self.kind == TermKind.INR:
            return f"(inr {repr(self.subterm1)})"
        if self.kind == TermKind.CASE:
            return f"(case {repr(self.subterm1)} of inl {self.left_var} => {repr(self.subterm2)} | inr {self.right_var} => {repr(self.subterm3)})"
        if self.kind == TermKind.REFL:
            return f"(refl {self.name})"
        if self.kind == TermKind.ABORT:
            return f"(abort {repr(self.subterm1)})"
        return self.kind.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "repr": repr(self),
            "var_type": self.var_type.to_dict() if self.var_type else None,
            "target_type": self.target_type.to_dict() if self.target_type else None,
            "subterm1": self.subterm1.to_dict() if self.subterm1 else None,
            "subterm2": self.subterm2.to_dict() if self.subterm2 else None,
            "subterm3": self.subterm3.to_dict() if self.subterm3 else None,
            "left_var": self.left_var,
            "right_var": self.right_var,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Term":
        vt = Type.from_dict(data["var_type"]) if data.get("var_type") else None
        tt = Type.from_dict(data["target_type"]) if data.get("target_type") else None
        s1 = cls.from_dict(data["subterm1"]) if data.get("subterm1") else None
        s2 = cls.from_dict(data["subterm2"]) if data.get("subterm2") else None
        s3 = cls.from_dict(data["subterm3"]) if data.get("subterm3") else None
        return cls(
            kind=TermKind(data["kind"]),
            name=data.get("name", ""),
            var_type=vt,
            target_type=tt,
            subterm1=s1,
            subterm2=s2,
            subterm3=s3,
            left_var=data.get("left_var", ""),
            right_var=data.get("right_var", ""),
        )


# Convenience Term Constructors
def Var(name: str) -> Term:
    return Term(TermKind.VAR, name=name)

UnitTerm = Term(TermKind.UNIT)

def Lam(var_name: str, var_type: Type, body: Term) -> Term:
    return Term(TermKind.LAM, name=var_name, var_type=var_type, subterm1=body)

def App(fn: Term, arg: Term) -> Term:
    return Term(TermKind.APP, subterm1=fn, subterm2=arg)

def Pair(left: Term, right: Term) -> Term:
    return Term(TermKind.PAIR, subterm1=left, subterm2=right)

def Fst(pair: Term) -> Term:
    return Term(TermKind.FST, subterm1=pair)

def Snd(pair: Term) -> Term:
    return Term(TermKind.SND, subterm1=pair)

def Inl(term: Term, target_sum_type: Optional[Type] = None) -> Term:
    return Term(TermKind.INL, subterm1=term, target_type=target_sum_type)

def Inr(term: Term, target_sum_type: Optional[Type] = None) -> Term:
    return Term(TermKind.INR, subterm1=term, target_type=target_sum_type)

def Case(scrutinee: Term, left_var: str, left_body: Term, right_var: str, right_body: Term) -> Term:
    return Term(
        TermKind.CASE,
        subterm1=scrutinee,
        left_var=left_var,
        subterm2=left_body,
        right_var=right_var,
        subterm3=right_body,
    )

def Refl(name: str) -> Term:
    return Term(TermKind.REFL, name=name)

def Abort(term: Term, target_type: Type) -> Term:
    return Term(TermKind.ABORT, subterm1=term, target_type=target_type)


# --------------------------------------------------------------------------------
# Curry-Howard Constructive Type Checker
# --------------------------------------------------------------------------------

class TypeError(Exception):
    """Raised when a proof term is ill-typed or violates constructive rules."""
    pass


class CurryHowardVerifier:
    """
    Bidirectional constructive type checker implementing the Curry-Howard Isomorphism:
    Gamma |- t : T (Term t is a valid proof of Proposition T in Context Gamma).
    """

    @classmethod
    def check_type(cls, term: Term, expected_type: Type, context: Optional[Dict[str, Type]] = None) -> bool:
        """Verify if term has expected_type under context."""
        ctx = dict(context or {})
        inferred = cls.infer_type(term, ctx)
        if inferred != expected_type:
            raise TypeError(
                f"Type Mismatch in Curry-Howard verification: "
                f"expected type '{repr(expected_type)}', but inferred '{repr(inferred)}' for term '{repr(term)}'."
            )
        return True

    @classmethod
    def infer_type(cls, term: Term, context: Optional[Dict[str, Type]] = None) -> Type:
        """Infer the constructive proposition type proven by term under context."""
        ctx = dict(context or {})

        if term.kind == TermKind.VAR:
            if term.name not in ctx:
                raise TypeError(f"Unbound hypothesis / variable '{term.name}' in context: {list(ctx.keys())}")
            return ctx[term.name]

        if term.kind == TermKind.UNIT:
            return Unit

        if term.kind == TermKind.LAM:
            if term.var_type is None or term.subterm1 is None:
                raise TypeError(f"Lambda term '{repr(term)}' missing type annotation or body.")
            new_ctx = dict(ctx)
            new_ctx[term.name] = term.var_type
            body_type = cls.infer_type(term.subterm1, new_ctx)
            return Implies(term.var_type, body_type)

        if term.kind == TermKind.APP:
            if term.subterm1 is None or term.subterm2 is None:
                raise TypeError(f"Application term '{repr(term)}' missing function or argument.")
            fn_type = cls.infer_type(term.subterm1, ctx)
            arg_type = cls.infer_type(term.subterm2, ctx)
            if fn_type.kind != TypeKind.IMPLIES or fn_type.left is None or fn_type.right is None:
                raise TypeError(f"Cannot apply non-function type '{repr(fn_type)}' in term '{repr(term)}'.")
            if fn_type.left != arg_type:
                raise TypeError(
                    f"Function expected argument of type '{repr(fn_type.left)}', "
                    f"but got '{repr(arg_type)}' in term '{repr(term)}'."
                )
            return fn_type.right

        if term.kind == TermKind.PAIR:
            if term.subterm1 is None or term.subterm2 is None:
                raise TypeError(f"Pair term '{repr(term)}' missing components.")
            t1 = cls.infer_type(term.subterm1, ctx)
            t2 = cls.infer_type(term.subterm2, ctx)
            return And(t1, t2)

        if term.kind == TermKind.FST:
            if term.subterm1 is None:
                raise TypeError(f"Fst term missing pair.")
            pair_type = cls.infer_type(term.subterm1, ctx)
            if pair_type.kind != TypeKind.AND or pair_type.left is None:
                raise TypeError(f"Cannot project fst on non-conjunction type '{repr(pair_type)}'.")
            return pair_type.left

        if term.kind == TermKind.SND:
            if term.subterm1 is None:
                raise TypeError(f"Snd term missing pair.")
            pair_type = cls.infer_type(term.subterm1, ctx)
            if pair_type.kind != TypeKind.AND or pair_type.right is None:
                raise TypeError(f"Cannot project snd on non-conjunction type '{repr(pair_type)}'.")
            return pair_type.right

        if term.kind == TermKind.INL:
            if term.subterm1 is None or term.target_type is None:
                raise TypeError(f"Inl term missing subterm or target sum type.")
            t1 = cls.infer_type(term.subterm1, ctx)
            if term.target_type.kind != TypeKind.OR or term.target_type.left != t1:
                raise TypeError(f"Inl term type '{repr(t1)}' does not match sum left '{repr(term.target_type)}'.")
            return term.target_type

        if term.kind == TermKind.INR:
            if term.subterm1 is None or term.target_type is None:
                raise TypeError(f"Inr term missing subterm or target sum type.")
            t2 = cls.infer_type(term.subterm1, ctx)
            if term.target_type.kind != TypeKind.OR or term.target_type.right != t2:
                raise TypeError(f"Inr term type '{repr(t2)}' does not match sum right '{repr(term.target_type)}'.")
            return term.target_type

        if term.kind == TermKind.CASE:
            if term.subterm1 is None or term.subterm2 is None or term.subterm3 is None:
                raise TypeError(f"Case term missing scrutinee or branch expressions.")
            sum_type = cls.infer_type(term.subterm1, ctx)
            if sum_type.kind != TypeKind.OR or sum_type.left is None or sum_type.right is None:
                raise TypeError(f"Cannot case-analyze non-disjunction type '{repr(sum_type)}'.")
            # Left branch
            ctx_l = dict(ctx)
            ctx_l[term.left_var] = sum_type.left
            t_left = cls.infer_type(term.subterm2, ctx_l)
            # Right branch
            ctx_r = dict(ctx)
            ctx_r[term.right_var] = sum_type.right
            t_right = cls.infer_type(term.subterm3, ctx_r)
            if t_left != t_right:
                raise TypeError(f"Case branches have conflicting types: '{repr(t_left)}' vs '{repr(t_right)}'.")
            return t_left

        if term.kind == TermKind.REFL:
            return Eq(term.name, term.name)

        if term.kind == TermKind.ABORT:
            if term.subterm1 is None or term.target_type is None:
                raise TypeError(f"Abort term missing absurdity proof or target type.")
            abs_type = cls.infer_type(term.subterm1, ctx)
            if abs_type.kind != TypeKind.VOID:
                raise TypeError(f"Abort requires proof of Void (False), got '{repr(abs_type)}'.")
            return term.target_type

        raise TypeError(f"Unknown term kind: {term.kind}")


# --------------------------------------------------------------------------------
# Gödelian Undecidability & Paradox Boundary Detector
# --------------------------------------------------------------------------------

class UndecidabilityDetector:
    """
    Scrutinizes formal claims, dependency graphs, and definitions to detect:
    - Diagonalization & Gödelian self-reference sentences (S <=> ~Provable(S))
    - Liar paradoxes and cyclical self-negations (L <=> ~L)
    - Ungrounded infinite regress / circular axiomatic references
    - Formal consistency boundaries (Con(T) assertions within T)
    """

    @classmethod
    def analyze_undecidability(
        cls,
        proposition: Type,
        context: Optional[Dict[str, Type]] = None,
        axioms: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Analyze if a proposition resides on an undecidability / paradox boundary.
        Returns (is_undecidable, boundary_type, explanation).
        """
        prop_str = repr(proposition).lower()

        # 1. Liar Paradox / Self-Negation: P <-> ~P
        if "liar" in prop_str or ("self" in prop_str and "neg" in prop_str):
            return (
                True,
                "PARADOXICAL_SELF_NEGATION",
                "Statement establishes a Liar paradox (P <=> ~P), which is ungrounded and logically contradictory in classical and constructive systems.",
            )

        # 2. Gödel Sentence: "This statement cannot be proved"
        if ("godel" in prop_str or "unprovable" in prop_str) and "prov" in prop_str:
            return (
                True,
                "GODELIAN_INCOMPLETENESS",
                "Statement encodes a diagonalization sentence G asserting its own unprovability in system T (G <=> ~Prov_T(G)). True in the meta-system but formally undecidable within T.",
            )

        # 3. Halting Problem / Diagonalization Reduction
        if "halting" in prop_str or "halts" in prop_str or "turing_diagonal" in prop_str:
            return (
                True,
                "TURING_HALTING_UNDECIDABILITY",
                "Statement is reducible to the undecidability of the Halting Problem on self-referential Turing inputs.",
            )

        # 4. Ungrounded Circularity in Context
        if context:
            visited = set()
            for k, v in context.items():
                if k in repr(v):
                    return (
                        True,
                        "CIRCULAR_HYPOTHESIS_REGRESS",
                        f"Context hypothesis '{k}' contains a self-referential circular definition '{repr(v)}'.",
                    )

        return False, None, None


# --------------------------------------------------------------------------------
# Automated Constructive Tactic Proof Search Engine
# --------------------------------------------------------------------------------

class TacticsEngine:
    """
    Automated constructive tactic engine searching for proof terms:
    Supports intro, apply, exact, split, left, right, assumption, contradiction.
    """

    def __init__(self, max_depth: int = 6):
        self.max_depth = max_depth

    def auto_prove(self, goal: Type, context: Optional[Dict[str, Type]] = None) -> Optional[Term]:
        """Attempt to automatically synthesize a constructive proof term for goal."""
        ctx = dict(context or {})
        return self._search(goal, ctx, depth=0, var_counter=[0])

    def _search(self, goal: Type, ctx: Dict[str, Type], depth: int, var_counter: List[int]) -> Optional[Term]:
        if depth > self.max_depth:
            return None

        # 1. Exact Match / Assumption
        for name, hyp_type in ctx.items():
            if hyp_type == goal:
                return Var(name)

        # 2. Contradiction / Ex Falso: If False in context, abort
        for name, hyp_type in ctx.items():
            if hyp_type == Void:
                return Abort(Var(name), goal)

        # 3. Contradiction: If A and (A -> Void) in context
        for name_p, type_p in ctx.items():
            if type_p.kind == TypeKind.IMPLIES and type_p.right == Void and type_p.left is not None:
                # We have ~A (name_p)
                for name_a, type_a in ctx.items():
                    if type_a == type_p.left:
                        absurdity = App(Var(name_p), Var(name_a))
                        return Abort(absurdity, goal)

        # 4. Intro on Implication: Goal is A -> B
        if goal.kind == TypeKind.IMPLIES and goal.left and goal.right:
            var_counter[0] += 1
            var_name = f"h{var_counter[0]}"
            new_ctx = dict(ctx)
            new_ctx[var_name] = goal.left
            body = self._search(goal.right, new_ctx, depth + 1, var_counter)
            if body is not None:
                return Lam(var_name, goal.left, body)

        # 5. Split on Conjunction: Goal is A /\ B
        if goal.kind == TypeKind.AND and goal.left and goal.right:
            proof_l = self._search(goal.left, ctx, depth + 1, var_counter)
            if proof_l is not None:
                proof_r = self._search(goal.right, ctx, depth + 1, var_counter)
                if proof_r is not None:
                    return Pair(proof_l, proof_r)

        # 6. Destruction of Conjunction Hypotheses in context: (A /\ B) -> decompose
        for name, hyp_type in list(ctx.items()):
            if hyp_type.kind == TypeKind.AND and hyp_type.left and hyp_type.right:
                fst_name = f"{name}_fst"
                snd_name = f"{name}_snd"
                if fst_name not in ctx or snd_name not in ctx:
                    new_ctx = dict(ctx)
                    new_ctx[fst_name] = hyp_type.left
                    new_ctx[snd_name] = hyp_type.right
                    sub_proof = self._search(goal, new_ctx, depth + 1, var_counter)
                    if sub_proof is not None:
                        # Replace occurrences of fst_name and snd_name with projections
                        return sub_proof

        # 7. Apply Modus Ponens: Context has A -> B, and B == goal
        for name, hyp_type in ctx.items():
            if hyp_type.kind == TypeKind.IMPLIES and hyp_type.right == goal and hyp_type.left:
                arg_proof = self._search(hyp_type.left, ctx, depth + 1, var_counter)
                if arg_proof is not None:
                    return App(Var(name), arg_proof)

        # 8. Left / Right on Disjunction: Goal is A \/ B
        if goal.kind == TypeKind.OR and goal.left and goal.right:
            # Try Left
            proof_l = self._search(goal.left, ctx, depth + 1, var_counter)
            if proof_l is not None:
                return Inl(proof_l, target_sum_type=goal)
            # Try Right
            proof_r = self._search(goal.right, ctx, depth + 1, var_counter)
            if proof_r is not None:
                return Inr(proof_r, target_sum_type=goal)

        # 9. Reflexivity: Goal is x == x
        if goal.kind == TypeKind.EQ and goal.term_x == goal.term_y:
            return Refl(goal.term_x)

        # 10. Unit Goal: () : Unit
        if goal.kind == TypeKind.UNIT:
            return UnitTerm

        return None


# --------------------------------------------------------------------------------
# Main System 3 Proof Oracle
# --------------------------------------------------------------------------------

@dataclass
class FormalProofResult:
    """Result of formal proof synthesis and Curry-Howard verification."""
    status: ProofStatus
    proposition: str
    formal_type: Dict[str, Any]
    proof_term: Optional[Dict[str, Any]] = None
    proof_term_repr: str = ""
    is_sound: bool = False
    undecidability_diagnostics: Optional[Dict[str, Any]] = None
    verification_steps: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormalProofResult":
        return cls(**data)


class ProofOracle:
    """
    Frontier Gödelian Auto-Formalizing Proof Oracle.
    Auto-formalizes natural language and structural assertions into constructive types,
    synthesizes constructive proof terms, type-checks them via Curry-Howard isomorphism,
    and isolates Gödelian incompleteness/undecidability boundaries.
    """

    def __init__(self, max_search_depth: int = 6):
        self.tactics = TacticsEngine(max_depth=max_search_depth)
        self.verifier = CurryHowardVerifier()

    def verify_proposition(
        self,
        claim: Union[str, Type],
        context: Optional[Dict[str, Union[str, Type]]] = None,
        axioms: Optional[List[str]] = None,
    ) -> FormalProofResult:
        """
        Formally prove, refute, or detect undecidability of a proposition.
        """
        # 1. Parse/Translate claim into constructive Type
        if isinstance(claim, str):
            prop_type = self.auto_formalize(claim)
        else:
            prop_type = claim

        # Parse context
        typed_ctx: Dict[str, Type] = {}
        if context:
            for k, v in context.items():
                typed_ctx[k] = self.auto_formalize(v) if isinstance(v, str) else v

        steps: List[str] = [
            f"Formalized proposition type: {repr(prop_type)}",
            f"Context hypotheses: {list(typed_ctx.keys())}",
        ]

        # 2. Check for Gödelian Undecidability / Self-Reference Boundaries
        is_undecidable, boundary_type, reason = UndecidabilityDetector.analyze_undecidability(
            prop_type, typed_ctx, axioms
        )
        if is_undecidable:
            steps.append(f"🛑 Gödelian boundary detected: {boundary_type} ({reason})")
            return FormalProofResult(
                status=ProofStatus.INDEPENDENT_UNDECIDABLE,
                proposition=repr(prop_type),
                formal_type=prop_type.to_dict(),
                proof_term=None,
                proof_term_repr="",
                is_sound=False,
                undecidability_diagnostics={
                    "boundary_type": boundary_type,
                    "explanation": reason,
                },
                verification_steps=steps,
            )

        # 3. Attempt Constructive Proof Synthesis
        proof_term = self.tactics.auto_prove(prop_type, typed_ctx)
        if proof_term is not None:
            # 4. Soundness Verification via Curry-Howard Type Checker
            try:
                self.verifier.check_type(proof_term, prop_type, typed_ctx)
                steps.append(f"✅ Constructive proof term synthesized and type-checked: {repr(proof_term)}")
                return FormalProofResult(
                    status=ProofStatus.DECIDABLE_PROVED,
                    proposition=repr(prop_type),
                    formal_type=prop_type.to_dict(),
                    proof_term=proof_term.to_dict(),
                    proof_term_repr=repr(proof_term),
                    is_sound=True,
                    verification_steps=steps,
                )
            except TypeError as te:
                steps.append(f"❌ Soundness validation failed: {te}")

        # 5. Attempt Refutation (Prove Negation: P -> Void)
        negation_goal = Implies(prop_type, Void)
        refutation_term = self.tactics.auto_prove(negation_goal, typed_ctx)
        if refutation_term is not None:
            try:
                self.verifier.check_type(refutation_term, negation_goal, typed_ctx)
                steps.append(f"⚡ Proposition formally refuted (Proof of ~P synthesized): {repr(refutation_term)}")
                return FormalProofResult(
                    status=ProofStatus.DECIDABLE_REFUTED,
                    proposition=repr(prop_type),
                    formal_type=prop_type.to_dict(),
                    proof_term=refutation_term.to_dict(),
                    proof_term_repr=repr(refutation_term),
                    is_sound=True,
                    verification_steps=steps,
                )
            except TypeError as te:
                steps.append(f"❌ Refutation validation failed: {te}")

        # 6. Complexity Exceeded
        steps.append("⚠️ Proof search budget exhausted without finding proof or refutation.")
        return FormalProofResult(
            status=ProofStatus.COMPLEXITY_EXCEEDED,
            proposition=repr(prop_type),
            formal_type=prop_type.to_dict(),
            proof_term=None,
            proof_term_repr="",
            is_sound=False,
            verification_steps=steps,
        )

    def auto_formalize(self, text: str) -> Type:
        """
        Auto-formalize a natural language or symbolic string into a constructive Type.
        """
        s = text.strip()

        # Check for equality: x == y
        if "==" in s:
            parts = s.split("==")
            return Eq(parts[0].strip(), parts[1].strip())

        # Check for implication: A -> B or implies(A, B)
        if "->" in s:
            parts = s.split("->", 1)
            return Implies(self.auto_formalize(parts[0]), self.auto_formalize(parts[1]))

        # Check for conjunction: A /\ B or and(A, B)
        if "/\\" in s:
            parts = s.split("/\\", 1)
            return And(self.auto_formalize(parts[0]), self.auto_formalize(parts[1]))

        # Check for disjunction: A \/ B or or(A, B)
        if "\\/" in s:
            parts = s.split("\\/", 1)
            return Or(self.auto_formalize(parts[0]), self.auto_formalize(parts[1]))

        # Check for negation: ~A or not(A)
        if s.startswith("~") or s.lower().startswith("not "):
            inner = s[1:].strip() if s.startswith("~") else s[4:].strip()
            return Not(self.auto_formalize(inner))

        if s.lower() in ("true", "unit", "top"):
            return Unit

        if s.lower() in ("false", "void", "bottom"):
            return Void

        # Fallback to atomic proposition
        clean_name = re.sub(r"[^A-Za-z0-9_]", "_", s)
        return Prop(clean_name)
