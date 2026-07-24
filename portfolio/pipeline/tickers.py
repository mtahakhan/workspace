#!/usr/bin/env python3
"""
Deterministically resolve new ISINs into ticker_map.csv - a CONFIRM-don't-GUESS
step. Full rationale/history: see AGENT_NOTES.md (read that first).

Quick reference: reads transaction_lots.csv (NOT transactions.csv directly -
run compute_lots.py first) for open positions with a blank Ticker, resolves
each via a real yfinance search + currency/history check, then appends the
new rows to ticker_map.csv (shared, committed - never overwrites existing
rows) with Sector left blank for a human to fill in. Every new pick must
still be reviewed against the printed table before trusting it.
"""

import csv
import sys

import yfinance as yf

from .paths import DATA_DIR

TICKER_MAP_FILE = DATA_DIR / "ticker_map.csv"
TRANSACTION_LOTS_FILE = DATA_DIR / "transaction_lots.csv"

# Currency preference for picking among a security's listings. Lower = better.
# EUR first (pipeline is EUR-native, matches the broker exactly, no FX hop);
# GBp/GBP last (London listings quote in pence and need an extra conversion).
CURRENCY_RANK = {"EUR": 0, "USD": 1, "GBP": 2, "GBp": 2}
SUPPORTED_CURRENCIES = set(CURRENCY_RANK)  # anything else can't be priced by the pipeline

def load_positions():
    """(total_open_count, {isin: (net_shares, company_name)} for positions with
    NO ticker yet) - read straight from transaction_lots.csv, which already
    has ISIN + a blank Ticker for anything compute_lots.py couldn't resolve.
    Deliberately does NOT re-run compute_lots' FIFO engine - that would just
    recompute exactly what's already sitting in transaction_lots.csv."""
    if not TRANSACTION_LOTS_FILE.exists():
        print("transaction_lots.csv not found - run `python3 -m pipeline.lots` first.", file=sys.stderr)
        return 0, {}
    all_isins = set()
    unmapped = {}
    with open(TRANSACTION_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            isin = row.get("ISIN", "")
            if not isin:
                continue  # old-schema file without ISIN column - re-run compute_lots.py
            all_isins.add(isin)
            if row["Ticker"]:
                continue
            shares, company = unmapped.get(isin, (0.0, row["Company"]))
            unmapped[isin] = (shares + float(row["Shares"]), company)
    unmapped = {isin: (round(shares, 6), company) for isin, (shares, company) in unmapped.items()}
    return len(all_isins), unmapped

def candidate_symbols(isin):
    """yfinance search results for an ISIN, as a list of symbol strings."""
    try:
        return [q.get("symbol") for q in yf.Search(isin).quotes if q.get("symbol")]
    except Exception as e:
        print(f"  (search failed for {isin}: {e})", file=sys.stderr)
        return []

def symbol_info(symbol):
    """(currency, last_price, has_history) for a symbol; (None, None, False) if
    it doesn't resolve. has_history checks for actual historical daily closes -
    some listings (OTC symbols, minor-exchange ISIN aliases) return a live
    quote but NO history, which would silently break backfill_history.py and
    drawdown/trend later, so a history-less candidate must rank below any
    candidate that has real history."""
    try:
        tk = yf.Ticker(symbol)
        fi = tk.fast_info
        currency = fi.get("currency")
        if currency is None:
            return None, None, False
        try:
            has_history = not tk.history(period="5d")["Close"].dropna().empty
        except Exception:
            has_history = False
        return currency, fi.get("lastPrice"), has_history
    except Exception:
        return None, None, False

def best_candidate(isin):
    """Return (picked_symbol, currency, price, all_candidates) for an ISIN.
    all_candidates is a list of (symbol, currency, price, has_history)."""
    seen = []
    for sym in candidate_symbols(isin)[:8]:  # cap lookups per ISIN for speed
        currency, price, has_history = symbol_info(sym)
        if currency is None:
            continue
        seen.append((sym, currency, price, has_history))
    # Rank: candidates WITH price history first (backfill needs it), then by
    # currency preference, then having a live price at all.
    def rank(entry):
        _sym, currency, price, has_history = entry
        return (0 if has_history else 1,
                CURRENCY_RANK.get(currency, 9),
                0 if price is not None else 1)
    seen.sort(key=rank)
    if seen:
        picked_sym, picked_ccy, picked_price, _ = seen[0]
        return picked_sym, picked_ccy, picked_price, seen
    return None, None, None, []

def main():
    total_open, new_isins = load_positions()

    print(f"{total_open} open positions; {total_open - len(new_isins)} already "
          f"mapped, resolving {len(new_isins)} new ISIN(s)...\n")

    if not new_isins:
        if total_open:
            print("Nothing new to resolve. Run `python3 -m pipeline.lots` to confirm everything maps cleanly.")
        return

    new_rows = []
    review = []
    for isin, (shares, company) in sorted(new_isins.items(), key=lambda kv: kv[1][1].lower()):
        picked, currency, price, cands = best_candidate(isin)
        flags = []
        if picked is None:
            flags.append("NO CANDIDATE - fill Ticker manually")
        elif currency not in SUPPORTED_CURRENCIES:
            flags.append(f"UNSUPPORTED CURRENCY {currency} - find a EUR/USD/GBP listing")
        elif currency != "EUR" and any(c[1] == "EUR" for c in cands):
            flags.append("EUR listing also exists - prefer it")
        if len([c for c in cands if c[1] in SUPPORTED_CURRENCIES]) > 1:
            flags.append("multiple listings - verify the pick is the right one")
        new_rows.append({"ISIN": isin, "Ticker": picked or "", "Company": company, "Sector": ""})
        review.append((company, isin, shares, picked, currency, price, cands, flags))

    # Append, don't overwrite - preserve every existing (possibly other-user-contributed) row.
    file_exists = TICKER_MAP_FILE.exists()
    with open(TICKER_MAP_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ISIN", "Ticker", "Company", "Sector"])
        if not file_exists:
            w.writeheader()
        w.writerows(new_rows)

    print(f"Appended {len(new_rows)} new row(s) to {TICKER_MAP_FILE} "
          f"(existing rows untouched).\n")
    print("REVIEW EACH NEW PICK - confirm it's the right company at a sane price:\n")
    for company, isin, shares, picked, currency, price, cands, flags in review:
        price_str = f"{price:.2f} {currency}" if price is not None else "no price"
        print(f"  {company[:34]:34s} {isin}  ->  {picked or '???':10s} {price_str}")
        if len(cands) > 1:
            alts = ", ".join(f"{s}({c})" for s, c, _ in cands if s != picked)
            if alts:
                print(f"      other listings: {alts}")
        for fl in flags:
            print(f"      ⚠ {fl}")
    print("\nNext: eyeball the prices above (a wrong ticker usually shows an absurd price or "
          "wrong currency), fix any flagged rows, fill in the blank Sector column for each new "
          "row in ticker_map.csv, then re-run `python3 -m pipeline.lots` to confirm everything maps cleanly.")

if __name__ == "__main__":
    main()
