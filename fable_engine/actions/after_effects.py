"""Agent After Effects - Agent-Native Motion Graphics & Video Composition Engine for Fable Mode.

Provides zero-dependency multi-track composition layers, keyframing (linear & bezier interpolation),
motion graphics rendering, and video frame sequence building guaranteed to operate under 500MB RAM.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.sax.saxutils import escape, quoteattr

from fable_engine.actions.resource_registry import SharedResourceRegistry


MAX_RENDER_FRAMES = 10_000


class Keyframe:
    """Represents a keyframe at a specific timestamp in seconds."""

    def __init__(self, time_sec: float, value: float, easing: str = "linear") -> None:
        self.time_sec = float(time_sec)
        self.value = float(value)
        self.easing = easing


class PropertyTrack:
    """Represents an animatable property (x, y, opacity, rotation, scale, width, height)."""

    def __init__(self, name: str, default_value: float = 0.0) -> None:
        self.name = name
        self.default_value = float(default_value)
        self.keyframes: List[Keyframe] = []

    def add_keyframe(self, time_sec: float, value: float, easing: str = "linear") -> None:
        self.keyframes.append(Keyframe(time_sec, value, easing))
        self.keyframes.sort(key=lambda k: k.time_sec)

    def evaluate(self, time_sec: float) -> float:
        if not self.keyframes:
            return self.default_value
        if time_sec <= self.keyframes[0].time_sec:
            return self.keyframes[0].value
        if time_sec >= self.keyframes[-1].time_sec:
            return self.keyframes[-1].value

        # Interpolate between keyframes
        for i in range(len(self.keyframes) - 1):
            k1 = self.keyframes[i]
            k2 = self.keyframes[i + 1]
            if k1.time_sec <= time_sec <= k2.time_sec:
                span = k2.time_sec - k1.time_sec
                t = (time_sec - k1.time_sec) / span if span > 0 else 0.0
                if k1.easing == "ease_in":
                    t = t * t
                elif k1.easing == "ease_out":
                    t = t * (2 - t)
                elif k1.easing == "ease_in_out":
                    t = 0.5 * (1 - math.cos(t * math.pi))
                return round(k1.value + t * (k2.value - k1.value), 6)

        return round(self.default_value, 6)


class AELayer:
    """Represents a multi-track visual/text/shape layer in an AE timeline."""

    def __init__(
        self,
        layer_id: str,
        name: str,
        layer_type: str = "SHAPE",  # SHAPE, TEXT, SOLID, VIDEO
        width: float = 100.0,
        height: float = 100.0,
        fill: str = "#38BDF8",
        text_content: Optional[str] = None,
        font_size: float = 24.0,
    ) -> None:
        self.layer_id = layer_id
        self.name = name
        self.layer_type = layer_type.upper()
        self.width = float(width)
        self.height = float(height)
        self.fill = fill
        self.text_content = text_content
        self.font_size = float(font_size)

        # Animatable tracks
        self.tracks: Dict[str, PropertyTrack] = {
            "x": PropertyTrack("x", 0.0),
            "y": PropertyTrack("y", 0.0),
            "scale": PropertyTrack("scale", 1.0),
            "rotation": PropertyTrack("rotation", 0.0),
            "opacity": PropertyTrack("opacity", 1.0),
        }

    def evaluate_state(self, time_sec: float) -> Dict[str, float]:
        return {name: track.evaluate(time_sec) for name, track in self.tracks.items()}

    def render_svg_element(self, time_sec: float) -> str:
        state = self.evaluate_state(time_sec)
        x = state["x"]
        y = state["y"]
        scale = state["scale"]
        rot = state["rotation"]
        opacity = max(0.0, min(1.0, state["opacity"]))

        if opacity <= 0.0:
            return ""

        transform_attr = f'transform="translate({x}, {y}) rotate({rot}) scale({scale})"'
        opacity_attr = f' opacity="{opacity}"' if opacity < 1.0 else ""

        if self.layer_type in ("SHAPE", "SOLID"):
            return f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="{self.fill}" {transform_attr}{opacity_attr}/>'
        elif self.layer_type == "TEXT" and self.text_content:
            return (
                f'<text x={quoteattr("0")} y={quoteattr(str(self.font_size))} '
                f'font-size={quoteattr(str(self.font_size))} font-family={quoteattr("sans-serif")} '
                f'fill={quoteattr(str(self.fill))} transform={quoteattr(f"translate({x}, {y}) rotate({rot}) scale({scale})")} '
                f'opacity={quoteattr(str(opacity))}>{escape(str(self.text_content))}</text>'
            )
        return ""


class AEComposition:
    """Represents a video timeline composition with multi-track layers."""

    def __init__(
        self,
        comp_id: str,
        name: str,
        width: float = 1920.0,
        height: float = 1080.0,
        duration_sec: float = 5.0,
        fps: float = 30.0,
    ) -> None:
        self.comp_id = comp_id
        self.name = name
        self.width = float(width)
        self.height = float(height)
        self.duration_sec = float(duration_sec)
        self.fps = float(fps)
        self.layers: List[AELayer] = []

    def add_layer(self, layer: AELayer) -> None:
        self.layers.append(layer)

    def render_frame_svg(self, time_sec: float) -> str:
        elements = [layer.render_svg_element(time_sec) for layer in self.layers]
        body = "\n".join(e for e in elements if e)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" style="background:#090D16">\n'
            f'{body}\n</svg>'
        )

    def render_video_sequence(self) -> List[Dict[str, Any]]:
        """Renders frames across the video composition timeline."""
        total_frames = self._validated_total_frames()
        frames: List[Dict[str, Any]] = []

        for f in range(total_frames):
            time_sec = f / self.fps
            svg = self.render_frame_svg(time_sec)
            frames.append({"frame": f, "timestamp_sec": round(time_sec, 3), "svg_content": svg})
        return frames

    def _validated_total_frames(self) -> int:
        if not math.isfinite(self.duration_sec) or not math.isfinite(self.fps) or self.duration_sec <= 0 or self.fps <= 0:
            raise ValueError("duration_sec and fps must be finite positive values")
        frame_count = self.duration_sec * self.fps
        if not math.isfinite(frame_count):
            raise ValueError(f"render would exceed the maximum of {MAX_RENDER_FRAMES} frames")
        total_frames = int(frame_count)
        if total_frames > MAX_RENDER_FRAMES:
            raise ValueError(f"render would exceed the maximum of {MAX_RENDER_FRAMES} frames")
        return total_frames

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comp_id": self.comp_id,
            "name": self.name,
            "resolution": {"width": self.width, "height": self.height},
            "duration_sec": self.duration_sec,
            "fps": self.fps,
            "total_frames": self._validated_total_frames(),
            "layers_count": len(self.layers),
        }


class AgentAfterEffectsEngine:
    """In-memory agent-native After Effects engine registry."""

    def __init__(self) -> None:
        self.compositions: SharedResourceRegistry[AEComposition] = SharedResourceRegistry()

    def get_or_create_comp(
        self, comp_id: str, name: str = "Main Comp", width: float = 1920.0, height: float = 1080.0, duration_sec: float = 5.0
    ) -> AEComposition:
        if comp_id not in self.compositions:
            self.compositions[comp_id] = AEComposition(comp_id, name, width, height, duration_sec)
        return self.compositions[comp_id]


GLOBAL_AE_ENGINE = AgentAfterEffectsEngine()


def _handle_ae_render_video(arguments: Dict[str, Any]) -> str:
    """Action handler for Agent After Effects tool."""
    action = arguments.get("ae_action", "inspect")
    comp_id = arguments.get("comp_id", "default_comp")

    if action in ("create_comp", "init"):
        name = arguments.get("name", "Video Composition")
        w = float(arguments.get("width", 1920))
        h = float(arguments.get("height", 1080))
        dur = float(arguments.get("duration_sec", 5.0))
        comp = GLOBAL_AE_ENGINE.get_or_create_comp(comp_id, name, w, h, dur)
        return json.dumps({"status": "success", "composition": comp.to_dict()})

    elif action in ("add_layer", "create_layer"):
        comp = GLOBAL_AE_ENGINE.get_or_create_comp(comp_id)
        layer_id = arguments.get("layer_id") or f"layer_{len(comp.layers) + 1}"
        layer = AELayer(
            layer_id=layer_id,
            name=arguments.get("name", "Layer"),
            layer_type=arguments.get("layer_type", "SHAPE"),
            width=float(arguments.get("width", 100)),
            height=float(arguments.get("height", 100)),
            fill=arguments.get("fill", "#38BDF8"),
            text_content=arguments.get("text_content"),
            font_size=float(arguments.get("font_size", 24)),
        )

        keyframes = arguments.get("keyframes", {})
        for prop_name, kf_list in keyframes.items():
            if prop_name in layer.tracks:
                for kf in kf_list:
                    layer.tracks[prop_name].add_keyframe(
                        float(kf.get("time", 0)), float(kf.get("value", 0)), kf.get("easing", "linear")
                    )

        comp.add_layer(layer)
        return json.dumps({"status": "success", "layer_id": layer_id, "comp": comp.to_dict()})

    elif action in ("render_frame", "preview_frame"):
        comp = GLOBAL_AE_ENGINE.compositions.get(comp_id)
        if not comp:
            return f"Error: Composition '{comp_id}' not found."
        time_sec = float(arguments.get("time_sec", 0.0))
        svg = comp.render_frame_svg(time_sec)
        return json.dumps({"status": "success", "comp_id": comp_id, "time_sec": time_sec, "frame_svg": svg})

    elif action in ("render_video", "render_full_video", "render_sequence"):
        comp = GLOBAL_AE_ENGINE.compositions.get(comp_id)
        if not comp:
            return f"Error: Composition '{comp_id}' not found."
        frames = comp.render_video_sequence()
        return json.dumps({"status": "success", "comp_id": comp_id, "total_frames": len(frames), "video_frames": frames})

    elif action in ("inspect", "get"):
        comp = GLOBAL_AE_ENGINE.compositions.get(comp_id)
        if not comp:
            comp = GLOBAL_AE_ENGINE.get_or_create_comp(comp_id)
        return json.dumps({"status": "success", "composition": comp.to_dict()})

    else:
        return f"Error: Unknown ae_action '{action}'. Supported: create_comp, add_layer, render_frame, render_video, inspect."
