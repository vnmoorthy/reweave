"""Autopilot: continuous monitoring of every registered source.

A daemon thread runs each source through the pipeline loop on an interval.
The gate semantics are unchanged — autopilot can *detect* and *propose*
around the clock, but deploys still wait for a human. Toggle at runtime via
the ``autopilot`` registry key (the dashboard switch), interval via
``REWEAVE_WATCH_INTERVAL`` seconds.
"""

from __future__ import annotations

import os
import threading
import time

from . import registry
from .pipeline import run_source

DEFAULT_INTERVAL = 60.0
_started = threading.Event()


def enabled() -> bool:
    return registry.kv_get("autopilot", "1") == "1"


def set_enabled(on: bool) -> None:
    registry.kv_set("autopilot", "1" if on else "0")
    registry.log_event(
        "-", "system", f"autopilot {'engaged' if on else 'paused'} by operator"
    )


def interval() -> float:
    try:
        return max(5.0, float(os.environ.get("REWEAVE_WATCH_INTERVAL", DEFAULT_INTERVAL)))
    except ValueError:
        return DEFAULT_INTERVAL


def _loop() -> None:
    while True:
        time.sleep(interval())
        if not enabled():
            continue
        for src in registry.list_sources():
            try:
                run_source(src["id"])
            except Exception as e:  # keep the watch alive no matter what
                registry.log_event(src["id"], "escalate", f"autopilot run failed: {e}")


def start() -> bool:
    """Start the watcher thread once per process. Returns True if started."""
    if _started.is_set():
        return False
    _started.set()
    threading.Thread(target=_loop, name="reweave-autopilot", daemon=True).start()
    return True
