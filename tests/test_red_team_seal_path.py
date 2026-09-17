"""Regression tests for the 1.3.6 red-team seal path fixes.

Defect 1: the advance_phase response formatter crashed with KeyError
'description' whenever a cognitive-bias finding was active, because
CognitiveBiasFinding.to_dict() emits evidence_trail/mitigation_strategy.

Defect 2: Phases 5-6 were unreachable for MCP clients. The red-team swarm
only accepted in-process callables (source strings were refused: no sandbox
executor), and a clean (0-breakage) report could not be recorded from
IMPLEMENTATION, so no public action could walk a session to SEALED.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("FABLE_DISABLE_AUTO_UPDATE", "1")


def _make_session_env(case=None):
    tmp = Path(tempfile.mkdtemp(prefix="fable-seal-test-"))
    os.environ["FABLE_DATA_DIR"] = str(tmp / "data")
    if case is not None:
        # Keep swarm plasticity consolidation and other cwd-relative writes
        # out of the repository tree.
        previous = os.getcwd()
        os.chdir(tmp)
        case.addCleanup(os.chdir, previous)
    return tmp


class SandboxExecutorTests(unittest.TestCase):
    def setUp(self):
        _make_session_env(self)

    def test_probe_resilient_target_survives_swarm(self):
        from fable_v2.coder_fleet.red_team_swarm import RedTeamSwarm
        from fable_v2.coder_fleet.sandbox_executor import load_sandboxed_target

        source = (
            "def summarize(text=None):\n"
            "    if text is None:\n"
            "        return ''\n"
            "    return str(text)[:200]\n"
        )
        target = load_sandboxed_target(source)
        try:
            report = RedTeamSwarm().run_full_review_cycle(
                target_callable=target, target_name="summarize"
            )
        finally:
            target.close()
        broken = [(f.scenario_id, f.error_message) for f in report.findings if f.broken]
        self.assertEqual(report.broken_count, 0, f"unexpected breakages: {broken}")
        self.assertGreaterEqual(report.total_probes, 5)

    def test_target_exception_maps_back(self):
        from fable_v2.coder_fleet.sandbox_executor import load_sandboxed_target

        target = load_sandboxed_target(
            "def boom(x):\n    raise ValueError('nope')\n"
        )
        try:
            with self.assertRaises(ValueError):
                target("probe")
        finally:
            target.close()

    def test_hung_target_times_out_and_worker_recovers(self):
        from fable_v2.coder_fleet.sandbox_executor import load_sandboxed_target

        target = load_sandboxed_target(
            "def hang(x):\n"
            "    if x == 'hang':\n"
            "        while True:\n"
            "            pass\n"
            "    return 'ok'\n",
            call_timeout=1.0,
        )
        try:
            with self.assertRaises(TimeoutError):
                target("hang")
            self.assertEqual(target("live"), "ok")
        finally:
            target.close()

    def test_ambiguous_entrypoint_is_an_honest_error(self):
        from fable_v2.coder_fleet.sandbox_executor import load_sandboxed_target, SandboxError

        with self.assertRaises(SandboxError):
            load_sandboxed_target("def a(x):\n    return x\n\ndef b(x):\n    return x\n")


class BiasFormatterRegressionTests(unittest.TestCase):
    def setUp(self):
        _make_session_env(self)

    def test_advance_phase_formats_active_bias_without_crash(self):
        from fable_engine.session import FableSession
        from fable_engine.actions.lifecycle import _handle_advance_phase
        session = FableSession(
            objective="formatter regression",
            session_name="bias-fmt-test",
            time_budget_minutes=2.0,
        )
        # The production trigger: an invariant whose proof restates its
        # statement makes the advance audit raise a CIRCULAR_REASONING
        # finding; the formatter must render it without KeyError.
        session.invariants.append({
            "id": "inv_001", "name": "INV-TAUT", "domain": "architecture",
            "formal_statement": "the gate holds",
            "proof_or_rationale": "the gate holds",
        })
        session.save()

        reply = _handle_advance_phase({
            "action": "advance_phase",
            "session_name": "bias-fmt-test",
            "next_phase": "Phase 2: Invariant Specification & Blueprint",
            "phase_summary": "formatter check",
        })
        self.assertNotIn("Error:", reply.splitlines()[0] if reply else "Error:")
        self.assertIn("Phase Advanced Successfully", reply)
        self.assertIn("simply restates the formal statement", reply)
        self.assertIn("MetaProofInducer", reply)


class FullSealWalkTests(unittest.TestCase):
    """Drive the public action surface to SEALED, then Phases 5 and 6.

    End-to-end regression for the 1.3.5 defect where no MCP action could
    complete the red-team gate. The engine's hard time-lock (2-minute
    authority budget) applies, so this test waits it out like a real host.
    """

    def setUp(self):
        self.tmp = _make_session_env(self)

    def _fable(self, args):
        from fable_engine.actions import handle_fable_session
        reply = handle_fable_session(args)
        first = (reply or "").splitlines()[0] if reply else ""
        self.assertFalse(
            first.startswith("Error:") or "🛑" in first,
            f"action {args.get('action')} refused: {reply[:400]}",
        )
        return reply

    def test_public_walk_reaches_sealed_and_phase_6(self):
        name = f"seal-walk-{int(time.time())}"
        work = self.tmp / "work"
        work.mkdir(exist_ok=True)
        target_py = work / "summarize.py"
        target_src = (
            "def summarize(text=None):\n"
            "    if text is None:\n"
            "        return ''\n"
            "    return str(text)[:200]\n"
        )
        target_py.write_text(target_src)
        evidence_a = work / "evidence-a.txt"
        evidence_a.write_text("harness-observed fact A\n")
        evidence_b = work / "evidence-b.txt"
        evidence_b.write_text("harness-observed fact B\n")

        self._fable({
            "action": "create_session", "session_name": name,
            "objective": "regression: reach SEALED via public actions",
            "time_budget_minutes": 2.0,
        })
        self._fable({
            "action": "log_epistemic_item", "session_name": name,
            "tag": "HYPOTHESIS", "claim": "plan under test",
            "evidence": "regression harness",
        })
        self._fable({
            "action": "log_epistemic_item", "session_name": name,
            "tag": "PROVEN", "claim": "evidence file A exists",
            "evidence": str(evidence_a),
        })
        self._fable({
            "action": "log_epistemic_item", "session_name": name,
            "tag": "PROVEN", "claim": "evidence file B exists",
            "evidence": str(evidence_b),
        })
        self._fable({
            "action": "advance_phase", "session_name": name,
            "next_phase": "Phase 2: Invariant Specification & Blueprint",
            "phase_summary": "grounding done",
        })
        self._fable({
            "action": "record_invariant", "session_name": name,
            "invariant_name": "INV-01", "formal_statement": "session seals only on evidence",
            "proof_or_rationale": "independent rationale: every gate checked by engine code",
        })
        self._fable({
            "action": "advance_phase", "session_name": name,
            "next_phase": "Phase 3: Adversarial Red-Teaming & Falsification",
            "phase_summary": "invariant recorded",
        })
        for i in (1, 2):
            self._fable({
                "action": "log_refinement_cycle", "session_name": name,
                "refinement_type": "adversarial_falsification",
                "focus_area": f"cycle {i}",
                "critique_or_bottleneck": f"adversarial pass {i}",
                "architectural_refinement": f"refinement {i}",
                "terminal_probe_results": "probes pass",
            })

        # Hard time-lock: the 2-minute authority budget must elapse.
        from fable_engine.actions import handle_fable_session
        deadline = time.time() + 180
        while True:
            reply = handle_fable_session({
                "action": "unlock_execution", "session_name": name,
                "rationale": "all cognitive gates recorded",
            })
            if "TIME-LOCK" not in reply and "has not elapsed" not in reply:
                break
            self.assertLess(time.time(), deadline, "time-lock never released")
            time.sleep(10)
        self.assertIn("UNLOCKED", reply)

        self._fable({
            "action": "advance_phase", "session_name": name,
            "next_phase": "Phase 4: Subagent Fleet Delegation",
            "phase_summary": "execution",
        })
        self._fable({
            "action": "set_goal_rubric", "session_name": name,
            "task_objective": "seal the session",
            "criteria": [{"pointer_id": "files", "description": "target written"}],
            "target_score": 0.9,
        })
        self._fable({
            "action": "track_file_change", "session_name": name,
            "file_path": str(target_py), "change_type": "created",
            "diff_summary": "created summarize.py",
        })
        sha = hashlib.sha256(target_py.read_bytes()).hexdigest()
        proof = self._fable({
            "action": "verify_proof", "session_name": name,
            "claim": "summarize.py content verified",
            "proof_type": "file_sha256", "evidence": sha,
            "target_resource": str(target_py),
        })
        self.assertIn("receipt", proof.lower())

        from fable_engine.session import get_or_load_session
        session = get_or_load_session(name)
        receipt_id = session.proof_receipts[-1]["receipt_id"]
        self._fable({
            "action": "evaluate_goal_rubric", "session_name": name,
            "item_evaluations": [{
                "pointer_id": "files", "satisfied": True, "score": 1.0,
                "evidence_receipt_id": receipt_id,
            }],
        })

        review = self._fable({
            "action": "red_team_code_review", "session_name": name,
            "target_name": "summarize", "target_code": target_src,
            "entrypoint": "summarize",
        })
        self.assertTrue(
            "RESILIENT" in review or "TASK COMPLETED" in review,
            f"unexpected review reply: {review[:300]}",
        )

        session = get_or_load_session(name)
        self.assertEqual(session.current_state.value, "SEALED")

        self._fable({
            "action": "advance_phase", "session_name": name,
            "next_phase": "Phase 5: Multi-Tier Verification & Gatekeeping",
            "phase_summary": "red team sealed",
        })
        self._fable({
            "action": "advance_phase", "session_name": name,
            "next_phase": "Phase 6: Final Walkthrough & Reporting",
            "phase_summary": "closing",
        })
        session = get_or_load_session(name)
        self.assertTrue(session.active_phase.startswith("Phase 6"))


if __name__ == "__main__":
    unittest.main()
