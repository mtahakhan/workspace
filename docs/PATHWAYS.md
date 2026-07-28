# Usage Pathways

This pipeline supports four distinct workflows. Pick the one that matches how you want to work.

---

## 1. Full Setup: Claude-Powered (Recommended for most users)

**Best for:** Interactive portfolio management, news research, buy/sell analysis, and daily reports powered by Claude.

### Setup (5 min + first-time data import)
```bash
make bootstrap
make claude-setup
```

`bootstrap` creates a Python venv and starts the MCP server in the background - deliberately Claude-free, it never touches Claude Code's own config. `claude-setup` is the separate, independent step that registers the server globally with Claude Code and installs the Skill. Then:

1. **Start a new Claude Code session** (any project)
2. **Ask about your portfolio** — it will walk you through first-run setup:
   - Ask for your Scalable Capital transaction export
   - Resolve any new ticker ISINs (one human review step)
   - Fetch initial prices
   - Set up optional daily automation (scheduled tasks)

### Daily workflow
- Claude Code fetches live prices daily (scheduled)
- Claude writes a daily markdown report with news research on every holding
- Ask Claude for specific analysis: "Should I rebalance?", "How's my sector concentration?", etc.

### See also
- [`docs/SETUP.md`](SETUP.md) — full walkthrough, including the Finnhub API key

---

## 2. Manual Pipeline Only: Just the Numbers (Python, no LLM)

**Best for:** You want deterministic portfolio math (positions, XIRR, drawdown, etc.) but prefer to analyze it yourself or with your own tools.

### Setup (5 min setup + first-time data import)
```bash
make setup-data-and-backfill
```

Creates the venv and server. No Claude Code session needed. Then:

1. Follow [`QUICKSTART.md`](QUICKSTART.md#first-time-setup-steps-0-4) steps 1-4: place `transactions.csv`, run `pipeline.lots`, then `pipeline.tickers` (the one step where you review the ticker matches yourself)
2. `make backfill` — pulls each ticker's full price history so drawdown/trend analysis has real history, not just today's price (one-time)

After that, `make refresh` works.

### Daily workflow
```bash
make refresh
```
Runs once: fetches prices → computes analysis → checks compliance → renders markdown report. Output saved to `data/personal/manual-runs/<timestamp>/report.md` and printed to stdout.

**Automate it** (optional):
```bash
# macOS/Linux: add to crontab
35 7 * * *  cd /path/to/repo && make refresh >> data/personal/manual-runs.log 2>&1
```

### See also
- [`docs/QUICKSTART.md`](QUICKSTART.md) — step-by-step walkthrough of the pipeline

---

## 3. Hybrid: Manual Pipeline + Claude Analysis

**Best for:** You run the numbers yourself daily, but want Claude's analysis on top when you ask.

### Setup
```bash
make bootstrap
make claude-setup
```
Same setup as Path 1 (venv, server, MCP registration, Skill install) — the only difference is what you do next. When Claude's first-run flow offers to set up scheduled tasks, decline and run `make refresh` yourself instead (see Path 2's daily workflow).

### Daily workflow
1. Run the pipeline yourself: `make refresh`
2. Ask Claude questions about the results in any Claude Code session
3. Claude can suggest rebalancing, flag risks, research specific holdings, etc.

---

## 4. Scheduled Daily Automation via Claude

**Best for:** You want daily reports and analysis, all automated, with Claude Code handling both data and prose.

### Setup
```bash
make bootstrap-with-schedule
```
One command - it chains `bootstrap` and `claude-setup` together (same end state as Path 1's two commands), plus a prompt to ask Claude to create the two scheduled tasks (`portfolio-daily-refresh` and `portfolio-daily-analysis`) — see [`SETUP.md`](SETUP.md#setting-up-daily-automation) for what each task does and how to check they're still running.

### Daily workflow
- Nothing — Claude does it automatically
- Check your daily reports in the data directory
- Ask Claude follow-up questions about yesterday's report anytime

---

## Comparison table

| Need | Path 1 (Claude) | Path 2 (Python) | Path 3 (Hybrid) | Path 4 (Automated) |
|---|---|---|---|---|
| **Setup command** | `make bootstrap` + `make claude-setup` | `make setup-data-and-backfill` | `make bootstrap` + `make claude-setup` | `make bootstrap-with-schedule` |
| **Run pipeline** | Claude daily (scheduled) | `make refresh` manually | You, daily: `make refresh` | Claude daily (scheduled) |
| **Analysis** | Claude writes reports | Read markdown yourself | Claude on demand | Claude daily reports |
| **Time commitment** | ~10 min setup, ask Claude anytime | 10 min setup + 2 min daily | 10 min setup + 2 min daily | ~10 min setup, nothing after |
| **LLM involved?** | ✅ Yes | ❌ No | ✅ Yes, on demand | ✅ Yes |
| **Needs Claude Code?** | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes |
| **Pricing** | Free (Claude Code) | Free | Free | Free |

---

## Common questions

**Can I switch paths?** Yes, they're not mutually exclusive. You can start with Path 2 (just the numbers), then add Path 1's Claude layer later by running `make claude-setup` - it's independent of `make bootstrap` and doesn't need re-running venv/server setup.

**What if I only want to backfill once, not fetch daily?** Every path supports this. Backfill is a one-time operation; daily `make refresh` (or Claude's scheduled tasks) just append new prices to the same files.

**What data goes where?** All paths write to `data/personal/` (your transactions, positions, analysis) and `data/impersonal/` (ticker maps, price history, fetched news). You choose the location during setup with `make setup-env`.

**How do I stop daily automation?** For Path 4 (scheduled tasks), delete the tasks in Claude Code. For manual cron (Path 2), remove the cron entry. The pipeline itself doesn't run automatically unless you tell it to.

**Can I use this with multiple portfolios?** Not yet. This is single-portfolio per repo. Clone the repo again and run setup for portfolio #2 in a different location.
