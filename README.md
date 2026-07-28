# Portfolio pipeline

A portfolio tracker and daily analysis pipeline for Scalable Capital, packaged
as a Claude Skill + a globally-registered MCP server. Clone this repo, run
one script, and it's available in every Claude Code session on the machine -
not just this project.

## Quick start (choose your path)

**Recommended: Guided setup + Claude-powered analysis**
```bash
make bootstrap
```
Then start a **new** Claude Code session and ask about your portfolio - it will walk
you through first-time setup (transactions, tickers, optional API key).

**Just want to run the numbers yourself, no Claude involved?**
```bash
make setup-data-and-backfill
```
Sets up the pipeline and backfills historical prices for analysis. Then use `make refresh`
to run it daily without any Claude Code or LLM.

**Already set up, just run today's numbers:**
```bash
make refresh
```

**Advanced: run individual steps manually for debugging**
See [`docs/QUICKSTART.md`](docs/QUICKSTART.md)

---

## Usage modes

Pick the path that matches your workflow:

| Path | Command | What you get | LLM involved? |
|---|---|---|---|
| **Full setup + daily Claude analysis** | `make bootstrap` | MCP server + Claude Skill globally registered; Claude handles setup flow, fetches news, writes daily reports | ✅ Yes |
| **Setup + manual deterministic pipeline** | `make setup-data-and-backfill` | Just the Python pipeline; you run `make refresh` daily from terminal | ❌ No |
| **Already set up, daily automation** | `make bootstrap-with-schedule` | Adds scheduled daily tasks to Claude Code (fetching + analysis) | ✅ Yes |
| **One-time manual run** | `make refresh` (after first-time setup) | Deterministic pipeline only - prices, analysis, compliance, report | ❌ No |

Full walkthrough with optional Finnhub API key: [`docs/SETUP.md`](docs/SETUP.md)

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
| [`skills/portfolio/`](skills/portfolio/SKILL.md) | The Claude Skill — self-contained, deployed globally by `bootstrap.sh` |
| [`Makefile`](Makefile) | `make bootstrap` (setup), `make refresh` (run), `make setup-data-and-backfill` (Python-only), plus individual targets |
| [`bootstrap.sh`](bootstrap.sh) | Full bootstrap orchestrator — delegates to `scripts/` in order |
| [`scripts/`](scripts/) | Bootstrap steps + manual pipeline runners (`fetch-prices.sh`, `run-pipeline.sh`) |
| [`setup-env.sh`](setup-env.sh) | Interactive prompt for Finnhub API key and data directory |

## What it does

Upload a Scalable Capital transaction export and it reconstructs your real
positions (FIFO cost basis), fetches live/historical prices, computes
value/gain/XIRR/drawdown/sector concentration/movers, and writes a daily
markdown report with news research on every holding - all deterministic
Python for the numbers, an LLM only for the prose and research on top.

See [`docs/SETUP.md`](docs/SETUP.md) for the full description and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it's built.
