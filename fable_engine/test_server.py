#!/usr/bin/env python3
"""Compatibility test entry point.

The old monolithic V1 suite was retired because it encoded the pre-attested
receipt contract. CI now discovers the focused suites under ``tests/``.
"""
from __future__ import annotations

import pathlib
import sys
import unittest


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    raise SystemExit(unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() is False)
