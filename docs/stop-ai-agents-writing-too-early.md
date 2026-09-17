# Start here: stop AI coding agents from writing too early

AI coding agents often move from a plausible plan to editing files before they have gathered enough evidence. Fable Mode adds a mechanical session gate: the agent can inspect and reason, but the Fable Engine will not report write permission until the configured authority timer and proof prerequisites pass.

Fable Mode is two separate pieces:

- **Fable Engine** is the MCP server that stores session state and enforces its gates.
- **The Fable Mode Agent Skill** is the optional workflow that tells a compatible agent how to use those gates.

Installing one does not silently activate the other.

## Install the engine

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

Run the pinned release without changing your global Python environment:

```bash
uvx --from fable-engine==1.3.6 fable-engine
```

### Claude Code

```bash
claude mcp add fable-engine -- uvx --from fable-engine==1.3.6 fable-engine
```

### Cursor or another JSON-configured MCP client

```json
{
  "mcpServers": {
    "fable-engine": {
      "command": "uvx",
      "args": ["--from", "fable-engine==1.3.6", "fable-engine"]
    }
  }
}
```

Restart or reload the client, then inspect its MCP tools. You should see `fable_session` plus the browser tools exposed by the server.

## Install the optional Agent Skill

From the root of the project where you want the skill:

```bash
uvx --from fable-engine==1.3.6 fable-mode install-skill --dry-run
uvx --from fable-engine==1.3.6 fable-mode install-skill --yes
```

The default destination is `.agents/skills/fable-mode`. Use `--target <dir>` for a different skill directory. The installer refuses to overwrite local edits unless you pass `--force`.

Reload the agent after installation.

## Run a first session

Ask your MCP client to call `fable_session` with:

```json
{
  "action": "create_session",
  "session_name": "parser-refactor",
  "objective": "Refactor the parser without changing its public behavior",
  "time_budget_minutes": 2
}
```

The result should show:

- `can_execute_code: False`;
- the active phase;
- the authority budget and remaining time;
- zero recorded evidence items and invariants.

Next, inspect the target repository and record real findings:

```json
{
  "action": "log_epistemic_item",
  "session_name": "parser-refactor",
  "tag": "PROVEN",
  "claim": "The public parser entry point is parse(text)",
  "evidence": "src/parser.py:18 and tests/test_parser.py"
}
```

Record a second evidence-backed claim and a falsifiable invariant:

```json
{
  "action": "record_invariant",
  "session_name": "parser-refactor",
  "invariant_name": "INV-01 public behavior",
  "formal_statement": "For every existing parser fixture, output before == output after",
  "proof_or_rationale": "Run the existing fixture suite before and after the change",
  "domain": "compatibility"
}
```

Use `get_status` to inspect the gate. When the timer has elapsed and prerequisites are satisfied, call `unlock_execution` with an evidence-based rationale. A rejected unlock is expected when a condition is still missing.

## What the four gates mean

1. **Think**: inspect the system and classify claims as `PROVEN`, `HYPOTHESIS`, or `UNKNOWN`.
2. **Prove**: attach evidence to key claims and define invariants that can fail.
3. **Attack**: run normal tests and targeted adversarial checks against the proposed change.
4. **Write**: edit only after the engine reports that execution is unlocked, then verify the final tree.

The minimum authority budget is two minutes. It is a floor, not a claim that two minutes is enough for every task.

## Boundaries

Fable Mode does not guarantee correct code. It also does not replace:

- the host's filesystem permissions or sandbox;
- repository instructions and review rules;
- user approval for external side effects;
- a container or VM for hostile code;
- tests, type checks, static analysis, or human review.

The V2 broker can add a separate process and policy boundary. For hostile workloads, run it inside an OS-level sandbox or container with restricted permissions.

## Troubleshooting

**The client cannot find `fable_session`.** Run the `uvx` command directly, check the MCP client configuration, and reload the client. MCP servers communicate over standard input and output; the client manages the process after configuration.

**`unlock_execution` is rejected.** Read the returned reason. Common causes are an active authority timer, fewer than two `PROVEN` items, or no recorded invariant. Do not relabel assumptions to satisfy the counter.

**The skill is installed but not used.** Confirm the destination matches the client's skill-discovery convention, then reload the client. The package cannot activate a host skill by itself.

**You need a different workflow.** The skill is guidance around the engine. Host permissions and the user's instructions still win.

## Next steps

- [Agent Skill reference](../skills/fable-mode/SKILL.md)
- [V2 architecture](./fable-v2-architecture.md)
- [V1 to V2 migration](./fable-v1-v2-migration.md)
- [System 3 architecture](./system3-architecture.md)
