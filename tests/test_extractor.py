from reweave.extractor import extract, parse_price


def test_extracts_all_products_from_seed_era(html_v1, seed_spec, golden):
    rows = extract(html_v1, seed_spec)
    assert len(rows) == len(golden)
    titles = {r["title"] for r in rows}
    assert {g["title"] for g in golden} <= titles
    by_title = {r["title"]: r for r in rows}
    for g in golden:
        assert abs(by_title[g["title"]]["price"] - g["price"]) < 0.01


def test_seed_spec_dies_on_redesign(html_v2, seed_spec):
    rows = extract(html_v2, seed_spec)
    assert rows == []  # every v1 selector is gone after the redesign


def test_price_parsing_formats():
    assert parse_price("$1,299.00") == 1299.0
    assert parse_price("1.299,00 €") == 1299.0
    assert parse_price("USD 12.99") == 12.99
    assert parse_price("129") == 129.0
    assert parse_price("free") is None
    assert parse_price("") is None
    assert parse_price("$449.99 $379.99") is None  # concatenated decoy must not parse
