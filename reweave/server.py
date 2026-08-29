"""FastAPI control plane: the dashboard, the JSON API, and the demo target.

Endpoints
---------
* ``GET  /``                      — mission-control dashboard
* ``GET  /demo-site``             — the breakable storefront (current era)
* ``GET  /api/state``             — full system state for the UI
* ``POST /api/run/{source_id}``   — trigger one pipeline cycle
* ``POST /api/chaos``             — ship a "redesign" to the demo site
* ``POST /api/heal/{pid}/approve``— human approves a repair (audit-logged)
* ``POST /api/heal/{pid}/reject`` — human rejects a repair
* ``POST /api/reset``             — restore the demo to its initial state
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from . import demo, impact, pipeline, registry
from .models import ExtractionSpec, FieldSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"


@asynccontextmanager
async def _lifespan(_: FastAPI):
    seed()
    yield


app = FastAPI(title="reweave", version="0.1.0", lifespan=_lifespan)


def seed() -> None:
    """Idempotently register the demo source with its v1 (seed-era) spec."""
    golden = json.loads((demo.demo_dir() / "golden.json").read_text(encoding="utf-8"))
    spec = ExtractionSpec(
        item_selector="div.product-card",
        fields=[
            FieldSpec("title", "h3.product-name", None, "text"),
            FieldSpec("price", "span.price-tag", None, "price"),
            FieldSpec("url", "a.product-link", "href", "url"),
        ],
        version=1,
        origin="seed",
    )
    registry.upsert_source(
        "nimbusmart", "NimbusMart · competitor pricing", "demo://nimbusmart", golden, spec
    )


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


@app.get("/demo-site", response_class=HTMLResponse)
def demo_site() -> str:
    return demo.current_html()


@app.get("/api/state")
def state() -> JSONResponse:
    return JSONResponse(
        {
            "sources": registry.list_sources(),
            "incidents": registry.list_incidents()[:20],
            "pending": registry.pending_proposals(),
            "events": registry.recent_events(80),
            "impact": registry.impact_totals(),
            "fleet_projection": impact.fleet_projection(n_scrapers=50),
            "demo_variant": demo.current_variant(),
        }
    )


@app.post("/api/run/{source_id}")
def run(source_id: str) -> JSONResponse:
    try:
        return JSONResponse(pipeline.run_source(source_id))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/chaos")
def chaos() -> JSONResponse:
    variant = demo.break_site()
    registry.log_event(
        "nimbusmart", "chaos", f"target site shipped a redesign (now structural era {variant})"
    )
    return JSONResponse({"demo_variant": variant})


@app.post("/api/heal/{pid}/approve")
def approve(pid: str, payload: dict = Body(default={})) -> JSONResponse:
    actor = (payload.get("actor") or "operator").strip() or "operator"
    try:
        return JSONResponse(pipeline.gate.approve(pid, actor))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, PermissionError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/heal/{pid}/reject")
def reject(pid: str, payload: dict = Body(default={})) -> JSONResponse:
    actor = (payload.get("actor") or "operator").strip() or "operator"
    try:
        return JSONResponse(
            pipeline.gate.reject(pid, actor, payload.get("reason", ""))
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, PermissionError) as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/reset")
def reset_demo() -> JSONResponse:
    registry.reset()
    demo.reset()
    seed()
    registry.log_event("nimbusmart", "system", "demo reset to initial state")
    return JSONResponse({"ok": True})
