# Troubleshooting

Day-to-day operational issues you might hit while using the `portfolio`
tools, and what to check. This is a self-contained reference bundled with
the skill - it doesn't assume access to the source repo.

## Missing or stale prices

- Check `fetch_prices`'s output for which tickers failed and why
- Check the analysis step's `stale_prices` field (`get_refresh(kind="analysis")` -
  `create_refresh` itself only returns a refresh id) - flags any ticker
  whose last price-history entry is 2+ days old
- Verify the ticker is still the correct exchange symbol (companies
  occasionally change listings) - ask the user to confirm if unsure
- Call `fetch_prices` again

## `transaction_lots.csv` share counts look wrong

- Call `compute_lots` again - it reports current positions and flags any
  ISIN missing a ticker mapping, or a mapping with a blank Sector
- If a same-day buy/sell pair looks mis-sequenced, that's a transaction
  ordering issue in the source data - report it rather than trying to
  reason out the correct order yourself

## Prices look wrong

- Confirm the resolved ticker is actually the security held - a
  wrong/ambiguous ticker can silently resolve to an unrelated company. This
  is the single biggest real bug source in this project's history. **Always
  resolve new tickers via `resolve_tickers`, never by guessing a shorthand
  symbol** - see SKILL.md's Absolute Rules.
- Check the broker account for any splits/adjustments
- Finnhub prices are ~5 min delayed (not real-time)

## Several records for the same day in a price-history file

Expected, not a bug. `fetch_prices` appends with no same-day check, so each run
in a day adds a record per ticker (2026-07-24 has 9). `analyze_portfolio`
collapses each ticker to the **last record per calendar day** when it reads
(`_collapse_to_daily` in `pipeline/analysis.py`), so movers stay day-over-day
and no reported figure is affected.

- **Do not delete the extra records or hand-edit the `.jsonl` files.** Each
  record carries its own timestamp, source URL and FX rate - that is an audit
  trail, and the readers already ignore the duplicates.
- **Do not skip a scheduled fetch** because someone already ran one manually.
- Be aware `backfill_history` rewrites a file at one record per day, so running
  it discards the extra intraday records for every day it covers.
- If movers look like an intraday move rather than a day-over-day one, that
  means the collapse isn't being applied - check that the MCP server was
  restarted after any change to `analysis.py` (it caches modules at startup).

## All movers show 0.0%, or every ticker is flat

Check the day of week first. On a weekend or market holiday the quote APIs
return the previous close, so consecutive days genuinely carry identical
prices and 0.0% across the board is correct output, not a fault. 2026-07-25
and 07-26 (Saturday/Sunday) look exactly like this. Only treat it as a bug if
it happens on a trading day.

## A price looks off by ~100x, or in the wrong currency entirely

- The pipeline supports EUR, USD, GBP, GBp (British pence, converted
  /100 first), and DKK. Any other currency is rejected, not silently mispriced.
- If the resolved ticker is in an unsupported currency (e.g. CAD, JPY),
  `resolve_tickers` will flag it - find an EUR/USD/GBP/DKK-listed alternative
  for that ISIN instead of inventing a new conversion.

## The MCP server isn't responding

- Not fixable from inside a chat session - it requires running a script on
  that machine. Tell the user to, from the source repo (they'll know where
  that is, or can find it - it's not something this skill can locate on its
  own, since it travels independently of the repo):
  - Run `make bootstrap` if the server process itself has died (common after
    a machine sleep/reboot - it's a background process, not a login service)
  - Run `make claude-setup` if the server's running but the registration
    itself is missing or stale (`claude mcp get portfolio` doesn't say
    "Connected")
