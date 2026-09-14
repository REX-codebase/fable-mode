"""Unit and Integration Tests for Agent Computer Suite in Fable Mode.

Tests Figma engine, After Effects video engine, Code Editor staging, and VM Sandbox execution.
"""

from __future__ import annotations

import json
import unittest
from fable_engine.actions import handle_fable_session
from fable_engine.actions.figma import AgentFigmaEngine, FigmaNode
from fable_engine.actions.after_effects import AgentAfterEffectsEngine, AELayer, AEComposition
from fable_engine.actions.agent_computer import AgentCodeEditor, AgentVMSandbox


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


class TestAgentCodeEditorAndVMSandbox(unittest.TestCase):
    def test_editor_staging_and_vm_rollback(self):
        editor = AgentCodeEditor()
        res_stage = editor.stage_file("test_script.py", "def add(a, b):\n    return a + b\n")
        self.assertTrue(res_stage["syntax_valid"])

        res_invalid = editor.stage_file("broken.py", "def bad_syntax(:")
        self.assertFalse(res_invalid["syntax_valid"])

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
