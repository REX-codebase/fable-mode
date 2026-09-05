---
name: design_3d
description: Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
domain: design_3d
activation_count: 16
synaptic_weights:
  webgpu_tsl: 0.95
  spring_motion_physics: 0.9
  fluid_typography: 0.88
  render_vector: 0.93
  perceptual_diff: 0.89
  fps_budget_profiler: 0.92
antibodies:
- antibody_id: ab_design_threejs_memory_leak
  domain: design_3d
  trigger_condition: Removing Three.js meshes from scene graph without recursively
    disposing geometry, materials, and textures
  lethal_anti_pattern: 'scene.remove(mesh); # Leaves GPU buffers and VRAM allocations
    leaked indefinitely'
  prescribed_defense: Implement recursive traversal disposing mesh.geometry.dispose(),
    material.dispose(), and texture.dispose() before nullifying references.
  severity: CRITICAL
  source_task_id: task_threejs_vram_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: WebGL renderer memory tracker confirmed 0 active geometries/textures
    after teardown
- antibody_id: ab_design_animation_loop_gc_freeze
  domain: design_3d
  trigger_condition: Instantiating new Vector3 or Color objects inside animate() render
    callback
  lethal_anti_pattern: function animate() { const pos = new THREE.Vector3(); mesh.position.copy(pos);
    }
  prescribed_defense: Pre-allocate scratch variables in file/class closure scope outside
    animate loop.
  severity: HIGH
  source_task_id: task_webgl_fps_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Frame profiler confirmed zero GC pause pauses > 1.2ms over
    60 seconds
- antibody_id: ab_design_unconstrained_canvas_cls
  domain: design_3d
  trigger_condition: Embedding WebGL canvas without explicit aspect-ratio or CSS width/height
    container constraints
  lethal_anti_pattern: <canvas id='webgl'></canvas> with dynamic JS resize causing
    Cumulative Layout Shift (CLS > 0.25)
  prescribed_defense: 'Wrap in fixed aspect-ratio container with CSS contain: strict
    and pre-sized dimensions.'
  severity: MEDIUM
  source_task_id: task_web_vitals_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Lighthouse audit confirmed CLS = 0.00 across mobile and
    desktop viewports
specialized_heuristics:
- 'Three.js / WebGPU Standards: Prefer Three Shading Language (TSL) node shaders and
  WebGPURenderer over legacy raw WebGL1 strings; verify hardware fallback.'
- 'Deterministic Physics Accumulator: Decouple render tick from physics loop using
  fixed 120Hz accumulator with alpha interpolation to eliminate frame jitter.'
- 'Fluid Typography Math: Use CSS clamp with golden ratio step factors clamp(1.25rem,
  2.5vw + 0.5rem, 3.5rem) to ensure zero layout shift across viewports.'
- 'Newtonian Spring Motion: Animate interactive states using spring physics parameters
  (stiffness k=170, damping c=26, mass m=1.0) rather than abrupt cubic-bezier presets.'
- 'Locked 60/120 FPS Budget: Zero heap allocation in requestAnimationFrame render
  loops; preallocate Vector3/Matrix4 scratch instances.'
last_consolidated_at: '2026-09-04T12:00:00+00:00'
---

# Cortical Lobe: `design_3d`

> [!NOTE]
> Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
> Activation count: 16.

## Metadata & Telemetry
- **Name**: `design_3d`
- **Description**: Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
- **Domain**: `design_3d`
- **Activation Count**: `16`
- **Total Antibodies**: `3`
- **Specialized Heuristics**: `5`
- **Last Consolidated**: `2026-09-04T12:00:00+00:00`

## Specialized Domain Heuristics
1. Three.js / WebGPU Standards: Prefer Three Shading Language (TSL) node shaders and WebGPURenderer over legacy raw WebGL1 strings; verify hardware fallback.
2. Deterministic Physics Accumulator: Decouple render tick from physics loop using fixed 120Hz accumulator with alpha interpolation to eliminate frame jitter.
3. Fluid Typography Math: Use CSS clamp with golden ratio step factors clamp(1.25rem, 2.5vw + 0.5rem, 3.5rem) to ensure zero layout shift across viewports.
4. Newtonian Spring Motion: Animate interactive states using spring physics parameters (stiffness k=170, damping c=26, mass m=1.0) rather than abrupt cubic-bezier presets.
5. Locked 60/120 FPS Budget: Zero heap allocation in requestAnimationFrame render loops; preallocate Vector3/Matrix4 scratch instances.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `webgpu_tsl` | `0.9500` | 🟢 Strong |
| `render_vector` | `0.9300` | 🟢 Strong |
| `fps_budget_profiler` | `0.9200` | 🟢 Strong |
| `spring_motion_physics` | `0.9000` | 🟢 Strong |
| `perceptual_diff` | `0.8900` | 🟢 Strong |
| `fluid_typography` | `0.8800` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_design_threejs_memory_leak` [CRITICAL]
- **Domain**: `design_3d`
- **Trigger Condition**: Removing Three.js meshes from scene graph without recursively disposing geometry, materials, and textures
- **Lethal Anti-Pattern**: scene.remove(mesh); # Leaves GPU buffers and VRAM allocations leaked indefinitely
- **Prescribed Defense**: Implement recursive traversal disposing mesh.geometry.dispose(), material.dispose(), and texture.dispose() before nullifying references.
- **Verified Counterfactual**: `WebGL renderer memory tracker confirmed 0 active geometries/textures after teardown`
- **Source Task ID**: `task_threejs_vram_audit`

#### Antibody `ab_design_animation_loop_gc_freeze` [HIGH]
- **Domain**: `design_3d`
- **Trigger Condition**: Instantiating new Vector3 or Color objects inside animate() render callback
- **Lethal Anti-Pattern**: function animate() { const pos = new THREE.Vector3(); mesh.position.copy(pos); }
- **Prescribed Defense**: Pre-allocate scratch variables in file/class closure scope outside animate loop.
- **Verified Counterfactual**: `Frame profiler confirmed zero GC pause pauses > 1.2ms over 60 seconds`
- **Source Task ID**: `task_webgl_fps_audit`

#### Antibody `ab_design_unconstrained_canvas_cls` [MEDIUM]
- **Domain**: `design_3d`
- **Trigger Condition**: Embedding WebGL canvas without explicit aspect-ratio or CSS width/height container constraints
- **Lethal Anti-Pattern**: <canvas id='webgl'></canvas> with dynamic JS resize causing Cumulative Layout Shift (CLS > 0.25)
- **Prescribed Defense**: Wrap in fixed aspect-ratio container with CSS contain: strict and pre-sized dimensions.
- **Verified Counterfactual**: `Lighthouse audit confirmed CLS = 0.00 across mobile and desktop viewports`
- **Source Task ID**: `task_web_vitals_audit`

