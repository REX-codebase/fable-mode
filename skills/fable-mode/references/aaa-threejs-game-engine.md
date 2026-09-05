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

## 3. Production Renderer Architectures: WebGL2 vs WebGPU

To achieve bulletproof stability across all browsers, mobile devices, and automated CI testbeds while unlocking next-generation graphics, the engine defines two cleanly separated, isolated renderer pipelines. **Never cross or mix WebGL and WebGPU pipelines in the same context.**

### 3.1 Universal Production WebGL2 Standard (Recommended for 100% Cross-Browser & CI Compatibility)

The WebGL2 standard is the default production workhorse. It guarantees 100% cross-browser compatibility, headless testability, and seamless post-processing via `EffectComposer`.

```typescript
import * as THREE from 'three';

export interface WebGLSceneSetup {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  cleanup: () => void;
}

export function createUniversalWebGLRenderer(container: HTMLElement): WebGLSceneSetup {
  // 1. Resilient dimension fallbacks (prevents 0x0 canvas collapse)
  const width = container.clientWidth || window.innerWidth || 800;
  const height = container.clientHeight || window.innerHeight || 600;

  // 2. Perspective Camera placed at standard framing coordinates
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 3, 8);
  camera.lookAt(0, 0, 0);

  // 3. Scene Graph
  const scene = new THREE.Scene();

  // 4. High-Performance WebGL2 Renderer
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    powerPreference: 'high-performance',
    alpha: false,
    stencil: false,
    depth: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
  renderer.setSize(width, height);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  container.appendChild(renderer.domElement);

  // 5. Mandatory PBR Baseline Lighting (Eliminates Black-Screen Void)
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.8);
  dirLight.position.set(5, 10, 7);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  dirLight.shadow.camera.near = 0.5;
  dirLight.shadow.camera.far = 50;
  dirLight.shadow.bias = -0.0001;
  scene.add(dirLight);

  // 6. Dynamic ResizeObserver for responsive viewports
  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const newWidth = entry.contentRect.width || container.clientWidth || window.innerWidth;
      const newHeight = entry.contentRect.height || container.clientHeight || window.innerHeight;
      if (newWidth === 0 || newHeight === 0) return;

      camera.aspect = newWidth / newHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(newWidth, newHeight);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
    }
  });
  resizeObserver.observe(container);

  return {
    renderer,
    scene,
    camera,
    cleanup: () => {
      resizeObserver.disconnect();
    },
  };
}
```

### 3.2 Next-Gen WebGPU & Three Shading Language (TSL) Pipeline

Next-generation AAA graphics leverage **WebGPU** with **Three Shading Language (TSL)** for unified CPU/GPU node graphs, compute shaders, and modern GPU pipelines.

> [!CAUTION]
> **WebGPU Initialization & Composer Invariants**:
> 1. `WebGPURenderer` requires **asynchronous initialization**: you MUST call `await renderer.init()` before rendering any frames or allocating buffers.
> 2. `EffectComposer` from `three/examples/jsm/postprocessing/EffectComposer.js` is built strictly for WebGL and **CANNOT be used with `WebGPURenderer`**. Attempting to pass `WebGPURenderer` into `EffectComposer` triggers fatal runtime crashes (`TypeError: renderer.getContext is not a function`). WebGPU post-processing must exclusively use node-based post processing (`PostProcessing` from `'three/webgpu'`). Never cross backends!

```typescript
import * as THREE from 'three';
import { WebGPURenderer } from 'three/webgpu';
import {
  Fn,
  vec3,
  vec4,
  uv,
  time,
  sin,
  mul,
  add,
  positionLocal,
  MeshStandardNodeMaterial,
} from 'three/tsl';

export async function createWebGPURenderer(
  container: HTMLElement
): Promise<{ renderer: WebGPURenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; cleanup: () => void }> {
  const width = container.clientWidth || window.innerWidth || 800;
  const height = container.clientHeight || window.innerHeight || 600;

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(0, 3, 8);
  camera.lookAt(0, 0, 0);

  const scene = new THREE.Scene();

  const renderer = new WebGPURenderer({
    antialias: false, // Handled in WebGPU post-processing node graph or MSAA
    powerPreference: 'high-performance',
    alpha: false,
    stencil: false,
    depth: true,
  });

  // MANDATORY: WebGPURenderer requires asynchronous initialization!
  await renderer.init();

  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
  renderer.setSize(width, height);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  container.appendChild(renderer.domElement);

  // Mandatory baseline lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.8);
  dirLight.position.set(5, 10, 7);
  dirLight.castShadow = true;
  scene.add(dirLight);

  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const newWidth = entry.contentRect.width || container.clientWidth;
      const newHeight = entry.contentRect.height || container.clientHeight;
      if (newWidth === 0 || newHeight === 0) return;

      camera.aspect = newWidth / newHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(newWidth, newHeight);
    }
  });
  resizeObserver.observe(container);

  return {
    renderer,
    scene,
    camera,
    cleanup: () => resizeObserver.disconnect(),
  };
}

/**
 * Procedural TSL Material Example
 * Demonstrates node-based vertex displacement and dynamic chromatic emission.
 */
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

## 4. Production Post-Processing Pipelines: WebGL2 vs WebGPU

To achieve cinematic visual fidelity, rendering passes through post-processing stacks calibrated specifically to the graphics backend:

```
WebGL2: Scene + Camera ──► RenderPass ──► GTAOPass ──► UnrealBloomPass ──► OutputPass ──► Canvas
WebGPU: Scene + Camera ──► pass() node ──► bloom() node ──► composite outputNode ──► Canvas
```

### 4.1 WebGL2 EffectComposer Pipeline

In WebGL2, post-processing is managed sequentially via `EffectComposer`.

```typescript
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';

export function setupWebGLPostProcessing(
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

  // 2. Ground-Truth Ambient Occlusion (GTAO) Pass
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

  // 4. OutputPass (Mandatory Final Pass)
  // CRITICAL: OutputPass is the modern Three.js standard replacing CopyShader/ShaderPass.
  // It handles linear-to-sRGB color space conversion and applies ACESFilmic tone mapping
  // directly on the composer's render target. Without OutputPass at the end of the composer chain,
  // renders will appear dull, washed out, or have crushed gamma curves.
  const outputPass = new OutputPass();
  composer.addPass(outputPass);

  return composer;
}
```

### 4.2 WebGPU Node Post-Processing Pipeline

In WebGPU, traditional passes are replaced with **TSL node-based composition** using `PostProcessing` from `'three/webgpu'`.

> [!IMPORTANT]
> In WebGPU loops, invoke `postProcessing.render()` instead of `renderer.render(scene, camera)`.

```typescript
import * as THREE from 'three';
import { PostProcessing } from 'three/webgpu';
import { pass } from 'three/tsl';
import { bloom } from 'three/addons/tsl/display/bloom.js';

export function setupWebGPUPostProcessing(
  renderer: any, // WebGPURenderer
  scene: THREE.Scene,
  camera: THREE.PerspectiveCamera
): PostProcessing {
  const postProcessing = new PostProcessing(renderer);

  // 1. Scene Texture Pass via TSL
  const scenePass = pass(scene, camera);
  const sceneColor = scenePass.getTextureNode('output');

  // 2. Node-based Bloom Pass
  const bloomPass = bloom(sceneColor, 0.65, 0.40, 0.85);

  // 3. Composite Output: Combine Scene and Bloom
  postProcessing.outputNode = sceneColor.add(bloomPass);

  return postProcessing;
}
```

---

## 5. GPU Mass Instancing (100,000+ Particles / Geometry)

Individual `THREE.Mesh` instances saturate the CPU-GPU draw call bottleneck. For debris, bullets, foliage, or crowds, use `THREE.InstancedMesh` or Custom Instanced Buffer Geometries.

> [!WARNING]
> **Frustum Culling Blindspot on InstancedMesh**:
> By default, Three.js computes frustum culling for an `InstancedMesh` using the bounding sphere of the underlying base geometry positioned at the origin `(0, 0, 0)`. When dynamic instance transformations position bullets, particles, or entities outside this origin bounding sphere, the renderer calculates that the origin is off-screen and **instantly culls the entire `InstancedMesh`**, causing every single instance in the scene to vanish without warning.
> **Prescribed Defense**: Always set `this.instancedMesh.frustumCulled = false;` on dynamic instanced meshes.

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

    // CRITICAL: Disable frustum culling on dynamic instanced meshes!
    // Without this, moving instances away from (0,0,0) causes the entire fleet to be culled.
    this.instancedMesh.frustumCulled = false;

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

Web Audio API integration with Three.js camera transforms, fully compliant with browser autoplay policies:

```typescript
export class SpatialAudioEngine {
  private listener: THREE.AudioListener;
  private soundPool: Map<string, THREE.AudioBuffer> = new Map();
  private isContextResumed = false;

  constructor(camera: THREE.Camera) {
    this.listener = new THREE.AudioListener();
    camera.add(this.listener);
    this.setupAutoplayUnlock();
  }

  /**
   * Browser Autoplay Policy Enforcement:
   * Modern browsers block Web Audio AudioContext from producing sound until
   * an explicit user interaction event occurs.
   * resumeOnUserInteraction() unlocks the suspended AudioContext on first input.
   */
  public resumeOnUserInteraction(): void {
    if (this.isContextResumed) return;
    const ctx = this.listener.context;
    if (ctx && ctx.state === 'suspended') {
      ctx.resume().then(() => {
        this.isContextResumed = true;
      });
    }
  }

  private setupAutoplayUnlock(): void {
    const unlock = () => {
      this.resumeOnUserInteraction();
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
      window.removeEventListener('touchstart', unlock);
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
    window.addEventListener('touchstart', unlock, { once: true });
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

Web browsers crash with `CONTEXT_LOST_WEBGL` or memory exhaustion when GPU resources are leaked. In SPA applications (React/Vue/Svelte) or tab transitions, unmounted canvases leave geometries, compiled shader programs, textures, and render targets resident in VRAM.

The engine mandates comprehensive recursive asset disposal:

```typescript
import * as THREE from 'three';

const STANDARD_TEXTURE_SLOTS = [
  'map',
  'normalMap',
  'roughnessMap',
  'metalnessMap',
  'aoMap',
  'emissiveMap',
  'bumpMap',
  'displacementMap',
  'envMap',
  'lightMap',
  'alphaMap',
  'clearcoatMap',
  'clearcoatRoughnessMap',
  'clearcoatNormalMap',
  'specularMap',
  'transmissionMap',
  'thicknessMap',
  'sheenColorMap',
  'sheenRoughnessMap',
  'iridescenceMap',
  'iridescenceThicknessMap',
] as const;

/**
 * Disposes all texture slots and internal programs on a material.
 */
export function disposeMaterial(material: THREE.Material): void {
  for (const slot of STANDARD_TEXTURE_SLOTS) {
    const texture = (material as any)[slot];
    if (texture && typeof texture.dispose === 'function' && texture.isTexture) {
      texture.dispose();
    }
  }

  // Also sweep any arbitrary attached texture references
  for (const key of Object.keys(material)) {
    const value = (material as any)[key];
    if (value && typeof value.dispose === 'function' && value.isTexture) {
      value.dispose();
    }
  }

  material.dispose();
}

/**
 * Recursively disposes geometries, textures, instanced buffers, and optional WebGLRenderer.
 */
export function disposeSceneHierarchy(
  root: THREE.Object3D,
  renderer?: THREE.WebGLRenderer
): void {
  root.traverse((object: any) => {
    // 1. Dispose InstancedMesh buffer attributes
    if (object.isInstancedMesh) {
      if (object.instanceMatrix && typeof object.instanceMatrix.dispose === 'function') {
        object.instanceMatrix.dispose();
      }
      if (object.instanceColor && typeof object.instanceColor.dispose === 'function') {
        object.instanceColor.dispose();
      }
    }

    // 2. Dispose all renderable geometries and materials
    if (
      object.isMesh ||
      object.isLine ||
      object.isPoints ||
      object.isSprite ||
      object.isInstancedMesh
    ) {
      if (object.geometry && typeof object.geometry.dispose === 'function') {
        object.geometry.dispose();
      }

      if (object.material) {
        if (Array.isArray(object.material)) {
          object.material.forEach((mat: THREE.Material) => disposeMaterial(mat));
        } else {
          disposeMaterial(object.material);
        }
      }
    }

    // 3. Dispose render targets if attached to custom nodes/passes
    if (object.renderTarget && typeof object.renderTarget.dispose === 'function') {
      object.renderTarget.dispose();
    }
  });

  // Remove root from its scene graph parent
  if (root.parent) {
    root.parent.remove(root);
  }

  // 4. Renderer Lifecycle Teardown
  if (renderer) {
    renderer.dispose();
    if (typeof renderer.forceContextLoss === 'function') {
      renderer.forceContextLoss();
    }
    if (renderer.domElement && renderer.domElement.parentNode) {
      renderer.domElement.parentNode.removeChild(renderer.domElement);
    }
  }
}
```

---

## 8. Asynchronous Model Loading & Scene Framing Protocol

Loading external GLTF/GLB models presents two primary failure modes: unhandled asynchronous rejections causing stalled interfaces, and uncentered/unscaled models rendering outside the camera frustum or at microscopic/colossal scales.

### 8.1 Production Promise-Based GLTF Loader with DRACO Compression

```typescript
import * as THREE from 'three';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

export async function loadGLTFModel(
  url: string,
  dracoDecoderPath = 'https://www.gstatic.com/draco/versioned/decoders/1.5.7/'
): Promise<GLTF> {
  const loader = new GLTFLoader();
  const dracoLoader = new DRACOLoader();
  dracoLoader.setDecoderPath(dracoDecoderPath);
  loader.setDRACOLoader(dracoLoader);

  return new Promise<GLTF>((resolve, reject) => {
    loader.load(
      url,
      (gltf) => {
        dracoLoader.dispose();
        resolve(gltf);
      },
      undefined,
      (error) => {
        dracoLoader.dispose();
        reject(new Error(`[loadGLTFModel] Failed to load 3D model from ${url}: ${error}`));
      }
    );
  });
}
```

### 8.2 Mandatory Matrix World Update & Auto-Framing Calculation

> [!IMPORTANT]
> **Matrix World Synchronization Invariant**:
> You **MUST** call `model.updateMatrixWorld(true)` before computing `new THREE.Box3().setFromObject(model)`. If the hierarchy transforms have not been synchronized through the root node, `setFromObject` calculates against stale or zero local matrices, yielding an incorrect bounding box (0,0,0) and positioning the camera inside or far away from the geometry.

```typescript
export function autoFrameModel(
  model: THREE.Object3D,
  camera: THREE.PerspectiveCamera,
  offsetFactor = 1.25
): { center: THREE.Vector3; radius: number; distance: number } {
  // 1. MANDATORY: Recalculate full world matrix hierarchy
  model.updateMatrixWorld(true);

  // 2. Compute object-aligned bounding box and bounding sphere
  const box = new THREE.Box3().setFromObject(model);
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);

  const sphere = new THREE.Sphere();
  box.getBoundingSphere(sphere);
  const radius = sphere.radius;

  // 3. Trigonometric Distance Calculation: distance = radius / sin(fov / 2)
  const fovRad = THREE.MathUtils.degToRad(camera.fov / 2);
  const distance = (radius / Math.sin(fovRad)) * offsetFactor;

  // 4. Reposition camera looking directly at object center
  camera.position.set(center.x, center.y + radius * 0.25, center.z + distance);
  camera.near = Math.max(0.01, radius / 100);
  camera.far = Math.max(1000, radius * 20);
  camera.updateProjectionMatrix();
  camera.lookAt(center);

  return { center, radius, distance };
}
```

---

## 9. Deterministic AI Three.js Guardrail Checklist

Every Three.js implementation produced by agents MUST satisfy this pre-flight verification checklist before milestone completion:

| # | Checkpoint | Failure Mode Prevented | Verification Rule |
| :--- | :--- | :--- | :--- |
| **1** | **Backend Isolation** | Crashes from passing `WebGPURenderer` into `EffectComposer` | Use `WebGLRenderer` with `EffectComposer`; use `WebGPURenderer` with `PostProcessing` from `'three/webgpu'`. Never mix. |
| **2** | **WebGPU Initialization** | Uninitialized context throw / silent blank canvas | `WebGPURenderer` must be awaited: `await renderer.init()`. |
| **3** | **Container Sizing Fallback** | 0x0 canvas collapse when parent has no initial CSS size | Always use `container.clientWidth || window.innerWidth` and attach `ResizeObserver`. |
| **4** | **PBR Baseline Lighting** | Complete black silhouette / black-screen void with Standard/Physical materials | Every PBR scene MUST instantiate `AmbientLight(0xffffff, 0.6)` + `DirectionalLight(0xffffff, 1.8)`. |
| **5** | **Camera Positioning** | Camera inside geometry `(0,0,0)` resulting in empty black render | Camera placed outside bounding volume (e.g. `(0, 3, 8)`) and auto-framed via `autoFrameModel`. |
| **6** | **Frustum Culling on Instancing** | 100,000 instances disappearing when moving away from origin | Set `instancedMesh.frustumCulled = false` for dynamic particle/bullet fleets. |
| **7** | **Texture Color Spaces** | Washed out, desaturated, or distorted normal/PBR maps | Color/Diffuse: `THREE.SRGBColorSpace`; Normal/Roughness/Metalness/AO: `THREE.NoColorSpace`. |
| **8** | **OutputPass Inclusion** | Blurry, dark, or color-crushed post-processing output | `OutputPass` must be the final pass in any WebGL2 `EffectComposer` chain. |
| **9** | **Audio Autoplay Unlocking** | AudioContext warning / silent audio in browser | Bind one-time `pointerdown`/`keydown` listener to resume suspended `AudioContext`. |
| **10** | **Model Matrix World Sync** | Camera looking at empty space or incorrect bounding box | Always call `model.updateMatrixWorld(true)` before `Box3.setFromObject()`. |
| **11** | **R3F Direct Mutation** | Catastrophic React re-render lag (0.5 FPS) in render loop | NEVER call `useState` inside `useFrame()`. Mutate object refs directly (`ref.current.rotation.y += dt`). |
| **12** | **Zero-Leak Teardown** | `CONTEXT_LOST_WEBGL` crash on tab switch or component unmount | Recursively dispose geometry, materials, all texture slots, buffer attributes, and call `renderer.forceContextLoss()`. |

---

## 10. Definition of Done for AAA 3D Graphics

- [x] **Locked 60+ FPS**: Physics loop decoupled at 120 Hz; zero frame-drops under profiling.
- [x] **Backend Isolation Enforced**: WebGL2 with `EffectComposer` or WebGPU with awaited `init()` and TSL `PostProcessing`.
- [x] **Scene Grounding Complete**: Baseline `AmbientLight` + `DirectionalLight` present; camera positioned outside bounding sphere; `ResizeObserver` attached.
- [x] **Post-Processing Calibrated**: Selective Bloom, GTAO, and `OutputPass` (ACES Filmic Tone Mapping + sRGB) active.
- [x] **Draw Calls < 50**: InstancedMesh applied to all particle/debris systems with `frustumCulled = false`.
- [x] **Zero Memory Leaks**: Full `disposeSceneHierarchy` lifecycle executed on teardown.
