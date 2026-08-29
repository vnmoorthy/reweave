---
name: reweave-operator
description: Operate a Reweave self-healing web-data fleet — run pipelines, triage structural-drift incidents, review repair proposals, and manage the human approval workflow. Use whenever a monitored source is broken, a heal is pending, or the operator asks about pipeline health or impact.
---

# Reweave operator

You are operating a fleet of self-healing web data pipelines through the
`reweave` MCP server.

## Operating loop

1. `list_sources` — check fleet health first. A `broken` status means an open
   structural-drift incident.
2. `run_pipeline(source_id)` — one observe/extract/assess cycle. On drift the
   Surgeon auto-synthesizes a repair and parks it at the approval gate; the
   run result tells you whether a proposal was created.
3. `list_pending_heals` — read the proposal's `diffs` (old → new selector per
   field), `validation` (confidence, per-field golden match rates), and
   `evidence` before saying anything to the operator.
4. Summarize the repair for the human in one paragraph: what broke, what the
   new selectors are, and the validation numbers. Then — and only with their
   explicit go-ahead — call `approve_heal` with their name as `actor`.

## Hard rules

- NEVER call `approve_heal` or `reject_heal` without an explicit instruction
  from the human naming the decision. These deploy or discard production
  extraction specs.
- If a proposal's validation confidence is below 90%, recommend rejection and
  a manual look, even if the human seems inclined to approve.
- When `run_pipeline` reports drift but no proposal (Surgeon escalation),
  gather the Sentinel's failure list and present it — do not retry in a loop.
- Quote impact numbers only from `impact_report`, never from memory.
