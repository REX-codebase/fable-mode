"""System 3 Causal Deliberation & Pearl's Do-Calculus Engine.

Provides structural causal models (SCM), Directed Acyclic Graph (DAG) validation,
Pearl's do-calculus interventions (graph surgery), counterfactual branch isolation,
and multi-dimensional brittleness/sensitivity analysis. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import copy
import hashlib
import json
import math


class CausalCycleError(Exception):
    """Raised when a cycle is detected in a causal graph that must be a DAG."""
    pass


class CausalNodeNotFoundError(Exception):
    """Raised when a referenced causal node does not exist."""
    pass


class CausalNodeType(str, Enum):
    """Classification of causal variables in the structural model."""
    EXOGENOUS = "exogenous"      # External constraint, input, or background parameter
    ENDOGENOUS = "endogenous"    # Internal computed state / intermediate variable
    INTERVENTION = "intervention" # Variable explicitly set via do-operator
    METRIC = "metric"            # Observable KPI / outcome of interest


@dataclass
class CausalEdge:
    """Directed causal dependency from source to target node."""
    source: str
    target: str
    weight: float = 1.0
    relation_type: str = "linear"  # "linear", "inverse", "threshold", "probabilistic", "custom"
    delay_ms: float = 0.0
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CausalEdge":
        return cls(**data)


@dataclass
class CausalNode:
    """Variable node in the Causal DAG."""
    node_id: str
    name: str
    node_type: CausalNodeType = CausalNodeType.ENDOGENOUS
    value: float = 0.0
    default_value: float = 0.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    equation_description: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def clamp_value(self, val: float) -> float:
        """Clamp value to defined bounds if specified."""
        if self.min_value is not None:
            val = max(self.min_value, val)
        if self.max_value is not None:
            val = min(self.max_value, val)
        return val

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["node_type"] = self.node_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CausalNode":
        data_copy = dict(data)
        if "node_type" in data_copy and isinstance(data_copy["node_type"], str):
            data_copy["node_type"] = CausalNodeType(data_copy["node_type"])
        return cls(**data_copy)


@dataclass
class InterventionResult:
    """Result of applying Pearl's do-operator do(X=x)."""
    interventions: Dict[str, float]
    original_values: Dict[str, float]
    counterfactual_values: Dict[str, float]
    deltas: Dict[str, float]
    severed_edges: List[Tuple[str, str]]
    impacted_nodes: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrittlenessReport:
    """Sensitivity and single-point-of-failure analysis of the causal model."""
    target_metric: str
    overall_brittleness_score: float  # [0.0, 1.0] (0 = resilient, 1 = hyper-fragile)
    single_points_of_failure: List[str]
    node_sensitivities: Dict[str, float]  # Absolute delta in target per unit perturbation
    critical_paths: List[List[str]]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CausalDAG:
    """
    Structural Causal Model (SCM) Directed Acyclic Graph.
    Implements Pearl's do-calculus, cycle detection, topological sorting,
    counterfactual branch isolation, and sensitivity analysis.
    """

    def __init__(self, name: str = "CausalModel"):
        self.name = name
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[CausalEdge] = []
        self._adjacency: Dict[str, List[CausalEdge]] = {}
        self._reverse_adjacency: Dict[str, List[CausalEdge]] = {}
        self._custom_evaluators: Dict[str, Callable[[Dict[str, float]], float]] = {}

    def add_node(
        self,
        node_id: str,
        name: Optional[str] = None,
        node_type: CausalNodeType = CausalNodeType.ENDOGENOUS,
        value: float = 0.0,
        default_value: Optional[float] = None,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        description: str = "",
        equation_description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CausalNode:
        """Add a causal variable node to the graph."""
        clean_id = node_id.strip()
        if not clean_id:
            raise ValueError("Node ID cannot be empty.")
        if clean_id in self.nodes:
            raise ValueError(f"Node '{clean_id}' already exists in DAG.")

        node = CausalNode(
            node_id=clean_id,
            name=name.strip() if name else clean_id,
            node_type=node_type,
            value=value,
            default_value=value if default_value is None else default_value,
            min_value=min_value,
            max_value=max_value,
            description=description,
            equation_description=equation_description,
            metadata=metadata or {},
        )
        self.nodes[clean_id] = node
        self._adjacency[clean_id] = []
        self._reverse_adjacency[clean_id] = []
        return node

    def add_edge(
        self,
        source: str,
        target: str,
        weight: float = 1.0,
        relation_type: str = "linear",
        delay_ms: float = 0.0,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CausalEdge:
        """Add a directed causal edge from source to target. Verifies acyclicity."""
        if source not in self.nodes:
            raise CausalNodeNotFoundError(f"Source node '{source}' not found.")
        if target not in self.nodes:
            raise CausalNodeNotFoundError(f"Target node '{target}' not found.")
        if source == target:
            raise CausalCycleError(f"Self-loop detected on node '{source}'.")

        # Check for duplicate edge
        for e in self.edges:
            if e.source == source and e.target == target:
                raise ValueError(f"Edge from '{source}' to '{target}' already exists.")

        edge = CausalEdge(
            source=source,
            target=target,
            weight=weight,
            relation_type=relation_type,
            delay_ms=delay_ms,
            description=description,
            metadata=metadata or {},
        )
        self.edges.append(edge)
        self._adjacency[source].append(edge)
        self._reverse_adjacency[target].append(edge)

        # Validate that adding this edge preserves DAG acyclicity
        is_dag, cycle_path = self.check_acyclicity()
        if not is_dag:
            # Rollback
            self.edges.remove(edge)
            self._adjacency[source].remove(edge)
            self._reverse_adjacency[target].remove(edge)
            raise CausalCycleError(
                f"Adding edge '{source}' -> '{target}' creates a cycle: {' -> '.join(cycle_path)}"
            )

        return edge

    def register_evaluator(
        self, node_id: str, evaluator_fn: Callable[[Dict[str, float]], float]
    ) -> None:
        """Register a custom structural equation evaluator function for a node."""
        if node_id not in self.nodes:
            raise CausalNodeNotFoundError(f"Node '{node_id}' not found.")
        self._custom_evaluators[node_id] = evaluator_fn

    def get_parents(self, node_id: str) -> List[str]:
        """Return immediate causal parents of a node."""
        if node_id not in self.nodes:
            raise CausalNodeNotFoundError(f"Node '{node_id}' not found.")
        return [e.source for e in self._reverse_adjacency.get(node_id, [])]

    def get_children(self, node_id: str) -> List[str]:
        """Return immediate causal children of a node."""
        if node_id not in self.nodes:
            raise CausalNodeNotFoundError(f"Node '{node_id}' not found.")
        return [e.target for e in self._adjacency.get(node_id, [])]

    def get_ancestors(self, node_id: str) -> Set[str]:
        """Return all causal ancestor node IDs."""
        ancestors: Set[str] = set()
        queue = list(self.get_parents(node_id))
        while queue:
            curr = queue.pop(0)
            if curr not in ancestors:
                ancestors.add(curr)
                queue.extend(self.get_parents(curr))
        return ancestors

    def get_descendants(self, node_id: str) -> Set[str]:
        """Return all causal descendant node IDs."""
        descendants: Set[str] = set()
        queue = list(self.get_children(node_id))
        while queue:
            curr = queue.pop(0)
            if curr not in descendants:
                descendants.add(curr)
                queue.extend(self.get_children(curr))
        return descendants

    def check_acyclicity(self) -> Tuple[bool, List[str]]:
        """
        Check if the graph is a valid DAG using DFS three-color cycle detection.
        Returns (is_acyclic, cycle_nodes_if_any).
        """
        visited: Dict[str, int] = {nid: 0 for nid in self.nodes}  # 0: unvisited, 1: visiting, 2: visited
        parent_map: Dict[str, Optional[str]] = {nid: None for nid in self.nodes}
        cycle: List[str] = []

        def dfs(u: str) -> bool:
            visited[u] = 1
            for edge in self._adjacency.get(u, []):
                v = edge.target
                if visited[v] == 1:
                    # Cycle found - reconstruct path
                    cycle.append(v)
                    curr = u
                    while curr != v and curr is not None:
                        cycle.append(curr)
                        curr = parent_map.get(curr)
                    cycle.append(v)
                    cycle.reverse()
                    return True
                elif visited[v] == 0:
                    parent_map[v] = u
                    if dfs(v):
                        return True
            visited[u] = 2
            return False

        for node_id in self.nodes:
            if visited[node_id] == 0:
                if dfs(node_id):
                    return False, cycle

        return True, []

    def topological_sort(self) -> List[str]:
        """
        Return nodes in topological order using Kahn's algorithm.
        Raises CausalCycleError if graph contains a cycle.
        """
        in_degree: Dict[str, int] = {nid: len(self._reverse_adjacency.get(nid, [])) for nid in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: List[str] = []

        while queue:
            u = queue.pop(0)
            order.append(u)
            for edge in self._adjacency.get(u, []):
                v = edge.target
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(order) != len(self.nodes):
            raise CausalCycleError("Graph contains a cycle; topological sort impossible.")

        return order

    def compute_forward(self, initial_values: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Propagate values through the DAG along topological order.
        For each endogenous node, calculates value from its parents via registered
        evaluator or default weighted combination.
        """
        order = self.topological_sort()
        values: Dict[str, float] = {}

        # Set initial / default values
        for nid, node in self.nodes.items():
            if initial_values and nid in initial_values:
                values[nid] = node.clamp_value(float(initial_values[nid]))
            else:
                values[nid] = node.value

        for nid in order:
            node = self.nodes[nid]
            parents = self.get_parents(nid)

            if not parents:
                # Exogenous root node keeps its assigned value
                continue

            if nid in self._custom_evaluators:
                # Custom registered structural equation
                raw_val = self._custom_evaluators[nid](values)
                values[nid] = node.clamp_value(raw_val)
            else:
                # Default structural aggregation: sum(weight * parent_val)
                computed = 0.0
                for edge in self._reverse_adjacency.get(nid, []):
                    p_val = values.get(edge.source, 0.0)
                    if edge.relation_type == "linear":
                        computed += edge.weight * p_val
                    elif edge.relation_type == "inverse":
                        computed += edge.weight / (p_val if abs(p_val) > 1e-6 else 1e-6)
                    elif edge.relation_type == "threshold":
                        computed += edge.weight if p_val >= 1.0 else 0.0
                    else:
                        computed += edge.weight * p_val

                values[nid] = node.clamp_value(computed)

        return values

    def do_intervention(
        self,
        interventions: Dict[str, float],
        base_values: Optional[Dict[str, float]] = None,
    ) -> InterventionResult:
        """
        Pearl's Do-Calculus: do(X_1=x_1, X_2=x_2, ...).
        Performs graph surgery:
        1. Cuts all incoming edges to intervened nodes (severing parental dependencies).
        2. Clamps intervened nodes to target values.
        3. Propagates counterfactual consequences downstream.
        4. Calculates exact counterfactual deltas without mutating original graph state.
        """
        # Validate intervention keys
        for nid in interventions:
            if nid not in self.nodes:
                raise CausalNodeNotFoundError(f"Intervention target '{nid}' not in DAG.")

        # 1. Compute factual baseline
        factual_values = self.compute_forward(base_values)

        # 2. Build surgically modified sub-DAG
        severed_edges: List[Tuple[str, str]] = []
        impacted_nodes_set: Set[str] = set()

        for nid in interventions:
            impacted_nodes_set.add(nid)
            impacted_nodes_set.update(self.get_descendants(nid))
            for parent in self.get_parents(nid):
                severed_edges.append((parent, nid))

        # Create clone graph for counterfactual simulation
        cloned_dag = CausalDAG.from_dict(self.to_dict())

        # Sever incoming edges in the clone
        cloned_dag.edges = [e for e in cloned_dag.edges if e.target not in interventions]
        cloned_dag._rebuild_adjacency()

        # Set fixed intervention values
        cf_initial = dict(factual_values)
        for nid, val in interventions.items():
            cf_initial[nid] = val
            if nid in cloned_dag.nodes:
                cloned_dag.nodes[nid].value = val

        # 3. Propagate in surgically altered DAG
        counterfactual_values = cloned_dag.compute_forward(cf_initial)

        # 4. Compute deltas
        deltas: Dict[str, float] = {}
        for nid in self.nodes:
            f_val = factual_values.get(nid, 0.0)
            cf_val = counterfactual_values.get(nid, 0.0)
            deltas[nid] = round(cf_val - f_val, 6)

        return InterventionResult(
            interventions=interventions,
            original_values=factual_values,
            counterfactual_values=counterfactual_values,
            deltas=deltas,
            severed_edges=severed_edges,
            impacted_nodes=sorted(list(impacted_nodes_set)),
            metadata={"intervened_count": len(interventions), "total_nodes": len(self.nodes)},
        )

    def evaluate_brittleness(
        self,
        target_metric: str,
        perturbation_delta: float = 0.1,
        critical_sensitivity_threshold: float = 1.5,
    ) -> BrittlenessReport:
        """
        Evaluate structural brittleness & sensitivity of target metric.
        Identifies single points of failure (nodes with sensitivity > threshold)
        and computes normalized system brittleness score.
        """
        if target_metric not in self.nodes:
            raise CausalNodeNotFoundError(f"Target metric node '{target_metric}' not found.")

        ancestors = self.get_ancestors(target_metric)
        if not ancestors:
            return BrittlenessReport(
                target_metric=target_metric,
                overall_brittleness_score=0.0,
                single_points_of_failure=[],
                node_sensitivities={},
                critical_paths=[],
                recommendations=["Target metric has no incoming causal dependencies; structurally isolated."],
            )

        baseline_values = self.compute_forward()
        base_metric_val = baseline_values.get(target_metric, 0.0)

        sensitivities: Dict[str, float] = {}
        spof_nodes: List[str] = []

        for anc in sorted(list(ancestors)):
            orig_val = baseline_values.get(anc, 1.0)
            perturbed_val = orig_val + perturbation_delta
            interv_res = self.do_intervention({anc: perturbed_val}, base_values=baseline_values)
            new_metric_val = interv_res.counterfactual_values.get(target_metric, base_metric_val)

            # Sensitivity = abs(d_metric / d_input)
            denom = max(abs(perturbation_delta), 1e-6)
            sens = abs(new_metric_val - base_metric_val) / denom
            sensitivities[anc] = round(sens, 4)

            if sens >= critical_sensitivity_threshold:
                spof_nodes.append(anc)

        # Compute overall brittleness score [0.0, 1.0] using sigmoid of max sensitivity
        max_sens = max(sensitivities.values()) if sensitivities else 0.0
        avg_sens = sum(sensitivities.values()) / len(sensitivities) if sensitivities else 0.0
        brittleness_score = round(1.0 - math.exp(-0.5 * (max_sens + avg_sens)), 4)

        # Find critical paths to target metric
        critical_paths: List[List[str]] = []
        for spof in spof_nodes:
            path = self._find_path(spof, target_metric)
            if path:
                critical_paths.append(path)

        recommendations: List[str] = []
        if spof_nodes:
            recommendations.append(
                f"Mitigate single points of failure: {', '.join(spof_nodes)} exhibit sensitivity > {critical_sensitivity_threshold}."
            )
            recommendations.append("Apply TRIZ Principle 24 (Intermediary) or Principle 1 (Segmentation) to decouple sensitive nodes.")
        else:
            recommendations.append("System demonstrates robust structural resilience under perturbation.")

        return BrittlenessReport(
            target_metric=target_metric,
            overall_brittleness_score=brittleness_score,
            single_points_of_failure=spof_nodes,
            node_sensitivities=sensitivities,
            critical_paths=critical_paths,
            recommendations=recommendations,
        )

    def _find_path(self, start: str, end: str) -> List[str]:
        """Find a directed path from start to end using BFS."""
        queue: List[List[str]] = [[start]]
        visited: Set[str] = {start}

        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == end:
                return path
            for edge in self._adjacency.get(node, []):
                next_node = edge.target
                if next_node not in visited:
                    visited.add(next_node)
                    queue.append(path + [next_node])
        return []

    def _rebuild_adjacency(self) -> None:
        """Internal helper to rebuild adjacency indices."""
        self._adjacency = {nid: [] for nid in self.nodes}
        self._reverse_adjacency = {nid: [] for nid in self.nodes}
        for edge in self.edges:
            if edge.source in self._adjacency:
                self._adjacency[edge.source].append(edge)
            if edge.target in self._reverse_adjacency:
                self._reverse_adjacency[edge.target].append(edge)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize DAG to JSON-compatible dictionary."""
        return {
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CausalDAG":
        """Deserialize DAG from dictionary."""
        dag = cls(name=data.get("name", "CausalModel"))
        for n_data in data.get("nodes", []):
            node = CausalNode.from_dict(n_data)
            dag.nodes[node.node_id] = node
            dag._adjacency[node.node_id] = []
            dag._reverse_adjacency[node.node_id] = []
        for e_data in data.get("edges", []):
            edge = CausalEdge.from_dict(e_data)
            dag.edges.append(edge)
            dag._adjacency[edge.source].append(edge)
            dag._reverse_adjacency[edge.target].append(edge)
        return dag
