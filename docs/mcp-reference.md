# API reference and protocol examples

## V1 MCP transport

The V1 server reads one JSON-RPC 2.0 message per line from stdin and writes
responses to stdout. Logging goes to stderr. It advertises one tool,
`fable_session`, with the schema in
[`../fable_engine/fable_session.json`](../fable_engine/fable_session.json).
The checked-in schema and runtime `TOOL_SCHEMA` must remain in sync.

### Initialize

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

A successful response includes `protocolVersion`, a `tools` capability, and
server information. Clients should then send the MCP notification (which has
no response):

```json
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
```

### List tools

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

The result contains a single tool named `fable_session`. A V1 `tools/call`
structured result uses the required fields `ok`, `action`, `text`, and
`isError`; transport success alone does not imply that the action succeeded.
`ping` is also implemented:

```json
{"jsonrpc":"2.0","id":3,"method":"ping","params":{}}
```

### Create and inspect a session

`tools/call` arguments are the tool arguments, not a second JSON-RPC request.
This creates a V1 session and persists it in the selected data directory:

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"fable_session","arguments":{"action":"create_session","session_name":"demo","objective":"Review a small change","time_budget_minutes":30}}}
```

The next request asks for telemetry:

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"fable_session","arguments":{"action":"telemetry","session_name":"demo"}}}
```

The schema's primary action values are:

```text
create_session, set_timer, get_status, telemetry, advance_phase,
log_epistemic_item, record_invariant, log_refinement_cycle,
unlock_execution, checkpoint_session, restore_session, list_sessions,
compile_delegation_contract, compress_payload, decompress_payload, view_slice,
accumulate_payload, flush_accumulator, get_compression_stats
```

Some server-side compatibility aliases exist, but clients should send the
schema's primary values. `unlock_execution` is a workflow gate, not a host
filesystem authorization. For required fields, enums, and descriptions use
the JSON schema rather than copying a partial table into a host integration.
The shipped descriptor also retains a legacy `accumulate_payload` parameter
name; the implementation reads `payload` for that action. This known
compatibility discrepancy is covered by the offline drift check and should be
removed only in a planned schema revision.

## V2 broker protocol (not MCP)

`fable-v2-broker` uses newline-delimited JSON objects on stdin/stdout. A
successful broker response has this shape. The side-effect-free `probe`
response is a stable host-facing contract with exactly these top-level fields:
`host`, `capabilities`, `available_executables`, `executable_identities`,
`execution_binding`, `writes_enabled`, `read_locked_interpreters`, `workspace`,
and `workspace_identity`.

```json
{"ok":true,"result":{"host":"fable-execution-broker","capabilities":["execute_command","inspect_files","probe_capabilities","write_file"],"available_executables":["python3"],"executable_identities":{"python3":{"path":"/absolute/path/to/python3","device":1,"inode":2,"size":12345,"mode":493,"sha256":"...","classification":"regular-executable"}},"execution_binding":"posix-open-descriptor","writes_enabled":false,"read_locked_interpreters":["bash","cmd","node","perl","powershell","python","python3","ruby","sh","zsh"],"workspace":"/absolute/path/to/workspace","workspace_identity":{"path":"/absolute/path/to/workspace","device":1,"inode":3}}}
```

Probe the broker:

```json
{"action":"probe"}
```

Inspect a normalized relative path:

```json
{"action":"inspect_files","path":"README.md","max_bytes":4096}
```

The locked-state smoke check is `probe` (and, for an existing regular file,
`inspect_files`); it does not attempt command execution:

```json
{"action":"probe"}
```

After an administrator unlocks writes through the separate control channel,
an allowlisted command may be submitted as an argv array (there is no shell
string). The default interpreter entries are deliberately rejected while
locked, so this is not a locked-state success example:

```json
{"action":"execute_command","command":["python3","--version"],"timeout_seconds":10}
```

Requesting a write while locked returns an error response. Writes become
available only after an administrator uses the separate control channel:

```json
{"action":"write_file","path":"notes/result.txt","content":"reviewed\n"}
```

The model-facing broker channel has no unlock action and accepts no write
authorization token. On POSIX the administrator can send `unlock_writes` with
the configured token through the inherited `--admin-fd` control pipe. This
channel must not be exposed to a model. On Windows, the repository does not
currently implement the `--admin-fd` path.

### MCP worker admission

Each broker stdio connection admits at most a bounded number of concurrent
`tools/call` workers. The default is 8; configure a different value for the
connection with the broker CLI option `--max-mcp-workers N` (the compatibility
alias `--max-workers N` is also accepted), where `N` is between 1 and 256.
This is a per-connection bound, not a host-wide scheduler or an OS resource
quota; deployments that need an aggregate limit should also limit broker
processes and apply OS/container controls.

When all slots are occupied, a request is rejected before its tool starts with
JSON-RPC error code `-32004`. The error has structured `data` with
`type: "overloaded"`, `reason: "mcp_worker_limit"`, `active_workers`,
`max_workers`, and `retryable: true`; clients should retry after capacity is
released. JSON-RPC notifications have no response and are dropped when
admission is full, as required by notification semantics. Completed and
cancelled calls release their slot and their worker record is removed. The
bound controls scheduling only; it does not alter the allowlist, write lock,
path checks, cancellation authorization, or process-group cleanup policy.

## Error and size behavior

Malformed V1 JSON-RPC requests receive JSON-RPC errors. Malformed broker
requests receive an `{ "ok": false, ... }` response and the broker continues
serving. Both protocols bound request/response sizes. V1's `tools/call` result
contains MCP text content; a text beginning with `Error:` is an application
result and should be surfaced as such by the host. Do not infer task
correctness from transport success.
