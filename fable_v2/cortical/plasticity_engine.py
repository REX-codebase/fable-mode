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

    name: str = ""
    description: str = ""
    activation_count: int = 0
    synaptic_weights: dict[str, float] = field(default_factory=dict)
    antibodies: list[HeuristicAntibody] = field(default_factory=list)
    specialized_heuristics: list[str] = field(default_factory=list)
    last_consolidated_at: str = ""

    def __init__(
        self,
        name: str = "",
        description: str = "",
        activation_count: int = 0,
        synaptic_weights: Optional[dict[str, float]] = None,
        antibodies: Optional[list[HeuristicAntibody]] = None,
        specialized_heuristics: Optional[list[str]] = None,
        last_consolidated_at: str = "",
        domain: Optional[Union[CorticalDomain, str]] = None,
    ) -> None:
        if not name and domain is not None:
            self.name = domain.value if isinstance(domain, CorticalDomain) else str(domain)
        else:
            self.name = name or (domain.value if isinstance(domain, CorticalDomain) else str(domain or ""))
        self.description = description
        self.activation_count = activation_count
        self.synaptic_weights = synaptic_weights if synaptic_weights is not None else {}
        self.antibodies = antibodies if antibodies is not None else []
        self.specialized_heuristics = specialized_heuristics if specialized_heuristics is not None else []
        self.last_consolidated_at = last_consolidated_at

    @property
    def domain(self) -> Union[CorticalDomain, str]:
        """Backward compatibility: returns CorticalDomain enum if matched, else string."""
        for d in CorticalDomain:
            if d.value == self.name:
                return d
        return self.name

    @domain.setter
    def domain(self, value: Union[CorticalDomain, str]) -> None:
        if isinstance(value, CorticalDomain):
            self.name = value.value
        else:
            self.name = str(value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize lobe to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "domain": self.name,
            "activation_count": self.activation_count,
            "synaptic_weights": {k: round(float(v), 4) for k, v in self.synaptic_weights.items()},
            "antibodies": [ab.to_dict() for ab in self.antibodies],
            "specialized_heuristics": list(self.specialized_heuristics),
            "last_consolidated_at": self.last_consolidated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CorticalLobe:
        """Construct CorticalLobe from dictionary."""
        name = str(d.get("name") or d.get("domain") or "general")
        baseline_descs = {
            "rust": "Systems invariants, borrow checker mechanics, and zero-cost abstractions",
            "python": "High-performance CPython, modern typing protocols, and asyncio event loops",
            "design_3d": "Haute aesthetics, WebGPU TSL shaders, and responsive UI motion",
            "research": "First-principles epistemology, causal DAG inference, and TRIZ contradiction resolution",
            "concurrency": "Lock-free synchronization, atomic memory ordering, and race hardening",
        }
        description = str(d.get("description") or baseline_descs.get(name, ""))

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
            name=name,
            description=description,
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
            f"# Cortical Lobe: `{self.name}`",
            "",
            "> [!NOTE]",
            f"> {self.description}" if self.description else f"> Living cortical memory lobe for {self.name} reasoning.",
            f"> Activation count: {self.activation_count}.",
            "",
            "## Metadata & Telemetry",
            f"- **Name**: `{self.name}`",
            f"- **Description**: {self.description or 'Specialized cortical lobe'}",
            f"- **Domain**: `{self.name}`",
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
            lobe_name = path.stem
            return cls(name=lobe_name)

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
                    lobe = cls.from_dict(parsed_dict)
                    if not lobe.name:
                        lobe.name = path.stem
                    return lobe

        # 2. Resilient fallback: parse human-authored markdown directly
        lobe_name = path.stem
        activation_count = 0
        description = ""
        last_consolidated = ""
        heuristics: list[str] = []
        antibodies: list[HeuristicAntibody] = []
        weights: dict[str, float] = {}

        desc_match = re.search(r"Description\*\*:\s*([^\n]+)", text)
        if desc_match:
            description = desc_match.group(1).strip()
        elif lobe_name in {
            "rust": "Systems invariants, borrow checker mechanics, and zero-cost abstractions",
            "python": "High-performance CPython, modern typing protocols, and asyncio event loops",
            "design_3d": "Haute aesthetics, WebGPU TSL shaders, and responsive UI motion",
            "research": "First-principles epistemology, causal DAG inference, and TRIZ contradiction resolution",
            "concurrency": "Lock-free synchronization, atomic memory ordering, and race hardening",
        }:
            description = {
                "rust": "Systems invariants, borrow checker mechanics, and zero-cost abstractions",
                "python": "High-performance CPython, modern typing protocols, and asyncio event loops",
                "design_3d": "Haute aesthetics, WebGPU TSL shaders, and responsive UI motion",
                "research": "First-principles epistemology, causal DAG inference, and TRIZ contradiction resolution",
                "concurrency": "Lock-free synchronization, atomic memory ordering, and race hardening",
            }[lobe_name]

        name_match = re.search(r"Name\*\*:\s*`?([^`\n]+)`?", text)
        if name_match:
            lobe_name = name_match.group(1).strip()

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
            name=lobe_name,
            description=description,
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

    def _normalize_domain(self, domain: Union[CorticalDomain, str]) -> str:
        """Convert string or enum to canonical lobe name slug."""
        if isinstance(domain, CorticalDomain):
            return domain.value
        domain_str = str(domain).strip()
        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', domain_str.lower()).strip('_')
        if not slug:
            return "custom_lobe"
        # Check if slug directly matches a built-in domain
        for d in CorticalDomain:
            if d.value == slug:
                return d.value
        # Check if lobe file already exists on disk
        if (self.cortex_dir / f"{slug}.md").exists():
            return slug
        if slug in self._lobes:
            return slug
        # Backward compatibility aliases for built-in lobes
        if "rust" in slug:
            return CorticalDomain.RUST.value
        if "python" in slug:
            return CorticalDomain.PYTHON.value
        if "design" in slug or "3d" in slug:
            return CorticalDomain.DESIGN_3D.value
        if "research" in slug or "paper" in slug:
            return CorticalDomain.RESEARCH.value
        if "concurr" in slug or "race" in slug or "thread" in slug:
            return CorticalDomain.CONCURRENCY.value
        return slug

    def _get_lobe_path(self, domain_or_name: Union[CorticalDomain, str]) -> Path:
        """Return filesystem path for a domain lobe markdown file."""
        slug = self._normalize_domain(domain_or_name)
        return self.cortex_dir / f"{slug}.md"

    def _load_or_create_lobe(
        self,
        domain_or_name: Union[CorticalDomain, str],
        description: Optional[str] = None,
    ) -> CorticalLobe:
        """Retrieve lobe from memory or disk, initializing or auto-sprouting if not found."""
        slug = self._normalize_domain(domain_or_name)
        if slug in self._lobes:
            lobe = self._lobes[slug]
            if description and not lobe.description:
                lobe.description = description
            return lobe

        lobe_path = self._get_lobe_path(slug)
        if lobe_path.exists():
            lobe = CorticalLobe.load_from_disk(lobe_path)
            if not lobe.name:
                lobe.name = slug
            if description and not lobe.description:
                lobe.description = description
        else:
            desc = description or f"Custom cortical lobe for {slug} development and specialized heuristics"
            lobe = CorticalLobe(name=slug, description=desc)
            lobe.save_to_disk(lobe_path)

        self._lobes[slug] = lobe
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

    def define_cortical_lobe(
        self,
        name: str = "",
        description: str = "",
        initial_heuristics: Optional[list[str]] = None,
        initial_synaptic_weights: Optional[dict[str, float]] = None,
        lobe_name: str = "",
    ) -> CorticalLobe:
        """Allows the AI or user to dynamically sprout a new Cortical Lobe from scratch!

        Cleans/slugifies the name, creates the lobe with name, description, initial heuristics,
        saves it to disk as cortex/<slug>.md, and integrates it into the synaptic matrix.
        """
        raw = str(name or lobe_name).strip()
        slug = re.sub(r'[^a-zA-Z0-9_-]', '_', raw.lower()).strip('_')
        if not slug:
            slug = "custom_lobe"

        clean_heuristics = [str(h).strip() for h in (initial_heuristics or []) if str(h).strip()]
        weights: dict[str, float] = {}
        if initial_synaptic_weights:
            for k, v in initial_synaptic_weights.items():
                try:
                    weights[str(k)] = round(min(1.0, max(0.05, float(v))), 4)
                except (ValueError, TypeError):
                    weights[str(k)] = 0.50

        desc = description.strip() if description else f"Custom cortical lobe for {slug} development and specialized heuristics"

        lobe = CorticalLobe(
            name=slug,
            description=desc,
            activation_count=1,
            synaptic_weights=weights,
            specialized_heuristics=clean_heuristics,
            last_consolidated_at=datetime.now(timezone.utc).isoformat(),
        )

        lobe_path = self.cortex_dir / f"{slug}.md"
        lobe.save_to_disk(lobe_path)
        self._lobes[slug] = lobe

        # Integrate into synaptic matrix
        if slug not in self._synaptic_matrix:
            self._synaptic_matrix[slug] = {}
        for node, w in weights.items():
            self._synaptic_matrix[slug][node] = w
            if node not in self._synaptic_matrix:
                self._synaptic_matrix[node] = {}
            self._synaptic_matrix[node][slug] = w

        self._save_synaptic_matrix()
        return lobe

    def activate_lobe(
        self,
        domain_or_name: Union[CorticalDomain, str] = "",
        description: Optional[str] = None,
        co_activated_nodes: Optional[list[str]] = None,
        domain: Optional[Union[CorticalDomain, str]] = None,
        name: Optional[Union[CorticalDomain, str]] = None,
    ) -> CorticalLobe:
        """Activate a domain lobe, incrementing its usage count and priming synaptic nodes.

        If the lobe does not exist, dynamically auto-sprouts it with name and description.
        """
        # Handle positional argument fallback if co_activated_nodes was passed as 2nd arg
        if isinstance(description, (list, tuple, set)):
            co_activated_nodes = list(description)
            description = None

        target = domain or name or domain_or_name
        if not target:
            raise ValueError("activate_lobe requires domain or lobe name.")

        slug = self._normalize_domain(target)
        lobe_path = self._get_lobe_path(slug)

        is_new = (slug not in self._lobes) and (not lobe_path.exists())
        if is_new:
            desc = description or f"Custom cortical lobe for {slug} development and specialized heuristics"
            lobe = self.define_cortical_lobe(name=slug, description=desc)
        else:
            lobe = self._load_or_create_lobe(slug, description=description)
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

        lobe.save_to_disk(self._get_lobe_path(slug))
        return lobe

    def list_cortical_lobes(self) -> list[dict[str, Any]]:
        """Dynamically scans <cortex_dir>/*.md on disk.

        Returns list of metadata dicts for all available lobes:
        (name, description, activation_count, antibody_count, heuristic_count, file_path).
        """
        lobes_meta: list[dict[str, Any]] = []
        if not self.cortex_dir.exists():
            return lobes_meta

        for md_file in sorted(self.cortex_dir.glob("*.md")):
            try:
                lobe = CorticalLobe.load_from_disk(md_file)
                lobes_meta.append({
                    "name": lobe.name or md_file.stem,
                    "description": lobe.description,
                    "activation_count": lobe.activation_count,
                    "antibody_count": len(lobe.antibodies),
                    "heuristic_count": len(lobe.specialized_heuristics),
                    "file_path": str(md_file.resolve()),
                })
            except Exception:
                lobes_meta.append({
                    "name": md_file.stem,
                    "description": "",
                    "activation_count": 0,
                    "antibody_count": 0,
                    "heuristic_count": 0,
                    "file_path": str(md_file.resolve()),
                })

        return lobes_meta

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
        slug = self._normalize_domain(domain)
        lobe = self._load_or_create_lobe(slug)
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
        dom_name = slug
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
                ab_id = f"ab_{slug}_{sc_id}"

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
                        domain=slug,
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
        lobe.save_to_disk(self._get_lobe_path(slug))
        self._save_synaptic_matrix()

        return {
            "status": "CONSOLIDATED",
            "domain": slug,
            "name": slug,
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
        slug = self._normalize_domain(domain)
        lobe = self._load_or_create_lobe(slug)

        lines: list[str] = [
            f"### 🧠 Cortical Lobe Memory: `{slug.upper()}` (Activations: {lobe.activation_count})",
            "",
        ]

        if lobe.description:
            lines.append(f"> **Description**: {lobe.description}")
            lines.append("")

        lines.extend([
            "> [!IMPORTANT]",
            f"> Cortical recall retrieved {len(lobe.antibodies)} heuristic antibodies and {len(lobe.specialized_heuristics)} domain invariants.",
            "",
        ])

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
