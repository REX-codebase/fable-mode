# Fable Haute SVG Craft, Coordinate Mathematics & Vector Design Engine
## Extreme-Precision Vector Engineering, Coordinate Pre-Calculation, OKLCH Gradients & Anti-Slop Visual Philosophy

The `Fable SVG Craft Engine` provides rigorous mathematical standards and aesthetic guidelines for constructing publication-grade scalable vector graphics (SVGs), interactive diagrams, telemetry HUDs, isometric system architectures, procedural filters, and generative visual widgets.

---

## 1. Anti-Slop Vector Philosophy & Core Principles

Generic AI vector generation typically produces "slop":
- Arbitrary, ungrounded coordinates that clip outside the `viewBox`.
- Muddy, over-saturated neon drop-shadows and generic purple/blue glow pills.
- Blurry rasterized filters or default shapes resembling stock clip-art.
- Misaligned anchor points with disconnected path segments.
- Broken responsive behavior due to missing or mismatched `preserveAspectRatio`.

The Fable Vector Engine enforces **Swiss-caliber precision, aerospace telemetry rigor, and Haute Modernist craftsmanship**:

1. **Deterministic Coordinate Pre-Calculation**: Never approximate by eye. Every curve, anchor, arc, and control point must be derived from rigorous trigonometric and geometric equations.
2. **Hairline Vector Definition**: Precision strokes utilize `stroke-width="0.5"` or `1`, paired with `vector-effect="non-scaling-stroke"` so hairlines remain razor-sharp across all zoom levels and display DPRs (Retina/4K).
3. **Perceptually Uniform OKLCH Lighting**: Gradients and fills are specified using OKLCH color space for smooth, natural luminance falloff without the muddy desaturation of legacy sRGB interpolation.
4. **Micro-Grain Texture & Optical Depth**: Procedural SVG noise (`feTurbulence`) creates organic material presence and eliminates banding on dark gradients.
5. **Strict Viewport Containment**: Every path coordinate (x, y) strictly satisfies 0 <= x <= W and 0 <= y <= H of the declared `viewBox="0 0 W H"`.

---

## 2. Coordinate Pre-Calculation Engine & Mathematical Templates

### 2.1 Polar-to-Cartesian Mapping (Radial Dials, Gauges, Network Hubs)
For any circle with center (cx, cy) and radius r:
x = cx + r * cos(theta)
y = cy + r * sin(theta)

*(Note: Angles theta in SVG standard coordinates are measured clockwise from the positive X-axis in radians. For 12-o'clock top start, offset by -pi/2.)*

```python
import math

def polar_to_cartesian(cx: float, cy: float, radius: float, angle_degrees: float) -> tuple[float, float]:
    """Calculate exact SVG (x, y) coordinates from polar angle (degrees, 0 = 12 o'clock)."""
    rad = (angle_degrees - 90.0) * (math.pi / 180.0)
    x = round(cx + (radius * math.cos(rad)), 3)
    y = round(cy + (radius * math.sin(rad)), 3)
    return x, y
```

### 2.2 SVG Circular Arc Construction
An SVG circular arc path segment from angle theta1 to theta2:
```python
def describe_arc(cx: float, cy: float, radius: float, start_deg: float, end_deg: float) -> str:
    """Generate deterministic SVG path `d` string for a circular arc."""
    x1, y1 = polar_to_cartesian(cx, cy, radius, start_deg)
    x2, y2 = polar_to_cartesian(cx, cy, radius, end_deg)
    delta = (end_deg - start_deg) % 360.0
    large_arc_flag = 1 if delta > 180.0 else 0
    sweep_flag = 1  # Clockwise
    return f"M {x1} {y1} A {radius} {radius} 0 {large_arc_flag} {sweep_flag} {x2} {y2}"
```

### 2.3 Smooth Cubic Bezier Curve Interpolation
For a sequence of points P0, P1, ..., Pn, generate natural continuous curvature using Catmull-Rom to cubic Bezier control points:

```python
def catmull_rom_to_bezier(points: list[tuple[float, float]]) -> str:
    """Convert points to smooth cubic Bezier SVG path."""
    if len(points) < 2:
        return ""
    d = [f"M {points[0][0]} {points[0][1]}"]
    for i in range(len(points) - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, len(points) - 1)]

        cp1x = round(p1[0] + (p2[0] - p0[0]) / 6.0, 3)
        cp1y = round(p1[1] + (p2[1] - p0[1]) / 6.0, 3)
        cp2x = round(p2[0] - (p3[0] - p1[0]) / 6.0, 3)
        cp2y = round(p2[1] - (p3[1] - p1[1]) / 6.0, 3)
        d.append(f"C {cp1x} {cp1y}, {cp2x} {cp2y}, {p2[0]} {p2[1]}")
    return " ".join(d)
```

### 2.4 Isometric 3D Projection Matrix
Convert (x, y, z) 3D coordinates into 2D SVG canvas points under 30 degree isometric projection:

```python
COS_30 = math.sqrt(3) / 2.0  # 0.866025
SIN_30 = 0.5

def project_iso(cx: float, cy: float, x: float, y: float, z: float) -> tuple[float, float]:
    """Project 3D world coordinates (x, y, z) into 2D isometric SVG coordinates."""
    svg_x = round(cx + (x - y) * COS_30, 2)
    svg_y = round(cy + (x + y) * SIN_30 - z, 2)
    return svg_x, svg_y
```

---

## 3. High-Craft SVG Filter Architecture

### 3.1 Organic Micro-Texture Film Grain Filter
Eliminates gradient banding and adds tactile physical presence:
```xml
<filter id="fable-micro-grain" x="0%" y="0%" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency="0.75" numOctaves="3" result="noise" />
  <feColorMatrix type="matrix" values="
    1 0 0 0 0
    0 1 0 0 0
    0 0 1 0 0
    0 0 0 0.04 0" in="noise" result="grain" />
  <feBlend mode="overlay" in="SourceGraphic" in2="grain" />
</filter>
```

### 3.2 Hairline Specular Rim Light Filter
Creates precision edges on cards and containers:
```xml
<filter id="fable-specular-rim" x="-10%" y="-10%" width="120%" height="120%">
  <feDropShadow dx="0" dy="1" stdDeviation="0.5" flood-color="oklch(1 0 0 / 0.18)" result="rim" />
  <feDropShadow dx="0" dy="12" stdDeviation="16" flood-color="oklch(0 0 0 / 0.45)" result="ambient" />
  <feMerge>
    <feMergeNode in="ambient" />
    <feMergeNode in="rim" />
    <feMergeNode in="SourceGraphic" />
  </feMerge>
</filter>
```

---

## 4. Curated OKLCH Color Tokens for Vector Art

All gradients and strokes use calibrated OKLCH coordinates:

| Token Name | OKLCH Value | Visual Character & Semantic Use |
| :--- | :--- | :--- |
| `void-black` | `oklch(0.08 0.015 270)` | Deep obsidian canvas base |
| `surface-1` | `oklch(0.14 0.018 268)` | Card container fill |
| `stroke-hairline`| `oklch(1 0 0 / 0.12)` | 0.5px subtle structural rule |
| `stroke-active` | `oklch(0.75 0.18 215)` | Luminescent telemetry accent |
| `signal-cyan` | `oklch(0.82 0.19 195)` | Primary data vector / active node |
| `signal-emerald`| `oklch(0.78 0.18 145)` | Verified proof / invariant passed |
| `signal-amber` | `oklch(0.79 0.17 65)` | Caution / latency warning / timer |
| `signal-crimson`| `oklch(0.68 0.22 25)` | Verification failure / contradiction |
| `mono-dim` | `oklch(0.55 0.02 265)` | Subdued secondary axis and labels |

---

## 5. Complete Haute SVG Component Template (Interactive Telemetry Card)

```xml
<svg viewBox="0 0 600 380" width="100%" height="100%"
     xmlns="http://www.w3.org/2000/svg"
     style="background: oklch(0.08 0.015 270); border-radius: 12px; font-family: 'Geist Mono', monospace;"
     role="img" aria-label="Fable Telemetry Gauge">
  <defs>
    <!-- Procedural Grain -->
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" result="n"/>
      <feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0.035 0"/>
      <feBlend mode="overlay" in="SourceGraphic"/>
    </filter>

    <!-- Linear Gradient with OKLCH Falloff -->
    <linearGradient id="cyan-glow" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="oklch(0.85 0.22 195)"/>
      <stop offset="100%" stop-color="oklch(0.65 0.18 240)"/>
    </linearGradient>

    <linearGradient id="card-grad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="oklch(0.16 0.02 265 / 0.8)"/>
      <stop offset="100%" stop-color="oklch(0.11 0.01 270 / 0.8)"/>
    </linearGradient>
  </defs>

  <!-- Background Base with Micro-Grain -->
  <rect width="600" height="380" fill="oklch(0.08 0.015 270)" filter="url(#grain)" />

  <!-- Container Panel with Hairline Rim -->
  <rect x="24" y="24" width="552" height="332" rx="10"
        fill="url(#card-grad)"
        stroke="oklch(1 0 0 / 0.12)" stroke-width="1"
        style="backdrop-filter: blur(16px);" />

  <!-- Header & Telemetry Index -->
  <text x="48" y="60" fill="oklch(0.82 0.19 195)" font-size="11" letter-spacing="0.12em" font-weight="600">[01] // SYSTEM 3 COGNITIVE TELEMETRY</text>
  <text x="552" y="60" text-anchor="end" fill="oklch(0.55 0.02 265)" font-size="11" letter-spacing="0.06em">60.0 FPS • P99: 1.2ms</text>
  <line x1="48" y1="74" x2="552" y2="74" stroke="oklch(1 0 0 / 0.08)" stroke-width="0.5" />

  <!-- Circular Dial Arc (Pre-calculated: cx=140, cy=180, r=60, 240 deg arc) -->
  <path d="M 97.574 222.426 A 60 60 0 1 1 182.426 222.426"
        fill="none" stroke="oklch(1 0 0 / 0.10)" stroke-width="6" stroke-linecap="round" />
  <path d="M 97.574 222.426 A 60 60 0 1 1 170.0 128.038"
        fill="none" stroke="url(#cyan-glow)" stroke-width="6" stroke-linecap="round"
        stroke-dasharray="314" stroke-dashoffset="60" />
  
  <text x="140" y="176" text-anchor="middle" fill="oklch(0.96 0.005 90)" font-size="22" font-weight="700">99.4%</text>
  <text x="140" y="196" text-anchor="middle" fill="oklch(0.55 0.02 265)" font-size="10" letter-spacing="0.08em">EPISTEMIC CONF</text>

  <!-- Real-time Spline Graph (Catmull-Rom Interpolated) -->
  <g transform="translate(250, 110)">
    <!-- Grid Lines -->
    <line x1="0" y1="0" x2="280" y2="0" stroke="oklch(1 0 0 / 0.06)" stroke-width="0.5" />
    <line x1="0" y1="45" x2="280" y2="45" stroke="oklch(1 0 0 / 0.06)" stroke-width="0.5" stroke-dasharray="2 4" />
    <line x1="0" y1="90" x2="280" y2="90" stroke="oklch(1 0 0 / 0.06)" stroke-width="0.5" />
    <line x1="0" y1="135" x2="280" y2="135" stroke="oklch(1 0 0 / 0.08)" stroke-width="0.5" />

    <!-- Area Gradient Fill -->
    <path d="M 0 110 C 40 95, 70 120, 110 70 C 150 20, 190 85, 230 40 C 255 15, 270 30, 280 25 L 280 135 L 0 135 Z"
          fill="oklch(0.82 0.19 195 / 0.12)" />
    <!-- Spline Stroke -->
    <path d="M 0 110 C 40 95, 70 120, 110 70 C 150 20, 190 85, 230 40 C 255 15, 270 30, 280 25"
          fill="none" stroke="url(#cyan-glow)" stroke-width="2" stroke-linecap="round"
          vector-effect="non-scaling-stroke" />

    <!-- Telemetry Axis Labels -->
    <text x="0" y="152" fill="oklch(0.45 0.01 265)" font-size="9">T-60s</text>
    <text x="140" y="152" text-anchor="middle" fill="oklch(0.45 0.01 265)" font-size="9">T-30s</text>
    <text x="280" y="152" text-anchor="end" fill="oklch(0.82 0.19 195)" font-size="9">LIVE: -0.124 F</text>
  </g>

  <!-- Bottom Metric Badges -->
  <g transform="translate(48, 285)">
    <rect x="0" y="0" width="150" height="38" rx="6" fill="oklch(0.12 0.015 270)" stroke="oklch(1 0 0 / 0.08)" stroke-width="0.5" />
    <text x="14" y="18" fill="oklch(0.55 0.02 265)" font-size="9" letter-spacing="0.08em">VARIATIONAL F</text>
    <text x="14" y="31" fill="oklch(0.96 0.005 90)" font-size="12" font-weight="700">0.0312 nat</text>

    <rect x="170" y="0" width="160" height="38" rx="6" fill="oklch(0.12 0.015 270)" stroke="oklch(1 0 0 / 0.08)" stroke-width="0.5" />
    <text x="184" y="18" fill="oklch(0.55 0.02 265)" font-size="9" letter-spacing="0.08em">KRIPKE INVARIANT</text>
    <text x="184" y="31" fill="oklch(0.78 0.18 145)" font-size="12" font-weight="700">AG(safe) True</text>

    <rect x="350" y="0" width="154" height="38" rx="6" fill="oklch(0.12 0.015 270)" stroke="oklch(1 0 0 / 0.08)" stroke-width="0.5" />
    <text x="364" y="18" fill="oklch(0.55 0.02 265)" font-size="9" letter-spacing="0.08em">PARALLEL THREADS</text>
    <text x="364" y="31" fill="oklch(0.82 0.19 195)" font-size="12" font-weight="700">16 FLEET WORKERS</text>
  </g>
</svg>
```

---

## 6. Pre-Flight Anti-Slop Quality Gate Checklist

Before outputting or shipping any SVG asset:
- [ ] **Bounding Box Enclosure**: Ensure minimum and maximum coordinates lie strictly within declared `viewBox`.
- [ ] **Aspect Ratio Declaration**: Verify `preserveAspectRatio="xMidYMid meet"` (or explicit value) is present.
- [ ] **Vector Effect**: Ensure continuous hairline strokes specify `vector-effect="non-scaling-stroke"`.
- [ ] **Color Calibration**: Fills and strokes use `oklch(...)` color definitions rather than generic saturated RGB defaults.
- [ ] **Typography Grounding**: All text uses monospace/tabular or designated luxury typography with precise `letter-spacing` and `x`/`y` alignment.
- [ ] **Accessibility Attributes**: Asset includes `role="img"` and descriptive `<title>` / `<desc>` elements.