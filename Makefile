.PHONY: bootstrap claude-setup codex-setup copilot-setup setup-data-and-backfill bootstrap-with-schedule venv-setup server-start mcp-register skill-install codex-mcp-register codex-skill-install copilot-mcp-register copilot-skill-install setup-env fetch-prices refresh backfill

## === MAIN ENTRY POINTS ===

## Base setup: venv + MCP server only. Deliberately Claude-free - never
## touches Claude Code's own config or ~/.claude/. See 'make claude-setup'
## to hook Claude Code into the server this starts.
bootstrap:
	./bootstrap.sh

## Register the MCP server + install the Skill with Claude Code. Independent
## of 'make bootstrap' - run any time after the server's up to add (or
## re-add) the Claude Code integration, without re-running venv/server setup.
claude-setup: mcp-register skill-install
	@echo ""
	@echo "Done. Start a NEW Claude Code session (any project) to pick up"
	@echo "the skill and MCP tools."

## Alternative to 'make claude-setup': register the MCP server + install the
## Skill with Codex CLI instead. Independent of 'make bootstrap' and of
## claude-setup - the two aren't mutually exclusive, both can be registered
## against the same running server. Requires the 'codex' CLI on PATH.
codex-setup: codex-mcp-register codex-skill-install
	@echo ""
	@echo "Done. Codex detects the skill automatically - restart it if the"
	@echo "MCP tools or skill don't show up right away."

## Alternative to 'make claude-setup' / 'make codex-setup': register the MCP
## server + install the Skill with GitHub Copilot CLI instead. Independent of
## 'make bootstrap' and the other two - none are mutually exclusive, all can
## be registered against the same running server. Requires the 'copilot' CLI
## on PATH.
copilot-setup: copilot-mcp-register copilot-skill-install
	@echo ""
	@echo "Done. Copilot detects the skill automatically - restart it if the"
	@echo "MCP tools or skill don't show up right away."

## Setup for pure-Python use: venv + server, then (assuming you've already
## placed data/personal/transactions.csv) builds positions, resolves tickers,
## and backfills history in one go. No Claude Code needed. Fails clearly if
## transactions.csv isn't there yet - place it and re-run.
setup-data-and-backfill:
	./bootstrap.sh
	./scripts/setup-data.sh

## Full Claude setup (bootstrap + claude-setup) + prompt to schedule daily
## Claude Code tasks (requires an active session)
bootstrap-with-schedule: bootstrap claude-setup
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

## Codex equivalent of 'make mcp-register' - registers with the codex CLI
## (Streamable HTTP) instead of claude
codex-mcp-register:
	./scripts/codex-mcp-register.sh

## Codex equivalent of 'make skill-install' - copies skills/portfolio/ to
## Codex's global skills directory ($HOME/.agents/skills/portfolio/)
codex-skill-install:
	./scripts/codex-skill-install.sh

## Copilot equivalent of 'make mcp-register' - registers with the copilot
## CLI (HTTP transport) instead of claude/codex
copilot-mcp-register:
	./scripts/copilot-mcp-register.sh

## Copilot equivalent of 'make skill-install' - copies skills/portfolio/ to
## Copilot's global skills directory (~/.copilot/skills/portfolio/)
copilot-skill-install:
	./scripts/copilot-skill-install.sh
