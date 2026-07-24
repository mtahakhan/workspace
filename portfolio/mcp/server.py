#!/usr/bin/env python3
"""MCP server exposing the portfolio/pipeline package's functions as typed tools.

Every tool below is a thin wrapper around the exact same function the
matching CLI entry point (`python3 -m pipeline.lots`, etc. - see
QUICKSTART.md) uses - there is no separate wrapper script, both this server
and the CLI import directly from the pipeline/ package, so there is exactly
one implementation of each computation (see PIPELINE.md / AGENT_NOTES.md's
component table). This file adds no new computation, it only changes how the
deterministic layer is invoked (a typed tool call instead of Bash +
stdout/JSON parsing). The CLI entry points remain fully usable standalone
(see QUICKSTART.md).

pipeline.lots / pipeline.tickers / pipeline.prices / pipeline.backfill's
main() produce human-readable progress/review text as their actual product
(not just diagnostics) - captured here via stdout redirection rather than
changing those functions, so their behavior is guaranteed identical to
running the CLI directly. pipeline.analysis.main() and pipeline.report.render()
already return structured data (a dict, a markdown string), so those are
called directly with no capture needed.
"""

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # portfolio/ - so the `pipeline` package is importable

from pipeline.analysis import main as _analyze_portfolio
from pipeline.backfill import main as _backfill_history
from pipeline.config import load_config
from pipeline.lots import main as _compute_lots
from pipeline.prices import main as _fetch_prices
from pipeline.report import render as _render_report
from pipeline.tickers import main as _resolve_tickers

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("portfolio")


def _capture_stdout(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


@mcp.tool()
def compute_lots() -> str:
    """Rebuild transaction_lots.csv (FIFO open lots) from transactions.csv + ticker_map.csv.
    Run after transactions.csv changes (new trades). Reports current per-ticker share totals
    and flags any ISIN missing from ticker_map.csv or with a blank Sector."""
    return _capture_stdout(_compute_lots)


@mcp.tool()
def resolve_tickers() -> str:
    """Resolve any ISIN in transaction_lots.csv that has no ticker_map.csv row yet, via a real
    yfinance search (never a guess), and append the result to ticker_map.csv. Returns a review
    table - eyeball every row before trusting it, especially any flagged with a warning (wrong
    company, unsupported currency, multiple candidate listings). Sector is left blank for a
    human to fill in afterward."""
    return _capture_stdout(_resolve_tickers)


@mcp.tool()
def fetch_prices() -> str:
    """Fetch today's live price for every ticker in transaction_lots.csv (Finnhub primary,
    yfinance fallback) and append one fully-sourced record per ticker to
    price_history/{TICKER}.jsonl. Run daily before analyze_portfolio."""
    return _capture_stdout(_fetch_prices)


@mcp.tool()
def backfill_history(period: str = "max") -> str:
    """One-off/rare: rewrite each ticker's full price_history/{TICKER}.jsonl from yfinance
    historical data, needed for accurate drawdown/trend figures. Slower than fetch_prices and
    not part of the daily cycle - only run this for a brand-new ticker or if history looks
    corrupted."""
    return _capture_stdout(_backfill_history, period=period)


@mcp.tool()
def analyze_portfolio() -> dict:
    """Deterministic numeric layer: portfolio value, gain/loss, sector breakdown, largest
    positions, high-water-mark/drawdown, today's movers, trend over several windows, and a real
    money-weighted XIRR - computed from transaction_lots.csv + price_history/*.jsonl, with every
    threshold read from config.json. Never recompute any of these numbers by hand; if one looks
    wrong, that's a bug to fix in this pipeline, not something to override by reasoning over the
    raw data. Also returns stale_prices (2+ day old quotes) and caveats (incl. a run-over-run
    value-divergence check), and appends this run to analysis_history.jsonl as a side effect."""
    return _analyze_portfolio()


@mcp.tool()
def render_report(analysis: dict) -> str:
    """Render analyze_portfolio's JSON output as the same markdown tables the daily report uses
    (Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete Holdings
    Table, XIRR Context, Data Notes). Pass the exact dict analyze_portfolio returned - never
    hand-transcribe a figure out of it yourself; if a section needs to look different, that's a
    change to make here, not a one-off rewrite."""
    return _render_report(analysis, load_config())


if __name__ == "__main__":
    mcp.run()
