import asyncio
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.domain import JobStatus, OutboxStatus, PlanValidationStatus
from app.main import create_app
from app.models import (
    AuditEventRecord,
    JobAttemptRecord,
    JobPlanRecord,
    JobRecord,
    OutboxEventRecord,
    UsageEventRecord,
    utc_now,
)
from app.outbox import publish_pending_events
from app.routes_v1 import runtime_status_response
from app.services import set_quota_enabled

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
    assert tengli.capabilities.external_authentication.availability == "unavailable"


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
