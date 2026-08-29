"""Frozen/source top-level wrapper; package imports remain valid in both modes."""
import sys

# Install trees have an exact file manifest; runtime probes must not create
# unlisted __pycache__ artifacts beside the canonical source payload.
sys.dont_write_bytecode = True
from fable_mode.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
