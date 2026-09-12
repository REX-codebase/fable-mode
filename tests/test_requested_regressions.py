import tempfile
import unittest
from pathlib import Path

from fable_engine.cas import DATA_DIR
from fable_engine.session import FableSession, RED_TEAM_ATTACK_VECTORS, SessionState
from fable_v2.cortical.plasticity_engine import (
    MAX_ACTIVE_NODES,
    CorticalLobe,
    HebbianPlasticityEngine,
    HeuristicAntibody,
)


class SessionRegressionTests(unittest.TestCase):
    @staticmethod
    def _clean_report(session: FableSession) -> dict:
        report = {
            "report_id": "clean-regression",
            "target_name": "session",
            "total_probes": len(RED_TEAM_ATTACK_VECTORS),
            "broken_count": 0,
            "passed": True,
            "findings": [
                {"scenario_id": vector, "vector": vector, "broken": False}
                for vector in RED_TEAM_ATTACK_VECTORS
            ],
            "report_origin": "red_team_swarm",
            "reviewed_change_id": session.derive_reviewed_change_id(),
        }
        report["attack_vector_results"] = session._attack_vector_results(report)
        report["red_team_receipt"] = session.issue_red_team_receipt(
            report, report["reviewed_change_id"]
        )
        return report

    @staticmethod
    def _add_current_sealing_evidence(session: FableSession) -> None:
        session.log_epistemic_item("PROVEN", "Current evidence one", "README.md:L1")
        session.log_epistemic_item("PROVEN", "Current evidence two", "README.md:L5")
        session.proof_receipts.append({"receipt_id": "current-sealing-receipt", "verified": True})
        session.set_goal_rubric(
            "Current rubric",
            [{
                "pointer_id": "P1",
                "satisfied": True,
                "score": 1.0,
                "verifier_command": "python -m unittest tests.test_requested_regressions",
                "evidence_receipt_id": "current-sealing-receipt",
            }],
        )
        session.log_refinement_cycle("security", "sealing", "restored provenance", "fresh evidence")

    def test_restored_file_changes_do_not_mask_a_new_trusted_change(self) -> None:
        original = FableSession("restored_file_changes", "provenance", 5.0)
        original.set_timer(5.0)
        original.execution_locked = False
        original.can_execute_code = True
        original.transition_to(SessionState.IMPLEMENTATION, "implementation complete")
        original.track_file_change("old.py", "modified", "historical change")
        original.transition_to(SessionState.RED_TEAM_GATE, "code written")

        restored = FableSession.from_dict(original.to_dict())
        self.assertTrue(restored.file_changes[0]["_restored_untrusted"])
        self._add_current_sealing_evidence(restored)
        current = restored.track_file_change("new.py", "modified", "current change")
        self.assertNotIn("_restored_untrusted", current)

        restored.record_breakage_report(self._clean_report(restored))
        self.assertEqual(restored.current_state, SessionState.SEALED)

    def test_receipt_key_is_process_local_and_not_deserialized(self) -> None:
        session = FableSession("receipt_key_local", "secret", 5.0)
        serialized = session.to_dict()
        self.assertNotIn("red_team_receipt_key", serialized)
        self.assertNotIn("_red_team_receipt_key", serialized)

        serialized["red_team_receipt_key"] = "00" * 32
        serialized["_red_team_receipt_key"] = "11" * 32
        restored = FableSession.from_dict(serialized)
        self.assertNotEqual(restored._red_team_receipt_key, bytes(32))
        self.assertNotEqual(restored._red_team_receipt_key, bytes.fromhex("11" * 32))

    def test_fifth_failure_escalates_and_records_breakages_in_ledger(self) -> None:
        session = FableSession("attempt_escalation", "bounds", 5.0)
        session.current_state = SessionState.RED_TEAM_GATE
        report = {
            "total_probes": 1,
            "broken_count": 1,
            "passed": False,
            "findings": [{
                "scenario_id": "unsafe-state",
                "vector": "state_invariant",
                "hypothesis": "State remains unsafe",
                "broken": True,
            }],
        }
        for attempt in range(5):
            session.record_breakage_report(dict(report, report_id=f"failed-{attempt}"))

        self.assertEqual(session.current_state, SessionState.ESCALATION_UNRESOLVED_BREAKAGES)
        self.assertEqual(session.remediation_attempt_count, 5)
        self.assertTrue(session.active_breakages[0]["human_arbitration_required"])
        ledger_id = session.active_breakages[0]["epistemic_ledger_item_id"]
        ledger_item = next(item for item in session.epistemic_ledger if item["id"] == ledger_id)
        self.assertIn(ledger_item["tag"], {"UNKNOWN", "HYPOTHESIS"})

    def test_elapsed_remediation_limit_escalates(self) -> None:
        now = [100.0]
        session = FableSession("elapsed_escalation", "bounds", 5.0, wall_clock=lambda: now[0])
        session.current_state = SessionState.RED_TEAM_GATE
        report = {
            "total_probes": 1,
            "broken_count": 1,
            "passed": False,
            "findings": [{"scenario_id": "unknown", "broken": True}],
        }
        session.record_breakage_report(dict(report, report_id="first"))
        now[0] += 900.0
        session.record_breakage_report(dict(report, report_id="elapsed"))
        self.assertEqual(session.current_state, SessionState.ESCALATION_UNRESOLVED_BREAKAGES)

    def test_clean_stage_rubric_requires_positive_target_and_satisfied_item(self) -> None:
        session = FableSession("rubric_acceptance", "clean-stage evidence", 5.0)
        session.epistemic_ledger = [
            {"tag": "PROVEN", "evidence": "one"},
            {"tag": "PROVEN", "evidence": "two"},
        ]
        session.refinement_cycles = [{}]
        session.file_changes = [{}]
        session.proof_receipts = [{"receipt_id": "valid", "verified": True}]
        valid_item = {"satisfied": True, "evidence_receipt_id": "valid"}

        session.goal_rubrics = [{
            "status": "achieved",
            "current_score": 0.0,
            "target_score": 0.0,
            "items": [valid_item],
        }]
        with self.assertRaisesRegex(ValueError, "lacks an achieved rubric"):
            session._validate_clean_stage_evidence()

        session.goal_rubrics = [{
            "status": "achieved",
            "current_score": 1.0,
            "target_score": 0.95,
            "items": [{"satisfied": False}],
        }]
        with self.assertRaisesRegex(ValueError, "lacks an achieved rubric"):
            session._validate_clean_stage_evidence()

        session.goal_rubrics[0]["items"] = [
            {"satisfied": False, "evidence_receipt_id": "missing"},
            valid_item,
        ]
        session._validate_clean_stage_evidence()

    def test_missing_broken_defaults_true_without_overriding_explicit_false(self) -> None:
        session = FableSession("missing_broken", "breakage defaults", 5.0)
        session.current_state = SessionState.RED_TEAM_GATE
        session.record_breakage_report({
            "report_id": "mixed-findings",
            "total_probes": 2,
            "broken_count": 1,
            "passed": False,
            "findings": [
                {"scenario_id": "missing-is-broken"},
                {"scenario_id": "explicitly-clean", "broken": False},
            ],
        })

        self.assertEqual(
            [item["scenario_id"] for item in session.active_breakages],
            ["missing-is-broken"],
        )


class CorticalRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cortex_dir = Path(self.temp_dir.name)
        self.engine = HebbianPlasticityEngine(cortex_dir=self.cortex_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sync_removes_stale_reciprocal_edges(self) -> None:
        self.engine.define_cortical_lobe(
            "sync_lobe", initial_synaptic_weights={"kept": 0.7, "stale": 0.8}
        )
        self.engine.define_cortical_lobe(
            "sync_lobe", initial_synaptic_weights={"kept": 0.9}
        )
        matrix = self.engine.get_synaptic_matrix()
        self.assertNotIn("stale", matrix["sync_lobe"])
        self.assertNotIn("sync_lobe", matrix["stale"])
        self.assertEqual(matrix["kept"]["sync_lobe"], 0.9)

    def test_pairwise_processing_is_deduplicated_and_bounded(self) -> None:
        nodes = [f"node-{index}" for index in range(MAX_ACTIVE_NODES + 50)]
        receipt = self.engine.consolidate_task(
            "bounded", co_activated_nodes=["", *nodes, *nodes], final_passed=True
        )
        self.assertEqual(len(receipt["activation_signals"]), MAX_ACTIVE_NODES)

    def test_synaptic_key_collisions_use_canonical_maximum_on_disk(self) -> None:
        lobe = self.engine.define_cortical_lobe(
            "canonical",
            initial_synaptic_weights={"<system>node": 0.4, "node": 0.8},
        )
        self.assertEqual(lobe.synaptic_weights, {"node": 0.8})
        restored = CorticalLobe.load_from_disk(self.cortex_dir / "canonical.md")
        self.assertEqual(restored.synaptic_weights, {"node": 0.8})
        self.assertEqual(self.engine.get_synaptic_matrix()["canonical"]["node"], 0.8)

    def test_source_task_id_survives_all_cortical_artifact_flows(self) -> None:
        antibody = HeuristicAntibody(
            antibody_id="ab-source",
            domain="concurrency",
            trigger_condition="race",
            lethal_anti_pattern="check then use",
            prescribed_defense="atomic operation",
            source_task_id="task-source-42",
        )
        restored_antibody = HeuristicAntibody.from_dict(antibody.to_dict())
        self.assertEqual(restored_antibody.source_task_id, "task-source-42")
        self.assertIn("Source Task ID", restored_antibody.to_markdown())

        lobe = CorticalLobe(name="source", antibodies=[restored_antibody])
        artifact = self.cortex_dir / "source.md"
        lobe.save_to_disk(artifact)
        restored_lobe = CorticalLobe.load_from_disk(artifact)
        self.assertEqual(restored_lobe.antibodies[0].source_task_id, "task-source-42")

        fallback = self.cortex_dir / "fallback.md"
        fallback.write_text(restored_antibody.to_markdown(), encoding="utf-8")
        fallback_lobe = CorticalLobe.load_from_disk(fallback)
        self.assertEqual(fallback_lobe.antibodies[0].source_task_id, "task-source-42")

        self.engine._lobes["source"] = restored_lobe
        recall = self.engine.recall_cortical_context("source")
        self.assertIn("Source Task ID", recall)
        self.assertIn("task-source-42", recall)

    def test_bundled_cortical_provenance_and_research_heuristic_are_preserved(self) -> None:
        cortex_dir = Path(__file__).resolve().parents[1] / "skills" / "fable-mode" / "cortex"
        expected_counts = {
            "concurrency": 3,
            "python": 3,
            "rust": 3,
            "research": 3,
            "security": 1,
        }
        for domain, count in expected_counts.items():
            lobe = CorticalLobe.load_from_disk(cortex_dir / f"{domain}.md")
            self.assertEqual(len(lobe.antibodies), count)
            self.assertTrue(all(antibody.source_task_id for antibody in lobe.antibodies))

        research = CorticalLobe.load_from_disk(cortex_dir / "research.md")
        self.assertTrue(
            any("Fable's zero-cost research scrapers" in item for item in research.specialized_heuristics)
        )

    def test_shared_default_engine_uses_data_directory(self) -> None:
        import fable_engine.session as session_module

        previous = session_module._GLOBAL_PLASTICITY_ENGINE
        session_module._GLOBAL_PLASTICITY_ENGINE = None
        try:
            engine = session_module.get_plasticity_engine()
            self.assertEqual(engine.cortex_dir, DATA_DIR / "cortex")
        finally:
            session_module._GLOBAL_PLASTICITY_ENGINE = previous


if __name__ == "__main__":
    unittest.main()
