#!/usr/bin/env bash
# Bootstrap the portfolio MCP server + Claude Skill globally, after cloning
# this repo on a new machine (or a fresh `claude` install on this one).
#
# What this does, in order:
#   1. Creates portfolio/portfolio_mcp/.venv (Python >=3.10) and installs deps
#   2. Starts the HTTP server in the background (nohup + PID file) if it's
#      not already running - NOT a login/boot service, just a background
#      process for this session; re-run this script after a reboot or crash
#   3. Registers it with `claude mcp add --scope user` (HTTP transport) so
#      it's available in every Claude Code session on this machine, in any
#      project - not just this one
#   4. Copies skills/portfolio/ (SKILL.md + references/) wholesale to
#      ~/.claude/skills/portfolio/ - self-contained, no dependency on this
#      repo's location surviving afterward. Deliberately NOT under .claude/
#      in this repo, so Claude Code doesn't also auto-discover it as a
#      project-scoped skill while developing here (see docs/ARCHITECTURE.md's
#      "Deployment model").
#
# Safe to re-run: steps are skipped if already done, and the MCP
# registration is replaced (not duplicated) each time.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_DIR="$REPO_DIR/portfolio/portfolio_mcp"
VENV="$MCP_DIR/.venv"
PID_FILE="$MCP_DIR/.server.pid"
LOG_FILE="$MCP_DIR/.server.log"
PORT="${PORTFOLIO_MCP_PORT:-8420}"
SERVER_URL="http://127.0.0.1:${PORT}/mcp"

if [ ! -d "$MCP_DIR" ]; then
  echo "error: $MCP_DIR not found - run this script from a checkout of the repo" >&2
  exit 1
fi

echo "==> [1/4] Setting up the server's venv"
if [ ! -d "$VENV" ]; then
  PYTHON_BIN=""
  for candidate in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    echo "error: no Python >=3.10 interpreter found (checked python3.10-python3.13)." >&2
    echo "The mcp package requires it; system python3 is often older. Install one and re-run." >&2
    exit 1
  fi
  echo "    using $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$VENV"
else
  echo "    already exists"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$MCP_DIR/requirements.txt"

echo "==> [2/4] Starting the portfolio MCP server (background, port $PORT)"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "    already running (pid $(cat "$PID_FILE"))"
else
  rm -f "$PID_FILE"
  (
    cd "$REPO_DIR/portfolio"
    PORTFOLIO_MCP_PORT="$PORT" nohup "$VENV/bin/python3" -m portfolio_mcp.server \
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

echo "==> [3/4] Registering the MCP server globally (user scope, HTTP)"
claude mcp remove portfolio -s user >/dev/null 2>&1 || true
claude mcp add --scope user --transport http portfolio "$SERVER_URL"

echo "==> [4/4] Installing the portfolio skill globally"
rm -rf "$HOME/.claude/skills/portfolio"
mkdir -p "$HOME/.claude/skills/portfolio"
cp -r "$REPO_DIR/skills/portfolio/." "$HOME/.claude/skills/portfolio/"

echo ""
echo "Done."
echo "  Server:  $SERVER_URL (pid $(cat "$PID_FILE"), logs: $LOG_FILE)"
echo "  Stop it: kill \$(cat $PID_FILE)"
echo "  Data:    $MCP_DIR/data/ (transactions.csv isn't there yet - upload it"
echo "           via the upload_transactions tool from a Claude Code session)"
echo ""
echo "Start a NEW Claude Code session (any project) to pick up the skill and MCP tools."
