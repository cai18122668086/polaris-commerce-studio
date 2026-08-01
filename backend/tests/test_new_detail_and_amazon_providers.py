import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.amazon_visual_suite_provider import (
    AMAZON_EXPECTED_ITEM_COUNT,
    AMAZON_ITEM_KEYS,
    AMAZON_ITEM_SPECS,
    AmazonVisualSuiteProvider,
    amazon_item_spec,
    validate_amazon_item_keys,
)
from app.crossborder_detail_provider import (
    CROSSBORDER_DETAIL_SKILL_ID,
    CrossborderDetailProvider,
)
from app.domestic_detail_provider import (
    DOMESTIC_DETAIL_SKILL_ID,
    DomesticDetailProvider,
)
from app.new_detail_skill_provider import (
    SKILL_ADAPTER_CONFIGURATION_KEY,
    AdapterValidationError,
    BundledSkillManifestValidator,
)
from app.provider import (
    ProviderArtifact,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from app.skill_runtime import SkillManifestRegistry, SkillRuntimeError


@dataclass
class RecordingManifestValidator:
    content_hash: str = "a" * 64
    error: SkillRuntimeError | None = None
    calls: list[str] = field(default_factory=list)

    def validate(self, skill_id: str) -> str:
        self.calls.append(skill_id)
        if self.error is not None:
            raise self.error
        return self.content_hash


class RecordingDelegate:
    name = "mock"
    model = "adapter-test"
    pricing_version = "adapter-test-v1"

    def __init__(self, result: ProviderResult | None = None) -> None:
        self.result = result or ProviderResult(outcome=ProviderOutcome.SUCCEEDED)
        self.requests: list[ProviderRequest] = []

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return self.result


def _request(
    operation: str,
    configuration: dict[str, object],
) -> ProviderRequest:
    return ProviderRequest(
        workspace_id="ws_test",
        job_id="job_test",
        job_item_id="item_test",
        attempt_id="attempt_test",
        operation=operation,
        idempotency_key="idem_test",
        configuration=configuration,
    )


def _amazon_request(
    item_key: str,
    width: int,
    height: int,
    *,
    operation: str = "amazon_visual_suite",
    marketplace: object = "amazon-us",
    **item_overrides: object,
) -> ProviderRequest:
    item: dict[str, object] = {
        "item_key": item_key,
        "target_width": width,
        "target_height": height,
        **item_overrides,
    }
    return _request(
        operation,
        {"job": {"settings": {"marketplace": marketplace}}, "item": item},
    )


def _artifact(width: int, height: int) -> ProviderArtifact:
    payload = b"real-provider-test-payload"
    return ProviderArtifact(
        payload=payload,
        filename="result.png",
        content_type="image/png",
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_bundled_manifest_validator_verifies_three_new_sources() -> None:
    registry = SkillManifestRegistry.bundled()
    source_base = Path(__file__).resolve().parents[1] / "skill_sources"
    skill_ids = (
        DOMESTIC_DETAIL_SKILL_ID,
        CROSSBORDER_DETAIL_SKILL_ID,
        "xinghe-amazon-visual-suite",
    )
    validator = BundledSkillManifestValidator(
        registry,
        source_roots={skill_id: source_base / skill_id for skill_id in skill_ids},
    )

    for skill_id in skill_ids:
        assert validator.validate(skill_id) == registry.get(skill_id).content_hash


def test_domestic_adapter_attaches_auto_plan_contract_and_defaults() -> None:
    delegate = RecordingDelegate()
    validator = RecordingManifestValidator()
    provider = DomesticDetailProvider(delegate, manifest_validator=validator)
    request = _request(
        "detail_pack",
        {
            "job": {
                "market_region": "domestic",
                "platform_code": "jd",
                "page_count": 6,
            },
            "item": {"item_key": "page-001"},
        },
    )

    result = asyncio.run(provider.execute(request))

    assert result is delegate.result
    assert validator.calls == [DOMESTIC_DETAIL_SKILL_ID]
    routed = delegate.requests[0]
    assert routed.operation == "detail_pack"
    assert routed.configuration["job"] == request.configuration["job"]
    adapter = routed.configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
    assert adapter["skill_id"] == DOMESTIC_DETAIL_SKILL_ID
    assert adapter["skill_content_hash"] == "a" * 64
    assert adapter["market_region"] == "domestic"
    assert adapter["planning"] == {
        "required": True,
        "persist_validated_plan": True,
        "auto_confirm_after_validation": True,
        "structure_repair_limit": 1,
        "changes_existing_confirmation_gate": False,
    }
    assert adapter["prompt"]["platform_code"] == "jd"
    assert adapter["prompt"]["language"] == "zh-CN"
    assert adapter["prompt"]["aspect_ratio"] == "3:4"
    assert adapter["prompt"]["requested_page_count"] == 6


def test_domestic_adapter_normalizes_pdd_to_pinduoduo() -> None:
    delegate = RecordingDelegate()
    provider = DomesticDetailProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(
            _request(
                "detail_pack",
                {
                    "job": {
                        "settings": {
                            "market_region": "domestic",
                            "platform_code": "pdd",
                        }
                    },
                    "item": {"item_key": "page-001"},
                },
            )
        )
    )

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert len(delegate.requests) == 1
    adapter = delegate.requests[0].configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
    assert adapter["prompt"]["platform_code"] == "pinduoduo"


@pytest.mark.parametrize("platform_code", ["ozon", "wildberries"])
def test_crossborder_russian_platform_prompt_defaults(platform_code: str) -> None:
    delegate = RecordingDelegate()
    provider = CrossborderDetailProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )
    request = _request(
        "detail_pack",
        {
            "job": {
                "market_region": "international",
                "platform_code": platform_code,
            }
        },
    )

    result = asyncio.run(provider.execute(request))

    assert result is delegate.result
    prompt = delegate.requests[0].configuration[
        SKILL_ADAPTER_CONFIGURATION_KEY
    ]["prompt"]
    assert prompt["language"] == "ru"
    assert prompt["aspect_ratio"] == "3:4"
    assert prompt["target_size"] == {
        "mode": "exact",
        "width": 900,
        "height": 1200,
        "aspect_ratio": "3:4",
    }
    assert prompt["requested_page_count"] == 8
    assert prompt["continue_after_single_page_failure"] is True


def test_crossborder_generic_prompt_uses_2k_english_defaults() -> None:
    delegate = RecordingDelegate()
    provider = CrossborderDetailProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(
            _request(
                "detail_pack",
                {
                    "job": {
                        "market_region": "international",
                        "platform_code": "amazon",
                    }
                },
            )
        )
    )

    assert result is delegate.result
    prompt = delegate.requests[0].configuration[
        SKILL_ADAPTER_CONFIGURATION_KEY
    ]["prompt"]
    assert prompt["platform_code"] == "amazon"
    assert prompt["language"] == "en"
    assert prompt["aspect_ratio"] == "16:9"
    assert prompt["target_size"] == {
        "mode": "quality_tier",
        "quality": "2K",
        "aspect_ratio": "16:9",
    }


@pytest.mark.parametrize(
    ("provider_factory", "configuration", "expected_code"),
    [
        (
            DomesticDetailProvider,
            {"job": {"market_region": "international"}},
            "DETAIL_MARKET_REGION_MISMATCH",
        ),
        (
            CrossborderDetailProvider,
            {"job": {"market_region": "domestic"}},
            "DETAIL_MARKET_REGION_MISMATCH",
        ),
    ],
)
def test_detail_adapters_reject_wrong_market_route(
    provider_factory: type[DomesticDetailProvider] | type[CrossborderDetailProvider],
    configuration: dict[str, object],
    expected_code: str,
) -> None:
    delegate = RecordingDelegate()
    provider = provider_factory(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(provider.execute(_request("detail_pack", configuration)))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == expected_code
    assert result.artifact is None
    assert delegate.requests == []


def test_detail_adapter_rejects_operation_mismatch() -> None:
    delegate = RecordingDelegate()
    validator = RecordingManifestValidator()
    provider = DomesticDetailProvider(delegate, manifest_validator=validator)

    result = asyncio.run(
        provider.execute(
            _request("local_edit", {"job": {"market_region": "domestic"}})
        )
    )

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "OPERATION_NOT_SUPPORTED"
    assert validator.calls == [DOMESTIC_DETAIL_SKILL_ID]
    assert delegate.requests == []


def test_manifest_failure_is_fail_closed_and_rechecked_per_call() -> None:
    delegate = RecordingDelegate()
    validator = RecordingManifestValidator(
        error=SkillRuntimeError(
            "SKILL_CONTENT_HASH_MISMATCH",
            "simulated source drift",
        )
    )
    provider = CrossborderDetailProvider(
        delegate,
        manifest_validator=validator,
    )
    request = _request(
        "detail_pack",
        {"job": {"market_region": "international"}},
    )

    first = asyncio.run(provider.execute(request))
    second = asyncio.run(provider.execute(request))

    assert first.outcome == ProviderOutcome.FAILED
    assert first.error_code == "SKILL_CONTENT_HASH_MISMATCH"
    assert second.error_code == "SKILL_CONTENT_HASH_MISMATCH"
    assert validator.calls == [
        CROSSBORDER_DETAIL_SKILL_ID,
        CROSSBORDER_DETAIL_SKILL_ID,
    ]
    assert delegate.requests == []


@pytest.mark.parametrize(
    "outcome",
    [ProviderOutcome.FAILED, ProviderOutcome.OUTCOME_UNKNOWN],
)
def test_detail_delegate_failure_and_unknown_are_passthrough(
    outcome: ProviderOutcome,
) -> None:
    delegated_result = ProviderResult(
        outcome=outcome,
        error_code="DELEGATE_RESULT",
        error_message="delegate controls the outcome",
        retryable=True,
    )
    delegate = RecordingDelegate(delegated_result)
    provider = DomesticDetailProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(
            _request("detail_pack", {"job": {"market_region": "domestic"}})
        )
    )

    assert result is delegated_result
    assert result.artifact is None


def test_amazon_inventory_and_dimension_mapping_are_canonical() -> None:
    assert AMAZON_EXPECTED_ITEM_COUNT == 21
    assert len(AMAZON_ITEM_KEYS) == 21
    assert (
        "MAIN-01",
        *(f"SECONDARY-{index:02d}" for index in range(1, 7)),
        *(f"A-DESKTOP-{index:02d}" for index in range(1, 8)),
        *(f"A-MOBILE-{index:02d}" for index in range(1, 8)),
    ) == AMAZON_ITEM_KEYS
    assert validate_amazon_item_keys(AMAZON_ITEM_KEYS) == AMAZON_ITEM_KEYS
    assert amazon_item_spec("MAIN-01").width == 2000
    assert amazon_item_spec("MAIN-01").height == 2000
    secondary = amazon_item_spec("SECONDARY-06")
    desktop = amazon_item_spec("A-DESKTOP-07")
    mobile = amazon_item_spec("A-MOBILE-07")
    assert (secondary.width, secondary.height) == (1200, 1600)
    assert (desktop.width, desktop.height) == (1464, 600)
    assert (mobile.width, mobile.height) == (1600, 1200)
    assert len(AMAZON_ITEM_SPECS) == AMAZON_EXPECTED_ITEM_COUNT


def test_amazon_adapter_attaches_item_contract_and_preserves_result() -> None:
    delegated_result = ProviderResult(outcome=ProviderOutcome.OUTCOME_UNKNOWN)
    delegate = RecordingDelegate(delegated_result)
    validator = RecordingManifestValidator()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=validator,
    )

    result = asyncio.run(
        provider.execute(_amazon_request("A-DESKTOP-03", 1464, 600))
    )

    assert result is delegated_result
    assert validator.calls == ["xinghe-amazon-visual-suite"]
    adapter = delegate.requests[0].configuration[
        SKILL_ADAPTER_CONFIGURATION_KEY
    ]
    assert adapter["expected_item_count"] == 21
    assert tuple(adapter["canonical_item_keys"]) == AMAZON_ITEM_KEYS
    assert adapter["item"] == {
        "item_key": "A-DESKTOP-03",
        "group": "a_desktop",
        "group_ordinal": 3,
        "target_width": 1464,
        "target_height": 600,
        "deliverable_counted": True,
        "contact_sheet": False,
    }


@pytest.mark.parametrize(
    ("provider_request", "expected_code"),
    [
        (
            _amazon_request("CONTACT-SHEET", 2000, 2000),
            "AMAZON_ITEM_KEY_INVALID",
        ),
        (
            _amazon_request(
                "MAIN-01",
                2000,
                2000,
                contact_sheet=True,
            ),
            "AMAZON_CONTACT_SHEET_NOT_DELIVERABLE",
        ),
        (
            _amazon_request("SECONDARY-01", 2000, 2000),
            "AMAZON_TARGET_SIZE_MISMATCH",
        ),
        (
            _request(
                "amazon_visual_suite",
                {"item": {"item_key": "MAIN-01"}},
            ),
            "AMAZON_TARGET_SIZE_MISSING",
        ),
    ],
)
def test_amazon_invalid_key_contact_sheet_and_size_are_rejected(
    provider_request: ProviderRequest,
    expected_code: str,
) -> None:
    delegate = RecordingDelegate()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(provider.execute(provider_request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == expected_code
    assert result.artifact is None
    assert delegate.requests == []


def test_amazon_non_amazon_marketplace_is_rejected_before_delegate() -> None:
    delegate = RecordingDelegate()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(_amazon_request("MAIN-01", 2000, 2000, marketplace="tmall"))
    )

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_MARKETPLACE_UNSUPPORTED"
    assert result.artifact is None
    assert delegate.requests == []


def test_amazon_operation_mismatch_is_rejected() -> None:
    delegate = RecordingDelegate()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(
            _amazon_request("MAIN-01", 2000, 2000, operation="detail_pack")
        )
    )

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "OPERATION_NOT_SUPPORTED"
    assert delegate.requests == []


def test_amazon_output_dimension_mismatch_fails_without_placeholder() -> None:
    delegate = RecordingDelegate(
        ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            artifact=_artifact(1200, 1200),
        )
    )
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(
        provider.execute(_amazon_request("MAIN-01", 2000, 2000))
    )

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_OUTPUT_DIMENSIONS_INVALID"
    assert result.artifact is None


def test_amazon_success_without_artifact_fails_closed() -> None:
    delegate = RecordingDelegate(ProviderResult(outcome=ProviderOutcome.SUCCEEDED))
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(provider.execute(_amazon_request("MAIN-01", 2000, 2000)))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_OUTPUT_ARTIFACT_MISSING"
    assert result.retryable is False
    assert result.artifact is None
    assert result.persisted_artifact is None
    assert len(delegate.requests) == 1


def test_amazon_inventory_rejects_contact_sheet_or_partial_list() -> None:
    with pytest.raises(AdapterValidationError) as exc_info:
        validate_amazon_item_keys((*AMAZON_ITEM_KEYS[:-1], "CONTACT-SHEET"))

    assert exc_info.value.code == "AMAZON_ITEM_INVENTORY_INVALID"


def test_domestic_detail_accepts_execution_coordinator_envelope() -> None:
    delegate = RecordingDelegate()
    provider = DomesticDetailProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )
    request = _request(
        "detail_pack",
        {
            "job": {
                "input": {"product_groups": [{"group_key": "main"}]},
                "settings": {
                    "market_region": "domestic",
                    "platform_code": "jd",
                    "page_count": 6,
                    "language": "zh-CN",
                },
            },
            "item": {"page": 1},
        },
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert len(delegate.requests) == 1
    adapter = delegate.requests[0].configuration[
        SKILL_ADAPTER_CONFIGURATION_KEY
    ]
    assert adapter["market_region"] == "domestic"
    assert adapter["prompt"]["platform_code"] == "jd"
    assert adapter["prompt"]["requested_page_count"] == 6
