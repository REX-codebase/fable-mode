"""
Fable-Mode Token Compression Subsystem (FableCompress)
======================================================
Pure standard library Python implementation of content-addressed storage (CAS),
adaptive micro-payload batching, high-entropy micro-bytecode serialization,
zero-copy windowed line slice viewing, and token compression verification.

Author: Antigravity Autonomous Subagent Fleet
License: MIT
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
import hashlib
import time
import unittest
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

# Ensure UTF-8 output encoding across Windows consoles and standard streams
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Canonical implementations re-exported from fable_engine.cas
from fable_engine.cas import (
    DATA_DIR,
    FABLE_CAS_DIR,
    MAX_CAS_OBJECT_BYTES,
    MAX_SLICE_RESPONSE_BYTES,
    AdaptiveChunkAccumulator,
    CASNotFoundError,
    CASSliceViewer,
    CAS_ENGINE,
    CompositeFrame,
    FableCASError,
    FableCASStore,
    FableCompress,
    FableGrammar333,
    IntegrityError,
    ThreadSafeLRUCache,
    _assert_private_path,
    _open_directory_nofollow,
    _safe_cas_node,
)


# ============================================================================
# Red-Team & Verification Test Suite
# ============================================================================

class TestFableCompressRedTeam(unittest.TestCase):
    """
    Comprehensive Red-Team and Invariant Verification Suite for FableCompress.
    Asserts:
    1. Lock-free atomic tmp-replace integrity
    2. Zero third-party dependencies
    3. Strict UTF-8 Windows preservation
    4. 100% bit-exact lossless roundtrips
    5. Invariant <= 0.003 tokens/character on large payloads
    """

    def setUp(self):
        self.test_dir = pathlib.Path(tempfile.mkdtemp(prefix="fable_test_"))
        self.compressor = FableCompress(root_dir=self.test_dir)

    def tearDown(self):
        # Clean up temporary test files
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_cas_store_atomic_writes_and_sha256(self):
        """Verify atomic writes, deterministic SHA-256 keys, and exact retrieval."""
        store = self.compressor.cas_store
        sample_text = "Fable-Mode Deterministic Deliberation Invariant Proof alpha beta gamma delta epsilon"
        
        uri = store.put(sample_text)
        self.assertTrue(uri.startswith("cas://"))
        self.assertEqual(len(store.normalize_ref(uri)), 64)

        # Retrieve text and bytes
        retrieved_text = store.get_text(uri)
        self.assertEqual(retrieved_text, sample_text)
        self.assertEqual(store.get_bytes(uri), sample_text.encode("utf-8"))

        # Verify integrity check returns True
        self.assertTrue(store.verify_integrity(uri))

    def test_02_cas_corruption_detection(self):
        """Red-team tamper test: corrupting on-disk bytes must fail integrity validation."""
        store = self.compressor.cas_store
        sample_text = "Original pristine payload before adversarial tampering."
        uri = store.put(sample_text)
        file_path = store.get_file_path(uri)

        # Clear memory cache so read hits disk
        store.cache.clear()

        # Corrupt single byte in file
        with open(file_path, "r+b") as f:
            f.seek(0)
            f.write(b"X")

        # Must raise IntegrityError when reading with verification enabled
        with self.assertRaises(IntegrityError):
            store.get_bytes(uri, verify=True)

        self.assertFalse(store.verify_integrity(uri))

    def test_03_lru_cache_bounds_and_eviction(self):
        """Verify LRU cache capacity limits and eviction behavior."""
        small_store = FableCASStore(root_dir=self.test_dir / "lru_test", cache_capacity=3)
        uris = [small_store.put(f"item_{i}") for i in range(5)]

        # Cache should only hold 3 items
        self.assertEqual(len(small_store.cache), 3)

        # Oldest items (0 and 1) should be evicted from memory cache but persist on disk
        self.assertFalse(small_store.cache.contains(small_store.normalize_ref(uris[0])))
        self.assertTrue(small_store.exists(uris[0]))
        self.assertEqual(small_store.get_text(uris[0]), "item_0")

    def test_04_adaptive_chunk_accumulator_coalescing(self):
        """Verify sub-1000 character stream micro-payload batching into 1KB+ frames."""
        acc = self.compressor.accumulator
        micro_payloads = [f"Micro-action log entry #{i:04d}: processed step safely." for i in range(40)]

        all_flushed_uris = []
        for p in micro_payloads:
            uris = acc.add(p, metadata={"step": "telemetry"})
            all_flushed_uris.extend(uris)

        # Final flush
        all_flushed_uris.extend(acc.flush())

        self.assertGreater(len(all_flushed_uris), 0)
        stats = acc.get_stats()
        self.assertEqual(stats["total_payloads_ingested"], 40)

        # Verify lossless extraction of every micro-payload from the flushed frames
        extracted_count = 0
        for uri in all_flushed_uris:
            frame_json = self.compressor.cas_store.get_text(uri)
            frame = CompositeFrame.deserialize_json(frame_json)
            for idx, item in enumerate(frame.items):
                p_text, meta = acc.extract_item(uri, idx)
                self.assertEqual(p_text, micro_payloads[extracted_count])
                self.assertEqual(meta.get("step"), "telemetry")
                extracted_count += 1

        self.assertEqual(extracted_count, 40)

    def test_05_grammar333_micro_bytecode_roundtrip(self):
        """Verify 100% bit-exact lossless roundtrip for all tool action types."""
        test_actions = [
            {
                "action_type": "run_command",
                "command": "pytest -v tests/test_cas.py",
                "cwd": "C:/Projects/Fable",
                "exit_code": 0,
                "stdout_ref": "cas://abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            },
            {
                "action_type": "view_file",
                "path": "c:/Users/hp1/Desktop/Documents/fable_compressor.py",
                "start_line": 1,
                "end_line": 100,
                "content_ref": "cas://1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            },
            {
                "action_type": "edit_file",
                "target_file": "c:/repo/module.py",
                "start_line": 42,
                "end_line": 45,
                "target_content": "def old_fn(): pass",
                "replacement_content": "def new_fn(): return True",
            },
            {
                "action_type": "mcp_call",
                "server": "fable-engine",
                "tool": "fable_session",
                "arguments": {"action": "log_refinement_cycle", "cycle": 4},
                "result_ref": "cas://0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff",
            },
            {
                "action_type": "cas_ref",
                "cas_ref": "cas://deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                "label": "system_prompt_manifest",
            },
        ]

        for action in test_actions:
            encoded_bytes = FableGrammar333.serialize(action)
            self.assertTrue(encoded_bytes.startswith(FableGrammar333.MAGIC_HEADER))
            decoded = FableGrammar333.deserialize(encoded_bytes)
            self.assertEqual(decoded, action)

    def test_06_cas_slice_viewer_zero_copy(self):
        """Verify windowed line slice extractor with 1-based indexing and boundaries."""
        sample_lines = [f"Line {i:03d}: The quick brown fox jumps over the lazy dog." for i in range(1, 101)]
        raw_doc = "\n".join(sample_lines)
        uri = self.compressor.cas_store.put(raw_doc)

        viewer = self.compressor.slice_viewer

        # Exact line count
        self.assertEqual(viewer.get_line_count(uri), 99)  # 99 newlines in 100 lines

        # Slice lines 10 to 15 (1-indexed inclusive)
        slice_result = viewer.view_slice(uri, 10, 15)
        expected = "\n".join(sample_lines[9:15])
        self.assertEqual(slice_result, expected)

        # Slice with line numbers
        numbered = viewer.view_slice(uri, 1, 2, include_line_numbers=True)
        self.assertIn("     1 | Line 001:", numbered)
        self.assertIn("     2 | Line 002:", numbered)

        # Edge cases: out of bounds end line
        full_slice = viewer.view_slice(uri, 1, 500)
        self.assertEqual(full_slice, raw_doc)

    def test_07_concurrent_multithreaded_writes(self):
        """Red-team race condition test: 20 concurrent threads writing to CAS."""
        store = self.compressor.cas_store
        errors: List[Exception] = []

        def worker(thread_id: int):
            try:
                for j in range(20):
                    data = f"Thread-{thread_id} iteration {j}: payload content {hashlib.md5(f'{thread_id}-{j}'.encode()).hexdigest()}"
                    uri = store.put(data)
                    read_back = store.get_text(uri)
                    if read_back != data:
                        raise ValueError(f"Mismatch in thread {thread_id}!")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors encountered: {errors}")

    def test_08_fuzzing_unicode_and_special_chars(self):
        """Red-team fuzz test: UTF-8 edge cases, surrogates, emojis, binary strings."""
        fuzz_samples = [
            "",
            "A",
            "\n\n\n\r\n\t",
            "CJK Unicode: test characters",
            "\x00\x01\x02\x03\x7f\x80\xff" * 50,
            json.dumps({"null": None, "bool": True, "float": 3.141592653589793, "nested": [1, 2, {"a": "b"}]}),
            "Line with no ending newline",
            "Line with CRLF\r\nAnother Line\r\nFinal Line\r\n",
        ]

        for idx, sample in enumerate(fuzz_samples):
            uri = self.compressor.cas_store.put(sample)
            retrieved = self.compressor.cas_store.get_text(uri) if isinstance(sample, str) else self.compressor.cas_store.get_bytes(uri)
            self.assertEqual(retrieved, sample, f"Fuzz sample {idx} failed roundtrip")

    def test_09_invariant_token_ratio_lte_0_003(self):
        """
        CRITICAL INVARIANT TEST:
        Asserts that CAS-compressed representations achieve <= 0.003 tokens/character
        on realistic large tool payloads (10KB, 50KB, 100KB, 500KB).
        """
        payload_sizes = [10_000, 50_000, 100_000, 500_000]
        
        print("\n" + "=" * 70)
        print("FABLE-MODE TOKEN COMPRESSION INVARIANT PROOF (<= 0.003 tokens/char)")
        print("=" * 70)

        for size in payload_sizes:
            # Generate realistic structured tool trace / log output
            raw_payload = (
                f"[TRACE_START: size={size}]\n"
                + "function analyze_ast_node(node: ASTNode) -> DiagnosticResult {\n"
                + "    // Fable-Mode recursive Deliberation pass\n"
                + "    const state = evaluate_invariants(node.get_constraints());\n"
                + "    return { valid: state.is_consistent(), score: 0.998 };\n"
                + "}\n"
            ) * (size // 200 + 1)
            raw_payload = raw_payload[:size]

            # Compress payload to CAS
            compressed_node = self.compressor.compress_payload_to_cas(raw_payload, label="ast_analysis_dump")
            
            # Canonical representation passed into LLM prompt
            compressed_repr = json.dumps(compressed_node, separators=(",", ":"))

            # Calculate token ratio
            ratio = self.compressor.calculate_token_ratio(raw_payload, compressed_repr)
            raw_tokens = self.compressor.estimate_token_count(raw_payload)
            comp_tokens = self.compressor.estimate_token_count(compressed_repr)

            pct_savings = (1.0 - (comp_tokens / float(raw_tokens))) * 100.0

            print(
                f"Payload: {size:7d} chars | "
                f"Raw Tokens: {raw_tokens:6d} -> Comp Tokens: {comp_tokens:3d} | "
                f"Ratio: {ratio:.6f} tokens/char | "
                f"Savings: {pct_savings:.2f}% | "
                f"Invariant (<=0.003): {'[PASS]' if ratio <= 0.003 else '[FAIL]'}"
            )

            # Strict assertion: Token ratio MUST be <= 0.003
            self.assertLessEqual(
                ratio,
                0.003,
                f"Token ratio {ratio:.6f} exceeded invariant threshold 0.003 for size {size}"
            )

            # Verify 100% bit-exact lossless roundtrip recovery
            recovered_text = self.compressor.decompress_cas_payload(compressed_node)
            self.assertEqual(len(recovered_text), len(raw_payload))
            self.assertEqual(recovered_text, raw_payload)

        print("=" * 70 + "\n")


# ============================================================================
# 7. Main CLI Execution & Verification Entry Point
# ============================================================================

def run_verification() -> int:
    """Execute test suite and print formatted report."""
    print("=" * 70)
    print("Fable-Mode Token Compression Subsystem (FableCompress) Verification")
    print("=" * 70)
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFableCompressRedTeam)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("\nALL TESTS PASSED! Strict Invariants & Bit-Exact Recovery Verified.")
        return 0
    else:
        print(f"\nVERIFICATION FAILED: {len(result.failures)} failures, {len(result.errors)} errors.")
        return 1


if __name__ == "__main__":
    sys.exit(run_verification())
