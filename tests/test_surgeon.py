from reweave import sentinel, surgeon
from reweave.extractor import extract


def _assert_heals(html, spec, golden):
    proposal = surgeon.propose_heal(html, spec, golden, "nimbusmart")
    assert proposal is not None, "Surgeon failed to synthesize a validated repair"
    assert proposal.validation.healthy
    assert proposal.new_spec.version == spec.version + 1
    rows = extract(html, proposal.new_spec)
    report = sentinel.assess("nimbusmart", rows, proposal.new_spec, golden)
    assert report.healthy
    for diff in proposal.diffs:
        assert diff.match_rate >= 0.75
    return proposal


def test_heals_full_redesign(html_v2, seed_spec, golden):
    proposal = _assert_heals(html_v2, seed_spec, golden)
    names = {d.name for d in proposal.diffs}
    assert {"(item container)", "title", "price", "url"} <= names
    # The healed spec must dodge the strikethrough was-price decoys.
    rows = extract(html_v2, proposal.new_spec)
    by_title = {r["title"]: r for r in rows}
    for g in golden:
        assert abs(by_title[g["title"]]["price"] - g["price"]) < 0.01


def test_heals_second_redesign_from_healed_spec(html_v2, html_v3, seed_spec, golden):
    first = _assert_heals(html_v2, seed_spec, golden)
    second = _assert_heals(html_v3, first.new_spec, golden)
    assert second.new_spec.version == 3


def test_refuses_to_heal_when_facts_are_gone(seed_spec, golden):
    # A page with none of the golden facts on it must not produce a proposal.
    html = "<html><body><div class='x'><p>Totally unrelated content</p></div></body></html>"
    assert surgeon.propose_heal(html, seed_spec, golden, "nimbusmart") is None


def test_evidence_and_samples_attached(html_v2, seed_spec, golden):
    proposal = surgeon.propose_heal(html_v2, seed_spec, golden, "nimbusmart")
    assert proposal.evidence
    assert proposal.sample_rows
    assert all("title" in r for r in proposal.sample_rows)
