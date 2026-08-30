# ADR-0002: Two independent approval layers (harness + core)

**Status:** accepted · **Date:** 2026-08-29

## Context

Reweave's deploy action (`approve_heal`) changes what a production pipeline
does. Agent harnesses (TrueForge, Claude Code) already provide human-approval
UX for destructive tools — so should Reweave rely on the harness gate alone?

## Decision

No. Two independent layers:

1. **Harness layer** — the MCP tool is annotated `destructiveHint`, and the
   shipped TrueForge config pins it to `always_ask`, so a conforming harness
   interposes its approval UI before the call.
2. **Core layer** — `ApprovalGate.approve()` independently requires a
   non-empty accountable `actor`, enforces one-way pending→approved/rejected
   transitions, and writes the actor to the audit ledger.

## Consequences

- A misconfigured or malicious harness (or a raw `curl`) still cannot deploy
  silently or anonymously.
- Accountability is data, not UI: "who approved this" survives in the ledger
  regardless of which surface performed the approval.
- Trade-off: double-approval friction in harnesses that already gate the
  tool. Accepted — the second "layer" costs one string argument.
