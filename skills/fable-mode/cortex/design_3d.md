---
name: design_3d
description: Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
domain: design_3d
activation_count: 18
synaptic_weights:
  webgpu_tsl: 0.95
  spring_motion_physics: 0.9
  fluid_typography: 0.88
  render_vector: 0.95
  perceptual_diff: 0.92
  fps_budget_profiler: 0.92
  run_command: 0.9
  ast_diagnostics: 0.88
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
- antibody_id: ab_design_threejs_black_screen_void
  domain: design_3d
  trigger_condition: Instantiating MeshStandardMaterial or MeshPhysicalMaterial without
    light sources or unpositioned camera
  lethal_anti_pattern: const mat = new THREE.MeshStandardMaterial(); const cam = new
    THREE.PerspectiveCamera(); // cam at 0,0,0 with no lights
  prescribed_defense: Enforce mandatory baseline AmbientLight(0.6) + DirectionalLight(1.8)
    and place camera outside bounding volume.
  severity: CRITICAL
  source_task_id: task_threejs_grounding_audit
  created_at: '2026-09-05T12:00:00+00:00'
  verified_counterfactual: Scene luminance probe confirmed non-zero RGB pixel readings
    and visible meshes across viewports
- antibody_id: ab_design_threejs_backend_composer_collision
  domain: design_3d
  trigger_condition: Passing WebGPURenderer into legacy EffectComposer
  lethal_anti_pattern: const renderer = new WebGPURenderer(); const composer = new
    EffectComposer(renderer);
  prescribed_defense: Use WebGLRenderer with EffectComposer; use WebGPURenderer (awaited
    .init()) with PostProcessing from 'three/webgpu'. Never cross backends.
  severity: CRITICAL
  source_task_id: task_threejs_backend_audit
  created_at: '2026-09-05T12:00:00+00:00'
  verified_counterfactual: Zero TypeError getContext crashes in node-based postprocessing
    and webgl tests
- antibody_id: ab_design_threejs_r3f_state_render_loop
  domain: design_3d
  trigger_condition: Calling useState or parent state dispatch inside useFrame()
  lethal_anti_pattern: useFrame(() => { setRotation(r => r + 0.01); });
  prescribed_defense: 'Mutate object ref directly: useFrame((_, delta) => { ref.current.rotation.y
    += delta; })'
  severity: HIGH
  source_task_id: task_r3f_render_audit
  created_at: '2026-09-05T12:00:00+00:00'
  verified_counterfactual: React render profiler verified 60 FPS locked with zero
    component re-renders during animation
- antibody_id: ab_design_threejs_texture_colorspace_distortion
  domain: design_3d
  trigger_condition: Assigning THREE.SRGBColorSpace to data textures (normal, roughness,
    metalness, ao) or failing to set SRGBColorSpace on diffuse maps
  lethal_anti_pattern: normalTexture.colorSpace = THREE.SRGBColorSpace;
  prescribed_defense: Diffuse maps MUST be THREE.SRGBColorSpace; normal/roughness/metalness/ao
    maps MUST be THREE.NoColorSpace.
  severity: HIGH
  source_task_id: task_pbr_colorspace_audit
  created_at: '2026-09-05T12:00:00+00:00'
  verified_counterfactual: Visual difference analyzer confirmed accurate PBR reflectance
    and normal perturbation without gamma warping
- antibody_id: ab_design_threejs_hypertrophic_overkill
  domain: design_3d
  trigger_condition: Implementing a 120Hz physics accumulator, post-processing composer,
    or instanced fleet for simple ambient UI, hero badges, or decorative 3D cards
  lethal_anti_pattern: 'const loop = new DeterministicGameLoop(updatePhysics, render);
    const composer = new EffectComposer(renderer); # Hypertrophic overkill for simple
    hero badge'
  prescribed_defense: Enforce Tier 1 Ambient UI profile (< 15 draw calls, MatCap/simple
    PBR, zero physics accumulators, no post-processing).
  severity: HIGH
  source_task_id: task_threejs_triage_audit
  created_at: '2026-09-05T12:00:00+00:00'
  verified_counterfactual: Profiler confirmed < 25MB VRAM and 60 FPS with zero accumulator
    overhead on ambient UI components
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
- 'Three.js Dual-Backend Standard: Use WebGL2 for universal stability with EffectComposer;
  use WebGPURenderer with await renderer.init() and TSL PostProcessing for next-gen
  features. Never mix backends.'
- 'Mandatory Scene Grounding Contract: Never render PBR materials without AmbientLight
  + DirectionalLight; always place camera outside object bounds and attach ResizeObserver.'
- 'React Three Fiber (R3F) Direct Mutation: Never call useState inside useFrame();
  mutate object refs directly. Wrap async loaders (useGLTF) in <Suspense>.'
- 'Strict Color Space Separation: Set SRGBColorSpace on diffuse/color textures; set
  NoColorSpace on normal/roughness/metalness/AO textures.'
- 'Universal Recursive Teardown: Recursively dispose all geometries, texture slots,
  buffer attributes, and call renderer.forceContextLoss().'
- '3D Complexity Triage: Classify task into Tier 1 (Ambient UI), Tier 2 (Configurator/HUD),
  or Tier 3 (Real-Time Game) before coding; never apply Tier 3 game-engine loops to
  Tier 1 decorative widgets.'
last_consolidated_at: '2026-09-05T12:00:00+00:00'
---

# Cortical Lobe: `design_3d`

> [!NOTE]
> Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
> Activation count: 18.

## Metadata & Telemetry
- **Name**: `design_3d`
- **Description**: Haute aesthetics, WebGPU TSL shaders, and responsive UI motion
- **Domain**: `design_3d`
- **Activation Count**: `18`
- **Total Antibodies**: `8`
- **Specialized Heuristics**: `11`
- **Last Consolidated**: `2026-09-05T12:00:00+00:00`

## Specialized Domain Heuristics
1. Three.js / WebGPU Standards: Prefer Three Shading Language (TSL) node shaders and WebGPURenderer over legacy raw WebGL1 strings; verify hardware fallback.
2. Deterministic Physics Accumulator: Decouple render tick from physics loop using fixed 120Hz accumulator with alpha interpolation to eliminate frame jitter.
3. Fluid Typography Math: Use CSS clamp with golden ratio step factors clamp(1.25rem, 2.5vw + 0.5rem, 3.5rem) to ensure zero layout shift across viewports.
4. Newtonian Spring Motion: Animate interactive states using spring physics parameters (stiffness k=170, damping c=26, mass m=1.0) rather than abrupt cubic-bezier presets.
5. Locked 60/120 FPS Budget: Zero heap allocation in requestAnimationFrame render loops; preallocate Vector3/Matrix4 scratch instances.
6. Three.js Dual-Backend Standard: Use WebGL2 for universal stability with EffectComposer; use WebGPURenderer with await renderer.init() and TSL PostProcessing for next-gen features. Never mix backends.
7. Mandatory Scene Grounding Contract: Never render PBR materials without AmbientLight + DirectionalLight; always place camera outside object bounds and attach ResizeObserver.
8. React Three Fiber (R3F) Direct Mutation: Never call useState inside useFrame(); mutate object refs directly. Wrap async loaders (useGLTF) in <Suspense>.
9. Strict Color Space Separation: Set SRGBColorSpace on diffuse/color textures; set NoColorSpace on normal/roughness/metalness/AO textures.
10. Universal Recursive Teardown: Recursively dispose all geometries, texture slots, buffer attributes, and call renderer.forceContextLoss().
11. 3D Complexity Triage: Classify task into Tier 1 (Ambient UI), Tier 2 (Configurator/HUD), or Tier 3 (Real-Time Game) before coding; never apply Tier 3 game-engine loops to Tier 1 decorative widgets.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `webgpu_tsl` | `0.9500` | 🟢 Strong |
| `render_vector` | `0.9500` | 🟢 Strong |
| `perceptual_diff` | `0.9200` | 🟢 Strong |
| `fps_budget_profiler` | `0.9200` | 🟢 Strong |
| `spring_motion_physics` | `0.9000` | 🟢 Strong |
| `run_command` | `0.9000` | 🟢 Strong |
| `fluid_typography` | `0.8800` | 🟢 Strong |
| `ast_diagnostics` | `0.8800` | 🟢 Strong |

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

#### Antibody `ab_design_threejs_black_screen_void` [CRITICAL]
- **Domain**: `design_3d`
- **Trigger Condition**: Instantiating MeshStandardMaterial or MeshPhysicalMaterial without light sources or unpositioned camera
- **Lethal Anti-Pattern**: const mat = new THREE.MeshStandardMaterial(); const cam = new THREE.PerspectiveCamera(); // cam at 0,0,0 with no lights
- **Prescribed Defense**: Enforce mandatory baseline AmbientLight(0.6) + DirectionalLight(1.8) and place camera outside bounding volume.
- **Verified Counterfactual**: `Scene luminance probe confirmed non-zero RGB pixel readings and visible meshes across viewports`
- **Source Task ID**: `task_threejs_grounding_audit`

#### Antibody `ab_design_threejs_backend_composer_collision` [CRITICAL]
- **Domain**: `design_3d`
- **Trigger Condition**: Passing WebGPURenderer into legacy EffectComposer
- **Lethal Anti-Pattern**: const renderer = new WebGPURenderer(); const composer = new EffectComposer(renderer);
- **Prescribed Defense**: Use WebGLRenderer with EffectComposer; use WebGPURenderer (awaited .init()) with PostProcessing from 'three/webgpu'. Never cross backends.
- **Verified Counterfactual**: `Zero TypeError getContext crashes in node-based postprocessing and webgl tests`
- **Source Task ID**: `task_threejs_backend_audit`

#### Antibody `ab_design_threejs_r3f_state_render_loop` [HIGH]
- **Domain**: `design_3d`
- **Trigger Condition**: Calling useState or parent state dispatch inside useFrame()
- **Lethal Anti-Pattern**: useFrame(() => { setRotation(r => r + 0.01); });
- **Prescribed Defense**: Mutate object ref directly: useFrame((_, delta) => { ref.current.rotation.y += delta; })
- **Verified Counterfactual**: `React render profiler verified 60 FPS locked with zero component re-renders during animation`
- **Source Task ID**: `task_r3f_render_audit`

#### Antibody `ab_design_threejs_texture_colorspace_distortion` [HIGH]
- **Domain**: `design_3d`
- **Trigger Condition**: Assigning THREE.SRGBColorSpace to data textures (normal, roughness, metalness, ao) or failing to set SRGBColorSpace on diffuse maps
- **Lethal Anti-Pattern**: normalTexture.colorSpace = THREE.SRGBColorSpace;
- **Prescribed Defense**: Diffuse maps MUST be THREE.SRGBColorSpace; normal/roughness/metalness/ao maps MUST be THREE.NoColorSpace.
- **Verified Counterfactual**: `Visual difference analyzer confirmed accurate PBR reflectance and normal perturbation without gamma warping`
- **Source Task ID**: `task_pbr_colorspace_audit`

#### Antibody `ab_design_threejs_hypertrophic_overkill` [HIGH]
- **Domain**: `design_3d`
- **Trigger Condition**: Implementing a 120Hz physics accumulator, post-processing composer, or instanced fleet for simple ambient UI, hero badges, or decorative 3D cards
- **Lethal Anti-Pattern**: const loop = new DeterministicGameLoop(updatePhysics, render); const composer = new EffectComposer(renderer); // Hypertrophic overkill for simple hero badge
- **Prescribed Defense**: Enforce Tier 1 Ambient UI profile (< 15 draw calls, MatCap/simple PBR, zero physics accumulators, no post-processing).
- **Verified Counterfactual**: `Profiler confirmed < 25MB VRAM and 60 FPS with zero accumulator overhead on ambient UI components`
- **Source Task ID**: `task_threejs_triage_audit`

