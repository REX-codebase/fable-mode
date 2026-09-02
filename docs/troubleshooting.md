# Troubleshooting

## The host cannot start the server

- Confirm Python is 3.10 or newer with `python3 --version` (POSIX/WSL) or
  `py -3 --version` (Windows).
- From a source checkout, activate the virtual environment and run
  `python -m pip install -e .`.
- For a pip-installed or frozen copy, run `fable-mode verify --install-dir
  PATH` (or the packaged executable's equivalent). For a source-helper copy,
  run `python3 PATH/runtime/fable_mode_entry.py verify --install-dir PATH`
  (use `py -3` on Windows). Verification checks the manifest and an MCP
  `initialize`/`tools/list` smoke exchange.
- Use an absolute executable path in a host configuration when the host does
  not inherit the shell's PATH. Keep the host's MCP stdout connected to the
  process; logs belong on stderr.

## The host sees no tool

Send `initialize`, then `notifications/initialized`, then `tools/list`. Confirm
that the listed tool is exactly `fable_session`. A registration made by the
installer is only a configuration edit; inspect the host configuration and
restart the host if it caches MCP servers.

The installer discovers `claude`, `agy`, and `codex` only when those commands
are available. `cc` and `antigravity` are opt-in aliases. A missing or
unhealthy host command is reported rather than silently treated as supported.

## Unlock is rejected

This is expected until all V1 conditions are met: the immutable authority
budget has elapsed, two `PROVEN` entries include evidence, one invariant has a
proof or rationale, and the session has reached Phase 3 or later. A shorter
`set_timer` pacing timer does not satisfy the authority deadline. Check
`telemetry` and advance one phase at a time with a summary.

A restored checkpoint's ledger entries are marked untrusted and do not satisfy
the evidence gate on their own. Do not put an emergency token in MCP
arguments; any administrative override is intentionally out of the model's
schema.

## State or CAS errors

Set `FABLE_DATA_DIR` to a real, user-private directory and ensure its parent
components are not symlinks/reparse points or special files. The launcher can
also receive `--state-dir PATH`. Check permissions and disk space. Do not copy
session JSON between users and assume it is a trusted audit record.

For a CAS error, keep the `cas://` reference unchanged and let the normal read
path verify it. Avoid the low-level `verify=False` maintenance option for
content shown to a model or server.

## Broker returns an error

- Confirm the workspace exists and is a directory.
- Use a normalized relative path for `inspect_files` and `write_file`; absolute
  paths, `..`, dot components, links, and special files are rejected.
- Supply an argv array to `execute_command`, not a shell command string. The
  executable must be allowlisted and resolvable at broker startup.
- A write is expected to fail while `writes_enabled` is false. On POSIX, start
  with `--admin-fd FD`, configure exactly one digest source, and send the
  unlock token through the administrator-only control pipe. The model channel
  cannot unlock writes. Likewise, the default `python`/`python3`/`pytest`
  executables are interpreter-like and command execution is blocked while
  locked; use `probe`/`inspect_files` for a locked smoke check and document
  any post-unlock command explicitly.
- `--admin-fd` is not implemented for Windows in this repository. Do not work
  around it by adding a token to model-facing JSON; use a separately developed
  protected control-handle adapter.

## Tests fail locally

Run commands from the repository root and use the supported Python range:

```sh
python -m unittest discover -s tests -p 'test_server*.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
python docs/check_docs.py
```

If only documentation checks fail, update the source-of-truth map and the
corresponding docs rather than weakening the check. The checker intentionally
does not make network requests, so external URL availability must be checked
separately.
