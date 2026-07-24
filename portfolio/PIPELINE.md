# Pipeline diagram

Visual companion to `AGENT_NOTES.md`'s file map and `README.md`'s "Data
pipeline" section - same information, diagram form. If this ever disagrees
with either of those, trust the prose docs and fix this diagram (see the rule
in `AGENT_NOTES.md` about keeping it in sync).

This diagram covers the deterministic pipeline and its task wrappers only.
The analysis/advisory layer applied on top of `TASKANALYSIS`'s output (or in
ad-hoc chat) is `INVESTMENT_FRAMEWORK.md` - not part of this diagram since it
doesn't read or write any pipeline file.

**Legend:** cylinders = persisted data files, rectangles = deterministic
`pipeline/` modules (no LLM involvement), hexagons = scheduled tasks
(LLM-in-the-loop wrapper around a deterministic module). Dotted edges =
rare/one-off, not part of the regular cycle.

Every rectangle below is a `python3 -m pipeline.<name>`-runnable module (see
`QUICKSTART.md`) and can also be invoked as a typed MCP tool via
`mcp/server.py` (same function, same output, no separate implementation) -
that's the invocation path the `portfolio` skill and scheduled tasks use.
See `AGENT_NOTES.md`'s pipeline components table for the tool-name mapping.
This diagram covers data flow, which doesn't change based on invocation
transport, so it isn't redrawn for this.

All data-file paths below are relative to `portfolio/data/`, except
`transactions.csv` which lives in `data/manual/` specifically (the one file
with no automated source) and `config.json` which stays at the `portfolio/`
root, not under `pipeline/`.

```mermaid
flowchart TD
    subgraph SETUP["① MANUAL - whenever you trade (run from a terminal)"]
        direction TB
        TXN[("data/manual/transactions.csv<br/>raw broker export<br/>(only external input)")]:::data
        TMAP[("data/ticker_map.csv<br/>ISIN, Ticker, Company, Sector<br/>shared / committed")]:::data
        LOTS[("data/transaction_lots.csv<br/>FIFO open lots<br/>ISIN, Ticker, Shares, dates, cost")]:::data

        CL1["pipeline.lots<br/>FIFO engine"]:::script
        SCAFF["pipeline.tickers<br/>yfinance resolve<br/>(only if new ISIN)"]:::script
        CL2["pipeline.lots<br/>(re-run)"]:::script

        TXN --> CL1
        TMAP --> CL1
        CL1 --> LOTS
        LOTS -- "blank-Ticker rows" --> SCAFF
        SCAFF -- "appends new rows" --> TMAP
        TMAP --> CL2
        TXN --> CL2
        CL2 --> LOTS
    end

    subgraph DAILY["② SCHEDULED - Claude Code tasks, daily"]
        direction TB
        PRICES[("data/price_history/{TICKER}.jsonl<br/>one file per ticker")]:::data
        JSONOUT[("pipeline.analysis output<br/>value, gain/loss, XIRR,<br/>drawdown, movers, trend, caveats,<br/>notable/notify_reasons")]:::data
        HIST[("data/analysis_history.jsonl<br/>generated_at, total_value, xirr_pct<br/>one line per run")]:::data
        MDOUT[("pipeline.report output<br/>deterministic markdown sections")]:::data
        REPORT[("data/daily-analysis/YYYY-MM-DD.md")]:::data
        NEWS[("data/news/{TICKER}/*.txt<br/>one file per meaningful source<br/>URL + fetched-at + method + text")]:::data

        CONFIG[("config.json<br/>thresholds + caveat/notify<br/>message templates")]:::data

        FETCH["pipeline.prices<br/>Finnhub / yfinance"]:::script
        ANALYZE["pipeline.analysis<br/>incl. value-divergence check"]:::script
        RENDER["pipeline.report"]:::script

        TASKFETCH{{"portfolio-price-fetch<br/>~07:11 Berlin<br/>LLM runs command, reports 1 line"}}:::task
        TASKANALYSIS{{"portfolio-daily-analysis<br/>~07:25 Berlin<br/>LLM web-searches ALL holdings in parallel<br/>(deeper context on flagged movers),<br/>writes Executive Summary + News Digest,<br/>never hand-transcribes a number"}}:::task

        TASKFETCH -.triggers.-> FETCH
        LOTS --> FETCH
        FETCH --> PRICES

        LOTS --> ANALYZE
        PRICES --> ANALYZE
        HIST -- "prior run's total_value" --> ANALYZE
        CONFIG -- "thresholds/caveat templates" --> ANALYZE
        CONFIG -- "short_hold_days_threshold" --> RENDER
        ANALYZE --> JSONOUT
        ANALYZE -- "appends" --> HIST
        JSONOUT --> RENDER
        RENDER --> MDOUT
        MDOUT --> TASKANALYSIS
        TASKANALYSIS --> REPORT
        TASKANALYSIS -- "meaningful sources" --> NEWS
    end

    BACKFILL["pipeline.backfill<br/>one-off / rare, full history"]:::script
    LOTS -. seeds .-> BACKFILL
    BACKFILL -. rewrites .-> PRICES

    classDef data fill:#eef1fb,stroke:#4b5fa8,stroke-width:1.5px,color:#262c52
    classDef script fill:#eaf4ec,stroke:#2f6f4e,stroke-width:1.5px,color:#163823
    classDef task fill:#fbf1de,stroke:#b3701f,stroke-width:1.5px,color:#4a2c0a
```
