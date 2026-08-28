#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "  Fable-Mode V1: Legacy MCP Session Engine"
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[+] Running Fable-Engine V1 test suite (legacy MCP server)..."
python3 "$SCRIPT_DIR/fable_engine/test_server.py"
echo "[✓] All tests passed (100%)."

SKILL_DEST="$HOME/.gemini/config/skills/fable-mode"
echo "[+] Installing skill to: $SKILL_DEST"
mkdir -p "$SKILL_DEST"
cp -r "$SCRIPT_DIR/skills/fable-mode/"* "$SKILL_DEST/"

# This is a host-specific Gemini-style layout; override MCP_DIR for another host.
MCP_DIR="${MCP_DIR:-$HOME/.gemini/antigravity/mcp/fable-engine}"
mkdir -p "$MCP_DIR"
cp "$SCRIPT_DIR/fable_engine/fable_session.json" "$MCP_DIR/fable_session.json"

echo "=========================================================="
echo "  Fable-Mode V1 installation complete (legacy MCP server)!"
echo "=========================================================="


