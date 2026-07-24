#!/usr/bin/env python3
"""
One-off backfill: populate price_history/{TICKER}.jsonl with each stock's full
available historical daily prices (yfinance period="max"). Not part of the
regular fetch_prices.py run - run manually to (re)seed history. Full
rationale/rules: see AGENT_NOTES.md (read that first, not this file).

Quick reference: one file per ticker, converted using each day's HISTORICAL FX
rate (not today's rate). Must stay in sync with fetch_prices.py's currency
support (EUR/USD/GBP/GBp) and write the same record schema.
"""

import csv
import json

import pandas as pd
import yfinance as yf

from .paths import DATA_DIR

TRANSACTION_LOTS_FILE = DATA_DIR / "transaction_lots.csv"
PRICE_HISTORY_DIR = DATA_DIR / "price_history"

YFINANCE_SOURCE_NAME = "yfinance (Yahoo Finance chart endpoint)"

# Currencies handled: EUR (no conversion), USD, GBP, GBp (British pence = GBP/100).
# Each non-EUR currency has a yfinance FX pair whose historical series is used for
# per-day conversion (never today's rate - see module docstring). Must stay in
# sync with fetch_prices.py's live-fetch currency support.
FX_PAIRS = {
    "USD": "EURUSD=X",
    "GBP": "EURGBP=X",
    "GBp": "EURGBP=X",  # same pair; the pence price is /100'd to GBP before applying
}
def _fx_source_name(pair):
    return f"yfinance ({pair}, Yahoo Finance chart endpoint)"

def load_tickers():
    """Currently-held tickers, derived from transaction_lots.csv (run
    `python3 -m pipeline.lots` first if you've traded since it was last generated)."""
    tickers, seen = [], set()
    with open(TRANSACTION_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            if row["Ticker"] and row["Ticker"] not in seen:
                seen.add(row["Ticker"])
                tickers.append(row["Ticker"])
    return tickers

def main(period="max"):
    tickers = load_tickers()

    print(f"Backfilling {period} history for {len(tickers)} tickers...")

    # Load each needed FX pair's history once, cached by pair symbol.
    fx_cache = {}
    def fx_history_for(pair):
        if pair not in fx_cache:
            s = yf.Ticker(pair).history(period=period)["Close"]
            s.index = s.index.tz_localize(None)
            fx_cache[pair] = s
        return fx_cache[pair]

    PRICE_HISTORY_DIR.mkdir(exist_ok=True)

    for t in tickers:
        tk = yf.Ticker(t)
        currency = tk.fast_info.get("currency")
        hist = tk.history(period=period)["Close"]
        hist.index = hist.index.tz_localize(None)
        price_source_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{t}"

        if hist.empty:
            print(f"  {t}: NO DATA")
            continue

        if currency == "EUR":
            prices_eur = hist.round(2)
            rates_used = pd.Series(1.0, index=hist.index)
            fx_pair = None
        elif currency in FX_PAIRS:
            fx_pair = FX_PAIRS[currency]
            fx_history = fx_history_for(fx_pair)
            fx_source_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{fx_pair}"
            # FX series only goes back so far (e.g. EUR/USD starts 2003-12-01 - the
            # Euro didn't exist before 1999). Truncate rather than back-fill a rate
            # that isn't real: for tickers with older history (IBM, AMD, ...), those
            # earlier years are dropped instead of being silently mispriced.
            fx_start = fx_history.index.min()
            hist = hist[hist.index >= fx_start]
            if hist.empty:
                print(f"  {t}: no overlap with available {fx_pair} data, skipping")
                continue
            rates_used = fx_history.reindex(hist.index).ffill()
            # GBp (pence) -> GBP before applying the EUR/GBP rate.
            price_in_fx_currency = hist / 100 if currency == "GBp" else hist
            prices_eur = (price_in_fx_currency / rates_used).round(2)
        else:
            print(f"  {t}: unsupported currency {currency}, skipping")
            continue

        out_file = PRICE_HISTORY_DIR / f"{t}.jsonl"
        with open(out_file, "w") as f:
            for date, price in prices_eur.items():
                if pd.isna(price):
                    continue
                timestamp = date.strftime("%Y-%m-%dT16:00:00")
                if currency == "EUR":
                    # No real conversion happened - provenance fields would just
                    # restate "already EUR"/rate=1.0, so they're omitted entirely.
                    record = {"timestamp": timestamp, "price_eur": float(price)}
                else:
                    original_price = float(hist.loc[date])
                    rate = float(rates_used.loc[date])
                    record = {
                        "timestamp": timestamp,
                        "price_eur": float(price),
                        "original_currency": currency,
                        "price_original_currency": round(original_price, 2),
                        "price_source_name": YFINANCE_SOURCE_NAME,
                        "price_source_url": price_source_url,
                        "conversion_rate": round(rate, 6),
                        "conversion_rate_source_name": _fx_source_name(fx_pair),
                        "conversion_rate_source_url": fx_source_url,
                    }
                f.write(json.dumps(record) + "\n")

        print(f"  {t}: {len(prices_eur)} rows ({currency}), {hist.index[0].date()} to {hist.index[-1].date()} -> {out_file.name}")

    print(f"\nDone. Wrote per-ticker files to {PRICE_HISTORY_DIR}/")

if __name__ == "__main__":
    main()
