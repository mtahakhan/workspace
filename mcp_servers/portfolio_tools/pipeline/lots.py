#!/usr/bin/env python3
"""
Build FIFO cost-basis lots from transactions.csv -> transaction_lots.csv.
Full rationale and rules: see AGENT_NOTES.md (read that before changing this
file - don't rely on figuring out the "why" from reading this source).

Quick reference: FIFO consumes oldest lots first on a Sell. "Security transfer"
rows are excluded (broker migration artifact). "Corporate action" rows carry
cost basis to the new ISIN, one rescaled lot per original lot (see build_lots).
Order fees are captured per lot in a Fee column, so cost basis can be all-in
without distorting the recorded execution price.

Output is ISIN-keyed and contains no Ticker, Company or Sector - those come
from ticker_map.csv and company_overrides.csv, joined by the separate
enrich_lots step (pipeline/enrich.py). Every downstream tool reads
enriched_lots.csv, not this file; the only callers of this file directly are
tickers.py (to detect ISINs not yet in ticker_map.csv) and enrich.py itself.
"""

import csv
import re
from collections import defaultdict
from datetime import datetime

from ..paths import TRANSACTIONS_FILE, TRANSACTION_LOTS_FILE

OUTPUT_FILE = TRANSACTION_LOTS_FILE

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
                "reference": (r.get("reference") or "").strip('"'),
                "description": r["description"].strip('"'),
                "type": r["type"],
                "isin": r["isin"],
                "shares": parse_number(r["shares"]),
                "price": parse_number(r["price"]),
                # Order fee, always a positive charge in the export. Blank on
                # non-order rows (corporate actions, transfers) -> 0.0.
                "fee": parse_number(r.get("fee")) or 0.0,
            })
    rows.sort(key=lambda r: r["date"])
    return rows


def reference_stem(reference):
    """Pairing key for the two legs of a corporate action.

    The broker gives both legs the same reference stem and suffixes the outgoing
    leg: `537521_..._1` (shares out, old ISIN) and `537521_...` (shares in, new
    ISIN). Pairing on this stem rather than "whichever swap happens to be
    pending" is what keeps two overlapping swaps from cross-wiring their cost
    bases - with one swap in the history either works, which is exactly why the
    weaker version survived unnoticed.
    """
    return re.sub(r"_\d+$", "", reference or "")

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
    """FIFO lots per ISIN. Returns ({isin: [{"date", "shares", "price", "fee"}, ...]},
    descriptions, unmatched_swaps).

    Note this keys lots by ISIN straight from transactions.csv and never consults
    ticker_map.csv - the map is applied to *output* in main(). That is why a
    corporate action's old ISIN carries its cost basis correctly while having no
    ticker_map row of its own: only the surviving ISIN ever needs a mapping.
    """
    lots = defaultdict(list)
    descriptions = {}
    pending_swaps = {}  # reference stem -> outgoing leg awaiting its incoming leg

    for r in rows:
        isin, shares, price = r["isin"], r["shares"], r["price"]
        # The broker sometimes puts the bare ISIN in the description field (seen on
        # the incoming leg of a corporate action). That is an identifier, not a
        # company name, and must not become one - compared against this row's own
        # ISIN rather than any specific hardcoded value, so it holds for the next
        # swap too.
        if r["description"] and r["description"] != isin:
            descriptions[isin] = r["description"]

        if r["type"] == "Security transfer":
            continue  # verified net-zero migration artifact, not a real transaction

        if r["type"] == "Corporate action":
            # ISIN swap / share consolidation (e.g. a reverse split). The
            # negative-share leg on the OLD isin releases that ISIN's open lots;
            # the positive-share leg on the NEW isin is where they land. The
            # original purchase dates carry across deliberately: a consolidation
            # is not a disposal, so the holding period must not restart.
            stem = reference_stem(r["reference"])
            if shares < 0:
                outgoing = lots.pop(isin, [])
                if outgoing:
                    pending_swaps[stem] = {"lots": outgoing, "old_isin": isin,
                                           "description": descriptions.get(isin)}
            else:
                swap = pending_swaps.pop(stem, None)
                if swap:
                    old_lots = swap["lots"]
                    total_old = sum(l["shares"] for l in old_lots)
                    if total_old > 0 and shares > 0:
                        if swap["description"]:
                            descriptions[isin] = swap["description"]
                        # One rescaled lot per original lot. Collapsing them into a
                        # single lot dated at their weighted-average timestamp would
                        # invent a purchase date on which no purchase happened, and
                        # destroy the per-lot grain that later FIFO sells and
                        # tax-lot tracking depend on. Each lot keeps its own date,
                        # total cost and fee; only the share count is rescaled.
                        for l in old_lots:
                            new_shares = l["shares"] / total_old * shares
                            lot_cost = l["shares"] * l["price"]
                            lots[isin].append({
                                "date": l["date"],
                                "shares": new_shares,
                                "price": lot_cost / new_shares,
                                "fee": l["fee"],
                                # Provenance, so a reader of the lot file can see why
                                # this lot's share count and price look nothing like
                                # any order in transactions.csv. Ratio is old:new -
                                # >1 is a reverse consolidation. A lot through two
                                # swaps keeps its original date but records the most
                                # recent event.
                                "ca_from": swap["old_isin"],
                                "ca_ratio": total_old / shares,
                                "ca_date": r["date"],
                            })
            continue

        if r["type"] in ("Buy", "Reinvestment_Distribution", "Savings plan"):
            lots[isin].append({"date": r["date"], "shares": shares, "price": price, "fee": r["fee"]})
        elif r["type"] == "Sell":
            remaining_to_sell = shares
            while remaining_to_sell > 1e-9 and lots[isin]:
                oldest = lots[isin][0]
                if oldest["shares"] <= remaining_to_sell + 1e-9:
                    remaining_to_sell -= oldest["shares"]
                    lots[isin].pop(0)
                else:
                    # Partial consumption: the entry fee follows the shares that
                    # remain open, so the surviving lot's all-in cost stays
                    # proportional. Computed before shares are decremented.
                    oldest["fee"] *= 1 - (remaining_to_sell / oldest["shares"])
                    oldest["shares"] -= remaining_to_sell
                    remaining_to_sell = 0
            if remaining_to_sell > 1e-6:
                print(f"WARNING: sold {remaining_to_sell} more shares of {isin} than tracked lots had - data gap")

    return lots, descriptions, pending_swaps

LOT_FIELDS = [
    "ISIN", "Company", "Shares", "Purchase Date", "Purchase Price", "Fee",
    "CA From ISIN", "CA Ratio", "CA Date",
]


def main():
    rows = load_transactions()
    print(f"Loaded {len(rows)} security transactions")
    verify_transfers_net_zero(rows)

    lots, descriptions, unmatched_swaps = build_lots(rows)
    if unmatched_swaps:
        # An outgoing corporate-action leg whose incoming leg never arrived means
        # that position's entire cost basis silently vanished from the output.
        # Loud, because the resulting lot file looks perfectly well-formed.
        print(f"WARNING: {len(unmatched_swaps)} corporate action(s) released lots that were never "
              f"re-landed on a new ISIN - cost basis for these is MISSING from the output:")
        for stem, swap in sorted(unmatched_swaps.items()):
            shares = sum(l["shares"] for l in swap["lots"])
            cost = sum(l["shares"] * l["price"] for l in swap["lots"])
            print(f"         {swap['old_isin']} (ref {stem}): {shares:.6f} shares, EUR {cost:.2f}")

    output_rows = []
    for isin, ls in lots.items():
        broker_name = descriptions.get(isin, isin)
        for l in sorted(ls, key=lambda x: x["date"]):
            if l["shares"] > 1e-6:
                output_rows.append({
                    "ISIN": isin,
                    "Company": broker_name,
                    "Shares": round(l["shares"], 6),
                    "Purchase Date": l["date"].date().isoformat(),
                    # The actual execution price, never fee-adjusted. Fee is a
                    # separate column so all-in cost is available without the
                    # recorded price silently ceasing to mean "what it traded at".
                    "Purchase Price": round(l["price"], 4),
                    "Fee": round(l["fee"], 4),
                    # Blank on ordinary lots; set only where a corporate action
                    # rescaled this lot (see build_lots).
                    "CA From ISIN": l.get("ca_from", ""),
                    "CA Ratio": round(l["ca_ratio"], 6) if "ca_ratio" in l else "",
                    "CA Date": l["ca_date"].date().isoformat() if "ca_date" in l else "",
                })

    output_rows.sort(key=lambda r: (r["ISIN"], r["Purchase Date"]))

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOT_FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nWrote {len(output_rows)} open lots to {OUTPUT_FILE}")
    print("Run enrich_lots next to join ticker_map + company_overrides -> enriched_lots.csv")

    print("\nCurrent positions (ISIN-keyed, no Ticker yet — see enriched_lots.csv after enrich_lots):")
    lot_totals = defaultdict(float)
    for r in output_rows:
        lot_totals[r["ISIN"]] += r["Shares"]
    for isin in sorted(lot_totals):
        print(f"  {isin}  {lot_totals[isin]:>10.4f} shares")

    # Only ISINs that still hold shares.
    open_isins = {isin for isin, ls in lots.items() if sum(l["shares"] for l in ls) > 1e-6}
    print(f"\n{len(open_isins)} open ISIN(s) — run resolve_tickers if any are new, "
          f"then enrich_lots to produce enriched_lots.csv")

if __name__ == "__main__":
    main()
