# Reweave API reference

Complete reference for every surface Reweave exposes: the REST API, the MCP
server, the CLI, the Python modules, environment variables, and the data
model. Everything here is derived from the source in `reweave/` — error
messages and response shapes are quoted verbatim from the code.

Contents:

1. [REST API](#1-rest-api)
2. [MCP tools](#2-mcp-tools)
3. [CLI](#3-cli)
4. [Python API](#4-python-api)
5. [Environment variables](#5-environment-variables)
6. [Data model](#6-data-model)

---

## 1. REST API

Served by `reweave serve` (FastAPI app in `reweave/server.py`), default
`http://127.0.0.1:8321`. All request and response bodies are JSON unless
noted. Error responses are FastAPI-standard: `{"detail": "<message>"}` with
the status codes listed per endpoint.

### Authentication

Off by default. Set `REWEAVE_API_TOKEN` and every route whose path starts
with `/api/` requires:

```
Authorization: Bearer <token>
```

A missing or wrong token returns `401 {"detail": "missing or invalid bearer
token"}`. Exempt even with a token set: `/` (dashboard), `/demo-site`,
`/api/health` (load balancers), and `/metrics` (Prometheus scrapers). Note
that only `/api/*` paths are ever checked, so `/`, `/demo-site`, and
`/metrics` are open by construction.

### `GET /`

The mission-control dashboard (`dashboard/index.html`) as `text/html`.

### `GET /demo-site`

The built-in breakable storefront, rendered at its current structural era
(`v1`/`v2`/`v3`), as `text/html`.

### `GET /api/state`

Full system state for the UI. Response:

```json
{
  "sources": [
    {
      "id": "nimbusmart", "name": "…", "url": "demo://nimbusmart",
      "status": "healthy | broken | unknown",
      "golden": [{...}], "active_version": 2, "last_checked": 1700000000.0,
      "latest_run": {"ts": ..., "row_count": ..., "healthy": ...,
                     "confidence": ..., "provenance": "..."}
    }
  ],
  "incidents": [ ...first 20, newest first... ],
  "pending":   [ ...pending HealProposal objects... ],
  "events":    [ ...80 most recent event rows... ],
  "impact":    {"heals": 0, "engineer_minutes_saved": 0.0, "dollars_saved": 0.0},
  "fleet_projection": {"expected_breaks_per_year": ..., "engineer_hours_per_year": ..., "dollars_per_year": ...},
  "demo_variant": "v1",
  "autopilot": {"enabled": true, "interval_s": 60.0}
}
```

`latest_run` is `null` for a source with no recorded runs. `fleet_projection`
is computed for `max(50, number_of_sources)` scrapers.

### `POST /api/sources` — onboard a source

Register a new source with zero selectors: golden examples in, validated
spec out (the Surgeon bootstraps the spec with the same record-anchored
synthesis it uses to heal).

Body:

```json
{"url": "https://…", "name": "optional display name",
 "golden": [{"title": "…", "price": 12.99, "url": "…"}, {…}]}
```

At least 2 golden records are required. The source id is a slug of `name`
(or the URL host if no name), deduplicated with a `-2`, `-3`, … suffix if
the slug is taken. A first pipeline run is executed immediately.

Response `201`:

```json
{"source_id": "…", "report": {DriftReport}, "spec": {ExtractionSpec}}
```

Errors (all `422`):

* `"url is required"`
* `"at least 2 golden example records are required"`
* `"could not fetch {url}: {error}"`
* `"could not anchor the golden examples on that page — check the values match what is visible (titles verbatim, prices as numbers)"`

### `DELETE /api/sources/{source_id}`

Remove a source and all of its specs, proposals, incidents, and runs.
Response: `{"ok": true}`. Error `404`: `"unknown source {source_id}"`.

### `GET /api/sources/{source_id}/rows`

Latest extracted rows. Query parameter `fmt`: `json` (default) or `csv`.

* `fmt=json` →
  `{"ts": ..., "row_count": ..., "healthy": ..., "confidence": ..., "provenance": "...", "rows": [{...}]}`
* `fmt=csv` → `text/csv` with header row and
  `Content-Disposition: attachment; filename="{source_id}.csv"`

Error `404`: `"no runs recorded for {source_id}"`.

### `GET /api/sources/{source_id}/history`

Up to 20 most recent run summaries, newest first:

```json
[{"id": "run_…", "ts": ..., "row_count": ..., "healthy": true,
  "confidence": ..., "provenance": "demo:v1"}]
```

An unknown source returns `[]` (no 404).

### `POST /api/autopilot`

Toggle continuous background monitoring at runtime (the dashboard switch).
Body: `{"enabled": true}` — any missing or falsy value disables. The toggle
is persisted in the registry (`kv` key `autopilot`), so it survives
restarts. Response: `{"enabled": true}`.

### `POST /api/sources/{source_id}/rollback`

Move the active spec pointer to a historical version. Because spec versions
are immutable, rollback is a pointer move — but it is still a production
change, so it demands an accountable actor and lands in the audit log and
webhook stream like any deploy.

Body: `{"to_version": 1, "actor": "who"}`. `actor` is required.
`to_version` is optional and defaults to `current_version - 1` (passing `0`
or `null` also falls back to the default).

Response: `{"source_id": "…", "active_version": 1}`.

Side effects: a `deploy` event (`"{actor} rolled back spec v{from} → v{to}"`)
and a `rollback` webhook. Rollback does not change the source's health
status or its incidents — the next pipeline run re-assesses against the
reactivated spec.

Errors:

* `422` — `"rollback requires an accountable actor"`
* `404` — `"unknown source {source_id}"`
* `404` — `"source {source_id} has no spec v{version}"`
* `409` — `"spec v{version} is already active"`

### `GET /api/health`

Liveness/readiness probe. Never requires auth. Response:

```json
{"status": "ok", "version": "0.2.0", "uptime_s": 12.3,
 "sources": 1, "autopilot": true}
```

### `GET /metrics`

Prometheus exposition format (`text/plain; version=0.0.4`), dependency-free.
Never requires auth. Emits:

| Metric | Type |
| --- | --- |
| `reweave_up` | gauge (constant `1` while serving) |
| `reweave_uptime_seconds` | (no TYPE line emitted) |
| `reweave_runs_total` | counter |
| `reweave_drift_detected_total` | counter |
| `reweave_heals_deployed_total` | counter |
| `reweave_engineer_minutes_saved_total` | counter |
| `reweave_dollars_saved_total` | counter |
| `reweave_pending_heals` | gauge |
| `reweave_open_incidents` | gauge |
| `reweave_sources_<status>` | gauge, one per source status (`healthy`, `broken`, `unknown`) |

Values are aggregated from the SQLite registry on each scrape (cheap `COUNT`
queries; no in-process state).

### `POST /api/run/{source_id}`

Trigger one pipeline cycle (fetch → extract → assess → heal → gate).
Response is the full pipeline result:

```json
{"report": {DriftReport}, "rows": [{...}], "provenance": "demo:v2",
 "spec_version": 1, "proposal": {HealProposal} | null}
```

`proposal` is non-null when drift was detected and a repair is pending
(either newly synthesized this run or already awaiting approval).

Error `404`: `"unknown source {source_id}"`. A source that exists but has no
active spec raises an unhandled `RuntimeError` (HTTP 500).

### `POST /api/chaos`

Demo only: advance the built-in storefront to its next structural era
(wraps around). Response: `{"demo_variant": "v2"}`.

### `POST /api/heal/{pid}/approve`

Deploy a pending repair: activates the proposal's new spec version, closes
the source's open incidents, marks it healthy, books the impact ledger
entry, and emits a `heal_approved` webhook.

Body: `{"actor": "who"}` — defaults to `"operator"` if omitted or blank.
Response: the full proposal object with `"status": "approved"` and
`resolved_at`/`resolved_by` set.

Errors:

* `404` — `"unknown proposal {pid}"`
* `409` — `"proposal {pid} already {approved|rejected}"`
* `409` — `"approval requires an accountable actor"`

### `POST /api/heal/{pid}/reject`

Reject a pending repair. Body: `{"actor": "who", "reason": "optional"}`
(`actor` defaults to `"operator"`). Response: the proposal object with
`"status": "rejected"`. Emits a `heal_rejected` webhook. Same error codes as
approve, with `"rejection requires an accountable actor"` for a blank actor.

### `POST /api/reset`

Delete the registry database, reset the demo site to `v1`, and re-seed the
demo source. Response: `{"ok": true}`.

### Webhook events

Set `REWEAVE_WEBHOOK_URL` and every significant state transition is POSTed
as JSON (see `reweave/notify.py`):

```json
{"event": "heal_pending", "source_id": "nimbusmart", "ts": 1700000000.0,
 "data": {"summary": "…", "proposal_id": "heal_…"},
 "text": "reweave: heal_pending on nimbusmart — …"}
```

The `text` field makes the payload work as-is with Slack incoming webhooks.

| Event | Emitted when | `data` keys |
| --- | --- | --- |
| `drift_detected` | Sentinel judges a run unhealthy | `summary` (failures, truncated to 300 chars), `confidence` |
| `heal_pending` | Surgeon's validated repair parked at the gate | `summary`, `proposal_id` |
| `heal_escalated` | Surgeon could not validate a repair | `summary` |
| `heal_approved` | a human approved a deploy | `summary`, `proposal_id` |
| `heal_rejected` | a human rejected a proposal | `summary` |
| `rollback` | active spec pointer moved back | `summary` |

Delivery is strictly best-effort: 4-second timeout, failures are recorded to
the event log and swallowed — a dead webhook endpoint never stalls or fails
a pipeline run.

---

## 2. MCP tools

`reweave mcp` serves the Model Context Protocol on stdio (JSON-RPC 2.0,
protocol version `2025-06-18`; implementation in
`reweave/harness/mcp_server.py`). Supported methods: `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`; anything else with
an id gets a `-32601 method not found` error. Tool failures are returned as
`isError: true` results (`"{ExceptionType}: {message}"`), not protocol
errors. `serverInfo` reports `{"name": "reweave", "version": "0.1.0"}`.

Annotations follow the MCP spec: `approve_heal` and `reject_heal` carry
`destructiveHint: true` so a conforming harness interposes a human before
they execute — in addition to Reweave's own `ApprovalGate`, which demands an
accountable actor even if the harness gate is bypassed. A ready-made
TrueForge registration with the matching approval policy is in
`harness/trueforge.mcp.json`.

### `list_sources`

List every monitored source with health status and active spec version.
Input: `{}`. Annotations: `readOnlyHint: true`.
Returns the array of source records (same shape as `sources` in
`GET /api/state`, without `latest_run`).

### `run_pipeline`

Run one observe/extract/assess cycle for a source. If structural drift is
detected, the Surgeon synthesizes a validated repair and parks it at the
approval gate. Never deploys anything by itself.
Input: `{"source_id": string}` (required).
Annotations: `readOnlyHint: false`, `destructiveHint: false`.
Returns the pipeline result with `rows` stripped (to keep tool results
compact): `{"report", "provenance", "spec_version", "proposal"}`.

### `list_pending_heals`

List repair proposals awaiting human approval, with full diffs and
validation evidence. Input: `{}`. Annotations: `readOnlyHint: true`.
Returns an array of `HealProposal` objects.

### `approve_heal`

DEPLOY a pending repair: activates the new extraction spec version.
Irreversible in effect — requires an accountable human actor.
Input: `{"proposal_id": string, "actor": string}` (both required; `actor` is
described as "Human accountable for this deploy").
Annotations: `destructiveHint: true`.
Returns the approved proposal object; errors (`unknown proposal`, `already
approved/rejected`, blank actor) surface as `isError` results.

### `reject_heal`

Reject a pending repair proposal with an optional reason.
Input: `{"proposal_id": string, "actor": string, "reason"?: string}`
(`proposal_id` and `actor` required). Annotations: `destructiveHint: true`.

### `add_source`

Onboard a new source with ZERO selectors: provide a url and 2+ golden
example records visible on the page; the Surgeon synthesizes and validates
the extraction spec from the examples.
Input: `{"url": string, "name"?: string, "golden": [object, …]}` (`url` and
`golden` required). Annotations: `destructiveHint: false`.
Returns `{"source_id", "report", "spec"}` (delegates to `POST /api/sources`).

### `get_rows`

The latest extracted rows for a source (the actual data).
Input: `{"source_id": string}` (required). Annotations: `readOnlyHint: true`.
Returns the latest run record including `rows`; `isError` with
`"no runs recorded for {source_id}"` when none exist.

### `impact_report`

Totals of approved heals and the engineer-time/dollar impact ledger.
Input: `{}`. Annotations: `readOnlyHint: true`. Returns:

```json
{"totals": {"heals": …, "engineer_minutes_saved": …, "dollars_saved": …},
 "fleet_projection_50_scrapers": {"expected_breaks_per_year": …,
   "engineer_hours_per_year": …, "dollars_per_year": …}}
```

### `chaos_break_demo`

Demo only: ship a structural redesign to the built-in target site.
Input: `{}`. Annotations: `destructiveHint: false`.
Returns `{"demo_variant": "v2"}`.

---

## 3. CLI

Entry point: `reweave` (`reweave/cli.py`). Every subcommand exits `0` on
success unless noted.

### `reweave serve [--host HOST] [--port PORT] [--no-autopilot]`

Run the control-plane API + dashboard under uvicorn.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | bind address |
| `--port` | `8321` | bind port |
| `--no-autopilot` | off | disable continuous background monitoring |

The flag sets `REWEAVE_AUTOPILOT` via `setdefault`, so an already-exported
`REWEAVE_AUTOPILOT` environment variable wins over `--no-autopilot`.

### `reweave run SOURCE_ID`

Run one pipeline cycle for a source and print the `DriftReport` as JSON to
stdout. Exit code `0` if the run was healthy, `1` if not — usable directly
in cron/CI health checks.

### `reweave add URL --golden PATH [--name NAME]`

Onboard a new source from golden examples (no selectors needed). `--golden`
(required) is a path to a JSON list of golden example records. Prints a
one-line summary (`onboarded '<id>' via <provenance>: spec v1 with N fields,
first run M rows, confidence P%`). Exits `1` with
`could not anchor the golden examples on that page` on stderr if
bootstrapping fails.

### `reweave export SOURCE_ID [--csv]`

Print a source's latest extracted rows to stdout as JSON (default) or CSV
(`--csv`). Exits `1` with `no runs recorded for {source_id}` on stderr if
the source has never run.

### `reweave chaos`

Demo only: break the demo site (ship a redesign). Prints
`demo site is now structural era <variant>`.

### `reweave reset`

Reset demo state: deletes the registry database, resets the demo site to
`v1`, re-seeds the demo source. Prints `demo state reset`.

### `reweave mcp`

Serve Reweave as an MCP server on stdio (for TrueForge or any MCP client).
See [MCP tools](#2-mcp-tools).

---

## 4. Python API

The subsystems compose as `fetch → extract → assess → (heal → gate)`; each
is importable and usable on its own.

### `reweave.pipeline`

```python
gate: ApprovalGate                      # module-level gate, autonomy="manual"
run_source(source_id: str) -> dict[str, Any]
```

`run_source` is one full observe/orient/decide cycle. Returns
`{"report": dict, "rows": list[dict], "provenance": str, "spec_version": int,
"proposal": dict | None}`. Raises `KeyError` for an unknown source and
`RuntimeError` for a source with no active spec. On drift it opens an
incident, emits `drift_detected`, and — if no proposal is already pending —
invokes the Surgeon; a validated repair is submitted to the gate, an
unvalidatable one escalates (`heal_escalated`). The loop never deploys.

### `reweave.surgeon`

```python
MIN_FIELD_MATCH = 0.75

propose_heal(html: str, old_spec: ExtractionSpec, golden: list[dict],
             source_id: str, base_url: str = "",
             anchor_field: str = "title") -> HealProposal | None

bootstrap_spec(html: str, golden: list[dict], source_id: str,
               base_url: str = "") -> HealProposal | None

synthesize_field(cards_with_recs: list[tuple[dict, Tag]],
                 fspec: FieldSpec) -> tuple[str, str | None, float, str] | None

infer_field_kind(name: str, value: Any) -> str    # "price" | "url" | "text"
```

`propose_heal` anchors golden records in the new DOM (needs at least 2),
generalizes their item cards into a new `item_selector`, synthesizes
per-field selectors from shared class/`data-*`/parent signatures, validates
every candidate against all anchored records (accept threshold
`MIN_FIELD_MATCH`), runs the candidate spec end-to-end, and only returns a
proposal whose self-test `DriftReport` is healthy. Returns `None` when no
validated repair exists. `bootstrap_spec` is onboarding via the same
machinery: it requires 2+ golden records and at least one text-kind field to
anchor on, and produces a version-1 spec with origin `"bootstrap"`.

Anchoring helpers (`find_text_nodes`, `find_title_nodes`, `find_price_nodes`,
`find_url_nodes`) locate golden values as text or attribute nodes and are
public for reuse.

### `reweave.sentinel`

```python
HEALTHY_THRESHOLD = 0.8
MIN_ROW_RATIO     = 0.6
MAX_NULL_RATE     = 0.34
MIN_GOLDEN_MATCH  = 0.6

assess(source_id: str, rows: list[dict], spec: ExtractionSpec,
       golden: list[dict]) -> DriftReport

golden_field_match_rate(rows: list[dict], golden: list[dict],
                        field: str, kind: str) -> float
```

Health is judged on evidence, not exit codes. `assess` scores three signals
— row volume vs. the golden set (weight 0.35), per-required-field null rates
(0.30), and golden-record agreement (0.35) — into a confidence score. A run
is healthy iff confidence ≥ `HEALTHY_THRESHOLD` **and** no individual check
failed (row collapse below `MIN_ROW_RATIO`, null rate above `MAX_NULL_RATE`,
golden match below `MIN_GOLDEN_MATCH` on a required field).
`golden_field_match_rate` is the fraction of golden values for a field that
appear anywhere in the extracted rows (text compared case/whitespace-
insensitively, prices within ±0.01, URLs by trailing path segment).

### `reweave.extractor`

```python
extract(html: str, spec: ExtractionSpec, base_url: str = "") -> list[dict]
read_field(item: Tag, selector: str, attr: str | None) -> str | None
coerce(raw: str | None, kind: str, base_url: str = "") -> Any
parse_price(text: str | None) -> float | None
norm_text(s: str | None) -> str | None
```

Deterministic by design: all intelligence lives in the Surgeon, which
*produces* specs. `extract` returns one row per `item_selector` match;
missing fields become `None`; containers where nothing extracted are dropped
as layout chrome. `read_field` treats selector `"."` or `":self"` as the
item itself. `parse_price` handles `$1,299.00`, `1.299,00 €`, `USD 12.99`.
`coerce` applies kind semantics (`price` → float, `url` → resolved against
`base_url`, `text` → whitespace-normalized).

### `reweave.gates`

```python
AUTONOMY_LEVELS = ("manual", "assisted", "auto")

class ApprovalGate:
    def __init__(self, autonomy: str = "manual") -> None      # ValueError on bad tier
    def submit(self, proposal: HealProposal) -> dict          # park at the gate
    def approve(self, proposal_id: str, actor: str) -> dict   # deploy
    def reject(self, proposal_id: str, actor: str, reason: str = "") -> dict
```

`approve` activates the proposal's spec, closes incidents, books the impact
ledger, and emits `heal_approved`. Both `approve` and `reject` raise
`PermissionError` for a blank actor, `KeyError` for an unknown proposal, and
`ValueError` for one that is no longer pending.

### Supporting modules

```python
reweave.fetch.fetch(url: str, timeout: float = 30.0) -> tuple[str, str]
# (html, provenance); provenance ∈ "demo:<variant>" | "file" |
# "brightdata:<zone>" | "direct". Scheme routing: demo:// → built-in site,
# file:// → local path, http(s):// → Bright Data Web Unlocker when
# BRIGHTDATA_API_KEY is set, plain httpx GET otherwise.

reweave.notify.emit(event: str, source_id: str,
                    data: dict | None = None) -> bool   # True on 2xx
reweave.notify.EVENTS  # the six lifecycle event names

reweave.watch.enabled() -> bool          # registry-backed toggle
reweave.watch.set_enabled(on: bool)
reweave.watch.interval() -> float        # REWEAVE_WATCH_INTERVAL, floor 5.0
reweave.watch.start() -> bool            # start the daemon thread once/process

reweave.impact.per_heal() -> tuple[float, float]   # (minutes, dollars)
reweave.impact.fleet_projection(n_scrapers: int, weeks: int = 52) -> dict
# Constants: MINUTES_PER_MANUAL_FIX=90.0, HOURLY_RATE_USD=95.0,
# WEEKLY_BREAK_RATE=0.125
```

`reweave.registry` exposes the persistence layer (`list_sources`,
`get_active_spec`, `save_spec`, `activate_version`, `spec_history`,
`pending_proposals`, `latest_run`, `run_history`, `recent_events`,
`impact_totals`, `ops_counters`, `reset`, …) — see the module for the full
set; all functions open a short-lived SQLite connection per call.

---

## 5. Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `REWEAVE_DB` | `.reweave/reweave.db` | Path to the SQLite registry file. Parent directories are created on demand. |
| `REWEAVE_DEMO_DIR` | `<repo>/demo` | Override the directory containing the demo storefront variants (`site_v1/`, …) and `golden.json`. |
| `REWEAVE_AUTOPILOT` | unset | `1`/`true`/`on` starts the autopilot watcher thread at server startup. `reweave serve` sets it to `1` (or `0` with `--no-autopilot`) only if not already set. |
| `REWEAVE_WATCH_INTERVAL` | `60` | Seconds between autopilot sweeps over all sources. Floor of 5 seconds; non-numeric values fall back to 60. |
| `REWEAVE_API_TOKEN` | unset | When set, `/api/*` routes require `Authorization: Bearer <token>` (`/api/health` exempt; `/`, `/demo-site`, `/metrics` are outside `/api/`). |
| `REWEAVE_WEBHOOK_URL` | unset | When set, lifecycle events are POSTed as JSON (Slack-compatible payload). Best-effort delivery, 4 s timeout. |
| `BRIGHTDATA_API_KEY` | unset | When set, `http(s)://` fetches route through Bright Data Web Unlocker (`https://api.brightdata.com/request`) instead of a direct GET. |
| `BRIGHTDATA_ZONE` | `web_unlocker1` | Bright Data zone name used for Web Unlocker requests. |

---

## 6. Data model

### SQLite tables

One file (`REWEAVE_DB`), created on first use. `events` is append-only and
`specs` are immutable versions: a heal never mutates history, it adds
version N+1 and moves the active pointer.

| Table | Columns | Notes |
| --- | --- | --- |
| `kv` | `key` PK, `value` | small runtime state: `autopilot` toggle, `demo_variant` |
| `sources` | `id` PK, `name`, `url`, `status` (default `'unknown'`), `golden` (JSON), `active_version` (default 1), `last_checked` | one row per monitored source; `golden` is the JSON list of golden records |
| `specs` | `source_id`, `version`, `spec` (JSON) — PK `(source_id, version)` | immutable `ExtractionSpec` versions; the active one is whichever `sources.active_version` points at |
| `proposals` | `id` PK, `source_id`, `data` (JSON `HealProposal`), `status`, `created_at` | status: `pending` / `approved` / `rejected` |
| `incidents` | `id` PK, `source_id`, `kind`, `detail`, `status` (default `'open'`), `opened_at`, `closed_at` | one open incident per `(source, kind)`; kind is `structural-drift` today |
| `events` | `id` autoincrement PK, `ts`, `source_id`, `level`, `message` | append-only audit log; levels seen in code: `run`, `drift`, `heal`, `gate`, `deploy`, `escalate`, `chaos`, `system` |
| `heals` | `id` PK, `source_id`, `ts`, `minutes_saved`, `dollars_saved`, `approved_by` | impact ledger, one row per approved heal |
| `runs` | `id` PK, `source_id`, `ts`, `row_count`, `healthy` (int), `confidence`, `provenance`, `rows` (JSON) | last 20 runs kept per source (`RUNS_KEPT_PER_SOURCE`) |

### JSON shapes

Serialized forms of the dataclasses in `reweave/models.py` (these are what
the REST API and MCP tools return).

**`ExtractionSpec`** — a versioned recipe for turning a page into rows:

```json
{
  "item_selector": "div.product-card",
  "fields": [
    {"name": "title", "selector": "h3.product-name", "attr": null,
     "kind": "text", "required": true},
    {"name": "price", "selector": "span.price-tag", "attr": null,
     "kind": "price", "required": true},
    {"name": "url", "selector": "a.product-link", "attr": "href",
     "kind": "url", "required": true}
  ],
  "version": 1,
  "origin": "seed",
  "created_at": 1700000000.0
}
```

`attr: null` means the field reads the node's text content; otherwise the
named attribute. `kind` ∈ `text | price | url`. `origin` ∈
`seed | heal | manual | bootstrap` (plus the transient `stub` used
internally during bootstrapping).

**`DriftReport`** — the Sentinel's verdict on one extraction run:

```json
{
  "source_id": "nimbusmart",
  "healthy": false,
  "confidence": 0.412,
  "row_count": 0,
  "expected_rows": 4,
  "fields": [
    {"name": "title", "null_rate": 1.0, "golden_match_rate": 0.0, "ok": false}
  ],
  "failures": [
    "row volume collapsed: 0 rows vs 4 golden records",
    "field 'title': 100% of rows extracted null"
  ],
  "checked_at": 1700000000.0
}
```

**`HealProposal`** — a candidate repair; never deployed without an explicit
approval:

```json
{
  "id": "heal_ab12cd34ef",
  "source_id": "nimbusmart",
  "base_version": 1,
  "new_spec": { ExtractionSpec },
  "diffs": [
    {"name": "(item container)", "old_selector": "div.product-card",
     "new_selector": "article.item-tile", "old_attr": null, "new_attr": null,
     "match_rate": 1.0, "strategy": "anchor containment"},
    {"name": "title", "old_selector": "h3.product-name",
     "new_selector": "div.item-label", "old_attr": null, "new_attr": null,
     "match_rate": 1.0, "strategy": "record-anchored synthesis"}
  ],
  "validation": { DriftReport },
  "evidence": [
    "anchored 4/4 golden records in the new DOM",
    "item container generalized to `article.item-tile` (12 matches on page)",
    "field `title`: `h3.product-name` → `div.item-label` (validated against 100% of anchored golden records)"
  ],
  "sample_rows": [{ "...first 6 extracted rows..." : "" }],
  "status": "pending",
  "created_at": 1700000000.0,
  "resolved_at": null,
  "resolved_by": null
}
```

`validation` is the self-test `DriftReport` produced by running the candidate
spec end-to-end before proposing — a proposal only exists if that self-test
came back healthy. `resolved_at`/`resolved_by` are filled when the proposal
is approved or rejected.
