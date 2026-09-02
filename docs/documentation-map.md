# Documentation source-of-truth map

Use the implementation as the authority for behavior and the matching doc for
explanation. If these disagree, fix the docs or file a compatibility note;
do not silently rely on a stale example.

| Topic | Authoritative source | Reader-facing documentation |
|---|---|---|
| Package version and release validation | `pyproject.toml`, `setup.py`, `fable_mode/__init__.py`, `build_scripts/build_release.py` | [`release-policy.md`](release-policy.md) |
| V1 MCP tool name, actions, and parameters | `fable_engine/fable_session.json` and `fable_engine/server.py:TOOL_SCHEMA` | [`mcp-reference.md`](mcp-reference.md) |
| V1 phase and unlock behavior | `fable_engine/server.py:FableSession` | [`fable-v1-theory.md`](fable-v1-theory.md), [`troubleshooting.md`](troubleshooting.md) |
| V1 process and persistence paths | `fable_mode/launcher.py`, `fable_engine/server.py` | [`data-and-artifacts.md`](data-and-artifacts.md) |
| V2 data contracts, run states, and System 3 package | `fable_v2/protocol.py`, `fable_v2/runtime.py`, `fable_v2/system3/` | [`fable-v2-architecture.md`](fable-v2-architecture.md) |
| V2 host capabilities | `fable_v2/adapters.py` | [`host-compatibility.md`](host-compatibility.md) |
| V2 broker actions and limits | `fable_v2/execution_broker.py` | [`mcp-reference.md`](mcp-reference.md), [`security-and-trust.md`](security-and-trust.md) |
| Source installation and entry points | `fable_mode/launcher.py`, `install.sh`, `install.ps1`, package metadata | [`README.md`](../README.md), [`fable-v1-v2-migration.md`](fable-v1-v2-migration.md) |
| Release artifacts and checksums | `.github/workflows/release.yml`, `build_scripts/build_release.py` | [`release-policy.md`](release-policy.md), [`data-and-artifacts.md`](data-and-artifacts.md) |
| Documentation and drift checks | `docs/check_docs.py`, `tests/test_documentation.py` | [`README.md`](../README.md), this map |
| Benchmark claims and interpretation | Study records created from this template | [`benchmark-methodology.md`](benchmark-methodology.md) |

`docs/platform.md`, `docs/use_cases.md`, and the other Zapia product notes are
account documentation rather than Fable runtime specifications. They are not
used as authority for Fable APIs.
