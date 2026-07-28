#!/usr/bin/env python3
"""
Deterministically resolve new ISINs into ticker_map.csv - a CONFIRM-don't-GUESS
step. Full rationale/history: see AGENT_NOTES.md (read that first).

Quick reference: reads transaction_lots.csv (NOT enriched_lots.csv — that file
is stale until enrich_lots runs, but tickers.py sits before enrich_lots in the
setup sequence) for currently-open ISINs, cross-checks against ticker_map.csv
to find any not yet mapped, resolves each via a real yfinance search +
currency/history check, then appends the new rows to ticker_map.csv (shared,
committed - never overwrites existing rows) with Sector left blank for a human
to fill in. Automatically calls enrich_lots at the end so enriched_lots.csv
is immediately current. Every new pick must still be reviewed against the
printed table before trusting it.
"""

import csv
import sys

import yfinance as yf

from ..paths import TICKER_MAP_FILE, TRANSACTION_LOTS_FILE, TRANSACTIONS_FILE


# Currency preference for picking among a security's listings. Lower = better.
# EUR first (pipeline is EUR-native, matches the broker exactly, no FX hop);
# GBp/GBP last (London listings quote in pence and need an extra conversion).
CURRENCY_RANK = {"EUR": 0, "USD": 1, "GBP": 2, "GBp": 2, "DKK": 3}
SUPPORTED_CURRENCIES = set(CURRENCY_RANK)  # anything else can't be priced by the pipeline

def load_positions():
    """(total_open_count, {isin: (net_shares, company_name)} for positions with
    NO ticker_map row yet) — reads transaction_lots.csv for open ISINs and
    checks each against ticker_map.csv to find unmapped ones.

    transaction_lots.csv is ISIN-keyed only (no Ticker column since the
    enrich_lots refactor), so we can no longer use a blank Ticker field as
    the "needs resolving" signal. Instead we load the ticker_map once and
    check ISIN membership directly — same semantic, different source.

    Deliberately does NOT re-run compute_lots' FIFO engine — that would just
    recompute exactly what's already in transaction_lots.csv."""
    if not TRANSACTION_LOTS_FILE.exists():
        print("transaction_lots.csv not found - call the compute_lots tool first.", file=sys.stderr)
        return 0, {}

    # Load the set of already-mapped ISINs from ticker_map.csv once.
    mapped_isins = set()
    if TICKER_MAP_FILE.exists():
        with open(TICKER_MAP_FILE) as f:
            for row in csv.DictReader(f):
                if row.get("Ticker", "").strip():
                    mapped_isins.add(row["ISIN"].strip())

    all_isins = set()
    unmapped = {}
    with open(TRANSACTION_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            isin = row.get("ISIN", "").strip()
            if not isin:
                continue  # missing ISIN column — re-run compute_lots
            all_isins.add(isin)
            if isin in mapped_isins:
                continue
            shares, company = unmapped.get(isin, (0.0, row.get("Company", isin)))
            unmapped[isin] = (shares + float(row["Shares"]), company)

    unmapped = {isin: (round(shares, 6), company) for isin, (shares, company) in unmapped.items()}
    return len(all_isins), unmapped

def load_all_transacted_isins():
    """(total_count, {isin: company}) for every ISIN ever transacted that has
    no ticker_map.csv row yet - reads transactions.csv directly, not
    transaction_lots.csv (which only ever carries CURRENTLY OPEN ISINs, by
    construction of the FIFO engine that produces it), so a position that was
    fully bought and fully sold before ticker resolution ever ran on it still
    gets resolved.

    Built for pipeline.realized's per-ticker realized-gain breakdown: a
    fully-closed ISIN with no ticker_map row renders as a bare ISIN there
    instead of a ticker/company name, because it was never in scope for
    load_positions() above.

    Deliberately a separate function rather than a change to load_positions():
    this can be 1-2 orders of magnitude slower for a long-lived account (every
    historical ISIN gets a yfinance search, not just today's open ones), and
    the daily pipeline (fetch_prices, analyze_portfolio) never needs anything
    beyond the open ISINs load_positions() already covers - see main()'s
    include_historical parameter, which keeps this opt-in.

    No share-count bookkeeping (unlike load_positions): the resolution loop
    in main() only needs a company name to search with and an ISIN to key the
    new ticker_map.csv row on, and share counts are otherwise never printed
    or used.
    """
    if not TRANSACTIONS_FILE.exists():
        print("transactions.csv not found - upload a transaction export first.", file=sys.stderr)
        return 0, {}

    mapped_isins = set()
    if TICKER_MAP_FILE.exists():
        with open(TICKER_MAP_FILE) as f:
            for row in csv.DictReader(f):
                if row.get("Ticker", "").strip():
                    mapped_isins.add(row["ISIN"].strip())

    all_isins = set()
    unmapped = {}
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row.get("status") != "Executed" or row.get("assetType") != "Security":
                continue
            isin = (row.get("isin") or "").strip()
            if not isin:
                continue
            all_isins.add(isin)
            if isin in mapped_isins or isin in unmapped:
                continue
            description = (row.get("description") or "").strip('"')
            # Same guard as lots.py: the broker sometimes puts the bare ISIN
            # in the description field (seen on a corporate action's incoming
            # leg) - that's an identifier, not a company name.
            unmapped[isin] = description if description and description != isin else isin

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

def main(include_historical: bool = False):
    """Resolve unmapped ISINs into ticker_map.csv.

    include_historical=False (default, unchanged from before): only ISINs in
    currently-open positions (transaction_lots.csv) - what the daily pipeline
    needs, and what every existing caller of this tool relies on.

    include_historical=True: also resolves ISINs from FULLY CLOSED positions
    (ones with no open lots today), read straight from transactions.csv. Opt-in
    and separate from the default because it can be 1-2 orders of magnitude
    slower for a long-lived account - every historical ISIN gets its own
    yfinance search, not just today's open ones. Use this to fill in tickers
    for pipeline.realized's per-ticker breakdown, which otherwise falls back
    to showing a bare ISIN for any position closed out before it was ever
    resolved.
    """
    if include_historical:
        total, new_isins_raw = load_all_transacted_isins()
        new_isins = new_isins_raw  # already {isin: company}
        scope_label = "ISIN(s) ever transacted (open + historical)"
    else:
        total, new_isins_raw = load_positions()
        new_isins = {isin: company for isin, (_shares, company) in new_isins_raw.items()}
        scope_label = "open position(s)"

    print(f"{total} {scope_label}; {total - len(new_isins)} already "
          f"mapped, resolving {len(new_isins)} new ISIN(s)...\n")

    if not new_isins:
        if total:
            print("Nothing new to resolve.")
        # Always re-enrich so enriched_lots.csv is fresh even when there was
        # nothing to resolve (e.g. after a set_ticker_mapping Sector fill).
        _run_enrich()
        return

    new_rows = []
    review = []
    for isin, company in sorted(new_isins.items(), key=lambda kv: kv[1].lower()):
        picked, currency, price, cands = best_candidate(isin)
        flags = []
        if picked is None:
            flags.append("NO CANDIDATE - fill Ticker manually")
        elif currency not in SUPPORTED_CURRENCIES:
            flags.append(f"UNSUPPORTED CURRENCY {currency} - find a EUR/USD/GBP/DKK listing")
        elif currency != "EUR" and any(c[1] == "EUR" for c in cands):
            flags.append("EUR listing also exists - prefer it")
        if len([c for c in cands if c[1] in SUPPORTED_CURRENCIES]) > 1:
            flags.append("multiple listings - verify the pick is the right one")
        new_rows.append({"ISIN": isin, "Ticker": picked or "", "Company": company, "Sector": ""})
        review.append((company, isin, picked, currency, price, cands, flags))

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
    for company, isin, picked, currency, price, cands, flags in review:
        price_str = f"{price:.2f} {currency}" if price is not None else "no price"
        print(f"  {company[:34]:34s} {isin}  ->  {picked or '???':10s} {price_str}")
        if len(cands) > 1:
            alts = ", ".join(f"{s}({c})" for s, c, _, _ in cands if s != picked)
            if alts:
                print(f"      other listings: {alts}")
        for fl in flags:
            print(f"      ⚠ {fl}")
    print("\nReview the picks above, fix any flagged rows with set_ticker_mapping, "
          "and fill in the blank Sector for each new row.")
    print("enriched_lots.csv has been updated — fetch_prices and analyze_portfolio "
          "will pick up the new tickers on their next run.")

    # Enrich immediately so enriched_lots.csv is never stale after a resolve.
    # Any ISINs whose Ticker is still blank (NO CANDIDATE / flagged) will appear
    # with an empty Ticker in enriched_lots.csv until fixed with set_ticker_mapping.
    _run_enrich()


def _run_enrich():
    """Run enrich_lots and print its output inline."""
    from .enrich import main as enrich_main
    print()
    enrich_main()

if __name__ == "__main__":
    main()
