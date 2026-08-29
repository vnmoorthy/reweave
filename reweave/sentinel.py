"""The Sentinel: structural-drift detection against golden records.

Silent failure is the killer ("the scraper 'succeeded' while writing empty
rows"), so health is judged on *evidence*, not exit codes:

* row-volume sanity vs. the golden set,
* per-field null rates,
* golden-record agreement — do the values we know to be true still come out?

Confidence is a weighted score; anything below ``HEALTHY_THRESHOLD`` opens an
incident and hands the page to the Surgeon.
"""

from __future__ import annotations

from typing import Any

from .models import DriftReport, ExtractionSpec, FieldHealth

HEALTHY_THRESHOLD = 0.8
MIN_ROW_RATIO = 0.6
MAX_NULL_RATE = 0.34
MIN_GOLDEN_MATCH = 0.6

_WEIGHTS = {"rows": 0.35, "nulls": 0.30, "golden": 0.35}


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return " ".join(v.split()).casefold()
    return v


def _values_match(kind: str, got: Any, want: Any) -> bool:
    if got is None or want is None:
        return False
    if kind == "price":
        try:
            return abs(float(got) - float(want)) < 0.01
        except (TypeError, ValueError):
            return False
    if kind == "url":
        g, w = str(got).rstrip("/"), str(want).rstrip("/")
        return g.endswith(w.split("/")[-1]) or w.endswith(g.split("/")[-1])
    return _norm(got) == _norm(want)


def golden_field_match_rate(
    rows: list[dict[str, Any]], golden: list[dict[str, Any]], field: str, kind: str
) -> float:
    """Fraction of golden values for `field` that appear anywhere in the rows."""
    if not golden:
        return 1.0
    hits = 0
    for g in golden:
        want = g.get(field)
        if want is None:
            continue
        if any(_values_match(kind, r.get(field), want) for r in rows):
            hits += 1
    denom = sum(1 for g in golden if g.get(field) is not None)
    return hits / denom if denom else 1.0


def assess(
    source_id: str,
    rows: list[dict[str, Any]],
    spec: ExtractionSpec,
    golden: list[dict[str, Any]],
) -> DriftReport:
    expected = len(golden)
    failures: list[str] = []

    row_score = min(1.0, len(rows) / max(1, expected))
    if expected and len(rows) < MIN_ROW_RATIO * expected:
        failures.append(
            f"row volume collapsed: {len(rows)} rows vs {expected} golden records"
        )

    field_healths: list[FieldHealth] = []
    null_scores: list[float] = []
    golden_scores: list[float] = []
    for f in spec.fields:
        n = len(rows)
        null_rate = (sum(1 for r in rows if r.get(f.name) is None) / n) if n else 1.0
        gm = golden_field_match_rate(rows, golden, f.name, f.kind)
        ok = True
        if f.required and null_rate > MAX_NULL_RATE:
            ok = False
            failures.append(f"field '{f.name}': {null_rate:.0%} of rows extracted null")
        if f.required and gm < MIN_GOLDEN_MATCH:
            ok = False
            failures.append(
                f"field '{f.name}': only {gm:.0%} of golden values still extractable"
            )
        field_healths.append(FieldHealth(f.name, round(null_rate, 3), round(gm, 3), ok))
        if f.required:
            null_scores.append(1.0 - null_rate)
            golden_scores.append(gm)

    null_score = sum(null_scores) / len(null_scores) if null_scores else 1.0
    golden_score = sum(golden_scores) / len(golden_scores) if golden_scores else 1.0
    confidence = (
        _WEIGHTS["rows"] * row_score
        + _WEIGHTS["nulls"] * null_score
        + _WEIGHTS["golden"] * golden_score
    )
    healthy = confidence >= HEALTHY_THRESHOLD and not failures
    return DriftReport(
        source_id=source_id,
        healthy=healthy,
        confidence=confidence,
        row_count=len(rows),
        expected_rows=expected,
        fields=field_healths,
        failures=failures,
    )
