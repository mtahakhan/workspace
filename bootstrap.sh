#!/usr/bin/env bash
# Bootstrap the portfolio MCP server, after cloning this repo on a new
# machine. Deliberately Claude-free - this only gets the server itself
# running; it never touches Claude Code's own config or ~/.claude/. For
# that, run `make claude-setup` separately (see scripts/mcp-register.sh,
# scripts/skill-install.sh) once the server's up.
#
# Orchestrates the steps in order:
#   0. setup-env.sh            - data directory + Finnhub key -> .env (first run only)
#   1. scripts/venv-setup.sh   - create .venv (Python >=3.10) + install deps
#   2. scripts/server-start.sh - start HTTP server in background (nohup + PID)
#
# Each step can also be run individually via `make <target>` (see Makefile).
# Safe to re-run: every step is skip-if-already-done.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"
PID_FILE="$MCP_DIR/.server.pid"
LOG_FILE="$MCP_DIR/.server.log"
PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

# Step 0: data directory + secrets. Interactive, and only when .env doesn't exist
# yet - a re-run of bootstrap must stay non-interactive. Use `make setup-env` to
# change either value later.
if [ ! -f "$MCP_DIR/.env" ]; then
  bash "$REPO_DIR/setup-env.sh"
fi

bash "$REPO_DIR/scripts/venv-setup.sh"
bash "$REPO_DIR/scripts/server-start.sh"

echo ""
echo "Done."
echo "  Server:  $SERVER_URL (pid $(cat "$PID_FILE"), logs: $LOG_FILE)"
echo "  Stop it: kill \$(cat $PID_FILE)"
DATA_DIR="$(grep -E '^PORTFOLIO_DATA_DIR=' "$MCP_DIR/.env" 2>/dev/null | cut -d= -f2- || true)"
echo "  Data:    ${DATA_DIR:-$REPO_DIR/data} (personal/ + impersonal/; change it with"
echo "           'make setup-env')"
echo ""
echo "Want Claude Code to use this server? Run 'make claude-setup' next -"
echo "registers it globally and installs the Skill. Otherwise, see"
echo "docs/QUICKSTART.md to run the pipeline yourself, no Claude Code needed."
