# Portfolio pipeline workspace

**Address the user as "Developer" in this project.**

**First run?** If `portfolio/transactions.csv` does not exist, this is a fresh
clone with no personal data set up yet - stop and follow
`portfolio/BOOTSTRAP.md` before doing anything else. Don't try to run any
pipeline script or assume default/example data; there is none by design (see
`.gitignore` - all personal data and secrets are excluded from this repo).

This workspace holds one project: a portfolio price-tracking and analysis
pipeline in `portfolio/`. It runs entirely on Claude Code scheduled tasks and
deterministic Python scripts - no external server, no other agent framework.

**Read `portfolio/AGENT_NOTES.md` before making ANY change to this pipeline.**
It's the systematic, consolidated rule set - every non-obvious behavior, past
bug, and design decision - written specifically so you never have to read the
Python source to understand why something works the way it does. Code
comments cover local line-level logic only; system-level rules live there.

**Read `portfolio/README.md` first** for the full pipeline (data flow, file
purposes, troubleshooting). The essentials (full detail + rationale in
`AGENT_NOTES.md`):

- `transactions.csv` (raw broker export) is the only source of truth for
  positions - there is no static holdings file. Everything else (shares, cost
  basis, purchase dates) is derived from it via `compute_lots.py`'s FIFO engine.
- Tickers must be the real, exchange-specific symbol (e.g. `BAYN.DE`, `SAN.PA`,
  `QBTS`), resolved via `scaffold_metadata.py` against the actual ISIN - never
  guessed. `ticker_map.csv` (ISIN, Ticker, Company, Sector) is shared/committed
  and append-only - a confirmed bug source when this rule was skipped once.
- All prices are stored and computed in EUR. `price_history/{TICKER}.jsonl`'s
  `price_eur` field is the one canonical value - never read a raw-currency
  field directly. Supported currencies: EUR, USD, GBP, GBp only.
- Two scheduled tasks run this daily: `portfolio-price-fetch` then
  `portfolio-daily-analysis`. `analyze_portfolio.py` is the deterministic
  numeric layer - don't recompute its numbers by hand; if one looks wrong,
  fix the script. Each task's real instructions live in `portfolio/tasks/*.md`,
  not in the schedule itself (the schedule's prompt is just a one-line pointer
  to the file) - edit the file, not the schedule, to change task behavior.
- When new trades happen: re-export `transactions.csv`, run
  `python3 compute_lots.py` to pick up the new rows, resolve any new ISIN it
  reports via `scaffold_metadata.py`, then run `python3 compute_lots.py`
  again to pick up the resolved ticker - nothing detects new trades on its own.

## Memory for this project

Project-specific memory lives in **`.claude/memory/`** in this workspace, not
Claude's global memory location - read `.claude/memory/MEMORY.md` for the
index. This keeps anything specific to this project colocated, visible, and
portable with the workspace itself, rather than siloed in a global,
machine-tied path. Only genuinely general, cross-project facts about the user
(not specific to this project) belong in the global memory system - if in
doubt, put it here instead.
