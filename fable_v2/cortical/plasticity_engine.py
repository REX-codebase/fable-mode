"""Modular Fable Part 2: Hebbian Cortical Plasticity & Lifelong Neuro-Evolutionary Engine.

Implements Donald Hebb's learning rule ('neurons that fire together, wire together')
for continuous cognitive adaptation and immunological antibody synthesis.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
from typing import Any, Optional, Union
import uuid

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


class CorticalDomain(str, Enum):
    """The 5 Specialized Cortical Domain Lobes."""

    RUST = "rust"
    PYTHON = "python"
    DESIGN_3D = "design_3d"
    RESEARCH = "research"
    CONCURRENCY = "concurrency"


@dataclass
class HeuristicAntibody:
    """An immunological heuristic antibody synthesized from red-team scars and adversarial breakages."""

    antibody_id: str
    domain: str
    trigger_condition: str
    lethal_anti_pattern: str
    prescribed_defense: str
    severity: str = "HIGH"
    source_task_id: str = ""
    created_at: str = ""
    verified_counterfactual: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize antibody to dictionary."""
        return {
            "antibody_id": self.antibody_id,
            "domain": self.domain,
            "trigger_condition": self.trigger_condition,
            "lethal_anti_pattern": self.lethal_anti_pattern,
            "prescribed_defense": self.prescribed_defense,
            "severity": self.severity,
            "source_task_id": self.source_task_id,
            "created_at": self.created_at,
            "verified_counterfactual": self.verified_counterfactual,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HeuristicAntibody:
        """Construct HeuristicAntibody from dictionary."""
        return cls(
            antibody_id=str(d.get("antibody_id", f"ab_{uuid.uuid4().hex[:8]}")),
            domain=str(d.get("domain", "general")),
            trigger_condition=str(d.get("trigger_condition", "")),
            lethal_anti_pattern=str(d.get("lethal_anti_pattern", "")),
            prescribed_defense=str(d.get("prescribed_defense", "")),
            severity=str(d.get("severity", "HIGH")),
            source_task_id=str(d.get("source_task_id", "")),
            created_at=str(d.get("created_at", datetime.now(timezone.utc).isoformat())),
            verified_counterfactual=str(d.get("verified_counterfactual", "")),
        )

    def to_markdown(self) -> str:
        """Render antibody as structured GitHub-flavored markdown."""
        lines = [
            f"#### Antibody `{self.antibody_id}` [{self.severity.upper()}]",
            f"- **Domain**: `{self.domain}`",
            f"- **Trigger Condition**: {self.trigger_condition}",
            f"- **Lethal Anti-Pattern**: {self.lethal_anti_pattern}",
            f"- **Prescribed Defense**: {self.prescribed_defense}",
        ]
        if self.verified_counterfactual:
            lines.append(f"- **Verified Counterfactual**: `{self.verified_counterfactual}`")
        if self.source_task_id:
            lines.append(f"- **Source Task ID**: `{self.source_task_id}`")
        lines.append("")
        return "\n".join(lines)


@dataclass
class CorticalLobe:
    """A persistent specialized domain lobe in the cortical cognitive engine."""

    domain: CorticalDomain
    activation_count: int = 0
    synaptic_weights: dict[str, float] = field(default_factory=dict)
    antibodies: list[HeuristicAntibody] = field(default_factory=list)
    specialized_heuristics: list[str] = field(default_factory=list)
    last_consolidated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize lobe to dictionary."""
        return {
            "domain": self.domain.value if isinstance(self.domain, CorticalDomain) else str(self.domain),
            "activation_count": self.activation_count,
            "synaptic_weights": {k: round(float(v), 4) for k, v in self.synaptic_weights.items()},
            "antibodies": [ab.to_dict() for ab in self.antibodies],
            "specialized_heuristics": list(self.specialized_heuristics),
            "last_consolidated_at": self.last_consolidated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CorticalLobe:
        """Construct CorticalLobe from dictionary."""
        raw_domain = d.get("domain", CorticalDomain.PYTHON.value)
        if isinstance(raw_domain, CorticalDomain):
            domain_val = raw_domain
        else:
            try:
                domain_val = CorticalDomain(str(raw_domain))
            except ValueError:
                domain_val = CorticalDomain.PYTHON

        raw_antibodies = d.get("antibodies", [])
        antibodies: list[HeuristicAntibody] = []
        for item in raw_antibodies:
            if isinstance(item, HeuristicAntibody):
                antibodies.append(item)
            elif isinstance(item, dict):
                antibodies.append(HeuristicAntibody.from_dict(item))

        weights: dict[str, float] = {}
        for k, v in d.get("synaptic_weights", {}).items():
            try:
                weights[str(k)] = round(float(v), 4)
            except (ValueError, TypeError):
                weights[str(k)] = 0.5

        heuristics = [str(h) for h in d.get("specialized_heuristics", [])]

        return cls(
            domain=domain_val,
            activation_count=int(d.get("activation_count", 0)),
            synaptic_weights=weights,
            antibodies=antibodies,
            specialized_heuristics=heuristics,
            last_consolidated_at=str(d.get("last_consolidated_at", "")),
        )

    def to_markdown(self) -> str:
        """Render complete cortical lobe markdown with frontmatter and human-readable body."""
        data = self.to_dict()
        
        # Build YAML frontmatter
        if _HAS_YAML:
            frontmatter = yaml.safe_dump(data, sort_keys=False)
        else:
            frontmatter = json.dumps(data, indent=2)

        lines: list[str] = [
            "---",
            frontmatter.strip(),
            "---",
            "",
            f"# Cortical Lobe: `{self.domain.value if isinstance(self.domain, CorticalDomain) else str(self.domain)}`",
            "",
            "> [!NOTE]",
            f"> Living cortical memory lobe for specialized domain reasoning. Activation count: {self.activation_count}.",
            "",
            "## Metadata & Telemetry",
            f"- **Domain**: `{self.domain.value if isinstance(self.domain, CorticalDomain) else str(self.domain)}`",
            f"- **Activation Count**: `{self.activation_count}`",
            f"- **Total Antibodies**: `{len(self.antibodies)}`",
            f"- **Specialized Heuristics**: `{len(self.specialized_heuristics)}`",
            f"- **Last Consolidated**: `{self.last_consolidated_at or 'Never'}`",
            "",
            "## Specialized Domain Heuristics",
        ]

        if self.specialized_heuristics:
            for idx, h in enumerate(self.specialized_heuristics, 1):
                lines.append(f"{idx}. {h}")
        else:
            lines.append("- *(No domain heuristics registered yet)*")
        lines.append("")

        lines.append("## Synaptic Tool & Node Weights (Hebbian Association)")
        if self.synaptic_weights:
            lines.append("| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |")
            lines.append("| :--- | :--- | :--- |")
            for node, weight in sorted(self.synaptic_weights.items(), key=lambda x: x[1], reverse=True):
                strength = "🟢 Strong" if weight >= 0.7 else ("🟡 Moderate" if weight >= 0.4 else "⚪ Latent")
                lines.append(f"| `{node}` | `{weight:.4f}` | {strength} |")
        else:
            lines.append("- *(No active synaptic connections)*")
        lines.append("")

        lines.append("## Immunological Antibodies (Red-Team Scars)")
        if self.antibodies:
            for ab in self.antibodies:
                lines.append(ab.to_markdown())
        else:
            lines.append("- *(Zero known fatal vulnerabilities cataloged)*")
        lines.append("")

        return "\n".join(lines)

    def save_to_disk(self, lobe_path: Union[Path, str]) -> None:
        """Persist cortical lobe to disk at lobe_path."""
        path = Path(lobe_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.to_markdown()
        path.write_text(content, encoding="utf-8")

    @classmethod
    def load_from_disk(cls, lobe_path: Union[Path, str]) -> CorticalLobe:
        """Load cortical lobe from disk at lobe_path, supporting frontmatter or markdown extraction."""
        path = Path(lobe_path)
        if not path.exists():
            domain_name = path.stem
            try:
                domain = CorticalDomain(domain_name)
            except ValueError:
                domain = CorticalDomain.PYTHON
            return cls(domain=domain)

        text = path.read_text(encoding="utf-8")

        # 1. Try parsing YAML / JSON frontmatter if present
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                raw_frontmatter = parts[1].strip()
                parsed_dict: Optional[dict[str, Any]] = None
                if _HAS_YAML:
                    try:
                        parsed = yaml.safe_load(raw_frontmatter)
                        if isinstance(parsed, dict):
                            parsed_dict = parsed
                    except Exception:
                        pass
                if parsed_dict is None:
                    try:
                        parsed = json.loads(raw_frontmatter)
                        if isinstance(parsed, dict):
                            parsed_dict = parsed
                    except Exception:
                        pass

                if parsed_dict is not None:
                    return cls.from_dict(parsed_dict)

        # 2. Resilient fallback: parse human-authored markdown directly
        domain_name = path.stem
        try:
            domain = CorticalDomain(domain_name)
        except ValueError:
            domain = CorticalDomain.PYTHON

        activation_count = 0
        last_consolidated = ""
        heuristics: list[str] = []
        antibodies: list[HeuristicAntibody] = []
        weights: dict[str, float] = {}

        # Regex extractions
        act_match = re.search(r"Activation Count\*\*:\s*`?(\d+)`?", text)
        if act_match:
            activation_count = int(act_match.group(1))

        last_match = re.search(r"Last Consolidated\*\*:\s*`?([^`\n]+)`?", text)
        if last_match and last_match.group(1).strip().lower() != "never":
            last_consolidated = last_match.group(1).strip()

        # Extract heuristics
        heuristics_section = re.search(
            r"## (?:Specialized Domain Heuristics|Core Domain Invariants|Heuristics)\n(.*?)(?=\n## |\Z)",
            text,
            re.DOTALL,
        )
        if heuristics_section:
            for line in heuristics_section.group(1).splitlines():
                clean = re.sub(r"^(\d+\.|\-|\*)\s+", "", line).strip()
                if clean and not clean.startswith("*(") and not clean.startswith(">"):
                    heuristics.append(clean)

        # Extract weights from table or bullets
        table_matches = re.findall(r"\|\s*`([^`]+)`\s*\|\s*`?([0-9.]+)`?\s*\|", text)
        for node, val in table_matches:
            try:
                weights[node.strip()] = round(float(val), 4)
            except ValueError:
                pass

        # Extract antibodies
        ab_blocks = re.findall(
            r"#### Antibody `([^`]+)` \[([A-Z]+)\]\s*\n- \*\*Domain\*\*:\s*`([^`]+)`\s*\n- \*\*Trigger Condition\*\*:\s*([^\n]+)\s*\n- \*\*Lethal Anti-Pattern\*\*:\s*([^\n]+)\s*\n- \*\*Prescribed Defense\*\*:\s*([^\n]+)(?:\s*\n- \*\*Verified Counterfactual\*\*:\s*`?([^`\n]+)`?)?",
            text,
        )
        for ab_id, sev, dom, trig, lethal, defense, counterfac in ab_blocks:
            antibodies.append(
                HeuristicAntibody(
                    antibody_id=ab_id.strip(),
                    domain=dom.strip(),
                    trigger_condition=trig.strip(),
                    lethal_anti_pattern=lethal.strip(),
                    prescribed_defense=defense.strip(),
                    severity=sev.strip(),
                    created_at=last_consolidated,
                    verified_counterfactual=counterfac.strip() if counterfac else "",
                )
            )

        return cls(
            domain=domain,
            activation_count=activation_count,
            synaptic_weights=weights,
            antibodies=antibodies,
            specialized_heuristics=heuristics,
            last_consolidated_at=last_consolidated,
        )


class HebbianPlasticityEngine:
    """Production Hebbian Plasticity & Lifelong Neuro-Evolutionary Engine."""

    def __init__(self, cortex_dir: Optional[Union[Path, str]] = None) -> None:
        if cortex_dir is not None:
            self.cortex_dir = Path(cortex_dir)
        else:
            # Resolve to skills/fable-mode/cortex in project repository
            repo_root = Path(__file__).resolve().parents[2]
            cortex_candidate = repo_root / "skills" / "fable-mode" / "cortex"
            if cortex_candidate.exists() or (repo_root / "skills" / "fable-mode").exists():
                self.cortex_dir = cortex_candidate
            else:
                self.cortex_dir = Path.cwd() / "skills" / "fable-mode" / "cortex"

        self.cortex_dir.mkdir(parents=True, exist_ok=True)
        self.matrix_path = self.cortex_dir / "synaptic_matrix.json"
        self._lobes: dict[str, CorticalLobe] = {}
        self._synaptic_matrix: dict[str, dict[str, float]] = self._load_synaptic_matrix()

    def _normalize_domain(self, domain: Union[CorticalDomain, str]) -> CorticalDomain:
        """Convert string or enum to canonical CorticalDomain."""
        if isinstance(domain, CorticalDomain):
            return domain
        domain_str = str(domain).lower().strip()
        for d in CorticalDomain:
            if d.value == domain_str:
                return d
        # Fallback mapping
        if "rust" in domain_str:
            return CorticalDomain.RUST
        if "python" in domain_str:
            return CorticalDomain.PYTHON
        if "design" in domain_str or "3d" in domain_str:
            return CorticalDomain.DESIGN_3D
        if "research" in domain_str or "paper" in domain_str:
            return CorticalDomain.RESEARCH
        if "concurr" in domain_str or "race" in domain_str or "thread" in domain_str:
            return CorticalDomain.CONCURRENCY
        return CorticalDomain.PYTHON

    def _get_lobe_path(self, domain: CorticalDomain) -> Path:
        """Return filesystem path for a domain lobe markdown file."""
        return self.cortex_dir / f"{domain.value}.md"

    def _load_or_create_lobe(self, domain: CorticalDomain) -> CorticalLobe:
        """Retrieve lobe from memory or disk, initializing baseline if not found."""
        domain_key = domain.value
        if domain_key in self._lobes:
            return self._lobes[domain_key]

        lobe_path = self._get_lobe_path(domain)
        if lobe_path.exists():
            lobe = CorticalLobe.load_from_disk(lobe_path)
            lobe.domain = domain
        else:
            lobe = CorticalLobe(domain=domain)

        self._lobes[domain_key] = lobe
        return lobe

    def _load_synaptic_matrix(self) -> dict[str, dict[str, float]]:
        """Load cross-domain synaptic co-activation matrix from disk."""
        if self.matrix_path.exists():
            try:
                data = json.loads(self.matrix_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    matrix: dict[str, dict[str, float]] = {}
                    for k, row in data.items():
                        if isinstance(row, dict):
                            matrix[str(k)] = {str(col): round(float(val), 4) for col, val in row.items()}
                    return matrix
            except Exception:
                pass
        return {}

    def _save_synaptic_matrix(self) -> None:
        """Persist cross-domain synaptic co-activation matrix to disk."""
        payload = json.dumps(self._synaptic_matrix, indent=2, sort_keys=True)
        self.matrix_path.write_text(payload, encoding="utf-8")

    def activate_lobe(
        self,
        domain: Union[CorticalDomain, str],
        co_activated_nodes: Optional[list[str]] = None,
    ) -> CorticalLobe:
        """Activate a domain lobe, incrementing its usage count and priming synaptic nodes."""
        dom = self._normalize_domain(domain)
        lobe = self._load_or_create_lobe(dom)
        lobe.activation_count += 1

        if co_activated_nodes:
            for node in co_activated_nodes:
                node_clean = str(node).strip()
                if not node_clean:
                    continue
                current_w = lobe.synaptic_weights.get(node_clean, 0.20)
                # Priming increase
                primed_w = min(1.0, max(0.05, current_w + 0.02))
                lobe.synaptic_weights[node_clean] = round(primed_w, 4)

        lobe.save_to_disk(self._get_lobe_path(dom))
        return lobe

    def consolidate_task(
        self,
        domain: Union[CorticalDomain, str],
        task_id: str,
        broken_scenarios: Optional[list[dict[str, Any]]] = None,
        final_passed: bool = True,
        lessons: Optional[list[Union[dict[str, Any], str]]] = None,
        co_activated_nodes: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Consolidate task outcomes using Donald Hebb's learning rule.

        Applies:
            ΔW_ij = η * Score * (A_i * A_j)
            where η = 0.1, Score = 1.0 (passed) or 0.2 (failed),
            and homeostatically normalizes weights bounded within [0.05, 1.0].
        Synthesizes HeuristicAntibody instances from red-team scars and broken scenarios.
        """
        dom = self._normalize_domain(domain)
        lobe = self._load_or_create_lobe(dom)
        lobe.activation_count += 1

        learning_rate = 0.10
        score = 1.0 if final_passed else 0.20
        active_nodes = [str(n).strip() for n in (co_activated_nodes or []) if str(n).strip()]

        # 1. Update lobe synaptic weights via Hebb's rule
        # A_domain = 1.0, A_node = 1.0
        for node in active_nodes:
            old_w = lobe.synaptic_weights.get(node, 0.30)
            delta_w = learning_rate * score * (1.0 * 1.0)
            new_w = min(1.0, max(0.05, old_w + delta_w))
            lobe.synaptic_weights[node] = round(new_w, 4)

        # 2. Homeostatic normalization across lobe weights
        # If total synaptic weight exceeds capacity, apply soft scaling while preserving [0.05, 1.0]
        if lobe.synaptic_weights:
            max_capacity = 25.0
            total_weight = sum(lobe.synaptic_weights.values())
            if total_weight > max_capacity:
                scale_factor = max_capacity / total_weight
                for k in lobe.synaptic_weights:
                    scaled = lobe.synaptic_weights[k] * scale_factor
                    lobe.synaptic_weights[k] = round(min(1.0, max(0.05, scaled)), 4)

        # 3. Update global synaptic co-activation matrix (pairwise between nodes)
        if len(active_nodes) >= 2:
            for i in range(len(active_nodes)):
                u = active_nodes[i]
                if u not in self._synaptic_matrix:
                    self._synaptic_matrix[u] = {}
                for j in range(i + 1, len(active_nodes)):
                    v = active_nodes[j]
                    if v not in self._synaptic_matrix:
                        self._synaptic_matrix[v] = {}

                    old_pair_w = self._synaptic_matrix[u].get(v, 0.15)
                    delta_pair_w = learning_rate * score * (1.0 * 1.0)
                    new_pair_w = round(min(1.0, max(0.05, old_pair_w + delta_pair_w)), 4)

                    self._synaptic_matrix[u][v] = new_pair_w
                    self._synaptic_matrix[v][u] = new_pair_w

        # Also connect domain to active nodes in global matrix
        dom_name = dom.value
        if dom_name not in self._synaptic_matrix:
            self._synaptic_matrix[dom_name] = {}
        for node in active_nodes:
            old_dom_w = self._synaptic_matrix[dom_name].get(node, 0.20)
            new_dom_w = round(min(1.0, max(0.05, old_dom_w + (learning_rate * score))), 4)
            self._synaptic_matrix[dom_name][node] = new_dom_w
            if node not in self._synaptic_matrix:
                self._synaptic_matrix[node] = {}
            self._synaptic_matrix[node][dom_name] = new_dom_w

        # 4. Synthesize Heuristic Antibodies from red-team broken scenarios
        antibodies_added = 0
        if broken_scenarios:
            for sc in broken_scenarios:
                sc_dict = sc if isinstance(sc, dict) else (sc.to_dict() if hasattr(sc, "to_dict") else asdict(sc))
                sc_id = str(sc_dict.get("scenario_id") or uuid.uuid4().hex[:6])
                ab_id = f"ab_{dom.value}_{sc_id}"

                trigger = str(
                    sc_dict.get("hypothesis")
                    or sc_dict.get("trigger_condition")
                    or f"Adversarial probe {sc_id}"
                )
                lethal = str(
                    sc_dict.get("error_message")
                    or sc_dict.get("lethal_anti_pattern")
                    or "Unchecked execution failure under adversarial pressure"
                )
                prescribed = (
                    sc_dict.get("prescribed_defense")
                    or sc_dict.get("remediation_directives")
                    or sc_dict.get("remediation")
                    or "Enforce strict precondition verification and atomic isolation."
                )
                if isinstance(prescribed, list):
                    prescribed = "; ".join(str(item) for item in prescribed)
                else:
                    prescribed = str(prescribed)

                severity = str(sc_dict.get("severity", "HIGH")).upper()
                counterfac = str(
                    sc_dict.get("reproduction_code")
                    or sc_dict.get("verified_counterfactual")
                    or f"Counterfactual validation against vector: {sc_dict.get('vector', 'chaos')}"
                )

                # Deduplicate by antibody_id or trigger_condition
                existing = any(
                    a.antibody_id == ab_id or a.trigger_condition == trigger
                    for a in lobe.antibodies
                )
                if not existing:
                    antibody = HeuristicAntibody(
                        antibody_id=ab_id,
                        domain=dom.value,
                        trigger_condition=trigger,
                        lethal_anti_pattern=lethal,
                        prescribed_defense=prescribed,
                        severity=severity,
                        source_task_id=task_id,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        verified_counterfactual=counterfac,
                    )
                    lobe.antibodies.append(antibody)
                    antibodies_added += 1

        # 5. Extract specialized heuristics from lessons
        heuristics_added = 0
        if lessons:
            for item in lessons:
                heuristic_text = ""
                if isinstance(item, str):
                    heuristic_text = item.strip()
                elif isinstance(item, dict):
                    heuristic_text = str(
                        item.get("heuristic") or item.get("lesson") or item.get("rule") or ""
                    ).strip()

                if heuristic_text and heuristic_text not in lobe.specialized_heuristics:
                    lobe.specialized_heuristics.append(heuristic_text)
                    heuristics_added += 1

        # 6. Save lobe and synaptic matrix to disk
        timestamp = datetime.now(timezone.utc).isoformat()
        lobe.last_consolidated_at = timestamp
        lobe.save_to_disk(self._get_lobe_path(dom))
        self._save_synaptic_matrix()

        return {
            "status": "CONSOLIDATED",
            "domain": dom.value,
            "task_id": task_id,
            "final_passed": final_passed,
            "learning_rate": learning_rate,
            "score": score,
            "antibodies_added": antibodies_added,
            "total_antibodies": len(lobe.antibodies),
            "heuristics_added": heuristics_added,
            "total_heuristics": len(lobe.specialized_heuristics),
            "synaptic_weights": copy.deepcopy(lobe.synaptic_weights),
            "consolidated_at": timestamp,
        }

    def recall_cortical_context(
        self,
        domain: Union[CorticalDomain, str],
        max_antibodies: int = 5,
    ) -> str:
        """Recall high-signal cortical memory block to inject into agent/subagent prompts."""
        dom = self._normalize_domain(domain)
        lobe = self._load_or_create_lobe(dom)

        lines: list[str] = [
            f"### 🧠 Cortical Lobe Memory: `{dom.value.upper()}` (Activations: {lobe.activation_count})",
            "",
            "> [!IMPORTANT]",
            f"> Cortical recall retrieved {len(lobe.antibodies)} heuristic antibodies and {len(lobe.specialized_heuristics)} domain invariants.",
            "",
        ]

        # Top antibodies sorted by severity
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_antibodies = sorted(
            lobe.antibodies,
            key=lambda a: (severity_rank.get(a.severity.upper(), 2), a.antibody_id),
        )[:max_antibodies]

        lines.append("#### 🛡️ Immunological Heuristic Antibodies (Red-Team Scars)")
        if sorted_antibodies:
            for ab in sorted_antibodies:
                lines.append(f"- **[{ab.severity.upper()}] Trigger**: {ab.trigger_condition}")
                lines.append(f"  - **Lethal Anti-Pattern**: `{ab.lethal_anti_pattern}`")
                lines.append(f"  - **Prescribed Defense**: {ab.prescribed_defense}")
                if ab.verified_counterfactual:
                    lines.append(f"  - **Counterfactual**: `{ab.verified_counterfactual}`")
        else:
            lines.append("- *(No active antibodies in this lobe)*")
        lines.append("")

        # Active domain heuristics
        lines.append("#### ⚡ Specialized Domain Heuristics & Invariants")
        if lobe.specialized_heuristics:
            for idx, h in enumerate(lobe.specialized_heuristics[:8], 1):
                lines.append(f"{idx}. {h}")
        else:
            lines.append("- *(Baseline heuristics only)*")
        lines.append("")

        # Top wired synaptic nodes/tools
        lines.append("#### 🔗 Strongly-Wired Synaptic Companion Tools & Nodes")
        if lobe.synaptic_weights:
            top_nodes = sorted(lobe.synaptic_weights.items(), key=lambda x: x[1], reverse=True)[:6]
            for node, weight in top_nodes:
                lines.append(f"- `{node}`: weight `{weight:.4f}`")
        else:
            lines.append("- *(Zero strong synaptic co-activations)*")
        lines.append("")

        return "\n".join(lines)

    def get_synaptic_matrix(self) -> dict[str, dict[str, float]]:
        """Return the complete cross-domain synaptic co-activation matrix."""
        return copy.deepcopy(self._synaptic_matrix)
