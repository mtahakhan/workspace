#!/usr/bin/env bash
# Bootstrap the portfolio MCP server + Claude Skill globally, after cloning
# this repo on a new machine (or a fresh `claude` install on this one).
#
# Orchestrates the four individual steps in order:
#   1. scripts/venv-setup.sh   - create .venv (Python >=3.10) + install deps
#   2. scripts/server-start.sh - start HTTP server in background (nohup + PID)
#   3. scripts/mcp-register.sh - register with `claude mcp add --scope user`
#   4. scripts/skill-install.sh - copy skills/portfolio/ to ~/.claude/skills/
#
# Each step can also be run individually via `make <target>` (see Makefile).
# Safe to re-run: every step is skip-if-already-done except steps 3 and 4,
# which always replace cleanly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"
PID_FILE="$MCP_DIR/.server.pid"
LOG_FILE="$MCP_DIR/.server.log"
PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

bash "$REPO_DIR/scripts/venv-setup.sh"
bash "$REPO_DIR/scripts/server-start.sh"
bash "$REPO_DIR/scripts/mcp-register.sh"
bash "$REPO_DIR/scripts/skill-install.sh"

echo ""
echo "Done."
echo "  Server:  $SERVER_URL (pid $(cat "$PID_FILE"), logs: $LOG_FILE)"
echo "  Stop it: kill \$(cat $PID_FILE)"
echo "  Data:    $MCP_DIR/data/ (transactions.csv isn't there yet - upload it"
echo "           via the upload_transactions tool from a Claude Code session)"
echo ""
echo "Start a NEW Claude Code session (any project) to pick up the skill and MCP tools."
