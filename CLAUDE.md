# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Address the user as "Developer" in this project.**

## What this is

One project: a portfolio price-tracking and analysis pipeline, packaged as a
single MCP server (`portfolio/portfolio_mcp/`) registered **globally** via
`bootstrap.sh` - not project-scoped. All computation is deterministic Python
(`portfolio_mcp/pipeline/`, a subpackage of the server itself); Claude's role
is orchestration, news research, and prose - it never computes a number
itself. The server is reached over HTTP (`streamable-http`, localhost-only)
and is the only sanctioned way to invoke this pipeline day to day.

This repo has four clearly separated parts - know which one you're in before
editing:

| Part | Where | For |
|---|---|---|
| The Claude Skill | [`skills/portfolio/`](skills/portfolio/SKILL.md) | An agent *using* the deployed pipeline, in any project. Self-contained - deliberately not under `.claude/`, so it doesn't also trigger as a project skill while you develop here. |
| Agent-dev rules | [`docs/AGENT_NOTES.md`](docs/AGENT_NOTES.md) | Rules and hard-won lessons for anyone (agent or human) modifying code in this repo. **Read before touching any pipeline module.** |
| Architecture | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system actually works - data flow, file map, MCP tools, methodology (currency handling, FIFO, XIRR, config schema). |
| Human setup | [`README.md`](README.md) / [`docs/SETUP.md`](docs/SETUP.md) / [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Cloning, running `bootstrap.sh`, getting a Finnhub key, or running the pipeline with no LLM at all. |

**First run?** If `upload_transactions` hasn't been called yet (no
`portfolio_mcp/data/manual/transactions.csv`), this is a fresh setup with no
personal data yet - follow `skills/portfolio/references/BOOTSTRAP.md` (the
same flow the skill uses when triggered fresh in any project). Don't assume
default/example data; there is none by design (see `.gitignore`).

**Read [`docs/AGENT_NOTES.md`](docs/AGENT_NOTES.md) before making ANY change
to the pipeline.** It's the consolidated rule set for developing here - every
non-obvious behavior, past bug, and design decision - so you never have to
reverse-engineer the "why" from source. It also explains why
`skills/portfolio/SKILL.md`'s behavioral rules (never guess a ticker, never
hand-recompute a number, etc.) apply here too even though the skill itself
won't auto-trigger in this repo.

## Commands

**Setup / (re)deployment** - `bootstrap.sh` (repo root) does all of this,
idempotently:
```bash
./bootstrap.sh
```
It creates `portfolio/portfolio_mcp/.venv` (needs Python >=3.10 - it
searches python3.10 through python3.13), starts the server in the
background (`portfolio_mcp/.server.pid`/`.server.log`), registers it with
`claude mcp add --scope user --transport http`, and copies
`skills/portfolio/` to `~/.claude/skills/portfolio/`. Re-run it any time
(after a reboot, a `requirements.txt` change, or after editing anything
under `skills/portfolio/`) - every step is skip-if-already-done except the
MCP registration and the skill copy, which are always replaced cleanly. See
[`docs/SETUP.md`](docs/SETUP.md) for the full human-facing walkthrough.

**Day to day**: everything goes through the `portfolio` MCP tools
(`upload_transactions`, `compute_lots`, `resolve_tickers`, `fetch_prices`,
`backfill_history`, `analyze_portfolio`, `render_report`) - never Bash, never
a standalone script. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)'s MCP
tools table for what each wraps.

**Direct module invocation** (debugging only, not the primary interface):
```bash
cd portfolio
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.lots
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.analysis | portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.report
```
See [`docs/QUICKSTART.md`](docs/QUICKSTART.md) for the full manual workflow.

**No automated test suite.** Verify a change by calling the affected tool
(or running its module directly) and inspecting the output; for anything
touching `analyze_portfolio`/`render_report`, diff the JSON/markdown against
a known-good run rather than eyeballing it.

## Where things live

**One package, no code outside it - `portfolio/portfolio_mcp/`:**
`server.py` (FastMCP, HTTP-only, wraps every tool in a lock), `pipeline/`
(the deterministic computation - `lots.py`, `tickers.py`, `prices.py`,
`backfill.py`, `analysis.py`, `report.py`, `config.py`, `uploads.py`),
`paths.py` (single source of truth for every path, never cwd-relative),
`data/` (everything the pipeline reads/writes). Full breakdown in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**`skills/portfolio/`** is the Claude Skill source - `SKILL.md` + a
self-contained `references/` bundle (including `references/tasks/*.md`, the
actual instructions the two scheduled tasks follow). `bootstrap.sh` copies
it wholesale to `~/.claude/skills/portfolio/`. See
[`docs/AGENT_NOTES.md`](docs/AGENT_NOTES.md)'s "Skill bundle vs. this repo"
before editing anything under it - it must stay self-contained (no
references out to `docs/`).

**`docs/`** - everything for developing in and understanding this repo:
`AGENT_NOTES.md` (rules/lessons), `ARCHITECTURE.md` (how it works),
`SETUP.md` (human bootstrap walkthrough), `QUICKSTART.md` (manual, no-LLM
workflow). There is no separate local memory system for this project -
anything durable enough to matter belongs in one of these docs (or the skill
bundle), not in a `.claude/memory/` file that only this machine sees.
