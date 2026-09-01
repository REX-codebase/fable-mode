#!/usr/bin/env bash
# Source-mode compatibility shim. The implementation lives in fable_mode.installer.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/fable_mode_entry.py" install "$@"
