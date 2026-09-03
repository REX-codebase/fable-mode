"""Mock Auditor Engine for Detecting Fake Tautological Tests and Mock Leakage.

Audits test suites for trivial assertions (assert True, 1==1), excessive mocking,
and absence of negative / error path tests.
"""
from __future__ import annotations

import ast
from typing import Any


class MockAuditorEngine:
    """Engine for auditing test assertions, tautologies, mock stubs, and negative branch coverage."""

    def audit_assertions(self, test_code: str) -> dict[str, Any]:
        """AST visitor detecting trivial assertions (assert True, assert 1 == 1, assert x is not None as lone check),

        calculating assertion density and flagging tautologies.
        """
        try:
            tree = ast.parse(test_code)
        except SyntaxError:
            return {
                "total_assertions": 0,
                "trivial_assertions_count": 0,
                "tautologies": [],
                "assertion_density": 0.0,
                "passed_audit": False,
                "error": "SyntaxError parsing test code",
            }

        tautologies: list[dict[str, Any]] = []
        total_assertions = 0
        test_functions = 0

        class AssertionVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                nonlocal test_functions
                super().__init__()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                nonlocal test_functions
                if node.name.startswith("test_") or node.name.endswith("_test"):
                    test_functions += 1

                    # Check for lone 'assert x is not None'
                    assert_stmts = [s for s in node.body if isinstance(s, ast.Assert)]
                    if len(node.body) == 1 and len(assert_stmts) == 1:
                        target_assert = assert_stmts[0]
                        if isinstance(target_assert.test, ast.Compare):
                            ops = target_assert.test.ops
                            comparators = target_assert.test.comparators
                            if any(isinstance(op, ast.IsNot) for op in ops) and any(
                                isinstance(c, ast.Constant) and c.value is None for c in comparators
                            ):
                                tautologies.append({
                                    "line": target_assert.lineno,
                                    "col": target_assert.col_offset,
                                    "type": "lone_not_none_assertion",
                                    "code_snippet": ast.unparse(target_assert) if hasattr(ast, "unparse") else "assert x is not None",
                                    "reason": "Test function contains only a single 'assert x is not None' check without behavior verification",
                                })

                self.generic_visit(node)

            def visit_Assert(self, node: ast.Assert) -> None:
                nonlocal total_assertions
                total_assertions += 1

                # Check assert True / assert 1
                if isinstance(node.test, ast.Constant):
                    if node.test.value is True or node.test.value == 1:
                        tautologies.append({
                            "line": node.lineno,
                            "col": node.col_offset,
                            "type": "constant_true_assertion",
                            "code_snippet": ast.unparse(node) if hasattr(ast, "unparse") else "assert True",
                            "reason": f"Tautological assertion with constant truth value '{node.test.value}'",
                        })

                # Check assert 1 == 1, assert "a" == "a"
                elif isinstance(node.test, ast.Compare):
                    cmp = node.test
                    if isinstance(cmp.left, ast.Constant) and len(cmp.comparators) == 1 and isinstance(cmp.comparators[0], ast.Constant):
                        if cmp.left.value == cmp.comparators[0].value and any(isinstance(op, (ast.Eq, ast.Is)) for op in cmp.ops):
                            tautologies.append({
                                "line": node.lineno,
                                "col": node.col_offset,
                                "type": "literal_equality_tautology",
                                "code_snippet": ast.unparse(node) if hasattr(ast, "unparse") else "assert a == a",
                                "reason": f"Trivial assertion comparing literal {cmp.left.value!r} to itself",
                            })

                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                nonlocal total_assertions
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id

                if func_name.startswith("assert"):
                    total_assertions += 1

                    if func_name in ("assertTrue", "assert_true") and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and first_arg.value is True:
                            tautologies.append({
                                "line": node.lineno,
                                "col": node.col_offset,
                                "type": "assertTrue_true_call",
                                "code_snippet": ast.unparse(node) if hasattr(ast, "unparse") else "self.assertTrue(True)",
                                "reason": "Trivial assertion call assertTrue(True)",
                            })

                    elif func_name in ("assertEqual", "assert_equal") and len(node.args) >= 2:
                        a1, a2 = node.args[0], node.args[1]
                        if isinstance(a1, ast.Constant) and isinstance(a2, ast.Constant) and a1.value == a2.value:
                            tautologies.append({
                                "line": node.lineno,
                                "col": node.col_offset,
                                "type": "assertEqual_identical_call",
                                "code_snippet": ast.unparse(node) if hasattr(ast, "unparse") else "self.assertEqual(a, a)",
                                "reason": f"Trivial assertion call assertEqual with identical constant {a1.value!r}",
                            })

                self.generic_visit(node)

        visitor = AssertionVisitor()
        visitor.visit(tree)

        trivial_count = len(tautologies)
        effective_tests = max(1, test_functions)
        density = round(total_assertions / effective_tests, 2)
        passed = (trivial_count == 0) and (total_assertions > 0)

        return {
            "total_assertions": total_assertions,
            "trivial_assertions_count": trivial_count,
            "tautologies": tautologies,
            "assertion_density": density,
            "passed_audit": passed,
        }

    def detect_mock_leakage(self, test_code: str) -> dict[str, Any]:
        """Check for excessive mock usage where core logic is stubbed out."""
        try:
            tree = ast.parse(test_code)
        except SyntaxError:
            return {
                "mock_count": 0,
                "mock_ratio": 0.0,
                "flagged_mocks": [],
                "has_excessive_mocking": False,
            }

        mock_identifiers = {"Mock", "MagicMock", "patch", "mocker", "monkeypatch", "PropertyMock"}
        mock_count = 0
        total_calls = 0
        flagged: list[dict[str, Any]] = []

        class MockVisitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                nonlocal mock_count, total_calls
                total_calls += 1
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr

                if name in mock_identifiers or "mock" in name.lower():
                    mock_count += 1
                    flagged.append({
                        "line": node.lineno,
                        "name": name,
                        "reason": f"Invocation of mock factory or stub '{name}'",
                    })
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                nonlocal mock_count
                for dec in node.decorator_list:
                    dec_name = ""
                    if isinstance(dec, ast.Name):
                        dec_name = dec.id
                    elif isinstance(dec, ast.Attribute):
                        dec_name = dec.attr
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            dec_name = dec.func.id
                        elif isinstance(dec.func, ast.Attribute):
                            dec_name = dec.func.attr

                    if "patch" in dec_name.lower():
                        mock_count += 1
                        flagged.append({
                            "line": dec.lineno if hasattr(dec, "lineno") else node.lineno,
                            "name": dec_name,
                            "reason": f"Patch decorator '@{dec_name}' stubbing dependencies",
                        })
                self.generic_visit(node)

        MockVisitor().visit(tree)
        ratio = round(mock_count / max(1, total_calls), 2)
        excessive = ratio > 0.5 or (mock_count >= 5 and ratio > 0.3)

        return {
            "mock_count": mock_count,
            "mock_ratio": ratio,
            "flagged_mocks": flagged,
            "has_excessive_mocking": excessive,
        }

    def enforce_negative_paths(self, test_code: str) -> dict[str, Any]:
        """Verify presence of negative test cases (assertRaises, except, pytest.raises)."""
        try:
            tree = ast.parse(test_code)
        except SyntaxError:
            return {
                "has_negative_tests": False,
                "negative_test_count": 0,
                "total_test_cases": 0,
                "negative_ratio": 0.0,
                "details": [],
            }

        negative_details: list[dict[str, Any]] = []
        total_test_cases = 0

        class NegativePathVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                nonlocal total_test_cases
                if node.name.startswith("test_") or node.name.endswith("_test"):
                    total_test_cases += 1
                    # Check if function name indicates negative test
                    lower_name = node.name.lower()
                    if any(w in lower_name for w in ("error", "invalid", "fail", "exception", "reject", "negative")):
                        negative_details.append({
                            "line": node.lineno,
                            "function": node.name,
                            "type": "naming_convention",
                            "description": f"Negative test detected from name '{node.name}'",
                        })
                self.generic_visit(node)

            def visit_With(self, node: ast.With) -> None:
                for item in node.items:
                    expr = item.context_expr
                    expr_name = ""
                    if isinstance(expr, ast.Call):
                        if isinstance(expr.func, ast.Attribute):
                            expr_name = expr.func.attr
                        elif isinstance(expr.func, ast.Name):
                            expr_name = expr.func.id

                    if expr_name in ("assertRaises", "raises", "assert_raises"):
                        negative_details.append({
                            "line": node.lineno,
                            "function": None,
                            "type": "with_assertRaises",
                            "description": f"Context manager '{expr_name}' testing error expectation",
                        })
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id

                if func_name in ("assertRaises", "assert_raises", "assertFalse"):
                    negative_details.append({
                        "line": node.lineno,
                        "function": None,
                        "type": "negative_assert_call",
                        "description": f"Assertion call '{func_name}' testing negative/failure path",
                    })
                self.generic_visit(node)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                # Presence of an except handler inside a test
                negative_details.append({
                    "line": node.lineno,
                    "function": None,
                    "type": "try_except_block",
                    "description": "Explicit exception handling checking error recovery",
                })
                self.generic_visit(node)

        NegativePathVisitor().visit(tree)

        neg_count = len(negative_details)
        effective_total = max(1, total_test_cases)
        ratio = round(neg_count / effective_total, 2)

        return {
            "has_negative_tests": neg_count > 0,
            "negative_test_count": neg_count,
            "total_test_cases": total_test_cases,
            "negative_ratio": ratio,
            "details": negative_details,
        }
