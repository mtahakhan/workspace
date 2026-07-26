#!/usr/bin/env bash
# Step 2: Start the portfolio MCP server in the background (nohup + PID file).
# Not a login/boot service - re-run after a reboot or crash.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"
PID_FILE="$MCP_DIR/.server.pid"
LOG_FILE="$MCP_DIR/.server.log"
PORT="${PORTFOLIO_MCP_PORT:-8420}"

if [ ! -f "$VENV/bin/python3" ]; then
  echo "error: venv not found at $VENV - run 'make venv-setup' first" >&2
  exit 1
fi

echo "==> [2/4] Starting the portfolio MCP server (background, port $PORT)"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "    already running (pid $(cat "$PID_FILE"))"
else
  rm -f "$PID_FILE"
  (
    cd "$REPO_DIR/mcp_servers"
    PORTFOLIO_MCP_PORT="$PORT" nohup "$VENV/bin/python3" -m portfolio_tools.server \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
  )
  sleep 2
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "error: server failed to start - check $LOG_FILE" >&2
    exit 1
  fi
  echo "    started (pid $(cat "$PID_FILE")), logs at $LOG_FILE"
fi
