from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import Iterator
from copy import deepcopy
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
from app.domain import JobStatus
from app.main import create_app
from app.models import (
    AssetRecord,
    AuditEventRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    UsageEventRecord,
)
from app.xinghe_agent import (
    IMAGE_FORMAT,
    IMAGE_SIZE,
    JPEG_QUALITY,
    FakeXingheGateway,
    ImageEditRequest,
    PlannerRequest,
    SourceImage,
    TengliOpenAICompatibleGateway,
    build_resume_signature,
    normalize_usage,
    quality_for_role,
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
    return response.json()


def _gateway(client: TestClient) -> FakeXingheGateway:
    planner = client.app.state.task_runner.coordinator.detail_planner
    assert planner is not None
    gateway = planner.gateway
    assert isinstance(gateway, FakeXingheGateway)
    return gateway


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


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("transport", "PLANNER_REQUEST_FAILED"),
        ("invalid_json", "PLANNER_SCHEMA_INVALID"),
        ("schema", "PLANNER_SCHEMA_INVALID"),
        ("wrong_page_count", "PLANNER_PAGE_COUNT_MISMATCH"),
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
        assert call.prompt.startswith("vertical 3:4 e-commerce detail page image")
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
        assert items[2].quality == "medium"

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
    assert metrics["job_wall_time"] is not None
    assert metrics["usage_missing_count"] == 3


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


def test_generated_assets_record_real_dimensions_without_resampling(
    client: TestClient,
) -> None:
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
        assert asset is not None
        usage = session.scalar(
            select(UsageEventRecord).where(UsageEventRecord.job_id == job["id"])
        )

    assert (asset.width, asset.height) == (24, 32)
    assert output["validation"]["requested_size"] == IMAGE_SIZE
    assert output["validation"]["locally_resampled"] is False
    assert usage is not None
    assert (usage.width, usage.height) == (24, 32)


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
    assert quality_for_role("Daily use scenario") == "medium"


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
                            "content": (
                                '{"analysis":{"category_key":"fashion",'
                                '"category_reason":"visible",'
                                '"product_image_analysis":{"visible_facts":[]},'
                                '"product_consistency_anchors":{},'
                                '"buyer_objections":["appearance"]},'
                                '"plan":{"campaign_style_lock":"lock",'
                                '"design_strength_lock":"lock",'
                                '"screens":[{"role":"Cover","title":"Title",'
                                '"label":"Label","composition":"Hero",'
                                '"device":"Line","difference":"Scale"}]}}'
                            )
                        }
                    }
                ],
            },
        )

    async def post_multipart(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        self.multipart_calls.append(kwargs)
        buffer = BytesIO()
        Image.new("RGB", (24, 32), color=(1, 2, 3)).save(
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
    transport = _RecordingTransport()
    adapter = TengliOpenAICompatibleGateway(
        api_key="test-placeholder-key",
        base_url="https://api.example.test",
        planner_model="gpt-5.6-terra",
        image_model="gpt-image-2",
        transport=transport,
    )
    source_bytes = BytesIO()
    Image.new("RGB", (24, 32), color=(4, 5, 6)).save(
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
                page_count=1,
                language="en",
                product_name="shoe",
                product_information=("visible",),
                platform_code="amazon",
                idempotency_key="planner-idem",
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
                prompt="vertical 3:4 e-commerce detail page image",
                quality="high",
                idempotency_key="image-idem",
            )
        )
    )

    assert planner.normalized_usage == normalize_usage(None)
    assert image.normalized_usage == normalize_usage(None)
    assert image.estimated_cost_micros == 90_000
    assert image.actual_cost_micros is None
    assert image.artifact is not None
    assert (image.artifact.width, image.artifact.height) == (24, 32)
    assert transport.json_calls[0]["url"].endswith("/v1/chat/completions")
    assert transport.multipart_calls[0]["url"].endswith("/v1/images/edits")
    fields = dict(transport.multipart_calls[0]["fields"])
    assert fields["size"] == IMAGE_SIZE
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
