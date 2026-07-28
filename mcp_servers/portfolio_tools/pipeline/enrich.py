#!/usr/bin/env python3
"""
Enrichment step: join transaction_lots.csv (pure FIFO output) with
ticker_map.csv, ticker_overrides.csv and company_overrides.csv to produce
enriched_lots.csv — the single file every downstream module reads.

Why this exists
---------------
`compute_lots` (lots.py) is a FIFO engine: it consumes transactions.csv and
produces cost-basis lots keyed by ISIN.  It needs to run to completion before
we can know which ISINs are currently open, which is the input `resolve_tickers`
needs.  Under the old design, lots.py also did the ticker/sector/company join
at write time, which forced a second `compute_lots` run after every
`resolve_tickers` call to embed the newly resolved tickers into the file.

Separating enrichment out removes that re-run entirely:

  1. compute_lots  → transaction_lots.csv   (ISIN-keyed, no Ticker/Sector/Company)
  2. resolve_tickers  (only when a new ISIN appears — reads transaction_lots.csv)
  3. enrich_lots   → enriched_lots.csv      (full join; run once after either step)

Every downstream module (prices, backfill, analysis, fees, storage) reads
enriched_lots.csv.  tickers.py is the only exception: it intentionally reads
transaction_lots.csv so it can detect ISINs whose Ticker is still blank.

Output schema
-------------
Identical to the old transaction_lots.csv schema so no downstream column
reference changes:

  Company, Ticker, ISIN, Sector, Shares, Purchase Date, Purchase Price,
  Fee, CA From ISIN, CA Ratio, CA Date

Ticker resolution order:
  1. ticker_overrides.csv (ISIN match) — explicit human correction of a
     resolve_tickers pick, e.g. substituting a supported-currency cross
     listing for one resolve_tickers flagged as unsupported
  2. ticker_map.csv (resolve_tickers' own pick) — never hand-edited in
     place, so it stays a pure record of what the automated search found

Company resolution order (same logic as the old lots.py main()):
  1. company_overrides.csv (ISIN match) — explicit human correction
  2. broker description from transaction_lots.csv
  3. fallback to ISIN string when no description exists
"""

import csv
import sys

from ..paths import (
    TRANSACTION_LOTS_FILE,
    TICKER_MAP_FILE,
    COMPANY_OVERRIDES_FILE,
    TICKER_OVERRIDES_FILE,
    ENRICHED_LOTS_FILE,
)

LOT_FIELDS = [
    "Company", "Ticker", "ISIN", "Sector",
    "Shares", "Purchase Date", "Purchase Price", "Fee",
    "CA From ISIN", "CA Ratio", "CA Date",
]


def load_ticker_metadata():
    """ISIN -> {ticker, sector} from ticker_map.csv. Empty dict when absent."""
    if not TICKER_MAP_FILE.exists():
        return {}
    with open(TICKER_MAP_FILE) as f:
        return {
            row["ISIN"]: {"ticker": row["Ticker"], "sector": row.get("Sector", "")}
            for row in csv.DictReader(f)
            if row["Ticker"]
        }


def load_company_overrides():
    """ISIN -> corrected display name from company_overrides.csv.

    Kept separate from ticker_map.csv deliberately: the broker's own
    description stays the default, so only explicitly listed ISINs are
    overridden, and each carries a Note explaining why.  Missing file or
    blank Company = no override.
    """
    if not COMPANY_OVERRIDES_FILE.exists():
        return {}
    with open(COMPANY_OVERRIDES_FILE) as f:
        return {
            row["ISIN"]: row["Company"].strip()
            for row in csv.DictReader(f)
            if row.get("Company", "").strip()
        }


def load_ticker_overrides():
    """ISIN -> corrected ticker from ticker_overrides.csv.

    Same opt-in pattern as load_company_overrides(), kept in its own file so
    ticker_map.csv - resolve_tickers' own record of what it picked - is never
    hand-edited in place. Typical case: the auto-picked listing trades in an
    unsupported currency and a cross-listed USD/EUR/GBP ADR is substituted
    here instead. Missing file or blank Ticker = no override.
    """
    if not TICKER_OVERRIDES_FILE.exists():
        return {}
    with open(TICKER_OVERRIDES_FILE) as f:
        return {
            row["ISIN"]: row["Ticker"].strip()
            for row in csv.DictReader(f)
            if row.get("Ticker", "").strip()
        }


def main():
    if not TRANSACTION_LOTS_FILE.exists():
        print("transaction_lots.csv not found — run compute_lots first.", file=sys.stderr)
        return

    metadata = load_ticker_metadata()
    overrides = load_company_overrides()
    ticker_overrides = load_ticker_overrides()
    applied_overrides = []
    applied_ticker_overrides = []

    output_rows = []
    with open(TRANSACTION_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            isin = row.get("ISIN", "")
            meta = metadata.get(isin, {})
            picked_ticker = meta.get("ticker", "") or row.get("Ticker", "")
            ticker = ticker_overrides.get(isin, picked_ticker)
            if ticker != picked_ticker and picked_ticker:
                applied_ticker_overrides.append((isin, picked_ticker, ticker))
            sector = meta.get("sector", "") or row.get("Sector", "")
            broker_name = row.get("Company", "") or isin
            company = overrides.get(isin, broker_name)
            if company != broker_name and broker_name:
                applied_overrides.append((ticker or isin, broker_name, company))
            output_rows.append({
                "Company": company,
                "Ticker": ticker,
                "ISIN": isin,
                "Sector": sector,
                "Shares": row["Shares"],
                "Purchase Date": row["Purchase Date"],
                "Purchase Price": row["Purchase Price"],
                "Fee": row.get("Fee", ""),
                "CA From ISIN": row.get("CA From ISIN", ""),
                "CA Ratio": row.get("CA Ratio", ""),
                "CA Date": row.get("CA Date", ""),
            })

    ENRICHED_LOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ENRICHED_LOTS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {len(output_rows)} enriched lots to {ENRICHED_LOTS_FILE}")

    if applied_ticker_overrides:
        print(f"\nApplied {len(applied_ticker_overrides)} ticker override(s):")
        for isin, picked, ticker in sorted(applied_ticker_overrides):
            print(f"  {isin}: '{picked}' (resolve_tickers pick) -> '{ticker}'")

    if applied_overrides:
        print(f"\nApplied {len(applied_overrides)} company-name override(s):")
        for ticker, broker_name, company in sorted(applied_overrides):
            print(f"  {ticker}: '{broker_name}' (broker) -> '{company}'")

    no_ticker = sorted({r["ISIN"] for r in output_rows if not r["Ticker"]})
    if no_ticker:
        print(
            f"\n{len(no_ticker)} ISIN(s) still have no Ticker — "
            f"run resolve_tickers then enrich_lots again: {no_ticker}"
        )


if __name__ == "__main__":
    main()
