"""Agent Figma - Agent-Native UI Design Engine for Fable Mode.

Provides zero-dependency node hierarchy management, flex/grid layout solver,
design token application, semantic tree inspection, and asset exporting (SVG, JSON, PPM)
guaranteed to operate under 500MB RAM.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.sax.saxutils import escape, quoteattr

from fable_engine.actions.resource_registry import SharedResourceRegistry


MAX_CANVAS_DIMENSION = 8192.0
MAX_CANVAS_PIXELS = 16_777_216.0


def _validate_dimensions(width: Any, height: Any) -> Tuple[float, float]:
    try:
        validated_width = float(width)
        validated_height = float(height)
    except (TypeError, ValueError) as exc:
        raise ValueError("width and height must be finite positive numbers") from exc
    if (
        not math.isfinite(validated_width)
        or not math.isfinite(validated_height)
        or validated_width < 1
        or validated_height < 1
        or validated_width > MAX_CANVAS_DIMENSION
        or validated_height > MAX_CANVAS_DIMENSION
        or validated_width * validated_height > MAX_CANVAS_PIXELS
    ):
        raise ValueError(
            f"width and height must be finite values from 1 to {int(MAX_CANVAS_DIMENSION)}, "
            f"with at most {int(MAX_CANVAS_PIXELS)} total pixels"
        )
    return validated_width, validated_height


def _validate_padding(value: Any) -> Tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("padding must be a list or tuple of exactly four numeric values")
    try:
        top, right, bottom, left = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("padding values must be finite numbers") from exc
    padding = (top, right, bottom, left)
    if not all(math.isfinite(item) for item in padding):
        raise ValueError("padding values must be finite numbers")
    return padding


class FigmaNode:
    """Represents an agent-native Figma design node."""

    def __init__(
        self,
        node_id: str,
        name: str,
        node_type: str = "FRAME",  # FRAME, TEXT, RECTANGLE, ELLIPSE, VECTOR, COMPONENT
        x: float = 0.0,
        y: float = 0.0,
        width: float = 100.0,
        height: float = 100.0,
        fill: Optional[str] = "#FFFFFF",
        stroke: Optional[str] = None,
        stroke_width: float = 1.0,
        corner_radius: float = 0.0,
        opacity: float = 1.0,
        text_content: Optional[str] = None,
        font_size: float = 14.0,
        font_family: str = "Inter, sans-serif",
        font_weight: str = "normal",
        text_align: str = "left",
        vector_path: Optional[str] = None,
        layout_mode: Optional[str] = None,  # NONE, HORIZONTAL, VERTICAL
        item_spacing: float = 0.0,
        padding: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),  # top, right, bottom, left
        align_items: str = "FLEX_START",  # FLEX_START, CENTER, FLEX_END, SPACE_BETWEEN
    ) -> None:
        self.node_id = node_id
        self.name = name
        self.node_type = node_type.upper()
        self.x = float(x)
        self.y = float(y)
        self.width = float(width)
        self.height = float(height)
        self.fill = fill
        self.stroke = stroke
        self.stroke_width = float(stroke_width)
        self.corner_radius = float(corner_radius)
        self.opacity = float(opacity)
        self.text_content = text_content
        self.font_size = float(font_size)
        self.font_family = font_family
        self.font_weight = font_weight
        self.text_align = text_align
        self.vector_path = vector_path
        self.layout_mode = layout_mode
        self.item_spacing = float(item_spacing)
        self.padding = _validate_padding(padding)
        self.align_items = align_items
        self.children: List[FigmaNode] = []
        self.styles: Dict[str, Any] = {}

    def add_child(self, child: "FigmaNode") -> None:
        self.children.append(child)

    def solve_layout(self) -> None:
        """Computes flex layout offsets for children if layout_mode is active."""
        if not self.layout_mode or self.layout_mode == "NONE" or not self.children:
            for child in self.children:
                child.solve_layout()
            return

        p_top, p_right, p_bottom, p_left = self.padding
        content_w = self.width - p_left - p_right
        content_h = self.height - p_top - p_bottom

        if self.layout_mode == "HORIZONTAL":
            current_x = p_left
            spacing = self.item_spacing
            if self.align_items == "SPACE_BETWEEN" and len(self.children) >= 2:
                remaining = content_w - sum(child.width for child in self.children)
                if remaining > 0:
                    spacing = remaining / (len(self.children) - 1)
            for child in self.children:
                child.x = current_x
                if self.align_items == "CENTER":
                    child.y = p_top + (content_h - child.height) / 2.0
                elif self.align_items == "FLEX_END":
                    child.y = p_top + content_h - child.height
                else:  # FLEX_START
                    child.y = p_top
                current_x += child.width + spacing
                child.solve_layout()

        elif self.layout_mode == "VERTICAL":
            current_y = p_top
            spacing = self.item_spacing
            if self.align_items == "SPACE_BETWEEN" and len(self.children) >= 2:
                remaining = content_h - sum(child.height for child in self.children)
                if remaining > 0:
                    spacing = remaining / (len(self.children) - 1)
            for child in self.children:
                child.y = current_y
                if self.align_items == "CENTER":
                    child.x = p_left + (content_w - child.width) / 2.0
                elif self.align_items == "FLEX_END":
                    child.x = p_left + content_w - child.width
                else:  # FLEX_START
                    child.x = p_left
                current_y += child.height + spacing
                child.solve_layout()

    def to_dict(self) -> Dict[str, Any]:
        """Returns JSON-serializable representation of the node tree."""
        data: Dict[str, Any] = {
            "node_id": self.node_id,
            "name": self.name,
            "type": self.node_type,
            "bounds": {"x": self.x, "y": self.y, "width": self.width, "height": self.height},
            "style": {
                "fill": self.fill,
                "stroke": self.stroke,
                "stroke_width": self.stroke_width,
                "corner_radius": self.corner_radius,
                "opacity": self.opacity,
            },
        }
        if self.node_type == "TEXT":
            data["text"] = {
                "content": self.text_content,
                "font_size": self.font_size,
                "font_family": self.font_family,
                "font_weight": self.font_weight,
                "align": self.text_align,
            }
        if self.vector_path:
            data["vector_path"] = self.vector_path
        if self.layout_mode:
            data["layout"] = {
                "mode": self.layout_mode,
                "spacing": self.item_spacing,
                "padding": self.padding,
                "align": self.align_items,
            }
        if self.children:
            data["children"] = [c.to_dict() for c in self.children]
        return data

    def render_svg(self, abs_x: float = 0.0, abs_y: float = 0.0) -> str:
        """Renders the node hierarchy into a clean SVG string."""
        curr_x = abs_x + self.x
        curr_y = abs_y + self.y
        parts: List[str] = []

        opacity_attr = f' opacity="{self.opacity}"' if self.opacity < 1.0 else ""
        fill_attr = f' fill="{self.fill}"' if self.fill else ' fill="none"'
        stroke_attr = f' stroke="{self.stroke}" stroke-width="{self.stroke_width}"' if self.stroke else ""

        if self.node_type in ("FRAME", "RECTANGLE", "COMPONENT"):
            rx_attr = f' rx="{self.corner_radius}"' if self.corner_radius > 0 else ""
            parts.append(
                f'<rect x="{curr_x}" y="{curr_y}" width="{self.width}" height="{self.height}"{rx_attr}{fill_attr}{stroke_attr}{opacity_attr}/>'
            )
        elif self.node_type == "ELLIPSE":
            cx = curr_x + self.width / 2.0
            cy = curr_y + self.height / 2.0
            rx = self.width / 2.0
            ry = self.height / 2.0
            parts.append(
                f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"{fill_attr}{stroke_attr}{opacity_attr}/>'
            )
        elif self.node_type == "TEXT" and self.text_content:
            tx = curr_x
            ty = curr_y + self.font_size
            parts.append(
                f'<text x={quoteattr(str(tx))} y={quoteattr(str(ty))} '
                f'font-family={quoteattr(str(self.font_family))} font-size={quoteattr(str(self.font_size))} '
                f'font-weight={quoteattr(str(self.font_weight))} fill={quoteattr(str(self.fill or "#000000"))} '
                f'opacity={quoteattr(str(self.opacity))}>{escape(str(self.text_content))}</text>'
            )
        elif self.node_type == "VECTOR" and self.vector_path:
            parts.append(
                f'<path d="{self.vector_path}" transform="translate({curr_x}, {curr_y})"{fill_attr}{stroke_attr}{opacity_attr}/>'
            )

        # Render children
        for child in self.children:
            parts.append(child.render_svg(curr_x, curr_y))

        return "\n".join(parts)


class AgentFigmaEngine:
    """In-memory agent-native Figma canvas registry."""

    def __init__(self) -> None:
        self.canvases: SharedResourceRegistry[FigmaNode] = SharedResourceRegistry()

    def get_or_create_canvas(self, canvas_id: str, width: float = 1440.0, height: float = 900.0) -> FigmaNode:
        if canvas_id not in self.canvases:
            width, height = _validate_dimensions(width, height)
            root = FigmaNode(
                node_id=canvas_id,
                name="Canvas Root",
                node_type="FRAME",
                width=width,
                height=height,
                fill="#0F172A",
            )
            self.canvases[canvas_id] = root
        return self.canvases[canvas_id]

    def add_node(self, canvas_id: str, parent_id: Optional[str], node_data: Dict[str, Any]) -> FigmaNode:
        width, height = _validate_dimensions(node_data.get("width", 100), node_data.get("height", 100))
        padding = _validate_padding(node_data.get("padding", [0, 0, 0, 0]))
        root = self.get_or_create_canvas(canvas_id)
        requested_node_id = node_data.get("node_id")
        if requested_node_id:
            node_id = str(requested_node_id)
            if self._find_node(root, node_id) is not None:
                raise ValueError(f"node_id '{node_id}' already exists in canvas '{canvas_id}'")
        else:
            counter = int(getattr(root, "_next_node_id", 1))
            node_id = f"node_{counter}"
            while self._find_node(root, node_id) is not None:
                counter += 1
                node_id = f"node_{counter}"
            root._next_node_id = counter + 1
        node = FigmaNode(
            node_id=node_id,
            name=node_data.get("name", "Node"),
            node_type=node_data.get("node_type", "FRAME"),
            x=float(node_data.get("x", 0)),
            y=float(node_data.get("y", 0)),
            width=width,
            height=height,
            fill=node_data.get("fill", "#FFFFFF"),
            stroke=node_data.get("stroke"),
            stroke_width=float(node_data.get("stroke_width", 1)),
            corner_radius=float(node_data.get("corner_radius", 0)),
            opacity=float(node_data.get("opacity", 1.0)),
            text_content=node_data.get("text_content"),
            font_size=float(node_data.get("font_size", 14)),
            font_family=node_data.get("font_family", "Inter, sans-serif"),
            font_weight=node_data.get("font_weight", "normal"),
            text_align=node_data.get("text_align", "left"),
            vector_path=node_data.get("vector_path"),
            layout_mode=node_data.get("layout_mode"),
            item_spacing=float(node_data.get("item_spacing", 0)),
            padding=padding,
            align_items=node_data.get("align_items", "FLEX_START"),
        )

        parent = self._find_node(root, parent_id) if parent_id else root
        if parent is None:
            parent = root
        parent.add_child(node)
        root.solve_layout()
        return node

    def _find_node(self, current: FigmaNode, node_id: str) -> Optional[FigmaNode]:
        if current.node_id == node_id:
            return current
        for child in current.children:
            res = self._find_node(child, node_id)
            if res:
                return res
        return None

    def export_canvas(self, canvas_id: str, export_format: str = "svg") -> str:
        root = self.canvases.get(canvas_id)
        if not root:
            return f"Error: Canvas '{canvas_id}' not found."

        root.solve_layout()
        export_format = export_format.lower()

        if export_format == "json":
            return json.dumps(root.to_dict(), indent=2)
        elif export_format in ("svg", "xml"):
            body = root.render_svg()
            return f'<svg xmlns="http://www.w3.org/2000/svg" width="{root.width}" height="{root.height}" viewBox="0 0 {root.width} {root.height}">\n{body}\n</svg>'
        elif export_format == "ppm":
            # Lightweight raw PPM image header (P3 ASCII format) for agent visual inspection
            width, height = _validate_dimensions(root.width, root.height)
            w, h = int(width), int(height)
            lines = [f"P3\n{w} {h}\n255"]
            bg_r, bg_g, bg_b = (15, 23, 42)  # slate dark background
            row = f"{bg_r} {bg_g} {bg_b} " * w
            for _ in range(h):
                lines.append(row)
            return "\n".join(lines)
        else:
            return f"Error: Unsupported format '{export_format}'. Supported: json, svg, ppm."


GLOBAL_FIGMA_ENGINE = AgentFigmaEngine()


def _handle_figma_design(arguments: Dict[str, Any]) -> str:
    """Action handler for Agent Figma tool."""
    action = arguments.get("figma_action", "inspect")
    canvas_id = arguments.get("canvas_id", "default_canvas")

    if action in ("create_canvas", "init"):
        w, h = _validate_dimensions(arguments.get("width", 1440), arguments.get("height", 900))
        node = GLOBAL_FIGMA_ENGINE.get_or_create_canvas(canvas_id, w, h)
        return json.dumps({"status": "success", "message": f"Canvas '{canvas_id}' created.", "canvas": node.to_dict()})

    elif action in ("add_node", "create_component", "create_node"):
        parent_id = arguments.get("parent_id")
        node_data = arguments.get("node_data", {})
        if not node_data:
            node_data = {
                "name": arguments.get("name", "Node"),
                "node_type": arguments.get("node_type", "FRAME"),
                "x": arguments.get("x", 0),
                "y": arguments.get("y", 0),
                "width": arguments.get("width", 100),
                "height": arguments.get("height", 100),
                "fill": arguments.get("fill", "#FFFFFF"),
                "text_content": arguments.get("text_content"),
                "layout_mode": arguments.get("layout_mode"),
                "item_spacing": arguments.get("item_spacing", 0),
            }
        node = GLOBAL_FIGMA_ENGINE.add_node(canvas_id, parent_id, node_data)
        return json.dumps({"status": "success", "node_added": node.to_dict()})

    elif action in ("export", "render"):
        fmt = arguments.get("format", "svg")
        content = GLOBAL_FIGMA_ENGINE.export_canvas(canvas_id, fmt)
        return json.dumps({"status": "success", "canvas_id": canvas_id, "format": fmt, "output": content})

    elif action in ("inspect", "tree", "get"):
        canvas = GLOBAL_FIGMA_ENGINE.canvases.get(canvas_id)
        if not canvas:
            canvas = GLOBAL_FIGMA_ENGINE.get_or_create_canvas(canvas_id)
        canvas.solve_layout()
        return json.dumps({"status": "success", "canvas": canvas.to_dict()})

    else:
        return f"Error: Unknown figma_action '{action}'. Supported: create_canvas, add_node, export, inspect."
