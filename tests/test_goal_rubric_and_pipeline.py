import unittest
import json
import time
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
for p in [str(BASE_DIR), str(BASE_DIR / "fable_engine"), str(Path(__file__).resolve().parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from server import (
    handle_fable_session,
    ACTIVE_SESSIONS,
    SESSIONS_DIR,
    FableSession,
    get_or_load_session,
)


class TestGoalRubricAndPipeline(unittest.TestCase):
    def setUp(self):
        self.session_name = f"test_rubric_pipe_{int(time.time() * 1000)}"

    def tearDown(self):
        if self.session_name in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[self.session_name]
        session_file = SESSIONS_DIR / f"{self.session_name}.json"
        if session_file.exists():
            try:
                session_file.unlink()
            except Exception:
                pass

    def _create_test_session(self, time_budget=10.0, objective="Test Rubrics and Pipelines"):
        return handle_fable_session({
            "action": "create_session",
            "session_name": self.session_name,
            "objective": objective,
            "time_budget_minutes": time_budget
        })

    def test_set_goal_rubric_defaults_and_custom_weights(self):
        self._create_test_session()

        # 1. Register rubric with default target_score and auto-generated rubric_id
        criteria = [
            {
                "pointer_id": "PTR-TEST-01",
                "description": "Unit tests pass with 100% coverage",
                "weight": 3.0,
                "verifier_command": "pytest tests/test_core.py"
            },
            {
                "pointer_id": "PTR-TEST-02",
                "description": "Clean linter with zero errors",
                "weight": 1.0,
                "verifier_command": "ruff check ."
            },
            "PTR-TEST-03: Memory consumption below 50MB"
        ]

        res = handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "task_objective": "Deliver high-reliability component",
            "criteria": criteria
        })

        self.assertIn("Goal Rubric Initialized", res)
        self.assertIn("95.0%", res)
        self.assertIn("PENDING", res)
        self.assertIn("PTR-TEST-01", res)
        self.assertIn("PTR-TEST-02", res)
        self.assertIn("PTR-TEST-03", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.goal_rubrics), 1)
        rubric = session.goal_rubrics[0]
        self.assertTrue(rubric["rubric_id"].startswith(f"rubric_{self.session_name}_"))
        self.assertEqual(rubric["target_score"], 0.95)
        self.assertEqual(rubric["status"], "pending")
        self.assertEqual(len(rubric["items"]), 3)
        self.assertEqual(rubric["items"][0]["weight"], 3.0)
        self.assertEqual(rubric["items"][1]["weight"], 1.0)
        self.assertEqual(rubric["items"][2]["weight"], 1.0)

        # 2. Register custom rubric with explicit rubric_id and custom target_score
        custom_res = handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "custom_rubric_v2",
            "target_score": 0.98,
            "criteria": [
                {"pointer_id": "P1", "description": "Spec 1", "weight": 2.0}
            ]
        })
        self.assertIn("custom_rubric_v2", custom_res)
        self.assertIn("98.0%", custom_res)
        self.assertEqual(len(session.goal_rubrics), 2)
        self.assertEqual(session.goal_rubrics[1]["rubric_id"], "custom_rubric_v2")
        self.assertEqual(session.goal_rubrics[1]["target_score"], 0.98)

    def test_evaluate_goal_rubric_transitions_status(self):
        self._create_test_session()

        # Rubric with 2 items: weights 1.0 and 3.0 (total weight 4.0), target 0.95
        handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "eval_rubric_test",
            "target_score": 0.95,
            "criteria": [
                {"pointer_id": "PTR-CORE", "description": "Core algorithm", "weight": 1.0},
                {"pointer_id": "PTR-SAFETY", "description": "Safety proofs", "weight": 3.0}
            ]
        })

        session = ACTIVE_SESSIONS[self.session_name]

        # Step 1: Evaluate only PTR-CORE (score: (1.0*1.0 + 3.0*0.0)/4.0 = 0.25 -> 25%)
        res1 = handle_fable_session({
            "action": "evaluate_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "eval_rubric_test",
            "evaluations": [
                {"pointer_id": "PTR-CORE", "satisfied": True, "score": 1.0, "evidence_receipt_id": "rcpt_core_1"}
            ]
        })

        self.assertIn("Goal Rubric Evaluation", res1)
        self.assertIn("25.00%", res1)
        self.assertIn("IN_PROGRESS (< 95%)", res1)
        rubric = session.get_goal_rubric("eval_rubric_test")
        self.assertEqual(rubric["current_score"], 0.25)
        self.assertEqual(rubric["status"], "in_progress")

        # Step 2: Evaluate PTR-SAFETY as satisfied (score: (1.0*1.0 + 3.0*1.0)/4.0 = 1.0 -> 100%)
        res2 = handle_fable_session({
            "action": "evaluate_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "eval_rubric_test",
            "evaluations": [
                {"pointer_id": "PTR-SAFETY", "satisfied": True, "score": 1.0, "evidence_receipt_id": "rcpt_safety_1"}
            ]
        })

        self.assertIn("100.00%", res2)
        self.assertIn("ACHIEVED (>= 95%)", res2)
        rubric = session.get_goal_rubric("eval_rubric_test")
        self.assertEqual(rubric["current_score"], 1.0)
        self.assertEqual(rubric["status"], "achieved")

        # Step 3: Partial score evaluation that meets target exactly:
        # e.g., reset and set target to 0.90, weights 1.0 and 1.0, scores 0.90 and 0.90 -> 0.90 >= 0.90 -> achieved
        handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "partial_rubric",
            "target_score": 0.90,
            "criteria": [
                {"pointer_id": "A", "weight": 1.0},
                {"pointer_id": "B", "weight": 1.0}
            ]
        })
        handle_fable_session({
            "action": "evaluate_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "partial_rubric",
            "evaluations": [
                {"pointer_id": "A", "score": 0.90, "satisfied": True},
                {"pointer_id": "B", "score": 0.90, "satisfied": True}
            ]
        })
        r_partial = session.get_goal_rubric("partial_rubric")
        self.assertEqual(r_partial["current_score"], 0.90)
        self.assertEqual(r_partial["status"], "achieved")

    def test_get_goal_rubric(self):
        self._create_test_session()

        # 1. Query before any rubric is registered
        empty_res = handle_fable_session({
            "action": "get_goal_rubric",
            "session_name": self.session_name
        })
        self.assertIn("No Goal Rubric Found", empty_res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertIsNone(session.get_goal_rubric())

        # 2. Register multiple rubrics
        handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "rubric_alpha",
            "criteria": ["Alpha Criterion 1"]
        })
        handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "rubric_beta",
            "criteria": ["Beta Criterion 1"]
        })

        # 3. Query without rubric_id returns latest rubric (rubric_beta)
        latest_res = handle_fable_session({
            "action": "get_goal_rubric",
            "session_name": self.session_name
        })
        self.assertIn("rubric_beta", latest_res)
        self.assertEqual(session.get_goal_rubric()["rubric_id"], "rubric_beta")

        # 4. Query specific rubric by ID
        alpha_res = handle_fable_session({
            "action": "get_goal_rubric",
            "session_name": self.session_name,
            "rubric_id": "rubric_alpha"
        })
        self.assertIn("rubric_alpha", alpha_res)
        self.assertEqual(session.get_goal_rubric("rubric_alpha")["rubric_id"], "rubric_alpha")

        # 5. Query non-existent rubric id returns None / empty
        self.assertIsNone(session.get_goal_rubric("non_existent_id"))

    def test_register_automation_pipeline(self):
        self._create_test_session()

        # 1. Register closed-loop pipeline spec with generator_cmd, evaluator_cmd, max_iterations
        res = handle_fable_session({
            "action": "register_automation_pipeline",
            "session_name": self.session_name,
            "pipeline_name": "svg_vector_perceptual_loop",
            "pipeline_type": "closed_loop",
            "generator_cmd": "python scratch/synthesize_svg.py",
            "evaluator_cmd": "python scratch/compare_ssim.py",
            "max_iterations": 8,
            "target_threshold": 0.96
        })

        self.assertIn("Autonomous Pipeline Registered", res)
        self.assertIn("svg_vector_perceptual_loop", res)
        self.assertIn("python scratch/synthesize_svg.py", res)
        self.assertIn("python scratch/compare_ssim.py", res)
        self.assertIn("96.0%", res)
        self.assertIn("8", res)

        session = ACTIVE_SESSIONS[self.session_name]
        self.assertEqual(len(session.automation_pipelines), 1)
        pipe = session.automation_pipelines[0]
        self.assertEqual(pipe["name"], "svg_vector_perceptual_loop")
        self.assertEqual(pipe["pipeline_type"], "closed_loop")
        self.assertEqual(pipe["generator_command"], "python scratch/synthesize_svg.py")
        self.assertEqual(pipe["evaluator_command"], "python scratch/compare_ssim.py")
        self.assertEqual(pipe["max_iterations"], 8)
        self.assertEqual(pipe["target_threshold"], 0.96)
        self.assertEqual(pipe["status"], "active")

        # 2. Register pipeline using parameter aliases: name, generator_command, evaluator_command, target_score
        res2 = handle_fable_session({
            "action": "register_automation_pipeline",
            "session_name": self.session_name,
            "name": "fuzzing_pipeline",
            "pipeline_type": "fuzzing",
            "generator_command": "python scratch/gen_fuzz.py",
            "evaluator_command": "python scratch/eval_fuzz.py",
            "target_score": 0.99,
            "max_iterations": 15
        })
        self.assertIn("fuzzing_pipeline", res2)
        self.assertIn("99.0%", res2)
        self.assertEqual(len(session.automation_pipelines), 2)
        pipe2 = session.automation_pipelines[1]
        self.assertEqual(pipe2["name"], "fuzzing_pipeline")
        self.assertEqual(pipe2["pipeline_type"], "fuzzing")
        self.assertEqual(pipe2["generator_command"], "python scratch/gen_fuzz.py")
        self.assertEqual(pipe2["evaluator_command"], "python scratch/eval_fuzz.py")
        self.assertEqual(pipe2["target_threshold"], 0.99)
        self.assertEqual(pipe2["max_iterations"], 15)

    def test_error_handling_and_validation(self):
        self._create_test_session()
        session = ACTIVE_SESSIONS[self.session_name]

        # 1. Missing session_name in actions
        for act in ["set_goal_rubric", "evaluate_goal_rubric", "get_goal_rubric", "register_automation_pipeline"]:
            res = handle_fable_session({"action": act})
            self.assertIn("Error:", res)
            self.assertIn("'session_name' is required", res)

        # 2. Non-existent session
        res_nosess = handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": "ghost_session_xyz",
            "criteria": ["Criterion 1"]
        })
        self.assertIn("Error:", res_nosess)
        self.assertIn("does not exist", res_nosess)

        # 3. Missing or empty criteria in set_goal_rubric
        res_nocrit = handle_fable_session({
            "action": "set_goal_rubric",
            "session_name": self.session_name
        })
        self.assertIn("Error:", res_nocrit)
        self.assertIn("'criteria'", res_nocrit)

        # 4. Direct session method validations:
        # 4a. Invalid criteria type / empty list raises ValueError
        with self.assertRaises(ValueError):
            session.set_goal_rubric(task_objective="test", criteria=[])

        # 4b. Invalid target_score outside [0.0, 1.0] raises ValueError
        with self.assertRaises(ValueError):
            session.set_goal_rubric(task_objective="test", criteria=["Valid"], target_score=1.5)

        with self.assertRaises(ValueError):
            session.set_goal_rubric(task_objective="test", criteria=["Valid"], target_score=-0.1)

        # 4c. evaluate_goal_rubric before any rubric is registered raises ValueError
        fresh_sess = FableSession(session_name="fresh_test_sess", objective="testing", time_budget_minutes=10.0)
        with self.assertRaises(ValueError):
            fresh_sess.evaluate_goal_rubric()

        # 4d. evaluate_goal_rubric with non-existent rubric_id raises ValueError
        session.set_goal_rubric(task_objective="test", criteria=["Valid criterion"])
        with self.assertRaises(ValueError):
            session.evaluate_goal_rubric(rubric_id="non_existent_rubric_999")

        # 4e. register_automation_pipeline with empty name raises ValueError
        with self.assertRaises(ValueError):
            session.register_automation_pipeline(name="")

        # 4f. register_automation_pipeline via handle_fable_session without name returns error
        res_noname = handle_fable_session({
            "action": "register_automation_pipeline",
            "session_name": self.session_name
        })
        self.assertIn("Error:", res_noname)
        self.assertIn("'name' is required", res_noname)


if __name__ == "__main__":
    unittest.main()
