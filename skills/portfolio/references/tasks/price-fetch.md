# portfolio-price-fetch task instructions

Call the `portfolio` MCP server's `fetch_prices` tool (no arguments). It's
registered globally (see `../../SKILL.md`'s intro) - it runs the exact same
code as `portfolio_tools/pipeline/prices.py`, see that module for what it does.

This gets the ticker list from the computed lots (derived from real broker transactions - there is no separate holdings file), fetches live prices (Finnhub primary, yfinance backup), and appends one fully-sourced record per ticker to that ticker's price history. There is no separate prices snapshot - the newest record IS the current price, read directly by `analyze_portfolio`. Where any of that is stored is the server's business; you never open it yourself. No further action needed - this task is fetch-only.

**Running this more than once a day is safe, and does not need avoiding.** The tool appends unconditionally with no same-day check, so N runs in a day leave N records for that day in each ticker's file. `analyze_portfolio` collapses each ticker's history to the last record per calendar day when it reads, so movers stay day-over-day and no reported figure is affected. The only real costs are API calls and extra lines in the history file - don't try to "clean up" or delete the extra records, and don't skip a scheduled run because someone already fetched manually. Report a one-line summary (how many tickers resolved, any missing) and stop. Do not write the daily analysis report - that's a separate task (`portfolio-daily-analysis`).

If a ticker is missing/unmapped, that likely means a new trade happened and `compute_lots` then `enrich_lots` need to be called (in that order) - but only do that if you have reason to believe transactions changed (a fresh `upload_transactions` call); don't run them speculatively. If the tool errors, report the exact error - do not attempt to fix ticker mappings or reintroduce a manual-override file, and do not fall back to running a script via Bash instead - an MCP tool error is a real error to report (see `../../SKILL.md`'s rule 3), not something to route around.
