"""System 3 meta-cognitive deliberation, evolutionary, and dialectical action handlers."""
from __future__ import annotations

import collections
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("fable-engine.actions.system3")

from fable_engine.session import (
    ACTIVE_SESSIONS,
    PHASES,
    SESSIONS_DIR,
    SILENT_DELIBERATION_REMINDER,
    FableSession,
    SessionState,
    _validate_session_name,
    _validate_time_budget,
    get_or_load_session,
)
# System 3 classes are lazily imported inside each handler to ensure near-instantaneous server startup

def _handle_system3_dialectical_synthesis(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import ThesisCandidate, AntithesisCritique, Contradiction, TRIZPrinciple, TRIZContradictionResolver, DialecticalSynthesizer
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_dialectical_synthesis'."
    thesis_title = arguments.get("thesis_title") or arguments.get("title") or "Architectural Thesis"
    thesis_desc = arguments.get("thesis_description") or arguments.get("description") or arguments.get("thesis") or "Primary architectural candidate."
    antithesis_title = arguments.get("antithesis_title") or arguments.get("critique_title") or arguments.get("critique") or "Adversarial Critique"

    raw_contradictions = arguments.get("contradictions") or arguments.get("contradiction_list") or []
    parsed_contradictions = []
    if isinstance(raw_contradictions, str):
        try:
            loaded = json.loads(raw_contradictions)
            if isinstance(loaded, list):
                raw_contradictions = loaded
            elif isinstance(loaded, dict):
                raw_contradictions = [loaded]
        except Exception:
            raw_contradictions = [
                {"improving_parameter": "performance", "worsening_parameter": "safety", "description": line.strip(), "severity": 0.7}
                for line in raw_contradictions.splitlines() if line.strip()
            ]

    if isinstance(raw_contradictions, list):
        for idx, c in enumerate(raw_contradictions):
            if isinstance(c, dict):
                parsed_contradictions.append(Contradiction(
                    contradiction_id=c.get("contradiction_id", f"c_{idx+1:03d}"),
                    improving_parameter=c.get("improving_parameter", "performance"),
                    worsening_parameter=c.get("worsening_parameter", "safety"),
                    description=c.get("description", "Architectural trade-off"),
                    severity=float(c.get("severity", 0.7)),
                ))
            elif isinstance(c, str):
                parsed_contradictions.append(Contradiction(
                    contradiction_id=f"c_{idx+1:03d}",
                    improving_parameter="performance",
                    worsening_parameter="safety",
                    description=c,
                    severity=0.7,
                ))

    failure_modes = arguments.get("failure_modes") or []
    if isinstance(failure_modes, str):
        try:
            failure_modes = json.loads(failure_modes)
        except Exception:
            failure_modes = [f.strip() for f in failure_modes.splitlines() if f.strip()]

    thesis = ThesisCandidate(
        thesis_id=f"th_{session_name}_{int(time.time()*1000)%10000}",
        title=thesis_title,
        description=thesis_desc,
    )
    critique = AntithesisCritique(
        critique_id=f"cr_{session_name}_{int(time.time()*1000)%10000}",
        thesis_id=thesis.thesis_id,
        title=antithesis_title,
        contradictions=parsed_contradictions,
        failure_modes=failure_modes if isinstance(failure_modes, list) else [str(failure_modes)],
        severity_score=float(arguments.get("severity_score", 0.75)),
    )

    max_rounds = int(arguments.get("max_debate_rounds", 4))
    threshold = float(arguments.get("target_residual_threshold", 0.15))

    synthesizer = DialecticalSynthesizer()
    synthesis = synthesizer.synthesize(
        thesis, critique, max_debate_rounds=max_rounds, target_residual_threshold=threshold
    )

    session = get_or_load_session(session_name)
    session.system3_syntheses.append(synthesis.to_dict())

    session.log_refinement_cycle(
        refinement_type="system3_dialectical_synthesis",
        focus_area=f"{thesis_title} vs {antithesis_title}",
        critique_or_bottleneck=f"Contradictions: {len(parsed_contradictions)} parameter conflicts analyzed.",
        architectural_refinement=synthesis.pareto_improvement_claim,
    )
    session.save()

    principles_list = "\n".join([f"- **TRIZ Principle #{p.number} ({p.name})**: {p.description}" for p in synthesis.transcended_principles]) or "- No principles transcended."
    contra_list = "\n".join([f"- `{c.improving_parameter}` vs `{c.worsening_parameter}`: {c.description} (Severity: {c.severity})" for c in synthesis.resolved_contradictions]) or "- None declared."

    return (
        f"### ⚡ System 3 Dialectical Synthesis Emerged\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Synthesis Title**: **{synthesis.title}** (`{synthesis.synthesis_id}`)\n"
        f"- **Debate Rounds Executed**: `{synthesis.debate_rounds_executed}`\n"
        f"- **Initial Contradiction Severity**: `{synthesis.initial_contradiction_score:.2f}`\n"
        f"- **Residual Contradiction Severity**: `{synthesis.residual_contradiction_score:.2f}`\n"
        f"- **Convergence Achieved**: `{'✅ YES' if synthesis.convergence_achieved else '⚠️ PARTIAL'}`\n\n"
        f"#### 🧬 Transcended TRIZ Inventive Principles:\n{principles_list}\n\n"
        f"#### ⚔️ Resolved Contradictions:\n{contra_list}\n\n"
        f"#### 🏛️ Synthesized Architectural Blueprint:\n{synthesis.synthesized_architecture}\n\n"
        f"> [!TIP]\n"
        f"> {synthesis.pareto_improvement_claim}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_causal_simulate(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import CausalDAG, CausalNode, CausalEdge, CausalNodeType
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_causal_simulate'."
    model_name = arguments.get("model_name", "System3CausalModel")
    nodes_input = arguments.get("nodes", [])
    edges_input = arguments.get("edges", [])
    interventions_input = arguments.get("interventions", {})
    target_metric = arguments.get("target_metric")

    if isinstance(nodes_input, str):
        try:
            nodes_input = json.loads(nodes_input)
        except Exception:
            nodes_input = []
    if isinstance(edges_input, str):
        try:
            edges_input = json.loads(edges_input)
        except Exception:
            edges_input = []
    if isinstance(interventions_input, str):
        try:
            interventions_input = json.loads(interventions_input)
        except Exception:
            interventions_input = {}

    dag = CausalDAG(name=model_name)
    for n in nodes_input:
        if isinstance(n, dict):
            dag.add_node(
                node_id=n.get("node_id", n.get("id")),
                name=n.get("name"),
                node_type=CausalNodeType(n.get("node_type", "endogenous")),
                value=float(n.get("value", 0.0)),
                default_value=float(n["default_value"]) if "default_value" in n else None,
                min_value=float(n["min_value"]) if "min_value" in n else None,
                max_value=float(n["max_value"]) if "max_value" in n else None,
                description=n.get("description", ""),
            )

    for e in edges_input:
        if isinstance(e, dict):
            dag.add_edge(
                source=e["source"],
                target=e["target"],
                weight=float(e.get("weight", 1.0)),
                relation_type=e.get("relation_type", "linear"),
                description=e.get("description", ""),
            )

    is_acyclic, cycle = dag.check_acyclicity()
    if not is_acyclic:
        return f"Error: Graph contains a cycle: {' -> '.join(cycle)}. Causal models must be valid DAGs."

    topo_order = dag.topological_sort()
    factual_values = dag.compute_forward()

    interv_res = None
    if interventions_input and isinstance(interventions_input, dict):
        interv_map = {k: float(v) for k, v in interventions_input.items()}
        interv_res = dag.do_intervention(interv_map)

    brittleness_rep = None
    if target_metric and target_metric in dag.nodes:
        brittleness_rep = dag.evaluate_brittleness(target_metric)

    session = get_or_load_session(session_name)
    new_graph_entry = {
        "dag": dag.to_dict(),
        "nodes": dag.to_dict().get("nodes", []),
        "edges": dag.to_dict().get("edges", []),
        "topological_order": topo_order,
        "factual_values": factual_values,
        "intervention": interv_res.to_dict() if interv_res else None,
        "brittleness": brittleness_rep.to_dict() if brittleness_rep else None,
        "timestamp": time.time(),
    }
    if len(session.system3_causal_graphs) == 1 and session.system3_causal_graphs[0].get("dag", {}).get("name") == f"Session_{session.session_name}_DAG":
        session.system3_causal_graphs[0] = new_graph_entry
    else:
        session.system3_causal_graphs.append(new_graph_entry)
    session.save()

    lines = [
        f"### 🌐 System 3 Pearl's Do-Calculus & Causal Simulation\n\n",
        f"- **Model**: `{dag.name}` ({len(dag.nodes)} nodes, {len(dag.edges)} directed causal edges)\n",
        f"- **Topological Order**: `{' -> '.join(topo_order)}`\n",
    ]

    if interv_res:
        lines.append(f"\n#### ✂️ Pearl's Do-Operator Intervention: `do({interv_res.interventions})`\n")
        lines.append(f"- **Severed Edges**: `{len(interv_res.severed_edges)}` ({interv_res.severed_edges})\n")
        lines.append(f"- **Impacted Nodes**: `{', '.join(interv_res.impacted_nodes)}`\n\n")
        lines.append("| Node | Factual Value | Counterfactual Value | Delta (Δ) |\n")
        lines.append("|---|---|---|---|\n")
        for nid in topo_order:
            f_val = interv_res.original_values.get(nid, 0.0)
            cf_val = interv_res.counterfactual_values.get(nid, 0.0)
            delta = interv_res.deltas.get(nid, 0.0)
            delta_str = f"+{delta:.4f}" if delta > 0 else f"{delta:.4f}"
            lines.append(f"| `{nid}` | {f_val:.4f} | **{cf_val:.4f}** | `{delta_str}` |\n")

    if brittleness_rep:
        lines.append(f"\n#### 🔬 Structural Brittleness Report (`{brittleness_rep.target_metric}`)\n")
        lines.append(f"- **Overall Brittleness Score**: `{brittleness_rep.overall_brittleness_score:.4f}` / 1.0\n")
        spof_str = ", ".join(brittleness_rep.single_points_of_failure) if brittleness_rep.single_points_of_failure else "None (Resilient)"
        lines.append(f"- **Single Points of Failure**: `{spof_str}`\n")
        for rec in brittleness_rep.recommendations:
            lines.append(f"- 💡 {rec}\n")

    if session.execution_locked:
        lines.append(SILENT_DELIBERATION_REMINDER)

    return "".join(lines)


def _handle_system3_evolve_paradigms(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import CognitiveGenome, CognitiveGenePool
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_evolve_paradigms'."
    generations = int(arguments.get("generations", 3))
    pop_size = int(arguments.get("population_size", 12))
    mutation_rate = float(arguments.get("mutation_rate", 0.15))
    crossover_rate = float(arguments.get("crossover_rate", 0.80))
    seed_paradigms = arguments.get("seed_paradigms")
    if isinstance(seed_paradigms, str):
        try:
            seed_paradigms = json.loads(seed_paradigms)
        except Exception:
            seed_paradigms = None

    weights = arguments.get("objective_weights")
    if isinstance(weights, str):
        try:
            weights = json.loads(weights)
        except Exception:
            weights = None

    pool = CognitiveGenePool(
        population_size=pop_size,
        mutation_rate=mutation_rate,
        crossover_rate=crossover_rate,
    )
    pool.initialize_population(seed_paradigms=seed_paradigms)

    for _ in range(generations):
        pool.evolve_generation()

    pareto_frontier = pool.get_pareto_frontier()
    best_genome = pool.get_best_genome(weights)

    session = get_or_load_session(session_name)
    session.system3_gene_pools.append(pool.to_dict())

    session.log_refinement_cycle(
        refinement_type="system3_evolutionary_optimization",
        focus_area=f"10D Pareto Frontier Search across {generations} generations",
        critique_or_bottleneck=f"Optimized {pop_size} genomes across 10 dimensions.",
        architectural_refinement=f"Evolved top paradigm '{best_genome.paradigm_name}' with scalar fitness {best_genome.compute_scalar_fitness(weights):.4f}.",
    )
    session.save()

    table_rows = []
    for g in pareto_frontier[:5]:
        f = g.fitness_scores
        table_rows.append(
            f"| `{g.genome_id}` | **{g.paradigm_name[:24]}** | `{f.get('latency',0):.2f}` | "
            f"`{f.get('throughput',0):.2f}` | `{f.get('memory_efficiency',0):.2f}` | "
            f"`{f.get('fault_tolerance',0):.2f}` | `{f.get('modularity',0):.2f}` | "
            f"`{f.get('security',0):.2f}` | `{f.get('token_compaction',0):.2f}` | `{g.compute_scalar_fitness(weights):.4f}` |"
        )

    table_str = "\n".join(table_rows)

    return (
        f"### 🧬 System 3 Evolutionary Paradigm Engine\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Generations Evolved**: `{pool.generation_count}` (Population: `{len(pool.population)}`)\n"
        f"- **Rank 1 Pareto Frontier Size**: `{len(pareto_frontier)}` non-dominated solutions\n"
        f"- **Top Archetype**: **{best_genome.paradigm_name}** (`{best_genome.genome_id}`)\n\n"
        f"#### 🏆 Top Rank 1 Non-Dominated Pareto Frontier:\n"
        f"| ID | Paradigm | Lat | Tput | Mem | Fault | Mod | Sec | Token | Score |\n"
        f"|---|---|---|---|---|---|---|---|---|---|\n"
        f"{table_str}\n\n"
        f"#### 🧬 Winning Gene Allocation (`{best_genome.genome_id}`):\n"
        + "\n".join([f"- **{k}**: `{v}`" for k, v in best_genome.genes.items()])
        + f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_induce_axioms(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import NeuroSymbolicAxiom, AxiomProvenance, AxiomStatus, MetaProofInducer
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_induce_axioms'."
    session = get_or_load_session(session_name)
    domain = arguments.get("domain", "architecture")

    inducer = MetaProofInducer()
    axioms = inducer.induce_axioms_from_session(
        receipts=[],
        evidence=[],
        session_telemetry=session.get_telemetry(),
        domain_hints=[domain],
    )

    for ax in axioms:
        session.system3_axioms.append(ax.to_dict())
        if not any(i.get("name") == ax.name for i in session.invariants):
            session.record_invariant(
                invariant_name=ax.name,
                formal_statement=ax.symbolic_expression,
                proof_or_rationale=ax.proof_sketch or ax.natural_language,
                domain=ax.domain if ax.domain in ("architecture", "design", "coding") else "architecture",
            )

    session.save()

    axiom_blocks = []
    for ax in axioms:
        axiom_blocks.append(
            f"#### 📜 `{ax.axiom_id}`: **{ax.name}** `[{ax.domain.upper()}]`\n"
            f"- **Symbolic Expression**: `{ax.symbolic_expression}`\n"
            f"- **Natural Language**: {ax.natural_language}\n"
            f"- **Epistemic Confidence**: `{ax.confidence * 100:.1f}%` (`{ax.status.value.upper()}`)\n"
            f"- **Proof Rationale**: {ax.proof_sketch}\n"
        )

    return (
        f"### 📐 System 3 Neuro-Symbolic Invariant Induction\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Axioms Induced**: `{len(axioms)}`\n"
        f"- **Auto-Recorded Invariants**: `{len(session.invariants)}` total in session\n\n"
        + "\n".join(axiom_blocks)
        + f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_meta_reflect(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import CognitiveBiasType, CognitiveBiasFinding, CognitiveBiasDetector, System3Executive
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_meta_reflect'."
    session = get_or_load_session(session_name)
    focus_area = arguments.get("focus_area", "Full Deliberation Trace")

    executive = System3Executive()
    report = executive.meta_reflect(session.to_dict())

    session.system3_reflections.append(report)

    bias_summary = f"{len(report['bias_findings'])} biases flagged" if report['bias_findings'] else "0 biases detected (Clean)"
    session.log_refinement_cycle(
        refinement_type="system3_meta_reflection",
        focus_area=focus_area,
        critique_or_bottleneck=f"Meta-cognitive audit: {bias_summary}. Contradiction density: {report['contradiction_density']:.2f}.",
        architectural_refinement=f"Shifted cognitive gear to {report['cognitive_gear']}. Updated search heuristics temperature: {report['updated_search_heuristics']['exploration_temperature']}.",
    )
    session.save()

    bias_lines = []
    for b in report["bias_findings"]:
        bias_lines.append(
            f"- ⚠️ **{b['bias_type'].upper()}** (Severity: `{b['severity']}` in *{b['detected_in']}*):\n"
            f"  - *Evidence*: {b['evidence_trail']}\n"
            f"  - *Mitigation*: {b['mitigation_strategy']}"
        )
    bias_block = "\n".join(bias_lines) if bias_lines else "✅ Zero cognitive biases detected. Epistemic reasoning is well-calibrated."

    directives_block = "\n".join([f"- 🎯 {d}" for d in report["directives"]])

    return (
        f"### 🧠 System 3 Meta-Cognitive Deliberation Audit\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Recommended Cognitive Gear**: `{report['cognitive_gear'].upper()}`\n"
        f"- **Contradiction Density**: `{report['contradiction_density']:.2f}`\n"
        f"- **Arbitration Rationale**: {report['arbitration_rationale']}\n\n"
        f"#### 🔍 Cognitive Bias Diagnostics:\n{bias_block}\n\n"
        f"#### 🚀 System 3 Executive Directives:\n{directives_block}\n\n"
        f"#### ⚙️ Dynamic Search Heuristics:\n"
        f"- **Exploration Temperature**: `{report['updated_search_heuristics']['exploration_temperature']}`\n"
        f"- **Pruning Cutoff Threshold**: `{report['updated_search_heuristics']['pruning_threshold']}`\n"
        f"- **Max Branching Factor**: `{report['updated_search_heuristics']['max_branching_factor']}`\n"
        f"- **Falsification Intensity**: `{report['updated_search_heuristics']['falsification_intensity']}`"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_tri_level_orchestrate(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import TriLevelArbitrator, CognitiveGear, SearchHeuristicConfig, DynamicSearchHeuristicRewriter
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_tri_level_orchestrate'."
    complexity = float(arguments.get("task_complexity", 0.75))
    density = float(arguments.get("contradiction_density", 0.60))
    failures = int(arguments.get("failure_count", 0))
    uncertainty = float(arguments.get("epistemic_uncertainty", 0.40))

    arbitrator = TriLevelArbitrator()
    decision = arbitrator.arbitrate(
        task_complexity=complexity,
        contradiction_density=density,
        failure_count=failures,
        epistemic_uncertainty=uncertainty,
    )

    session = get_or_load_session(session_name)
    session.system3_orchestrations.append({
        "decision": decision,
        "timestamp": time.time(),
        "inputs": {
            "complexity": complexity,
            "density": density,
            "failures": failures,
            "uncertainty": uncertainty,
        }
    })
    session.save()

    directives_str = "\n".join([f"- {d}" for d in decision["directives"]])

    return (
        f"### 🎛️ System 3 Tri-Level Cognitive Arbitration\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Recommended Operating Gear**: `⚙️ {decision['recommended_gear'].upper()}`\n"
        f"- **Composite Difficulty Index**: `{decision['composite_difficulty']:.3f}` / 1.0\n"
        f"- **Arbitration Rationale**: {decision['rationale']}\n\n"
        f"#### 🧭 Prescribed Cognitive Action Directives:\n{directives_str}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_hyperbolic_embed(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import PoincareBall, HyperbolicPoint, HyperbolicTreeEmbedder
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_hyperbolic_embed'."
    tree_input = arguments.get("tree")
    if tree_input is None:
        return "Error: 'tree' is required for action 'system3_hyperbolic_embed'."
    if isinstance(tree_input, str):
        try:
            tree_input = json.loads(tree_input)
        except Exception:
            return "Error: Failed to parse 'tree' as JSON."

    root_id = arguments.get("root_id")
    dimension = int(arguments.get("dimension", 2))
    curvature = float(arguments.get("curvature", 1.0))
    base_step = float(arguments.get("base_step", 1.0))
    node_labels = arguments.get("node_labels")
    if isinstance(node_labels, str):
        try:
            node_labels = json.loads(node_labels)
        except Exception:
            node_labels = None

    embedder = HyperbolicTreeEmbedder(dimension=dimension, curvature=curvature, base_step_distance=base_step)
    result = embedder.embed_hierarchy(tree=tree_input, root_id=root_id, node_labels=node_labels)

    session = get_or_load_session(session_name)
    session.system3_hyperbolic_embeddings.append(result.to_dict())

    session.log_refinement_cycle(
        refinement_type="system3_hyperbolic_embedding",
        focus_area=f"Hierarchical Poincaré Manifold Embedding ({result.total_nodes} nodes, depth {result.tree_depth})",
        critique_or_bottleneck=f"Embedded hierarchy into {dimension}D Poincaré ball with curvature c={curvature:.2f}.",
        architectural_refinement=(
            f"Manifold tree embedding verified: avg_distortion={result.average_distortion:.4f}, "
            f"max_distortion={result.max_distortion:.4f}, stress={result.stress:.4f}, "
            f"exponential capacity ratio={result.hierarchical_capacity_ratio:.2f}x."
        ),
    )
    session.save()

    node_table = []
    for nid, node in list(result.nodes.items())[:10]:
        coords_str = f"({', '.join([f'{c:.4f}' for c in node.coords])})"
        node_table.append(
            f"| `{node.node_id}` | **{node.label[:20]}** | `{node.depth}` | `{node.subtree_size}` | `{coords_str}` |"
        )
    node_table_str = "\n".join(node_table)

    return (
        f"### 🌐 System 3 Poincaré Hyperbolic Manifold Embedding\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Manifold**: Poincaré Ball $\\mathbb{{B}}^{{{result.dimension}}}_{{c={result.curvature:.2f}}}$\n"
        f"- **Hierarchy**: Root `{result.root_id}` ({result.total_nodes} nodes, max depth `{result.tree_depth}`)\n"
        f"- **Mean Metric Distortion**: `{result.average_distortion:.4f}` (Max: `{result.max_distortion:.4f}`)\n"
        f"- **Metric Stress Metric**: `{result.stress:.4f}`\n"
        f"- **Hyperbolic Volume Expansion Ratio**: `{result.hierarchical_capacity_ratio:.2f}x` vs Euclidean $\\mathbb{{R}}^{{{result.dimension}}}$\n\n"
        f"#### 📍 Top Embedded Nodes in $\\mathbb{{B}}^{{{result.dimension}}}$:\n"
        f"| Node ID | Label | Depth | Subtree | Poincaré Coordinates |\n"
        f"|---|---|---|---|---|\n"
        f"{node_table_str}\n"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_kripke_verify(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import KripkeStructure, KripkeWorld, KripkeModelChecker
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_kripke_verify'."
    formula = arguments.get("formula", "").strip()
    if not formula:
        return "Error: 'formula' is required for action 'system3_kripke_verify'."
    model_name = arguments.get("model_name", "System3KripkeModel")
    worlds_input = arguments.get("worlds", [])
    transitions_input = arguments.get("transitions", [])
    initial_world = arguments.get("initial_world")

    if isinstance(worlds_input, str):
        try:
            worlds_input = json.loads(worlds_input)
        except Exception:
            worlds_input = []
    if isinstance(transitions_input, str):
        try:
            transitions_input = json.loads(transitions_input)
        except Exception:
            transitions_input = []

    structure = KripkeStructure(name=model_name)
    for w in worlds_input:
        if isinstance(w, dict):
            structure.add_world(
                world_id=w.get("world_id", w.get("id")),
                propositions=w.get("propositions", w.get("props", [])),
                name=w.get("name", ""),
                is_initial=w.get("is_initial", False),
                metadata=w.get("metadata", {}),
            )
        elif isinstance(w, str):
            structure.add_world(world_id=w)

    if isinstance(transitions_input, dict):
        for src, targets in transitions_input.items():
            for tgt in (targets if isinstance(targets, list) else [targets]):
                structure.add_transition(src, tgt)
    elif isinstance(transitions_input, list):
        for t in transitions_input:
            if isinstance(t, dict) and "source" in t and "target" in t:
                structure.add_transition(t["source"], t["target"])
            elif isinstance(t, (list, tuple)) and len(t) >= 2:
                structure.add_transition(str(t[0]), str(t[1]))

    checker = KripkeModelChecker(structure)
    res = checker.check(formula=formula, initial_world=initial_world)

    session = get_or_load_session(session_name)
    session.system3_kripke_verifications.append(res.to_dict())

    session.log_refinement_cycle(
        refinement_type="system3_kripke_verification",
        focus_area=f"Modal / CTL Verification: {res.formula}",
        critique_or_bottleneck=f"Evaluated Kripke model '{structure.name}' ({res.total_worlds} worlds).",
        architectural_refinement=(
            f"Model checking result: {'✅ SATISFIED' if res.is_satisfied else '❌ VIOLATED'}. "
            f"Satisfied worlds: {len(res.satisfied_worlds)}/{res.total_worlds}. "
            f"Witness/Counterexample: {res.witness_path or res.counterexample_path}."
        ),
    )
    session.save()

    trace_block = ""
    if res.counterexample_path:
        trace_block = f"\n#### ❌ Counterexample Violation Trace:\n`{' -> '.join(res.counterexample_path)}`\n"
    elif res.witness_path:
        trace_block = f"\n#### ✅ Witness Path:\n`{' -> '.join(res.witness_path)}`\n"

    return (
        f"### 🛡️ System 3 Kripke Modal Model Verification\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Model**: `{structure.name}` ({res.total_worlds} worlds)\n"
        f"- **Formula**: `{res.formula}`\n"
        f"- **Status**: `{'✅ SATISFIED' if res.is_satisfied else '❌ VIOLATED'}` at initial world `{res.initial_world}`\n"
        f"- **Satisfied Worlds**: `{', '.join(res.satisfied_worlds) if res.satisfied_worlds else 'None'}`\n"
        f"- **Violated Worlds**: `{', '.join(res.violated_worlds) if res.violated_worlds else 'None'}`\n"
        f"{trace_block}\n"
        f"> [!TIP]\n"
        f"> {res.details}"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_active_inference(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import ActiveInferenceEngine, GenerativeModel, Policy, create_default_architecture_pomdp
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_active_inference'."
    obs = arguments.get("observation", "HIGH_THROUGHPUT_CLEAN").strip()
    gamma = float(arguments.get("gamma", 16.0))
    policies_input = arguments.get("policies")
    if isinstance(policies_input, str):
        try:
            policies_input = json.loads(policies_input)
        except Exception:
            policies_input = None

    parsed_policies = []
    if policies_input and isinstance(policies_input, list):
        for p in policies_input:
            if isinstance(p, dict) and "policy_id" in p and "actions" in p:
                parsed_policies.append(Policy.from_dict(p))
            elif isinstance(p, str):
                parsed_policies.append(Policy(policy_id=f"pol_{p}", actions=[p]))

    # Check if custom model components provided
    states = arguments.get("states")
    observations = arguments.get("observations")
    actions = arguments.get("actions")
    a_mat = arguments.get("a_matrix")
    b_mats = arguments.get("b_matrices")
    c_pref = arguments.get("c_preferences")
    d_prior = arguments.get("d_prior")

    if all(x is not None for x in [states, observations, actions, a_mat, b_mats, c_pref, d_prior]):
        if isinstance(states, str): states = json.loads(states)
        if isinstance(observations, str): observations = json.loads(observations)
        if isinstance(actions, str): actions = json.loads(actions)
        if isinstance(a_mat, str): a_mat = json.loads(a_mat)
        if isinstance(b_mats, str): b_mats = json.loads(b_mats)
        if isinstance(c_pref, str): c_pref = json.loads(c_pref)
        if isinstance(d_prior, str): d_prior = json.loads(d_prior)
        gen_model = GenerativeModel(
            states=states,
            observations=observations,
            actions=actions,
            a_matrix=a_mat,
            b_matrices=b_mats,
            c_preferences=c_pref,
            d_prior=d_prior,
        )
    else:
        gen_model = create_default_architecture_pomdp()

    engine = ActiveInferenceEngine(generative_model=gen_model, policy_precision_gamma=gamma)
    report = engine.select_action(observation=obs, candidate_policies=parsed_policies)

    session = get_or_load_session(session_name)
    session.system3_active_inferences.append(report.to_dict())

    session.log_refinement_cycle(
        refinement_type="system3_active_inference",
        focus_area=f"Free Energy Minimization for observation '{obs}'",
        critique_or_bottleneck=(
            f"Variational Free Energy F={report.variational_free_energy_f:.4f} "
            f"(Complexity KL={report.complexity_kl:.4f}, Accuracy={report.accuracy_log_likelihood:.4f})."
        ),
        architectural_refinement=(
            f"Selected optimal policy '{report.selected_policy.policy_id}' ({report.selected_action}) "
            f"with Expected Free Energy G={report.selected_policy.expected_free_energy_g:.4f}, "
            f"Information Gain={report.selected_policy.epistemic_information_gain:.4f}, "
            f"Goal Utility={report.selected_policy.pragmatic_goal_utility:.4f}."
        ),
    )
    session.save()

    policy_table = []
    for p in report.evaluated_policies:
        opt_mark = "🏆 OPTIMAL" if p.is_optimal else ""
        policy_table.append(
            f"| `{p.policy_id}` | `{p.actions}` | `{p.expected_free_energy_g:.4f}` | "
            f"`{p.risk_pragmatic_divergence:.4f}` | `{p.ambiguity_expected_entropy:.4f}` | "
            f"`{p.epistemic_information_gain:.4f}` | `{p.pragmatic_goal_utility:.4f}` | "
            f"`{p.probability * 100:.1f}%` | {opt_mark} |"
        )
    pol_table_str = "\n".join(policy_table)

    belief_table = "\n".join([f"- **{k}**: `{v * 100:.1f}%`" for k, v in report.belief_state.items()])

    return (
        f"### ⚡ System 3 Friston Active Inference & Variational Free Energy\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Ingested Observation**: `{report.current_observation}`\n"
        f"- **Variational Free Energy (F)**: `{report.variational_free_energy_f:.4f}` (Surprisal Bound)\n"
        f"  - *Complexity (KL)*: `{report.complexity_kl:.4f}`\n"
        f"  - *Accuracy (Log-Likelihood)*: `{report.accuracy_log_likelihood:.4f}`\n"
        f"- **Selected Policy**: **{report.selected_policy.policy_id}** -> Action: `🎯 {report.selected_action}`\n\n"
        f"#### 🧠 Updated Hidden State Belief Distribution $q(s)$:\n{belief_table}\n\n"
        f"#### 📊 Evaluated Policy Landscape ($G(\\pi) = \\text{{Risk}} + \\text{{Ambiguity}}$):\n"
        f"| Policy ID | Actions | EFE ($G$) | Risk | Ambiguity | Epistemic Info Gain | Goal Utility | Prob | Status |\n"
        f"|---|---|---|---|---|---|---|---|---|\n"
        f"{pol_table_str}\n"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


def _handle_system3_proof_oracle(arguments: Dict[str, Any]) -> str:
    from fable_v2.system3 import ProofOracle, CurryHowardVerifier, UndecidabilityDetector, TacticsEngine, ProofStatus, FormalProofResult, Prop, Implies, And, App, Pair, Fst, Snd, Inl, Inr, Case, Refl, Abort
    action = arguments.get("action", "").strip().lower()
    session_name = arguments.get("session_name", "").strip()
    session: Optional[FableSession] = None
    if not session_name:
        return "Error: 'session_name' is required for action 'system3_proof_oracle'."
    claim = arguments.get("claim")
    if not claim:
        return "Error: 'claim' is required for action 'system3_proof_oracle'."

    context = arguments.get("context")
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except Exception:
            context = None

    axioms = arguments.get("axioms")
    if isinstance(axioms, str):
        try:
            axioms = json.loads(axioms)
        except Exception:
            axioms = None

    oracle = ProofOracle()
    res = oracle.verify_proposition(claim=claim, context=context, axioms=axioms)

    session = get_or_load_session(session_name)
    session.system3_proof_oracle_verifications.append(res.to_dict())

    # Auto-record invariant if proved and sound
    if res.status == ProofStatus.DECIDABLE_PROVED and res.is_sound:
        inv_name = f"INV-ORACLE: {str(claim)[:32]}"
        if not any(i.get("name") == inv_name for i in session.invariants):
            session.record_invariant(
                invariant_name=inv_name,
                formal_statement=res.proposition,
                proof_or_rationale=f"Curry-Howard Constructive Proof Term: {res.proof_term_repr}",
                domain="architecture",
            )

    session.log_refinement_cycle(
        refinement_type="system3_proof_oracle",
        focus_area=f"Curry-Howard Constructive Proof: {res.proposition}",
        critique_or_bottleneck=f"Evaluated status: {res.status.value.upper()}.",
        architectural_refinement=(
            f"Proof Oracle verdict: {res.status.value.upper()} (Sound: {res.is_sound}). "
            f"Proof Term: {res.proof_term_repr or 'None'}."
        ),
    )
    session.save()

    steps_str = "\n".join([f"- {s}" for s in res.verification_steps])
    undec_str = ""
    if res.undecidability_diagnostics:
        undec_str = (
            f"\n#### 🛑 Gödelian Boundary Diagnostics:\n"
            f"- **Boundary Type**: `{res.undecidability_diagnostics.get('boundary_type')}`\n"
            f"- **Explanation**: {res.undecidability_diagnostics.get('explanation')}\n"
        )

    return (
        f"### 📜 System 3 Gödelian Auto-Formalizing Proof Oracle\n\n"
        f"- **Session**: `{session.session_name}`\n"
        f"- **Proposition**: `{res.proposition}`\n"
        f"- **Decision Status**: `{'✅ ' if res.status == ProofStatus.DECIDABLE_PROVED else '⚡ ' if res.status == ProofStatus.DECIDABLE_REFUTED else '🛑 '}{res.status.value.upper()}`\n"
        f"- **Soundness Verified**: `{'✅ TRUE' if res.is_sound else '❌ UNVERIFIED'}`\n"
        + (f"- **Constructive Proof Term**: `{res.proof_term_repr}`\n" if res.proof_term_repr else "")
        + f"{undec_str}\n"
        f"#### 🔍 Verification Trace:\n{steps_str}\n"
        f"{SILENT_DELIBERATION_REMINDER if session.execution_locked else ''}"
    )


