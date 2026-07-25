#!/usr/bin/env python3
"""Accepts an uploaded transactions.csv (as raw text, e.g. from the
upload_transactions MCP tool) and saves it to data/manual/transactions.csv -
the one file in this pipeline with no automated source. Delivered via the
server's upload tool rather than the user placing a file directly at that
path, since there's no guaranteed shared filesystem between whoever is
talking to this server and wherever it happens to be running. Full pipeline
rationale: see AGENT_NOTES.md.
"""

from ..paths import MANUAL_DIR

TRANSACTIONS_FILE = MANUAL_DIR / "transactions.csv"
BACKUP_FILE = MANUAL_DIR / "transactions.csv.bak"

# Scalable Capital's export format - see AGENT_NOTES.md / lots.py's load_transactions().
EXPECTED_HEADER_COLUMNS = (
    "date", "time", "status", "reference", "description", "assetType",
    "type", "isin", "shares", "price", "amount", "fee", "tax", "currency",
)

def save(csv_content: str) -> str:
    """Validate + persist an uploaded transactions export. Always a full
    re-export (not incremental) - overwrites whatever was there before,
    keeping one backup. Returns a human-readable status message."""
    stripped = csv_content.strip()
    header = stripped.splitlines()[0] if stripped else ""
    header_columns = [c.strip() for c in header.split(";")]

    if header_columns != list(EXPECTED_HEADER_COLUMNS):
        return (
            "REJECTED - this doesn't look like a Scalable Capital transaction export.\n"
            f"Expected header: {';'.join(EXPECTED_HEADER_COLUMNS)}\n"
            f"Got: {header or '(empty)'}\n"
            "If you're on a different broker, this format isn't supported yet - "
            "see pipeline/lots.py's load_transactions() to adapt it."
        )

    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    backed_up = False
    if TRANSACTIONS_FILE.exists():
        BACKUP_FILE.write_text(TRANSACTIONS_FILE.read_text())
        backed_up = True

    TRANSACTIONS_FILE.write_text(csv_content)
    row_count = len(stripped.splitlines()) - 1  # minus header
    backup_note = f" (previous version backed up to {BACKUP_FILE.name})" if backed_up else ""
    return (
        f"Saved {row_count} transaction row(s) to {TRANSACTIONS_FILE}{backup_note}. "
        "Next: call compute_lots to rebuild positions from it."
    )
