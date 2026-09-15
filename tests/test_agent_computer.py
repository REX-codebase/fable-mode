"""Unit and Integration Tests for Agent Computer Suite in Fable Mode.

Tests Figma engine, After Effects video engine, Code Editor staging, and VM Sandbox execution.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree
from fable_engine.actions import handle_fable_session
from fable_engine.actions.figma import AgentFigmaEngine, FigmaNode, MAX_CANVAS_DIMENSION
from fable_engine.actions.after_effects import (
    AgentAfterEffectsEngine,
    AELayer,
    AEComposition,
    MAX_RENDER_FRAMES,
)
from fable_engine.actions.agent_computer import (
    AgentCodeEditor,
    AgentVMSandbox,
    _handle_vm_test_and_commit,
    _resolve_confined,
)
from fable_engine.actions.resource_registry import MAX_DESIGN_RESOURCES


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

    def test_space_between_layout_for_both_orientations(self):
        horizontal = FigmaNode("h", "H", width=500, height=100, layout_mode="HORIZONTAL", align_items="SPACE_BETWEEN")
        horizontal.add_child(FigmaNode("h1", "H1", width=100, height=20))
        horizontal.add_child(FigmaNode("h2", "H2", width=100, height=20))
        horizontal.add_child(FigmaNode("h3", "H3", width=100, height=20))
        horizontal.solve_layout()
        self.assertEqual([child.x for child in horizontal.children], [0.0, 200.0, 400.0])

        vertical = FigmaNode("v", "V", width=100, height=500, layout_mode="VERTICAL", align_items="SPACE_BETWEEN")
        vertical.add_child(FigmaNode("v1", "V1", width=20, height=100))
        vertical.add_child(FigmaNode("v2", "V2", width=20, height=100))
        vertical.solve_layout()
        self.assertEqual([child.y for child in vertical.children], [0.0, 400.0])

    def test_figma_svg_text_is_xml_safe(self):
        node = FigmaNode(
            "text",
            "Text",
            node_type="TEXT",
            text_content='<unsafe & "text">',
            font_family='Bad"Font & Co',
            font_weight='bold" onclick="x',
            fill='red" data-x="1',
        )
        rendered = node.render_svg()
        parsed = ElementTree.fromstring(rendered)
        self.assertEqual(parsed.text, '<unsafe & "text">')
        self.assertEqual(parsed.attrib["font-family"], 'Bad"Font & Co')

    def test_canvas_wide_node_ids_are_unique(self):
        engine = AgentFigmaEngine()
        parent = engine.add_node("ids", None, {"node_id": "parent"})
        nested = engine.add_node("ids", parent.node_id, {})
        sibling = engine.add_node("ids", None, {})
        self.assertNotEqual(nested.node_id, sibling.node_id)
        with self.assertRaisesRegex(ValueError, "already exists"):
            engine.add_node("ids", None, {"node_id": nested.node_id})

    def test_padding_and_canvas_dimensions_are_validated(self):
        engine = AgentFigmaEngine()
        with self.assertRaises(ValueError):
            engine.add_node("padding", None, {"padding": [1, 2, 3]})
        self.assertNotIn("padding", engine.canvases)
        with self.assertRaises(ValueError):
            engine.add_node("padding", None, {"padding": [1, 2, 3, math.inf]})
        node = engine.add_node("padding", None, {"padding": [1, 2, 3, 4]})
        self.assertEqual(node.padding, (1.0, 2.0, 3.0, 4.0))

        invalid = handle_fable_session({
            "action": "figma_design",
            "figma_action": "create_canvas",
            "canvas_id": "too_large",
            "width": MAX_CANVAS_DIMENSION + 1,
            "height": 10,
        })
        self.assertTrue(invalid.startswith("Error:"), invalid)
        subpixel = handle_fable_session({
            "action": "figma_design",
            "figma_action": "create_canvas",
            "canvas_id": "subpixel",
            "width": 0.5,
            "height": 10,
        })
        self.assertTrue(subpixel.startswith("Error:"), subpixel)

    def test_figma_and_ae_registries_share_a_bound(self):
        figma = AgentFigmaEngine()
        after_effects = AgentAfterEffectsEngine()
        for index in range(MAX_DESIGN_RESOURCES + 5):
            if index % 2:
                figma.get_or_create_canvas(f"canvas-{index}")
            else:
                after_effects.get_or_create_comp(f"comp-{index}")
        self.assertLessEqual(len(figma.canvases) + len(after_effects.compositions), MAX_DESIGN_RESOURCES)


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

    def test_ae_render_is_bounded_and_text_is_xml_safe(self):
        oversized = AEComposition("large", "Large", duration_sec=MAX_RENDER_FRAMES + 1, fps=1)
        with self.assertRaisesRegex(ValueError, "maximum"):
            oversized.render_video_sequence()

        layer = AELayer(
            "text",
            "Text",
            layer_type="TEXT",
            text_content='<unsafe & "text">',
            fill='red" data-x="1',
        )
        rendered = layer.render_svg_element(0)
        parsed = ElementTree.fromstring(rendered)
        self.assertEqual(parsed.text, '<unsafe & "text">')
        self.assertEqual(parsed.attrib["fill"], 'red" data-x="1')


class TestAgentCodeEditorAndVMSandbox(unittest.TestCase):
    def test_editor_staging_and_vm_rollback(self):
        editor = AgentCodeEditor()
        res_stage = editor.stage_file("test_script.py", "def add(a, b):\n    return a + b\n")
        self.assertTrue(res_stage["syntax_valid"])

        res_invalid = editor.stage_file("broken.py", "def bad_syntax(:")
        self.assertFalse(res_invalid["syntax_valid"])
        self.assertIsNone(editor.get_staged("broken.py"))

        editor.stage_file("test_script.py", "def broken(:")
        self.assertIn("return a + b", editor.get_staged("test_script.py") or "")

    def test_editor_and_vm_paths_are_confined(self):
        editor = AgentCodeEditor()
        for filepath in ("../escape.py", "/tmp/escape.py", "C:\\escape.py", "a\\..\\escape.py"):
            with self.assertRaises(ValueError, msg=filepath):
                editor.stage_file(filepath, "value = 1\n")

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            self.assertEqual(_resolve_confined(root_path, "src/good.py"), root_path / "src" / "good.py")
            with self.assertRaises(ValueError):
                _resolve_confined(root_path, "../bad.py")

    def test_vm_copies_baseline_before_overlay_and_uses_namespace(self):
        with tempfile.TemporaryDirectory() as host, tempfile.NamedTemporaryFile() as host_sentinel:
            host_root = Path(host)
            (host_root / "tests").mkdir()
            (host_root / "tests" / "baseline.txt").write_text("baseline", encoding="utf-8")
            (host_root / "target.py").write_text("old\n", encoding="utf-8")
            command = (
                f"{sys.executable} -c \"from pathlib import Path; import socket; "
                "assert Path('tests/baseline.txt').read_text() == 'baseline'; "
                "assert Path('target.py').read_text() == 'new\\n'; "
                f"assert not Path('{host_sentinel.name}').exists(); "
                "assert socket.socket().connect_ex(('1.1.1.1', 80)) != 0\""
            )
            with mock.patch("fable_engine.actions.agent_computer.TRUSTED_HOST_ROOT", host_root):
                result = AgentVMSandbox().run_tests_and_promote({"target.py": "new\n"}, command)
            self.assertEqual(result["status"], "promoted", result)
            self.assertEqual((host_root / "target.py").read_text(encoding="utf-8"), "new\n")

    def test_atomic_promotion_restores_all_files_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as host, tempfile.TemporaryDirectory() as sandbox:
            host_root = Path(host)
            sandbox_root = Path(sandbox)
            first = host_root / "first.py"
            second = host_root / "second.py"
            first.write_text("first-old", encoding="utf-8")
            second.write_text("second-old", encoding="utf-8")
            confined = [
                ("first.py", "first-new", sandbox_root / "first.py", first),
                ("second.py", "second-new", sandbox_root / "second.py", second),
            ]
            real_replace = os.replace
            staged_replacements = 0

            def fail_second_stage(source, destination):
                nonlocal staged_replacements
                if ".stage-" in str(source):
                    staged_replacements += 1
                    if staged_replacements == 2:
                        raise OSError("injected replacement failure")
                return real_replace(source, destination)

            with mock.patch("fable_engine.actions.agent_computer.os.replace", side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, "injected"):
                    AgentVMSandbox._promote_atomically(host_root, confined)
            self.assertEqual(first.read_text(encoding="utf-8"), "first-old")
            self.assertEqual(second.read_text(encoding="utf-8"), "second-old")

    def test_vm_handler_requires_unlocked_session_and_rejects_host_root(self):
        with mock.patch("fable_engine.actions.agent_computer.get_or_load_session") as load_session:
            load_session.return_value = SimpleNamespace(execution_locked=True, can_execute_code=False)
            locked = _handle_vm_test_and_commit({"session_name": "session"})
            self.assertIn("execution is locked", locked)

            load_session.return_value = SimpleNamespace(execution_locked=False, can_execute_code=True)
            overridden = _handle_vm_test_and_commit({"session_name": "session", "host_root": "/tmp"})
            self.assertIn("cannot be supplied", overridden)

    def test_agent_computer_action_fields_are_declared_in_schema(self):
        schema_path = Path(__file__).parents[1] / "fable_engine" / "fable_session.json"
        properties = json.loads(schema_path.read_text(encoding="utf-8"))["parameters"]["properties"]
        expected = {
            "figma_action",
            "canvas_id",
            "ae_action",
            "comp_id",
            "editor_action",
            "filepath",
            "test_command",
            "host_root",
        }
        self.assertEqual(expected - properties.keys(), set())
        self.assertTrue(all(properties[name]["type"] == "string" for name in expected))

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
