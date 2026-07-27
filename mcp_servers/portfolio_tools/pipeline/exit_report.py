#!/usr/bin/env python3
"""Exit P&L report: "if I sell everything today and walk away, how much did I make?"

This module answers one question the daily pipeline deliberately does not: the
**net money-weighted result of the whole Scalable Capital account** — deposits
in, withdrawals out, realized gains/losses on every closed round-trip, taxes
withheld, broker fees, and the unrealized P&L on what is still open — assembled
into a single exit figure.

The daily pipeline (analysis.py, report.py) tracks only *open* positions
because that is what the daily report needs.  When a Sell removes a lot from
the FIFO stack the realized gain/loss disappears with it.  This module reads
`transactions.csv` independently and reconstructs the complete picture, on top
of whatever `analyze_portfolio` already computed for the open side.

## Method

Capital flows (what actually left/entered the bank account):
  - `total_deposited`  — sum of all Deposit rows (positive amounts the broker
                         applied to the cash balance; PRIME subscription
                         credit rows are excluded because they are fee credits,
                         not real cash arriving from a bank).
  - `total_withdrawn`  — sum of all Withdrawal rows (positive, representing
                         money that left the broker back to the user's bank).
  - `net_capital_in`   — total_deposited − total_withdrawn

Realized activity (closed round-trips — positions completely or partially sold):
  - `realized_proceeds_eur`  — gross proceeds from all Sell rows.
  - `realized_cost_eur`      — FIFO cost basis of the sold shares (shares *
                               execution price + pro-rated entry fee at the
                               time of the buy).
  - `realized_gain_eur`      — proceeds − cost (before tax).
  - `realized_fees_eur`      — exit-side fees on sell orders (the fee column
                               on Sell rows; entry fees on closed lots are
                               already inside realized_cost_eur).

Taxes:
  - `total_tax_eur`          — sum of the `tax` column across every executed
                               row (the broker withholds at source on realised
                               gains; this is always a non-negative number).

Open positions (sourced from analyze_portfolio, passed in):
  - `open_value_eur`         — current market value of open positions.
  - `open_cost_eur`          — FIFO cost basis of open positions (fee-inclusive).
  - `open_unrealized_gain_eur`

Hypothetical exit:
  - `hypothetical_exit_value_eur`  — open_value + current cash balance (from
                                     cash.py) — what you'd have in your account
                                     in EUR after selling everything at latest
                                     prices, before any further taxes on the
                                     open-position gains.
  - `net_pnl_eur`                  — hypothetical_exit_value − net_capital_in
                                     — net EUR gained or lost versus what was
                                     put in, after all fees and taxes already
                                     paid.  Does NOT include tax you would still
                                     owe on the open unrealized gains (that
                                     depends on your jurisdiction / holding
                                     period and is outside the scope of this
                                     deterministic module).

## What is NOT included / caveats

- Tax that would still be triggered by selling the remaining open positions is
  NOT deducted (it is jurisdiction-specific and cannot be computed without
  knowing the applicable rate, cost basis per tax lot, and any offsetting
  losses already declared).
- Dividend / interest / distribution cash rows flow through correctly as
  part of the cash balance (they increase available cash), but they are NOT
  broken out as a separate line in this report because the broker folds them
  into the Cash asset-type rows — they are simply part of what remained in
  the account.
- PRIME subscription credits (Deposit rows whose description contains
  "PRIME bis") represent a fee credit / cashback, not real deposited capital,
  so they are excluded from `total_deposited` and tracked separately as
  `prime_credits_eur`.

## Run order

This module is self-contained: it reads `transactions.csv` directly (for the
realized/tax/capital-flow pass), and accepts the open-position data from a
caller (pass `analysis` — the dict `analyze_portfolio` returns) so it does NOT
re-run the full analysis just to get open values.  A typical call:

    analysis = analyze_portfolio()          # via MCP tool
    report   = generate_exit_report(analysis)   # via MCP tool

Running this module directly (debugging):

    cd mcp_servers
    portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.analysis \
      | portfolio_tools/.venv/bin/python3 -m portfolio_tools.pipeline.exit_report

(Reads analysis JSON from stdin when run directly; takes a dict when called
from the server.)
"""

import csv
import json
import sys
from datetime import datetime

from ..paths import TRANSACTIONS_FILE


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _parse_number(s: str) -> float:
    """German decimal format: '1.074,00' -> 1074.00. Blank -> 0.0."""
    s = (s or "").strip()
    if not s:
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def _is_prime_credit(row: dict) -> bool:
    """True for Deposit rows that represent a PRIME subscription credit/cashback.

    These are broker-issued credits (not real money arriving from a bank) and
    should not inflate `total_deposited`.  Identified by 'PRIME bis' in the
    description — the same pattern fees.prime_status_from_transactions() uses.
    """
    return "PRIME bis" in (row.get("description") or "")


# ---------------------------------------------------------------------------
# Capital flow pass  (all Cash + Security rows, signed amounts)
# ---------------------------------------------------------------------------

def _capital_flows(rows: list[dict]) -> dict:
    """Deposits, withdrawals, income, cash-row fees, and taxes from the full ledger.

    Scalable Capital uses two distinct type names for real cash movements:
      - type="Deposit" / type="Withdrawal"  — standard bank wire deposits/withdrawals
      - type="Cash Transfer In" / "Cash Transfer Out" — Scalable's internal transfer
        mechanism (e.g. Flex Account ↔ Broker sub-account, or a broker migration).
        These are signed by the broker: Cash Transfer In is positive (money arrives),
        Cash Transfer Out is negative (money leaves).  Their net is NOT always zero —
        a €3,049.15 net-positive remainder has been confirmed in this portfolio, so
        they must be counted.

    Income types (not capital — the broker generated them, you didn't wire them in):
      - type="Distribution" — ETF dividend / distribution cash payouts
      - type="Interest"     — cash interest (e.g. Flex account)
    These are surfaced as a separate income breakdown; their amounts flow through
    cash.py's balance correctly already but were previously unattributed.

    Cash-row fees (type="Fee") are broker charges applied directly to the cash
    account (e.g. PRIME+ subscription fee), distinct from the per-order fee
    column on Security rows.  Also surfaced separately.

    Security rows (Buys/Sells) are portfolio mechanics, not capital flows — they
    are internal movements between the cash and securities sub-accounts.
    """
    total_deposited = 0.0
    total_withdrawn = 0.0
    prime_credits = 0.0
    total_tax = 0.0
    tax_refunds_eur = 0.0  # Cash/Taxes rows with positive amount = broker refund of over-withheld tax
    distributions_eur = 0.0
    interest_eur = 0.0
    cash_fees_eur = 0.0  # type="Fee" rows on the Cash assetType
    income_detail: list[dict] = []  # one entry per Distribution / Interest row

    for r in rows:
        typ = r.get("type", "")
        amount = _parse_number(r.get("amount", "0"))
        tax = _parse_number(r.get("tax", "0"))
        total_tax += tax

        # Security rows (Buys/Sells) are portfolio mechanics, not capital flows
        if r.get("assetType") == "Security":
            continue

        if typ == "Deposit":
            if _is_prime_credit(r):
                prime_credits += amount
            else:
                total_deposited += amount
        elif typ == "Withdrawal":
            # Standard withdrawals: broker records as negative amount
            total_withdrawn += abs(amount)
        elif typ == "Cash Transfer In":
            # Scalable internal transfer arriving — real money, treat as deposited
            total_deposited += amount
        elif typ == "Cash Transfer Out":
            # Scalable internal transfer leaving — real money, treat as withdrawn
            total_withdrawn += abs(amount)
        elif typ == "Distribution":
            distributions_eur += amount
            income_detail.append({
                "date": r.get("date", ""),
                "type": "Distribution",
                "gross_eur": round(amount, 2),
                "tax_eur": round(tax, 2),
                "net_eur": round(amount - tax, 2),
                "description": (r.get("description") or "").strip('"')[:50],
            })
        elif typ == "Interest":
            interest_eur += amount
            income_detail.append({
                "date": r.get("date", ""),
                "type": "Interest",
                "gross_eur": round(amount, 2),
                "tax_eur": round(tax, 2),
                "net_eur": round(amount - tax, 2),
                "description": (r.get("description") or "").strip('"')[:50],
            })
        elif typ == "Fee":
            # Cash-row broker fee (e.g. PRIME+ subscription charge) — negative amount
            cash_fees_eur += abs(amount)
        elif typ == "Taxes":
            # Positive amount = broker refunding previously over-withheld tax
            # (German: Steuererstattung, annual settlement). Negative would be an
            # additional charge — treat symmetrically with abs/sign.
            if amount > 0:
                tax_refunds_eur += amount
            # A negative Taxes row would be an extra charge; hasn't been observed
            # but if it appears it will correctly reduce tax_refunds_eur below.
            else:
                tax_refunds_eur += amount  # adds a negative, i.e. increases net cost

    income_detail.sort(key=lambda x: x["date"])

    return {
        "total_deposited": round(total_deposited, 2),
        "total_withdrawn": round(total_withdrawn, 2),
        "prime_credits_eur": round(prime_credits, 2),
        "total_tax_eur": round(total_tax, 2),
        "tax_refunds_eur": round(tax_refunds_eur, 2),
        "distributions_eur": round(distributions_eur, 2),
        "interest_eur": round(interest_eur, 2),
        "cash_fees_eur": round(cash_fees_eur, 2),
        "income_detail": income_detail,
    }


# ---------------------------------------------------------------------------
# Realized gain pass  (FIFO reconstruction of closed round-trips)
# ---------------------------------------------------------------------------

def _realized_gain(rows: list[dict]) -> dict:
    """Walk the Security rows in chronological order using FIFO to pair sells
    against their corresponding buys.  Returns totals for the *closed* side
    only — open lots are not touched.

    This intentionally re-implements a minimal subset of lots.py's build_lots()
    rather than importing it, because:
      (a) lots.py produces open lots only — it discards realized info on pop;
      (b) this module must remain independent of the rest of the pipeline so
          the existing pipeline is entirely unaffected by adding it;
      (c) the logic needed here (pair buy cost against sell proceeds FIFO) is
          a small subset of build_lots' full responsibility.

    Corporate actions and Security transfer rows are excluded by the same rules
    as lots.py: transfers net to zero and are infrastructure artifacts; a
    corporate action replaces share counts / ISINs but is not a sale, so
    proceeds = 0 and we just carry cost/shares forward to the new ISIN.
    """
    from collections import defaultdict

    # open_lots[isin] = [{"shares", "price", "fee"}, ...]   (FIFO queue)
    open_lots: dict = defaultdict(list)

    realized_proceeds = 0.0
    realized_cost = 0.0
    realized_entry_fees = 0.0  # entry fees on the closed lots (already in cost)
    realized_exit_fees = 0.0   # broker fees on the sell orders themselves

    for r in rows:
        if r.get("assetType") != "Security":
            continue
        typ = r.get("type", "")

        if typ == "Security transfer":
            continue

        if typ == "Corporate action":
            # Minimal handling: carry open lots from old ISIN to new ISIN
            # preserving cost basis, mirroring lots.py's consolidation logic.
            shares = _parse_number(r.get("shares", "0"))
            isin = r.get("isin", "")
            if shares < 0:
                # outgoing leg — pop lots from old ISIN, stash them
                # We don't have the reference stem pairing here so we use a
                # simple "one pending swap at a time per ISIN" approach which
                # is sufficient for the realized-gain calculation (we only care
                # about total cost carried, not per-lot dates).
                open_lots[f"__swap_out_{isin}"] = open_lots.pop(isin, [])
            else:
                # incoming leg — find the matching outgoing stash
                old_isin = None
                for key in list(open_lots):
                    if key.startswith("__swap_out_"):
                        old_isin = key[len("__swap_out_"):]
                        break
                if old_isin is not None:
                    old_lots = open_lots.pop(f"__swap_out_{old_isin}", [])
                    total_old = sum(l["shares"] for l in old_lots)
                    if total_old > 0 and shares > 0:
                        # Rescale share counts, keep total cost and fees
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
            realized_proceeds += proceeds
            realized_exit_fees += fee

            remaining = shares  # shares to consume
            while remaining > 1e-9 and open_lots[isin]:
                oldest = open_lots[isin][0]
                if oldest["shares"] <= remaining + 1e-9:
                    # Consume entire lot
                    realized_cost += oldest["shares"] * oldest["price"] + oldest["fee"]
                    realized_entry_fees += oldest["fee"]
                    remaining -= oldest["shares"]
                    open_lots[isin].pop(0)
                else:
                    # Partial consumption — pro-rate fee just like lots.py does
                    fraction = remaining / oldest["shares"]
                    partial_fee = oldest["fee"] * fraction
                    realized_cost += remaining * oldest["price"] + partial_fee
                    realized_entry_fees += partial_fee
                    oldest["fee"] *= (1 - fraction)
                    oldest["shares"] -= remaining
                    remaining = 0

    return {
        "realized_proceeds_eur": round(realized_proceeds, 2),
        "realized_cost_eur": round(realized_cost, 2),
        "realized_gain_eur": round(realized_proceeds - realized_cost, 2),
        "realized_entry_fees_eur": round(realized_entry_fees, 2),
        "realized_exit_fees_eur": round(realized_exit_fees, 2),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(analysis: dict) -> dict:
    """Compute the full exit P&L report.

    Args:
        analysis: the dict returned by pipeline.analysis.main() (i.e. the
                  output of analyze_portfolio).  Used for open-position value,
                  cost, and the current cash balance (via pipeline.cash).

    Returns a dict with all the fields described in the module docstring.
    """
    from .cash import balance as cash_balance

    if not TRANSACTIONS_FILE.exists():
        return {"error": "no transaction history uploaded yet"}

    # --- load all executed rows, chronological order ---
    rows = []
    with open(TRANSACTIONS_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("status") != "Executed":
                continue
            rows.append(r)
    rows.sort(key=lambda r: datetime.strptime(
        f'{r["date"]} {r["time"]}', "%Y-%m-%d %H:%M:%S"
    ))

    # --- last executed transaction date (informational only) ---
    # NOT a proxy for export freshness: a long gap here just means no trades
    # happened, not that the export is missing rows. An earlier version of this
    # function treated "days since last executed row" as "days since the export
    # was downloaded" and auto-flagged the cash balance as incomplete whenever a
    # user simply hadn't traded in >1 day — a false positive confirmed on
    # 2026-07-28 (the export actually contained Pending/Cancelled rows dated
    # days after the last execution, proving it was current). Report the date
    # plainly and let the reader judge; don't infer staleness from it.
    last_tx_date = None
    if rows:
        last_tx_date = datetime.strptime(rows[-1]["date"], "%Y-%m-%d").date()
    today = datetime.now().date()
    days_since_last_tx = (today - last_tx_date).days if last_tx_date else None

    flows = _capital_flows(rows)
    realized = _realized_gain(rows)
    cash = cash_balance()

    # --- open-position figures from the analysis dict ---
    totals = analysis.get("totals", {})
    open_value = totals.get("total_value", 0.0) or 0.0
    open_cost = totals.get("total_cost", 0.0) or 0.0
    open_fees = totals.get("total_fees_eur", 0.0) or 0.0
    open_unrealized_gain = totals.get("gain_eur", 0.0) or 0.0

    cash_balance_eur = (cash.get("balance_eur") or 0.0)
    # `complete`/`note` here are cash.py's own diagnosis only (implausible-negative
    # check) - no longer overridden by trade-date recency.
    cash_complete = cash.get("complete", False)

    # --- hypothetical exit ---
    # What you'd hold if you sold everything at the latest prices right now:
    # current market value of securities + whatever cash is sitting in the account.
    hypothetical_exit_value = round(open_value + cash_balance_eur, 2)

    # Net P&L: what you'd walk away with minus what you put in.
    net_capital_in = round(flows["total_deposited"] - flows["total_withdrawn"], 2)
    net_pnl = round(hypothetical_exit_value - net_capital_in, 2)

    # All-time fees: order fees (entry+exit, open+closed) + cash-row broker fees
    total_fees_all_time = round(
        open_fees
        + realized["realized_entry_fees_eur"]
        + realized["realized_exit_fees_eur"]
        + flows["cash_fees_eur"],
        2,
    )

    total_income_gross = round(flows["distributions_eur"] + flows["interest_eur"], 2)
    total_income_tax = round(
        sum(e["tax_eur"] for e in flows["income_detail"]), 2
    )
    total_income_net = round(total_income_gross - total_income_tax, 2)

    generated_at = datetime.now().isoformat()

    return {
        "generated_at": generated_at,
        # --- what went in and came out ---
        "capital_flows": {
            "total_deposited_eur": flows["total_deposited"],
            "total_withdrawn_eur": flows["total_withdrawn"],
            "net_capital_in_eur": net_capital_in,
            "prime_credits_eur": flows["prime_credits_eur"],
        },
        # --- income earned (dividends, distributions, interest) ---
        "income": {
            "distributions_eur": flows["distributions_eur"],
            "interest_eur": flows["interest_eur"],
            "total_gross_eur": total_income_gross,
            "total_tax_eur": total_income_tax,
            "total_net_eur": total_income_net,
            "detail": flows["income_detail"],
        },
        # --- realized side (closed positions) ---
        "realized": {
            "proceeds_eur": realized["realized_proceeds_eur"],
            "cost_eur": realized["realized_cost_eur"],
            "gain_eur": realized["realized_gain_eur"],
            "entry_fees_eur": realized["realized_entry_fees_eur"],
            "exit_fees_eur": realized["realized_exit_fees_eur"],
        },
        # --- open side (from analyze_portfolio) ---
        "open_positions": {
            "market_value_eur": round(open_value, 2),
            "cost_basis_eur": round(open_cost, 2),
            "unrealized_gain_eur": round(open_unrealized_gain, 2),
            "entry_fees_on_open_lots_eur": round(open_fees, 2),
        },
        # --- taxes ---
        "taxes": {
            "withheld_gross_eur": flows["total_tax_eur"],
            "refunded_eur": flows["tax_refunds_eur"],
            "net_eur": round(flows["total_tax_eur"] - flows["tax_refunds_eur"], 2),
            "note": (
                "Tax withheld is the sum of the broker's tax column across all executed rows. "
                "Tax refunded is the sum of Cash/Taxes rows where the broker returned "
                "previously over-withheld tax (Steuererstattung). "
                "Tax that would be triggered by selling remaining open positions is NOT "
                "included — it depends on jurisdiction, holding period, and offsetting "
                "losses, which this module cannot determine."
            ),
        },
        # --- cash ---
        "cash": {
            "balance_eur": round(cash_balance_eur, 2),
            "complete": cash_complete,
            "note": cash.get("note", ""),
            "last_executed_transaction_date": last_tx_date.isoformat() if last_tx_date else None,
            "days_since_last_executed_transaction": days_since_last_tx,
        },
        # --- summary ---
        "summary": {
            "hypothetical_exit_value_eur": hypothetical_exit_value,
            "net_capital_in_eur": net_capital_in,
            "net_pnl_eur": net_pnl,
            "total_fees_all_time_eur": total_fees_all_time,
            "total_tax_net_eur": round(flows["total_tax_eur"] - flows["tax_refunds_eur"], 2),
            "net_pnl_after_fees_and_tax_note": (
                "net_pnl_eur already reflects all fees and taxes that have been paid "
                "to date (they reduced cash). Tax on unrealized open-position gains "
                "is not deducted — see taxes.note."
            ),
        },
    }


def render(report: dict) -> str:
    """Render a generate() result as a markdown report string."""
    if "error" in report:
        return f"## Exit P&L Report\n\nError: {report['error']}"

    def money(x):
        if x is None:
            return "n/a"
        return f"-€{-x:,.2f}" if x < 0 else f"€{x:,.2f}"

    def row(label, value, bold=False):
        v = f"**{value}**" if bold else value
        return f"| {label} | {v} |"

    cf = report["capital_flows"]
    ic = report["income"]
    rl = report["realized"]
    op = report["open_positions"]
    tx = report["taxes"]
    ca = report["cash"]
    sm = report["summary"]

    lines = [
        "## Exit P&L Report",
        "",
        f"*Generated: {report['generated_at']}*",
        "",
        "### Capital Flows (deposits & withdrawals)",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Total deposited (bank wires + internal transfers in)", money(cf["total_deposited_eur"])),
        row("Total withdrawn (bank wires + internal transfers out)", money(cf["total_withdrawn_eur"])),
        row("PRIME subscription credits (excluded from deposited)", money(cf["prime_credits_eur"])),
        row("**Net capital in**", money(cf["net_capital_in_eur"]), bold=True),
        "",
        "### Income Earned (dividends, distributions, interest)",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("ETF distributions / dividends (gross)", money(ic["distributions_eur"])),
        row("Cash interest (gross)", money(ic["interest_eur"])),
        row("Tax withheld on income", money(-ic["total_tax_eur"])),
        row("**Total income (net of tax)**", money(ic["total_net_eur"]), bold=True),
    ]

    if ic["detail"]:
        lines += [
            "",
            "| Date | Type | Description | Gross | Tax | Net |",
            "|------|------|-------------|------:|----:|----:|",
        ]
        for e in ic["detail"]:
            lines.append(
                f"| {e['date']} | {e['type']} | {e['description'] or '—'} "
                f"| €{e['gross_eur']:.2f} | €{e['tax_eur']:.2f} | €{e['net_eur']:.2f} |"
            )

    lines += [
        "",
        "### Realized Activity (closed positions)",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Gross sale proceeds", money(rl["proceeds_eur"])),
        row("FIFO cost of sold shares (incl. entry fees)", money(rl["cost_eur"])),
        row("Entry fees on closed lots", money(rl["entry_fees_eur"])),
        row("Exit (sell-order) fees", money(rl["exit_fees_eur"])),
        row("**Realized gain / loss**", money(rl["gain_eur"]), bold=True),
        "",
        "### Open Positions (current, from analyze_portfolio)",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Current market value", money(op["market_value_eur"])),
        row("Cost basis (incl. entry fees)", money(op["cost_basis_eur"])),
        row("Entry fees on open lots", money(op["entry_fees_on_open_lots_eur"])),
        row("**Unrealized gain / loss**", money(op["unrealized_gain_eur"]), bold=True),
        "",
        "### Taxes & Fees",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Tax withheld on income (distributions + interest)", money(ic["total_tax_eur"])),
        row("Tax withheld on security gains", money(tx["withheld_gross_eur"] - ic["total_tax_eur"])),
        row("Total tax withheld (gross)", money(tx["withheld_gross_eur"])),
        row("Tax refunded by broker (Steuererstattung)", money(-tx["refunded_eur"])),
        row("**Net tax cost**", money(tx["net_eur"]), bold=True),
        row("Order fees (entry + exit, open + closed positions)", money(sm["total_fees_all_time_eur"])),
        "",
        f"*{tx['note']}*",
        "",
        "### Cash Balance",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Current cash balance", money(ca["balance_eur"])),
        row(
            "Last executed transaction",
            f"{ca['last_executed_transaction_date']} ({ca['days_since_last_executed_transaction']} days ago)"
            if ca.get("last_executed_transaction_date") else "n/a",
        ),
        row("Cash balance plausible?", "Yes" if ca["complete"] else f"No — {ca['note']}"),
        "",
        "### Hypothetical Exit Summary",
        "",
        "| Item | Amount |",
        "|------|--------|",
        row("Current market value (open positions)", money(op["market_value_eur"])),
        row("+ Cash in account", money(ca["balance_eur"])),
        row("= **Hypothetical exit value** (before tax on open gains)", money(sm["hypothetical_exit_value_eur"]), bold=True),
        row("Net capital invested", money(sm["net_capital_in_eur"])),
        row("**Net P&L** (exit value − net capital in)", money(sm["net_pnl_eur"]), bold=True),
        row("of which: income earned (net)", money(ic["total_net_eur"])),
        row("of which: realized trading gain/loss", money(rl["gain_eur"])),
        row("of which: unrealized gain/loss (open positions)", money(op["unrealized_gain_eur"])),
        row("Total fees paid (all time, incl. PRIME charges)", money(sm["total_fees_all_time_eur"])),
        row("Net tax cost (withheld minus refunds)", money(sm["total_tax_net_eur"])),
        "",
        f"*{sm['net_pnl_after_fees_and_tax_note']}*",
    ]
    return "\n".join(lines)


def main(analysis: dict | None = None):
    """Entry point for direct module invocation (debugging).

    Reads analysis JSON from stdin if analysis is not passed (so you can pipe
    portfolio_tools.pipeline.analysis | portfolio_tools.pipeline.exit_report).
    """
    if analysis is None:
        analysis = json.loads(sys.stdin.read())
    report = generate(analysis)
    print(render(report))
    return report


if __name__ == "__main__":
    main()
