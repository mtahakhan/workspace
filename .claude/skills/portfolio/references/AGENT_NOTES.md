# Agent Notes - read this before touching any code

This file exists so you never have to read the Python source to understand
*why* this pipeline works the way it does, or what's already been tried and
failed. Code comments explain local, line-level logic; this file explains
system-level rules, past bugs, and design decisions. If you're about to change
behavior, extend the pipeline, or debug something that looks wrong, read this
first - the answer is very likely already written down here.

**Giving investment analysis or advice from this data (chat questions, the
daily report's Executive Summary/Holdings News Digest, or any explicit
mode)?** Read **`INVESTMENT_FRAMEWORK.md`** first - it's the analysis/advisory
layer on top of this pipeline's numbers, kept separate from this file because
it governs interpretation and opinions, not data mechanics.

## Absolute rules (do these, always)

1. **Never guess a ticker symbol.** Call the `resolve_tickers` MCP tool for
   any new ISIN - it does a real `yfinance` search and checks actual
   currency/price. Freehand ticker guessing has a confirmed 0% success rate
   in this project: a bootstrap run by a smaller model guessed 7 tickers and
   got all 7 wrong (see "Ticker resolution" below for the specific failures).
   A wrong ticker doesn't error - it silently prices an unrelated company.
2. **Never recompute `analyze_portfolio`'s numbers by hand.** If a number
   looks wrong, that's a bug to fix in the pipeline module, not something to
   override by reasoning over the raw data yourself.
3. **Never modify any deterministic pipeline module**
   (`portfolio_mcp/pipeline/lots.py`, `prices.py`, `backfill.py`,
   `analysis.py`, `tickers.py`, `report.py`, `config.py`, `uploads.py`, or
   `portfolio_mcp/server.py`/`lock.py`/`paths.py`) **without first confirming
   intent with the user.** If something looks wrong or errors, the default
   action is to **report it** - what happened, why it might be happening, and
   2-3 concrete options for how to debug or fix it - and stop there. Only
   edit the code once the user has confirmed they want a change made and
   roughly how. This applies doubly during an unattended scheduled-task run
   (`portfolio-price-fetch`, `portfolio-daily-analysis`): there's no one
   present to confirm intent, so an error there gets reported (in the report
   / via notification) and left alone, never silently patched. `config.json`
   is the deliberate exception - tuning a threshold or caveat wording there
   is a config change, not a code change, and doesn't need this same
   confirm-first treatment (see "Configurable thresholds and caveats" below)
   - but a `config.json` edit that breaks JSON parsing or drops a template
   placeholder still surfaces as a hard error per rule 3's spirit, not a
   silent fallback.
4. **Never write ad-hoc currency-conversion code.** The pipeline supports
   EUR, USD, GBP, and GBp (British pence, /100 to GBP). If you hit another
   currency, that's a sign the ticker/listing is wrong - resolve a different
   listing via the `resolve_tickers` tool, don't add a new conversion path.
   (This already happened once: a bootstrap picked a London `.L` listing
   quoted in GBp and invented one-off GBP conversion code instead of
   recognizing the real fix was a different, EUR-native listing. GBp support
   is now built into `pipeline/prices.py`/`pipeline/backfill.py` permanently,
   so this specific gap shouldn't recur - but the general principle holds for
   any future unsupported currency.)
5. **Never ask the user to paste an API key into chat, and never ask them to
   paste `transactions.csv` into chat either now that `upload_transactions`
   exists** - call that tool with the CSV content instead, so the raw
   financial data still doesn't have to sit in the conversation transcript
   any longer than the single tool call. For the Finnhub key specifically:
   copy `.env.example` to `.env` (inside `portfolio_mcp/`, wherever the
   server is actually running - see "Deployment model" below) and have the
   user fill it in themselves in their editor. Only check for the *absence*
   of the placeholder text - never read/print the real key.
6. **Never do a *serial* web-search across every position** during daily
   analysis - dispatch all per-ticker searches as one parallel batch instead.
   A prior version of this pipeline timed out (600s, no output) doing a full
   per-ticker deep-dive on all 23 holdings *serially*; the failure was the
   serial execution, not the full coverage, so full-portfolio news research
   is fine as long as it's batched in parallel (see `tasks/daily-analysis.md`'s
   Holdings News Digest step). Deeper research (multi-query, iterative) still
   stays scoped to the flagged `movers` or an explicitly-invoked mode - see
   `INVESTMENT_FRAMEWORK.md`'s "Research scope".
7. **Edit the source repo's `portfolio/tasks/*.md` to change scheduled-task
   behavior, not the schedule itself.** The schedule's prompt is just a
   one-line pointer to that file - the real instructions live there, not in
   this reference copy's own `tasks/*.md` (which is read-only documentation
   of what they do - see SKILL.md's "Reading vs. editing"). If you don't
   know the source repo's location, ask the user rather than guessing.
8. **Keep `PIPELINE.md`'s Mermaid diagram in sync.** Any change to
   a module's inputs/outputs, the run order, a data file, or a scheduled
   task - in this file's "Pipeline components" table, `README.md`'s "Data
   pipeline" section, or the actual code - must land alongside a matching
   edit to the diagram in the same change. Same principle as the table below:
   an out-of-date diagram is worse than no diagram.

## Deployment model - read this before assuming anything about paths or "the project"

This is **not** a project-scoped tool. `bootstrap.sh` (repo root) registers
the `portfolio` MCP server and Claude Skill **globally** (`claude mcp add
--scope user`, plus copying `.claude/skills/portfolio/` to
`~/.claude/skills/portfolio/`) - the server is a single long-running HTTP
process (`portfolio_mcp/server.py`, `mcp.run(transport="streamable-http")`,
bound to `127.0.0.1` only) that every Claude Code session on the machine
talks to, in every project, not just this repo. There is no
`${CLAUDE_PROJECT_DIR}`-relative anything left in this codebase - every path
is computed from `portfolio_mcp/paths.py`'s `PACKAGE_ROOT =
Path(__file__).resolve().parent`, i.e. relative to wherever this package's
own source happens to live on disk, never from cwd or "the current project."
**Concretely: if you're working in some unrelated project and the `portfolio`
MCP tools are available, they still operate on this one repo's data** - that
is by design, not a bug.

Because it's one shared server reachable from potentially-concurrent
sessions/projects, `portfolio_mcp/server.py` wraps **every** tool call in a
single `fcntl.flock`-based lock (`portfolio_mcp/lock.py`,
`data/.pipeline.lock`) before it touches anything under `data/` - see that
file's docstring for why a single global lock beats per-file locks here.
Never add a new tool that touches `data/` without routing it through that
same lock (`server.py`'s `_locked` helper).

There's no file upload path assumed between whoever's talking to the server
and wherever the server is running (could be a different machine entirely,
in principle) - `transactions.csv` arrives via the `upload_transactions` tool
(raw CSV text as a string argument), not by the user placing a file at a
path. `portfolio_mcp/pipeline/uploads.py` validates the header against the
expected Scalable Capital column set before saving (rejects garbage rather
than silently accepting a wrong-format paste), and keeps one `.bak` of
whatever was there before.

## File map (what reads/writes what)

See **`PIPELINE.md`** for the diagram (Mermaid, kept up to date per rule 8
above) - not duplicated here so there's exactly one diagram to keep in sync,
not two that can silently drift apart.

**Run order matters**: `compute_lots` runs FIRST (it works fine even with an
empty/missing `data/ticker_map.csv` - just leaves `Ticker`/`Sector` blank),
THEN `resolve_tickers` (reads `data/transaction_lots.csv`'s blank-`Ticker`
rows - which is why it needs an `ISIN` column - to resolve and append to
`data/ticker_map.csv`), THEN re-run `compute_lots` to pick up the resolved
tickers. `resolve_tickers` deliberately does NOT re-run the FIFO engine
itself - it reads the ISIN+blank-Ticker rows straight from
`data/transaction_lots.csv`, which is already exactly that computation's
output. (All paths in this section are relative to `portfolio_mcp/`.)

`data/ticker_map.csv` is the ONLY file resolved by `resolve_tickers` and the
only manually-maintained input besides `data/manual/transactions.csv`
itself. It's shared/committed (not personal data - a factual ISIN->ticker
mapping is the same for everyone), and append-only in practice: once an ISIN
is resolved correctly, that entry should never need to change.

## Pipeline components (KEEP THIS TABLE UP TO DATE)

Whenever a module, tool, or file's role changes, update this table in the
same change - it's the authoritative inventory and must never drift from
reality.

**Code layout: everything lives inside `portfolio/portfolio_mcp/` - one
package, no code outside it.** The pipeline is a subpackage of the server,
not a sibling project:

```
portfolio/
  portfolio_mcp/            <- the whole distributable unit
    server.py                  FastMCP server, HTTP-only, the locking wrapper
    lock.py                    fcntl.flock-based cross-request/cross-process lock
    paths.py                   PACKAGE_ROOT/DATA_DIR/CONFIG_FILE/ENV_FILE - single source of truth
    config.json, .env          config/secrets, not data
    pipeline/                  the deterministic computation, unchanged in substance
      lots.py, tickers.py, prices.py, backfill.py, analysis.py, report.py, config.py, uploads.py
    data/                      internal default location - see "Deployment model" above
      manual/transactions.csv, ticker_map.csv, transaction_lots.csv,
      price_history/*.jsonl, analysis_history.jsonl, news/, daily-analysis/
    requirements.txt, .venv/   one venv for the whole package (needs Python >=3.10)
  bootstrap.sh                 (repo root, not here) - global registration
```

Named `portfolio_mcp`, not `mcp`, specifically so it never collides with the
third-party `mcp` SDK package this server imports
(`from mcp.server.fastmcp import FastMCP`) - a same-named local package would
shadow or be shadowed by that import depending on sys.path order. Don't
rename it back to `mcp` for "clarity" - that's the one name it can't have.

Every pipeline module still has its own `if __name__ == "__main__":` and can
be run directly (`portfolio_mcp/.venv/bin/python3 -m
portfolio_mcp.pipeline.<name>`, from inside `portfolio/`) for local
debugging, but **the sanctioned interface is the MCP tools, over HTTP** - see
"Deployment model" above. Don't design any new feature around direct module
invocation being the primary path.

**Data files** (paths relative to `portfolio_mcp/`):

| File | Holds | Produced by |
|---|---|---|
| `data/manual/transactions.csv` | Raw broker export - the only external input | `upload_transactions` tool (keeps one `.bak`) |
| `data/ticker_map.csv` | ISIN, Ticker, Company, Sector - shared, committed | `resolve_tickers` (Ticker/Company) + you (Sector) |
| `config.json` | All tunable thresholds (stale-price age, mover/divergence %, split-sanity ratio, short-hold days, top-N counts) and every caveat/notify-reason message template - shared, committed, not personal data. Edit values here, not in code - see "Configurable thresholds and caveats" below | You (hand-edited); `pipeline/config.py` just loads it |
| `data/transaction_lots.csv` | Current open positions - FIFO lots, real dates/prices | `compute_lots` |
| `data/price_history/{TICKER}.jsonl` | Full sourced price history, one file per ticker | `fetch_prices` (daily) / `backfill_history` (one-off) |
| `data/analysis_history.jsonl` | One line per `analyze_portfolio` run: `generated_at`, `total_value`, `xirr_pct` - append-only, used only for the run-over-run divergence check | `analyze_portfolio` |
| `data/daily-analysis/*.md` | Generated reports | `portfolio-daily-analysis` task |
| `data/news/{TICKER}/*.txt` | One file per fetched news source deemed meaningful (metadata header + fetched text) - see `INVESTMENT_FRAMEWORK.md` | `portfolio-daily-analysis` task + any ad-hoc analysis that fetches news |

**MCP tools (`portfolio_mcp/server.py`) - all deterministic, zero LLM
involvement in the computation itself, all serialized through the global
lock:**

| Tool | Wraps | Uses | Produces | Run order |
|---|---|---|---|---|
| `upload_transactions` | `pipeline/uploads.py` | Raw CSV text (tool argument) | `data/manual/transactions.csv` (+ `.bak` of previous) | whenever the user has a new export |
| `compute_lots` | `pipeline/lots.py` | `data/manual/transactions.csv` + `data/ticker_map.csv` | `data/transaction_lots.csv` | 1st (works even if ticker_map.csv is empty/missing) |
| `resolve_tickers` | `pipeline/tickers.py` | `data/transaction_lots.csv` (blank-Ticker rows, by ISIN) + `yfinance` search/currency/history checks | Appends rows to `data/ticker_map.csv` (Sector blank) | 2nd, only when needed |
| `compute_lots` (re-run) | same | same | fresh `data/transaction_lots.csv` with resolved tickers | 3rd, after resolve_tickers |
| `fetch_prices` | `pipeline/prices.py` | `data/transaction_lots.csv` + Finnhub/yfinance | Appends to `data/price_history/*.jsonl` | daily |
| `backfill_history` | `pipeline/backfill.py` | `data/transaction_lots.csv` + yfinance historical | Rewrites `data/price_history/*.jsonl` (full history) | one-off/rare |
| `analyze_portfolio` | `pipeline/analysis.py` (+ `pipeline/config.py`) | `data/transaction_lots.csv` + `data/price_history/*.jsonl` + last line of `data/analysis_history.jsonl` + `config.json` (thresholds/caveat templates) | JSON: value, gain/loss, drawdown, XIRR, movers, trend, `stale_prices`, `caveats` (incl. value-divergence check), `notable`/`notify_reasons` (deterministic push-notification signal - see below); appends a new line to `data/analysis_history.jsonl` | after fetch_prices |
| `render_report` | `pipeline/report.py` | `analyze_portfolio`'s JSON (passed as the `analysis` argument) + `config.json` (`short_hold_days_threshold`) | Markdown: Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers (numbers only), Complete Holdings Table, XIRR Context, Data Notes | after analyze_portfolio, before the report is written |

**Scheduled tasks - thin LLM wrappers around the deterministic core:**

| Task | Does | Deterministic or LLM? |
|---|---|---|
| `portfolio-price-fetch` (~07:11 Berlin) | Calls `fetch_prices`, reports one line | Almost entirely deterministic - LLM just calls the tool and reports |
| `portfolio-daily-analysis` (~07:25 Berlin) | Calls `analyze_portfolio` then `render_report`, WebSearches the flagged `movers` (deeper context) and all other holdings (one-line news digest) in a single parallel batch, writes an Executive Summary, and prepends it to the rendered markdown | Hybrid - every number/table comes untouched from `render_report`; LLM only adds the Executive Summary and news-research prose, never hand-transcribes a figure |

Both tasks' real instructions live in the source repo's `portfolio/tasks/*.md`,
not the schedule itself (this file's own `tasks/*.md` sibling is a read-only
copy for reference - see SKILL.md's "Reading vs. editing").

**Reference/instruction files (not executed):** `AGENT_NOTES.md` (this file),
`README.md` (human+agent overview), `PIPELINE.md` (Mermaid diagram of the
whole pipeline - keep in sync, see rule 8 above), `BOOTSTRAP.md` (first-run
setup, now upload-tool-driven - see that file), `QUICKSTART.md`
(direct-module debugging reference, not the primary usage path anymore),
`CLAUDE.md` (workspace-root auto-loaded entry point), `INVESTMENT_FRAMEWORK.md`
(analysis/advisory layer - modes, signals, portfolio/risk rules - used once
pipeline output already exists; never touches the pipeline itself),
`.claude/skills/portfolio/SKILL.md` (packages this file's absolute rules +
the MCP tool mapping so they're loaded automatically for portfolio-related
requests, without duplicating this content - see that file), `bootstrap.sh`
(repo root - global registration, see "Deployment model" above).

## Ticker resolution - what already went wrong once

A bootstrap run by a smaller model (Haiku) guessed tickers instead of
calling `resolve_tickers`. All 7 of its guesses were wrong:

| ISIN (company) | Guessed | Reality |
|---|---|---|
| CA13321L1085 (Cameco) | `CCO` ($2.41, wrong company) | `CCJ` ($87) |
| DE0005557508 (Deutsche Telekom) | `DTE` | DTE Energy Co (unrelated US utility) |
| DE000A3DSV01 (Cantourage) | `HIGH` | wrong company entirely |
| GB0009895292 (AstraZeneca) | `AZN.L` (777 GBp) | works, but forced ad-hoc GBP code that didn't exist yet |
| IE00B1XNHC34 (iShares Clean Energy) | `INRG.L` (GBp) | `IQQH.DE` (EUR-native, same fund) |
| IE00B3WJKG14 (iShares S&P500 Tech) | `IITU.L` (GBp) | `QDVE.DE` (EUR-native, same fund) |
| IE000I8KRLL9 (iShares Semis) | `SEMI` | `SEC0.DE` (EUR-native) |

Same underlying lesson twice: (1) a bare/shorthand ticker frequently collides
with an unrelated company on a different exchange, and (2) even when a
guessed listing "works" (returns a price), it may be on a worse exchange
(wrong currency, needs an FX hop) when a EUR-native listing of the exact same
security exists. `resolve_tickers` now checks currency and ranks EUR-native
listings first specifically because of this.

Historical bugs from earlier in this project's life (before `resolve_tickers`
existed) with the same root cause: `CAN`->Canaan Inc instead of Cantourage
Group, `IRE`->a leveraged Iren SpA ETF instead of IREN Ltd.

**2026-07-24: the above bugs reached a published report.** An 11:03 run of
`portfolio-daily-analysis` used the still-bad `ticker_map.csv` and reported
€32,568.97 (+64.4%) - built on fictitious/wrong tickers (`IXSK`, `XLK`
outright didn't exist in the portfolio; gold read as `EGLD`; `CAN`/`IRE` as
above). The mapping was fixed later that day and a re-run at 17:34 produced
the real number, €16,113.58 (-3.53%, XIRR -12.64%) - roughly half the
reported value. Nothing in the pipeline had flagged the first number as
suspicious even though a portfolio doubling in hours is implausible. Fix:
`analyze_portfolio` now records each run's `total_value` to
`data/analysis_history.jsonl` and adds a `caveats` entry
(`check_value_divergence`) if it moved >20% since the previous run - treat
that caveat as "investigate before publishing," not as a real market move.

## Currency handling

Supported: **EUR** (no conversion), **USD**, **GBP**, **GBp** (British pence -
divided by 100 to GBP before applying the EUR/GBP rate). Anything else is
rejected (returns `None`/skipped), not silently mispriced - this is
intentional. `price_eur` is the one field every downstream module reads;
never read `price_original_currency` for computation, only for display/audit.

`pipeline/prices.py` (live) and `pipeline/backfill.py` (historical) each
implement this independently but must stay in sync - if you add a currency
to one, add it to the other. Historical FX rates are used for backfill (not
today's rate applied retroactively) - each FX pair's series only goes back so
far (e.g. EUR/USD data starts 2003-12-01, since the Euro didn't exist before
1999), so older ticker history is truncated rather than priced with a
fabricated rate.

## FIFO / transaction parsing rules (pipeline/lots.py)

- Sort transactions by full **date+time**, not date alone. A previous version
  sorted by date only; since the broker export lists transactions newest-first,
  same-day trades tied on the sort key and fell back to file order (which is
  backwards - latest-time-first). This caused a real phantom-lot bug: a sell
  at 08:46 got processed before that same morning's buy at 08:23, an hour out
  of sequence, fabricating an extra share of history that didn't exist.
- `"Security transfer"` transaction rows are a broker/account migration
  artifact (e.g. this project's Dec 2025 Scalable Capital migration: a
  same-ISIN withdrawal immediately followed by a deposit of the identical
  quantity). Verified to net to exactly zero per ISIN, then excluded entirely
  so original purchase dates survive the migration instead of resetting.
- `"Corporate action"` rows can represent a reverse split/ISIN change (e.g.
  this project's WisdomTree Brent Crude Oil 3x Daily Short ISIN swap). Handle
  by carrying the old ISIN's total cost basis and weighted-average purchase
  date onto the new ISIN - it's a continuation, not a disposal + new purchase.

## Historical price data quality

`pipeline/analysis.py` drops historical price points that are more than 100x
away from a ticker's current price (`SPLIT_ADJUSTMENT_SANITY_RATIO`). This
guards against a real, confirmed data bug: `yfinance`'s historical data for
some thinly-traded/leveraged ETPs isn't retroactively adjusted for later
reverse splits. A 3x daily leveraged short-oil ETC in this project showed
~€220,000 in Jan 2016 (a real historical price level before later reverse
splits) vs ~€14.50 today - both numbers are "real" in isolation, but not on
the same split-adjusted share-count basis, so multiplying by today's share
count silently corrupted any EUR-value computation. 100x is deliberately
generous so it never triggers on ordinary volatility.

**Known performance issue (not yet fixed, unrelated to the HTTP/locking
work):** `compute_portfolio_value_series`/`price_at_or_before` in
`pipeline/analysis.py` does a linear scan per (date × position) pair to build
the full-history value series that drawdown/trend use - O(dates × positions
× history length). Observed taking ~20-25s of real CPU time against this
portfolio's ~22 tickers (some with 5,000+ history points from
`backfill_history`'s `period="max"`), with much higher wall-clock time in at
least one sandboxed test environment (low CPU%, consistent with I/O wait) -
unclear whether that wall-clock gap reproduces on a normal machine. Worth
optimizing (e.g. binary search instead of linear scan, since each ticker's
history is already sorted) if it becomes a real problem, but that's a
separate change from anything in this file's "Deployment model" section -
don't conflate the two if you're debugging a slow `analyze_portfolio` call.

## Trend vs. drawdown: two different, deliberately different methodologies

- **`drawdown`/high-water-mark** uses the FULL available price history for
  every ticker, multiplied by TODAY's share count - a synthetic "what if I'd
  held this exact portfolio further back" calculation. This is intentional
  and already agreed on: it answers "what's the worst-case value swing of my
  current holdings," not a claim about the portfolio's real historical value.
- **`trend.since_inception`** is anchored to the EARLIEST actual purchase date
  in `data/transaction_lots.csv`, NOT the earliest available price-history point.
  Using full history here was tried and produced a real, confirmed bug: it
  showed **+57,000%** using a Siemens price from 1996, because the portfolio
  (in its current form) didn't exist until 2024. Don't "fix" this back to
  using full history - the discrepancy between these two methodologies is the
  point, not an inconsistency to resolve.

## Annualized return (XIRR)

`annualized_returns` is a real money-weighted XIRR computed from
`data/transaction_lots.csv`'s actual purchase dates/prices - not `total_return /
years_held`. Check `weighted_avg_holding_days` before treating any single
position's XIRR as meaningful: annualizing a short real holding period
produces mathematically extreme numbers (e.g. a genuine 37% gain over 12
weeks annualizes to 300%+). That's correct math, not a bug, but it's easy to
misread without the holding-period context alongside it. No position needs to
have been held a full year for the *portfolio-wide* XIRR to be meaningful.

## Notification signal (notable/notify_reasons)

Whether the daily task sends a push notification is a fixed rule evaluated by
`analyze_portfolio`, not a judgment call made fresh each run - see
`tasks/daily-analysis.md` step 8. `notable` is `true` if any of: a mover's
`|change_pct|` is >= `config.json`'s `thresholds.mover_notable_pct` (5% by
default, percentage move, not EUR size - consistent with how `compute_movers`
itself ranks movers), `stale_prices` is non-empty, or the value-divergence
check fired. `notify_reasons` lists which, rendered from
`config.json`'s `notify_reasons` templates. This replaced an earlier version
of the task that left "large move" undefined and included "target breached" -
that phrase never corresponded to any tracked data (no price-target field
exists anywhere in this pipeline) and was removed rather than implemented; revisit if
per-position price targets are ever actually added as a feature.

## Configurable thresholds and caveats (config.json)

Every numeric threshold and every caveat/notify-reason message string used by
`pipeline/analysis.py` and `pipeline/report.py` lives in `config.json`, not
hardcoded in the modules - `stale_price_max_age_days`, `mover_notable_pct`,
`value_divergence_pct`, `split_adjustment_sanity_ratio`, `full_year_holding_days`,
`short_hold_days_threshold`, `movers_top_n`, `largest_positions_top_n` under
`thresholds`; the boilerplate methodology notes plus the templated
tickers-without-lot-data/stale-prices/short-holding/value-divergence messages
under `caveats`; the three notification message templates under
`notify_reasons`. To change a number or wording, edit `config.json` directly -
no code change needed, and it takes effect on the next call to either tool
(the server reads the file fresh every call - no caching to invalidate).

`pipeline/config.py` is a thin shared loader (`load_config()`), imported by
both `analysis.py` and `report.py` - it does NOT duplicate `config.json`'s
values as Python defaults. That's deliberate: this project already has one
instance of "two copies of the same information silently drifting apart"
(the Mermaid diagram, rule 8 above) and the fix there was "exactly one place
to keep in sync." Baking a second, hardcoded set of defaults into
`pipeline/config.py` would recreate that same failure mode for thresholds
instead. So a missing or invalid `config.json` is a hard error (`SystemExit`
with a clear message), not a silent fallback - consistent with rule 3's
"report it and stop" for unattended runs. `config.json` is committed
(shared/non-personal, like `data/ticker_map.csv`), so "missing" should only
happen from local file damage, never a fresh clone.

Message templates use Python `str.format()` placeholders (e.g. `{tickers}`,
`{max_age_days}`, `{change_pct:+.1f}`) - if you edit a template's wording,
keep its placeholder names intact or the corresponding `.format(...)` call in
`analyze_portfolio`'s `main()` will raise a `KeyError`.

## Data provenance / secrets

Every `data/price_history/{TICKER}.jsonl` record for a non-EUR ticker carries its
original currency, raw price, exact source URL (API token redacted before
persisting), and the FX rate + source used. EUR-native records omit all of
this (would just be no-op restatements). Never persist an API token/secret
into any output file, ever.
