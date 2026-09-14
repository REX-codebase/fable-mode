<div align="center">

<br/>

<img src="./assets/logo-light-mode.svg" width="120" alt="Fable Mode"/>

# Fable Mode

**Agents that think before they write.**

<br/>

<img src="./assets/badge-python.svg" alt="Python 3.10+"/>
&nbsp;
<img src="./assets/badge-mit.svg" alt="MIT"/>
&nbsp;
<img src="./assets/badge-mcp.svg" alt="MCP"/>
&nbsp;
<img src="./assets/badge-stdlib.svg" alt="Zero Dependencies"/>

<br/><br/>

</div>

---

<br/>

Fable Mode is a control plane for AI coding agents.

It forces structured deliberation, evidence, and adversarial review  
**before** any code is written to your workspace.

No complexity. No hype. Just a mechanical lock that keeps agents honest.

<br/>

<div align="center">
  <img src="./assets/flow-simple.svg" width="720" alt="Think → Prove → Attack → Write"/>
</div>

<br/>

### How it works

1. **Think** — Time-locked deliberation. The agent cannot write until the timer ends.
2. **Prove** — Claims need real evidence (tool receipts, hashes, invariants).
3. **Attack** — A red-team swarm tries to break the code.
4. **Write** — Only then is the workspace unlocked.

<br/>

### Install

```bash
# Clone
git clone https://github.com/REX-codebase/fable-mode.git
cd fable-mode

# Run the MCP server
python -m fable_engine.server
```

Point your agent (Claude Code, Cursor, Codex, etc.) at the MCP server.  
That’s it.

<br/>

### Why

Most agents jump straight to editing files.  
Fable Mode makes them earn the right to touch your code.

<br/>

---

<div align="center">

<sub>MIT License · Built by REX</sub>

</div>
