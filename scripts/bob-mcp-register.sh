#!/usr/bin/env bash
# Register the portfolio MCP server globally with IBM Bob (user scope, HTTP transport).
# Safe to re-run - merges into existing ~/.bob/settings/mcp.json without clobbering
# other servers already registered there.
set -euo pipefail

PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"
MCP_FILE="$HOME/.bob/settings/mcp.json"
MERGE_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/bob-mcp-merge.py"

echo "==> [bob 1/2] Registering the MCP server globally with IBM Bob (HTTP, port $PORT)"

mkdir -p "$(dirname "$MCP_FILE")"

python3 "$MERGE_SCRIPT" "$MCP_FILE" "portfolio" "$SERVER_URL"

echo "    written to $MCP_FILE"
