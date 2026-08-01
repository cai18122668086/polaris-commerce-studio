from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.amazon_visual_suite_provider import AmazonVisualSuiteProvider
from app.config import default_skill_root, default_xinghe_skill_root
from app.creative_image_provider import CreativeImageProvider
from app.crossborder_detail_provider import CrossborderDetailProvider
from app.domain import JobStatus, JobType
from app.domestic_detail_provider import (
    DOMESTIC_DETAIL_SKILL_ID,
    DomesticDetailProvider,
)
from app.product_image_provider import ProductImageProvider
from app.provider import (
    FakeProvider,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from app.provider_registry import (
    DetailMarketRoutingPlanner,
    RegisteredOperationRoutingProvider,
    UnavailableProvider,
)
from app.reference_remix_provider import ReferenceRemixProvider
from app.skill_runtime import SkillRuntimeProvider
from app.xinghe_agent import XingheImageProvider, XinghePlanningCoordinator
from tests.test_api import WORKSPACE_ID, idem, upload_asset


@dataclass
class RecordingProvider:
    name: str
    model: str = "routing-test"
    pricing_version: str = "routing-test-v1"
    requests: list[ProviderRequest] = field(default_factory=list)

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_request_id=f"{self.name}-request",
            usage_reported=True,
            raw_usage={"provider_type": self.name, "network_requests": 0},
        )


class TrackingUnavailableProvider(UnavailableProvider):
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return await super().execute(request)


@dataclass
class RecordingPlanner:
    status: JobStatus = JobStatus.AWAITING_CONFIRMATION
    calls: list[str] = field(default_factory=list)

    async def plan(self, job_id: str) -> JobStatus | None:
        self.calls.append(job_id)
        return self.status


def _request(operation: str, configuration: dict[str, Any]) -> ProviderRequest:
    return ProviderRequest(
        workspace_id=WORKSPACE_ID,
        job_id="job-routing",
        job_item_id="item-routing",
        attempt_id="attempt-routing",
        operation=operation,
        idempotency_key="routing-idempotency",
        configuration=configuration,
    )


def _create_detail_job(
    client: TestClient,
    asset_id: str,
    market_region: str,
) -> str:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers=idem(),
        json={
            "type": "detail_pack",
            "intent": "submit",
            "input": {
                "product_groups": [
                    {"group_key": market_region, "asset_ids": [asset_id]}
                ]
            },
            "configuration": {
                "product_name": f"{market_region} routing",
                "platform_code": "tmall" if market_region == "domestic" else "amazon",
                "market_region": market_region,
                "language": "zh-CN" if market_region == "domestic" else "en",
                "page_count": 1,
            },
        },
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def test_mock_new_image_routes_keep_the_structural_fake_provider(
    client: TestClient,
) -> None:
    router = cast(
        RegisteredOperationRoutingProvider,
        client.app.state.task_runner.coordinator.provider,
    )
    default = router.default_provider

    assert isinstance(default, SkillRuntimeProvider)
    assert isinstance(default.provider, FakeProvider)
    assert default.provider.external_network_request_count == 0
    for operation in (
        JobType.PRODUCT_IMAGE.value,
        JobType.REFERENCE_REMIX.value,
        JobType.CREATIVE_IMAGE.value,
    ):
        assert router.routes[operation] is default
    amazon = router.routes[JobType.AMAZON_VISUAL_SUITE.value]
    assert isinstance(amazon, AmazonVisualSuiteProvider)
    assert amazon.delegate is default


@pytest.mark.parametrize(
    ("operation", "adapter_type", "configuration"),
    [
        (
            JobType.PRODUCT_IMAGE.value,
            ProductImageProvider,
            {
                "job": {
                    "input": {"product_asset_ids": ["asset-product"]},
                    "settings": {"task_type": "scene_main", "image_count": 1},
                },
                "item": {"item_key": "image-001"},
            },
        ),
        (
            JobType.REFERENCE_REMIX.value,
            ReferenceRemixProvider,
            {
                "job": {
                    "input": {
                        "product_asset_ids": ["asset-product"],
                        "reference_asset_ids": ["asset-style"],
                    },
                    "settings": {"image_count": 1},
                },
                "item": {"item_key": "image-001"},
            },
        ),
        (
            JobType.CREATIVE_IMAGE.value,
            CreativeImageProvider,
            {
                "job": {
                    "input": {"product_asset_ids": ["asset-product"]},
                    "settings": {"image_count": 1},
                },
                "item": {"item_key": "image-001"},
            },
        ),
    ],
)
def test_real_unregistered_new_image_routes_fail_closed_without_fake_fallback(
    operation: str,
    adapter_type: type[
        ProductImageProvider | ReferenceRemixProvider | CreativeImageProvider
    ],
    configuration: dict[str, Any],
) -> None:
    fallback = FakeProvider()
    unavailable = TrackingUnavailableProvider()
    route = adapter_type(unavailable, manifest_validator=lambda _skill_id: True)
    detail = RecordingProvider("stable-detail")
    local = RecordingProvider("stable-local")
    domestic = RecordingProvider("domestic-detail")
    router = RegisteredOperationRoutingProvider(
        fallback,
        detail,
        local,
        {operation: route},
        domestic_detail_provider=domestic,
    )

    result = asyncio.run(router.execute(_request(operation, configuration)))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "PROVIDER_NOT_CONFIGURED"
    assert result.raw_usage["called"] is False
    assert result.raw_usage["network_requests"] == 0
    assert fallback.call_count == 0
    assert len(unavailable.requests) == 1
    assert detail.requests == []
    assert local.requests == []
    assert domestic.requests == []


def test_detail_provider_routes_domestic_only_and_preserves_international_chain(
) -> None:
    fallback = RecordingProvider("default")
    international = RecordingProvider("stable-international")
    local = RecordingProvider("stable-local")
    domestic = RecordingProvider("domestic")
    router = RegisteredOperationRoutingProvider(
        fallback,
        international,
        local,
        {},
        domestic_detail_provider=domestic,
    )

    domestic_result = asyncio.run(
        router.execute(
            _request(
                JobType.DETAIL_PACK.value,
                {"job": {"settings": {"market_region": "domestic"}}},
            )
        )
    )
    international_result = asyncio.run(
        router.execute(
            _request(
                JobType.DETAIL_PACK.value,
                {"job": {"settings": {"market_region": "international"}}},
            )
        )
    )

    assert domestic_result.provider_request_id == "domestic-request"
    assert international_result.provider_request_id == "stable-international-request"
    assert len(domestic.requests) == 1
    assert len(international.requests) == 1
    assert fallback.requests == []
    assert local.requests == []
    assert router.detail_provider is international
    assert not isinstance(router.detail_provider, CrossborderDetailProvider)


def test_detail_planner_routes_by_durable_market_region(client: TestClient) -> None:
    source = upload_asset(client, filename="planner-routing.png")
    domestic_job_id = _create_detail_job(client, source["id"], "domestic")
    international_job_id = _create_detail_job(client, source["id"], "international")
    domestic = RecordingPlanner()
    international = RecordingPlanner()
    router = DetailMarketRoutingPlanner(
        client.app.state.session_factory,
        international,
        domestic,
    )

    assert asyncio.run(router.plan(domestic_job_id)) == JobStatus.AWAITING_CONFIRMATION
    assert (
        asyncio.run(router.plan(international_job_id))
        == JobStatus.AWAITING_CONFIRMATION
    )

    assert domestic.calls == [domestic_job_id]
    assert international.calls == [international_job_id]


def test_built_routing_keeps_international_legacy_and_domestic_skill_identity(
    client: TestClient,
) -> None:
    coordinator = client.app.state.task_runner.coordinator
    planner_router = cast(DetailMarketRoutingPlanner, coordinator.detail_planner)
    provider_router = cast(RegisteredOperationRoutingProvider, coordinator.provider)
    international_planner = cast(
        XinghePlanningCoordinator, planner_router.international
    )
    domestic_planner = cast(XinghePlanningCoordinator, planner_router.domestic)
    domestic_adapter = provider_router.domestic_detail_provider

    assert international_planner.skill_id == "xinghe-ecommerce-detail"
    assert international_planner.skill_root == default_xinghe_skill_root()
    assert domestic_planner.skill_id == DOMESTIC_DETAIL_SKILL_ID
    assert domestic_planner.skill_root == default_skill_root(DOMESTIC_DETAIL_SKILL_ID)

    assert isinstance(provider_router.detail_provider, XingheImageProvider)
    assert provider_router.detail_provider.skill_id == "xinghe-ecommerce-detail"
    assert provider_router.detail_provider.skill_root == default_xinghe_skill_root()
    assert JobType.DETAIL_PACK.value not in provider_router.routes
    assert not isinstance(provider_router.detail_provider, CrossborderDetailProvider)

    assert isinstance(domestic_adapter, DomesticDetailProvider)
    assert domestic_adapter.route.skill_id == DOMESTIC_DETAIL_SKILL_ID
    domestic_delegate = cast(XingheImageProvider, domestic_adapter.delegate)
    assert domestic_delegate.skill_id == DOMESTIC_DETAIL_SKILL_ID
    assert domestic_delegate.skill_root == default_skill_root(DOMESTIC_DETAIL_SKILL_ID)
    assert Path(domestic_delegate.skill_root).is_dir()
