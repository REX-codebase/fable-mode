"""Compute Orchestrator Engine for Thinking Budgets, MCTS Exploration, and Best-of-N Consensus.

Calculates model token velocity profiles, performs deterministic Monte Carlo Tree Search,
and synthesizes multi-candidate consensus rankings.
"""
from __future__ import annotations

import math
from typing import Any


class MCTSNode:
    """A node in the Monte Carlo Tree Search tree."""

    def __init__(self, name: str, parent: MCTSNode | None = None, depth: int = 0) -> None:
        self.name = name
        self.parent = parent
        self.children: list[MCTSNode] = []
        self.visits: int = 0
        self.value: float = 0.0
        self.depth: int = depth

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def ucb1(self, exploration_constant: float = 1.414) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else self.visits
        exploit = self.value / self.visits
        explore = exploration_constant * math.sqrt(math.log(max(1, parent_visits)) / self.visits)
        return exploit + explore


class ComputeOrchestratorEngine:
    """Engine for compute budgeting, MCTS decision search, and candidate consensus evaluation."""

    def calculate_thinking_budget(self, complexity_score: float, failure_count: int) -> dict[str, Any]:
        """Calculate recommended thinking tokens (4k-64k) and model tier based on complexity

        and previous failure iterations.
        """
        clamped_complexity = max(0.0, min(10.0, float(complexity_score)))
        clamped_failures = max(0, int(failure_count))

        # Base token range: 4,096 to 65,536
        min_tokens = 4096
        max_tokens = 65536

        # Difficulty scaling
        factor = (clamped_complexity / 10.0) ** 1.2
        failure_bonus = clamped_failures * 8192
        raw_tokens = min_tokens + int((max_tokens - min_tokens) * factor) + failure_bonus
        recommended_tokens = max(min_tokens, min(max_tokens, raw_tokens))
        # Round to nearest 1024
        recommended_tokens = (recommended_tokens // 1024) * 1024

        # Model tier determination
        if clamped_complexity <= 3.0 and clamped_failures == 0:
            model_tier = "flash"
            strategy = "direct_single_pass"
        elif clamped_complexity <= 7.0 and clamped_failures <= 1:
            model_tier = "pro"
            strategy = "dual_pass_verification"
        else:
            model_tier = "deepthink"
            strategy = "system3_mcts_redteam"

        return {
            "complexity_score": clamped_complexity,
            "failure_count": clamped_failures,
            "recommended_tokens": recommended_tokens,
            "model_tier": model_tier,
            "strategy": strategy,
        }

    def mcts_explore(self, problem_spec: dict[str, Any], branches: int = 4, depth: int = 2) -> dict[str, Any]:
        """Simulate branch exploration and value backpropagation using Monte Carlo Tree Search."""
        root = MCTSNode(name="root", depth=0)
        candidate_strategies = problem_spec.get("strategies") or [f"strategy_branch_{i+1}" for i in range(branches)]

        # Expand root
        for strat in candidate_strategies[:branches]:
            child = MCTSNode(name=str(strat), parent=root, depth=1)
            root.children.append(child)

        # Simulation iterations
        total_simulations = max(20, branches * depth * 6)

        for _ in range(total_simulations):
            # 1. Selection
            curr = root
            while not curr.is_leaf() and curr.depth < depth:
                curr = max(curr.children, key=lambda n: n.ucb1())

            # 2. Expansion if not at max depth
            if curr.depth < depth and curr.visits > 0:
                for sub_i in range(min(2, branches)):
                    sub_child = MCTSNode(name=f"{curr.name}.step_{sub_i+1}", parent=curr, depth=curr.depth + 1)
                    curr.children.append(sub_child)
                curr = curr.children[0]

            # 3. Simulation / Rollout evaluation
            # Heuristic score based on candidate attributes or pseudo-deterministic fitness
            base_fitness = 0.5
            strat_bonus = (hash(curr.name) % 100) / 200.0  # [0.0, 0.5]
            depth_penalty = curr.depth * 0.02
            reward = max(0.0, min(1.0, base_fitness + strat_bonus - depth_penalty))

            # 4. Backpropagation
            back = curr
            while back is not None:
                back.visits += 1
                back.value += reward
                back = back.parent

        # Select best branch from root
        best_child = max(root.children, key=lambda n: n.visits)

        # Build recommended path
        path = [best_child.name]
        trav = best_child
        while trav.children:
            trav = max(trav.children, key=lambda n: n.visits)
            path.append(trav.name)

        tree_summary = [
            {
                "name": ch.name,
                "visits": ch.visits,
                "avg_value": round(ch.value / max(1, ch.visits), 4),
                "ucb1": round(ch.ucb1(), 4),
            }
            for ch in root.children
        ]

        return {
            "root_visits": root.visits,
            "best_branch": {
                "name": best_child.name,
                "visits": best_child.visits,
                "avg_value": round(best_child.value / max(1, best_child.visits), 4),
            },
            "branches_explored": len(root.children),
            "tree_summary": tree_summary,
            "recommended_path": path,
        }

    def best_of_n_consensus(self, candidate_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Select highest scoring candidate via differential comparison and consensus scoring."""
        if not candidate_results:
            return {
                "selected_candidate": None,
                "consensus_score": 0.0,
                "rankings": [],
                "differential_notes": ["No candidate results provided for evaluation"],
            }

        ranked_candidates: list[dict[str, Any]] = []

        for idx, cand in enumerate(candidate_results):
            cand_id = cand.get("id", f"candidate_{idx+1}")
            pass_rate = float(cand.get("test_pass_rate", cand.get("pass_rate", 1.0)))
            raw_score = float(cand.get("score", 0.5))
            complexity = float(cand.get("complexity", 5.0))
            # Simplicity bonus (lower complexity is better)
            simplicity = max(0.0, 1.0 - (complexity / 10.0))

            # Composite weighted fitness
            fitness = (pass_rate * 0.50) + (raw_score * 0.35) + (simplicity * 0.15)
            ranked_candidates.append({
                "candidate": cand,
                "id": cand_id,
                "fitness": round(fitness, 4),
                "pass_rate": pass_rate,
                "raw_score": raw_score,
                "simplicity": simplicity,
            })

        ranked_candidates.sort(key=lambda x: x["fitness"], reverse=True)
        winner = ranked_candidates[0]["candidate"]

        # Calculate consensus (agreement among top candidates on pass rate / score)
        high_performers = [c for c in ranked_candidates if c["fitness"] >= 0.7]
        consensus_score = round(len(high_performers) / len(ranked_candidates), 4)

        differential_notes: list[str] = [
            f"Selected winner '{ranked_candidates[0]['id']}' with top composite fitness {ranked_candidates[0]['fitness']}",
        ]
        if len(ranked_candidates) > 1:
            margin = round(ranked_candidates[0]["fitness"] - ranked_candidates[1]["fitness"], 4)
            differential_notes.append(f"Fitness margin over runner-up: +{margin}")

        return {
            "selected_candidate": winner,
            "consensus_score": consensus_score,
            "rankings": ranked_candidates,
            "differential_notes": differential_notes,
        }
