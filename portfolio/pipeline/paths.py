"""Single source of truth for this package's filesystem layout.

Every other module imports PORTFOLIO_DIR/DATA_DIR from here instead of each
recomputing Path(__file__).parent.parent independently - see AGENT_NOTES.md
rule 8 on keeping one copy of anything in sync, applied to path constants too.
"""

from pathlib import Path

PORTFOLIO_DIR = Path(__file__).resolve().parent.parent  # portfolio/ - one level above this package
DATA_DIR = PORTFOLIO_DIR / "data"
