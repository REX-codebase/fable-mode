#!/usr/bin/env python3
"""Fable evidence-adjudicator benchmark.

Runs the deterministic evidence lint over the labeled adversarial corpus in
fixtures/adversarial_cases.json and reports:

- catch_rate:       fraction of fabricated sessions the lint flags
- false_flag_rate:  fraction of legitimate sessions wrongly flagged
- accuracy:         overall correct classifications

The corpus, not the score, is the asset: every fooling pattern found in the
wild must become a fixture here. With --llm and FABLE_ADJUDICATOR_API_KEY set,
the full two-layer adjudicator (lint + external reviewer) is scored instead,
which costs one API call per case.

Usage:
    python benchmarks/adversarial_evidence_benchmark.py [--llm] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fable_engine.adjudicator import (  # noqa: E402
    AdjudicatorConfig,
    adjudicate_session,
    analyze_evidence_quality,
)

DEFAULTS = {
    "objective": "",
    "active_phase": "Phase 3: Adversarial Red-Teaming & Falsification",
    "time_budget_minutes": 30.0,
    "epistemic_ledger": [],
    "invariants": [],
    "refinement_cycles": [],
    "proof_receipts": [],
    "breakage_reports": [],
}


def as_session(payload):
    fields = {**DEFAULTS, **payload}
    return SimpleNamespace(**fields)


def run(cases, use_llm: bool):
    results = []
    config = AdjudicatorConfig.from_env() if use_llm else None
    for case in cases:
        session = as_session(case["session"])
        if use_llm:
            receipt = adjudicate_session(session, config=config)
            flagged = receipt["verdict"] == "fail"
            detail = receipt["issues"][:3]
        else:
            lint = analyze_evidence_quality(session)
            flagged = lint["suspicious"]
            detail = lint["critical"][:3]
        expect_flag = case["label"] == "fabricated"
        results.append({
            "id": case["id"],
            "label": case["label"],
            "flagged": flagged,
            "correct": flagged == expect_flag,
            "detail": detail,
        })
    fabricated = [r for r in results if r["label"] == "fabricated"]
    legitimate = [r for r in results if r["label"] == "legitimate"]
    metrics = {
        "mode": "two_layer_llm" if use_llm else "deterministic_lint",
        "cases": len(results),
        "catch_rate": sum(r["flagged"] for r in fabricated) / max(1, len(fabricated)),
        "false_flag_rate": sum(r["flagged"] for r in legitimate) / max(1, len(legitimate)),
        "accuracy": sum(r["correct"] for r in results) / max(1, len(results)),
        "misses": [r["id"] for r in fabricated if not r["flagged"]],
        "false_flags": [r["id"] for r in legitimate if r["flagged"]],
    }
    return metrics, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="score the full two-layer adjudicator (needs API key)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output only")
    args = parser.parse_args()

    fixtures = Path(__file__).resolve().parent / "fixtures" / "adversarial_cases.json"
    corpus = json.loads(fixtures.read_text(encoding="utf-8"))
    metrics, results = run(corpus["cases"], use_llm=args.llm)

    if args.json:
        print(json.dumps({"metrics": metrics, "results": results}, indent=2))
        return 0

    print(f"Mode:           {metrics['mode']}")
    print(f"Cases:          {metrics['cases']}")
    print(f"Catch rate:     {metrics['catch_rate']:.0%} of fabricated sessions flagged")
    print(f"False flags:    {metrics['false_flag_rate']:.0%} of legitimate sessions flagged")
    print(f"Accuracy:       {metrics['accuracy']:.0%}")
    for r in results:
        mark = "ok " if r["correct"] else "BAD"
        print(f"  [{mark}] {r['id']:<28} label={r['label']:<10} flagged={r['flagged']}")
    if metrics["misses"] or metrics["false_flags"]:
        print("\nUnsolved cases (grow the algorithm here):")
        for bad in metrics["misses"] + metrics["false_flags"]:
            print(f"  - {bad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
