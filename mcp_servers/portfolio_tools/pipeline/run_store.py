#!/usr/bin/env python3
"""Persistence for "refreshes" - one directory per call to the create_refresh
MCP tool, holding the four files that a full deterministic pass produces
(analyze_portfolio, check_compliance, render_report, generate_exit_report).

Why this exists: those four computations used to be four separate MCP tools
that handed their full payload back to the caller directly, and three of them
additionally required the caller to pass analyze_portfolio's dict straight
back in as an argument - which meant the numbers had to survive
in-conversation from one tool call to the next. That's fine within a single
task's own conversation, but it stops the tasks from being independent: the
price-fetch task and the daily-analysis task are separate scheduled
invocations with no shared context, so nothing computed by one can be an
argument to a tool called by the other.

The fix is one write endpoint (create_refresh in server.py) that runs all
four steps and writes each result as its own file inside one new directory -
a "refresh" - identified by a single id string ("{date}/{time}"), and a
matching read endpoint (get_refresh) that takes that id back. Nothing is ever
passed between tool calls as an argument.

Directory layout: PIPELINE_RUNS_DIR/{YYYY-MM-DD}/{HH-MM-SS-ffffff}/, so
"list every refresh from one day" (list_refreshes) is a plain directory
listing rather than a filename-prefix filter. Multiple refreshes per day are
normal, not an edge case - same as fetch_prices already being safe to call
more than once a day.

A refresh is "valid" only if all four files are present. create_refresh stops
at the first step that raises (see server.py) rather than catching and
continuing, so a mid-run failure leaves a real, identifiable gap - an
incomplete directory - rather than silently substituting stale or partial
data. Callers (get_refresh, and the task instructions in
skills/portfolio/references/tasks/*.md) treat an incomplete refresh as
unusable and fall back to another valid one from the same day, or to running
create_refresh again.
"""

import json
from datetime import datetime

# kind -> (filename, format). One entry per step create_refresh runs, in the
# order they run. The format tag decides how save/load (de)serializes it -
# JSON for the three dict-producing steps, plain text for render_report's
# markdown.
_KINDS = {
    "analysis": ("analysis.json", "json"),
    "compliance": ("compliance.json", "json"),
    "render": ("render.md", "text"),
    "exit_report": ("exit-report.json", "json"),
}


def valid_kinds():
    return list(_KINDS)


def _kind_path(refresh_dir, kind):
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {sorted(_KINDS)}, got {kind!r}")
    filename, _ = _KINDS[kind]
    return refresh_dir / filename


def new_refresh_dir(base_dir):
    """Create and return a new refresh directory under base_dir, nested
    {YYYY-MM-DD}/{HH-MM-SS-ffffff} - one call per create_refresh run."""
    now = datetime.now()
    refresh_dir = base_dir / now.strftime("%Y-%m-%d") / now.strftime("%H-%M-%S-%f")
    refresh_dir.mkdir(parents=True, exist_ok=False)
    return refresh_dir


def refresh_id(base_dir, refresh_dir):
    """The "{date}/{time}" id a caller uses to refer back to this refresh -
    refresh_dir's path relative to base_dir, as a string."""
    return str(refresh_dir.relative_to(base_dir))


def save_kind(refresh_dir, kind, data):
    """Write one step's output into an existing refresh directory. `data` is a
    dict for the JSON kinds, a str for "render". Returns nothing - the caller
    already has refresh_dir/refresh_id; there is no separate path per file to
    report."""
    path = _kind_path(refresh_dir, kind)
    _, fmt = _KINDS[kind]
    if fmt == "json":
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    else:
        path.write_text(data.rstrip() + "\n", encoding="utf-8")


def is_valid(refresh_dir):
    """A refresh is valid only if every step's file is present - see module
    docstring. Doesn't check content, only that each step got as far as
    writing its file."""
    return refresh_dir.is_dir() and all(
        _kind_path(refresh_dir, kind).exists() for kind in _KINDS
    )


def list_refresh_dirs(base_dir, date=None):
    """Refresh directories for one day (default today), oldest first. Returns
    Path objects regardless of validity - callers that only want usable
    refreshes should filter with is_valid()."""
    day = (date or datetime.now().date().isoformat()).strip()
    day_dir = base_dir / day
    if not day_dir.exists():
        return []
    return sorted(p for p in day_dir.iterdir() if p.is_dir())


def latest_valid_refresh_dir(base_dir, date=None):
    """The most recent *valid* refresh - scoped to one day if `date` is given,
    otherwise the most recent valid refresh across all days. Raises
    FileNotFoundError (message safe to return directly to a caller) if none
    qualifies - either nothing has run yet, or every candidate is incomplete."""
    if date:
        candidates = list_refresh_dirs(base_dir, date)
    else:
        candidates = sorted(
            p for day_dir in (base_dir.iterdir() if base_dir.exists() else [])
            if day_dir.is_dir()
            for p in day_dir.iterdir() if p.is_dir()
        )
    for refresh_dir in reversed(candidates):
        if is_valid(refresh_dir):
            return refresh_dir
    scope = f" on {date}" if date else ""
    raise FileNotFoundError(
        f"No valid refresh{scope} - either create_refresh hasn't been called{scope} yet, "
        f"or every refresh{scope} is incomplete (a prior run stopped partway through)."
    )


def resolve_refresh_dir(base_dir, refresh_id_str=None, date=None):
    """The refresh directory a get_refresh/list_refreshes caller means: an
    exact refresh_id_str if given (must exist, need not be valid - the caller
    decides what to do with an incomplete one), else the latest valid refresh
    (see latest_valid_refresh_dir)."""
    if refresh_id_str:
        refresh_dir = base_dir / refresh_id_str.strip()
        if not refresh_dir.is_dir():
            raise FileNotFoundError(f"No refresh {refresh_id_str!r}.")
        return refresh_dir
    return latest_valid_refresh_dir(base_dir, date)


def get_kind(refresh_dir, kind):
    """Read one step's output back. Returns a dict for JSON kinds, a str for
    "render". Raises FileNotFoundError if that step's file isn't in this
    refresh (an incomplete refresh, or an unknown refresh_id)."""
    path = _kind_path(refresh_dir, kind)
    if not path.exists():
        raise FileNotFoundError(
            f"No {kind!r} file in this refresh ({path.parent.name}) - "
            f"it's incomplete, stopped before this step ran."
        )
    _, fmt = _KINDS[kind]
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if fmt == "json" else text
