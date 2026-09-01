"""System 3 Evolutionary Paradigm Engine & 10D Pareto Frontier Optimizer.

Implements genetic algorithms, multi-objective NSGA-II non-dominated Pareto sorting,
crowding-distance diversity maintenance, and architectural genome mutation/crossover.
Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import copy
import hashlib
import json
import math
import random
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


PARETO_DIMENSIONS = [
    "latency",             # Speed / execution responsiveness (higher is better)
    "throughput",          # Concurrency / operations per second
    "memory_efficiency",   # Low footprint / bounded cache overhead
    "fault_tolerance",     # Resilience under faults / self-healing
    "modularity",          # Decoupling / clear component boundaries
    "simplicity",          # Low cognitive complexity / maintainability
    "testability",         # Ease of automated verification / determinism
    "security",            # Trust boundaries / isolation / attack surface
    "determinism",         # Reproducibility / zero race conditions
    "token_compaction",    # Compaction efficiency (CAS storage / grammar)
]

GENE_ALLELE_OPTIONS = {
    "concurrency_model": [
        "actor_model", "event_loop_async", "worker_thread_pool",
        "lock_free_ring_buffer", "csp_channels", "speculative_dual_pass"
    ],
    "state_persistence": [
        "cas_immutable_store", "event_sourcing_log", "write_ahead_log",
        "in_memory_sharded_lru", "cow_snapshot_tree", "hybrid_disk_mmap"
    ],
    "synchronization": [
        "optimistic_concurrency_cas", "single_writer_multi_reader",
        "crdt_conflict_free", "pessimistic_rwlock", "message_passing_only"
    ],
    "cache_hierarchy": [
        "two_level_sharded_lru", "direct_mapped_cas",
        "arc_adaptive_replacement", "write_through_memory_pool"
    ],
    "error_recovery": [
        "ooda_circuit_breaker", "erlang_supervisor_tree",
        "exponential_backoff_jitter", "fail_fast_rollback", "shadow_consensus"
    ],
    "data_layout": [
        "columnar_structure_of_arrays", "row_array_of_structures",
        "flat_buffer_varint", "chunked_composite_frames"
    ],
    "execution_strategy": [
        "subagent_fleet_pipeline", "hierarchical_director_worker",
        "deterministic_single_pass", "mcts_branching_deliberation"
    ],
    "network_topology": [
        "hub_and_spoke_orchestrator", "peer_to_peer_mesh",
        "ring_token_bus", "hierarchical_tree"
    ],
}


@dataclass
class CognitiveGenome:
    """Genetic encoding of an architectural candidate paradigm."""
    genome_id: str
    paradigm_name: str
    genes: Dict[str, Any] = field(default_factory=dict)
    fitness_scores: Dict[str, float] = field(default_factory=dict)
    generation: int = 0
    pareto_rank: int = 1
    crowding_distance: float = 0.0
    lineage: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def dominates(self, other: "CognitiveGenome") -> bool:
        """
        Pareto Dominance Check:
        Returns True if self is >= other in all 10 dimensions AND strictly > in at least one.
        """
        better_in_at_least_one = False
        for dim in PARETO_DIMENSIONS:
            score_self = self.fitness_scores.get(dim, 0.0)
            score_other = other.fitness_scores.get(dim, 0.0)
            if score_self < score_other:
                return False
            if score_self > score_other:
                better_in_at_least_one = True
        return better_in_at_least_one

    def compute_scalar_fitness(self, weights: Optional[Dict[str, float]] = None) -> float:
        """Compute weighted scalar composite fitness score [0.0, 1.0]."""
        w = weights or {dim: 1.0 / len(PARETO_DIMENSIONS) for dim in PARETO_DIMENSIONS}
        total_w = sum(w.values()) or 1.0
        score = sum(self.fitness_scores.get(dim, 0.0) * w.get(dim, 1.0) for dim in PARETO_DIMENSIONS)
        return round(score / total_w, 4)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveGenome":
        return cls(**data)


def create_random_genome(
    genome_id: str,
    paradigm_name: str,
    generation: int = 0,
    seed: Optional[int] = None,
) -> CognitiveGenome:
    """Instantiate a valid randomized genome across the architectural dimensions."""
    rng = random.Random(seed)
    genes: Dict[str, Any] = {}
    for gene_name, alleles in GENE_ALLELE_OPTIONS.items():
        genes[gene_name] = rng.choice(alleles)

    # Continuous parameters
    genes["verification_depth"] = round(rng.uniform(0.5, 1.0), 3)
    genes["compression_target"] = round(rng.uniform(0.001, 0.005), 5)
    genes["concurrency_workers"] = rng.randint(2, 16)

    # Default heuristic fitness initialization
    fitness: Dict[str, float] = {}
    for dim in PARETO_DIMENSIONS:
        fitness[dim] = round(rng.uniform(0.5, 0.85), 3)

    return CognitiveGenome(
        genome_id=genome_id,
        paradigm_name=paradigm_name,
        genes=genes,
        fitness_scores=fitness,
        generation=generation,
    )


class CognitiveGenePool:
    """
    Population manager executing NSGA-II Multi-Objective Evolutionary Optimization
    across the 10D Pareto frontier with elite preservation and crowding distance diversity.
    """

    def __init__(
        self,
        population_size: int = 20,
        mutation_rate: float = 0.15,
        crossover_rate: float = 0.80,
        random_seed: Optional[int] = 42,
    ):
        self.population_size = max(4, population_size)
        self.mutation_rate = max(0.01, min(1.0, mutation_rate))
        self.crossover_rate = max(0.1, min(1.0, crossover_rate))
        self.rng = random.Random(random_seed)
        self.population: List[CognitiveGenome] = []
        self.generation_count: int = 0
        self.history: List[Dict[str, Any]] = []

    def initialize_population(
        self,
        seed_paradigms: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Seed initial population with provided archetypes and generated variants."""
        self.population = []
        self.generation_count = 0

        # Ingest custom seeds if provided
        if seed_paradigms:
            for idx, p in enumerate(seed_paradigms):
                gid = p.get("genome_id", f"seed_{idx+1:03d}")
                name = p.get("paradigm_name", f"Seed Paradigm #{idx+1}")
                genes = p.get("genes", {})
                # Fill missing genes
                for k, v in GENE_ALLELE_OPTIONS.items():
                    if k not in genes:
                        genes[k] = self.rng.choice(v)
                if "verification_depth" not in genes:
                    genes["verification_depth"] = 0.85
                if "compression_target" not in genes:
                    genes["compression_target"] = 0.003
                if "concurrency_workers" not in genes:
                    genes["concurrency_workers"] = 4

                fitness = p.get("fitness_scores", {})
                for dim in PARETO_DIMENSIONS:
                    if dim not in fitness:
                        fitness[dim] = 0.70

                genome = CognitiveGenome(
                    genome_id=gid,
                    paradigm_name=name,
                    genes=genes,
                    fitness_scores=fitness,
                    generation=0,
                )
                self.population.append(genome)

        # Fill remainder with diversified random archetypes
        archetype_names = [
            "Ultra-Low Latency Ring Engine",
            "Resilient CAS-Immutable Actor Grid",
            "Adaptive Neuro-Symbolic Pipeline",
            "High-Throughput Varint Streamer",
            "Hierarchical Supervisor Worktree",
            "Zero-Allocation Columnar Engine",
            "Speculative Dual-Pass MCTS",
            "Event-Sourced Self-Healing Bus",
        ]

        while len(self.population) < self.population_size:
            idx = len(self.population) + 1
            name = archetype_names[idx % len(archetype_names)] + f" (Gen 0 #{idx})"
            genome = create_random_genome(f"g0_{idx:03d}", name, generation=0, seed=self.rng.randint(1, 1000000))
            self.population.append(genome)

    def evaluate_fitness(
        self,
        fitness_fn: Optional[Callable[[CognitiveGenome], Dict[str, float]]] = None,
    ) -> None:
        """
        Evaluate 10D fitness scores for all genomes in the population.
        If no custom evaluator provided, uses domain structural heuristics.
        """
        for genome in self.population:
            if fitness_fn:
                scores = fitness_fn(genome)
                genome.fitness_scores.update(scores)
            else:
                # Built-in structural heuristic evaluator based on gene synergies
                g = genome.genes
                scores: Dict[str, float] = {}

                # Latency & Throughput heuristics
                is_lock_free = g.get("concurrency_model") == "lock_free_ring_buffer"
                is_cas_imm = g.get("state_persistence") == "cas_immutable_store"
                is_soa = g.get("data_layout") == "columnar_structure_of_arrays"

                scores["latency"] = min(0.98, 0.65 + (0.20 if is_lock_free else 0.05) + (0.10 if is_soa else 0.0))
                scores["throughput"] = min(0.98, 0.60 + (0.15 if is_lock_free else 0.05) + (0.15 if g.get("concurrency_workers", 4) >= 8 else 0.05))
                scores["memory_efficiency"] = min(0.98, 0.70 + (0.15 if is_cas_imm else 0.0) + (0.10 if is_soa else 0.0))
                scores["fault_tolerance"] = min(0.98, 0.65 + (0.25 if g.get("error_recovery") == "ooda_circuit_breaker" else 0.10))
                scores["modularity"] = min(0.98, 0.75 + (0.15 if g.get("execution_strategy") == "subagent_fleet_pipeline" else 0.05))
                scores["simplicity"] = min(0.95, 0.85 - (0.15 if is_lock_free else 0.0) - (0.10 if g.get("concurrency_workers", 4) > 8 else 0.0))
                scores["testability"] = min(0.98, 0.70 + (0.20 if g.get("synchronization") == "single_writer_multi_reader" else 0.05))
                scores["security"] = min(0.98, 0.75 + (0.15 if is_cas_imm else 0.05))
                scores["determinism"] = min(0.98, 0.80 + (0.15 if is_cas_imm else 0.0))
                scores["token_compaction"] = min(0.99, 0.75 + (0.20 if g.get("data_layout") == "chunked_composite_frames" else 0.05))

                for dim in PARETO_DIMENSIONS:
                    scores[dim] = round(max(0.1, min(0.99, scores.get(dim, 0.7))), 3)

                genome.fitness_scores = scores

    def fast_non_dominated_sort(self) -> List[List[CognitiveGenome]]:
        """
        NSGA-II Fast Non-Dominated Sorting Algorithm.
        Sorts the population into Pareto Fronts F_1, F_2, ... F_k.
        Front 1 (rank 1) contains the strictly non-dominated solutions.
        """
        fronts: List[List[CognitiveGenome]] = [[]]
        domination_count: Dict[str, int] = {}
        dominated_solutions: Dict[str, List[CognitiveGenome]] = {}

        for p in self.population:
            domination_count[p.genome_id] = 0
            dominated_solutions[p.genome_id] = []
            for q in self.population:
                if p.dominates(q):
                    dominated_solutions[p.genome_id].append(q)
                elif q.dominates(p):
                    domination_count[p.genome_id] += 1

            if domination_count[p.genome_id] == 0:
                p.pareto_rank = 1
                fronts[0].append(p)

        i = 0
        while len(fronts[i]) > 0:
            next_front: List[CognitiveGenome] = []
            for p in fronts[i]:
                for q in dominated_solutions[p.genome_id]:
                    domination_count[q.genome_id] -= 1
                    if domination_count[q.genome_id] == 0:
                        q.pareto_rank = i + 2
                        next_front.append(q)
            i += 1
            fronts.append(next_front)

        # Remove trailing empty front
        if fronts and not fronts[-1]:
            fronts.pop()

        return fronts

    def calculate_crowding_distance(self, front: List[CognitiveGenome]) -> None:
        """
        Compute crowding distance for genomes in a front to favor diversity along the frontier.
        Boundary points receive infinite distance.
        """
        l = len(front)
        if l == 0:
            return
        if l <= 2:
            for g in front:
                g.crowding_distance = float("inf")
            return

        for g in front:
            g.crowding_distance = 0.0

        for dim in PARETO_DIMENSIONS:
            # Sort front by current objective
            front.sort(key=lambda g: g.fitness_scores.get(dim, 0.0))
            front[0].crowding_distance = float("inf")
            front[-1].crowding_distance = float("inf")

            dim_min = front[0].fitness_scores.get(dim, 0.0)
            dim_max = front[-1].fitness_scores.get(dim, 0.0)
            denom = max(1e-6, dim_max - dim_min)

            for i in range(1, l - 1):
                if not math.isinf(front[i].crowding_distance):
                    prev_score = front[i - 1].fitness_scores.get(dim, 0.0)
                    next_score = front[i + 1].fitness_scores.get(dim, 0.0)
                    front[i].crowding_distance += (next_score - prev_score) / denom

    def crossover(self, parent1: CognitiveGenome, parent2: CognitiveGenome) -> Tuple[CognitiveGenome, CognitiveGenome]:
        """Uniform & blended genetic crossover between two architectural genomes."""
        if self.rng.random() > self.crossover_rate:
            # Clone without crossover
            return copy.deepcopy(parent1), copy.deepcopy(parent2)

        genes1 = copy.deepcopy(parent1.genes)
        genes2 = copy.deepcopy(parent2.genes)

        for gene_key in list(genes1.keys()):
            if self.rng.random() < 0.5:
                # Swap discrete gene
                genes1[gene_key], genes2[gene_key] = genes2.get(gene_key, genes1[gene_key]), genes1[gene_key]

        # Blend continuous parameters
        for cont_param in ["verification_depth", "compression_target"]:
            v1 = genes1.get(cont_param, 0.8)
            v2 = genes2.get(cont_param, 0.8)
            alpha = self.rng.uniform(0.2, 0.8)
            genes1[cont_param] = round(alpha * v1 + (1 - alpha) * v2, 4)
            genes2[cont_param] = round((1 - alpha) * v1 + alpha * v2, 4)

        gid1 = f"g{self.generation_count+1}_{self.rng.randint(100, 999)}"
        gid2 = f"g{self.generation_count+1}_{self.rng.randint(100, 999)}"

        child1 = CognitiveGenome(
            genome_id=gid1,
            paradigm_name=f"Hybrid({parent1.paradigm_name[:15]}+{parent2.paradigm_name[:15]})",
            genes=genes1,
            generation=self.generation_count + 1,
            lineage=[parent1.genome_id, parent2.genome_id],
        )
        child2 = CognitiveGenome(
            genome_id=gid2,
            paradigm_name=f"Recombinant({parent2.paradigm_name[:15]}+{parent1.paradigm_name[:15]})",
            genes=genes2,
            generation=self.generation_count + 1,
            lineage=[parent2.genome_id, parent1.genome_id],
        )
        return child1, child2

    def mutate(self, genome: CognitiveGenome) -> CognitiveGenome:
        """Mutate genome discrete alleles and continuous variables."""
        mutated_genes = copy.deepcopy(genome.genes)

        for gene_name, alleles in GENE_ALLELE_OPTIONS.items():
            if self.rng.random() < self.mutation_rate:
                # Gene flip
                new_val = self.rng.choice(alleles)
                mutated_genes[gene_name] = new_val

        # Continuous jitter
        if self.rng.random() < self.mutation_rate:
            depth = mutated_genes.get("verification_depth", 0.85)
            mutated_genes["verification_depth"] = round(max(0.1, min(1.0, depth + self.rng.gauss(0, 0.05))), 3)

        if self.rng.random() < self.mutation_rate:
            workers = mutated_genes.get("concurrency_workers", 4)
            mutated_genes["concurrency_workers"] = max(1, min(32, workers + self.rng.choice([-1, 1, 2])))

        genome.genes = mutated_genes
        return genome

    def tournament_selection(self, k: int = 3) -> CognitiveGenome:
        """Crowded Tournament Selection based on Pareto Rank and Crowding Distance."""
        candidates = self.rng.sample(self.population, min(k, len(self.population)))
        # Winner has lower rank (better), or in tie has higher crowding distance
        candidates.sort(key=lambda g: (g.pareto_rank, -g.crowding_distance))
        return candidates[0]

    def evolve_generation(
        self,
        fitness_fn: Optional[Callable[[CognitiveGenome], Dict[str, float]]] = None,
        elite_ratio: float = 0.2,
    ) -> List[CognitiveGenome]:
        """
        Execute one complete generation of NSGA-II Multi-Objective Evolution:
        1. Evaluate fitness scores.
        2. Fast non-dominated sorting into Pareto fronts.
        3. Compute crowding distance.
        4. Select elites from Front 1.
        5. Generate offspring via tournament selection, crossover, and mutation.
        6. Form new population and increment generation count.
        """
        if not self.population:
            self.initialize_population()

        self.evaluate_fitness(fitness_fn)
        fronts = self.fast_non_dominated_sort()
        for front in fronts:
            self.calculate_crowding_distance(front)

        # Record history snapshot
        front1 = fronts[0] if fronts else []
        self.history.append({
            "generation": self.generation_count,
            "population_size": len(self.population),
            "front1_size": len(front1),
            "front1_best_scalar": max([g.compute_scalar_fitness() for g in front1]) if front1 else 0.0,
            "front1_genomes": [g.genome_id for g in front1],
        })

        # Elite selection from top fronts
        num_elites = max(2, int(self.population_size * elite_ratio))
        next_population: List[CognitiveGenome] = []

        for front in fronts:
            if len(next_population) + len(front) <= num_elites:
                next_population.extend([copy.deepcopy(g) for g in front])
            else:
                # Partial front fill based on crowding distance
                sorted_front = sorted(front, key=lambda g: g.crowding_distance, reverse=True)
                needed = num_elites - len(next_population)
                next_population.extend([copy.deepcopy(g) for g in sorted_front[:needed]])
                break

        # Breed remaining offspring
        while len(next_population) < self.population_size:
            p1 = self.tournament_selection()
            p2 = self.tournament_selection()
            c1, c2 = self.crossover(p1, p2)
            c1 = self.mutate(c1)
            next_population.append(c1)
            if len(next_population) < self.population_size:
                c2 = self.mutate(c2)
                next_population.append(c2)

        self.generation_count += 1
        self.population = next_population
        self.evaluate_fitness(fitness_fn)
        new_fronts = self.fast_non_dominated_sort()
        for front in new_fronts:
            self.calculate_crowding_distance(front)

        return self.get_pareto_frontier()

    def get_pareto_frontier(self) -> List[CognitiveGenome]:
        """Return the current Generation's Rank 1 non-dominated Pareto frontier."""
        fronts = self.fast_non_dominated_sort()
        return fronts[0] if fronts else []

    def get_best_genome(self, weights: Optional[Dict[str, float]] = None) -> CognitiveGenome:
        """Return the highest-scoring genome according to scalar objective weighting."""
        if not self.population:
            self.initialize_population()
        self.evaluate_fitness()
        return max(self.population, key=lambda g: g.compute_scalar_fitness(weights))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize GenePool to JSON dictionary."""
        return {
            "population_size": self.population_size,
            "generation_count": self.generation_count,
            "mutation_rate": self.mutation_rate,
            "crossover_rate": self.crossover_rate,
            "population": [g.to_dict() for g in self.population],
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveGenePool":
        """Deserialize GenePool from dictionary."""
        pool = cls(
            population_size=data.get("population_size", 20),
            mutation_rate=data.get("mutation_rate", 0.15),
            crossover_rate=data.get("crossover_rate", 0.80),
        )
        pool.generation_count = data.get("generation_count", 0)
        pool.history = data.get("history", [])
        pool.population = [
            CognitiveGenome.from_dict(g) for g in data.get("population", [])
        ]
        return pool
