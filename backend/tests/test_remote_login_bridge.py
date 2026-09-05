import base64
from io import BytesIO

import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def admin_access(client):
    client.app.state.settings.announcement_admin_emails = ["admin@example.com"]


def _worker(client):
    enrollment = client.post(
        "/api/ecommerce/workers/enrollments",
        json={"workspace_id": "ws_test", "device_id": "remote-device"},
    ).json()["data"]
    return client.post(
        "/api/ecommerce/workers/register",
        json={
            "enrollment_token": enrollment["enrollment_token"],
            "device_id": "remote-device",
            "protocol_version": "worker.v1",
            "agent_version": "test",
            "capabilities": ["browser.taobao", "login.taobao"],
        },
    ).json()["data"]


def test_remote_login_job_claim_frame_and_ready(client):
    worker = _worker(client)
    account_response = client.post(
        "/api/ecommerce/accounts",
        json={
            "workspace_id": "ws_test",
            "platform": "taobao",
            "account_key": "remote-seller",
            "worker_id": worker["worker"]["id"],
        },
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()["data"]
    created = client.post(
        "/api/ecommerce/login-jobs",
        json={"account_id": account["id"], "worker_id": worker["worker"]["id"]},
    )
    assert created.status_code == 201, created.text
    job = created.json()["data"]["login_job"]
    assert job["state"] == "queued"

    headers = {"Authorization": f"Bearer {worker['session_token']}"}
    claimed = client.post(
        f"/api/ecommerce/workers/{worker['worker']['id']}/login-jobs/claim",
        headers=headers,
        json={"platforms": ["taobao"]},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["data"]["id"] == job["id"]

    output = BytesIO()
    Image.new("RGB", (1, 1), "white").save(output, format="JPEG")
    frame = base64.b64encode(output.getvalue()).decode("ascii")
    uploaded = client.post(
        f"/api/ecommerce/workers/{worker['worker']['id']}/login-jobs/{job['id']}/frames",
        headers=headers,
        json={"data": frame, "content_type": "image/jpeg", "sequence": 1},
    )
    assert uploaded.status_code == 200, uploaded.text
    preview = client.get(f"/api/ecommerce/session/preview?session_id={job['id']}")
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"

    ready = client.post(
        f"/api/ecommerce/workers/{worker['worker']['id']}/login-jobs/{job['id']}/state",
        headers=headers,
        json={"state": "ready"},
    )
    assert ready.status_code == 200, ready.text
    status = client.get(f"/api/ecommerce/login-jobs/{job['id']}")
    assert status.status_code == 200, status.text
    assert status.json()["data"]["state"] == "ready"


def test_remote_login_input_is_queued_for_the_owning_worker(client):
    worker = _worker(client)
    account = client.post(
        "/api/ecommerce/accounts",
        json={
            "workspace_id": "ws_test",
            "platform": "taobao",
            "account_key": "remote-input",
            "worker_id": worker["worker"]["id"],
        },
    ).json()["data"]
    job = client.post(
        "/api/ecommerce/login-jobs",
        json={"account_id": account["id"], "worker_id": worker["worker"]["id"]},
    ).json()["data"]["login_job"]
    headers = {"Authorization": f"Bearer {worker['session_token']}"}
    claimed = client.post(
        f"/api/ecommerce/workers/{worker['worker']['id']}/login-jobs/claim",
        headers=headers,
        json={"platforms": ["taobao"]},
    )
    assert claimed.status_code == 200

    input_response = client.post(
        "/api/ecommerce/session/input",
        json={
            "account_id": account["id"],
            "type": "text",
            "text": "example@example.com",
        },
    )
    assert input_response.status_code == 200, input_response.text
    control = client.get(
        f"/api/ecommerce/workers/{worker['worker']['id']}/login-jobs/{job['id']}/control",
        headers=headers,
    )
    assert control.status_code == 200
    assert control.json()["data"]["actions"] == [
        {"type": "text", "text": "example@example.com", "button": "left"}
    ]


def test_remote_login_rejects_bad_frame_and_offline_start(client):
    worker = _worker(client)
    account_response = client.post(
        "/api/ecommerce/accounts",
        json={
            "workspace_id": "ws_test",
            "platform": "taobao",
            "account_key": "offline-seller",
            "worker_id": worker["worker"]["id"],
        },
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()["data"]
    with client.app.state.session_factory() as session:
        from app.models import EcommerceWorkerRecord

        record = session.get(EcommerceWorkerRecord, worker["worker"]["id"])
        record.status = "offline"
        session.commit()
    response = client.post(
        "/api/ecommerce/login-jobs",
        json={"account_id": account["id"], "worker_id": worker["worker"]["id"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOCAL_WORKER_OFFLINE"
