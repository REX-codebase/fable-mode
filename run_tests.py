#!/usr/bin/env python3
"""Unified Test Runner and Code Quality / Security Verification Suite for Fable Mode.

Runs compilation checks, static AST security audits, V1 server suite, V2 unit test suite, and installer syntax checks.
"""

import ast
import os
import sys
import subprocess
import time
from pathlib import Path


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_step(description, command):
    print(f"\n[RUNNING] {description}...")
    start_time = time.time()
    result = subprocess.run(command, shell=True)
    elapsed = time.time() - start_time
    if result.returncode == 0:
        print(f"[PASSED] {description} ({elapsed:.2f}s)")
        return True
    else:
        print(f"[FAILED] {description} (exit code {result.returncode})")
        return False


def run_ast_security_scan():
    """Zero-dependency static AST analysis for dangerous function calls and bug risk patterns."""
    print("\n[RUNNING] Static AST Security & Quality Audit...")
    start_time = time.time()
    issues = []

    roots = ["fable_mode", "fable_engine", "fable_v2"]

    for root_dir in roots:
        for path in Path(root_dir).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception as e:
                issues.append(f"{path}: Failed to parse AST: {e}")
                continue

            for node in ast.walk(tree):
                # Check for wildcard imports (from x import *)
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "*":
                            issues.append(f"{path}:{node.lineno}: Wildcard import 'from {node.module} import *'")

                # Check for raw eval() calls outside allowed dynamic execution boundaries
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "eval":
                        if "red_team_swarm.py" not in str(path):
                            issues.append(f"{path}:{node.lineno}: Prohibited call to eval()")

    elapsed = time.time() - start_time
    if not issues:
        print(f"[PASSED] Static AST Security & Quality Audit ({elapsed:.2f}s)")
        return True
    else:
        print(f"[FAILED] Static AST Security & Quality Audit found {len(issues)} issues:")
        for issue in issues:
            print(f"  - {issue}")
        return False


def main():
    print_header("FABLE MODE CI/CD VERIFICATION SUITE")

    # 1. Bytecode Compilation & Syntax Check
    all_passed = run_step("Bytecode Compilation & Syntax Check",
                          f"{sys.executable} -m compileall -q fable_mode fable_engine fable_v2 tests")

    # 2. Static AST Security & Bug Detection Audit
    ast_passed = run_ast_security_scan()
    all_passed = all_passed and ast_passed

    steps = [
        ("V1 Canonical MCP Server Suite",
         f"{sys.executable} fable_engine/test_server.py"),
        ("V2 Comprehensive Unit Test Suite",
         f"{sys.executable} -m unittest discover -s tests -p \"test_*.py\""),
    ]

    if sys.platform != "win32":
        steps.append(("Shell Script Syntax (install.sh)", "sh -n install.sh"))

    for name, cmd in steps:
        success = run_step(name, cmd)
        if not success:
            all_passed = False

    print_header("SUMMARY")
    if all_passed:
        print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("VERIFICATION CHECKS FAILED! Please review the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
