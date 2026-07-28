#!/usr/bin/env bash
# One-stop first-time data setup, no Claude Code involved: given
# transactions.csv is already placed, chains lots -> tickers -> backfill so
# you don't have to run each pipeline module by hand. See docs/QUICKSTART.md
# steps 1-6 for what each of these does individually.
#
# Ticker resolution still needs a human to review the picks (deliberately -
# see pipeline/tickers.py's "CONFIRM-don't-GUESS" docstring) - this script
# doesn't skip that, it just runs everything in one command and tells you
# clearly at the end if anything needs fixing before you trust the numbers.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
PY="$MCP_DIR/.venv/bin/python3"

if [ ! -f "$PY" ]; then
  echo "error: venv not found at $MCP_DIR/.venv - run 'make venv-setup' first" >&2
  exit 1
fi

cd "$MCP_DIR"

TRANSACTIONS_FILE="$("$PY" -c 'from portfolio_tools.paths import TRANSACTIONS_FILE; print(TRANSACTIONS_FILE)')"
if [ ! -f "$TRANSACTIONS_FILE" ]; then
  echo "error: no transactions export found at $TRANSACTIONS_FILE" >&2
  echo "Export your transaction history from Scalable Capital and save it there" >&2
  echo "(create the parent directory if needed), then re-run this." >&2
  exit 1
fi

echo "==> [1/3] Building positions from $TRANSACTIONS_FILE"
"$PY" -m portfolio_tools.pipeline.lots

echo ""
echo "==> [2/3] Resolving tickers for any new holdings"
TICKERS_LOG="$(mktemp)"
"$PY" -m portfolio_tools.pipeline.tickers 2>&1 | tee "$TICKERS_LOG"

echo ""
echo "==> [3/3] Backfilling historical prices (this can take a few minutes)"
"$PY" -m portfolio_tools.pipeline.backfill

echo ""
if grep -q '⚠' "$TICKERS_LOG"; then
  echo "==> Done, but ACTION NEEDED: some ticker picks above were flagged (⚠)."
  echo "    Fix them in data/impersonal/ticker_map.csv, then re-run this script"
  echo "    (lots/tickers/backfill are all safe to re-run)."
else
  echo "==> Done. Still yours to fill in: the blank Sector column in"
  echo "    data/impersonal/ticker_map.csv for any new holdings."
fi
rm -f "$TICKERS_LOG"
echo ""
echo "Once you're happy with the ticker map, 'make refresh' (repo root) runs"
echo "the pipeline daily - prices, analysis, compliance, report."
