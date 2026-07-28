#!/usr/bin/env python3
"""Portfolio compliance checker.

Evaluates the portfolio against every hard rule in INVESTMENT_FRAMEWORK.md
and returns a structured report the agent reads - it never re-applies the
rules itself.

Checks performed:
  - Sleeve split (Core ~80% / Tactical ~20%), based on role assignments
  - Max single non-hedge position (<=20% of investable)
  - Secure-hedge category cap (<=30% combined)
  - Top-3 combined (<=40%)
  - Sector concentration (each sector <=40%)
  - Cash ceiling (<=EUR 5,000 reserve; above that is a breach)
  - Small positions: positions below EUR 250 whose exit would cost EUR 0.99
    (i.e. not PRIME ETF buys - those are free to buy but cost to sell)
  - Fee drag history summary (delegated to fees.py)

All percentages are of the investable portfolio (securities only, cash excluded).
Roles determine sleeve membership; missing roles are flagged separately.

The hedge-ticker set is maintained in fee_rules.json under "hedge_isins" so
it can be updated without touching code.
"""

import csv
from datetime import date
from typing import Optional

from .config import load_config
from .fees import (fee_drag_summary, fee_drag_by_ticker, prime_status_from_transactions,
                   load_fee_rules, FEE_FREE)
from ..paths import ROLES_FILE, FEE_RULES_FILE

# Sleeve mapping: role label -> sleeve name. The mapping itself is structural
# (determined by role definitions), not a tunable threshold, so it stays in code.
ROLE_TO_SLEEVE = {
    "Core Compounder": "Core",
    "Growth": "Core",
    "Defensive": "Core",
    "Opportunistic": "Tactical",
}


def _load_roles() -> dict:
    """Ticker -> {"role", "note"}.  Empty dict if file absent.

    `note` is a free-text human annotation on the role assignment (e.g.
    flagging an instrument that structurally doesn't fit the framework at
    all) - captured here, not just `role`, so it can be surfaced
    automatically by `_role_notes()` below rather than requiring an agent to
    remember to call `read_roles` separately to see it. See AGENT_NOTES.md's
    2026-07-28 entry: 3BRS.MI's note ("decays structurally, placed here by
    default") existed the whole time but nothing wired it into automated
    output until this was added.
    """
    if not ROLES_FILE.exists():
        return {}
    with open(ROLES_FILE, newline="") as f:
        return {r["Ticker"].strip(): {"role": r.get("Role", "").strip(),
                                      "note": r.get("Note", "").strip()}
                for r in csv.DictReader(f) if r.get("Ticker", "").strip()}


def _load_positions_with_value(analysis_positions: list) -> list:
    """Filter to priced positions only and attach their role/sleeve/role_note."""
    roles = _load_roles()
    instrument_rules = load_fee_rules()
    hedge_isins = set(instrument_rules.get("hedge_isins", []))

    positions = []
    for p in analysis_positions:
        if p.get("value") is None:
            continue
        ticker = p["ticker"]
        role_info = roles.get(ticker, {})
        role = role_info.get("role", "")
        role_note = role_info.get("note", "")
        sleeve = ROLE_TO_SLEEVE.get(role, "Unknown")
        # Determine hedge status by ISIN (requires the position to carry ISIN,
        # which analysis.py doesn't include).  Fall back to description match.
        # The hedge_isins list in fee_rules.json is the authoritative source.
        is_hedge = p.get("isin", "") in hedge_isins
        if not is_hedge and instrument_rules.get("hedge_descriptions"):
            dl = p.get("company", "").lower()
            is_hedge = any(h.lower() in dl for h in instrument_rules["hedge_descriptions"])
        positions.append({**p, "role": role, "sleeve": sleeve, "is_hedge": is_hedge,
                          "role_note": role_note})
    return positions


def _role_notes(positions: list) -> list:
    """Positions whose role carries a human-authored note - typically flagging
    an instrument that structurally doesn't fit the framework (e.g. a
    leveraged/inverse daily-reset product that decays regardless of
    direction). These pre-existing annotations in roles.csv should never
    require an agent to remember to call read_roles separately to notice
    them - see the module docstring on `_load_roles`."""
    return [{"ticker": p["ticker"], "company": p["company"], "role": p["role"],
             "note": p["role_note"]}
            for p in positions if p.get("role_note")]


def _check_sleeve_split(positions: list, total_value: float, cfg: dict) -> dict:
    core_target = cfg["core_sleeve_target_pct"]
    tactical_target = cfg["tactical_sleeve_target_pct"]
    drift_threshold = cfg["sleeve_drift_threshold_pp"]

    core_val = sum(p["value"] for p in positions if p["sleeve"] == "Core")
    tactical_val = sum(p["value"] for p in positions if p["sleeve"] == "Tactical")
    unknown_val = sum(p["value"] for p in positions if p["sleeve"] == "Unknown")

    core_pct = round(core_val / total_value * 100, 1) if total_value else 0
    tactical_pct = round(tactical_val / total_value * 100, 1) if total_value else 0
    unknown_pct = round(unknown_val / total_value * 100, 1) if total_value else 0

    core_drift = abs(core_pct - core_target)
    breach = core_drift > drift_threshold

    return {
        "core_pct": core_pct,
        "tactical_pct": tactical_pct,
        "unknown_pct": unknown_pct,
        "core_target_pct": core_target,
        "tactical_target_pct": tactical_target,
        "drift_pp": round(core_drift, 1),
        "breach": breach,
        "note": (f"Core sleeve at {core_pct}%, {core_drift:.1f}pp from {core_target}% target"
                 if breach else f"Core/Tactical split on target ({core_pct}% / {tactical_pct}%)"),
    }


def _check_concentration(positions: list, total_value: float, cfg: dict) -> dict:
    max_single = cfg["max_single_position_pct"]
    max_hedge = cfg["max_hedge_combined_pct"]
    max_top3 = cfg["max_top3_combined_pct"]

    results = {"max_single": [], "hedge_combined": {}, "top3": {}, "breaches": []}

    # Max single non-hedge position
    non_hedge = sorted([p for p in positions if not p["is_hedge"]],
                       key=lambda p: -p["value"])
    for p in non_hedge:
        pct = round(p["value"] / total_value * 100, 1) if total_value else 0
        if pct > max_single:
            results["max_single"].append({
                "ticker": p["ticker"], "value_eur": p["value"], "pct": pct,
                "limit_pct": max_single,
            })
            results["breaches"].append(
                f"{p['ticker']} {pct}% exceeds {max_single}% single-position limit"
            )

    # Hedge combined
    hedge_val = sum(p["value"] for p in positions if p["is_hedge"])
    hedge_pct = round(hedge_val / total_value * 100, 1) if total_value else 0
    hedge_breach = hedge_pct > max_hedge
    results["hedge_combined"] = {
        "value_eur": round(hedge_val, 2), "pct": hedge_pct,
        "limit_pct": max_hedge, "breach": hedge_breach,
    }
    if hedge_breach:
        over_eur = round(hedge_val - total_value * max_hedge / 100, 2)
        results["breaches"].append(
            f"Hedge holdings {hedge_pct}% exceeds {max_hedge}% cap "
            f"(over by EUR {over_eur:,.2f})"
        )

    # Top 3 combined (all positions, hedge or not)
    top3 = sorted(positions, key=lambda p: -p["value"])[:3]
    top3_val = sum(p["value"] for p in top3)
    top3_pct = round(top3_val / total_value * 100, 1) if total_value else 0
    top3_breach = top3_pct > max_top3
    results["top3"] = {
        "tickers": [p["ticker"] for p in top3],
        "value_eur": round(top3_val, 2), "pct": top3_pct,
        "limit_pct": max_top3, "breach": top3_breach,
    }
    if top3_breach:
        results["breaches"].append(
            f"Top 3 positions ({', '.join(p['ticker'] for p in top3)}) "
            f"combined {top3_pct}% exceeds {max_top3}% limit"
        )

    return results


def _check_sectors(sector_breakdown: list, cfg: dict) -> dict:
    max_sector = cfg["max_sector_pct"]
    breaches = []
    for s in sector_breakdown:
        if s.get("pct_of_portfolio") and s["pct_of_portfolio"] > max_sector:
            breaches.append({
                "sector": s["sector"], "pct": s["pct_of_portfolio"],
                "limit_pct": max_sector,
            })
    return {
        "breaches": [f"{b['sector']} {b['pct']}% exceeds {max_sector}% sector limit"
                     for b in breaches],
        "details": breaches,
    }


def _check_cash(cash_balance_eur: Optional[float], cfg: dict) -> dict:
    ceiling = cfg["cash_ceiling_eur"]
    if cash_balance_eur is None:
        return {"balance_eur": None, "breach": False,
                "note": "cash balance unavailable - run cash check first"}
    breach = cash_balance_eur > ceiling
    excess = round(cash_balance_eur - ceiling, 2) if breach else 0.0
    return {
        "balance_eur": cash_balance_eur,
        "ceiling_eur": ceiling,
        "breach": breach,
        "note": (f"Cash EUR {cash_balance_eur:,.2f} exceeds EUR {ceiling:,.0f} ceiling "
                 f"by EUR {excess:,.2f} - deploy or withdraw the excess"
                 if breach else
                 f"Cash EUR {cash_balance_eur:,.2f} within EUR {ceiling:,.0f} ceiling"),
    }


def _check_small_positions(positions: list, prime_active: bool, cfg: dict, fee_cfg: dict) -> dict:
    """Flag positions below the threshold whose exit would cost the flat fee
    (or the post-migration fee). PRIME ETF buys >= 250 are free but *sells*
    still cost without PRIME, so those appear here too."""
    threshold = cfg["small_position_threshold_eur"]
    fee_flat = fee_cfg["flat_eur"]
    fee_xetra = fee_cfg["xetra_eur"]
    migration_date = date.fromisoformat(fee_cfg["xetra_migration_date"])

    today = date.today()
    post_migration = today >= migration_date
    exit_fee = fee_xetra if post_migration else (FEE_FREE if prime_active else fee_flat)

    if exit_fee == FEE_FREE:
        return {"exit_fee_eur": FEE_FREE, "threshold_eur": threshold, "small_positions": [],
                "note": "PRIME active - exits are free, no minimum-size concern"}

    small = []
    for p in positions:
        if p["value"] >= threshold:
            continue
        round_trip = exit_fee * 2
        drag_pct = round(round_trip / p["value"] * 100, 1) if p["value"] else None
        small.append({
            "ticker": p["ticker"],
            "value_eur": p["value"],
            "exit_fee_eur": exit_fee,
            "round_trip_eur": round_trip,
            "round_trip_drag_pct": drag_pct,
            "role": p.get("role", ""),
            "sleeve": p.get("sleeve", ""),
        })

    small.sort(key=lambda x: x["value_eur"])
    return {
        "exit_fee_eur": exit_fee,
        "threshold_eur": threshold,
        "small_positions": small,
        "note": (f"{len(small)} position(s) below EUR {threshold} "
                 f"- exit costs EUR {exit_fee} each (round-trip EUR {exit_fee * 2})"
                 if small else
                 f"No positions below EUR {threshold}"),
    }


def _missing_roles(positions: list) -> list:
    """Tickers with no role assigned - their sleeve is unknown so compliance is partial."""
    return [p["ticker"] for p in positions if not p.get("role")]


def main(
    analysis_positions: list,
    sector_breakdown: list,
    total_value: float,
    cash_balance_eur: Optional[float] = None,
) -> dict:
    """Run all compliance checks.  Inputs come directly from analyze_portfolio's output
    (pass `analysis["positions"]`, `analysis["sectors"]`, `analysis["totals"]["total_value"]`).
    Cash comes from cash.balance()["balance_eur"].

    Returns a structured dict with:
      - breaches: list of human-readable breach strings (empty = clean)
      - sleeve_split, concentration, sectors, cash, small_positions: per-check detail
      - fee_history: aggregate fee drag from fees.fee_drag_summary()
      - fee_drag_by_ticker: lifetime fees per ticker, including closed positions
      - prime_status: current PRIME subscription status
      - missing_roles: tickers with no role (compliance is partial for these)
      - role_notes: positions whose role has a human-authored note (e.g. an
        instrument flagged as structurally not fitting the framework)
    """
    config = load_config()
    cfg = config["compliance"]
    fee_cfg = config["fees"]

    prime = prime_status_from_transactions()
    positions = _load_positions_with_value(analysis_positions)

    sleeve = _check_sleeve_split(positions, total_value, cfg)
    concentration = _check_concentration(positions, total_value, cfg)
    sectors = _check_sectors(sector_breakdown, cfg)
    cash = _check_cash(cash_balance_eur, cfg)
    small = _check_small_positions(positions, prime["active"], cfg, fee_cfg)
    missing = _missing_roles(positions)
    role_notes = _role_notes(positions)

    all_breaches = []
    if sleeve["breach"]:
        all_breaches.append(sleeve["note"])
    all_breaches.extend(concentration["breaches"])
    all_breaches.extend(sectors["breaches"])
    if cash["breach"]:
        all_breaches.append(cash["note"])

    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "breaches": all_breaches,
        "breach_count": len(all_breaches),
        "sleeve_split": sleeve,
        "concentration": concentration,
        "sectors": sectors,
        "cash": cash,
        "small_positions": small,
        "fee_history": fee_drag_summary(),
        # Lifetime fees per ticker, incl. closed positions - what churn actually
        # cost, as distinct from analyze_portfolio's open-lot-only fees_eur.
        "fee_drag_by_ticker": fee_drag_by_ticker(),
        "prime_status": prime,
        "missing_roles": missing,
        "missing_roles_note": (
            f"Roles missing for {len(missing)} position(s): {', '.join(missing)} "
            f"- sleeve split and some concentration checks are partial until assigned"
            if missing else "All positions have roles assigned"
        ),
        # Human-authored notes on role assignments - e.g. flagging an instrument
        # that structurally doesn't fit the framework at all (leveraged/inverse
        # decay products). Surfaced unconditionally so a pre-existing annotation
        # in roles.csv is never missed just because nobody thought to call
        # read_roles separately - see _role_notes()'s docstring.
        "role_notes": role_notes,
    }


if __name__ == "__main__":
    # main() takes analyze_portfolio's output as arguments rather than reading a
    # file, so unlike the other pipeline modules it needs those inputs assembled
    # first. Done here so the module still honours the "every module runs
    # directly with -m" convention (see ARCHITECTURE.md's Code layout) instead of
    # forcing every caller to wire analysis -> compliance by hand.
    import json

    from . import analysis as _analysis
    from . import cash as _cash

    _d = _analysis.main()
    _c = _cash.balance()
    print(json.dumps(main(
        analysis_positions=_d["positions"],
        sector_breakdown=_d["sectors"],
        total_value=_d["totals"]["total_value"],
        cash_balance_eur=_c.get("balance_eur") if _c.get("complete") else None,
    ), indent=2, default=str))
