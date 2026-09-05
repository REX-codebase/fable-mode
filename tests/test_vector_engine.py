"""Comprehensive Unit Test Suite for Fable-Vector Neuro-Symbolic Vector Engine.

Verifies:
1. OKLCHColor and APCA contrast calibration (|Lc| >= 60, WCAG AAA accessibility, relative luminance, edge cases).
2. ParametricGeometry (Polar/Cartesian, circular arcs, Catmull-Rom splines with C1/C2 continuity, isometric matrix).
3. BoundingBox (spatial queries, intersections, enclosure, viewBox formatting).
4. VNode (AST tree structure, serialization, defensive sanitization).
5. VLayoutSolver (relational constraints, viewport pinning, thread-safety, defensive guards against NaN/Inf/null-bytes/deep-nesting).
6. FableVectorCompiler (XML AST well-formedness, viewBox enclosure, procedural noise filters, OKLCH gradients, a11y).
7. CoderFleetDispatcher vector integration ("compile_vector" and "solve_layout" actions).
"""
from __future__ import annotations

import concurrent.futures
import math
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fable_v2.coder_fleet import (
    BoundingBox,
    CoderFleetDispatcher,
    FableVectorCompiler,
    OKLCHColor,
    ParametricGeometry,
    VLayoutSolver,
    VNode,
)


class TestOKLCHColorAndAPCA(unittest.TestCase):
    """Test suite for OKLCH color space math, luminance, and APCA contrast scoring."""

    def test_oklch_initialization_and_clamping(self) -> None:
        c1 = OKLCHColor(l=0.75, c=0.15, h=250.0, alpha=0.9)
        self.assertAlmostEqual(c1.l, 0.75)
        self.assertAlmostEqual(c1.c, 0.15)
        self.assertAlmostEqual(c1.h, 250.0)
        self.assertAlmostEqual(c1.alpha, 0.9)

        # Defensive clamping for out-of-bound inputs
        c2 = OKLCHColor(l=-0.5, c=-0.1, h=400.0, alpha=1.5)
        self.assertEqual(c2.l, 0.0)
        self.assertEqual(c2.c, 0.0)
        self.assertAlmostEqual(c2.h, 40.0)
        self.assertEqual(c2.alpha, 1.0)

        # Defensive coercion for NaN and Inf
        c3 = OKLCHColor(l=float("nan"), c=float("inf"), h=float("-inf"), alpha=float("nan"))
        self.assertEqual(c3.l, 0.0)
        self.assertEqual(c3.c, 0.0)
        self.assertEqual(c3.h, 0.0)
        self.assertEqual(c3.alpha, 1.0)

    def test_to_svg_formatting(self) -> None:
        c_opaque = OKLCHColor(l=0.96, c=0.01, h=270.0, alpha=1.0)
        self.assertEqual(c_opaque.to_svg(), "oklch(0.9600 0.0100 270.00)")

        c_translucent = OKLCHColor(l=0.12, c=0.02, h=270.0, alpha=0.85)
        self.assertEqual(c_translucent.to_svg(), "oklch(0.1200 0.0200 270.00 / 0.85)")

    def test_estimated_y_relative_luminance(self) -> None:
        # Achromatic black
        black = OKLCHColor(l=0.0, c=0.0, h=0.0)
        self.assertAlmostEqual(black.estimated_y(), 0.0, places=4)

        # Achromatic white
        white = OKLCHColor(l=1.0, c=0.0, h=0.0)
        self.assertAlmostEqual(white.estimated_y(), 1.0, places=4)

        # Mid-gray achromatic: Y == l^3
        mid_gray = OKLCHColor(l=0.5, c=0.0, h=0.0)
        self.assertAlmostEqual(mid_gray.estimated_y(), 0.125, places=4)

        # Chromatic color should produce valid Y in [0, 1]
        cyan = OKLCHColor(l=0.75, c=0.18, h=190.0)
        y_cyan = cyan.estimated_y()
        self.assertGreaterEqual(y_cyan, 0.0)
        self.assertLessEqual(y_cyan, 1.0)

    def test_apca_contrast_high_contrast_pairs(self) -> None:
        """Verify APCA contrast meets or exceeds |Lc| >= 60 for accessible typography."""
        # Cyber-Obsidian Monolith design tokens:
        # Light text on deep obsidian substrate (WoB - negative score)
        text_primary = OKLCHColor(l=0.96, c=0.01, h=270.0)   # High-contrast read
        void_deep = OKLCHColor(l=0.08, c=0.02, h=270.0)      # Deep obsidian
        lc_wob = text_primary.apca_contrast(void_deep)

        self.assertLess(lc_wob, 0.0, "Light text on dark bg should yield negative Lc in APCA")
        self.assertGreaterEqual(abs(lc_wob), 60.0, f"Expected |Lc| >= 60, got {abs(lc_wob)}")
        self.assertGreaterEqual(abs(lc_wob), 75.0, f"Expected WCAG AAA |Lc| >= 75, got {abs(lc_wob)}")

        # Dark text on light background (BoW - positive score)
        dark_text = OKLCHColor(l=0.08, c=0.02, h=270.0)
        light_bg = OKLCHColor(l=0.98, c=0.01, h=270.0)
        lc_bow = dark_text.apca_contrast(light_bg)

        self.assertGreater(lc_bow, 0.0, "Dark text on light bg should yield positive Lc in APCA")
        self.assertGreaterEqual(lc_bow, 60.0, f"Expected Lc >= 60, got {lc_bow}")
        self.assertGreaterEqual(lc_bow, 75.0, f"Expected WCAG AAA Lc >= 75, got {lc_bow}")

    def test_apca_contrast_edge_cases(self) -> None:
        # Identical colors must have zero contrast
        color = OKLCHColor(l=0.5, c=0.1, h=180.0)
        self.assertAlmostEqual(color.apca_contrast(color), 0.0, places=3)

        # Extremely small delta luminance below noise threshold
        c_a = OKLCHColor(l=0.500, c=0.0, h=0.0)
        c_b = OKLCHColor(l=0.5001, c=0.0, h=0.0)
        self.assertEqual(c_a.apca_contrast(c_b), 0.0)

    def test_from_hex_conversion(self) -> None:
        c_black = OKLCHColor.from_hex("#000000")
        self.assertAlmostEqual(c_black.l, 0.0, places=3)
        self.assertAlmostEqual(c_black.c, 0.0, places=3)

        c_white = OKLCHColor.from_hex("#ffffff")
        self.assertAlmostEqual(c_white.l, 1.0, places=3)
        self.assertAlmostEqual(c_white.c, 0.0, places=3)

        # Contrast between white and black
        lc = c_white.apca_contrast(c_black)
        self.assertGreaterEqual(abs(lc), 100.0)


class TestParametricGeometry(unittest.TestCase):
    """Test suite for 2D parametric geometry, arcs, splines, and isometric projection."""

    def test_polar_to_cartesian(self) -> None:
        # Center (100, 100), radius 50
        x, y = ParametricGeometry.polar_to_cartesian(100.0, 100.0, 50.0, 0.0)
        self.assertAlmostEqual(x, 150.0, places=3)
        self.assertAlmostEqual(y, 100.0, places=3)

        x, y = ParametricGeometry.polar_to_cartesian(100.0, 100.0, 50.0, 90.0)
        self.assertAlmostEqual(x, 100.0, places=3)
        self.assertAlmostEqual(y, 150.0, places=3)

        x, y = ParametricGeometry.polar_to_cartesian(100.0, 100.0, 50.0, 180.0)
        self.assertAlmostEqual(x, 50.0, places=3)
        self.assertAlmostEqual(y, 100.0, places=3)

        x, y = ParametricGeometry.polar_to_cartesian(100.0, 100.0, 50.0, 270.0)
        self.assertAlmostEqual(x, 100.0, places=3)
        self.assertAlmostEqual(y, 50.0, places=3)

    def test_circular_arc(self) -> None:
        # 90 degree arc
        arc_d = ParametricGeometry.circular_arc(50.0, 50.0, 30.0, 0.0, 90.0, clock_wise=True)
        self.assertTrue(arc_d.startswith("M 80.0000 50.0000 A 30.0000 30.0000 0 0 1"))

        # Full 360 degree circle
        full_circle_d = ParametricGeometry.circular_arc(50.0, 50.0, 30.0, 0.0, 360.0)
        self.assertIn("A 30.0000 30.0000", full_circle_d)
        # Semicircles combined
        self.assertEqual(full_circle_d.count("A"), 2)

    def test_catmull_rom_spline_c1_continuity(self) -> None:
        """Verify Catmull-Rom spline generates exact C1 (tangent) continuous cubic Bezier segments."""
        pts = [
            (20.0, 30.0),
            (60.0, 120.0),
            (120.0, 80.0),
            (180.0, 160.0),
            (240.0, 50.0),
            (300.0, 100.0),
        ]

        segments = ParametricGeometry.derive_catmull_rom_bezier_segments(pts, tension=0.5, closed=False)
        self.assertEqual(len(segments), len(pts) - 1)

        # For every adjacent pair of segments (S_k and S_{k+1}), verify:
        # 1. C0 continuity: end point of S_k == start point of S_{k+1}
        # 2. C1 continuity: tangent leaving S_k == tangent entering S_{k+1}
        for k in range(len(segments) - 1):
            p1_curr, c1_curr, c2_curr, p2_curr = segments[k]
            p1_next, c1_next, c2_next, p2_next = segments[k + 1]

            # C0 positional continuity
            self.assertAlmostEqual(p2_curr[0], p1_next[0], places=4)
            self.assertAlmostEqual(p2_curr[1], p1_next[1], places=4)

            # Cubic Bezier first derivative:
            # Incoming tangent at end of segment k: B'_curr(1) = 3 * (P2 - C2)
            tan_in_x = 3.0 * (p2_curr[0] - c2_curr[0])
            tan_in_y = 3.0 * (p2_curr[1] - c2_curr[1])

            # Outgoing tangent at start of segment k+1: B'_next(0) = 3 * (C1 - P1)
            tan_out_x = 3.0 * (c1_next[0] - p1_next[0])
            tan_out_y = 3.0 * (c1_next[1] - p1_next[1])

            # Tangents must be identical within floating point threshold
            self.assertAlmostEqual(tan_in_x, tan_out_x, places=4, msg=f"C1 continuity violated in X at junction {k}")
            self.assertAlmostEqual(tan_in_y, tan_out_y, places=4, msg=f"C1 continuity violated in Y at junction {k}")

    def test_catmull_rom_spline_svg_output(self) -> None:
        pts = [(10.0, 10.0), (50.0, 80.0), (100.0, 30.0)]
        d_str = ParametricGeometry.catmull_rom_spline(pts)
        self.assertTrue(d_str.startswith("M 10.0000 10.0000"))
        self.assertIn("C ", d_str)
        self.assertFalse(d_str.endswith("Z"))

        # Closed spline
        closed_d = ParametricGeometry.catmull_rom_spline(pts, closed=True)
        self.assertTrue(closed_d.endswith("Z"))

    def test_isometric_projection_30_degree(self) -> None:
        # Origin
        iso_x, iso_y = ParametricGeometry.isometric_project(0.0, 0.0, 0.0)
        self.assertEqual(iso_x, 0.0)
        self.assertEqual(iso_y, 0.0)

        # X axis point: (100, 0, 0)
        # x_iso = 100 * cos(30 deg) = 100 * 0.866025 = 86.6025
        # y_iso = 100 * sin(30 deg) = 100 * 0.5 = 50.0
        iso_x, iso_y = ParametricGeometry.isometric_project(100.0, 0.0, 0.0)
        self.assertAlmostEqual(iso_x, 86.6025, places=3)
        self.assertAlmostEqual(iso_y, 50.0, places=3)

        # Z elevation: (0, 0, 50) -> y_screen shifted upward by 50
        iso_x, iso_y = ParametricGeometry.isometric_project(0.0, 0.0, 50.0)
        self.assertEqual(iso_x, 0.0)
        self.assertAlmostEqual(iso_y, -50.0, places=3)


class TestBoundingBox(unittest.TestCase):
    """Test suite for spatial queries and viewBox bounding box calculations."""

    def test_bbox_properties(self) -> None:
        b = BoundingBox(x=10.0, y=20.0, width=100.0, height=50.0)
        self.assertEqual(b.right, 110.0)
        self.assertEqual(b.bottom, 70.0)
        self.assertEqual(b.cx, 60.0)
        self.assertEqual(b.cy, 45.0)

    def test_contains(self) -> None:
        b = BoundingBox(x=0.0, y=0.0, width=100.0, height=100.0)
        # Point containment
        self.assertTrue(b.contains((50.0, 50.0)))
        self.assertTrue(b.contains((0.0, 0.0)))
        self.assertTrue(b.contains((100.0, 100.0)))
        self.assertFalse(b.contains((101.0, 50.0)))
        self.assertFalse(b.contains((-1.0, 50.0)))

        # Sub-box containment
        inside = BoundingBox(x=10.0, y=10.0, width=50.0, height=50.0)
        self.assertTrue(b.contains(inside))

        outside = BoundingBox(x=90.0, y=90.0, width=20.0, height=20.0)
        self.assertFalse(b.contains(outside))

    def test_intersects(self) -> None:
        b1 = BoundingBox(x=0.0, y=0.0, width=50.0, height=50.0)
        b2 = BoundingBox(x=40.0, y=40.0, width=50.0, height=50.0)
        b3 = BoundingBox(x=60.0, y=60.0, width=50.0, height=50.0)

        self.assertTrue(b1.intersects(b2))
        self.assertTrue(b2.intersects(b3))
        self.assertFalse(b1.intersects(b3))

    def test_enclosing_box_and_viewbox(self) -> None:
        boxes = [
            BoundingBox(x=10.0, y=20.0, width=40.0, height=30.0),
            BoundingBox(x=100.0, y=80.0, width=50.0, height=60.0),
        ]
        enc = BoundingBox.enclosing(boxes, padding=10.0)
        # min_x = 10, min_y = 20, max_right = 150, max_bottom = 140
        # with pad=10: x=0, y=10, width=140+20=160, height=120+20=140
        self.assertEqual(enc.x, 0.0)
        self.assertEqual(enc.y, 10.0)
        self.assertEqual(enc.width, 160.0)
        self.assertEqual(enc.height, 140.0)

        viewbox = enc.to_viewbox()
        self.assertEqual(viewbox, "0.00 10.00 160.00 140.00")


class TestVNode(unittest.TestCase):
    """Test suite for VNode AST representation, serialization, and sanitization."""

    def test_vnode_creation_and_defaults(self) -> None:
        node = VNode(id="card_main", kind="card", width=300.0, height=200.0)
        self.assertEqual(node.id, "card_main")
        self.assertEqual(node.kind, "card")
        self.assertEqual(node.width, 300.0)
        self.assertEqual(node.height, 200.0)
        self.assertEqual(node.bbox.width, 300.0)

    def test_vnode_defensive_sanitization(self) -> None:
        # Null bytes stripped
        bad_id = "node\x00_test"
        bad_kind = "CARD\x00"
        node = VNode(id=bad_id, kind=bad_kind, width=-50.0, height=float("nan"))
        self.assertEqual(node.id, "node_test")
        self.assertEqual(node.kind, "card")
        self.assertEqual(node.width, 0.0)
        self.assertEqual(node.height, 0.0)

    def test_vnode_hierarchy_and_serialization(self) -> None:
        parent = VNode(id="root", kind="card", width=400.0, height=300.0)
        child = VNode(id="badge1", kind="badge", width=80.0, height=24.0)
        parent.add_child(child)

        self.assertEqual(len(parent.children), 1)
        found = parent.find_by_id("badge1")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, "badge1")

        # Roundtrip serialization
        data = parent.to_dict()
        restored = VNode.from_dict(data)
        self.assertEqual(restored.id, "root")
        self.assertEqual(len(restored.children), 1)
        self.assertEqual(restored.children[0].id, "badge1")


class TestVLayoutSolver(unittest.TestCase):
    """Test suite for relational 2D layout solver, constraints, and defensive guards."""

    def setUp(self) -> None:
        self.solver = VLayoutSolver()

    def test_pin_to_viewport_anchors(self) -> None:
        node = VNode(id="panel", kind="card", width=200.0, height=100.0)

        # Top-Left
        self.solver.pin_to_viewport(node, 1920.0, 1080.0, anchor="top-left", margin=20.0)
        self.assertEqual(node.x, 20.0)
        self.assertEqual(node.y, 20.0)

        # Top-Right
        self.solver.pin_to_viewport(node, 1920.0, 1080.0, anchor="top-right", margin=20.0)
        self.assertEqual(node.x, 1920.0 - 200.0 - 20.0)
        self.assertEqual(node.y, 20.0)

        # Bottom-Right
        self.solver.pin_to_viewport(node, 1920.0, 1080.0, anchor="bottom-right", margin=10.0)
        self.assertEqual(node.x, 1920.0 - 200.0 - 10.0)
        self.assertEqual(node.y, 1080.0 - 100.0 - 10.0)

        # Center
        self.solver.pin_to_viewport(node, 1000.0, 600.0, anchor="center")
        self.assertEqual(node.x, 400.0)
        self.assertEqual(node.y, 250.0)

    def test_align_relative_relations(self) -> None:
        ref = VNode(id="ref", kind="card", x=100.0, y=100.0, width=200.0, height=150.0)
        target = VNode(id="target", kind="badge", width=50.0, height=30.0)

        # Right of with middle alignment
        self.solver.align_relative(target, ref, relation="right_of", gap=15.0, alignment="center")
        self.assertEqual(target.x, 100.0 + 200.0 + 15.0)
        self.assertEqual(target.y, ref.cy - 15.0)

        # Below with start alignment
        self.solver.align_relative(target, ref, relation="below", gap=10.0, alignment="start")
        self.assertEqual(target.x, 100.0)
        self.assertEqual(target.y, 100.0 + 150.0 + 10.0)

        # Left of
        self.solver.align_relative(target, ref, relation="left_of", gap=5.0, alignment="start")
        self.assertEqual(target.x, 100.0 - 50.0 - 5.0)
        self.assertEqual(target.y, 100.0)

        # Inside / center
        self.solver.align_relative(target, ref, relation="inside")
        self.assertEqual(target.x, 100.0 + (200.0 - 50.0) / 2.0)
        self.assertEqual(target.y, 100.0 + (150.0 - 30.0) / 2.0)

    def test_solve_with_props_constraints(self) -> None:
        root = VNode(id="container", kind="card", width=800.0, height=600.0)
        header = VNode(id="header", kind="card", width=760.0, height=80.0, props={
            "pin_to_viewport": {"anchor": "top-left", "margin": 20.0},
        })
        content = VNode(id="content", kind="card", width=760.0, height=450.0, props={
            "align_relative": {"reference_id": "header", "relation": "below", "gap": 20.0},
        })
        root.add_child(header)
        root.add_child(content)

        bbox = self.solver.solve(root, viewport_width=800.0, viewport_height=600.0)
        self.assertEqual(header.x, 20.0)
        self.assertEqual(header.y, 20.0)
        self.assertEqual(content.x, 20.0)
        self.assertEqual(content.y, 120.0)
        self.assertGreater(bbox.width, 0.0)
        self.assertGreater(bbox.height, 0.0)

    def test_defensive_input_guards(self) -> None:
        # Guard against NaN/Inf in solve
        node = VNode(id="bad_node", kind="card", width=float("nan"), height=float("inf"))
        bbox = self.solver.solve(node, viewport_width=float("nan"), viewport_height=float("-inf"))
        self.assertTrue(math.isfinite(bbox.x))
        self.assertTrue(math.isfinite(bbox.y))
        self.assertTrue(math.isfinite(bbox.width))
        self.assertTrue(math.isfinite(bbox.height))

        # Guard against deep nesting recursion overflow
        deep_root = VNode(id="lvl_0", kind="card")
        curr = deep_root
        for idx in range(1, 80):
            nxt = VNode(id=f"lvl_{idx}", kind="card")
            curr.add_child(nxt)
            curr = nxt

        with self.assertRaises(ValueError):
            self.solver.solve(deep_root)

    def test_thread_safety(self) -> None:
        solver = VLayoutSolver()

        def worker(idx: int) -> float:
            n1 = VNode(id=f"n1_{idx}", kind="card", width=100.0, height=50.0)
            n2 = VNode(id=f"n2_{idx}", kind="badge", width=40.0, height=20.0)
            solver.pin_to_viewport(n1, 1000.0, 1000.0, anchor="top-left", margin=idx * 2.0)
            solver.align_relative(n2, n1, relation="right_of", gap=5.0)
            return n2.x

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            results = [f.result() for f in futures]

        self.assertEqual(len(results), 20)
        for i, res in enumerate(results):
            expected = (i * 2.0) + 100.0 + 5.0
            self.assertEqual(res, expected)


class TestFableVectorCompiler(unittest.TestCase):
    """Test suite for SVG compilation, XML AST well-formedness, filters, and gradients."""

    def setUp(self) -> None:
        self.compiler = FableVectorCompiler()

    def test_compile_xml_ast_well_formedness(self) -> None:
        # Build comprehensive scene with all 7 VNode kinds
        root = VNode(id="dashboard", kind="card", x=0.0, y=0.0, width=1200.0, height=800.0, props={
            "title": "Quantum Telemetry Dashboard",
            "desc": "Real-time Fable Neuro-Symbolic Vector Telemetry",
        })

        # Dial node
        dial = VNode(id="cpu_gauge", kind="dial", x=50.0, y=50.0, width=160.0, height=160.0, props={
            "value": 0.82,
            "label": "82% CPU",
        })
        root.add_child(dial)

        # Spline node
        spline = VNode(id="waveform", kind="spline", x=250.0, y=50.0, width=400.0, height=160.0, props={
            "points": [(0, 80), (100, 20), (200, 140), (300, 40), (400, 80)],
            "tension": 0.5,
        })
        root.add_child(spline)

        # Text node
        text_node = VNode(id="header_text", kind="text", x=700.0, y=80.0, width=300.0, height=30.0, props={
            "text": "NEURO-SYMBOLIC RUNTIME: NOMINAL",
            "font_size": 16,
            "font_weight": "700",
        })
        root.add_child(text_node)

        # Badge node
        badge = VNode(id="status_badge", kind="badge", x=700.0, y=120.0, width=100.0, height=28.0, props={
            "label": "ONLINE",
        })
        root.add_child(badge)

        # Grid node
        grid = VNode(id="bg_grid", kind="grid", x=50.0, y=260.0, width=500.0, height=400.0, props={
            "spacing": 32.0,
            "isometric": False,
        })
        root.add_child(grid)

        # Isometric grid
        iso_grid = VNode(id="iso_grid", kind="grid", x=600.0, y=260.0, width=500.0, height=400.0, props={
            "spacing": 40.0,
            "isometric": True,
        })
        root.add_child(iso_grid)

        # Conduit node
        conduit = VNode(id="wire_1", kind="conduit", x=210.0, y=130.0, width=40.0, height=0.0, props={
            "x1": 210.0, "y1": 130.0, "x2": 250.0, "y2": 130.0,
        })
        root.add_child(conduit)

        # Compile to SVG
        svg_code = self.compiler.compile(root)
        self.assertIsInstance(svg_code, str)
        self.assertGreater(len(svg_code), 500)

        # Validate that output is strictly well-formed XML AST
        xml_root = ET.fromstring(svg_code)
        self.assertEqual(xml_root.tag.split("}")[-1], "svg")

        # Accessibility checks
        self.assertEqual(xml_root.attrib.get("role"), "img")
        self.assertIn("Quantum Telemetry", xml_root.attrib.get("aria-label", ""))

        # Verify <title> and <desc>
        titles = [e.text for e in xml_root.findall("{http://www.w3.org/2000/svg}title") or xml_root.findall("title")]
        self.assertTrue(any("Quantum Telemetry" in str(t) for t in titles))

        # Procedural noise filter check
        filters = xml_root.findall(".//{http://www.w3.org/2000/svg}filter") or xml_root.findall(".//filter")
        filter_ids = [f.attrib.get("id") for f in filters]
        self.assertIn("fable-micro-grain", filter_ids)

        turbulences = xml_root.findall(".//{http://www.w3.org/2000/svg}feTurbulence") or xml_root.findall(".//feTurbulence")
        self.assertGreaterEqual(len(turbulences), 1)

        # OKLCH Gradients check
        linear_grads = xml_root.findall(".//{http://www.w3.org/2000/svg}linearGradient") or xml_root.findall(".//linearGradient")
        grad_ids = [g.attrib.get("id") for g in linear_grads]
        self.assertIn("fable-grad-obsidian", grad_ids)
        self.assertIn("fable-grad-specular", grad_ids)
        self.assertIn("fable-grad-accent", grad_ids)

        # ViewBox enclosure check
        viewbox = xml_root.attrib.get("viewBox", "")
        self.assertTrue(viewbox, "viewBox attribute must be present")
        vb_parts = [float(p) for p in viewbox.split()]
        self.assertEqual(len(vb_parts), 4)
        self.assertGreaterEqual(vb_parts[2], 1200.0)
        self.assertGreaterEqual(vb_parts[3], 800.0)


class TestFleetDispatcherVectorIntegration(unittest.TestCase):
    """Test suite for CoderFleetDispatcher vector action dispatching."""

    def setUp(self) -> None:
        self.dispatcher = CoderFleetDispatcher()

    def test_list_actions_contains_vector_actions(self) -> None:
        actions = self.dispatcher.list_actions()
        self.assertIn("compile_vector", actions)
        self.assertIn("solve_layout", actions)

    def test_dispatch_compile_vector(self) -> None:
        node_def = {
            "id": "telemetry_card",
            "kind": "card",
            "width": 320.0,
            "height": 180.0,
            "props": {
                "title": "Core Status",
            },
            "children": [
                {
                    "id": "badge_ok",
                    "kind": "badge",
                    "x": 20.0,
                    "y": 20.0,
                    "width": 60.0,
                    "height": 24.0,
                    "props": {"label": "OK"},
                }
            ],
        }
        res = self.dispatcher.dispatch("compile_vector", {"root": node_def})
        self.assertTrue(res["success"])
        self.assertIn("svg", res["result"])
        self.assertTrue(res["result"]["valid"])

        # Check SVG string validity
        svg_code = res["result"]["svg"]
        parsed = ET.fromstring(svg_code)
        self.assertEqual(parsed.tag.split("}")[-1], "svg")

    def test_dispatch_solve_layout(self) -> None:
        node_def = {
            "id": "root_card",
            "kind": "card",
            "width": 500.0,
            "height": 300.0,
            "children": [
                {
                    "id": "sidebar",
                    "kind": "card",
                    "width": 120.0,
                    "height": 260.0,
                    "props": {"pin_to_viewport": {"anchor": "top-left", "margin": 20.0}},
                },
                {
                    "id": "main_view",
                    "kind": "card",
                    "width": 320.0,
                    "height": 260.0,
                    "props": {"align_relative": {"reference_id": "sidebar", "relation": "right_of", "gap": 20.0}},
                },
            ],
        }
        res = self.dispatcher.dispatch("solve_layout", {"root": node_def, "viewport_width": 500.0, "viewport_height": 300.0})
        self.assertTrue(res["success"])
        self.assertIn("bbox", res["result"])
        self.assertIn("viewBox", res["result"])
        self.assertEqual(res["result"]["root"]["children"][1]["x"], 160.0)


if __name__ == "__main__":
    unittest.main()
