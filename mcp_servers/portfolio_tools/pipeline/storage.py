#!/usr/bin/env python3
"""Reads and writes for the two artifacts the LLM produces rather than computes:
fetched news sources and the daily report.

Why this module exists: everything else under data/ is written by a deterministic
pipeline module, but news text and the report's prose come from the agent. Before
this, the agent wrote those files itself with a generic file tool, which meant it
had to know the data directory's location and hand-type each metadata header - so
the header was only as accurate as the model's memory, and the layout could drift
per run. Routing them through here makes the server the only thing that knows
where data lives (see paths.py) and the only thing that formats a header.

Callers pass content and facts, never paths. Filenames, timestamps, slugs and the
directory layout are decided here.
"""

import csv
import re
import unicodedata
from datetime import datetime

from ..paths import NEWS_DIR, REPORTS_DIR, ROLES_FILE, TICKER_MAP_FILE, TRANSACTION_LOTS_FILE

SLUG_MAX_LEN = 60
TICKER_MAP_FIELDS = ["ISIN", "Ticker", "Company", "Sector"]
ROLES_FIELDS = ["Ticker", "Role", "Assigned", "Note"]

# Valid role labels. Allocation is now governed by the two-sleeve model
# (Core ~80% / Tactical ~20%) rather than per-role bands - see
# INVESTMENT_FRAMEWORK.md. The old 40-60/20-40/<=15/5-20 bands are superseded.
# compliance.py is the authoritative place for every limit check.
PORTFOLIO_ROLES = {
    "Core Compounder",
    "Growth",
    "Opportunistic",
    "Defensive",
}


def _slugify(text, fallback="source"):
    """Lowercase ASCII hyphenated slug, <=SLUG_MAX_LEN chars. Falls back when a
    title is missing or slugifies to nothing (e.g. a CJK-only headline)."""
    if not text:
        return fallback
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:SLUG_MAX_LEN].rstrip("-")
    return slug or fallback


def _source_domain(url):
    match = re.match(r"https?://([^/]+)", url or "")
    return match.group(1).replace("www.", "") if match else ""


def save_news_source(ticker, company, source_url, title, text,
                     fetch_method="WebSearch", retrieved_for="portfolio-daily-analysis"):
    """Persist one fetched news source under news/{TICKER}/, with a generated
    metadata header. One file per source; the timestamp+slug filename makes it
    identifiable at a glance and cannot collide with a prior day's file for the
    same ticker. Returns a one-line confirmation naming the file written."""
    if not ticker or not ticker.strip():
        raise ValueError("ticker is required")
    if not text or not text.strip():
        raise ValueError("text is required - a source with no fetched text isn't worth persisting")

    now = datetime.now().astimezone()
    slug = _slugify(title, fallback=_slugify(_source_domain(source_url)) or "source")
    filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{slug}.txt"

    ticker_dir = NEWS_DIR / ticker.strip()
    ticker_dir.mkdir(parents=True, exist_ok=True)
    path = ticker_dir / filename

    header = (
        f"Ticker: {ticker.strip()}\n"
        f"Company: {company or ''}\n"
        f"Source URL: {source_url or ''}\n"
        f"Title: {title or ''}\n"
        f"Fetched At: {now.isoformat(timespec='seconds')}\n"
        f"Fetch Method: {fetch_method}\n"
        f"Retrieved For: {retrieved_for}\n"
    )
    path.write_text(f"{header}\n{text.strip()}\n", encoding="utf-8")
    return f"Saved news source for {ticker.strip()}: {filename}"


def save_report(markdown, report_date=None):
    """Write the daily report. Defaults to today; pass report_date (YYYY-MM-DD)
    only to backfill or correct a specific day. Overwrites that day's report, so
    re-running the analysis replaces it rather than accumulating duplicates."""
    if not markdown or not markdown.strip():
        raise ValueError("markdown is required")
    day = (report_date or datetime.now().date().isoformat()).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError(f"report_date must be YYYY-MM-DD, got {day!r}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{day}.md"
    existed = path.exists()
    path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return f"{'Replaced' if existed else 'Wrote'} report for {day} ({len(markdown.splitlines())} lines)"


def get_report(report_date=None):
    """Return one report's markdown. Defaults to the most recent one, which is
    what 'what did yesterday's report say' actually wants."""
    if report_date:
        day = report_date.strip()
        path = REPORTS_DIR / f"{day}.md"
        if not path.exists():
            return f"No report for {day}."
        return path.read_text(encoding="utf-8")
    reports = _report_paths()
    if not reports:
        return "No reports yet."
    return reports[-1].read_text(encoding="utf-8")


def list_reports(limit=30):
    """Available report dates, newest first."""
    reports = _report_paths()
    if not reports:
        return "No reports yet."
    dates = [p.stem for p in reversed(reports)][:limit]
    return "\n".join(dates)


def list_news(ticker, limit=20):
    """Filenames of persisted sources for one ticker, newest first - enough to
    see what has already been captured without exposing where it lives."""
    ticker_dir = NEWS_DIR / ticker.strip()
    if not ticker_dir.exists():
        return f"No news stored for {ticker}."
    files = sorted((p.name for p in ticker_dir.glob("*.txt")), reverse=True)[:limit]
    return "\n".join(files) if files else f"No news stored for {ticker}."


def get_news_source(ticker, filename):
    """Full text of one previously saved source, by the filename list_news gave."""
    path = (NEWS_DIR / ticker.strip() / filename).resolve()
    news_root = NEWS_DIR.resolve()
    if not path.is_relative_to(news_root):  # filename must not escape the news tree
        raise ValueError("filename must be a plain filename, not a path")
    if not path.exists():
        return f"No such stored source: {ticker}/{filename}"
    return path.read_text(encoding="utf-8")


def read_ticker_map():
    """The whole ticker map as text, so a blank Sector or a suspect Ticker can be
    reviewed without opening the file."""
    if not TICKER_MAP_FILE.exists():
        return "ticker_map is empty."
    return TICKER_MAP_FILE.read_text(encoding="utf-8")


def read_lots(ticker=None):
    """Open FIFO lots as text - every lot, or just one ticker's.

    The lot-level view (date, shares, execution price, fee per lot) that
    analyze_portfolio only ever reports in aggregate. Exists so a figure like
    weighted_avg_holding_days can be traced back to the purchases behind it
    without reading transaction_lots.csv off disk - which the skill forbids, and
    which is machine-specific anyway since the data root is configurable.
    """
    if not TRANSACTION_LOTS_FILE.exists():
        return "No lots file yet - run compute_lots first."
    text = TRANSACTION_LOTS_FILE.read_text(encoding="utf-8")
    if not ticker:
        return text
    lines = text.splitlines()
    header, rows = lines[0], lines[1:]
    wanted = ticker.strip().upper()
    matched = [r for r in rows if r.split(",")[1:2] == [wanted]]
    if not matched:
        known = sorted({r.split(",")[1] for r in rows if len(r.split(",")) > 1 and r.split(",")[1]})
        return f"No open lots for {wanted}. Tickers with open lots: {', '.join(known)}"
    return "\n".join([header] + matched)


def set_ticker_mapping(isin, ticker=None, company=None, sector=None):
    """Create or update one ISIN's row. Only the fields passed are changed, so a
    Sector can be filled in without restating the ticker.

    This exists because resolve_tickers deliberately leaves Sector blank for a
    human judgment call, and a mis-resolved listing sometimes needs correcting -
    both of which used to mean hand-editing the CSV. Rewrites the file in place,
    preserving row order and every column not being set.
    """
    isin = (isin or "").strip()
    if not isin:
        raise ValueError("isin is required")
    if ticker is None and company is None and sector is None:
        raise ValueError("pass at least one of ticker, company, sector")

    rows, found = [], False
    if TICKER_MAP_FILE.exists():
        with open(TICKER_MAP_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
    for row in rows:
        if row.get("ISIN", "").strip() == isin:
            found = True
            for field, value in (("Ticker", ticker), ("Company", company), ("Sector", sector)):
                if value is not None:
                    row[field] = value.strip()
    if not found:
        rows.append({"ISIN": isin, "Ticker": (ticker or "").strip(),
                     "Company": (company or "").strip(), "Sector": (sector or "").strip()})

    TICKER_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TICKER_MAP_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TICKER_MAP_FIELDS)
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in TICKER_MAP_FIELDS} for row in rows)

    changed = ", ".join(f"{k}={v!r}" for k, v in
                        (("Ticker", ticker), ("Company", company), ("Sector", sector)) if v is not None)
    return (f"{'Updated' if found else 'Added'} {isin}: {changed}. "
            f"Run compute_lots to apply it to positions.")


def read_roles():
    """{ticker: {"role", "assigned", "note"}} - empty if never assigned."""
    if not ROLES_FILE.exists():
        return {}
    with open(ROLES_FILE, newline="") as f:
        return {r["Ticker"].strip(): {"role": r.get("Role", "").strip(),
                                      "assigned": r.get("Assigned", "").strip(),
                                      "note": r.get("Note", "").strip()}
                for r in csv.DictReader(f) if r.get("Ticker", "").strip()}


def set_position_role(ticker, role, note=""):
    """Assign or change one holding's portfolio role.

    Roles are re-assessed, not set once: a Growth position whose thesis breaks
    becomes Opportunistic (or an exit candidate), and the allocation bands are
    only meaningful if the labels still describe reality. `Assigned` records when
    the current label was last confirmed, so a stale one is visible as stale.
    """
    ticker = (ticker or "").strip()
    role = (role or "").strip()
    if not ticker:
        raise ValueError("ticker is required")
    if role not in PORTFOLIO_ROLES:
        raise ValueError(f"role must be one of {sorted(PORTFOLIO_ROLES)}, got {role!r}")

    roles = read_roles()
    previous = roles.get(ticker, {}).get("role", "")
    roles[ticker] = {"role": role, "assigned": datetime.now().date().isoformat(),
                     "note": note.strip() or roles.get(ticker, {}).get("note", "")}

    ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ROLES_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ROLES_FIELDS)
        writer.writeheader()
        for t in sorted(roles):
            writer.writerow({"Ticker": t, "Role": roles[t]["role"],
                             "Assigned": roles[t]["assigned"], "Note": roles[t]["note"]})

    if previous and previous != role:
        return f"{ticker}: role changed {previous} -> {role}"
    return f"{ticker}: role set to {role}" if not previous else f"{ticker}: role reconfirmed as {role}"


def _report_paths():
    """Report files sorted ascending by date (filenames are YYYY-MM-DD.md)."""
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("*.md"))
