#!/usr/bin/env bash
# Run the deterministic part of the pipeline once, with no Claude Code and no
# MCP server involved - the same steps create_refresh runs when called via
# the `portfolio` MCP tool (see docs/ARCHITECTURE.md's "Refreshes"), just
# invoked directly against this package's own venv. See docs/QUICKSTART.md
# for the step-by-step version of exactly what this automates.
#
# Requires transaction_lots.csv / enriched_lots.csv to already exist (run
# `pipeline.lots` and `pipeline.tickers` first - see QUICKSTART.md steps 1-4)
# and $FINNHUB_API_KEY optionally set via mcp_servers/portfolio_tools/.env.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$REPO_DIR/mcp_servers/portfolio_tools"
VENV="$MCP_DIR/.venv"
PY="$VENV/bin/python3"

if [ ! -f "$PY" ]; then
  echo "error: venv not found at $VENV - run 'make venv-setup' first" >&2
  exit 1
fi

OUT_DIR="$REPO_DIR/data/personal/manual-runs/$(date +%Y-%m-%d_%H-%M-%S)"
mkdir -p "$OUT_DIR"

echo "==> [1/4] Fetching prices"
"$REPO_DIR/scripts/fetch-prices.sh"

cd "$REPO_DIR/mcp_servers"

echo "==> [2/4] Computing analysis"
"$PY" -m portfolio_tools.pipeline.analysis > "$OUT_DIR/analysis.json"

echo "==> [3/4] Checking compliance"
"$PY" -m portfolio_tools.pipeline.compliance > "$OUT_DIR/compliance.json"

echo "==> [4/4] Rendering report + exit report"
"$PY" -m portfolio_tools.pipeline.report "$OUT_DIR/analysis.json" > "$OUT_DIR/report.md"
"$PY" -m portfolio_tools.pipeline.exit_report < "$OUT_DIR/analysis.json" > "$OUT_DIR/exit-report.md"

echo ""
echo "Done. Output saved under ${OUT_DIR#"$REPO_DIR"/}/"
echo "  analysis.json, compliance.json, report.md, exit-report.md"
echo ""
cat "$OUT_DIR/report.md"
