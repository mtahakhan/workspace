#!/usr/bin/env bash
# Run just the price fetch, with no Claude Code and no MCP server involved -
# appends today's live price for every ticker to its own
# data/impersonal/price_history/{TICKER}.jsonl. Raises (non-zero exit) if any
# ticker fails on both Finnhub and yfinance - tickers that DID resolve are
# still fetched and appended first. See docs/QUICKSTART.md step 5.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"
PY="$VENV/bin/python3"

if [ ! -f "$PY" ]; then
  echo "error: venv not found at $VENV - run 'make venv-setup' first" >&2
  exit 1
fi

cd "$REPO_DIR/mcp_servers"
"$PY" -m portfolio_tools.pipeline.prices
