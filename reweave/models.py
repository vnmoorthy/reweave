"""Typed domain model for the whole healing lifecycle.

Everything that crosses a subsystem boundary (extractor -> sentinel ->
surgeon -> gate -> registry) is one of these frozen-shape records, so the
audit log can serialize any state transition losslessly.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> float:
    return time.time()


@dataclass
class FieldSpec:
    """One extractable field: a relative CSS selector inside an item container."""

    name: str
    selector: str
    attr: str | None = None  # None -> text content, otherwise an attribute name
    kind: str = "text"  # text | price | url
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "FieldSpec":
        return FieldSpec(**d)


@dataclass
class ExtractionSpec:
    """A versioned recipe for turning a page into rows."""

    item_selector: str
    fields: list[FieldSpec]
    version: int = 1
    origin: str = "seed"  # seed | heal | manual
    created_at: float = field(default_factory=now)

    def field_map(self) -> dict[str, FieldSpec]:
        return {f.name: f for f in self.fields}

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_selector": self.item_selector,
            "fields": [f.to_dict() for f in self.fields],
            "version": self.version,
            "origin": self.origin,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ExtractionSpec":
        return ExtractionSpec(
            item_selector=d["item_selector"],
            fields=[FieldSpec.from_dict(f) for f in d["fields"]],
            version=d.get("version", 1),
            origin=d.get("origin", "seed"),
            created_at=d.get("created_at", now()),
        )


@dataclass
class FieldHealth:
    name: str
    null_rate: float
    golden_match_rate: float
    ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriftReport:
    """The Sentinel's verdict on one extraction run."""

    source_id: str
    healthy: bool
    confidence: float
    row_count: int
    expected_rows: int
    fields: list[FieldHealth]
    failures: list[str]
    checked_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "healthy": self.healthy,
            "confidence": round(self.confidence, 3),
            "row_count": self.row_count,
            "expected_rows": self.expected_rows,
            "fields": [f.to_dict() for f in self.fields],
            "failures": self.failures,
            "checked_at": self.checked_at,
        }


@dataclass
class FieldDiff:
    name: str
    old_selector: str | None
    new_selector: str | None
    old_attr: str | None
    new_attr: str | None
    match_rate: float
    strategy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealProposal:
    """A candidate repair. Never deployed without an explicit approval."""

    source_id: str
    base_version: int
    new_spec: ExtractionSpec
    diffs: list[FieldDiff]
    validation: DriftReport
    evidence: list[str]
    sample_rows: list[dict[str, Any]]
    id: str = field(default_factory=lambda: new_id("heal"))
    status: str = "pending"  # pending | approved | rejected
    created_at: float = field(default_factory=now)
    resolved_at: float | None = None
    resolved_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "base_version": self.base_version,
            "new_spec": self.new_spec.to_dict(),
            "diffs": [d.to_dict() for d in self.diffs],
            "validation": self.validation.to_dict(),
            "evidence": self.evidence,
            "sample_rows": self.sample_rows,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }
