# Setup

Human-facing instructions for getting this repo running on a machine, via
Claude Code (the sanctioned path). If you'd rather run the pipeline directly
from a terminal with no LLM involved at all, see [`QUICKSTART.md`](QUICKSTART.md)
instead. For what the system actually does once it's running, see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## What this is

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
  parallel batch, with deeper context on notable movers, and archive every
  meaningful source fetched as its own file under `data/news/{TICKER}/`

**Currently supports Scalable Capital's transaction export format.** Other
brokers' CSV exports have different columns/formats and aren't parsed yet -
see `portfolio_mcp/pipeline/lots.py`'s `load_transactions()` if you need to
adapt it for a different broker.

## Prerequisites

- A Python >=3.10 interpreter on the machine (`bootstrap.sh` searches
  python3.10 through python3.13)
- The `claude` CLI installed and on `PATH`

## 1. Run `bootstrap.sh`

From the repo root:
```bash
./bootstrap.sh
```
This is the only setup command you need to run by hand, and it's safe to
re-run any time (after a reboot, a `requirements.txt` change, or just to
confirm everything's still wired up). It:

1. Creates `portfolio/portfolio_mcp/.venv` and installs dependencies
2. Starts the HTTP server in the background (`nohup` + PID file) if it's not
   already running - this is **not** a login/boot service, so re-run this
   script after a reboot or crash to bring it back up
3. Registers the server with `claude mcp add --scope user --transport http`,
   so it's available in every Claude Code session on the machine, in any
   project
4. Copies `skills/portfolio/` (the whole directory - `SKILL.md` +
   `references/`) to `~/.claude/skills/portfolio/`, replacing whatever was
   there - self-contained, no dependency on this repo's location surviving
   afterward

## 2. Start a new Claude Code session

Any project, not just this one - the skill and MCP tools are both global
now. Ask it anything portfolio-related and the `portfolio` skill should
trigger. If nothing has been uploaded yet, it will walk you through first-run
setup itself (see `skills/portfolio/references/BOOTSTRAP.md` if you want to
read that flow yourself first) - in short: it copies `.env.example` to
`.env` for you, points you at the Finnhub signup below, asks for your
transaction export, and resolves any new tickers by calling the real
`resolve_tickers` tool (never guessing).

## Getting a Finnhub API key (optional)

1. Go to https://finnhub.io/register and sign up (free, no card required)
2. Copy the API key from your dashboard
3. Copy `portfolio/portfolio_mcp/.env.example` to
   `portfolio/portfolio_mcp/.env` and replace the placeholder with your real
   key yourself, in your editor - don't paste it into a Claude Code
   conversation, since it would end up in the transcript

The pipeline works fully without one - `yfinance` alone covers everything.
Finnhub is just a faster/more-reliable primary source for plain US tickers
(free tier: 60 req/min, 30k/month; doesn't cover non-US exchanges, which is
why `yfinance` is the fallback there too).

**Supported currencies**: EUR, USD, GBP, and GBp (British pence, e.g. London
`.L`-suffixed listings). Anything else is rejected rather than silently
mispriced - see [`ARCHITECTURE.md`](ARCHITECTURE.md)'s "Currency handling".

## Setting up daily automation

Two Claude Code scheduled tasks drive the daily workflow -
`portfolio-price-fetch` and `portfolio-daily-analysis`. The first-run flow
above creates these for you if they don't exist yet; if you want to set them
up yourself, or check they're still there, use
`claude` and ask it to list/create scheduled tasks named `portfolio-price-fetch`
and `portfolio-daily-analysis` - each one's prompt should just say to invoke
the `portfolio` skill and follow its `references/tasks/{name}.md` (the skill
itself resolves that path once loaded; see
[`ARCHITECTURE.md`](ARCHITECTURE.md)'s "Scheduled tasks").

## Checking things are running

```bash
claude mcp get portfolio          # should say "Connected"
cat portfolio/portfolio_mcp/.server.log
kill -0 $(cat portfolio/portfolio_mcp/.server.pid)   # exits 0 if the process is alive
```
If the server died (common after a machine sleep/reboot, since it's a
background process, not a login service), just re-run `./bootstrap.sh` - it
detects and skips anything already set up, and restarts the server if it's
not running.

## Further reading

- [`ARCHITECTURE.md`](ARCHITECTURE.md) - how the system actually works
- [`AGENT_NOTES.md`](AGENT_NOTES.md) - rules and lessons learned, for anyone
  developing in this repo
- [`QUICKSTART.md`](QUICKSTART.md) - running the pipeline directly, no
  Claude Code or LLM involved
- `skills/portfolio/` - the Claude Skill itself (what gets deployed globally)
