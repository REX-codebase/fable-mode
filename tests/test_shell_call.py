"""Direct shell transport for agents without native MCP access."""
import io
import json
import sys
import unittest
from unittest import mock

from fable_mode.launcher import MAX_SHELL_REQUEST_BYTES, _shell_call


class ShellCallTests(unittest.TestCase):
    def _call(self, payload: bytes):
        stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            status = _shell_call()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_valid_json_lines_share_one_runtime_and_emit_one_result_each(self):
        requests = [{"action": "list_sessions"}, {"action": "list_sessions"}]
        payload = "".join(json.dumps(item) + "\n" for item in requests).encode()
        with mock.patch("fable_engine.server.handle_fable_session", side_effect=["first", "second"]) as handle:
            status, stdout, stderr = self._call(payload)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual([json.loads(line) for line in stdout.splitlines()],
                         [{"ok": True, "result": "first"}, {"ok": True, "result": "second"}])
        self.assertEqual([call.args[0] for call in handle.call_args_list], requests)

    def test_empty_invalid_and_non_object_requests_fail(self):
        for payload in (b"", b"not json", b"[]", b'{}', b'{"action": ""}'):
            with self.subTest(payload=payload):
                status, stdout, stderr = self._call(payload)
                self.assertEqual(status, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("call: "))

    def test_oversized_request_is_rejected_before_json_parse(self):
        status, stdout, stderr = self._call(b"{" + b"x" * MAX_SHELL_REQUEST_BYTES)
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("exceeds 1 MiB", stderr)
