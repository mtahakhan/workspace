---
name: portfolio
description: Use for anything about the user's Scalable Capital investment portfolio - checking holdings/value, running the daily price-fetch or analysis pipeline, questions about a specific held ticker, rebalancing, XIRR/performance, sector exposure, or giving buy/hold/trim/exit opinions. Also use when a new trade needs to be recorded, a new ISIN needs a ticker resolved, or a deterministic pipeline script errors and needs debugging.
---

# Portfolio pipeline

`portfolio/` is a deterministic portfolio tracker + analysis pipeline (FIFO
cost basis from real broker transactions, live/historical prices, XIRR,
drawdown, sector concentration) plus an LLM-driven daily report on top of it.
Full detail lives in the docs below - this file is a thin pointer + the rules
that apply on every invocation, not a copy of that content (don't fork it -
see `AGENT_NOTES.md` rule 8 on keeping exactly one copy of anything in sync).

**Read first, depending on what's being asked:**
- `portfolio/README.md` - what the pipeline does, file map, troubleshooting
- `portfolio/AGENT_NOTES.md` - **read before changing or debugging any script** - absolute rules, every past bug and why, config.json
- `portfolio/INVESTMENT_FRAMEWORK.md` - **read before giving analysis/advice** (chat questions, Executive Summary, scoring, rebalancing) - modes, signals, portfolio/risk rules
- `portfolio/PIPELINE.md` - Mermaid diagram of the whole data flow
- `portfolio/BOOTSTRAP.md` - **follow this instead of everything else** if `portfolio/data/manual/transactions.csv` doesn't exist yet (fresh clone)
- `portfolio/tasks/*.md` - the actual instructions for the two daily scheduled tasks

## Use the `portfolio` MCP server, not Bash, for every deterministic step

| Need to... | Call this MCP tool | Wraps |
|---|---|---|
| Rebuild positions after a new trade | `compute_lots` | `compute_lots.py` |
| Resolve a new ISIN to a real ticker | `resolve_tickers` | `scaffold_metadata.py` |
| Fetch today's live prices | `fetch_prices` | `fetch_prices.py` |
| Backfill full price history (rare/one-off) | `backfill_history` | `backfill_history.py` |
| Compute portfolio value/gain/XIRR/movers/etc. | `analyze_portfolio` | `analyze_portfolio.py` |
| Render that JSON as report markdown | `render_report` | `render_report.py` |

These tools call the exact same functions the CLI scripts use - same
computation, same output, just typed instead of Bash+stdout parsing. The
scripts are still fully standalone-runnable (`portfolio/QUICKSTART.md`); the
MCP server doesn't replace them, it's just how this skill should invoke them.

Standard daily flow: `fetch_prices` → `analyze_portfolio` → `render_report`
(pass `render_report` the exact dict `analyze_portfolio` returned) → then
research news and write the Executive Summary yourself - see
`portfolio/tasks/daily-analysis.md` for the full, current step-by-step.

## Absolute rules (apply every time, not just when debugging)

1. **Never guess a ticker symbol.** Always call `resolve_tickers` for a new
   ISIN. A bootstrap run that guessed instead got 7/7 wrong - see
   `AGENT_NOTES.md`'s "Ticker resolution" section for the specific failures.
2. **Never recompute `analyze_portfolio`'s numbers by hand**, and never
   hand-transcribe a figure out of its JSON into your own prose/tables -
   `render_report` renders every table. If a number looks wrong, that's a bug
   to report (see rule 3), not something to override by reasoning over raw
   data.
3. **Never modify a deterministic script** (`compute_lots.py`,
   `fetch_prices.py`, `backfill_history.py`, `analyze_portfolio.py`,
   `scaffold_metadata.py`, `render_report.py`, `config.py`, `mcp/server.py`)
   **without confirming intent with the user first.** Default action on an
   error: report what happened and 2-3 concrete options, then stop -
   especially during an unattended scheduled-task run, where there's no one
   to confirm with. `config.json` is the deliberate exception (a threshold
   tweak is a config change, not a code change).
4. **Never write ad-hoc currency-conversion code.** Supported: EUR, USD, GBP,
   GBp. Anything else means the ticker/listing is wrong - resolve a different
   listing via `resolve_tickers`, don't add a new conversion path.
5. **Never ask the user to paste an API key into chat.**
6. **Research news in one parallel batch, never a serial per-ticker loop** -
   a prior serial version timed out. Full-portfolio coverage is fine as long
   as it's dispatched in parallel.
7. Edit `portfolio/tasks/*.md` to change scheduled-task behavior, never the
   schedule itself - the schedule's prompt is just a pointer to the file.
