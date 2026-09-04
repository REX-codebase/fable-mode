---
domain: research
activation_count: 12
synaptic_weights:
  citation_verifier: 0.96
  contradiction_resolver: 0.91
  first_principles_synthesis: 0.94
  epistemic_grounding: 0.95
  latex_derivation: 0.87
  triz_dialectic: 0.89
antibodies:
- antibody_id: ab_research_hallucinated_citation
  domain: research
  trigger_condition: Emitting paper citations, authors, or benchmark numbers without
    verifying exact DOI or primary archive existence
  lethal_anti_pattern: As proven by Vaswani et al. (2021) in 'Scalable Attention Invariants'...
  prescribed_defense: Query documentation tools (e.g., query-docs, search_web) and
    verify DOI/URL before committing citation to knowledge graph.
  severity: CRITICAL
  source_task_id: task_research_citation_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Automated DOI resolver verified 100% of citations in literature
    review
- antibody_id: ab_research_cherry_picked_benchmarks
  domain: research
  trigger_condition: Reporting throughput or latency metrics under artificial isolated
    synthetic conditions without reporting tail percentiles (p99/p99.9)
  lethal_anti_pattern: Our cache achieved 12M ops/sec (ignoring 400ms p99 latency
    spikes during compaction)
  prescribed_defense: Mandate reporting median, p95, p99, and worst-case tail latencies
    alongside mean throughput.
  severity: HIGH
  source_task_id: task_research_metrics_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Test harness generated complete CDF curves demonstrating
    sustained performance
- antibody_id: ab_research_collider_bias_fallacy
  domain: research
  trigger_condition: Conditioning on a common effect (collider) when analyzing distributed
    system failure root causes
  lethal_anti_pattern: Filtering logs only for failed requests and concluding that
    network timeout causes CPU spikes
  prescribed_defense: Apply Pearl's do-calculus back-door criterion to identify and
    adjust for genuine causal parents.
  severity: MEDIUM
  source_task_id: task_research_causal_audit
  created_at: '2026-09-04T12:00:00+00:00'
  verified_counterfactual: Causal DAG model confirmed zero spurious correlation across
    50,000 trace events
specialized_heuristics:
- 'First-Principles Synthesis: Deconstruct complex empirical claims into fundamental
  physical, mathematical, or algorithmic axioms before synthesizing conclusions.'
- 'Counterfactual Citation Validation: Every paper citation or benchmark figure must
  cite a primary DOI, arXiv ID, or verified source URL; never cite ungrounded second-hand
  summaries.'
- 'Cross-Source Contradiction Resolution: When two reputable sources disagree, resolve
  the dialectical tension by identifying differing hidden boundary conditions (e.g.
  workload profile, hardware architecture, caching layers).'
- 'Epistemic State Partitioning: Explicitly tag propositions as [PROVEN] (receipt
  backed), [HYPOTHESIS] (untested inference), or [UNKNOWN] (unmeasured parameter).'
- 'Causal vs Correlative Discipline: Construct a Pearlian Directed Acyclic Graph (DAG)
  before claiming intervention efficacy; rule out confounding and collider bias.'
last_consolidated_at: '2026-09-04T12:00:00+00:00'
---

# Cortical Lobe: `research`

> [!NOTE]
> Living cortical memory lobe for specialized domain reasoning. Activation count: 12.

## Metadata & Telemetry
- **Domain**: `research`
- **Activation Count**: `12`
- **Total Antibodies**: `3`
- **Specialized Heuristics**: `5`
- **Last Consolidated**: `2026-09-04T12:00:00+00:00`

## Specialized Domain Heuristics
1. First-Principles Synthesis: Deconstruct complex empirical claims into fundamental physical, mathematical, or algorithmic axioms before synthesizing conclusions.
2. Counterfactual Citation Validation: Every paper citation or benchmark figure must cite a primary DOI, arXiv ID, or verified source URL; never cite ungrounded second-hand summaries.
3. Cross-Source Contradiction Resolution: When two reputable sources disagree, resolve the dialectical tension by identifying differing hidden boundary conditions (e.g. workload profile, hardware architecture, caching layers).
4. Epistemic State Partitioning: Explicitly tag propositions as [PROVEN] (receipt backed), [HYPOTHESIS] (untested inference), or [UNKNOWN] (unmeasured parameter).
5. Causal vs Correlative Discipline: Construct a Pearlian Directed Acyclic Graph (DAG) before claiming intervention efficacy; rule out confounding and collider bias.

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `citation_verifier` | `0.9600` | 🟢 Strong |
| `epistemic_grounding` | `0.9500` | 🟢 Strong |
| `first_principles_synthesis` | `0.9400` | 🟢 Strong |
| `contradiction_resolver` | `0.9100` | 🟢 Strong |
| `triz_dialectic` | `0.8900` | 🟢 Strong |
| `latex_derivation` | `0.8700` | 🟢 Strong |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_research_hallucinated_citation` [CRITICAL]
- **Domain**: `research`
- **Trigger Condition**: Emitting paper citations, authors, or benchmark numbers without verifying exact DOI or primary archive existence
- **Lethal Anti-Pattern**: As proven by Vaswani et al. (2021) in 'Scalable Attention Invariants'...
- **Prescribed Defense**: Query documentation tools (e.g., query-docs, search_web) and verify DOI/URL before committing citation to knowledge graph.
- **Verified Counterfactual**: `Automated DOI resolver verified 100% of citations in literature review`
- **Source Task ID**: `task_research_citation_audit`

#### Antibody `ab_research_cherry_picked_benchmarks` [HIGH]
- **Domain**: `research`
- **Trigger Condition**: Reporting throughput or latency metrics under artificial isolated synthetic conditions without reporting tail percentiles (p99/p99.9)
- **Lethal Anti-Pattern**: Our cache achieved 12M ops/sec (ignoring 400ms p99 latency spikes during compaction)
- **Prescribed Defense**: Mandate reporting median, p95, p99, and worst-case tail latencies alongside mean throughput.
- **Verified Counterfactual**: `Test harness generated complete CDF curves demonstrating sustained performance`
- **Source Task ID**: `task_research_metrics_audit`

#### Antibody `ab_research_collider_bias_fallacy` [MEDIUM]
- **Domain**: `research`
- **Trigger Condition**: Conditioning on a common effect (collider) when analyzing distributed system failure root causes
- **Lethal Anti-Pattern**: Filtering logs only for failed requests and concluding that network timeout causes CPU spikes
- **Prescribed Defense**: Apply Pearl's do-calculus back-door criterion to identify and adjust for genuine causal parents.
- **Verified Counterfactual**: `Causal DAG model confirmed zero spurious correlation across 50,000 trace events`
- **Source Task ID**: `task_research_causal_audit`

