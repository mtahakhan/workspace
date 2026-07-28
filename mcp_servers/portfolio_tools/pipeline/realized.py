#!/usr/bin/env python3
"""Per-ticker realized (and optionally unrealized) gain/loss breakdown.

Extends exit_report.py's portfolio-wide FIFO realized-gain pass with a
per-ticker breakdown, and folds in each ticker's current unrealized gain/loss
(from analyze_portfolio's open positions) - unless the caller asks to
exclude it.

Why this exists
----------------
exit_report.py answers "what's my total realized gain, portfolio-wide" but
discards the per-ticker breakdown once it sums to one number. analyze_portfolio
(analysis.py) answers "what's each open position's unrealized gain" but only
for tickers still held - a ticker that was fully bought and fully sold before
the current holding period (and never re-bought) doesn't appear anywhere in
analysis output, because it isn't an open position. This module is the one
place both are available together, per ticker, so a question like "did I
ever realize a profit on X" (as opposed to "is X currently up") can be
answered directly instead of inferred from an aggregate that mixes closed
and open activity together.

Real example this was built for: a user asked whether they'd realized any
profit on INTC. `fee_drag_by_ticker` (compliance.py) showed 14 lifetime
orders for INTC but only 7 open lots existed - meaning an earlier round of
INTC had been fully closed before the current position was built, and no
existing tool could isolate that closed round's gain/loss from the
portfolio-wide realized total.

Method
------
Reuses the same FIFO walk as exit_report.py's _realized_gain (buy/sell
pairing, corporate-action carry-forward, partial-lot fee proration) - kept as
an independent copy for the same reason exit_report.py gives for its own
copy: this must stay unaffected by changes elsewhere in the pipeline, and
lots.py's build_lots() discards realized info on pop so it can't be reused
directly. The one difference from exit_report.py: results are keyed per ISIN
during the walk, then merged into per-ticker rows afterward (a ticker can
span more than one ISIN across a corporate-action rename - e.g. 3BRS.MI's
2026-04-20 reverse consolidation - so any sells before and after such a swap
must be combined into one row, not reported as two).

ISIN -> Ticker/Company comes from ticker_map.csv (the same source
enrich_lots.py uses), so a ticker that has since fully closed out (no open
lots, so absent from enriched_lots.csv / analyze_portfolio) still resolves to
a real ticker rather than a bare ISIN.

Unrealized side (optional): joined in from the `analysis` dict's `positions`
list (already computed by analyze_portfolio - never recomputed here), keyed
by ticker. A ticker with only closed history (no current position) simply
gets no unrealized entry.

include_unrealized=False strips the "unrealized" key and the
unrealized/combined totals from the payload entirely (not zeroed) - a caller
asking for "just the realized picture" gets a payload that can't be misread
as including unrealized swings, rather than one where they happen to be 0.0.
"""

import csv
from collections import defaultdict
from datetime import datetime

from ..paths import TRANSACTIONS_FILE, TICKER_MAP_FILE


# ---------------------------------------------------------------------------
# Helpers (private) - see exit_report.py for the same helpers' rationale
# ---------------------------------------------------------------------------

def _parse_number(s: str) -> float:
    """German decimal format: '1.074,00' -> 1074.00. Blank -> 0.0."""
    s = (s or "").strip()
    if not s:
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def _load_executed_rows() -> list[dict]:
    rows = []
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("status") != "Executed":
                continue
            rows.append(r)
    rows.sort(key=lambda r: datetime.strptime(
        f'{r["date"]} {r["time"]}', "%Y-%m-%d %H:%M:%S"
    ))
    return rows


def _load_ticker_metadata() -> dict:
    """ISIN -> {ticker, company} from ticker_map.csv. Missing file -> {}."""
    if not TICKER_MAP_FILE.exists():
        return {}
    with open(TICKER_MAP_FILE) as f:
        return {
            row["ISIN"]: {
                "ticker": row.get("Ticker", "") or row["ISIN"],
                "company": row.get("Company", "") or row["ISIN"],
            }
            for row in csv.DictReader(f)
        }


# ---------------------------------------------------------------------------
# Realized gain pass, keyed per ISIN (same FIFO rules as exit_report.py)
# ---------------------------------------------------------------------------

def _realized_by_isin(rows: list[dict]) -> dict:
    """Walk the Security rows in chronological order using FIFO to pair sells
    against their corresponding buys, per ISIN. Returns closed-side totals
    only - open lots are not touched. See exit_report.py's _realized_gain for
    the full rationale on why this re-implements a subset of lots.py rather
    than importing it.
    """
    open_lots: dict = defaultdict(list)
    realized: dict = defaultdict(lambda: {
        "proceeds_eur": 0.0, "cost_eur": 0.0,
        "entry_fees_eur": 0.0, "exit_fees_eur": 0.0,
        "closed_lots": 0, "sell_orders": 0,
    })

    for r in rows:
        if r.get("assetType") != "Security":
            continue
        typ = r.get("type", "")

        if typ == "Security transfer":
            continue

        if typ == "Corporate action":
            # Same minimal carry-forward as exit_report.py: preserve cost
            # basis across an ISIN swap without needing the reference-stem
            # pairing lots.py uses (sufficient here since we only need
            # aggregate cost, not per-lot dates).
            shares = _parse_number(r.get("shares", "0"))
            isin = r.get("isin", "")
            if shares < 0:
                open_lots[f"__swap_out_{isin}"] = open_lots.pop(isin, [])
            else:
                old_isin = None
                for key in list(open_lots):
                    if key.startswith("__swap_out_"):
                        old_isin = key[len("__swap_out_"):]
                        break
                if old_isin is not None:
                    old_lots = open_lots.pop(f"__swap_out_{old_isin}", [])
                    total_old = sum(l["shares"] for l in old_lots)
                    if total_old > 0 and shares > 0:
                        for l in old_lots:
                            l["shares"] = l["shares"] / total_old * shares
                        open_lots[isin].extend(old_lots)
            continue

        shares = _parse_number(r.get("shares", "0"))
        price = _parse_number(r.get("price", "0"))
        fee = _parse_number(r.get("fee", "0"))
        isin = r.get("isin", "")

        if typ in ("Buy", "Reinvestment_Distribution", "Savings plan"):
            open_lots[isin].append({"shares": shares, "price": price, "fee": fee})

        elif typ == "Sell":
            proceeds = abs(_parse_number(r.get("amount", "0")))
            realized[isin]["proceeds_eur"] += proceeds
            realized[isin]["exit_fees_eur"] += fee
            realized[isin]["sell_orders"] += 1

            remaining = shares
            while remaining > 1e-9 and open_lots[isin]:
                oldest = open_lots[isin][0]
                if oldest["shares"] <= remaining + 1e-9:
                    realized[isin]["cost_eur"] += oldest["shares"] * oldest["price"] + oldest["fee"]
                    realized[isin]["entry_fees_eur"] += oldest["fee"]
                    realized[isin]["closed_lots"] += 1
                    remaining -= oldest["shares"]
                    open_lots[isin].pop(0)
                else:
                    fraction = remaining / oldest["shares"]
                    partial_fee = oldest["fee"] * fraction
                    realized[isin]["cost_eur"] += remaining * oldest["price"] + partial_fee
                    realized[isin]["entry_fees_eur"] += partial_fee
                    oldest["fee"] *= (1 - fraction)
                    oldest["shares"] -= remaining
                    remaining = 0

    return realized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(analysis: dict, include_unrealized: bool = True) -> dict:
    """Per-ticker realized (and, unless include_unrealized=False, unrealized)
    gain/loss.

    Args:
        analysis: the dict returned by pipeline.analysis.main() - used only
                  for each open position's current market value/cost/gain,
                  never recomputed here. Ignored (may be {}) when
                  include_unrealized=False.
        include_unrealized: when False, every row's "unrealized" key and the
                  portfolio-wide unrealized/combined totals are omitted
                  entirely (not zeroed) - see module docstring.

    Returns a dict with one entry per ticker that has EITHER a closed
    round-trip OR a current open position - a ticker fully bought and fully
    sold, with nothing open today, still gets a row.
    """
    if not TRANSACTIONS_FILE.exists():
        return {"error": "no transaction history uploaded yet"}

    rows = _load_executed_rows()
    realized_by_isin = _realized_by_isin(rows)
    metadata = _load_ticker_metadata()

    def ticker_of(isin):
        meta = metadata.get(isin)
        return meta["ticker"] if meta else isin

    def company_of(isin):
        meta = metadata.get(isin)
        return meta["company"] if meta else isin

    # --- realized, merged by ticker (a ticker can span >1 ISIN across a
    # corporate-action rename) ---
    realized_by_ticker: dict = {}
    for isin, r in realized_by_isin.items():
        if r["sell_orders"] == 0:
            continue
        ticker = ticker_of(isin)
        agg = realized_by_ticker.setdefault(ticker, {
            "company": company_of(isin), "isins": [],
            "proceeds_eur": 0.0, "cost_eur": 0.0,
            "entry_fees_eur": 0.0, "exit_fees_eur": 0.0,
            "closed_lots": 0, "sell_orders": 0,
        })
        agg["isins"].append(isin)
        agg["proceeds_eur"] += r["proceeds_eur"]
        agg["cost_eur"] += r["cost_eur"]
        agg["entry_fees_eur"] += r["entry_fees_eur"]
        agg["exit_fees_eur"] += r["exit_fees_eur"]
        agg["closed_lots"] += r["closed_lots"]
        agg["sell_orders"] += r["sell_orders"]

    # --- unrealized, from analyze_portfolio's already-open positions ---
    unrealized_by_ticker = {}
    open_position_company = {}
    if include_unrealized:
        for p in analysis.get("positions", []):
            unrealized_by_ticker[p["ticker"]] = {
                "market_value_eur": round(p.get("value", 0.0), 2),
                "cost_basis_eur": round(p.get("cost", 0.0), 2),
                "gain_eur": round(p.get("gain_eur", 0.0), 2),
                "gain_pct": p.get("gain_pct"),
            }
            open_position_company[p["ticker"]] = p.get("company", "")

    all_tickers = set(realized_by_ticker) | set(unrealized_by_ticker)

    by_ticker = []
    for ticker in sorted(all_tickers):
        r = realized_by_ticker.get(ticker)
        u = unrealized_by_ticker.get(ticker)

        realized_block = None
        if r:
            gain_eur = round(r["proceeds_eur"] - r["cost_eur"], 2)
            # gain_eur is already net of entry fees (they're baked into cost_eur
            # via each lot's "fee" field - see _realized_by_isin) but NOT of exit
            # fees: the broker's Sell "amount" column is gross shares*price, with
            # the order fee charged as a separate deduction (verified directly
            # against transactions.csv - amount never has the fee subtracted).
            # gain_after_fees_eur is the true net cash impact of the round trip;
            # gain_eur is kept as-is (pre-exit-fee) to match exit_report.py's own
            # convention of reporting the gain and the fees as separate lines
            # rather than one pre-merged figure.
            total_fees_eur = round(r["entry_fees_eur"] + r["exit_fees_eur"], 2)
            realized_block = {
                "isins": sorted(set(r["isins"])),
                "proceeds_eur": round(r["proceeds_eur"], 2),
                "cost_eur": round(r["cost_eur"], 2),
                "gain_eur": gain_eur,
                "entry_fees_eur": round(r["entry_fees_eur"], 2),
                "exit_fees_eur": round(r["exit_fees_eur"], 2),
                "total_fees_eur": total_fees_eur,
                "gain_after_fees_eur": round(gain_eur - r["exit_fees_eur"], 2),
                "closed_lots": r["closed_lots"],
                "sell_orders": r["sell_orders"],
            }

        entry = {
            "ticker": ticker,
            "company": (r["company"] if r else "") or open_position_company.get(ticker, ticker),
            "has_realized_activity": realized_block is not None,
            "currently_held": u is not None,
            "realized": realized_block,
        }
        if include_unrealized:
            entry["unrealized"] = u
            entry["total_gain_eur"] = round(
                (realized_block["gain_eur"] if realized_block else 0.0) +
                (u["gain_eur"] if u else 0.0),
                2,
            )
            # Unrealized positions haven't paid an exit fee yet (nothing's been
            # sold), so it's already "after fees" as far as fees paid to date go -
            # only the realized side needs the exit-fee adjustment.
            entry["total_gain_after_fees_eur"] = round(
                (realized_block["gain_after_fees_eur"] if realized_block else 0.0) +
                (u["gain_eur"] if u else 0.0),
                2,
            )
        by_ticker.append(entry)

    totals = {
        "realized_gain_eur": round(
            sum(e["realized"]["gain_eur"] for e in by_ticker if e["realized"]), 2
        ),
        "realized_gain_after_fees_eur": round(
            sum(e["realized"]["gain_after_fees_eur"] for e in by_ticker if e["realized"]), 2
        ),
        "total_fees_eur": round(
            sum(e["realized"]["total_fees_eur"] for e in by_ticker if e["realized"]), 2
        ),
        "tickers_with_realized_activity": sum(1 for e in by_ticker if e["realized"]),
    }
    if include_unrealized:
        totals["unrealized_gain_eur"] = round(
            sum(e["unrealized"]["gain_eur"] for e in by_ticker if e.get("unrealized")), 2
        )
        totals["combined_gain_eur"] = round(
            totals["realized_gain_eur"] + totals["unrealized_gain_eur"], 2
        )
        totals["combined_gain_after_fees_eur"] = round(
            totals["realized_gain_after_fees_eur"] + totals["unrealized_gain_eur"], 2
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "include_unrealized": include_unrealized,
        "by_ticker": by_ticker,
        "totals": totals,
    }


def render(report: dict, ticker: str | None = None) -> str:
    """Render a generate() result as a markdown table. Pass `ticker` to
    render just that one row's detail instead of the full table."""
    if "error" in report:
        return f"## Realized Gain by Ticker\n\nError: {report['error']}"

    def money(x):
        if x is None:
            return "n/a"
        return f"-€{-x:,.2f}" if x < 0 else f"€{x:,.2f}"

    rows = report["by_ticker"]
    if ticker:
        wanted = ticker.strip().upper()
        rows = [r for r in rows if r["ticker"] == wanted]
        if not rows:
            known = sorted({r["ticker"] for r in report["by_ticker"]})
            return f"No activity found for '{ticker}'. Known tickers: {', '.join(known)}"

    include_unrealized = report["include_unrealized"]
    lines = [
        "## Realized Gain by Ticker" + (" (excludes unrealized)" if not include_unrealized else ""),
        "",
        f"*Generated: {report['generated_at']}*",
        "",
    ]

    # "Realized Gain" = proceeds - cost, entry fees already included (baked into
    # cost per lot) but NOT exit fees (broker's Sell amount is gross - see
    # generate()'s comment). "Fees" here is the exit-side fee only, since entry
    # fees are already inside "Realized Gain" - showing both would double-count.
    # "Net After Fees" = Realized Gain - Fees = the true cash result.
    header = "| Ticker | Company | Realized Gain | Exit Fees | Net After Fees | Closed Lots |"
    sep = "|---|---|---:|---:|---:|---:|"
    if include_unrealized:
        header = ("| Ticker | Company | Realized Gain | Exit Fees | Realized Net | "
                   "Unrealized Gain | Total (Net) | Held Now |")
        sep = "|---|---|---:|---:|---:|---:|---:|:---:|"
    lines += [header, sep]

    for e in rows:
        r = e["realized"]
        realized_gain = money(r["gain_eur"]) if r else "—"
        exit_fees = money(r["exit_fees_eur"]) if r else "—"
        realized_net = money(r["gain_after_fees_eur"]) if r else "—"
        if include_unrealized:
            unrealized_gain = money(e["unrealized"]["gain_eur"]) if e.get("unrealized") else "—"
            held = "yes" if e["currently_held"] else "no"
            lines.append(
                f"| {e['ticker']} | {e['company']} | {realized_gain} | {exit_fees} | {realized_net} "
                f"| {unrealized_gain} | {money(e['total_gain_after_fees_eur'])} | {held} |"
            )
        else:
            closed_lots = r["closed_lots"] if r else 0
            lines.append(
                f"| {e['ticker']} | {e['company']} | {realized_gain} | {exit_fees} "
                f"| {realized_net} | {closed_lots} |"
            )

    # Totals: recomputed from `rows` (not report["totals"]) so a single-ticker
    # filter shows that ticker's own totals instead of the whole portfolio's -
    # report["totals"] is always portfolio-wide regardless of the `ticker` filter.
    scope = "shown ticker" if ticker else "all tickers shown"
    realized_sum = round(sum(e["realized"]["gain_eur"] for e in rows if e["realized"]), 2)
    exit_fees_sum = round(sum(e["realized"]["exit_fees_eur"] for e in rows if e["realized"]), 2)
    entry_fees_sum = round(sum(e["realized"]["entry_fees_eur"] for e in rows if e["realized"]), 2)
    realized_net_sum = round(realized_sum - exit_fees_sum, 2)
    with_activity = sum(1 for e in rows if e["realized"])
    lines += ["", "### Totals", "", "| Item | Amount |", "|---|---:|"]
    lines.append(f"| Realized gain, {scope} (before exit fees) | {money(realized_sum)} |")
    lines.append(f"| - of which entry fees (already included above) | {money(entry_fees_sum)} |")
    lines.append(f"| Exit fees on these closed round-trips | {money(exit_fees_sum)} |")
    lines.append(f"| **Realized gain, {scope}, net of all fees** | **{money(realized_net_sum)}** |")
    lines.append(f"| Tickers with any realized (closed) activity | {with_activity} |")
    if include_unrealized:
        unrealized_sum = round(sum(e["unrealized"]["gain_eur"] for e in rows if e.get("unrealized")), 2)
        combined_net_sum = round(realized_net_sum + unrealized_sum, 2)
        lines.append(f"| Unrealized gain, {scope} (no exit fee paid yet) | {money(unrealized_sum)} |")
        lines.append(f"| **Combined (realized + unrealized), {scope}, net of fees** | **{money(combined_net_sum)}** |")

    return "\n".join(lines)


def main(analysis: dict | None = None, include_unrealized: bool = True, ticker: str | None = None):
    """Entry point for direct module invocation (debugging)."""
    if analysis is None:
        if include_unrealized:
            from .analysis import main as analyze_portfolio
            analysis = analyze_portfolio()
        else:
            analysis = {}
    report = generate(analysis, include_unrealized=include_unrealized)
    print(render(report, ticker=ticker))
    return report


if __name__ == "__main__":
    main()
