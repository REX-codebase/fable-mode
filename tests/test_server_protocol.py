import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fable_engine.server import FableCASStore, IntegrityError, MAX_RPC_LINE_BYTES, main


class ServerProtocolRegressionTests(unittest.TestCase):
    def test_cached_verified_cas_reads_detect_disk_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FableCASStore(Path(tmp))
            ref = store.put("trusted")
            path = store.get_file_path(ref)
            path.write_text("tampered", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                store.get_bytes(ref, verify=True)
            self.assertFalse(store.verify_integrity(ref))

    def test_verify_false_is_explicit_low_level_cache_opt_out(self):
        """Only the opt-out can return cached bytes after disk tampering."""
        with tempfile.TemporaryDirectory() as tmp:
            store = FableCASStore(Path(tmp))
            ref = store.put("trusted")
            store.get_file_path(ref).write_text("tampered", encoding="utf-8")
            self.assertEqual(store.get_bytes(ref, verify=False), b"trusted")
            with self.assertRaises(IntegrityError):
                store.get_text(ref, verify=True)

    def test_malformed_jsonrpc_requests_are_controlled_errors(self):
        requests = "not-json\n[]\n" + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": []}) + "\n"
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(requests)), patch("sys.stdout", output):
            main()
        responses = [json.loads(line) for line in output.getvalue().splitlines() if line]
        self.assertEqual([item["error"]["code"] for item in responses], [-32700, -32600, -32600])

    def test_rpc_line_limit_counts_untrimmed_frame(self):
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(" " * (MAX_RPC_LINE_BYTES + 1) + "\n")), patch("sys.stdout", output):
            main()
        response = json.loads(output.getvalue())
        self.assertEqual(response["error"]["code"], -32600)

    def test_interactive_initialize_does_not_wait_for_eof(self):
        """A short frame must be answered while stdin remains open."""
        root = Path(tempfile.mkdtemp(prefix="fable-interactive-"))
        proc = subprocess.Popen(
            [sys.executable, "-u", os.fspath(Path(__file__).resolve().parents[1] / "fable_engine" / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=os.fspath(root),
        )
        line = []
        reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()), daemon=True)
        try:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1,
                                         "method": "initialize", "params": {}}) + "\n")
            proc.stdin.flush()
            reader.start()
            reader.join(timeout=3)
            self.assertFalse(reader.is_alive(), "interactive response waited for EOF")
            self.assertTrue(line and line[0])
            self.assertEqual(json.loads(line[0])["id"], 1)
        finally:
            if proc.stdin:
                proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=2)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
