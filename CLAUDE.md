# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Address the user as "Developer" in this project.**

## What this is

One project: a portfolio price-tracking and analysis pipeline, packaged as a
single MCP server (`portfolio/portfolio_mcp/`) registered **globally** via
`bootstrap.sh` - not project-scoped. All computation is deterministic Python
(`portfolio_mcp/pipeline/`, a subpackage of the server itself, not a sibling
project); Claude's role is orchestration, news research, and prose - it
never computes a number itself. The server is reached over HTTP
(`streamable-http`, localhost-only) and is the only sanctioned way to invoke
this pipeline day to day - see `.claude/skills/portfolio/references/AGENT_NOTES.md`'s "Deployment
model" before assuming anything about paths, "the project," or how to run
something.

**First run?** If `upload_transactions` hasn't been called yet (no
`portfolio_mcp/data/manual/transactions.csv`), this is a fresh setup with no
personal data yet - stop and follow `.claude/skills/portfolio/references/BOOTSTRAP.md` before doing
anything else. Don't assume default/example data; there is none by design
(see `.gitignore` - all personal data and secrets are excluded from this repo).

**Read `.claude/skills/portfolio/references/AGENT_NOTES.md` before making ANY change to the pipeline.**
It's the consolidated rule set - every non-obvious behavior, past bug, and
design decision - so you never have to reverse-engineer the "why" from
source. Code comments cover local logic only; system-level rules live there.

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
`.claude/skills/portfolio/` to `~/.claude/skills/portfolio/`. Re-run it any
time (after a reboot, a `requirements.txt` change, or just to confirm
everything's still wired up) - every step is skip-if-already-done except the
MCP registration, which is always replaced cleanly.

**Day to day**: everything goes through the `portfolio` MCP tools
(`upload_transactions`, `compute_lots`, `resolve_tickers`, `fetch_prices`,
`backfill_history`, `analyze_portfolio`, `render_report`) - never Bash, never
a standalone script (there isn't one). See `.claude/skills/portfolio/references/AGENT_NOTES.md`'s
pipeline components table for what each wraps.

**Direct module invocation** (debugging only, not the primary interface):
```bash
cd portfolio
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.lots
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.analysis | portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.report
```

**No automated test suite.** Verify a change by calling the affected tool
(or running its module directly) and inspecting the output; for anything
touching `analyze_portfolio`/`render_report`, diff the JSON/markdown against
a known-good run rather than eyeballing it - that's the pattern this
codebase has actually been validated with throughout its history.

## Architecture

**One package, no code outside it - `portfolio/portfolio_mcp/`:**
- `server.py` - FastMCP server, HTTP-only (`streamable-http`, bound to
  `127.0.0.1`), one typed tool per pipeline step. Wraps every tool call in a
  lock (`lock.py`, `fcntl.flock` on `data/.pipeline.lock`) since it's one
  long-running process potentially reached by concurrent
  sessions/projects - see "Deployment model" in `.claude/skills/portfolio/references/AGENT_NOTES.md` for why a
  single global lock, not per-file locks.
- `pipeline/` - the actual computation (`lots.py`, `tickers.py`,
  `prices.py`, `backfill.py`, `analysis.py`, `report.py`, `config.py`,
  `uploads.py`), nested inside the server package, not a sibling. Each
  module still has its own `main()` and is runnable directly for debugging.
- `paths.py` - single source of truth for every path (`PACKAGE_ROOT =
  Path(__file__).resolve().parent`, then `DATA_DIR`/`CONFIG_FILE`/
  `ENV_FILE`/`MANUAL_DIR` relative to that) - never cwd- or
  project-relative, since there's no "current project" for a globally
  registered server.
- `data/` - internal default location for everything the pipeline reads or
  writes; `data/manual/transactions.csv` arrives via the
  `upload_transactions` tool (raw CSV text as an argument), not by anyone
  placing a file there.

Named `portfolio_mcp`, not `mcp`, so it never collides with the third-party
`mcp` SDK package this server imports - don't rename it back.

`.claude/skills/portfolio/SKILL.md` is a thin pointer (triggers on
portfolio-related requests, lists the MCP tool mapping, restates
`.claude/skills/portfolio/references/AGENT_NOTES.md`'s absolute rules) - it does not fork any of that content,
and `bootstrap.sh` keeps a copy of it at `~/.claude/skills/portfolio/` in
sync with whatever's checked in here (re-run `bootstrap.sh` after editing
the skill).

**Data flow (see `.claude/skills/portfolio/references/PIPELINE.md` for the full Mermaid diagram):**
`upload_transactions` saves `data/manual/transactions.csv` (the one manual
input, raw broker export) → `compute_lots` FIFOs it into
`data/transaction_lots.csv` → any ISIN missing from `data/ticker_map.csv`
gets resolved by `resolve_tickers` (real `yfinance` search, **never a
guessed symbol** - a prior guess-based run got 7/7 wrong, see
`.claude/skills/portfolio/references/AGENT_NOTES.md`) → `fetch_prices` appends today's price to
`data/price_history/{TICKER}.jsonl` → `analyze_portfolio` computes
value/gain/XIRR/drawdown/movers/trend into JSON (also appending to
`data/analysis_history.jsonl` for its own run-over-run divergence check) →
`render_report` renders that JSON into markdown tables, verbatim, so the LLM
layer never hand-transcribes a figure.

`data/` holds everything the pipeline reads or writes; `config.json` (all
tunable thresholds and message templates) and `.env` (Finnhub key) stay at
the `portfolio_mcp/` root since they're config/secrets, not data.

**Scheduled orchestration:** two Claude Code scheduled tasks,
`portfolio-price-fetch` and `portfolio-daily-analysis`, whose real
instructions live in `portfolio/tasks/*.md` (the schedule itself is just a
one-line pointer to the file - edit the file, not the schedule, to change
behavior). The daily-analysis task is the only place that mixes deterministic
output with LLM work: it calls the MCP tools for every number, then
researches news for all holdings in one parallel batch (never serially - a
prior serial version timed out) and writes the Executive Summary, using
`.claude/skills/portfolio/references/INVESTMENT_FRAMEWORK.md` for framing/signal vocabulary.

## Memory for this project

Project-specific memory lives in **`.claude/memory/`** in this workspace, not
Claude's global memory location - read `.claude/memory/MEMORY.md` for the
index. This keeps anything specific to this project colocated, visible, and
portable with the workspace itself, rather than siloed in a global,
machine-tied path. Only genuinely general, cross-project facts about the user
(not specific to this project) belong in the global memory system - if in
doubt, put it here instead.
