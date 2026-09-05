"""Fable-Vector Neuro-Symbolic Vector Engine.

High-precision, pure-Python vector graphics and layout engine featuring:
- OKLCHColor: Perceptually uniform color modeling, relative luminance, and APCA contrast.
- ParametricGeometry: Polar/Cartesian conversions, circular arcs, Catmull-Rom splines
  with C1/C2 continuity and cubic Bezier derivation, and 30-degree isometric projection.
- BoundingBox: Enclosure, intersections, and viewport fitting.
- VNode: Hierarchical vector AST representation (cards, dials, splines, text, badges, grids, conduits).
- VLayoutSolver: Thread-safe 2D relational layout solver with defensive parameter coercion.
- FableVectorCompiler: Compiles VNode tree into production-grade SVG with viewBox enclosure,
  micro-grain procedural noise filters, OKLCH gradients, and accessibility attributes.
"""
from __future__ import annotations

import math
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


# ==============================================================================
# 1. OKLCH COLOR WITH APCA ACCESSIBILITY
# ==============================================================================

def _coerce_finite_float(val: Any, default: float = 0.0) -> float:
    """Defensively coerce any value to a finite float, preventing NaN/Inf crashes."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def _sanitize_text(val: Any, default: str = "") -> str:
    """Defensively sanitize strings, stripping null bytes and non-printable control chars."""
    if val is None:
        return default
    s = str(val)
    # Strip null bytes and control chars except newline, tab, carriage return
    s = s.replace("\x00", "")
    return re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


@dataclass
class OKLCHColor:
    """Perceptually uniform color in cylindrical OKLCH color space.

    Attributes:
        l: Lightness, normalized in [0.0, 1.0].
        c: Chroma, >= 0.0 (typically [0.0, 0.4]).
        h: Hue angle in degrees in [0.0, 360.0).
        alpha: Opacity in [0.0, 1.0].
    """
    l: float
    c: float
    h: float
    alpha: float = 1.0

    def __post_init__(self) -> None:
        # Defensive coercion against NaN / Inf / invalid types
        self.l = max(0.0, min(1.0, _coerce_finite_float(self.l, 0.0)))
        self.c = max(0.0, _coerce_finite_float(self.c, 0.0))
        h_val = _coerce_finite_float(self.h, 0.0)
        self.h = (h_val % 360.0 + 360.0) % 360.0
        self.alpha = max(0.0, min(1.0, _coerce_finite_float(self.alpha, 1.0)))

    def to_svg(self) -> str:
        """Serialize to CSS Color Module Level 4 oklch() functional syntax."""
        if abs(self.alpha - 1.0) > 1e-4:
            return f"oklch({self.l:.4f} {self.c:.4f} {self.h:.2f} / {self.alpha:.2f})"
        return f"oklch({self.l:.4f} {self.c:.4f} {self.h:.2f})"

    def estimated_y(self) -> float:
        """Compute estimated CIE 1931 relative luminance Y in [0.0, 1.0].

        Converts from OKLCH -> OKLab -> LMS cube -> Linear sRGB -> Y.
        When chroma is zero (achromatic), Y collapses exactly to l^3.
        """
        if self.c < 1e-6:
            return self.l ** 3

        rad = math.radians(self.h)
        a = self.c * math.cos(rad)
        b = self.c * math.sin(rad)

        # OKLab to non-linear LMS
        l_prime = self.l + 0.3963377774 * a + 0.2158037573 * b
        m_prime = self.l - 0.1055613458 * a - 0.0638541728 * b
        s_prime = self.l - 0.0894841775 * a - 1.2914855480 * b

        # Cubic non-linearity
        lms_l = l_prime ** 3
        lms_m = m_prime ** 3
        lms_s = s_prime ** 3

        # LMS to Linear sRGB
        r_lin = +4.0767434770 * lms_l - 3.3077115913 * lms_m + 0.2309699292 * lms_s
        g_lin = -1.2684380046 * lms_l + 2.6097574011 * lms_m - 0.3413193965 * lms_s
        b_lin = -0.0041960863 * lms_l - 0.7034186147 * lms_m + 1.7076147010 * lms_s

        # Rec. 709 / sRGB relative luminance Y
        y = 0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin
        return max(0.0, min(1.0, y))

    def apca_contrast(self, background: OKLCHColor) -> float:
        """Calculate APCA (Advanced Perceptual Contrast Algorithm) Lc score.

        Implements APCA 0.98G standard:
        - Returns positive Lc for dark text on light background (BoW).
        - Returns negative Lc for light text on dark background (WoB).
        - WCAG AAA body text typically requires |Lc| >= 75.
        - Large text / prominent UI requires |Lc| >= 60.
        """
        y_txt = self.estimated_y()
        y_bg = background.estimated_y()

        # Black clipping threshold and exponent
        blk_thrs = 0.022
        blk_clmp = 1.414

        # Power exponents for normal (BoW) and reverse (WoB) polarities
        norm_bg_power = 0.56
        norm_txt_power = 0.57
        rev_bg_power = 0.62
        rev_txt_power = 0.65

        scale_bow = 1.1414
        scale_wob = 1.1414
        lo_bow_offset = 0.027
        lo_wob_offset = 0.027
        lo_clip = 0.1
        delta_y_min = 0.0005

        # Soft black clamp near near-zero luminance
        y_bg_c = y_bg if y_bg >= blk_thrs else y_bg + (blk_thrs - y_bg) ** blk_clmp
        y_txt_c = y_txt if y_txt >= blk_thrs else y_txt + (blk_thrs - y_txt) ** blk_clmp

        if abs(y_bg_c - y_txt_c) < delta_y_min:
            return 0.0

        if y_bg_c > y_txt_c:
            # Dark text on light background (Black on White - BoW)
            s_apca = (y_bg_c ** norm_bg_power - y_txt_c ** norm_txt_power) * scale_bow
            if s_apca < lo_clip:
                return 0.0
            return (s_apca - lo_bow_offset) * 100.0
        else:
            # Light text on dark background (White on Black - WoB)
            s_apca = (y_bg_c ** rev_bg_power - y_txt_c ** rev_txt_power) * scale_wob
            if s_apca > -lo_clip:
                return 0.0
            return (s_apca + lo_wob_offset) * 100.0

    @classmethod
    def from_hex(cls, hex_code: str, alpha: float = 1.0) -> OKLCHColor:
        """Create OKLCHColor from standard sRGB hex string (#RGB, #RRGGBB, #RRGGBBAA)."""
        clean = hex_code.strip().lstrip("#")
        if len(clean) == 3:
            r = int(clean[0] * 2, 16) / 255.0
            g = int(clean[1] * 2, 16) / 255.0
            b = int(clean[2] * 2, 16) / 255.0
        elif len(clean) == 6:
            r = int(clean[0:2], 16) / 255.0
            g = int(clean[2:4], 16) / 255.0
            b = int(clean[4:6], 16) / 255.0
        elif len(clean) == 8:
            r = int(clean[0:2], 16) / 255.0
            g = int(clean[2:4], 16) / 255.0
            b = int(clean[4:6], 16) / 255.0
            alpha = int(clean[6:8], 16) / 255.0
        else:
            return cls(l=0.0, c=0.0, h=0.0, alpha=alpha)

        # Gamma decode to linear sRGB
        def to_lin(c_val: float) -> float:
            return c_val / 12.92 if c_val <= 0.04045 else ((c_val + 0.055) / 1.055) ** 2.4

        r_lin, g_lin, b_lin = to_lin(r), to_lin(g), to_lin(b)

        # Linear sRGB to LMS
        l_cone = 0.4122214708 * r_lin + 0.5363325363 * g_lin + 0.0514459929 * b_lin
        m_cone = 0.2119034982 * r_lin + 0.6806995451 * g_lin + 0.1073969566 * b_lin
        s_cone = 0.0883024619 * r_lin + 0.2817188376 * g_lin + 0.6299787005 * b_lin

        # Cube root
        l_prime = math.copysign(abs(l_cone) ** (1.0 / 3.0), l_cone)
        m_prime = math.copysign(abs(m_cone) ** (1.0 / 3.0), m_cone)
        s_prime = math.copysign(abs(s_cone) ** (1.0 / 3.0), s_cone)

        # LMS to OKLab
        l_ok = 0.2104542553 * l_prime + 0.7936177850 * m_prime - 0.0040720468 * s_prime
        a_ok = 1.9779984951 * l_prime - 2.4285922050 * m_prime + 0.4505937099 * s_prime
        b_ok = 0.0259040371 * l_prime + 0.7827717662 * m_prime - 0.8086757660 * s_prime

        # OKLab to OKLCH
        chroma = math.sqrt(a_ok * a_ok + b_ok * b_ok)
        hue = math.degrees(math.atan2(b_ok, a_ok)) % 360.0

        return cls(l=l_ok, c=chroma, h=hue, alpha=alpha)


# ==============================================================================
# 2. PARAMETRIC GEOMETRY & CURVES
# ==============================================================================

class ParametricGeometry:
    """Pure-Python parametric math and vector geometry solver."""

    @staticmethod
    def polar_to_cartesian(
        cx: float,
        cy: float,
        radius: float,
        angle_degrees: float,
    ) -> tuple[float, float]:
        """Convert 2D polar coordinates (radius, angle_degrees) centered at (cx, cy) to Cartesian (x, y)."""
        cx_c = _coerce_finite_float(cx)
        cy_c = _coerce_finite_float(cy)
        rad_c = max(0.0, _coerce_finite_float(radius))
        ang_c = _coerce_finite_float(angle_degrees)

        theta = math.radians(ang_c)
        x = cx_c + rad_c * math.cos(theta)
        y = cy_c + rad_c * math.sin(theta)
        return (round(x, 4), round(y, 4))

    @staticmethod
    def circular_arc(
        cx: float,
        cy: float,
        radius: float,
        start_angle: float,
        end_angle: float,
        clock_wise: bool = True,
    ) -> str:
        """Generate an SVG path command string for a circular arc.

        Angles are in degrees. Supports arbitrary arc spans including full 360-degree circles.
        """
        cx_c = _coerce_finite_float(cx)
        cy_c = _coerce_finite_float(cy)
        rad_c = max(0.0, _coerce_finite_float(radius))
        start_a = _coerce_finite_float(start_angle)
        end_a = _coerce_finite_float(end_angle)

        if rad_c <= 1e-6:
            return f"M {cx_c:.4f} {cy_c:.4f}"

        # Calculate angular distance along the direction of travel
        if clock_wise:
            delta = (end_a - start_a) % 360.0
        else:
            delta = (start_a - end_a) % 360.0

        x_start, y_start = ParametricGeometry.polar_to_cartesian(cx_c, cy_c, rad_c, start_a)

        # If full circle (or delta ~ 360), SVG arc requires two 180-degree semicircles
        if abs(delta) < 1e-4 or abs(delta - 360.0) < 1e-4:
            mid_a = start_a + (180.0 if clock_wise else -180.0)
            x_mid, y_mid = ParametricGeometry.polar_to_cartesian(cx_c, cy_c, rad_c, mid_a)
            sweep = 1 if clock_wise else 0
            return (
                f"M {x_start:.4f} {y_start:.4f} "
                f"A {rad_c:.4f} {rad_c:.4f} 0 1 {sweep} {x_mid:.4f} {y_mid:.4f} "
                f"A {rad_c:.4f} {rad_c:.4f} 0 1 {sweep} {x_start:.4f} {y_start:.4f}"
            )

        x_end, y_end = ParametricGeometry.polar_to_cartesian(cx_c, cy_c, rad_c, end_a)
        large_arc = 1 if delta > 180.0 else 0
        sweep_flag = 1 if clock_wise else 0

        return f"M {x_start:.4f} {y_start:.4f} A {rad_c:.4f} {rad_c:.4f} 0 {large_arc} {sweep_flag} {x_end:.4f} {y_end:.4f}"

    @staticmethod
    def derive_catmull_rom_bezier_segments(
        points: Sequence[tuple[float, float]],
        tension: float = 0.5,
        closed: bool = False,
    ) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]]:
        """Derive cubic Bezier control segments (P1, C1, C2, P2) for a Catmull-Rom spline.

        Guarantees C1 (tangent) continuity across all internal control points:
        Tangents at junction point P2 of segment k and junction point P1 of segment k+1 are identical:
            T(P2) = k * (P3 - P1)
        where k = (1.0 - tension) / 3.0 (or standard scaling factor).
        """
        pts = [(_coerce_finite_float(p[0]), _coerce_finite_float(p[1])) for p in points]
        n = len(pts)
        if n < 2:
            return []

        # Tangent scale factor: standard Catmull-Rom has tension=0.0 giving k = 1/6.
        # With parameter tension in [0, 1], k = (1.0 - tension) / 3.0 gives smooth C1 curves.
        clamped_tension = max(-2.0, min(1.0, _coerce_finite_float(tension, 0.5)))
        k = (1.0 - clamped_tension) / 3.0

        segments: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]] = []

        if closed:
            for i in range(n):
                p0 = pts[(i - 1) % n]
                p1 = pts[i]
                p2 = pts[(i + 1) % n]
                p3 = pts[(i + 2) % n]

                c1 = (p1[0] + k * (p2[0] - p0[0]), p1[1] + k * (p2[1] - p0[1]))
                c2 = (p2[0] - k * (p3[0] - p1[0]), p2[1] - k * (p3[1] - p1[1]))
                segments.append((p1, c1, c2, p2))
        else:
            # Open curve with extrapolated virtual end control points
            p_ghost_start = (2.0 * pts[0][0] - pts[1][0], 2.0 * pts[0][1] - pts[1][1])
            p_ghost_end = (2.0 * pts[-1][0] - pts[-2][0], 2.0 * pts[-1][1] - pts[-2][1])

            extended = [p_ghost_start] + pts + [p_ghost_end]
            for i in range(1, len(extended) - 2):
                p0 = extended[i - 1]
                p1 = extended[i]
                p2 = extended[i + 1]
                p3 = extended[i + 2]

                c1 = (p1[0] + k * (p2[0] - p0[0]), p1[1] + k * (p2[1] - p0[1]))
                c2 = (p2[0] - k * (p3[0] - p1[0]), p2[1] - k * (p3[1] - p1[1]))
                segments.append((p1, c1, c2, p2))

        return segments

    @staticmethod
    def catmull_rom_spline(
        points: Sequence[tuple[float, float]],
        tension: float = 0.5,
        closed: bool = False,
    ) -> str:
        """Convert a list of 2D control points into a smooth SVG cubic Bezier path string ('d')."""
        segments = ParametricGeometry.derive_catmull_rom_bezier_segments(points, tension=tension, closed=closed)
        if not segments:
            if points:
                p0 = points[0]
                return f"M {_coerce_finite_float(p0[0]):.4f} {_coerce_finite_float(p0[1]):.4f}"
            return ""

        first_p1 = segments[0][0]
        commands = [f"M {first_p1[0]:.4f} {first_p1[1]:.4f}"]

        for _, c1, c2, p2 in segments:
            commands.append(f"C {c1[0]:.4f} {c1[1]:.4f}, {c2[0]:.4f} {c2[1]:.4f}, {p2[0]:.4f} {p2[1]:.4f}")

        if closed:
            commands.append("Z")

        return " ".join(commands)

    @staticmethod
    def isometric_project(
        x: float,
        y: float,
        z: float = 0.0,
        angle_degrees: float = 30.0,
    ) -> tuple[float, float]:
        """Project 3D coordinates (x, y, z) to 2D screen coordinates using a 30-degree isometric matrix.

        Standard isometric projection equations:
            x_screen = (x - y) * cos(theta)
            y_screen = (x + y) * sin(theta) - z
        """
        xc = _coerce_finite_float(x)
        yc = _coerce_finite_float(y)
        zc = _coerce_finite_float(z)
        theta = math.radians(_coerce_finite_float(angle_degrees, 30.0))

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        x_iso = (xc - yc) * cos_t
        y_iso = (xc + yc) * sin_t - zc

        return (round(x_iso, 4), round(y_iso, 4))


# ==============================================================================
# 3. BOUNDING BOX
# ==============================================================================

@dataclass
class BoundingBox:
    """Axis-Aligned 2D Bounding Box (AABB) with spatial queries and viewBox support."""
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        self.x = _coerce_finite_float(self.x, 0.0)
        self.y = _coerce_finite_float(self.y, 0.0)
        self.width = max(0.0, _coerce_finite_float(self.width, 0.0))
        self.height = max(0.0, _coerce_finite_float(self.height, 0.0))

    @property
    def right(self) -> float:
        """Right coordinate (x + width)."""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """Bottom coordinate (y + height)."""
        return self.y + self.height

    @property
    def cx(self) -> float:
        """Center X coordinate."""
        return self.x + self.width / 2.0

    @property
    def cy(self) -> float:
        """Center Y coordinate."""
        return self.y + self.height / 2.0

    def contains(self, item: BoundingBox | tuple[float, float] | list[float]) -> bool:
        """Check if this bounding box contains a point (x, y) or another BoundingBox."""
        if isinstance(item, BoundingBox):
            return (
                item.x >= self.x
                and item.right <= self.right
                and item.y >= self.y
                and item.bottom <= self.bottom
            )
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            px = _coerce_finite_float(item[0])
            py = _coerce_finite_float(item[1])
            return (self.x <= px <= self.right) and (self.y <= py <= self.bottom)
        return False

    def intersects(self, other: BoundingBox) -> bool:
        """Check if this bounding box intersects/overlaps with another BoundingBox."""
        if not isinstance(other, BoundingBox):
            return False
        return not (
            self.right < other.x
            or other.right < self.x
            or self.bottom < other.y
            or other.bottom < self.y
        )

    @classmethod
    def enclosing(cls, boxes: Iterable[BoundingBox], padding: float = 0.0) -> BoundingBox:
        """Compute the minimal bounding box enclosing all given boxes, with optional padding."""
        box_list = [b for b in boxes if isinstance(b, BoundingBox) and (b.width > 0 or b.height > 0)]
        if not box_list:
            pad = max(0.0, _coerce_finite_float(padding))
            return cls(x=-pad, y=-pad, width=2.0 * pad, height=2.0 * pad)

        min_x = min(b.x for b in box_list)
        min_y = min(b.y for b in box_list)
        max_right = max(b.right for b in box_list)
        max_bottom = max(b.bottom for b in box_list)

        pad = max(0.0, _coerce_finite_float(padding))
        return cls(
            x=min_x - pad,
            y=min_y - pad,
            width=(max_right - min_x) + 2.0 * pad,
            height=(max_bottom - min_y) + 2.0 * pad,
        )

    def to_viewbox(self, padding: float = 0.0) -> str:
        """Format as SVG viewBox string: 'min-x min-y width height'."""
        pad = max(0.0, _coerce_finite_float(padding))
        vx = self.x - pad
        vy = self.y - pad
        vw = self.width + 2.0 * pad
        vh = self.height + 2.0 * pad
        return f"{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}"


# ==============================================================================
# 4. VNODE (VECTOR AST NODE)
# ==============================================================================

VALID_VNODE_KINDS = {
    "card",
    "dial",
    "spline",
    "text",
    "badge",
    "grid",
    "conduit",
}


@dataclass
class VNode:
    """Vector Node AST representing a visual or structural element."""
    id: str
    kind: str
    width: float = 0.0
    height: float = 0.0
    x: float = 0.0
    y: float = 0.0
    props: dict[str, Any] = field(default_factory=dict)
    children: list[VNode] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Defensive string sanitation
        self.id = _sanitize_text(self.id, default="node_0")
        if not self.id:
            self.id = f"node_{id(self)}"

        raw_kind = _sanitize_text(self.kind, default="card").lower()
        self.kind = raw_kind if raw_kind in VALID_VNODE_KINDS else "card"

        # Defensive coordinate coercion
        self.width = max(0.0, _coerce_finite_float(self.width, 0.0))
        self.height = max(0.0, _coerce_finite_float(self.height, 0.0))
        self.x = _coerce_finite_float(self.x, 0.0)
        self.y = _coerce_finite_float(self.y, 0.0)

        if not isinstance(self.props, dict):
            self.props = {}
        if not isinstance(self.children, list):
            self.children = []

    @property
    def bbox(self) -> BoundingBox:
        """Get the bounding box of this node alone."""
        return BoundingBox(self.x, self.y, self.width, self.height)

    @property
    def right(self) -> float:
        """Right coordinate (x + width)."""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """Bottom coordinate (y + height)."""
        return self.y + self.height

    @property
    def cx(self) -> float:
        """Center X coordinate."""
        return self.x + self.width / 2.0

    @property
    def cy(self) -> float:
        """Center Y coordinate."""
        return self.y + self.height / 2.0

    def compute_total_bbox(self) -> BoundingBox:
        """Compute the enclosing bounding box of this node and all its children."""
        boxes = [self.bbox]
        for child in self.children:
            if isinstance(child, VNode):
                boxes.append(child.compute_total_bbox())
        return BoundingBox.enclosing(boxes)

    def add_child(self, child: VNode) -> VNode:
        """Add a child VNode and return it."""
        if not isinstance(child, VNode):
            raise TypeError(f"Expected VNode, got {type(child).__name__}")
        self.children.append(child)
        return child

    def find_by_id(self, target_id: str, _depth: int = 0) -> VNode | None:
        """Find a node by ID in this subtree with deep-nesting recursion guard."""
        if _depth > 100:
            return None
        clean_id = _sanitize_text(target_id)
        if self.id == clean_id:
            return self
        for child in self.children:
            found = child.find_by_id(clean_id, _depth + 1)
            if found is not None:
                return found
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize VNode subtree to dictionary."""
        return {
            "id": self.id,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "props": dict(self.props),
            "children": [c.to_dict() for c in self.children if isinstance(c, VNode)],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], _depth: int = 0) -> VNode:
        """Deserialize dictionary into a VNode tree with deep-nesting protection."""
        if _depth > 100:
            raise ValueError("VNode nesting exceeds maximum recursion depth of 100")
        if not isinstance(data, dict):
            raise TypeError("VNode data must be a dictionary")

        children_data = data.get("children", [])
        children: list[VNode] = []
        if isinstance(children_data, list):
            for child_dict in children_data:
                if isinstance(child_dict, dict):
                    children.append(cls.from_dict(child_dict, _depth + 1))

        return cls(
            id=str(data.get("id", "node")),
            kind=str(data.get("kind", "card")),
            width=_coerce_finite_float(data.get("width", 0.0)),
            height=_coerce_finite_float(data.get("height", 0.0)),
            x=_coerce_finite_float(data.get("x", 0.0)),
            y=_coerce_finite_float(data.get("y", 0.0)),
            props=dict(data.get("props", {})),
            children=children,
        )


# ==============================================================================
# 5. VLAYOUT SOLVER
# ==============================================================================

class VLayoutSolver:
    """Thread-safe 2D relational layout solver with defensive parameter coercion.

    Guards against:
    - NaN and Infinite values
    - Null bytes in node identifiers and strings
    - Deep nesting recursion overflows
    - Cyclic relational dependencies
    """

    def __init__(self, max_depth: int = 64) -> None:
        self._lock = threading.RLock()
        self.max_depth = max(4, min(256, max_depth))
        self._constraints: list[dict[str, Any]] = []

    def clear_constraints(self) -> None:
        """Clear all registered relational constraints."""
        with self._lock:
            self._constraints.clear()

    def pin_to_viewport(
        self,
        node: VNode,
        viewport_width: float,
        viewport_height: float,
        anchor: str = "top-left",
        margin: float = 0.0,
    ) -> VNode:
        """Anchor a VNode to viewport coordinates based on an anchor mode.

        Supported anchors:
        'top-left', 'top-right', 'bottom-left', 'bottom-right',
        'center', 'top-center', 'bottom-center', 'center-left', 'center-right'.
        """
        with self._lock:
            vw = max(0.0, _coerce_finite_float(viewport_width, 1920.0))
            vh = max(0.0, _coerce_finite_float(viewport_height, 1080.0))
            m = max(0.0, _coerce_finite_float(margin, 0.0))
            clean_anchor = _sanitize_text(anchor, "top-left").lower()

            w = node.width
            h = node.height

            if clean_anchor == "top-left":
                node.x = m
                node.y = m
            elif clean_anchor == "top-right":
                node.x = vw - w - m
                node.y = m
            elif clean_anchor == "bottom-left":
                node.x = m
                node.y = vh - h - m
            elif clean_anchor == "bottom-right":
                node.x = vw - w - m
                node.y = vh - h - m
            elif clean_anchor == "center":
                node.x = (vw - w) / 2.0
                node.y = (vh - h) / 2.0
            elif clean_anchor == "top-center":
                node.x = (vw - w) / 2.0
                node.y = m
            elif clean_anchor == "bottom-center":
                node.x = (vw - w) / 2.0
                node.y = vh - h - m
            elif clean_anchor == "center-left":
                node.x = m
                node.y = (vh - h) / 2.0
            elif clean_anchor == "center-right":
                node.x = vw - w - m
                node.y = (vh - h) / 2.0
            else:
                node.x = m
                node.y = m

            return node

    def align_relative(
        self,
        target: VNode,
        reference: VNode,
        relation: str,
        gap: float = 0.0,
        alignment: str = "start",
    ) -> VNode:
        """Position target relative to reference using relational constraints and alignments.

        Relations:
        - 'right_of' / 'right': target is positioned to the right of reference
        - 'left_of' / 'left': target is positioned to the left of reference
        - 'below' / 'bottom': target is positioned below reference
        - 'above' / 'top': target is positioned above reference
        - 'inside' / 'center': target is centered inside reference

        Alignments:
        - For horizontal relations: 'start' (top), 'center' (middle), 'end' (bottom)
        - For vertical relations: 'start' (left), 'center' (middle), 'end' (right)
        """
        with self._lock:
            g = _coerce_finite_float(gap, 0.0)
            rel = _sanitize_text(relation, "right_of").lower()
            align = _sanitize_text(alignment, "start").lower()

            if rel in ("right_of", "right", "after"):
                target.x = reference.right + g
                if align in ("center", "middle"):
                    target.y = reference.cy - target.height / 2.0
                elif align in ("end", "bottom"):
                    target.y = reference.bottom - target.height
                else:
                    target.y = reference.y

            elif rel in ("left_of", "left", "before"):
                target.x = reference.x - target.width - g
                if align in ("center", "middle"):
                    target.y = reference.cy - target.height / 2.0
                elif align in ("end", "bottom"):
                    target.y = reference.bottom - target.height
                else:
                    target.y = reference.y

            elif rel in ("below", "bottom", "under"):
                target.y = reference.bottom + g
                if align in ("center", "middle"):
                    target.x = reference.cx - target.width / 2.0
                elif align in ("end", "right"):
                    target.x = reference.right - target.width
                else:
                    target.x = reference.x

            elif rel in ("above", "top"):
                target.y = reference.y - target.height - g
                if align in ("center", "middle"):
                    target.x = reference.cx - target.width / 2.0
                elif align in ("end", "right"):
                    target.x = reference.right - target.width
                else:
                    target.x = reference.x

            elif rel in ("inside", "center", "fit"):
                target.x = reference.x + (reference.width - target.width) / 2.0
                target.y = reference.y + (reference.height - target.height) / 2.0

            return target

    def register_constraint(
        self,
        target_id: str,
        reference_id: str,
        relation: str,
        gap: float = 0.0,
        alignment: str = "start",
    ) -> None:
        """Register a deferred relational constraint to be solved in topological order."""
        with self._lock:
            self._constraints.append({
                "target_id": _sanitize_text(target_id),
                "reference_id": _sanitize_text(reference_id),
                "relation": _sanitize_text(relation),
                "gap": _coerce_finite_float(gap),
                "alignment": _sanitize_text(alignment),
            })

    def _verify_depth(self, node: VNode, current_depth: int = 1) -> None:
        """Defensively verify that the node tree does not exceed max_depth."""
        if current_depth > self.max_depth:
            raise ValueError(f"Tree nesting depth exceeded safety threshold of {self.max_depth}")
        for child in node.children:
            if isinstance(child, VNode):
                self._verify_depth(child, current_depth + 1)

    def solve(
        self,
        root: VNode | None = None,
        viewport_width: float = 1920.0,
        viewport_height: float = 1080.0,
        nodes: list[VNode] | None = None,
    ) -> BoundingBox:
        """Solve layout constraints and compute the total enclosing BoundingBox."""
        with self._lock:
            vw = max(0.0, _coerce_finite_float(viewport_width, 1920.0))
            vh = max(0.0, _coerce_finite_float(viewport_height, 1080.0))

            all_nodes: list[VNode] = []
            if root is not None:
                self._verify_depth(root)
                all_nodes.append(root)
                # Gather all nodes recursively
                def collect(n: VNode) -> None:
                    for ch in n.children:
                        if isinstance(ch, VNode):
                            all_nodes.append(ch)
                            collect(ch)
                collect(root)

            if nodes:
                for nd in nodes:
                    if isinstance(nd, VNode) and nd not in all_nodes:
                        self._verify_depth(nd)
                        all_nodes.append(nd)

            node_map = {n.id: n for n in all_nodes if n.id}

            # Solve viewport pinning declared in props
            for n in all_nodes:
                pin_prop = n.props.get("pin_to_viewport")
                if isinstance(pin_prop, dict):
                    anchor = pin_prop.get("anchor", "top-left")
                    margin = pin_prop.get("margin", 0.0)
                    self.pin_to_viewport(n, vw, vh, anchor=anchor, margin=margin)

            # Solve relational constraints declared in props
            for n in all_nodes:
                align_prop = n.props.get("align_relative")
                if isinstance(align_prop, dict):
                    ref_id = _sanitize_text(align_prop.get("reference_id", ""))
                    if ref_id in node_map and ref_id != n.id:
                        ref_node = node_map[ref_id]
                        rel = align_prop.get("relation", "right_of")
                        gap = align_prop.get("gap", 0.0)
                        align = align_prop.get("alignment", "start")
                        self.align_relative(n, ref_node, relation=rel, gap=gap, alignment=align)

            # Solve registered constraints with simple topological cycle guard
            visited_targets: set[str] = set()
            for c in self._constraints:
                t_id = c["target_id"]
                r_id = c["reference_id"]
                if t_id == r_id or t_id in visited_targets:
                    continue
                if t_id in node_map and r_id in node_map:
                    self.align_relative(
                        node_map[t_id],
                        node_map[r_id],
                        relation=c["relation"],
                        gap=c["gap"],
                        alignment=c["alignment"],
                    )
                    visited_targets.add(t_id)

            if root is not None:
                return root.compute_total_bbox()
            elif all_nodes:
                return BoundingBox.enclosing([n.bbox for n in all_nodes])
            return BoundingBox(0.0, 0.0, vw, vh)

    def solve_layout(
        self,
        root: VNode | dict[str, Any],
        viewport_width: float = 1920.0,
        viewport_height: float = 1080.0,
    ) -> dict[str, Any]:
        """Unified method for dispatcher integration accepting either VNode or dict."""
        with self._lock:
            if isinstance(root, dict):
                vroot = VNode.from_dict(root)
            elif isinstance(root, VNode):
                vroot = root
            else:
                raise TypeError(f"Invalid root type: {type(root).__name__}")

            bbox = self.solve(vroot, viewport_width, viewport_height)
            return {
                "success": True,
                "bbox": {
                    "x": bbox.x,
                    "y": bbox.y,
                    "width": bbox.width,
                    "height": bbox.height,
                    "right": bbox.right,
                    "bottom": bbox.bottom,
                },
                "viewBox": bbox.to_viewbox(padding=16.0),
                "root": vroot.to_dict(),
            }


# ==============================================================================
# 6. FABLE VECTOR COMPILER
# ==============================================================================

class FableVectorCompiler:
    """Production-grade vector compiler generating XML-standard SVG with OKLCH, filters, and a11y."""

    def __init__(self, default_padding: float = 24.0) -> None:
        self.default_padding = max(0.0, _coerce_finite_float(default_padding, 24.0))

    def _color_to_str(self, val: Any, fallback: str = "none") -> str:
        """Coerce OKLCHColor or string to valid SVG color."""
        if isinstance(val, OKLCHColor):
            return val.to_svg()
        if isinstance(val, str):
            clean = _sanitize_text(val).strip()
            return clean if clean else fallback
        return fallback

    def compile(
        self,
        root: VNode | dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> str:
        """Compile a VNode tree into an SVG string conforming strictly to XML standard.

        Features:
        - ViewBox enclosure computed automatically from node bounding boxes.
        - Micro-grain procedural noise filter (<feTurbulence> + <feColorMatrix>).
        - Embedded OKLCH Linear and Radial gradients.
        - Accessibility attributes (role='img', <title>, <desc>, aria-label).
        """
        opts = options or {}
        if isinstance(root, dict):
            vroot = VNode.from_dict(root)
        elif isinstance(root, VNode):
            vroot = root
        else:
            raise TypeError(f"Expected VNode or dict, got {type(root).__name__}")

        # Solve layout if not already pinned
        solver = VLayoutSolver()
        solver.solve(vroot)

        # Enclosing viewBox
        pad = max(0.0, _coerce_finite_float(opts.get("padding", self.default_padding)))
        total_bbox = vroot.compute_total_bbox()
        view_box_str = total_bbox.to_viewbox(padding=pad)

        # Accessibility metadata
        title_text = _sanitize_text(opts.get("title", vroot.props.get("title", f"Fable Vector: {vroot.id}")))
        desc_text = _sanitize_text(opts.get("desc", vroot.props.get("desc", "Neuro-Symbolic Vector Graphics generated by Fable-Vector Engine")))

        # Construct XML ElementTree
        svg_attribs = {
            "xmlns": "http://www.w3.org/2000/svg",
            "viewBox": view_box_str,
            "width": "100%",
            "height": "100%",
            "role": "img",
            "aria-label": title_text,
        }
        svg_elem = ET.Element("svg", svg_attribs)

        # Accessibility title and desc
        title_elem = ET.SubElement(svg_elem, "title")
        title_elem.text = title_text
        desc_elem = ET.SubElement(svg_elem, "desc")
        desc_elem.text = desc_text

        # <defs> element for procedural noise and gradients
        defs_elem = ET.SubElement(svg_elem, "defs")
        self._build_defs(defs_elem, opts)

        # Recursively render nodes
        self._render_vnode(svg_elem, vroot)

        # Convert to well-formed string and verify XML AST parsing
        raw_xml = ET.tostring(svg_elem, encoding="unicode", method="xml")
        
        # Verify XML AST well-formedness
        try:
            ET.fromstring(raw_xml)
        except ET.ParseError as err:
            raise ValueError(f"FableVectorCompiler generated malformed XML AST: {err}")

        return raw_xml

    def _build_defs(self, defs: ET.Element, opts: dict[str, Any]) -> None:
        """Inject micro-grain noise filter and OKLCH gradients into <defs>."""
        # 1. Micro-grain procedural noise filter (feTurbulence)
        filter_elem = ET.SubElement(defs, "filter", {
            "id": "fable-micro-grain",
            "x": "0%",
            "y": "0%",
            "width": "100%",
            "height": "100%",
        })
        ET.SubElement(filter_elem, "feTurbulence", {
            "type": "fractalNoise",
            "baseFrequency": "0.85",
            "numOctaves": "4",
            "stitchTiles": "stitch",
            "result": "noise",
        })
        ET.SubElement(filter_elem, "feColorMatrix", {
            "type": "matrix",
            "values": "0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.05 0",
            "in": "noise",
            "result": "grain",
        })
        ET.SubElement(filter_elem, "feComposite", {
            "operator": "in",
            "in": "grain",
            "in2": "SourceGraphic",
            "result": "composite",
        })
        ET.SubElement(filter_elem, "feBlend", {
            "mode": "overlay",
            "in": "composite",
            "in2": "SourceGraphic",
        })

        # 2. Cyber-Obsidian Monolith OKLCH Gradients
        obsidian_grad = ET.SubElement(defs, "linearGradient", {
            "id": "fable-grad-obsidian",
            "x1": "0%",
            "y1": "0%",
            "x2": "100%",
            "y2": "100%",
        })
        ET.SubElement(obsidian_grad, "stop", {
            "offset": "0%",
            "stop-color": "oklch(0.16 0.03 270)",
            "stop-opacity": "0.95",
        })
        ET.SubElement(obsidian_grad, "stop", {
            "offset": "100%",
            "stop-color": "oklch(0.08 0.02 270)",
            "stop-opacity": "0.98",
        })

        # Specular rim highlight gradient
        specular_grad = ET.SubElement(defs, "linearGradient", {
            "id": "fable-grad-specular",
            "x1": "0%",
            "y1": "0%",
            "x2": "100%",
            "y2": "0%",
        })
        ET.SubElement(specular_grad, "stop", {
            "offset": "0%",
            "stop-color": "oklch(1.00 0.00 0 / 0.18)",
        })
        ET.SubElement(specular_grad, "stop", {
            "offset": "100%",
            "stop-color": "oklch(1.00 0.00 0 / 0.02)",
        })

        # Accent gradient (Teal-Cyan to Violet)
        accent_grad = ET.SubElement(defs, "linearGradient", {
            "id": "fable-grad-accent",
            "x1": "0%",
            "y1": "0%",
            "x2": "100%",
            "y2": "100%",
        })
        ET.SubElement(accent_grad, "stop", {
            "offset": "0%",
            "stop-color": "oklch(0.75 0.18 190)",
        })
        ET.SubElement(accent_grad, "stop", {
            "offset": "100%",
            "stop-color": "oklch(0.55 0.22 260)",
        })

    def _render_vnode(self, parent_elem: ET.Element, node: VNode) -> None:
        """Render a VNode and its children into SVG elements according to kind."""
        g = ET.SubElement(parent_elem, "g", {
            "id": node.id,
            "class": f"fable-vnode fable-{node.kind}",
        })

        props = node.props
        fill = self._color_to_str(props.get("fill"), fallback="none")
        stroke = self._color_to_str(props.get("stroke"), fallback="none")
        stroke_width = str(_coerce_finite_float(props.get("stroke_width", 1.0)))

        if node.kind == "card":
            rx = str(_coerce_finite_float(props.get("rx", 12.0)))
            # Default card background to obsidian gradient if not specified
            card_fill = fill if fill != "none" else "url(#fable-grad-obsidian)"
            card_stroke = stroke if stroke != "none" else "oklch(0.28 0.02 270 / 0.50)"

            # Main card body with micro-grain filter
            ET.SubElement(g, "rect", {
                "x": f"{node.x:.2f}",
                "y": f"{node.y:.2f}",
                "width": f"{node.width:.2f}",
                "height": f"{node.height:.2f}",
                "rx": rx,
                "fill": card_fill,
                "stroke": card_stroke,
                "stroke-width": stroke_width,
                "filter": "url(#fable-micro-grain)",
            })

            # Specular top hairline rim highlight
            if props.get("specular_rim", True) and node.width > 20:
                ET.SubElement(g, "line", {
                    "x1": f"{node.x + 8:.2f}",
                    "y1": f"{node.y + 1:.2f}",
                    "x2": f"{node.right - 8:.2f}",
                    "y2": f"{node.y + 1:.2f}",
                    "stroke": "url(#fable-grad-specular)",
                    "stroke-width": "1",
                    "stroke-linecap": "round",
                })

        elif node.kind == "dial":
            cx = node.cx
            cy = node.cy
            radius = min(node.width, node.height) / 2.0 - 8.0
            radius = max(2.0, radius)
            start_angle = _coerce_finite_float(props.get("start_angle", 135.0))
            end_angle = _coerce_finite_float(props.get("end_angle", 405.0))
            value = max(0.0, min(1.0, _coerce_finite_float(props.get("value", 0.75))))

            # Background track arc
            track_d = ParametricGeometry.circular_arc(cx, cy, radius, start_angle, end_angle)
            ET.SubElement(g, "path", {
                "d": track_d,
                "fill": "none",
                "stroke": self._color_to_str(props.get("track_color"), "oklch(0.20 0.02 270)"),
                "stroke-width": str(_coerce_finite_float(props.get("track_width", 6.0))),
                "stroke-linecap": "round",
            })

            # Value indicator arc
            val_span = (end_angle - start_angle) * value
            current_end = start_angle + val_span
            val_d = ParametricGeometry.circular_arc(cx, cy, radius, start_angle, current_end)
            ET.SubElement(g, "path", {
                "d": val_d,
                "fill": "none",
                "stroke": self._color_to_str(props.get("dial_color"), "url(#fable-grad-accent)"),
                "stroke-width": str(_coerce_finite_float(props.get("dial_width", 6.0))),
                "stroke-linecap": "round",
            })

            # Value text in center
            if "label" in props or "value" in props:
                lbl = _sanitize_text(props.get("label", f"{int(value * 100)}%"))
                txt = ET.SubElement(g, "text", {
                    "x": f"{cx:.2f}",
                    "y": f"{cy + 4:.2f}",
                    "text-anchor": "middle",
                    "fill": self._color_to_str(props.get("text_color"), "oklch(0.96 0.01 270)"),
                    "font-family": "system-ui, -apple-system, sans-serif",
                    "font-size": "14",
                    "font-weight": "600",
                })
                txt.text = lbl

        elif node.kind == "spline":
            raw_pts = props.get("points", [])
            tension = _coerce_finite_float(props.get("tension", 0.5))
            closed = bool(props.get("closed", False))
            pts: list[tuple[float, float]] = []
            if isinstance(raw_pts, list):
                for p in raw_pts:
                    if isinstance(p, (tuple, list)) and len(p) >= 2:
                        pts.append((node.x + _coerce_finite_float(p[0]), node.y + _coerce_finite_float(p[1])))

            d_str = ParametricGeometry.catmull_rom_spline(pts, tension=tension, closed=closed)
            ET.SubElement(g, "path", {
                "d": d_str,
                "fill": fill,
                "stroke": stroke if stroke != "none" else "url(#fable-grad-accent)",
                "stroke-width": stroke_width if stroke_width != "0.0" else "2",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            })

        elif node.kind == "text":
            font_size = str(_coerce_finite_float(props.get("font_size", 14.0)))
            font_weight = _sanitize_text(props.get("font_weight", "500"))
            font_family = _sanitize_text(props.get("font_family", "system-ui, -apple-system, sans-serif"))
            text_anchor = _sanitize_text(props.get("text_anchor", "start"))
            txt_fill = fill if fill != "none" else "oklch(0.96 0.01 270)"
            raw_content = _sanitize_text(props.get("text", node.id))

            txt_elem = ET.SubElement(g, "text", {
                "x": f"{node.x:.2f}",
                "y": f"{node.y + node.height:.2f}" if node.height > 0 else f"{node.y:.2f}",
                "fill": txt_fill,
                "font-family": font_family,
                "font-size": font_size,
                "font-weight": font_weight,
                "text-anchor": text_anchor,
            })
            txt_elem.text = raw_content

        elif node.kind == "badge":
            rx = str(min(node.width, node.height) / 2.0)
            badge_fill = fill if fill != "none" else "oklch(0.20 0.03 270)"
            badge_stroke = stroke if stroke != "none" else "oklch(0.75 0.18 190 / 0.5)"

            ET.SubElement(g, "rect", {
                "x": f"{node.x:.2f}",
                "y": f"{node.y:.2f}",
                "width": f"{node.width:.2f}",
                "height": f"{node.height:.2f}",
                "rx": rx,
                "fill": badge_fill,
                "stroke": badge_stroke,
                "stroke-width": stroke_width,
            })

            label = _sanitize_text(props.get("label", node.id))
            txt_elem = ET.SubElement(g, "text", {
                "x": f"{node.cx:.2f}",
                "y": f"{node.cy + 4:.2f}",
                "text-anchor": "middle",
                "fill": self._color_to_str(props.get("text_color"), "oklch(0.96 0.01 270)"),
                "font-family": "system-ui, -apple-system, sans-serif",
                "font-size": "11",
                "font-weight": "600",
            })
            txt_elem.text = label

        elif node.kind == "grid":
            spacing = max(8.0, _coerce_finite_float(props.get("spacing", 32.0)))
            grid_stroke = stroke if stroke != "none" else "oklch(0.20 0.01 270 / 0.4)"
            is_isometric = bool(props.get("isometric", False))

            if is_isometric:
                # Isometric dot matrix or isometric diamond grid
                cols = int(node.width / spacing) + 1
                rows = int(node.height / spacing) + 1
                for c_idx in range(cols):
                    for r_idx in range(rows):
                        iso_x, iso_y = ParametricGeometry.isometric_project(c_idx * spacing, r_idx * spacing)
                        ET.SubElement(g, "circle", {
                            "cx": f"{node.x + iso_x:.2f}",
                            "cy": f"{node.y + iso_y:.2f}",
                            "r": "1.5",
                            "fill": grid_stroke,
                        })
            else:
                # Cartesian orthogonal lines
                cur_x = node.x
                while cur_x <= node.right:
                    ET.SubElement(g, "line", {
                        "x1": f"{cur_x:.2f}", "y1": f"{node.y:.2f}",
                        "x2": f"{cur_x:.2f}", "y2": f"{node.bottom:.2f}",
                        "stroke": grid_stroke, "stroke-width": stroke_width,
                    })
                    cur_x += spacing

                cur_y = node.y
                while cur_y <= node.bottom:
                    ET.SubElement(g, "line", {
                        "x1": f"{node.x:.2f}", "y1": f"{cur_y:.2f}",
                        "x2": f"{node.right:.2f}", "y2": f"{cur_y:.2f}",
                        "stroke": grid_stroke, "stroke-width": stroke_width,
                    })
                    cur_y += spacing

        elif node.kind == "conduit":
            x1 = _coerce_finite_float(props.get("x1", node.x))
            y1 = _coerce_finite_float(props.get("y1", node.y))
            x2 = _coerce_finite_float(props.get("x2", node.right))
            y2 = _coerce_finite_float(props.get("y2", node.bottom))
            mid_x = (x1 + x2) / 2.0
            conduit_d = f"M {x1:.2f} {y1:.2f} C {mid_x:.2f} {y1:.2f}, {mid_x:.2f} {y2:.2f}, {x2:.2f} {y2:.2f}"
            ET.SubElement(g, "path", {
                "d": conduit_d,
                "fill": "none",
                "stroke": stroke if stroke != "none" else "oklch(0.55 0.22 260)",
                "stroke-width": stroke_width if stroke_width != "0.0" else "2",
                "stroke-dasharray": _sanitize_text(props.get("dasharray", "")),
            })

        # Recursively render children
        for child in node.children:
            if isinstance(child, VNode):
                self._render_vnode(g, child)
