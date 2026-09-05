---
name: security
description: Custom cortical lobe for security development and specialized heuristics
domain: security
activation_count: 15
synaptic_weights:
  red_team_swarm: 0.8082
  mutation: 0.7983
  test_harness: 0.7812
  property_oracle: 0.3648
antibodies:
- antibody_id: ab_security_sec_sqli_01
  domain: security
  trigger_condition: Unsanitized input in query
  lethal_anti_pattern: SQLSyntaxError
  prescribed_defense: Enforce parameterized queries with atomic binding
  severity: CRITICAL
  source_task_id: task_sec_01
  created_at: '2026-09-05T12:58:11.469175+00:00'
  verified_counterfactual: query("' OR 1=1 --")
specialized_heuristics: []
last_consolidated_at: '2026-09-05T14:30:10.209868+00:00'
---

# Cortical Lobe: `security`

> [!NOTE]
> Custom cortical lobe for security development and specialized heuristics
> Activation count: 15.

## Metadata & Telemetry
- **Name**: `security`
- **Description**: Custom cortical lobe for security development and specialized heuristics
- **Domain**: `security`
- **Activation Count**: `15`
- **Total Antibodies**: `1`
- **Specialized Heuristics**: `0`
- **Last Consolidated**: `2026-09-05T14:30:10.209868+00:00`

## Specialized Domain Heuristics
- *(No domain heuristics registered yet)*

## Synaptic Tool & Node Weights (Hebbian Association)
| Synaptic Node / Tool | Weight ($W_{ij}$) | Strength |
| :--- | :--- | :--- |
| `red_team_swarm` | `0.8082` | 🟢 Strong |
| `mutation` | `0.7983` | 🟢 Strong |
| `test_harness` | `0.7812` | 🟢 Strong |
| `property_oracle` | `0.3648` | ⚪ Latent |

## Immunological Antibodies (Red-Team Scars)
#### Antibody `ab_security_sec_sqli_01` [CRITICAL]
- **Domain**: `security`
- **Trigger Condition**: Unsanitized input in query
- **Lethal Anti-Pattern**: SQLSyntaxError
- **Prescribed Defense**: Enforce parameterized queries with atomic binding
- **Verified Counterfactual**: `query("' OR 1=1 --")`
- **Source Task ID**: `task_sec_01`

