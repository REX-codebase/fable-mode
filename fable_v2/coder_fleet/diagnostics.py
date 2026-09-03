"""Diagnostics Engine for AST-based Static Analysis and Automated Quick-Fixes.

Pure-Python implementation with zero external C-dependencies.
"""
from __future__ import annotations

import ast
import builtins
import re
from typing import Any

# Standard known library symbols for automated quick-fixes
KNOWN_IMPORTS: dict[str, str] = {
    "os": "import os",
    "sys": "import sys",
    "re": "import re",
    "json": "import json",
    "math": "import math",
    "time": "import time",
    "datetime": "import datetime",
    "Path": "from pathlib import Path",
    "List": "from typing import List",
    "Dict": "from typing import Dict",
    "Set": "from typing import Set",
    "Tuple": "from typing import Tuple",
    "Optional": "from typing import Optional",
    "Union": "from typing import Union",
    "Any": "from typing import Any",
    "Callable": "from typing import Callable",
    "Iterable": "from typing import Iterable",
    "Mapping": "from typing import Mapping",
    "Sequence": "from typing import Sequence",
    "defaultdict": "from collections import defaultdict",
    "Counter": "from collections import Counter",
    "deque": "from collections import deque",
    "uuid": "import uuid",
    "hashlib": "import hashlib",
    "subprocess": "import subprocess",
}


class DiagnosticsEngine:
    """Engine for syntax validation, AST semantic diagnostics, and automated quick fixes."""

    def __init__(self) -> None:
        self._builtins: set[str] = set(dir(builtins)) | {
            "__name__",
            "__doc__",
            "__file__",
            "__package__",
            "__annotations__",
            "__builtins__",
            "__spec__",
            "__loader__",
            "self",
            "cls",
        }

    def run_diagnostics(self, source_code: str, language: str = "python") -> list[dict[str, Any]]:
        """Run AST-based syntax and semantic checks.

        Returns list of {line, col, code, message, severity, symbol}.
        """
        if language.lower() != "python":
            return [
                {
                    "line": 1,
                    "col": 0,
                    "code": "UNSUPPORTED_LANGUAGE",
                    "message": f"Language '{language}' diagnostics not supported (Python only)",
                    "severity": "warning",
                }
            ]

        diagnostics: list[dict[str, Any]] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            return [
                {
                    "line": exc.lineno or 1,
                    "col": exc.offset or 0,
                    "code": "E999",
                    "message": f"SyntaxError: {exc.msg}",
                    "severity": "error",
                    "symbol": None,
                }
            ]

        # 1. Collect imports, defined symbols, loaded symbols, and special nodes
        imported_symbols: dict[str, tuple[int, int, ast.AST, str]] = {}  # name -> (line, col, node, import_stmt)
        defined_symbols: set[str] = set(self._builtins)
        loaded_symbols: list[tuple[str, int, int]] = []

        class ScopeCollector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.bare_excepts: list[tuple[int, int]] = []
                self.duplicate_keys: list[tuple[int, int, str]] = []

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported_symbols[name] = (node.lineno, node.col_offset, node, "import")
                    defined_symbols.add(name)
                self.generic_visit(node)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_symbols[name] = (node.lineno, node.col_offset, node, "from")
                    defined_symbols.add(name)
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                defined_symbols.add(node.name)
                for arg in node.args.args + node.args.kwonlyargs:
                    defined_symbols.add(arg.arg)
                if node.args.vararg:
                    defined_symbols.add(node.args.vararg.arg)
                if node.args.kwarg:
                    defined_symbols.add(node.args.kwarg.arg)
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                defined_symbols.add(node.name)
                for arg in node.args.args + node.args.kwonlyargs:
                    defined_symbols.add(arg.arg)
                if node.args.vararg:
                    defined_symbols.add(node.args.vararg.arg)
                if node.args.kwarg:
                    defined_symbols.add(node.args.kwarg.arg)
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                defined_symbols.add(node.name)
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> None:
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    defined_symbols.add(node.id)
                elif isinstance(node.ctx, ast.Load):
                    loaded_symbols.append((node.id, node.lineno, node.col_offset))
                self.generic_visit(node)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                if node.type is None:
                    self.bare_excepts.append((node.lineno, node.col_offset))
                if node.name:
                    defined_symbols.add(node.name)
                self.generic_visit(node)

            def visit_comprehension(self, node: ast.comprehension) -> None:
                if isinstance(node.target, ast.Name):
                    defined_symbols.add(node.target.id)
                elif isinstance(node.target, (ast.Tuple, ast.List)):
                    for elt in node.target.elts:
                        if isinstance(elt, ast.Name):
                            defined_symbols.add(elt.id)
                self.generic_visit(node)

            def visit_Dict(self, node: ast.Dict) -> None:
                seen_keys: set[Any] = set()
                for k in node.keys:
                    if isinstance(k, ast.Constant):
                        if k.value in seen_keys:
                            self.duplicate_keys.append((k.lineno, k.col_offset, repr(k.value)))
                        else:
                            seen_keys.add(k.value)
                self.generic_visit(node)

        collector = ScopeCollector()
        collector.visit(tree)

        # 2. Check for unused imports (W0611)
        loaded_names = {name for name, _, _ in loaded_symbols}
        for name, (line, col, _node, _stmt_type) in imported_symbols.items():
            if name not in loaded_names:
                diagnostics.append({
                    "line": line,
                    "col": col,
                    "code": "W0611",
                    "message": f"Unused import '{name}'",
                    "severity": "warning",
                    "symbol": name,
                })

        # 3. Check for undefined names (E0602)
        reported_undefined: set[str] = set()
        for name, line, col in loaded_symbols:
            if name not in defined_symbols and name not in reported_undefined:
                reported_undefined.add(name)
                diagnostics.append({
                    "line": line,
                    "col": col,
                    "code": "E0602",
                    "message": f"Undefined name '{name}'",
                    "severity": "error",
                    "symbol": name,
                })

        # 4. Check bare excepts (W0702)
        for line, col in collector.bare_excepts:
            diagnostics.append({
                "line": line,
                "col": col,
                "code": "W0702",
                "message": "Bare 'except:' used without specifying exception type",
                "severity": "warning",
                "symbol": None,
            })

        # 5. Check duplicate dictionary keys (W0109)
        for line, col, key_repr in collector.duplicate_keys:
            diagnostics.append({
                "line": line,
                "col": col,
                "code": "W0109",
                "message": f"Duplicate key {key_repr} in dictionary literal",
                "severity": "warning",
                "symbol": key_repr,
            })

        # Sort diagnostics by line number
        diagnostics.sort(key=lambda d: (d.get("line", 0), d.get("col", 0)))
        return diagnostics

    def apply_quick_fix(self, diagnostic: dict[str, Any], source_code: str) -> str:
        """Apply an automated fix for a diagnostic issue."""
        code = diagnostic.get("code")
        symbol = diagnostic.get("symbol")
        line_num = diagnostic.get("line", 1)
        lines = source_code.splitlines(keepends=True)

        if code == "W0611" and symbol:
            # Unused import removal
            if 1 <= line_num <= len(lines):
                target_line = lines[line_num - 1]
                # If the line only imports this symbol, remove the line
                # Example: "import os\n" or "from math import sqrt\n"
                clean = target_line.strip()
                if clean in (f"import {symbol}", f"import {symbol} as {symbol}"):
                    lines.pop(line_num - 1)
                    return "".join(lines)
                from_match = re.match(r"^from\s+[\w\.]+\s+import\s+(.+)$", clean)
                if from_match:
                    imported_items = [i.strip() for i in from_match.group(1).split(",") if i.strip()]
                    remaining = [i for i in imported_items if i != symbol and not i.endswith(f" as {symbol}")]
                    if not remaining:
                        lines.pop(line_num - 1)
                    else:
                        module_part = clean.split("import")[0]
                        indent = len(target_line) - len(target_line.lstrip())
                        new_line = " " * indent + module_part + "import " + ", ".join(remaining) + "\n"
                        lines[line_num - 1] = new_line
                    return "".join(lines)
                # Fallback: remove full line if symbol is found in it
                if symbol in clean:
                    lines.pop(line_num - 1)
                    return "".join(lines)

        elif code == "E0602" and symbol:
            # Undefined name: auto-insert import if recognized
            fix_stmt = KNOWN_IMPORTS.get(symbol)
            if fix_stmt:
                # Find best insertion point (after module docstring and future imports)
                insert_idx = 0
                for idx, line in enumerate(lines):
                    s = line.strip()
                    if s.startswith('"""') or s.startswith("'''"):
                        # docstring handling
                        continue
                    if s.startswith("from __future__"):
                        insert_idx = idx + 1
                    elif s.startswith("import ") or s.startswith("from "):
                        insert_idx = idx
                        break
                    elif s and not s.startswith("#"):
                        insert_idx = idx
                        break

                lines.insert(insert_idx, fix_stmt + "\n")
                return "".join(lines)

        elif code == "W0702":
            # Bare except fix
            if 1 <= line_num <= len(lines):
                target_line = lines[line_num - 1]
                if "except:" in target_line:
                    lines[line_num - 1] = target_line.replace("except:", "except Exception:", 1)
                    return "".join(lines)

        return source_code
