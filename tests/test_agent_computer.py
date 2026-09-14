"""Unit and Integration Tests for Agent Computer Suite in Fable Mode.

Tests Figma engine, After Effects video engine, Code Editor staging, and VM Sandbox execution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree
from fable_engine.actions import handle_fable_session
from fable_engine.actions.figma import AgentFigmaEngine, FigmaNode
from fable_engine.actions.after_effects import (
    MAX_RENDERED_FRAMES,
    AgentAfterEffectsEngine,
    AELayer,
    AEComposition,
)
from fable_engine.actions.agent_computer import (
    AgentCodeEditor,
    AgentVMSandbox,
    _handle_vm_test_and_commit,
)


class TestAgentFigmaEngine(unittest.TestCase):
    def test_figma_node_and_layout(self):
        root = FigmaNode("root", "Root Frame", "FRAME", width=1000, height=800, layout_mode="HORIZONTAL", item_spacing=10)
        c1 = FigmaNode("c1", "Card 1", "RECTANGLE", width=200, height=300, fill="#10B981")
        c2 = FigmaNode("c2", "Card 2", "RECTANGLE", width=200, height=300, fill="#6366F1")
        root.add_child(c1)
        root.add_child(c2)
        root.solve_layout()

        self.assertEqual(c1.x, 0.0)
        self.assertEqual(c2.x, 210.0)

        svg = root.render_svg()
        self.assertIn('<rect x="0.0" y="0.0" width="1000.0" height="800.0"', svg)
        self.assertIn('<rect x="0.0" y="0.0" width="200.0" height="300.0"', svg)
        self.assertIn('<rect x="210.0" y="0.0" width="200.0" height="300.0"', svg)

    def test_svg_escapes_text_and_dynamic_attributes(self):
        node = FigmaNode(
            "text",
            "Text",
            "TEXT",
            fill='red" onload="bad',
            text_content="<unsafe>&text",
            font_family='A "quoted" font',
            font_weight='bold" bad="1',
            opacity=0.5,
        )
        svg = f"<svg>{node.render_svg()}</svg>"
        parsed = ElementTree.fromstring(svg)
        text = parsed.find("text")
        self.assertIsNotNone(text)
        self.assertEqual(text.text, "<unsafe>&text")
        self.assertEqual(text.attrib["fill"], 'red" onload="bad')

    def test_node_ids_are_canvas_wide_unique(self):
        engine = AgentFigmaEngine()
        parent = engine.add_node("unique", None, {"node_id": "parent"})
        nested = engine.add_node("unique", parent.node_id, {})
        sibling = engine.add_node("unique", None, {})
        self.assertNotEqual(nested.node_id, sibling.node_id)
        with self.assertRaisesRegex(ValueError, "already exists"):
            engine.add_node("unique", None, {"node_id": nested.node_id})

    def test_padding_and_canvas_dimensions_are_bounded(self):
        engine = AgentFigmaEngine()
        with self.assertRaisesRegex(ValueError, "exactly four"):
            engine.add_node("padding", None, {"padding": [1, 2, 3]})
        with self.assertRaisesRegex(ValueError, "finite"):
            engine.add_node("padding", None, {"padding": [0, 0, float("nan"), 0]})

        response = handle_fable_session({
            "action": "figma_design",
            "figma_action": "create_canvas",
            "canvas_id": "oversized",
            "width": 10_000,
            "height": 10,
        })
        self.assertTrue(response.startswith("Error:"), response)

    def test_figma_action_dispatch(self):
        res_str = handle_fable_session({
            "action": "figma_design",
            "figma_action": "create_canvas",
            "canvas_id": "test_canvas",
            "width": 1280,
            "height": 720
        })
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")

        res_str2 = handle_fable_session({
            "action": "figma_design",
            "figma_action": "add_node",
            "canvas_id": "test_canvas",
            "node_data": {
                "name": "Header Text",
                "node_type": "TEXT",
                "text_content": "Welcome to Agent Computer",
                "font_size": 32
            }
        })
        res2 = json.loads(res_str2)
        self.assertEqual(res2["status"], "success")

        res_str3 = handle_fable_session({
            "action": "figma_design",
            "figma_action": "export",
            "canvas_id": "test_canvas",
            "format": "svg"
        })
        res3 = json.loads(res_str3)
        self.assertEqual(res3["status"], "success")
        self.assertIn("<svg", res3["output"])


class TestAgentAfterEffectsEngine(unittest.TestCase):
    def test_ae_keyframes_and_rendering(self):
        comp = AEComposition("comp1", "Test Video", width=1920, height=1080, duration_sec=2.0, fps=10.0)
        layer = AELayer("l1", "Moving Box", "SHAPE", width=100, height=100, fill="#F59E0B")
        layer.tracks["x"].add_keyframe(0.0, 0.0)
        layer.tracks["x"].add_keyframe(2.0, 500.0)
        comp.add_layer(layer)

        frame0 = comp.render_frame_svg(0.0)
        self.assertIn('translate(0.0, 0.0)', frame0)

        frame_mid = comp.render_frame_svg(1.0)
        self.assertIn('translate(250.0, 0.0)', frame_mid)

        frame_end = comp.render_frame_svg(2.0)
        self.assertIn('translate(500.0, 0.0)', frame_end)

        video = comp.render_video_sequence()
        self.assertEqual(len(video), 20)

    def test_video_frame_count_is_bounded(self):
        comp = AEComposition("bounded", "Bounded", duration_sec=MAX_RENDERED_FRAMES + 1, fps=1)
        with self.assertRaisesRegex(ValueError, "frame limit"):
            comp.render_video_sequence()
        overflow = AEComposition("overflow", "Overflow", duration_sec=1e308, fps=1e308)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            overflow.render_video_sequence()

    def test_text_layer_svg_is_xml_safe(self):
        layer = AELayer(
            "text",
            "Text",
            "TEXT",
            fill='blue" onload="bad',
            text_content="<unsafe>&text",
        )
        parsed = ElementTree.fromstring(f"<svg>{layer.render_svg_element(0)}</svg>")
        text = parsed.find("text")
        self.assertIsNotNone(text)
        self.assertEqual(text.text, "<unsafe>&text")
        self.assertEqual(text.attrib["fill"], 'blue" onload="bad')

    def test_ae_action_dispatch(self):
        res_str = handle_fable_session({
            "action": "ae_render_video",
            "ae_action": "create_comp",
            "comp_id": "promo_comp",
            "duration_sec": 1.0
        })
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")

        res_str2 = handle_fable_session({
            "action": "ae_render_video",
            "ae_action": "render_video",
            "comp_id": "promo_comp"
        })
        res2 = json.loads(res_str2)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["total_frames"], 30)


class TestAgentCodeEditorAndVMSandbox(unittest.TestCase):
    def test_editor_staging_and_vm_rollback(self):
        editor = AgentCodeEditor()
        res_stage = editor.stage_file("test_script.py", "def add(a, b):\n    return a + b\n")
        self.assertTrue(res_stage["syntax_valid"])

        res_invalid = editor.stage_file("broken.py", "def bad_syntax(:")
        self.assertFalse(res_invalid["syntax_valid"])
        self.assertIsNone(editor.get_staged("broken.py"))

    def test_editor_rejects_absolute_and_traversal_paths(self):
        editor = AgentCodeEditor()
        for filepath in ("/tmp/escape.py", "../escape.py", "safe/../../escape.py", "C:\\escape.py"):
            with self.subTest(filepath=filepath), self.assertRaises(PermissionError):
                editor.stage_file(filepath, "x = 1\n")

    def test_vm_copies_baseline_before_overlay_and_promotes(self):
        with tempfile.TemporaryDirectory() as host_dir:
            host = Path(host_dir)
            (host / "tests").mkdir()
            (host / "tests" / "test_baseline.py").write_text("baseline", encoding="utf-8")
            (host / "module.py").write_text("old", encoding="utf-8")
            sandbox = AgentVMSandbox(host)

            def inspect_workspace(workspace, _command):
                self.assertEqual((workspace / "tests" / "test_baseline.py").read_text(), "baseline")
                self.assertEqual((workspace / "module.py").read_text(), "new")
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

            with patch.object(sandbox, "_run_tests", side_effect=inspect_workspace):
                result = sandbox.run_tests_and_promote({"module.py": "new"})

            self.assertEqual(result["status"], "promoted")
            self.assertEqual((host / "module.py").read_text(), "new")
            self.assertTrue((host / "tests" / "test_baseline.py").exists())

    def test_atomic_promotion_restores_earlier_replacements(self):
        with tempfile.TemporaryDirectory() as host_dir:
            host = Path(host_dir)
            first = host / "first.py"
            second = host / "second.py"
            first.write_text("first-old", encoding="utf-8")
            second.write_text("second-old", encoding="utf-8")
            sandbox = AgentVMSandbox(host)
            real_replace = os.replace

            def fail_second_new_file(source, destination):
                if Path(source).name.startswith(".fable-new-") and Path(destination) == second:
                    raise OSError("simulated replacement failure")
                return real_replace(source, destination)

            with patch.object(sandbox, "_run_tests", return_value={
                "exit_code": 0, "stdout": "", "stderr": ""
            }), patch("fable_engine.actions.agent_computer.os.replace", side_effect=fail_second_new_file):
                result = sandbox.run_tests_and_promote({
                    "first.py": "first-new",
                    "second.py": "second-new",
                })

            self.assertEqual(result["status"], "error")
            self.assertEqual(first.read_text(), "first-old")
            self.assertEqual(second.read_text(), "second-old")

    def test_sandbox_command_unshares_network_and_uses_no_host_shell(self):
        with tempfile.TemporaryDirectory() as host_dir:
            workspace = Path(host_dir)
            sandbox = AgentVMSandbox(workspace)
            with patch("fable_engine.actions.agent_computer.shutil.which", return_value="/usr/bin/bwrap"):
                command = sandbox._sandbox_command(workspace, "python -m unittest")
            self.assertIn("--unshare-all", command)
            self.assertIn("--cap-drop", command)
            self.assertIn("--bind", command)
            self.assertEqual(command[-3:], ["/bin/sh", "-c", "python -m unittest"])

    def test_vm_action_requires_unlocked_session_and_rejects_host_root(self):
        locked = SimpleNamespace(execution_locked=True, can_execute_code=False)
        with patch("fable_engine.actions.agent_computer.get_or_load_session", return_value=locked):
            result = _handle_vm_test_and_commit({"session_name": "locked"})
        self.assertIn("execution is locked", result)

        result = _handle_vm_test_and_commit({"session_name": "any", "host_root": "/tmp"})
        self.assertIn("cannot be supplied", result)

    def test_agent_computer_action_dispatch(self):
        res_str = handle_fable_session({
            "action": "editor_stage_diff",
            "editor_action": "stage",
            "filepath": "sample.py",
            "content": "# Sample code\nx = 42\n"
        })
        res = json.loads(res_str)
        self.assertEqual(res["status"], "staged")

        res_view = handle_fable_session({
            "action": "editor_stage_diff",
            "editor_action": "view_staged",
            "filepath": "sample.py"
        })
        res_v = json.loads(res_view)
        self.assertEqual(res_v["status"], "found")
        self.assertIn("x = 42", res_v["content"])


if __name__ == "__main__":
    unittest.main()
