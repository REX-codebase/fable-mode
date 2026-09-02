import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from fable_v2.protocol import (
    FileChangeRecord,
    ModelVelocityProfile,
    ProofReceipt,
    ToolReceipt,
    VisualMockupSpec,
)
from fable_v2.proof_engine import (
    DeterministicProofValidator,
    ProofStatus,
    ProofType,
    ProofValidationResult,
)
from fable_v2.system3.kripke import KripkeStructure
from fable_v2.system3.oracle import Prop, ProofOracle


class TestDeterministicProofValidator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.validator = DeterministicProofValidator(workspace_root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ast_valid_python_file(self):
        py_file = self.root / 'sample_module.py'
        code = "def calculate_metric(x: int, y: int) -> int:\n    return x + y\n\nclass MetricEngine:\n    pass\n"
        py_file.write_text(code, encoding='utf-8')
        res = self.validator.validate_ast(
            code_or_path=str(py_file),
            required_symbols=['calculate_metric', 'MetricEngine'],
            claim='Verify sample_module exports required symbols',
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.confidence, 1.0)
        self.assertEqual(res.proof_type, ProofType.AST_GROUNDED.value)

    def test_ast_missing_symbol_rejected(self):
        code = "def foo(): pass\n"
        res = self.validator.validate_ast(
            code_or_path=code,
            required_symbols=['foo', 'bar'],
            claim='Missing symbol check',
        )
        self.assertFalse(res.passed)

    def test_file_sha256_valid(self):
        content = b'Deterministic payload 123456789'
        expected_sha = hashlib.sha256(content).hexdigest()
        file_path = self.root / 'data.bin'
        file_path.write_bytes(content)

        res = self.validator.validate_file_sha256(
            file_path=str(file_path),
            expected_sha256=expected_sha,
            claim='Validate binary data integrity',
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.proof_type, ProofType.FILE_SHA256.value)

    def test_tool_receipt_validation(self):
        rcpt = ToolReceipt.from_result(
            receipt_id='rcpt-001',
            session_id='sess-001',
            capability='unit_test',
            tool_name='pytest',
            tool_input={'args': ['-k', 'test_core']},
            tool_output={'passed': True, 'duration': 0.05},
            success=True,
        )
        session_receipts = {'rcpt-001': rcpt}

        res = self.validator.validate_tool_receipt(
            receipt=rcpt,
            session_receipts=session_receipts,
            claim='Unit test execution receipt',
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.proof_type, ProofType.EMPIRICAL_RECEIPT.value)

    def test_anti_tautology_rejects_generic_strings(self):
        bad_claims = [
            'tested',
            'verified',
            'works',
            'it works',
            'done',
            'fixed',
            'looks good',
            'success',
            'true',
            'x == x',
            '1 == 1',
        ]
        for bad in bad_claims:
            self.assertTrue(self.validator.is_tautological(bad))

    def test_formal_logic_curry_howard(self):
        from fable_v2.system3.oracle import Implies
        A = Prop('A')
        B = Prop('B')
        prop = Implies(A, Implies(B, A))
        res = self.validator.validate_formal_logic(
            proposition_or_formula=prop,
            claim='Constructive tautology A -> B -> A',
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.proof_type, ProofType.FORMAL_LOGIC.value)

    def test_temporal_invariant_kripke_ctl(self):
        ks = KripkeStructure(name='StateMachine')
        ks.add_world('w_init', {'initialized', 'safe'}, is_initial=True)
        ks.add_world('w_work', {'safe', 'active'})
        ks.add_transition('w_init', 'w_work')
        ks.add_transition('w_work', 'w_work')

        res = self.validator.validate_temporal_invariant(
            formula='AG(safe)',
            kripke_structure=ks,
            initial_world='w_init',
            claim='Safety invariant holds',
        )
        self.assertTrue(res.passed)

    def test_vector_coordinates_validation(self):
        valid_bbox = {'x': 100, 'y': 200, 'width': 800, 'height': 600}
        res = self.validator.validate_vector_coordinates(
            coordinates_data=valid_bbox,
            claim='Layout bounding box spec',
        )
        self.assertTrue(res.passed)

    def test_polyglot_ast_typescript_and_rust(self):
        ts_code = "export interface UserProfile {\n  id: string;\n}\n\nexport function fetchUserProfile(id: string): UserProfile {\n  return { id };\n}\n"
        res_ts = self.validator.validate_ast(
            code_or_path=ts_code,
            required_symbols=['UserProfile', 'fetchUserProfile'],
            claim='Verify TypeScript interface and function export',
        )
        self.assertTrue(res_ts.passed)
        self.assertEqual(res_ts.metadata.get('language'), 'typescript')

        rs_code = "pub struct CausalGraph {\n  nodes: usize,\n}\n\npub fn create_graph() -> CausalGraph {\n  CausalGraph { nodes: 0 }\n}\n"
        res_rs = self.validator.validate_ast(
            code_or_path=rs_code,
            required_symbols=['CausalGraph', 'create_graph'],
            claim='Verify Rust struct and function',
        )
        self.assertTrue(res_rs.passed)
        self.assertEqual(res_rs.metadata.get('language'), 'rust')

    def test_unregistered_tool_receipt_rejected(self):
        res = self.validator.validate_tool_receipt(
            receipt="stdout: Fake execution output without registration",
            session_receipts={},
            claim="Fake claim with stdout substring",
        )
        self.assertFalse(res.passed)
        self.assertIn("not found in active session receipts", res.details)

    def test_kripke_safety_fails_on_tainted_context(self):
        clean_res = self.validator.validate_temporal_invariant(
            formula="AG(safe)",
            context={"safe": True, "has_failures": False},
        )
        self.assertTrue(clean_res.passed)

        tainted_res = self.validator.validate_temporal_invariant(
            formula="AG(safe)",
            context={"safe": False, "has_failures": True},
        )
        self.assertFalse(tainted_res.passed)

    def test_svg_viewbox_coordinate_validation(self):
        valid_svg = '<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg"><rect x="10" y="20" width="100" height="50" /></svg>'
        res = self.validator.validate_vector_coordinates(
            coordinates_data=valid_svg,
            claim="Valid SVG viewport check",
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.metadata["viewBox"], [0.0, 0.0, 800.0, 600.0])

        invalid_svg = '<svg viewBox="0 0 -100 600"></svg>'
        res_inv = self.validator.validate_vector_coordinates(
            coordinates_data=invalid_svg,
            claim="Invalid SVG viewport check",
        )
        self.assertFalse(res_inv.passed)


class TestProtocolDataclasses(unittest.TestCase):
    def test_proof_receipt_to_dict(self):
        rcpt = ProofReceipt(
            receipt_id='rcpt-123',
            claim='Cryptographic SHA256 match',
            proof_type='file_sha256',
            target_resource='/app/core.py',
            sha256_digest='abc' * 20 + 'abcd',
            verified_at='2026-09-02T12:00:00Z',
            verifier_details={'size_bytes': 1024},
        )
        d = rcpt.to_dict()
        self.assertEqual(d['receipt_id'], 'rcpt-123')

    def test_file_change_record_to_dict(self):
        change = FileChangeRecord(
            file_path='fable_v2/proof_engine.py',
            change_type='create',
            before_hash=None,
            after_hash='def' * 21 + 'd',
            diff_summary='+500 lines DeterministicProofValidator',
            rationale='Implement deterministic proof engine',
            affected_invariants=('AG(safe)', 'AST_grounding'),
            timestamp='2026-09-02T12:00:00Z',
        )
        d = change.to_dict()
        self.assertEqual(d['file_path'], 'fable_v2/proof_engine.py')

    def test_visual_mockup_spec_to_dict(self):
        mockup = VisualMockupSpec(
            mockup_id='mockup-001',
            concept_name='Cinematic Glass',
            aesthetic_archetype='glassmorphism',
            prompt='High contrast dark mode',
            image_url=None,
            coordinates_data={'card_w': 320},
            palette=('#0f172a', '#38bdf8'),
            typography={'heading': 'Inter Display'},
            status='approved',
            selected_by_user=True,
            created_at='2026-09-02T12:00:00Z',
        )
        d = mockup.to_dict()
        self.assertEqual(d['mockup_id'], 'mockup-001')

    def test_model_velocity_profile_to_dict(self):
        profile = ModelVelocityProfile(
            model_tier='pro',
            tokens_per_sec=42.5,
            avg_tool_latency_sec=1.1,
            sample_count=10,
            high_throughput_mode=False,
            exploration_multiplier=1.0,
            last_updated='2026-09-02T12:00:00Z',
        )
        d = profile.to_dict()
        self.assertEqual(d['model_tier'], 'pro')


if __name__ == '__main__':
    unittest.main()
