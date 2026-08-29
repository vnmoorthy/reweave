"""Full lifecycle through the HTTP control plane:

healthy → chaos (redesign ships) → drift detected → repair proposed →
human approves at the gate → pipeline healthy again on the new spec →
impact booked to the ledger.
"""

from fastapi.testclient import TestClient

from reweave.server import app


def test_full_healing_lifecycle():
    with TestClient(app) as client:
        client.post("/api/reset")

        # 1. Seed era: pipeline is healthy.
        r = client.post("/api/run/nimbusmart").json()
        assert r["report"]["healthy"]
        assert r["spec_version"] == 1

        # 2. The target site ships a redesign overnight.
        assert client.post("/api/chaos").json()["demo_variant"] == "v2"

        # 3. Drift is detected; the Surgeon parks a repair at the gate.
        r = client.post("/api/run/nimbusmart").json()
        assert not r["report"]["healthy"]
        assert r["proposal"] is not None
        pid = r["proposal"]["id"]
        assert r["proposal"]["status"] == "pending"

        # 3b. Nothing deploys without approval: rerun still uses v1 and stays broken.
        r = client.post("/api/run/nimbusmart").json()
        assert r["spec_version"] == 1
        assert not r["report"]["healthy"]

        # 4. A human approves the repair (with accountability).
        approved = client.post(
            f"/api/heal/{pid}/approve", json={"actor": "demo-judge"}
        ).json()
        assert approved["status"] == "approved"

        # 5. Healthy again on spec v2, no human wrote a selector.
        r = client.post("/api/run/nimbusmart").json()
        assert r["report"]["healthy"]
        assert r["spec_version"] == 2

        # 6. Impact is on the ledger.
        state = client.get("/api/state").json()
        assert state["impact"]["heals"] == 1
        assert state["impact"]["dollars_saved"] > 0
        assert state["sources"][0]["status"] == "healthy"


def test_reject_leaves_old_spec_active():
    with TestClient(app) as client:
        client.post("/api/reset")
        client.post("/api/run/nimbusmart")
        client.post("/api/chaos")
        r = client.post("/api/run/nimbusmart").json()
        pid = r["proposal"]["id"]

        rejected = client.post(
            f"/api/heal/{pid}/reject", json={"actor": "demo-judge", "reason": "want a second look"}
        ).json()
        assert rejected["status"] == "rejected"

        r = client.post("/api/run/nimbusmart").json()
        assert r["spec_version"] == 1  # nothing deployed
        # A fresh proposal is synthesized on the next run after a rejection.
        assert r["proposal"] is not None and r["proposal"]["id"] != pid


def test_double_approve_is_conflict():
    with TestClient(app) as client:
        client.post("/api/reset")
        client.post("/api/run/nimbusmart")
        client.post("/api/chaos")
        pid = client.post("/api/run/nimbusmart").json()["proposal"]["id"]
        assert client.post(f"/api/heal/{pid}/approve", json={"actor": "a"}).status_code == 200
        assert client.post(f"/api/heal/{pid}/approve", json={"actor": "a"}).status_code == 409
