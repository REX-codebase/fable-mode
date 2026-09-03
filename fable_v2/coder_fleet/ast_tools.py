"""Tree-Sitter / AST Codemod Engine for Structural Queries and Refactoring.

Pure-Python implementation utilizing standard library ast and tokenize modules
with zero mandatory external C-dependencies.
"""
from __future__ import annotations

import ast
import io
import json
import tokenize
from typing import Any


class TreeSitterCodemodEngine:
    """Engine for syntax verification, AST structural queries, and safe symbol renaming."""

    def query_ast(self, source_code: str, node_type: str = "FunctionDef") -> list[dict[str, Any]]:
        """Query AST nodes matching node_type with line numbers, arguments, and metadata."""
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        results: list[dict[str, Any]] = []

        for node in ast.walk(tree):
            if type(node).__name__ == node_type:
                item: dict[str, Any] = {
                    "node_type": node_type,
                    "name": getattr(node, "name", None),
                    "line": getattr(node, "lineno", 1),
                    "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                    "col": getattr(node, "col_offset", 0),
                }

                # Extract arguments if FunctionDef or AsyncFunctionDef
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args_list: list[str] = [arg.arg for arg in node.args.args]
                    if node.args.vararg:
                        args_list.append(f"*{node.args.vararg.arg}")
                    for kw in node.args.kwonlyargs:
                        args_list.append(kw.arg)
                    if node.args.kwarg:
                        args_list.append(f"**{node.args.kwarg.arg}")
                    item["args"] = args_list

                    # Decorators
                    item["decorators"] = [
                        ast.unparse(d) if hasattr(ast, "unparse") else getattr(d, "id", "decorator")
                        for d in node.decorator_list
                    ]

                    # Return annotation
                    if node.returns:
                        item["returns"] = ast.unparse(node.returns) if hasattr(ast, "unparse") else str(node.returns)

                    # Docstring
                    item["docstring"] = ast.get_docstring(node)

                elif isinstance(node, ast.ClassDef):
                    item["bases"] = [
                        ast.unparse(b) if hasattr(ast, "unparse") else getattr(b, "id", "base")
                        for b in node.bases
                    ]
                    item["docstring"] = ast.get_docstring(node)

                elif isinstance(node, ast.Call):
                    func_name = ast.unparse(node.func) if hasattr(ast, "unparse") else getattr(node.func, "id", "call")
                    item["func_name"] = func_name
                    item["arg_count"] = len(node.args)

                results.append(item)

        results.sort(key=lambda x: (x.get("line", 0), x.get("col", 0)))
        return results

    def rename_symbol(self, source_code: str, old_name: str, new_name: str) -> tuple[str, int]:
        """AST / tokenizer-based identifier rename that preserves string literals and comments

        without false substring matches.
        """
        if not source_code or old_name == new_name:
            return source_code, 0

        try:
            tokens = list(tokenize.tokenize(io.BytesIO(source_code.encode("utf-8")).readline))
        except (tokenize.TokenError, IndentationError):
            return source_code, 0

        # Collect exact NAME tokens matching old_name
        replacements: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for tok in tokens:
            if tok.type == tokenize.NAME and tok.string == old_name:
                replacements.append((tok.start, tok.end))

        if not replacements:
            return source_code, 0

        # Apply replacements backwards so line/column coordinates remain valid
        lines = source_code.splitlines(keepends=True)
        for (s_row, s_col), (e_row, e_col) in sorted(replacements, reverse=True):
            if 1 <= s_row <= len(lines):
                line = lines[s_row - 1]
                new_line = line[:s_col] + new_name + line[e_col:]
                lines[s_row - 1] = new_line

        return "".join(lines), len(replacements)

    def verify_syntax(self, source_code: str, language: str = "python") -> dict[str, Any]:
        """Verify code syntax, returning {valid: bool, error: str, line: int}."""
        lang = language.lower()

        if lang == "python":
            try:
                ast.parse(source_code)
                return {
                    "valid": True,
                    "error": None,
                    "line": None,
                    "col": None,
                    "language": "python",
                }
            except SyntaxError as exc:
                return {
                    "valid": False,
                    "error": exc.msg,
                    "line": exc.lineno or 1,
                    "col": exc.offset or 0,
                    "language": "python",
                }

        elif lang == "json":
            try:
                json.loads(source_code)
                return {
                    "valid": True,
                    "error": None,
                    "line": None,
                    "col": None,
                    "language": "json",
                }
            except json.JSONDecodeError as exc:
                return {
                    "valid": False,
                    "error": exc.msg,
                    "line": exc.lineno,
                    "col": exc.colno,
                    "language": "json",
                }

        return {
            "valid": False,
            "error": f"Unsupported language '{language}' for syntax verification",
            "line": None,
            "col": None,
            "language": language,
        }
