# Fable Mode Marketing Audit Brief

## Product positioning

Fable Mode is an open-source, Python 3.10+, dependency-free MCP cognitive-engine layer for AI coding agents. Its strongest differentiator is not generic “better reasoning”; it is **mechanically enforced engineering deliberation**: a time-lock and state machine delay workspace authority until evidence, verification, and adversarial review requirements are satisfied.

## Primary audience

The clearest initial audience is technically sophisticated AI-agent builders, coding-agent power users, MCP adopters, and developers who care about reliability, reproducibility, security, and testable execution. Secondary audiences are research engineers exploring verifier-guided agents and maintainers of complex Python/TypeScript/Rust systems.

## Best marketing wedge

Lead with the concrete pain: coding agents can start editing too quickly and accept plausible-but-unverified work. Present Fable Mode as a **safety and quality control plane for agentic software engineering**, not as a claim that it produces flawless code or human-like cognition.

## Proof points available in the repository

| Proof point | Evidence location |
|---|---|
| Open source and MIT licensed | LICENSE, README badges |
| Python 3.10+ and zero runtime dependencies | pyproject.toml, README |
| MCP JSON-RPC integration | README and fable_engine/fable_session.json |
| Mechanical time-lock and six-phase lifecycle | README and rules/fable-mode.md |
| Closed-loop red-team remediation | README, fable_v2, tests/test_redteam_remediation.py |
| Proof receipts, AST/symbol grounding, checksums | v1.3.0 release notes and fable_v2/proof_engine.py |
| Cross-platform CI | .github/workflows/test.yml: Ubuntu, macOS, Windows; Python 3.10–3.12 |
| Broad automated test coverage | tests/ and CI; README claims 183 tests, while the current checkout contains 267 test functions, so the badge should be reconciled before promotion |
| Current release | v1.3.0, published 2026-09-02 |
| Current public traction | 21 GitHub stars and 1 fork observed on the repository page |

## Messaging risks to fix

1. Avoid unsupported absolute claims such as “flawless code,” “ungameable,” “0ms startup overhead,” and “omniscient” in top-level promotional copy unless each is precisely scoped and demonstrated.
2. The repository currently presents V1, V2, and System 3 concepts together. Marketing should separate the stable user journey from frontier/experimental modules.
3. The README is technically rich but has a high cognitive load. A quick-start path, 60-second demo, and “what it does / does not do” section should appear before deep architecture.
4. The README badge says 183/183 tests while the checkout contains 267 test functions; validate and update the badge or explain the counting method.
5. The GitHub About panel has no visible description or topics. This is an immediate discoverability gap.

## Recommended one-line positioning

> Fable Mode is an open-source MCP control plane that makes AI coding agents deliberate, verify, and survive adversarial review before they earn permission to modify your workspace.

## Recommended short pitch

> AI coding agents are fast at editing and unreliable at knowing when they should wait. Fable Mode adds a deterministic control layer: mechanical time-locks, evidence-gated proof receipts, red-team remediation, and persistent engineering memory. It works with Python 3.10+, uses no runtime dependencies, and integrates through MCP.
