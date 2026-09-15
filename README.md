<div align="center">

<br/>

<img src="./assets/logo-light-mode.svg" width="120" alt="Fable Mode"/>

# Fable Mode

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
<img src="https://img.shields.io/badge/tests-473%20passing-black" alt="473 tests passing"/>

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

https://github.com/user-attachments/assets/27f4f8a2-b1bb-4398-a08c-bc9fd93d69d7

<br/>

### See it work

A session starts locked. Confidence does not unlock it.

```text
>>> session = create_session('demo-refactor', budget='2 min')
    state=INIT  execution_locked=True  can_execute_code=False

>>> session.unlock_execution('the plan looks fine, let me write code now')
    PermissionError: HARD TIME-LOCK VIOLATION: Execution unlock rejected!
    The immutable 2.0m authority budget has not elapsed yet
    (Remaining: 1m 59s / 120.0s).
```

The same gates guard every phase: evidence receipts for claims, a five-vector
red-team swarm for code, and a sealed record of what was verified.

<br/>

### Install

```bash
pip install fable-engine
```

Point your agent at the MCP server:

```jsonc
// Claude Code: claude mcp add fable-engine -- python -m fable_engine.server
// Cursor: ~/.cursor/mcp.json
{
  "mcpServers": {
    "fable-engine": {
      "command": "python",
      "args": ["-m", "fable_engine.server"]
    }
  }
}
```

Python 3.10+, zero runtime dependencies. PyPI package publishing is in progress.

<br/>

### How it works

1. **Think** — Time-locked deliberation. The agent cannot write until the timer ends.
2. **Prove** — Claims need real evidence (tool receipts, hashes, invariants).
3. **Attack** — A red-team swarm tries to break the code.
4. **Write** — Only then is the workspace unlocked.

<br/>

### What it is not

- Not a claim of flawless code. It is a checkable workflow, not a guarantee.
- Not a bigger prompt. The locks are enforced by the engine, not by wording.
- Not a framework lock-in. It speaks MCP and runs beside your current agent.

<br/>

### Docs

- [V1 → V2 migration](./docs/fable-v1-v2-migration.md)
- [V2 architecture](./docs/fable-v2-architecture.md)
- [System 3 (experimental)](./docs/system3-architecture.md)

<br/>

### Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

<br/>

---

<div align="center">

<sub>MIT License · Built by REX</sub>

</div>
