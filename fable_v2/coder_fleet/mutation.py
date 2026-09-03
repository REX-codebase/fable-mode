"""Mutation Verifier Engine for AST-based Mutant Injection and Test Rigor Auditing.

Generates semantic AST mutations and verifies whether test suites actually catch mutants
or whether tests are fake / tautological.
"""
from __future__ import annotations

import ast
import copy
from typing import Any

from .test_harness import TestHarnessEngine


class MutationVerifierEngine:
    """Engine for generating AST-based code mutants and assessing test suite kill rates."""

    def __init__(self, test_harness: TestHarnessEngine | None = None) -> None:
        self._harness = test_harness or TestHarnessEngine()

    def inject_mutants(self, source_code: str) -> list[dict[str, Any]]:
        """Generate 3-5 AST-based mutants:

        - inverts >/<, ==/!=
        - flips True/False
        - replaces numeric constants
        - removes return statements / alters return values
        - inverts arithmetic operators (+/-)
        """
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        # Find mutation candidates
        candidates: list[tuple[ast.AST, str, Any]] = []

        for node in ast.walk(tree):
            # 1. Comparison operations
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, ast.Gt):
                        candidates.append((node, "invert_comparison_gt_to_lt", (op, ast.Lt())))
                    elif isinstance(op, ast.Lt):
                        candidates.append((node, "invert_comparison_lt_to_gt", (op, ast.Gt())))
                    elif isinstance(op, ast.GtE):
                        candidates.append((node, "invert_comparison_gte_to_lte", (op, ast.LtE())))
                    elif isinstance(op, ast.LtE):
                        candidates.append((node, "invert_comparison_lte_to_gte", (op, ast.GtE())))
                    elif isinstance(op, ast.Eq):
                        candidates.append((node, "invert_comparison_eq_to_neq", (op, ast.NotEq())))
                    elif isinstance(op, ast.NotEq):
                        candidates.append((node, "invert_comparison_neq_to_eq", (op, ast.Eq())))

            # 2. Boolean and numeric constants
            elif isinstance(node, ast.Constant):
                if node.value is True:
                    candidates.append((node, "flip_boolean_true_to_false", False))
                elif node.value is False:
                    candidates.append((node, "flip_boolean_false_to_true", True))
                elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    new_val = 1 if node.value == 0 else (node.value + 1)
                    candidates.append((node, "mutate_numeric_constant", new_val))

            # 3. Return statements
            elif isinstance(node, ast.Return):
                if node.value is not None:
                    candidates.append((node, "remove_return_value", None))

            # 4. Arithmetic operators
            elif isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Add):
                    candidates.append((node, "invert_arithmetic_add_to_sub", ast.Sub()))
                elif isinstance(node.op, ast.Sub):
                    candidates.append((node, "invert_arithmetic_sub_to_add", ast.Add()))

        mutants: list[dict[str, Any]] = []
        seen_codes: set[str] = {source_code.strip()}

        for target_node, mut_type, mut_arg in candidates:
            if len(mutants) >= 5:
                break

            mutated_tree = copy.deepcopy(tree)

            class Mutator(ast.NodeTransformer):
                def __init__(self, target_line: int, target_col: int) -> None:
                    self.target_line = target_line
                    self.target_col = target_col
                    self.mutated = False

                def visit_Compare(self, n: ast.Compare) -> ast.AST:
                    self.generic_visit(n)
                    if not self.mutated and getattr(n, "lineno", -1) == self.target_line and getattr(n, "col_offset", -1) == self.target_col:
                        if mut_type.startswith("invert_comparison"):
                            old_op, new_op = mut_arg
                            new_ops = []
                            for op in n.ops:
                                if type(op) is type(old_op) and not self.mutated:
                                    new_ops.append(new_op)
                                    self.mutated = True
                                else:
                                    new_ops.append(op)
                            n.ops = new_ops
                    return n

                def visit_Constant(self, n: ast.Constant) -> ast.AST:
                    if not self.mutated and getattr(n, "lineno", -1) == self.target_line and getattr(n, "col_offset", -1) == self.target_col:
                        if mut_type in ("flip_boolean_true_to_false", "flip_boolean_false_to_true", "mutate_numeric_constant"):
                            n.value = mut_arg
                            self.mutated = True
                    return n

                def visit_Return(self, n: ast.Return) -> ast.AST:
                    self.generic_visit(n)
                    if not self.mutated and getattr(n, "lineno", -1) == self.target_line and getattr(n, "col_offset", -1) == self.target_col:
                        if mut_type == "remove_return_value":
                            n.value = ast.Constant(value=None)
                            self.mutated = True
                    return n

                def visit_BinOp(self, n: ast.BinOp) -> ast.AST:
                    self.generic_visit(n)
                    if not self.mutated and getattr(n, "lineno", -1) == self.target_line and getattr(n, "col_offset", -1) == self.target_col:
                        if mut_type.startswith("invert_arithmetic"):
                            n.op = mut_arg
                            self.mutated = True
                    return n

            line = getattr(target_node, "lineno", 1)
            col = getattr(target_node, "col_offset", 0)
            mutator = Mutator(line, col)
            mutated_tree = mutator.visit(mutated_tree)
            ast.fix_missing_locations(mutated_tree)

            try:
                mutated_code = ast.unparse(mutated_tree)
            except Exception:
                continue

            if mutated_code.strip() not in seen_codes:
                seen_codes.add(mutated_code.strip())
                mutants.append({
                    "mutant_id": f"mutant_{len(mutants) + 1}",
                    "mutated_code": mutated_code,
                    "mutation_type": mut_type,
                    "line": line,
                })

        return mutants

    def audit_test_strength(self, source_code: str, test_code: str, timeout_sec: float = 3.0) -> dict[str, Any]:
        """Run test_code against each mutant using run_scratch_test.

        If tests still pass against mutant, mutant survived (test is weak/fake!).
        If tests fail, mutant killed.
        Returns {mutants_total, mutants_killed, mutants_survived, mutation_score, is_thorough}.
        """
        baseline_code = f"{source_code}\n\n{test_code}"
        baseline_run = self._harness.run_scratch_test(baseline_code, timeout_sec=timeout_sec)

        if not baseline_run["success"]:
            return {
                "mutants_total": 0,
                "mutants_killed": 0,
                "mutants_survived": 0,
                "mutation_score": 0.0,
                "is_thorough": False,
                "error": f"Baseline test failed on unmutated code: {baseline_run.get('stderr')}",
                "survived_mutant_details": [],
            }

        mutants = self.inject_mutants(source_code)
        if not mutants:
            return {
                "mutants_total": 0,
                "mutants_killed": 0,
                "mutants_survived": 0,
                "mutation_score": 1.0,
                "is_thorough": True,
                "survived_mutant_details": [],
            }

        killed: list[dict[str, Any]] = []
        survived: list[dict[str, Any]] = []

        for m in mutants:
            mutant_test = f"{m['mutated_code']}\n\n{test_code}"
            run_res = self._harness.run_scratch_test(mutant_test, timeout_sec=timeout_sec)

            if not run_res["success"]:
                # Mutant killed! The test failed as expected on mutated code.
                killed.append(m)
            else:
                # Mutant survived! The test erroneously passed despite bug injected.
                survived.append({
                    "mutant_id": m["mutant_id"],
                    "mutation_type": m["mutation_type"],
                    "line": m["line"],
                    "reason": "Test suite passed despite mutation (weak or missing assertion)",
                })

        total = len(mutants)
        killed_count = len(killed)
        survived_count = len(survived)
        score = round(killed_count / total, 4) if total > 0 else 1.0
        is_thorough = score >= 0.75

        return {
            "mutants_total": total,
            "mutants_killed": killed_count,
            "mutants_survived": survived_count,
            "mutation_score": score,
            "is_thorough": is_thorough,
            "survived_mutant_details": survived,
        }
