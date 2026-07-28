# Usage Pathways

This pipeline supports four distinct workflows. Pick the one that matches how you want to work.

---

## 1. Full Setup: Claude-Powered (Recommended for most users)

**Best for:** Interactive portfolio management, news research, buy/sell analysis, and daily reports powered by Claude.

### Setup (5 min + first-time data import)
```bash
make bootstrap
```

This does everything: creates a Python venv, starts the MCP server in the background, registers it globally with Claude Code, and installs the Skill. Then:

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
- [`docs/SETUP.md`](SETUP.md) — full walkthrough with screenshots and API key instructions

---

## 2. Manual Pipeline Only: Just the Numbers (Python, no LLM)

**Best for:** You want deterministic portfolio math (positions, XIRR, drawdown, etc.) but prefer to analyze it yourself or with your own tools.

### Setup (5 min, includes backfilling)
```bash
make setup-data-and-backfill
```

This creates the venv and server, then backfills historical price data so your analysis has real history (not just today's prices). No Claude Code session needed — you run this once and you're ready.

### First-time data import
1. Export your transactions from Scalable Capital → save as `data/personal/transactions.csv`
2. Run: `make refresh`
3. The pipeline will ask you to review ticker ISINs (one human step, one command to fix)

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
1. **First: set up the pipeline**
   ```bash
   make setup-data-and-backfill
   ```

2. **Then: register the MCP server and Skill with Claude**
   ```bash
   make mcp-register
   make skill-install
   ```

3. **Start a Claude Code session** and ask about your portfolio — the Skill will have access to your existing analysis data

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

Then in a Claude Code session:
```
Ask Claude to "set up daily portfolio tasks"
```

This creates two scheduled tasks that run automatically every morning:
- **portfolio-daily-refresh** — fetches prices
- **portfolio-daily-analysis** — computes analysis, researches news, writes report

### Daily workflow
- Nothing — Claude does it automatically
- Check your daily reports in the data directory
- Ask Claude follow-up questions about yesterday's report anytime

### See also
- [`docs/SETUP.md`](SETUP.md#setting-up-daily-automation) — scheduling details

---

## Comparison table

| Need | Path 1 (Claude) | Path 2 (Python) | Path 3 (Hybrid) | Path 4 (Automated) |
|---|---|---|---|---|
| **Setup command** | `make bootstrap` | `make setup-data-and-backfill` | Both setups | `make bootstrap-with-schedule` |
| **Run pipeline** | Claude daily (scheduled) | `make refresh` manually | You, daily: `make refresh` | Claude daily (scheduled) |
| **Analysis** | Claude writes reports | Read markdown yourself | Claude on demand | Claude daily reports |
| **Time commitment** | ~10 min setup, ask Claude anytime | 10 min setup + 2 min daily | 10 min setup + 2 min daily | ~10 min setup, nothing after |
| **LLM involved?** | ✅ Yes | ❌ No | ✅ Yes, on demand | ✅ Yes |
| **Needs Claude Code?** | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes |
| **Pricing** | Free (Claude Code) | Free | Free | Free |

---

## Common questions

**Can I switch paths?** Yes, they're not mutually exclusive. You can start with Path 2 (just the numbers), then add Path 1's Claude layer later by running `make mcp-register && make skill-install` from any Claude Code session.

**What if I only want to backfill once, not fetch daily?** Every path supports this. Backfill is a one-time operation; daily `make refresh` (or Claude's scheduled tasks) just append new prices to the same files.

**What data goes where?** All paths write to `data/personal/` (your transactions, positions, analysis) and `data/impersonal/` (ticker maps, price history, fetched news). You choose the location during setup with `make setup-env`.

**How do I stop daily automation?** For Path 4 (scheduled tasks), delete the tasks in Claude Code. For manual cron (Path 2), remove the cron entry. The pipeline itself doesn't run automatically unless you tell it to.

**Can I use this with multiple portfolios?** Not yet. This is single-portfolio per repo. Clone the repo again and run setup for portfolio #2 in a different location.
