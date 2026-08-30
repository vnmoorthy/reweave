# ADR-0001: Record-anchored selector synthesis (not LLM-first repair)

**Status:** accepted · **Date:** 2026-08-29

## Context

When a site redesign breaks extraction, something must produce new selectors.
The obvious 2026 answer is "ask an LLM to look at the HTML." We rejected that
as the *primary* mechanism.

## Decision

The primary repair mechanism is deterministic: anchor the already-known
golden facts in the new DOM, infer item containers from co-containment of two
independent facts (title + price), generalize shared CSS signatures, and
accept only candidates that reproduce the golden records (≥75% per field,
full Sentinel pass for the assembled spec). LLM-proposed candidates are
welcome — as *additional candidates in the same validation pipeline*.

## Consequences

- Repairs are explainable ("validated against 8/8 golden records"), cheap
  (tens of ms, no tokens), and runnable offline — the demo cannot die on
  stage and CI needs no API keys.
- A hallucinated selector cannot reach production: validation is the trust
  boundary, so the LLM's trust level is irrelevant.
- Trade-off: synthesis fails when the facts themselves vanish (paywalls,
  full content changes). That failure mode is escalation-to-human with
  evidence, which we consider correct behavior, not a limitation to
  engineer away.
