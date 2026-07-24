#!/usr/bin/env python3
"""CLI entry point - the real logic lives in pipeline/analysis.py; see AGENT_NOTES.md."""
import json

from pipeline.analysis import main

if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
