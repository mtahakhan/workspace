#!/usr/bin/env bash
# Step 3: Register the portfolio MCP server globally (user scope, HTTP transport).
# Safe to re-run - removes any existing registration first to avoid duplicates.
set -euo pipefail

PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

echo "==> [3/4] Registering the MCP server globally (user scope, HTTP)"
claude mcp remove portfolio -s user >/dev/null 2>&1 || true
claude mcp add --scope user --transport http portfolio "$SERVER_URL"
