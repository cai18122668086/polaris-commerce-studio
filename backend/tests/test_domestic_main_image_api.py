from __future__ import annotations

import hashlib
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from app.domestic_main_image_models import (
    DomesticMainImageCommandRecord,
    DomesticMainImageGenerationRecord,
    DomesticMainImageTaskRecord,
)

WORKSPACE_ID = "ws_test"


def _png() -> bytes:
    image = Image.new("RGB", (1024, 1024), "#ece5d8")
    draw = ImageDraw.Draw(image)
    draw.ellipse((190, 120, 834, 764), fill="#cb4b35")
    draw.rounded_rectangle((360, 680, 664, 930), radius=42, fill="#f7f2e9")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _upload(client: TestClient) -> dict[str, object]:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers={"Idempotency-Key": "main-image-source-fixture"},
        files={"file": ("product.png", _png(), "image/png")},
        data={"media_kind": "image", "origin_kind": "upload"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_zero_cost_api_reaches_first_generation_contract_without_provider_call(
    client: TestClient,
) -> None:
    asset = _upload(client)
    create_payload = {
        "product_name": "桌面循环扇",
        "category": "小家电",
        "product_information": "红白配色，单个扇头，额定电压 5V。",
        "verified_attributes": {"额定电压": "5V"},
        "verified_selling_points": [
            "三档风速",
            "上下角度可调",
            "可拆洗前网罩",
            "USB-C 供电",
            "桌面小体积",
            "红白双色机身",
        ],
        "sources": [{"asset_id": asset["id"], "role": "primary"}],
    }
    created = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks",
        headers={"Idempotency-Key": "main-image-task-fixture"},
        json=create_payload,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["skill_state"] == "AWAITING_IDENTITY"
    replay = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks",
        headers={"Idempotency-Key": "main-image-task-fixture"},
        json=create_payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == task["id"]

    identity = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks/{task['id']}/identity",
        json={
            "expected_revision": task["revision"],
            "identity_contract": {
                "product_form": "圆形扇头连接圆角矩形底座",
                "identity_summary": "红色外框、白色中心、单扇头单底座",
                "must_preserve": ["单扇头与单底座连接", "红白色块关系"],
                "must_not_change": ["不得增加扇头", "不得改变红白配色"],
            },
        },
    )
    assert identity.status_code == 200, identity.text
    planned = identity.json()
    assert planned["skill_state"] == "AWAITING_AUTHORIZATION"
    assert len(planned["plan"]) == 6

    authorized = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks/{task['id']}/authorize",
        json={
            "expected_revision": planned["revision"],
            "approval_text": "我确认六图规划",
        },
    )
    assert authorized.status_code == 200, authorized.text
    ready = authorized.json()
    assert ready["skill_state"] == "AWAITING_GENERATED_ASSET"
    assert ready["generation_request_ready"] is True
    assert ready["reference_roles"] == ["PRODUCT_IDENTITY_AUTHORITY"]
    assert ready["edit_target_role"] == "PRODUCT_IDENTITY_AUTHORITY"

    with client.app.state.session_factory() as session:
        stored = session.get(DomesticMainImageTaskRecord, task["id"])
        assert stored is not None
        request = stored.generation_request
        assert request is not None
        expected_prompt_hash = hashlib.sha256(
            request["prompt"].encode("utf-8")
        ).hexdigest()
        assert request["prompt_sha256"] == expected_prompt_hash
        assert (
            session.scalar(select(func.count(DomesticMainImageGenerationRecord.id)))
            == 0
        )
        commands = session.scalars(
            select(DomesticMainImageCommandRecord)
            .where(DomesticMainImageCommandRecord.task_id == task["id"])
            .order_by(DomesticMainImageCommandRecord.sequence)
        ).all()
        assert [item.command for item in commands] == [
            "start",
            "lock-identity",
            "compile-v013",
            "authorize",
            "generate-next",
        ]
        assert all(
            item.exit_code == 0 and item.transition_committed for item in commands
        )


def test_stale_revision_cannot_advance_task_twice(client: TestClient) -> None:
    asset = _upload(client)
    created = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks",
        headers={"Idempotency-Key": "main-image-stale-fixture"},
        json={
            "product_name": "桌面循环扇",
            "category": "小家电",
            "product_information": "红白配色，单扇头。",
            "verified_selling_points": ["三档风速"],
            "sources": [{"asset_id": asset["id"], "role": "primary"}],
        },
    ).json()
    identity_payload = {
        "expected_revision": 0,
        "identity_contract": {
            "product_form": "圆形扇头连接圆角矩形底座",
            "identity_summary": "红色外框、白色中心、单扇头单底座",
            "must_preserve": ["单扇头与单底座连接"],
            "must_not_change": ["不得增加扇头"],
        },
    }
    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks/{created['id']}/identity",
        json=identity_payload,
    )
    assert first.status_code == 200
    stale = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/domestic-main-image/tasks/{created['id']}/identity",
        json=identity_payload,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_SESSION_REVISION"
