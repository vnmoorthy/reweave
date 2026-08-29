"""Harness integrations.

Reweave's core is harness-agnostic; :mod:`reweave.harness.mcp_server` exposes
the whole healing lifecycle as MCP tools so any MCP-speaking agent harness —
TrueForge first among them — can drive it, with the harness's own
human-approval gate layered in front of the destructive tools.
"""
