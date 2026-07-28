# Agent notes - read this before touching any code in this repo

This file is for an agent (or human) **developing in this repository** -
modifying `portfolio_tools/pipeline/*`, `server.py`, `config.json`, the skill
bundle, or the docs themselves. It is not the portfolio skill, and it does
not get deployed anywhere - it stays in the source repo. If you're here to
*use* the deployed pipeline (calling the MCP tools day to day, for this
project or any other), that's [`skills/portfolio/SKILL.md`](../skills/portfolio/SKILL.md)
instead.

**Even though the portfolio skill won't auto-trigger in this repo** (it's
deliberately outside `.claude/` - see `ARCHITECTURE.md`'s "Deployment
model"), every behavioral rule in `skills/portfolio/SKILL.md`'s "Absolute
rules" still applies whenever you call the `portfolio` MCP tools from here -
never guess a ticker, never hand-recompute `analyze_portfolio`'s numbers,
never write ad-hoc currency-conversion code, never put an API key or raw
transactions CSV into chat. Read that file too; it's not restated here so
there's exactly one place those rules live.

For how the system actually works (data flow, file map, MCP tools, currency
handling, FIFO rules, XIRR/trend methodology, `config.json` schema), see
[`ARCHITECTURE.md`](ARCHITECTURE.md) - this file covers only rules,
workflow, and lessons already learned the hard way.

## Rules for developing in this repo

1. **Never modify a deterministic pipeline module**
   (`portfolio_tools/pipeline/lots.py`, `prices.py`, `backfill.py`,
   `analysis.py`, `tickers.py`, `report.py`, `config.py`, `uploads.py`,
   `compliance.py`, `fees.py`, `cash.py`, `exit_report.py`, `storage.py`,
   `run_store.py`, or `portfolio_tools/server.py`/`lock.py`/`paths.py`) **without first confirming
   intent with the user.** If something looks wrong or errors, the default
   action is to **report it** - what happened, why it might be happening, and
   2-3 concrete options for how to debug or fix it - and stop there. Only
   edit the code once the user has confirmed they want a change made and
   roughly how. This applies doubly during an unattended scheduled-task run
   (`portfolio-daily-refresh`, `portfolio-daily-analysis`): there's no one
   present to confirm intent, so an error there gets reported (in the report
   / via notification) and left alone, never silently patched. `config.json`
   is the deliberate exception - tuning a threshold or caveat wording there
   is a config change, not a code change, and doesn't need this same
   confirm-first treatment (see `ARCHITECTURE.md`'s "Configurable
   thresholds") - but a `config.json` edit that breaks JSON parsing or drops
   a template placeholder still surfaces as a hard error per this rule's
   spirit, not a silent fallback.
2. **Edit `skills/portfolio/references/tasks/*.md` to change scheduled-task
   behavior, never the schedule itself.** Each scheduled task's own prompt
   (`~/.claude/scheduled-tasks/{taskId}/SKILL.md`, outside this repo) is just
   a one-line pointer: invoke the `portfolio` skill, then follow
   `references/tasks/{name}.md` wherever that skill loaded from. The real
   instructions live in the bundled file itself - edit it here in the repo,
   then **re-run `bootstrap.sh`** so the globally-deployed copy the scheduler
   actually reads at runtime picks up the change. Editing only the deployed
   `~/.claude/skills/...` copy works too but drifts from the repo until the
   next `bootstrap.sh` overwrites it.
3. **Keep `ARCHITECTURE.md`'s Mermaid diagram in sync.** Any change to a
   module's inputs/outputs, the run order, a data file, or a scheduled task -
   in that file's tables, or the actual code - must land alongside a matching
   edit to the diagram in the same change. An out-of-date diagram is worse
   than no diagram.
4. **Never hardcode a data path, and never read or write data outside an MCP
   tool.** The data root is external and configurable (`PORTFOLIO_DATA_DIR`,
   else `<repo>/data/`), so a literal path is wrong on any machine configured
   differently. `paths.py` is the only module that knows the layout - every
   other module imports named constants from it and builds nothing itself.
   The same applies to agents *using* the pipeline: news sources, reports and
   ticker-map edits all go through `pipeline/storage.py`'s tools
   (`save_news_source`, `save_report`, `set_ticker_mapping`, …), never a file
   tool. This is what lets the data move without touching code, and it's why
   the metadata headers on stored news are generated rather than typed.
5. **Never duplicate information that already lives in one place.** This
   project has hit "two copies silently drifting apart" more than once (the
   Mermaid diagram vs. the prose it illustrates; `config.json`'s values
   almost got a second hardcoded copy in `pipeline/config.py`). When adding
   docs or code, ask where the *one* place for a given fact should be, and
   link to it instead of restating it.

## Skill bundle vs. this repo

`skills/portfolio/` is a **self-contained copy** - everything it references
(`references/*.md`) must resolve from within that directory alone, because
`bootstrap.sh` copies it wholesale to `~/.claude/skills/portfolio/`, where it
gets triggered from arbitrary other projects that have no access to this
repo's `docs/`. Concretely:

- Never add a cross-reference from anything under `skills/portfolio/` to
  `docs/` or anywhere else outside the skill bundle - it would silently
  break the moment the skill is deployed globally and triggered from a
  different project.
- If a skill reference file needs something from `docs/` (architecture
  detail, a rule, a historical bug account), either summarize the relevant
  part directly in the skill file, or conclude it doesn't actually belong in
  the skill (i.e. it's dev-only content, and the skill user doesn't need it
  to operate the tools correctly).
- After editing anything under `skills/portfolio/`, re-run `bootstrap.sh` to
  redeploy - it's idempotent and always replaces the global copy wholesale.

## Notable incidents (why some things are the way they are)

**This project used to run on OpenClaw** (a gateway/cron/subagent stack -
`SOUL.md`, `IDENTITY.md`, `AGENTS.md`, `HEARTBEAT.md`, `TOOLS.md`,
`MEMORY.md`, a `memory/` directory) before being rebuilt on Claude Code
scheduled tasks + this deterministic pipeline. All of that scaffolding was
removed as part of the migration. **If you ever encounter an OpenClaw-style
memory file referencing this project elsewhere** (outside this repo), it
describes the superseded, buggier system it replaced (static `holdings.csv`,
`manual_prices.json` overrides, Selenium scraping for EU tickers) - don't
trust it as a description of how this project currently works.

**Ticker guessing has a confirmed 0% success rate.** A bootstrap run by a
smaller model guessed 7 tickers instead of calling `resolve_tickers`, and
got all 7 wrong:

| ISIN (company) | Guessed | Reality |
|---|---|---|
| CA13321L1085 (Cameco) | `CCO` ($2.41, wrong company) | `CCJ` ($87) |
| DE0005557508 (Deutsche Telekom) | `DTE` | DTE Energy Co (unrelated US utility) |
| DE000A3DSV01 (Cantourage) | `HIGH` | wrong company entirely |
| GB0009895292 (AstraZeneca) | `AZN.L` (777 GBp) | works, but forced ad-hoc GBP code that didn't exist yet |
| IE00B1XNHC34 (iShares Clean Energy) | `INRG.L` (GBp) | `IQQH.DE` (EUR-native, same fund) |
| IE00B3WJKG14 (iShares S&P500 Tech) | `IITU.L` (GBp) | `QDVE.DE` (EUR-native, same fund) |
| IE000I8KRLL9 (iShares Semis) | `SEMI` | `SEC0.DE` (EUR-native) |

Same lesson twice over: (1) a bare/shorthand ticker frequently collides with
an unrelated company on a different exchange, and (2) even when a guessed
listing "works" (returns a price), it may be on a worse exchange (wrong
currency, needs an FX hop) when a EUR-native listing of the exact same
security exists. `resolve_tickers` now checks currency and ranks EUR-native
listings first specifically because of this. Historical bugs from earlier in
this project's life (before `resolve_tickers` existed), same root cause:
`CAN`→Canaan Inc instead of Cantourage Group, `IRE`→a leveraged Iren SpA ETF
instead of IREN Ltd.

**2026-07-24: the above reached a published report.** An 11:03 run of
`portfolio-daily-analysis` used a still-bad `ticker_map.csv` and reported
€32,568.97 (+64.4%) - built on fictitious/wrong tickers (`IXSK`, `XLK`
outright didn't exist in the portfolio; gold read as `EGLD`; `CAN`/`IRE` as
above). The mapping was fixed later that day and a re-run at 17:34 produced
the real number, €16,113.58 (-3.53%, XIRR -12.64%) - roughly half the
reported value. Nothing in the pipeline had flagged the first number as
suspicious even though a portfolio doubling in hours is implausible. Fix:
`analyze_portfolio` now records each run's `total_value` to
`data/personal/analysis_history.jsonl` and adds a `caveats` entry
(`check_value_divergence`) if it moved >20% since the previous run.

**2026-07-27: the displayed company name does not come from `ticker_map.csv`.**
The holding `IREN` was showing as "Iren", which reads as the unrelated Italian
utility Iren SpA; it is IREN Limited (Nasdaq, formerly Iris Energy), an AI
cloud / data-center operator. Editing `ticker_map.csv`'s `Company` column
changed nothing, because `lots.py` sources `Company` from the broker's own
`description` field in `transactions.csv` - `ticker_map.csv`'s `Company` is
only ever written and read by `resolve_tickers`, and never reaches a report.
Fix: `data/impersonal/company_overrides.csv` (ISIN, Company, Note), applied by
`lots.py`'s `load_company_overrides()`. Deliberately an opt-in table rather
than "prefer ticker_map everywhere": the broker's description stays the
default, only listed ISINs are overridden, each entry carries a Note, and
`compute_lots` prints every override it applied so a silent rename is
impossible. A missing file or blank `Company` means no override, so a fresh
clone is unaffected. Same run also recategorized IREN Energy → Technology in
`ticker_map.csv` (Technology 53.8% → 54.6%, Energy 2.6% → 1.8%; totals and
XIRR unchanged). Reports dated before 2026-07-27 keep the old name and sector
on purpose - they are records of what was reported at the time.

**2026-07-27: `fetch_prices` appends without a same-day check, so "day-over-day"
was really "since the last fetch".** `prices.py`'s `append_price_history` opens
the file in `"a"` mode unconditionally, so N runs in a day leave N records for
that day - 2026-07-24 has 9 per ticker, 07-25 has 7. `compute_movers` took
`hist[-2]` vs `hist[-1]`, which is day-over-day *only* at one record per day;
its docstring asserted "Day-over-day" while the code said "two most recent
entries". Replaying 2026-07-24 with all 9 records shows all 23 tickers
computing 0.00% (the day's last two fetches returned identical prices) against
true day-over-day moves of up to 9.26pp (SAP.DE), -8.55% (IREN), -8.04% (ARM).
The published 07-24 report escaped this by running mid-afternoon, when
`hist[-2]` happened to be a 15:27 intraday record close to the prior close -
its "-6.1%" for IREN was an 80-minute intraday delta labelled "Daily Change",
numerically near the true -5.96% by luck. Fix: `_collapse_to_daily` in
`analysis.py`, applied inside `load_ticker_history`, so every reader
(`compute_movers`, `build_value_series`, drawdown, trend) sees one record per
calendar day, last write wins. Chosen over a write-side guard because it also
corrects the already-duplicated history and keeps every fetch on disk with its
own source URL and FX rate. `get_current_prices` and the staleness check were
always correct (latest record = latest price) and are unchanged; re-running
`analyze_portfolio` after the fix reproduced every figure exactly.

**2026-07-27: a corporate-action audit that the pipeline passed, and four latent bugs
it flushed out.** A report said 3BRS.MI had been held 101 days; the position's only
transaction under its own ISIN (`XS3306517098`) is a corporate action dated
2026-04-20 with price 0,00, and the predecessor ISIN (`IE00BLRPRK35`) is not in
`ticker_map.csv` at all - so the figure looked fabricated. It was correct.
`build_lots` keys FIFO by ISIN straight from `transactions.csv` and only applies
`ticker_map` to *output*, which is why the old ISIN carries its cost basis while
having no mapping of its own. FIFO left exactly the three 2026-04-17 buys open
(1187+1500+1475 = 4162 shares, EUR 183.79), and the 650:1 consolidation carried
both cost and the original acquisition date across - 101 days, not the 98 the
corporate-action date would give. Re-running `compute_lots` reproduced the file
byte-identically. **Do not read "the source row has price 0,00" as a missing cost
basis**, and do not assume an ISIN absent from `ticker_map.csv` is invisible to the
FIFO engine - it isn't.

What the audit did surface, all now fixed: (1) the swap's two legs were paired by
"whichever swap is pending" rather than the broker's reference stem
(`537521_..._1` / `537521_...`), so two overlapping swaps would cross-wire cost
bases; (2) surviving lots were collapsed into a single lot dated at their
*weighted-average timestamp*, which was lossless here only because all three
shared 2026-04-17 - with multi-date survivors it invents a purchase date no
purchase happened on and destroys the grain later FIFO sells and tax-lot tracking
need; (3) the incoming leg's description is the bare ISIN, which was excluded by
hardcoding the literal `"XS3306517098"` rather than comparing against the row's own
ISIN; (4) the "ISINs with open positions but NO row in ticker_map.csv" warning
tested membership of a `defaultdict` instead of open shares, so it named 14
long-closed holdings (Apple, Nvidia, Snowflake, Lufthansa, United Airlines, ...)
as needing resolution. An unmatched outgoing leg now warns loudly, because a
vanished cost basis otherwise produces a perfectly well-formed lot file.

**2026-07-27: cost basis went fee-inclusive.** `load_transactions` never read the
`fee` column, so cost basis excluded every EUR 0.99 order fee. Fees are now captured
per lot (a `Fee` column in `transaction_lots.csv`, pro-rated when a partial sell
consumes a lot) and added to cost in `analysis.py`, including the XIRR cashflows -
the outflow is what actually left the account. Deliberately a separate column rather
than folded into `Purchase Price`, so the recorded price keeps meaning "what it
traded at". Effect on the 2026-07-27 figures: total cost 16,703.92 → 16,763.90
(EUR 59.98 of fees), gain -4.26% → -4.60%, portfolio XIRR -14.68% → -15.81%,
3BRS.MI -41.78% → -42.71%. **Figures in `analysis_history.jsonl` from before this
change are fee-exclusive and not directly comparable.** The new `## Fee Drag`
report section (threshold `fee_drag_notable_pct`) exists because the per-position
numbers are stark at the small end - HIGH.DE carries EUR 1.98 of entry fees against
EUR 11.36 of value, 17.4%.

**Careful: flat movers are usually the calendar, not a bug.** While chasing the
above I wrongly blamed the duplicate records for the 2026-07-25 report's five
0.0% movers. 07-25 and 07-26 were a Saturday and Sunday - the quote APIs return
the previous close, so identical prices across those days are correct. The
replay disproved the hypothesis (0.00% before *and* after the fix); the real
evidence was 07-24, a Friday. Check the weekday before treating flatness as a
defect.

**The MCP server caches pipeline modules at startup.** It is one long-running
process, so editing a `pipeline/*.py` module has *no effect* on tool calls
until it is restarted - and the tool will keep succeeding with the old code,
which looks exactly like a change that "didn't work". There is no
`server-stop` target and `scripts/server-start.sh` skips when the PID in
`.server.pid` is live, so: `kill $(cat mcp_servers/portfolio_tools/.server.pid)`
then `make server-start`. Caught while adding `company_overrides.csv` above -
`compute_lots` ran clean and silently produced the pre-change output.

**A phantom-lot FIFO bug** came from sorting transactions by date only. The
broker export lists transactions newest-first, so same-day trades tied on
the sort key and fell back to file order (backwards - latest-time-first). A
sell at 08:46 got processed before that same morning's buy at 08:23, an hour
out of sequence, fabricating an extra share of history that didn't exist.
Fixed by sorting on full date+time (see `ARCHITECTURE.md`'s "FIFO /
transaction parsing rules").

**A currency-conversion near-miss:** a bootstrap picked a London `.L`
listing quoted in GBp (pence) and invented one-off GBP conversion code
instead of recognizing the real fix was a different, EUR-native listing.
GBp support is now built into `pipeline/prices.py`/`pipeline/backfill.py`
permanently, so this specific gap shouldn't recur - but the general
principle (unsupported currency means the ticker/listing is wrong, not a
missing conversion path) holds for any future currency: adding one is a
deliberate call by whoever maintains this repo (as DKK was, for
Copenhagen-listed securities - see `ARCHITECTURE.md`'s "Currency handling"),
never an agent's own workaround for a single flagged ISIN.

**A split-adjustment data bug:** `yfinance`'s historical data for some
thinly-traded/leveraged ETPs isn't retroactively adjusted for later reverse
splits. A 3x daily leveraged short-oil ETC in this project showed
~€220,000 in Jan 2016 (a real historical price level before later reverse
splits) vs ~€14.50 today - both numbers are "real" in isolation, but not on
the same split-adjusted share-count basis, so multiplying by today's share
count silently corrupted any EUR-value computation. Fixed by dropping
historical points more than 100x from the current price (see
`ARCHITECTURE.md`'s "Historical price data quality").

**A trend-methodology bug:** using full price history for
`trend.since_inception` produced **+57,000%**, using a Siemens price from
1996, because the portfolio (in its current form) didn't exist until 2024.
Fixed by anchoring `since_inception` to the earliest actual purchase date in
`transaction_lots.csv` instead (see `ARCHITECTURE.md`'s "Trend vs.
drawdown").

**A serial web-search timeout:** an earlier version of the daily-analysis
task did a full per-ticker deep-dive *serially* across all 23 holdings and
timed out (600s, no output). The fix was dispatching as one parallel batch,
not narrowing scope back down to movers only - full-portfolio coverage is
fine as long as it's parallel.

**A notification-signal cleanup:** an earlier version of the daily task left
"large move" undefined and included "target breached" as a notify reason -
that phrase never corresponded to any tracked data (no price-target field
exists anywhere in this pipeline) and was removed rather than implemented;
revisit if per-position price targets are ever actually added.

**2026-07-27: `cash.py` was corrupted by Security transfer amounts from the
broker migration.** The Dec 2025 Scalable Capital migration (Baader Bank →
Scalable) produced 12 `Security transfer` rows in the export. `lots.py`
already excluded these as migration artifacts (the shares net to zero per
ISIN). But `cash.py` summed their `amount` column too - and the two legs of
each transfer were valued at different prices on different dates (outgoing at
Baader's Dec 5 NAV, incoming at Scalable's Dec 6 NAV), so their amounts do
NOT net to zero. The result was a phantom +€13.20 in the reported cash
balance. Fix: `load_cash_rows()` now skips `type == "Security transfer"` rows
with the same `continue` `lots.py` uses, and the module docstring explains why.
The corrected balance dropped from €8.92 → −€4.28, which correctly triggers
the "implausible negative" warning because the export was also missing a small
number of executed trades from after 2026-07-16 (confirmed by comparing against
the broker's displayed balance of €0.73). **The rule: any time `cash.py` reports
a negative balance on a supposedly complete export, the first suspect is either
missing rows or a new type of non-cash Security row that must be excluded.**

**2026-07-28: correction to the note above, and a real bug in
`exit_report.py`'s staleness check.** The "export was also missing executed
trades from after 2026-07-16" claim two paragraphs up was itself wrong. A full
audit (independently re-deriving every capital-flow, cash-balance, and FIFO
realized-gain figure by hand from the raw CSV, in a session with no memory of
writing the original fix) matched `exit_report.py`'s output to the cent, and
the user confirmed no transactions occurred after 2026-07-16. The export was
never incomplete - the code's own staleness check was the bug:

```python
last_tx_date = ...  # date of the last EXECUTED row
export_stale_days = (today - last_tx_date).days
if export_stale_days > 1:
    cash_complete = False
    stale_note = "Transaction export is N days old... Re-download..."
```

This conflates "days since the last **executed** trade" with "days since the
**export was downloaded**." They are independent: a user can go quiet for
weeks on a perfectly fresh, complete export. Proof it was a false positive
here: the raw file contained `Pending`/`Cancelled` order rows dated through
2026-07-24 - eight days *after* the flagged "stale" cutoff - which only exist
if the export was pulled recently. **Fix:** the auto-warning is removed;
`generate_exit_report` now surfaces `last_executed_transaction_date` and
`days_since_last_executed_transaction` as plain facts in the `cash` section,
with no inference about export completeness attached. `cash.py`'s own
implausible-negative check (the -€1.00 threshold, unrelated code path) is
untouched and still flags -€4.28 independently - whether *that* threshold or
diagnosis is actually correct remains an open question, not resolved by this
fix. **The rule: a "quiet period, then a stale-data warning" pattern is worth
checking for this exact conflation before trusting the warning - lack of
recent activity is not evidence of missing data.**

**2026-07-28: `analyze_portfolio`/`check_compliance`/`render_report`/
`generate_exit_report` collapsed from four stateful MCP tools into one
`create_refresh` call, writing a "refresh" directory instead of four
independent files.** The original four each took no arguments *except* that
three of them required the caller to pass `analyze_portfolio`'s dict back in
as an `analysis` argument - fine within one task's own conversation, but it
meant `portfolio-daily-analysis` (which has no memory of
`portfolio-daily-refresh`'s conversation - they're separate scheduled
invocations) had to call all four itself just to get numbers it could have
read off disk. An intermediate design (this same day, superseded before
ship) tried fixing that by giving each of the four its own timestamped file
under `pipeline-runs/{tool}/*.json` and a matching `get_*` tool - stateless,
but eight tools for four computations, and four directories to keep in sync
by convention rather than by construction.

The shipped design: `portfolio-daily-refresh` now calls exactly two tools -
`fetch_prices`, then `create_refresh` - and `create_refresh` runs all four
steps in one call, each reading the previous step's result in memory (never
from a file, never as a passed argument) and writing its own file into one
new directory: `pipeline-runs/{date}/{time}/{analysis,compliance,render,
exit-report}`. The call returns only that directory's id. `portfolio-daily-
analysis` reads it back with one tool, `get_refresh(kind, refresh_id)`, and
`list_refreshes(date)` lists what's available (flagging `[valid]` vs.
`[INCOMPLETE]`). Net surface: 4 tools instead of 8, one directory instead of
four, and the two scheduled tasks stay fully independent - nothing computed
by one is ever an argument to a tool the other calls.

`create_refresh` deliberately stops at the first step that fails rather
than attempting the rest - a mid-run failure leaves an incomplete
directory (fewer than four files), and every reader (`get_refresh`,
`list_refreshes`, the task instructions) treats that as unusable and falls
back to another valid refresh from the same day, or a fresh `create_refresh`
call. This was a deliberate choice over a "best-effort, run all four
independently" alternative: compliance/render/exit-report don't actually
depend on each other (only on analysis), so best-effort would salvage more
of a broken run - but it would also make "which steps actually ran" a thing
every reader has to reason about per-refresh, instead of a single valid/
invalid flag. Stop-on-first-failure was chosen to keep that binary.

Same day, a second, independent gap got fixed while this was in flight:
`fetch_prices` never raised on a per-ticker miss (both Finnhub and yfinance
failing for one ticker) - it only printed to stdout, and that stdout was the
*only* place the failure was visible, via the old tool's return value. Under
the new design `fetch_prices` returns almost nothing on success (by design -
see `create_refresh`'s docstring), which would have made a silent miss
completely invisible. Fix: `pipeline/prices.py`'s `main()` now raises after
appending whatever *did* succeed, so a partial fetch isn't lost but the tool
call surfaces as a real error - the caller is expected to stop and report it
rather than proceed to `create_refresh` on an incomplete price set (same
"report and stop" rule as everywhere else in this pipeline).

**2026-07-28: 3BRS.MI (a 3x leveraged inverse Brent ETP) was the single
worst-performing position in the book - down 42.7% total return, the worst
XIRR of any holding - and nothing in the report flagged it.** Root cause:
every "something's wrong here" mechanism in `analysis.py` was gated on the
56-day `trend_movers` window (`compute_trend_movers`, and the `deep_drawdown`
notify check that reads from it). 3BRS.MI's 56-day return was **+12.37%** -
it fell sharply on a Brent spike, then partly recovered as oil eased, and
that whipsaw netted the medium window out to a number nowhere near the
notable threshold. The position's *total* return since purchase was still
terrible; the window-based checks simply never looked at that number. A
second, independent gap made it worse: `roles.csv` already carried a note on
this exact ticker - *"Fits no role in a 2-5yr framework; 3x daily-reset
decays structurally. Placed here by default."* - written by a prior session,
but nothing in the pipeline or the report task ever read `Note` back into
automated output; it just sat in the CSV waiting for someone to remember to
call `read_roles`.

Two fixes, deliberately independent of each other and of the existing
window-based checks (see AGENT_NOTES.md rule 5 - the fix is a new
orthogonal check, not a patch to the window logic, precisely because
patching the window would just move the blind spot rather than removing
it):

1. **`compute_underwater_positions()` in `analysis.py`** flags any position
   whose `gain_pct` (total, non-annualized return - anchored to the
   purchase price, immune to whipsaws by construction) is `<=
   -thresholds.underwater_notable_pct` (25% by default). Returned as
   `underwater_positions`, rendered as its own `## Underwater Positions`
   section in `report.py` (parallel to, not a replacement for, Trend
   Movers), and wired into `notify_reasons`/`notable` on its own - it does
   not depend on `trend_movers` membership at all.
2. **`role_notes` in `compliance.py`** - `_load_roles()` now captures
   `Note` alongside `Role`, and `check_compliance` returns every position
   whose role carries one, unconditionally. `daily-analysis.md` now
   requires treating a role note describing a real framework-fit problem
   (as opposed to just a rationale for the role label) as a strong prior
   toward escalating in `## Signals & Actions` - see also
   `INVESTMENT_FRAMEWORK.md`'s Sell Discipline, which now has an explicit
   bullet for "the instrument itself is structurally unsuited to being held
   at all," independent of whether its underlying thesis is fine.

**The rule this generalizes to:** a windowed/threshold check (movers,
trend_movers, any future one) only catches a problem whose *shape* matches
the window - a slow bleed, a whipsaw, or a problem that predates the
window's start can all hide from it by construction. When a position turns
out to be a bad investment that nothing flagged, the fix is essentially
never "widen the window" (that just relocates the blind spot); it's asking
whether a *different, window-independent* signal (total return since
purchase, a structural property of the instrument itself, a human-authored
annotation already sitting in the data) would have caught it, and adding
that as its own check rather than retrofitting the existing one.
