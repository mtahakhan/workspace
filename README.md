# Portfolio pipeline

A portfolio tracker and daily analysis pipeline for Scalable Capital: a
deterministic Python pipeline behind an MCP server, with an optional Claude
Skill on top. The MCP server setup is Claude-free by design - the Claude Code
integration is a separate, independent step, not baked into base setup.
Upload a transaction export and it reconstructs your real positions, fetches
prices, computes value/gain/XIRR/drawdown/sector concentration, and writes a
daily report - see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the
full description.

## Quick start

```bash
make bootstrap
```
Sets up the venv and starts the MCP server - no Claude Code involved yet.

**Want Claude Code to use it?**
```bash
make claude-setup
```
Registers the MCP server globally and installs the Skill. Then start a
**new** Claude Code session and ask about your portfolio - it will walk you
through first-time setup (transactions, tickers, optional API key).

**Want something else** - just the numbers with no LLM, a hybrid of both, or
full automation? See [`docs/PATHWAYS.md`](docs/PATHWAYS.md) for all four
setup paths and their trade-offs.

## What's in this repo

### Documentation
| Doc | For |
|---|---|
| [`docs/PATHWAYS.md`](docs/PATHWAYS.md) | **Start here** — compares all four usage modes (Claude, Python-only, hybrid, automated) |
| [`docs/SETUP.md`](docs/SETUP.md) | Full setup walkthrough for Claude Code path, Finnhub API key, daily automation |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Running the pipeline manually from terminal, step-by-step with explanations |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system works — data flow, file map, MCP tools, methodology |
| [`docs/AGENT_NOTES.md`](docs/AGENT_NOTES.md) | Rules and lessons learned, for anyone developing in this repo |

### Code & Scripts
| Path | What |
|---|---|
| [`mcp_servers/portfolio_tools/`](mcp_servers/portfolio_tools/) | The MCP server + deterministic pipeline (FIFO cost basis, prices, XIRR, drawdown, compliance, etc.) |
| [`skills/portfolio/`](skills/portfolio/SKILL.md) | The Claude Skill — self-contained, deployed globally by `make claude-setup` |
| [`Makefile`](Makefile) | `make bootstrap` (venv + server, Claude-free), `make claude-setup` (Claude Code integration, independent), `make refresh` (run), `make setup-data-and-backfill` (Python-only), plus individual targets |
| [`bootstrap.sh`](bootstrap.sh) | Base bootstrap orchestrator — venv + server only, never touches Claude Code's own config |
| [`scripts/`](scripts/) | Bootstrap steps + manual pipeline runners (`fetch-prices.sh`, `run-pipeline.sh`) |
| [`setup-env.sh`](setup-env.sh) | Interactive prompt for Finnhub API key and data directory |
