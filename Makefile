.PHONY: bootstrap setup-data-and-backfill bootstrap-with-schedule venv-setup server-start mcp-register skill-install setup-env fetch-prices refresh run-once

## === MAIN ENTRY POINTS ===

## Full setup with Claude + MCP server + Skill (recommended)
## Walks you through first-run setup in Claude Code after this completes
bootstrap:
	./bootstrap.sh

## Setup for pure-Python use: venv + server + backfilled historical prices
## Then use 'make refresh' daily to run the pipeline, no Claude Code needed
setup-data-and-backfill:
	./bootstrap.sh
	@echo ""
	@echo "Backfilling historical prices for analysis (this takes a minute or two)..."
	@cd mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.backfill
	@echo "Done. Now upload your transactions.csv via 'make refresh' or the upload_transactions tool."

## Setup + schedule daily tasks in Claude Code (requires active Claude Code session)
bootstrap-with-schedule:
	./bootstrap.sh
	@echo ""
	@echo "Setting up scheduled tasks in Claude Code..."
	@echo "Run this in a Claude Code session to enable daily automation:"
	@echo "  ask Claude to 'schedule portfolio refresh' or create daily-refresh and daily-analysis tasks"
	@echo "See docs/SETUP.md for details."

## === PIPELINE COMMANDS ===

## Run the deterministic pipeline once: prices -> analysis -> compliance -> report
## No Claude Code or MCP server needed. Output saved + printed to stdout.
## See docs/QUICKSTART.md for step-by-step explanation.
refresh:
	./scripts/run-pipeline.sh

## Fetch today's live prices only (no analysis/compliance/report)
## Fails loudly if any ticker can't be priced.
fetch-prices:
	./scripts/fetch-prices.sh

## === SETUP STEPS (can also be run individually) ===

## Step 0: interactively set data directory + Finnhub API key (first run only)
setup-env:
	./setup-env.sh

## Step 1: create .venv (Python >=3.10) and install dependencies
venv-setup:
	./scripts/venv-setup.sh

## Step 2: start the MCP server in the background (nohup + PID file)
server-start:
	./scripts/server-start.sh

## Step 3: register the MCP server globally with claude (user scope, HTTP)
mcp-register:
	./scripts/mcp-register.sh

## Step 4: copy skills/portfolio/ to ~/.claude/skills/portfolio/
skill-install:
	./scripts/skill-install.sh
