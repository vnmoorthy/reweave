"""The pipeline loop: fetch → extract → assess → (heal → gate).

One call to :func:`run_source` is one full observe/orient/decide cycle:

* healthy extraction → rows returned, status recorded, done;
* drift detected → incident opened, the Surgeon synthesizes a repair in an
  isolated pass, and the proposal is parked at the approval gate;
* healing impossible → the incident escalates to a human with the Sentinel's
  full evidence attached.

The loop never deploys anything. Acting on a proposal is the Gate's job, and
the Gate answers to a person.
"""

from __future__ import annotations

from typing import Any

from . import registry, sentinel, surgeon
from .extractor import extract
from .fetch import fetch
from .gates import ApprovalGate

gate = ApprovalGate(autonomy="manual")


def run_source(source_id: str) -> dict[str, Any]:
    src = registry.get_source(source_id)
    if src is None:
        raise KeyError(f"unknown source {source_id}")
    spec = registry.get_active_spec(source_id)
    if spec is None:
        raise RuntimeError(f"source {source_id} has no active extraction spec")

    html, provenance = fetch(src["url"])
    rows = extract(html, spec, base_url=src["url"])
    report = sentinel.assess(source_id, rows, spec, src["golden"])

    registry.record_run(source_id, rows, report.healthy, report.confidence, provenance)
    registry.log_event(
        source_id,
        "run",
        f"pipeline run via {provenance}: {report.row_count} rows, "
        f"confidence {report.confidence:.0%} (spec v{spec.version})",
    )

    result: dict[str, Any] = {
        "report": report.to_dict(),
        "rows": rows,
        "provenance": provenance,
        "spec_version": spec.version,
        "proposal": None,
    }

    if report.healthy:
        registry.set_source_status(source_id, "healthy")
        registry.close_incidents(source_id)
        return result

    registry.set_source_status(source_id, "broken")
    registry.open_incident(
        source_id,
        "structural-drift",
        "; ".join(report.failures) or "confidence below threshold",
    )
    registry.log_event(
        source_id,
        "drift",
        f"structural drift detected: {'; '.join(report.failures) or 'low confidence'}",
    )

    if registry.pending_proposals(source_id):
        registry.log_event(source_id, "gate", "heal already pending — awaiting approval")
        result["proposal"] = registry.pending_proposals(source_id)[0]
        return result

    registry.log_event(source_id, "heal", "Surgeon engaged: record-anchored selector synthesis")
    proposal = surgeon.propose_heal(
        html, spec, src["golden"], source_id, base_url=src["url"]
    )
    if proposal is None:
        registry.log_event(
            source_id,
            "escalate",
            "Surgeon could not validate a repair — escalating to human with full evidence",
        )
        return result

    registry.log_event(
        source_id,
        "heal",
        f"repair synthesized and self-tested in isolation: "
        f"{len(proposal.diffs)} selector changes, "
        f"validation confidence {proposal.validation.confidence:.0%}",
    )
    gate.submit(proposal)
    result["proposal"] = proposal.to_dict()
    return result
