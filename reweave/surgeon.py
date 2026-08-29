"""The Surgeon: record-anchored selector synthesis.

When a site redesign breaks extraction, the page's *structure* changed but the
*facts* on it mostly did not. The Surgeon exploits that invariant:

1. **Anchor** — locate each golden record's known values (title, price, url)
   as text/attribute nodes in the new DOM.
2. **Containerize** — for every record, the smallest ancestor that contains
   the record's title *and* price is its item card; cards are generalized
   into a new ``item_selector`` from their shared class/attribute signature.
3. **Synthesize** — per field, candidate relative selectors are generated
   from the signatures of the anchored nodes (classes, ``data-*`` attributes,
   parent-child paths) plus any LLM-proposed candidates.
4. **Validate** — every candidate is executed against *all* cards and scored
   by golden agreement. Selectors are accepted on evidence, never on vibes:
   an LLM suggestion passes through exactly the same validation as a
   synthesized one.

The output is a :class:`~reweave.models.HealProposal` carrying the full
before/after diff, per-field match rates, and sample rows — everything a
human needs to approve or reject the deploy in one glance.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from bs4 import BeautifulSoup
from bs4.element import Tag

from . import sentinel
from .extractor import coerce, extract, norm_text, parse_price
from .models import (
    DriftReport,
    ExtractionSpec,
    FieldDiff,
    FieldSpec,
    HealProposal,
)

_CLASS_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
MIN_FIELD_MATCH = 0.75


# ---------------------------------------------------------------------------
# Anchoring
# ---------------------------------------------------------------------------

def _text_of(node: Tag) -> str:
    return node.get_text(" ", strip=True)


def _deepest(nodes: list[Tag]) -> list[Tag]:
    """Drop any node that has a descendant also present in the list."""
    out = []
    node_set = set(id(n) for n in nodes)
    for n in nodes:
        if not any(id(d) in node_set for d in n.find_all(True)):
            out.append(n)
    return out


def find_title_nodes(root: Tag, title: str) -> list[Tag]:
    want = norm_text(title)
    hits = [
        n
        for n in root.find_all(True)
        if norm_text(_text_of(n)) == want
    ]
    return _deepest(hits)


def find_price_nodes(root: Tag, price: float) -> list[Tag]:
    hits = []
    for n in root.find_all(True):
        t = _text_of(n)
        if len(t) > 24:
            continue
        p = parse_price(t)
        if p is not None and abs(p - price) < 0.01:
            hits.append(n)
    return _deepest(hits)


def find_url_nodes(root: Tag, url: str) -> list[Tag]:
    tail = str(url).rstrip("/").split("/")[-1]
    if not tail:
        return []
    return [
        n
        for n in root.find_all("a", href=True)
        if str(n["href"]).rstrip("/").split("/")[-1] == tail
    ]


def _containing_card(title_node: Tag, record: dict[str, Any]) -> Tag | None:
    """Smallest ancestor of the title that also contains the record's price."""
    price = record.get("price")
    for anc in title_node.parents:
        if not isinstance(anc, Tag) or anc.name in ("html", "body", "[document]"):
            break
        if price is None:
            return anc  # no second anchor available; first real ancestor wins
        if find_price_nodes(anc, float(price)):
            return anc
    return None


# ---------------------------------------------------------------------------
# Selector generalization
# ---------------------------------------------------------------------------

def _classes(node: Tag) -> set[str]:
    return {c for c in (node.get("class") or []) if _CLASS_OK.match(c)}


def _data_attrs(node: Tag) -> set[str]:
    return {k for k in node.attrs if k.startswith("data-")}


def _shared_signature_selectors(nodes: list[Tag]) -> list[str]:
    """Candidate CSS selectors matching what all the nodes have in common."""
    if not nodes:
        return []
    tags = {n.name for n in nodes}
    cands: list[str] = []
    if len(tags) == 1:
        tag = nodes[0].name
        shared_cls = set.intersection(*(_classes(n) for n in nodes))
        if shared_cls:
            cands.append(tag + "." + ".".join(sorted(shared_cls)))
            for c in sorted(shared_cls):
                cands.append(f"{tag}.{c}")
        shared_data = set.intersection(*(_data_attrs(n) for n in nodes))
        for k in sorted(shared_data):
            cands.append(f"{tag}[{k}]")
        parents = [n.parent for n in nodes if isinstance(n.parent, Tag)]
        if len(parents) == len(nodes) and len({p.name for p in parents}) == 1:
            p_cls = set.intersection(*(_classes(p) for p in parents))
            if p_cls:
                cands.append(
                    f"{parents[0].name}.{sorted(p_cls)[0]} > {tag}"
                )
            else:
                cands.append(f"{parents[0].name} > {tag}")
        cands.append(tag)
    else:
        shared_cls = set.intersection(*(_classes(n) for n in nodes))
        for c in sorted(shared_cls):
            cands.append(f".{c}")
    seen: set[str] = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _score_selector(sel: str) -> float:
    """Stability heuristic used only to break validation ties."""
    score = 0.0
    if "[data-" in sel:
        score += 2.0
    score += 0.5 * sel.count(".")
    score -= 0.02 * len(sel)
    if ">" in sel:
        score -= 0.3
    return score


# ---------------------------------------------------------------------------
# Healing
# ---------------------------------------------------------------------------

def _anchor_records(
    soup: BeautifulSoup, golden: list[dict[str, Any]], anchor_field: str
) -> list[tuple[dict[str, Any], Tag, Tag]]:
    """Return (record, title_node, card) for every golden record we can pin."""
    anchored = []
    for rec in golden:
        title = rec.get(anchor_field)
        if not title:
            continue
        for tnode in find_title_nodes(soup, str(title)):
            card = _containing_card(tnode, rec)
            if card is not None:
                anchored.append((rec, tnode, card))
                break
    return anchored


def _validated_item_selector(
    soup: BeautifulSoup, cards: list[Tag], expected: int
) -> str | None:
    for cand in _shared_signature_selectors(cards):
        try:
            found = soup.select(cand)
        except Exception:
            continue
        if len(cards) <= len(found) <= max(expected * 3, len(cards) + 4):
            if all(any(f is c for f in found) for c in cards):
                return cand
    return None


def _field_nodes_for_record(
    card: Tag, rec: dict[str, Any], fspec: FieldSpec
) -> list[Tag]:
    val = rec.get(fspec.name)
    if val is None:
        return []
    if fspec.kind == "price":
        return find_price_nodes(card, float(val))
    if fspec.kind == "url":
        return find_url_nodes(card, str(val))
    return find_title_nodes(card, str(val))


def _validate_field(
    cards_with_recs: list[tuple[dict[str, Any], Tag]],
    field_name: str,
    selector: str,
    attr: str | None,
    kind: str,
) -> float:
    hits = 0
    for rec, card in cards_with_recs:
        want = rec.get(field_name)
        try:
            node = card.select_one(selector)
        except Exception:
            return 0.0
        raw = None
        if node is not None:
            raw = node.get(attr) if attr else node.get_text(" ", strip=True)
            if isinstance(raw, list):
                raw = " ".join(raw)
        got = coerce(raw, kind)
        if sentinel._values_match(kind, got, want):
            hits += 1
    return hits / len(cards_with_recs) if cards_with_recs else 0.0


def synthesize_field(
    cards_with_recs: list[tuple[dict[str, Any], Tag]], fspec: FieldSpec
) -> tuple[str, str | None, float, str] | None:
    """Return (selector, attr, match_rate, strategy) or None."""
    per_record_nodes: list[Tag] = []
    usable: list[tuple[dict[str, Any], Tag]] = []
    for rec, card in cards_with_recs:
        nodes = _field_nodes_for_record(card, rec, fspec)
        if nodes:
            per_record_nodes.append(nodes[0])
            usable.append((rec, card))
    if len(usable) < max(2, int(0.5 * len(cards_with_recs))):
        return None

    attr = "href" if fspec.kind == "url" else None
    candidates = _shared_signature_selectors(per_record_nodes)

    best: tuple[float, float, str] | None = None  # (match, stability, selector)
    for cand in candidates:
        rate = _validate_field(cards_with_recs, fspec.name, cand, attr, fspec.kind)
        if rate < MIN_FIELD_MATCH:
            continue
        key = (rate, _score_selector(cand), cand)
        if best is None or key > best:
            best = key
    if best is None:
        return None
    return best[2], attr, best[0], "record-anchored synthesis"


def propose_heal(
    html: str,
    old_spec: ExtractionSpec,
    golden: list[dict[str, Any]],
    source_id: str,
    base_url: str = "",
    anchor_field: str = "title",
) -> HealProposal | None:
    """Synthesize and validate a repaired spec, or return None if impossible."""
    soup = BeautifulSoup(html, "lxml")

    anchored = _anchor_records(soup, golden, anchor_field)
    if len(anchored) < 2:
        return None
    cards = [card for _, _, card in anchored]
    cards_with_recs = [(rec, card) for rec, _, card in anchored]

    item_selector = _validated_item_selector(soup, cards, expected=len(golden))
    if item_selector is None:
        return None

    new_fields: list[FieldSpec] = []
    diffs: list[FieldDiff] = []
    evidence: list[str] = [
        f"anchored {len(anchored)}/{len(golden)} golden records in the new DOM",
        f"item container generalized to `{item_selector}` "
        f"({len(soup.select(item_selector))} matches on page)",
    ]

    for f in old_spec.fields:
        syn = synthesize_field(cards_with_recs, f)
        if syn is None:
            if not f.required:
                continue
            return None
        selector, attr, rate, strategy = syn
        new_fields.append(
            FieldSpec(name=f.name, selector=selector, attr=attr, kind=f.kind, required=f.required)
        )
        diffs.append(
            FieldDiff(
                name=f.name,
                old_selector=f.selector,
                new_selector=selector,
                old_attr=f.attr,
                new_attr=attr,
                match_rate=round(rate, 3),
                strategy=strategy,
            )
        )
        evidence.append(
            f"field `{f.name}`: `{f.selector}` → `{selector}` "
            f"(validated against {rate:.0%} of anchored golden records)"
        )

    new_spec = ExtractionSpec(
        item_selector=item_selector,
        fields=new_fields,
        version=old_spec.version + 1,
        origin="heal",
    )

    # Sandbox self-test: run the candidate spec end-to-end before proposing.
    rows = extract(html, new_spec, base_url)
    validation: DriftReport = sentinel.assess(source_id, rows, new_spec, golden)
    if not validation.healthy:
        return None

    diffs.insert(
        0,
        FieldDiff(
            name="(item container)",
            old_selector=old_spec.item_selector,
            new_selector=item_selector,
            old_attr=None,
            new_attr=None,
            match_rate=round(len(anchored) / len(golden), 3),
            strategy="anchor containment",
        ),
    )

    return HealProposal(
        source_id=source_id,
        base_version=old_spec.version,
        new_spec=new_spec,
        diffs=diffs,
        validation=validation,
        evidence=evidence,
        sample_rows=rows[:6],
    )
