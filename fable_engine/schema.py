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
    "title": "Fable session, evidence, and review workflow",
    "description": (
        "Runs one Fable operation selected by `action`. Use it for Fable sessions, gates, "
        "evidence/proofs, review rubrics, checkpoints, compression, design audits, research "
        "scrapers, and explicitly experimental System 3 operations; use browser_* tools for "
        "web-page navigation and interaction. Start stateful workflows with `create_session` "
        "and a `session_name`; later session actions reuse that name. Only fields documented "
        "for the selected action are read, and missing or invalid inputs return an `Error:` "
        "message without raising an MCP transport error. Status/list/telemetry/get/view/check "
        "operations are read-only. Create, log, record, set, advance, checkpoint, restore, "
        "track, evaluate, register, compress/accumulate, evolve, generate, and scraper "
        "operations can persist Fable state or artifacts. `unlock_execution` remains blocked "
        "until its time and rationale gates pass; `apply_auto_update` can replace installed "
        "Fable files. The result is action-specific human-readable text in `result`; inspect "
        "that text for success or `Error:` before continuing."
    ),
    "annotations": {
        "title": "Fable session, evidence, and review workflow",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "outputSchema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Action-specific result text. Failures begin with `Error:`."
            }
        },
        "required": ["result"],
        "additionalProperties": False,
    },
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
                    "adjudicate_evidence",
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
                "description": "Source-code string input. Loaded and probed in an isolated subprocess sandbox (process boundary, resource limits, per-call timeout)."
            },
            "code_snippet": {
                "type": "string",
                "description": "Alternative alias for source-code string input. Executed in the isolated subprocess sandbox."
            },
            "entrypoint": {
                "type": "string",
                "description": "Optional function name to probe inside the target source for red-team review. Auto-detected when the source defines exactly one public function."
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
                "description": "Remediated source-code string input. Executed in the isolated subprocess sandbox."
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
                    "description": "Timeout in seconds for page load (maximum 30 seconds).",
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_navigate",
        "title": "Navigate current browser session",
        "annotations": {"title": "Navigate current browser session", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Loads `url` into an existing browser session, replacing its current document and adding a history entry. Use this instead of browser_open when continuing in a known session; if `session_id` is omitted, the active session is reused or a default session is created. It waits up to `timeout` seconds and returns the resulting URL, title, viewport, scroll position, and indexed elements; network, timeout, size, and parse failures return an error object without changing committed page state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL to navigate to."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."},
                "timeout": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": MAX_BROWSER_OPEN_TIMEOUT_SECONDS,
                    "default": DEFAULT_BROWSER_OPEN_TIMEOUT_SECONDS,
                    "description": "Timeout in seconds for page load (maximum 30 seconds).",
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_click",
        "description": "Navigates to the href of a link element by its stable element ID. Elements without an href are unsupported.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Stable element ID of an href-bearing link."},
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            },
            "required": ["element_id"]
        }
    },
    {
        "name": "browser_type",
        "title": "Replace text field value",
        "annotations": {"title": "Replace text field value", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Replaces the full value of a text-like input or textarea identified by `element_id`; it does not submit the form. Use browser_press for single-key edits or activation. An omitted `session_id` targets the active/default session. Returns status `typed`, the element ID, and the supplied text; missing or non-editable elements return an error object and are not changed.",
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
        "title": "Capture layered page snapshots",
        "annotations": {"title": "Capture layered page snapshots", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Captures up to `max_layers` PNGs from the top of the current document, one 1280x800 viewport per layer, without changing the session scroll position. Use this for multi-viewport page coverage; use browser_screenshot for only the current viewport. An omitted `session_id` targets the active/default session. Returns layer count, offsets, dimensions, and base64 PNG data; `max_layers` defaults to 3 and is capped at 10.",
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
        "title": "Capture current viewport",
        "annotations": {"title": "Capture current viewport", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Captures one 1280x800 PNG of the current viewport without navigation or scroll changes. Use this for the visible region; use browser_snapshot_layers for multi-viewport coverage. An omitted `session_id` targets the active/default session. Returns one layer with its offset, dimensions, and base64 PNG data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_close",
        "title": "Close browser session",
        "annotations": {"title": "Close browser session", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Closes and permanently discards one in-memory browser session, including its current document and history; persistent profile cookies remain saved. Use it when that tab is no longer needed. `session_id` targets a specific session; if omitted, the active session is closed. Returns `closed`, or `not_found` without changing another session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_back",
        "title": "Go back in browser history",
        "annotations": {"title": "Go back in browser history", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Loads the previous history entry in the active or named browser session without adding a new history entry. Use it for history traversal rather than browser_navigate. If history is already at its first entry, it is a no-op that returns current page status. A navigation failure returns an error and preserves the history index; omitting `session_id` reuses or creates the active/default session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional browser tab/session identifier."}
            }
        }
    },
    {
        "name": "browser_forward",
        "title": "Go forward in browser history",
        "annotations": {"title": "Go forward in browser history", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "outputSchema": {"type": "object", "additionalProperties": True},
        "description": "Loads the next history entry in the active or named browser session without adding a new history entry. Use it after browser_back rather than browser_navigate. If no forward entry exists, it is a no-op that returns current page status. A navigation failure returns an error and preserves the history index; omitting `session_id` reuses or creates the active/default session.",
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
        "description": "Edits supported text controls, moves focus with Tab, or activates links with Enter.",
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
