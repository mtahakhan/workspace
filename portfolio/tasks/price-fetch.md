# portfolio-price-fetch task instructions

Run the portfolio price fetch script:

```
cd /Users/user/openclaw/workspace/portfolio && python3 fetch_prices.py
```

This gets the ticker list from `transaction_lots.csv` (derived from real broker transactions - there is no separate holdings file), fetches live prices (Finnhub primary, yfinance backup), and appends one fully-sourced line per ticker to its own history file at `price_history/{TICKER}.jsonl` (one file per stock, e.g. `price_history/AMD.jsonl`, `price_history/BAYN.DE.jsonl`). There is no separate prices.json snapshot - each file's last line IS the current price, read directly by analyze_portfolio.py. No further action needed - this task is fetch-only. Report a one-line summary (how many tickers resolved, any missing) and stop. Do not write the daily analysis report - that's a separate task (`portfolio-daily-analysis`).

If a ticker is missing/unmapped, that likely means a new trade happened and `python3 compute_lots.py` needs to be re-run first (it rebuilds `transaction_lots.csv` from `transactions.csv`) - but only do that if you have reason to believe `transactions.csv` actually changed; don't run it speculatively. If the script errors for another reason, report the exact error - do not attempt to fix ticker mappings or reintroduce a manual-override file (tickers in transaction_lots.csv are already the real, direct exchange symbols; that's intentional, see portfolio/README.md).
