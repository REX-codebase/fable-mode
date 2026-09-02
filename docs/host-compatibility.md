# Host and platform compatibility

This matrix distinguishes what has actually run in repository automation from
what is only documented or experimental. A host profile is an expected
capability set, not an attestation. An adapter must probe the live host and
call `HostCapabilities.attest(...)` before treating the report as
authoritative.

## Platform status

| Environment | V1 source suite | V2 foundation suite | Release artifact | Status |
|---|---:|---:|---:|---|
| Ubuntu GitHub runner, Python 3.10-3.12 | Yes | Yes | Linux x86_64 | Tested in CI |
| macOS GitHub runner, Python 3.10-3.12 | Yes | Yes | macOS x86_64 and arm64 | Tested in CI |
| Windows GitHub runner, Python 3.10-3.12 | Yes | Yes | Windows x86_64 | Tested in CI |
| WSL2 with Python 3.10+ | No dedicated runner | Python code is expected to run as Linux source | No WSL archive | Documented, not CI-tested |
| macOS arm64 source | No dedicated source runner | No dedicated source runner | macOS arm64 release archive | Release artifact tested in the macOS 15 Apple Silicon build; source mode remains locally validated |
| Linux arm64 source | No dedicated runner | No dedicated runner | No arm64 release archive | Documented as a possible source build; validate locally |
| Python older than 3.10 | No | No | No | Not supported |
| 32-bit release target | No | No | No | Not supported by published artifacts |

The CI matrix tests the project and packaging paths. It does not test every
combination of Python patch release, shell, filesystem, host CLI, or model.
Release archives are architecture-specific and should not be assumed to run
on another architecture.

## Host integration status

| Host/integration | V1 MCP registration | V2 profile | Status and caveat |
|---|---|---|---|
| Generic MCP stdio client | The server is a standard local stdio MCP process | Not automatic | Documented; test the client's MCP version and process launch |
| Antigravity | Discoverable file-backed registration path | Expected profile in `fable_v2.adapters` | Experimental adapter surface; live probe required |
| Claude Code | Discoverable CLI registration when its command is available | Expected profile | Experimental integration; CLI behavior is host-owned |
| Codex | Discoverable CLI registration when its command is available | Expected profile | Experimental integration; CLI behavior is host-owned |
| Cursor | No built-in registration claim | Expected profile | Experimental V2 profile only; no adapter is shipped |
| Zapia | No built-in registration claim | Expected profile | Experimental V2 profile only; no adapter is shipped |
| Grok Build | No built-in registration claim | Empty expected profile | Not implemented; an external adapter would be needed |
| Unknown host | No automatic compatibility claim | Empty expected profile | Not supported by default; implement and attest an adapter |

The V1 installer discovers `claude`, `agy`, and `codex`; aliases `cc` and
`antigravity` are opt-in. Discovery and registration are not proof that the
host will expose or enforce the resulting tool. Review the generated
configuration and run a smoke test.

## V2 broker caveats

The broker works as a Python process on supported source platforms, but its
administrator control option `--admin-fd` currently requires POSIX. Therefore
this repository does not provide a complete Windows V2 write-unlock path.
Windows deployments need an equivalent protected control-handle adapter before
claiming that capability. On every OS, the broker is a policy boundary and
should be combined with OS-level isolation for untrusted workloads.
