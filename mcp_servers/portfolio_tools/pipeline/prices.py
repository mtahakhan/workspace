#!/usr/bin/env python3
"""
Fetch current prices for open portfolio positions: Finnhub (primary, registered
API, USD only, US-listed symbols only) + yfinance (backup, covers EUR/USD/GBP/DKK
directly). Appends a fully-sourced record per ticker to price_history/{TICKER}.jsonl.
Full rationale/rules: see AGENT_NOTES.md (read that first, not this file, to
understand the "why").

Quick reference: ticker list comes from transaction_lots.csv. price_eur is the
one field every downstream script should read. Supported currencies: EUR, USD,
GBP, GBp, DKK - see AGENT_NOTES.md before adding another one.
"""

import csv
import json
from datetime import datetime

import requests
import yfinance as yf

from ..paths import ENRICHED_LOTS_FILE, PRICE_HISTORY_DIR, ENV_FILE


FX_SOURCE_NAME = "exchangerate-api.com"
FX_SOURCE_URL = "https://api.exchangerate-api.com/v4/latest/EUR"

# Currencies the pipeline understands. GBp is British pence (1/100 GBP) - London
# listings (yfinance symbols ending .L) quote in GBp, so it's common enough that
# it's supported here permanently rather than being bolted on per-setup. DKK
# (Danish Krone) added for Copenhagen-listed securities (e.g. Novo Nordisk's
# primary listing, NOVO-B.CO) - same permanent-support reasoning as GBp.
FALLBACK_RATES = {"USD": 1.09, "GBP": 0.84, "DKK": 7.46}  # 1 EUR = X, only used if the live fetch fails

def fetch_exchange_rates():
    """Fetch current EUR->{USD,GBP,DKK} rates. Returns (rates_dict, source_name, source_url).
    rates_dict maps currency -> units per 1 EUR."""
    try:
        resp = requests.get(FX_SOURCE_URL, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("rates", {})
            rates = {c: data.get(c) for c in ("USD", "GBP", "DKK")}
            if all(rates.values()):
                print(f"Exchange rates (live): 1 EUR = {rates['USD']} USD, {rates['GBP']} GBP, {rates['DKK']} DKK")
                return rates, FX_SOURCE_NAME, FX_SOURCE_URL
    except Exception as e:
        print(f"Exchange rate fetch failed: {e}")
    print(f"Using fallback exchange rates: {FALLBACK_RATES}")
    return dict(FALLBACK_RATES), "hardcoded fallback (fetch failed)", None

# Fetched fresh at the start of main() (not here) - this used to run once at
# import time, which is fine for a one-shot CLI process but would silently
# freeze the rate for the lifetime of a long-running process (e.g. the MCP
# server importing this module once and calling main() many times).
EUR_RATES = FX_RATE_SOURCE_NAME = FX_RATE_SOURCE_URL = None

FINNHUB_KEY = None
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("FINNHUB_API_KEY="):
                FINNHUB_KEY = line.split("=", 1)[1].strip()
                break

def load_tickers():
    """Return the list of currently-open-position tickers, derived from
    enriched_lots.csv (run enrich_lots first if it's stale)."""
    tickers = []
    seen = set()
    with open(ENRICHED_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            t = row["Ticker"]
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
    return tickers

def _make_record(price_original, currency, source_name, source_url):
    """Build the price record. price_eur is the one field every downstream
    consumer should use. The provenance fields (original currency, source,
    FX rate) are only added when a real conversion happened - for EUR-native
    tickers they'd just be redundant restatements of price_eur/"already EUR"/
    rate=1.0, so they're omitted entirely rather than stored as no-op data.

    Supported currencies: EUR (no conversion), USD, GBP, GBp (British
    pence = GBP/100), and DKK. Anything else returns None so the caller
    treats it as a miss rather than silently mispricing it - a wrong currency
    almost always means a wrong ticker was chosen (see scaffold_metadata.py /
    BOOTSTRAP.md)."""
    if currency == "EUR":
        return {"price_eur": round(price_original, 2)}

    # Normalize GBp (pence) to GBP first, remembering the original for provenance.
    fx_currency = currency
    price_for_conversion = price_original
    if currency == "GBp":
        fx_currency = "GBP"
        price_for_conversion = price_original / 100

    rate = EUR_RATES.get(fx_currency)
    if rate is None:
        return None  # unsupported currency - caller treats as a miss

    return {
        "price_eur": round(price_for_conversion / rate, 2),
        "original_currency": currency,  # "GBp" here means the price_original_currency is in pence
        "price_original_currency": round(price_original, 2),
        "price_source_name": source_name,
        "price_source_url": source_url,
        "conversion_rate": rate,  # units of GBP/USD per 1 EUR (GBp is /100'd to GBP before applying)
        "conversion_rate_source_name": FX_RATE_SOURCE_NAME,
        "conversion_rate_source_url": FX_RATE_SOURCE_URL,
    }

def append_price_history(records):
    """Append one fully-sourced line per ticker to its own
    price_history/{TICKER}.jsonl (one file per stock, no shared-file rotation -
    each just grows indefinitely, fine even at high fetch frequency)."""
    PRICE_HISTORY_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().isoformat()
    for ticker, record in records.items():
        line = {"timestamp": timestamp, **record}
        with open(PRICE_HISTORY_DIR / f"{ticker}.jsonl", "a") as f:
            f.write(json.dumps(line) + "\n")

def fetch_finnhub(ticker):
    """Fetch single ticker price from Finnhub. Returns a sourced record or None.
    Finnhub's free tier only reliably covers US-listed symbols, so this cleanly
    fails (returns None, doesn't return wrong data) for exchange-suffixed
    symbols like "BAYN.DE" - verified against all EU tickers in this portfolio.
    Finnhub only ever returns USD quotes on the free tier."""
    if not FINNHUB_KEY:
        return None
    public_url = f"https://finnhub.io/api/v1/quote?symbol={ticker}"  # token redacted before persisting
    try:
        resp = requests.get(f"{public_url}&token={FINNHUB_KEY}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "c" in data and data["c"]:
                return _make_record(data["c"], "USD", "Finnhub", public_url)
    except Exception as e:
        print(f"Finnhub error for {ticker}: {e}")
    return None

def fetch_yfinance_one(ticker):
    """Fetch a single ticker's price from yfinance. Returns a sourced record or None.
    Uses per-ticker fast_info (not a batch download) so currency is known per symbol
    and there's no risk of the MultiIndex/date-alignment issues a batch call has.
    The URL logged is yfinance's actual (unofficial, undocumented) backend
    endpoint - see yfinance/const.py - not a made-up placeholder."""
    try:
        fi = yf.Ticker(ticker).fast_info
        price = fi.get("lastPrice")
        currency = fi.get("currency")
        if price is None:
            return None
        source_url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        record = _make_record(price, currency, "yfinance (Yahoo Finance chart endpoint)", source_url)
        if record is None:
            print(f"  {ticker}: yfinance returned unsupported currency {currency}")
        return record
    except Exception as e:
        print(f"yfinance error for {ticker}: {e}")
        return None

def main():
    global EUR_RATES, FX_RATE_SOURCE_NAME, FX_RATE_SOURCE_URL
    EUR_RATES, FX_RATE_SOURCE_NAME, FX_RATE_SOURCE_URL = fetch_exchange_rates()

    tickers = load_tickers()
    print(f"Fetching prices for {len(tickers)} tickers...")

    def describe(record):
        """Records are trimmed to just price_eur when currency was already EUR
        (no conversion happened) - fall back gracefully for the log line."""
        if "original_currency" in record:
            return f"{record['original_currency']} {record['price_original_currency']}"
        return "EUR (native)"

    records = {}
    for ticker in tickers:
        record = fetch_finnhub(ticker)
        if record is not None:
            records[ticker] = record
            print(f"  {ticker}: {record['price_eur']} EUR (Finnhub, {describe(record)})")
            continue

        record = fetch_yfinance_one(ticker)
        if record is not None:
            records[ticker] = record
            print(f"  {ticker}: {record['price_eur']} EUR (yfinance, {describe(record)})")
        else:
            print(f"  {ticker}: MISSING (not found in Finnhub or yfinance)")

    missing = set(tickers) - set(records.keys())
    append_price_history(records)

    print(f"\nAppended {len(records)} sourced prices to {PRICE_HISTORY_DIR}/")
    if missing:
        # Raised, not just printed: the caller (the create_refresh MCP tool)
        # needs to stop rather than proceed to analyze_portfolio on a stale/
        # incomplete price set - see SKILL.md rule 3, "report the exact error
        # and stop" rather than silently continuing. Successfully-fetched
        # tickers are still appended above before this raises, so a partial
        # fetch isn't lost - only the tickers that actually failed are missing.
        raise RuntimeError(
            f"{len(missing)} ticker(s) missing (not found in Finnhub or yfinance): "
            f"{', '.join(sorted(missing))}. {len(records)} other ticker(s) were "
            f"fetched and appended successfully."
        )

if __name__ == "__main__":
    main()
