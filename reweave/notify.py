"""Outbound webhooks: push lifecycle events to the systems teams live in.

Set ``REWEAVE_WEBHOOK_URL`` and every significant state transition is POSTed
as JSON (``{"event", "source_id", "ts", "data"}``). Works as-is with Slack's
incoming webhooks (a ``text`` field is included), PagerDuty events relays, or
any internal collector.

Delivery is strictly best-effort by design: a slow or dead webhook endpoint
must never stall or fail a pipeline run, so failures are swallowed after
being recorded to the event log.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

EVENTS = (
    "drift_detected",
    "heal_pending",
    "heal_escalated",
    "heal_approved",
    "heal_rejected",
    "rollback",
)

_TIMEOUT = 4.0


def webhook_url() -> str | None:
    return os.environ.get("REWEAVE_WEBHOOK_URL") or None


def emit(event: str, source_id: str, data: dict[str, Any] | None = None) -> bool:
    """POST one event to the configured webhook. Returns True on 2xx."""
    url = webhook_url()
    if not url:
        return False
    payload = {
        "event": event,
        "source_id": source_id,
        "ts": time.time(),
        "data": data or {},
        "text": f"reweave: {event} on {source_id}"
        + (f" — {data.get('summary')}" if data and data.get("summary") else ""),
    }
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
        return 200 <= resp.status_code < 300
    except Exception:
        from . import registry

        registry.log_event(source_id, "system", f"webhook delivery failed for {event}")
        return False
