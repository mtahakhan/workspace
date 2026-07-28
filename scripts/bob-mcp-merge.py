#!/usr/bin/env python3
"""Merge a single MCP server entry into ~/.bob/settings/mcp.json safely.

Usage: bob-mcp-merge.py <mcp_file> <server_name> <server_url>
"""
import json
import sys

mcp_file, server_name, server_url = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    with open(mcp_file) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

cfg.setdefault("mcpServers", {})
cfg["mcpServers"][server_name] = {"url": server_url}

with open(mcp_file, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
