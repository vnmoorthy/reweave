# ADR-0003: Immutable spec versions with an active pointer

**Status:** accepted · **Date:** 2026-08-29

## Context

An approved heal must change the running extraction spec. Update-in-place is
simpler; versioning adds bookkeeping.

## Decision

Specs are immutable rows keyed `(source_id, version)`. A heal writes
`v(N+1)` and approval moves `sources.active_version`. Nothing ever rewrites
a historical spec.

## Consequences

- **Rollback is a pointer move** — a bad approval is recoverable in seconds,
  which is what makes granting approval psychologically cheap (and therefore
  actually used, instead of rubber-stamped).
- The full lineage of every selector the pipeline ever ran is queryable —
  drift patterns per site become analyzable data (feeds the roadmap's drift
  prediction).
- A `HealProposal` can reference its `base_version` precisely, so a proposal
  computed against a stale spec is detectable at approval time.
- Trade-off: unbounded historical rows. Acceptable: specs are small JSON, and
  pruning is a policy decision for fleet mode, not a correctness concern.
