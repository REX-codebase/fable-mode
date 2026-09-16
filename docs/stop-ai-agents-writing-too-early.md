# Stop AI coding agents from writing too early

AI coding agents often move from a plausible plan to editing files before they have gathered enough evidence. Prompt instructions can ask them to slow down, but a model can reinterpret or skip prompt advice. Fable Mode adds a mechanical gate: the agent can inspect and reason, but it cannot earn write permission until the configured time lock and proof checks pass.

## The failure mode

A typical unsafe loop looks like this:

1. The agent reads one or two files.
2. It forms a confident hypothesis.
3. It edits code before testing the hypothesis.
4. Tests reveal a hidden constraint after the workspace has already changed.

Fable Mode separates research from authority. A session begins with execution locked. Claims need evidence receipts, implementation faces adversarial review, and the final record shows what was checked.

## Install the MCP server

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) so your MCP client can run the package without changing your global Python environment.

```bash
uvx --from fable-engine==1.3.3 fable-engine
```

For Claude Code:

```bash
claude mcp add fable-engine -- uvx --from fable-engine==1.3.3 fable-engine
```

For an MCP client that uses JSON configuration:

```json
{
  "mcpServers": {
    "fable-engine": {
      "command": "uvx",
      "args": ["--from", "fable-engine==1.3.3", "fable-engine"]
    }
  }
}
```

## What the gate changes

Fable Mode uses four stages:

- **Think:** keep execution locked while the agent gathers context and specifies invariants.
- **Prove:** attach evidence to claims instead of treating confidence as proof.
- **Attack:** try to break the proposed change through adversarial checks.
- **Write:** unlock only after the earlier gates pass.

The minimum time budget is two minutes. That is a floor, not a claim that two minutes is enough for every task. Use a longer budget when the codebase, blast radius, or uncertainty is larger.

## When to use it

Fable Mode fits work where premature edits are expensive:

- migrations and dependency upgrades;
- security-sensitive changes;
- refactors across unfamiliar code;
- changes with hidden compatibility constraints;
- autonomous coding runs where no person reviews every intermediate step.

It is not a guarantee of correct code. It makes the path to write access explicit and checkable, so a coding agent cannot treat a good-sounding plan as permission to edit.

## Verify the server before connecting a client

The package has no runtime dependencies. You can confirm the pinned release and inspect its MCP initialization response in an isolated environment before adding it to an editor or agent:

```bash
uvx --from fable-engine==1.3.3 fable-engine
```

The server communicates over standard input and output. MCP clients start and manage that process for you after configuration.

## Next steps

- Read the [V2 architecture](./fable-v2-architecture.md).
- Review the [V1 to V2 migration guide](./fable-v1-v2-migration.md).
- Inspect the source and tests in the [Fable Mode repository](https://github.com/REX-codebase/fable-mode).
