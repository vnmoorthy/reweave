<div align="center">

# 🧵 reweave

**Self-healing web data pipelines.**
*Break the site. Watch the agent stitch it back.*

[![CI](https://github.com/vnmoorthy/reweave/actions/workflows/ci.yml/badge.svg)](https://github.com/vnmoorthy/reweave/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP Server](https://img.shields.io/badge/MCP-server-39d3e6)](docs/architecture.md#mcp-surface)
[![Built on TrueForge](https://img.shields.io/badge/harness-TrueForge-b18cff)](https://github.com/truefoundry/trueforge)
[![Data via Bright Data](https://img.shields.io/badge/fetch-Bright%20Data-ffb454)](https://brightdata.com)

[Website](https://vnmoorthy.github.io/reweave/) ·
[Architecture](docs/architecture.md) ·
[Healing protocol](docs/architecture.md#the-healing-protocol) ·
[Demo in 90 seconds](#-the-90-second-demo)

<img src="docs/assets/dashboard-gate.png" alt="Reweave mission control — a synthesized repair waiting at the human approval gate" width="920">

<sub>*A repair the agent synthesized and validated by itself, waiting at the approval gate. No selector was written by a human.*</sub>

</div>

---

## The treadmill

Every team that extracts data from the web is on the same treadmill. The community's own numbers (r/webscraping):

- **10–15% of scrapers break every single week** when target sites change structure.
- One person can maintain ~100 scrapers. **Nobody can maintain 200.**
- The worst failures are **silent** — the job exits 0 and writes empty or wrong rows into downstream pricing, dashboards, and models for days.
- A "simple" selector fix is never simple: triage → reproduce → rewrite → test → deploy → backfill ≈ **90 engineer-minutes**, every time, forever.

At a 50-scraper fleet that compounds to **~325 breaks and ~487 engineer-hours (~$46,000) a year** of pure toil.

## What reweave does

Reweave is an autonomous repair agent for that loop — with a human in command of every deploy:

```
        ┌────────────┐     drift      ┌────────────┐   validated    ┌────────────┐
  fetch │  SENTINEL  │ ─────────────▶ │  SURGEON   │ ─────────────▶ │    GATE    │
 ─────▶ │  detects   │                │ synthesizes│                │  a human   │
        │  breakage  │ ◀───────────── │  a repair  │                │  approves  │
        └────────────┘   redeployed   └────────────┘                └─────┬──────┘
              ▲                                                          │
              └────────────────── spec v(N+1) activated ◀────────────────┘
```

1. **The Sentinel** validates every extraction against *golden records* — facts known to be true. It catches silent failures: row-volume collapse, null-rate spikes, golden values that stopped being extractable.
2. **The Surgeon** performs **record-anchored selector synthesis**: it re-locates the golden facts in the redesigned DOM, infers the new item containers, generalizes shared CSS signatures into candidate selectors, and accepts only candidates that reproduce the golden data. (Optional LLM candidates go through *exactly the same validation* — evidence over vibes.)
3. **The Gate** quarantines the repair. A named human sees the full before/after selector diff, per-field match rates, and sample rows — and only their explicit approval activates spec `v(N+1)`. Every decision lands in an audit ledger with the actor's name.

The result: a 90-minute manual fix becomes a **30-second review-and-approve**, and nothing ever deploys itself.

## 🚀 Quickstart

```bash
git clone https://github.com/vnmoorthy/reweave && cd reweave
pip install -e ".[dev]"
reweave serve          # mission control on http://localhost:8321
```

Then run the loop from the dashboard — or entirely from the CLI:

```bash
reweave run nimbusmart   # healthy: 8 rows, confidence 100%
reweave chaos            # the target site ships a redesign 💥
reweave run nimbusmart   # drift detected → repair synthesized → parked at the gate
```

## 🎬 The 90-second demo

The repo ships with a breakable storefront (three complete front-end "eras" of the same site). In the dashboard:

| | |
|---|---|
| **1. Run pipeline** | 8 products extracted, 100% confidence. |
| **2. ⚡ Ship redesign** | The storefront visibly redesigns *in the embedded target-site pane* — every selector the pipeline relied on is now gone. |
| **3. Run pipeline** | The Sentinel reports the drift with named failures. The Surgeon anchors 8/8 golden records in the new DOM, synthesizes four new selectors, self-tests them, and parks a 100%-validated repair at the gate. |
| **4. Approve** | Type your name (approvals are accountable), approve, and the pipeline is green again on spec v2 — with $142.50 of recovered toil booked to the impact ledger. |
| **5. Do it again** | Ship the *second* redesign (a utility-class rebuild). The healed spec heals again. |

<div align="center">
<img src="docs/assets/site-v1.png" alt="Target site, seed era" width="44%"> <img src="docs/assets/site-v2.png" alt="Target site after the redesign" width="44%">
<br><sub>*The same store, before and after the chaos button. Titles, prices and links survive; every selector dies.*</sub>
</div>

## 🛡️ Safety model

Reweave treats "agent deploys its own code change" as the risk it is:

- **Two independent gates.** The MCP surface annotates `approve_heal` with `destructiveHint`, so a conforming harness (TrueForge's approval policy, Claude Code's permission prompt) interposes a human *before the tool call* — and Reweave's own `ApprovalGate` still requires an accountable actor *inside* the call. Defense in depth.
- **Immutable spec versions.** A heal never mutates history; it writes `v(N+1)` and moves a pointer. Rollback is a pointer move.
- **Evidence-gated synthesis.** A selector that cannot reproduce the golden records does not become a proposal, whether it came from the synthesizer or an LLM.
- **Append-only audit ledger.** Who approved what, when, and what it changed — queryable forever.

## 🔌 Runs inside TrueForge

Reweave is an [MCP server](docs/architecture.md#mcp-surface). Register it in [TrueForge](https://github.com/truefoundry/trueforge) with the shipped [approval policy](harness/trueforge.mcp.json) and the [`reweave-operator` skill pack](skills/reweave-operator/SKILL.md):

```jsonc
{ "mcpServers": { "reweave": { "command": "reweave", "args": ["mcp"] } },
  "approvalPolicy": { "reweave": { "approve_heal": "always_ask" } } }
```

The harness's agent triages incidents, reads proposals, and *asks its human* — the SKILL.md pack pins the operating rules (never approve without an explicit instruction; recommend rejection under 90% validation confidence).

For hostile production sites, set `BRIGHTDATA_API_KEY` and fetching routes through **Bright Data Web Unlocker** automatically — every page carries provenance (`brightdata:zone`, `direct`, `demo:v2`) into the audit log.

## 🧪 Tested like infrastructure

```bash
python -m pytest      # 13 tests, including the full lifecycle E2E
```

The E2E suite proves the whole story: healthy → redesign → drift → synthesis → *nothing deploys on rerun* → human approves → healthy on v2 → impact booked. Plus: healing the second redesign *from the healed spec*, refusing to heal when the facts are gone, rejection flows, and double-approve conflicts.

## 📐 Project layout

```
reweave/
├── reweave/                 # the package
│   ├── extractor.py         # deterministic spec execution (all intelligence lives upstream)
│   ├── sentinel.py          # golden-record drift detection
│   ├── surgeon.py           # record-anchored selector synthesis
│   ├── gates.py             # accountable approval gate (manual/assisted/auto tiers)
│   ├── pipeline.py          # the observe→orient→decide loop
│   ├── registry.py          # SQLite: immutable spec versions, incidents, audit ledger
│   ├── fetch.py             # Bright Data Web Unlocker / direct / demo, with provenance
│   ├── impact.py            # the toil-recovered ledger (defensible math, sourced)
│   ├── server.py            # FastAPI control plane
│   └── harness/mcp_server.py# dependency-free MCP stdio server
├── dashboard/               # single-file mission control UI
├── demo/                    # the breakable storefront (3 structural eras) + golden records
├── skills/reweave-operator/ # TrueForge SKILL.md instruction pack
├── harness/                 # TrueForge MCP registration + approval policy
├── tests/                   # 13 tests incl. full-lifecycle E2E
└── docs/architecture.md     # deep dive: components, protocol, trust boundaries
```

## 🗺️ Roadmap

- **Drift prediction** — schedule canary runs when a site's asset fingerprints churn, catching redesigns before the first bad row.
- **Tiered autonomy graduation** — per-source trust: `manual` → `assisted` (auto-approve above a confidence bar, notify) → `auto` (approve, audit, allow instant rollback).
- **Fleet mode** — hosted Postgres registry, hundreds of sources, team approvals.
- **Beyond CSS** — synthesis targets for JSON APIs, XHR payloads, and LLM-extraction prompts.

## Contributing & license

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md). MIT licensed.

<sub>Built in one day at the **Agent Harness Hackathon** (SF, Aug 2026) on **TrueForge** · **Bright Data** · **Qodo**. The pain is real — go read r/webscraping.</sub>
