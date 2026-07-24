# Portfolio Management System

## What This Does

A portfolio tracker and daily analysis pipeline that runs entirely on Claude
Code - no external server, no OpenClaw, no other agent framework. Point it at
a broker transaction export and it will:

- Reconstruct your real, current positions (shares, cost basis, purchase
  dates) from actual buy/sell history via FIFO - not a manually maintained
  spreadsheet that can drift out of sync
- Fetch live prices daily (Finnhub primary, yfinance backup) in EUR, fully
  sourced (original currency, API used, FX rate applied - all persisted, not
  just the final number)
- Compute portfolio value, gain/loss, sector concentration, largest positions,
  high-water-mark/drawdown, daily movers, and a real money-weighted annualized
  return (XIRR) - all deterministic Python, not estimated by an LLM
- Write a daily markdown report, researching every holding's news in a single
  parallel batch (not a serial loop, which timed out previously), with deeper
  context on notable movers, and archive every meaningful source fetched
  (URL, timestamp, method) as its own file under `news/{TICKER}/`

**Currently supports Scalable Capital's transaction export format.** Other
brokers' CSV exports have different columns/formats and aren't parsed yet -
see `compute_lots.py`'s `load_transactions()` if you need to adapt it for a
different broker.

**First time running this?** See `BOOTSTRAP.md` - Claude will walk through
setup automatically if it detects this is a fresh clone (no `transactions.csv`
present yet).

**Working on this codebase (agent or human)?** Read **`AGENT_NOTES.md` first.**
It consolidates every non-obvious rule, past bug, and design decision into one
place, specifically so you never have to read the Python source to understand
why something works the way it does.

**Want investment analysis or advice from this data** (chat questions, or the
daily report's Executive Summary/News Digest)? See **`INVESTMENT_FRAMEWORK.md`**
- the analysis/advisory layer used once the pipeline's numbers already exist.
It never changes a pipeline number itself.

## Data pipeline (in order)

See **`PIPELINE.md`** for a Mermaid diagram of everything below.

1. **`transactions.csv`** — raw broker transaction export (Scalable Capital). The
   one file with no automated source; re-export from the broker and update
   this whenever you trade. Everything else derives from it.
2. **`compute_lots.py`** → **`transaction_lots.csv`** — FIFO cost-basis engine.
   Reconstructs exactly which shares are still held, when, and at what price,
   from the real transaction history (handles partial sells, the WisdomTree
   ISIN-swap corporate action, and the Dec 2025 broker-migration transfer rows).
   This is the sole source of current open positions (ticker, company, shares,
   weighted-average cost) — there is no separate positions file.
3. **`ticker_map.csv`** (ISIN, Ticker, Company, Sector) — the resolved ticker
   symbol and sector, the two things broker exports can't provide. Shared and
   committed - an ever-growing lookup table (see `scaffold_metadata.py`),
   because resolving a ticker correctly once means nobody using this project
   ever has to re-solve it. Run `python3 scaffold_metadata.py` to
   deterministically resolve any new ISIN via a real yfinance lookup (never a
   guess) whenever `compute_lots.py` reports one as unmapped; Sector still
   needs a quick human judgment call afterward (see `AGENT_NOTES.md` for why
   ticker guessing must never happen).
4. **`fetch_prices.py`** → **`price_history/{TICKER}.jsonl`** — fetches the
   ticker list from `transaction_lots.csv`, gets live prices (Finnhub primary,
   yfinance fallback), and appends one fully-sourced record per ticker
   (original currency, source name/URL, FX rate + source) to its own history
   file. There is no separate latest-price snapshot file - each file's last
   line IS the current price.
5. **`analyze_portfolio.py`** — deterministic numeric layer: value, gain/loss,
   sector breakdown, high-water-mark/drawdown, movers, trend, and a real
   money-weighted XIRR (annualized return) from `transaction_lots.csv`'s actual
   purchase dates. Also flags any ticker whose latest `price_history` entry is
   more than 2 days old (stale/failed fetch) - see `stale_prices` in its output
   - and flags a run-over-run `total_value` swing >20% (see `analysis_history.jsonl`)
   as a likely data bug rather than a real market move. Both thresholds (and
   every other tunable number/message in the pipeline) live in `config.json`,
   not hardcoded - see `AGENT_NOTES.md`'s "Configurable thresholds and caveats".
6. **`render_report.py`** — takes `analyze_portfolio.py`'s JSON (piped via
   stdin) and renders every table/figure in the daily report as markdown.
   Exists so the LLM writing the report never hand-transcribes a number out of
   the JSON - it only writes the Executive Summary and the Movers research
   prose, and appends them around this script's output.

## Daily Workflow (scheduled tasks)

- **`portfolio-price-fetch`** (~07:11 Berlin) — runs `fetch_prices.py`
- **`portfolio-daily-analysis`** (~07:25 Berlin) — runs `analyze_portfolio.py`
  piped into `render_report.py`, researches all holdings' news in one
  parallel batch (never a serial loop — a prior serial full-scan attempt
  timed out) with deeper context on notable movers, writes
  `daily-analysis/YYYY-MM-DD.md`

Each scheduled task's actual instructions are NOT stored in the schedule
itself - the schedule's prompt is just a one-line pointer ("read and follow
`tasks/{name}.md`"). The real instructions live in **`tasks/price-fetch.md`**
and **`tasks/daily-analysis.md`**, so editing task behavior is a normal file
edit (visible, diffable, version-controlled with everything else) rather than
a separate tool call against the scheduler. If you change what a task should
do, edit the file in `tasks/`, not the schedule.

## When you trade

1. Re-export `transactions.csv` from Scalable Capital (or add the new rows)
2. Run `python3 compute_lots.py` to regenerate `transaction_lots.csv` - this
   picks up the new transaction(s), leaving `Ticker`/`Sector` blank for any
   brand-new ISIN
3. If it reports a brand-new ISIN, run `python3 scaffold_metadata.py` to
   resolve its ticker deterministically (appends to `ticker_map.csv`), review
   the printed pick, then fill in its Sector directly in `ticker_map.csv`
4. Re-run `python3 compute_lots.py` to pick up the resolved ticker
5. (Optional) Run `python3 fetch_prices.py` to pick up the new ticker immediately

Skipping this means `transaction_lots.csv` (and therefore XIRR, position
values, and drawdown) go stale while prices keep updating daily around it —
there's no automation that detects a new trade on its own.

## Files

| File | Purpose | Maintained by |
|------|---------|--------|
| `transactions.csv` | Raw broker export — the actual source of truth | You, manually |
| `ticker_map.csv` | ISIN, Ticker, Company, Sector. Shared, committed, ever-growing | `scaffold_metadata.py` (append-only) + you (Sector) |
| `transaction_lots.csv` | FIFO-derived open lots (shares, dates, prices) | `compute_lots.py` |
| `price_history/{TICKER}.jsonl` | Full sourced price history per ticker - last line = current price | `fetch_prices.py` (append) / `backfill_history.py` (seed) |
| `analysis_history.jsonl` | One line per `analyze_portfolio.py` run (`generated_at`, `total_value`, `xirr_pct`) - powers the value-divergence caveat | `analyze_portfolio.py` (append) |
| `daily-analysis/*.md` | Generated reports | scheduled task, output only |
| `news/{TICKER}/*.txt` | One file per fetched news source deemed meaningful - metadata header (URL, fetched-at, fetch method) + the fetched text | scheduled task + ad-hoc analysis, output only |
| `PIPELINE.md` | Mermaid diagram of the whole pipeline | Kept in sync by hand - see `AGENT_NOTES.md` rule 8 |
| `tasks/*.md` | Actual scheduled-task instructions (schedule just points here) | You, when task behavior needs to change |
| `INVESTMENT_FRAMEWORK.md` | Analysis/advisory layer (modes, signals, portfolio/risk rules) used on top of pipeline output | You, when analysis approach needs to change |
| `.env` | Finnhub API key (gitignored, never committed) | You, rarely |
| `.env.example` | Committed placeholder template - copy to `.env` and fill in your key | Ships with the repo |

## Troubleshooting

### Missing or stale prices
- Check `fetch_prices.py` output for which tickers failed and why
- Check `analyze_portfolio.py`'s `stale_prices` output field - flags any ticker whose last `price_history` entry is 2+ days old
- Verify the ticker in `ticker_map.csv` is still the correct exchange symbol (companies occasionally change listings)
- Re-run `python3 fetch_prices.py`

### transaction_lots.csv share counts look wrong
- Re-run `python3 compute_lots.py` — it prints current positions and flags any ISIN missing a `ticker_map.csv` row, or a row with a blank Sector
- If a same-day buy/sell pair looks mis-sequenced, check `transactions.csv`'s `time` column - lots are sorted by full date+time, not date alone

### Prices look wrong
- Confirm the ticker in `ticker_map.csv` is the security you actually hold — a wrong/ambiguous ticker can silently resolve to an unrelated company. This is the single biggest real bug source in this project - confirmed cases: `CAN`→Canaan Inc instead of Cantourage Group `HIGH.DE`, `DTE`→DTE Energy instead of Deutsche Telekom `DTE.DE`, `IRE`→a leveraged Iren SpA ETF instead of IREN Ltd, and (from a bootstrap run by a smaller model that guessed tickers instead of using `scaffold_metadata.py`) `CCO`→a $2.41 unrelated stock instead of Cameco `CCJ`@$87, plus several London `.L` listings picked in GBp (pence) that should have been EUR-native alternatives. **Always resolve new tickers via `scaffold_metadata.py`, never by guessing a shorthand symbol.**
- Check Scalable Capital for any splits/adjustments
- Finnhub prices are ~5 min delayed (not real-time)

### A price looks off by ~100x, or in the wrong currency entirely
- Check `price_history/{TICKER}.jsonl`'s `original_currency` field for that ticker - the pipeline supports EUR, USD, GBP, and GBp (British pence, converted by /100 first). Any other currency is rejected, not silently mispriced.
- If `ticker_map.csv` points at a listing in an unsupported currency (e.g. CAD, JPY), `scaffold_metadata.py` will flag it - find an EUR/USD/GBP-listed alternative for that ISIN instead

## Testing

Run the full pipeline manually:
```bash
python3 portfolio/scaffold_metadata.py # only needed if you have a new, unmapped ISIN
python3 portfolio/compute_lots.py      # only needed if transactions.csv changed
python3 portfolio/fetch_prices.py
python3 portfolio/analyze_portfolio.py | python3 portfolio/render_report.py
```

## API Status

- **yfinance**: Free, primary source — covers both US and EU-listed tickers directly (e.g. `BAYN.DE`, `SAN.PA`, `3BRS.MI`, `EWG2.SG`, `SEC0.DE`)
- **Finnhub**: Free tier (60 req/min, 30k/month) — fallback for bare US tickers only; its free tier doesn't cover non-US exchanges

All free, no credit card required.

**Supported currencies**: EUR, USD, GBP, and GBp (British pence, e.g. London
`.L`-suffixed listings - divided by 100 to GBP before converting). Anything
else is rejected rather than silently mispriced - `scaffold_metadata.py` flags
it so you can pick a different listing for that ISIN.

### Getting a Finnhub API key
1. Go to https://finnhub.io/register and sign up (free, no card required)
2. Copy the API key from your dashboard
3. Copy `portfolio/.env.example` to `portfolio/.env` and replace the
   placeholder with your real key - do this yourself in your editor, don't
   paste the key into chat with Claude (it would end up in the conversation
   history)

The pipeline still works without one (yfinance alone covers everything), but
Finnhub as primary is faster/more reliable for the plain US tickers it supports.
