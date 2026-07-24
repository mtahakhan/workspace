# Pipeline diagram

Visual companion to `AGENT_NOTES.md`'s file map and `README.md`'s "Data
pipeline" section - same information, diagram form. If this ever disagrees
with either of those, trust the prose docs and fix this diagram (see the rule
in `AGENT_NOTES.md` about keeping it in sync).

**Legend:** cylinders = persisted data files, rectangles = deterministic
scripts (no LLM involvement), hexagons = scheduled tasks (LLM-in-the-loop
wrapper around a deterministic script). Dotted edges = rare/one-off, not part
of the regular cycle.

```mermaid
flowchart TD
    subgraph SETUP["① MANUAL - whenever you trade (run from a terminal)"]
        direction TB
        TXN[("transactions.csv<br/>raw broker export<br/>(only external input)")]:::data
        TMAP[("ticker_map.csv<br/>ISIN, Ticker, Company, Sector<br/>shared / committed")]:::data
        LOTS[("transaction_lots.csv<br/>FIFO open lots<br/>ISIN, Ticker, Shares, dates, cost")]:::data

        CL1["compute_lots.py<br/>FIFO engine"]:::script
        SCAFF["scaffold_metadata.py<br/>yfinance resolve<br/>(only if new ISIN)"]:::script
        CL2["compute_lots.py<br/>(re-run)"]:::script

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
        PRICES[("price_history/{TICKER}.jsonl<br/>one file per ticker")]:::data
        JSONOUT[("analyze_portfolio.py output<br/>value, gain/loss, XIRR,<br/>drawdown, movers, trend, caveats")]:::data
        REPORT[("daily-analysis/YYYY-MM-DD.md")]:::data

        FETCH["fetch_prices.py<br/>Finnhub / yfinance"]:::script
        ANALYZE["analyze_portfolio.py"]:::script

        TASKFETCH{{"portfolio-price-fetch<br/>~07:11 Berlin<br/>LLM runs command, reports 1 line"}}:::task
        TASKANALYSIS{{"portfolio-daily-analysis<br/>~07:25 Berlin<br/>LLM web-searches flagged movers only,<br/>writes the narrative report"}}:::task

        TASKFETCH -.triggers.-> FETCH
        LOTS --> FETCH
        FETCH --> PRICES

        LOTS --> ANALYZE
        PRICES --> ANALYZE
        ANALYZE --> JSONOUT
        JSONOUT --> TASKANALYSIS
        TASKANALYSIS --> REPORT
    end

    BACKFILL["backfill_history.py<br/>one-off / rare, full history"]:::script
    LOTS -. seeds .-> BACKFILL
    BACKFILL -. rewrites .-> PRICES

    classDef data fill:#eef1fb,stroke:#4b5fa8,stroke-width:1.5px,color:#262c52
    classDef script fill:#eaf4ec,stroke:#2f6f4e,stroke-width:1.5px,color:#163823
    classDef task fill:#fbf1de,stroke:#b3701f,stroke-width:1.5px,color:#4a2c0a
```
