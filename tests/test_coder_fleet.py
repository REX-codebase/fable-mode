"""Comprehensive Unit Test Suite for the 10-Tool Coder Subagent MCP Fleet.

Tests all engines:
- VisualGroundingEngine
- DiagnosticsEngine
- TreeSitterCodemodEngine
- AtomicWorkspaceEngine
- TestHarnessEngine
- MutationVerifierEngine
- MockAuditorEngine
- PropertyOracleEngine
- ReceiptAttestorEngine
- ComputeOrchestratorEngine
- CoderFleetDispatcher
"""
from __future__ import annotations

import sys
import unittest

from fable_v2.coder_fleet import (
    AtomicWorkspaceEngine,
    CoderFleetDispatcher,
    ComputeOrchestratorEngine,
    DiagnosticsEngine,
    MockAuditorEngine,
    MutationVerifierEngine,
    PropertyOracleEngine,
    ReceiptAttestorEngine,
    TestHarnessEngine,
    TreeSitterCodemodEngine,
    VisualGroundingEngine,
)


class TestVisualGroundingEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = VisualGroundingEngine()

    def test_render_vector_valid(self) -> None:
        svg_code = (
            '<svg viewBox="0 0 100 100" width="100" height="100">'
            '  <rect x="10" y="10" width="50" height="50" fill="#ff0000"/>'
            '  <circle cx="50" cy="50" r="25" stroke="#00ff00"/>'
            '  <path d="M 10 10 L 90 90 Z" />'
            "</svg>"
        )
        res = self.engine.render_vector(svg_code)
        self.assertTrue(res["valid"])
        self.assertEqual(res["viewBox"], [0.0, 0.0, 100.0, 100.0])
        self.assertEqual(res["width"], "100")
        self.assertEqual(res["height"], "100")
        self.assertIn("rect", res["element_types"])
        self.assertIn("circle", res["element_types"])
        self.assertIn("path", res["element_types"])
        self.assertEqual(len(res["paths"]), 1)
        self.assertGreaterEqual(res["metadata"]["total_path_commands"], 3)

    def test_render_vector_invalid(self) -> None:
        res = self.engine.render_vector("<svg><unclosed></svg>")
        self.assertFalse(res["valid"])
        self.assertIn("error", res)

        empty_res = self.engine.render_vector("")
        self.assertFalse(empty_res["valid"])

    def test_perceptual_diff(self) -> None:
        svg_code = (
            '<svg viewBox="0 0 200 200">'
            '  <rect x="0" y="0" width="100" height="100" fill="#123456"/>'
            '  <path d="M 0 0 L 100 100"/>'
            "</svg>"
        )
        target_spec = {
            "expected_types": ["rect", "path"],
            "palette": ["#123456"],
            "min_elements": 2,
            "min_paths": 1,
            "viewBox": [0.0, 0.0, 200.0, 200.0],
        }
        res = self.engine.perceptual_diff(svg_code, target_spec)
        self.assertGreaterEqual(res["similarity_score"], 0.9)
        self.assertEqual(res["coverage"], 1.0)
        self.assertEqual(len(res["diff_details"]), 0)

    def test_extract_palette_and_boxes(self) -> None:
        svg_code = (
            '<svg viewBox="0 0 100 100">'
            '  <rect x="10" y="20" width="30" height="40" fill="#abcdef" stroke="rgb(0, 128, 255)"/>'
            '  <circle cx="60" cy="70" r="15" style="fill: oklch(0.7 0.15 150); stroke: #ffffff"/>'
            "</svg>"
        )
        res = self.engine.extract_palette_and_boxes(svg_code)
        palette = res["palette"]
        self.assertIn("#abcdef", palette["fills"])
        self.assertIn("#ffffff", palette["strokes"])
        self.assertTrue(any("oklch" in c.lower() for c in palette["all_colors"]))

        boxes = res["bounding_boxes"]
        self.assertEqual(len(boxes), 2)
        rect_box = [b for b in boxes if b["tag"] == "rect"][0]
        self.assertEqual(rect_box["x"], 10.0)
        self.assertEqual(rect_box["y"], 20.0)
        self.assertEqual(rect_box["width"], 30.0)
        self.assertEqual(rect_box["height"], 40.0)


class TestDiagnosticsEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DiagnosticsEngine()

    def test_run_diagnostics_syntax_error(self) -> None:
        bad_code = "def broken(\n  return 1"
        diags = self.engine.run_diagnostics(bad_code)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0]["code"], "E999")
        self.assertEqual(diags[0]["severity"], "error")

    def test_run_diagnostics_unused_import(self) -> None:
        code = "import os\n\ndef run():\n    return 42\n"
        diags = self.engine.run_diagnostics(code)
        unused = [d for d in diags if d["code"] == "W0611"]
        self.assertEqual(len(unused), 1)
        self.assertEqual(unused[0]["symbol"], "os")

    def test_run_diagnostics_undefined_name(self) -> None:
        code = "def compute():\n    return unknown_symbol * 2\n"
        diags = self.engine.run_diagnostics(code)
        undef = [d for d in diags if d["code"] == "E0602"]
        self.assertEqual(len(undef), 1)
        self.assertEqual(undef[0]["symbol"], "unknown_symbol")

    def test_run_diagnostics_bare_except(self) -> None:
        code = "try:\n    x = 1\nexcept:\n    x = 0\n"
        diags = self.engine.run_diagnostics(code)
        bare = [d for d in diags if d["code"] == "W0702"]
        self.assertEqual(len(bare), 1)

    def test_apply_quick_fix_unused_import(self) -> None:
        code = "import os\n\ndef run():\n    return 42\n"
        diags = self.engine.run_diagnostics(code)
        unused_diag = [d for d in diags if d["code"] == "W0611"][0]
        fixed = self.engine.apply_quick_fix(unused_diag, code)
        self.assertNotIn("import os", fixed)

    def test_apply_quick_fix_undefined_name(self) -> None:
        code = "def calc():\n    return math.sqrt(16)\n"
        diags = self.engine.run_diagnostics(code)
        undef_diag = [d for d in diags if d["code"] == "E0602" and d["symbol"] == "math"][0]
        fixed = self.engine.apply_quick_fix(undef_diag, code)
        self.assertIn("import math", fixed)

    def test_apply_quick_fix_bare_except(self) -> None:
        code = "try:\n    x = 1\nexcept:\n    x = 0\n"
        diags = self.engine.run_diagnostics(code)
        bare_diag = [d for d in diags if d["code"] == "W0702"][0]
        fixed = self.engine.apply_quick_fix(bare_diag, code)
        self.assertIn("except Exception:", fixed)


class TestTreeSitterCodemodEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = TreeSitterCodemodEngine()

    def test_query_ast_functions(self) -> None:
        code = (
            "def add(a: int, b: int = 0) -> int:\n"
            '    """Add two numbers."""\n'
            "    return a + b\n"
        )
        nodes = self.engine.query_ast(code, node_type="FunctionDef")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "add")
        self.assertEqual(nodes[0]["args"], ["a", "b"])
        self.assertEqual(nodes[0]["docstring"], "Add two numbers.")

    def test_rename_symbol_safe(self) -> None:
        source = (
            "def calculate(value):\n"
            "    # Note: calculate is fast\n"
            '    msg = "do not calculate this calculate"\n'
            "    return calculate(value - 1) if value > 0 else 0\n"
        )
        new_code, count = self.engine.rename_symbol(source, "calculate", "compute")
        self.assertEqual(count, 2)  # Function definition and recursive call
        self.assertIn("def compute(value):", new_code)
        self.assertIn("return compute(value - 1)", new_code)
        # Verify comment and string were NOT touched
        self.assertIn("# Note: calculate is fast", new_code)
        self.assertIn('"do not calculate this calculate"', new_code)

    def test_verify_syntax(self) -> None:
        valid_py = "x = 42\n"
        invalid_py = "x = (\n"
        self.assertTrue(self.engine.verify_syntax(valid_py, "python")["valid"])
        self.assertFalse(self.engine.verify_syntax(invalid_py, "python")["valid"])

        valid_json = '{"a": 1, "b": [2, 3]}'
        invalid_json = '{"a": 1,}'
        self.assertTrue(self.engine.verify_syntax(valid_json, "json")["valid"])
        self.assertFalse(self.engine.verify_syntax(invalid_json, "json")["valid"])


class TestAtomicWorkspaceEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AtomicWorkspaceEngine()

    def test_checkpoint_inspect_and_rollback(self) -> None:
        initial_files = {
            "main.py": "def main():\n    print('hello')\n",
            "utils.py": "def util():\n    return 1\n",
        }
        chk_id = self.engine.create_checkpoint("task-101", initial_files)
        self.assertTrue(chk_id.startswith("chk_task-101_"))

        # Modify files
        current_files = {
            "main.py": "def main():\n    print('world')\n",  # modified
            "new.py": "NEW = True\n",                        # added
            # utils.py deleted
        }

        patch = self.engine.inspect_patch(chk_id, current_files)
        self.assertEqual(patch["files_changed"], 3)
        self.assertEqual(patch["details"]["main.py"]["status"], "modified")
        self.assertEqual(patch["details"]["new.py"]["status"], "added")
        self.assertEqual(patch["details"]["utils.py"]["status"], "deleted")

        # Rollback
        restored = self.engine.rollback(chk_id)
        self.assertEqual(restored, initial_files)

    def test_commit_milestone(self) -> None:
        files = {"config.json": '{"v": 1}'}
        chk_id = self.engine.create_checkpoint("milestone-task", files)
        milestone = self.engine.commit_milestone(chk_id, "Initial baseline commit")
        self.assertEqual(milestone["checkpoint_id"], chk_id)
        self.assertEqual(milestone["message"], "Initial baseline commit")
        self.assertEqual(milestone["status"], "committed")
        self.assertEqual(len(milestone["digest"]), 64)


class TestTestHarnessEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = TestHarnessEngine()

    def test_run_scratch_test_success(self) -> None:
        code = "print('harness_success')\n"
        res = self.engine.run_scratch_test(code, timeout_sec=3.0)
        self.assertTrue(res["success"])
        self.assertEqual(res["returncode"], 0)
        self.assertIn("harness_success", res["stdout"])
        self.assertFalse(res["timed_out"])

    def test_run_scratch_test_timeout(self) -> None:
        code = "import time\ntime.sleep(2.0)\n"
        res = self.engine.run_scratch_test(code, timeout_sec=0.2)
        self.assertFalse(res["success"])
        self.assertTrue(res["timed_out"])
        self.assertEqual(res["returncode"], -1)

    def test_concurrency_fuzz(self) -> None:
        code = (
            "counter = 0\n"
            "def target_fn():\n"
            "    global counter\n"
            "    counter += 1\n"
        )
        res = self.engine.concurrency_fuzz(code, threads=2, iterations=20)
        self.assertTrue(res["success"])
        self.assertFalse(res["race_conditions_detected"])

    def test_profile_memory_and_cpu(self) -> None:
        code = "data = [i ** 2 for i in range(10000)]\n"
        res = self.engine.profile_memory_and_cpu(code)
        self.assertTrue(res["success"])
        self.assertGreater(res["peak_memory_bytes"], 0)
        self.assertGreaterEqual(res["duration_ms"], 0.0)


class TestMutationVerifierEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MutationVerifierEngine()

    def test_inject_mutants(self) -> None:
        code = (
            "def check_value(x: int) -> bool:\n"
            "    if x > 10:\n"
            "        return True\n"
            "    return False\n"
        )
        mutants = self.engine.inject_mutants(code)
        self.assertGreaterEqual(len(mutants), 3)
        self.assertLessEqual(len(mutants), 5)
        for m in mutants:
            self.assertIn("mutant_id", m)
            self.assertIn("mutated_code", m)
            self.assertIn("mutation_type", m)

    def test_audit_test_strength_kills_mutants(self) -> None:
        source_code = (
            "def is_positive(x: int) -> bool:\n"
            "    if x > 0:\n"
            "        return True\n"
            "    return False\n"
        )
        # Strong test suite that tests > 0 thoroughly
        test_code = (
            "assert is_positive(5) is True\n"
            "assert is_positive(0) is False\n"
            "assert is_positive(-5) is False\n"
        )
        res = self.engine.audit_test_strength(source_code, test_code)
        self.assertGreater(res["mutants_total"], 0)
        self.assertGreater(res["mutants_killed"], 0)
        self.assertGreaterEqual(res["mutation_score"], 0.5)

    def test_audit_test_strength_detects_fake_tests(self) -> None:
        source_code = (
            "def is_positive(x: int) -> bool:\n"
            "    if x > 0:\n"
            "        return True\n"
            "    return False\n"
        )
        # Fake test that does not actually check function output
        fake_test = "assert True\nassert 1 == 1\n"
        res = self.engine.audit_test_strength(source_code, fake_test)
        self.assertEqual(res["mutants_killed"], 0)
        self.assertEqual(res["mutation_score"], 0.0)
        self.assertFalse(res["is_thorough"])


class TestMockAuditorEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MockAuditorEngine()

    def test_audit_assertions_flags_tautologies(self) -> None:
        test_code = (
            "def test_fake():\n"
            "    assert True\n"
            "    assert 1 == 1\n"
            "    self.assertTrue(True)\n"
        )
        res = self.engine.audit_assertions(test_code)
        self.assertFalse(res["passed_audit"])
        self.assertGreaterEqual(res["trivial_assertions_count"], 3)
        self.assertEqual(len(res["tautologies"]), res["trivial_assertions_count"])

    def test_audit_assertions_passes_clean_test(self) -> None:
        clean_code = (
            "def test_real():\n"
            "    result = 2 + 2\n"
            "    assert result == 4\n"
        )
        res = self.engine.audit_assertions(clean_code)
        self.assertTrue(res["passed_audit"])
        self.assertEqual(res["trivial_assertions_count"], 0)

    def test_detect_mock_leakage(self) -> None:
        excessive_mock_code = (
            "from unittest.mock import Mock, patch\n"
            "@patch('service.api')\n"
            "def test_stubbed(mock_api):\n"
            "    m1 = Mock()\n"
            "    m2 = Mock()\n"
            "    m3 = Mock()\n"
        )
        res = self.engine.detect_mock_leakage(excessive_mock_code)
        self.assertGreaterEqual(res["mock_count"], 3)
        self.assertTrue(res["has_excessive_mocking"])

    def test_enforce_negative_paths(self) -> None:
        code_with_negatives = (
            "import unittest\n"
            "class TestErrors(unittest.TestCase):\n"
            "    def test_invalid_input_error(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            int('abc')\n"
        )
        res = self.engine.enforce_negative_paths(code_with_negatives)
        self.assertTrue(res["has_negative_tests"])
        self.assertGreaterEqual(res["negative_test_count"], 1)


class TestPropertyOracleEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PropertyOracleEngine()

    def test_generate_property_matrix(self) -> None:
        matrix = self.engine.generate_property_matrix(["str", "int", "float", "list"], count=30)
        self.assertEqual(len(matrix), 30)
        # Check boundary elements exist
        self.assertTrue(any(isinstance(x, str) and x == "" for x in matrix))
        self.assertTrue(any(isinstance(x, int) and x == 0 for x in matrix))
        self.assertTrue(any(isinstance(x, float) for x in matrix))
        self.assertTrue(any(isinstance(x, list) and len(x) == 0 for x in matrix))

    def test_verify_algebraic_invariants_holds(self) -> None:
        module_code = (
            "import json\n"
            "def encode(x):\n"
            "    return json.dumps(x)\n"
            "def decode(s):\n"
            "    return json.loads(s)\n"
        )
        sample_inputs = [{"a": 1}, [1, 2, 3], "test string", 42, True]
        res = self.engine.verify_algebraic_invariants(module_code, "encode", "decode", sample_inputs)
        self.assertTrue(res["roundtrip_invariant_holds"])
        self.assertEqual(res["passed"], 5)
        self.assertEqual(res["failed"], 0)

    def test_verify_algebraic_invariants_fails(self) -> None:
        module_code = (
            "def encode(x):\n"
            "    return x + 1\n"
            "def decode(x):\n"
            "    return x  # buggy decode, missing - 1\n"
        )
        sample_inputs = [10, 20, 30]
        res = self.engine.verify_algebraic_invariants(module_code, "encode", "decode", sample_inputs)
        self.assertFalse(res["roundtrip_invariant_holds"])
        self.assertEqual(res["failed"], 3)
        self.assertGreaterEqual(len(res["failure_examples"]), 1)


class TestReceiptAttestorEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ReceiptAttestorEngine()

    def test_attest_execution_and_verify(self) -> None:
        cmd = [sys.executable, "-c", "print('attest_test_output')"]
        receipt = self.engine.attest_execution(cmd)
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("attest_test_output", receipt["stdout"])
        self.assertTrue(receipt["tamper_evident"])
        self.assertGreater(receipt["pid"], 0)

        # Verification must pass
        self.assertTrue(self.engine.verify_receipt(receipt))

    def test_verify_receipt_tampered(self) -> None:
        cmd = [sys.executable, "-c", "print('ok')"]
        receipt = self.engine.attest_execution(cmd)
        self.assertTrue(self.engine.verify_receipt(receipt))

        # Tamper with stdout
        tampered_receipt = dict(receipt)
        tampered_receipt["stdout"] = "tampered output\n"
        self.assertFalse(self.engine.verify_receipt(tampered_receipt))

        # Tamper with exit code
        tampered_exit = dict(receipt)
        tampered_exit["exit_code"] = 1
        self.assertFalse(self.engine.verify_receipt(tampered_exit))


class TestComputeOrchestratorEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ComputeOrchestratorEngine()

    def test_calculate_thinking_budget(self) -> None:
        # Low complexity
        low_res = self.engine.calculate_thinking_budget(complexity_score=2.0, failure_count=0)
        self.assertEqual(low_res["model_tier"], "flash")
        self.assertLessEqual(low_res["recommended_tokens"], 16384)

        # High complexity with failures
        high_res = self.engine.calculate_thinking_budget(complexity_score=9.0, failure_count=2)
        self.assertEqual(high_res["model_tier"], "deepthink")
        self.assertGreaterEqual(high_res["recommended_tokens"], 32768)

    def test_mcts_explore(self) -> None:
        spec = {"problem": "find best search algorithm", "strategies": ["binary_search", "hash_index", "b_tree"]}
        res = self.engine.mcts_explore(spec, branches=3, depth=2)
        self.assertGreater(res["root_visits"], 0)
        self.assertIn("best_branch", res)
        self.assertGreater(len(res["recommended_path"]), 0)
        self.assertEqual(len(res["tree_summary"]), 3)

    def test_best_of_n_consensus(self) -> None:
        candidates = [
            {"id": "cand_A", "score": 0.95, "test_pass_rate": 1.0, "complexity": 3.0},
            {"id": "cand_B", "score": 0.80, "test_pass_rate": 0.9, "complexity": 7.0},
            {"id": "cand_C", "score": 0.50, "test_pass_rate": 0.6, "complexity": 9.0},
        ]
        res = self.engine.best_of_n_consensus(candidates)
        self.assertEqual(res["selected_candidate"]["id"], "cand_A")
        self.assertGreater(res["consensus_score"], 0.0)
        self.assertEqual(len(res["rankings"]), 3)


class TestCoderFleetDispatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = CoderFleetDispatcher()

    def test_list_actions(self) -> None:
        actions = self.dispatcher.list_actions()
        expected = [
            "render_vector", "perceptual_diff", "extract_palette_and_boxes",
            "run_diagnostics", "apply_quick_fix",
            "query_ast", "rename_symbol", "verify_syntax",
            "create_checkpoint", "inspect_patch", "rollback", "commit_milestone",
            "run_scratch_test", "concurrency_fuzz", "profile_memory_and_cpu",
            "inject_mutants", "audit_test_strength",
            "audit_assertions", "detect_mock_leakage", "enforce_negative_paths",
            "generate_property_matrix", "verify_algebraic_invariants",
            "attest_execution", "verify_receipt",
            "calculate_thinking_budget", "mcts_explore", "best_of_n_consensus",
        ]
        for a in expected:
            self.assertIn(a, actions)

    def test_dispatch_render_vector(self) -> None:
        svg_code = '<svg viewBox="0 0 50 50"><circle cx="25" cy="25" r="20"/></svg>'
        res = self.dispatcher.dispatch("render_vector", {"code": svg_code})
        self.assertTrue(res["success"])
        self.assertTrue(res["result"]["valid"])

    def test_dispatch_run_diagnostics(self) -> None:
        res = self.dispatcher.dispatch("run_diagnostics", {"source_code": "x = 1\n"})
        self.assertTrue(res["success"])
        self.assertEqual(len(res["result"]), 0)

    def test_dispatch_unknown_action(self) -> None:
        res = self.dispatcher.dispatch("unknown_fleet_action", {})
        self.assertFalse(res["success"])
        self.assertIn("Unknown fleet action", res["error"])


if __name__ == "__main__":
    unittest.main()
