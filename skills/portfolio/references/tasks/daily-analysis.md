# portfolio-daily-analysis task instructions

Generate today's portfolio analysis report. This is a separate scheduled
invocation from `portfolio-price-fetch` with no memory of it - it never
calls `fetch_prices` or `create_refresh` itself. Both already ran earlier
today as part of `portfolio-price-fetch` (see `price-fetch.md`), producing
one refresh directory with four files (analysis, compliance, render,
exit-report) and returning only its id. This task's only job is to read
that refresh back - always through the `get_refresh` MCP tool, never a file
tool or Bash, same rule as everything else in this pipeline (see
`../../SKILL.md`'s "Never touch the filesystem") - then add the parts that
need a model: news research and the Executive Summary.

`get_refresh` with no `refresh_id` always resolves to the latest **valid**
refresh (one with all four files) - an incomplete refresh from a failed run
is skipped automatically. If it comes back "No valid refresh..."
(everything today is missing or incomplete), `portfolio-price-fetch` hasn't
successfully run yet today - report that plainly and stop. Don't work
around it by calling `fetch_prices` or any deterministic tool yourself;
that's `portfolio-price-fetch`'s job (or `portfolio-refresh` if the user
explicitly asks for an on-demand refresh - see `refresh.md`), and running it
from here would defeat the point of keeping the two tasks independent.

Steps:
1. Call `get_refresh` with `kind="analysis"` (no `refresh_id`). This is the
   JSON `analyze_portfolio` computed as part of today's refresh:
   position/portfolio value, cost basis, gain/loss, sector concentration,
   largest positions, high-water-mark/drawdown, daily movers, trend
   (since-inception/30d/90d/365d), `annualized_returns` (real XIRR, not an
   estimate), `trend_movers` (positions whose medium-window move breaches
   the notable threshold), per-position `trend_30d_pct`/`trend_56d_pct`/
   `drawdown_from_high_pct`, `stale_prices`, `caveats`, and
   `notable`/`notify_reasons`. Do NOT recompute any of these numbers
   yourself by reasoning over the raw data - use exactly what's in this
   JSON. If a number looks wrong, that's a bug to fix in
   `portfolio_tools/pipeline/analysis.py` (confirm with the user first, see
   `../../SKILL.md` rule 3), not something to override by hand.
2. Call `get_refresh` with `kind="render"` (no `refresh_id`) - the markdown
   `render_report` already produced from the same refresh: Portfolio
   Overview, Trend, Sector Breakdown, Largest Positions, Movers (numbers
   only), Trend Movers, Complete Holdings Table, Corporate Actions, Fee
   Drag, XIRR Context, and Data Notes. Do NOT hand-transcribe numbers out of
   step 1's JSON into your own tables/prose - every figure in those
   sections must come from this markdown, not from you retyping the JSON.
   If a section needs to look different, that's a change to make in
   `portfolio_tools/pipeline/report.py` (confirm with the user first), not
   a bypass for one run.
3. Read the caveats/Data Notes from step 1's JSON and respect them - in
   particular: `annualized_returns.portfolio_xirr_pct` (not `gain_pct`) is
   the figure to check against the 10-15%/yr target, don't over-interpret
   any single position's XIRR without checking its
   `weighted_avg_holding_days` first (short holding periods produce
   mathematically extreme annualized numbers - that's correct math, not
   noteworthy on its own; the XIRR Context table in step 2 already flags
   these), flag anything in `stale_prices`, and treat a value-divergence
   caveat as a signal to investigate (check the ticker map with
   `read_ticker_map` for a mapping bug, a corrupted price history point,
   etc.) before writing the report, not something to report as a genuine
   market move without checking. If `annualized_returns.tickers_without_lot_data`
   is non-empty, note it as a data gap in the report - fixing it (running
   `compute_lots`/`enrich_lots`/`resolve_tickers`) is `portfolio-price-fetch`'s
   job on its next run, not something to trigger from here.
4. Call `get_refresh` with `kind="compliance"` (no `refresh_id`). It encodes
   every hard limit in `../INVESTMENT_FRAMEWORK.md` (sleeve split, max
   single non-hedge position, secure-hedge cap, top-3 combined, sector
   concentration, cash ceiling, sub-EUR 250 positions) and has a structured
   `breaches` list - empty means nothing to act on. **Never re-evaluate
   these limits yourself in prose, and never restate a limit against a
   figure you transcribed by hand**; report what this JSON says. Any breach
   is exactly the kind of thing step 9's `## Signals & Actions` section
   exists for. It also has `prime_status`, `fee_history`, and
   `fee_drag_by_ticker` (lifetime fees per ticker including closed
   positions - distinct from step 1's per-position `fees_eur`, which counts
   only fees still attached to open lots; the gap between the two is what
   churn cost). If `missing_roles` is non-empty the sleeve check is partial
   - say so rather than reporting the split as authoritative, and use
   `set_position_role` to fill gaps.
5. Call `get_refresh` with `kind="exit_report"` (no `refresh_id`). It
   answers "if I sold everything today and exited Scalable Capital, what's
   my net gain/loss?" - capital flows, realized FIFO gain on closed
   positions, income, taxes, fees, and a hypothetical-exit summary. Condense
   it into a **small** `## Exit Summary` section for the report - a handful
   of lines, not the full multi-table breakdown: net capital in, realized
   gain (all-time), unrealized gain (open positions), hypothetical exit
   value, net P&L, total fees paid, net tax cost. Do not hand-transcribe or
   recompute any of these figures - take them directly from this JSON, same
   rule as step 2. Include the `cash` section's
   `last_executed_transaction_date` / `days_since_last_executed_transaction`
   as a plain fact (e.g. "last trade: 2026-07-16, 12 days ago") - it is
   informational only, **not** a data-completeness signal on its own; a
   long gap just means no trades happened. Separately, check the `cash`
   section's `complete`/`note` fields (from `cash.py`'s own
   implausible-negative check, independent of trade recency) - if
   `complete` is `false`, say so plainly and treat the cash balance /
   hypothetical exit value as unreliable for that reason, the same way
   `stale_prices` is treated elsewhere in this task. Do not infer
   staleness from the transaction-date gap yourself - an earlier version of
   this tool did exactly that and produced a false "export is stale"
   warning on 2026-07-27 that had to be corrected (see
   `docs/AGENT_NOTES.md`, 2026-07-28 entry, in the source repo).
6. Research news for every holding, not just movers - but dispatch it as
   ONE parallel batch of WebSearch calls (all tickers in a single
   message/turn), never a serial loop over tickers one at a time. A prior
   version of this pipeline timed out (600s, no output) doing a full
   per-ticker deep-dive *serially* - the fix is parallel dispatch, not
   narrowing scope back down to movers only (see `../../SKILL.md`'s rule
   6). Three tiers of depth from the same batch, using step 1's JSON for
   the ticker lists:
   - **6a. Day-over-day movers** — the tickers in step 1's `movers` output
     (also the Movers table in step 2's markdown): query for today's news
     as usual (e.g. `"QBTS stock news [month year]"`). Fill the context
     note into the Movers table's `Context` column.
   - **6b. Trend movers** — the tickers in step 1's `trend_movers` output
     (also the Trend Movers table): query with the trend direction as
     context, not today's headlines. Use a query like `"why is Arm
     Holdings down since May 2026"` or `"IONQ stock decline 2026"` — this
     returns cause, not just news. Also call `list_news` for each of these
     tickers and, for any stored sources within the last 14 days, call
     `get_news_source` to read the prior coverage: if today's research
     repeats the same narrative as two weeks ago, say "third week of the
     same de-rating" rather than re-discovering it. Fill the `Why` column
     in the Trend Movers table with a one-to-two sentence cause summary. If
     a ticker appears in both movers and trend_movers, give it a combined
     note covering both timeframes.
   - **6c. All other holdings** — a short one-line note per ticker in a new
     **Holdings News Digest** section. If nothing notable turns up, write
     "No News" rather than omitting it — every holding should appear.
   - For every distinct source (URL) that actually contributed to a note —
     i.e. deemed meaningful, not every raw search hit, and skip
     near-duplicate coverage of the same story — call the
     `save_news_source` MCP tool once, passing `ticker`, `company`,
     `source_url`, `title`, the `text` you actually used, and
     `fetch_method` set to the real query you ran (e.g. `WebSearch (query:
     "ARM stock decline May 2026")`). The server generates the timestamp,
     filename and metadata header — don't construct any of that yourself,
     and don't write the file with a file tool. "No News" tickers get no
     call.
7. Save the report with the `save_report` MCP tool (no date argument - it
   defaults to today), in this order: a `## Signals & Actions` section **if
   and only if** step 8 produced anything, then your own Executive Summary
   prose, then step 2's rendered markdown (with the Movers Context and
   Trend Movers Why columns filled in), then the `## Exit Summary` section
   from step 5, then the Holdings News Digest section appended after it.
   Re-saving replaces that day's report rather than duplicating it, so a
   corrected re-run is safe. Use `get_report` if you need to compare
   against a previous day. This is the only step that should involve you
   writing prose/tables by hand - everything else comes from data already
   computed and rendered by `portfolio-price-fetch`. For the Executive
   Summary's framing and vocabulary (signals, portfolio roles, sell
   discipline), follow `../INVESTMENT_FRAMEWORK.md` - but keep rule 8 below
   in mind: it doesn't mean forcing a BUY/HOLD/TRIM/EXIT signal onto every
   position every day.
8. Only include prescriptive action recommendations when something
   genuinely warrants it - not every day. **When there is one, it goes in
   its own `## Signals & Actions` section at the very top of the report,
   never inline in the Executive Summary prose.** Every other section of
   the report has a scannable `##` heading, so an actionable call buried
   mid-paragraph is the one thing a reader cannot jump to - this happened
   on 2026-07-27, where a TRIM/EXIT call sat in the fifth paragraph of a
   seven-paragraph summary and the user could not find it. Give each call
   its signal (🟢/🟡/🟠/🔴), the position, an action (Increase/Maintain/
   Reduce/Close), the reasoning, and any execution caveat (EUR 250 minimum
   order size, the EUR 0.99 exit fee, or a `## Fee Drag` row showing fees
   are already a material share of the position). **Sleeve-aware
   escalation rule for trend data**: a large 56d drawdown in
   `trend_movers` is not automatically a sell signal — interpret it in the
   context of the position's sleeve:
   - *Core (3-5yr horizon)*: sustained drawdown is noise unless it breaks
     the original thesis. Only escalate to 🟠/🔴 if the `Why` research in
     step 6b identifies a structural change (business model, competitive
     position, regulation) — not a sector rotation or macro headwind
     alone.
   - *Tactical (catalyst-driven)*: check whether the catalyst is still
     live. If the move is working against the thesis and the original
     horizon has passed, 🟡/🟠 is appropriate even without a thesis break.
   - *Hedge*: drawdown in a hedge is expected during risk-on moves; only
     flag if the hedge is correlating with the rest of the book.
   - Use step 4's `missing_roles` output to identify positions without a
     sleeve assignment — those cannot be interpreted this way, and the gap
     should be noted. On a day with nothing to act on, omit the section
     entirely rather than emitting an empty one - its presence is itself
     the signal that something needs attention.
9. Send a push notification only if step 1's JSON has `"notable": true` -
   use `notify_reasons` as the notification content. This is a fixed rule
   evaluated by `analyze_portfolio` itself when it ran earlier as part of
   `create_refresh` (large mover >= `MOVER_NOTABLE_THRESHOLD_PCT`, stale
   prices, or a value-divergence caveat), not a daily judgment call - don't
   notify on your own assessment of "notable" if the field is `false`, and
   don't skip notifying if it's `true`.

This is intended to be extended with additional research dimensions later -
keep the report structure additive (new sections can be appended) rather
than assuming this is the final scope. If you add a new computed indicator,
add it to `portfolio_tools/pipeline/analysis.py` (numbers) and
`portfolio_tools/pipeline/report.py` (its markdown rendering) so it stays
deterministic rather than computing or formatting it ad hoc in this file.
