"""Breakable demo target: a mock storefront with three structural eras.

* ``v1`` — the era the seed spec was written for.
* ``v2`` — a full front-end redesign: renamed classes, restructured cards,
  decoy sale badges. Breaks every v1 selector.
* ``v3`` — a second redesign (utility-class soup), proving repeat healing.

The "chaos button" in the dashboard cycles variants — the live-demo
equivalent of a production site shipping a redesign while you sleep.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import registry

_VARIANT_KEY = "demo_variant"


def demo_dir() -> Path:
    override = os.environ.get("REWEAVE_DEMO_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "demo"


def variants() -> list[str]:
    return sorted(
        p.name.removeprefix("site_")
        for p in demo_dir().glob("site_*")
        if (p / "index.html").exists()
    )


def current_variant() -> str:
    return registry.kv_get(_VARIANT_KEY, "v1") or "v1"


def set_variant(variant: str) -> str:
    if variant not in variants():
        raise ValueError(f"unknown demo variant {variant!r}; have {variants()}")
    registry.kv_set(_VARIANT_KEY, variant)
    return variant


def break_site() -> str:
    """Advance to the next structural era (wraps around past the last one)."""
    vs = variants()
    cur = current_variant()
    nxt = vs[(vs.index(cur) + 1) % len(vs)] if cur in vs else vs[0]
    return set_variant(nxt)


def reset() -> str:
    return set_variant("v1")


def current_html() -> str:
    return (demo_dir() / f"site_{current_variant()}" / "index.html").read_text(
        encoding="utf-8"
    )
