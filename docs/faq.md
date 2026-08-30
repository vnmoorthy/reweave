# Reweave FAQ

Straight answers about how Reweave actually behaves, including the parts
that are not built yet. Endpoint and function names refer to
[the API reference](reference.md); design rationale lives in
[the architecture doc](architecture.md).

### How do golden records stay fresh?

They don't refresh automatically — golden records are the trust anchor, so
Reweave deliberately never edits them on its own. They are stored once per
source (in `sources.golden`) and every health check and heal is validated
against that same set. The matching is lenient enough to survive normal
churn: `golden_field_match_rate` asks whether each golden value appears
*anywhere* in the extracted rows (case/whitespace-insensitive text, prices
within ±0.01, URLs by trailing path segment), and the per-field threshold is
0.6, so up to 40% of golden values can drift away before a required field
trips. When your golden facts genuinely go stale (prices changed on the real
site), update them: today that means deleting and re-onboarding the source
(`DELETE /api/sources/{id}` then `POST /api/sources`), which also resets its
version history. There is no endpoint to patch golden records in place yet.

### What happens when a golden fact vanishes from the page?

Say a golden product is delisted. Its values stop matching in every field,
which drags down `golden_match_rate` and the weighted confidence score. With
a small golden set this can push a source below the healthy threshold even
though the page structure is fine — a false drift. The Surgeon then also has
less to work with: healing requires anchoring at least 2 golden records in
the DOM. Practical guidance: use 4+ golden records, pick durable items
(bestsellers, house brands), and treat a `drift_detected` webhook whose
failures are all `golden values still extractable` (rather than null-rate or
row-count failures) as a hint that the *facts* moved, not the markup.

### Does Reweave work on JavaScript-rendered sites?

Only through Bright Data. The default fetch path is a plain `httpx` GET —
whatever HTML the server returns is what the extractor sees, with no JS
execution. Set `BRIGHTDATA_API_KEY` and every `http(s)://` fetch routes
through Web Unlocker, which handles JS rendering, proxy rotation, and
CAPTCHA solving upstream and returns the rendered HTML. Every run records
which channel produced the bytes (`provenance`: `direct` vs
`brightdata:<zone>`), so the audit log always shows what the agent acted on.
There is no built-in headless browser.

### What about rate limits and politeness?

Reweave is light-touch by construction — one GET per source per cycle, no
crawling — but the politeness controls are coarse. Autopilot sweeps all
sources sequentially every `REWEAVE_WATCH_INTERVAL` seconds (default 60,
floor 5). Direct fetches send an identifying User-Agent
(`reweave/0.1 (+https://github.com/vnmoorthy/reweave)`). What does *not*
exist today: robots.txt handling, per-domain throttling, retry backoff, or
jitter. If you monitor many sources on one domain, raise the interval; if
you need rotation and unblocking, that is what the Bright Data path is for.

### How will the autonomy tiers work?

`gates.AUTONOMY_LEVELS` defines three tiers: `manual`, `assisted`, `auto`.
Today only `manual` has behavior — the one gate the pipeline constructs is
`ApprovalGate(autonomy="manual")`, nothing in the codebase calls
`approve()` automatically, and the tier field is not consulted at
approve-time. It is a policy knob with a reserved seat, not a feature: the
intended shape (per the gate's design notes) is graduating trust per source
— e.g. auto-approving repairs above a confidence bar for sources you've
watched succeed repeatedly — rather than a system-wide switch. Whatever tier
a source runs at, the accountable-actor requirement and the audit trail stay.

### How does rollback work?

Spec versions are immutable — a heal adds version N+1 and moves the
`active_version` pointer — so rollback is a pointer move, not a revert
commit. `POST /api/sources/{id}/rollback` with `{"actor": "you"}` moves the
pointer to the previous version (or pass `to_version` explicitly to jump
anywhere in the history). It requires an accountable actor (422 without
one), refuses to "roll back" to the already-active version (409), logs a
`deploy` audit event, and fires the `rollback` webhook. The version you
rolled away from stays in `specs`, so rolling forward again is the same
call. Note rollback does not touch health status or incidents; the next
pipeline run re-assesses with the reactivated spec and opens an incident if
it is also broken.

### Can Reweave handle multi-page catalogs?

Not today — extraction is single-page. `fetch()` retrieves exactly one URL
and `extract()` runs the spec over that one document; there is no pagination
following, no per-item detail-page fetch, and every field must be present on
the listing card itself. The workaround is to register each page as its own
source (`?page=2` as a separate URL with its own golden records), which
works but multiplies sources. Pagination-aware sources are a real gap, not a
hidden feature.

### How do LLM-proposed selector candidates fit in?

The architecture reserves a slot for them, and the important part is *where*
the slot is: candidates, not decisions. The Surgeon's candidate generation
is deterministic today (shared classes, `data-*` attributes, parent-child
signatures of the anchored nodes). An LLM's proposed selectors would enter
that same candidate list inside `synthesize_field` and pass through exactly
the same validation — executed against every anchored golden record,
accepted only at ≥75% agreement, then the whole spec self-tested end-to-end
before a proposal exists. A hallucinated selector scores 0 and dies in
validation. No LLM output can reach production any other way, because the
only deploy path is an approved proposal. To be clear: no LLM calls exist in
the runtime yet.

### Why not just update specs in place?

Because the diff *is* the review. A `HealProposal` shows a human
old-selector → new-selector per field with match rates and sample rows;
that only stays trustworthy if the "old" side is a stable, immutable
version. Immutability also buys the audit trail (every spec that ever ran
is still in `specs`, every transition in append-only `events`), one-call
rollback (see above), and blame-free debugging — you can export the exact
spec that produced any historical run. The cost is a few KB of SQLite per
version, which is nothing.

### What does the Surgeon do when it can't find a repair?

It escalates instead of guessing. If fewer than 2 golden records anchor in
the new DOM, no item selector covers the anchored cards, a required field
can't be validated at ≥75%, or the end-to-end self-test comes back
unhealthy, `propose_heal` returns `None`. The pipeline then logs an
`escalate` event, leaves the incident open, and fires the `heal_escalated`
webhook — a human gets the Sentinel's full evidence rather than a
low-confidence auto-fix. Autopilot keeps re-running the loop each interval,
so a transient cause (bad fetch, half-deployed redesign) can still heal
itself on a later cycle.

### Does approving a heal re-run the pipeline?

No. `approve` moves the active pointer, closes the source's incidents,
marks it healthy, and books the impact ledger — the next run (manual
`POST /api/run/{id}` or the next autopilot sweep) is what actually extracts
with the new spec. If the approved spec turns out wrong anyway, that next
run fails assessment, re-opens an incident, and the cycle starts again;
`rollback` is available if you want the old spec back immediately.

### Where do the "dollars saved" numbers come from?

A formula you can argue with, not a vibe — the constants are in
`reweave/impact.py` with sources in
[architecture.md](architecture.md#impact-model): 90 engineer-minutes per
manual fix (the conservative floor of the 1–3 hour range practitioners
report), $95/hour fully-loaded data-engineering cost, and a 12.5% weekly
break rate for fleet projections (midpoint of the reported 10–15%). Every
approved heal books exactly one fix avoided; change the constants and every
number downstream changes with them.

### How should I run Reweave in production?

It is a single process with a single SQLite file, and it hosts like one:

* Run `reweave serve` under a supervisor (systemd, a container) behind a
  TLS-terminating reverse proxy. Point `REWEAVE_DB` at a persistent volume.
* Exactly **one** instance per database — SQLite is the registry and the
  autopilot thread lives in-process. There is no HA or multi-writer story.
* Set `REWEAVE_API_TOKEN`. That puts a bearer token on all `/api/*` routes;
  note the dashboard (`/`), demo site, `/api/health`, and `/metrics` remain
  open, so keep the proxy in front if the dashboard itself must be private.
* Wire `/api/health` to your load balancer, scrape `/metrics` with
  Prometheus, and set `REWEAVE_WEBHOOK_URL` to a Slack incoming webhook so
  `drift_detected` / `heal_pending` / `heal_escalated` land where the team
  looks. Webhook delivery is best-effort and never blocks a run.
* Enable autopilot (`REWEAVE_AUTOPILOT=1`) and size `REWEAVE_WATCH_INTERVAL`
  to your politeness budget; approvals still come from humans, so the
  pending-heals queue is the thing to watch.
