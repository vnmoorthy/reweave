"""The product surface: zero-selector onboarding, stored runs, export, autopilot."""

from fastapi.testclient import TestClient

from reweave import registry, surgeon
from reweave.extractor import extract
from reweave.server import app


def test_bootstrap_spec_from_examples_alone(html_v1, golden):
    proposal = surgeon.bootstrap_spec(html_v1, golden, "newsource")
    assert proposal is not None
    assert proposal.new_spec.version == 1
    assert proposal.new_spec.origin == "bootstrap"
    rows = extract(html_v1, proposal.new_spec)
    assert len(rows) == len(golden)
    titles = {r["title"] for r in rows}
    assert {g["title"] for g in golden} <= titles


def test_bootstrap_anchors_attribute_carried_values():
    # Real-world pattern (books.toscrape.com): visible link text is truncated,
    # the full title lives in the anchor's `title` attribute.
    html = """
    <html><body><section>
      <article class="pod"><h3><a class="tl" title="A Light in the Attic" href="/c/a-light_1">A Light in the ...</a></h3><p class="amt">£51.77</p></article>
      <article class="pod"><h3><a class="tl" title="Tipping the Velvet" href="/c/tipping_2">Tipping the ...</a></h3><p class="amt">£53.74</p></article>
      <article class="pod"><h3><a class="tl" title="Sharp Objects" href="/c/sharp_3">Sharp ...</a></h3><p class="amt">£47.82</p></article>
    </section></body></html>
    """
    golden = [
        {"title": "A Light in the Attic", "price": 51.77, "url": "/c/a-light_1"},
        {"title": "Tipping the Velvet", "price": 53.74, "url": "/c/tipping_2"},
        {"title": "Sharp Objects", "price": 47.82, "url": "/c/sharp_3"},
    ]
    proposal = surgeon.bootstrap_spec(html, golden, "books")
    assert proposal is not None, "attribute-carried titles must be anchorable"
    title_field = proposal.new_spec.field_map()["title"]
    assert title_field.attr == "title"
    rows = extract(html, proposal.new_spec)
    assert {r["title"] for r in rows} == {g["title"] for g in golden}
    assert {r["price"] for r in rows} == {g["price"] for g in golden}


def test_bootstrap_refuses_unanchorable_page(golden):
    html = "<html><body><p>nothing to see here</p></body></html>"
    assert surgeon.bootstrap_spec(html, golden, "x") is None
    assert surgeon.bootstrap_spec("<html></html>", golden[:1], "x") is None  # <2 examples


def test_onboard_export_delete_lifecycle(golden):
    with TestClient(app) as client:
        client.post("/api/reset")

        # Onboard a second source against the same live demo page — golden
        # examples in, validated spec out, zero selectors written.
        r = client.post(
            "/api/sources",
            json={"url": "demo://nimbusmart", "name": "Shadow Fleet", "golden": golden[:4]},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["source_id"]
        assert r.json()["report"]["healthy"]
        assert r.json()["spec"]["origin"] == "bootstrap"

        # The data is stored and exportable.
        rows = client.get(f"/api/sources/{sid}/rows").json()
        assert rows["row_count"] == 8
        assert rows["rows"][0]["title"]
        csv_text = client.get(f"/api/sources/{sid}/rows?fmt=csv").text
        assert csv_text.splitlines()[0] == "title,price,url"
        assert len(csv_text.splitlines()) == 9  # header + 8 rows

        history = client.get(f"/api/sources/{sid}/history").json()
        assert len(history) == 1 and history[0]["healthy"]

        # Sources are removable.
        assert client.delete(f"/api/sources/{sid}").status_code == 200
        assert client.get(f"/api/sources/{sid}/rows").status_code == 404


def test_onboarding_rejects_bad_input():
    with TestClient(app) as client:
        client.post("/api/reset")
        assert client.post("/api/sources", json={"url": "", "golden": []}).status_code == 422
        assert (
            client.post(
                "/api/sources", json={"url": "demo://nimbusmart", "golden": [{"title": "x"}]}
            ).status_code
            == 422
        )
        r = client.post(
            "/api/sources",
            json={
                "url": "demo://nimbusmart",
                "golden": [{"title": "Not On Page"}, {"title": "Also Missing"}],
            },
        )
        assert r.status_code == 422
        assert "anchor" in r.json()["detail"]


def test_runs_are_recorded_and_pruned():
    with TestClient(app) as client:
        client.post("/api/reset")
        for _ in range(registry.RUNS_KEPT_PER_SOURCE + 5):
            client.post("/api/run/nimbusmart")
        history = client.get("/api/sources/nimbusmart/history").json()
        assert len(history) == registry.RUNS_KEPT_PER_SOURCE


def test_autopilot_toggle():
    with TestClient(app) as client:
        client.post("/api/reset")
        assert client.get("/api/state").json()["autopilot"]["enabled"] is True
        client.post("/api/autopilot", json={"enabled": False})
        assert client.get("/api/state").json()["autopilot"]["enabled"] is False
        client.post("/api/autopilot", json={"enabled": True})
        assert client.get("/api/state").json()["autopilot"]["enabled"] is True
