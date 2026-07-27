# Quickstart - running this without Claude, or without the MCP server

Everything in this pipeline is plain Python. You don't need Claude Code, an
LLM, or the `portfolio` MCP server running to use the core data pipeline
yourself from a terminal - this guide walks through exactly that. The one
place an LLM genuinely adds something is writing the narrative daily report
(research on notable movers, prose) - see "What you lose without an LLM" at
the end. (If you *do* want the MCP server/Skill path - the normal, sanctioned
way to use this day to day - see [`SETUP.md`](SETUP.md) and run
`../bootstrap.sh` instead of this guide.)

**Always use this package's own venv, never a system Python.** Every command
below is run as `portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.<module>` from
inside `mcp_servers/` - there are no standalone script files; the pipeline is
a subpackage of the `portfolio_tools` server package (see
[`ARCHITECTURE.md`](ARCHITECTURE.md)), and `-m` is how you invoke a module in
it directly. This is the same venv `../bootstrap.sh` creates
(`mcp_servers/portfolio_tools/.venv`) - if you've already run that, skip
straight to step 1; there's no separate environment for "manual" use.

## 0. Create the venv (skip if `../bootstrap.sh` already has)

```bash
cd mcp_servers
# use the highest available Python >=3.10 - try in order:
for py in python3.13 python3.12 python3.11 python3.10; do
  command -v "$py" >/dev/null 2>&1 && { "$py" -m venv portfolio_tools/.venv; break; }
done
portfolio_tools/.venv/bin/pip install -r portfolio_tools/requirements.txt
```
A system Python is used here only to create the venv — this is unavoidable
(you can't use the venv to create itself). **Every command after this point
uses `portfolio_tools/.venv/bin/python3` or `portfolio_tools/.venv/bin/pip` exclusively — never a bare
`python3` or `pip`.**

## 1. Get your transaction history

Export your transaction history from your broker. **This currently only
parses Scalable Capital's export format**: a semicolon-delimited CSV with
columns `date;time;status;reference;description;assetType;type;isin;shares;price;amount;fee;tax;currency`,
prices using German decimal commas (`1.074,00` = 1074.00). If your broker
exports differently, you'll need to adapt `portfolio_tools/pipeline/lots.py`'s
`load_transactions()` function, or convert your export to match this format
first.

Save the export as `data/personal/transactions.csv` (create
`data/personal/` if it doesn't exist yet - normally the `upload_transactions`
MCP tool creates it, but you're bypassing that here).

## 2. (Optional) Finnhub API key

The pipeline works fully without this - `yfinance` alone covers everything.
Finnhub is just a faster/more-reliable primary source for plain US tickers.

```bash
cp mcp_servers/portfolio_tools/.env.example mcp_servers/portfolio_tools/.env
```
Then open `mcp_servers/portfolio_tools/.env` in any text editor and replace
the placeholder with a real key from https://finnhub.io/register (free, no
card required).

## 3. Build your current positions (run this first - resolving tickers needs its output)

```bash
cd mcp_servers
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.lots
```

Reconstructs exactly which shares you still hold, and when/at what price you
bought them, from your full transaction history (handles partial sells,
corporate actions, and broker-migration artifacts automatically). Writes
`data/personal/transaction_lots.csv`, including a blank `Ticker`/`Sector`
for any ISIN `data/impersonal/ticker_map.csv` doesn't have yet - that's
expected on a first run and is exactly what the next step resolves.

## 4. Resolve tickers for your holdings

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.tickers
```

Reads `data/personal/transaction_lots.csv` for any open position with a
blank `Ticker`, looks each one up via a real `yfinance` search, and prints a
review table like:

```
  Deutsche Telekom                   DE0005557508  ->  DTE.DE     26.26 EUR
  Cameco                             CA13321L1085  ->  CCO.TO     122.74 CAD
      ⚠ UNSUPPORTED CURRENCY CAD - find a EUR/USD/GBP listing
```

**You need to eyeball this table yourself** - this is the one step where
human judgment replaces what an LLM would otherwise help verify. For each row:
- Does the picked ticker match the company name? A wildly-off price or
  unexpected currency usually means it's the wrong company or listing.
- Any row with a `⚠` warning needs a manual fix: open
  `data/impersonal/ticker_map.csv` in a text editor and replace that
  ticker with a better one. You can check any candidate yourself (still
  through the venv):
  ```bash
  portfolio_tools/.venv/bin/python3 -c "import yfinance as yf; print(yf.Ticker('TICKER').fast_info)"
  ```
  Look at the `currency` field - **supported currencies are EUR, USD, GBP,
  and GBp** (British pence - e.g. London `.L`-suffixed listings, converted
  /100 to GBP). Anything else isn't supported - find a different EUR/USD/GBP
  listing for that same ISIN rather than trying to add a new currency yourself.

Then open `data/impersonal/ticker_map.csv` and fill in the blank `Sector`
column for each new row (any taxonomy you like - Technology, Healthcare,
Commodities, etc; it's just used for the sector-concentration breakdown).

Re-run `portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.lots` then
`portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.tickers` any time you buy a
new security for the first time - the latter only resolves ISINs it hasn't
seen before and never overwrites existing rows. Once the former reports no
missing tickers or sectors, you're done with this step.

## 5. Fetch prices

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.prices
```

Gets live prices for every ticker in `transaction_lots.csv` (Finnhub first if
you set up a key, yfinance otherwise), and appends one line per ticker to its
own history file at `data/impersonal/price_history/{TICKER}.jsonl`.

## 6. (One-time) Backfill historical prices

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.backfill
```

Pulls each ticker's full available price history (as far back as `yfinance`
has data) so drawdown/trend analysis has real history instead of a single
day. Takes a bit longer than step 5. You only need to run this once per
ticker - step 5 keeps appending to the same files daily after that.

## 7. Compute your portfolio metrics

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis
```

Prints a single JSON object to stdout with everything: per-position value and
gain/loss, sector breakdown, largest positions, high-water-mark/drawdown,
today's movers, trend over several time windows, and a real money-weighted
annualized return (XIRR) - computed from your actual purchase dates, not
estimated. Also includes a `caveats` array explaining any methodology
subtleties for that specific run (read it - it changes based on your data)
and a `stale_prices` list flagging any ticker that hasn't updated in 2+ days.

Redirect it to a file or pipe it into `json.tool` for readability:
```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m json.tool
```

It also appends `{generated_at, total_value, xirr_pct}` to
`data/personal/analysis_history.jsonl` each run, and adds a `caveats`
entry if `total_value` swung more than 20% (configurable in
`config.json`) since the previous run - a real incident (a bad
ticker mapping doubled the reported value) is what this guards against; see
[`AGENT_NOTES.md`](AGENT_NOTES.md)'s "Notable incidents".

**Note:** this step can be slow against a portfolio with many years of
backfilled history per ticker - see [`ARCHITECTURE.md`](ARCHITECTURE.md)'s
"Historical price data quality" section for a known, unresolved performance
characteristic.

## 8. Render it as markdown

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.report
```

Turns the JSON into the same markdown tables the daily report uses - Portfolio
Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete
Holdings Table, Corporate Actions, Fee Drag, XIRR Context, Data Notes - no LLM
involved, this is plain Python string formatting over the JSON above.

The Corporate Actions and Fee Drag sections only appear when there is something
in them - a holding whose lots came through a share consolidation/split, or one
whose entry fees are at least `fee_drag_notable_pct` of its current value.

## 9. Check it against the framework's hard limits

```bash
portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.compliance
```

This one runs `analysis` internally (its `main()` takes that output as
arguments rather than reading a file), so it does the work of step 7 again -
no need to pipe anything in.

Evaluates the portfolio against every allocation limit in the investment
framework - sleeve split, single-position and secure-hedge caps, top-3 and
per-sector concentration, the cash ceiling, and positions too small to pay their
own exit fee - and prints a `breaches` list. Empty means nothing to act on.

Two inputs are yours to maintain:

- **`data/personal/roles.csv`** assigns each holding a role (Core Compounder /
  Growth / Opportunistic / Defensive). The sleeve split is computed from these,
  so anything listed in `missing_roles` makes that particular check partial.
- **`data/impersonal/fee_rules.json`** holds the PRIME ETF issuer list and the
  secure-hedge ISIN list. Add a new gold/silver instrument there, not in code.

It also reports `prime_status` (parsed from the transaction ledger - worth
knowing, since without an active PRIME subscription every sell costs a fee),
`fee_history`, and `fee_drag_by_ticker`. That last one is lifetime fees per
ticker *including* closed positions, which is different from the per-position
`fees_eur` in step 7 - that counts only fees still attached to open lots. The gap
between the two is what repeated round-trips actually cost.

## Automating this without Claude

Set up your own cron job (macOS/Linux) or Task Scheduler (Windows) to run
step 5 daily, then step 7+8 shortly after. Example crontab entry (adjust the
path and time - note it still always calls the venv's own interpreter, never
a bare `python3`):
```
7 7 * * *  cd /path/to/mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.prices
25 7 * * *  cd /path/to/mcp_servers && portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis | portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.report > data/personal/daily-analysis/$(date +\%Y-\%m-\%d).md
```
This is a genuine alternative to running the MCP server for the
deterministic half of the pipeline - it just means you're maintaining your
own scheduler instead of Claude Code's, and you lose everything in "What you
lose without an LLM" below.

## What you lose without an LLM

`analysis` + `report` together produce every number and table in the daily
report - nothing about using an LLM changes any of those. What you don't get
without one:
- **An Executive Summary** - the daily task writes a few sentences of framing
  prose above the rendered tables; without an LLM you're reading the tables
  cold
- **News research on every holding** - the daily task web-searches all
  positions in parallel (one-line digest each) plus deeper context on
  whatever `analyze_portfolio` flags as a significant mover, filling in
  the Movers table's Context column, and archives each meaningful source as
  its own file under `data/impersonal/news/{TICKER}/`; running the
  pipeline yourself just gives you numbers and flagged tickers/percentages,
  not the "why" behind any of it or a record of where it came from
- **Investment analysis/advice grounded in this data** - if you ask Claude
  about a specific holding, portfolio structure, or rebalancing, it follows
  `skills/portfolio/references/INVESTMENT_FRAMEWORK.md`'s modes/signals;
  running the pipeline yourself gives you the numbers those opinions would
  be based on, not the opinions
- **Interactive ticker review** (step 4) - a human still has to eyeball the
  table either way; an LLM just makes confirming/asking follow-up questions
  faster than manually running `yfinance` lookups yourself
- **The `upload_transactions` convenience** - direct module usage means you
  place the file yourself (step 1) rather than pasting its content to a tool

Everything else - the actual financial computation, and every table in the
report - is identical either way, because it's the same deterministic Python
code in both cases.
