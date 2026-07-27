#!/usr/bin/env python3
"""Cash balance from the broker transaction history.

Why this exists: `lots.py` filters to `assetType == "Security"` and discards
every `Cash` row - deposits, withdrawals, transfers, distributions, interest,
taxes, fees. That's correct for building FIFO lots, but it meant the pipeline
had no concept of cash at all, with two consequences:

  1. The framework's cash guidance (5-10% in normal markets, 10-25% in
     uncertain ones - see INVESTMENT_FRAMEWORK.md) could never be checked.
  2. Every reported weight was a share of *securities*, not of the portfolio.
     A position at "36% of the portfolio" is only 36% of your actual wealth if
     cash is ~0.

Method: the balance is just the running sum of every executed row's signed
`amount`, minus fees and taxes carried in their own columns. Security buys are
negative amounts and sells positive, so securities and cash rows reconcile
against each other in one pass - no separate accounting needed.

Sanity check: for a complete export the result should be a small, plausible
balance. When this was first written it came to EUR 7.93 across 268 rows,
which is what "the export is internally consistent" looks like - a wildly
negative or implausibly large number means rows are missing (a partial export,
or a broker migration with no opening balance), so `balance()` returns that
diagnosis alongside the figure rather than a bare number.
"""

import csv
from datetime import datetime

from ..paths import TRANSACTIONS_FILE

# A balance outside this range means the export almost certainly isn't complete
# rather than that the user really holds that much/little - see module docstring.
IMPLAUSIBLE_NEGATIVE = -1.0


def _parse_number(s):
    """German decimal format: '1.074,00' -> 1074.00. Blank -> 0.0."""
    s = (s or "").strip()
    if not s:
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def load_cash_rows():
    """Every executed row with its signed cash effect, oldest first."""
    rows = []
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r["status"] != "Executed":
                continue
            rows.append({
                "date": datetime.strptime(f'{r["date"]} {r["time"]}', "%Y-%m-%d %H:%M:%S"),
                "asset_type": r["assetType"],
                "type": r["type"],
                # amount is signed by the broker (buys negative, sells/deposits positive);
                # fee and tax are separate positive columns that always reduce cash
                "delta": _parse_number(r["amount"]) - _parse_number(r["fee"]) - _parse_number(r["tax"]),
            })
    rows.sort(key=lambda r: r["date"])
    return rows


def balance():
    """Current cash balance plus a completeness diagnosis.

    Returns {"balance_eur", "rows_counted", "complete", "note"}. `complete` is
    False when the running balance implies missing rows - reported rather than
    silently trusted, because a wrong cash figure would distort every weight
    downstream (see module docstring).
    """
    if not TRANSACTIONS_FILE.exists():
        return {"balance_eur": None, "rows_counted": 0, "complete": False,
                "note": "no transaction history uploaded yet"}

    rows = load_cash_rows()
    total = round(sum(r["delta"] for r in rows), 2)

    complete, note = True, ""
    if not rows:
        complete, note = False, "transaction history is empty"
    elif total < IMPLAUSIBLE_NEGATIVE:
        complete = False
        note = (f"implied cash is negative ({total:.2f} EUR), which a cash account cannot be - "
                f"the export is probably missing rows (partial export, or a broker migration "
                f"with no opening balance). Treat cash-based checks as unreliable until fixed.")
    return {"balance_eur": total, "rows_counted": len(rows), "complete": complete, "note": note}


def main():
    result = balance()
    print(f"Cash balance: EUR {result['balance_eur']:,.2f} "
          f"(from {result['rows_counted']} executed transactions)")
    if not result["complete"]:
        print(f"WARNING: {result['note']}")


if __name__ == "__main__":
    main()
