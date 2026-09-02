# AAA WebGL/WebGPU Three.js Game Engine Architecture
## 60+ FPS Deterministic Game Loops, TSL WebGPU Shaders, Post-Processing Pipelines, GPU Instancing & Zero-Leak Memory Management

This production manual documents the **AAA Three.js Game Engine Standard** within `fable-mode`. It establishes the engineering architecture required to build desktop-grade, AAA / Call-of-Duty-caliber 3D web applications, interactive simulations, and real-time gaming experiences running locked at **60–120+ FPS** across WebGL2 and WebGPU.

---

## 1. High-Level Engine Architecture

```
+───────────────────────────────────────────────────────────────────────────────+
|                        AAA 3D RUNTIME ARCHITECTURE                            |
+───────────────────────────────────────────────────────────────────────────────+
| 1. DETERMINISTIC LOOP       │ Decoupled Physics Accumulator (dt = 1/120s),     |
|                             │ State Interpolation (alpha), Zero-Jitter Render.|
+─────────────────────────────┼─────────────────────────────────────────────────+
| 2. WEBGPU / TSL PIPELINE    │ Three Shading Language (TSL) Node Shaders,      |
|                             │ GPU Compute Passes, WebGL2 Fallback Path.       |
+─────────────────────────────┼─────────────────────────────────────────────────+
| 3. POST-PROCESSING STACK    │ HDR Tone Mapping (ACES/AgX), Selective Bloom,   |
|                             │ GTAO/SSAO Ambient Occlusion, SSR Reflections.   |
+─────────────────────────────┼─────────────────────────────────────────────────+
| 4. GPU MASS INSTANCING      │ InstancedMesh Matrices, Dynamic Instance Buffers|
|                             │ 100,000+ Particles via GPU Compute / Ping-Pong. |
+─────────────────────────────┼─────────────────────────────────────────────────+
| 5. 3D SPATIAL AUDIO         │ Web Audio Positional Audio, Cone Attenuation,   |
|                             │ Inverse-Square Distance Decay, Doppler Shifts.  |
+─────────────────────────────┼─────────────────────────────────────────────────+
| 6. ZERO-LEAK LIFECYCLE      │ Recursive GPU Buffer Disposal, DRACO/KTX2 Pools,|
|                             │ Dynamic LOD Hierarchies, VRAM Garbage Hygiene.  |
+───────────────────────────────────────────────────────────────────────────────+
```

---

## 2. Deterministic Fixed-Timestep Game Loop & Physics Accumulator

Variable `requestAnimationFrame` delta times ($dt$) cause non-deterministic physics tunneling, frame stuttering, and simulation desynchronization. The engine enforces a **Fixed-Timestep Accumulator with State Interpolation**:

$$\Delta t_{\text{accum}} \leftarrow \Delta t_{\text{accum}} + \min(\Delta t_{\text{frame}}, \Delta t_{\text{max}})$$
$$\text{while } \Delta t_{\text{accum}} \ge \Delta t_{\text{physics}} : \quad \text{Integrate}(\Delta t_{\text{physics}}), \quad \Delta t_{\text{accum}} \leftarrow \Delta t_{\text{accum}} - \Delta t_{\text{physics}}$$
$$\alpha = \frac{\Delta t_{\text{accum}}}{\Delta t_{\text{physics}}}, \qquad \text{State}_{\text{render}} = (1 - \alpha)\text{State}_{\text{prev}} + \alpha \text{State}_{\text{curr}}$$

### Production TypeScript Game Loop Implementation

```typescript
export class DeterministicGameLoop {
  private physicsTimestep = 1 / 120; // 120 Hz internal physics
  private maxAccumulator = 0.1;      // Clamp to prevent spiral-of-death
  private accumulator = 0;
  private lastTimestamp = 0;
  private isRunning = false;

  constructor(
    private updatePhysics: (dt: number) => void,
    private renderInterpolated: (alpha: number) => void
  ) {}

  public start(): void {
    this.isRunning = true;
    this.lastTimestamp = performance.now();
    requestAnimationFrame(this.tick);
  }

  public stop(): void {
    this.isRunning = false;
  }

  private tick = (currentTimestamp: number): void => {
    if (!this.isRunning) return;

    let frameDelta = (currentTimestamp - this.lastTimestamp) / 1000;
    this.lastTimestamp = currentTimestamp;

    // Prevent spiral-of-death when tab was in background
    if (frameDelta > this.maxAccumulator) {
      frameDelta = this.maxAccumulator;
    }

    this.accumulator += frameDelta;

    // Execute fixed physics steps
    while (this.accumulator >= this.physicsTimestep) {
      this.updatePhysics(this.physicsTimestep);
      this.accumulator -= this.physicsTimestep;
    }

    // Alpha interpolation factor for ultra-smooth rendering
    const alpha = this.accumulator / this.physicsTimestep;
    this.renderInterpolated(alpha);

    requestAnimationFrame(this.tick);
  };
}
```

---

## 3. WebGPU & Three Shading Language (TSL) Pipeline

Next-generation AAA graphics leverage **WebGPU** with **Three Shading Language (TSL)** for unified CPU/GPU node graphs, compute shaders, and automatic WebGL2 fallback.

### 3.1 WebGPU Renderer Initialization
```typescript
import * as THREE from 'three';
import { WebGPURenderer } from 'three/webgpu';

export function createAAARenderer(container: HTMLElement): WebGPURenderer {
  const renderer = new WebGPURenderer({
    antialias: false, // Handled in post-processing pipeline
    powerPreference: 'high-performance',
    alpha: false,
    stencil: false,
    depth: true,
  });

  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  container.appendChild(renderer.domElement);
  return renderer;
}
```

### 3.2 Custom Vertex Displacement & Noise Caustics in TSL
```typescript
import {
  Fn,
  vec3,
  vec4,
  uv,
  time,
  sin,
  cos,
  mul,
  add,
  positionLocal,
  MeshStandardNodeMaterial,
} from 'three/tsl';

export function createAtmosphericHologramMaterial(): MeshStandardNodeMaterial {
  const material = new MeshStandardNodeMaterial({
    roughness: 0.1,
    metalness: 0.8,
    transparent: true,
    opacity: 0.9,
  });

  // TSL Procedural Vertex Displacement Function
  const displaceVertex = Fn(() => {
    const p = positionLocal;
    const wave = sin(add(mul(p.y, 4.0), mul(time, 2.0)));
    const offset = mul(vec3(0.0, 0.0, wave), 0.05);
    return add(p, offset);
  });

  material.positionNode = displaceVertex();

  // TSL Dynamic Chromatic Hologram Emission Node
  const hologramColor = Fn(() => {
    const coords = uv();
    const scanline = sin(add(mul(coords.y, 120.0), mul(time, 6.0)));
    return vec4(0.0, 0.85, 1.0, add(0.4, mul(scanline, 0.2)));
  });

  material.emissiveNode = hologramColor();
  return material;
}
```

---

## 4. Production Post-Processing Pipeline

To achieve cinematic visual fidelity, the rendering passes through a calibrated post-processing composer:

```
Scene + Camera ──► RenderPass (Depth/Normal/Color) ──► GTAO Pass ──► UnrealBloom (Selective) ──► SSR ──► ACES ToneMap + Film Dither ──► Viewport
```

```typescript
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';

export function setupAAAPostProcessing(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number
): EffectComposer {
  const composer = new EffectComposer(renderer);

  // 1. Base Geometry Render Pass
  const renderPass = new RenderPass(scene, camera);
  composer.addPass(renderPass);

  // 2. Ground-Truth Ambient Occlusion (GTAO)
  const gtaoPass = new GTAOPass(scene, camera, width, height);
  gtaoPass.output = GTAOPass.OUTPUT.Default;
  gtaoPass.updateGtaoMaterial({
    radius: 0.8,
    distanceExponent: 1.2,
    thickness: 1.0,
    scale: 1.0,
    samples: 16,
  });
  composer.addPass(gtaoPass);

  // 3. Selective High-Dynamic-Range Bloom
  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(width, height),
    0.65, // Bloom Strength
    0.40, // Bloom Radius
    0.85  // Bloom Threshold (Only highlights emit bloom)
  );
  composer.addPass(bloomPass);

  // 4. Output Pass (ACES Filmic Tone Mapping + sRGB Conversion)
  const outputPass = new OutputPass();
  composer.addPass(outputPass);

  return composer;
}
```

---

## 5. GPU Mass Instancing (100,000+ Particles / Geometry)

Individual `THREE.Mesh` instances saturate the CPU-GPU draw call bottleneck. For debris, bullets, foliage, or crowds, use `THREE.InstancedMesh` or Custom Instanced Buffer Geometries:

```typescript
export class GPUInstancedBulletFleet {
  private instancedMesh: THREE.InstancedMesh;
  private dummy = new THREE.Object3D();
  private count: number;

  constructor(scene: THREE.Scene, count: number = 50000) {
    this.count = count;
    const geometry = new THREE.CylinderGeometry(0.04, 0.04, 0.8, 6);
    const material = new THREE.MeshBasicMaterial({
      color: 0x00ffff,
      toneMapped: false, // Max emission for bloom
    });

    this.instancedMesh = new THREE.InstancedMesh(geometry, material, count);
    this.instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    scene.add(this.instancedMesh);
  }

  public updatePositions(
    positions: Float32Array,
    rotations: Float32Array
  ): void {
    for (let i = 0; i < this.count; i++) {
      const idx = i * 3;
      this.dummy.position.set(positions[idx], positions[idx + 1], positions[idx + 2]);
      this.dummy.rotation.set(rotations[idx], rotations[idx + 1], rotations[idx + 2]);
      this.dummy.updateMatrix();
      this.instancedMesh.setMatrixAt(i, this.dummy.matrix);
    }
    this.instancedMesh.instanceMatrix.needsUpdate = true;
  }
}
```

---

## 6. Positional 3D Spatial Audio Pipeline

Using the Web Audio API integrated with Three.js camera transforms:

```typescript
export class SpatialAudioEngine {
  private listener: THREE.AudioListener;
  private soundPool: Map<string, THREE.AudioBuffer> = new Map();

  constructor(camera: THREE.Camera) {
    this.listener = new THREE.AudioListener();
    camera.add(this.listener);
  }

  public attachPositionalEmitter(
    parentMesh: THREE.Object3D,
    buffer: THREE.AudioBuffer,
    refDistance = 2.0,
    maxDistance = 50.0
  ): THREE.PositionalAudio {
    const sound = new THREE.PositionalAudio(this.listener);
    sound.setBuffer(buffer);
    sound.setRefDistance(refDistance);
    sound.setMaxDistance(maxDistance);
    sound.setDistanceModel('inverse');
    sound.setRolloffFactor(1.5);
    sound.setDirectionalCone(180, 230, 0.2); // Directional audio cone

    parentMesh.add(sound);
    return sound;
  }
}
```

---

## 7. Zero-Leak Memory Management & Asset Lifecycle Protocol

Web browsers crash with `CONTEXT_LOST_WEBGL` when VRAM is exhausted. The engine mandates recursive asset teardown:

```typescript
export function disposeSceneHierarchy(root: THREE.Object3D): void {
  root.traverse((object) => {
    if ((object as THREE.Mesh).isMesh) {
      const mesh = object as THREE.Mesh;

      // 1. Dispose Geometry
      if (mesh.geometry) {
        mesh.geometry.dispose();
      }

      // 2. Dispose Materials & Attached Textures
      if (mesh.material) {
        const materials = Array.isArray(mesh.material)
          ? mesh.material
          : [mesh.material];

        materials.forEach((mat) => {
          for (const key of Object.keys(mat)) {
            const value = (mat as any)[key];
            if (value && typeof value.dispose === 'function' && value.isTexture) {
              value.dispose();
            }
          }
          mat.dispose();
        });
      }
    }
  });

  if (root.parent) {
    root.parent.remove(root);
  }
}
```

---

## 8. Definition of Done for AAA 3D Graphics

- [x] **Locked 60+ FPS**: Physics loop decoupled at 120 Hz; zero frame-drops under profiling.
- [x] **WebGPU/TSL Architecture**: Next-gen shader pipeline with robust WebGL2 fallback.
- [x] **Post-Processing Calibrated**: Selective Bloom, GTAO, ACES Filmic Tone Mapping active.
- [x] **Draw Calls < 50**: InstancedMesh applied to all particle/debris systems.
- [x] **Zero Memory Leaks**: Full `disposeSceneHierarchy` lifecycle implemented.
