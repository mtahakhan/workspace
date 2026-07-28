.PHONY: bootstrap setup-data-and-backfill bootstrap-with-schedule venv-setup server-start mcp-register skill-install setup-env fetch-prices refresh backfill

## === MAIN ENTRY POINTS ===

## Full setup with Claude + MCP server + Skill (recommended)
## Walks you through first-run setup in Claude Code after this completes
bootstrap:
	./bootstrap.sh

## Setup for pure-Python use: venv + server, then (assuming you've already
## placed data/personal/transactions.csv) builds positions, resolves tickers,
## and backfills history in one go. No Claude Code needed. Fails clearly if
## transactions.csv isn't there yet - place it and re-run.
setup-data-and-backfill:
	./bootstrap.sh
	./scripts/setup-data.sh

## Setup + prompt to schedule daily Claude Code tasks (requires an active session)
bootstrap-with-schedule:
	./bootstrap.sh
	@echo ""
	@echo "In a Claude Code session, ask it to create two scheduled tasks:"
	@echo "  portfolio-daily-refresh  and  portfolio-daily-analysis"
	@echo "See docs/SETUP.md#setting-up-daily-automation for details."

## === PIPELINE COMMANDS ===

## Fetch today's live prices only (no analysis/compliance/report)
## Fails loudly if any ticker can't be priced.
fetch-prices:
	./scripts/fetch-prices.sh

## Run the deterministic pipeline once: prices -> analysis -> compliance -> report
## No Claude Code or MCP server needed. Output saved + printed to stdout.
## See docs/QUICKSTART.md for step-by-step explanation.
refresh:
	./scripts/run-pipeline.sh



## (One-time per ticker) backfill full historical prices - requires tickers
## already resolved (docs/QUICKSTART.md steps 1-4); see docs/QUICKSTART.md step 6
backfill:
	cd mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.backfill

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
