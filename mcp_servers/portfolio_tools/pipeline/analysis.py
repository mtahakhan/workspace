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
from ..paths import PRICE_HISTORY_DIR, ENRICHED_LOTS_FILE, ANALYSIS_HISTORY_FILE


def load_transaction_lots():
    """Return {ticker: [{"date", "shares", "price", "fee", "company", "sector"}, ...]}
    Reads enriched_lots.csv — the join of FIFO lots + ticker_map + company_overrides.
    Missing file / missing ticker -> no lots (XIRR falls back gracefully).
    This is also the sole source of current positions - see load_open_positions().

    "price" is the execution price exactly as traded; "fee" is that lot's share of
    the order fee, kept separate so cost basis can be all-in (shares*price + fee)
    without the recorded price drifting from what the security actually traded at.
    A lot file written before the Fee column existed reads as fee 0.0 rather than
    failing, so an older data directory still loads."""
    if not ENRICHED_LOTS_FILE.exists():
        return {}
    lots = {}
    with open(ENRICHED_LOTS_FILE) as f:
        for row in csv.DictReader(f):
            if not row["Ticker"]:
                continue
            lots.setdefault(row["Ticker"], []).append({
                "date": datetime.strptime(row["Purchase Date"], "%Y-%m-%d"),
                "shares": float(row["Shares"]),
                "price": float(row["Purchase Price"]),
                "fee": float(row.get("Fee") or 0.0),
                "company": row["Company"],
                "sector": row["Sector"],
                "ca_from": row.get("CA From ISIN") or None,
                "ca_ratio": float(row["CA Ratio"]) if row.get("CA Ratio") else None,
                "ca_date": row.get("CA Date") or None,
            })
    return lots


def compute_corporate_actions(lots):
    """Corporate actions behind the current open lots, one entry per (ticker, event).

    A reverse consolidation makes a position's own price history discontinuous - the
    share count and per-share price change by the ratio on a single day with no trade
    behind it - so a % return or a price chart spanning the event needs this context to
    read correctly. Derived from lot provenance rather than re-read from
    transactions.csv, so it always describes the lots actually being reported on.
    """
    events = {}
    for ticker, ticker_lots in lots.items():
        for l in ticker_lots:
            if not l["ca_from"] or not l["ca_ratio"]:
                continue
            key = (ticker, l["ca_date"], l["ca_from"])
            e = events.setdefault(key, {
                "ticker": ticker, "company": l["company"], "date": l["ca_date"],
                "from_isin": l["ca_from"], "ratio": round(l["ca_ratio"], 4),
                "kind": "reverse consolidation" if l["ca_ratio"] > 1 else "split",
                "shares_affected": 0.0, "cost_carried_eur": 0.0,
            })
            e["shares_affected"] += l["shares"]
            e["cost_carried_eur"] += l["shares"] * l["price"] + l["fee"]
    for e in events.values():
        e["shares_affected"] = round(e["shares_affected"], 6)
        e["cost_carried_eur"] = round(e["cost_carried_eur"], 2)
    return sorted(events.values(), key=lambda e: (e["date"] or "", e["ticker"]))

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
        # Outflow is what actually left the account: consideration plus the order
        # fee, so the return is measured against real money spent, not the
        # fee-excluding notional.
        cashflows = [(l["date"], -(l["shares"] * l["price"] + l["fee"])) for l in ticker_lots]
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
    EUR, Fees EUR) from transaction_lots.csv - the sole source, no separate file.
    "Bought at EUR" here is the shares-weighted average execution price across
    that ticker's open lots, always in sync with the real transaction history.
    "Fees EUR" is the entry fees still attached to those open lots - carried
    alongside rather than folded into the average price, so cost basis is all-in
    while the price stays the traded price."""
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
            "Fees EUR": round(sum(l["fee"] for l in ticker_lots), 2),
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

def price_return_pct(history, days, now=None):
    """Percent change in a ticker's own price over the trailing `days`.

    Forward-filled at the start of the window (price_at_or_before), so a
    non-trading day or a gap in history doesn't silently drop the window. None
    when there is no price that far back - a position younger than the window
    has no trend over it, which is different from a flat one.
    """
    if not history:
        return None
    now = now or datetime.now()
    then = price_at_or_before(history, now - timedelta(days=days))
    current = history[-1]["price"]
    if not then or not current:
        return None
    return round((current / then - 1) * 100, 2)


def window_high(history, days, now=None):
    """Highest price in the trailing `days`. None if the window holds no points."""
    if not history:
        return None
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    prices = [r["price"] for r in history if r["timestamp"] >= cutoff and r["price"]]
    return max(prices) if prices else None


def compute_position_trends(open_positions, all_history, cfg):
    """Per-position price trend: where each holding has been going *recently*,
    independent of when it was bought.

    This exists because every other per-position return here is anchored to the
    purchase (`gain_pct`, `xirr_pct`) or to a single session (`movers`), and
    neither describes the current trajectory. Cost-basis return is an accident
    of entry timing: on 2026-07-27 ARM showed +25.9% since buy and a +177% XIRR
    while being down 35% over eight weeks and 40% off its own 52-week high. Both
    figures were correct; only one of them said where the position was heading.

    `drawdown_from_high_pct` is per-ticker, against that ticker's own trailing
    high - not the portfolio-level high-water mark in compute_drawdown, which
    answers a different question.
    """
    now = datetime.now()
    short_d, medium_d = cfg["trend_short_days"], cfg["trend_medium_days"]
    high_d = cfg["trend_high_window_days"]
    trends = {}
    for pos in open_positions:
        hist = all_history.get(pos["Ticker"], [])
        high = window_high(hist, high_d, now)
        current = hist[-1]["price"] if hist else None
        trends[pos["Ticker"]] = {
            f"trend_{short_d}d_pct": price_return_pct(hist, short_d, now),
            f"trend_{medium_d}d_pct": price_return_pct(hist, medium_d, now),
            "high_eur": round(high, 2) if high else None,
            "drawdown_from_high_pct": (
                round((current / high - 1) * 100, 2) if high and current else None
            ),
        }
    return trends


def compute_trend_movers(positions, trends, cfg):
    """Positions whose *medium-window* move is large - "something has been
    happening for two months", as distinct from compute_movers' "something
    happened today". Derived from compute_position_trends' output rather than
    recomputed, so the two can never disagree.
    """
    key = f"trend_{cfg['trend_medium_days']}d_pct"
    flagged = [
        {"ticker": p["ticker"], "company": p["company"],
         "change_pct": trends[p["ticker"]][key],
         "drawdown_from_high_pct": trends[p["ticker"]]["drawdown_from_high_pct"]}
        for p in positions
        if trends.get(p["ticker"], {}).get(key) is not None
        and abs(trends[p["ticker"]][key]) >= cfg["trend_notable_pct"]
    ]
    flagged.sort(key=lambda m: abs(m["change_pct"]), reverse=True)
    return flagged[:cfg["trend_movers_top_n"]]


def compute_positions(open_positions, prices, trends=None):
    """Cost basis is all-in: shares * execution price + the entry fees still
    attached to the open lots. `fees_eur` is reported separately as well, so a
    position's fee drag is visible rather than buried inside its cost.

    `trends` (from compute_position_trends) is merged onto each position so a
    reader gets since-buy return and recent trajectory in one place - they
    routinely disagree, and seeing only one of them is how a position in a
    two-month slide reads as a winner."""
    trends = trends or {}
    positions = []
    for pos in open_positions:
        ticker = pos["Ticker"]
        price = prices.get(ticker)
        fees = pos["Fees EUR"]
        cost = pos["Shares"] * pos["Bought at EUR"] + fees
        if price is None:
            positions.append({"ticker": ticker, "company": pos["Company"], "sector": pos["Sector"],
                               "shares": pos["Shares"], "price": None, "value": None,
                               "cost": round(cost, 2), "fees_eur": round(fees, 2),
                               "gain_eur": None, "gain_pct": None, "fee_drag_pct": None,
                               **trends.get(ticker, {})})
            continue
        value = pos["Shares"] * price
        gain_eur = value - cost
        gain_pct = (gain_eur / cost * 100) if cost else None
        positions.append({
            "ticker": ticker, "company": pos["Company"], "sector": pos["Sector"],
            "shares": pos["Shares"], "price": price, "value": round(value, 2),
            "cost": round(cost, 2), "fees_eur": round(fees, 2),
            "gain_eur": round(gain_eur, 2),
            "gain_pct": round(gain_pct, 2) if gain_pct is not None else None,
            # Entry fees as a share of what the position is worth now - the number
            # that says whether a small position can still pay for its own exit.
            "fee_drag_pct": round(fees / value * 100, 2) if value else None,
            **trends.get(ticker, {}),
        })
    return positions

def compute_portfolio_totals(positions):
    total_value = sum(p["value"] for p in positions if p["value"] is not None)
    total_cost = sum(p["cost"] for p in positions)
    total_fees = sum(p["fees_eur"] for p in positions)
    gain_eur = total_value - total_cost
    gain_pct = (gain_eur / total_cost * 100) if total_cost else None
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        # Entry fees inside total_cost above, surfaced separately so the drag is
        # attributable rather than invisible. Fees on already-closed round trips
        # are NOT here - those left with the lots they belonged to; see
        # fees.fee_drag_summary() for whole-history fee statistics.
        "total_fees_eur": round(total_fees, 2),
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

    position_trends = compute_position_trends(open_positions, all_history, th)
    positions = compute_positions(open_positions, prices, position_trends)
    totals = compute_portfolio_totals(positions)
    sectors = compute_sector_breakdown(positions, totals["total_value"])
    largest = compute_largest_positions(positions, th["largest_positions_top_n"])
    full_value_series = compute_portfolio_value_series(open_positions, all_history)
    drawdown = compute_drawdown(full_value_series, totals["total_value"])
    movers = compute_movers(open_positions, all_history, th["movers_top_n"])
    trend_movers = compute_trend_movers(positions, position_trends, th)
    trend = compute_trend(full_value_series, lots)
    annualized = compute_annualized_returns(open_positions, prices, lots)
    corporate_actions = compute_corporate_actions(lots)

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
    # Notify when a position is deeply off its own high, regardless of what happened
    # today. This fires at most once per position per run and is gated by a separate
    # threshold so it can be tuned independently of the day-over-day mover threshold.
    deep_drawdown = [
        m for m in trend_movers
        if m.get("drawdown_from_high_pct") is not None
        and m["drawdown_from_high_pct"] <= -th["drawdown_notable_pct"]
    ]
    if deep_drawdown:
        notify_reasons.append(nr["deep_drawdown"].format(
            threshold_pct=th["drawdown_notable_pct"],
            positions_desc=", ".join(
                f"{m['ticker']} {m['drawdown_from_high_pct']:+.1f}% vs high"
                for m in deep_drawdown
            ),
        ))

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
        "trend_movers": trend_movers,
        "corporate_actions": corporate_actions,
        "stale_prices": stale,
        "caveats": caveats,
        "notable": bool(notify_reasons),
        "notify_reasons": notify_reasons,
    }
    record_analysis_history(generated_at, totals["total_value"], annualized["portfolio_xirr_pct"])
    return result

if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
