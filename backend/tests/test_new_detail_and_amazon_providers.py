import asyncio
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.amazon_visual_suite_provider import (
    AMAZON_AUDIT_CONFIGURATION_KEY,
    AMAZON_EXPECTED_ITEM_COUNT,
    AMAZON_ITEM_KEYS,
    AMAZON_ITEM_SPECS,
    AMAZON_PLAN_CONFIGURATION_KEY,
    AmazonVisualSuiteProvider,
    amazon_item_spec,
    validate_amazon_item_keys,
)
from app.crossborder_detail_provider import (
    CROSSBORDER_DETAIL_SKILL_ID,
    CrossborderDetailProvider,
)
from app.domestic_detail_provider import (
    DOMESTIC_DEFAULT_SIZE,
    DOMESTIC_DETAIL_SKILL_ID,
    DomesticDetailProvider,
)
from app.new_detail_skill_provider import (
    SKILL_ADAPTER_CONFIGURATION_KEY,
    AdapterValidationError,
    BundledSkillManifestValidator,
)
from app.new_image_skill_provider import SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION
from app.provider import (
    ProviderArtifact,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from app.skill_runtime import SkillManifestRegistry, SkillRuntimeError
from app.xinghe_single_image_provider import DEFAULT_ALLOWED_PROMPT_FIELDS


def _assert_strict_single_image_envelope(request: ProviderRequest) -> None:
    envelope = request.configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
    assert set(envelope) == {
        "schema_version",
        "skill_id",
        "skill_content_hash",
        "operation",
        "item_key",
        "item_ordinal",
        "source_assets",
        "target",
        "prompt_input",
    }
    identifier = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
    assert identifier.fullmatch(envelope["item_key"])
    assert 1 <= len(envelope["source_assets"]) <= 8
    target = envelope["target"]
    assert set(target) == {
        "width",
        "height",
        "aspect_ratio",
        "quality",
        "output_format",
        "fit",
    }
    assert isinstance(target["width"], int) and target["width"] > 0
    assert isinstance(target["height"], int) and target["height"] > 0
    divisor = math.gcd(target["width"], target["height"])
    assert target["aspect_ratio"] == (
        f"{target['width'] // divisor}:{target['height'] // divisor}"
    )
    assert target["fit"] in {"cover", "contain", "pad"}
    assert set(envelope["prompt_input"]) <= DEFAULT_ALLOWED_PROMPT_FIELDS
    assert all(value not in ("", []) for value in envelope["prompt_input"].values())


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
    try:
        spec = amazon_item_spec(item_key)
    except AdapterValidationError:
        spec = None
    if spec is not None:
        item[AMAZON_PLAN_CONFIGURATION_KEY] = {
            "analysis": {
                "product_master_description": {
                    "silhouette_and_proportions": "Preserve the supplied shape.",
                    "color_and_material_appearance": "Preserve visible appearance.",
                    "logos_labels_and_patterns": "Preserve visible markings.",
                    "structural_parts": "Do not add or remove parts.",
                    "scale_and_physics": "Keep scale and physical logic credible.",
                    "unknowns": [],
                },
                "product_consistency_anchors": {
                    "overall_silhouette": "One exact SKU.",
                },
            },
            "campaign_style_lock": {"style": "consistent campaign"},
            "design_strength_lock": {"strength": "product-led evidence"},
            "product_consistency_lock": {"sku_identity": "one exact SKU"},
            "layout_diversity_lock": {"max_same_layout_family": 3},
            "screen": {
                "item_key": spec.item_key,
                "buyer_question": spec.buyer_question,
                "selling_point": spec.selling_point,
                "information_confidence": "confirmed visible facts only",
                "visual_proof": spec.visual_proof,
                "headline": spec.headline,
                "subcopy": spec.subcopy,
                "layout_direction": spec.layout_direction,
                "layout_family": f"planned-{spec.group}",
                "camera_angle": "planned camera angle",
                "product_position": "planned product position",
                "background_system": "planned background system",
                "prop_strategy": "planned prop strategy",
                "copy_density": "sparse",
                "source_material": spec.source_material,
                "risk_note": spec.risk_note,
            },
            "resume_signature": "b" * 64,
        }
    return _request(
        operation,
        {
            "job": {
                "input": {
                    "white_background_product_asset_ids": ["asset-white"],
                    "detail_asset_ids": ["asset-detail"],
                    "package_asset_ids": ["asset-package"],
                    "scene_asset_ids": ["asset-scene"],
                    "brand_asset_ids": ["asset-brand"],
                },
                "settings": {
                    "marketplace": marketplace,
                    "product_name": "Test product",
                    "listing_title": "Test listing",
                    "bullet_points": ["Point one"],
                    "brand_colors": ["navy"],
                    "language": "en-US",
                    "private_note": "must-not-reach-envelope",
                },
            },
            "item": item,
        },
    )


class StrictRecordingDelegate(RecordingDelegate):
    async def execute(self, request: ProviderRequest) -> ProviderResult:
        _assert_strict_single_image_envelope(request)
        return await super().execute(request)


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


def _jpeg_artifact(width: int, height: int) -> ProviderArtifact:
    payload = b"amazon-ready-jpeg-test-payload"
    return ProviderArtifact(
        payload=payload,
        filename="result.jpg",
        content_type="image/jpeg",
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
    assert adapter["prompt"]["resolved_size"] == DOMESTIC_DEFAULT_SIZE
    assert adapter["prompt"]["target_size"] == {
        "mode": "exact",
        "width": 1200,
        "height": 1600,
        "aspect_ratio": "3:4",
    }
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
    prompt = delegate.requests[0].configuration[SKILL_ADAPTER_CONFIGURATION_KEY][
        "prompt"
    ]
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
    prompt = delegate.requests[0].configuration[SKILL_ADAPTER_CONFIGURATION_KEY][
        "prompt"
    ]
    assert prompt["platform_code"] == "amazon"
    assert prompt["language"] == "en"
    assert prompt["aspect_ratio"] == "16:9"
    assert prompt["target_size"] == {
        "mode": "quality_tier",
        "quality": "2K",
        "aspect_ratio": "16:9",
    }


def test_domestic_rejects_explicit_non_three_by_four_size() -> None:
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
                        "market_region": "domestic",
                        "platform_code": "tmall",
                        "size": "1600x1600",
                    }
                },
            )
        )
    )

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "DETAIL_SIZE_UNSUPPORTED"
    assert delegate.requests == []


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
        provider.execute(_request("local_edit", {"job": {"market_region": "domestic"}}))
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
    delegate = StrictRecordingDelegate(delegated_result)
    validator = RecordingManifestValidator()
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=validator,
    )

    result = asyncio.run(provider.execute(_amazon_request("A-DESKTOP-03", 1464, 600)))

    assert result is delegated_result
    assert validator.calls == ["xinghe-amazon-visual-suite"]
    adapter = delegate.requests[0].configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
    assert adapter["schema_version"] == SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION
    assert adapter["skill_id"] == "xinghe-amazon-visual-suite"
    assert adapter["skill_content_hash"] == "a" * 64
    assert adapter["operation"] == "amazon_visual_suite"
    assert adapter["item_key"] == "A-DESKTOP-03"
    assert adapter["item_ordinal"] == AMAZON_ITEM_KEYS.index("A-DESKTOP-03")
    assert adapter["source_assets"] == [
        {"asset_id": "asset-white", "role": "white_background_product"},
        {"asset_id": "asset-detail", "role": "product_detail"},
        {"asset_id": "asset-package", "role": "package_reference"},
        {"asset_id": "asset-scene", "role": "scene_reference"},
        {"asset_id": "asset-brand", "role": "brand_reference"},
    ]
    assert adapter["target"] == {
        "aspect_ratio": "61:25",
        "width": 1464,
        "height": 600,
        "quality": "high",
        "output_format": "jpeg",
        "fit": "contain",
    }
    prompt = adapter["prompt_input"]
    assert prompt["marketplace"] == "amazon-us"
    assert prompt["product_name"] == "Test product"
    assert prompt["product_information"] == ["Test listing", "Point one"]
    assert prompt["color_palette"] == ["navy"]
    assert prompt["language"] == "en-US"
    assert prompt["composition"] == "a_desktop"
    assert prompt["image_count"] == 1
    assert prompt["creative_direction"] == [
        "Asset type: Desktop A+ core-feature module",
        (
            "Layout direction: Wide structure or macro composition with "
            "evidence larger than text."
        ),
        "Layout family: planned-a_desktop",
        "Camera angle: planned camera angle",
        "Product position: planned product position",
        "Background system: planned background system",
        "Prop strategy: planned prop strategy",
        "Copy density: sparse",
    ]
    assert prompt["copy_requirements"] == [
        (
            "Headline: One short differentiation headline grounded in "
            "confirmed evidence."
        ),
        "Subcopy: Use sparse feature labels only where legible.",
    ]
    assert (
        "Buyer question: What makes it different?"
        in prompt["reference_guidance"]
    )
    assert (
        "Visual proof: Use mechanism, structure, craft, or close-detail evidence."
        in prompt["reference_guidance"]
    )
    assert prompt["reference_guidance"][0].startswith(
        "Product Master Description: "
    )
    assert len(prompt["negative_constraints"]) == 3
    assert "private_note" not in prompt
    audit = delegate.requests[0].configuration[AMAZON_AUDIT_CONFIGURATION_KEY]
    assert audit["expected_item_count"] == 21
    assert tuple(audit["canonical_item_keys"]) == AMAZON_ITEM_KEYS
    assert audit["contact_sheet"] is False
    assert audit["item"] == {
        "item_key": "A-DESKTOP-03",
        "delegate_item_key": "A-DESKTOP-03",
        "group": "a_desktop",
        "group_ordinal": 3,
        "target_width": 1464,
        "target_height": 600,
        "deliverable_counted": True,
        "contact_sheet": False,
        "plan_resume_signature": "b" * 64,
        "task": {
            "id": "A-DESKTOP-03",
            "asset_type": "Desktop A+ core-feature module",
            "final_size": "1464x600",
            "buyer_question": "What makes it different?",
            "selling_point": (
                "Explain one confirmed mechanism, structure, technology, craft, "
                "or detail."
            ),
            "information_confidence": (
                "Use confirmed facts first; soften reasonable inferences; omit "
                "every needs-confirmation claim from the image."
            ),
            "visual_proof": (
                "Use mechanism, structure, craft, or close-detail evidence."
            ),
            "headline": (
                "One short differentiation headline grounded in confirmed evidence."
            ),
            "subcopy": "Use sparse feature labels only where legible.",
            "layout_direction": (
                "Wide structure or macro composition with evidence larger than text."
            ),
            "source_material": (
                "Prioritize product_detail and white_background_product references."
            ),
            "risk_note": (
                "Do not invent materials, construction, technology, patents, or "
                "lab evidence."
            ),
        },
    }


def test_amazon_all_21_items_have_independent_authoritative_task_contracts() -> None:
    delegate = StrictRecordingDelegate(
        ProviderResult(outcome=ProviderOutcome.OUTCOME_UNKNOWN)
    )
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    for spec in AMAZON_ITEM_SPECS:
        asyncio.run(
            provider.execute(_amazon_request(spec.item_key, spec.width, spec.height))
        )

    required_task_fields = {
        "id",
        "asset_type",
        "final_size",
        "buyer_question",
        "selling_point",
        "information_confidence",
        "visual_proof",
        "headline",
        "subcopy",
        "layout_direction",
        "source_material",
        "risk_note",
    }
    task_rows: list[tuple[tuple[str, str], ...]] = []
    for ordinal, (spec, request) in enumerate(
        zip(AMAZON_ITEM_SPECS, delegate.requests, strict=True)
    ):
        adapter = request.configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
        audit = request.configuration[AMAZON_AUDIT_CONFIGURATION_KEY]
        task = audit["item"]["task"]
        prompt = adapter["prompt_input"]

        assert adapter["item_key"] == AMAZON_ITEM_KEYS[ordinal] == spec.item_key
        assert adapter["item_ordinal"] == ordinal
        assert adapter["target"]["width"] == spec.width
        assert adapter["target"]["height"] == spec.height
        assert adapter["target"]["output_format"] == "jpeg"
        assert adapter["target"]["fit"] == (
            "pad" if spec.group == "main" else "contain"
        )
        assert set(task) == required_task_fields
        assert task["id"] == spec.item_key
        assert task["final_size"] == f"{spec.width}x{spec.height}"
        assert all(isinstance(value, str) and value for value in task.values())
        assert prompt["product_information"] == ["Test listing", "Point one"]
        assert (
            f"Buyer question: {task['buyer_question']}"
            in prompt["reference_guidance"]
        )
        assert (
            f"Selling point: {task['selling_point']}"
            in prompt["reference_guidance"]
        )
        assert (
            f"Visual proof: {task['visual_proof']}"
            in prompt["reference_guidance"]
        )
        assert prompt["creative_direction"][1] == (
            f"Layout direction: {task['layout_direction']}"
        )
        assert prompt["copy_requirements"] == [
            f"Headline: {task['headline']}",
            f"Subcopy: {task['subcopy']}",
        ]
        assert prompt["negative_constraints"][1] == task["risk_note"]
        task_rows.append(tuple(sorted(task.items())))

    assert len(delegate.requests) == AMAZON_EXPECTED_ITEM_COUNT
    assert len(set(task_rows)) == AMAZON_EXPECTED_ITEM_COUNT


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

    result = asyncio.run(provider.execute(_amazon_request("MAIN-01", 2000, 2000)))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_OUTPUT_DIMENSIONS_INVALID"
    assert result.artifact is None


def test_amazon_exact_size_png_fails_amazon_ready_format_contract() -> None:
    delegate = RecordingDelegate(
        ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            artifact=_artifact(2000, 2000),
        )
    )
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(provider.execute(_amazon_request("MAIN-01", 2000, 2000)))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "AMAZON_OUTPUT_FORMAT_INVALID"
    assert result.retryable is False
    assert result.artifact is None


def test_amazon_exact_size_jpeg_is_preserved_as_final_deliverable() -> None:
    artifact = _jpeg_artifact(1600, 1200)
    delegated_result = ProviderResult(
        outcome=ProviderOutcome.SUCCEEDED,
        artifact=artifact,
    )
    delegate = RecordingDelegate(delegated_result)
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=RecordingManifestValidator(),
    )

    result = asyncio.run(provider.execute(_amazon_request("A-MOBILE-07", 1600, 1200)))

    assert result is delegated_result
    assert result.artifact is artifact
    assert result.artifact.content_type == "image/jpeg"


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
    adapter = delegate.requests[0].configuration[SKILL_ADAPTER_CONFIGURATION_KEY]
    assert adapter["market_region"] == "domestic"
    assert adapter["prompt"]["platform_code"] == "jd"
    assert adapter["prompt"]["requested_page_count"] == 6
