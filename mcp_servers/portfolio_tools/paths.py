"""Single source of truth for this package's filesystem layout.

Every path here is derived from PACKAGE_ROOT (this package's own location on
disk), never from the current working directory or from any notion of "the
current project" - this server is registered globally and invoked over HTTP,
so there is no meaningful project context to resolve paths against. It always
operates on the same data, regardless of which Claude Code session or project
is talking to it. See AGENT_NOTES.md rule 8 on keeping one copy of anything
(here: path constants) in sync - every other module imports from here.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent   # portfolio_mcp/
DATA_DIR = PACKAGE_ROOT / "data"
MANUAL_DIR = DATA_DIR / "manual"
CONFIG_FILE = PACKAGE_ROOT / "config.json"
ENV_FILE = PACKAGE_ROOT / ".env"
