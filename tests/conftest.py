import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own SQLite registry."""
    monkeypatch.setenv("REWEAVE_DB", str(tmp_path / "reweave.db"))
    yield


@pytest.fixture
def golden():
    return json.loads((REPO / "demo" / "golden.json").read_text())


@pytest.fixture
def html_v1():
    return (REPO / "demo" / "site_v1" / "index.html").read_text()


@pytest.fixture
def html_v2():
    return (REPO / "demo" / "site_v2" / "index.html").read_text()


@pytest.fixture
def html_v3():
    return (REPO / "demo" / "site_v3" / "index.html").read_text()


@pytest.fixture
def seed_spec():
    from reweave.models import ExtractionSpec, FieldSpec

    return ExtractionSpec(
        item_selector="div.product-card",
        fields=[
            FieldSpec("title", "h3.product-name", None, "text"),
            FieldSpec("price", "span.price-tag", None, "price"),
            FieldSpec("url", "a.product-link", "href", "url"),
        ],
        version=1,
    )
