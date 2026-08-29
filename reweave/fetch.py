"""Page acquisition with provenance.

Resolution order per URL scheme:

* ``demo://``   — the built-in breakable target site (used by tests and the live demo)
* ``file://``   — local fixtures
* ``http(s)://`` — Bright Data Web Unlocker when ``BRIGHTDATA_API_KEY`` is set
  (hostile-web fetching: proxy rotation, JS rendering, CAPTCHA solving handled
  upstream), otherwise a plain httpx GET.

Every fetch returns ``(html, provenance)`` so the UI and audit log can show
exactly which channel produced the bytes the agent acted on.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

BRIGHTDATA_ENDPOINT = "https://api.brightdata.com/request"
USER_AGENT = "reweave/0.1 (+https://github.com/vnmoorthy/reweave)"


def fetch(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """Return (html, provenance) for a URL."""
    if url.startswith("demo://"):
        from . import demo

        return demo.current_html(), f"demo:{demo.current_variant()}"

    if url.startswith("file://"):
        return Path(url[len("file://"):]).read_text(encoding="utf-8"), "file"

    api_key = os.environ.get("BRIGHTDATA_API_KEY")
    zone = os.environ.get("BRIGHTDATA_ZONE", "web_unlocker1")
    if api_key:
        resp = httpx.post(
            BRIGHTDATA_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"zone": zone, "url": url, "format": "raw"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text, f"brightdata:{zone}"

    resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text, "direct"
