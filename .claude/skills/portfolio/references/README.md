# Portfolio Management System

## What This Does

A portfolio tracker and daily analysis pipeline, exposed as a globally
registered MCP server (`portfolio`) that Claude Code talks to over HTTP -
not tied to any particular project. Upload a broker transaction export and
it will:

- Reconstruct your real, current positions (shares, cost basis, purchase
  dates) from actual buy/sell history via FIFO - not a manually maintained
  spreadsheet that can drift out of sync
- Fetch live prices daily (Finnhub primary, yfinance backup) in EUR, fully
  sourced (original currency, API used, FX rate applied - all persisted, not
  just the final number)
- Compute portfolio value, gain/loss, sector concentration, largest positions,
  high-water-mark/drawdown, daily movers, and a real money-weighted annualized
  return (XIRR) - all deterministic Python, not estimated by an LLM
- Write a daily markdown report, researching every holding's news in a single
  parallel batch (not a serial loop, which timed out previously), with deeper
  context on notable movers, and archive every meaningful source fetched
  (URL, timestamp, method) as its own file under `data/news/{TICKER}/`

**Currently supports Scalable Capital's transaction export format.** Other
brokers' CSV exports have different columns/formats and aren't parsed yet -
see `portfolio_mcp/pipeline/lots.py`'s `load_transactions()` if you need to
adapt it for a different broker.

**First time setting this up?** Run `bootstrap.sh` (repo root) to install
the server and register it + the Claude Skill globally, then see
`BOOTSTRAP.md` for the rest (uploading your transaction history, resolving
tickers). No `data/manual/transactions.csv` present yet is exactly the
"fresh setup" signal.

**Working on this codebase (agent or human)?** Read **`AGENT_NOTES.md` first.**
It consolidates every non-obvious rule, past bug, and design decision into one
place, specifically so you never have to read the Python source to understand
why something works the way it does. It also explains the deployment model
(global, HTTP-only, one server for every project) in more depth than this file.

**Want investment analysis or advice from this data** (chat questions, or the
daily report's Executive Summary/News Digest)? See **`INVESTMENT_FRAMEWORK.md`**
- the analysis/advisory layer used once the pipeline's numbers already exist.
It never changes a pipeline number itself.

## Layout

Everything lives inside `portfolio_mcp/` - one package, not a project plus a
separate server:

- `portfolio_mcp/server.py` - the FastMCP server. HTTP-only
  (`streamable-http`, bound to `127.0.0.1`), and the only sanctioned way to
  invoke this pipeline (see "Claude Skill / MCP server" below). Wraps every
  tool call in a lock (`portfolio_mcp/lock.py`) since it's one long-running
  process potentially reached by concurrent sessions/projects.
- `portfolio_mcp/pipeline/` - the deterministic computation, as a subpackage
  of the server, not a sibling project: FIFO engine (`lots.py`), ticker
  resolution (`tickers.py`), price fetch/backfill (`prices.py`/
  `backfill.py`), analysis (`analysis.py`), report rendering (`report.py`),
  config loading (`config.py`), transaction upload handling (`uploads.py`).
- `portfolio_mcp/paths.py` - single source of truth for every filesystem
  path this package uses, all computed from the package's own location on
  disk (`Path(__file__).resolve().parent`), never from cwd or "the current
  project" - there isn't one; see `AGENT_NOTES.md`'s "Deployment model".
- `portfolio_mcp/data/` - internal default location for everything the
  pipeline reads/writes (see "Files" below); `data/manual/transactions.csv`
  is the one file with no automated source, and arrives via the
  `upload_transactions` tool, not by anyone placing a file there directly.
- `portfolio_mcp/config.json`, `.env`/`.env.example` - config/secrets.
- `portfolio_mcp/requirements.txt`, `.venv/` - one venv for the whole
  package (server + pipeline), needs Python >=3.10.
- `bootstrap.sh` (repo root) - sets up the venv, starts the server, and
  registers it + the Claude Skill globally. See that section below.
- `tasks/` - the two scheduled tasks' actual instructions.
- `.claude/skills/portfolio/` (workspace-level) - the Claude Skill source;
  `bootstrap.sh` copies it to `~/.claude/skills/portfolio/`.

## Data pipeline (in order)

See **`PIPELINE.md`** for a Mermaid diagram of everything below. Every step
is exposed as an MCP tool - that's the sanctioned way to invoke it. Each
pipeline module can also be run directly
(`portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.<name>`, from
inside `portfolio/`) for local debugging, calling the exact same function
either way.

1. **`upload_transactions`** → **`data/manual/transactions.csv`** — the one
   file with no automated source. Paste the complete raw CSV text (Scalable
   Capital's export format) whenever you trade; this is always a full
   re-export, not incremental, and the tool keeps one `.bak` of whatever was
   there before.
2. **`compute_lots`** → **`data/transaction_lots.csv`** — FIFO cost-basis
   engine. Reconstructs exactly which shares are still held, when, and at
   what price, from the real transaction history (handles partial sells, the
   WisdomTree ISIN-swap corporate action, and the Dec 2025 broker-migration
   transfer rows). This is the sole source of current open positions (ticker,
   company, shares, weighted-average cost) — there is no separate positions
   file.
3. **`data/ticker_map.csv`** (ISIN, Ticker, Company, Sector) — the resolved
   ticker symbol and sector, the two things broker exports can't provide.
   Shared and committed - an ever-growing lookup table (see
   `resolve_tickers`), because resolving a ticker correctly once means
   nobody using this project ever has to re-solve it. Call `resolve_tickers`
   to deterministically resolve any new ISIN via a real yfinance lookup
   (never a guess) whenever `compute_lots` reports one as unmapped; Sector
   still needs a quick human judgment call afterward (see `AGENT_NOTES.md`
   for why ticker guessing must never happen).
4. **`fetch_prices`** → **`data/price_history/{TICKER}.jsonl`** — fetches
   the ticker list from `transaction_lots.csv`, gets live prices (Finnhub
   primary, yfinance fallback), and appends one fully-sourced record per
   ticker (original currency, source name/URL, FX rate + source) to its own
   history file. There is no separate latest-price snapshot file - each
   file's last line IS the current price.
5. **`analyze_portfolio`** — deterministic numeric layer: value, gain/loss,
   sector breakdown, high-water-mark/drawdown, movers, trend, and a real
   money-weighted XIRR (annualized return) from `transaction_lots.csv`'s actual
   purchase dates. Also flags any ticker whose latest `price_history` entry is
   more than 2 days old (stale/failed fetch) - see `stale_prices` in its output
   - and flags a run-over-run `total_value` swing >20% (see
   `data/analysis_history.jsonl`) as a likely data bug rather than a real
   market move. Both thresholds (and every other tunable number/message in
   the pipeline) live in `config.json`, not hardcoded - see
   `AGENT_NOTES.md`'s "Configurable thresholds and caveats".
6. **`render_report`** — takes `analyze_portfolio`'s JSON (as the `analysis`
   argument) and renders every table/figure in the daily report as markdown.
   Exists so the LLM writing the report never hand-transcribes a number out of
   the JSON - it only writes the Executive Summary and the Movers research
   prose, and appends them around this tool's output.

## Claude Skill / MCP server

This is a global tool, not a per-project one - **run `bootstrap.sh` once**
(repo root) and both pieces below are available in every Claude Code session
on the machine, in any project:

- **`portfolio` MCP server** (`portfolio_mcp/server.py`) - exposes each
  pipeline step above as a typed tool (`upload_transactions`, `compute_lots`,
  `resolve_tickers`, `fetch_prices`, `backfill_history`, `analyze_portfolio`,
  `render_report`), calling the exact same functions direct module
  invocation would. Deployed as a single long-running HTTP process (`http://
  127.0.0.1:8420/mcp` by default - see `PORTFOLIO_MCP_PORT` in
  `bootstrap.sh`), registered via `claude mcp add --scope user`. Every tool
  call is serialized through a lock (`portfolio_mcp/lock.py`) since it's one
  process potentially reached by multiple concurrent sessions/projects - see
  `AGENT_NOTES.md`'s "Deployment model" for why.
- **`portfolio` skill** (`.claude/skills/portfolio/SKILL.md`, copied to
  `~/.claude/skills/portfolio/` by `bootstrap.sh`) - packages when to use
  this pipeline, the MCP tool mapping, and `AGENT_NOTES.md`'s absolute rules
  so they're loaded automatically for portfolio-related requests in any
  project, not just this one.

`bootstrap.sh` is idempotent - safe to re-run after a reboot (it starts the
server fresh, since it's a background process, not a login service - see
that script's header) or just to pick up a `requirements.txt` change.

## Daily Workflow (scheduled tasks)

- **`portfolio-price-fetch`** (~07:11 Berlin) — calls `fetch_prices`
- **`portfolio-daily-analysis`** (~07:25 Berlin) — calls `analyze_portfolio`
  then `render_report`, researches all holdings' news in one parallel batch
  (never a serial loop — a prior serial full-scan attempt timed out) with
  deeper context on notable movers, writes `data/daily-analysis/YYYY-MM-DD.md`

Each scheduled task's actual instructions are NOT stored in the schedule
itself - the schedule's prompt is just a one-line pointer ("read and follow
`tasks/{name}.md`"). The real instructions live in **`tasks/price-fetch.md`**
and **`tasks/daily-analysis.md`**, so editing task behavior is a normal file
edit (visible, diffable, version-controlled with everything else) rather than
a separate tool call against the scheduler. If you change what a task should
do, edit the file in `tasks/`, not the schedule.

## When you trade

1. Call `upload_transactions` with your freshly re-exported CSV (Scalable
   Capital)
2. Call `compute_lots` to regenerate `data/transaction_lots.csv` - this
   picks up the new transaction(s), leaving `Ticker`/`Sector` blank for any
   brand-new ISIN
3. If it reports a brand-new ISIN, call `resolve_tickers` to resolve it
   deterministically (appends to `data/ticker_map.csv`), review the pick,
   then fill in its Sector directly in `data/ticker_map.csv`
4. Call `compute_lots` again to pick up the resolved ticker
5. (Optional) Call `fetch_prices` to pick up the new ticker immediately

Skipping this means `transaction_lots.csv` (and therefore XIRR, position
values, and drawdown) go stale while prices keep updating daily around it —
there's no automation that detects a new trade on its own.

## Files

| File | Purpose | Maintained by |
|------|---------|--------|
| `data/manual/transactions.csv` | Raw broker export — the actual source of truth | `upload_transactions` tool (keeps one `.bak`) |
| `data/ticker_map.csv` | ISIN, Ticker, Company, Sector. Shared, committed, ever-growing | `resolve_tickers` (append-only) + you (Sector) |
| `data/transaction_lots.csv` | FIFO-derived open lots (shares, dates, prices) | `compute_lots` |
| `data/price_history/{TICKER}.jsonl` | Full sourced price history per ticker - last line = current price | `fetch_prices` (append) / `backfill_history` (seed) |
| `data/analysis_history.jsonl` | One line per `analyze_portfolio` run (`generated_at`, `total_value`, `xirr_pct`) - powers the value-divergence caveat | `analyze_portfolio` (append) |
| `data/daily-analysis/*.md` | Generated reports | scheduled task, output only |
| `data/news/{TICKER}/*.txt` | One file per fetched news source deemed meaningful - metadata header (URL, fetched-at, fetch method) + the fetched text | scheduled task + ad-hoc analysis, output only |
| `PIPELINE.md` | Mermaid diagram of the whole pipeline | Kept in sync by hand - see `AGENT_NOTES.md` rule 8 |
| `tasks/*.md` | Actual scheduled-task instructions (schedule just points here) | You, when task behavior needs to change |
| `INVESTMENT_FRAMEWORK.md` | Analysis/advisory layer (modes, signals, portfolio/risk rules) used on top of pipeline output | You, when analysis approach needs to change |
| `.env` | Finnhub API key (gitignored, never committed) | You, rarely |
| `.env.example` | Committed placeholder template - copy to `.env` and fill in your key | Ships with the repo |
| `portfolio_mcp/server.py`, `requirements.txt`, `.venv/` | The `portfolio` MCP server and its own dependencies/interpreter | You (setup via `bootstrap.sh`), server code as needed |
| `bootstrap.sh` | Global registration (repo root) | You, when the deployment (port, venv location) needs to change |

## Troubleshooting

### Missing or stale prices
- Check `fetch_prices`'s output for which tickers failed and why
- Check `analyze_portfolio`'s `stale_prices` output field - flags any ticker whose last `price_history` entry is 2+ days old
- Verify the ticker in `data/ticker_map.csv` is still the correct exchange symbol (companies occasionally change listings)
- Call `fetch_prices` again

### transaction_lots.csv share counts look wrong
- Call `compute_lots` again — it reports current positions and flags any ISIN missing a `data/ticker_map.csv` row, or a row with a blank Sector
- If a same-day buy/sell pair looks mis-sequenced, check `data/manual/transactions.csv`'s `time` column - lots are sorted by full date+time, not date alone

### Prices look wrong
- Confirm the ticker in `data/ticker_map.csv` is the security you actually hold — a wrong/ambiguous ticker can silently resolve to an unrelated company. This is the single biggest real bug source in this project - confirmed cases: `CAN`→Canaan Inc instead of Cantourage Group `HIGH.DE`, `DTE`→DTE Energy instead of Deutsche Telekom `DTE.DE`, `IRE`→a leveraged Iren SpA ETF instead of IREN Ltd, and (from a bootstrap run by a smaller model that guessed tickers instead of using `resolve_tickers`) `CCO`→a $2.41 unrelated stock instead of Cameco `CCJ`@$87, plus several London `.L` listings picked in GBp (pence) that should have been EUR-native alternatives. **Always resolve new tickers via `resolve_tickers`, never by guessing a shorthand symbol.**
- Check Scalable Capital for any splits/adjustments
- Finnhub prices are ~5 min delayed (not real-time)

### A price looks off by ~100x, or in the wrong currency entirely
- Check `data/price_history/{TICKER}.jsonl`'s `original_currency` field for that ticker - the pipeline supports EUR, USD, GBP, and GBp (British pence, converted by /100 first). Any other currency is rejected, not silently mispriced.
- If `data/ticker_map.csv` points at a listing in an unsupported currency (e.g. CAD, JPY), `resolve_tickers` will flag it - find an EUR/USD/GBP-listed alternative for that ISIN instead

### The MCP server isn't responding
- Check it's actually running: `claude mcp get portfolio` (should say `Connected`)
- Check the log: `portfolio_mcp/.server.log`
- Check the PID is alive: `kill -0 $(cat portfolio_mcp/.server.pid)`
- Re-run `bootstrap.sh` - it detects and skips anything already set up, and starts the server if it's not running

## Testing

Via the MCP tools (the sanctioned path - see "Claude Skill / MCP server"
above), or directly for local debugging, from inside `portfolio/`:
```bash
cd portfolio
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.tickers   # only if you have a new, unmapped ISIN
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.lots      # only if transactions.csv changed
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.prices
portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.analysis | portfolio_mcp/.venv/bin/python3 -m portfolio_mcp.pipeline.report
```
Direct invocation calls the exact same functions the MCP tools do, just
without going through the server/lock - fine for debugging a single module,
but don't build anything around this being the primary interface.

## API Status

- **yfinance**: Free, primary source — covers both US and EU-listed tickers directly (e.g. `BAYN.DE`, `SAN.PA`, `3BRS.MI`, `EWG2.SG`, `SEC0.DE`)
- **Finnhub**: Free tier (60 req/min, 30k/month) — fallback for bare US tickers only; its free tier doesn't cover non-US exchanges

All free, no credit card required.

**Supported currencies**: EUR, USD, GBP, and GBp (British pence, e.g. London
`.L`-suffixed listings - divided by 100 to GBP before converting). Anything
else is rejected rather than silently mispriced - `resolve_tickers` flags
it so you can pick a different listing for that ISIN.

### Getting a Finnhub API key
1. Go to https://finnhub.io/register and sign up (free, no card required)
2. Copy the API key from your dashboard
3. Copy `portfolio_mcp/.env.example` to `portfolio_mcp/.env` and replace the
   placeholder with your real key - do this yourself in your editor, don't
   paste the key into chat with Claude (it would end up in the conversation
   history)

The pipeline still works without one (yfinance alone covers everything), but
Finnhub as primary is faster/more reliable for the plain US tickers it supports.
