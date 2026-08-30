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
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import __version__, demo, impact, notify, pipeline, registry, watch
from .fetch import fetch
from .models import ExtractionSpec, FieldSpec
from .surgeon import bootstrap_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"
STARTED_AT = time.time()

# Paths that stay open when REWEAVE_API_TOKEN is set: the dashboard itself,
# the demo target, health for load balancers, and metrics for scrapers.
_AUTH_EXEMPT = ("/", "/demo-site", "/api/health", "/metrics")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    seed()
    if os.environ.get("REWEAVE_AUTOPILOT", "").lower() in ("1", "true", "on"):
        watch.start()
    yield


app = FastAPI(title="reweave", version=__version__, lifespan=_lifespan)


@app.middleware("http")
async def _bearer_auth(request: Request, call_next):
    """Optional API protection: set REWEAVE_API_TOKEN to require
    `Authorization: Bearer <token>` on every /api/ route (health exempt)."""
    token = os.environ.get("REWEAVE_API_TOKEN")
    if (
        token
        and request.url.path.startswith("/api/")
        and request.url.path not in _AUTH_EXEMPT
        and request.headers.get("authorization") != f"Bearer {token}"
    ):
        return JSONResponse({"detail": "missing or invalid bearer token"}, status_code=401)
    return await call_next(request)


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


@app.post("/api/sources/{source_id}/rollback")
def rollback(source_id: str, payload: dict = Body(default={})) -> JSONResponse:
    """Move the active spec pointer to a historical version.

    Immutable versions make this a pointer move (ADR-0003) — but it is still
    a production change, so it demands an accountable actor and lands in the
    audit ledger and webhook stream like any deploy.
    """
    actor = (payload.get("actor") or "").strip()
    if not actor:
        raise HTTPException(422, "rollback requires an accountable actor")
    src = registry.get_source(source_id)
    if src is None:
        raise HTTPException(404, f"unknown source {source_id}")
    current = src["active_version"]
    to_version = payload.get("to_version") or current - 1
    if to_version == current:
        raise HTTPException(409, f"spec v{to_version} is already active")
    try:
        registry.activate_version(source_id, int(to_version))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    registry.log_event(
        source_id, "deploy", f"{actor} rolled back spec v{current} → v{to_version}"
    )
    notify.emit(
        "rollback", source_id, {"summary": f"v{current} → v{to_version} by {actor}"}
    )
    return JSONResponse({"source_id": source_id, "active_version": int(to_version)})


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "uptime_s": round(time.time() - STARTED_AT, 1),
            "sources": len(registry.list_sources()),
            "autopilot": watch.enabled(),
        }
    )


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Prometheus exposition format, dependency-free."""
    counters = registry.ops_counters()
    gauges = {"pending_heals", "open_incidents"} | {
        k for k in counters if k.startswith("sources_")
    }
    lines = [
        "# HELP reweave_up 1 if the control plane is serving.",
        "# TYPE reweave_up gauge",
        "reweave_up 1",
        f"reweave_uptime_seconds {round(time.time() - STARTED_AT, 1)}",
    ]
    for key, value in sorted(counters.items()):
        kind = "gauge" if key in gauges else "counter"
        lines.append(f"# TYPE reweave_{key} {kind}")
        lines.append(f"reweave_{key} {value}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


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
