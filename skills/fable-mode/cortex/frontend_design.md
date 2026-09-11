---
{
  "name": "frontend_design",
  "description": "Frontier UI/UX engineering, Anti-Slop taste engine, and Awwwards-winning architecture",
  "domain": "frontend_design",
  "activation_count": 24,
  "synaptic_weights": {
    "audit_anti_slop": 0.98,
    "infer_design_brief": 0.96,
    "generate_design_tokens": 0.95,
    "generate_awwwards_scaffold": 0.95,
    "validate_preflight_design": 0.94,
    "render_vector": 0.92,
    "spring_motion_physics": 0.9,
    "fluid_typography": 0.9
  },
  "antibodies": [
    {
      "antibody_id": "ab_design_purple_glow_slop",
      "domain": "frontend_design",
      "trigger_condition": "Using generic purple/violet glowing radial or gradient blobs (bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl)",
      "lethal_anti_pattern": "<div class=\"absolute -top-40 right-0 h-96 w-96 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl opacity-30\"></div>",
      "prescribed_defense": "Eliminate generic purple blobs. Use a single curated OKLCH accent colorway anchored on a neutral base with inverse-square volumetric lighting.",
      "severity": "CRITICAL",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Visual difference probe verified zero purple gradient artifacts; clean monochromatic OKLCH substrate confirmed."
    },
    {
      "antibody_id": "ab_design_centered_three_card_cliche",
      "domain": "frontend_design",
      "trigger_condition": "Generating centered hero followed by 3 equal feature cards with icons in colored rounded boxes",
      "lethal_anti_pattern": "<div class=\"grid grid-cols-1 md:grid-cols-3 gap-8 text-center\"><div class=\"p-6 rounded-xl shadow\"><h3>Feature 1</h3></div>...</div>",
      "prescribed_defense": "Enforce dynamic asymmetric Bento Grid layout with mixed cell spans (2x2 hero cell, 2x1 telemetry ribbon, 1x1 sandboxes) and contrasting visual surfaces.",
      "severity": "HIGH",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Layout inspector confirmed asymmetric 50/50 split and 8/4 bento grid with zero identical centered cards."
    },
    {
      "antibody_id": "ab_design_inter_font_crutch",
      "domain": "frontend_design",
      "trigger_condition": "Defaulting lazily to font-sans without explicit typographic pairing or relying on generic Inter/Arial",
      "lethal_anti_pattern": "<body class=\"font-sans\"> # Default unstyled Inter without display hierarchy",
      "prescribed_defense": "Pair curated display typefaces (Geist Display, Satoshi, PP Editorial New, Cabinet Grotesk) with body sans and monospace telemetry. Apply golden-ratio fluid clamp scales.",
      "severity": "HIGH",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "CSS AST analyzer verified explicit display and body font declarations with zero fallback font-sans crutches."
    },
    {
      "antibody_id": "ab_design_div_screenshot_mockup",
      "domain": "frontend_design",
      "trigger_condition": "Rendering fake browser or macOS preview windows with 3 colored circle dots in CSS",
      "lethal_anti_pattern": "<div class=\"flex gap-2\"><span class=\"w-3 h-3 rounded-full bg-red-500\"></span><span class=\"w-3 h-3 rounded-full bg-yellow-500\"></span><span class=\"w-3 h-3 rounded-full bg-green-500\"></span></div>",
      "prescribed_defense": "Prohibit fake div screenshot window bars. Render authentic interactive component sandboxes or real high-resolution imagery.",
      "severity": "CRITICAL",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "DOM scanner verified complete absence of fake colored window dots; real telemetry widgets rendered."
    },
    {
      "antibody_id": "ab_design_llm_marketing_fluff",
      "domain": "frontend_design",
      "trigger_condition": "Injecting generic LLM buzzwords ('supercharge', 'unleash', 'next-gen AI', 'delve into', 'seamlessly integrate')",
      "lethal_anti_pattern": "<h1>Supercharge your workflow with our next-gen AI platform</h1>",
      "prescribed_defense": "Replace marketing buzzwords with concrete, functional, measurable engineering copy ('Deterministic execution brokers delivering sub-60ms state transitions').",
      "severity": "HIGH",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "AST copy auditor confirmed zero regex matches for banned LLM marketing marker phrases."
    },
    {
      "antibody_id": "ab_design_viewport_instability_h_screen",
      "domain": "frontend_design",
      "trigger_condition": "Using h-screen or height: 100vh causing mobile address-bar resize jumping",
      "lethal_anti_pattern": "<section class=\"h-screen w-full flex items-center justify-center\">",
      "prescribed_defense": "Strictly use min-h-[100dvh] with desktop top padding capped at pt-24 (6rem) for rock-solid mobile stability.",
      "severity": "MEDIUM",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Mobile emulator verified zero Cumulative Layout Shift (CLS = 0.00) during mobile URL bar collapse."
    },
    {
      "antibody_id": "ab_design_rsc_motion_leak",
      "domain": "frontend_design",
      "trigger_condition": "Invoking motion/react hooks (useScroll, useMotionValue, AnimatePresence) inside Next.js Server Components without 'use client'",
      "lethal_anti_pattern": "// app/page.tsx (without use client)\\nimport { motion } from \"motion/react\";",
      "prescribed_defense": "Isolate interactive spring motion into dedicated client leaf components with 'use client' at the file top.",
      "severity": "HIGH",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Next.js build compilation confirmed zero SSR hydration crashes or React Server Component boundary errors."
    },
    {
      "antibody_id": "ab_design_contrast_sub_ratio_gray",
      "domain": "frontend_design",
      "trigger_condition": "Rendering low-contrast washed-out text (e.g. text-gray-400 on light gray cards) failing WCAG AA (contrast < 4.5:1)",
      "lethal_anti_pattern": "<p class=\"text-zinc-400 bg-zinc-100\">Subtext</p> # Contrast ratio 2.3:1 (fails WCAG AA)",
      "prescribed_defense": "Validate all text against APCA Lc >= 75 / WCAG AA >= 4.5:1 mathematical luminance before committing styles.",
      "severity": "CRITICAL",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Color analyzer verified text-to-background contrast ratio >= 4.5:1 across all light and dark theme tokens."
    },
    {
      "antibody_id": "ab_design_eyebrow_overload",
      "domain": "frontend_design",
      "trigger_condition": "Stacking uppercase tracking eyebrows on every single section (> 1 per 3 sections)",
      "lethal_anti_pattern": "<span class=\"tracking-widest uppercase text-xs\">Section Eyebrow</span> on all 5 page sections",
      "prescribed_defense": "Restrain uppercase tracking eyebrows to at most 1 per 3 sections (Total <= ceil(N / 3)).",
      "severity": "MEDIUM",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Static inspection verified eyebrow count <= ceil(section_count / 3) across all generated pages."
    },
    {
      "antibody_id": "ab_design_bento_grid_hollow_padding",
      "domain": "frontend_design",
      "trigger_condition": "Filling bento grid with empty decorative cards or uniform boring boxes without contrasting visual treatments",
      "lethal_anti_pattern": "<div class=\"grid grid-cols-3 gap-4\"><div>Card 1</div><div>Card 2</div>...</div>",
      "prescribed_defense": "Bento grids must have exactly as many cells as real content. At least 2-3 cells must feature contrasting treatments (interactive widget, dark container, live telemetry pill).",
      "severity": "MEDIUM",
      "source_task_id": "",
      "created_at": "2026-09-06T12:00:00+00:00",
      "verified_counterfactual": "Bento grid inspector verified mixed spans (2x2, 2x1, 1x1) with real functional telemetry in every cell."
    }
  ],
  "specialized_heuristics": [
    "Brief Inference (\"Read the Room\"): Infer page kind, target audience, and calibrated dials before writing code; state the mandatory Design Read Declaration.",
    "The Three Dials Calibration: Calibrate Variance (1-10), Motion (1-10), and Density (1-10) dynamically based on brief inference.",
    "7-Layer Optical Depth Staging: Construct interfaces across Atmospheric Void, Micro-Grain Texture, Volumetric Lighting, Refractive Substrate, Hairline Specular Rims, Fluid Typography, and Micro-Physics.",
    "The 6 Haute Aesthetic Archetypes: Select from Cyber Obsidian Monolith, Haute Editorial Modernism, Swiss Precision Vignelli, Kinetic Spatial HUD, Neo-Nordic Warmth, or Cold Chromatic Luxury.",
    "Golden-Ratio Fluid Typography Math: Use CSS clamp(min, slope * 100vw + intercept, max) from 375px to 1440px for zero layout shift.",
    "Newtonian Damped Harmonic Motion: Drive interactive states with 2nd-order damped spring parameters (stiffness k, damping c, mass m, zeta) via motion/react.",
    "Single-Line CTA Constraint: Enforce whitespace-nowrap on all button CTAs; ensure button labels fit on a single line on desktop.",
    "Hero Stack Discipline: Hero section text is capped at max 4 elements (optional eyebrow, max 2-line headline, max 20-word subtext, primary CTA + max 1 secondary).",
    "Desktop Navigation Cap: Single-line sticky header strictly capped at <= 80px height (h-16 to h-20).",
    "Pre-Flight 5-Point Quality Gate: Verify Viewport Fit (100dvh), Descender Clearance, Invariant Locks, Interactive Contrast, and Copy Restraint before shipping."
  ],
  "last_consolidated_at": "2026-09-06T12:00:00+00:00"
}
---

# Cortical Lobe: `frontend_design`

> [!NOTE]
> Frontier UI/UX engineering, Anti-Slop taste engine, and Awwwards-winning architecture
> Activation count: 24.

## Metadata & Telemetry
- **Name**: `frontend_design`
- **Description**: Frontier UI/UX engineering, Anti-Slop taste engine, and Awwwards-winning architecture
- **Domain**: `frontend_design`
- **Activation Count**: `24`
- **Total Antibodies**: `10`
- **Specialized Heuristics**: `10`
- **Last Consolidated**: `2026-09-06T12:00:00+00:00`

## Specialized Domain Heuristics
1. Brief Inference ("Read the Room"): Infer page kind, target audience, and calibrated dials before writing code; state the mandatory Design Read Declaration.
2. The Three Dials Calibration: Calibrate Variance (1-10), Motion (1-10), and Density (1-10) dynamically based on brief inference.
3. 7-Layer Optical Depth Staging: Construct interfaces across Atmospheric Void, Micro-Grain Texture, Volumetric Lighting, Refractive Substrate, Hairline Specular Rims, Fluid Typography, and Micro-Physics.
4. The 6 Haute Aesthetic Archetypes: Select from Cyber Obsidian Monolith, Haute Editorial Modernism, Swiss Precision Vignelli, Kinetic Spatial HUD, Neo-Nordic Warmth, or Cold Chromatic Luxury.
5. Golden-Ratio Fluid Typography Math: Use CSS clamp(min, slope * 100vw + intercept, max) from 375px to 1440px for zero layout shift.
6. Newtonian Damped Harmonic Motion: Drive interactive states with 2nd-order damped spring parameters (stiffness k, damping c, mass m, zeta) via motion/react.
7. Single-Line CTA Constraint: Enforce whitespace-nowrap on all button CTAs; ensure button labels fit on a single line on desktop.
8. Hero Stack Discipline: Hero section text is capped at max 4 elements (optional eyebrow, max 2-line headline, max 20-word subtext, primary CTA + max 1 secondary).
9. Desktop Navigation Cap: Single-line sticky header strictly capped at <= 80px height (h-16 to h-20).
10. Pre-Flight 5-Point Quality Gate: Verify Viewport Fit (100dvh), Descender Clearance, Invariant Locks, Interactive Contrast, and Copy Restraint before shipping.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `audit_anti_slop` | `0.9800` | 🟢 Strong |
| `infer_design_brief` | `0.9600` | 🟢 Strong |
| `generate_design_tokens` | `0.9500` | 🟢 Strong |
| `generate_awwwards_scaffold` | `0.9500` | 🟢 Strong |
| `validate_preflight_design` | `0.9400` | 🟢 Strong |
| `render_vector` | `0.9200` | 🟢 Strong |
| `spring_motion_physics` | `0.9000` | 🟢 Strong |
| `fluid_typography` | `0.9000` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_design_purple_glow_slop` [CRITICAL]
- **Domain**: `frontend_design`
- **Trigger Condition**: Using generic purple/violet glowing radial or gradient blobs (bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl)
- **Lethal Anti-Pattern**: <div class="absolute -top-40 right-0 h-96 w-96 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl opacity-30"></div>
- **Prescribed Defense**: Eliminate generic purple blobs. Use a single curated OKLCH accent colorway anchored on a neutral base with inverse-square volumetric lighting.
- **Verified Counterfactual**: `Visual difference probe verified zero purple gradient artifacts; clean monochromatic OKLCH substrate confirmed.`

#### Antibody `ab_design_centered_three_card_cliche` [HIGH]
- **Domain**: `frontend_design`
- **Trigger Condition**: Generating centered hero followed by 3 equal feature cards with icons in colored rounded boxes
- **Lethal Anti-Pattern**: <div class="grid grid-cols-1 md:grid-cols-3 gap-8 text-center"><div class="p-6 rounded-xl shadow"><h3>Feature 1</h3></div>...</div>
- **Prescribed Defense**: Enforce dynamic asymmetric Bento Grid layout with mixed cell spans (2x2 hero cell, 2x1 telemetry ribbon, 1x1 sandboxes) and contrasting visual surfaces.
- **Verified Counterfactual**: `Layout inspector confirmed asymmetric 50/50 split and 8/4 bento grid with zero identical centered cards.`

#### Antibody `ab_design_inter_font_crutch` [HIGH]
- **Domain**: `frontend_design`
- **Trigger Condition**: Defaulting lazily to font-sans without explicit typographic pairing or relying on generic Inter/Arial
- **Lethal Anti-Pattern**: <body class="font-sans"> # Default unstyled Inter without display hierarchy
- **Prescribed Defense**: Pair curated display typefaces (Geist Display, Satoshi, PP Editorial New, Cabinet Grotesk) with body sans and monospace telemetry. Apply golden-ratio fluid clamp scales.
- **Verified Counterfactual**: `CSS AST analyzer verified explicit display and body font declarations with zero fallback font-sans crutches.`

#### Antibody `ab_design_div_screenshot_mockup` [CRITICAL]
- **Domain**: `frontend_design`
- **Trigger Condition**: Rendering fake browser or macOS preview windows with 3 colored circle dots in CSS
- **Lethal Anti-Pattern**: <div class="flex gap-2"><span class="w-3 h-3 rounded-full bg-red-500"></span><span class="w-3 h-3 rounded-full bg-yellow-500"></span><span class="w-3 h-3 rounded-full bg-green-500"></span></div>
- **Prescribed Defense**: Prohibit fake div screenshot window bars. Render authentic interactive component sandboxes or real high-resolution imagery.
- **Verified Counterfactual**: `DOM scanner verified complete absence of fake colored window dots; real telemetry widgets rendered.`

#### Antibody `ab_design_llm_marketing_fluff` [HIGH]
- **Domain**: `frontend_design`
- **Trigger Condition**: Injecting generic LLM buzzwords ('supercharge', 'unleash', 'next-gen AI', 'delve into', 'seamlessly integrate')
- **Lethal Anti-Pattern**: <h1>Supercharge your workflow with our next-gen AI platform</h1>
- **Prescribed Defense**: Replace marketing buzzwords with concrete, functional, measurable engineering copy ('Deterministic execution brokers delivering sub-60ms state transitions').
- **Verified Counterfactual**: `AST copy auditor confirmed zero regex matches for banned LLM marketing marker phrases.`

#### Antibody `ab_design_viewport_instability_h_screen` [MEDIUM]
- **Domain**: `frontend_design`
- **Trigger Condition**: Using h-screen or height: 100vh causing mobile address-bar resize jumping
- **Lethal Anti-Pattern**: <section class="h-screen w-full flex items-center justify-center">
- **Prescribed Defense**: Strictly use min-h-[100dvh] with desktop top padding capped at pt-24 (6rem) for rock-solid mobile stability.
- **Verified Counterfactual**: `Mobile emulator verified zero Cumulative Layout Shift (CLS = 0.00) during mobile URL bar collapse.`

#### Antibody `ab_design_rsc_motion_leak` [HIGH]
- **Domain**: `frontend_design`
- **Trigger Condition**: Invoking motion/react hooks (useScroll, useMotionValue, AnimatePresence) inside Next.js Server Components without 'use client'
- **Lethal Anti-Pattern**: // app/page.tsx (without use client)\nimport { motion } from "motion/react";
- **Prescribed Defense**: Isolate interactive spring motion into dedicated client leaf components with 'use client' at the file top.
- **Verified Counterfactual**: `Next.js build compilation confirmed zero SSR hydration crashes or React Server Component boundary errors.`

#### Antibody `ab_design_contrast_sub_ratio_gray` [CRITICAL]
- **Domain**: `frontend_design`
- **Trigger Condition**: Rendering low-contrast washed-out text (e.g. text-gray-400 on light gray cards) failing WCAG AA (contrast < 4.5:1)
- **Lethal Anti-Pattern**: <p class="text-zinc-400 bg-zinc-100">Subtext</p> # Contrast ratio 2.3:1 (fails WCAG AA)
- **Prescribed Defense**: Validate all text against APCA Lc >= 75 / WCAG AA >= 4.5:1 mathematical luminance before committing styles.
- **Verified Counterfactual**: `Color analyzer verified text-to-background contrast ratio >= 4.5:1 across all light and dark theme tokens.`

#### Antibody `ab_design_eyebrow_overload` [MEDIUM]
- **Domain**: `frontend_design`
- **Trigger Condition**: Stacking uppercase tracking eyebrows on every single section (> 1 per 3 sections)
- **Lethal Anti-Pattern**: <span class="tracking-widest uppercase text-xs">Section Eyebrow</span> on all 5 page sections
- **Prescribed Defense**: Restrain uppercase tracking eyebrows to at most 1 per 3 sections (Total <= ceil(N / 3)).
- **Verified Counterfactual**: `Static inspection verified eyebrow count <= ceil(section_count / 3) across all generated pages.`

#### Antibody `ab_design_bento_grid_hollow_padding` [MEDIUM]
- **Domain**: `frontend_design`
- **Trigger Condition**: Filling bento grid with empty decorative cards or uniform boring boxes without contrasting visual treatments
- **Lethal Anti-Pattern**: <div class="grid grid-cols-3 gap-4"><div>Card 1</div><div>Card 2</div>...</div>
- **Prescribed Defense**: Bento grids must have exactly as many cells as real content. At least 2-3 cells must feature contrasting treatments (interactive widget, dark container, live telemetry pill).
- **Verified Counterfactual**: `Bento grid inspector verified mixed spans (2x2, 2x1, 1x1) with real functional telemetry in every cell.`
