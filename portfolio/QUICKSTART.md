# Quickstart - running this without Claude at all

Everything in this pipeline is plain Python. You don't need Claude Code, an
LLM, or any agent to run the core data pipeline yourself from a terminal -
this guide walks through exactly that. The one place an LLM genuinely adds
something is writing the narrative daily report (research on notable movers,
prose) - see "What you lose without an LLM" at the end.

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
exports differently, you'll need to adapt `compute_lots.py`'s
`load_transactions()` function, or convert your export to match this format
first.

Save the export as `portfolio/transactions.csv`.

## 3. (Optional) Finnhub API key

The pipeline works fully without this - `yfinance` alone covers everything.
Finnhub is just a faster/more-reliable primary source for plain US tickers.

```bash
cp portfolio/.env.example portfolio/.env
```
Then open `portfolio/.env` in any text editor and replace the placeholder
with a real key from https://finnhub.io/register (free, no card required).

## 4. Build your current positions (run this first - scaffold_metadata.py needs its output)

```bash
cd portfolio
python3 compute_lots.py
```

Reconstructs exactly which shares you still hold, and when/at what price you
bought them, from your full transaction history (handles partial sells,
corporate actions, and broker-migration artifacts automatically). Writes
`transaction_lots.csv`, including a blank `Ticker`/`Sector` for any ISIN
`ticker_map.csv` doesn't have yet - that's expected on a first run and is
exactly what the next step resolves.

## 5. Resolve tickers for your holdings

```bash
python3 scaffold_metadata.py
```

Reads `transaction_lots.csv` for any open position with a blank `Ticker`,
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
- Any row with a `⚠` warning needs a manual fix: open `ticker_map.csv` in a
  text editor and replace that ticker with a better one. You can check any
  candidate yourself:
  ```bash
  python3 -c "import yfinance as yf; print(yf.Ticker('TICKER').fast_info)"
  ```
  Look at the `currency` field - **supported currencies are EUR, USD, GBP,
  and GBp** (British pence - e.g. London `.L`-suffixed listings, converted
  /100 to GBP). Anything else isn't supported - find a different EUR/USD/GBP
  listing for that same ISIN rather than trying to add a new currency yourself.

Then open `portfolio/ticker_map.csv` and fill in the blank `Sector` column
for each new row (any taxonomy you like - Technology, Healthcare, Commodities,
etc; it's just used for the sector-concentration breakdown).

Re-run `python3 compute_lots.py` then `python3 scaffold_metadata.py` any time
you buy a new security for the first time - the latter only resolves ISINs
it hasn't seen before and never overwrites existing rows. Once
`compute_lots.py` reports no missing tickers or sectors, you're done with
this step.

## 6. Fetch prices

```bash
python3 fetch_prices.py
```

Gets live prices for every ticker in `transaction_lots.csv` (Finnhub first if
you set up a key, yfinance otherwise), and appends one line per ticker to its
own history file at `price_history/{TICKER}.jsonl`.

## 7. (One-time) Backfill historical prices

```bash
python3 backfill_history.py
```

Pulls each ticker's full available price history (as far back as `yfinance`
has data) so drawdown/trend analysis has real history instead of a single
day. Takes a bit longer than step 6. You only need to run this once per
ticker - `fetch_prices.py` keeps appending to the same files daily after that.

## 8. Compute your portfolio metrics

```bash
python3 analyze_portfolio.py
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
python3 analyze_portfolio.py | python3 -m json.tool
```

## Automating this without Claude

Set up your own cron job (macOS/Linux) or Task Scheduler (Windows) to run
step 6 (`fetch_prices.py`) daily, then step 8 (`analyze_portfolio.py`)
shortly after. Example crontab entry (adjust the path and time):
```
7 7 * * *  cd /path/to/portfolio && python3 fetch_prices.py
25 7 * * *  cd /path/to/portfolio && python3 analyze_portfolio.py > daily-analysis/$(date +\%Y-\%m-\%d).json
```

## What you lose without an LLM

`analyze_portfolio.py`'s JSON output has everything numeric - nothing about
using an LLM changes any of those numbers. What you don't get without one:
- The **narrative markdown report** (`daily-analysis/YYYY-MM-DD.md`) - you'd
  be reading the raw JSON, or writing your own summary from it
- **Research on notable movers** - the daily task does a targeted web search
  on whatever `analyze_portfolio.py` flags as a significant move; running the
  pipeline yourself just gives you the flagged ticker/percentage, not the
  "why" behind the move
- **Interactive ticker review** (step 4) - a human still has to eyeball the
  table either way; an LLM just makes confirming/asking follow-up questions
  faster than manually running `yfinance` lookups yourself

Everything else - the actual financial computation - is identical either way,
because it's the same deterministic Python code in both cases.
