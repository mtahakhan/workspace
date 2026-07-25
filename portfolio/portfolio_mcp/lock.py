"""Cross-request, cross-process serialization for this package's data files.

The server is deployed over HTTP as one long-running process that can receive
concurrent tool calls (from multiple Claude Code sessions/projects, since
it's registered globally, not spawned fresh per session like a stdio server
would be). None of the read-modify-write sequences in pipeline/ (e.g.
compute_lots reading transaction_lots.csv + ticker_map.csv then rewriting the
former, resolve_tickers appending to ticker_map.csv) are safe under
concurrent access on their own. server.py wraps every tool call in DATA_LOCK
so only one tool call actually touches the data directory at a time - simpler
and more bulletproof than per-file locks, which would still leave gaps
between related files (e.g. compute_lots touches both ticker_map.csv and
transaction_lots.csv; a lock on just one of them wouldn't prevent
resolve_tickers racing on the other mid-computation).

fcntl.flock is used rather than a plain threading.Lock because it also
correctly serializes across separate processes (e.g. if the server is ever
accidentally started twice) - on Linux/macOS, flock() blocks a second
LOCK_EX request on the same file even from a different open() call in the
same process, so this covers both the intra-process (concurrent HTTP
requests) and inter-process case with one mechanism.
"""

import contextlib
import fcntl
from pathlib import Path


@contextlib.contextmanager
def locked(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
