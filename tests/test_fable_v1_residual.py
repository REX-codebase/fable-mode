"""Adversarial coverage for the V1 server boundary and gate contract."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_engine.server import (
    FableCASStore, FableSession, FableCASError, EvidenceReceiptError,
    _canonical_hash, main,
)


class V1ResidualAdversarialTests(unittest.TestCase):
    def _receipt(self, session: FableSession, receipt_id: str, output):
        return {
            "receipt_id": receipt_id, "session_id": session.session_id,
            "capability": "test", "tool_name": "test-runner",
            "input_hash": _canonical_hash({"id": receipt_id}),
            "output_hash": _canonical_hash(output), "success": True,
            "output": output,
        }

    def test_proven_items_cannot_reuse_receipt_or_output(self):
        session = FableSession("distinct_receipts", "test", 1)
        output = {"passed": True}
        receipt = self._receipt(session, "r1", output)
        session.register_host_receipt(receipt)
        evidence = {"receipt_id": "r1", "session_id": session.session_id,
                    "content": output, "content_hash": receipt["output_hash"],
                    "source_output_hash": receipt["output_hash"],
                    "claim": "first independent result"}
        session.log_epistemic_item("PROVEN", "first independent result", evidence)
        with self.assertRaises(EvidenceReceiptError):
            session.log_epistemic_item("PROVEN", "same result again", evidence)
        with self.assertRaises(EvidenceReceiptError):
            session.register_host_receipt(self._receipt(session, "r2", output))

    def test_placeholder_invariants_are_not_gate_inputs(self):
        session = FableSession("substantive_invariant", "test", 1)
        for statement, proof in (("statement", "rationale"), ("the system is correct", "because"),
                                 ("TODO", "TODO")):
            with self.assertRaises(ValueError):
                session.record_invariant("INV", statement, proof)

    def test_phase_progression_requires_typed_substantive_prerequisites(self):
        session = FableSession("phase_prereqs", "test", 1)
        with self.assertRaises(ValueError):
            session.advance_phase("Phase 2: Invariant Specification & Blueprint", "done")
        session.log_epistemic_item("HYPOTHESIS", "A measurable design assumption")
        session.advance_phase("Phase 2: Invariant Specification & Blueprint", "Grounding identified the design assumptions")
        with self.assertRaises(ValueError):
            session.advance_phase("Phase 3: Adversarial Red-Teaming & Falsification", "ready")

    def test_scoped_cas_isolated_and_quota_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            a = FableCASStore(Path(td), namespace="session-a", max_namespace_bytes=4,
                              max_namespace_objects=1)
            b = FableCASStore(Path(td), namespace="session-b", max_namespace_bytes=4,
                              max_namespace_objects=1)
            ref = a.put(b"1234")
            with self.assertRaises(Exception):
                b.get_bytes(ref)
            with self.assertRaises(FableCASError):
                a.put(b"5678")

    def test_deadline_is_rejected_as_unsupported_not_posthoc(self):
        wire = "".join(json.dumps(x) + "\n" for x in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "fable_session", "arguments": {"action": "list_sessions"},
                "deadline_seconds": 1}}, 
        ))
        out = io.StringIO()
        with patch("sys.stdin", io.StringIO(wire)), patch("sys.stdout", out):
            main()
        responses = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(responses[1]["error"]["code"], -32003)
        self.assertIn("Unsupported", responses[1]["error"]["message"])


if __name__ == "__main__":
    unittest.main()
