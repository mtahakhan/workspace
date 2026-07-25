#!/usr/bin/env python3
"""The `portfolio` MCP server - HTTP-only, registered globally (see
../bootstrap.sh), not tied to any particular Claude Code project. Every tool
below wraps a `pipeline/` function directly (pipeline is a subpackage of this
same package, not a separate CLI project) - there is exactly one
implementation of each computation, this file only adds the typed-tool
interface and the concurrency guard described below.

Deployment model: this process is meant to be started once (by
bootstrap.sh) and left running, reached over HTTP by any number of Claude
Code sessions across any number of projects - not spawned fresh per session
the way a stdio server would be. That means concurrent tool calls are a real
possibility, so every tool call is serialized through DATA_LOCK (see lock.py)
before it touches anything under data/ - none of the pipeline's
read-modify-write sequences (e.g. compute_lots reading transaction_lots.csv +
ticker_map.csv then rewriting the former) are safe under concurrent access on
their own.

pipeline.lots / pipeline.tickers / pipeline.prices / pipeline.backfill's
main() produce human-readable progress/review text as their actual product
(not just diagnostics) - captured here via stdout redirection rather than
changing those functions. pipeline.analysis.main() and pipeline.report.render()
already return structured data (a dict, a markdown string), so those are
called directly with no capture needed.
"""

import contextlib
import io
import os

from mcp.server.fastmcp import FastMCP

from .lock import locked
from .paths import DATA_DIR
from .pipeline.analysis import main as _analyze_portfolio
from .pipeline.backfill import main as _backfill_history
from .pipeline.config import load_config
from .pipeline.lots import main as _compute_lots
from .pipeline.prices import main as _fetch_prices
from .pipeline.report import render as _render_report
from .pipeline.tickers import main as _resolve_tickers
from .pipeline.uploads import save as _save_transactions

HOST = "127.0.0.1"  # localhost only - this serves personal financial data, never bind wider than this
PORT = int(os.environ.get("PORTFOLIO_MCP_PORT", "8420"))

LOCK_FILE = DATA_DIR / ".pipeline.lock"

mcp = FastMCP("portfolio", host=HOST, port=PORT)


def _capture_stdout(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _locked(fn, *args, **kwargs):
    """Every tool goes through this - see module docstring on why."""
    with locked(LOCK_FILE):
        return fn(*args, **kwargs)


@mcp.tool()
def upload_transactions(csv_content: str) -> str:
    """Save the user's broker transaction export into this server's own data
    directory - the file never needs to exist on whatever filesystem the caller
    is on. Paste the COMPLETE raw CSV text (semicolon-delimited, German decimal
    commas; Scalable Capital's export format only, for now). This is always a
    full re-export, not incremental - paste the whole file every time you trade,
    not just new rows. The previous upload (if any) is kept as a .bak file.
    Call compute_lots next to rebuild positions from it."""
    return _locked(_save_transactions, csv_content)


@mcp.tool()
def compute_lots() -> str:
    """Rebuild transaction_lots.csv (FIFO open lots) from transactions.csv + ticker_map.csv.
    Run after transactions.csv changes (new trades, or a fresh upload_transactions call).
    Reports current per-ticker share totals and flags any ISIN missing from ticker_map.csv
    or with a blank Sector."""
    return _locked(_capture_stdout, _compute_lots)


@mcp.tool()
def resolve_tickers() -> str:
    """Resolve any ISIN in transaction_lots.csv that has no ticker_map.csv row yet, via a real
    yfinance search (never a guess), and append the result to ticker_map.csv. Returns a review
    table - eyeball every row before trusting it, especially any flagged with a warning (wrong
    company, unsupported currency, multiple candidate listings). Sector is left blank for a
    human to fill in afterward."""
    return _locked(_capture_stdout, _resolve_tickers)


@mcp.tool()
def fetch_prices() -> str:
    """Fetch today's live price for every ticker in transaction_lots.csv (Finnhub primary,
    yfinance fallback) and append one fully-sourced record per ticker to
    price_history/{TICKER}.jsonl. Run daily before analyze_portfolio."""
    return _locked(_capture_stdout, _fetch_prices)


@mcp.tool()
def backfill_history(period: str = "max") -> str:
    """One-off/rare: rewrite each ticker's full price_history/{TICKER}.jsonl from yfinance
    historical data, needed for accurate drawdown/trend figures. Slower than fetch_prices and
    not part of the daily cycle - only run this for a brand-new ticker or if history looks
    corrupted."""
    return _locked(_capture_stdout, _backfill_history, period=period)


@mcp.tool()
def analyze_portfolio() -> dict:
    """Deterministic numeric layer: portfolio value, gain/loss, sector breakdown, largest
    positions, high-water-mark/drawdown, today's movers, trend over several windows, and a real
    money-weighted XIRR - computed from transaction_lots.csv + price_history/*.jsonl, with every
    threshold read from config.json. Never recompute any of these numbers by hand; if one looks
    wrong, that's a bug to fix in this pipeline, not something to override by reasoning over the
    raw data. Also returns stale_prices (2+ day old quotes) and caveats (incl. a run-over-run
    value-divergence check), and appends this run to analysis_history.jsonl as a side effect."""
    return _locked(_analyze_portfolio)


@mcp.tool()
def render_report(analysis: dict) -> str:
    """Render analyze_portfolio's JSON output as the same markdown tables the daily report uses
    (Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete Holdings
    Table, XIRR Context, Data Notes). Pass the exact dict analyze_portfolio returned - never
    hand-transcribe a figure out of it yourself; if a section needs to look different, that's a
    change to make here, not a one-off rewrite."""
    return _locked(_render_report, analysis, load_config())


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
