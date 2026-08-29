from reweave import sentinel
from reweave.extractor import extract


def test_healthy_on_seed_era(html_v1, seed_spec, golden):
    rows = extract(html_v1, seed_spec)
    report = sentinel.assess("nimbusmart", rows, seed_spec, golden)
    assert report.healthy
    assert report.confidence > 0.95


def test_detects_structural_drift(html_v2, seed_spec, golden):
    rows = extract(html_v2, seed_spec)
    report = sentinel.assess("nimbusmart", rows, seed_spec, golden)
    assert not report.healthy
    assert report.confidence < 0.5
    assert report.failures  # named, human-readable failure reasons


def test_partial_breakage_is_still_drift(html_v1, seed_spec, golden):
    # Simulate a partial break: price selector rot only.
    broken = html_v1.replace('class="price-tag"', 'class="price-tag-old"')
    rows = extract(broken, seed_spec)
    report = sentinel.assess("nimbusmart", rows, seed_spec, golden)
    assert not report.healthy
    assert any("price" in f for f in report.failures)
