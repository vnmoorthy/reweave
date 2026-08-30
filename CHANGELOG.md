# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.3.0] — 2026-08-29

Operational maturity: run it like infrastructure.

### Added
- **`GET /api/health`** — status, version, uptime, source count (kept open
  for load balancers even when auth is on).
- **`GET /metrics`** — dependency-free Prometheus exposition: runs, drift
  detections, heals deployed, minutes/dollars recovered, pending heals, open
  incidents, per-status source gauges.
- **Outbound webhooks** (`REWEAVE_WEBHOOK_URL`) — `drift_detected`,
  `heal_pending`, `heal_escalated`, `heal_approved`, `heal_rejected`,
  `rollback` POSTed as JSON (Slack-compatible `text` field). Best-effort by
  design: a dead endpoint can never stall a pipeline run.
- **One-click rollback** — `POST /api/sources/{id}/rollback` and a dashboard
  `↩` button; immutable versions make it a pointer move (ADR-0003), but it
  still demands an accountable actor and lands in the ledger + webhooks.
- **Optional API auth** (`REWEAVE_API_TOKEN`) — bearer-token guard on all
  `/api/` routes; the dashboard prompts once and remembers the token.
- **Docker** — multi-stage image, compose file, deploy guide
  ([docs/deploy.md](docs/deploy.md)).
- **Reference docs** ([docs/reference.md](docs/reference.md)) — full REST,
  MCP, CLI, Python API, env var, and data-model reference; FAQ
  ([docs/faq.md](docs/faq.md)).
- **Benchmarks** ([benchmarks/](benchmarks/)) — reproducible harness with
  measured numbers for extract/assess/heal/bootstrap.
- 6 new tests (26 total).

## [0.2.0] — 2026-08-29

From demo to product: sources in, data out, watching around the clock.

### Added
- **Zero-selector onboarding** (`POST /api/sources`, `reweave add`, MCP
  `add_source`, dashboard "＋ Add source"): provide a URL and 2+ golden
  example records; the Surgeon bootstraps the extraction spec with the same
  record-anchored synthesis it uses to heal. Verified against the live web.
- **Attribute anchoring** — golden values are found in node text *or*
  attributes (`title=`, `alt=`), with per-shape candidate groups; handles
  real catalogs that truncate visible text. Item-container selection now
  picks the most specific selector covering all anchored cards, so a few
  examples generalize to a full page.
- **Stored runs & export** — every run's rows are recorded (last 20 per
  source), browsable in the dashboard data drawer, exportable as CSV/JSON
  (`/api/sources/{id}/rows`, `reweave export`, MCP `get_rows`).
- **Autopilot** — continuous background monitoring of all sources
  (`REWEAVE_WATCH_INTERVAL`, default 60s) with a dashboard toggle; deploys
  still require a human at the gate.
- Source removal, run history endpoint, per-source run buttons; 7 new tests
  (20 total).

## [0.1.0] — 2026-08-29

The one-day build (Agent Harness Hackathon, SF).

### Added
- **Sentinel** — golden-record drift detection: row-volume, per-field null
  rates, golden agreement; catches silent failures, not just crashes.
- **Surgeon** — record-anchored selector synthesis: anchor → containerize →
  generalize → validate; decoy-resistant price parsing; refuses to propose
  anything that can't reproduce the golden records.
- **Gate** — accountable approvals with immutable spec versioning, one-way
  proposal transitions, and an append-only audit + impact ledger.
- **MCP server** (stdio, dependency-free) with `destructiveHint` annotations
  on deploy/discard tools; TrueForge registration config + `reweave-operator`
  SKILL.md pack.
- **Fetch layer** with provenance: Bright Data Web Unlocker / direct / demo.
- **Mission-control dashboard** — fleet, live event stream, approval gate
  with before/after diffs, embedded breakable target site.
- **Demo storefront** with three structural eras + chaos cycling.
- **13-test suite** including full-lifecycle E2E (drift → heal → gate →
  deploy → impact) and repeat-healing across redesigns.
- CI (Python 3.10–3.12), product website (GitHub Pages), 10-slide deck.

[0.3.0]: https://github.com/vnmoorthy/reweave/releases/tag/v0.3.0
[0.2.0]: https://github.com/vnmoorthy/reweave/releases/tag/v0.2.0
[0.1.0]: https://github.com/vnmoorthy/reweave/releases/tag/v0.1.0
