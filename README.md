<div align="center">

<br/>

<img src="./assets/logo-light-mode.svg" width="120" alt="Fable Mode"/>

# Fable Mode

<!-- mcp-name: io.github.REX-codebase/fable-mode -->

**Agents that think before they write.**

<br/>

<a href="https://github.com/REX-codebase/fable-mode"><img src="https://img.shields.io/badge/python-3.10%2B-black" alt="Python 3.10+"/></a>
&nbsp;
<a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-black" alt="MIT"/></a>
&nbsp;
<a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/protocol-MCP-black" alt="MCP"/></a>
&nbsp;
<img src="https://img.shields.io/badge/dependencies-0-black" alt="Zero Dependencies"/>
&nbsp;
<img src="https://img.shields.io/badge/tests-490%20passing-black" alt="490 tests passing"/>

<br/><br/>

</div>

---

<br/>

Fable Mode is an open-source control plane for AI coding agents.

It makes an agent deliberate, produce evidence, and survive adversarial review
**before** it earns permission to write to your workspace. The gates are
mechanical, not prompt advice: no timer, no proof, no write access.

<br/>

<div align="center">
  <img src="./assets/flow-simple.svg" width="720" alt="Think → Prove → Attack → Write"/>
</div>

### Demo

**KERR // ORRERY**

One self-contained HTML file. Raw WebGL, zero libraries, zero external assets,
and zero build step.

https://github.com/user-attachments/assets/8287bbfe-e3ee-4dcf-ba0f-f9ff22ae79bd

<sub>7 renders rejected before final · 2 bugs caught · 10/10 red-team probes passed</sub>

<br/>

**Fable Mode overview**

https://github.com/user-attachments/assets/27f4f8a2-b1bb-4398-a08c-bc9fd93d69d7

<br/>

### Quick start

A session starts locked. Confidence does not unlock it.

1. Install the MCP server using one of the options below.
2. Add the optional Agent Skill if you want the full workflow.
3. Ask your agent to use Fable Mode for a concrete coding task and choose a time budget.

A new session starts with execution locked:

```json
{
  "action": "create_session",
  "session_name": "demo-refactor",
  "objective": "Refactor the parser without changing public behavior",
  "time_budget_minutes": 2
}
```

The agent then records evidence and an invariant. An early `unlock_execution`
request is rejected until the authority timer and proof prerequisites pass.
Use `get_status` at any point to see the active phase, remaining time, evidence
counts, and lock state.

The same gates guard every phase: evidence receipts for claims, a five-vector
red-team swarm for code, and a sealed record of what was verified.

<br/>

### One package, two agent environments

Fable ships as one PyPI package. The same package contains the runtime, stdio
MCP server, and complete Agent Skill. Setup is explicit so installing an MCP
server never silently activates workspace instructions.

Run setup from the project the agent will work in:

```bash
uvx --from fable-engine==1.3.9 fable-mode setup --yes
```

This resolves the pinned package in an isolated uv environment and copies the
bundled skill to `.agents/skills/fable-mode`. Use `--dry-run` to preview or
`--target <dir>` for another skill directory. For a persistent install, use:

```bash
python -m pip install fable-engine
fable-mode setup --yes
```

Then choose only the invocation that matches the agent environment.

#### Native MCP client

Run `fable-engine` as the stdio server. For example:

```jsonc
// Claude Code: claude mcp add fable-engine -- uvx --from fable-engine==1.3.9 fable-engine
// Cursor or another JSON-configured client:
{
  "mcpServers": {
    "fable-engine": {
      "command": "uvx",
      "args": ["--from", "fable-engine==1.3.9", "fable-engine"]
    }
  }
}
```

[![Install MCP server in VS Code](https://img.shields.io/badge/VS_Code-Install_MCP_server-007ACC?logo=visualstudiocode&logoColor=white)](vscode:mcp/install?%7B%22name%22%3A%22fable-engine%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22fable-engine%3D%3D1.3.9%22%2C%22fable-engine%22%5D%7D)

#### Shell sandbox with internet, no MCP host

The same package exposes a direct JSON transport. Pipe one `fable_session`
argument object to `fable-mode call`:

```bash
printf '%s\n' '{"action":"create_session","session_name":"demo","objective":"Verify this change","time_budget_minutes":2}' \
  | uvx --from fable-engine==1.3.9 fable-mode call
```

The command uses JSON Lines: one `fable_session` argument object per input line
and one JSON result per output line. Keep that process open for a full workflow so
the authority timer and session stay in the same trusted runtime. A one-line pipe
is useful for a single inspection call. Each uvx command can resolve an
isolated environment; `pip install` is better when the sandbox keeps a Python
environment between calls. Session data persists outside that environment in
Fable's data directory (`FABLE_DATA_DIR` can override it).

Python 3.10+, zero runtime dependencies. Published on [PyPI as `fable-engine`](https://pypi.org/project/fable-engine/).

#### Skill activation remains explicit

`setup` is the unified path. The older `install-skill` command remains as a
compatible alias for skill-only installation. Neither `fable-engine` nor
`pip install fable-engine` writes instructions into a workspace on its own.

<br/>

### How it works

1. **Think** — Time-locked deliberation. The agent cannot write until the timer ends.
2. **Prove** — Claims need real evidence (tool receipts, hashes, invariants).
3. **Attack** — A red-team swarm tries to break the code.
4. **Write** — Only then is the workspace unlocked.

<br/>

### Optional: AI evidence adjudicator

The evidence in a session is written by an AI agent, so Fable can optionally
ask an external reviewer model to audit that evidence before the workspace
unlocks. Stdlib-only, one bounded HTTPS call, no local model, no extra RAM to
speak of. Off by default; fail-closed when enforcing. It raises the cost of
fabricated proof - it cannot guarantee deception is impossible, and the
mechanical gates stay the primary authority. Setup and honest limits:
[AI evidence adjudicator](./docs/ai-evidence-adjudicator.md).

<br/>

### What it is not

- Not a claim of flawless code. It is a checkable workflow, not a guarantee.
- Not a bigger prompt. The locks are enforced by the engine, not by wording.
- Not a framework lock-in. It speaks MCP and runs beside your current agent.

<br/>

### Docs

- [Start here: practical guide](./docs/stop-ai-agents-writing-too-early.md)
- [Agent Skill reference](./skills/fable-mode/SKILL.md)
- [V1 → V2 migration](./docs/fable-v1-v2-migration.md)
- [V2 architecture](./docs/fable-v2-architecture.md)
- [System 3 (experimental)](./docs/system3-architecture.md)
- [AI evidence adjudicator (optional)](./docs/ai-evidence-adjudicator.md)

<br/>

### Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

<br/>

---

<div align="center">

<sub>MIT License · Built by REX</sub>

</div>
