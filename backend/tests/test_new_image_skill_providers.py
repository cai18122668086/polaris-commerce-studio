from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.creative_image_provider import CreativeImageProvider
from app.product_image_provider import PRODUCT_IMAGE_PRESETS, ProductImageProvider
from app.provider import (
    ProviderArtifact,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from app.reference_remix_provider import ReferenceRemixProvider


@dataclass
class ManifestSpy:
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    def __call__(self, skill_id: str) -> None:
        self.calls.append(skill_id)
        if self.error is not None:
            raise self.error


class StubDelegate:
    name = "stub-image-provider"
    model = "stub-image-model"
    pricing_version = "test-only"

    def __init__(self, result: ProviderResult) -> None:
        self.result = result
        self.requests: list[ProviderRequest] = []

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return self.result


def _artifact_result(*, raw_usage: dict[str, Any] | None = None) -> ProviderResult:
    payload = b"independent-image-payload"
    return ProviderResult(
        outcome=ProviderOutcome.SUCCEEDED,
        provider_request_id="provider-request-1",
        usage_reported=True,
        raw_usage=raw_usage or {"output_images": 1},
        artifact=ProviderArtifact(
            payload=payload,
            filename="image-001.png",
            content_type="image/png",
            width=1024,
            height=1024,
            sha256=hashlib.sha256(payload).hexdigest(),
        ),
        provider_name="stub-image-provider",
        model_name="stub-image-model",
        pricing_version="test-only",
    )


def _request(
    operation: str,
    *,
    input_config: dict[str, Any],
    settings: dict[str, Any],
) -> ProviderRequest:
    return ProviderRequest(
        workspace_id="ws-1",
        job_id="job-1",
        job_item_id="item-1",
        attempt_id="attempt-1",
        operation=operation,
        idempotency_key="idem-1",
        configuration={
            "job": {"input": input_config, "settings": settings},
            "item": {"ordinal": 0},
        },
    )


@pytest.mark.parametrize("preset", sorted(PRODUCT_IMAGE_PRESETS))
def test_product_image_supports_all_eight_presets_and_delegates(preset: str) -> None:
    expected = _artifact_result()
    delegate = StubDelegate(expected)
    validator = ManifestSpy()
    provider = ProductImageProvider(delegate, manifest_validator=validator)
    settings: dict[str, Any] = {"task_type": preset, "image_count": 1}
    if preset == "change_color":
        settings["target_color"] = "海军蓝"
    request = _request(
        "product_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings=settings,
    )

    result = asyncio.run(provider.execute(request))

    assert result is expected
    assert delegate.requests == [request]
    assert validator.calls == ["xinghe-wanneng-shengtu-3-0"]


def test_manifest_validator_runs_before_every_delegate_call() -> None:
    delegate = StubDelegate(_artifact_result())
    validator = ManifestSpy()
    provider = CreativeImageProvider(delegate, manifest_validator=validator)
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"image_count": 4},
    )

    asyncio.run(provider.execute(request))
    asyncio.run(provider.execute(request))

    assert validator.calls == [
        "xinghe-ecommerce-creative-image",
        "xinghe-ecommerce-creative-image",
    ]
    assert delegate.requests == [request, request]


def test_product_change_color_rejects_missing_target_color() -> None:
    delegate = StubDelegate(_artifact_result())
    validator = ManifestSpy()
    provider = ProductImageProvider(delegate, manifest_validator=validator)
    request = _request(
        "product_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"task_type": "change_color", "image_count": 1},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "TARGET_COLOR_REQUIRED"
    assert delegate.requests == []
    assert validator.calls == []


@pytest.mark.parametrize(
    ("input_config", "missing_key"),
    [
        ({"reference_asset_ids": ["asset-style"]}, "product_asset_ids"),
        ({"product_asset_ids": ["asset-product"]}, "reference_asset_ids"),
    ],
)
def test_reference_remix_requires_product_and_style_clues(
    input_config: dict[str, Any],
    missing_key: str,
) -> None:
    delegate = StubDelegate(_artifact_result())
    validator = ManifestSpy()
    provider = ReferenceRemixProvider(delegate, manifest_validator=validator)
    request = _request(
        "reference_remix",
        input_config=input_config,
        settings={"image_count": 1},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "REQUIRED_IMAGE_INPUT_MISSING"
    assert missing_key in (result.error_message or "")
    assert delegate.requests == []
    assert validator.calls == []


@pytest.mark.parametrize("image_count", [0, 5, True, "4"])
def test_creative_image_rejects_out_of_range_image_count(
    image_count: object,
) -> None:
    delegate = StubDelegate(_artifact_result())
    provider = CreativeImageProvider(delegate, manifest_validator=ManifestSpy())
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"image_count": image_count},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "IMAGE_COUNT_OUT_OF_RANGE"
    assert delegate.requests == []


def test_delegate_failure_is_passed_through_unchanged() -> None:
    expected = ProviderResult(
        outcome=ProviderOutcome.FAILED,
        provider_request_id="provider-request-failed",
        error_code="UPSTREAM_FAILED",
        error_message="stub failure",
        usage_reported=True,
        raw_usage={"request_count": 1},
        retryable=True,
        provider_name="stub-image-provider",
    )
    delegate = StubDelegate(expected)
    provider = ReferenceRemixProvider(delegate, manifest_validator=ManifestSpy())
    request = _request(
        "reference_remix",
        input_config={
            "product_asset_ids": ["asset-product"],
            "reference_asset_ids": ["asset-style"],
        },
        settings={"image_count": 1},
    )

    result = asyncio.run(provider.execute(request))

    assert result is expected
    assert delegate.requests == [request]


def test_operation_mismatch_fails_before_manifest_or_delegate() -> None:
    delegate = StubDelegate(_artifact_result())
    validator = ManifestSpy()
    provider = ProductImageProvider(delegate, manifest_validator=validator)
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"task_type": "scene_main", "image_count": 1},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "OPERATION_NOT_SUPPORTED"
    assert delegate.requests == []
    assert validator.calls == []


def test_missing_manifest_validator_fails_closed() -> None:
    delegate = StubDelegate(_artifact_result())
    provider = CreativeImageProvider(delegate)
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"image_count": 4},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "SKILL_MANIFEST_VALIDATOR_REQUIRED"
    assert delegate.requests == []


def test_manifest_validation_failure_does_not_call_delegate() -> None:
    delegate = StubDelegate(_artifact_result())
    validator = ManifestSpy(error=RuntimeError("private validator details"))
    provider = CreativeImageProvider(delegate, manifest_validator=validator)
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"image_count": 4},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "SKILL_MANIFEST_VALIDATION_FAILED"
    assert "private validator details" not in (result.error_message or "")
    assert delegate.requests == []


@pytest.mark.parametrize(
    "delegate_result",
    [
        ProviderResult(outcome=ProviderOutcome.SUCCEEDED),
        _artifact_result(raw_usage={"placeholder": True}),
        _artifact_result(raw_usage={"artifact_kind": "contact_sheet"}),
    ],
)
def test_success_requires_a_real_independent_image_artifact(
    delegate_result: ProviderResult,
) -> None:
    delegate = StubDelegate(delegate_result)
    provider = CreativeImageProvider(delegate, manifest_validator=ManifestSpy())
    request = _request(
        "creative_image",
        input_config={"product_asset_ids": ["asset-product"]},
        settings={"image_count": 4},
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "GENERATED_IMAGE_ARTIFACT_REQUIRED"
    assert delegate.requests == [request]
