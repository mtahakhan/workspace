# First-run setup

This file is instructions for Claude, not the human user - follow it
whenever `upload_transactions` hasn't been called yet (no
`portfolio_mcp/data/manual/transactions.csv` - see `../CLAUDE.md`). Unlike a
typical onboarding doc, this one stays in the repo permanently - it's generic
setup instructions, not personalized content, so future re-clones (by this
user or anyone else) need it too. Each step below checks its own precondition
first, so this is safe to resume if it's interrupted partway through - never
skip a step just because a later one looks done.

**Read `AGENT_NOTES.md` before Step 4** - it has the full rule set
and bug history behind this setup's most error-prone step. Don't try to infer
the rules by reading the Python source; they're already written down there.

## Step 0: Confirm the server is actually running

The `portfolio` MCP tools only exist if `bootstrap.sh` (repo root) has been
run. If they're not available, tell the user to run `./bootstrap.sh` from a
terminal first (it needs a Python >=3.10 interpreter on the machine, and the
`claude` CLI) - you can't do this step for them, since it changes their local
Claude Code configuration, not just this repo's files. Once it's done, a new
Claude Code session will have the tools available.

## Step 1: Brief the user

Read the **"What This Does"** section of `README.md` and present it
to the user close to verbatim (that section is the single source of truth for
this briefing - don't improvise your own summary of what the pipeline does,
so the briefing stays consistent across every fresh setup). Then tell them
you'll walk through setup: API key, their transaction history, then a few
quick questions about any new holdings.

## Step 2: API key

Check if `portfolio_mcp/.env` exists. **Never ask the user to paste their API
key into chat** - it would end up in the session transcript. Instead:

1. If `portfolio_mcp/.env` doesn't exist, copy `portfolio_mcp/.env.example`
   to `portfolio_mcp/.env` (the example file just has a placeholder, safe to
   copy)
2. Point the user to the "Getting a Finnhub API key" section of
   `README.md` (free signup, no card required) and ask them to open
   `portfolio_mcp/.env` themselves and replace the placeholder with their
   real key - wherever the server is actually running (see
   `AGENT_NOTES.md`'s "Deployment model" if that's not obvious to you)
3. Tell them plainly that yfinance alone (no key at all) also fully works if
   they'd rather skip this entirely - Finnhub is a fallback/speed improvement
   for US tickers, not a requirement
4. To check whether they've filled it in, only check for the *absence* of the
   placeholder text (e.g. `grep -q your_key_here portfolio_mcp/.env`) - don't
   read/print/echo the actual file contents back, so the real key never
   appears in your own output either

## Step 3: Get their transaction history

Ask the user to export their transaction history from their broker, then
call the **`upload_transactions`** MCP tool with the raw CSV content -
**never ask them to paste it into chat as prose first**, the tool call
itself is already the minimal-exposure path (see `AGENT_NOTES.md` rule 5).
Tell them plainly: **this currently only parses Scalable Capital's export
format** (semicolon-delimited, German decimal commas, columns:
date;time;status;reference;description;assetType;type;isin;shares;price;amount;fee;tax;currency).
`upload_transactions` checks the header and rejects anything that doesn't
match this shape - if it does, and they're on a different broker, say so
clearly and offer to look at `portfolio_mcp/pipeline/lots.py`'s
`load_transactions()` together to adapt it, rather than silently guessing at
their format.

## Step 4: Resolve tickers - call the tools, DO NOT guess tickers yourself

**This is the single most error-prone step in the whole setup. Follow it
exactly, in this exact order. Do not skip the tool calls and reason it out
yourself, even if you're confident.** A prior bootstrap run guessed tickers by
reasoning instead of calling these tools and got 7 out of 7 wrong - including
picking wrong companies entirely (a bare `CCO` resolved to a $2.41 stock, not
Cameco/`CCJ` at $87) and picking London listings priced in GBp (pence, not
pounds) that then required inventing currency-conversion code that didn't
exist. None of that is hypothetical - it already happened once.

Call these two MCP tools, in order:

1. **`compute_lots`** - reports which ISINs have an open position but no
   `data/ticker_map.csv` row yet.
2. **`resolve_tickers`** - looks each one up via a real `yfinance` search
   (not a guess), checks its actual currency and price, and APPENDS a
   proposed row to `data/ticker_map.csv` (a shared file - it never overwrites
   existing rows). Returns a review table like this:

```
  Deutsche Telekom                   DE0005557508  ->  DTE.DE     26.26 EUR
  Cameco                             CA13321L1085  ->  CCO.TO     122.74 CAD
      ⚠ UNSUPPORTED CURRENCY CAD - find a EUR/USD/GBP listing
```

For every line in that table:
1. Read the company name and the picked ticker together - do they look like
   the same company? (A price that's wildly different from what you'd expect,
   or a currency you didn't expect, usually means it's the wrong company or
   wrong listing - that's the point of showing you the price.)
2. If a line has a `⚠` warning, it needs a manual fix in `data/ticker_map.csv`:
   open the file, replace that ticker with a better one, and verify the new
   one with `python3 -c "import yfinance as yf; print(yf.Ticker('TICKER').fast_info)"`
   before trusting it - check `currency` is one of EUR/USD/GBP/GBp.
3. If you are not fully sure a pick is right, ask the user to confirm before
   moving on - don't silently accept an uncertain pick.

Once every row looks right, fill in the blank Sector column directly in
`data/ticker_map.csv` for each new row (it's `ISIN,Ticker,Company,Sector` - one
file, all four columns, shared and committed) - ask the user what taxonomy
they want (Technology, Healthcare, Commodities, etc; there's no fixed list,
this one's just their preference).

Call **`compute_lots`** again after all of this. It will now report two
separate things if anything is still missing: ISINs with no
`data/ticker_map.csv` row at all (call `resolve_tickers` again, or fix
manually), and rows that have a Ticker but a blank Sector (fill it in).
Repeat until neither list has entries, and the reported position share
counts look sane to the user.

## Step 5: Fetch prices and seed history

Call **`fetch_prices`** (live prices) then **`backfill_history`** (full
historical backfill per ticker, needed for accurate drawdown/trend - takes a
little longer, uses `period="max"` by default). Report any tickers that
failed to resolve and work through them the same way as Step 4 (usually
means the ticker in `data/ticker_map.csv` isn't quite right, or is in a
currency the pipeline doesn't support - see README's "Supported currencies").

## Step 6: Verify the numbers

Call **`analyze_portfolio`** and show the user the resulting portfolio
value, gain/loss, and any entries in `caveats` or `stale_prices`. Confirm the
total roughly matches what they'd expect before considering setup done - this
is the same kind of sanity check that caught several real bugs during this
pipeline's own development (wrong tickers, unadjusted stock splits, phantom
FIFO lots from a sort-order bug) - don't skip it just because the tool call
returned without an error.

## Step 7: Set up daily automation

Check `mcp__scheduled-tasks__list_scheduled_tasks` for tasks named
`portfolio-price-fetch` and `portfolio-daily-analysis`. If either is missing,
create it: the schedule's `prompt` should be a one-line pointer ("read and
follow `tasks/price-fetch.md`" / `.../daily-analysis.md`) - the real
instructions already live in those files, don't inline them into the schedule
prompt (see README's "Daily Workflow" section for why). Suggested timing:
price-fetch a few minutes before daily-analysis, both once daily; ask the user
if they'd prefer a different time or frequency.

## Done

Tell the user setup is complete and summarize what will now happen
automatically each day. Do not delete this file - it's meant to stay for next
time (a new machine, a reset, someone else cloning the repo).
