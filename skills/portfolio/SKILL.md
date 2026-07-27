---
name: portfolio
description: Use for anything about the user's Scalable Capital investment portfolio - checking holdings/value, running the daily price-fetch or analysis pipeline, questions about a specific held ticker, rebalancing, XIRR/performance, sector exposure, or giving buy/hold/trim/exit opinions. Also use when a new trade needs to be recorded (including uploading a fresh transactions export), a new ISIN needs a ticker resolved, or a deterministic pipeline module errors and needs debugging.
---

# Portfolio pipeline

A deterministic portfolio tracker + analysis pipeline (FIFO cost basis from
real broker transactions, live/historical prices, XIRR, drawdown, sector
concentration) plus an LLM-driven daily report on top of it, reachable via
the `portfolio` MCP server - registered globally, so these tools may show up
in any project, not just one specific workspace. **They always operate on
the same one portfolio's data regardless of which project you're in** - that
is deliberate, not a bug: the server is a single long-running process
reachable from every Claude Code session on this machine, not a per-project
tool.

Upload a broker transaction export (`upload_transactions`) and the pipeline
reconstructs real positions via FIFO, fetches live/historical prices
(Finnhub primary, yfinance backup), computes value/gain/XIRR/drawdown/sector
concentration/movers, and renders a daily markdown report - all deterministic
Python, never estimated or hand-computed by an LLM. **Currently only parses
Scalable Capital's transaction export format.**

**Read first, depending on what's being asked** - these are self-contained
copies bundled with this skill (`references/`), not links back to wherever
the source repo happens to be cloned, so they resolve the same way
regardless of which project triggered this skill:
- `references/INVESTMENT_FRAMEWORK.md` - **read before giving analysis/advice** (chat questions, Executive Summary, scoring, rebalancing) - modes, signals, portfolio/risk rules
- `references/BOOTSTRAP.md` - **follow this instead of everything else** if `upload_transactions` hasn't been called yet (fresh setup - no transaction data at all)
- `references/TROUBLESHOOTING.md` - missing/stale/wrong prices, wrong currency, server not responding
- `references/tasks/*.md` - what the two daily scheduled tasks do - **this is
  the actual operational file the schedule follows**, not a read-only copy
  (see "Reading vs. editing" below)

`references/INVESTMENT_FRAMEWORK.md`, `references/BOOTSTRAP.md`, and
`references/TROUBLESHOOTING.md` are kept in sync with the source repo by
re-running `bootstrap.sh` there - never hand-edit them from inside a
deployed skill copy. `references/tasks/*.md` is
the one exception: there is no separate source-repo copy of it - this
bundled file *is* the source of truth for scheduled-task behavior (see
below).

## Reading vs. editing

Most of the above is read-only reference material, safe to consult from any
project. **Modifying the actual system - a pipeline module or `config.json` -
always requires the source repo**, which is a specific fixed location on this
machine, not something that travels with the skill. If you don't already know
that path from earlier in the conversation, **ask the user** rather than
guessing or searching for it - don't assume the current project is that repo
just because this skill triggered.

`references/tasks/*.md` is the one exception: it's edited in place, right
here in the skill bundle (in the source repo at
`skills/portfolio/references/tasks/*.md`, then re-deployed via
`bootstrap.sh`) - see rule 7 below.

## Use the `portfolio` MCP tools for every deterministic step - never Bash, never guess

| Need to... | Call this MCP tool | Wraps |
|---|---|---|
| Record a new/updated transaction history | `upload_transactions` | `pipeline/uploads.py` |
| Rebuild positions after a new trade | `compute_lots` | `pipeline/lots.py` |
| Resolve a new ISIN to a real ticker | `resolve_tickers` | `pipeline/tickers.py` |
| Fetch today's live prices | `fetch_prices` | `pipeline/prices.py` |
| Backfill full price history (rare/one-off) | `backfill_history` | `pipeline/backfill.py` |
| Compute portfolio value/gain/XIRR/movers/etc. | `analyze_portfolio` | `pipeline/analysis.py` |
| Render that JSON as report markdown | `render_report` | `pipeline/report.py` |
| Persist a news source you fetched | `save_news_source` | `pipeline/storage.py` |
| Save today's finished report | `save_report` | `pipeline/storage.py` |
| Read a past report / list report dates | `get_report` / `list_reports` | `pipeline/storage.py` |
| See or read already-stored news | `list_news` / `get_news_source` | `pipeline/storage.py` |

These tools call the exact same functions direct module invocation would -
same computation, same output, just typed and reachable over HTTP instead of
Bash+stdout parsing. There is no other supported way to run this pipeline
day to day; don't fall back to Bash if a tool call errors (see rule 3 below).

Standard daily flow: `fetch_prices` → `analyze_portfolio` → `render_report`
(pass `render_report` the exact dict `analyze_portfolio` returned) → then
research news and write the Executive Summary yourself - see
`references/tasks/daily-analysis.md` for the full, current step-by-step.

## Never touch the filesystem

**Every read and write of portfolio data goes through an MCP tool - including
the news sources and the report, which you author.** Don't use file tools,
don't use Bash, and don't try to work out where the data is: it lives outside
the server package, its location is configurable per machine
(`PORTFOLIO_DATA_DIR`), and it may not be inside any repo you can see. A path
that looks right in one project would be wrong or absent in another.

This is why `save_news_source`, `save_report`, `get_report`, `list_reports`,
`list_news` and `get_news_source` exist. They take content and facts, never
paths, and the server decides filenames, timestamps and metadata headers so
they stay identical across runs instead of depending on what you remembered
to type.

The one exception is this skill's own `references/tasks/*.md` (see rule 7) -
skill files, not portfolio data.

## Absolute rules (apply every time, not just when debugging)

1. **Never guess a ticker symbol.** Always call `resolve_tickers` for a new
   ISIN - it does a real `yfinance` search and checks actual currency/price.
   Freehand ticker guessing has a confirmed 0% success rate in this
   project's history (wrong companies entirely, or a correct company on the
   wrong exchange/currency) - a wrong ticker doesn't error, it silently
   prices an unrelated company.
2. **Never recompute `analyze_portfolio`'s numbers by hand**, and never
   hand-transcribe a figure out of its JSON into your own prose/tables -
   `render_report` renders every table. If a number looks wrong, that's a bug
   to report (see rule 3), not something to override by reasoning over raw
   data.
3. **Never modify a deterministic pipeline module**
   (`portfolio_tools/pipeline/lots.py`, `prices.py`, `backfill.py`,
   `analysis.py`, `tickers.py`, `report.py`, `config.py`, `uploads.py`, or
   `portfolio_tools/server.py`/`lock.py`/`paths.py`, all in the source repo -
   see "Reading vs. editing" above) **without confirming intent with the
   user first.** Default action on an error: report what happened and 2-3
   concrete options, then stop - especially during an unattended
   scheduled-task run, where there's no one to confirm with. `config.json`
   is the deliberate exception (a threshold tweak is a config change, not a
   code change).
4. **Never write ad-hoc currency-conversion code.** Supported: EUR, USD, GBP,
   GBp. Anything else means the ticker/listing is wrong - resolve a different
   listing via `resolve_tickers`, don't add a new conversion path.
5. **Never ask the user to paste an API key, or their transactions CSV,
   directly into chat as prose.** For a new/updated transaction history,
   call `upload_transactions` with the file content - that's what it's for,
   and it keeps the raw data out of the transcript as much as a tool call
   allows. For the Finnhub key, point them at `.env`/`.env.example` (in the
   source repo) instead.
6. **Research news in one parallel batch, never a serial per-ticker loop** -
   a prior serial version timed out. Full-portfolio coverage is fine as long
   as it's dispatched in parallel.
7. **Edit this skill's own `references/tasks/*.md` to change scheduled-task
   behavior, never the schedule itself** - the schedule's prompt is just a
   pointer to the skill, which points at this file. Edit it in the source
   repo (`skills/portfolio/references/tasks/*.md`) and re-run `bootstrap.sh`
   to redeploy - see "Reading vs. editing" above.
