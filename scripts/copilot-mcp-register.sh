#!/usr/bin/env bash
# Register the portfolio MCP server globally with GitHub Copilot CLI (HTTP
# transport). Mirrors scripts/mcp-register.sh / scripts/codex-mcp-register.sh,
# but for Copilot - see
# https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
# for Copilot's MCP config format (~/.copilot/mcp-config.json).
# Safe to re-run - removes any existing registration first to avoid duplicates.
set -euo pipefail

PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

if ! command -v copilot >/dev/null 2>&1; then
  echo "error: 'copilot' CLI not found on PATH - install GitHub Copilot CLI first" >&2
  echo "       (https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/overview)" >&2
  exit 1
fi

echo "==> Registering the MCP server globally with Copilot (HTTP transport)"
copilot mcp remove portfolio >/dev/null 2>&1 || true
copilot mcp add --transport http portfolio "$SERVER_URL"
