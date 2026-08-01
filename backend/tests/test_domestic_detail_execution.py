from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain import JobStatus, PlanValidationStatus
from app.models import (
    AuditEventRecord,
    JobAttemptRecord,
    JobPlanRecord,
)
from app.xinghe_agent import FakeXingheGateway
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset

AUTO_CONFIRM_ACTION = "detail_plan.auto_confirmed"


def _create_detail_job(
    client: TestClient,
    asset_id: str,
    *,
    market_region: str,
    auto_start_after_plan: bool,
    page_count: int = 1,
    platform_code: str | None = None,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "display_name": f"{market_region} detail execution boundary",
            "input": {
                "product_groups": [
                    {"group_key": "primary", "asset_ids": [asset_id]}
                ]
            },
            "configuration": {
                "product_name": "Execution boundary product",
                "selling_points": ["durable plan", "bounded generation"],
                "platform_code": platform_code
                or ("tmall" if market_region == "domestic" else "amazon"),
                "market_region": market_region,
                "language": "zh-CN" if market_region == "domestic" else "en",
                "page_count": page_count,
                "auto_start_after_plan": auto_start_after_plan,
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _gateway(client: TestClient) -> FakeXingheGateway:
    planner = client.app.state.task_runner.coordinator.detail_planner
    assert planner is not None
    gateway = planner.gateway
    assert isinstance(gateway, FakeXingheGateway)
    return gateway


def _auto_confirm_audit_count(client: TestClient, job_id: str) -> int:
    with client.app.state.session_factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.action == AUTO_CONFIRM_ACTION,
                    AuditEventRecord.request_id == job_id,
                )
            )
            or 0
        )


def test_domestic_valid_plan_auto_confirms_generates_and_reentry_is_idempotent(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="domestic-auto-confirm.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert completed["status"] == JobStatus.COMPLETED.value
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 1
    with client.app.state.session_factory() as session:
        plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )
        audit = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.action == AUTO_CONFIRM_ACTION,
                AuditEventRecord.request_id == job["id"],
            )
        )
        attempt_count = session.scalar(
            select(func.count())
            .select_from(JobAttemptRecord)
            .where(JobAttemptRecord.job_id == job["id"])
        )
    assert plan is not None and plan.confirmed_at is not None
    assert audit is not None
    assert audit.resource_type == "job_plan"
    assert audit.resource_id == plan.id
    assert audit.details["job_id"] == job["id"]
    assert audit.details["plan_revision"] == plan.revision
    assert audit.details["market_region"] == "domestic"
    assert audit.details["auto_start_after_plan"] is True
    assert attempt_count == 1

    assert (
        asyncio.run(client.app.state.task_runner.run(str(job["id"])))
        == JobStatus.COMPLETED
    )
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 1
    assert _auto_confirm_audit_count(client, str(job["id"])) == 1
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobAttemptRecord)
                .where(JobAttemptRecord.job_id == job["id"])
            )
            == 1
        )


def test_domestic_auto_confirm_recovers_after_planner_commit_before_confirmation(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="domestic-auto-confirm-recovery.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
    )
    runner = client.app.state.task_runner
    coordinator = runner.coordinator
    planner = coordinator.detail_planner
    assert planner is not None
    gateway = _gateway(client)

    assert coordinator.prepare(str(job["id"])) == JobStatus.PLANNING
    assert (
        asyncio.run(planner.plan(str(job["id"])))
        == JobStatus.AWAITING_CONFIRMATION
    )
    with client.app.state.session_factory() as session:
        plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )
        assert plan is not None and plan.confirmed_at is None
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []

    assert asyncio.run(runner.run(str(job["id"]))) == JobStatus.COMPLETED
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 1
    assert _auto_confirm_audit_count(client, str(job["id"])) == 1

    assert asyncio.run(runner.run(str(job["id"]))) == JobStatus.COMPLETED
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 1
    assert _auto_confirm_audit_count(client, str(job["id"])) == 1


def test_domestic_unsupported_platform_fails_before_planner_provider_call(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="domestic-unsupported-platform.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
        platform_code="unsupported-marketplace",
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    failed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_code"] == "DETAIL_PLATFORM_UNSUPPORTED"
    assert gateway.planner_calls == []
    assert gateway.image_calls == []
    assert failed.get("plan") is None
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0


def test_domestic_auto_start_false_stops_at_confirmation_gate(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="domestic-manual-confirm.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=False,
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    current = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert current["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    assert current["plan"]["confirmed_at"] is None
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0


def test_domestic_invalid_plan_never_reaches_image_provider(
    client: TestClient,
) -> None:
    gateway = _gateway(client)
    gateway.planner_failure = "schema"
    source = upload_asset(client, filename="domestic-invalid-plan.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
    )

    assert dispatch_pending(client) == 1
    failed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_code"] == "PLANNER_SCHEMA_INVALID"
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    assert failed["plan"]["validation_status"] == PlanValidationStatus.INVALID.value
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0


def test_international_plan_still_waits_and_legacy_confirmation_api_generates(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="international-manual-confirm.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="international",
        auto_start_after_plan=True,
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert planned["plan"]["confirmed_at"] is None
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0

    assert (
        asyncio.run(client.app.state.task_runner.run(str(job["id"])))
        == JobStatus.AWAITING_CONFIRMATION
    )
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0

    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": planned["plan"]["revision"]},
    )
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["status"] == JobStatus.PROCESSING.value
    assert dispatch_pending(client) == 1

    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert completed["status"] == JobStatus.COMPLETED.value
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 1
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0
