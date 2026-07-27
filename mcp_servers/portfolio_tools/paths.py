"""Single source of truth for this package's filesystem layout.

Code lives in the package; **data does not**. The data root is external and
configurable, so the server can be pointed at a directory outside this repo
(a synced folder, an encrypted volume, somewhere with its own backups)
without touching code. Resolution order:

  1. ``PORTFOLIO_DATA_DIR`` in the process environment
  2. ``PORTFOLIO_DATA_DIR=`` in this package's ``.env`` (written by
     ``setup-env.sh``) - so the value survives however the server is launched
  3. ``<repo>/data/`` - the default when the user picks nothing

Inside the data root there are exactly two subdirectories, and the split is
what decides whether something is committable:

  ``personal/``    - what the user actually owns and is worth: transactions,
                     derived FIFO lots, analysis history, generated reports.
                     Never committed (see .gitignore).
  ``impersonal/``  - facts about securities and the world, true for everyone:
                     ticker_map.csv, company_overrides.csv, price history, and
                     fetched news. Committed and ever-growing, so resolving a
                     ticker or fetching a day's close is work nobody using this
                     project has to repeat.

The line between them is ownership, not subject matter: a market close for AMD
is the same number whoever looks it up, whereas how many shares of it you hold
is not. That makes the rule mechanical - all of ``personal/`` is gitignored,
all of ``impersonal/`` is committed, with no per-file exceptions to remember.

Nothing here is derived from the current working directory or from any notion
of "the current project" - this server is registered globally and invoked over
HTTP, so there is no project context to resolve paths against. It always
operates on the same data regardless of which Claude Code session is talking
to it. See AGENT_NOTES.md rule 8 on keeping one copy of anything (here: path
constants) in sync - every other module imports from here, and no module
builds a data path of its own.
"""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent          # mcp_servers/portfolio_tools/
REPO_ROOT = PACKAGE_ROOT.parent.parent                  # the repo checkout
CONFIG_FILE = PACKAGE_ROOT / "config.json"              # committed source, not data
ENV_FILE = PACKAGE_ROOT / ".env"                        # server config + secrets

DATA_DIR_ENV_VAR = "PORTFOLIO_DATA_DIR"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


def _env_file_value(key):
    """Read one KEY=value out of .env. Returns "" if absent - .env is optional."""
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def resolve_data_dir():
    """The configured data root, as an absolute path. See module docstring."""
    configured = os.environ.get(DATA_DIR_ENV_VAR, "").strip() or _env_file_value(DATA_DIR_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DATA_DIR


DATA_DIR = resolve_data_dir()
PERSONAL_DIR = DATA_DIR / "personal"
IMPERSONAL_DIR = DATA_DIR / "impersonal"

# --- personal: what the user holds and what it's worth, never committed ---
TRANSACTIONS_FILE = PERSONAL_DIR / "transactions.csv"
TRANSACTIONS_BACKUP_FILE = PERSONAL_DIR / "transactions.csv.bak"
TRANSACTION_LOTS_FILE = PERSONAL_DIR / "transaction_lots.csv"
# enriched_lots.csv is the join of transaction_lots.csv + ticker_map.csv +
# company_overrides.csv.  It is the file every downstream module reads; only
# lots.py (FIFO engine) and tickers.py (detects blank-Ticker ISINs) read the
# raw transaction_lots.csv directly.
ENRICHED_LOTS_FILE = PERSONAL_DIR / "enriched_lots.csv"
ANALYSIS_HISTORY_FILE = PERSONAL_DIR / "analysis_history.jsonl"
REPORTS_DIR = PERSONAL_DIR / "daily-analysis"
# Portfolio role per holding (Core Compounder / Growth / Opportunistic / Defensive).
# Personal, not impersonal: a role describes how a position functions in *this*
# portfolio, not a fact about the security - the same ETF is Growth for one holder
# and Defensive for another.
ROLES_FILE = PERSONAL_DIR / "roles.csv"

# --- impersonal: facts about securities, true for everyone, committed ---
TICKER_MAP_FILE = IMPERSONAL_DIR / "ticker_map.csv"
COMPANY_OVERRIDES_FILE = IMPERSONAL_DIR / "company_overrides.csv"
# Fee schedule rules: PRIME ETF issuer list, hedge ISIN list, any other
# hand-maintained exceptions to the programmatic fee logic.  Committed
# (impersonal) because it describes the broker's public fee structure, not
# anything personal about the user's holdings.
FEE_RULES_FILE = IMPERSONAL_DIR / "fee_rules.json"
PRICE_HISTORY_DIR = IMPERSONAL_DIR / "price_history"
NEWS_DIR = IMPERSONAL_DIR / "news"

LOCK_FILE = DATA_DIR / ".pipeline.lock"
