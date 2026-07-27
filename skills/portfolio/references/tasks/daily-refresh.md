# portfolio-daily-refresh task instructions

Run the full deterministic pipeline - two tool calls, in order:

1. Call `fetch_prices` (no arguments). Gets the ticker list from the computed
   lots (derived from real broker transactions - there is no separate
   holdings file), fetches live prices (Finnhub primary, yfinance backup),
   and appends one fully-sourced record per ticker to that ticker's price
   history. **Raises if any ticker fails on both sources** - tickers that DID
   resolve are still fetched and appended first, so a partial fetch isn't
   lost, but the call as a whole errors out. If it errors, report the exact
   error and stop (see `../../SKILL.md`'s rule 3) - do not proceed to step 2
   on an incomplete price set, do not attempt to fix ticker mappings
   yourself, and do not fall back to running a script via Bash. If a ticker
   is missing/unmapped (as opposed to a live fetch failure), that likely
   means a new trade happened and `compute_lots` then `enrich_lots` need to
   be called (in that order) - but only do that if you have reason to
   believe transactions changed (a fresh `upload_transactions` call); don't
   run them speculatively.
2. Call `create_refresh` (no arguments). Runs every remaining deterministic
   step in order - analysis, compliance, render, exit-report - and writes
   all four results into one new directory (a "refresh"), returning only
   its id (e.g. `2026-07-28/07-11-03-041233`). It stops at the first step
   that fails and reports the error the same way - do not attempt any of
   this yourself if it errors, and do not treat a partially-written refresh
   as usable; the next task that reads it (`portfolio-daily-analysis`,
   `portfolio-refresh`) already knows to skip an incomplete one.

**Running this whole task more than once a day is safe and does not need
avoiding** - `fetch_prices` still appends unconditionally (no same-day
check), and `create_refresh` writes a new directory per call rather than
overwriting a previous one. Don't skip a scheduled run because someone
already ran this manually today.

Report a one-line summary (confirmation that both calls succeeded, and the
refresh id `create_refresh` returned) and stop. Do not research news, do not
write an Executive Summary, and do not call `save_report` - all of that is
`portfolio-daily-analysis`'s job, working from the refresh this task just
wrote.
