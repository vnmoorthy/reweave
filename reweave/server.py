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

import csv
import io
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import demo, impact, pipeline, registry, watch
from .fetch import fetch
from .models import ExtractionSpec, FieldSpec
from .surgeon import bootstrap_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"


@asynccontextmanager
async def _lifespan(_: FastAPI):
    seed()
    if os.environ.get("REWEAVE_AUTOPILOT", "").lower() in ("1", "true", "on"):
        watch.start()
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
    sources = registry.list_sources()
    for s in sources:
        run = registry.latest_run(s["id"])
        s["latest_run"] = (
            {k: run[k] for k in ("ts", "row_count", "healthy", "confidence", "provenance")}
            if run
            else None
        )
    return JSONResponse(
        {
            "sources": sources,
            "incidents": registry.list_incidents()[:20],
            "pending": registry.pending_proposals(),
            "events": registry.recent_events(80),
            "impact": registry.impact_totals(),
            "fleet_projection": impact.fleet_projection(n_scrapers=max(50, len(sources))),
            "demo_variant": demo.current_variant(),
            "autopilot": {"enabled": watch.enabled(), "interval_s": watch.interval()},
        }
    )


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "source"
    if registry.get_source(slug):
        n = 2
        while registry.get_source(f"{slug}-{n}"):
            n += 1
        slug = f"{slug}-{n}"
    return slug


@app.post("/api/sources", status_code=201)
def add_source(payload: dict = Body(...)) -> JSONResponse:
    """Register a new source with ZERO selectors: golden examples in, spec out.

    Body: {"url": ..., "name"?: ..., "golden": [{...}, {...}, ...]}
    The Surgeon bootstraps the extraction spec from the golden examples using
    the same record-anchored synthesis it uses to heal.
    """
    url = (payload.get("url") or "").strip()
    golden = payload.get("golden") or []
    if not url:
        raise HTTPException(422, "url is required")
    if not isinstance(golden, list) or len(golden) < 2:
        raise HTTPException(422, "at least 2 golden example records are required")

    try:
        html, provenance = fetch(url)
    except Exception as e:
        raise HTTPException(422, f"could not fetch {url}: {e}") from e

    proposal = bootstrap_spec(html, golden, "bootstrap", base_url=url)
    if proposal is None:
        raise HTTPException(
            422,
            "could not anchor the golden examples on that page — check the values "
            "match what is visible (titles verbatim, prices as numbers)",
        )

    name = (payload.get("name") or "").strip() or url
    source_id = _slugify(payload.get("name") or url.split("//")[-1].split("/")[0])
    registry.upsert_source(source_id, name, url, golden, proposal.new_spec)
    registry.log_event(
        source_id,
        "deploy",
        f"source onboarded via {provenance}: spec v1 bootstrapped from "
        f"{len(golden)} golden examples ({len(proposal.new_spec.fields)} fields, "
        f"validation confidence {proposal.validation.confidence:.0%}) — no selectors written",
    )
    result = pipeline.run_source(source_id)
    return JSONResponse(
        {"source_id": source_id, "report": result["report"], "spec": proposal.new_spec.to_dict()},
        status_code=201,
    )


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str) -> JSONResponse:
    if registry.get_source(source_id) is None:
        raise HTTPException(404, f"unknown source {source_id}")
    registry.remove_source(source_id)
    registry.log_event(source_id, "system", "source removed by operator")
    return JSONResponse({"ok": True})


@app.get("/api/sources/{source_id}/rows")
def source_rows(source_id: str, fmt: str = "json"):
    run = registry.latest_run(source_id)
    if run is None:
        raise HTTPException(404, f"no runs recorded for {source_id}")
    if fmt == "csv":
        buf = io.StringIO()
        fieldnames = list(run["rows"][0].keys()) if run["rows"] else []
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(run["rows"])
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{source_id}.csv"'},
        )
    return JSONResponse(
        {k: run[k] for k in ("ts", "row_count", "healthy", "confidence", "provenance", "rows")}
    )


@app.get("/api/sources/{source_id}/history")
def source_history(source_id: str) -> JSONResponse:
    return JSONResponse(registry.run_history(source_id))


@app.post("/api/autopilot")
def toggle_autopilot(payload: dict = Body(default={})) -> JSONResponse:
    watch.set_enabled(bool(payload.get("enabled")))
    return JSONResponse({"enabled": watch.enabled()})


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
