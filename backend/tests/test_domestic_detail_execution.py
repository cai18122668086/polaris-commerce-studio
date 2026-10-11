# ruff: noqa: E501
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain import JobStatus, PlanValidationStatus
from app.models import (
    AuditEventRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
)
from app.xinghe_agent import (
    IMAGE_SIZE,
    FakeXingheGateway,
    PlannerRequest,
    _fake_plan,
    _planner_prompt,
    build_resume_signature,
    compile_page_prompt,
    validate_planner_payload,
)
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset

AUTO_CONFIRM_ACTION = "detail_plan.auto_confirmed"


def _create_detail_job(
    client: TestClient,
    asset_id: str,
    *,
    market_region: str,
    auto_start_after_plan: bool,
    page_count: int = 8,
    platform_code: str | None = None,
    reference_asset_ids: list[str] | None = None,
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
                ],
                "reference_asset_ids": reference_asset_ids or [],
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


def _aurora_approval_payload(planned: dict[str, object]) -> dict[str, object]:
    """Return the exact native Aurora v4.3 approval packet for a planned job."""

    plan = planned.get("plan")
    assert isinstance(plan, dict)
    payload = plan.get("payload")
    assert isinstance(payload, dict)
    aurora = payload.get("aurora_v4_3")
    assert isinstance(aurora, dict)
    return {
        "expected_revision": plan["revision"],
        "approval_text": "我已审阅完整 group→screen 审批包，并批准按 3:8 pair 画布生成。",
        "approval_document_sha256": aurora["approval_document_sha256"],
        "approved_module_count": aurora["approved_module_count"],
        "approved_pair_canvas_aspect_ratio": aurora[
            "approved_pair_canvas_aspect_ratio"
        ],
    }


def test_domestic_valid_plan_requires_approval_then_waits_for_final_review(
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
    # Aurora's native pair canvas is 1440×3840 (5.53 MP); keep the test
    # harness limit above that Skill contract before approving generation.
    client.app.state.settings.max_image_pixels = 6_000_000
    client.app.state.storage.validator.max_image_pixels = 6_000_000

    dispatch_count = dispatch_pending(client)
    assert dispatch_count in (0, 1)
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert planned["plan"]["confirmed_at"] is None
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json=_aurora_approval_payload(planned),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["status"] == JobStatus.PROCESSING.value
    # The test fixture uses inline dispatch, so the route's background
    # outbox publisher may already have completed generation before the
    # response is observed.  A second publish is therefore optional.
    dispatch_count = dispatch_pending(client)
    awaiting_review = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert awaiting_review["status"] == JobStatus.AWAITING_FINAL_REVIEW.value
    assert awaiting_review["stage"] == "awaiting_user_final_review"
    assert all(item["status"] == "succeeded" for item in awaiting_review["items"])
    assert len(gateway.image_calls) == 4
    assert all(call.size == "1440x3840" for call in gateway.image_calls)
    assert all("PAIR_PLAN_MERGE" in call.prompt for call in gateway.image_calls)
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
    assert audit is None
    assert attempt_count == 8

    assert (
        asyncio.run(client.app.state.task_runner.run(str(job["id"])))
        == JobStatus.AWAITING_FINAL_REVIEW
    )
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 4
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobAttemptRecord)
                .where(JobAttemptRecord.job_id == job["id"])
            )
            == 8
        )


def test_domestic_plan_commit_recovery_preserves_confirmation_gate(
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

    client.app.state.settings.max_image_pixels = 6_000_000
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json=_aurora_approval_payload(planned),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert asyncio.run(runner.run(str(job["id"]))) == JobStatus.AWAITING_FINAL_REVIEW
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 4
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0

    assert asyncio.run(runner.run(str(job["id"]))) == JobStatus.AWAITING_FINAL_REVIEW
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 4
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0


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
    assert failed["error_code"] == "AURORA_PLAN_SCHEMA_INVALID"
    # Native Aurora emits one initial planning request and eight bounded
    # module-completion requests before the final schema gate.
    assert len(gateway.planner_calls) == 9
    assert gateway.image_calls == []
    assert failed["plan"]["validation_status"] == PlanValidationStatus.INVALID.value
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0


def test_domestic_product_and_style_sources_keep_distinct_durable_roles(
    client: TestClient,
) -> None:
    product = upload_asset(client, filename="domestic-role-product.png")
    style = upload_asset(client, filename="domestic-role-style.png")
    job = _create_detail_job(
        client,
        product["id"],
        market_region="domestic",
        auto_start_after_plan=True,
        reference_asset_ids=[style["id"]],
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    assert len(gateway.planner_calls) == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    client.app.state.settings.max_image_pixels = 6_000_000
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json=_aurora_approval_payload(planned),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert dispatch_pending(client) == 1
    reviewed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert reviewed["status"] == JobStatus.AWAITING_FINAL_REVIEW.value
    assert len(gateway.image_calls) == 4
    assert [
        source.source_role for source in gateway.planner_calls[0].sources
    ] == ["product_reference", "style_reference"]
    image_roles = [source.source_role for source in gateway.image_calls[0].sources]
    assert image_roles[0] == "format_canvas"
    assert image_roles[1:] == ["product_reference", "style_reference"]
    planner_prompt = _planner_prompt(gateway.planner_calls[0])
    assert "aurora-domestic-ecommerce-detail-page v4.3.0" in planner_prompt
    assert "product_reference" in planner_prompt
    assert "style_reference" in planner_prompt
    image_prompt = gateway.image_calls[0].prompt
    assert image_prompt.startswith("CONTINUOUS_PAIR_RENDERING_LOCKED")
    assert "3:8" in image_prompt
    assert "PAIR_OUTPUT_LOCK" in image_prompt

    with client.app.state.session_factory() as session:
        item = session.scalar(
            select(JobItemRecord).where(JobItemRecord.job_id == job["id"])
        )
        assert item is not None
        relations = session.scalars(
            select(JobAssetRecord)
            .where(JobAssetRecord.job_id == job["id"])
            .order_by(JobAssetRecord.role)
        ).all()
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id == item.id,
                AuditEventRecord.action == "xinghe.image_reserved",
            )
        )
    assert [source["role"] for source in item.configuration["source_assets"]] == [
        "product_reference",
        "style_reference",
    ]
    assert {(relation.asset_id, relation.role) for relation in relations} == {
        (product["id"], "product_reference"),
        (style["id"], "style_reference"),
    }
    assert reservation is not None
    assert reservation.details["source_role_counts"] == {
        "format_canvas": 1,
        "product_reference": 1,
        "style_reference": 1,
    }


def test_domestic_protocol_fields_are_preserved_and_compiled_into_prompt() -> None:
    request = PlannerRequest(
        workspace_id="ws-domestic",
        job_id="job-domestic",
        group_key="primary",
        sources=(),
        page_count=2,
        language="zh-CN",
        product_name="",
        product_information=(),
        platform_code="tmall",
        size="1200x1600",
        idempotency_key="offline",
        domestic_protocol=True,
    )
    payload = deepcopy(_fake_plan(request))
    payload["analysis"]["buyer_demand_map"] = {
        "priority": ["trust", "proof"]
    }
    payload["analysis"]["information_confidence"] = {
        "visible": ["shape"],
        "needs_confirmation": ["material"],
    }
    payload["plan"]["reference_visual_style_lock"] = {
        "hierarchy": "editorial",
        "page_rhythm": "impact then proof",
    }
    payload["plan"]["screens"][0].update(
        {
            "buyer_demand": "Can I trust what I see?",
            "matched_selling_point": "Visible structure",
            "visual_proof": {"method": "material macro"},
            "risk_reminder": "Do not infer material",
            "physical_logic_lock": {"contact": "grounded"},
        }
    )

    structured = validate_planner_payload(
        payload,
        2,
        preserve_protocol_fields=True,
    )
    assert structured["analysis"]["buyer_demand_map"] == {
        "priority": ["trust", "proof"]
    }
    assert structured["plan"]["reference_visual_style_lock"]["hierarchy"] == (
        "editorial"
    )
    assert structured["plan"]["screens"][0]["visual_proof"] == {
        "method": "material macro"
    }
    prompt = compile_page_prompt(
        structured_plan=structured,
        screen=structured["plan"]["screens"][0],
        page_number=1,
        page_count=2,
        language="zh-CN",
        product_name="",
        product_information=(),
        source_count=2,
        source_roles=("product_reference", "style_reference"),
        size="1200x1600",
        include_protocol_fields=True,
    )
    assert "visible product from supplied images" in prompt
    assert '"buyer_demand_map":{"priority":["trust","proof"]}' in prompt
    assert '"reference_visual_style_lock"' in prompt
    assert '"buyer_demand":"Can I trust what I see?"' in prompt
    assert '"visual_proof":{"method":"material macro"}' in prompt
    assert '"risk_reminder":"Do not infer material"' in prompt
    assert '"physical_logic_lock":{"contact":"grounded"}' in prompt


def test_domestic_protocol_fields_survive_planning_and_reach_generation(
    client: TestClient,
    monkeypatch,
) -> None:
    source = upload_asset(client, filename="domestic-protocol-fields.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
    )
    gateway = _gateway(client)
    original_plan = gateway.plan

    async def plan_with_protocol(request):
        result = await original_plan(request)
        payload = deepcopy(result.payload)
        payload["campaign_thesis"] = "以真实可见结构回答买家信任问题。"
        payload["modules"][0]["visual_proof_direction"] = "展示可见结构证据"
        return replace(result, payload=payload)

    monkeypatch.setattr(gateway, "plan", plan_with_protocol)
    assert dispatch_pending(client) == 1

    with client.app.state.session_factory() as session:
        plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )
        item = session.scalar(
            select(JobItemRecord).where(JobItemRecord.job_id == job["id"])
        )
    assert plan is not None
    assert item is not None
    group = plan.payload["groups"][0]
    assert "aurora_plan" in group["plan_protocol_fields"], sorted(group["plan_protocol_fields"])
    assert "campaign_thesis" in group["plan_protocol_fields"]["aurora_plan"], sorted(group["plan_protocol_fields"]["aurora_plan"])
    assert group["plan_protocol_fields"]["aurora_plan"]["campaign_thesis"] == (
        "以真实可见结构回答买家信任问题。"
    )
    assert "aurora_module" in plan.payload["pages"][0], sorted(
        plan.payload["pages"][0]
    )
    assert plan.payload["pages"][0]["aurora_module"]["visual_proof_direction"] == (
        "展示可见结构证据"
    )
    assert "真实可见结构回答买家信任问题" in item.configuration["prompt"]
    assert "展示可见结构证据" in item.configuration["prompt"]


def test_domestic_resume_signature_includes_source_role() -> None:
    base = {
        "groups": [
            (
                "primary",
                [
                    ("product_reference", "product.png", "a" * 64),
                    ("style_reference", "style.png", "b" * 64),
                ],
            )
        ],
        "base_url": "https://api.example.test",
        "planner_model": "planner",
        "image_model": "image",
        "page_count": 8,
        "language": "zh-CN",
        "product_name": "visible",
        "product_information": [],
        "platform_code": "tmall",
        "size": IMAGE_SIZE,
        "medium_price_micros": 45_000,
        "high_price_micros": 90_000,
    }
    original = build_resume_signature(**base)
    changed = deepcopy(base)
    changed["groups"][0][1][1] = (
        "product_reference",
        "style.png",
        "b" * 64,
    )
    assert build_resume_signature(**changed) != original


def test_domestic_internal_empty_product_name_uses_visible_product_fallback(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="domestic-empty-name.png")
    job = _create_detail_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
    )
    with client.app.state.session_factory() as session:
        record = session.get(JobRecord, job["id"])
        assert record is not None
        configuration = deepcopy(record.configuration)
        configuration["settings"]["product_name"] = ""
        record.configuration = configuration
        session.commit()

    assert dispatch_pending(client) == 1
    gateway = _gateway(client)
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    client.app.state.settings.max_image_pixels = 6_000_000
    client.app.state.storage.validator.max_image_pixels = 6_000_000
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json=_aurora_approval_payload(planned),
    )
    assert confirmed.status_code == 202, confirmed.text
    assert dispatch_pending(client) == 1
    reviewed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert reviewed["status"] == JobStatus.AWAITING_FINAL_REVIEW.value
    assert gateway.planner_calls[0].product_name == (
        "visible product from supplied images"
    )
    assert "visible product from supplied images" in gateway.image_calls[0].prompt


def test_international_plan_requires_confirmation_then_waits_for_manual_qa(
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
    assert completed["status"] == JobStatus.AWAITING_FINAL_REVIEW.value
    assert completed["stage"] == "awaiting_user_final_review"
    assert len(gateway.image_calls) == 8
    assert len(gateway.planner_calls) == 1
    assert _auto_confirm_audit_count(client, str(job["id"])) == 0
