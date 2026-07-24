# Quickstart - running this without Claude at all

Everything in this pipeline is plain Python. You don't need Claude Code, an
LLM, or any agent to run the core data pipeline yourself from a terminal -
this guide walks through exactly that. The one place an LLM genuinely adds
something is writing the narrative daily report (research on notable movers,
prose) - see "What you lose without an LLM" at the end.

Every command below is run as `python3 -m pipeline.<module>` from inside
`portfolio/` - there are no standalone script files; the pipeline is a
regular Python package (`portfolio/pipeline/`) and `-m` is how you invoke a
module in it directly.

## 1. Prerequisites

- Python 3.9+
- Install the three third-party packages this project uses:
  ```bash
  pip install yfinance pandas requests
  ```
  (Everything else used is Python's standard library.)

## 2. Get your transaction history

Export your transaction history from your broker. **This currently only
parses Scalable Capital's export format**: a semicolon-delimited CSV with
columns `date;time;status;reference;description;assetType;type;isin;shares;price;amount;fee;tax;currency`,
prices using German decimal commas (`1.074,00` = 1074.00). If your broker
exports differently, you'll need to adapt `pipeline/lots.py`'s
`load_transactions()` function, or convert your export to match this format
first.

Save the export as `portfolio/data/manual/transactions.csv`.

## 3. (Optional) Finnhub API key

The pipeline works fully without this - `yfinance` alone covers everything.
Finnhub is just a faster/more-reliable primary source for plain US tickers.

```bash
cp portfolio/.env.example portfolio/.env
```
Then open `portfolio/.env` in any text editor and replace the placeholder
with a real key from https://finnhub.io/register (free, no card required).

## 4. Build your current positions (run this first - pipeline.tickers needs its output)

```bash
cd portfolio
python3 -m pipeline.lots
```

Reconstructs exactly which shares you still hold, and when/at what price you
bought them, from your full transaction history (handles partial sells,
corporate actions, and broker-migration artifacts automatically). Writes
`data/transaction_lots.csv`, including a blank `Ticker`/`Sector` for any ISIN
`data/ticker_map.csv` doesn't have yet - that's expected on a first run and is
exactly what the next step resolves.

## 5. Resolve tickers for your holdings

```bash
python3 -m pipeline.tickers
```

Reads `data/transaction_lots.csv` for any open position with a blank `Ticker`,
looks each one up via a real `yfinance` search, and prints a review table like:

```
  Deutsche Telekom                   DE0005557508  ->  DTE.DE     26.26 EUR
  Cameco                             CA13321L1085  ->  CCO.TO     122.74 CAD
      ⚠ UNSUPPORTED CURRENCY CAD - find a EUR/USD/GBP listing
```

**You need to eyeball this table yourself** - this is the one step where
human judgment replaces what an LLM would otherwise help verify. For each row:
- Does the picked ticker match the company name? A wildly-off price or
  unexpected currency usually means it's the wrong company or listing.
- Any row with a `⚠` warning needs a manual fix: open `data/ticker_map.csv` in a
  text editor and replace that ticker with a better one. You can check any
  candidate yourself:
  ```bash
  python3 -c "import yfinance as yf; print(yf.Ticker('TICKER').fast_info)"
  ```
  Look at the `currency` field - **supported currencies are EUR, USD, GBP,
  and GBp** (British pence - e.g. London `.L`-suffixed listings, converted
  /100 to GBP). Anything else isn't supported - find a different EUR/USD/GBP
  listing for that same ISIN rather than trying to add a new currency yourself.

Then open `portfolio/data/ticker_map.csv` and fill in the blank `Sector` column
for each new row (any taxonomy you like - Technology, Healthcare, Commodities,
etc; it's just used for the sector-concentration breakdown).

Re-run `python3 -m pipeline.lots` then `python3 -m pipeline.tickers` any time
you buy a new security for the first time - the latter only resolves ISINs
it hasn't seen before and never overwrites existing rows. Once
`pipeline.lots` reports no missing tickers or sectors, you're done with
this step.

## 6. Fetch prices

```bash
python3 -m pipeline.prices
```

Gets live prices for every ticker in `data/transaction_lots.csv` (Finnhub first if
you set up a key, yfinance otherwise), and appends one line per ticker to its
own history file at `data/price_history/{TICKER}.jsonl`.

## 7. (One-time) Backfill historical prices

```bash
python3 -m pipeline.backfill
```

Pulls each ticker's full available price history (as far back as `yfinance`
has data) so drawdown/trend analysis has real history instead of a single
day. Takes a bit longer than step 6. You only need to run this once per
ticker - `pipeline.prices` keeps appending to the same files daily after that.

## 8. Compute your portfolio metrics

```bash
python3 -m pipeline.analysis
```

Prints a single JSON object to stdout with everything: per-position value and
gain/loss, sector breakdown, largest positions, high-water-mark/drawdown,
today's movers, trend over several time windows, and a real money-weighted
annualized return (XIRR) - computed from your actual purchase dates, not
estimated. Also includes a `caveats` array explaining any methodology
subtleties for that specific run (read it - it changes based on your data)
and a `stale_prices` list flagging any ticker that hasn't updated in 2+ days.

Redirect it to a file or pipe it into `python3 -m json.tool` for readability:
```bash
python3 -m pipeline.analysis | python3 -m json.tool
```

It also appends `{generated_at, total_value, xirr_pct}` to `data/analysis_history.jsonl`
each run, and adds a `caveats` entry if `total_value` swung more than 20%
(configurable in `config.json`) since the previous run - a real incident (a
bad ticker mapping doubled the reported
value) is what this guards against; see `AGENT_NOTES.md`.

## 9. Render it as markdown

```bash
python3 -m pipeline.analysis | python3 -m pipeline.report
```

Turns the JSON into the same markdown tables the daily report uses - Portfolio
Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete
Holdings Table, XIRR Context, Data Notes - no LLM involved, this is plain
Python string formatting over the JSON above.

## Automating this without Claude

Set up your own cron job (macOS/Linux) or Task Scheduler (Windows) to run
step 6 (`pipeline.prices`) daily, then step 8+9 (`pipeline.analysis` piped
into `pipeline.report`) shortly after. Example crontab entry (adjust the
path and time):
```
7 7 * * *  cd /path/to/portfolio && python3 -m pipeline.prices
25 7 * * *  cd /path/to/portfolio && python3 -m pipeline.analysis | python3 -m pipeline.report > data/daily-analysis/$(date +\%Y-\%m-\%d).md
```

## What you lose without an LLM

`pipeline.analysis` + `pipeline.report` together produce every number and
table in the daily report - nothing about using an LLM changes any of those.
What you don't get without one:
- **An Executive Summary** - the daily task writes a few sentences of framing
  prose above the rendered tables; without an LLM you're reading the tables
  cold
- **News research on every holding** - the daily task web-searches all
  positions in parallel (one-line digest each) plus deeper context on
  whatever `pipeline.analysis` flags as a significant mover, filling in
  the Movers table's Context column, and archives each meaningful source as
  its own file under `data/news/{TICKER}/`; running the pipeline yourself just
  gives you numbers and flagged tickers/percentages, not the "why" behind any
  of it or a record of where it came from
- **Investment analysis/advice grounded in this data** - if you ask Claude
  about a specific holding, portfolio structure, or rebalancing, it follows
  `INVESTMENT_FRAMEWORK.md`'s modes/signals; running the pipeline yourself
  gives you the numbers those opinions would be based on, not the opinions
- **Interactive ticker review** (step 4) - a human still has to eyeball the
  table either way; an LLM just makes confirming/asking follow-up questions
  faster than manually running `yfinance` lookups yourself

Everything else - the actual financial computation, and every table in the
report - is identical either way, because it's the same deterministic Python
code in both cases.
