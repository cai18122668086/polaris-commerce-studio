from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.amazon_visual_suite_provider import (
    AMAZON_EXPECTED_ITEM_COUNT,
    AMAZON_ITEM_KEYS,
    AMAZON_ITEM_SPECS,
    AMAZON_PLAN_CONFIGURATION_KEY,
    AmazonVisualSuiteProvider,
    validate_amazon_planner_payload,
)
from app.domain import JobStatus, PlanValidationStatus
from app.models import JobItemRecord, JobPlanRecord
from app.provider import ProviderOutcome, ProviderRequest, ProviderResult
from app.task_runner import MockTaskRunner
from app.xinghe_agent import (
    FakeXingheGateway,
    ImageCallResult,
    ImageEditRequest,
    PlannerCallResult,
    PlannerRequest,
    XingheAgentError,
    _fake_plan,
    validate_planner_payload,
)
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset


@dataclass
class _RecordingDelegate:
    name: str = "recording"
    model: str = "recording-image"
    pricing_version: str = "recording-v1"
    requests: list[ProviderRequest] = field(default_factory=list)

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult(outcome=ProviderOutcome.SUCCEEDED)


class _ManifestValidator:
    def validate(self, skill_id: str) -> str:
        assert skill_id == "xinghe-amazon-visual-suite"
        return "a" * 64


class _CountingGateway(FakeXingheGateway):
    provider_name = "offline-contract-provider"
    planner_model = "offline-contract-planner"
    image_model = "offline-contract-image"
    pricing_version = "offline-contract-v1"

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        result = await super().plan(request)
        return replace(
            result,
            provider_request_id=f"offline_plan_{len(self.planner_calls)}",
            request_id_presence="present",
        )

    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        result = await super().edit(request)
        return replace(
            result,
            provider_request_id=(
                f"offline_image_{request.job_id}_{request.job_item_id}_"
                f"{request.attempt_id}"
            ),
        )


class _DuplicateOutputGateway(_CountingGateway):
    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        return await super().edit(replace(request, page_number=1))


class _OneFailureGateway(_CountingGateway):
    def __init__(self) -> None:
        super().__init__(image_failures={1: 1})


def _install_counting_runner(
    client: TestClient,
    *,
    gateway_type: type[_CountingGateway] = _CountingGateway,
) -> _CountingGateway:
    gateway = gateway_type()
    client.app.state.storage.validator.max_image_pixels = 5_000_000
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=2,
        amazon_visual_suite_provider_enabled=True,
    )
    return gateway


def _planner_request(
    *,
    page_count: int = AMAZON_EXPECTED_ITEM_COUNT,
    planning_profile: str = "amazon_visual_suite",
) -> PlannerRequest:
    return PlannerRequest(
        workspace_id=WORKSPACE_ID,
        job_id="job_contract",
        group_key="amazon-product",
        sources=(),
        page_count=page_count,
        language="en-US",
        product_name="Visible product",
        product_information=("Visible facts only",),
        platform_code="amazon-us",
        size="amazon-canonical-multi-size-v1",
        idempotency_key="job_contract:planner",
        planning_profile=planning_profile,
    )


def _valid_amazon_payload() -> dict[str, Any]:
    return _fake_plan(_planner_request())


def _provider_request_without_plan_context() -> ProviderRequest:
    spec = AMAZON_ITEM_SPECS[0]
    return ProviderRequest(
        workspace_id=WORKSPACE_ID,
        job_id="job_contract",
        job_item_id="item_contract",
        attempt_id="attempt_contract",
        operation="amazon_visual_suite",
        idempotency_key="attempt_contract",
        configuration={
            "job": {
                "input": {
                    "white_background_product_asset_ids": ["asset-white"],
                },
                "settings": {
                    "marketplace": "amazon-us",
                    "language": "en-US",
                },
            },
            "item": {
                "item_key": spec.item_key,
                "group": spec.group,
                "target_width": spec.width,
                "target_height": spec.height,
            },
        },
    )


def test_amazon_validator_requires_product_master() -> None:
    payload = _valid_amazon_payload()
    payload["analysis"].pop("product_master_description")

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code in {
        "PLANNER_SCHEMA_INVALID",
        "AMAZON_PRODUCT_MASTER_INVALID",
    }
    assert raised.value.json_pointer == "/analysis/product_master_description"


def test_amazon_validator_rejects_incomplete_product_master() -> None:
    payload = _valid_amazon_payload()
    payload["analysis"]["product_master_description"].pop("structural_parts")

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code == "AMAZON_PRODUCT_MASTER_INVALID"
    assert raised.value.json_pointer is not None
    assert raised.value.json_pointer.endswith("/structural_parts")


def test_amazon_validator_rejects_blank_product_master_value() -> None:
    payload = _valid_amazon_payload()
    payload["analysis"]["product_master_description"][
        "silhouette_and_proportions"
    ] = "   "

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code in {
        "PLANNER_SCHEMA_INVALID",
        "AMAZON_PRODUCT_MASTER_INVALID",
    }
    assert raised.value.json_pointer is not None
    assert raised.value.json_pointer.endswith("/silhouette_and_proportions")


def test_amazon_validator_rejects_empty_product_consistency_lock() -> None:
    payload = _valid_amazon_payload()
    payload["plan"]["product_consistency_lock"] = {}

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code in {
        "PLANNER_SCHEMA_INVALID",
        "AMAZON_PRODUCT_CONSISTENCY_LOCK_INVALID",
    }
    assert raised.value.json_pointer == "/plan/product_consistency_lock"


def test_amazon_validator_rejects_wrong_item_key() -> None:
    payload = _valid_amazon_payload()
    payload["plan"]["screens"][4]["item_key"] = "SECONDARY-99"

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code == "AMAZON_ITEM_INVENTORY_INVALID"
    assert raised.value.json_pointer == "/plan/screens"


@pytest.mark.parametrize("field", ["layout_family", "background_system"])
def test_amazon_validator_rejects_excessive_composition_reuse(field: str) -> None:
    payload = _valid_amazon_payload()
    for screen in payload["plan"]["screens"]:
        screen[field] = "same-composition-system"

    with pytest.raises(XingheAgentError) as raised:
        validate_amazon_planner_payload(payload)

    assert raised.value.code in {
        "PLANNER_CROSS_PAGE_DIVERSITY_INVALID",
        "AMAZON_LAYOUT_DIVERSITY_INVALID",
    }
    assert raised.value.json_pointer == "/plan/screens"


@pytest.mark.parametrize("field", ["layout_family", "background_system"])
def test_crossborder_validator_rejects_excessive_composition_reuse(
    field: str,
) -> None:
    request = _planner_request(
        page_count=8,
        planning_profile="crossborder_detail",
    )
    payload = _fake_plan(request)
    for screen in payload["plan"]["screens"]:
        screen[field] = "same-composition-system"

    with pytest.raises(XingheAgentError) as raised:
        validate_planner_payload(
            payload,
            request.page_count,
            require_cross_page_locks=True,
        )

    assert raised.value.code == "PLANNER_CROSS_PAGE_DIVERSITY_INVALID"
    assert raised.value.json_pointer == "/plan/screens"


def test_amazon_provider_rejects_missing_persisted_plan_context() -> None:
    delegate = _RecordingDelegate()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=_ManifestValidator(),
    )

    result = asyncio.run(provider.execute(_provider_request_without_plan_context()))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_PLAN_CONTEXT_MISSING"
    assert result.artifact is None
    assert delegate.requests == []


def _create_amazon_job(client: TestClient, asset_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "amazon_visual_suite",
            "intent": "submit",
            "display_name": "Amazon fail-closed planning gate",
            "input": {
                "white_background_product_asset_ids": [asset_id],
            },
            "configuration": {
                "marketplace": "amazon-us",
                "product_name": "Visible product",
                "listing_title": "Visible product listing",
                "bullet_points": ["Visible facts only"],
                "language": "en-US",
            },
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _reachable_gateways(root: object) -> list[Any]:
    gateways: dict[int, Any] = {}
    seen: set[int] = set()
    pending = [root]
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        gateway = getattr(value, "gateway", None)
        if gateway is not None and hasattr(gateway, "image_calls"):
            gateways[id(gateway)] = gateway
        for attribute in ("international", "domestic", "amazon"):
            child = getattr(value, attribute, None)
            if child is not None:
                pending.append(child)
    return list(gateways.values())


def test_amazon_job_persists_product_master_and_plan_before_confirmation(
    client: TestClient,
) -> None:
    source = upload_asset(client, filename="amazon-white-background.png")
    job = _create_amazon_job(client, source["id"])

    published = dispatch_pending(client)
    assert published == 1
    planned = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert planned["status"] == JobStatus.AWAITING_CONFIRMATION.value
    assert planned["stage"] == "awaiting_confirmation"
    assert planned["plan"]["validation_status"] == PlanValidationStatus.VALID.value
    assert planned["plan"]["confirmed_at"] is None
    payload = planned["plan"]["payload"]
    assert payload["state"] == "awaiting_confirmation"
    assert len(payload["pages"]) == AMAZON_EXPECTED_ITEM_COUNT
    assert tuple(page["item_key"] for page in payload["pages"]) == AMAZON_ITEM_KEYS
    product_master = payload["groups"][0]["analysis"][
        "product_master_description"
    ]
    assert set(product_master) >= {
        "silhouette_and_proportions",
        "color_and_material_appearance",
        "logos_labels_and_patterns",
        "structural_parts",
        "scale_and_physics",
        "unknowns",
    }
    assert payload["usage"]["image"] == {
        "reported_requests": 0,
        "unreported_requests": 0,
    }

    with client.app.state.session_factory() as session:
        durable_plan = session.scalar(
            select(JobPlanRecord).where(JobPlanRecord.job_id == job["id"])
        )
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job["id"])
            .order_by(JobItemRecord.ordinal)
        ).all()

    assert durable_plan is not None
    assert durable_plan.confirmed_at is None
    assert durable_plan.validation_status == PlanValidationStatus.VALID.value
    assert len(items) == AMAZON_EXPECTED_ITEM_COUNT
    assert tuple(item.item_key for item in items) == AMAZON_ITEM_KEYS
    assert all(item.stage == "awaiting_confirmation" for item in items)
    for item in items:
        context = item.configuration[AMAZON_PLAN_CONFIGURATION_KEY]
        assert set(context) >= {
            "analysis",
            "campaign_style_lock",
            "design_strength_lock",
            "product_consistency_lock",
            "layout_diversity_lock",
            "screen",
            "resume_signature",
        }
        assert context["analysis"]["product_master_description"] == product_master
        assert context["screen"]["item_key"] == item.item_key
        assert context["resume_signature"] == payload["resume_signature"]

    gateways = _reachable_gateways(
        client.app.state.task_runner.coordinator.detail_planner
    )
    assert gateways
    assert all(gateway.image_calls == [] for gateway in gateways)
    assert sum(len(gateway.planner_calls) for gateway in gateways) == 1

    assert dispatch_pending(client) == 0
    assert sum(len(gateway.planner_calls) for gateway in gateways) == 1


def test_amazon_cancel_while_awaiting_confirmation_keeps_image_calls_zero(
    client: TestClient,
) -> None:
    gateway = _install_counting_runner(client)
    source = upload_asset(client, filename="amazon-cancel-white.png")
    job = _create_amazon_job(client, source["id"])
    assert dispatch_pending(client) == 1

    cancelled = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/cancel",
        headers=idem(),
        json={"reason": "user cancelled before Amazon generation"},
    )

    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["status"] == JobStatus.CANCELLED.value
    assert len(gateway.planner_calls) == 1
    assert gateway.image_calls == []


def test_confirmed_amazon_plan_drives_all_prompts_and_retry_reuses_plan(
    client: TestClient,
) -> None:
    gateway = _install_counting_runner(client)
    source = upload_asset(client, filename="amazon-confirm-white.png")
    job = _create_amazon_job(client, source["id"])
    assert dispatch_pending(client) == 1
    assert len(gateway.planner_calls) == 1

    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 202, confirmed.text
    published = dispatch_pending(client)
    assert published == 1, {
        "job": client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json(),
        "planner_calls": len(gateway.planner_calls),
        "image_calls": len(gateway.image_calls),
    }
    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()

    assert completed["status"] == JobStatus.COMPLETED.value, [
        (item["item_key"], item["status"], item.get("error_code"))
        for item in completed["items"]
    ]
    assert completed["api_request_count"] == 22
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == AMAZON_EXPECTED_ITEM_COUNT
    assert {call.group_key for call in gateway.image_calls} == set(AMAZON_ITEM_KEYS)
    for call in gateway.image_calls:
        assert "Product Master Description:" in call.prompt
        assert "Product Consistency Lock:" in call.prompt
        assert "Campaign Style Lock:" in call.prompt
        assert "Layout Diversity Lock:" in call.prompt
    business_quality = completed["plan"]["payload"]["business_quality"]
    assert business_quality["status"] == "needs_review"
    assert business_quality["technical_delivery_status"] == "completed"
    assert business_quality["manual_review_required"] is True
    assert business_quality["automatic_redraw_enabled"] is False

    calls_before_redelivery = (
        len(gateway.planner_calls),
        len(gateway.image_calls),
    )
    asyncio.run(client.app.state.task_runner.run(job["id"]))
    redelivered = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert (
        len(gateway.planner_calls),
        len(gateway.image_calls),
    ) == calls_before_redelivery
    assert redelivered["plan"]["payload"]["business_quality"] == business_quality



def test_amazon_retry_reuses_confirmed_plan_without_second_planner_call(
    client: TestClient,
) -> None:
    failed_gateway = _install_counting_runner(
        client,
        gateway_type=_OneFailureGateway,
    )
    source = upload_asset(client, filename="amazon-retry-white.png")
    job = _create_amazon_job(client, source["id"])
    assert dispatch_pending(client) == 1
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 202, confirmed.text
    assert dispatch_pending(client) == 1
    partial = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert partial["status"] == JobStatus.PARTIAL.value
    assert len(failed_gateway.planner_calls) == 1
    assert len(failed_gateway.image_calls) == AMAZON_EXPECTED_ITEM_COUNT

    retried = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/retry",
        headers=idem(),
        json={"scope": "full", "item_ids": []},
    )
    assert retried.status_code == 201, retried.text
    retry_job = retried.json()

    retry_gateway = _install_counting_runner(client)
    assert dispatch_pending(client) == 1
    retried_completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{retry_job['id']}"
    ).json()

    assert retried_completed["status"] == JobStatus.COMPLETED.value
    assert retry_gateway.planner_calls == []
    assert len(retry_gateway.image_calls) == AMAZON_EXPECTED_ITEM_COUNT
    retry_payload = retried_completed["plan"]["payload"]
    assert retry_payload["usage"]["planner"] == []
    assert retry_payload["usage"]["planner_reused_from_job_id"] == job["id"]
    assert retry_payload["business_quality"]["status"] == "needs_review"
    assert not any(
        finding["code"] == "AMAZON_EXACT_DUPLICATE_OUTPUT"
        for finding in retry_payload["business_quality"]["deterministic_findings"]
    )


def test_amazon_exact_duplicate_outputs_fail_business_quality_only(
    client: TestClient,
) -> None:
    gateway = _install_counting_runner(
        client,
        gateway_type=_DuplicateOutputGateway,
    )
    source = upload_asset(client, filename="amazon-duplicate-white.png")
    job = _create_amazon_job(client, source["id"])
    assert dispatch_pending(client) == 1
    confirmed = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}/plan/confirm",
        headers=idem(),
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 202, confirmed.text
    published = dispatch_pending(client)
    assert published == 1, {
        "job": client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
        ).json(),
        "planner_calls": len(gateway.planner_calls),
        "image_calls": len(gateway.image_calls),
    }

    completed = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    quality = completed["plan"]["payload"]["business_quality"]
    assert completed["status"] == JobStatus.COMPLETED.value
    assert completed["stage"] == "completed_quality_failed"
    assert quality["status"] == "failed"
    assert quality["technical_delivery_status"] == "completed"
    assert any(
        finding["code"] == "AMAZON_EXACT_DUPLICATE_OUTPUT"
        for finding in quality["deterministic_findings"]
    )
    assert len(gateway.planner_calls) == 1
    assert len(gateway.image_calls) == AMAZON_EXPECTED_ITEM_COUNT


def test_valid_amazon_payload_is_not_mutated_by_validation() -> None:
    payload = _valid_amazon_payload()
    original = deepcopy(payload)

    validated = validate_amazon_planner_payload(payload)

    assert payload == original
    assert tuple(
        screen["item_key"] for screen in validated["plan"]["screens"]
    ) == AMAZON_ITEM_KEYS
