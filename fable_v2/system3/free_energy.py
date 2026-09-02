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

from ..protocol import canonical_hash


EPS = 1e-12


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return float(value)


def _normalize(dist: Sequence[float]) -> List[float]:
    """Normalize a finite, bounded probability vector."""
    if len(dist) > 128 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)) or x < 0 for x in dist):
        raise ValueError("probability vector contains invalid or unbounded values")
    total = sum(float(x) for x in dist)
    if not math.isfinite(total):
        raise ValueError("probability vector sum must be finite")
    if total < EPS:
        # Uniform fallback
        n = len(dist)
        return [1.0 / max(1, n)] * n
    return [max(EPS, x / total) for x in dist]


def _softmax(values: Sequence[float], temperature: float = 1.0) -> List[float]:
    """Numerically stable softmax."""
    if not values:
        return []
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v))
           for v in values):
        raise ValueError("softmax values must be finite")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not math.isfinite(float(temperature)):
        raise ValueError("softmax temperature must be finite")
    temp = max(1e-6, float(temperature))
    scaled = [float(v) / temp for v in values]
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

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id must be non-empty")
        if (not isinstance(self.actions, list) or len(self.actions) > 128
                or any(not isinstance(a, str) or not a.strip() for a in self.actions)):
            raise ValueError("policy actions are invalid or unbounded")
        if not self.actions:
            raise ValueError("policy must contain at least one action")
        self.actions = list(self.actions)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def commitment(self) -> str:
        return canonical_hash(self.to_dict())

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

    def __post_init__(self) -> None:
        for name in ("expected_free_energy_g", "risk_pragmatic_divergence",
                     "ambiguity_expected_entropy", "epistemic_information_gain",
                     "pragmatic_goal_utility", "probability"):
            _finite(getattr(self, name), name)
        if not 0 <= self.probability <= 1:
            raise ValueError("policy probability must be between 0 and 1")
        if (not isinstance(self.actions, list) or not self.actions
                or any(not isinstance(a, str) or not a.strip() for a in self.actions)):
            raise ValueError("policy evaluation actions are invalid")
        self.actions = list(self.actions)
        self.metadata = copy.deepcopy(dict(self.metadata))
        canonical_hash(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(asdict(self))

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
        if not self.states or not self.observations or not self.actions:
            raise ValueError("generative model requires non-empty states, observations, and actions")
        if any(not isinstance(x, str) or not x.strip() for x in (*self.states, *self.observations, *self.actions)):
            raise ValueError("generative model labels must be non-empty strings")
        if len(self.states) > 128 or len(self.observations) > 128 or len(self.actions) > 128:
            raise ValueError("generative model exceeds bounds")
        num_s = len(self.states)
        num_o = len(self.observations)
        if len(self.d_prior) != num_s:
            raise ValueError(f"D prior length {len(self.d_prior)} != number of states {num_s}")
        if len(self.c_preferences) != num_o:
            raise ValueError(f"C preferences length {len(self.c_preferences)} != number of observations {num_o}")
        if len(self.a_matrix) != num_o or any(len(row) != num_s for row in self.a_matrix):
            raise ValueError(f"A matrix must have shape ({num_o}, {num_s})")
        for action, matrix in self.b_matrices.items():
            if action not in self.actions or not isinstance(matrix, list) or len(matrix) != num_s:
                raise ValueError("B transition matrix has invalid action or shape")
            if any(not isinstance(row, list) or len(row) != num_s for row in matrix):
                raise ValueError("B transition matrix has invalid shape")
            if any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or not math.isfinite(float(value)) or float(value) < 0
                   for row in matrix for value in row):
                raise ValueError("B transition matrix contains invalid values")
            if any(sum(float(matrix[i][j]) for i in range(num_s)) < EPS for j in range(num_s)):
                raise ValueError("B transition matrix contains an empty transition column")
        if set(self.b_matrices) != set(self.actions):
            raise ValueError("B transition matrices must cover every action")
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

    def __post_init__(self) -> None:
        if type(self.step) is not int or self.step < 0:
            raise ValueError("free-energy step must be a non-negative integer")
        for name in ("variational_free_energy_f", "complexity_kl",
                     "accuracy_log_likelihood", "surprisal_bound"):
            _finite(getattr(self, name), name)
        self.belief_state = {str(k): _finite(v, f"belief {k}") for k, v in self.belief_state.items()}
        self.evaluated_policies = list(self.evaluated_policies)
        self.telemetry = copy.deepcopy(dict(self.telemetry))
        canonical_hash(self.telemetry)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy({
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
        })

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
        if not isinstance(generative_model, GenerativeModel):
            raise TypeError("generative_model must be GenerativeModel")
        self.model = copy.deepcopy(generative_model)
        if not isinstance(policy_precision_gamma, (int, float)) or not math.isfinite(float(policy_precision_gamma)) or policy_precision_gamma < 0 or policy_precision_gamma > 1_000_000:
            raise ValueError("policy precision is invalid or out of bounds")
        self.gamma = float(policy_precision_gamma)
        self.current_beliefs: List[float] = list(self.model.d_prior)
        self._belief_commitment: str = canonical_hash(self.current_beliefs)
        self.step_count: int = 0
        self.history: List[Dict[str, Any]] = []
        self.last_observation: Optional[str] = None
        self._observation_commitment: Optional[str] = None
        self.last_prediction: List[Dict[str, Any]] = []
        self.last_action: Optional[str] = None
        self.last_update: Optional[Dict[str, float]] = None
        self.state_trusted: bool = True
        self._model_commitment: str = canonical_hash(self.model.to_dict())
        self._prediction_commitment: Optional[str] = None
        self._prediction_observation_commitment: Optional[str] = None
        self._policy_commitments: Dict[str, str] = {}
        self._policy_refs: Dict[str, Policy] = {}
        self._last_policies: List[Policy] = []
        self._action_commitment: Optional[str] = None

    def _ensure_trusted(self) -> None:
        beliefs_ok = (isinstance(self.current_beliefs, list)
                      and len(self.current_beliefs) == len(self.model.states)
                      and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                              and math.isfinite(float(x)) and float(x) >= 0
                              for x in self.current_beliefs))
        if (not self.state_trusted
                or canonical_hash(self.model.to_dict()) != self._model_commitment
                or not beliefs_ok
                or canonical_hash(self.current_beliefs) != self._belief_commitment):
            self.state_trusted = False
            raise ValueError("active-inference state is untrusted")

    def _validate_evaluations(self, evaluations: Any, *, require_bound: bool = True) -> List[PolicyEvaluation]:
        if not isinstance(evaluations, list) or not evaluations or len(evaluations) > 10_000:
            raise ValueError("predictions must be a non-empty bounded list")
        normalized: List[PolicyEvaluation] = []
        seen: Set[str] = set()
        for item in evaluations:
            if not isinstance(item, PolicyEvaluation):
                raise TypeError("predictions must contain PolicyEvaluation records")
            if item.policy_id in seen or not item.actions or any(a not in self.model.actions for a in item.actions):
                raise ValueError("prediction contains a duplicate or invalid action")
            # The object returned by predict is caller-mutable.  Compare it to
            # the private snapshot before allowing it to drive action/update.
            for value_name in ("expected_free_energy_g", "risk_pragmatic_divergence",
                                "ambiguity_expected_entropy", "epistemic_information_gain",
                                "pragmatic_goal_utility", "probability"):
                _finite(getattr(item, value_name), value_name)
            declared_policy_commitment = item.metadata.get("policy_commitment")
            if declared_policy_commitment is not None and (
                    self._policy_commitments.get(item.policy_id) != declared_policy_commitment
                    or (item.policy_id in self._policy_refs
                        and self._policy_refs[item.policy_id].commitment() != declared_policy_commitment)):
                raise PermissionError("policy record is not bound to this prediction")
            seen.add(item.policy_id)
            normalized.append(item)
        if require_bound:
            if (self._prediction_commitment is None
                    or self._prediction_observation_commitment != self._observation_commitment):
                raise PermissionError("predictions are not bound to the current observation")
            if canonical_hash([x.to_dict() for x in normalized]) != self._prediction_commitment:
                raise PermissionError("predictions were modified or are not bound to this engine")
        return normalized

    def observe(self, observation: str) -> str:
        """Record an observation from the environment (no self-reported state)."""
        self._ensure_trusted()
        if observation not in self.model.observations:
            raise ValueError(f"Unknown observation '{observation}'. Available: {self.model.observations}")
        self.last_observation = observation
        self._observation_commitment = canonical_hash(observation)
        return observation

    def predict(self, candidate_policies: Optional[List[Policy]] = None) -> List[PolicyEvaluation]:
        """Predict policy outcomes from the current posterior without acting."""
        self._ensure_trusted()
        policies = candidate_policies or [
            Policy(policy_id=f"policy_{act}", actions=[act], label=f"Execute {act}")
            for act in self.model.actions
        ]
        if not isinstance(policies, list) or len(policies) > 10_000:
            raise ValueError("too many candidate policies")
        seen_policy_ids: Set[str] = set()
        for policy in policies:
            if not isinstance(policy, Policy):
                raise TypeError("candidate policies must be Policy records")
            if policy.policy_id in seen_policy_ids or any(a not in self.model.actions for a in policy.actions):
                raise ValueError("candidate policy contains duplicate or invalid actions")
            # Capture the complete policy before evaluation; a caller must not
            # mutate actions or metadata between predict and act.
            self._policy_commitments[policy.policy_id] = policy.commitment()
            self._policy_refs[policy.policy_id] = policy
            seen_policy_ids.add(policy.policy_id)
        self._last_policies = list(policies)
        evaluations = [self.evaluate_policy(policy) for policy in policies]
        for evaluation, policy in zip(evaluations, policies):
            evaluation.metadata["policy_commitment"] = self._policy_commitments[policy.policy_id]
        self.last_prediction = [copy.deepcopy(evaluation.to_dict()) for evaluation in evaluations]
        self._prediction_commitment = canonical_hash(self.last_prediction)
        self._prediction_observation_commitment = self._observation_commitment
        return evaluations

    def act(self, predictions: Optional[List[PolicyEvaluation]] = None) -> str:
        """Select an action only from an untampered, engine-bound prediction set."""
        self._ensure_trusted()
        if predictions is None:
            if self._prediction_commitment is not None and self.last_prediction:
                evaluations = [PolicyEvaluation.from_dict(copy.deepcopy(item))
                               for item in self.last_prediction]
            else:
                evaluations = self.predict()
        else:
            evaluations = predictions
        self._validate_evaluations(evaluations, require_bound=True)
        selected = min(evaluations, key=lambda item: item.expected_free_energy_g)
        if not selected.actions or selected.actions[0] not in self.model.actions:
            raise ValueError("selected prediction contains an invalid action")
        self.last_action = selected.actions[0]
        self._action_commitment = canonical_hash({
            "action": self.last_action,
            "predictions": self._prediction_commitment,
        })
        return self.last_action

    def update(self, observation: Optional[str] = None) -> Dict[str, float]:
        """Update beliefs from the bound observation and prediction set only."""
        self._ensure_trusted()
        if self.last_observation is None:
            raise PermissionError("update requires a prior observed environment value")
        observed = self.last_observation if observation is None else observation
        if (observed != self.last_observation or observed not in self.model.observations
                or self._observation_commitment != canonical_hash(self.last_observation)):
            raise PermissionError("update observation is not bound to the prior observation")
        if self._prediction_commitment is None or self.last_action is None:
            raise PermissionError("update requires bound predictions and a selected action")
        self._validate_evaluations(
            [PolicyEvaluation.from_dict(item) for item in self.last_prediction],
            require_bound=True,
        )
        if self._action_commitment != canonical_hash({
                "action": self.last_action, "predictions": self._prediction_commitment}):
            raise PermissionError("selected action is not bound to the current predictions")
        f_val, complexity, accuracy = self.update_beliefs(observed)
        for name, value in (("variational_free_energy_f", f_val),
                            ("complexity_kl", complexity),
                            ("accuracy_log_likelihood", accuracy)):
            _finite(value, name)
        self.last_update = {
            "variational_free_energy_f": f_val,
            "complexity_kl": complexity,
            "accuracy_log_likelihood": accuracy,
        }
        return dict(self.last_update)

    def observe_predict_act_update(
        self, observation: str, candidate_policies: Optional[List[Policy]] = None
    ) -> Dict[str, Any]:
        """Run the complete observe -> predict -> act -> update lifecycle."""
        self.observe(observation)
        predictions = self.predict(candidate_policies)
        action = self.act(predictions)
        update = self.update(observation)
        self.step_count += 1
        record = {
            "step": self.step_count, "observation": observation,
            "policies": [copy.deepcopy(policy.to_dict()) for policy in self._last_policies],
            "predictions": [item.to_dict() for item in predictions],
            "action": action, "update": update,
        }
        # ``candidate_policies`` is None when defaults were generated; retain
        # the actual policy records so a restored cycle can revalidate mutable
        # labels, descriptions, and metadata as well as its actions.
        if not record["policies"]:
            record["policies"] = [
                {"policy_id": item.policy_id, "actions": list(item.actions),
                 "label": "", "description": "", "metadata": {}}
                for item in predictions
            ]
        self.history.append(copy.deepcopy(record))
        return record

    def update_beliefs(self, observation: str) -> Tuple[float, float, float]:
        """
        Perception step: Update posterior state beliefs q(s) given observation o:
        ln q*(s) = ln p(s) + ln p(o | s) - ln Z
        Returns (Free_Energy_F, Complexity_KL, Accuracy_Log_Likelihood).
        """
        self._ensure_trusted()
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
        self._belief_commitment = canonical_hash(self.current_beliefs)

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
        self._ensure_trusted()
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
        self._ensure_trusted()
        if not isinstance(candidate_policies, list):
            raise TypeError("candidate_policies must be a list")
        self.step_count += 1

        # 1. Perception
        if observation not in self.model.observations:
            raise ValueError(f"Unknown observation '{observation}'. Available: {self.model.observations}")
        self.last_observation = observation
        self._observation_commitment = canonical_hash(observation)
        f_val, comp_kl, acc_ll = self.update_beliefs(observation)

        if not candidate_policies:
            # Generate default 1-step policies for all actions
            candidate_policies = [
                Policy(policy_id=f"policy_{act}", actions=[act], label=f"Execute {act}")
                for act in self.model.actions
            ]

        if not candidate_policies or any(not isinstance(p, Policy) or not p.actions
                                         or any(a not in self.model.actions for a in p.actions)
                                         for p in candidate_policies):
            raise ValueError("candidate policies contain invalid actions")
        if len({p.policy_id for p in candidate_policies}) != len(candidate_policies):
            raise ValueError("candidate policies contain duplicate identifiers")
        self._last_policies = list(candidate_policies)
        for policy in candidate_policies:
            self._policy_commitments[policy.policy_id] = policy.commitment()
            self._policy_refs[policy.policy_id] = policy

        # 2. Policy Planning
        evaluations = [self.evaluate_policy(p) for p in candidate_policies]
        for evaluation, policy in zip(evaluations, candidate_policies):
            evaluation.metadata["policy_commitment"] = self._policy_commitments[policy.policy_id]
        self.last_prediction = [copy.deepcopy(evaluation.to_dict()) for evaluation in evaluations]
        self._prediction_commitment = canonical_hash(self.last_prediction)
        self._prediction_observation_commitment = self._observation_commitment

        # 3. Policy Posterior P(pi) = softmax(-gamma * G)
        neg_g_values = [-self.gamma * e.expected_free_energy_g for e in evaluations]
        probs = _softmax(neg_g_values)
        for e, p in zip(evaluations, probs):
            e.probability = p

        # Find best policy (minimum G)
        best_eval = min(evaluations, key=lambda e: e.expected_free_energy_g)
        best_eval.is_optimal = True
        selected_action = best_eval.actions[0] if best_eval.actions else self.model.actions[0]
        self.last_action = selected_action
        self._action_commitment = canonical_hash({
            "action": selected_action, "predictions": self._prediction_commitment})

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
        self._ensure_trusted()
        return {
            "model": self.model.to_dict(),
            "gamma": self.gamma,
            "current_beliefs": self.current_beliefs,
            "step_count": self.step_count,
            "history": copy.deepcopy(self.history),
            "last_observation": self.last_observation,
            "last_prediction": copy.deepcopy(self.last_prediction),
            "last_action": self.last_action,
            "last_update": copy.deepcopy(self.last_update),
            "state_trusted": bool(self.state_trusted),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActiveInferenceEngine":
        """Restore only a structurally and semantically consistent history."""
        if not isinstance(data, dict) or not isinstance(data.get("model"), dict):
            raise ValueError("restored inference state requires a model mapping")
        model = GenerativeModel.from_dict(copy.deepcopy(data["model"]))
        engine = cls(generative_model=model, policy_precision_gamma=data.get("gamma", 16.0))
        if data.get("state_trusted", True) is not True:
            engine.state_trusted = False
            raise ValueError("restored active-inference state is explicitly untrusted")
        beliefs = data.get("current_beliefs", model.d_prior)
        if (not isinstance(beliefs, list) or len(beliefs) != len(model.states)
                or any(not isinstance(x, (int, float)) or isinstance(x, bool)
                       or not math.isfinite(float(x)) or float(x) < 0 for x in beliefs)):
            raise ValueError("restored belief state is invalid")
        total = sum(float(x) for x in beliefs)
        if total < EPS or abs(total - 1.0) > 1e-6:
            raise ValueError("restored belief state is not normalized")
        engine.current_beliefs = [float(x) for x in beliefs]

        step_count = data.get("step_count", 0)
        if type(step_count) is not int or step_count < 0 or step_count > 1_000_000:
            raise ValueError("restored inference step count is invalid")
        history = data.get("history", [])
        if not isinstance(history, list) or len(history) > 100_000 or len(history) != step_count:
            raise ValueError("restored inference history/step count mismatch")
        valid_actions = set(model.actions)
        valid_observations = set(model.observations)
        for index, record in enumerate(history, 1):
            if not isinstance(record, dict) or record.get("step") != index:
                raise ValueError("restored inference history has invalid step ordering")
            observation = record.get("observation")
            action = record.get("action")
            if observation not in valid_observations or action not in valid_actions:
                raise ValueError("restored inference history has invalid observation/action")
            policies_data = record.get("policies")
            if policies_data is not None:
                if (not isinstance(policies_data, list) or not policies_data
                        or len(policies_data) > 10_000):
                    raise ValueError("restored inference history has invalid policy records")
                policies = [Policy.from_dict(copy.deepcopy(item)) for item in policies_data]
                if len({p.policy_id for p in policies}) != len(policies):
                    raise ValueError("restored policy list contains duplicates")
                if any(any(a not in valid_actions for a in p.actions) for p in policies):
                    raise ValueError("restored policy contains an invalid action")
            predictions = record.get("predictions")
            if not isinstance(predictions, list) or not predictions:
                raise ValueError("restored inference history lacks policy predictions")
            policy_ids = set()
            for prediction in predictions:
                if not isinstance(prediction, dict) or not isinstance(prediction.get("policy_id"), str):
                    raise ValueError("restored policy prediction is malformed")
                if prediction["policy_id"] in policy_ids:
                    raise ValueError("restored policy list contains duplicates")
                policy_ids.add(prediction["policy_id"])
                actions = prediction.get("actions")
                if not isinstance(actions, list) or not actions or any(a not in valid_actions for a in actions):
                    raise ValueError("restored policy contains an invalid action")
                for key in ("expected_free_energy_g", "risk_pragmatic_divergence",
                            "ambiguity_expected_entropy", "epistemic_information_gain",
                            "pragmatic_goal_utility", "probability"):
                    value = prediction.get(key)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError("restored policy contains a non-finite metric")
            update = record.get("update")
            if not isinstance(update, dict) or any(
                    not isinstance(update.get(key), (int, float)) or isinstance(update.get(key), bool)
                    or not math.isfinite(float(update.get(key)))
                    for key in ("variational_free_energy_f", "complexity_kl", "accuracy_log_likelihood")):
                raise ValueError("restored inference update is malformed")
        engine.step_count = step_count
        engine.history = copy.deepcopy(history)
        last_observation = data.get("last_observation")
        if last_observation is not None and last_observation not in valid_observations:
            raise ValueError("restored last observation is invalid")
        last_action = data.get("last_action")
        if last_action is not None and last_action not in valid_actions:
            raise ValueError("restored last action is invalid")
        last_prediction = data.get("last_prediction", [])
        if not isinstance(last_prediction, list):
            raise ValueError("restored last prediction must be a list")
        # Validate the same prediction schema by using a synthetic history row.
        if last_prediction:
            policy_ids = set()
            for prediction in last_prediction:
                if (not isinstance(prediction, dict) or not isinstance(prediction.get("policy_id"), str)
                        or prediction["policy_id"] in policy_ids
                        or not isinstance(prediction.get("actions"), list)
                        or not prediction["actions"]
                        or any(a not in valid_actions for a in prediction["actions"])):
                    raise ValueError("restored last policy list is invalid")
                policy_ids.add(prediction["policy_id"])
                for key in ("expected_free_energy_g", "risk_pragmatic_divergence",
                            "ambiguity_expected_entropy", "epistemic_information_gain",
                            "pragmatic_goal_utility", "probability"):
                    value = prediction.get(key)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError("restored last policy metric is invalid")
        last_update = data.get("last_update")
        if last_update is not None and (not isinstance(last_update, dict) or any(
                not isinstance(last_update.get(key), (int, float)) or isinstance(last_update.get(key), bool)
                or not math.isfinite(float(last_update.get(key)))
                for key in ("variational_free_energy_f", "complexity_kl", "accuracy_log_likelihood"))):
            raise ValueError("restored last update is invalid")
        if step_count == 0 and any(x is not None for x in (last_observation, last_action, last_update)):
            raise ValueError("empty restored history cannot have last-step state")
        engine.last_observation = last_observation
        engine._observation_commitment = (canonical_hash(last_observation)
                                          if last_observation is not None else None)
        engine.last_prediction = copy.deepcopy(last_prediction)
        engine.last_action = last_action
        engine.last_update = copy.deepcopy(last_update)

        # Recompute every recorded cycle from the model, rather than trusting
        # persisted predictions, actions, metrics, or beliefs.  A structurally
        # valid but numerically edited checkpoint therefore cannot become a
        # trusted inference state.
        recomputed = cls(generative_model=copy.deepcopy(model), policy_precision_gamma=engine.gamma)
        for record in history:
            if record.get("policies") is not None:
                policies = [Policy.from_dict(copy.deepcopy(p)) for p in record["policies"]]
            else:
                policies = [Policy(policy_id=p["policy_id"], actions=list(p["actions"]))
                            for p in record["predictions"]]
            expected = recomputed.observe_predict_act_update(record["observation"], policies)
            if canonical_hash(expected) != canonical_hash(record):
                raise ValueError("restored inference metrics do not match recomputed predictions")
        if engine.current_beliefs != recomputed.current_beliefs:
            raise ValueError("restored belief state does not match recomputed history")
        if last_observation != recomputed.last_observation:
            raise ValueError("restored last observation does not match recomputed state")
        if step_count and (not last_prediction
                or canonical_hash(last_prediction) != canonical_hash(recomputed.last_prediction)):
            raise ValueError("restored last prediction does not match recomputed state")
        if last_action != recomputed.last_action or last_update != recomputed.last_update:
            raise ValueError("restored last action/update does not match recomputed state")
        engine._belief_commitment = canonical_hash(engine.current_beliefs)
        engine._prediction_commitment = recomputed._prediction_commitment
        engine._prediction_observation_commitment = recomputed._prediction_observation_commitment
        engine._policy_commitments = dict(recomputed._policy_commitments)
        engine._policy_refs = dict(recomputed._policy_refs)
        engine._last_policies = list(recomputed._last_policies)
        engine._action_commitment = recomputed._action_commitment
        engine.state_trusted = True
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

# Auditable System 3 coding-loop helpers.  Kept in this shipped module so
# package manifests cannot silently omit the anti-laziness primitives.
def prediction_error(predicted: Any, observed: Any) -> float:
    """Compute bounded error from values, never from a caller success claim."""
    if isinstance(predicted, bool) or isinstance(observed, bool):
        return 0.0 if predicted == observed else 1.0
    if isinstance(predicted, (int, float)) and isinstance(observed, (int, float)):
        p, o = _finite(predicted, "predicted outcome"), _finite(observed, "observed outcome")
        return min(1.0, abs(p - o) / max(1.0, abs(p), abs(o)))
    return 0.0 if canonical_hash(predicted) == canonical_hash(observed) else 1.0


def revise_belief(confidence: float, error: float) -> Dict[str, float]:
    prior, err = _finite(confidence, "confidence"), _finite(error, "prediction_error")
    if not 0.0 <= prior <= 1.0 or not 0.0 <= err <= 1.0:
        raise ValueError("belief inputs must be in [0, 1]")
    return {"prior_confidence": prior, "posterior_confidence": max(0.0, min(1.0, prior * (1.0 - err))),
            "prediction_error": err}


def policy_revision(action: str, error: float, revision_index: int) -> Dict[str, Any]:
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be non-empty")
    err = _finite(error, "prediction_error")
    if not 0.0 <= err <= 1.0 or type(revision_index) is not int or revision_index < 1:
        raise ValueError("invalid policy revision inputs")
    payload = {"action": action.strip(), "prediction_error": err, "revision_index": revision_index}
    return {**payload, "revision_id": canonical_hash(payload)}
