"""Visual Grounding Engine for Vector / SVG Analysis and Perceptual Diffing.

Pure-Python implementation using xml.etree.ElementTree with zero external C-dependencies.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any


class VisualGroundingEngine:
    """Engine for parsing, perceptually analyzing, and verifying vector SVG assets."""

    # SVG XML namespace prefix pattern
    _NS_REGEX = re.compile(r"^\{.*?\}")
    
    # Color regex patterns
    _HEX_COLOR_REGEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
    _RGB_COLOR_REGEX = re.compile(r"rgba?\([^)]+\)", re.IGNORECASE)
    _HSL_COLOR_REGEX = re.compile(r"hsla?\([^)]+\)", re.IGNORECASE)
    _OKLCH_COLOR_REGEX = re.compile(r"oklch\([^)]+\)", re.IGNORECASE)

    @classmethod
    def _clean_tag(cls, raw_tag: str) -> str:
        """Remove XML namespace URI from tag name."""
        return cls._NS_REGEX.sub("", raw_tag).lower()

    def render_vector(self, code: str, format: str = "svg") -> dict[str, Any]:
        """Parse vector/SVG code, validate XML tags, extract viewBox, paths, and element counts.

        Returns rendering metadata dict.
        """
        if not code or not code.strip():
            return {
                "valid": False,
                "format": format,
                "error": "Empty vector code provided",
                "elements_count": 0,
                "element_types": {},
                "paths": [],
                "warnings": ["Empty input string"],
                "metadata": {},
            }

        try:
            # Parse XML
            root = ET.fromstring(code.strip())
        except ET.ParseError as err:
            return {
                "valid": False,
                "format": format,
                "error": f"XML parse error: {err}",
                "elements_count": 0,
                "element_types": {},
                "paths": [],
                "warnings": [f"Malformed XML syntax at line {err.position[0] if hasattr(err, 'position') else 'unknown'}"],
                "metadata": {},
            }

        root_tag = self._clean_tag(root.tag)
        warnings: list[str] = []
        if root_tag != "svg":
            warnings.append(f"Root tag is <{root_tag}>, expected <svg>")

        # Extract viewBox
        view_box_raw = root.attrib.get("viewBox") or root.attrib.get("viewbox")
        view_box: list[float] | None = None
        if view_box_raw:
            try:
                parts = [float(p) for p in re.split(r"[\s,]+", view_box_raw.strip()) if p]
                if len(parts) == 4:
                    view_box = parts
                else:
                    warnings.append(f"Invalid viewBox components: {view_box_raw}")
            except ValueError:
                warnings.append(f"Non-numeric viewBox values: {view_box_raw}")

        width = root.attrib.get("width")
        height = root.attrib.get("height")

        # Traverse elements
        element_types: dict[str, int] = {}
        paths: list[str] = []
        total_elements = 0

        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            total_elements += 1
            element_types[tag] = element_types.get(tag, 0) + 1

            if tag == "path":
                d_attr = elem.attrib.get("d")
                if d_attr:
                    paths.append(d_attr.strip())

        # Path complexity calculation (count of path commands: M, L, C, S, Q, T, A, Z, etc.)
        total_commands = sum(len(re.findall(r"[MmLlHhVvCcSsQqTtAaZz]", p)) for p in paths)

        return {
            "valid": True,
            "format": format,
            "viewBox": view_box,
            "width": width,
            "height": height,
            "elements_count": total_elements,
            "element_types": element_types,
            "paths": paths,
            "warnings": warnings,
            "metadata": {
                "root_tag": root_tag,
                "path_count": len(paths),
                "total_path_commands": total_commands,
            },
        }

    def perceptual_diff(self, svg_code: str, target_spec: dict[str, Any]) -> dict[str, Any]:
        """Calculate coverage, element counts, path complexity, and similarity score (0.0 to 1.0)."""
        render_res = self.render_vector(svg_code)
        if not render_res["valid"]:
            return {
                "similarity_score": 0.0,
                "element_counts": {},
                "target_element_counts": target_spec.get("expected_counts", {}),
                "path_complexity": 0,
                "coverage": 0.0,
                "diff_details": [f"Invalid SVG: {render_res.get('error')}"],
            }

        element_counts = render_res["element_types"]
        path_complexity = render_res["metadata"]["total_path_commands"]
        diff_details: list[str] = []

        sub_scores: list[float] = []

        # 1. Element type coverage
        expected_types = target_spec.get("expected_types", [])
        if expected_types:
            matched_types = sum(1 for t in expected_types if element_counts.get(t, 0) > 0)
            type_coverage = matched_types / len(expected_types)
            sub_scores.append(type_coverage)
            for t in expected_types:
                if element_counts.get(t, 0) == 0:
                    diff_details.append(f"Missing expected element type <{t}>")
        else:
            sub_scores.append(1.0)

        # 2. Minimum element count requirement
        min_elements = target_spec.get("min_elements", 1)
        actual_count = render_res["elements_count"]
        if actual_count >= min_elements:
            sub_scores.append(1.0)
        else:
            sub_scores.append(actual_count / max(1, min_elements))
            diff_details.append(f"Element count {actual_count} is less than minimum {min_elements}")

        # 3. Minimum paths requirement
        min_paths = target_spec.get("min_paths", 0)
        actual_paths = len(render_res["paths"])
        if min_paths > 0:
            if actual_paths >= min_paths:
                sub_scores.append(1.0)
            else:
                sub_scores.append(actual_paths / min_paths)
                diff_details.append(f"Path count {actual_paths} is less than minimum {min_paths}")

        # 4. Palette match if expected palette is specified
        expected_palette = target_spec.get("palette", [])
        if expected_palette:
            extracted = self.extract_palette_and_boxes(svg_code)
            actual_colors = set(c.lower() for c in extracted["palette"]["all_colors"])
            matched_colors = 0
            for c in expected_palette:
                if c.lower() in actual_colors:
                    matched_colors += 1
                else:
                    diff_details.append(f"Expected color '{c}' not found in SVG palette")
            sub_scores.append(matched_colors / len(expected_palette))

        # 5. ViewBox match if specified
        target_vb = target_spec.get("viewBox")
        if target_vb:
            actual_vb = render_res["viewBox"]
            if actual_vb == target_vb:
                sub_scores.append(1.0)
            else:
                sub_scores.append(0.5 if actual_vb else 0.0)
                diff_details.append(f"viewBox {actual_vb} does not match expected {target_vb}")

        similarity_score = sum(sub_scores) / len(sub_scores) if sub_scores else 1.0
        similarity_score = round(max(0.0, min(1.0, similarity_score)), 4)
        coverage = round(sum(1.0 for s in sub_scores if s >= 0.99) / max(1, len(sub_scores)), 4)

        return {
            "similarity_score": similarity_score,
            "element_counts": element_counts,
            "target_element_counts": target_spec.get("expected_counts", {}),
            "path_complexity": path_complexity,
            "coverage": coverage,
            "diff_details": diff_details,
        }

    def extract_palette_and_boxes(self, svg_code: str) -> dict[str, Any]:
        """Extract color fills/strokes (hex/rgb/hsl/oklch) and bounding geometry."""
        if not svg_code or not svg_code.strip():
            return {
                "palette": {"fills": [], "strokes": [], "all_colors": []},
                "bounding_boxes": [],
                "total_elements": 0,
            }

        try:
            root = ET.fromstring(svg_code.strip())
        except ET.ParseError:
            return {
                "palette": {"fills": [], "strokes": [], "all_colors": []},
                "bounding_boxes": [],
                "total_elements": 0,
            }

        fills: set[str] = set()
        strokes: set[str] = set()
        all_colors: set[str] = set()
        boxes: list[dict[str, Any]] = []
        total_elements = 0

        def _extract_colors_from_string(text: str) -> list[str]:
            results = []
            for match in self._HEX_COLOR_REGEX.finditer(text):
                results.append(match.group(0))
            for match in self._RGB_COLOR_REGEX.finditer(text):
                results.append(match.group(0))
            for match in self._HSL_COLOR_REGEX.finditer(text):
                results.append(match.group(0))
            for match in self._OKLCH_COLOR_REGEX.finditer(text):
                results.append(match.group(0))
            return results

        def _clean_color_value(val: str | None) -> str | None:
            if not val:
                return None
            val = val.strip()
            if val.lower() in ("none", "transparent", "currentcolor", "inherit"):
                return None
            return val

        for elem in root.iter():
            tag = self._clean_tag(elem.tag)
            total_elements += 1
            attrib = elem.attrib

            # Fill attribute
            f_val = _clean_color_value(attrib.get("fill"))
            if f_val:
                fills.add(f_val)
                all_colors.add(f_val)

            # Stroke attribute
            s_val = _clean_color_value(attrib.get("stroke"))
            if s_val:
                strokes.add(s_val)
                all_colors.add(s_val)

            # Inline style attribute
            style_attr = attrib.get("style", "")
            if style_attr:
                style_colors = _extract_colors_from_string(style_attr)
                for sc in style_colors:
                    all_colors.add(sc)
                for part in style_attr.split(";"):
                    if ":" in part:
                        prop, _, v = part.partition(":")
                        prop = prop.strip().lower()
                        v_clean = _clean_color_value(v)
                        if v_clean:
                            if prop == "fill":
                                fills.add(v_clean)
                            elif prop == "stroke":
                                strokes.add(v_clean)

            # Extract bounding geometry
            box_info: dict[str, Any] | None = None
            if tag == "rect":
                try:
                    box_info = {
                        "tag": "rect",
                        "x": float(attrib.get("x", 0)),
                        "y": float(attrib.get("y", 0)),
                        "width": float(attrib.get("width", 0)),
                        "height": float(attrib.get("height", 0)),
                    }
                except ValueError:
                    pass
            elif tag == "circle":
                try:
                    cx = float(attrib.get("cx", 0))
                    cy = float(attrib.get("cy", 0))
                    r = float(attrib.get("r", 0))
                    box_info = {
                        "tag": "circle",
                        "x": cx - r,
                        "y": cy - r,
                        "width": 2 * r,
                        "height": 2 * r,
                        "cx": cx,
                        "cy": cy,
                        "r": r,
                    }
                except ValueError:
                    pass
            elif tag == "ellipse":
                try:
                    cx = float(attrib.get("cx", 0))
                    cy = float(attrib.get("cy", 0))
                    rx = float(attrib.get("rx", 0))
                    ry = float(attrib.get("ry", 0))
                    box_info = {
                        "tag": "ellipse",
                        "x": cx - rx,
                        "y": cy - ry,
                        "width": 2 * rx,
                        "height": 2 * ry,
                        "cx": cx,
                        "cy": cy,
                        "rx": rx,
                        "ry": ry,
                    }
                except ValueError:
                    pass
            elif tag == "line":
                try:
                    x1 = float(attrib.get("x1", 0))
                    y1 = float(attrib.get("y1", 0))
                    x2 = float(attrib.get("x2", 0))
                    y2 = float(attrib.get("y2", 0))
                    box_info = {
                        "tag": "line",
                        "x": min(x1, x2),
                        "y": min(y1, y2),
                        "width": abs(x2 - x1),
                        "height": abs(y2 - y1),
                    }
                except ValueError:
                    pass

            if box_info:
                boxes.append(box_info)

        return {
            "palette": {
                "fills": sorted(fills),
                "strokes": sorted(strokes),
                "all_colors": sorted(all_colors),
            },
            "bounding_boxes": boxes,
            "total_elements": total_elements,
        }
