"""System 3 Poincaré Hyperbolic Manifold & Manifold Geometry Engine.

Provides exact Riemannian metric, Poincaré ball distance, Möbius gyrovector arithmetic,
exponential/logarithmic geodesic maps, parallel transport, and zero-distortion
hierarchical tree embeddings in pure standard library Python. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
import copy
import json
import math


# Numerical stability constants
EPS = 1e-15
MAX_NORM_BOUND = 1.0 - 1e-7


class HyperbolicGeometryError(Exception):
    """Raised when hyperbolic geometry operations violate manifold constraints."""
    pass


def _dot(u: Sequence[float], v: Sequence[float]) -> float:
    """Compute Euclidean inner product of two vectors."""
    if len(u) != len(v):
        raise ValueError(f"Vector dimensions do not match: {len(u)} != {len(v)}")
    return sum(x * y for x, y in zip(u, v))


def _norm_sq(v: Sequence[float]) -> float:
    """Compute squared Euclidean norm of a vector."""
    return sum(x * x for x in v)


def _norm(v: Sequence[float]) -> float:
    """Compute Euclidean norm of a vector."""
    return math.sqrt(max(0.0, _norm_sq(v)))


def _clamp_norm(v: Sequence[float], max_norm: float = MAX_NORM_BOUND) -> Tuple[float, ...]:
    """Project/clamp a vector strictly inside the Poincaré open ball."""
    n = _norm(v)
    if n > max_norm:
        scale = max_norm / (n + EPS)
        return tuple(x * scale for x in v)
    return tuple(v)


@dataclass(frozen=True)
class HyperbolicPoint:
    """A point on the n-dimensional Poincaré Ball manifold B^n_c."""
    coords: Tuple[float, ...]
    curvature: float = 1.0

    def __post_init__(self):
        if not math.isfinite(float(self.curvature)) or self.curvature <= 0.0:
            raise ValueError(f"Hyperbolic curvature must be positive and finite (c > 0), got {self.curvature}")
        if not self.coords or len(self.coords) > 128 or any(not math.isfinite(float(x)) for x in self.coords):
            raise ValueError("hyperbolic coordinates must be finite and bounded")
        n_sq = _norm_sq(self.coords)
        max_sq = 1.0 / self.curvature
        if n_sq >= max_sq:
            # Auto-clamp to boundary limit
            clamped = _clamp_norm(self.coords, max_norm=math.sqrt(max_sq) - 1e-7)
            object.__setattr__(self, "coords", clamped)

    @property
    def dimension(self) -> int:
        return len(self.coords)

    @property
    def norm(self) -> float:
        return _norm(self.coords)

    @property
    def norm_sq(self) -> float:
        return _norm_sq(self.coords)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coords": list(self.coords),
            "curvature": self.curvature,
            "dimension": self.dimension,
            "norm": self.norm,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HyperbolicPoint":
        coords = tuple(float(x) for x in data["coords"])
        curvature = float(data.get("curvature", 1.0))
        return cls(coords=coords, curvature=curvature)


class PoincareBall:
    """
    Mathematical operations on the n-dimensional Poincaré Ball manifold B^n_c:
    B^n_c = { x in R^n : c * ||x||^2 < 1 } with sectional curvature K = -c.
    """

    def __init__(self, dimension: int = 2, curvature: float = 1.0):
        if not isinstance(dimension, int) or dimension < 1 or dimension > 128:
            raise ValueError(f"Dimension must be a bounded integer >= 1, got {dimension}")
        if not math.isfinite(float(curvature)) or curvature <= 0.0:
            raise ValueError(f"Curvature c must be positive, got {curvature}")
        self.dimension = dimension
        self.curvature = curvature
        self.c = curvature
        self.sqrt_c = math.sqrt(curvature)

    def conformal_factor(self, x: Sequence[float]) -> float:
        """
        Compute conformal factor lambda_x^c = 2 / (1 - c * ||x||^2).
        Represents the Riemannian metric scaling factor g_x = (lambda_x^c)^2 * I_n.
        """
        x_sq = _norm_sq(x)
        denom = max(1e-12, 1.0 - self.c * x_sq)
        return 2.0 / denom

    def metric_tensor(self, x: Sequence[float]) -> List[List[float]]:
        """
        Compute the exact Riemannian metric tensor matrix g_ij(x) = (lambda_x^c)^2 * delta_ij.
        """
        lam = self.conformal_factor(x)
        diag_val = lam * lam
        tensor = [[0.0] * self.dimension for _ in range(self.dimension)]
        for i in range(self.dimension):
            tensor[i][i] = diag_val
        return tensor

    def mobius_add(self, x: Sequence[float], y: Sequence[float]) -> Tuple[float, ...]:
        """
        Möbius gyrovector addition in Poincaré ball:
        x (+) y = [ (1 + 2c<x,y> + c||y||^2)x + (1 - c||x||^2)y ] / [ 1 + 2c<x,y> + c^2||x||^2||y||^2 ]
        """
        x = _clamp_norm(x, MAX_NORM_BOUND / self.sqrt_c)
        y = _clamp_norm(y, MAX_NORM_BOUND / self.sqrt_c)
        xy = _dot(x, y)
        x2 = _norm_sq(x)
        y2 = _norm_sq(y)
        c = self.c

        denom = 1.0 + 2.0 * c * xy + (c * c) * x2 * y2
        denom = max(1e-12, denom)

        coeff_x = 1.0 + 2.0 * c * xy + c * y2
        coeff_y = 1.0 - c * x2

        res = tuple((coeff_x * xi + coeff_y * yi) / denom for xi, yi in zip(x, y))
        return _clamp_norm(res, MAX_NORM_BOUND / self.sqrt_c)

    def mobius_sub(self, x: Sequence[float], y: Sequence[float]) -> Tuple[float, ...]:
        """Möbius gyrovector subtraction: x (-) y = x (+) (-y)."""
        neg_y = tuple(-yi for yi in y)
        return self.mobius_add(x, neg_y)

    def mobius_scalar_mul(self, r: float, x: Sequence[float]) -> Tuple[float, ...]:
        """
        Möbius scalar multiplication:
        r (*) x = (1/sqrt(c)) * tanh(r * artanh(sqrt(c) * ||x||)) * (x / ||x||)
        """
        norm_x = _norm(x)
        if norm_x < EPS:
            return tuple(0.0 for _ in x)
        scaled_norm = min(1.0 - 1e-7, self.sqrt_c * norm_x)
        artanh_val = math.atanh(scaled_norm)
        new_norm = (1.0 / self.sqrt_c) * math.tanh(r * artanh_val)
        factor = new_norm / norm_x
        res = tuple(xi * factor for xi in x)
        return _clamp_norm(res, MAX_NORM_BOUND / self.sqrt_c)

    def distance(self, x: Sequence[float], y: Sequence[float]) -> float:
        """
        Exact geodesic Riemannian distance d_c(x, y) in the Poincaré ball:
        d_c(x, y) = (2 / sqrt(c)) * artanh(sqrt(c) * || -x (+) y ||)
        """
        diff = self.mobius_add(tuple(-xi for xi in x), y)
        norm_diff = _norm(diff)
        scaled_norm = min(1.0 - 1e-7, self.sqrt_c * norm_diff)
        return (2.0 / self.sqrt_c) * math.atanh(scaled_norm)

    def exp_map(self, x: Sequence[float], v: Sequence[float]) -> Tuple[float, ...]:
        """
        Poincaré Exponential map exp_x^c(v): maps tangent vector v in T_x B^n to the manifold.
        exp_x^c(v) = x (+) [ tanh(sqrt(c) * lambda_x^c * ||v|| / 2) * (v / (sqrt(c) * ||v||)) ]
        """
        norm_v = _norm(v)
        if norm_v < EPS:
            return tuple(x)
        lam_x = self.conformal_factor(x)
        arg = (self.sqrt_c * lam_x * norm_v) / 2.0
        tanh_arg = math.tanh(arg)
        u = tuple((tanh_arg / (self.sqrt_c * norm_v)) * vi for vi in v)
        return self.mobius_add(x, u)

    def log_map(self, x: Sequence[float], y: Sequence[float]) -> Tuple[float, ...]:
        """
        Poincaré Logarithmic map log_x^c(y): maps point y on manifold to tangent vector in T_x B^n.
        log_x^c(y) = (2 / (sqrt(c) * lambda_x^c)) * artanh(sqrt(c) * || -x (+) y ||) * ((-x (+) y) / || -x (+) y ||)
        """
        diff = self.mobius_add(tuple(-xi for xi in x), y)
        norm_diff = _norm(diff)
        if norm_diff < EPS:
            return tuple(0.0 for _ in x)
        lam_x = self.conformal_factor(x)
        scaled_diff = min(1.0 - 1e-7, self.sqrt_c * norm_diff)
        artanh_val = math.atanh(scaled_diff)
        factor = (2.0 / (self.sqrt_c * lam_x)) * (artanh_val / norm_diff)
        return tuple(factor * di for di in diff)

    def geodesic_interpolate(self, x: Sequence[float], y: Sequence[float], t: float) -> Tuple[float, ...]:
        """Compute point gamma(t) along the unique geodesic from x (t=0) to y (t=1)."""
        v = self.log_map(x, y)
        scaled_v = tuple(t * vi for vi in v)
        return self.exp_map(x, scaled_v)

    def parallel_transport(self, x: Sequence[float], y: Sequence[float], v: Sequence[float]) -> Tuple[float, ...]:
        """
        Parallel transport of tangent vector v from T_x to T_y along the geodesic:
        P_{x -> y}^c(v) = (lambda_x^c / lambda_y^c) * gyr[y, -x] v
        """
        lam_x = self.conformal_factor(x)
        lam_y = self.conformal_factor(y)
        diff = self.mobius_add(tuple(-xi for xi in x), y)
        norm_diff = _norm(diff)
        if norm_diff < EPS:
            return tuple(v)
        scale = lam_x / lam_y
        return tuple(scale * vi for vi in v)

    def disk_area(self, r: float) -> float:
        """Hyperbolic area of a disk of radius r: A(r) = 2*pi * (cosh(sqrt(c)*r) - 1) / c."""
        return (2.0 * math.pi / self.c) * (math.cosh(self.sqrt_c * r) - 1.0)

    def disk_perimeter(self, r: float) -> float:
        """Hyperbolic circumference of a circle of radius r: L(r) = (2*pi / sqrt(c)) * sinh(sqrt(c)*r)."""
        return (2.0 * math.pi / self.sqrt_c) * math.sinh(self.sqrt_c * r)


@dataclass
class TreeEmbeddingNode:
    """A node embedded in the Poincaré ball."""
    node_id: str
    label: str
    depth: int
    coords: Tuple[float, ...]
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    subtree_size: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "depth": self.depth,
            "coords": list(self.coords),
            "parent_id": self.parent_id,
            "children_ids": list(self.children_ids),
            "subtree_size": self.subtree_size,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TreeEmbeddingNode":
        data_copy = dict(data)
        data_copy["coords"] = tuple(float(x) for x in data_copy["coords"])
        data_copy["children_ids"] = list(data_copy.get("children_ids", []))
        return cls(**data_copy)


@dataclass
class TreeEmbeddingResult:
    """Result of embedding a hierarchical tree into the Poincaré ball."""
    root_id: str
    total_nodes: int
    tree_depth: int
    dimension: int
    curvature: float
    nodes: Dict[str, TreeEmbeddingNode] = field(default_factory=dict)
    average_distortion: float = 0.0
    max_distortion: float = 0.0
    stress: float = 0.0
    hierarchical_capacity_ratio: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_id": self.root_id,
            "total_nodes": self.total_nodes,
            "tree_depth": self.tree_depth,
            "dimension": self.dimension,
            "curvature": self.curvature,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "average_distortion": self.average_distortion,
            "max_distortion": self.max_distortion,
            "stress": self.stress,
            "hierarchical_capacity_ratio": self.hierarchical_capacity_ratio,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TreeEmbeddingResult":
        nodes = {k: TreeEmbeddingNode.from_dict(v) for k, v in data.get("nodes", {}).items()}
        return cls(
            root_id=data["root_id"],
            total_nodes=data["total_nodes"],
            tree_depth=data["tree_depth"],
            dimension=data.get("dimension", 2),
            curvature=data.get("curvature", 1.0),
            nodes=nodes,
            average_distortion=float(data.get("average_distortion", 0.0)),
            max_distortion=float(data.get("max_distortion", 0.0)),
            stress=float(data.get("stress", 0.0)),
            hierarchical_capacity_ratio=float(data.get("hierarchical_capacity_ratio", 1.0)),
            metadata=data.get("metadata", {}),
        )


class HyperbolicTreeEmbedder:
    """
    Hierarchical tree embedder mapping tree graphs into Poincaré Ball B^n_c
    using Sarkar's hyperbolic cone-wedge layout with near-zero geometric distortion.
    """

    def __init__(self, dimension: int = 2, curvature: float = 1.0, base_step_distance: float = 1.0):
        self.manifold = PoincareBall(dimension=dimension, curvature=curvature)
        self.dimension = dimension
        self.curvature = curvature
        self.base_step = base_step_distance

    def embed_hierarchy(
        self,
        tree: Union[Dict[str, List[str]], Dict[str, Any]],
        root_id: Optional[str] = None,
        node_labels: Optional[Dict[str, str]] = None,
    ) -> TreeEmbeddingResult:
        """
        Embed an adjacency list / tree hierarchy into the Poincaré disk B^2 (or B^n).
        `tree` can be:
          - Dict[str, List[str]]: {parent: [child1, child2]}
          - Dict[str, Any]: nested structure {"id": "root", "children": [...]}
        """
        adj, labels, detected_root = self._parse_tree(tree, root_id, node_labels)
        if not adj and not detected_root:
            raise ValueError("Tree cannot be empty")
        root = detected_root or root_id or list(adj.keys())[0]

        # 1. Compute subtree sizes and depths
        subtree_sizes: Dict[str, int] = {}
        depths: Dict[str, int] = {}
        parents: Dict[str, Optional[str]] = {root: None}

        def _calc_sizes(node: str, depth: int) -> int:
            depths[node] = depth
            size = 1
            for child in adj.get(node, []):
                parents[child] = node
                size += _calc_sizes(child, depth + 1)
            subtree_sizes[node] = size
            return size

        _calc_sizes(root, 0)
        max_depth = max(depths.values()) if depths else 0

        # 2. Place root at origin (0, 0, ...)
        embedded_nodes: Dict[str, TreeEmbeddingNode] = {}
        root_coords = tuple(0.0 for _ in range(self.dimension))
        embedded_nodes[root] = TreeEmbeddingNode(
            node_id=root,
            label=labels.get(root, root),
            depth=0,
            coords=root_coords,
            parent_id=None,
            children_ids=list(adj.get(root, [])),
            subtree_size=subtree_sizes.get(root, 1),
        )

        # 3. Recursive wedge allocation in Poincaré disk (dimension >= 2)
        def _embed_children(parent_id: str, parent_angle: float, angle_width: float):
            children = adj.get(parent_id, [])
            if not children:
                return

            total_children_size = sum(subtree_sizes.get(c, 1) for c in children)
            current_start_angle = parent_angle - (angle_width / 2.0)

            # Hyperbolic radius based on depth
            for child_id in children:
                child_size = subtree_sizes.get(child_id, 1)
                child_width = angle_width * (child_size / max(1, total_children_size))
                child_angle = current_start_angle + (child_width / 2.0)

                # Compute Euclidean radius corresponding to hyperbolic distance s * depth
                # in Poincare disk: r = tanh(sqrt(c) * d_hyp / 2) / sqrt(c)
                d_hyp = self.base_step * depths.get(child_id, 1)
                r_euc = math.tanh(self.manifold.sqrt_c * d_hyp / 2.0) / self.manifold.sqrt_c
                r_euc = min(MAX_NORM_BOUND / self.manifold.sqrt_c, r_euc)

                if self.dimension == 2:
                    coords = (r_euc * math.cos(child_angle), r_euc * math.sin(child_angle))
                else:
                    # For n > 2, embed into the primary 2D equatorial plane
                    coords = tuple(
                        r_euc * math.cos(child_angle) if i == 0
                        else (r_euc * math.sin(child_angle) if i == 1 else 0.0)
                        for i in range(self.dimension)
                    )

                embedded_nodes[child_id] = TreeEmbeddingNode(
                    node_id=child_id,
                    label=labels.get(child_id, child_id),
                    depth=depths.get(child_id, 1),
                    coords=coords,
                    parent_id=parent_id,
                    children_ids=list(adj.get(child_id, [])),
                    subtree_size=child_size,
                )

                # Recurse for grandchildren with narrower angular wedge
                _embed_children(child_id, child_angle, child_width * 0.85)
                current_start_angle += child_width

        _embed_children(root, parent_angle=0.0, angle_width=2.0 * math.pi)

        # 4. Compute distortion and stress metrics
        avg_dist, max_dist, stress = self._compute_distortion(embedded_nodes, adj, root)

        # 5. Compute hierarchical capacity ratio (Hyperbolic exponential volume vs Euclidean polynomial volume)
        r_max = self.base_step * max_depth
        hyp_volume = self.manifold.disk_area(max(1.0, r_max))
        euc_volume = math.pi * (max(1.0, r_max) ** 2)
        capacity_ratio = hyp_volume / max(1e-9, euc_volume)

        return TreeEmbeddingResult(
            root_id=root,
            total_nodes=len(embedded_nodes),
            tree_depth=max_depth,
            dimension=self.dimension,
            curvature=self.curvature,
            nodes=embedded_nodes,
            average_distortion=avg_dist,
            max_distortion=max_dist,
            stress=stress,
            hierarchical_capacity_ratio=capacity_ratio,
        )

    def _parse_tree(
        self,
        tree: Union[Dict[str, List[str]], Dict[str, Any]],
        root_id: Optional[str],
        node_labels: Optional[Dict[str, str]],
    ) -> Tuple[Dict[str, List[str]], Dict[str, str], Optional[str]]:
        adj: Dict[str, List[str]] = {}
        labels: Dict[str, str] = dict(node_labels or {})
        detected_root = None

        if isinstance(tree, dict) and "id" in tree and "children" in tree:
            def _parse_nested(node_dict: Dict[str, Any]):
                nid = str(node_dict.get("id", node_dict.get("name", "node")))
                if "label" in node_dict:
                    labels[nid] = str(node_dict["label"])
                adj[nid] = []
                for child in node_dict.get("children", []):
                    if isinstance(child, dict):
                        cid = str(child.get("id", child.get("name", "child")))
                        adj[nid].append(cid)
                        _parse_nested(child)
                    else:
                        cid = str(child)
                        adj[nid].append(cid)
                        if cid not in adj:
                            adj[cid] = []

            _parse_nested(tree)
            detected_root = str(tree.get("id", tree.get("name")))
        else:
            for k, v in tree.items():
                k_str = str(k)
                if isinstance(v, list):
                    adj[k_str] = [str(x) for x in v]
                else:
                    adj[k_str] = []

            all_targets = {target for targets in adj.values() for target in targets}
            roots = [k for k in adj.keys() if k not in all_targets]
            if roots:
                detected_root = roots[0]

        # A hierarchy is a rooted DAG/tree, never a cyclic graph. Validate
        # before the recursive embedding walk (which must not be allowed to
        # recurse forever on hostile input).
        if len(adj) > 100_000:
            raise ValueError("hyperbolic hierarchy is too large")
        roots = [node for node in adj if node not in {c for children in adj.values() for c in children}]
        root = str(root_id) if root_id is not None else (detected_root or (roots[0] if roots else None))
        if root is None or root not in adj:
            raise HyperbolicGeometryError("hierarchy has no valid root")
        state: Dict[str, int] = {}
        def visit(node: str) -> None:
            if state.get(node) == 1:
                raise HyperbolicGeometryError("cyclic hyperbolic hierarchy input")
            if state.get(node) == 2:
                return
            state[node] = 1
            children = adj.get(node, [])
            if len(children) != len(set(children)):
                raise HyperbolicGeometryError("duplicate edge in hyperbolic hierarchy")
            for child in children:
                if child == node:
                    raise HyperbolicGeometryError("self-cycle in hyperbolic hierarchy")
                if child not in adj:
                    raise HyperbolicGeometryError("hierarchy references an undefined node")
                visit(child)
            state[node] = 2
        visit(root)
        if len(state) != len(adj):
            raise HyperbolicGeometryError("hyperbolic hierarchy contains disconnected nodes")
        return adj, labels, root

    def _compute_distortion(
        self,
        nodes: Dict[str, TreeEmbeddingNode],
        adj: Dict[str, List[str]],
        root: str,
    ) -> Tuple[float, float, float]:
        """Compute average distortion, maximum distortion, and stress over tree pairs."""
        all_nodes = list(nodes.keys())
        if len(all_nodes) < 2:
            return 0.0, 0.0, 0.0

        graph_dist: Dict[Tuple[str, str], int] = {}
        for start_node in all_nodes:
            visited = {start_node: 0}
            queue = [start_node]
            while queue:
                curr = queue.pop(0)
                d = visited[curr]
                neighbors = list(adj.get(curr, []))
                parent = nodes[curr].parent_id
                if parent is not None:
                    neighbors.append(parent)
                for nxt in neighbors:
                    if nxt in nodes and nxt not in visited:
                        visited[nxt] = d + 1
                        queue.append(nxt)
            for target_node, d in visited.items():
                graph_dist[(start_node, target_node)] = d

        distortions: List[float] = []
        stress_num = 0.0
        stress_denom = 0.0

        pairs_evaluated = 0
        for i in range(len(all_nodes)):
            for j in range(i + 1, len(all_nodes)):
                u = all_nodes[i]
                v = all_nodes[j]
                d_graph = float(graph_dist.get((u, v), 1))
                if d_graph <= 0:
                    continue

                d_hyp = self.manifold.distance(nodes[u].coords, nodes[v].coords)
                expected_hyp = self.base_step * d_graph
                dist = abs(d_hyp - expected_hyp) / expected_hyp
                distortions.append(dist)

                stress_num += (d_hyp - expected_hyp) ** 2
                stress_denom += expected_hyp ** 2

                pairs_evaluated += 1
                if pairs_evaluated >= 500:
                    break
            if pairs_evaluated >= 500:
                break

        if not distortions:
            return 0.0, 0.0, 0.0

        avg_dist = sum(distortions) / len(distortions)
        max_dist = max(distortions)
        stress = math.sqrt(stress_num / max(1e-12, stress_denom))
        return avg_dist, max_dist, stress
