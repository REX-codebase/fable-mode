"""Property Oracle Engine for Boundary Matrix Generation and Algebraic Invariant Verification.

Generates extreme edge-case fuzzing matrices and verifies roundtrip invariants
(e.g., decode(encode(x)) == x) using isolated execution harnesses.
"""
from __future__ import annotations

import base64
import json
import math
import pickle
import sys
from typing import Any

from .test_harness import TestHarnessEngine


class PropertyOracleEngine:
    """Engine for generating boundary property testing matrices and verifying algebraic invariants."""

    def __init__(self, test_harness: TestHarnessEngine | None = None) -> None:
        self._harness = test_harness or TestHarnessEngine()

    def generate_property_matrix(self, types: list[str], count: int = 50) -> list[Any]:
        """Generate extreme boundary values (empty strings, MAX_INT, unicode, negative values,

        None, large lists, floats) for the specified types.
        """
        pools: list[list[Any]] = []
        normalized_types = {t.lower().strip() for t in types}

        if any(t in normalized_types for t in ("str", "string", "text")):
            pools.append([
                "",
                " ",
                "\t",
                "\n",
                "\r\n",
                "\x00",
                "null",
                "None",
                "undefined",
                "0",
                "-1",
                "🔥🚀✨🎉",
                "A" * 1024,
                "a\x00b\x00c",
                "<script>alert('xss')</script>",
                "' OR '1'='1' --",
                '{"key": "value", "nested": [1, 2]}',
                "https://example.com/api?q=test&page=1",
                "c:\\Windows\\System32\\cmd.exe",
                "/dev/null",
            ])

        if any(t in normalized_types for t in ("int", "integer", "number")):
            pools.append([
                0,
                1,
                -1,
                2,
                -2,
                42,
                -42,
                100,
                -100,
                255,
                256,
                65535,
                65536,
                2**31 - 1,
                -2**31,
                2**63 - 1,
                -2**63,
                10**18,
                -10**18,
                sys.maxsize,
                -sys.maxsize - 1,
            ])

        if any(t in normalized_types for t in ("float", "decimal", "real")):
            pools.append([
                0.0,
                -0.0,
                1.0,
                -1.0,
                0.5,
                -0.5,
                math.pi,
                math.e,
                1e-15,
                1e15,
                1e-300,
                1e300,
                float("inf"),
                float("-inf"),
            ])

        if any(t in normalized_types for t in ("bool", "boolean")):
            pools.append([True, False])

        if any(t in normalized_types for t in ("list", "array", "sequence")):
            pools.append([
                [],
                [None],
                [0],
                [""],
                [True, False],
                [1, 2, 3, 4, 5],
                ["alpha", "beta", "gamma"],
                [[], [[]]],
                list(range(50)),
                [0] * 100,
            ])

        if any(t in normalized_types for t in ("dict", "map", "object")):
            pools.append([
                {},
                {"": ""},
                {"key": "value"},
                {"a": 1, "b": 2, "c": 3},
                {"nested": {"level1": {"level2": True}}},
                {"list": [1, 2, 3]},
            ])

        if any(t in normalized_types for t in ("none", "null", "nonetype")):
            pools.append([None])

        if any(t in normalized_types for t in ("bytes", "binary")):
            pools.append([
                b"",
                b"\x00",
                b"hello world",
                b"\xff\xfe\xfd\xfc",
                bytes([i % 256 for i in range(128)]),
            ])

        if not pools:
            pools.append(["", 0, 0.0, False, None, [], {}])

        # Interleave round-robin across all requested pools to ensure balanced coverage
        result: list[Any] = []
        max_pool_len = max(len(p) for p in pools)
        for idx in range(max_pool_len):
            for pool in pools:
                if idx < len(pool):
                    result.append(pool[idx])
                    if len(result) >= count:
                        return result

        # If count still exceeds unique items, cycle through
        cycle_idx = 0
        while len(result) < count and pools:
            pool = pools[cycle_idx % len(pools)]
            result.append(pool[(cycle_idx // len(pools)) % len(pool)])
            cycle_idx += 1

        return result[:count]

    def verify_algebraic_invariants(
        self,
        module_code: str,
        encode_fn: str,
        decode_fn: str,
        sample_inputs: list[Any],
    ) -> dict[str, Any]:
        """Test decode(encode(x)) == x roundtrip consistency."""
        if not sample_inputs:
            return {
                "total_tested": 0,
                "passed": 0,
                "failed": 0,
                "success_rate": 1.0,
                "roundtrip_invariant_holds": True,
                "failure_examples": [],
            }

        encoded_payload = base64.b64encode(pickle.dumps(sample_inputs)).decode("ascii")

        driver = f"""
import base64
import json
import pickle
import sys

{module_code}

raw_inputs = pickle.loads(base64.b64decode("{encoded_payload}".encode("ascii")))
encoder = globals().get("{encode_fn}")
decoder = globals().get("{decode_fn}")

if encoder is None or decoder is None:
    print("__INVARIANT_OUTPUT__" + json.dumps({{"error": "Target functions not found in module"}}))
    sys.exit(0)

total = len(raw_inputs)
passed = 0
failed = 0
failure_examples = []

for item in raw_inputs:
    try:
        enc = encoder(item)
        dec = decoder(enc)
        # Handle float nan comparison
        if isinstance(item, float) and item != item:
            is_equal = isinstance(dec, float) and dec != dec
        else:
            is_equal = (dec == item)

        if is_equal:
            passed += 1
        else:
            failed += 1
            if len(failure_examples) < 10:
                failure_examples.append({{
                    "input": repr(item),
                    "encoded": repr(enc),
                    "decoded": repr(dec),
                    "reason": "dec(enc(x)) != x",
                }})
    except Exception as exc:
        failed += 1
        if len(failure_examples) < 10:
            failure_examples.append({{
                "input": repr(item),
                "error": f"{{type(exc).__name__}}: {{exc}}",
                "reason": "Exception during roundtrip",
            }})

output = {{
    "total_tested": total,
    "passed": passed,
    "failed": failed,
    "success_rate": round(passed / max(1, total), 4),
    "roundtrip_invariant_holds": failed == 0,
    "failure_examples": failure_examples,
}}
print("__INVARIANT_OUTPUT__" + json.dumps(output))
"""
        res = self._harness.run_scratch_test(driver, timeout_sec=6.0)
        marker = "__INVARIANT_OUTPUT__"

        if marker in res.get("stdout", ""):
            payload_str = res["stdout"].split(marker, 1)[1].strip()
            try:
                data = json.loads(payload_str)
                return data
            except json.JSONDecodeError:
                pass

        return {
            "total_tested": len(sample_inputs),
            "passed": 0,
            "failed": len(sample_inputs),
            "success_rate": 0.0,
            "roundtrip_invariant_holds": False,
            "error": res.get("stderr") or "Failed to execute roundtrip verification",
            "failure_examples": [],
        }
