#!/usr/bin/env bash
# Step 1: Create the venv (Python >=3.10) and install dependencies.
# A system Python is used only here to create the venv itself; every
# subsequent invocation uses .venv/bin/python3 or .venv/bin/pip exclusively.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"

if [ ! -d "$MCP_DIR" ]; then
  echo "error: $MCP_DIR not found - run from a checkout of the repo" >&2
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
echo "    deps installed"
