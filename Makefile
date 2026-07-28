.PHONY: bootstrap venv-setup server-start mcp-register skill-install setup-env fetch-prices refresh

## Run all bootstrap steps in order (idempotent, safe to re-run)
bootstrap:
	./bootstrap.sh

## Fetch today's live prices only (no analysis/compliance/report) - no Claude
## Code or MCP server needed. Fails loudly if any ticker can't be priced.
fetch-prices:
	./scripts/fetch-prices.sh

## Run the deterministic pipeline once: fetch prices, then compute analysis +
## compliance + render + exit-report - no Claude Code or MCP server needed.
## Output saved under data/personal/manual-runs/<timestamp>/ and the report
## printed to stdout. See docs/QUICKSTART.md for the equivalent step-by-step.
refresh:
	./scripts/run-pipeline.sh

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

## Interactively set Finnhub API key and write .env
setup-env:
	./setup-env.sh
