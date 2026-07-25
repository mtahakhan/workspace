# Troubleshooting

Day-to-day operational issues you might hit while using the `portfolio`
tools, and what to check. This is a self-contained reference bundled with
the skill - it doesn't assume access to the source repo.

## Missing or stale prices

- Check `fetch_prices`'s output for which tickers failed and why
- Check `analyze_portfolio`'s `stale_prices` output field - flags any ticker
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

## A price looks off by ~100x, or in the wrong currency entirely

- The pipeline supports EUR, USD, GBP, and GBp (British pence, converted
  /100 first). Any other currency is rejected, not silently mispriced.
- If the resolved ticker is in an unsupported currency (e.g. CAD, JPY),
  `resolve_tickers` will flag it - find an EUR/USD/GBP-listed alternative
  for that ISIN instead of inventing a new conversion.

## The MCP server isn't responding

- This means the source repo's server process isn't running or isn't
  registered - not something fixable from inside a chat session, since it
  requires running a script on that machine. Tell the user to re-run
  `bootstrap.sh` from the source repo (they'll know where that is, or can
  find it - it's not something this skill can locate on its own, since it
  travels independently of the repo).
