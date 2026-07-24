#!/usr/bin/env python3
"""CLI entry point - the real rendering logic lives in pipeline/report.py; see
AGENT_NOTES.md. Reads analyze_portfolio.py's JSON from stdin or a file path
argument, prints markdown to stdout.

Usage: python3 analyze_portfolio.py | python3 render_report.py
"""
import json
import sys

from pipeline.config import load_config
from pipeline.report import render

def main():
    raw = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    data = json.load(raw)
    return render(data, load_config())

if __name__ == "__main__":
    print(main())
