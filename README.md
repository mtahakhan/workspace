# Portfolio pipeline

A portfolio tracker and daily analysis pipeline for Scalable Capital, packaged
as a Claude Skill + a globally-registered MCP server. Clone this repo, run
one script, and it's available in every Claude Code session on the machine -
not just this project.

## Quick start

```bash
./bootstrap.sh
```
Needs Python >=3.10 and the `claude` CLI. This sets up the server, starts it
in the background, registers the `portfolio` MCP server and Claude Skill
globally, and is safe to re-run any time. Then start a **new** Claude Code
session (any project) and ask it about your portfolio - if nothing's been
uploaded yet, it will walk you through first-run setup itself.

Full walkthrough, including getting a (free, optional) Finnhub API key: see
[`docs/SETUP.md`](docs/SETUP.md).

Want to run the pipeline yourself from a terminal, with no Claude Code or LLM
involved at all? See [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## What's in this repo

| Path | What |
|---|---|
| [`mcp_servers/portfolio_tools/`](mcp_servers/portfolio_tools/) | The MCP server + deterministic pipeline (FIFO cost basis, prices, XIRR, drawdown, etc.) |
| [`skills/portfolio/`](skills/portfolio/SKILL.md) | The Claude Skill - self-contained, deployed globally by `bootstrap.sh` |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system works - data flow, file map, MCP tools, methodology |
| [`docs/AGENT_NOTES.md`](docs/AGENT_NOTES.md) | Rules and lessons learned, for anyone developing in this repo |
| [`docs/SETUP.md`](docs/SETUP.md) | This README, expanded - full human setup walkthrough |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Running the pipeline manually, no Claude Code needed |
| [`Makefile`](Makefile) | `make bootstrap` (all steps), `make fetch-prices` / `make refresh` (run the pipeline manually, no Claude Code needed), plus individual bootstrap targets and `make setup-env` |
| [`bootstrap.sh`](bootstrap.sh) | Full bootstrap orchestrator - delegates to `scripts/` in order |
| [`scripts/`](scripts/) | Bootstrap steps (`venv-setup.sh`, `server-start.sh`, `mcp-register.sh`, `skill-install.sh`) + manual pipeline runners (`fetch-prices.sh`, `run-pipeline.sh`) |
| [`setup-env.sh`](setup-env.sh) | Interactive prompt to write the Finnhub API key to `.env` |

## What it does

Upload a Scalable Capital transaction export and it reconstructs your real
positions (FIFO cost basis), fetches live/historical prices, computes
value/gain/XIRR/drawdown/sector concentration/movers, and writes a daily
markdown report with news research on every holding - all deterministic
Python for the numbers, an LLM only for the prose and research on top.

See [`docs/SETUP.md`](docs/SETUP.md) for the full description and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it's built.
