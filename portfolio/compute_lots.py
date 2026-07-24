#!/usr/bin/env python3
"""
Build FIFO cost-basis lots from transactions.csv -> transaction_lots.csv.
Full rationale and rules: see AGENT_NOTES.md (read that before changing this
file - don't rely on figuring out the "why" from reading this source).

Quick reference: uses ticker_map.csv (ISIN,Ticker,Company,Sector - shared,
committed) for the two things transactions.csv can't provide. FIFO consumes
oldest lots first on a Sell. "Security transfer" rows are excluded (broker
migration artifact). "Corporate action" rows carry cost basis to the new ISIN.
"""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PORTFOLIO_DIR = Path(__file__).parent
TRANSACTIONS_FILE = PORTFOLIO_DIR / "transactions.csv"
TICKER_MAP_FILE = PORTFOLIO_DIR / "ticker_map.csv"  # shared, committed - ISIN,Ticker,Company,Sector
OUTPUT_FILE = PORTFOLIO_DIR / "transaction_lots.csv"

def load_ticker_metadata():
    """ISIN -> {ticker, sector} from the shared ticker_map.csv."""
    if not TICKER_MAP_FILE.exists():
        return {}
    with open(TICKER_MAP_FILE) as f:
        return {row["ISIN"]: {"ticker": row["Ticker"], "sector": row.get("Sector", "")}
                for row in csv.DictReader(f) if row["Ticker"]}

def parse_number(s):
    """German decimal format: '1.074,00' -> 1074.00"""
    if not s or not s.strip():
        return None
    return float(s.strip().replace(".", "").replace(",", "."))

def load_transactions():
    """Note: sort key must include time-of-day, not just date. The raw export
    lists transactions newest-first; a date-only sort key leaves Python's
    stable sort to break same-day ties in that (reverse-chronological) file
    order, which silently mis-sequences same-day buy/sell pairs and can cause
    a phantom oversell (confirmed: this produced an extra fabricated lot for
    ISLN.L before the fix - Jan 30's sell at 08:46 was processed before that
    same day's buy at 08:23, an hour backwards)."""
    rows = []
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            if r["status"] != "Executed" or r["assetType"] != "Security":
                continue
            rows.append({
                "date": datetime.strptime(f'{r["date"]} {r["time"]}', "%Y-%m-%d %H:%M:%S"),
                "description": r["description"].strip('"'),
                "type": r["type"],
                "isin": r["isin"],
                "shares": parse_number(r["shares"]),
                "price": parse_number(r["price"]),
            })
    rows.sort(key=lambda r: r["date"])
    return rows

def verify_transfers_net_zero(rows):
    """Confirm the Security transfer assumption before relying on it."""
    net = defaultdict(float)
    for r in rows:
        if r["type"] == "Security transfer":
            net[r["isin"]] += r["shares"]
    bad = {isin: total for isin, total in net.items() if abs(total) > 0.001}
    if bad:
        print(f"WARNING: Security transfer rows do NOT net to zero for: {bad}")
        print("         These will still be excluded, but purchase history may be wrong for them.")
    else:
        print(f"Verified: Security transfer rows net to zero for all {len(net)} affected ISINs - excluding them.")

def build_lots(rows):
    """FIFO lots per ISIN. Returns {isin: [{"date", "shares", "price"}, ...]}"""
    lots = defaultdict(list)
    descriptions = {}

    for r in rows:
        isin, shares, price = r["isin"], r["shares"], r["price"]
        if r["description"] and r["description"] not in ("", "XS3306517098"):
            descriptions[isin] = r["description"]

        if r["type"] == "Security transfer":
            continue  # verified net-zero migration artifact, not a real transaction

        if r["type"] == "Corporate action":
            # Only known case: WisdomTree ISIN swap. The negative-share row on the
            # OLD isin signals "consolidate all lots of this ISIN"; the positive-share
            # row on the NEW isin is where they land, carrying total cost + weighted
            # average original date forward (not the corporate-action date), so the
            # real holding period for return purposes is preserved.
            if shares < 0:
                old_isin = isin
                old_lots = lots.pop(old_isin, [])
                total_shares = sum(l["shares"] for l in old_lots)
                total_cost = sum(l["shares"] * l["price"] for l in old_lots)
                if total_shares > 0:
                    weighted_date_ts = sum(l["date"].timestamp() * l["shares"] for l in old_lots) / total_shares
                    lots[f"__pending_from_{old_isin}"] = [{
                        "date": datetime.fromtimestamp(weighted_date_ts),
                        "shares": total_shares,
                        "price": total_cost / total_shares,
                    }]
                    if old_isin in descriptions:
                        descriptions[f"__pending_desc"] = descriptions[old_isin]
            else:
                pending_key = next((k for k in lots if k.startswith("__pending_from_")), None)
                if pending_key:
                    carried = lots.pop(pending_key)
                    if "__pending_desc" in descriptions:
                        descriptions[isin] = descriptions.pop("__pending_desc")
                    for l in carried:
                        # new ISIN's share count differs (that's the whole point of the
                        # split) but total cost basis is preserved, just re-priced per share
                        new_price = (l["shares"] * l["price"]) / shares
                        lots[isin].append({"date": l["date"], "shares": shares, "price": new_price})
            continue

        if r["type"] in ("Buy", "Reinvestment_Distribution", "Savings plan"):
            lots[isin].append({"date": r["date"], "shares": shares, "price": price})
        elif r["type"] == "Sell":
            remaining_to_sell = shares
            while remaining_to_sell > 1e-9 and lots[isin]:
                oldest = lots[isin][0]
                if oldest["shares"] <= remaining_to_sell + 1e-9:
                    remaining_to_sell -= oldest["shares"]
                    lots[isin].pop(0)
                else:
                    oldest["shares"] -= remaining_to_sell
                    remaining_to_sell = 0
            if remaining_to_sell > 1e-6:
                print(f"WARNING: sold {remaining_to_sell} more shares of {isin} than tracked lots had - data gap")

    return lots, descriptions

def main():
    rows = load_transactions()
    print(f"Loaded {len(rows)} security transactions")
    verify_transfers_net_zero(rows)

    lots, descriptions = build_lots(rows)
    lots = {isin: ls for isin, ls in lots.items() if not isin.startswith("__pending_from_")}
    metadata = load_ticker_metadata()

    output_rows = []
    for isin, ls in lots.items():
        meta = metadata.get(isin, {})
        ticker = meta.get("ticker", "")
        sector = meta.get("sector", "")
        company = descriptions.get(isin, isin)
        for l in sorted(ls, key=lambda x: x["date"]):
            if l["shares"] > 1e-6:
                output_rows.append({
                    "Company": company, "Ticker": ticker, "ISIN": isin, "Sector": sector,
                    "Shares": round(l["shares"], 6),
                    "Purchase Date": l["date"].date().isoformat(),
                    "Purchase Price": round(l["price"], 4),
                })

    output_rows.sort(key=lambda r: (r["Ticker"] or r["Company"], r["Purchase Date"]))

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Company", "Ticker", "ISIN", "Sector", "Shares", "Purchase Date", "Purchase Price"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nWrote {len(output_rows)} open lots to {OUTPUT_FILE}")

    print("\nCurrent positions (derived from transactions.csv):")
    lot_totals = defaultdict(float)
    for r in output_rows:
        if r["Ticker"]:
            lot_totals[r["Ticker"]] += r["Shares"]
    for t in sorted(lot_totals):
        print(f"  {t:10s} {lot_totals[t]:>10.4f} shares")

    no_ticker = sorted(isin for isin in lots if isin not in metadata)
    if no_ticker:
        print(f"\nISINs with open positions but NO row in ticker_map.csv - "
              f"run scaffold_metadata.py, or add manually: {no_ticker}")

    no_sector = sorted(metadata[isin]["ticker"] for isin in lots
                        if isin in metadata and not metadata[isin]["sector"])
    if no_sector:
        print(f"\nticker_map.csv rows with a Ticker but a blank Sector - "
              f"fill in Sector for: {no_sector}")

if __name__ == "__main__":
    main()
