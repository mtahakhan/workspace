#!/usr/bin/env python3
"""
Deterministic portfolio metrics calculator - the numeric layer of the daily
analysis. Prints structured JSON so the LLM-driven report only has to write
narrative/research around these numbers, never compute them itself. Full
rationale/rules (including why trend and drawdown deliberately use different
history-scoping methodologies, why XIRR needs weighted_avg_holding_days
context, and the historical-data-quality guard): see AGENT_NOTES.md - read
that first, not this file, to understand the "why" behind anything below.

Indicators: position/portfolio value & gain/loss, sector breakdown, largest
positions, high-water-mark/drawdown, daily movers, trend (since-inception/30d/
90d/365d), annualized return (XIRR), stale_prices, and a deterministic
notable/notify_reasons signal for the daily notification decision.
"""

import csv
import json
import sys
from datetime import datetime, timedelta

from .config import load_config
from ..paths import PRICE_HISTORY_DIR, TRANSACTION_LOTS_FILE, ANALYSIS_HISTORY_FILE


def load_transaction_lots():
    """Return {ticker: [{"date", "shares", "price", "company", "sector"}, ...]}
    Missing file / missing ticker -> no lots for it (XIRR falls back gracefully).
    This is also the sole source of current positions - see load_open_positions()."""
    if not TRANSACTION_LOTS_FILE.exists():
        return {}
    lots = {}
    with open(TRANSACTION_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            if not row["Ticker"]:
                continue
            lots.setdefault(row["Ticker"], []).append({
                "date": datetime.strptime(row["Purchase Date"], "%Y-%m-%d"),
                "shares": float(row["Shares"]),
                "price": float(row["Purchase Price"]),
                "company": row["Company"],
                "sector": row["Sector"],
            })
    return lots

def xirr(cashflows):
    """cashflows: [(date, amount), ...] - negative for outflows (purchases),
    positive for the final inflow (current value). Returns annualized rate as
    a percent, or None if unsolvable (needs at least one sign change).
    Bisection, not Newton's method - guaranteed to converge given a valid
    bracket, which matters more here than raw speed for ~20-lot problems."""
    if len(cashflows) < 2:
        return None
    if not (any(cf > 0 for _, cf in cashflows) and any(cf < 0 for _, cf in cashflows)):
        return None
    t0 = min(d for d, _ in cashflows)

    def npv(rate):
        return sum(cf / ((1 + rate) ** ((d - t0).days / 365.0)) for d, cf in cashflows)

    lo, hi = -0.9999, 20.0  # -99.99% to +2000% annualized
    npv_lo, npv_hi = npv(lo), npv(hi)
    if npv_lo * npv_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-6:
            return round(mid * 100, 2)
        if npv_lo * npv_mid < 0:
            hi, npv_hi = mid, npv_mid
        else:
            lo, npv_lo = mid, npv_mid
    return round((lo + hi) / 2 * 100, 2)

def compute_annualized_returns(open_positions, prices, lots):
    """Per-position XIRR (where lot data exists) plus one portfolio-wide XIRR.
    Also returns weighted_avg_holding_days per position - see AGENT_NOTES.md
    ("Annualized return") before interpreting any single position's XIRR."""
    today = datetime.now()
    per_position = {}
    portfolio_cashflows = []

    for pos in open_positions:
        ticker = pos["Ticker"]
        ticker_lots = lots.get(ticker, [])
        price = prices.get(ticker)
        cashflows = [(l["date"], -l["shares"] * l["price"]) for l in ticker_lots]
        if price is not None and ticker_lots:
            current_value = sum(l["shares"] for l in ticker_lots) * price
            cashflows.append((today, current_value))
        rate = xirr(cashflows)
        holding_days = None
        if ticker_lots:
            total_shares = sum(l["shares"] for l in ticker_lots)
            if total_shares:
                weighted_days = sum((today - l["date"]).days * l["shares"] for l in ticker_lots) / total_shares
                holding_days = round(weighted_days)
        per_position[ticker] = {"xirr_pct": rate, "weighted_avg_holding_days": holding_days}
        portfolio_cashflows.extend((d, cf) for d, cf in cashflows if d != today)

    total_current_value = sum(
        sum(l["shares"] for l in lots.get(pos["Ticker"], [])) * prices[pos["Ticker"]]
        for pos in open_positions if pos["Ticker"] in lots and pos["Ticker"] in prices
    )
    portfolio_cashflows.append((today, total_current_value))
    portfolio_rate = xirr(portfolio_cashflows)

    tickers_missing_lots = [pos["Ticker"] for pos in open_positions if pos["Ticker"] not in lots]
    return {
        "portfolio_xirr_pct": portfolio_rate,
        "per_position_xirr_pct": per_position,
        "tickers_without_lot_data": tickers_missing_lots,
    }

def load_open_positions(lots):
    """Derive current open positions (Ticker, Company, Sector, Shares, Bought at
    EUR) from transaction_lots.csv - the sole source, no separate file. "Bought
    at EUR" here is the shares-weighted average cost across that ticker's open
    lots, always in sync with the real transaction history."""
    open_positions = []
    for ticker, ticker_lots in lots.items():
        total_shares = sum(l["shares"] for l in ticker_lots)
        if total_shares <= 1e-9:
            continue
        weighted_cost = sum(l["shares"] * l["price"] for l in ticker_lots) / total_shares
        open_positions.append({
            "Ticker": ticker,
            "Company": ticker_lots[0]["company"],
            "Sector": ticker_lots[0]["sector"],
            "Shares": round(total_shares, 6),
            "Bought at EUR": round(weighted_cost, 4),
        })
    open_positions.sort(key=lambda pos: pos["Ticker"])
    return open_positions

def latest_prices_from_history(all_history):
    """The 'current price' for each ticker is just the last line of its own
    price_history/{TICKER}.jsonl - no separate prices.json snapshot file.
    Returns {ticker: price_eur} for tickers with at least one history point."""
    return {ticker: hist[-1]["price"] for ticker, hist in all_history.items() if hist}

def stale_tickers(all_history, max_age_days):
    """Tickers whose latest history point is older than max_age_days, or that
    have no history at all - replaces what prices.json's missing_tickers used
    to flag, and catches more: a ticker silently failing to fetch for several
    days in a row, not just on today's run."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    stale = []
    for ticker, hist in all_history.items():
        if not hist:
            stale.append({"ticker": ticker, "last_price_date": None})
        elif hist[-1]["timestamp"] < cutoff:
            stale.append({"ticker": ticker, "last_price_date": hist[-1]["timestamp"].date().isoformat()})
    return stale

def _filter_unadjusted_splits(records, ticker, sanity_ratio):
    """Drop historical points >sanity_ratio away from the ticker's current price -
    guards against unadjusted historical splits in yfinance data. See
    AGENT_NOTES.md ("Historical price data quality") for the confirmed case
    this caught. Default (100x) is deliberately generous - never triggers on
    ordinary volatility."""
    if len(records) < 2:
        return records
    latest_price = records[-1]["price"]
    if not latest_price:
        return records
    kept = [r for r in records if 1 / sanity_ratio <= r["price"] / latest_price <= sanity_ratio]
    dropped = len(records) - len(kept)
    if dropped:
        print(f"  {ticker}: dropped {dropped} history points inconsistent with current price "
              f"(likely unadjusted split) - retained {len(kept)}/{len(records)}", file=sys.stderr)
    return kept

def _collapse_to_daily(records):
    """Collapse to one record per calendar day - the last fetch of that day wins.

    `fetch_prices` appends unconditionally (prices.py's append_price_history opens
    the file in "a" mode), so running it N times in a day leaves N records for that
    day - 2026-07-24 has 9 per ticker, 2026-07-25 has 7. But everything downstream
    assumes a daily series: compute_movers' "day-over-day" is literally the last two
    entries, and build_value_series turns each distinct timestamp into its own point.

    Without this collapse a second same-day fetch silently redefines "daily change"
    as "change since the last fetch". Replaying 2026-07-24 (a Friday, 9 records per
    ticker) with the raw history gives 0.00% for all 23 tickers - the day's last two
    fetches returned identical prices - against true day-over-day moves of up to
    +9.26% (SAP.DE) and -8.55% (IREN). Note backfill.py writes exactly one record per
    day (open(..., "w")), so one-per-day is the file's intended grain and fetch_prices
    is the writer that departs from it.

    Do NOT read flat movers as proof of this bug: on a weekend or market holiday the
    quote APIs return the previous close, so genuinely identical consecutive days are
    correct output (2026-07-25 and 07-26 were Sat/Sun). Check the weekday first.

    Keeping the *last* record of each day matches get_current_prices (latest record =
    current price) and preserves that record's real timestamp, so the staleness check
    is unaffected. Duplicates stay on disk untouched - each carries its own source URL
    and FX rate, and that audit trail is worth keeping.
    """
    by_day = {}
    for r in records:  # ascending, so the day's last record overwrites earlier ones
        by_day[r["timestamp"].date()] = r
    return [by_day[day] for day in sorted(by_day)]

def load_ticker_history(ticker, split_adjustment_sanity_ratio):
    """Return [{timestamp: datetime, price: float}, ...] sorted ascending, one record
    per calendar day (see _collapse_to_daily). Empty if no file."""
    path = PRICE_HISTORY_DIR / f"{ticker}.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # price_history/*.jsonl is fully sourced (original currency, source, FX rate, etc.)
            # but "price_eur" is the one field every downstream computation should use -
            # explicitly reading that key here, not any of the original-currency ones.
            records.append({"timestamp": datetime.fromisoformat(obj["timestamp"]), "price": obj["price_eur"]})
    records.sort(key=lambda r: r["timestamp"])
    records = _collapse_to_daily(records)
    return _filter_unadjusted_splits(records, ticker, split_adjustment_sanity_ratio)

def price_at_or_before(history, when):
    """Latest known price at or before `when` (forward-fill). None if no such point exists."""
    result = None
    for r in history:
        if r["timestamp"] <= when:
            result = r["price"]
        else:
            break
    return result

def compute_positions(open_positions, prices):
    positions = []
    for pos in open_positions:
        ticker = pos["Ticker"]
        price = prices.get(ticker)
        cost = pos["Shares"] * pos["Bought at EUR"]
        if price is None:
            positions.append({"ticker": ticker, "company": pos["Company"], "sector": pos["Sector"],
                               "shares": pos["Shares"], "price": None, "value": None,
                               "cost": round(cost, 2), "gain_eur": None, "gain_pct": None})
            continue
        value = pos["Shares"] * price
        gain_eur = value - cost
        gain_pct = (gain_eur / cost * 100) if cost else None
        positions.append({
            "ticker": ticker, "company": pos["Company"], "sector": pos["Sector"],
            "shares": pos["Shares"], "price": price, "value": round(value, 2),
            "cost": round(cost, 2), "gain_eur": round(gain_eur, 2),
            "gain_pct": round(gain_pct, 2) if gain_pct is not None else None,
        })
    return positions

def compute_portfolio_totals(positions):
    total_value = sum(p["value"] for p in positions if p["value"] is not None)
    total_cost = sum(p["cost"] for p in positions)
    gain_eur = total_value - total_cost
    gain_pct = (gain_eur / total_cost * 100) if total_cost else None
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "gain_eur": round(gain_eur, 2),
        "gain_pct": round(gain_pct, 2) if gain_pct is not None else None,
        "positions_priced": sum(1 for p in positions if p["value"] is not None),
        "positions_total": len(positions),
    }

def compute_sector_breakdown(positions, total_value):
    sectors = {}
    for p in positions:
        if p["value"] is None:
            continue
        s = sectors.setdefault(p["sector"], {"value": 0.0, "cost": 0.0, "count": 0})
        s["value"] += p["value"]
        s["cost"] += p["cost"]
        s["count"] += 1
    result = []
    for sector, d in sectors.items():
        gain_pct = ((d["value"] - d["cost"]) / d["cost"] * 100) if d["cost"] else None
        pct_of_portfolio = (d["value"] / total_value * 100) if total_value else None
        result.append({
            "sector": sector, "positions": d["count"], "value": round(d["value"], 2),
            "cost": round(d["cost"], 2),
            "pct_of_portfolio": round(pct_of_portfolio, 2) if pct_of_portfolio is not None else None,
            "gain_pct": round(gain_pct, 2) if gain_pct is not None else None,
        })
    result.sort(key=lambda s: s["value"], reverse=True)
    return result

def compute_largest_positions(positions, top_n):
    priced = [p for p in positions if p["value"] is not None]
    return sorted(priced, key=lambda p: p["value"], reverse=True)[:top_n]

def compute_portfolio_value_series(open_positions, all_history):
    """Reconstruct a daily portfolio-total-value time series by forward-filling
    each ticker's own price history onto the union of all known timestamps."""
    all_dates = sorted({r["timestamp"] for hist in all_history.values() for r in hist})
    series = []
    for d in all_dates:
        total = 0.0
        any_priced = False
        for pos in open_positions:
            price = price_at_or_before(all_history.get(pos["Ticker"], []), d)
            if price is not None:
                total += price * pos["Shares"]
                any_priced = True
        if any_priced:
            series.append({"timestamp": d, "total_value": round(total, 2)})
    return series

def compute_drawdown(full_value_series, current_value):
    if not full_value_series:
        return {"high_water_mark": current_value, "high_water_mark_date": "today", "drawdown_pct": 0.0}
    peak_point = max(full_value_series, key=lambda r: r["total_value"])
    hwm = max(peak_point["total_value"], current_value)
    hwm_date = "today" if current_value >= peak_point["total_value"] else peak_point["timestamp"].date().isoformat()
    drawdown_pct = ((current_value - hwm) / hwm * 100) if hwm else 0.0
    return {"high_water_mark": round(hwm, 2), "high_water_mark_date": hwm_date, "drawdown_pct": round(drawdown_pct, 2)}

def compute_movers(open_positions, all_history, top_n):
    """Day-over-day % change per ticker, using the two most recent history entries.

    That IS day-over-day only because load_ticker_history collapses each ticker's
    history to one record per calendar day - see _collapse_to_daily. Don't feed this
    a raw, uncollapsed history: multiple same-day fetches turn it into an intraday
    change still labelled "daily".
    """
    movers = []
    for pos in open_positions:
        hist = all_history.get(pos["Ticker"], [])
        if len(hist) < 2:
            continue
        prev_price, curr_price = hist[-2]["price"], hist[-1]["price"]
        if prev_price:
            pct = (curr_price - prev_price) / prev_price * 100
            movers.append({"ticker": pos["Ticker"], "company": pos["Company"], "prev_price": prev_price,
                            "curr_price": curr_price, "change_pct": round(pct, 2)})
    movers.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
    return movers[:top_n]

def _trend_over(full_value_series, since):
    """Value now vs value at/after `since` (or the earliest point if None)."""
    points = [p for p in full_value_series if since is None or p["timestamp"] >= since]
    if len(points) < 2:
        return None
    value_then, value_now = points[0]["total_value"], points[-1]["total_value"]
    change_pct = ((value_now - value_then) / value_then * 100) if value_then else None
    return {
        "date_then": points[0]["timestamp"].date().isoformat(),
        "value_then": value_then, "value_now": value_now,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
    }

def compute_trend(full_value_series, lots):
    """Portfolio value trend at a few reference horizons, all from the SAME
    full-history series compute_drawdown uses. IMPORTANT: since_inception is
    anchored to the earliest transaction_lots.csv purchase date, NOT the
    earliest price-history point - see AGENT_NOTES.md ("Trend vs. drawdown")
    before changing this; using full history here produced a confirmed,
    shipped-and-caught bug (+57,000% from a 1996 price)."""
    now = datetime.now()
    all_lot_dates = [l["date"] for ls in lots.values() for l in ls]
    inception = min(all_lot_dates) if all_lot_dates else None
    return {
        "since_inception": _trend_over(full_value_series, inception),
        "last_30d": _trend_over(full_value_series, now - timedelta(days=30)),
        "last_90d": _trend_over(full_value_series, now - timedelta(days=90)),
        "last_365d": _trend_over(full_value_series, now - timedelta(days=365)),
    }

def check_value_divergence(total_value, threshold_pct, message_template, history_file=ANALYSIS_HISTORY_FILE):
    """Compare against the previous run's total_value to catch data bugs (bad
    ticker mappings, corrupted price history, etc.) that silently produce a
    wildly wrong portfolio value instead of an error - see AGENT_NOTES.md
    "Ticker resolution" incident, where a bad mapping roughly doubled the
    reported value with no other symptom. Returns a caveat string, or None if
    there's no prior run or the swing is unremarkable."""
    if not history_file.exists():
        return None
    last_line = None
    with open(history_file) as f:
        for line in f:
            if line.strip():
                last_line = line
    if last_line is None:
        return None
    prev = json.loads(last_line)
    if not prev["total_value"]:
        return None
    change_pct = (total_value - prev["total_value"]) / prev["total_value"] * 100
    if abs(change_pct) < threshold_pct:
        return None
    return message_template.format(
        change_pct=change_pct,
        prev_value=prev["total_value"],
        prev_time=prev["generated_at"],
        curr_value=total_value,
    )

def record_analysis_history(generated_at, total_value, xirr_pct, history_file=ANALYSIS_HISTORY_FILE):
    with open(history_file, "a") as f:
        f.write(json.dumps({"generated_at": generated_at, "total_value": total_value, "xirr_pct": xirr_pct}) + "\n")

def main():
    config = load_config()
    th = config["thresholds"]
    cv = config["caveats"]
    nr = config["notify_reasons"]

    lots = load_transaction_lots()
    open_positions = load_open_positions(lots)
    all_history = {pos["Ticker"]: load_ticker_history(pos["Ticker"], th["split_adjustment_sanity_ratio"])
                   for pos in open_positions}
    prices = latest_prices_from_history(all_history)
    stale = stale_tickers(all_history, th["stale_price_max_age_days"])

    positions = compute_positions(open_positions, prices)
    totals = compute_portfolio_totals(positions)
    sectors = compute_sector_breakdown(positions, totals["total_value"])
    largest = compute_largest_positions(positions, th["largest_positions_top_n"])
    full_value_series = compute_portfolio_value_series(open_positions, all_history)
    drawdown = compute_drawdown(full_value_series, totals["total_value"])
    movers = compute_movers(open_positions, all_history, th["movers_top_n"])
    trend = compute_trend(full_value_series, lots)
    annualized = compute_annualized_returns(open_positions, prices, lots)

    caveats = [
        cv["gain_pct_note"],
        cv["xirr_methodology_note"],
        cv["drawdown_forward_fill_note"],
        cv["trend_methodology_note"],
    ]
    if annualized["tickers_without_lot_data"]:
        caveats.append(cv["tickers_without_lot_data"].format(
            tickers=", ".join(annualized["tickers_without_lot_data"])
        ))
    if stale:
        stale_desc = ", ".join(f"{s['ticker']} (last: {s['last_price_date'] or 'never'})" for s in stale)
        caveats.append(cv["stale_prices"].format(
            max_age_days=th["stale_price_max_age_days"], stale_desc=stale_desc
        ))
    max_holding_days = max(
        (v["weighted_avg_holding_days"] for v in annualized["per_position_xirr_pct"].values()
         if v["weighted_avg_holding_days"] is not None), default=0)
    if max_holding_days < th["full_year_holding_days"]:
        caveats.append(cv["short_holding_period"].format(max_holding_days=max_holding_days))
    divergence = check_value_divergence(
        totals["total_value"], th["value_divergence_pct"], cv["value_divergence"]
    )
    if divergence:
        caveats.append(divergence)

    # Explicit, reproducible notification signal - so "is today notable enough to
    # notify" is a fixed rule evaluated the same way every run, not a fresh judgment
    # call each morning. Keep in sync with tasks/daily-analysis.md's notify step.
    notify_reasons = []
    big_movers = [m for m in movers if abs(m["change_pct"]) >= th["mover_notable_pct"]]
    if big_movers:
        notify_reasons.append(nr["large_movers"].format(
            threshold_pct=th["mover_notable_pct"],
            movers_desc=", ".join(f"{m['ticker']} {m['change_pct']:+.1f}%" for m in big_movers),
        ))
    if stale:
        notify_reasons.append(nr["stale_prices"].format(tickers=", ".join(s["ticker"] for s in stale)))
    if divergence:
        notify_reasons.append(nr["value_divergence"])

    generated_at = datetime.now().isoformat()
    result = {
        "generated_at": generated_at,
        "totals": totals,
        "positions": positions,
        "sectors": sectors,
        "largest_positions": [{"ticker": p["ticker"], "company": p["company"],
                                "value": p["value"], "gain_pct": p["gain_pct"]} for p in largest],
        "drawdown": drawdown,
        "movers": movers,
        "trend": trend,
        "annualized_returns": annualized,
        "stale_prices": stale,
        "caveats": caveats,
        "notable": bool(notify_reasons),
        "notify_reasons": notify_reasons,
    }
    record_analysis_history(generated_at, totals["total_value"], annualized["portfolio_xirr_pct"])
    return result

if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
