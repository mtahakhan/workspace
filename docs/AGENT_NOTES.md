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
   `analysis.py`, `tickers.py`, `report.py`, `config.py`, `uploads.py`, or
   `portfolio_tools/server.py`/`lock.py`/`paths.py`) **without first confirming
   intent with the user.** If something looks wrong or errors, the default
   action is to **report it** - what happened, why it might be happening, and
   2-3 concrete options for how to debug or fix it - and stop there. Only
   edit the code once the user has confirmed they want a change made and
   roughly how. This applies doubly during an unattended scheduled-task run
   (`portfolio-price-fetch`, `portfolio-daily-analysis`): there's no one
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
4. **Never duplicate information that already lives in one place.** This
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
`data/analysis_history.jsonl` and adds a `caveats` entry
(`check_value_divergence`) if it moved >20% since the previous run.

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
missing conversion path) holds for any future currency.

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
