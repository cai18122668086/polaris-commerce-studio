from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from collections.abc import Iterator
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.domain import AssetOriginKind, JobAssetDirection, JobStatus
from app.execution import AttemptLease
from app.main import create_app
from app.models import (
    AssetRecord,
    AuditEventRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    UsageEventRecord,
    WorkspaceLimitRecord,
    utc_now,
)
from app.provider import ProviderRequest
from app.provider_quota import PROVIDER_JOB_QUOTA_ACTION
from app.task_runner import MockTaskRunner
from app.xinghe_agent import (
    IMAGE_FORMAT,
    IMAGE_SIZE,
    JPEG_QUALITY,
    PLAN_SCHEMA_VERSION,
    PLANNING_POLICY_VERSION,
    QUALITY_POLICY_VERSION,
    WORKFLOW_VERSION,
    FakeXingheGateway,
    ImageEditRequest,
    OperationRoutingProvider,
    PlannerRequest,
    SourceImage,
    TengliOpenAICompatibleGateway,
    XingheAgentError,
    XingheImageProvider,
    _artifact_from_bytes,
    _json_pointer,
    _planner_content_payload_with_trace,
    _planner_structure_fingerprint,
    build_resume_signature,
    normalize_usage,
    quality_for_role,
    validate_planner_payload,
)
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset


def _create_detail_job(
    client: TestClient,
    asset_ids: list[str],
    *,
    page_count: int,
    intent: str = "submit",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": intent,
            "display_name": "Bounded Agent gate",
            "input": {
                "product_groups": [
                    {"group_key": "shoe", "asset_ids": asset_ids}
                ]
            },
            "configuration": {
                "product_name": "Visible shoe",
                "selling_points": ["dark upper", "light outsole"],
                "platform_code": "amazon",
                "language": "en",
                "page_count": page_count,
            },
        },
    )
    assert response.status_code == 202
    job = response.json()
    planner = client.app.state.task_runner.coordinator.detail_planner
    gateway = planner.gateway if planner is not None else None
    if getattr(gateway, "provider_name", None) == "tengli":
        # Offline adapter tests bypass HTTP runner selection, so seed the
        # durable authorization that production submission creates.
        with client.app.state.session_factory() as session:
            session.add(
                AuditEventRecord(
                    workspace_id=WORKSPACE_ID,
                    actor_user_id=None,
                    action=PROVIDER_JOB_QUOTA_ACTION,
                    resource_type="job",
                    resource_id=job["id"],
                    request_id=job["id"],
                    details={
                        "estimated_cost_micros": 1,
                        "provider_request_count": 1,
                        "daily_limit_micros": 1,
                        "monthly_limit_micros": 1,
                        "daily_request_limit": 1,
                    },
                )
            )
            session.commit()
    return job


def _gateway(client: TestClient) -> FakeXingheGateway:
    planner = client.app.state.task_runner.coordinator.detail_planner
    assert planner is not None
    gateway = planner.gateway
    assert isinstance(gateway, FakeXingheGateway)
    return gateway


class _OfflineNonMockGateway(FakeXingheGateway):
    """No-network test double that exercises the deliverable provider path."""

    provider_name = "offline-test-provider"
    planner_model = "offline-test-planner"
    image_model = "offline-test-image"
    pricing_version = "offline-test-zero-v1"


@pytest.fixture
def postgres_xinghe_client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "set POLARIS_TEST_DATABASE_URL to run PostgreSQL Agent tests"
        )
    base_url = make_url(database_url)
    if base_url.get_backend_name() != "postgresql":
        raise pytest.UsageError("POLARIS_TEST_DATABASE_URL must use PostgreSQL")
    schema_name = f"xinghe_agent_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    options = str(base_url.query.get("options", "")).strip()
    scoped_url = base_url.update_query_dict(
        {"options": f"{options} -csearch_path={schema_name}".strip()}
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        development_user_id="usr_test",
        development_workspace_id=WORKSPACE_ID,
        development_workspace_name="PostgreSQL Agent",
        access_url_secret="test-access-url-secret",
        database_url=scoped_url.render_as_string(hide_password=False),
        auto_create_schema=True,
        storage_backend="local",
        storage_dir=tmp_path / "storage",
        auto_process_jobs=False,
        task_dispatcher="inline",
        mock_job_delay_seconds=0.03,
        xinghe_concurrency=6,
        max_upload_bytes=2 * 1024 * 1024,
        max_image_pixels=2_000_000,
    )
    try:
        with TestClient(create_app(settings)) as client:
            yield client
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.parametrize("page_count", [1, 8, 12])
def test_exact_page_count_uses_one_planner_call(
    client: TestClient,
    page_count: int,
) -> None:
    source = upload_asset(client, filename=f"shoe-{page_count}.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=page_count)

    assert dispatch_pending(client) == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    gateway = _gateway(client)

    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert len(planned["plan"]["payload"]["pages"]) == page_count
    assert planned["plan"]["payload"]["controls"] == {
        "automatic_reflection_rounds": 0,
        "automatic_review_enabled": False,
        "automatic_redraw_enabled": False,
        "successful_page_auto_redraw_enabled": False,
        "max_failed_page_retries": 2,
    }
    assert len(gateway.planner_calls) == 1
    assert gateway.planner_calls[0].page_count == page_count
    assert gateway.image_calls == []


def test_new_detail_job_pins_v2_all_high_evidence(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="v2-all-high.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=4)

    assert dispatch_pending(client) == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    payload = planned["plan"]["payload"]

    assert planned["release_version"] == WORKFLOW_VERSION
    assert planned["strategy_version"] == PLANNING_POLICY_VERSION
    assert planned["plan"]["schema_version"] == PLAN_SCHEMA_VERSION
    assert payload["workflow_version"] == WORKFLOW_VERSION
    assert [page["quality"] for page in payload["pages"]] == ["high"] * 4
    assert [item["quality"] for item in planned["items"]] == ["high"] * 4
    assert payload["cost"]["pending_high_count"] == 4
    assert payload["cost"]["pending_medium_count"] == 0

    with client.app.state.session_factory() as session:
        plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job["id"])
            .order_by(JobItemRecord.ordinal)
        ).all()

    assert plan is not None
    assert plan.validator_version == PLANNING_POLICY_VERSION
    assert all(
        item.configuration["workflow_version"] == WORKFLOW_VERSION
        and item.configuration["planning_policy_version"]
        == PLANNING_POLICY_VERSION
        and item.configuration["quality_policy_version"]
        == QUALITY_POLICY_VERSION
        for item in items
    )


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("transport", "PLANNER_REQUEST_FAILED"),
        ("invalid_json", "PLANNER_SCHEMA_INVALID"),
        ("schema", "PLANNER_SCHEMA_INVALID"),
        ("wrong_page_count", "PLANNER_SCHEMA_INVALID"),
    ],
)
def test_invalid_planner_fails_group_with_zero_image_calls(
    client: TestClient,
    failure: str,
    expected_code: str,
) -> None:
    gateway = _gateway(client)
    gateway.planner_failure = failure
    source = upload_asset(client, filename=f"{failure}.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=3)

    assert dispatch_pending(client) == 1
    failed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_code"] == expected_code
    assert failed["failed_item_count"] == 3
    assert all(item["status"] == "failed" for item in failed["items"])
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []
    assert failed["plan"]["payload"]["image_request_count"] == 0


def test_missing_planner_fails_closed_without_static_fallback(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="no-planner.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)
    gateway = _gateway(client)
    client.app.state.task_runner.coordinator.detail_planner = None

    assert dispatch_pending(client) == 1
    failed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_code"] == "DETAIL_PLANNER_UNAVAILABLE"
    assert failed["plan"] is None
    assert gateway.planner_calls == []
    assert gateway.image_calls == []


def test_all_ordered_angles_reach_planner_and_every_page(
    client: TestClient,
) -> None:
    sources = [
        upload_asset(client, filename=f"shoe-angle-{index}.jpg")
        for index in range(1, 4)
    ]
    job = _create_detail_job(
        client,
        [source["id"] for source in sources],
        page_count=3,
    )
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    assert len(gateway.planner_calls) == 1
    planner_names = [
        source.filename for source in gateway.planner_calls[0].sources
    ]
    assert planner_names == [f"shoe-angle-{index}.jpg" for index in range(1, 4)]
    assert all(source.payload for source in gateway.planner_calls[0].sources)
    assert gateway.image_calls == []

    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert response.status_code == 202
    assert gateway.image_calls == []
    assert dispatch_pending(client) == 1

    assert len(gateway.image_calls) == 3
    for call in gateway.image_calls:
        assert [source.filename for source in call.sources] == planner_names
        assert all(source.payload for source in call.sources)
        assert call.size == IMAGE_SIZE
        assert call.output_format == IMAGE_FORMAT
        assert call.jpeg_quality == JPEG_QUALITY
        assert call.prompt.startswith(
            "e-commerce detail page image; exact canvas 1024x1536 (2:3)"
        )
        assert "source marks, never as product branding" in call.prompt


@pytest.mark.parametrize("concurrency", [1, 2, 6])
def test_bounded_configurable_image_concurrency(
    settings: Settings,
    concurrency: int,
) -> None:
    configured = settings.model_copy(
        update={
            "xinghe_concurrency": concurrency,
            "mock_job_delay_seconds": 0.03,
        }
    )
    with TestClient(create_app(configured)) as client:
        source = upload_asset(client, filename=f"c{concurrency}.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=6)
        gateway = _gateway(client)

        assert dispatch_pending(client) == 1
        assert (
            client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
                headers=idem(),
                json={"expected_revision": 1},
            ).status_code
            == 202
        )
        assert dispatch_pending(client) == 1
        assert gateway.max_active_images == concurrency


def test_postgres_agent_concurrency_retry_and_usage_are_durable(
    postgres_xinghe_client: TestClient,
) -> None:
    client = postgres_xinghe_client
    sources = [
        upload_asset(client, filename=f"postgres-angle-{index}.jpg")
        for index in range(3)
    ]
    gateway = _gateway(client)
    gateway.image_failures = {2: 1}
    job = _create_detail_job(
        client,
        [source["id"] for source in sources],
        page_count=6,
    )

    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    with client.app.state.session_factory() as session:
        attempts = session.scalar(
            select(func.count())
            .select_from(JobAttemptRecord)
            .where(JobAttemptRecord.job_id == job["id"])
        )
        usages = session.scalar(
            select(func.count())
            .select_from(UsageEventRecord)
            .where(UsageEventRecord.job_id == job["id"])
        )

    assert completed["status"] == JobStatus.COMPLETED.value
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 7
    assert gateway.max_active_images == 6
    assert attempts == 7
    assert usages == 7
    assert all(len(call.sources) == 3 for call in gateway.image_calls)


def test_failed_pages_retry_twice_and_successes_never_retry(
    client: TestClient,
) -> None:
    gateway = _gateway(client)
    gateway.image_failures = {2: 2, 3: 3}
    source = upload_asset(client, filename="retry.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=3)

    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    partial = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    page_calls = {
        page: sum(call.page_number == page for call in gateway.image_calls)
        for page in (1, 2, 3)
    }

    assert partial["status"] == JobStatus.PARTIAL.value
    assert page_calls == {1: 1, 2: 3, 3: 3}
    assert partial["succeeded_item_count"] == 2
    assert partial["failed_item_count"] == 1

    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers=idem(),
        json={"scope": "failed", "item_ids": []},
    )
    assert retried.status_code == 201
    retry_cost = retried.json()["plan"]["payload"]["cost"]
    assert (
        retry_cost["pending_medium_count"] + retry_cost["pending_high_count"]
        == 1
    )
    assert retried.json()["plan"]["payload"]["usage"]["planner"] == []
    assert dispatch_pending(client) == 1
    resumed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{retried.json()['id']}"
    ).json()

    assert resumed["status"] == JobStatus.COMPLETED.value
    assert len(gateway.planner_calls) == 1
    assert sum(call.page_number == 1 for call in gateway.image_calls) == 1
    assert sum(call.page_number == 2 for call in gateway.image_calls) == 3
    assert sum(call.page_number == 3 for call in gateway.image_calls) == 4
    assert sum(item["result_source"] == "reused" for item in resumed["items"]) == 2


def test_plan_edit_changes_quality_and_resume_signature_before_dispatch(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="edit-plan.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=3)
    assert dispatch_pending(client) == 1
    gateway = _gateway(client)
    with client.app.state.session_factory() as session:
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job["id"])
            .order_by(JobItemRecord.ordinal)
        ).all()
        original_signature = items[2].configuration["resume_signature"]
        assert items[2].quality == "high"

    current = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    payload = deepcopy(current["plan"]["payload"])
    payload["pages"][2]["role"] = "Macro texture close-up"
    payload["pages"][2]["title"] = "Visible texture"
    updated = client.put(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan",
        json={"expected_revision": 1, "payload": payload},
    )
    assert updated.status_code == 200
    assert updated.json()["validation_status"] == "valid"
    assert gateway.image_calls == []

    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 2},
    )
    assert confirmed.status_code == 202
    assert gateway.image_calls == []
    with client.app.state.session_factory() as session:
        item = session.scalar(
            select(JobItemRecord).where(
                JobItemRecord.job_id == job["id"],
                JobItemRecord.ordinal == 2,
            )
        )
        assert item is not None
        assert item.quality == "high"
        assert item.configuration["resume_signature"] != original_signature


def test_unreported_usage_is_explicit_and_metrics_are_distinct(
    client: TestClient,
) -> None:
    gateway = _gateway(client)
    gateway.usage_reported = False
    source = upload_asset(client, filename="usage.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)

    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    metrics = completed["plan"]["payload"]["metrics"]
    with client.app.state.session_factory() as session:
        events = session.scalars(
            select(UsageEventRecord).where(UsageEventRecord.job_id == job["id"])
        ).all()

    assert completed["status"] == JobStatus.COMPLETED.value
    assert completed["cost"]["usage_completeness"] == "none"
    assert all(event.usage_reported is False for event in events)
    assert all(event.input_tokens is None for event in events)
    assert all(event.raw_usage["raw"] is None for event in events)
    assert metrics["average_api_latency"] is not None
    assert metrics["image_wall_time"] is not None
    assert metrics["effective_seconds_per_page"] is not None
    assert metrics["throughput_pages_per_second"] > 0
    assert metrics["job_wall_time"] is not None
    assert metrics["usage_missing_count"] == 3


def test_throughput_metric_has_stable_zero_and_completed_semantics(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="throughput-lifecycle.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)

    assert dispatch_pending(client) == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert (
        planned["plan"]["payload"]["metrics"]["throughput_pages_per_second"]
        == 0.0
    )

    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 202
    assert (
        confirmed.json()["plan"]["payload"]["metrics"][
            "throughput_pages_per_second"
        ]
        == 0.0
    )

    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    metrics = completed["plan"]["payload"]["metrics"]
    assert completed["status"] == JobStatus.COMPLETED.value
    assert metrics["success_count"] == 2
    assert metrics["image_wall_time"] > 0
    assert metrics["throughput_pages_per_second"] == pytest.approx(
        metrics["success_count"] / metrics["image_wall_time"]
    )
    persisted = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()["plan"]["payload"]["metrics"]
    assert persisted["throughput_pages_per_second"] == pytest.approx(
        metrics["throughput_pages_per_second"]
    )


def test_budget_and_manifest_preflight_happen_before_provider(
    settings: Settings,
) -> None:
    configured = settings.model_copy(
        update={
            "tengli_smoke_budget_usd": 0.00001,
            "xinghe_medium_price_micros": 45_000,
            "xinghe_high_price_micros": 90_000,
        }
    )
    with TestClient(create_app(configured)) as client:
        source = upload_asset(client, filename="budget.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=1)
        gateway = _gateway(client)

        assert dispatch_pending(client) == 1
        failed = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()

        assert failed["status"] == JobStatus.FAILED.value
        assert failed["error_code"] == "BUDGET_LIMIT_EXCEEDED"
        assert gateway.planner_calls == []
        assert gateway.image_calls == []


class _Budget429Transport:
    def __init__(self, page_count: int) -> None:
        self.page_count = page_count
        self.planner_calls = 0
        self.image_calls = 0

    async def post_json(self, **_: Any) -> tuple[int, dict[str, Any]]:
        self.planner_calls += 1
        return (
            200,
            {
                "id": "offline-planner",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                _valid_planner_content(self.page_count)
                            )
                        }
                    }
                ],
            },
        )

    async def post_multipart(self, **_: Any) -> tuple[int, dict[str, Any]]:
        self.image_calls += 1
        return 429, {"id": f"offline-429-{self.image_calls}"}


def _valid_planner_content(page_count: int) -> dict[str, Any]:
    roles = [
        "hero_cover",
        "buyer_objection",
        "scenario_proof",
        "structure_detail",
        "material_macro",
        "feature_evidence",
        "closing_summary",
    ]
    structures = [
        "asymmetric hero",
        "split evidence",
        "deep scene",
        "cutaway detail",
        "macro strip",
        "comparison grid",
        "closing stack",
    ]
    scales = ["hero", "medium", "scene", "macro", "cutaway"]
    devices = ["speed halo", "material magnifier", "floating proof card"]
    screens = []
    for index in range(page_count):
        role = roles[index % len(roles)]
        if page_count > 1 and index == page_count - 1:
            role = "closing_summary"
        screens.append(
            {
                "role": role,
                "title": f"Title {index + 1}",
                "label": f"Label {index + 1}",
                "composition": f"Composition {index + 1}",
                "device": devices[index % len(devices)],
                "difference": f"Difference {index + 1}",
                "structure": structures[index % len(structures)],
                "subject_scale": scales[index % len(scales)],
            }
        )
    return {
        "analysis": {
            "category_key": "fashion",
            "category_reason": "visible",
            "product_image_analysis": {"visible_facts": []},
            "product_consistency_anchors": {},
            "buyer_objections": ["appearance"],
        },
        "plan": {
            "campaign_style_lock": {
                "palette": "black, ivory, and one electric accent",
                "typography": "bold editorial sans",
                "background": "layered studio gradients",
                "lighting": "directional premium key light",
                "icon_style": "minimal outlined proof icons",
                "whitespace": "intentional asymmetric breathing room",
                "product_scale": "varied hero, medium, and macro scales",
            },
            "design_strength_lock": {
                "category_visual_motif": "fashion runway motion",
                "composition_contrast": "alternate hero, split, scene, and macro",
                "signature_devices": [
                    "speed halo",
                    "material magnifier",
                    "floating proof card",
                ],
                "color_contrast": "dark-light alternation with electric accent",
                "template_ban": "no repeated centered-product template",
                "rhythm_map": [
                    f"page {index + 1}: {structures[index % len(structures)]}"
                    for index in range(page_count)
                ],
            },
            "screens": screens,
        },
    }


def _planner_validation_path_cases() -> list[Any]:
    cases: list[Any] = [
        pytest.param(7, 1, "/", id="root"),
        pytest.param(
            {"plan": _valid_planner_content(1)["plan"]},
            1,
            "/analysis",
            id="analysis",
        ),
        pytest.param(
            {"analysis": _valid_planner_content(1)["analysis"]},
            1,
            "/plan",
            id="plan",
        ),
    ]
    mutations = [
        (
            "category-key",
            ("analysis", "category_key"),
            "",
            "/analysis/category_key",
        ),
        (
            "product-image-analysis",
            ("analysis", "product_image_analysis"),
            [],
            "/analysis/product_image_analysis",
        ),
        (
            "buyer-objections",
            ("analysis", "buyer_objections"),
            [],
            "/analysis/buyer_objections",
        ),
        (
            "campaign-style-lock",
            ("plan", "campaign_style_lock"),
            [],
            "/plan/campaign_style_lock",
        ),
        (
            "design-strength-lock",
            ("plan", "design_strength_lock"),
            None,
            "/plan/design_strength_lock",
        ),
        (
            "screens-type",
            ("plan", "screens"),
            {},
            "/plan/screens",
        ),
        (
            "screen-item",
            ("plan", "screens", 0),
            7,
            "/plan/screens/0",
        ),
        (
            "screen-title",
            ("plan", "screens", 0, "title"),
            " ",
            "/plan/screens/0/title",
        ),
    ]
    for case_id, path, replacement, expected_path in mutations:
        payload = _valid_planner_content(1)
        target: Any = payload
        for token in path[:-1]:
            target = target[token]
        target[path[-1]] = replacement
        cases.append(
            pytest.param(payload, 1, expected_path, id=case_id)
        )
    cases.append(
        pytest.param(
            _valid_planner_content(1),
            2,
            "/plan/screens",
            id="screen-count",
        )
    )
    return cases


@pytest.mark.parametrize(
    ("payload", "page_count", "expected_path"),
    _planner_validation_path_cases(),
)
def test_planner_schema_errors_use_json_pointer_paths(
    payload: object,
    page_count: int,
    expected_path: str,
) -> None:
    with pytest.raises(XingheAgentError) as exc_info:
        validate_planner_payload(payload, page_count)

    assert exc_info.value.code == "PLANNER_SCHEMA_INVALID"
    assert exc_info.value.json_pointer == expected_path


def test_complete_planner_mapping_missing_consistency_anchors_fails_closed() -> None:
    payload = _valid_planner_content(1)
    del payload["analysis"]["product_consistency_anchors"]

    with pytest.raises(XingheAgentError) as exc_info:
        validate_planner_payload(payload, 1)

    assert exc_info.value.code == "PLANNER_SCHEMA_INVALID"
    assert exc_info.value.json_pointer == (
        "/analysis/product_consistency_anchors"
    )
    assert "product_consistency_anchors" not in payload["analysis"]


def test_valid_planner_mapping_with_consistency_anchors_passes() -> None:
    payload = _valid_planner_content(1)

    validated = validate_planner_payload(payload, 1)

    assert validated["analysis"]["product_consistency_anchors"] == {}


def test_json_pointer_escapes_reference_tokens() -> None:
    assert _json_pointer() == "/"
    assert _json_pointer("a/b", "~key", 0) == "/a~1b/~0key/0"


@pytest.mark.parametrize(
    ("content", "expected_trace", "decoded"),
    [
        (
            json.dumps(_valid_planner_content(1)),
            ("whole_json:decoded", "whole_json:decoded_kind:mapping"),
            True,
        ),
        (
            f"```json\n{json.dumps(_valid_planner_content(1))}\n```",
            (
                "whole_json:decode_failed",
                "fence:matched",
                "fence_json:decoded",
                "fence_json:decoded_kind:mapping",
            ),
            True,
        ),
        (
            "unsafe raw planner content",
            (
                "whole_json:decode_failed",
                "fence:not_matched",
            ),
            False,
        ),
        (
            "```json\n{not-json}\n```",
            (
                "whole_json:decode_failed",
                "fence:matched",
                "fence_json:decode_failed",
            ),
            False,
        ),
    ],
    ids=["whole-json", "fenced-json", "not-fenced", "invalid-fenced-json"],
)
def test_planner_parse_trace_is_fixed_and_content_free(
    content: str,
    expected_trace: tuple[str, ...],
    decoded: bool,
) -> None:
    payload, trace = _planner_content_payload_with_trace(content)

    assert trace == expected_trace
    assert isinstance(payload, dict) is decoded
    assert content not in json.dumps(trace)


@pytest.mark.parametrize(
    ("content", "expected_kind"),
    [
        ("[]", "list"),
        ("7", "scalar"),
        ("null", "null"),
        ("```json\n[]\n```", "list"),
        ("```\nfalse\n```", "scalar"),
        ("```json\nnull\n```", "null"),
    ],
)
def test_planner_parse_trace_records_decoded_kind(
    content: str,
    expected_kind: str,
) -> None:
    _, trace = _planner_content_payload_with_trace(content)

    assert trace[-1].endswith(f"decoded_kind:{expected_kind}")


def test_planner_structure_fingerprint_uses_shape_not_values() -> None:
    first = _valid_planner_content(1)
    same_shape = deepcopy(first)
    same_shape["analysis"]["category_key"] = "secret-category-value"
    same_shape["plan"]["screens"][0]["title"] = "secret-title-value"
    changed_shape = deepcopy(first)
    del changed_shape["plan"]["screens"][0]["title"]

    first_fingerprint = _planner_structure_fingerprint(first)
    assert _planner_structure_fingerprint(same_shape) == first_fingerprint
    assert _planner_structure_fingerprint(changed_shape) != first_fingerprint
    assert len(first_fingerprint) == 64
    assert "secret" not in first_fingerprint


class _PlannerContentTransport(_Budget429Transport):
    def __init__(self, content: str, *, page_count: int) -> None:
        super().__init__(page_count)
        self.content = content

    async def post_json(self, **_: Any) -> tuple[int, dict[str, Any]]:
        self.planner_calls += 1
        return (
            200,
            {
                "id": "offline-planner-content",
                "choices": [{"message": {"content": self.content}}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )


class _PlannerEnvelopeTransport(_Budget429Transport):
    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__(1)
        self.response = response

    async def post_json(self, **_: Any) -> tuple[int, dict[str, Any]]:
        self.planner_calls += 1
        return 200, deepcopy(self.response)


def _install_budget_runner(
    client: TestClient,
    transport: _Budget429Transport,
    *,
    budget_limit_micros: int,
    concurrency: int,
) -> TengliOpenAICompatibleGateway:
    gateway = TengliOpenAICompatibleGateway(
        api_key="offline-placeholder",
        base_url="https://offline.invalid",
        planner_model="planner",
        image_model="image",
        transport=transport,
        medium_price_micros=45_000,
        high_price_micros=90_000,
    )
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=concurrency,
        budget_limit_micros=budget_limit_micros,
        medium_price_micros=45_000,
        high_price_micros=90_000,
    )
    return gateway


def test_tengli_planner_fails_closed_without_durable_provider_quota(
    client: TestClient,
) -> None:
    transport = _Budget429Transport(page_count=1)
    _install_budget_runner(
        client,
        transport,
        budget_limit_micros=200_000_000,
        concurrency=1,
    )
    source = upload_asset(client, filename="quota-gate.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=1)
    with client.app.state.session_factory() as session:
        reservation = session.scalar(
            select(AuditEventRecord).where(
                AuditEventRecord.action == PROVIDER_JOB_QUOTA_ACTION,
                AuditEventRecord.resource_id == job["id"],
            )
        )
        assert reservation is not None
        session.delete(reservation)
        session.commit()

    assert dispatch_pending(client) == 1
    failed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert failed["status"] == JobStatus.FAILED.value
    assert failed["error_code"] == "PROVIDER_QUOTA_RESERVATION_MISSING"
    assert transport.planner_calls == 0
    assert transport.image_calls == 0


@pytest.mark.parametrize(
    (
        "response",
        "expected_envelope",
        "expected_bytes",
        "expected_sha256",
        "expected_request_id",
        "expected_usage",
    ),
    [
        (
            {},
            {
                "envelope_kind": "mapping",
                "choices_kind": "missing",
                "choices_count": None,
                "choice0_kind": "missing",
                "message_kind": "missing",
                "content_kind": "missing",
            },
            None,
            None,
            "absent",
            ("absent", "absent"),
        ),
        (
            {"choices": []},
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 0,
                "choice0_kind": "missing",
                "message_kind": "missing",
                "content_kind": "missing",
            },
            None,
            None,
            "absent",
            ("absent", "absent"),
        ),
        (
            {
                "id": "secret-request-id",
                "choices": [
                    {"message": {"content": []}},
                    {"message": {"content": "ignored"}},
                ],
                "usage": {},
            },
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 2,
                "choice0_kind": "mapping",
                "message_kind": "mapping",
                "content_kind": "list",
            },
            None,
            None,
            "present",
            ("present", "incomplete"),
        ),
        (
            {
                "choices": [{"message": {"content": {"unsafe": "value"}}}],
                "usage": {"input_tokens": 1},
            },
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 1,
                "choice0_kind": "mapping",
                "message_kind": "mapping",
                "content_kind": "mapping",
            },
            None,
            None,
            "absent",
            ("present", "incomplete"),
        ),
        (
            {
                "choices": [{"message": {"content": None}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            },
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 1,
                "choice0_kind": "mapping",
                "message_kind": "mapping",
                "content_kind": "null",
            },
            None,
            None,
            "absent",
            ("present", "complete"),
        ),
        (
            {"choices": [{"message": {"content": ""}}]},
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 1,
                "choice0_kind": "mapping",
                "message_kind": "mapping",
                "content_kind": "string",
            },
            0,
            hashlib.sha256(b"").hexdigest(),
            "absent",
            ("absent", "absent"),
        ),
        (
            {"choices": [{"message": {"content": "机密正文"}}]},
            {
                "envelope_kind": "mapping",
                "choices_kind": "list",
                "choices_count": 1,
                "choice0_kind": "mapping",
                "message_kind": "mapping",
                "content_kind": "string",
            },
            len(bytes("机密正文", "utf-8")),
            hashlib.sha256(bytes("机密正文", "utf-8")).hexdigest(),
            "absent",
            ("absent", "absent"),
        ),
    ],
    ids=[
        "choices-missing",
        "choices-empty",
        "choices-multiple-array-content",
        "object-content",
        "null-content-complete-usage",
        "empty-string-content",
        "unicode-string-content",
    ],
)
def test_raw_planner_envelope_diagnostics_are_safe_and_durable(
    settings: Settings,
    response: dict[str, Any],
    expected_envelope: dict[str, Any],
    expected_bytes: int | None,
    expected_sha256: str | None,
    expected_request_id: str,
    expected_usage: tuple[str, str],
) -> None:
    with TestClient(create_app(settings)) as client:
        transport = _PlannerEnvelopeTransport(response)
        _install_budget_runner(
            client,
            transport,
            budget_limit_micros=200_000_000,
            concurrency=1,
        )
        source = upload_asset(client, filename="raw-envelope.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=1)

        assert dispatch_pending(client) == 1
        failed = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()

        assert failed["status"] == JobStatus.FAILED.value
        expected_error = (
            "PLANNER_SCHEMA_INVALID"
            if expected_bytes not in (None, 0)
            else "PLANNER_RESPONSE_INVALID"
        )
        assert failed["error_code"] == expected_error
        diagnostics = failed["plan"]["payload"]["planner_diagnostics"][0]
        expected_trace = (
            ["whole_json:decode_failed", "fence:not_matched"]
            if expected_bytes not in (None, 0)
            else ["provider_payload:rejected_before_json_parse"]
        )
        assert diagnostics == {
            "schema": "xinghe-planner-diagnostics",
            "version": "xinghe-planner-observability-v2",
            "parse_trace": expected_trace,
            "structure_fingerprint": diagnostics["structure_fingerprint"],
            "provider_envelope": expected_envelope,
            "content_utf8_bytes": expected_bytes,
            "content_sha256": expected_sha256,
            "request_id_presence": expected_request_id,
            "usage_presence": expected_usage[0],
            "usage_completeness": expected_usage[1],
        }
        assert len(diagnostics["structure_fingerprint"]) == 64
        persisted = json.dumps(failed, ensure_ascii=False, sort_keys=True)
        assert "secret-request-id" not in persisted
        assert "机密正文" not in persisted
        assert '"unsafe": "value"' not in persisted


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(_valid_planner_content(6)),
        f"```json\n{json.dumps(_valid_planner_content(6))}\n```",
        f"```JSON  \r\n{json.dumps(_valid_planner_content(6))}\r\n```\t",
        f"\n\t``` \t\n{json.dumps(_valid_planner_content(6))}\n```\n ",
    ],
    ids=[
        "whole-object",
        "json-fence",
        "uppercase-json-tag-with-horizontal-whitespace",
        "untagged-fence-with-boundary-whitespace",
    ],
)
def test_strict_planner_content_reaches_confirmation_gate(
    settings: Settings,
    content: str,
) -> None:
    page_count = 6
    with TestClient(create_app(settings)) as client:
        transport = _PlannerContentTransport(content, page_count=page_count)
        _install_budget_runner(
            client,
            transport,
            budget_limit_micros=200_000_000,
            concurrency=6,
        )
        source = upload_asset(client, filename="fenced-planner.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=page_count)

        assert dispatch_pending(client) == 1
        planned = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()

        assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
        plan_payload = planned["plan"]["payload"]
        assert len(plan_payload["pages"]) == page_count
        assert (
            plan_payload.get("planner_request_count", transport.planner_calls) == 1
        )
        assert plan_payload.get("image_request_count", transport.image_calls) == 0
        assert len(plan_payload["usage"]["planner"]) == 1
        assert plan_payload["usage"]["image"]["reported_requests"] == 0
        assert plan_payload["metrics"]["usage_missing_count"] == 0
        planner_usage = plan_payload["usage"]["planner"][0]
        assert planner_usage["reported"] is True
        assert planner_usage["normalized"]["total_tokens"] == 150
        assert planner_usage["actual_cost_micros"] is None
        assert plan_payload["cost"]["budget_limit_micros"] == 200_000_000
        assert plan_payload["cost"]["estimated_pending_micros"] == 540_000
        diagnostics = plan_payload["planner_diagnostics"]
        assert len(diagnostics) == 1
        assert diagnostics[0]["schema"] == "xinghe-planner-diagnostics"
        assert diagnostics[0]["version"] == "xinghe-planner-observability-v2"
        assert diagnostics[0]["parse_trace"][-2].endswith(":decoded")
        assert diagnostics[0]["parse_trace"][-1].endswith(
            ":decoded_kind:mapping"
        )
        raw_content = content.encode("utf-8")
        assert diagnostics[0]["content_utf8_bytes"] == len(raw_content)
        assert diagnostics[0]["content_sha256"] == hashlib.sha256(
            raw_content
        ).hexdigest()
        assert diagnostics[0]["provider_envelope"] == {
            "envelope_kind": "mapping",
            "choices_kind": "list",
            "choices_count": 1,
            "choice0_kind": "mapping",
            "message_kind": "mapping",
            "content_kind": "string",
        }
        assert diagnostics[0]["request_id_presence"] == "present"
        assert diagnostics[0]["usage_presence"] == "present"
        assert diagnostics[0]["usage_completeness"] == "complete"
        assert len(diagnostics[0]["structure_fingerprint"]) == 64
        assert set(diagnostics[0]["structure_fingerprint"]) <= set(
            "0123456789abcdef"
        )
        assert transport.planner_calls == 1
        assert transport.image_calls == 0


@pytest.mark.parametrize(
    ("content", "expected_code", "expected_path"),
    [
        ("plain non-JSON text", "PLANNER_SCHEMA_INVALID", "/"),
        ("7", "PLANNER_SCHEMA_INVALID", "/"),
        ('[{"analysis": {}, "plan": {}}]', "PLANNER_SCHEMA_INVALID", "/"),
        (
            f"{json.dumps(_valid_planner_content(6))}\n"
            f"{json.dumps(_valid_planner_content(6))}",
            "PLANNER_SCHEMA_INVALID",
            "/",
        ),
        (
            f"```json\n{json.dumps(_valid_planner_content(6))}\n```\n"
            "```\n7\n```",
            "PLANNER_SCHEMA_INVALID",
            "/",
        ),
        (
            f"Planner result:\n```json\n"
            f"{json.dumps(_valid_planner_content(6))}\n```",
            "PLANNER_SCHEMA_INVALID",
            "/",
        ),
        (
            f"```json\n{json.dumps(_valid_planner_content(6))}\n```\n"
            "End of planner result.",
            "PLANNER_SCHEMA_INVALID",
            "/",
        ),
        (
            f"```json\n{json.dumps(_valid_planner_content(6))}",
            "PLANNER_SCHEMA_INVALID",
            "/",
        ),
        (
            json.dumps({"analysis": {}, "plan": {}}),
            "PLANNER_SCHEMA_INVALID",
            "/analysis/category_key",
        ),
        (
            f"```json\n{json.dumps(_valid_planner_content(5))}\n```",
            "PLANNER_SCHEMA_INVALID",
            "/plan/screens",
        ),
    ],
    ids=[
        "plain-text",
        "json-scalar",
        "json-array",
        "ambiguous-multiple-objects",
        "multiple-fences-second-scalar",
        "nonempty-prefix",
        "nonempty-suffix",
        "malformed-fence",
        "missing-fields",
        "non-six-pages",
    ],
)
def test_unsafe_planner_content_fails_closed_before_image(
    settings: Settings,
    content: str,
    expected_code: str,
    expected_path: str,
) -> None:
    page_count = 6
    with TestClient(create_app(settings)) as client:
        transport = _PlannerContentTransport(content, page_count=page_count)
        _install_budget_runner(
            client,
            transport,
            budget_limit_micros=200_000_000,
            concurrency=6,
        )
        source = upload_asset(client, filename="invalid-planner-content.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=page_count)

        assert dispatch_pending(client) == 1
        failed = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()

        assert failed["status"] == JobStatus.FAILED.value
        assert failed["error_code"] == expected_code
        assert failed["plan"]["validation_errors"] == [
            {
                "code": expected_code,
                "message": failed["error_message"],
                "path": expected_path,
            }
        ]
        plan_payload = failed["plan"]["payload"]
        assert plan_payload["planner_request_count"] == 1
        assert plan_payload["image_request_count"] == 0
        assert len(plan_payload.get("pages", [])) == 0
        planner_usage = plan_payload["usage"]["planner"][0]
        assert planner_usage["reported"] is True
        assert planner_usage["normalized"]["total_tokens"] == 150
        assert planner_usage["actual_cost_micros"] is None
        assert plan_payload.get("cost", {}).get("budget_limit_micros") is None
        assert plan_payload.get("cost", {}).get("estimated_pending_micros") is None
        diagnostics = plan_payload["planner_diagnostics"]
        assert len(diagnostics) == 1
        assert diagnostics[0]["schema"] == "xinghe-planner-diagnostics"
        assert diagnostics[0]["version"] == "xinghe-planner-observability-v2"
        assert diagnostics[0]["parse_trace"]
        assert len(diagnostics[0]["structure_fingerprint"]) == 64
        with client.app.state.session_factory() as session:
            audit = session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.resource_id == job["id"],
                    AuditEventRecord.action == "xinghe.planning_failed",
                )
            )
        assert audit is not None
        assert audit.details["error_path"] == expected_path
        assert audit.details["planner_diagnostics"] == diagnostics
        assert transport.planner_calls == 1
        assert transport.image_calls == 0


def test_planner_diagnostics_never_persist_response_content(
    settings: Settings,
) -> None:
    marker = "sensitive-planner-response-marker"
    with TestClient(create_app(settings)) as client:
        transport = _PlannerContentTransport(marker, page_count=1)
        _install_budget_runner(
            client,
            transport,
            budget_limit_micros=200_000_000,
            concurrency=1,
        )
        source = upload_asset(client, filename="diagnostics-redaction.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=1)

        assert dispatch_pending(client) == 1
        failed = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()
        with client.app.state.session_factory() as session:
            audit = session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.resource_id == job["id"],
                    AuditEventRecord.action == "xinghe.planning_failed",
                )
            )

        assert failed["status"] == JobStatus.FAILED.value
        assert failed["plan"]["validation_errors"][0]["path"] == "/"
        assert marker not in json.dumps(failed, sort_keys=True)
        assert audit is not None
        assert marker not in json.dumps(audit.details, sort_keys=True)
        assert transport.planner_calls == 1
        assert transport.image_calls == 0


def _confirm_job(client: TestClient, job_id: str) -> None:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job_id}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert response.status_code == 202


def test_retry_budget_is_cumulative_and_fails_before_extra_provider_call(
    settings: Settings,
) -> None:
    configured = settings.model_copy(
        update={
            "tengli_smoke_budget_usd": 0.09,
            "xinghe_medium_price_micros": 45_000,
            "xinghe_high_price_micros": 90_000,
            "xinghe_concurrency": 1,
        }
    )
    with TestClient(create_app(configured)) as client:
        transport = _Budget429Transport(page_count=1)
        _install_budget_runner(
            client,
            transport,
            budget_limit_micros=90_000,
            concurrency=1,
        )
        source = upload_asset(client, filename="budget-retry.jpg")
        job = _create_detail_job(client, [source["id"]], page_count=1)

        assert dispatch_pending(client) == 1
        _confirm_job(client, job["id"])
        assert dispatch_pending(client) == 1
        assert transport.planner_calls == 1
        assert transport.image_calls == 1

        failed = client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json()
        assert failed["status"] == JobStatus.FAILED.value
        with client.app.state.session_factory() as session:
            audits = session.scalars(
                select(AuditEventRecord)
                .where(
                    AuditEventRecord.request_id.in_(
                        select(JobAttemptRecord.id).where(
                            JobAttemptRecord.job_id == job["id"]
                        )
                    ),
                    AuditEventRecord.action.in_(
                        [
                            "xinghe.image_reserved",
                            "xinghe.image_budget_rejected",
                        ]
                    ),
                )
                .order_by(AuditEventRecord.id)
            ).all()
            usages = session.scalars(
                select(UsageEventRecord).where(
                    UsageEventRecord.job_id == job["id"]
                )
            ).all()
            credit_reservation = session.scalar(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.job_id == job["id"]
                )
            )
        reserved = [
            event for event in audits if event.action == "xinghe.image_reserved"
        ]
        rejected = [
            event
            for event in audits
            if event.action == "xinghe.image_budget_rejected"
        ]
        assert len(reserved) == 1
        assert len(rejected) == 1
        assert sum(
            int(event.details["estimated_cost_micros"])
            for event in reserved
        ) == 90_000
        assert rejected[0].details["cumulative_exposure_micros"] == 180_000
        assert sum(event.estimated_cost_micros or 0 for event in usages) == 90_000
        assert sorted(
            bool(event.raw_usage["metrics"]["provider_called"])
            for event in usages
        ) == [False, True]
        assert credit_reservation is not None
        assert credit_reservation.status == "settled"
        assert credit_reservation.settled_credits == 0


def test_concurrent_and_duplicate_delivery_cannot_oversubscribe_budget(
    postgres_xinghe_client: TestClient,
) -> None:
    client = postgres_xinghe_client
    transport = _Budget429Transport(page_count=2)
    _install_budget_runner(
        client,
        transport,
        budget_limit_micros=180_000,
        concurrency=2,
    )
    source = upload_asset(client, filename="budget-concurrent.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)

    assert dispatch_pending(client) == 1
    _confirm_job(client, job["id"])
    assert dispatch_pending(client) == 1
    assert transport.image_calls == 2
    assert asyncio.run(client.app.state.task_runner.run(job["id"])) == JobStatus.FAILED
    assert transport.image_calls == 2
    with client.app.state.session_factory() as session:
        reservations = session.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.action == "xinghe.image_reserved",
                AuditEventRecord.request_id.in_(
                    select(JobAttemptRecord.id).where(
                        JobAttemptRecord.job_id == job["id"]
                    )
                ),
            )
            .order_by(AuditEventRecord.id)
        ).all()
    assert sum(
        int(event.details["estimated_cost_micros"])
        for event in reservations
    ) == 180_000


def test_budget_reservation_survives_duplicate_attempt_and_worker_recovery(
    client: TestClient,
) -> None:
    transport = _Budget429Transport(page_count=1)
    gateway = _install_budget_runner(
        client,
        transport,
        budget_limit_micros=90_000,
        concurrency=1,
    )
    source = upload_asset(client, filename="budget-recovery.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=1)
    assert dispatch_pending(client) == 1
    _confirm_job(client, job["id"])

    coordinator = client.app.state.task_runner.coordinator
    assert coordinator.prepare(job["id"]) == JobStatus.PROCESSING
    lease = coordinator.claim_next_item(job["id"])
    assert isinstance(lease, AttemptLease)
    assert coordinator.mark_provider_started(lease) is True
    routed = coordinator.provider
    assert isinstance(routed, OperationRoutingProvider)
    detail_provider = routed.detail_provider
    assert isinstance(detail_provider, XingheImageProvider)
    request = ProviderRequest(
        workspace_id=lease.workspace_id,
        job_id=lease.job_id,
        job_item_id=lease.item_id,
        attempt_id=lease.attempt_id,
        operation=lease.operation,
        idempotency_key=lease.provider_idempotency_key,
        configuration=lease.configuration,
    )
    configuration, sources = detail_provider._authorize(request)
    detail_provider._reserve_call_budget(
        request,
        configuration,
        source_count=len(sources),
    )
    with pytest.raises(XingheAgentError) as exc_info:
        detail_provider._reserve_call_budget(
            request,
            configuration,
            source_count=len(sources),
        )
    assert exc_info.value.code == "IMAGE_CALL_ALREADY_RESERVED"

    with client.app.state.session_factory() as session:
        attempt = session.get(JobAttemptRecord, lease.attempt_id)
        assert attempt is not None
        attempt.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    recovery = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=1,
        budget_limit_micros=90_000,
        medium_price_micros=45_000,
        high_price_micros=90_000,
    )
    assert asyncio.run(recovery.run(job["id"])) == JobStatus.FAILED
    assert transport.image_calls == 0
    with client.app.state.session_factory() as session:
        reservations = session.scalar(
            select(func.count())
            .select_from(AuditEventRecord)
            .where(
                AuditEventRecord.action == "xinghe.image_reserved",
                AuditEventRecord.request_id == lease.attempt_id,
            )
        )
    assert reservations == 1


def test_mock_detail_pack_discards_artifacts_before_storage(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="mock-artifact.jpg")
    storage_root = client.app.state.settings.storage_dir
    before_files = sorted(
        path.relative_to(storage_root)
        for path in storage_root.rglob("*")
        if path.is_file()
    )
    with client.app.state.session_factory() as session:
        before_asset_count = int(
            session.scalar(select(func.count()).select_from(AssetRecord)) or 0
        )
        before_asset_bytes = int(
            session.scalar(
                select(func.coalesce(func.sum(AssetRecord.byte_size), 0))
            )
            or 0
        )
        limits = session.get(WorkspaceLimitRecord, WORKSPACE_ID)
        assert limits is not None
        before_quota = limits.storage_quota_bytes

    job = _create_detail_job(client, [source["id"]], page_count=2)
    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert completed["status"] == JobStatus.COMPLETED.value
    assert all(item["result_source"] == "mock" for item in completed["items"])
    assert not [
        relation
        for relation in completed["assets"]
        if relation["direction"] == JobAssetDirection.OUTPUT.value
    ]
    listed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        params={"include_total": "true"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == before_asset_count
    assert {asset["id"] for asset in listed.json()["items"]} == {source["id"]}

    with client.app.state.session_factory() as session:
        generated_assets = session.scalar(
            select(func.count())
            .select_from(AssetRecord)
            .where(AssetRecord.origin_kind == AssetOriginKind.GENERATED.value)
        )
        output_relations = session.scalar(
            select(func.count())
            .select_from(JobAssetRecord)
            .where(
                JobAssetRecord.job_id == job["id"],
                JobAssetRecord.direction == JobAssetDirection.OUTPUT.value,
            )
        )
        asset_bytes = session.scalar(
            select(func.coalesce(func.sum(AssetRecord.byte_size), 0))
        )
        current_limits = session.get(WorkspaceLimitRecord, WORKSPACE_ID)
        usage = session.scalars(
            select(UsageEventRecord)
            .where(UsageEventRecord.job_id == job["id"])
            .order_by(UsageEventRecord.occurred_at)
        ).all()

    assert generated_assets == 0
    assert output_relations == 0
    assert int(asset_bytes or 0) == before_asset_bytes
    assert current_limits is not None
    assert current_limits.storage_quota_bytes == before_quota
    assert len(usage) == 2
    assert all(event.provider == "mock" for event in usage)
    assert all(event.output_image_count == 0 for event in usage)
    assert all(event.estimated_cost_micros == 0 for event in usage)
    assert all(event.actual_cost_micros == 0 for event in usage)
    assert all(event.raw_usage["output_images"] == 0 for event in usage)
    assert all(event.raw_usage["raw"]["output_images"] == 0 for event in usage)
    assert all(event.raw_usage["raw"]["network_requests"] == 0 for event in usage)
    assert all(
        event.raw_usage["metrics"]["mock_artifact_discarded"] is True
        for event in usage
    )
    after_files = sorted(
        path.relative_to(storage_root)
        for path in storage_root.rglob("*")
        if path.is_file()
    )
    assert after_files == before_files


def test_non_mock_artifacts_remain_deliverable_without_resampling(
    client: TestClient,
) -> None:
    gateway = _OfflineNonMockGateway()
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=1,
    )
    source = upload_asset(client, filename="dimensions.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=1)
    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    output = next(asset for asset in completed["assets"] if asset["is_deliverable"])
    with client.app.state.session_factory() as session:
        asset = session.get(AssetRecord, output["asset_id"])
        usage = session.scalar(
            select(UsageEventRecord).where(UsageEventRecord.job_id == job["id"])
        )

    assert asset is not None
    assert (asset.width, asset.height) == (1024, 1536)
    assert output["direction"] == JobAssetDirection.OUTPUT.value
    assert output["validation"]["requested_size"] == IMAGE_SIZE
    assert output["validation"]["locally_resampled"] is False
    assert completed["items"][0]["result_source"] == "generated"
    assert usage is not None
    assert usage.provider == _OfflineNonMockGateway.provider_name
    assert (usage.width, usage.height) == (1024, 1536)


def test_duplicate_delivery_is_idempotent_across_plan_and_generation(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="duplicate.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)
    gateway = _gateway(client)

    assert dispatch_pending(client) == 1
    assert (
        client.app.state.task_runner.coordinator.run
        is not None
    )
    assert asyncio.run(
        client.app.state.task_runner.run(job["id"])
    ) == JobStatus.AWAITING_CONFIRMATION
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []

    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    assert asyncio.run(
        client.app.state.task_runner.run(job["id"])
    ) == JobStatus.COMPLETED
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == 2
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobAttemptRecord)
                .where(JobAttemptRecord.job_id == job["id"])
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(UsageEventRecord)
                .where(UsageEventRecord.job_id == job["id"])
            )
            == 2
        )


def test_concurrent_planning_delivery_uses_one_reserved_call(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="planning-race.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)
    gateway = _gateway(client)
    gateway.delay_seconds = 0.05

    async def deliver_twice() -> list[JobStatus | None]:
        return list(
            await asyncio.gather(
                client.app.state.task_runner.run(job["id"]),
                client.app.state.task_runner.run(job["id"]),
            )
        )

    results = asyncio.run(deliver_twice())
    current = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert JobStatus.AWAITING_CONFIRMATION in results
    assert len(gateway.planner_calls) == 1
    assert current["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert gateway.image_calls == []


def test_cancel_while_awaiting_confirmation_keeps_image_calls_zero(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="cancel.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)
    gateway = _gateway(client)
    assert dispatch_pending(client) == 1

    cancelled = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/cancel",
        headers=idem(),
        json={"reason": "user cancelled"},
    )

    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == JobStatus.CANCELLED.value
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []


def test_durable_plan_survives_runner_recreation(
    client: TestClient,
) -> None:
    from app.task_runner import MockTaskRunner

    source = upload_asset(client, filename="restart.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=2)
    gateway = _gateway(client)
    assert dispatch_pending(client) == 1
    assert len(gateway.planner_calls) == 1

    replacement_gateway = FakeXingheGateway()
    replacement = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=replacement_gateway,
        xinghe_concurrency=2,
    )
    client.app.state.task_runner = replacement
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert completed["status"] == JobStatus.COMPLETED.value
    assert replacement_gateway.planner_calls == []
    assert len(replacement_gateway.image_calls) == 2


def test_resume_signature_invalidates_every_output_affecting_change() -> None:
    base = {
        "groups": [("shoe", [("front.jpg", "a" * 64), ("side.jpg", "b" * 64)])],
        "base_url": "https://api.example.test",
        "planner_model": "planner",
        "image_model": "image",
        "page_count": 8,
        "language": "en",
        "product_name": "shoe",
        "product_information": ["visible"],
        "platform_code": "amazon",
        "size": IMAGE_SIZE,
        "medium_price_micros": 45_000,
        "high_price_micros": 90_000,
    }
    original = build_resume_signature(**base)
    mutations = [
        {"groups": [("shoe", [("side.jpg", "b" * 64), ("front.jpg", "a" * 64)])]},
        {"base_url": "https://other.example.test"},
        {"planner_model": "planner-v2"},
        {"image_model": "image-v2"},
        {"page_count": 12},
        {"language": "fr"},
        {"product_name": "other"},
        {"product_information": ["changed"]},
        {"platform_code": "shopify"},
        {"size": "1000x1000"},
        {"medium_price_micros": 46_000},
        {"high_price_micros": 91_000},
    ]
    for mutation in mutations:
        changed = {**base, **mutation}
        assert build_resume_signature(**changed) != original


def test_semantic_quality_routing_is_version_stable() -> None:
    high_roles = [
        "封面叙事",
        "材质纹理微距",
        "Structural close-up",
        "Surface craft detail",
    ]
    assert all(quality_for_role(role) == "high" for role in high_roles)
    assert quality_for_role("Daily use scenario") == "high"


def _jpeg(size: tuple[int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(1, 2, 3)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_image_artifact_uses_requested_canvas_size_contract() -> None:
    artifact = _artifact_from_bytes(
        _jpeg((1024, 1536)),
        filename="requested-size.jpg",
        expected_size=IMAGE_SIZE,
    )

    assert (artifact.width, artifact.height) == (1024, 1536)
    assert artifact.locally_resampled is False
    assert (artifact.provider_width, artifact.provider_height) == (1024, 1536)

    resampled = _artifact_from_bytes(
        _jpeg((512, 768)),
        filename="provider-size.jpg",
        expected_size=IMAGE_SIZE,
    )
    assert (resampled.width, resampled.height) == (1024, 1536)
    assert resampled.locally_resampled is True
    assert (resampled.provider_width, resampled.provider_height) == (512, 768)
    with Image.open(BytesIO(resampled.payload)) as image:
        assert image.size == (1024, 1536)

    with pytest.raises(XingheAgentError) as exc_info:
        _artifact_from_bytes(
            _jpeg((512, 512)),
            filename="wrong-ratio.jpg",
            expected_size=IMAGE_SIZE,
        )
    assert exc_info.value.code == "IMAGE_RESPONSE_SIZE_INVALID"


class _RecordingTransport:
    def __init__(self) -> None:
        self.json_calls: list[dict[str, Any]] = []
        self.multipart_calls: list[dict[str, Any]] = []

    async def post_json(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.json_calls.append(kwargs)
        return (
            200,
            {
                "id": "planner_request",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(_valid_planner_content(2))
                        }
                    }
                ],
            },
        )

    async def post_multipart(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.multipart_calls.append(kwargs)
        buffer = BytesIO()
        width, height = (
            int(value)
            for value in dict(kwargs["fields"])["size"].split("x")
        )
        Image.new("RGB", (width, height), color=(1, 2, 3)).save(
            buffer,
            format="JPEG",
            quality=92,
        )
        return (
            200,
            {
                "id": "image_request",
                "data": [
                    {"b64_json": base64.b64encode(buffer.getvalue()).decode()}
                ],
            },
        )


def test_tengli_adapter_is_openai_compatible_and_usage_safe() -> None:
    requested_size = "1000x1000"
    transport = _RecordingTransport()
    adapter = TengliOpenAICompatibleGateway(
        api_key="test-placeholder-key",
        base_url="https://api.example.test",
        planner_model="gpt-5.6-terra",
        image_model="gpt-image-2",
        transport=transport,
    )
    source_bytes = BytesIO()
    Image.new("RGB", (1024, 1536), color=(4, 5, 6)).save(
        source_bytes,
        format="JPEG",
    )
    sources = tuple(
        SourceImage(
            asset_id=f"asset_{index}",
            group_key="shoe",
            filename=f"shoe-{index}.jpg",
            content_type="image/jpeg",
            sha256="a" * 64,
            payload=source_bytes.getvalue(),
        )
        for index in range(3)
    )
    planner = asyncio.run(
        adapter.plan(
            PlannerRequest(
                workspace_id="ws_test",
                job_id="job_test",
                group_key="shoe",
                sources=sources,
                page_count=2,
                language="en",
                product_name="shoe",
                product_information=(
                    "visible",
                    "Do not describe this product as waterproof",
                ),
                platform_code="amazon",
                size=requested_size,
                idempotency_key="planner-idem",
                system_prompt="pinned same-source protocol",
            )
        )
    )
    image = asyncio.run(
        adapter.edit(
            ImageEditRequest(
                workspace_id="ws_test",
                job_id="job_test",
                job_item_id="item_test",
                attempt_id="attempt_test",
                page_number=1,
                group_key="shoe",
                sources=sources,
                prompt="square e-commerce product image",
                quality="high",
                idempotency_key="image-idem",
                size=requested_size,
            )
        )
    )

    assert planner.normalized_usage == normalize_usage(None)
    assert image.normalized_usage == normalize_usage(None)
    assert image.estimated_cost_micros == 90_000
    assert image.actual_cost_micros is None
    assert image.artifact is not None
    assert (image.artifact.width, image.artifact.height) == (1000, 1000)
    assert transport.json_calls[0]["url"].endswith("/v1/chat/completions")
    messages = transport.json_calls[0]["payload"]["messages"]
    assert messages[0] == {
        "role": "system",
        "content": "pinned same-source protocol",
    }
    planner_text = messages[1]["content"][0]["text"]
    assert (
        "/analysis/product_consistency_anchors is REQUIRED" in planner_text
    )
    assert "inside the top-level analysis object" in planner_text
    assert "always emit it as a JSON object; never omit it" in planner_text
    assert (
        "Every screen requires role, title, label, composition" in planner_text
    )
    assert "four distinct structures" in planner_text
    assert "three subject scales" in planner_text
    assert "two substantively different devices" in planner_text
    assert "final role MUST be exactly closing_summary" in planner_text
    for prohibited_claim in (
        "leather",
        "comfort",
        "durability",
        "wear resistance",
    ):
        assert prohibited_claim in planner_text
    assert "explicit, non-negotiable hard constraint" in planner_text
    assert "every safety-relevant field of every plan screen" in planner_text
    assert "must never be violated" in planner_text
    assert "including FALILIAN when visible" in planner_text
    assert "not product branding or selling points" in planner_text
    assert (
        "points=['visible', 'Do not describe this product as waterproof']"
        in planner_text
    )
    assert transport.multipart_calls[0]["url"].endswith("/v1/images/edits")
    fields = dict(transport.multipart_calls[0]["fields"])
    assert fields["size"] == requested_size
    assert fields["output_format"] == IMAGE_FORMAT
    assert fields["output_compression"] == str(JPEG_QUALITY)
    assert len(transport.multipart_calls[0]["files"]) == 3
    assert all(
        record[0] == "image"
        for record in transport.multipart_calls[0]["files"]
    )
    assert "test-placeholder-key" not in repr(adapter)


def test_sensitive_agent_audits_store_no_prompt_source_or_key(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="sensitive.jpg")
    job = _create_detail_job(client, [source["id"]], page_count=1)
    assert dispatch_pending(client) == 1
    assert (
        client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
            headers=idem(),
            json={"expected_revision": 1},
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    with client.app.state.session_factory() as session:
        audits = session.scalars(
            select(AuditEventRecord).where(
                AuditEventRecord.resource_id.in_(
                    select(JobItemRecord.id).where(
                        JobItemRecord.job_id == job["id"]
                    )
                )
                | (AuditEventRecord.resource_id == job["id"])
            )
        ).all()
        attempts = session.scalar(
            select(func.count())
            .select_from(JobAttemptRecord)
            .where(JobAttemptRecord.job_id == job["id"])
        )
        plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )

    serialized = str([audit.details for audit in audits]).lower()
    assert "prompt" not in serialized
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert "object_key" not in serialized
    assert attempts == 1
    assert plan is not None
