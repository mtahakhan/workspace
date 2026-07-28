# Quickstart - Running the Pipeline Manually

Everything in this pipeline is plain Python. You don't need Claude Code, an LLM, or the `portfolio` MCP server running to use the core data pipeline yourself from a terminal.

**Quick navigation:**
- **Just want to run the pipeline today?** → [Running the pipeline daily](#running-the-pipeline-daily)
- **Setting up for the first time?** → [First-time setup](#first-time-setup-steps-0-4)
- **Want to understand each step?** → [Detailed step-by-step](#detailed-step-by-step-steps-0-9)
- **Want to automate it?** → [Automating without Claude](#automating-without-claude)

**Alternative paths:**
- Want Claude to handle this for you? See [`SETUP.md`](SETUP.md) instead
- Want to see all four usage options? See [`PATHWAYS.md`](PATHWAYS.md)

---

## Running the pipeline daily

If you've already set up (steps 0-4 done), use this one-liner:

```bash
make refresh
```

This fetches prices, computes analysis, checks compliance, and renders a markdown report. Output saved to `data/personal/manual-runs/<timestamp>/` and printed to stdout.

**Just fetch prices today, no analysis?**
```bash
make fetch-prices
```

**Want to understand what `make refresh` does?** See [Detailed step-by-step](#detailed-step-by-step-steps-0-9).

---

## First-time setup (Steps 0-4)

Do this once. These steps import your transactions and resolve ticker symbols.

### Step 0. Create the venv (skip if `bootstrap.sh` already has)

```bash
cd mcp_servers
# use the highest available Python >=3.10 - try in order:
for py in python3.13 python3.12 python3.11 python3.10; do
  command -v "$py" >/dev/null 2>&1 && { "$py" -m venv portfolio_tools/.venv; break; }
done
portfolio_tools/.venv/bin/pip install -r portfolio_tools/requirements.txt
```

**Every command after this point uses `portfolio_tools/.venv/bin/python3` exclusively** — never a bare `python3` or `pip`.

### Step 1. Get your transaction history

Export your transaction history from Scalable Capital as CSV (semicolon-delimited, German decimal format).

Save it as `data/personal/transactions.csv` (create `data/personal/` if it doesn't exist):
```bash
mkdir -p data/personal
# copy your export here as transactions.csv
```

**This currently only parses Scalable Capital's format.** Other brokers' CSV exports are different - see `portfolio_tools/pipeline/lots.py`'s `load_transactions()` if you need to adapt it.

### Step 2. (Optional) Finnhub API key

The pipeline works fully without this — `yfinance` alone covers everything. See [`SETUP.md`](SETUP.md#getting-a-finnhub-api-key-optional) for how to get one and wire it into `.env`.

### Step 3. Build your current positions

```bash
cd mcp_servers
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.lots
```

Reconstructs which shares you still hold, cost basis, and purchase dates from your transaction history (handles partial sells and corporate actions automatically).

Writes `data/personal/transaction_lots.csv` with a blank `Ticker`/`Sector` for any ISIN not yet in `data/impersonal/ticker_map.csv` — that's expected and step 4 resolves it.

### Step 4. Resolve tickers for your holdings

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.tickers
```

Looks up each blank ticker via `yfinance` and prints a review table:

```
  Deutsche Telekom                   DE0005557508  ->  DTE.DE     26.26 EUR
  Cameco                             CA13321L1085  ->  CCO.TO     122.74 CAD
      ⚠ UNSUPPORTED CURRENCY CAD - find a EUR/USD/GBP/DKK listing
```

**Eyeball each row yourself** — this is where human judgment is essential:
- Does the ticker match the company name?
- Is the price reasonable?
- Any `⚠` warnings? Fix them in `data/impersonal/ticker_map.csv`

**Only EUR/USD/GBP/GBp/DKK are supported** - see [`ARCHITECTURE.md`](ARCHITECTURE.md#currency-handling) for the full rule. Anything else needs a different listing.

Then fill in the blank `Sector` column in `ticker_map.csv` for each new row (Technology, Healthcare, etc.).

**Re-run both steps 3 and 4** each time you buy a new security for the first time. Step 4 only resolves new ISINs and never overwrites existing rows.

---

## Detailed step-by-step (Steps 0-9)

After setup (steps 0-4), these are the steps `make refresh` runs daily.

### Step 5. Fetch prices

```bash
cd mcp_servers
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.prices
```

Gets live prices for every ticker (Finnhub first if you set up a key, yfinance otherwise) and appends one line per ticker to `data/impersonal/price_history/{TICKER}.jsonl`.

**Exits non-zero if any ticker fails** — that's intentional; a partial price set makes analysis meaningless. Tickers that did resolve are still appended first, so nothing's lost on retry.

### Step 6. (One-time) Backfill historical prices

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.backfill
```
(or, from the repo root: `make backfill`)

Pulls each ticker's full available price history (as far back as `yfinance` has) so drawdown/trend analysis has real history instead of just today's prices. Requires tickers already resolved (steps 3-4) - it reads `enriched_lots.csv`.

**Run this only once per ticker** — step 5 keeps appending to the same files daily after that. Takes a bit longer than step 5 (a few minutes depending on your portfolio size).

### Step 7. Compute your portfolio metrics

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis
```

Prints a single JSON object: per-position value and gain/loss, sector breakdown, largest positions, high-water-mark/drawdown, today's movers, trend analysis, and XIRR (real money-weighted annualized return from your actual purchase dates, not estimated).

Also includes:
- `caveats` array explaining methodology subtleties for this run (changes based on your data)
- `stale_prices` list flagging tickers not updated in 2+ days

**For readability:**
```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m json.tool
```

**Note:** This step can be slow with many years of backfilled history per ticker — see [`ARCHITECTURE.md`](ARCHITECTURE.md)'s "Historical price data quality" for details.

It also appends `{generated_at, total_value, xirr_pct}` to `data/personal/analysis_history.jsonl` each run, and adds a `caveats` entry if `total_value` swung >20% since the last run (guard against bad ticker mappings).

### Step 8. Render it as markdown

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.report
```

Turns the JSON into markdown tables: Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete Holdings Table, Corporate Actions, Fee Drag, XIRR Context, Data Notes.

No LLM involved — this is plain Python string formatting over the JSON above. Corporate Actions and Fee Drag sections only appear when relevant (share splits/consolidations, or notable fees).

### Step 9. Check it against the framework's hard limits

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.compliance
```

Evaluates the portfolio against every allocation limit: sleeve split, single-position and secure-hedge caps, top-3 and per-sector concentration, cash ceiling, positions too small to pay exit fees.

Prints a `breaches` list. Empty means nothing to act on.

Also reports:
- `prime_status` (worth knowing — PRIME subscription affects sell fees)
- `fee_history` and `fee_drag_by_ticker` (lifetime fees including closed positions)

Two files are yours to maintain:
- **`data/personal/roles.csv`** — assigns each holding a role (Core Compounder / Growth / Opportunistic / Defensive)
- **`data/impersonal/fee_rules.json`** — PRIME issuer list and secure-hedge ISIN list

---

## Automating without Claude

### Option 1: Use `make refresh` with cron (simplest)

```
35 7 * * *  cd /path/to/repo && make refresh >> data/personal/manual-runs.log 2>&1
```

This chains steps 5/7/8/9 in one command, fails loudly if any ticker can't be priced, and writes output under `data/personal/manual-runs/<timestamp>/` plus stdout.

### Option 2: Wire up individual commands (more control)

```
7 7 * * *  cd /path/to/mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.prices
25 7 * * *  cd /path/to/mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.report > data/personal/daily-analysis/$(date +\%Y-\%m-\%d).md
```

This lets you fetch prices earlier than analysis (e.g., market open vs. market close), or run steps at different times.

---

## What you lose without an LLM

`analysis` + `report` together produce every number and table in the daily report — nothing about using an LLM changes any of those. **What you don't get without one:**

- **Executive Summary** — prose framing above the tables; without an LLM you're reading tables cold
- **News research on every holding** — web-searched one-line digests on all positions, plus deeper context on notable movers, archived as files under `data/impersonal/news/{TICKER}/` — running the pipeline yourself gives you flagged tickers/percentages, not the "why" or sources
- **Investment analysis/advice** — if you ask Claude about a holding/structure/rebalancing, it follows [`INVESTMENT_FRAMEWORK.md`](../skills/portfolio/references/INVESTMENT_FRAMEWORK.md)'s methodology — running the pipeline yourself gives you the numbers those opinions would be based on, not the opinions
- **Interactive ticker review** — a human eyeballs the lookup table either way; an LLM just makes confirming/follow-ups faster than manual `yfinance` lookups
- **Upload convenience** — you place `transactions.csv` yourself rather than pasting its content to a tool

**Everything else — actual financial computation, every table — is identical**, because it's the same deterministic Python code either way.
