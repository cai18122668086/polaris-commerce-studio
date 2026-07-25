import asyncio
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.domain import OutboxStatus
from app.models import (
    JobAttemptRecord,
    OutboxEventRecord,
    UsageEventRecord,
    utc_now,
)
from app.outbox import publish_pending_events

WORKSPACE_ID = "ws_test"


def image_payload(
    size: tuple[int, int] = (96, 96),
    color: tuple[int, int, int] = (235, 197, 64),
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


def upload_asset(
    client: TestClient,
    *,
    filename: str = "product.png",
    media_kind: str = "image",
    key: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers={"Idempotency-Key": key or str(uuid4())},
        data={"origin_kind": "upload", "media_kind": media_kind},
        files={"file": (filename, image_payload(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def local_edit_payload(source_id: str, mask_id: str) -> dict:
    return {
        "type": "local_edit",
        "intent": "submit",
        "display_name": "蓝色耳机",
        "input": {
            "source_asset_id": source_id,
            "selection_mask_asset_id": mask_id,
        },
        "configuration": {
            "instruction": "将耳罩改为深蓝色",
            "quality": "balanced",
            "output_format": "png",
        },
    }


def create_local_edit_job(
    client: TestClient,
    source_id: str,
    mask_id: str,
    *,
    key: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=local_edit_payload(source_id, mask_id),
    )
    assert response.status_code == 202, response.text
    return response.json()


def dispatch_pending(client: TestClient) -> int:
    return publish_pending_events(
        client.app.state.settings,
        client.app.state.session_factory,
        client.app.state.task_runner,
    )


def test_health_identity_and_empty_collections(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    me = client.get("/api/v1/me")
    workspaces = client.get("/api/v1/workspaces")
    assets = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/assets")
    jobs = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs")

    assert live.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"
    assert me.json() == {"id": "usr_test"}
    assert workspaces.json()[0]["id"] == WORKSPACE_ID
    assert assets.json()["items"] == []
    assert jobs.json()["items"] == []


def test_upload_is_idempotent_private_and_accessible_by_signed_url(
    client: TestClient,
) -> None:
    key = str(uuid4())
    asset = upload_asset(client, key=key)
    replay = upload_asset(client, key=key)

    assert replay["id"] == asset["id"]
    assert asset["sha256"]
    assert "storage_key" not in asset
    assert "object_key" not in asset
    assert "storage_bucket" not in asset

    access = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{asset['id']}/access-url",
        json={"disposition": "inline", "variant": "original"},
    )
    assert access.status_code == 200
    content = client.get(access.json()["url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"


def test_upload_rejects_missing_idempotency_and_invalid_images(
    client: TestClient,
) -> None:
    missing_key = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        files={"file": ("product.png", image_payload(), "image/png")},
    )
    invalid = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers=idem(),
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_IMAGE"
    assert invalid.json()["error"]["request_id"].startswith("req_")


def test_idempotency_key_reuse_with_different_request_is_rejected(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="source.png")
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    key = str(uuid4())
    first = create_local_edit_job(client, source["id"], mask["id"], key=key)
    replay = create_local_edit_job(client, source["id"], mask["id"], key=key)
    assert first["id"] == replay["id"]

    changed = local_edit_payload(source["id"], mask["id"])
    changed["configuration"]["instruction"] = "改成红色"
    conflict = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": key},
        json=changed,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_job_uses_relational_items_outbox_and_exact_costs(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="source.png")
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    job = create_local_edit_job(client, source["id"], mask["id"])

    assert job["status"] == "queued"
    assert len(job["items"]) == 1
    assert {item["role"] for item in job["assets"]} == {
        "source",
        "selection_mask",
    }
    assert job["cost"]["estimated_min"]["micros"] == "40000"
    assert job["cost"]["actual"] is None

    assert dispatch_pending(client) == 1
    completed = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}").json()
    assert completed["status"] == "completed"
    assert completed["items"][0]["status"] == "succeeded"
    assert completed["cost"]["actual"]["micros"] == "0"
    assert completed["cost"]["actual_credits"] == 0

    # Redelivery is harmless: no second attempt or usage event is created.
    asyncio.run(client.app.state.task_runner.run(job["id"]))
    with client.app.state.session_factory() as session:
        attempts = session.scalar(
            select(func.count())
            .select_from(JobAttemptRecord)
            .where(JobAttemptRecord.job_id == job["id"])
        )
        usage_events = session.scalar(
            select(func.count())
            .select_from(UsageEventRecord)
            .where(UsageEventRecord.job_id == job["id"])
        )
    assert attempts == 1
    assert usage_events == 1


def test_cancel_is_terminal_and_retry_creates_a_new_job(client: TestClient) -> None:
    source = upload_asset(client, filename="source.png")
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    job = create_local_edit_job(client, source["id"], mask["id"])

    cancelled = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/cancel",
        headers=idem(),
        json={"reason": "用户主动取消"},
    )
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers=idem(),
        json={"scope": "full", "item_ids": []},
    )
    assert retried.status_code == 201
    assert retried.json()["id"] != job["id"]
    assert retried.json()["retry_of_job_id"] == job["id"]
    assert retried.json()["root_job_id"] == job["id"]


def test_detail_pack_stops_for_validated_plan_confirmation(
    client: TestClient,
) -> None:
    reference = upload_asset(client)
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "display_name": "耳机详情页",
            "input": {
                "product_groups": [
                    {"group_key": "product-1", "asset_ids": [reference["id"]]}
                ]
            },
            "configuration": {
                "product_name": "无线耳机",
                "selling_points": ["降噪", "长续航"],
                "platform_code": "amazon",
                "language": "zh-CN",
                "page_count": 3,
            },
        },
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    published = dispatch_pending(client)
    if published != 1:
        with client.app.state.session_factory() as session:
            event = session.scalar(
                select(OutboxEventRecord).where(
                    OutboxEventRecord.aggregate_id == job_id
                )
            )
            failure = event.last_error if event else "missing outbox event"
        raise AssertionError(f"plan dispatch failed: {failure}")
    planned = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}").json()
    assert planned["status"] == "awaiting_confirmation"
    assert planned["plan"]["validation_status"] == "valid"
    assert len(planned["plan"]["payload"]["pages"]) == 3

    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 202
    dispatch_pending(client)
    completed = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}").json()
    assert completed["status"] == "completed"
    assert completed["succeeded_item_count"] == 3


def test_missing_assets_and_unknown_workspace_do_not_leak(client: TestClient) -> None:
    unknown_workspace = client.get("/api/v1/workspaces/ws_unknown/assets")
    assert unknown_workspace.status_code == 404
    assert unknown_workspace.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

    missing = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "local_edit",
            "intent": "submit",
            "input": {
                "source_asset_id": "asset_missing",
                "selection_mask_asset_id": "asset_missing_mask",
            },
            "configuration": {
                "instruction": "修改颜色",
                "quality": "balanced",
                "output_format": "png",
            },
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "INPUT_ASSET_NOT_FOUND"


def test_outbox_failure_stays_recoverable(client: TestClient) -> None:
    source = upload_asset(client, filename="source.png")
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    job = create_local_edit_job(client, source["id"], mask["id"])

    with client.app.state.session_factory() as session:
        event = session.scalar(
            select(OutboxEventRecord).where(OutboxEventRecord.aggregate_id == job["id"])
        )
        assert event is not None
        assert event.status == OutboxStatus.PENDING.value
        event.status = OutboxStatus.PUBLISHING.value
        event.locked_at = utc_now() - timedelta(minutes=6)
        event.locked_by = "dead-dispatcher"
        session.commit()

    assert dispatch_pending(client) == 1

    with client.app.state.session_factory() as session:
        event = session.scalar(
            select(OutboxEventRecord).where(OutboxEventRecord.aggregate_id == job["id"])
        )
        assert event is not None
        assert event.status == OutboxStatus.PUBLISHED.value
        assert event.attempt_count == 1
