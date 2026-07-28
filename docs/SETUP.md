# Setup - Claude Code Path

Instructions for getting this repo running with Claude Code (MCP server + Skill) - one of four usage pathways compared in [`PATHWAYS.md`](PATHWAYS.md). For what the system actually does once it's running, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for running it without Claude Code at all, see [`QUICKSTART.md`](QUICKSTART.md).

**Currently supports Scalable Capital's transaction export format only.** Other
brokers' CSV exports have different columns/formats - see `portfolio_tools/pipeline/lots.py`'s
`load_transactions()` if you need to adapt it for a different broker.

## Prerequisites

- A Python >=3.10 interpreter on the machine (`bootstrap.sh` searches
  python3.10 through python3.13)
- The `claude` CLI installed and on `PATH`

## 1. Run `bootstrap.sh` (or `make bootstrap`)

From the repo root:
```bash
make bootstrap
```
Safe to re-run any time (after a reboot, a `requirements.txt` change, or just
to confirm everything's still wired up). It runs two steps in order (each in
its own script under `scripts/`) - you can also run either individually:

| Make target | What it does |
|---|---|
| `make venv-setup` | Creates `mcp_servers/portfolio_tools/.venv` (Python >=3.10) and installs dependencies |
| `make server-start` | Starts the HTTP server in the background (`nohup` + PID file) - **not** a login/boot service, re-run after a reboot or crash |

**Deliberately Claude-free** - this step never touches Claude Code's own
config or `~/.claude/`. It just gets the server itself running, which works
just as well for the Python-only path (see [`PATHWAYS.md`](PATHWAYS.md)) as
it does for this one.

On a first run (no `.env` yet), bootstrap starts by asking two things: your
Finnhub API key (optional - press Enter to skip) and **where to keep your
data**. Press Enter for the default, `<repo>/data/`, or give any absolute
path - a synced folder, an encrypted volume, anywhere with its own backups.
It's written to the server's `.env` as `PORTFOLIO_DATA_DIR`.

The directory gets two subdirectories: `personal/` (your transactions,
positions and reports - never committed) and `impersonal/` (ticker lookup
tables, price history and fetched news - committed, since those are the same
facts for everyone).

To change either value later, run `make setup-env` and restart the server.
**Changing the path does not move existing data** - move the contents
yourself, keeping `personal/` and `impersonal/` intact.

## 2. Run `make claude-setup`

```bash
make claude-setup
```
This is the step that actually hooks Claude Code into the server `make
bootstrap` just started - independent of it, and safe to re-run any time
(e.g. to pick up a `skills/portfolio/` update) without touching the venv or
restarting the server. Two steps:

| Make target | What it does |
|---|---|
| `make mcp-register` | Registers with `claude mcp add --scope user --transport http`, available in every Claude Code session on the machine |
| `make skill-install` | Copies `skills/portfolio/` to `~/.claude/skills/portfolio/`, replacing whatever was there - self-contained, no dependency on this repo's location surviving afterward |

## 3. Start a new Claude Code session

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
3. Run `make setup-env` - it will prompt you for the key and write it to
   `mcp_servers/portfolio_tools/.env` without echoing the full value to the
   terminal. Or copy `.env.example` to `.env` and edit it yourself - just
   don't paste the key into a Claude Code conversation (it would end up in
   the transcript)

The pipeline works fully without one - `yfinance` alone covers everything.
Finnhub is just a faster/more-reliable primary source for plain US tickers
(free tier: 60 req/min, 30k/month; doesn't cover non-US exchanges, which is
why `yfinance` is the fallback there too).

Only EUR/USD/GBP/GBp/DKK holdings are priced - see [`ARCHITECTURE.md`](ARCHITECTURE.md#currency-handling)
for the full rule and why.

## Setting up daily automation

Two Claude Code scheduled tasks drive the daily workflow -
`portfolio-daily-refresh` and `portfolio-daily-analysis`. The first-run flow
above creates these for you if they don't exist yet; if you want to set them
up yourself, or check they're still there, use
`claude` and ask it to list/create scheduled tasks named `portfolio-daily-refresh`
and `portfolio-daily-analysis` - each one's prompt should just say to invoke
the `portfolio` skill and follow its `references/tasks/{name}.md` (the skill
itself resolves that path once loaded; see
[`ARCHITECTURE.md`](ARCHITECTURE.md)'s "Scheduled tasks").

## Checking things are running

```bash
claude mcp get portfolio          # should say "Connected"
cat mcp_servers/portfolio_tools/.server.log
kill -0 $(cat mcp_servers/portfolio_tools/.server.pid)   # exits 0 if the process is alive
```
If the server died (common after a machine sleep/reboot, since it's a
background process, not a login service), just re-run `./bootstrap.sh` - it
detects and skips anything already set up, and restarts the server if it's
not running.

## Further reading

- [`PATHWAYS.md`](PATHWAYS.md) - the other three usage paths (Python-only, hybrid, fully automated)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) - how the system actually works
- [`AGENT_NOTES.md`](AGENT_NOTES.md) - rules and lessons learned, for anyone
  developing in this repo
- [`QUICKSTART.md`](QUICKSTART.md) - running the pipeline directly, no
  Claude Code or LLM involved
- `skills/portfolio/` - the Claude Skill itself (what gets deployed globally)
