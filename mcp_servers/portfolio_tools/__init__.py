"""The portfolio MCP server: a self-contained package (server + pipeline + its
own data directory). Deliberately named `portfolio_mcp`, not `mcp`, so it
never collides with the third-party `mcp` SDK package this server imports
(`from mcp.server.fastmcp import FastMCP`) - a same-named local package would
shadow or be shadowed by that import depending on sys.path order.
"""
