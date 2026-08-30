"""Operational surface: health, metrics, rollback, bearer auth, webhooks."""

from fastapi.testclient import TestClient

from reweave import notify
from reweave.server import app


def _drive_to_healed(client):
    client.post("/api/reset")
    client.post("/api/run/nimbusmart")
    client.post("/api/chaos")
    pid = client.post("/api/run/nimbusmart").json()["proposal"]["id"]
    client.post(f"/api/heal/{pid}/approve", json={"actor": "ops-test"})
    client.post("/api/run/nimbusmart")


def test_health_endpoint():
    with TestClient(app) as client:
        client.post("/api/reset")
        h = client.get("/api/health").json()
        assert h["status"] == "ok"
        assert h["sources"] >= 1
        assert h["uptime_s"] >= 0
        assert "version" in h


def test_metrics_prometheus_format():
    with TestClient(app) as client:
        _drive_to_healed(client)
        r = client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        text = r.text
        assert "reweave_up 1" in text
        assert "# TYPE reweave_heals_deployed_total counter" in text
        assert "reweave_heals_deployed_total 1" in text
        assert "reweave_sources_healthy 1" in text
        assert "reweave_runs_total" in text


def test_rollback_moves_pointer_and_audits():
    with TestClient(app) as client:
        _drive_to_healed(client)
        assert client.get("/api/state").json()["sources"][0]["active_version"] == 2

        # No anonymous rollbacks.
        assert client.post("/api/sources/nimbusmart/rollback", json={}).status_code == 422

        r = client.post(
            "/api/sources/nimbusmart/rollback", json={"actor": "ops-test"}
        )
        assert r.status_code == 200 and r.json()["active_version"] == 1
        state = client.get("/api/state").json()
        assert state["sources"][0]["active_version"] == 1
        assert any("rolled back spec v2 → v1" in e["message"] for e in state["events"])

        # Rolling back to the already-active version is a conflict;
        # unknown versions are a 404.
        assert (
            client.post(
                "/api/sources/nimbusmart/rollback",
                json={"actor": "ops-test", "to_version": 1},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/sources/nimbusmart/rollback",
                json={"actor": "ops-test", "to_version": 99},
            ).status_code
            == 404
        )


def test_bearer_auth_guards_api(monkeypatch):
    monkeypatch.setenv("REWEAVE_API_TOKEN", "s3cret")
    with TestClient(app) as client:
        assert client.get("/api/state").status_code == 401
        assert client.post("/api/run/nimbusmart").status_code == 401
        # Health stays open for load balancers; the dashboard page still serves.
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        ok = client.get("/api/state", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200


def test_webhooks_fire_on_lifecycle_events(monkeypatch):
    calls = []

    class FakeResp:
        status_code = 200

    monkeypatch.setenv("REWEAVE_WEBHOOK_URL", "https://hooks.example.test/reweave")
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kw: calls.append((url, kw["json"])) or FakeResp())

    with TestClient(app) as client:
        _drive_to_healed(client)
        client.post("/api/sources/nimbusmart/rollback", json={"actor": "ops-test"})

    events = [payload["event"] for _, payload in calls]
    assert "drift_detected" in events
    assert "heal_pending" in events
    assert "heal_approved" in events
    assert "rollback" in events
    url, payload = calls[0]
    assert url == "https://hooks.example.test/reweave"
    assert payload["source_id"] == "nimbusmart"
    assert payload["text"].startswith("reweave: ")


def test_webhook_failure_never_breaks_the_run(monkeypatch):
    monkeypatch.setenv("REWEAVE_WEBHOOK_URL", "https://hooks.example.test/reweave")

    def explode(*a, **kw):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr(notify.httpx, "post", explode)
    with TestClient(app) as client:
        client.post("/api/reset")
        client.post("/api/chaos")
        r = client.post("/api/run/nimbusmart")
        assert r.status_code == 200  # drift + webhook failure, run still completes
        assert r.json()["proposal"] is not None
