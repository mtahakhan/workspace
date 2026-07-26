.PHONY: bootstrap venv-setup server-start mcp-register skill-install setup-env

## Run all bootstrap steps in order (idempotent, safe to re-run)
bootstrap:
	./bootstrap.sh

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
