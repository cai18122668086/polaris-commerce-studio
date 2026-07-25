import asyncio
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

WORKSPACE_ID = "workspace-demo"


def image_payload(
    size: tuple[int, int] = (96, 96),
    color: tuple[int, int, int] = (235, 197, 64),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def upload_asset(client: TestClient, filename: str = "product.png") -> dict:
    response = client.post(
        "/api/assets",
        data={"workspace_id": WORKSPACE_ID, "origin": "upload"},
        files={"file": (filename, image_payload(), "image/png")},
    )
    assert response.status_code == 201
    return response.json()


def create_local_edit_job(client: TestClient, asset_id: str) -> dict:
    response = client.post(
        "/api/jobs",
        json={
            "type": "local_edit",
            "workspace_id": WORKSPACE_ID,
            "input_asset_ids": [asset_id],
            "configuration": {
                "quality": "balanced",
                "selection_coverage": 0.124,
            },
            "estimated_cost": 2,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_health_and_empty_collections(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["task_runner"] == "mock"

    assets = client.get("/api/assets", params={"workspace_id": WORKSPACE_ID})
    jobs = client.get("/api/jobs", params={"workspace_id": WORKSPACE_ID})
    assert assets.json() == {"items": [], "total": 0}
    assert jobs.json() == {"items": [], "total": 0}


def test_upload_validates_and_persists_image_metadata(client: TestClient) -> None:
    asset = upload_asset(client)
    assert asset["filename"] == "product.png"
    assert asset["content_type"] == "image/png"
    assert asset["width"] == 96
    assert asset["height"] == 96
    assert asset["storage_key"].startswith(f"{WORKSPACE_ID}/")

    fetched = client.get(f"/api/assets/{asset['id']}")
    listed = client.get(
        "/api/assets",
        params={"workspace_id": WORKSPACE_ID, "origin": "upload"},
    )
    assert fetched.status_code == 200
    assert listed.json()["total"] == 1


def test_upload_rejects_non_image_payload(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        data={"workspace_id": WORKSPACE_ID},
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


def test_workspace_id_rejects_path_characters(client: TestClient) -> None:
    response = client.post(
        "/api/assets",
        data={"workspace_id": "../workspace"},
        files={"file": ("product.png", image_payload(), "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_job_lifecycle_cancel_and_retry(client: TestClient) -> None:
    asset = upload_asset(client)
    job = create_local_edit_job(client, asset["id"])
    assert job["status"] == "queued"
    assert job["progress"] == 0
    assert job["api_request_count"] == 0

    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.status_code == 201
    assert retried.json()["status"] == "queued"
    assert retried.json()["retry_of_job_id"] == job["id"]
    assert retried.json()["parent_job_id"] == job["id"]


def test_mock_runner_completes_without_external_api_usage(
    client: TestClient,
) -> None:
    asset = upload_asset(client)
    job = create_local_edit_job(client, asset["id"])

    asyncio.run(client.app.state.task_runner.run(job["id"]))
    completed = client.get(f"/api/jobs/{job['id']}")
    payload = completed.json()

    assert payload["status"] == "completed"
    assert payload["progress"] == 100
    assert payload["api_request_count"] == 0
    assert payload["actual_cost"] == 0
    assert payload["usage"]["reported"] is False
    assert payload["raw_outputs"][0]["kind"] == "phase1_mock_result"


def test_job_rejects_missing_or_invalid_asset_groups(client: TestClient) -> None:
    missing = client.post(
        "/api/jobs",
        json={
            "type": "local_edit",
            "workspace_id": WORKSPACE_ID,
            "input_asset_ids": ["asset_missing"],
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "INPUT_ASSET_NOT_FOUND"

    invalid_group = client.post(
        "/api/jobs",
        json={
            "type": "detail_pack",
            "workspace_id": WORKSPACE_ID,
            "input_asset_ids": [],
        },
    )
    assert invalid_group.status_code == 422
    assert invalid_group.json()["error"]["code"] == "VALIDATION_ERROR"


def test_queue_failure_marks_job_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = upload_asset(client)
    client.app.state.settings.auto_process_jobs = True
    client.app.state.settings.task_dispatcher = "celery"

    def unavailable(_: str) -> None:
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr("app.tasks.process_job.delay", unavailable)
    response = client.post(
        "/api/jobs",
        json={
            "type": "local_edit",
            "workspace_id": WORKSPACE_ID,
            "input_asset_ids": [asset["id"]],
        },
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "TASK_QUEUE_UNAVAILABLE"
    failed = client.get(f"/api/jobs/{error['details']['job_id']}").json()
    assert failed["status"] == "failed"
    assert failed["error_code"] == "TASK_QUEUE_UNAVAILABLE"
