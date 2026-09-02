# Security and trust boundaries

Fable records and gates workflow state; it does not turn a model or a host
into a trusted computing base. Choose the boundary that matches the data and
workload.

| Component or claim | What it provides | What it does not provide |
|---|---|---|
| V1 `unlock_execution` | Server-side session conditions: elapsed authority budget, evidence-bearing ledger entries, an invariant rationale, and Phase 3+ | Correctness, OS permissions, a sandbox, or independent proof of a claim |
| V1 MCP stdio | Local process transport with bounded JSON-RPC frames/responses | Network authentication, tenant isolation, or protection from a privileged host |
| V1 `PROVEN` entry | A required non-empty evidence pointer and validation of its shape | Independent confirmation that the pointer or claim is true |
| V2 `ToolReceipt` and `Evidence` | Hash-linked invocation output and provenance relationships | Truth of the output, safe content, or authorization to run the tool |
| V2 in-process verifier | A runtime-attested result bound to a candidate in the same application | A security boundary; application code can alter its own verifier |
| V2 `process_attested` verifier | A contract for results from an isolated/authenticated verifier service | Isolation by itself, unless the deployment actually supplies it |
| V2 execution broker | Allowlisted argv execution, bounded output, path containment, and writes locked by default | A complete OS sandbox, network isolation, or protection from privileged code |
| Administrator token/control handle | Out-of-band write authorization for a configured broker | A secret that may safely be placed in model-facing JSON or prompts |
| SHA-256 CAS reference | Content addressing and integrity checks for ordinary reads | Encryption, access control, confidentiality, or authenticity of the producer |
| Checkpoint/event history | Detection of some edited/reordered state in the runtime | A signed audit record; keys or trust material must remain outside state |

## Deployment checklist

- Use a dedicated least-privilege account, workspace, and data directory.
- Put untrusted workloads in a container, VM, OS sandbox, or equivalent.
- Keep administrator tokens and signing keys out of prompts, MCP schemas,
  checkpoints, and model-readable files.
- Treat model output, tool output, receipts, evidence, and downloaded archives
  as untrusted until independently checked.
- Run deterministic checks before model judges and require evidence from the
  candidate being verified.
- Probe and attest host capabilities; do not grant permissions from an
  expected profile alone.
- Review file permissions and symlink/reparse-point behavior on the target OS.
- Do not expose the broker's administrator file descriptor to the model.
- Use the release checksum and verify the artifact's provenance before running
  it. Published artifacts are currently unsigned; a valid checksum alone does
  not identify who built an artifact.
