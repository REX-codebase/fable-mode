"""
MCP Tool Schemas for Fable Engine.
Defines the JSON Schema contract for the fable_session tool.
"""

from __future__ import annotations

from fable_engine.browser import (
    DEFAULT_BROWSER_OPEN_TIMEOUT_SECONDS,
    MAX_BROWSER_OPEN_TIMEOUT_SECONDS,
)
from fable_engine.session import PHASES

TOOL_SCHEMA = {
    "name": "fable_session",
    "description": (
        "Fable Cognitive Engine Session & Telemetry Manager for MCP-compatible agent hosts.\n"
        "Enforces DeepThink cognitive rigor, hard mechanical time-lock, anti-rush execution lockout, epistemic truth logging (PROVEN/HYPOTHESIS/UNKNOWN),\n"
        "formal domain invariant modeling, continuous rethink-refine cycles, phased progression gating, subagent delegation contract compilation,\n"
        "live user-controlled time-budgeted pacing telemetry, token compression subsystem (Content-Addressed Storage, 0.003 tokens/character invariant),\n"
        "and System 3 Meta-Cognitive Deliberation & Dialectical Evolutionary Architecture (Pearl do-calculus, TRIZ contradiction synthesis, 10D Pareto genetic search, axiom induction)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_session",
                    "set_timer",
                    "get_status",
                    "telemetry",
                    "advance_phase",
                    "log_epistemic_item",
                    "record_invariant",
                    "log_refinement_cycle",
                    "unlock_execution",
                    "checkpoint_session",
                    "restore_session",
                    "list_sessions",
                    "compile_delegation_contract",
                    "compress_payload",
                    "decompress_payload",
                    "view_slice",
                    "accumulate_payload",
                    "flush_accumulator",
                    "get_compression_stats",
                    "system3_dialectical_synthesis",
                    "system3_causal_simulate",
                    "system3_evolve_paradigms",
                    "system3_induce_axioms",
                    "system3_meta_reflect",
                    "system3_tri_level_orchestrate",
                    "system3_hyperbolic_embed",
                    "system3_kripke_verify",
                    "system3_active_inference",
                    "system3_proof_oracle",
                    "track_file_change",
                    "get_session_lineage",
                    "inspect_plan",
                    "verify_proof",
                    "record_visual_mockups",
                    "validate_event_history",
                    "set_goal_rubric",
                    "evaluate_goal_rubric",
                    "get_goal_rubric",
                    "register_automation_pipeline",
                    "red_team_code_review",
                    "record_breakage_report",
                    "verify_red_team_remediation",
                    "cortical_define_lobe",
                    "cortical_list_lobes",
                    "check_auto_update",
                    "apply_auto_update",
                    "evolve_cortex",
                    "audit_anti_slop",
                    "infer_design_brief",
                    "generate_design_tokens",
                    "generate_awwwards_scaffold",
                    "validate_preflight_design",
                    "list_design_archetypes",
                    "scrape_web",
                    "scrape_youtube",
                    "scrape_reddit",
                    "scrape_x",
                    "scrape_github",
                    "scrape_arxiv"
                ],
                "description": "The Fable session action to perform."
            },
            "session_name": {
                "type": "string",
                "description": "Unique identifier / name for the Fable session."
            },
            "objective": {
                "type": "string",
                "description": "High-level goal or problem statement for the reasoning session."
            },
            "time_budget_minutes": {
                "type": "number",
                "description": "Immutable outer authority budget in minutes. set_timer can only change the internal pacing timer."
            },
            "next_phase": {
                "type": "string",
                "enum": PHASES,
                "description": "Target phase to advance the session into."
            },
            "phase_summary": {
                "type": "string",
                "description": "Concise summary of findings or deliverables completed in the previous phase."
            },
            "tag": {
                "type": "string",
                "enum": ["PROVEN", "HYPOTHESIS", "UNKNOWN"],
                "description": "Epistemic classification tag for truth calibration."
            },
            "claim": {
                "type": "string",
                "description": "Fact, hypothesis statement, or unknown parameter to track in epistemic ledger."
            },
            "evidence": {
                "type": "string",
                "description": "Source file, command output, line number, or URL supporting the claim."
            },
            "invariant_name": {
                "type": "string",
                "description": "Identifier or title of the formal invariant (e.g., 'INV-01: Zero-Deadlock Ring Buffer')."
            },
            "formal_statement": {
                "type": "string",
                "description": "Mathematical or formal contract specification that must never be violated."
            },
            "proof_or_rationale": {
                "type": "string",
                "description": "Proof sketch, rationale, or inductive argument establishing the invariant."
            },
            "domain": {
                "type": "string",
                "description": "Domain boundary for the invariant or cortical plasticity consolidation."
            },
            "refinement_type": {
                "type": "string",
                "description": "Type of rethink-refine cycle (e.g. 'archetype_exploration', 'triz_resolution', 'adversarial_falsification', 'benchmark_probe', 'failure_mode_analysis')."
            },
            "focus_area": {
                "type": "string",
                "description": "Specific subsystem, component, algorithm, or interface being critically re-evaluated."
            },
            "critique_or_bottleneck": {
                "type": "string",
                "description": "Critical flaw, vulnerability, edge case, memory/latency bottleneck, or assumption scrutinized."
            },
            "architectural_refinement": {
                "type": "string",
                "description": "Concrete architectural evolution, optimization, or algorithm change derived from the critique."
            },
            "terminal_probe_results": {
                "type": "string",
                "description": "Live empirical probe output, benchmark figures, latency numbers, or profiling stats supporting the refinement."
            },
            "artifact_path": {
                "type": "string",
                "description": "Absolute filesystem path to blueprint artifact, proof, or benchmark script documenting the refinement."
            },
            "rationale": {
                "type": "string",
                "description": "Justification for unlocking code execution after satisfying cognitive gates."
            },
            "subagent_prompt": {
                "type": "string",
                "description": "The delegation prompt or contract text for the subagent to validate."
            },
            "content": {
                "type": "string",
                "description": "Raw text content or payload to store/compress into Content-Addressed Storage (CAS)."
            },
            "payload": {
                "type": "string",
                "description": "Micro-payload text for adaptive batch accumulator or CAS storage."
            },
            "cas_ref": {
                "type": "string",
                "description": "CAS reference URI (cas://<sha256_hex>) or 64-char hash."
            },
            "start_line": {
                "type": "integer",
                "description": "Starting line number (1-indexed inclusive) for windowed line slice viewing."
            },
            "end_line": {
                "type": "integer",
                "description": "Ending line number (1-indexed inclusive) for windowed line slice viewing."
            },
            "include_line_numbers": {
                "type": "boolean",
                "description": "Whether to format line slice with line numbers."
            },
            "label": {
                "type": "string",
                "description": "Optional label or description for compressed CAS node."
            },
            "force_flush": {
                "type": "boolean",
                "description": "Force flush buffered micro-payloads immediately into a composite frame."
            },
            "metadata": {
                "type": "object",
                "description": "Optional metadata dictionary attached to accumulated micro-payload."
            },
            "thesis_title": {
                "type": "string",
                "description": "Title of the thesis paradigm for System 3 dialectical synthesis."
            },
            "thesis_description": {
                "type": "string",
                "description": "Core architecture description and assumptions for the thesis candidate."
            },
            "antithesis_title": {
                "type": "string",
                "description": "Title of the antithesis / adversarial critique."
            },
            "contradictions": {
                "description": "List of parameter trade-offs / contradictions to resolve with TRIZ principles.",
                "type": ["array", "string"]
            },
            "failure_modes": {
                "description": "List of adversarial failure modes identified in critique.",
                "type": ["array", "string"]
            },
            "max_debate_rounds": {
                "type": "integer",
                "description": "Maximum number of dialectical debate rounds for synthesis (default 4)."
            },
            "target_residual_threshold": {
                "type": "number",
                "description": "Target residual contradiction score threshold for convergence (default 0.15)."
            },
            "model_name": {
                "type": "string",
                "description": "Name for the causal DAG model in System 3 simulation."
            },
            "nodes": {
                "description": "List of node dictionaries for Causal DAG construction.",
                "type": ["array", "string"]
            },
            "edges": {
                "description": "List of directed edge dictionaries for Causal DAG construction.",
                "type": ["array", "string"]
            },
            "interventions": {
                "description": "Dictionary of Pearl's do-operator interventions: {node_id: value}.",
                "type": ["object", "string"]
            },
            "target_metric": {
                "type": "string",
                "description": "Target KPI node ID for sensitivity and structural brittleness analysis."
            },
            "generations": {
                "type": "integer",
                "description": "Number of evolutionary generations to run (default 3)."
            },
            "population_size": {
                "type": "integer",
                "description": "Population size for evolutionary gene pool (default 12)."
            },
            "mutation_rate": {
                "type": "number",
                "description": "Genetic mutation rate probability (default 0.15)."
            },
            "crossover_rate": {
                "type": "number",
                "description": "Genetic crossover rate probability (default 0.80)."
            },
            "seed_paradigms": {
                "description": "Optional list of initial paradigm definitions to seed the gene pool.",
                "type": ["array", "string"]
            },
            "objective_weights": {
                "description": "Optional dictionary of weights across the 10 Pareto dimensions.",
                "type": ["object", "string"]
            },
            "task_complexity": {
                "type": "number",
                "description": "Task complexity index [0.0, 1.0] for tri-level cognitive arbitration."
            },
            "contradiction_density": {
                "type": "number",
                "description": "Contradiction density index [0.0, 1.0] for cognitive gear shifting."
            },
            "failure_count": {
                "type": "integer",
                "description": "Historical failure count for tri-level cognitive gear arbitration."
            },
            "epistemic_uncertainty": {
                "type": "number",
                "description": "Epistemic uncertainty index [0.0, 1.0] for arbitration."
            },
            "tree": {
                "description": "Tree hierarchy adjacency list or nested dict for hyperbolic embedding.",
                "type": ["object", "array", "string"]
            },
            "root_id": {
                "type": "string",
                "description": "Root node ID for hyperbolic tree embedding or initial world."
            },
            "dimension": {
                "type": "integer",
                "description": "Dimension of Poincaré ball manifold (default 2)."
            },
            "curvature": {
                "type": "number",
                "description": "Sectional curvature c > 0 of Poincaré manifold (default 1.0)."
            },
            "base_step": {
                "type": "number",
                "description": "Base geodesic step distance for hyperbolic tree embedding (default 1.0)."
            },
            "node_labels": {
                "description": "Optional mapping of node IDs to readable labels.",
                "type": ["object", "string"]
            },
            "worlds": {
                "description": "List of world/state definitions for Kripke structure.",
                "type": ["array", "string"]
            },
            "transitions": {
                "description": "List of transitions or adjacency dictionary for Kripke structure.",
                "type": ["array", "object", "string"]
            },
            "formula": {
                "type": "string",
                "description": "CTL / modal formula string to verify against Kripke structure (e.g. 'AG(safe)', 'EF(goal)')."
            },
            "initial_world": {
                "type": "string",
                "description": "Initial world ID for Kripke model checking."
            },
            "observation": {
                "type": "string",
                "description": "Current sensory observation for Active Inference belief updating."
            },
            "policies": {
                "description": "List of candidate action sequence policies for Expected Free Energy evaluation.",
                "type": ["array", "string"]
            },
            "gamma": {
                "type": "number",
                "description": "Policy precision inverse temperature gamma for Active Inference softmax (default 16.0)."
            },
            "states": {
                "description": "List of hidden state identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "observations": {
                "description": "List of observation identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "actions": {
                "description": "List of control action identifiers for Active Inference POMDP.",
                "type": ["array", "string"]
            },
            "a_matrix": {
                "description": "Observation likelihood matrix A [O x S] for Active Inference.",
                "type": ["array", "string"]
            },
            "b_matrices": {
                "description": "State transition matrices B [Action -> S x S] for Active Inference.",
                "type": ["object", "string"]
            },
            "c_preferences": {
                "description": "Prior preference distribution C over observations for Active Inference.",
                "type": ["array", "string"]
            },
            "d_prior": {
                "description": "Prior initial state belief distribution D for Active Inference.",
                "type": ["array", "string"]
            },
            "context": {
                "description": "Hypothesis typing context dictionary {name: type} for proof oracle.",
                "type": ["object", "string"]
            },
            "axioms": {
                "description": "List of reference axiom names or strings for proof oracle.",
                "type": ["array", "string"]
            },
            "file_path": {
                "type": "string",
                "description": "Target file path for file change tracking or proof verification."
            },
            "change_type": {
                "type": "string",
                "enum": ["modified", "created", "deleted", "slated"],
                "description": "Classification of file change."
            },
            "diff_summary": {
                "type": "string",
                "description": "Concise summary of file changes, diff, or slated edits."
            },
            "affected_invariants": {
                "description": "List or string of invariant names affected by this file change.",
                "type": ["array", "string"]
            },
            "proof_type": {
                "type": "string",
                "enum": ["ast", "receipt", "file_sha256", "formal_logic", "vector_coordinates"],
                "description": "Deterministic proof type."
            },
            "target_resource": {
                "type": "string",
                "description": "Target resource (file path, receipt ID) for proof verification."
            },
            "mockups": {
                "description": "List of concept dictionaries for visual mockup recording.",
                "type": ["array", "string"]
            },
            "selected_concept": {
                "type": "string",
                "description": "Identifier of the selected visual concept archetype."
            },
            "task_objective": {
                "type": "string",
                "description": "Task objective or target outcome for goal scoring rubric."
            },
            "criteria": {
                "description": "List of criteria pointers or JSON string of rubric items for goal score evaluation.",
                "type": ["array", "string", "object"]
            },
            "target_score": {
                "type": "number",
                "description": "Target composite goal score threshold (default 0.95, min 0.0, max 1.0)."
            },
            "rubric_id": {
                "type": "string",
                "description": "Identifier of the goal rubric."
            },
            "item_evaluations": {
                "description": "Item evaluations mapping, list, or JSON string with pointer_id, satisfied, score, evidence_receipt_id.",
                "type": ["array", "object", "string"]
            },
            "name": {
                "type": "string",
                "description": "Name identifier for automation pipeline spec."
            },
            "pipeline_name": {
                "type": "string",
                "description": "Alternative alias for automation pipeline name."
            },
            "pipeline_type": {
                "type": "string",
                "description": "Type of autonomous pipeline (default 'closed_loop')."
            },
            "generator_command": {
                "type": "string",
                "description": "Shell command or tool invocation for candidate generator."
            },
            "generator_cmd": {
                "type": "string",
                "description": "Alias for generator_command: shell command or tool invocation for candidate generator."
            },
            "evaluator_command": {
                "type": "string",
                "description": "Shell command or tool invocation for candidate evaluator."
            },
            "evaluator_cmd": {
                "type": "string",
                "description": "Alias for evaluator_command: shell command or tool invocation for candidate evaluator."
            },
            "evaluations": {
                "description": "Alias for item_evaluations: list or dict of criterion evaluation updates.",
                "type": ["array", "object", "string"]
            },
            "target_threshold": {
                "type": "number",
                "description": "Target threshold score for pipeline iteration termination (default 0.95)."
            },
            "max_iterations": {
                "type": "integer",
                "description": "Maximum closed-loop iterations before halting (default 10)."
            },
            "target_name": {
                "type": "string",
                "description": "Identifier or name of the target module, class, or function for red-team review."
            },
            "target_code": {
                "type": "string",
                "description": "Source-code string input. Dynamic target execution from source-code strings is disabled and requires a separate sandboxed executor."
            },
            "code_snippet": {
                "type": "string",
                "description": "Alternative alias for source-code string input. Dynamic target execution from source-code strings is disabled and requires a separate sandboxed executor."
            },
            "custom_hypotheses": {
                "description": "List or JSON string of custom adversarial hypotheses / attack vectors.",
                "type": ["array", "string"]
            },
            "broken_scenarios": {
                "description": "List or JSON string of broken attack scenarios found during red-team review.",
                "type": ["array", "string"]
            },
            "remediated_code": {
                "type": "string",
                "description": "Remediated source-code string input. Dynamic target execution from source-code strings is disabled and requires a separate sandboxed executor."
            },
            "prior_report": {
                "description": "Prior red-team breakage report dictionary or JSON string to verify remediation against.",
                "type": ["object", "string"]
            },
            "task_id": {
                "type": "string",
                "description": "Task identifier for cortical plasticity consolidation or session lineage."
            },
            "code": {
                "type": "string",
                "description": "Source code content (HTML, JSX, CSS, or TSX) to audit or validate against anti-slop gates."
            },
            "archetype": {
                "type": "string",
                "enum": [
                    "cyber_obsidian_monolith",
                    "haute_editorial_modernism",
                    "swiss_precision_vignelli",
                    "kinetic_spatial_hud",
                    "neo_nordic_warmth",
                    "cold_chromatic_luxury"
                ],
                "description": "Haute aesthetic archetype identifier for design tokens or scaffolding."
            },
            "archetype_override": {
                "type": "string",
                "description": "Optional override for Haute aesthetic archetype."
            },
            "dials_override": {
                "type": "object",
                "description": "Optional discrete dials override: variance (1-10), motion (1-10), density (1-10)."
            },
            "user_prompt": {
                "type": "string",
                "description": "Alias for prompt: high-level design prompt describing desired web experience."
            },
            "target": {
                "type": "string",
                "description": "Target URL, ID, subreddit, repo, paper ID, handle, or search query string for research scraping actions."
            },
            "auto_log_epistemic": {
                "type": "boolean",
                "description": "Whether to automatically record retrieved research findings as a [HYPOTHESIS] candidate item in Fable Session's epistemic ledger for subsequent cross-verification."
            }
        },
        "required": ["action"]
    }
}

BROWSER_TOOL_SCHEMAS = [
    {
        "name": "browser_open",
        "description": "Opens a URL in the stealth agent browser using persistent local logins/profile (<=20 MB RAM ceiling). Supports local dev servers across all languages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL or localhost address to open."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."},
                "timeout": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": MAX_BROWSER_OPEN_TIMEOUT_SECONDS,
                    "default": DEFAULT_BROWSER_OPEN_TIMEOUT_SECONDS,
                    "description": "Timeout in seconds for page load.",
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_navigate",
        "description": "Navigates the browser session to a new URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to navigate to."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_click",
        "description": "Clicks an interactive element by its stable element ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Stable element ID to click."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["element_id"]
        }
    },
    {
        "name": "browser_type",
        "description": "Types text into an input field identified by its stable element ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Stable element ID to type into."},
                "text": {"type": "string", "description": "Text content to enter into element."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["element_id", "text"]
        }
    },
    {
        "name": "browser_scroll",
        "description": "Scrolls the page vertically by delta pixels.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delta_y": {"type": "integer", "description": "Vertical pixel scroll offset."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["delta_y"]
        }
    },
    {
        "name": "browser_snapshot_layers",
        "description": "Captures N sequential screen-sized viewport PNG snapshots (1 layer = 1 PC viewport height, 1280x800 px).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_layers": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Maximum number of screen-sized viewport layers to capture (default 3)."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_screenshot",
        "description": "Captures a single viewport PNG snapshot of the current scroll position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_close",
        "description": "Closes an active browser tab session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_back",
        "description": "Navigates back in history for the browser session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_forward",
        "description": "Navigates forward in history for the browser session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_wait",
        "description": "Waits for a specified duration in seconds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "minimum": 0, "maximum": 10, "description": "Seconds to wait."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["seconds"]
        }
    },
    {
        "name": "browser_press",
        "description": "Presses a keyboard key on an element or active window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Keyboard key to press (e.g. 'Enter', 'Tab')."},
                "element_id": {"type": "string", "description": "Optional element ID target."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["key"]
        }
    },
    {
        "name": "browser_reload",
        "description": "Reloads the current page in the browser session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    }
]
