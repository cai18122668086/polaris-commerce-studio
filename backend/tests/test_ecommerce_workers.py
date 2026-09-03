from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import EcommerceWorkerRecord


def _enroll(client, device_id="device-test"):
    response = client.post(
        "/api/ecommerce/workers/enrollments",
        json={"workspace_id": "ws_test", "device_id": device_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_worker_registration_is_scope_bound_and_one_time(client):
    enrollment = _enroll(client)
    payload = {
        "enrollment_token": enrollment["enrollment_token"],
        "device_id": "device-test",
        "protocol_version": "worker.v1",
        "agent_version": "0.1.0",
        "capabilities": ["browser.taobao", "login.taobao"],
    }
    registered = client.post("/api/ecommerce/workers/register", json=payload)
    assert registered.status_code == 201, registered.text
    data = registered.json()["data"]
    assert data["worker"]["status"] == "online"
    assert data["worker"]["capabilities"] == ["browser.taobao", "login.taobao"]
    assert "session_token_hash" not in data["worker"]

    replay = client.post("/api/ecommerce/workers/register", json=payload)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "WORKER_ENROLLMENT_INVALID"


def test_worker_protocol_rejects_sensitive_or_unknown_fields(client):
    enrollment = _enroll(client, "device-strict")
    payload = {
        "enrollment_token": enrollment["enrollment_token"],
        "device_id": "device-strict",
        "protocol_version": "worker.v1",
        "agent_version": "0.1.0",
        "capabilities": [],
        "cookies": "must-not-be-accepted",
    }
    response = client.post("/api/ecommerce/workers/register", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_worker_heartbeat_and_expiry_are_explicit(client):
    enrollment = _enroll(client, "device-heartbeat")
    registered = client.post(
        "/api/ecommerce/workers/register",
        json={
            "enrollment_token": enrollment["enrollment_token"],
            "device_id": "device-heartbeat",
            "protocol_version": "worker.v1",
            "agent_version": "0.1.0",
            "capabilities": ["browser.taobao"],
        },
    )
    data = registered.json()["data"]
    heartbeat = client.post(
        f"/api/ecommerce/workers/{data['worker']['id']}/heartbeat",
        headers={"Authorization": f"Bearer {data['session_token']}"},
        json={
            "protocol_version": "worker.v1",
            "agent_version": "0.1.1",
            "ready": True,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["data"]["status"] == "online"

    with client.app.state.session_factory() as session:
        worker = session.scalar(
            select(EcommerceWorkerRecord).where(
                EcommerceWorkerRecord.id == data["worker"]["id"]
            )
        )
        assert worker is not None
        worker.last_seen_at = datetime.now(UTC) - timedelta(seconds=1000)
        session.commit()
    listed = client.get("/api/ecommerce/workers", params={"workspace_id": "ws_test"})
    assert listed.status_code == 200
    assert listed.json()["data"][0]["status"] == "offline"
    assert listed.json()["data"][0]["error_code"] == "WORKER_OFFLINE"
