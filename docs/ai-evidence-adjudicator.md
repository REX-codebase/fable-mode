# AI Evidence Adjudicator (optional)

An external reviewer model that audits a session's recorded evidence before
execution unlocks. It exists because the evidence in a Fable session is itself
written by an AI agent, and an AI agent can fabricate plausible-looking proof.

The adjudicator is a second opinion, not a guarantee. See
[Honest limits](#honest-limits) before relying on it.

## What it does

Two layers, code first:

1. **Deterministic evidence lint** (always local, stdlib, zero network, zero
   extra RAM): flags fabrication-shaped patterns by rule - placeholder text
   (`lorem ipsum`, `TBD`, `TODO`), generic success claims with no artifact
   ("it works", "all tests passed"), evidence that restates the claim
   word-for-word (circular), the same evidence recycled across claims, empty
   evidence, failed proof receipts, and padded refinement cycles.
2. **External reviewer model** (optional, needs an API key): the engine
   bundles the session's evidence into a bounded JSON snapshot and sends it,
   clearly marked as untrusted data, to an external LLM API. The lint's
   findings travel with it as engine-computed ground truth. The model's reply
   is strictly parsed into `pass`, `fail`, or `uncertain`.

Flow at `unlock_execution`, after the mechanical gates pass:

- The lint runs always. A critical lint finding is a `fail` verdict on its
  own - deterministic findings outrank any model output.
- Without an API key, the lint alone is the verdict (the receipt records
  `llm_status: skipped_no_api_key`). With a key, the model review runs too,
  and its reply is merged with the lint findings.
- A receipt (verdict, issues, lint summary, bundle SHA-256, latency) is
  recorded in the session's proof receipts. The API key and full prompt are
  never stored.
- In `enforcing` mode, anything other than `pass` blocks the unlock.
  In `advisory` mode (default), the receipt is recorded but never blocks.

You can also request a review at any time with the `adjudicate_evidence`
action of `fable_session`.

## Resource profile

- Stdlib only. No SDK, no embedded model, no GPU.
- RAM overhead is one JSON payload capped at 24 KB plus the HTTP response.
- One HTTPS request per adjudication, default 15 s timeout (clamped 3-60 s).
- Disabled by default: zero network calls and zero behavior change.
- Enforcing mode works fully offline: the deterministic lint is the gate,
  the external reviewer only deepens it.

## Setup

```bash
export FABLE_ADJUDICATOR_ENABLED=1
export FABLE_ADJUDICATOR_API_KEY=your_key_here
# optional
export FABLE_ADJUDICATOR_STYLE=gemini        # gemini (default) | openai
export FABLE_ADJUDICATOR_MODEL=gemini-2.0-flash
export FABLE_ADJUDICATOR_MODE=advisory       # advisory (default) | enforcing
export FABLE_ADJUDICATOR_TIMEOUT_SECONDS=15
```

- `gemini` style calls `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
  A free AI Studio key works.
- `openai` style calls an OpenAI-compatible chat-completions endpoint
  (`https://api.openai.com/v1/chat/completions` unless
  `FABLE_ADJUDICATOR_ENDPOINT` overrides it).

Start with `advisory`. Read the receipts. Move to `enforcing` only when the
verdicts are consistently sensible for your workloads.

## Failure behavior

Fail-closed. Timeouts, HTTP errors, unreachable endpoints, empty replies, and
malformed model output all resolve to `uncertain`. In enforcing mode,
`uncertain` blocks the unlock just like `fail`. If the API key is missing, no
network call is attempted; the deterministic lint still runs and its verdict
stands on its own.

## Injection resistance

Evidence is data, not instructions. The bundle is wrapped in explicit
untrusted-data markers (and any copy of those markers inside the evidence
itself is scrubbed), the model is told to judge rather than obey, the reply
must be a strict JSON object, and verdicts outside the known set are rejected.
The bundle itself is size-capped per field and in total.

## Measuring detection quality

`benchmarks/adversarial_evidence_benchmark.py` scores the verifier against a
labeled corpus of fabricated and legitimate evidence snapshots
(`benchmarks/fixtures/adversarial_cases.json`). Baseline on the seed corpus
(16 cases): 100% catch rate on fabricated evidence, 0% false flags on
legitimate evidence - run it yourself:

```bash
python benchmarks/adversarial_evidence_benchmark.py
```

A seed corpus this small proves only that the rules fire. The corpus, not the
score, is the asset: every new fooling pattern found in the wild must land as
a fixture, and detection claims are only as strong as the corpus is
adversarial. `--llm` scores the full two-layer pipeline (one API call per
case, needs a key).

## Honest limits

- No verifier can guarantee that no AI will ever fool it. This adjudicator
  raises the cost of fabricated evidence; it does not make deception
  impossible.
- The reviewer model can be wrong in both directions: it can pass weak
  evidence and fail good evidence.
- A submission crafted to mislead this specific reviewer can sometimes
  succeed. Rotate models if you depend on this gate.
- The deterministic lint only knows the patterns it was taught; novel
  fabrication styles slip past it until the benchmark corpus teaches them.
- The mechanical gates (immutable time-lock, deterministic proof receipts,
  anti-idle refinement cycles) remain the primary authority. The adjudicator
  is one more gate that must agree, never a replacement for the others.
