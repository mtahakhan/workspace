#!/usr/bin/env python3
"""Fee computation for Scalable Capital orders.

This module encodes the broker's published fee schedule so the agent never
has to apply the rules itself - it just reads the output.

For **executed** orders, the broker's recorded `fee` column is ground truth;
call `fee_for_executed_row()` to read it directly.

For **prospective** orders, `fee_for_prospective_order()` returns the
deterministic fee from the rules below, verified zero-exception against
268 real orders (2024-10 to 2026-07).

Rules (EIX/gettex platform, valid until xetra_migration_date in config.json):
  - Savings-plan / dividend-reinvestment rows: EUR 0.00 always
  - PRIME ETF (issuer in prime_etf_issuers in fee_rules.json) Buy >= EUR 250:
    EUR 0.00 regardless of PRIME subscription
  - All other trades: flat_eur without PRIME, EUR 0.00 with active PRIME

After xetra_migration_date:
  - All trades: xetra_eur regardless of instrument or subscription tier.
  - The PRIME ETF free-buy rule ends entirely.

Numeric fee amounts and the migration date live in config.json ("fees" section).
The issuer/ISIN lists live in fee_rules.json (impersonal/, committed).
"""

import csv
import json
from datetime import date, datetime
from typing import Optional

from .config import load_config
from ..paths import TRANSACTIONS_FILE, FEE_RULES_FILE, TICKER_MAP_FILE, ENRICHED_LOTS_FILE

FEE_FREE = 0.0


def load_fee_rules() -> dict:
    """Load fee_rules.json.  Returns a safe default if file is absent."""
    if not FEE_RULES_FILE.exists():
        return {"prime_etf_issuers": ["amundi", "ishares", "vanguard", "xtrackers"]}
    return json.loads(FEE_RULES_FILE.read_text(encoding="utf-8"))


def _is_prime_etf(description: str, prime_etf_issuers: list[str]) -> bool:
    """True when the instrument's description names a PRIME ETF issuer."""
    dl = description.lower()
    return any(issuer in dl for issuer in prime_etf_issuers)


def _parse_number(s: str) -> float:
    """German decimal format: '1.074,00' -> 1074.00. Blank -> 0.0."""
    s = (s or "").strip()
    if not s:
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fee_for_executed_row(row: dict) -> float:
    """Read the fee for an already-executed transaction row.

    `row` must have a `fee` key in German decimal format (as in transactions.csv).
    Returns the broker's recorded fee as a float - this is ground truth, no
    inference.
    """
    return _parse_number(row.get("fee", "0"))


def fee_for_prospective_order(
    order_type: str,
    description: str,
    amount_eur: float,
    trade_date: Optional[date] = None,
    prime_active: bool = False,
) -> dict:
    """Compute the expected fee for a not-yet-executed order.

    Args:
        order_type:   'Buy', 'Sell', 'Savings plan', or 'Reinvestment_Distribution'
        description:  Instrument name as it would appear in the broker export
        amount_eur:   Absolute order value in EUR (positive)
        trade_date:   Date of the trade (defaults to today)
        prime_active: Whether the PRIME+ subscription is currently active

    Returns a dict with:
        fee_eur     - expected fee
        rule        - short explanation of which rule applied
        post_migration - True if the Xetra fee schedule applies
    """
    cfg = load_config()["fees"]
    fee_flat = cfg["flat_eur"]
    fee_xetra = cfg["xetra_eur"]
    migration_date = date.fromisoformat(cfg["xetra_migration_date"])

    instrument_rules = load_fee_rules()
    prime_etf_issuers = instrument_rules.get("prime_etf_issuers", [])

    effective_date = trade_date or date.today()
    post_migration = effective_date >= migration_date

    if post_migration:
        return {"fee_eur": fee_xetra,
                "rule": f"post-migration flat rate (Xetra/gettex from {cfg['xetra_migration_date']})",
                "post_migration": True}

    # Always free regardless of platform or subscription
    if order_type in ("Savings plan", "Reinvestment_Distribution"):
        return {"fee_eur": FEE_FREE, "rule": f"{order_type} - always free", "post_migration": False}

    # PRIME ETF buy >= EUR 250: free on FREE tier too
    if (order_type == "Buy"
            and _is_prime_etf(description, prime_etf_issuers)
            and amount_eur >= 250.0):
        return {"fee_eur": FEE_FREE,
                "rule": "PRIME ETF buy >= EUR 250 - free on both tiers",
                "post_migration": False}

    # Everything else: free under PRIME, flat rate otherwise
    if prime_active:
        return {"fee_eur": FEE_FREE, "rule": "PRIME subscription active", "post_migration": False}

    return {"fee_eur": fee_flat, "rule": "standard EIX/gettex flat rate", "post_migration": False}


def prime_status_from_transactions() -> dict:
    """Derive PRIME subscription status from the transaction export.

    Looks for the most recent 'Deposit' row whose description contains 'PRIME bis'
    and parses the expiry date from it.  Returns:
        {"active": bool, "expires": "YYYY-MM-DD" | None, "note": str}
    """
    if not TRANSACTIONS_FILE.exists():
        return {"active": False, "expires": None, "note": "no transaction history"}

    import re
    latest_expiry = None

    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("status") != "Executed":
                continue
            if r.get("type") != "Deposit":
                continue
            desc = r.get("description", "")
            m = re.search(r"PRIME bis (\d{2})\.(\d{2})\.(\d{4})", desc)
            if m:
                expiry = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                if latest_expiry is None or expiry > latest_expiry:
                    latest_expiry = expiry

    today = date.today()
    if latest_expiry is None:
        return {"active": False, "expires": None, "note": "no PRIME subscription rows found"}
    if latest_expiry >= today:
        return {"active": True, "expires": latest_expiry.isoformat(),
                "note": f"PRIME active until {latest_expiry.isoformat()}"}
    return {"active": False, "expires": latest_expiry.isoformat(),
            "note": f"PRIME expired {latest_expiry.isoformat()}"}


def fee_drag_summary() -> dict:
    """Compute aggregate fee statistics from the real transaction history.

    Returns a dict with total fees paid, per-bucket stats (by order size),
    and the worst N orders by fee-drag percentage.  Used by check_compliance
    to give a historical context section in the report.
    """
    if not TRANSACTIONS_FILE.exists():
        return {"error": "no transaction history"}

    rules = load_fee_rules()
    prime_etf_issuers = rules.get("prime_etf_issuers", [])

    paid = []
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("status") != "Executed" or r.get("assetType") != "Security":
                continue
            fee = _parse_number(r.get("fee", "0"))
            if fee <= 0:
                continue
            amount = abs(_parse_number(r.get("amount", "0")))
            if amount <= 0:
                continue
            paid.append({
                "date": r["date"],
                "description": r.get("description", "")[:40],
                "amount_eur": amount,
                "fee_eur": fee,
                "drag_pct": round(fee / amount * 100, 2),
            })

    if not paid:
        return {"total_fees_eur": 0.0, "orders_with_fee": 0, "buckets": [], "worst_orders": []}

    total = round(sum(o["fee_eur"] for o in paid), 2)
    buckets = []
    for lo, hi, label in [(0, 25, "<EUR 25"), (25, 50, "EUR 25-50"),
                          (50, 100, "EUR 50-100"), (100, 250, "EUR 100-250"),
                          (250, float("inf"), ">EUR 250")]:
        b = [o for o in paid if lo <= o["amount_eur"] < hi]
        if b:
            buckets.append({
                "label": label, "count": len(b),
                "avg_drag_pct": round(sum(o["drag_pct"] for o in b) / len(b), 2),
            })

    worst = sorted(paid, key=lambda o: -o["drag_pct"])[:6]
    return {
        "total_fees_eur": total,
        "orders_with_fee": len(paid),
        "buckets": buckets,
        "worst_orders": worst,
    }


def fee_drag_by_ticker(top_n: int = 10) -> list:
    """Lifetime fees paid per ticker, including on positions since closed.

    Distinct from `analyze_portfolio`'s per-position `fees_eur`, which counts only
    the entry fees still attached to *open* lots. The difference is what churn
    actually cost: a ticker traded in and out repeatedly keeps paying EUR 0.99 per
    order while its open-lot fees stay small. 3BRS.MI is the worked example - 11
    orders, EUR 10.89 lifetime, against EUR 2.97 on the lots still open.

    Keyed by ticker via ticker_map.csv; ISINs with no mapping are grouped under
    their ISIN so a closed position never silently drops out of the total.
    """
    if not TRANSACTIONS_FILE.exists():
        return []

    isin_to_ticker = {}
    if TICKER_MAP_FILE.exists():
        with open(TICKER_MAP_FILE, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Ticker"):
                    isin_to_ticker[row["ISIN"]] = row["Ticker"]

    # A security that went through an ISIN swap paid most of its fees under the
    # OLD identifier, which has no ticker_map row of its own (only the surviving
    # ISIN needs one). Without this the fees show up orphaned under a dead ISIN
    # instead of against the ticker still holding the position. Read from lot
    # provenance so no dead ISIN has to be hand-maintained in ticker_map.csv.
    if ENRICHED_LOTS_FILE.exists():
        with open(ENRICHED_LOTS_FILE, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("CA From ISIN") and row.get("Ticker"):
                    isin_to_ticker.setdefault(row["CA From ISIN"], row["Ticker"])

    by_key = {}
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("status") != "Executed" or r.get("assetType") != "Security":
                continue
            fee = _parse_number(r.get("fee", "0"))
            if fee <= 0:
                continue
            isin = r.get("isin", "")
            key = isin_to_ticker.get(isin, isin or "unknown")
            e = by_key.setdefault(key, {"ticker": key, "orders": 0, "fees_eur": 0.0,
                                        "turnover_eur": 0.0})
            e["orders"] += 1
            e["fees_eur"] += fee
            e["turnover_eur"] += abs(_parse_number(r.get("amount", "0")))

    for e in by_key.values():
        e["fees_eur"] = round(e["fees_eur"], 2)
        e["turnover_eur"] = round(e["turnover_eur"], 2)
        e["drag_pct"] = round(e["fees_eur"] / e["turnover_eur"] * 100, 2) if e["turnover_eur"] else None

    return sorted(by_key.values(), key=lambda e: -e["fees_eur"])[:top_n]
