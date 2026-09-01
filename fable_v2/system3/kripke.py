"""System 3 Kripke Modal Model Checker & Multi-World Branching Semantics.

Implements Kripke multi-world structures, modal logic operators (Box, Diamond),
and Computational Tree Logic (CTL/CTL*) temporal operators (AG, EF, AF, AX, EX, EG, AU, EU)
with fixed-point state satisfaction, witness/counterexample path generation, and
AST formula parsing in pure standard library Python. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import copy
import json
import re


class CTLOperator(str, Enum):
    """CTL Temporal and Modal Logic Operators."""
    ATOM = "ATOM"
    TRUE = "TRUE"
    FALSE = "FALSE"
    NOT = "NOT"
    AND = "AND"
    OR = "OR"
    IMPLIES = "IMPLIES"
    EX = "EX"          # Exists Next
    AX = "AX"          # All Next
    EF = "EF"          # Exists Finally (Reachability)
    AF = "AF"          # All Finally (Liveness)
    EG = "EG"          # Exists Globally (Persistence)
    AG = "AG"          # All Globally (Safety Invariant)
    EU = "EU"          # Exists Until (E[p U q])
    AU = "AU"          # All Until (A[p U q])
    BOX = "BOX"        # Modal Necessity (Box p)
    DIAMOND = "DIAMOND"# Modal Possibility (Diamond p)


@dataclass
class FormulaNode:
    """Abstract Syntax Tree node for CTL / Modal logic formulas."""
    op: CTLOperator
    name: str = ""                         # Atomic proposition name if ATOM
    left: Optional["FormulaNode"] = None    # Subformula / Left operand
    right: Optional["FormulaNode"] = None   # Right operand (for AND, OR, IMPLIES, EU, AU)

    def to_string(self) -> str:
        if self.op == CTLOperator.ATOM:
            return self.name
        if self.op == CTLOperator.TRUE:
            return "true"
        if self.op == CTLOperator.FALSE:
            return "false"
        if self.op == CTLOperator.NOT and self.left:
            return f"not({self.left.to_string()})"
        if self.op in (CTLOperator.AND, CTLOperator.OR, CTLOperator.IMPLIES) and self.left and self.right:
            return f"{self.op.value.lower()}({self.left.to_string()}, {self.right.to_string()})"
        if self.op in (CTLOperator.EX, CTLOperator.AX, CTLOperator.EF, CTLOperator.AF, CTLOperator.EG, CTLOperator.AG, CTLOperator.BOX, CTLOperator.DIAMOND) and self.left:
            return f"{self.op.value}({self.left.to_string()})"
        if self.op in (CTLOperator.EU, CTLOperator.AU) and self.left and self.right:
            return f"{self.op.value[0]}[{self.left.to_string()} U {self.right.to_string()}]"
        return f"{self.op.value}"


@dataclass
class KripkeWorld:
    """A world/state in the Kripke structure."""
    world_id: str
    name: str = ""
    propositions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_prop(self, prop: str) -> bool:
        return prop in self.propositions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "world_id": self.world_id,
            "name": self.name or self.world_id,
            "propositions": sorted(list(self.propositions)),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KripkeWorld":
        return cls(
            world_id=data["world_id"],
            name=data.get("name", data["world_id"]),
            propositions=set(data.get("propositions", [])),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ModelCheckResult:
    """Result of Kripke model checking evaluation."""
    formula: str
    is_satisfied: bool
    initial_world: str
    satisfied_worlds: List[str] = field(default_factory=list)
    violated_worlds: List[str] = field(default_factory=list)
    total_worlds: int = 0
    counterexample_path: Optional[List[str]] = None
    witness_path: Optional[List[str]] = None
    details: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelCheckResult":
        return cls(**data)


class KripkeStructure:
    """
    Kripke Model M = (W, R, L, W0)
    - W: Set of Worlds/States
    - R: Transition / Accessibility Relation W -> P(W)
    - L: Valuation / Labeling Function W -> P(AP)
    - W0: Initial Worlds
    """

    def __init__(self, name: str = "KripkeModel"):
        self.name = name
        self.worlds: Dict[str, KripkeWorld] = {}
        self.transitions: Dict[str, Set[str]] = {}
        self.inverse_transitions: Dict[str, Set[str]] = {}
        self.initial_worlds: Set[str] = set()

    def add_world(
        self,
        world_id: str,
        propositions: Optional[Sequence[str]] = None,
        name: str = "",
        is_initial: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KripkeWorld:
        """Add a world state with its atomic propositions."""
        props = set(propositions or [])
        world = KripkeWorld(
            world_id=world_id,
            name=name or world_id,
            propositions=props,
            metadata=metadata or {},
        )
        self.worlds[world_id] = world
        if world_id not in self.transitions:
            self.transitions[world_id] = set()
        if world_id not in self.inverse_transitions:
            self.inverse_transitions[world_id] = set()
        if is_initial or not self.initial_worlds:
            self.initial_worlds.add(world_id)
        return world

    def add_transition(self, source: str, target: str):
        """Add directed transition / accessibility relation from source to target."""
        if source not in self.worlds:
            self.add_world(source)
        if target not in self.worlds:
            self.add_world(target)
        self.transitions[source].add(target)
        self.inverse_transitions[target].add(source)

    def get_successors(self, world_id: str) -> Set[str]:
        return self.transitions.get(world_id, set())

    def get_predecessors(self, world_id: str) -> Set[str]:
        return self.inverse_transitions.get(world_id, set())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "worlds": {k: v.to_dict() for k, v in self.worlds.items()},
            "transitions": {k: sorted(list(v)) for k, v in self.transitions.items()},
            "initial_worlds": sorted(list(self.initial_worlds)),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KripkeStructure":
        ks = cls(name=data.get("name", "KripkeModel"))
        for wid, wdata in data.get("worlds", {}).items():
            ks.add_world(
                world_id=wid,
                propositions=wdata.get("propositions", []),
                name=wdata.get("name", wid),
                metadata=wdata.get("metadata", {}),
            )
        for src, targets in data.get("transitions", {}).items():
            for tgt in targets:
                ks.add_transition(src, tgt)
        if "initial_worlds" in data:
            ks.initial_worlds = set(data["initial_worlds"])
        return ks


class FormulaParser:
    """
    Recursive parser for CTL and Modal logic formula strings.
    Supported syntaxes:
      - Atomic: "safe", "error", "p"
      - Constants: "true", "false"
      - Boolean: "not(p)", "and(p, q)", "or(p, q)", "implies(p, q)"
      - Modal: "box(p)", "diamond(p)", "[](p)", "<>(p)"
      - Temporal: "AG(p)", "AF(p)", "EF(p)", "EG(p)", "AX(p)", "EX(p)"
      - Until: "E[p U q]", "A[p U q]", "EU(p, q)", "AU(p, q)"
    """

    @classmethod
    def parse(cls, expr: str) -> FormulaNode:
        s = expr.strip()
        if not s:
            return FormulaNode(CTLOperator.TRUE)

        # True / False
        if s.lower() == "true":
            return FormulaNode(CTLOperator.TRUE)
        if s.lower() == "false":
            return FormulaNode(CTLOperator.FALSE)

        # Modal shortcut symbols
        if s.startswith("[](") and s.endswith(")"):
            return FormulaNode(CTLOperator.BOX, left=cls.parse(s[3:-1]))
        if s.startswith("<>(") and s.endswith(")"):
            return FormulaNode(CTLOperator.DIAMOND, left=cls.parse(s[3:-1]))

        # Functional syntax: AG(...), EF(...), etc.
        m_func = re.match(r"^([A-Za-z0-9_]+)\s*\((.*)\)$", s, re.DOTALL)
        if m_func:
            op_name = m_func.group(1).upper()
            inner = m_func.group(2).strip()

            if op_name in ("NOT", "NEG"):
                return FormulaNode(CTLOperator.NOT, left=cls.parse(inner))
            if op_name in ("BOX", "NECESSARY"):
                return FormulaNode(CTLOperator.BOX, left=cls.parse(inner))
            if op_name in ("DIAMOND", "POSSIBLE"):
                return FormulaNode(CTLOperator.DIAMOND, left=cls.parse(inner))
            if op_name in ("AG", "AF", "EF", "EG", "AX", "EX"):
                return FormulaNode(CTLOperator[op_name], left=cls.parse(inner))

            if op_name in ("AND", "OR", "IMPLIES", "EU", "AU"):
                args = cls._split_top_level_args(inner)
                if len(args) == 2:
                    return FormulaNode(
                        CTLOperator[op_name],
                        left=cls.parse(args[0]),
                        right=cls.parse(args[1]),
                    )

        # Bracketed Until syntax: E[p U q] or A[p U q]
        m_until = re.match(r"^([EA])\s*\[\s*(.*?)\s+[Uu]\s+(.*?)\s*\]$", s)
        if m_until:
            quant = m_until.group(1).upper()
            left_expr = m_until.group(2)
            right_expr = m_until.group(3)
            op = CTLOperator.EU if quant == "E" else CTLOperator.AU
            return FormulaNode(op, left=cls.parse(left_expr), right=cls.parse(right_expr))

        # Default: Atomic Proposition
        return FormulaNode(CTLOperator.ATOM, name=s)

    @classmethod
    def _split_top_level_args(cls, s: str) -> List[str]:
        args = []
        depth_paren = 0
        depth_bracket = 0
        curr = []
        for ch in s:
            if ch == "(":
                depth_paren += 1
                curr.append(ch)
            elif ch == ")":
                depth_paren -= 1
                curr.append(ch)
            elif ch == "[":
                depth_bracket += 1
                curr.append(ch)
            elif ch == "]":
                depth_bracket -= 1
                curr.append(ch)
            elif ch == "," and depth_paren == 0 and depth_bracket == 0:
                args.append("".join(curr).strip())
                curr = []
            else:
                curr.append(ch)
        if curr:
            args.append("".join(curr).strip())
        return args


class KripkeModelChecker:
    """
    Fixed-point CTL and Modal Logic Model Checker for Kripke Structures.
    Computes exact state satisfaction sets Sat(phi) and generates witness/counterexample traces.
    """

    def __init__(self, structure: KripkeStructure):
        self.kripke = structure

    def check(
        self,
        formula: Union[str, FormulaNode],
        initial_world: Optional[str] = None,
    ) -> ModelCheckResult:
        """
        Verify if Kripke structure satisfies formula starting from initial world.
        """
        if isinstance(formula, str):
            ast = FormulaParser.parse(formula)
            formula_str = formula
        else:
            ast = formula
            formula_str = ast.to_string()

        sat_worlds = self.sat(ast)
        all_worlds = set(self.kripke.worlds.keys())
        violated_worlds = sorted(list(all_worlds - sat_worlds))

        init_w = initial_world or (list(self.kripke.initial_worlds)[0] if self.kripke.initial_worlds else None)
        if init_w is None and self.kripke.worlds:
            init_w = list(self.kripke.worlds.keys())[0]

        is_satisfied = init_w in sat_worlds if init_w else False

        # Generate Counterexample or Witness paths
        counterexample = None
        witness = None

        if not is_satisfied and init_w:
            counterexample = self._generate_counterexample(ast, init_w, sat_worlds)
        elif is_satisfied and init_w:
            witness = self._generate_witness(ast, init_w, sat_worlds)

        details = (
            f"Formula '{formula_str}' is {'SATISFIED' if is_satisfied else 'VIOLATED'} "
            f"at initial world '{init_w}'. ({len(sat_worlds)}/{len(all_worlds)} worlds satisfied)"
        )

        return ModelCheckResult(
            formula=formula_str,
            is_satisfied=is_satisfied,
            initial_world=init_w or "",
            satisfied_worlds=sorted(list(sat_worlds)),
            violated_worlds=violated_worlds,
            total_worlds=len(all_worlds),
            counterexample_path=counterexample,
            witness_path=witness,
            details=details,
        )

    def sat(self, node: FormulaNode) -> Set[str]:
        """Compute set of all worlds satisfying subformula node via fixed points."""
        all_w = set(self.kripke.worlds.keys())

        if node.op == CTLOperator.TRUE:
            return set(all_w)

        if node.op == CTLOperator.FALSE:
            return set()

        if node.op == CTLOperator.ATOM:
            return {w for w, obj in self.kripke.worlds.items() if obj.has_prop(node.name)}

        if node.op == CTLOperator.NOT and node.left:
            return all_w - self.sat(node.left)

        if node.op == CTLOperator.AND and node.left and node.right:
            return self.sat(node.left) & self.sat(node.right)

        if node.op == CTLOperator.OR and node.left and node.right:
            return self.sat(node.left) | self.sat(node.right)

        if node.op == CTLOperator.IMPLIES and node.left and node.right:
            sat_l = self.sat(node.left)
            sat_r = self.sat(node.right)
            return (all_w - sat_l) | sat_r

        # Modal Logic Operators
        if node.op == CTLOperator.BOX and node.left:
            # Box p: true in w iff for all accessible w', p holds
            sat_p = self.sat(node.left)
            return {w for w in all_w if self.kripke.get_successors(w).issubset(sat_p)}

        if node.op == CTLOperator.DIAMOND and node.left:
            # Diamond p: true in w iff exists accessible w' where p holds
            sat_p = self.sat(node.left)
            return {w for w in all_w if bool(self.kripke.get_successors(w) & sat_p)}

        # CTL Next State Operators
        if node.op == CTLOperator.EX and node.left:
            sat_p = self.sat(node.left)
            return self._pre_exists(sat_p)

        if node.op == CTLOperator.AX and node.left:
            sat_p = self.sat(node.left)
            return self._pre_all(sat_p)

        # CTL Fixed-Point Operators
        if node.op == CTLOperator.EF and node.left:
            # EF(p) = mu Z. (p | EX(Z)) [Least Fixed Point]
            sat_p = self.sat(node.left)
            z = set(sat_p)
            while True:
                nxt = z | self._pre_exists(z)
                if nxt == z:
                    return z
                z = nxt

        if node.op == CTLOperator.AF and node.left:
            # AF(p) = mu Z. (p | AX(Z)) [Least Fixed Point]
            sat_p = self.sat(node.left)
            z = set(sat_p)
            while True:
                nxt = z | self._pre_all(z)
                if nxt == z:
                    return z
                z = nxt

        if node.op == CTLOperator.EG and node.left:
            # EG(p) = nu Z. (p & EX(Z)) [Greatest Fixed Point]
            sat_p = self.sat(node.left)
            z = set(sat_p)
            while True:
                nxt = z & self._pre_exists(z)
                if nxt == z:
                    return z
                z = nxt

        if node.op == CTLOperator.AG and node.left:
            # AG(p) = nu Z. (p & AX(Z)) [Greatest Fixed Point]
            sat_p = self.sat(node.left)
            z = set(sat_p)
            while True:
                nxt = z & self._pre_all(z)
                if nxt == z:
                    return z
                z = nxt

        if node.op == CTLOperator.EU and node.left and node.right:
            # E[p U q] = mu Z. (q | (p & EX(Z))) [Least Fixed Point]
            sat_p = self.sat(node.left)
            sat_q = self.sat(node.right)
            z = set(sat_q)
            while True:
                nxt = z | (sat_p & self._pre_exists(z))
                if nxt == z:
                    return z
                z = nxt

        if node.op == CTLOperator.AU and node.left and node.right:
            # A[p U q] = mu Z. (q | (p & AX(Z))) [Least Fixed Point]
            sat_p = self.sat(node.left)
            sat_q = self.sat(node.right)
            z = set(sat_q)
            while True:
                nxt = z | (sat_p & self._pre_all(z))
                if nxt == z:
                    return z
                z = nxt

        return set()

    def _pre_exists(self, target_set: Set[str]) -> Set[str]:
        """Compute Pre_exists(S) = { w in W | exists w' in S. (w, w') in R }."""
        pre = set()
        for w in self.kripke.worlds:
            if bool(self.kripke.get_successors(w) & target_set):
                pre.add(w)
        return pre

    def _pre_all(self, target_set: Set[str]) -> Set[str]:
        """Compute Pre_all(S) = { w in W | forall w'. (w, w') in R => w' in S }."""
        pre = set()
        for w in self.kripke.worlds:
            succ = self.kripke.get_successors(w)
            if succ and succ.issubset(target_set):
                pre.add(w)
        return pre

    def _generate_counterexample(
        self,
        node: FormulaNode,
        start_world: str,
        sat_worlds: Set[str],
    ) -> Optional[List[str]]:
        """Find shortest counterexample trace demonstrating violation."""
        if node.op == CTLOperator.AG and node.left:
            # Violation of AG(p): find shortest path to a world w not in Sat(p)
            target_violators = set(self.kripke.worlds.keys()) - self.sat(node.left)
            return self._find_shortest_path(start_world, target_violators)

        if node.op == CTLOperator.AX and node.left:
            sat_p = self.sat(node.left)
            for succ in self.kripke.get_successors(start_world):
                if succ not in sat_p:
                    return [start_world, succ]

        if node.op == CTLOperator.AF and node.left:
            # Violation of AF(p): world never reaches p
            return [start_world]

        return [start_world]

    def _generate_witness(
        self,
        node: FormulaNode,
        start_world: str,
        sat_worlds: Set[str],
    ) -> Optional[List[str]]:
        """Find shortest witness trace demonstrating satisfiability."""
        if node.op == CTLOperator.EF and node.left:
            target_sat = self.sat(node.left)
            return self._find_shortest_path(start_world, target_sat)

        if node.op == CTLOperator.EX and node.left:
            sat_p = self.sat(node.left)
            for succ in self.kripke.get_successors(start_world):
                if succ in sat_p:
                    return [start_world, succ]

        if node.op == CTLOperator.EU and node.left and node.right:
            target_q = self.sat(node.right)
            return self._find_shortest_path(start_world, target_q)

        return [start_world]

    def _find_shortest_path(self, start_world: str, targets: Set[str]) -> Optional[List[str]]:
        """BFS shortest path from start_world to any node in targets."""
        if start_world in targets:
            return [start_world]

        queue: List[List[str]] = [[start_world]]
        visited: Set[str] = {start_world}

        while queue:
            path = queue.pop(0)
            curr = path[-1]
            for succ in self.kripke.get_successors(curr):
                if succ in targets:
                    return path + [succ]
                if succ not in visited:
                    visited.add(succ)
                    queue.append(path + [succ])

        return None
