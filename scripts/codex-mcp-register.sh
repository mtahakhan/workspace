#!/usr/bin/env bash
# Register the portfolio MCP server globally with Codex CLI (Streamable HTTP).
# Mirrors scripts/mcp-register.sh, but for Codex instead of Claude Code - see
# https://developers.openai.com/codex/mcp for Codex's MCP config format.
# Safe to re-run - removes any existing registration first to avoid duplicates.
set -euo pipefail

PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

if ! command -v codex >/dev/null 2>&1; then
  echo "error: 'codex' CLI not found on PATH - install Codex CLI first" >&2
  echo "       (https://developers.openai.com/codex/cli)" >&2
  exit 1
fi

echo "==> Registering the MCP server globally with Codex (Streamable HTTP)"
codex mcp remove portfolio >/dev/null 2>&1 || true
codex mcp add portfolio --url "$SERVER_URL"
