"""Deterministic extraction engine.

Applies a versioned :class:`~reweave.models.ExtractionSpec` to raw HTML.
The engine is intentionally dumb: all intelligence lives in the Surgeon,
which *produces* specs. Keeping execution deterministic is what makes a
repair reviewable — the diff between two specs fully describes the change
in behavior.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import ExtractionSpec

_WS = re.compile(r"\s+")


def norm_text(s: str | None) -> str | None:
    if s is None:
        return None
    out = _WS.sub(" ", s).strip()
    return out or None


def parse_price(text: str | None) -> float | None:
    """Parse '$1,299.00', '1.299,00 €', 'USD 12.99' … into a float."""
    if not text:
        return None
    t = re.sub(r"[^\d.,]", "", text)
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        if re.search(r",\d{1,2}$", t) and t.count(",") == 1:
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def coerce(raw: str | None, kind: str, base_url: str = "") -> Any:
    if kind == "price":
        return parse_price(raw)
    if kind == "url":
        raw = norm_text(raw)
        return urljoin(base_url, raw) if raw else None
    return norm_text(raw)


def read_field(item: Tag, selector: str, attr: str | None) -> str | None:
    try:
        node = item.select_one(selector) if selector not in (".", ":self") else item
    except Exception:
        return None
    if node is None:
        return None
    if attr:
        val = node.get(attr)
        if isinstance(val, list):
            val = " ".join(val)
        return val
    return node.get_text(" ", strip=True)


def extract(html: str, spec: ExtractionSpec, base_url: str = "") -> list[dict[str, Any]]:
    """Return one row per item container. Missing fields become ``None``."""
    soup = BeautifulSoup(html, "lxml")
    try:
        items = soup.select(spec.item_selector)
    except Exception:
        items = []
    rows: list[dict[str, Any]] = []
    for item in items:
        row: dict[str, Any] = {}
        for f in spec.fields:
            raw = read_field(item, f.selector, f.attr)
            row[f.name] = coerce(raw, f.kind, base_url)
        # A container where literally nothing extracted is layout chrome, not an item.
        if any(v is not None for v in row.values()):
            rows.append(row)
    return rows
