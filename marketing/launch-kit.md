# Fable Mode Launch Kit

## Core narrative

AI coding agents are optimized to move. Production engineering requires them to know when to stop, inspect evidence, challenge assumptions, and earn the right to write. Fable Mode is an open-source MCP control plane that inserts those gates into the agent workflow.

The strongest public story is not “we solved AI reasoning.” It is: **we made deliberation and verification executable constraints instead of optional prompt advice.**

## 30-second demo script

1. Start with a deliberately non-trivial engineering task and show the agent entering the Fable lifecycle instead of immediately editing files.
2. Show the mechanical time-lock and the evidence ledger: the agent must state assumptions, plan the work, and produce receipts before workspace authority is unlocked.
3. Trigger a red-team review with the five attack personas: chaos environment, Byzantine payload, concurrency race, resource exhaustion, and state invariant.
4. Show a failing breakage report rejecting the milestone, followed by remediation and re-attack.
5. End on the sealed state and the one-line install path. The takeaway: **Fable Mode turns “please be careful” into a machine-checkable workflow.**

## X / Twitter launch post

AI coding agents are very good at starting.

They are less good at knowing when to stop, verify, and defend a change.

Fable Mode is an open-source MCP control plane that adds:

- mechanical time-locks
- evidence-gated proof receipts
- closed-loop red-team remediation
- persistent engineering memory

The agent does not earn workspace authority by sounding confident. It earns it by surviving the checks.

GitHub: https://github.com/REX-codebase/fable-mode

## X / Twitter technical thread

**1/7** The problem: an agent can produce a plausible patch before it has modeled the failure modes. Prompting “think harder” is not an enforcement mechanism.

**2/7** Fable Mode adds a deterministic lifecycle around agentic engineering: initialize, deliberate, implement, red-team, arbitrate, and seal.

**3/7** The workspace is not unlocked merely because a model says the task is complete. Fable records evidence, validates receipts, grounds claims against the codebase, and applies explicit transition guards.

**4/7** The red-team loop attacks five surfaces: chaotic environments, Byzantine payloads, concurrency races, resource exhaustion, and state invariants.

**5/7** If breakages remain, the milestone is rejected. The implementation is remediated and attacked again until the prior failures are actually closed.

**6/7** Fable Mode is open source, MIT licensed, Python 3.10+, dependency-free at runtime, and exposed through MCP JSON-RPC tooling.

**7/7** This is not a claim of flawless code. It is a proposal for making agentic software work more evidence-driven, adversarial, and inspectable.

Try it: https://github.com/REX-codebase/fable-mode

## LinkedIn post

Most AI coding workflows have a hidden asymmetry: the model gets permission to edit immediately, while verification arrives later—if it arrives at all.

Fable Mode is an open-source MCP control plane designed to reverse that asymmetry. It introduces mechanical time-locks, evidence-gated proof receipts, adversarial red-team review, and persistent engineering memory into the coding-agent loop.

The practical idea is simple: **workspace authority should be earned by verified evidence, not granted by fluent confidence.**

The project is written for builders working with MCP, coding agents, Python, and reliability-sensitive systems. The repository includes a cross-platform CI matrix, a deterministic lifecycle, proof-engine components, and closed-loop remediation tests.

Read the architecture and try the install path: https://github.com/REX-codebase/fable-mode

Feedback is especially welcome from people building agent runtimes, tool-use protocols, and software verification systems.

## Hacker News submission draft

**Title:** Fable Mode: An MCP control plane that makes coding agents earn workspace authority

**URL:** https://github.com/REX-codebase/fable-mode

**Text:** I built Fable Mode as an open-source experiment in making agentic software engineering more evidence-driven. Instead of relying only on prompts that ask an LLM to be careful, it wraps the workflow in explicit state transitions: deliberate first, implement, run an adversarial red-team pass, reject unresolved breakages, and seal only after remediation is verified. It also includes proof receipts, AST/symbol grounding, checksums, MCP JSON-RPC integration, and persistent domain memory. The interesting question is whether mechanical workflow constraints can reduce premature edits and confirmation bias in coding agents. I would particularly value criticism of the trust model, the red-team semantics, and where the system is over-engineered.

## Reddit / developer-community post

I’m sharing Fable Mode, an MIT-licensed open-source MCP control plane for coding agents.

The design premise is that “think harder” is not the same as an enforceable engineering process. Fable adds a deterministic lifecycle with a mechanical time-lock, evidence-gated proof receipts, an adversarial review swarm, and a closed remediation loop. The red-team pass specifically targets environmental chaos, malformed payloads, concurrency races, resource exhaustion, and state-invariant failures.

The project is intentionally opinionated and still evolving. I’m looking for technically critical feedback rather than hype: Which parts of this control model are useful? Where are the trust boundaries weak? Which integrations or benchmarks would make this credible?

Repository: https://github.com/REX-codebase/fable-mode

## Direct outreach message

Hey — I’m working on Fable Mode, an open-source MCP control plane for coding agents. It adds mechanical deliberation gates, evidence receipts, and a closed-loop red-team step before an agent can treat a change as sealed. Given your work on [agent runtimes / MCP / testing / reliability], I thought the trust-model angle might be relevant. I’d genuinely value a critical read of the architecture, especially where the enforcement boundary is still aspirational. Repo: https://github.com/REX-codebase/fable-mode

## Campaign sequence

| Day | Action | Objective |
|---|---|---|
| 1 | Publish the README update and GitHub metadata improvements | Convert repository visitors and improve search discovery |
| 2 | Post the 30-second demo clip or terminal recording | Make the mechanism tangible |
| 3 | Publish the technical thread | Explain why this is different from prompt-only workflows |
| 4 | Submit to Hacker News during an active weekday window | Invite high-signal technical criticism |
| 5 | Share the Reddit/developer-community version in one relevant community | Reach practitioners without cross-post spam |
| 6 | Open a “trust model and benchmark ideas” discussion | Turn attention into contribution |
| 7 | Publish a short follow-up with one concrete red-team failure and remediation trace | Demonstrate rather than repeat the pitch |

## Conversion improvements to measure

Track stars, forks, release downloads, README clicks into installation, issue quality, and the number of contributors who successfully run the canonical test suite. The most important near-term signal is not raw impressions; it is whether a technically serious visitor can understand the product, install it, and reproduce one evidence-gated workflow in under ten minutes.
