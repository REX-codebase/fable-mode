#!/usr/bin/env python3
"""Unified Test Runner and Static AST Policy Verification Suite for Fable Mode.

Runs compilation checks, static AST policy audits, V1 server suite, V2 unit test suite, and installer syntax checks.
Supports --policy-only and --suite-only flags for modular CI job execution.
"""

import argparse
import ast
import sys
import subprocess
import time
from pathlib import Path


# Explicitly documented allowlist for legitimate dynamic evaluation
ALLOWED_EVAL_FILES = {
    Path("fable_v2/coder_fleet/red_team_swarm.py"): "Compiles dynamic counterfactual attack scenarios for adversarial code testing"
}


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_step(description, cmd_args):
    print(f"\n[RUNNING] {description}...")
    start_time = time.time()
    result = subprocess.run(cmd_args)
    elapsed = time.time() - start_time
    if result.returncode == 0:
        print(f"[PASSED] {description} ({elapsed:.2f}s)")
        return True
    else:
        print(f"[FAILED] {description} (exit code {result.returncode})")
        return False


def run_ast_policy_checks():
    """Zero-dependency static AST policy analysis for prohibited imports and unapproved eval calls."""
    print("\n[RUNNING] Static AST Policy Checks...")
    start_time = time.time()
    issues = []

    roots = ["fable_mode", "fable_engine", "fable_v2"]

    # Fail fast if required codebase directories disappear or get renamed
    for root_dir in roots:
        root_path = Path(root_dir)
        if not root_path.exists() or not root_path.is_dir():
            print(f"[FAILED] Missing required directory for AST policy scan: {root_dir}")
            return False

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

                # Check for eval() calls outside explicit allowlist
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "eval":
                        rel_path = path.as_posix()
                        is_allowed = any(
                            path == allowed_path or rel_path.endswith(allowed_path.as_posix())
                            for allowed_path in ALLOWED_EVAL_FILES
                        )
                        if not is_allowed:
                            issues.append(f"{path}:{node.lineno}: Prohibited call to eval()")

    elapsed = time.time() - start_time
    if not issues:
        print(f"[PASSED] Static AST Policy Checks ({elapsed:.2f}s)")
        return True
    else:
        print(f"[FAILED] Static AST Policy Checks found {len(issues)} issues:")
        for issue in issues:
            print(f"  - {issue}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Fable Mode Unified Test Runner")
    parser.add_argument("--policy-only", action="store_true", help="Run only bytecode compilation & AST policy checks")
    parser.add_argument("--suite-only", action="store_true", help="Run only the test suites and syntax checks")
    args = parser.parse_args()

    print_header("FABLE MODE CI/CD VERIFICATION SUITE")
    all_passed = True

    if not args.suite_only:
        # 1. Bytecode Compilation & Syntax Check
        compile_passed = run_step(
            "Bytecode Compilation Check",
            [sys.executable, "-m", "compileall", "-q", "fable_mode", "fable_engine", "fable_v2", "tests"]
        )
        # 2. Static AST Policy Checks
        policy_passed = run_ast_policy_checks()
        all_passed = all_passed and compile_passed and policy_passed

    if not args.policy_only:
        steps = [
            ("V1 Canonical MCP Server Suite", [sys.executable, "fable_engine/test_server.py"]),
            ("V2 Comprehensive Unit Test Suite", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]),
        ]

        if sys.platform != "win32":
            steps.append(("Shell Script Syntax (install.sh)", ["sh", "-n", "install.sh"]))

        for name, cmd_args in steps:
            success = run_step(name, cmd_args)
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
