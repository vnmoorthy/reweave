"""The Gate: no repair reaches production without an accountable approval.

This is the project's safety thesis made concrete. The Surgeon can be as
clever as it likes — its output is *quarantined* in the proposal store. Only
an explicit ``approve(proposal_id, actor)`` moves the active spec pointer,
and the actor lands in the audit ledger next to the impact booking.

Autonomy is tiered (``manual`` today; ``assisted``/``auto`` are policy knobs,
not code changes) so teams can graduate trust per source rather than
system-wide.
"""

from __future__ import annotations

from typing import Any

from . import impact, registry
from .models import ExtractionSpec, HealProposal

AUTONOMY_LEVELS = ("manual", "assisted", "auto")


class ApprovalGate:
    def __init__(self, autonomy: str = "manual") -> None:
        if autonomy not in AUTONOMY_LEVELS:
            raise ValueError(f"autonomy must be one of {AUTONOMY_LEVELS}")
        self.autonomy = autonomy

    def submit(self, proposal: HealProposal) -> dict[str, Any]:
        registry.add_proposal(proposal)
        registry.log_event(
            proposal.source_id,
            "gate",
            f"heal proposal {proposal.id} awaiting human approval "
            f"(v{proposal.base_version} → v{proposal.new_spec.version}, "
            f"validation confidence {proposal.validation.confidence:.0%})",
        )
        return proposal.to_dict()

    def approve(self, proposal_id: str, actor: str) -> dict[str, Any]:
        if not actor or not actor.strip():
            raise PermissionError("approval requires an accountable actor")
        data = registry.get_proposal(proposal_id)
        if data is None:
            raise KeyError(f"unknown proposal {proposal_id}")
        if data["status"] != "pending":
            raise ValueError(f"proposal {proposal_id} already {data['status']}")

        spec = ExtractionSpec.from_dict(data["new_spec"])
        registry.save_spec(data["source_id"], spec, activate=True)
        registry.set_proposal_status(proposal_id, "approved", actor)
        registry.close_incidents(data["source_id"])
        registry.set_source_status(data["source_id"], "healthy")

        minutes, dollars = impact.per_heal()
        registry.record_heal(data["source_id"], minutes, dollars, actor)
        registry.log_event(
            data["source_id"],
            "deploy",
            f"{actor} approved heal {proposal_id}: spec v{spec.version} deployed "
            f"(+{minutes:.0f} engineer-minutes, +${dollars:.2f} saved)",
        )
        data["status"] = "approved"
        return data

    def reject(self, proposal_id: str, actor: str, reason: str = "") -> dict[str, Any]:
        if not actor or not actor.strip():
            raise PermissionError("rejection requires an accountable actor")
        data = registry.get_proposal(proposal_id)
        if data is None:
            raise KeyError(f"unknown proposal {proposal_id}")
        if data["status"] != "pending":
            raise ValueError(f"proposal {proposal_id} already {data['status']}")
        registry.set_proposal_status(proposal_id, "rejected", actor)
        registry.log_event(
            data["source_id"],
            "gate",
            f"{actor} rejected heal {proposal_id}" + (f": {reason}" if reason else ""),
        )
        data["status"] = "rejected"
        return data
