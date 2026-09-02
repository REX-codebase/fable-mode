# Benchmark methodology template

Use this template before comparing model-alone, V1-assisted, or V2-assisted
runs. A benchmark result is evidence for the stated task set and environment,
not a universal product guarantee.

## Study definition

- **Study ID and date:**
- **Repository revision / package version:**
- **Host and adapter revision:**
- **OS, architecture, Python, and model versions:**
- **Task domain and intended users:**
- **Primary question:**
- **Pre-registered hypotheses:**
- **Exclusions and safety limits:**

## Task set

- **Source:**
- **Number of tasks:**
- **Difficulty strata:**
- **Train/tuning tasks:**
- **Held-out evaluation tasks:**
- **Leakage controls:**
- **Definition of success for each task:**
- **Human review rubric, if used:**

Do not tune prompts, verifier thresholds, or task selection on the held-out
set. If tasks are generated, publish the generator, seed policy, and filtering
rules.

## Conditions

Run at least these conditions where applicable:

1. model/host without Fable;
2. V1 with the same model and host tools;
3. V2 with the same model, adapter, budget, and broker policy.

Randomize task and condition order when practical. Record retries, timeouts,
failed tool calls, verifier decisions, and any manual intervention. Report
both per-task outcomes and aggregate outcomes.

## Metrics to record

- success and failure counts with the success definition;
- confidence intervals or uncertainty estimates appropriate to the sample;
- cost or token use;
- wall-clock latency and active compute time separately;
- tool-call and verifier counts;
- repair attempts and failure categories;
- verifier false-positive and false-negative checks against an independent
  adjudication sample;
- resource use and crash/recovery behavior;
- unsupported or skipped tasks by reason.

Do not report an effectiveness percentage without its denominator, task set,
condition, uncertainty, and success definition. Do not convert a workflow
gate, a receipt count, or a synthetic score into an accuracy claim.

## Results record

- **Baseline result:**
- **Fable result:**
- **Absolute difference:**
- **Uncertainty / interval:**
- **Cost and latency difference:**
- **Verifier quality:**
- **Failure analysis:**
- **Per-host differences:**
- **Threats to validity:**
- **Raw logs and hashes:**
- **Reproduction command:**

## Interpretation checklist

- Is the baseline non-zero and meaningfully specified?
- Were all systems given equivalent task information and tool access?
- Were failed and abandoned tasks counted consistently?
- Could a verifier, prompt, or selection rule have leaked the answer?
- Does the result replicate on another host, model, or task slice?
- Which claims are demonstrated, which are hypotheses, and which remain
  unknown?
