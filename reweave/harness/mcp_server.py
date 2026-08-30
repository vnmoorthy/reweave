"""Reweave as an MCP server (stdio transport, JSON-RPC 2.0).

A dependency-free implementation of the Model Context Protocol surface that
an agent harness needs: ``initialize``, ``tools/list``, ``tools/call``.

Tool annotations follow the MCP spec: ``approve_heal`` and ``reject_heal``
are marked ``destructiveHint`` so a conforming harness (TrueForge's approval
gate, Claude Code's permission prompt, …) interposes a human before they
execute. That layering is deliberate: even if the harness-level gate is
bypassed, Reweave's own :class:`~reweave.gates.ApprovalGate` still demands an
accountable actor — defense in depth for agentic writes.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .. import __version__, demo, impact, registry
from ..pipeline import gate, run_source

PROTOCOL_VERSION = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_sources",
        "description": "List every monitored source with health status and active spec version.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "run_pipeline",
        "description": (
            "Run one observe/extract/assess cycle for a source. If structural drift is "
            "detected, the Surgeon synthesizes a validated repair and parks it at the "
            "approval gate. Never deploys anything by itself."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"source_id": {"type": "string"}},
            "required": ["source_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "list_pending_heals",
        "description": "List repair proposals awaiting human approval, with full diffs and validation evidence.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "approve_heal",
        "description": (
            "DEPLOY a pending repair: activates the new extraction spec version. "
            "Irreversible in effect — requires an accountable human actor."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "actor": {"type": "string", "description": "Human accountable for this deploy"},
            },
            "required": ["proposal_id", "actor"],
        },
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "reject_heal",
        "description": "Reject a pending repair proposal with an optional reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "actor": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["proposal_id", "actor"],
        },
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "add_source",
        "description": (
            "Onboard a new source with ZERO selectors: provide a url and 2+ golden "
            "example records visible on the page; the Surgeon synthesizes and "
            "validates the extraction spec from the examples."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "name": {"type": "string"},
                "golden": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["url", "golden"],
        },
        "annotations": {"destructiveHint": False},
    },
    {
        "name": "get_rows",
        "description": "The latest extracted rows for a source (the actual data).",
        "inputSchema": {
            "type": "object",
            "properties": {"source_id": {"type": "string"}},
            "required": ["source_id"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "impact_report",
        "description": "Totals of approved heals and the engineer-time/dollar impact ledger.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "chaos_break_demo",
        "description": "Demo only: ship a structural redesign to the built-in target site.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"destructiveHint": False},
    },
]


def _call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "list_sources":
        return registry.list_sources()
    if name == "run_pipeline":
        out = run_source(args["source_id"])
        out.pop("rows", None)  # keep tool results compact for the model
        return out
    if name == "list_pending_heals":
        return registry.pending_proposals()
    if name == "approve_heal":
        return gate.approve(args["proposal_id"], args["actor"])
    if name == "reject_heal":
        return gate.reject(args["proposal_id"], args["actor"], args.get("reason", ""))
    if name == "add_source":
        from .. import server

        payload = {"url": args["url"], "name": args.get("name", ""), "golden": args["golden"]}
        resp = server.add_source(payload)
        return json.loads(bytes(resp.body))
    if name == "get_rows":
        run = registry.latest_run(args["source_id"])
        if run is None:
            raise KeyError(f"no runs recorded for {args['source_id']}")
        return run
    if name == "impact_report":
        return {
            "totals": registry.impact_totals(),
            "fleet_projection_50_scrapers": impact.fleet_projection(50),
        }
    if name == "chaos_break_demo":
        return {"demo_variant": demo.break_site()}
    raise KeyError(f"unknown tool {name}")


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "reweave", "version": __version__},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        try:
            result = _call_tool(params.get("name", ""), params.get("arguments", {}) or {})
            content = [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": content, "isError": False}}
        except Exception as e:  # tool errors are results, not protocol failures
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                    "isError": True,
                },
            }
    if mid is not None:
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return None


def serve_stdio() -> None:
    from .. import server

    server.seed()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
