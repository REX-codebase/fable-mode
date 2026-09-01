"""System 3 Friston Active Inference & Variational Free Energy Engine.

Implements Karl Friston's Free Energy Principle for autonomous agentic reasoning:
- Variational Free Energy F = Complexity - Accuracy (KL-Divergence + Surprisal bound)
- Expected Free Energy G(pi) decomposition: Epistemic Value (Information Gain) + Pragmatic Value (Goal Utility)
- POMDP/MDP generative models (A likelihood, B transitions, C preferences, D priors)
- Policy evaluation, action selection, and variational belief updates in pure standard library Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
import copy
import json
import math


EPS = 1e-12


def _normalize(dist: Sequence[float]) -> List[float]:
    """Normalize a vector to a valid probability distribution."""
    total = sum(dist)
    if total < EPS:
        # Uniform fallback
        n = len(dist)
        return [1.0 / max(1, n)] * n
    return [max(EPS, x / total) for x in dist]


def _softmax(values: Sequence[float], temperature: float = 1.0) -> List[float]:
    """Numerically stable softmax."""
    if not values:
        return []
    temp = max(1e-6, temperature)
    scaled = [v / temp for v in values]
    max_v = max(scaled)
    exps = [math.exp(v - max_v) for v in scaled]
    sum_exps = sum(exps)
    return [e / sum_exps for e in exps]


def _kl_divergence(p: Sequence[float], q: Sequence[float]) -> float:
    """Compute Kullback-Leibler divergence D_KL(P || Q) = sum(P_i * ln(P_i / Q_i))."""
    p_norm = _normalize(p)
    q_norm = _normalize(q)
    div = 0.0
    for pi, qi in zip(p_norm, q_norm):
        if pi > EPS:
            div += pi * math.log(pi / max(EPS, qi))
    return max(0.0, div)


def _entropy(dist: Sequence[float]) -> float:
    """Compute Shannon entropy H(P) = -sum(P_i * ln(P_i))."""
    p_norm = _normalize(dist)
    h = 0.0
    for pi in p_norm:
        if pi > EPS:
            h -= pi * math.log(pi)
    return max(0.0, h)


@dataclass
class Policy:
    """A planned sequence of actions over a future horizon."""
    policy_id: str
    actions: List[str]
    label: str = ""
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Policy":
        return cls(**data)


@dataclass
class PolicyEvaluation:
    """Breakdown of Expected Free Energy G(pi) for policy selection."""
    policy_id: str
    actions: List[str]
    expected_free_energy_g: float
    risk_pragmatic_divergence: float    # D_KL(q(o|pi) || P(o in C)) - Divergence from prior preferences
    ambiguity_expected_entropy: float   # E_q(s)[ H(P(o|s)) ] - Expected observation ambiguity
    epistemic_information_gain: float   # Mutual Information I(s; o | pi) (Exploration Value)
    pragmatic_goal_utility: float       # Expected Log-Preference E[ ln C(o) ] (Exploitation Value)
    probability: float                  # Softmax posterior probability P(pi)
    is_optimal: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyEvaluation":
        return cls(**data)


@dataclass
class GenerativeModel:
    """
    Active Inference Generative Model:
    - S: Hidden states {s_1, ..., s_N}
    - O: Observations {o_1, ..., o_M}
    - U: Control actions {u_1, ..., u_K}
    - A: Observation likelihood matrix P(o_m | s_n) [M x N]
    - B: State transition matrices P(s_{t+1} | s_t, u) [K x N x N]
    - C: Prior preference distribution over observations P(o) [M]
    - D: Prior beliefs over initial hidden states P(s_0) [N]
    """
    states: List[str]
    observations: List[str]
    actions: List[str]
    a_matrix: List[List[float]]               # Shape: (len(observations), len(states))
    b_matrices: Dict[str, List[List[float]]]   # action -> Matrix of shape (len(states), len(states))
    c_preferences: List[float]                # Length: len(observations)
    d_prior: List[float]                      # Length: len(states)

    def __post_init__(self):
        num_s = len(self.states)
        num_o = len(self.observations)
        if len(self.d_prior) != num_s:
            raise ValueError(f"D prior length {len(self.d_prior)} != number of states {num_s}")
        if len(self.c_preferences) != num_o:
            raise ValueError(f"C preferences length {len(self.c_preferences)} != number of observations {num_o}")
        if len(self.a_matrix) != num_o or any(len(row) != num_s for row in self.a_matrix):
            raise ValueError(f"A matrix must have shape ({num_o}, {num_s})")
        # Normalize columns of A
        norm_a = [[0.0] * num_s for _ in range(num_o)]
        for s_idx in range(num_s):
            col = [self.a_matrix[o_idx][s_idx] for o_idx in range(num_o)]
            norm_col = _normalize(col)
            for o_idx in range(num_o):
                norm_a[o_idx][s_idx] = norm_col[o_idx]
        self.a_matrix = norm_a
        self.c_preferences = _normalize(self.c_preferences)
        self.d_prior = _normalize(self.d_prior)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GenerativeModel":
        return cls(**data)


@dataclass
class FreeEnergyReport:
    """Comprehensive Active Inference Free Energy state and policy telemetry."""
    step: int
    current_observation: str
    belief_state: Dict[str, float]
    variational_free_energy_f: float
    complexity_kl: float
    accuracy_log_likelihood: float
    surprisal_bound: float
    evaluated_policies: List[PolicyEvaluation]
    selected_policy: PolicyEvaluation
    selected_action: str
    telemetry: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "current_observation": self.current_observation,
            "belief_state": self.belief_state,
            "variational_free_energy_f": self.variational_free_energy_f,
            "complexity_kl": self.complexity_kl,
            "accuracy_log_likelihood": self.accuracy_log_likelihood,
            "surprisal_bound": self.surprisal_bound,
            "evaluated_policies": [p.to_dict() for p in self.evaluated_policies],
            "selected_policy": self.selected_policy.to_dict(),
            "selected_action": self.selected_action,
            "telemetry": self.telemetry,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FreeEnergyReport":
        policies = [PolicyEvaluation.from_dict(p) for p in data.get("evaluated_policies", [])]
        sel_pol = PolicyEvaluation.from_dict(data["selected_policy"])
        return cls(
            step=data["step"],
            current_observation=data["current_observation"],
            belief_state=data["belief_state"],
            variational_free_energy_f=data["variational_free_energy_f"],
            complexity_kl=data["complexity_kl"],
            accuracy_log_likelihood=data["accuracy_log_likelihood"],
            surprisal_bound=data["surprisal_bound"],
            evaluated_policies=policies,
            selected_policy=sel_pol,
            selected_action=data["selected_action"],
            telemetry=data.get("telemetry", {}),
        )


class ActiveInferenceEngine:
    """
    Friston Active Inference Engine:
    Minimizes Variational Free Energy F w.r.t beliefs (Perception)
    and minimizes Expected Free Energy G w.r.t policies (Action).
    """

    def __init__(
        self,
        generative_model: GenerativeModel,
        policy_precision_gamma: float = 16.0,
    ):
        self.model = generative_model
        self.gamma = policy_precision_gamma
        self.current_beliefs: List[float] = list(self.model.d_prior)
        self.step_count: int = 0
        self.history: List[Dict[str, Any]] = []

    def update_beliefs(self, observation: str) -> Tuple[float, float, float]:
        """
        Perception step: Update posterior state beliefs q(s) given observation o:
        ln q*(s) = ln p(s) + ln p(o | s) - ln Z
        Returns (Free_Energy_F, Complexity_KL, Accuracy_Log_Likelihood).
        """
        if observation not in self.model.observations:
            raise ValueError(f"Unknown observation '{observation}'. Available: {self.model.observations}")

        obs_idx = self.model.observations.index(observation)
        num_s = len(self.model.states)

        # Unnormalized log posterior: ln d_i + ln A[obs_idx][i]
        log_joint = []
        for s_idx in range(num_s):
            prior_s = max(EPS, self.current_beliefs[s_idx])
            like_s = max(EPS, self.model.a_matrix[obs_idx][s_idx])
            log_joint.append(math.log(prior_s) + math.log(like_s))

        # Posterior beliefs via softmax
        self.current_beliefs = _softmax(log_joint)

        # Calculate Variational Free Energy F = Complexity - Accuracy
        # Complexity = D_KL(q(s) || p(s))
        complexity = _kl_divergence(self.current_beliefs, self.model.d_prior)

        # Accuracy = E_q(s)[ ln p(o | s) ]
        accuracy = 0.0
        for s_idx in range(num_s):
            like_s = max(EPS, self.model.a_matrix[obs_idx][s_idx])
            accuracy += self.current_beliefs[s_idx] * math.log(like_s)

        f_total = complexity - accuracy

        return f_total, complexity, accuracy

    def evaluate_policy(self, policy: Policy) -> PolicyEvaluation:
        """
        Evaluate Expected Free Energy G(pi) for candidate policy pi:
        G(pi) = Risk (Pragmatic Divergence) + Ambiguity (Expected Uncertainty)
        """
        num_s = len(self.model.states)
        num_o = len(self.model.observations)

        # Forward simulate trajectory of beliefs under policy
        pred_state = list(self.current_beliefs)
        total_g = 0.0
        total_risk = 0.0
        total_ambiguity = 0.0
        total_info_gain = 0.0
        total_utility = 0.0

        for action in policy.actions:
            if action not in self.model.b_matrices:
                raise ValueError(f"Action '{action}' does not have a B transition matrix.")

            b_mat = self.model.b_matrices[action]
            # Next state prediction: pred_next[i] = sum_j B[i][j] * pred_state[j]
            next_state = [0.0] * num_s
            for i in range(num_s):
                for j in range(num_s):
                    next_state[i] += b_mat[i][j] * pred_state[j]
            pred_state = _normalize(next_state)

            # Predicted observation distribution: pred_obs[m] = sum_n A[m][n] * pred_state[n]
            pred_obs = [0.0] * num_o
            for m in range(num_o):
                for n in range(num_s):
                    pred_obs[m] += self.model.a_matrix[m][n] * pred_state[n]
            pred_obs = _normalize(pred_obs)

            # 1. Risk: D_KL( q(o | pi) || C )
            risk = _kl_divergence(pred_obs, self.model.c_preferences)

            # 2. Ambiguity: E_q(s)[ H( A[:, s] ) ]
            ambiguity = 0.0
            for s_idx in range(num_s):
                col = [self.model.a_matrix[o_idx][s_idx] for o_idx in range(num_o)]
                ambiguity += pred_state[s_idx] * _entropy(col)

            # 3. Epistemic Information Gain: H(q(o | pi)) - Ambiguity (Mutual Information I(s; o))
            entropy_obs = _entropy(pred_obs)
            info_gain = max(0.0, entropy_obs - ambiguity)

            # 4. Pragmatic Utility: E_q(o)[ ln C(o) ]
            utility = 0.0
            for o_idx in range(num_o):
                utility += pred_obs[o_idx] * math.log(max(EPS, self.model.c_preferences[o_idx]))

            step_g = risk + ambiguity

            total_g += step_g
            total_risk += risk
            total_ambiguity += ambiguity
            total_info_gain += info_gain
            total_utility += utility

        return PolicyEvaluation(
            policy_id=policy.policy_id,
            actions=list(policy.actions),
            expected_free_energy_g=total_g,
            risk_pragmatic_divergence=total_risk,
            ambiguity_expected_entropy=total_ambiguity,
            epistemic_information_gain=total_info_gain,
            pragmatic_goal_utility=total_utility,
            probability=0.0, # Will be normalized across policies
        )

    def select_action(
        self,
        observation: str,
        candidate_policies: List[Policy],
    ) -> FreeEnergyReport:
        """
        Execute one complete Active Inference reasoning cycle:
        1. Ingest observation and update state beliefs (Perception).
        2. Evaluate candidate policies across Epistemic & Pragmatic value (Planning).
        3. Compute policy posterior distribution P(pi) via softmax(-gamma * G).
        4. Select optimal policy and action (Action).
        """
        self.step_count += 1

        # 1. Perception
        f_val, comp_kl, acc_ll = self.update_beliefs(observation)

        if not candidate_policies:
            # Generate default 1-step policies for all actions
            candidate_policies = [
                Policy(policy_id=f"policy_{act}", actions=[act], label=f"Execute {act}")
                for act in self.model.actions
            ]

        # 2. Policy Planning
        evaluations = [self.evaluate_policy(p) for p in candidate_policies]

        # 3. Policy Posterior P(pi) = softmax(-gamma * G)
        neg_g_values = [-self.gamma * e.expected_free_energy_g for e in evaluations]
        probs = _softmax(neg_g_values)
        for e, p in zip(evaluations, probs):
            e.probability = p

        # Find best policy (minimum G)
        best_eval = min(evaluations, key=lambda e: e.expected_free_energy_g)
        best_eval.is_optimal = True
        selected_action = best_eval.actions[0] if best_eval.actions else self.model.actions[0]

        belief_dict = {
            self.model.states[i]: self.current_beliefs[i]
            for i in range(len(self.model.states))
        }

        report = FreeEnergyReport(
            step=self.step_count,
            current_observation=observation,
            belief_state=belief_dict,
            variational_free_energy_f=f_val,
            complexity_kl=comp_kl,
            accuracy_log_likelihood=acc_ll,
            surprisal_bound=f_val,
            evaluated_policies=evaluations,
            selected_policy=best_eval,
            selected_action=selected_action,
            telemetry={
                "policy_precision_gamma": self.gamma,
                "states_count": len(self.model.states),
                "observations_count": len(self.model.observations),
                "entropy_of_beliefs": _entropy(self.current_beliefs),
            },
        )

        self.history.append(report.to_dict())
        return report

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model.to_dict(),
            "gamma": self.gamma,
            "current_beliefs": self.current_beliefs,
            "step_count": self.step_count,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveInferenceEngine":
        model = GenerativeModel.from_dict(data["model"])
        engine = cls(generative_model=model, policy_precision_gamma=data.get("gamma", 16.0))
        engine.current_beliefs = list(data.get("current_beliefs", model.d_prior))
        engine.step_count = int(data.get("step_count", 0))
        engine.history = list(data.get("history", []))
        return engine


def create_default_architecture_pomdp() -> GenerativeModel:
    """
    Factory for a standard Software Architecture Active Inference POMDP:
    States: {OPTIMAL_DECOUPLED, CONTENTION_BOTTLENECK, MEMORY_LEAK, INTEGRITY_FAULT}
    Observations: {HIGH_THROUGHPUT_CLEAN, LOCK_CONTENTION_WARN, MEMORY_GROWTH_WARN, CHECKSUM_FAIL}
    Actions: {APPLY_CAS_ISOLATION, SHARD_WORKERS, REFACTOR_MUTEX, RUN_BENCHMARK}
    """
    states = ["OPTIMAL_DECOUPLED", "CONTENTION_BOTTLENECK", "MEMORY_LEAK", "INTEGRITY_FAULT"]
    observations = ["HIGH_THROUGHPUT_CLEAN", "LOCK_CONTENTION_WARN", "MEMORY_GROWTH_WARN", "CHECKSUM_FAIL"]
    actions = ["APPLY_CAS_ISOLATION", "SHARD_WORKERS", "REFACTOR_MUTEX", "RUN_BENCHMARK"]

    # A matrix [O x S]: observation likelihoods
    a_mat = [
        [0.85, 0.05, 0.05, 0.05],  # HIGH_THROUGHPUT_CLEAN
        [0.05, 0.80, 0.10, 0.05],  # LOCK_CONTENTION_WARN
        [0.05, 0.10, 0.80, 0.05],  # MEMORY_GROWTH_WARN
        [0.05, 0.05, 0.05, 0.85],  # CHECKSUM_FAIL
    ]

    # B matrices [S x S] for each action
    b_mats: Dict[str, List[List[float]]] = {}

    # APPLY_CAS_ISOLATION transitions towards OPTIMAL_DECOUPLED
    b_mats["APPLY_CAS_ISOLATION"] = [
        [0.90, 0.70, 0.60, 0.30],
        [0.05, 0.20, 0.10, 0.10],
        [0.03, 0.05, 0.25, 0.10],
        [0.02, 0.05, 0.05, 0.50],
    ]

    # SHARD_WORKERS reduces contention
    b_mats["SHARD_WORKERS"] = [
        [0.80, 0.65, 0.10, 0.10],
        [0.10, 0.25, 0.10, 0.10],
        [0.05, 0.05, 0.70, 0.10],
        [0.05, 0.05, 0.10, 0.70],
    ]

    # REFACTOR_MUTEX targets lock contention
    b_mats["REFACTOR_MUTEX"] = [
        [0.85, 0.75, 0.10, 0.10],
        [0.05, 0.15, 0.10, 0.10],
        [0.05, 0.05, 0.70, 0.10],
        [0.05, 0.05, 0.10, 0.70],
    ]

    # RUN_BENCHMARK maintains state (pure diagnostic/epistemic probe)
    b_mats["RUN_BENCHMARK"] = [
        [0.95, 0.05, 0.05, 0.05],
        [0.02, 0.90, 0.02, 0.02],
        [0.02, 0.03, 0.90, 0.03],
        [0.01, 0.02, 0.03, 0.90],
    ]

    # C preferences: agent strongly desires clean high throughput
    c_pref = [0.85, 0.05, 0.05, 0.05]

    # D prior: initial uniform/slightly optimistic state belief
    d_prior = [0.50, 0.20, 0.15, 0.15]

    return GenerativeModel(
        states=states,
        observations=observations,
        actions=actions,
        a_matrix=a_mat,
        b_matrices=b_mats,
        c_preferences=c_pref,
        d_prior=d_prior,
    )
