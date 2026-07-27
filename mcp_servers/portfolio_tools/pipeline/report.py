#!/usr/bin/env python3
"""
Renders analyze_portfolio's JSON into the deterministic markdown sections
of the daily report (tables and figures only - no judgment calls). Reads
JSON from stdin or a file path argument, prints markdown to stdout.

This exists so the LLM-driven daily-analysis task never hand-transcribes
numbers out of the JSON into prose/tables - every figure in these sections is
mechanically derived, matching the "all numbers are untouched script output"
rule in AGENT_NOTES.md. The task still writes its own Executive Summary and
the Movers "Context" research (using the Movers table's Ticker column as the
targeted-WebSearch list), and appends them around this output.

Primary interface is the render_report MCP tool, which calls render(data,
config) directly (it already has the dict, not stdin JSON) - main() below is
only for direct debugging: `.venv/bin/python3 -m portfolio_tools.pipeline.analysis |
.venv/bin/python3 -m portfolio_tools.pipeline.report` (from inside
mcp_servers/portfolio_tools/, using this package's own venv - never a system
interpreter).
"""

import json
import sys

from .config import load_config

def money(x):
    return f"-€{-x:,.2f}" if x < 0 else f"€{x:,.2f}"

def pct(x, plus=True):
    return f"{x:+.1f}%" if plus else f"{x:.1f}%"

def render_overview(data):
    t = data["totals"]
    d = data["drawdown"]
    xirr = data["annualized_returns"]["portfolio_xirr_pct"]
    lines = [
        "## Portfolio Overview",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Total Cost Basis** (incl. fees) | {money(t['total_cost'])} |",
        f"| **- of which entry fees** | {money(t.get('total_fees_eur', 0.0))} |",
        f"| **Current Market Value** | {money(t['total_value'])} |",
        f"| **Unrealized Gain/Loss** | **{money(t['gain_eur'])}** |",
        f"| **Total Return (non-annualized)** | {pct(t['gain_pct'])} |",
        f"| **Annualized Return (XIRR)** | **{pct(xirr) if xirr is not None else 'n/a'}** (target: 10-15%/yr) |",
        f"| **Holdings** | {t['positions_total']} positions ({t['positions_priced']} priced) |",
        f"| **High-Water Mark** | {money(d['high_water_mark'])} ({d['high_water_mark_date']}) |",
        f"| **Current Drawdown** | {pct(d['drawdown_pct'])} |",
        "",
        "**Trend:**",
        "",
        "| Period | Value Then | Change |",
        "|--------|-----------|--------|",
    ]
    labels = {
        "since_inception": "Since inception",
        "last_30d": "Last 30 days",
        "last_90d": "Last 90 days",
        "last_365d": "Last 365 days",
    }
    for key, label in labels.items():
        tr = data["trend"][key]
        date_suffix = f" ({tr['date_then']})" if key == "since_inception" else ""
        lines.append(f"| {label}{date_suffix} | {money(tr['value_then'])} | {pct(tr['change_pct'])} |")
    return "\n".join(lines)

def render_sectors(data):
    lines = [
        "## Sector Breakdown",
        "",
        "| Sector | Holdings | % Portfolio | Market Value | Cost Basis | Return |",
        "|--------|----------|------------|--------------|-----------|--------|",
    ]
    for s in sorted(data["sectors"], key=lambda s: -s["value"]):
        lines.append(
            f"| **{s['sector']}** | {s['positions']} | {pct(s['pct_of_portfolio'], plus=False)} | "
            f"{money(s['value'])} | {money(s['cost'])} | {pct(s['gain_pct'])} |"
        )
    return "\n".join(lines)

def render_largest_positions(data):
    lines = [
        "## Largest Positions (Market Value)",
        "",
        "| Ticker | Company | Value | Return |",
        "|--------|---------|-------|--------|",
    ]
    for p in data["largest_positions"]:
        lines.append(f"| **{p['ticker']}** | {p['company']} | {money(p['value'])} | {pct(p['gain_pct'])} |")
    return "\n".join(lines)

def render_movers(data):
    lines = [
        "## Movers Analysis",
        "",
        "Top movers by absolute daily price change. `Context` needs targeted WebSearch on "
        "these tickers only - fill it in, do not research the rest of the portfolio.",
        "",
        "| Ticker | Company | Prev | Curr | Daily Change | Context |",
        "|--------|---------|------|------|--------------|---------|",
    ]
    for m in data["movers"]:
        lines.append(
            f"| **{m['ticker']}** | {m['company']} | {money(m['prev_price'])} | {money(m['curr_price'])} | "
            f"**{pct(m['change_pct'])}** | _fill in_ |"
        )
    return "\n".join(lines)

def render_holdings_table(data):
    lines = [
        "## Complete Holdings Table",
        "",
        "| Ticker | Company | Sector | Shares | Price € | Value € | Cost € | Fees € | Gain € | Return |",
        "|--------|---------|--------|--------|---------|---------|--------|--------|--------|--------|",
    ]
    for p in sorted(data["positions"], key=lambda p: -p["value"]):
        lines.append(
            f"| {p['ticker']} | {p['company']} | {p['sector']} | {p['shares']:g} | {p['price']:,.2f} | "
            f"{p['value']:,.2f} | {p['cost']:,.2f} | {p.get('fees_eur', 0.0):,.2f} | "
            f"{p['gain_eur']:+,.2f} | {pct(p['gain_pct'])} |"
        )
    t = data["totals"]
    lines.append(
        f"| **TOTALS** | | | | | **{t['total_value']:,.2f}** | **{t['total_cost']:,.2f}** | "
        f"**{t.get('total_fees_eur', 0.0):,.2f}** | "
        f"**{t['gain_eur']:+,.2f}** | **{pct(t['gain_pct'])}** |"
    )
    return "\n".join(lines)


def render_corporate_actions(data):
    """Consolidations/splits behind the current open lots.

    Rendered because a reverse consolidation breaks a position's price history at a
    single date with no trade behind it: share count and per-share price both change
    by the ratio. Without this, that position's chart and its % return look like a
    market move. Nothing to show renders nothing.
    """
    events = data.get("corporate_actions") or []
    if not events:
        return ""
    lines = [
        "## Corporate Actions",
        "",
        "Events behind the current open lots. Cost basis and the original acquisition "
        "date carry across - a consolidation is not a disposal, so the holding period "
        "does not restart.",
        "",
        "| Date | Ticker | Event | From ISIN | Shares Now | Cost Carried € |",
        "|------|--------|-------|-----------|------------|----------------|",
    ]
    for e in events:
        ratio = e["ratio"]
        desc = (f"{ratio:g}:1 {e['kind']}" if ratio >= 1 else f"1:{1/ratio:g} {e['kind']}")
        lines.append(
            f"| {e['date']} | **{e['ticker']}** | {desc} | {e['from_isin']} | "
            f"{e['shares_affected']:g} | {e['cost_carried_eur']:,.2f} |"
        )
    return "\n".join(lines)


def render_fee_drag(data, min_drag_pct):
    """Positions whose entry fees are a material share of what they're now worth.

    Deliberately a threshold list rather than a column on every row: fee drag is
    only decision-relevant when it's large, and at that point it bears directly
    on whether a position can pay for its own exit. Empty section renders as
    nothing at all rather than an empty table.
    """
    flagged = [p for p in data["positions"]
               if p.get("fee_drag_pct") is not None and p["fee_drag_pct"] >= min_drag_pct]
    if not flagged:
        return ""
    lines = [
        "## Fee Drag",
        "",
        f"Positions where entry fees are >= {min_drag_pct}% of current value. Exiting costs "
        f"a further EUR 0.99 per order without PRIME.",
        "",
        "| Ticker | Company | Value € | Entry Fees € | Fee Drag |",
        "|--------|---------|---------|--------------|----------|",
    ]
    for p in sorted(flagged, key=lambda p: -p["fee_drag_pct"]):
        lines.append(
            f"| {p['ticker']} | {p['company']} | {p['value']:,.2f} | {p['fees_eur']:,.2f} | "
            f"{p['fee_drag_pct']:.2f}% |"
        )
    return "\n".join(lines)

def render_xirr_context(data, short_hold_days_threshold):
    per_position = data["annualized_returns"]["per_position_xirr_pct"]
    lines = [
        "## XIRR Context",
        "",
        f"Portfolio XIRR: **{pct(data['annualized_returns']['portfolio_xirr_pct'])}** "
        "(target: 10-15%/yr). Per-position XIRRs below sorted by holding period - short "
        f"holds (<{short_hold_days_threshold} days) produce mathematically extreme annualized "
        "numbers even for ordinary moves; treat those as extrapolation noise, not signal.",
        "",
        "| Ticker | XIRR | Holding Days | |",
        "|--------|------|--------------|--|",
    ]
    ordered = sorted(
        per_position.items(),
        key=lambda kv: kv[1]["weighted_avg_holding_days"] or 0,
        reverse=True,
    )
    for ticker, v in ordered:
        days = v["weighted_avg_holding_days"]
        flag = f"short hold (<{short_hold_days_threshold}d) - extrapolation, not a measured trend" \
            if days is not None and days < short_hold_days_threshold else ""
        xirr_str = pct(v["xirr_pct"]) if v["xirr_pct"] is not None else "n/a"
        lines.append(f"| {ticker} | {xirr_str} | {days if days is not None else 'n/a'} | {flag} |")
    if data["annualized_returns"]["tickers_without_lot_data"]:
        lines.append("")
        lines.append(
            "No lot data (excluded from XIRR): "
            + ", ".join(data["annualized_returns"]["tickers_without_lot_data"])
        )
    return "\n".join(lines)

def render_caveats(data):
    if not data["caveats"] and not data["stale_prices"]:
        return ""
    lines = ["## Data Notes", ""]
    if data["stale_prices"]:
        stale_desc = ", ".join(
            f"{s['ticker']} (last: {s['last_price_date'] or 'never'})" for s in data["stale_prices"]
        )
        lines.append(f"**Stale prices:** {stale_desc}")
        lines.append("")
    for c in data["caveats"]:
        lines.append(f"- {c}")
    return "\n".join(lines)

def render(data, config):
    sections = [
        render_overview(data),
        render_sectors(data),
        render_largest_positions(data),
        render_movers(data),
        render_holdings_table(data),
        render_corporate_actions(data),
        render_fee_drag(data, config["thresholds"]["fee_drag_notable_pct"]),
        render_xirr_context(data, config["thresholds"]["short_hold_days_threshold"]),
        render_caveats(data),
    ]
    return "\n\n---\n\n".join(s for s in sections if s)

def main():
    raw = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    data = json.load(raw)
    return render(data, load_config())

if __name__ == "__main__":
    print(main())
