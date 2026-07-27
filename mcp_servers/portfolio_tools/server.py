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
from .paths import LOCK_FILE
from .pipeline import storage as _storage
from .pipeline.analysis import main as _analyze_portfolio
from .pipeline.backfill import main as _backfill_history
from .pipeline.cash import balance as _cash_balance
from .pipeline.compliance import main as _check_compliance
from .pipeline.config import load_config
from .pipeline.enrich import main as _enrich_lots
from .pipeline.lots import main as _compute_lots
from .pipeline.prices import main as _fetch_prices
from .pipeline.report import render as _render_report
from .pipeline.tickers import main as _resolve_tickers
from .pipeline.uploads import save as _save_transactions

HOST = "127.0.0.1"  # localhost only - this serves personal financial data, never bind wider than this
PORT = int(os.environ.get("PORTFOLIO_MCP_PORT", "8420"))


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
    """Rebuild transaction_lots.csv (pure FIFO lots, ISIN-keyed) from transactions.csv.
    Run after transactions.csv changes (new trades, or a fresh upload_transactions call).
    Reports open ISINs and flags any not yet in ticker_map.csv.

    Run enrich_lots afterward to produce enriched_lots.csv — the file every downstream
    tool (fetch_prices, analyze_portfolio, etc.) reads."""
    return _locked(_capture_stdout, _compute_lots)


@mcp.tool()
def enrich_lots() -> str:
    """Join transaction_lots.csv with ticker_map.csv and company_overrides.csv to produce
    enriched_lots.csv — the single file every downstream tool reads.

    Run this after compute_lots, after resolve_tickers (to pick up newly resolved tickers),
    or after set_ticker_mapping (to apply a corrected Sector or Ticker). Replaces the old
    pattern of running compute_lots a second time after resolve_tickers."""
    return _locked(_capture_stdout, _enrich_lots)


@mcp.tool()
def resolve_tickers() -> str:
    """Resolve any ISIN in transaction_lots.csv that has no ticker_map.csv row yet, via a real
    yfinance search (never a guess), and append the result to ticker_map.csv. Returns a review
    table - eyeball every row before trusting it, especially any flagged with a warning (wrong
    company, unsupported currency, multiple candidate listings). Sector is left blank for a
    human to fill in afterward. Run enrich_lots after this to apply the resolved tickers."""
    return _locked(_capture_stdout, _resolve_tickers)


@mcp.tool()
def fetch_prices() -> str:
    """Fetch today's live price for every ticker in transaction_lots.csv (Finnhub primary,
    yfinance fallback) and append one fully-sourced record per ticker to
    price_history/{TICKER}.jsonl. Run daily before analyze_portfolio.

    Safe to run more than once a day: it appends unconditionally (no same-day check),
    so N runs leave N records for that day, and analyze_portfolio collapses each ticker
    to the last record per calendar day on read. Extra runs cost API calls and add
    history lines, but cannot corrupt a reported figure."""
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
def check_compliance(analysis: dict) -> dict:
    """Evaluate the portfolio against every hard rule in INVESTMENT_FRAMEWORK.md.
    Pass the exact dict analyze_portfolio returned.

    Checks: sleeve split (Core ~80% / Tactical ~20%), max single non-hedge
    position (<=20%), secure-hedge combined cap (<=30%), top-3 combined
    (<=40%), sector concentration (<=40% each), cash ceiling (<=EUR 5,000),
    and positions below EUR 250 whose exit fee is EUR 0.99.

    Returns a structured dict with a top-level `breaches` list (empty = clean)
    and per-check detail sections. The agent reads this output; it never
    re-applies the rules in prose.

    Also returns `prime_status` (current PRIME subscription state derived from
    transactions), `fee_history` (aggregate fee drag stats), and
    `missing_roles` (tickers with no role assigned, which makes sleeve checks
    partial)."""
    cash = _cash_balance()
    cash_eur = cash.get("balance_eur") if cash.get("complete") else None
    return _locked(
        _check_compliance,
        analysis_positions=analysis["positions"],
        sector_breakdown=analysis["sectors"],
        total_value=analysis["totals"]["total_value"],
        cash_balance_eur=cash_eur,
    )


@mcp.tool()
def render_report(analysis: dict) -> str:
    """Render analyze_portfolio's JSON output as the same markdown tables the daily report uses
    (Portfolio Overview, Trend, Sector Breakdown, Largest Positions, Movers, Complete Holdings
    Table, Fee Drag, XIRR Context, Data Notes). Pass the exact dict analyze_portfolio returned - never
    hand-transcribe a figure out of it yourself; if a section needs to look different, that's a
    change to make here, not a one-off rewrite."""
    return _locked(_render_report, analysis, load_config())


@mcp.tool()
def save_news_source(ticker: str, company: str, source_url: str, title: str, text: str,
                     fetch_method: str = "WebSearch",
                     retrieved_for: str = "portfolio-daily-analysis") -> str:
    """Persist one fetched news source for a ticker. Call this instead of writing a file
    yourself - you don't need to know where data lives, and the server generates the
    timestamp, filename slug and metadata header so they can't drift between runs.

    One call per distinct source that actually informed a note (skip near-duplicate
    coverage of the same story, and skip tickers where nothing notable turned up).
    Pass `text` as the article text/snippet you actually used, and `fetch_method` as the
    real query you ran, e.g. 'WebSearch (query: "AMD stock news")'."""
    return _locked(_storage.save_news_source, ticker, company, source_url, title, text,
                   fetch_method=fetch_method, retrieved_for=retrieved_for)


@mcp.tool()
def save_report(markdown: str, report_date: str = "") -> str:
    """Save the daily analysis report. Defaults to today; pass report_date (YYYY-MM-DD)
    only to backfill or correct a specific day. Re-saving replaces that day's report
    rather than adding a duplicate.

    Pass the complete report: your Executive Summary, then render_report's markdown with
    the Movers Context column filled in, then the Holdings News Digest."""
    return _locked(_storage.save_report, markdown, report_date or None)


@mcp.tool()
def get_report(report_date: str = "") -> str:
    """Return a previously saved report's markdown - the most recent one by default, or a
    specific day with report_date (YYYY-MM-DD). Use this to compare against yesterday
    instead of trying to open the file."""
    return _locked(_storage.get_report, report_date or None)


@mcp.tool()
def list_reports(limit: int = 30) -> str:
    """Dates of saved reports, newest first."""
    return _locked(_storage.list_reports, limit)


@mcp.tool()
def list_news(ticker: str, limit: int = 20) -> str:
    """Filenames of news sources already stored for a ticker, newest first - useful to
    check what's been captured before re-fetching the same story."""
    return _locked(_storage.list_news, ticker, limit)


@mcp.tool()
def get_news_source(ticker: str, filename: str) -> str:
    """Full text of one stored news source, by a filename from list_news."""
    return _locked(_storage.get_news_source, ticker, filename)


@mcp.tool()
def read_roles() -> str:
    """Current portfolio role per holding (Core Compounder / Growth / Opportunistic /
    Defensive), with when each was last confirmed. Roles drive the framework's
    allocation bands, so a stale label quietly invalidates that check."""
    roles = _locked(_storage.read_roles)
    if not roles:
        return "No roles assigned yet."
    return "\n".join(f"{t}: {v['role']} (confirmed {v['assigned']})"
                     + (f" - {v['note']}" if v["note"] else "")
                     for t, v in sorted(roles.items()))


@mcp.tool()
def set_position_role(ticker: str, role: str, note: str = "") -> str:
    """Assign or re-confirm one holding's portfolio role. Valid roles: Core Compounder,
    Growth, Opportunistic, Defensive.

    Re-assess rather than trusting the stored label: a Growth position whose thesis
    breaks is Opportunistic (or an exit candidate), and the allocation bands only mean
    something if the labels still describe reality."""
    return _locked(_storage.set_position_role, ticker, role, note)


@mcp.tool()
def read_ticker_map() -> str:
    """The ISIN -> Ticker/Company/Sector table as text. Use this to review a blank
    Sector or a suspect ticker instead of opening the file."""
    return _locked(_storage.read_ticker_map)


@mcp.tool()
def list_lots(ticker: str = "") -> str:
    """Open FIFO lots - every lot, or one ticker's if you pass it.

    Read-only lot-level detail (purchase date, shares, execution price, fee per lot)
    behind figures analyze_portfolio only reports in aggregate. Use it to check what a
    weighted_avg_holding_days or cost basis is actually built from - e.g. whether a
    position is one lot or several, and whether its shares came through a corporate
    action. Never edit the underlying file to "fix" what this shows; lots are derived,
    so the fix is in transactions.csv or compute_lots."""
    return _locked(_storage.read_lots, ticker or None)


@mcp.tool()
def set_ticker_mapping(isin: str, ticker: str = "", company: str = "", sector: str = "") -> str:
    """Create or update one ISIN's row in the ticker map. Only the fields you pass are
    changed, so you can fill in a Sector without restating the ticker.

    Needed because resolve_tickers deliberately leaves Sector blank for a human
    judgment call, and a mis-resolved listing occasionally needs correcting. Never
    guess a ticker here - resolve_tickers is the only sanctioned way to determine one
    (see the skill's rule 1). enriched_lots.csv is updated automatically — no
    separate enrich_lots call needed."""
    return _locked(_storage.set_ticker_mapping, isin,
                   ticker or None, company or None, sector or None)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
