# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

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

[0.1.0]: https://github.com/vnmoorthy/reweave/releases/tag/v0.1.0
