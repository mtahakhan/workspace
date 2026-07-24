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

1. **Never guess a ticker symbol.** Run `scaffold_metadata.py` for any new
   ISIN - it does a real `yfinance` search and checks actual currency/price.
   Freehand ticker guessing has a confirmed 0% success rate in this project:
   a bootstrap run by a smaller model guessed 7 tickers and got all 7 wrong
   (see "Ticker resolution" below for the specific failures). A wrong ticker
   doesn't error - it silently prices an unrelated company.
2. **Never recompute `analyze_portfolio.py`'s numbers by hand.** If a number
   looks wrong, that's a bug to fix in the script, not something to
   override by reasoning over the raw data yourself.
3. **Never modify any deterministic script (`compute_lots.py`,
   `fetch_prices.py`, `backfill_history.py`, `analyze_portfolio.py`,
   `scaffold_metadata.py`) without first confirming intent with the user.**
   If something looks wrong or errors, the default action is to **report it**
   - what happened, why it might be happening, and 2-3 concrete options for
   how to debug or fix it - and stop there. Only edit the code once the user
   has confirmed they want a change made and roughly how. This applies
   doubly during an unattended scheduled-task run (`portfolio-price-fetch`,
   `portfolio-daily-analysis`): there's no one present to confirm intent, so
   an error there gets reported (in the report / via notification) and left
   alone, never silently patched.
4. **Never write ad-hoc currency-conversion code.** The pipeline supports
   EUR, USD, GBP, and GBp (British pence, /100 to GBP). If you hit another
   currency, that's a sign the ticker/listing is wrong - find a supported
   listing for that ISIN via `scaffold_metadata.py`, don't add a new
   conversion path. (This already happened once: a bootstrap picked a London
   `.L` listing quoted in GBp and invented one-off GBP conversion code instead
   of recognizing the real fix was a different, EUR-native listing. GBp
   support is now built into `fetch_prices.py`/`backfill_history.py`
   permanently, so this specific gap shouldn't recur - but the general
   principle holds for any future unsupported currency.)
5. **Never ask the user to paste an API key into chat.** Copy
   `.env.example` to `.env` and have them fill it in themselves in their
   editor. Only check for the *absence* of the placeholder text - never
   read/print the real key.
6. **Never do a *serial* web-search across every position** during daily
   analysis - dispatch all per-ticker searches as one parallel batch instead.
   A prior version of this pipeline timed out (600s, no output) doing a full
   per-ticker deep-dive on all 23 holdings *serially*; the failure was the
   serial execution, not the full coverage, so full-portfolio news research
   is fine as long as it's batched in parallel (see `tasks/daily-analysis.md`'s
   Holdings News Digest step). Deeper research (multi-query, iterative) still
   stays scoped to the flagged `movers` or an explicitly-invoked mode - see
   `INVESTMENT_FRAMEWORK.md`'s "Research scope".
7. **Edit `portfolio/tasks/*.md` to change scheduled-task behavior, not the
   schedule itself.** The schedule's prompt is just a one-line pointer to the
   file - the real instructions live in the file.
8. **Keep `portfolio/PIPELINE.md`'s Mermaid diagram in sync.** Any change to
   a script's inputs/outputs, the run order, a data file, or a scheduled
   task - in this file's "Pipeline components" table, `README.md`'s "Data
   pipeline" section, or the actual code - must land alongside a matching
   edit to the diagram in the same change. Same principle as the table below:
   an out-of-date diagram is worse than no diagram.

## File map (what reads/writes what)

See **`PIPELINE.md`** for the diagram (Mermaid, kept up to date per rule 8
above) - not duplicated here so there's exactly one diagram to keep in sync,
not two that can silently drift apart.

**Run order matters**: `compute_lots.py` runs FIRST (it works fine even with
an empty/missing `ticker_map.csv` - just leaves `Ticker`/`Sector` blank), THEN
`scaffold_metadata.py` (reads `transaction_lots.csv`'s blank-`Ticker` rows -
which is why it needs an `ISIN` column - to resolve and append to
`ticker_map.csv`), THEN re-run `compute_lots.py` to pick up the resolved
tickers. `scaffold_metadata.py` deliberately does NOT re-run the FIFO engine
itself - it reads the ISIN+blank-Ticker rows straight from
`transaction_lots.csv`, which is already exactly that computation's output.

`ticker_map.csv` is the ONLY file resolved by `scaffold_metadata.py` and the
only manually-maintained input besides `transactions.csv` itself. It's
shared/committed (not personal data - a factual ISIN->ticker mapping is the
same for everyone), and append-only in practice: once an ISIN is resolved
correctly, that entry should never need to change.

## Pipeline components (KEEP THIS TABLE UP TO DATE)

Whenever a script, task, or file's role changes, update this table in the same
change - it's the authoritative inventory and must never drift from reality.

**Data files:**

| File | Holds | Produced by |
|---|---|---|
| `transactions.csv` | Raw broker export - the only external input | You (manual export) |
| `ticker_map.csv` | ISIN, Ticker, Company, Sector - shared, committed | `scaffold_metadata.py` (Ticker/Company) + you (Sector) |
| `transaction_lots.csv` | Current open positions - FIFO lots, real dates/prices | `compute_lots.py` |
| `price_history/{TICKER}.jsonl` | Full sourced price history, one file per ticker | `fetch_prices.py` (daily) / `backfill_history.py` (one-off) |
| `analysis_history.jsonl` | One line per `analyze_portfolio.py` run: `generated_at`, `total_value`, `xirr_pct` - append-only, used only for the run-over-run divergence check | `analyze_portfolio.py` |
| `daily-analysis/*.md` | Generated reports | `portfolio-daily-analysis` task |
| `news/{TICKER}/*.txt` | One file per fetched news source deemed meaningful (metadata header + fetched text) - see `INVESTMENT_FRAMEWORK.md` | `portfolio-daily-analysis` task + any ad-hoc analysis that fetches news |

**Scripts - all deterministic, zero LLM involvement in the computation:**

| Script | Uses | Produces | Run order |
|---|---|---|---|
| `compute_lots.py` | `transactions.csv` + `ticker_map.csv` | `transaction_lots.csv` | 1st (works even if ticker_map.csv is empty/missing) |
| `scaffold_metadata.py` | `transaction_lots.csv` (blank-Ticker rows, by ISIN) + `yfinance` search/currency/history checks | Appends rows to `ticker_map.csv` (Sector blank) | 2nd, only when needed |
| `compute_lots.py` (re-run) | same | fresh `transaction_lots.csv` with resolved tickers | 3rd, after scaffold_metadata.py |
| `fetch_prices.py` | `transaction_lots.csv` + Finnhub/yfinance | Appends to `price_history/*.jsonl` | daily |
| `backfill_history.py` | `transaction_lots.csv` + yfinance historical | Rewrites `price_history/*.jsonl` (full history) | one-off/rare |
| `analyze_portfolio.py` | `transaction_lots.csv` + `price_history/*.jsonl` + last line of `analysis_history.jsonl` | JSON: value, gain/loss, drawdown, XIRR, movers, trend, `stale_prices`, `caveats` (incl. value-divergence check); appends a new line to `analysis_history.jsonl` | after fetch_prices.py |
| `render_report.py` | `analyze_portfolio.py`'s JSON (via stdin/pipe) | Markdown: Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers (numbers only), Complete Holdings Table, XIRR Context, Data Notes | after analyze_portfolio.py, before the report is written |

**Scheduled tasks - thin LLM wrappers around the deterministic core:**

| Task | Does | Deterministic or LLM? |
|---|---|---|
| `portfolio-price-fetch` (~07:11 Berlin) | Runs `fetch_prices.py`, reports one line | Almost entirely deterministic - LLM just runs the command and reports |
| `portfolio-daily-analysis` (~07:25 Berlin) | Runs `analyze_portfolio.py` piped into `render_report.py`, WebSearches the flagged `movers` (deeper context) and all other holdings (one-line news digest) in a single parallel batch, writes an Executive Summary, and prepends it to the rendered markdown | Hybrid - every number/table comes untouched from `render_report.py`; LLM only adds the Executive Summary and news-research prose, never hand-transcribes a figure |

Both tasks' real instructions live in `tasks/*.md`, not the schedule itself.

**Reference/instruction files (not executed):** `AGENT_NOTES.md` (this file),
`README.md` (human+agent overview), `PIPELINE.md` (Mermaid diagram of the
whole pipeline - keep in sync, see rule 8 above), `BOOTSTRAP.md` (first-run
setup), `QUICKSTART.md` (human-only, no-LLM manual usage), `CLAUDE.md`
(workspace-root auto-loaded entry point), `INVESTMENT_FRAMEWORK.md`
(analysis/advisory layer - modes, signals, portfolio/risk rules - used once
pipeline output already exists; never touches the pipeline itself).

## Ticker resolution - what already went wrong once

A bootstrap run by a smaller model (Haiku) guessed tickers instead of running
`scaffold_metadata.py`. All 7 of its guesses were wrong:

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
security exists. `scaffold_metadata.py` now checks currency and ranks
EUR-native listings first specifically because of this.

Historical bugs from earlier in this project's life (before `scaffold_metadata.py`
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
`analyze_portfolio.py` now records each run's `total_value` to
`analysis_history.jsonl` and adds a `caveats` entry (`check_value_divergence`)
if it moved >20% since the previous run - treat that caveat as "investigate
before publishing," not as a real market move.

## Currency handling

Supported: **EUR** (no conversion), **USD**, **GBP**, **GBp** (British pence -
divided by 100 to GBP before applying the EUR/GBP rate). Anything else is
rejected (returns `None`/skipped), not silently mispriced - this is
intentional. `price_eur` is the one field every downstream script reads;
never read `price_original_currency` for computation, only for display/audit.

`fetch_prices.py` (live) and `backfill_history.py` (historical) each implement
this independently but must stay in sync - if you add a currency to one, add
it to the other. Historical FX rates are used for backfill (not today's rate
applied retroactively) - each FX pair's series only goes back so far (e.g.
EUR/USD data starts 2003-12-01, since the Euro didn't exist before 1999), so
older ticker history is truncated rather than priced with a fabricated rate.

## FIFO / transaction parsing rules (compute_lots.py)

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

`analyze_portfolio.py` drops historical price points that are more than 100x
away from a ticker's current price (`SPLIT_ADJUSTMENT_SANITY_RATIO`). This
guards against a real, confirmed data bug: `yfinance`'s historical data for
some thinly-traded/leveraged ETPs isn't retroactively adjusted for later
reverse splits. A 3x daily leveraged short-oil ETC in this project showed
~€220,000 in Jan 2016 (a real historical price level before later reverse
splits) vs ~€14.50 today - both numbers are "real" in isolation, but not on
the same split-adjusted share-count basis, so multiplying by today's share
count silently corrupted any EUR-value computation. 100x is deliberately
generous so it never triggers on ordinary volatility.

## Trend vs. drawdown: two different, deliberately different methodologies

- **`drawdown`/high-water-mark** uses the FULL available price history for
  every ticker, multiplied by TODAY's share count - a synthetic "what if I'd
  held this exact portfolio further back" calculation. This is intentional
  and already agreed on: it answers "what's the worst-case value swing of my
  current holdings," not a claim about the portfolio's real historical value.
- **`trend.since_inception`** is anchored to the EARLIEST actual purchase date
  in `transaction_lots.csv`, NOT the earliest available price-history point.
  Using full history here was tried and produced a real, confirmed bug: it
  showed **+57,000%** using a Siemens price from 1996, because the portfolio
  (in its current form) didn't exist until 2024. Don't "fix" this back to
  using full history - the discrepancy between these two methodologies is the
  point, not an inconsistency to resolve.

## Annualized return (XIRR)

`annualized_returns` is a real money-weighted XIRR computed from
`transaction_lots.csv`'s actual purchase dates/prices - not `total_return /
years_held`. Check `weighted_avg_holding_days` before treating any single
position's XIRR as meaningful: annualizing a short real holding period
produces mathematically extreme numbers (e.g. a genuine 37% gain over 12
weeks annualizes to 300%+). That's correct math, not a bug, but it's easy to
misread without the holding-period context alongside it. No position needs to
have been held a full year for the *portfolio-wide* XIRR to be meaningful.

## Data provenance / secrets

Every `price_history/{TICKER}.jsonl` record for a non-EUR ticker carries its
original currency, raw price, exact source URL (API token redacted before
persisting), and the FX rate + source used. EUR-native records omit all of
this (would just be no-op restatements). Never persist an API token/secret
into any output file, ever.
