# portfolio-refresh task instructions (on-demand)

Trigger: a chat request to refresh or re-run something mid-day - "refresh
the news", "rerun the analysis", "get me updated numbers", "redo today's
report", "pull fresh prices and redo the report". This is **not** one of
the two scheduled tasks (`portfolio-price-fetch` / `portfolio-daily-analysis`,
which still run automatically once a day each on their own schedule) - it's
the ad hoc equivalent, invoked directly from a chat session whenever the
user wants an update without waiting for the next scheduled cycle.

There are two operations. Figure out which was asked for; if genuinely
ambiguous, ask.

- **Full refresh** ("rerun the analysis", "get fresh prices/numbers", "pull
  fresh prices and redo the report") - always the complete deterministic
  pass, never a partial one: follow `price-fetch.md` exactly (`fetch_prices`
  then `create_refresh`). There is no "just the numbers, skip a step" mode -
  a refresh is atomic. Report the same one-line summary `price-fetch.md`
  calls for.
- **News/report regeneration** ("refresh the news", "redo the Executive
  Summary", "regenerate today's report") - reuses an existing refresh
  rather than creating a new one, unless none exists yet for today (see
  below).

If the user wants both - a full refresh AND a regenerated report from it -
do the full refresh first, then regenerate from what it just produced.

## News/report regeneration

Call `list_refreshes` with today's date. Look at the results:

- **If there's at least one `[valid]` entry**, follow `daily-analysis.md`'s
  steps 1-9. Its `get_refresh` calls default to the latest valid refresh
  overall, which will be the one you just confirmed exists for today unless
  the user asked to use a specific *older* refresh from today (e.g. "use
  this morning's numbers, not just now's") - in that case pass that
  refresh's id as `get_refresh`'s `refresh_id` argument for every call in
  that task instead of leaving it blank, so every section comes from the
  same refresh consistently.
- **If every entry is `[INCOMPLETE]`, or `list_refreshes` reports nothing
  for today**, there is no valid data to build a report from yet - say so
  plainly (a report can't be refreshed if a valid refresh doesn't exist),
  then do a full refresh first (`price-fetch.md`'s two calls), and continue
  into `daily-analysis.md` using that new refresh.

`save_report` always replaces today's file rather than duplicating it (see
`../../SKILL.md`), so regenerating the report - with or without a preceding
full refresh - is safe to repeat as many times as the user wants within the
same day. Every refresh directory from earlier today (including this
morning's scheduled one) stays on disk untouched; only the saved report
itself gets replaced.
