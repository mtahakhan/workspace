#!/usr/bin/env python3
"""Loads config.json - the pipeline's thresholds and caveat/notification
message templates, kept in one committed file (shared/non-personal, like
ticker_map.csv) so they can be tuned without editing code. Deliberately no
Python-side default values duplicating config.json's content: AGENT_NOTES.md's
"exactly one X to keep in sync" principle applies here too - a missing/broken
config.json is a real problem to report and stop on, not something to paper
over with a second, silently-drifting copy of the same values.
"""

import json

from ..paths import CONFIG_FILE

def load_config():
    if not CONFIG_FILE.exists():
        raise SystemExit(
            f"{CONFIG_FILE} is missing - it's a committed file (like ticker_map.csv), "
            "not personal data. Restore it from git rather than recreating it by hand."
        )
    try:
        return json.loads(CONFIG_FILE.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"{CONFIG_FILE} is invalid JSON: {e}")
