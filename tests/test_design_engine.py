"""Comprehensive Test Suite for Fable-Mode Frontend Design & Anti-Slop Taste Engine.

Tests:
1. DesignDials & AestheticArchetype profiles (bounds, serialization, WCAG contrast)
2. Fluid typography clamp formula derivation & Spring physics presets
3. AntiSlopAuditor static scan & violation detection across all 6 anti-patterns
4. BriefInferenceEngine ("Read the Room") across varied domain prompts
5. AwwwardsScaffoldGenerator 7-layer optical depth output and zero-slop verification
6. PreFlightDesignGate 5-point verification checks (pass & fail paths)
7. CoderFleetDispatcher routing and parameter binding for all design actions
8. Fable-Engine session action handlers formatting & markdown generation
"""
from __future__ import annotations

import unittest
from typing import Any

from fable_v2.coder_fleet import (
    AestheticArchetype,
    AntiSlopAuditor,
    AwwwardsScaffoldGenerator,
    BriefInferenceEngine,
    CoderFleetDispatcher,
    DesignDials,
    DesignEngine,
    HauteDesignTheme,
    OKLCHColorToken,
    PreFlightDesignGate,
    calculate_contrast_ratio,
    generate_fluid_clamp,
    HAUTE_THEMES,
    SPRING_PRESETS,
)
from fable_v2.coder_fleet.design_engine import SlopViolation, SpringPreset
from fable_engine.actions import handle_fable_session
from fable_engine.actions.fleet import (
    _handle_audit_anti_slop,
    _handle_infer_design_brief,
    _handle_generate_design_tokens,
    _handle_generate_awwwards_scaffold,
    _handle_validate_preflight_design,
    _handle_list_design_archetypes,
)


class TestDesignDialsAndTokens(unittest.TestCase):
    """Test dials clamping, serialization, and OKLCH color/typography tokens."""

    def test_dials_clamping_and_serialization(self) -> None:
        dials = DesignDials(variance=15, motion=-3, density=4)
        self.assertEqual(dials.variance, 10)
        self.assertEqual(dials.motion, 1)
        self.assertEqual(dials.density, 4)

        d_dict = dials.to_dict()
        self.assertEqual(d_dict, {"variance": 10, "motion": 1, "density": 4})

        recovered = DesignDials.from_dict(d_dict)
        self.assertEqual(recovered.variance, 10)
        self.assertEqual(recovered.motion, 1)
        self.assertEqual(recovered.density, 4)

        v_str = dials.vector_str()
        self.assertIn("Variance: 10", v_str)
        self.assertIn("Motion: 1", v_str)
        self.assertIn("Density: 4", v_str)

    def test_all_six_archetypes_present_and_valid(self) -> None:
        self.assertEqual(len(AestheticArchetype), 6)
        for arch in AestheticArchetype:
            self.assertIn(arch, HAUTE_THEMES)
            theme = HAUTE_THEMES[arch]
            self.assertIsInstance(theme, HauteDesignTheme)
            self.assertTrue(theme.title)
            self.assertTrue(theme.description)
            self.assertIsInstance(theme.bg_void, OKLCHColorToken)
            self.assertIsInstance(theme.text_primary, OKLCHColorToken)
            self.assertIsInstance(theme.accent_primary, OKLCHColorToken)

    def test_oklch_css_and_luminance(self) -> None:
        c1 = OKLCHColorToken(0.985, 0.005, 270.0)
        c2 = OKLCHColorToken(0.08, 0.02, 270.0)
        self.assertEqual(c1.to_css(), "oklch(0.985 0.005 270.0)")

        alpha_token = OKLCHColorToken(0.12, 0.015, 270.0, alpha=0.7)
        self.assertIn("/ 0.70)", alpha_token.to_css())

        # Contrast calculation
        contrast = calculate_contrast_ratio(c1, c2)
        self.assertGreater(contrast, 7.0)  # Meets WCAG AAA

        # Same colors have 1.0 contrast
        self.assertAlmostEqual(calculate_contrast_ratio(c1, c1), 1.0, places=1)

    def test_fluid_clamp_generation(self) -> None:
        clamp_str = generate_fluid_clamp(1.5, 3.0, 375.0, 1440.0)
        self.assertTrue(clamp_str.startswith("clamp("))
        self.assertTrue(clamp_str.endswith("3.000rem)"))
        self.assertIn("vw", clamp_str)

    def test_spring_presets(self) -> None:
        self.assertIn("snappy", SPRING_PRESETS)
        self.assertIn("modal", SPRING_PRESETS)
        self.assertIn("velvet", SPRING_PRESETS)
        self.assertIn("magnetic", SPRING_PRESETS)
        for name, preset in SPRING_PRESETS.items():
            self.assertGreater(preset.stiffness, 0)
            self.assertGreater(preset.damping, 0)
            self.assertGreater(preset.mass, 0)
            self.assertGreater(preset.zeta, 0)


class TestAntiSlopAuditor(unittest.TestCase):
    """Exhaustive test suite for static anti-slop code auditing."""

    def setUp(self) -> None:
        self.auditor = AntiSlopAuditor()

    def test_purple_gradient_slop_detected(self) -> None:
        slop_code = """
        <div class="h-96 w-96 rounded-full bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl opacity-30">
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        self.assertGreater(res["fatal_count"], 0)
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_01_PURPLE_GRADIENT", rule_ids)

    def test_llm_buzzwords_detected(self) -> None:
        slop_code = """
        <section>
          <h1>Supercharge your workflow with our next-gen AI platform</h1>
          <p>Delve into seamless integration and revolutionize productivity.</p>
        </section>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        self.assertGreater(res["high_count"], 0)
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_02_LLM_BUZZWORD", rule_ids)

    def test_fake_div_dots_detected(self) -> None:
        slop_code = """
        <div class="flex items-center gap-2 p-3 bg-zinc-900">
          <span class="w-3 h-3 rounded-full bg-red-500"></span>
          <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
          <span class="w-3 h-3 rounded-full bg-green-500"></span>
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_03_DIV_SCREENSHOT_MOCKUP", rule_ids)

    def test_viewport_instability_h_screen_detected(self) -> None:
        slop_code = """
        <main class="h-screen w-full flex items-center justify-center">
          <p>Hero Content</p>
        </main>
        """
        res = self.auditor.audit_code(slop_code)
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_05_VIEWPORT_INSTABILITY", rule_ids)

    def test_clean_awwwards_code_passes(self) -> None:
        clean_code = """
        <div class="min-h-[100dvh] w-full bg-[oklch(0.08_0.02_270)] text-[oklch(0.985_0.005_270)] antialiased">
          <header class="h-16 border-b border-white/10 px-6 flex items-center justify-between">
            <span class="font-bold text-sm tracking-tight">KINETIC // 01</span>
            <button class="whitespace-nowrap px-4 py-2 bg-emerald-400 text-black text-xs font-semibold rounded-sm">
              Deploy Cluster
            </button>
          </header>
          <main class="max-w-7xl mx-auto px-6 pt-20">
            <h1 class="text-5xl font-bold tracking-tight leading-[0.95]">
              Sub-second deterministic state verification.
            </h1>
            <p class="mt-4 text-zinc-400 max-w-lg">
              Hardware-grounded consensus engines processing 120,000 transactions per second.
            </p>
          </main>
        </div>
        """
        res = self.auditor.audit_code(clean_code)
        self.assertTrue(res["clean"])
        self.assertEqual(res["score"], 1.0)
        self.assertEqual(len(res["violations"]), 0)

    def test_empty_code_handling(self) -> None:
        res = self.auditor.audit_code("")
        self.assertTrue(res["clean"])
        self.assertEqual(res["score"], 1.0)

    def test_icon_circle_blob_detected(self) -> None:
        slop_code = """
        <div class="p-6 bg-white rounded-xl">
          <div class="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-600">
            <svg class="w-6 h-6"></svg>
          </div>
          <h3>Feature Title</h3>
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_07_ICON_CIRCLE_BLOB", rule_ids)

    def test_naked_outline_none_focus_removal_detected(self) -> None:
        slop_code = """
        <button class="px-4 py-2 bg-blue-600 text-white rounded outline-none">
          Click Here
        </button>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_08_FOCUS_OUTLINE_REMOVAL", rule_ids)

    def test_layout_thrashing_transition_detected(self) -> None:
        slop_code = """
        <div style="transition: width 0.3s ease, height 0.3s ease;">
          Content
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_09_LAYOUT_THRASHING", rule_ids)

    def test_expanded_llm_cliches_detected(self) -> None:
        slop_code = """
        <p>In today's fast-paced world, dive deep and unlock the potential to empower your team with seamless integration.</p>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        self.assertGreaterEqual(res["high_count"], 3)

    def test_focus_visible_before_outline_none_passes_audit(self) -> None:
        valid_code = """
        <button class="focus-visible:ring-2 focus-visible:ring-blue-500 outline-none px-4 py-2">
          Accessible Button
        </button>
        """
        res = self.auditor.audit_code(valid_code)
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertNotIn("ANTI_SLOP_08_FOCUS_OUTLINE_REMOVAL", rule_ids)

    def test_purple_via_gradient_detected(self) -> None:
        slop_code = """
        <div class="bg-gradient-to-r from-purple-600 via-pink-500 to-indigo-600 text-transparent bg-clip-text">
          Generic AI Title
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_01_PURPLE_GRADIENT", rule_ids)

    def test_linear_gradient_hex_detected(self) -> None:
        slop_code = """
        <div style="background: linear-gradient(to right, #8b5cf6, #ec4899);">
          Slop Header
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_01_PURPLE_GRADIENT", rule_ids)

    def test_div_dots_reordered_classes_detected(self) -> None:
        slop_code = """
        <div class="flex items-center gap-2">
          <div class="bg-red-500 w-3 h-3 rounded-full"></div>
          <div class="bg-yellow-500 w-3 h-3 rounded-full"></div>
          <div class="bg-green-500 w-3 h-3 rounded-full"></div>
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_03_DIV_SCREENSHOT_MOCKUP", rule_ids)

    def test_three_card_parent_text_center_detected(self) -> None:
        slop_code = """
        <div class="grid grid-cols-3 gap-6 text-center">
          <div>Card 1</div>
          <div>Card 2</div>
          <div>Card 3</div>
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_04_CENTERED_THREE_CARD", rule_ids)

    def test_default_font_sans_crutch_detected(self) -> None:
        slop_code = """
        <body class="font-sans">
          <h1>Generic Title</h1>
          <p>Unstyled text</p>
        </body>
        """
        res = self.auditor.audit_code(slop_code)
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_10_DEFAULT_FONT_CRUTCH", rule_ids)

    def test_rsc_motion_leak_detected(self) -> None:
        rsc_code = """
        import { motion } from "motion/react";
        export default function HeroSection() {
          return <motion.div animate={{ opacity: 1 }} />;
        }
        """
        res = self.auditor.audit_code(rsc_code, file_path="components/Hero.tsx")
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_11_RSC_MOTION_LEAK", rule_ids)

    def test_low_contrast_gray_text_detected(self) -> None:
        slop_code = """
        <div class="bg-white text-zinc-400 p-4">
          Washed out subtext that fails WCAG AA contrast ratio
        </div>
        """
        res = self.auditor.audit_code(slop_code)
        self.assertFalse(res["clean"])
        rule_ids = [v["rule_id"] for v in res["violations"]]
        self.assertIn("ANTI_SLOP_12_LOW_CONTRAST_TEXT", rule_ids)


class TestBriefInferenceEngine(unittest.TestCase):
    """Test brief inference and room-reading across diverse domain prompts."""

    def setUp(self) -> None:
        self.engine = BriefInferenceEngine()

    def test_developer_tool_inference(self) -> None:
        brief = self.engine.infer_brief("Create a real-time kubernetes pod telemetry monitoring CLI dashboard")
        self.assertEqual(brief["archetype"], AestheticArchetype.KINETIC_SPATIAL_HUD.value)
        self.assertIn("Kinetic Spatial HUD", brief["archetype_title"])
        self.assertIn("Design Read:", brief["design_read"])
        self.assertEqual(brief["dials"]["density"], 8)

    def test_editorial_journal_inference(self) -> None:
        brief = self.engine.infer_brief("Publish an intellectual essay and literature journal reading experience")
        self.assertEqual(brief["archetype"], AestheticArchetype.HAUTE_EDITORIAL_MODERNISM.value)
        self.assertEqual(brief["dials"]["variance"], 9)
        self.assertIn("PP Editorial New", brief["typography"]["display"])

    def test_cold_luxury_inference(self) -> None:
        brief = self.engine.infer_brief("Showcase for high-end titanium mechanical watch horology")
        self.assertEqual(brief["archetype"], AestheticArchetype.COLD_CHROMATIC_LUXURY.value)
        self.assertEqual(brief["dials"]["density"], 3)

    def test_neo_nordic_lifestyle_inference(self) -> None:
        brief = self.engine.infer_brief("Artisan specialty coffee roastery storefront with organic wood warmth")
        self.assertEqual(brief["archetype"], AestheticArchetype.NEO_NORDIC_WARMTH.value)
        self.assertIn("Neo-Nordic", brief["archetype_title"])

    def test_swiss_precision_inference(self) -> None:
        brief = self.engine.infer_brief("Minimalist Swiss architecture museum exhibition poster")
        self.assertEqual(brief["archetype"], AestheticArchetype.SWISS_PRECISION_VIGNELLI.value)

    def test_dials_override(self) -> None:
        brief = self.engine.infer_brief(
            "Minimalist Swiss architecture museum",
            dials_override={"variance": 2, "motion": 1, "density": 2},
        )
        self.assertEqual(brief["dials"]["variance"], 2)
        self.assertEqual(brief["dials"]["motion"], 1)
        self.assertEqual(brief["dials"]["density"], 2)

    def test_archetype_override_harmonization(self) -> None:
        brief = self.engine.infer_brief("Generic prompt", archetype_override="haute_editorial_modernism")
        self.assertEqual(brief["archetype"], AestheticArchetype.HAUTE_EDITORIAL_MODERNISM.value)
        self.assertIn("Haute Editorial Modernism", brief["design_read"])
        self.assertIn("PP Editorial New", brief["typography"]["display"])

    def test_archetype_from_str_normalization(self) -> None:
        self.assertEqual(AestheticArchetype.from_str("cyber-obsidian-monolith"), AestheticArchetype.CYBER_OBSIDIAN_MONOLITH)
        self.assertEqual(AestheticArchetype.from_str("Haute Editorial Modernism"), AestheticArchetype.HAUTE_EDITORIAL_MODERNISM)
        self.assertEqual(AestheticArchetype.from_str("SWISS_PRECISION_VIGNELLI"), AestheticArchetype.SWISS_PRECISION_VIGNELLI)
        self.assertEqual(AestheticArchetype.from_str("kinetic spatial hud"), AestheticArchetype.KINETIC_SPATIAL_HUD)
        self.assertIsNone(AestheticArchetype.from_str("nonexistent_style"))

    def test_empty_prompt_defaults(self) -> None:
        brief = self.engine.infer_brief("")
        self.assertTrue(brief["archetype"])
        self.assertTrue(brief["design_read"])
        self.assertIn("Design Read:", brief["design_read"])


class TestAwwwardsScaffoldGenerator(unittest.TestCase):
    """Test award-winning layout scaffolding and 7-layer optical depth generation."""

    def setUp(self) -> None:
        self.generator = AwwwardsScaffoldGenerator()

    def test_scaffold_generation_and_zero_slop_compliance(self) -> None:
        res = self.generator.generate_scaffold("Frontier AI algorithmic execution broker")
        self.assertTrue(res["anti_slop_verified"])
        self.assertTrue(res["audit_result"]["clean"])
        self.assertEqual(res["audit_result"]["score"], 1.0)

        # Verify 7-Layer Optical Depth components in output
        html = res["html_layout"]
        self.assertIn("feTurbulence", html)  # Layer 1: SVG Micro-grain noise
        self.assertIn("radial", html.lower())  # Layer 2: Volumetric lighting
        self.assertIn("backdrop-blur", html)  # Layer 3: Refractive glass substrate
        self.assertIn("border-[var(--color-border-hairline)]", html)  # Layer 4: Hairline specular rim
        self.assertIn("min-h-[100dvh]", html)  # Viewport stability
        self.assertNotIn("h-screen", html)  # Zero mobile jump
        self.assertIn("whitespace-nowrap", html)  # Single line CTA
        self.assertIn("grid", html)  # Asymmetric Bento layout

    def test_scaffold_archetype_override(self) -> None:
        res = self.generator.generate_scaffold("Minimalist website", archetype_override="haute_editorial_modernism")
        self.assertEqual(res["archetype"], "haute_editorial_modernism")
        self.assertIn("PP Editorial New", res["tailwind_v4_theme"])
        self.assertIn("Haute Editorial Modernism", res["design_read"])


class TestPreFlightDesignGate(unittest.TestCase):
    """Test 5-point pre-flight design verification checklist."""

    def setUp(self) -> None:
        self.gate = PreFlightDesignGate()
        self.scaffold = AwwwardsScaffoldGenerator()

    def test_clean_scaffold_passes_gate(self) -> None:
        res_scaffold = self.scaffold.generate_scaffold("High performance database telemetry")
        val = self.gate.validate_design(res_scaffold["html_layout"])
        self.assertTrue(val["approved"])
        self.assertEqual(val["passed_checks"], 5)
        self.assertEqual(val["total_checks"], 5)
        self.assertGreaterEqual(val["composite_score"], 0.95)

    def test_failing_code_rejected(self) -> None:
        bad_code = """
        <section class="h-screen bg-gradient-to-tr from-purple-500 to-indigo-500 blur-3xl">
          <h1>Supercharge your next-gen AI</h1>
          <div class="flex gap-2">
            <span class="w-3 h-3 rounded-full bg-red-500"></span>
            <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
          </div>
        </section>
        """
        val = self.gate.validate_design(bad_code)
        self.assertFalse(val["approved"])
        self.assertLess(val["passed_checks"], 5)

    def test_preflight_gate_rejects_naked_outline_none(self) -> None:
        code_with_naked_outline = """
        <div class="min-h-[100dvh]">
          <button class="whitespace-nowrap outline-none">Action</button>
        </div>
        """
        val = self.gate.validate_design(code_with_naked_outline)
        self.assertFalse(val["approved"])
        chk4 = next(c for c in val["checklist"] if c["point"] == 4)
        self.assertFalse(chk4["passed"])

    def test_preflight_gate_accepts_focus_visible_before_outline_none(self) -> None:
        code_with_accessible_focus = """
        <div class="min-h-[100dvh]">
          <button class="whitespace-nowrap focus-visible:ring-2 focus-visible:ring-blue-500 outline-none px-4 py-2">
            Action
          </button>
        </div>
        """
        val = self.gate.validate_design(code_with_accessible_focus)
        chk4 = next(c for c in val["checklist"] if c["point"] == 4)
        self.assertTrue(chk4["passed"])


class TestCoderFleetDispatcherDesignRouting(unittest.TestCase):
    """Test CoderFleetDispatcher routing to all 6 design actions."""

    def setUp(self) -> None:
        self.dispatcher = CoderFleetDispatcher()

    def test_all_design_actions_registered(self) -> None:
        actions = self.dispatcher.list_actions()
        self.assertIn("audit_anti_slop", actions)
        self.assertIn("infer_design_brief", actions)
        self.assertIn("generate_design_tokens", actions)
        self.assertIn("generate_awwwards_scaffold", actions)
        self.assertIn("validate_preflight_design", actions)
        self.assertIn("list_design_archetypes", actions)

    def test_dispatch_audit_anti_slop(self) -> None:
        res = self.dispatcher.dispatch("audit_anti_slop", {"code": "<div class='min-h-[100dvh]'></div>"})
        self.assertTrue(res["success"])
        self.assertTrue(res["result"]["clean"])

    def test_dispatch_infer_design_brief(self) -> None:
        res = self.dispatcher.dispatch("infer_design_brief", {"prompt": "cybernetic aerospace avionics"})
        self.assertTrue(res["success"])
        self.assertEqual(res["result"]["archetype"], "cyber_obsidian_monolith")

    def test_dispatch_generate_design_tokens(self) -> None:
        res = self.dispatcher.dispatch("generate_design_tokens", {"archetype": "swiss_precision_vignelli"})
        self.assertTrue(res["success"])
        self.assertIn("Neue Haas Grotesk", res["result"]["typography"]["font_display"])

    def test_dispatch_generate_awwwards_scaffold(self) -> None:
        res = self.dispatcher.dispatch("generate_awwwards_scaffold", {"prompt": "Luxury watchmaker"})
        self.assertTrue(res["success"])
        self.assertTrue(res["result"]["anti_slop_verified"])

    def test_dispatch_validate_preflight_design(self) -> None:
        res = self.dispatcher.dispatch("validate_preflight_design", {"code": "<div class='min-h-[100dvh]'></div>"})
        self.assertTrue(res["success"])
        self.assertTrue(res["result"]["approved"])

    def test_dispatch_list_design_archetypes(self) -> None:
        res = self.dispatcher.dispatch("list_design_archetypes", {})
        self.assertTrue(res["success"])
        self.assertEqual(len(res["result"]), 6)

    def test_dispatch_with_parameter_aliases(self) -> None:
        # html alias for audit_anti_slop
        r1 = self.dispatcher.dispatch("audit_anti_slop", {"html": "<div class='min-h-[100dvh]'></div>"})
        self.assertTrue(r1["success"])
        self.assertTrue(r1["result"]["clean"])

        # content alias for validate_preflight_design
        r2 = self.dispatcher.dispatch("validate_preflight_design", {"content": "<div class='min-h-[100dvh]'></div>"})
        self.assertTrue(r2["success"])
        self.assertTrue(r2["result"]["approved"])

        # user_prompt alias for infer_design_brief
        r3 = self.dispatcher.dispatch("infer_design_brief", {"user_prompt": "realtime kubernetes telemetry"})
        self.assertTrue(r3["success"])
        self.assertEqual(r3["result"]["archetype"], "kinetic_spatial_hud")

        # name alias for generate_design_tokens
        r4 = self.dispatcher.dispatch("generate_design_tokens", {"name": "cold_chromatic_luxury"})
        self.assertTrue(r4["success"])
        self.assertEqual(r4["result"]["archetype"], "cold_chromatic_luxury")

        # user_prompt alias for generate_awwwards_scaffold
        r5 = self.dispatcher.dispatch("generate_awwwards_scaffold", {"user_prompt": "Titanium horology"})
        self.assertTrue(r5["success"])
        self.assertTrue(r5["result"]["anti_slop_verified"])


class TestFableEngineDesignActionHandlers(unittest.TestCase):
    """Test fable-engine server action handlers for design actions."""

    def test_handle_audit_anti_slop(self) -> None:
        out = _handle_audit_anti_slop({"code": "<div class='min-h-[100dvh]'>Valid layout</div>"})
        self.assertIn("Anti-Slop Design Audit", out)
        self.assertIn("CLEAN", out)

    def test_handle_infer_design_brief(self) -> None:
        out = _handle_infer_design_brief({"prompt": "modern developer cockpit"})
        self.assertIn("Brief Inference & Design Read", out)
        self.assertIn("Kinetic Spatial HUD", out)

    def test_handle_infer_design_brief_with_overrides(self) -> None:
        out = _handle_infer_design_brief({
            "prompt": "Modern interface",
            "archetype_override": "swiss_precision_vignelli",
            "dials_override": {"variance": 2, "motion": 1, "density": 3},
        })
        self.assertIn("Swiss Precision", out)
        self.assertIn("Variance `2` / Motion `1` / Density `3`", out)

    def test_handle_generate_design_tokens(self) -> None:
        out = _handle_generate_design_tokens({"archetype": "haute_editorial_modernism"})
        self.assertIn("Haute Design Tokens", out)
        self.assertIn("Editorial", out)
        self.assertIn("@theme", out)

    def test_handle_generate_awwwards_scaffold(self) -> None:
        out = _handle_generate_awwwards_scaffold({"prompt": "Enterprise data platform"})
        self.assertIn("Awwwards-Caliber Zero-Slop Scaffold Generated", out)
        self.assertIn("100% CLEAN", out)

    def test_handle_validate_preflight_design(self) -> None:
        out = _handle_validate_preflight_design({"code": "<div class='min-h-[100dvh]'>Valid</div>"})
        self.assertIn("5-Point Pre-Flight Design Gate", out)
        self.assertIn("PRE-FLIGHT APPROVED", out)

    def test_handle_list_design_archetypes(self) -> None:
        out = _handle_list_design_archetypes({})
        self.assertIn("Haute Aesthetic Archetypes", out)
        self.assertIn("cyber_obsidian_monolith", out)
        self.assertIn("haute_editorial_modernism", out)
        self.assertIn("swiss_precision_vignelli", out)

    def test_dispatch_via_handle_fable_session(self) -> None:
        out = handle_fable_session({"action": "list_design_archetypes"})
        self.assertIn("Haute Aesthetic Archetypes", out)
        self.assertNotIn("Unknown action", out)


if __name__ == "__main__":
    unittest.main()


