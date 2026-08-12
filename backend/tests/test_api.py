import asyncio
import hashlib
import json
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain import (
    JobItemStatus,
    JobStatus,
    JobType,
    OutboxStatus,
    PlanValidationStatus,
)
from app.main import create_app
from app.model_pose_catalog import resolve_model_pose_catalog_item
from app.models import (
    AssetRecord,
    AuditEventRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    OutboxEventRecord,
    UsageEventRecord,
    WorkspaceCreditAccountRecord,
    utc_now,
)
from app.outbox import publish_pending_events
from app.routes_v1 import runtime_status_response
from app.services import set_credit_enforcement_enabled, set_quota_enabled

WORKSPACE_ID = "ws_test"


def image_payload(
    size: tuple[int, int] = (96, 96),
    color: tuple[int, int, int] = (235, 197, 64),
    image_format: str = "PNG",
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
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
    assert me.json() == {
        "id": "usr_test",
        "email": None,
        "display_name": "Development User",
        "status": "active",
        "email_verified": True,
    }
    assert workspaces.json()[0]["id"] == WORKSPACE_ID
    assert assets.json()["items"] == []
    assert jobs.json()["items"] == []


def test_catalog_pose_keeps_object_when_commit_succeeds_but_reports_failure(
    client: TestClient,
) -> None:
    pose = resolve_model_pose_catalog_item(
        "female-001",
        next(
            item["referenceSha256"]
            for item in json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "catalog_assets"
                    / "model-pose-transfer"
                    / "catalog.json"
                ).read_text(encoding="utf-8")
            )["items"]
            if item["slug"] == "female-001"
        ),
    )
    original_factory = client.app.state.session_factory
    failure_raised = False

    class CommitSucceededButRaisedSession(Session):
        def commit(self) -> None:
            nonlocal failure_raised
            should_raise = not failure_raised and any(
                isinstance(record, AssetRecord)
                and record.asset_metadata.get("catalog_id")
                == "ecommerce-model-pose-transfer"
                for record in self.identity_map.values()
            )
            super().commit()
            if should_raise:
                failure_raised = True
                raise RuntimeError("simulated lost commit acknowledgement")

    client.app.state.session_factory = sessionmaker(
        bind=client.app.state.engine,
        class_=CommitSucceededButRaisedSession,
        expire_on_commit=False,
    )
    try:
        response = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/model-pose-transfer/pose-assets",
            headers=idem(),
            json={
                "pose_slug": pose.slug,
                "reference_sha256": pose.reference_sha256,
            },
        )
    finally:
        client.app.state.session_factory = original_factory

    assert response.status_code == 201, response.text
    assert failure_raised is True
    asset = response.json()
    with original_factory() as verification_session:
        committed = verification_session.get(AssetRecord, asset["id"])
        assert committed is not None
        stored_path = client.app.state.storage.root / committed.object_key
    assert stored_path.exists()
    assert stored_path.read_bytes() == pose.read_original()


def test_real_provider_switches_default_to_fail_closed(settings) -> None:
    assert settings.product_image_provider_enabled is False
    assert settings.reference_remix_provider_enabled is False
    assert settings.model_pose_transfer_provider_enabled is False
    assert settings.creative_image_provider_enabled is False
    assert settings.amazon_visual_suite_provider_enabled is False
    assert settings.crossborder_detail_provider_enabled is False


def test_runtime_capabilities_report_mock_and_tengli_execution(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/runtime")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "test",
        "authentication_mode": "development",
        "task_runner": "mock",
        "capabilities": {
            "features": {
                feature: {
                    "availability": "available",
                    "execution": "mock",
                    "reason_code": "TASK_RUNNER_MOCK",
                }
                for feature in (
                    "local_edit",
                    "product_image",
                    "reference_remix",
                    "model_pose_transfer",
                    "creative_image",
                    "detail_pack",
                    "amazon_visual_suite",
                    "domestic_main_image",
                )
            },
            "asset_management": {
                "availability": "available",
                "execution": "local",
                "reason_code": None,
            },
            "local_edit": {
                "availability": "available",
                "execution": "mock",
                "reason_code": "TASK_RUNNER_MOCK",
            },
            "detail_pack": {
                "availability": "available",
                "execution": "mock",
                "reason_code": "TASK_RUNNER_MOCK",
            },
            "external_authentication": {
                "availability": "unavailable",
                "execution": "none",
                "reason_code": "EXTERNAL_AUTHENTICATION_NOT_IMPLEMENTED",
            },
        },
    }

    tengli = runtime_status_response(
        environment="production",
        authentication_mode="external",
        task_runner="tengli",
    )
    assert tengli.capabilities.local_edit.execution == "provider"
    assert tengli.capabilities.local_edit.reason_code is None
    assert tengli.capabilities.detail_pack.execution == "provider"
    assert tengli.capabilities.detail_pack.reason_code is None
    for feature in (
        "product_image",
        "reference_remix",
        "model_pose_transfer",
        "creative_image",
        "amazon_visual_suite",
        "domestic_main_image",
        "crossborder_detail",
    ):
        status = tengli.capabilities.features[feature]
        assert status.availability == "unavailable"
        assert status.execution == "none"
        assert status.reason_code == "REAL_PROVIDER_NOT_REGISTERED"
    assert tengli.capabilities.external_authentication.availability == "unavailable"


@pytest.mark.parametrize(
    ("setting_name", "feature_name"),
    [
        ("product_image_provider_enabled", "product_image"),
        ("reference_remix_provider_enabled", "reference_remix"),
        ("model_pose_transfer_provider_enabled", "model_pose_transfer"),
        ("creative_image_provider_enabled", "creative_image"),
        ("amazon_visual_suite_provider_enabled", "amazon_visual_suite"),
        ("domestic_main_image_provider_enabled", "domestic_main_image"),
        ("crossborder_detail_provider_enabled", "crossborder_detail"),
    ],
)
def test_runtime_capabilities_enable_only_the_selected_real_provider(
    setting_name: str,
    feature_name: str,
) -> None:
    runtime = runtime_status_response(
        environment="production",
        authentication_mode="external",
        task_runner="tengli",
        **{setting_name: True},
    )

    selected = runtime.capabilities.features[feature_name]
    assert selected.availability == "available"
    assert selected.execution == "provider"
    assert selected.reason_code is None
    for name, capability in runtime.capabilities.features.items():
        if name in {"local_edit", "detail_pack", feature_name}:
            continue
        assert capability.availability == "unavailable"
        assert capability.execution == "none"
        assert capability.reason_code == "REAL_PROVIDER_NOT_REGISTERED"


def test_runtime_requires_an_authenticated_principal(settings) -> None:
    external_settings = settings.model_copy(update={"auth_mode": "external"})

    with TestClient(create_app(external_settings)) as external:
        response = external.get("/api/v1/runtime")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["error"]["request_id"].startswith("req_")


def test_runtime_openapi_contract_is_explicit_and_stable(client: TestClient) -> None:
    schema = client.app.openapi()
    operation = schema["paths"]["/api/v1/runtime"]["get"]
    schemas = schema["components"]["schemas"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RuntimeStatusResponse"
    }
    assert operation["responses"]["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert schemas["RuntimeStatusResponse"]["required"] == [
        "environment",
        "authentication_mode",
        "task_runner",
        "capabilities",
    ]
    assert set(schemas["RuntimeCapabilities"]["properties"]) == {
        "features",
        "asset_management",
        "local_edit",
        "detail_pack",
        "external_authentication",
    }
    availability = schemas["CapabilityStatus"]["properties"]["availability"]
    execution = schemas["CapabilityStatus"]["properties"]["execution"]
    reason_code = schemas["CapabilityStatus"]["properties"]["reason_code"]
    assert availability["enum"] == ["available", "unavailable"]
    assert execution["enum"] == ["local", "mock", "provider", "none"]
    assert reason_code["anyOf"][0]["enum"] == [
        "LOCAL_EDIT_PROVIDER_NOT_IMPLEMENTED",
        "TASK_RUNNER_MOCK",
        "REAL_PROVIDER_NOT_REGISTERED",
        "EXTERNAL_AUTHENTICATION_NOT_IMPLEMENTED",
    ]
    assert "internal testing" in availability["description"]
    assert "clients must read execution" in operation["description"]


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


@pytest.mark.parametrize(
    ("filename", "image_format", "declared_content_type", "expected_content_type"),
    [
        ("product.jpg", "JPEG", "image/jpeg", "image/jpeg"),
        ("product.jpeg", "JPEG", "image/jpeg", "image/jpeg"),
        ("product.png", "PNG", "image/png", "image/png"),
        ("product.webp", "WEBP", "image/webp", "image/webp"),
    ],
)
def test_upload_accepts_supported_image_formats(
    client: TestClient,
    filename: str,
    image_format: str,
    declared_content_type: str,
    expected_content_type: str,
) -> None:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers=idem(),
        data={"origin_kind": "upload", "media_kind": "image"},
        files={
            "file": (
                filename,
                image_payload(image_format=image_format),
                declared_content_type,
            )
        },
    )

    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["original_filename"] == filename
    assert asset["content_type"] == expected_content_type


def test_upload_rejects_unsupported_image_format(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers=idem(),
        data={"origin_kind": "upload", "media_kind": "image"},
        files={
            "file": (
                "product.gif",
                image_payload(image_format="GIF"),
                "image/gif",
            )
        },
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_IMAGE_TYPE"
    assert error["message"] == "仅支持 JPG/JPEG、PNG 和 WebP 图片。"


def test_same_origin_access_mode_never_returns_internal_s3_url(
    client: TestClient,
) -> None:
    client.app.state.settings.asset_access_url_mode = "same_origin"
    presign = AsyncMock(return_value="http://minio:9000/private-object")
    client.app.state.storage.create_access_url = presign
    asset = upload_asset(client)

    access = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{asset['id']}/access-url",
        json={"disposition": "attachment", "variant": "original"},
    )

    assert access.status_code == 200
    url = access.json()["url"]
    assert url.startswith(
        f"http://testserver/api/v1/workspaces/{WORKSPACE_ID}/assets/{asset['id']}/content?"
    )
    assert "minio" not in url
    presign.assert_not_awaited()
    content = client.get(url)
    assert content.status_code == 200
    assert content.content == image_payload()


@pytest.mark.parametrize(
    "filename",
    [
        "中文文件名.png",
        "中文 mixed name.png",
        "商品🌟预览.png",
        f"{'长文件名' * 30}.png",
    ],
)
def test_asset_content_disposition_supports_utf8_filenames(
    client: TestClient,
    filename: str,
) -> None:
    client.app.state.settings.asset_access_url_mode = "same_origin"
    asset = upload_asset(client, filename=filename)

    access = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets/{asset['id']}/access-url",
        json={"disposition": "attachment", "variant": "original"},
    )
    assert access.status_code == 200

    content = client.get(access.json()["url"])
    assert content.status_code == 200
    assert content.content == image_payload()
    header = content.headers["content-disposition"]
    assert header.isascii()
    assert header.startswith('attachment; filename="')
    assert "; filename*=UTF-8''" in header


def _detail_submit_payload(asset_id: str) -> dict:
    return {
        "type": "detail_pack",
        "intent": "submit",
        "display_name": "Provider beta quota",
        "input": {
            "product_groups": [{"group_key": "product", "asset_ids": [asset_id]}]
        },
        "configuration": {
            "product_name": "Visible product",
            "selling_points": ["visible facts only"],
            "platform_code": "amazon",
            "language": "en",
            "page_count": 1,
        },
    }


def _amazon_submit_payload(asset_id: str) -> dict:
    return {
        "type": "amazon_visual_suite",
        "intent": "submit",
        "display_name": "Amazon provider quota envelope",
        "input": {
            "white_background_product_asset_ids": [asset_id],
            "detail_asset_ids": [],
            "package_asset_ids": [],
            "scene_asset_ids": [],
            "brand_asset_ids": [],
            "reference_asset_ids": [],
            "competitor_reference_asset_ids": [],
        },
        "configuration": {
            "marketplace": "amazon-us",
            "product_name": "Visible product",
            "listing_title": "Visible product title",
            "bullet_points": ["visible facts only"],
            "language": "en-US",
        },
    }


def test_detail_pack_accepts_cross_border_image_size(client: TestClient) -> None:
    reference = upload_asset(client)
    payload = _detail_submit_payload(reference["id"])
    payload["configuration"]["size"] = "1600x1600"

    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )

    assert response.status_code == 202
    assert response.json()["configuration"]["settings"]["size"] == "1600x1600"


def test_detail_pack_rejects_unknown_image_size(client: TestClient) -> None:
    reference = upload_asset(client)
    payload = _detail_submit_payload(reference["id"])
    payload["configuration"]["size"] = "999x999"

    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )

    assert response.status_code == 422


def test_real_provider_quota_disabled_skips_recurring_limits(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.provider_quota_enabled = False
    settings.tengli_daily_budget_usd = 0
    settings.tengli_monthly_budget_usd = 0
    settings.tengli_daily_request_limit = 0
    set_quota_enabled(False)
    try:
        asset = upload_asset(client)
        response = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
            headers=idem(),
            json=_detail_submit_payload(asset["id"]),
        )

        assert response.status_code == 202
        with client.app.state.session_factory() as session:
            reservations = session.scalars(
                select(AuditEventRecord).where(
                    AuditEventRecord.action == "provider.beta_job_reserved"
                )
            ).all()
        assert reservations == []
    finally:
        settings.provider_quota_enabled = True
        set_quota_enabled(True)


def test_real_provider_zero_recurring_limits_keep_usage_ledger_unbounded(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.provider_quota_enabled = True
    settings.workspace_credit_enforcement_enabled = False
    settings.tengli_daily_budget_usd = 0
    settings.tengli_monthly_budget_usd = 0
    settings.tengli_daily_request_limit = 0
    set_quota_enabled(True)
    set_credit_enforcement_enabled(False)
    try:
        asset = upload_asset(client)
        with client.app.state.session_factory() as session:
            account = session.get(WorkspaceCreditAccountRecord, WORKSPACE_ID)
            assert account is not None
            account.balance_credits = 0
            account.reserved_credits = 0
            session.commit()

        response = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
            headers=idem(),
            json=_detail_submit_payload(asset["id"]),
        )

        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        with client.app.state.session_factory() as session:
            provider_reservation = session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.action == "provider.beta_job_reserved",
                    AuditEventRecord.resource_id == job_id,
                )
            )
            credit_reservation = session.scalar(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.job_id == job_id
                )
            )
            account = session.get(WorkspaceCreditAccountRecord, WORKSPACE_ID)
        assert provider_reservation is not None
        assert provider_reservation.details["daily_limit_micros"] == 0
        assert provider_reservation.details["monthly_limit_micros"] == 0
        assert provider_reservation.details["daily_request_limit"] == 0
        assert credit_reservation is not None
        assert account is not None
        assert account.balance_credits == 0
        assert account.reserved_credits == 0
    finally:
        settings.workspace_credit_enforcement_enabled = True
        set_credit_enforcement_enabled(True)

def test_amazon_real_provider_reserves_complete_automation_envelope(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.amazon_visual_suite_provider_enabled = True
    settings.tengli_daily_budget_usd = 10
    settings.tengli_monthly_budget_usd = 20
    settings.tengli_daily_request_limit = 45
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client, filename="amazon-source.png")

    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=_amazon_submit_payload(asset["id"]),
    )

    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    with client.app.state.session_factory() as session:
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.action == "provider.beta_job_reserved",
                AuditEventRecord.resource_id == job_id,
                AuditEventRecord.request_id == job_id,
            )
        )
    assert reservation is not None
    assert reservation.details["provider_request_count"] == 45
    assert reservation.details["estimated_cost_micros"] == 4_530_000
    assert reservation.details["image_budget_micros"] == 1_890_000
    assert reservation.details["planner_reserve_micros"] == 250_000


def test_real_provider_job_reservation_is_idempotent_and_daily_bounded(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 0.5
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 20
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    key = str(uuid4())
    payload = _detail_submit_payload(asset["id"])

    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    replay = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    blocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROVIDER_DAILY_BUDGET_EXCEEDED"
    with client.app.state.session_factory() as session:
        reservations = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.action == "provider.beta_job_reserved"
            )
        ).all()
    assert len(reservations) == 1
    assert reservations[0].details["estimated_cost_micros"] == 430_000
    assert reservations[0].details["provider_request_count"] == 3


def test_real_provider_daily_request_limit_blocks_before_dispatch(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 2
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 3
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    payload = _detail_submit_payload(asset["id"])

    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    blocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )

    assert first.status_code == 202
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROVIDER_DAILY_REQUEST_LIMIT_EXCEEDED"


def test_unknown_planner_outcome_is_charged_conservatively_and_releases_images(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 0.7
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 5
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    payload = _detail_submit_payload(asset["id"])

    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert first.status_code == 202
    job_id = first.json()["id"]
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job is not None
        job.status = JobStatus.FAILED.value
        job.stage = "planning_failed"
        job.progress = 100
        job.finished_at = utc_now()
        job.error_code = "PLANNER_OUTCOME_UNKNOWN"
        reservation_payload = {
            "state": "planner_reserved",
            "groups": [{"group_key": "product"}],
        }
        session.add(
            JobPlanRecord(
                id=f"plan_{uuid4().hex}",
                workspace_id=WORKSPACE_ID,
                job_id=job_id,
                revision=1,
                schema_version="v1",
                payload=reservation_payload,
                payload_hash="0" * 64,
                validation_status=PlanValidationStatus.INVALID.value,
                validation_errors=[{"code": "PLANNER_OUTCOME_UNKNOWN"}],
                validator_version="structured-plan-v2",
                validated_at=utc_now(),
            )
        )
        session.commit()

    second = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert second.status_code == 202
    with client.app.state.session_factory() as session:
        settlement = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id == job_id,
                AuditEventRecord.action == "provider.beta_job_settled",
            )
        )
        release = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id == job_id,
                AuditEventRecord.action == "provider.beta_job_released",
            )
        )
        assert settlement is not None
        assert release is not None
        assert settlement.details["charged_cost_micros"] == 250_000
        assert settlement.details["actual_provider_request_count"] == 1
        assert settlement.details["cost_basis"] == "conservative_unknown"
        assert settlement.details["actual_cost_reported_count"] == 0
        assert settlement.details["conservative_unknown_count"] == 1
        assert release.details["released_cost_micros"] == 180_000
        assert release.details["released_request_count"] == 2


def test_terminal_detail_without_attempt_evidence_fails_quota_closed(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 0.7
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 5
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    payload = _detail_submit_payload(asset["id"])
    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert first.status_code == 202
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, first.json()["id"])
        assert job is not None
        job.status = JobStatus.FAILED.value
        job.stage = "planning_failed"
        job.progress = 100
        job.finished_at = utc_now()
        job.error_code = "CORRUPT_MISSING_EVIDENCE"
        session.commit()

    blocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "PROVIDER_QUOTA_LEDGER_INVALID"


@pytest.mark.parametrize(
    "tamper",
    [
        "duplicate_reservation",
        "duplicate_settlement",
        "wrong_settlement_request_id",
        "wrong_reservation_event",
        "changed_reserved_cost",
        "changed_reserved_requests",
        "cost_over_reservation",
        "requests_over_reservation",
    ],
)
def test_provider_quota_ledger_rejects_duplicate_or_inconsistent_events(
    client: TestClient,
    tamper: str,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 2
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 20
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    payload = _detail_submit_payload(asset["id"])
    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert first.status_code == 202
    job_id = first.json()["id"]

    with client.app.state.session_factory() as session:
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.workspace_id == WORKSPACE_ID,
                AuditEventRecord.action == "provider.beta_job_reserved",
                AuditEventRecord.resource_id == job_id,
            )
        )
        assert reservation is not None
        if tamper == "duplicate_reservation":
            session.add(
                AuditEventRecord(
                    workspace_id=WORKSPACE_ID,
                    action="provider.beta_job_reserved",
                    resource_type="job",
                    resource_id=job_id,
                    request_id=job_id,
                    details=dict(reservation.details),
                )
            )
        else:
            reserved_cost = int(reservation.details["estimated_cost_micros"])
            reserved_requests = int(reservation.details["provider_request_count"])
            settlement_details = {
                "ledger_version": 2,
                "reservation_event_id": reservation.id,
                "reserved_cost_micros": reserved_cost,
                "reserved_request_count": reserved_requests,
                "charged_cost_micros": 0,
                "actual_provider_request_count": 0,
            }
            if tamper == "wrong_reservation_event":
                settlement_details["reservation_event_id"] = reservation.id + 1
            elif tamper == "changed_reserved_cost":
                settlement_details["reserved_cost_micros"] = reserved_cost - 1
            elif tamper == "changed_reserved_requests":
                settlement_details["reserved_request_count"] = reserved_requests - 1
            elif tamper == "cost_over_reservation":
                settlement_details["charged_cost_micros"] = reserved_cost + 1
            elif tamper == "requests_over_reservation":
                settlement_details["actual_provider_request_count"] = (
                    reserved_requests + 1
                )
            settlement_request_id = (
                "wrong_request_id"
                if tamper == "wrong_settlement_request_id"
                else job_id
            )
            settlement_count = 2 if tamper == "duplicate_settlement" else 1
            for _ in range(settlement_count):
                session.add(
                    AuditEventRecord(
                        workspace_id=WORKSPACE_ID,
                        action="provider.beta_job_settled",
                        resource_type="job",
                        resource_id=job_id,
                        request_id=settlement_request_id,
                        details=dict(settlement_details),
                    )
                )
        session.commit()

    blocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "PROVIDER_QUOTA_LEDGER_INVALID"


def test_nonterminal_job_with_valid_zero_settlement_fails_quota_closed(
    client: TestClient,
) -> None:
    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 0.7
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 20
    settings.tengli_planner_reserve_micros = 250_000
    asset = upload_asset(client)
    payload = _detail_submit_payload(asset["id"])
    first = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert first.status_code == 202
    job_id = first.json()["id"]

    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.workspace_id == WORKSPACE_ID,
                AuditEventRecord.action == "provider.beta_job_reserved",
                AuditEventRecord.resource_id == job_id,
            )
        )
        assert job is not None
        assert job.status == JobStatus.QUEUED.value
        assert reservation is not None
        reserved_cost = int(reservation.details["estimated_cost_micros"])
        reserved_requests = int(reservation.details["provider_request_count"])
        session.add(
            AuditEventRecord(
                workspace_id=WORKSPACE_ID,
                action="provider.beta_job_settled",
                resource_type="job",
                resource_id=job_id,
                request_id=job_id,
                details={
                    "ledger_version": 2,
                    "reservation_event_id": reservation.id,
                    "reserved_cost_micros": reserved_cost,
                    "reserved_request_count": reserved_requests,
                    "charged_cost_micros": 0,
                    "actual_provider_request_count": 0,
                },
            )
        )
        session.commit()

    blocked = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json=payload,
    )
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "PROVIDER_QUOTA_LEDGER_INVALID"


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
    corrupt_png = bytearray(image_payload(size=(2, 2)))
    idat_offset = corrupt_png.index(b"IDAT")
    idat_length = int.from_bytes(corrupt_png[idat_offset - 4 : idat_offset], "big")
    corrupt_png[idat_offset + 4 + idat_length] ^= 1
    corrupt = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers=idem(),
        files={"file": ("corrupt.png", bytes(corrupt_png), "image/png")},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_IMAGE"
    assert (
        invalid.json()["error"]["message"]
        == "文件不是可识别的 JPG/JPEG、PNG 或 WebP 图片。"
    )
    assert invalid.json()["error"]["request_id"].startswith("req_")
    assert corrupt.status_code == 400
    assert corrupt.json()["error"]["code"] == "INVALID_IMAGE"


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
    assert job["cost"]["estimated_min"]["micros"] == "45000"
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


def _seed_partial_retry_source(
    client: TestClient,
    *,
    job_type: JobType,
    failed_error_details: dict[str, object],
) -> tuple[str, str]:
    job_id = f"job_{uuid4().hex}"
    item_count = 21 if job_type == JobType.AMAZON_VISUAL_SUITE else 2
    now = utc_now()
    failed_item_id = ""
    with client.app.state.session_factory() as session:
        session.add(
            JobRecord(
                id=job_id,
                workspace_id=WORKSPACE_ID,
                type=job_type.value,
                status=JobStatus.PARTIAL.value,
                stage=JobStatus.PARTIAL.value,
                display_name="Retry semantics fixture",
                progress=100,
                configuration={},
                expected_item_count=item_count,
                succeeded_item_count=item_count - 1,
                failed_item_count=1,
                error_code="AMAZON_VISUAL_REVIEW_INVALID",
                error_message="Review infrastructure failed.",
                currency="USD",
                finished_at=now,
            )
        )
        for ordinal in range(item_count):
            item_id = f"item_{uuid4().hex}"
            failed = ordinal == 0
            if failed:
                failed_item_id = item_id
            session.add(
                JobItemRecord(
                    id=item_id,
                    workspace_id=WORKSPACE_ID,
                    job_id=job_id,
                    item_key=f"ITEM-{ordinal + 1:02d}",
                    ordinal=ordinal,
                    status=(
                        JobItemStatus.FAILED.value
                        if failed
                        else JobItemStatus.SUCCEEDED.value
                    ),
                    stage=("suite_review_infrastructure_failed" if failed else "done"),
                    quality="medium",
                    configuration={},
                    result_source="generated" if not failed else None,
                    error_code=("AMAZON_VISUAL_REVIEW_INVALID" if failed else None),
                    error_message=("Review infrastructure failed." if failed else None),
                    error_details=failed_error_details if failed else None,
                    finished_at=now,
                )
            )
        session.commit()
    return job_id, failed_item_id


def _replace_retry_fixture_item_state(
    client: TestClient,
    *,
    job_id: str,
    item_key: str,
    status: JobItemStatus,
    error_details: dict[str, object] | None = None,
) -> str:
    with client.app.state.session_factory() as session:
        job = session.get(JobRecord, job_id)
        assert job is not None
        item = session.scalar(
            select(JobItemRecord).where(
                JobItemRecord.job_id == job_id,
                JobItemRecord.item_key == item_key,
            )
        )
        assert item is not None
        assert item.status == JobItemStatus.SUCCEEDED.value

        job.succeeded_item_count -= 1
        if status == JobItemStatus.FAILED:
            job.failed_item_count += 1
        item.status = status.value
        item.stage = "failed" if status == JobItemStatus.FAILED else status.value
        item.result_source = None
        item.error_code = (
            "AMAZON_IMAGE_QUALITY_FAILED" if status == JobItemStatus.FAILED else None
        )
        item.error_message = (
            "Image quality failed." if status == JobItemStatus.FAILED else None
        )
        item.error_details = error_details
        session.commit()
        return item.id


def _retry_pending_item_keys(response_json: dict) -> set[str]:
    return {
        item["item_key"]
        for item in response_json["items"]
        if item["status"] == JobItemStatus.PENDING.value
    }


def _attach_retry_fixture_deliverables(
    client: TestClient,
    *,
    job_id: str,
    asset_id: str,
    missing_item_keys: set[str] | None = None,
    non_deliverable_item_keys: set[str] | None = None,
) -> None:
    missing = missing_item_keys or set()
    non_deliverable = non_deliverable_item_keys or set()
    with client.app.state.session_factory() as session:
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job_id)
            .order_by(JobItemRecord.ordinal)
        ).all()
        for item in items:
            if item.item_key in missing:
                continue
            session.add(
                JobAssetRecord(
                    workspace_id=WORKSPACE_ID,
                    job_id=job_id,
                    job_item_id=item.id,
                    asset_id=asset_id,
                    direction="output",
                    role="amazon_visual_suite",
                    ordinal=item.ordinal,
                    is_deliverable=item.item_key not in non_deliverable,
                    validation={},
                )
            )
        session.commit()


def test_amazon_partial_review_infrastructure_failure_allows_complete_archive(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="preserved-suite.png")
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
            "retryable": False,
        },
    )
    _attach_retry_fixture_deliverables(
        client,
        job_id=job_id,
        asset_id=source["id"],
    )

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )

    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert bundle.namelist() == [
            f"ITEM-{ordinal:02d}.png" for ordinal in range(1, 22)
        ]


@pytest.mark.parametrize(
    ("missing_item_keys", "non_deliverable_item_keys"),
    [
        ({"ITEM-21"}, set()),
        (set(), {"ITEM-21"}),
    ],
)
def test_amazon_partial_review_infrastructure_archive_requires_all_deliverables(
    client: TestClient,
    missing_item_keys: set[str],
    non_deliverable_item_keys: set[str],
) -> None:
    source = upload_asset(client, filename="incomplete-suite.png")
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )
    _attach_retry_fixture_deliverables(
        client,
        job_id=job_id,
        asset_id=source["id"],
        missing_item_keys=missing_item_keys,
        non_deliverable_item_keys=non_deliverable_item_keys,
    )

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )

    assert archive.status_code == 409
    assert archive.json()["error"]["code"] == "DELIVERABLE_ARCHIVE_INCOMPLETE"


def test_amazon_partial_image_quality_failure_archive_remains_closed(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="quality-failed-suite.png")
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "image_quality_failure",
            "image_quality_failed": True,
            "generated_asset_preserved": False,
        },
    )
    _attach_retry_fixture_deliverables(
        client,
        job_id=job_id,
        asset_id=source["id"],
    )

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )

    assert archive.status_code == 409
    assert archive.json()["error"]["code"] == "DELIVERABLE_ARCHIVE_NOT_READY"


def test_amazon_partial_mixed_failure_archive_remains_closed(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="mixed-failure-suite.png")
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )
    _replace_retry_fixture_item_state(
        client,
        job_id=job_id,
        item_key="ITEM-02",
        status=JobItemStatus.FAILED,
        error_details={
            "failure_kind": "image_quality_failure",
            "image_quality_failed": True,
            "generated_asset_preserved": False,
        },
    )
    _attach_retry_fixture_deliverables(
        client,
        job_id=job_id,
        asset_id=source["id"],
    )

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )

    assert archive.status_code == 409
    assert archive.json()["error"]["code"] == "DELIVERABLE_ARCHIVE_NOT_READY"


@pytest.mark.parametrize(
    ("job_type", "terminal_status"),
    [
        (JobType.DETAIL_PACK, JobStatus.PARTIAL),
        (JobType.AMAZON_VISUAL_SUITE, JobStatus.FAILED),
    ],
)
def test_preserved_review_marker_does_not_open_other_archive_states(
    client: TestClient,
    job_type: JobType,
    terminal_status: JobStatus,
) -> None:
    source = upload_asset(client, filename="closed-archive.png")
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=job_type,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )
    if terminal_status != JobStatus.PARTIAL:
        with client.app.state.session_factory() as session:
            job = session.get(JobRecord, job_id)
            assert job is not None
            job.status = terminal_status.value
            job.stage = terminal_status.value
            if terminal_status == JobStatus.FAILED:
                job.succeeded_item_count = 0
                job.failed_item_count = job.expected_item_count
            session.commit()
    _attach_retry_fixture_deliverables(
        client,
        job_id=job_id,
        asset_id=source["id"],
    )

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )

    assert archive.status_code == 409
    assert archive.json()["error"]["code"] == "DELIVERABLE_ARCHIVE_NOT_READY"


def test_amazon_review_infrastructure_failure_hides_and_rejects_image_retry(
    client: TestClient,
) -> None:
    job_id, blocker_item_id = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
            "retryable": False,
        },
    )

    detail = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}")
    assert detail.status_code == 200
    assert "retry" not in detail.json()["allowed_actions"]
    assert "clone" in detail.json()["allowed_actions"]

    listed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        params={"type": JobType.AMAZON_VISUAL_SUITE.value},
    )
    assert listed.status_code == 200
    listed_job = next(item for item in listed.json()["items"] if item["id"] == job_id)
    assert "retry" not in listed_job["allowed_actions"]

    retry_payloads = [
        {"scope": "failed", "item_ids": []},
        {"scope": "full", "item_ids": []},
        {"scope": "missing", "item_ids": []},
        {"scope": "selected", "item_ids": [blocker_item_id]},
    ]
    for payload in retry_payloads:
        rejected = client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/retry",
            headers=idem(),
            json=payload,
        )
        assert rejected.status_code == 409
        error = rejected.json()["error"]
        assert error["code"] == "AMAZON_REVIEW_INFRASTRUCTURE_RETRY_NOT_APPLICABLE"
        assert "图片已成功生成并保留" in error["message"]
        assert error["details"] == {
            "failure_kind": "review_infrastructure_failure",
            "generated_asset_preserved": True,
            "blocked_item_ids": [blocker_item_id],
        }

    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize(
    ("scope", "expected_pending_keys"),
    [
        ("failed", {"ITEM-02"}),
        ("missing", {"ITEM-02", "ITEM-03"}),
        ("selected", {"ITEM-02"}),
        ("full", {f"ITEM-{ordinal:02d}" for ordinal in range(2, 22)}),
    ],
)
def test_amazon_review_blocker_is_excluded_when_real_failures_are_retryable(
    client: TestClient,
    scope: str,
    expected_pending_keys: set[str],
) -> None:
    job_id, blocker_item_id = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )
    image_failure_item_id = _replace_retry_fixture_item_state(
        client,
        job_id=job_id,
        item_key="ITEM-02",
        status=JobItemStatus.FAILED,
        error_details={
            "failure_kind": "image_quality_failure",
            "image_quality_failed": True,
            "generated_asset_preserved": False,
        },
    )
    _replace_retry_fixture_item_state(
        client,
        job_id=job_id,
        item_key="ITEM-03",
        status=JobItemStatus.CANCELLED,
    )

    detail = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}")
    assert detail.status_code == 200
    assert "retry" in detail.json()["allowed_actions"]

    listed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        params={"type": JobType.AMAZON_VISUAL_SUITE.value},
    )
    assert listed.status_code == 200
    listed_job = next(item for item in listed.json()["items"] if item["id"] == job_id)
    assert "retry" in listed_job["allowed_actions"]

    item_ids = [blocker_item_id, image_failure_item_id] if scope == "selected" else []
    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/retry",
        headers=idem(),
        json={"scope": scope, "item_ids": item_ids},
    )
    assert retried.status_code == 201, retried.text
    pending_keys = _retry_pending_item_keys(retried.json())
    assert pending_keys == expected_pending_keys
    assert "ITEM-01" not in pending_keys


def test_amazon_mixed_failure_selected_blocker_only_is_rejected(
    client: TestClient,
) -> None:
    job_id, blocker_item_id = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )
    _replace_retry_fixture_item_state(
        client,
        job_id=job_id,
        item_key="ITEM-02",
        status=JobItemStatus.FAILED,
        error_details={
            "failure_kind": "image_quality_failure",
            "image_quality_failed": True,
            "generated_asset_preserved": False,
        },
    )

    detail = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}")
    assert detail.status_code == 200
    assert "retry" in detail.json()["allowed_actions"]

    rejected = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/retry",
        headers=idem(),
        json={"scope": "selected", "item_ids": [blocker_item_id]},
    )
    assert rejected.status_code == 409
    error = rejected.json()["error"]
    assert error["code"] == "AMAZON_REVIEW_INFRASTRUCTURE_RETRY_NOT_APPLICABLE"
    assert error["details"]["blocked_item_ids"] == [blocker_item_id]


def test_amazon_image_quality_failure_remains_retryable(client: TestClient) -> None:
    job_id, _ = _seed_partial_retry_source(
        client,
        job_type=JobType.AMAZON_VISUAL_SUITE,
        failed_error_details={
            "failure_kind": "image_quality_failure",
            "image_quality_failed": True,
            "generated_asset_preserved": False,
        },
    )

    detail = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}")
    assert detail.status_code == 200
    assert "retry" in detail.json()["allowed_actions"]

    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/retry",
        headers=idem(),
        json={"scope": "failed", "item_ids": []},
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["retry_of_job_id"] == job_id
    pending = [item for item in retried.json()["items"] if item["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["item_key"] == "ITEM-01"


@pytest.mark.parametrize(
    ("scope", "expected_pending_keys"),
    [
        ("failed", {"ITEM-01"}),
        ("missing", {"ITEM-01"}),
        ("selected", {"ITEM-01"}),
        ("full", {"ITEM-01", "ITEM-02"}),
    ],
)
def test_review_infrastructure_marker_does_not_change_other_skill_retry(
    client: TestClient,
    scope: str,
    expected_pending_keys: set[str],
) -> None:
    job_id, marker_item_id = _seed_partial_retry_source(
        client,
        job_type=JobType.LOCAL_EDIT,
        failed_error_details={
            "failure_kind": "review_infrastructure_failure",
            "image_quality_failed": False,
            "generated_asset_preserved": True,
        },
    )

    detail = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}")
    assert detail.status_code == 200
    assert "retry" in detail.json()["allowed_actions"]

    listed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        params={"type": JobType.LOCAL_EDIT.value},
    )
    assert listed.status_code == 200
    listed_job = next(item for item in listed.json()["items"] if item["id"] == job_id)
    assert "retry" in listed_job["allowed_actions"]

    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/retry",
        headers=idem(),
        json={
            "scope": scope,
            "item_ids": [marker_item_id] if scope == "selected" else [],
        },
    )
    assert retried.status_code == 201, retried.text
    assert _retry_pending_item_keys(retried.json()) == expected_pending_keys


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


def test_clone_real_provider_job_reserves_quota_before_dispatch(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="source.png")
    mask = upload_asset(client, filename="mask.png", media_kind="mask")
    job = create_local_edit_job(client, source["id"], mask["id"])
    assert dispatch_pending(client) == 1

    settings = client.app.state.settings
    settings.task_runner = "tengli"
    settings.tengli_daily_budget_usd = 2
    settings.tengli_monthly_budget_usd = 5
    settings.tengli_daily_request_limit = 20
    settings.tengli_planner_reserve_micros = 250_000

    cloned = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/clone",
        headers=idem(),
    )

    assert cloned.status_code == 201, cloned.text
    cloned_id = cloned.json()["id"]
    with client.app.state.session_factory() as session:
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.action == "provider.beta_job_reserved",
                AuditEventRecord.resource_id == cloned_id,
                AuditEventRecord.request_id == cloned_id,
            )
        )
    assert reservation is not None
    assert reservation.details["provider_request_count"] == 4


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
    unavailable_archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )
    assert unavailable_archive.status_code == 409
    assert (
        unavailable_archive.json()["error"]["code"]
        == "DELIVERABLE_ARCHIVE_NOT_READY"
    )

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

    # The mock runner intentionally creates no image outputs. Attach the uploaded
    # test image as each canonical deliverable so the archive path stays zero-cost.
    with client.app.state.session_factory() as session:
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job_id)
            .order_by(JobItemRecord.ordinal)
        ).all()
        for item in items:
            session.add(
                JobAssetRecord(
                    workspace_id=WORKSPACE_ID,
                    job_id=job_id,
                    job_item_id=item.id,
                    asset_id=reference["id"],
                    direction="output",
                    role="detail_page",
                    ordinal=item.ordinal,
                    is_deliverable=True,
                    validation={"sha256": reference["sha256"]},
                )
            )
        session.commit()
    completed = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}").json()

    archive = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )
    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"] == "application/zip"
    assert "attachment" in archive.headers["content-disposition"]
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert bundle.namelist() == [
            "page-001.png",
            "page-002.png",
            "page-003.png",
        ]
        deliverables = {
            asset["ordinal"]: asset
            for asset in completed["assets"]
            if asset["direction"] == "output" and asset["is_deliverable"]
        }
        for ordinal, name in enumerate(bundle.namelist()):
            assert hashlib.sha256(bundle.read(name)).hexdigest() == (
                deliverables[ordinal]["validation"]["sha256"]
            )

    repeated = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/deliverables.zip"
    )
    assert repeated.status_code == 200
    after_download = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}"
    ).json()
    assert after_download["api_request_count"] == completed["api_request_count"]


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
