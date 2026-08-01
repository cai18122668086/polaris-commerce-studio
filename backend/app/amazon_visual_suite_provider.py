"""Independent manifest-gated adapter for the Amazon 21-image suite."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import gcd
from typing import Any

from app.amazon_visual_suite_contract import (
    AMAZON_DEFAULT_MARKETPLACE,
    AMAZON_MARKETPLACES,
)
from app.new_detail_skill_provider import (
    SKILL_ADAPTER_CONFIGURATION_KEY,
    AdapterValidationError,
    BundledSkillManifestValidator,
    ManifestValidator,
    job_configuration_from,
    rejected_result,
)
from app.new_image_skill_provider import (
    SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION,
    NewImageSkillContractError,
    compact_prompt_input,
    optional_string,
    optional_string_list,
    require_asset_ids,
    role_labelled_assets,
    validate_optional_asset_ids,
)
from app.provider import Provider, ProviderOutcome, ProviderRequest, ProviderResult
from app.skill_runtime import SkillRuntimeError

AMAZON_VISUAL_SUITE_OPERATION = "amazon_visual_suite"
AMAZON_VISUAL_SUITE_SKILL_ID = "xinghe-amazon-visual-suite"
AMAZON_ADAPTER_CONTRACT_VERSION = SINGLE_IMAGE_ADAPTER_CONTRACT_VERSION
AMAZON_EXPECTED_ITEM_COUNT = 21
AMAZON_AUDIT_CONFIGURATION_KEY = "amazon_visual_suite_audit"


@dataclass(frozen=True)
class AmazonItemSpec:
    item_key: str
    group: str
    group_ordinal: int
    width: int
    height: int


def _build_item_specs() -> tuple[AmazonItemSpec, ...]:
    return (
        AmazonItemSpec("MAIN-01", "main", 1, 2000, 2000),
        *(
            AmazonItemSpec(
                f"SECONDARY-{ordinal:02d}",
                "secondary",
                ordinal,
                1200,
                1600,
            )
            for ordinal in range(1, 7)
        ),
        *(
            AmazonItemSpec(
                f"A-DESKTOP-{ordinal:02d}",
                "a_desktop",
                ordinal,
                1464,
                600,
            )
            for ordinal in range(1, 8)
        ),
        *(
            AmazonItemSpec(
                f"A-MOBILE-{ordinal:02d}",
                "a_mobile",
                ordinal,
                1600,
                1200,
            )
            for ordinal in range(1, 8)
        ),
    )


AMAZON_ITEM_SPECS = _build_item_specs()
AMAZON_ITEM_KEYS = tuple(spec.item_key for spec in AMAZON_ITEM_SPECS)
_AMAZON_ITEM_SPEC_BY_KEY = {spec.item_key: spec for spec in AMAZON_ITEM_SPECS}


def amazon_item_spec(item_key: str) -> AmazonItemSpec:
    try:
        return _AMAZON_ITEM_SPEC_BY_KEY[item_key]
    except KeyError as exc:
        raise AdapterValidationError(
            "AMAZON_ITEM_KEY_INVALID",
            f"Unknown Amazon deliverable item key: {item_key}.",
        ) from exc


def validate_amazon_item_keys(item_keys: Sequence[str]) -> tuple[str, ...]:
    """Validate the exact stable 21-key inventory and ordering."""

    normalized = tuple(item_keys)
    if normalized != AMAZON_ITEM_KEYS:
        missing = [key for key in AMAZON_ITEM_KEYS if key not in normalized]
        extra = [key for key in normalized if key not in AMAZON_ITEM_KEYS]
        raise AdapterValidationError(
            "AMAZON_ITEM_INVENTORY_INVALID",
            (
                "Amazon visual suite requires the canonical 21-item inventory; "
                f"missing={missing}, extra={extra}."
            ),
        )
    return normalized


class AmazonVisualSuiteProvider:
    """Validate one Amazon JobItem and delegate real or fake generation.

    Contact sheets are intentionally absent from ``AMAZON_ITEM_KEYS`` and can
    never pass this adapter as a counted deliverable.
    """

    def __init__(
        self,
        delegate: Provider,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        self.delegate = delegate
        self.manifest_validator = (
            manifest_validator or BundledSkillManifestValidator()
        )
        self.name = delegate.name
        self.model = delegate.model
        self.pricing_version = delegate.pricing_version

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            content_hash = self.manifest_validator.validate(
                AMAZON_VISUAL_SUITE_SKILL_ID
            )
            if not isinstance(content_hash, str) or not content_hash.strip():
                raise AdapterValidationError(
                    "SKILL_MANIFEST_VALIDATION_FAILED",
                    "The Skill manifest validator did not return a content hash.",
                )
            routed_request, spec = self.prepare_request(
                request,
                content_hash=content_hash.strip(),
            )
        except SkillRuntimeError as exc:
            return rejected_result(self, exc.code, str(exc))
        except (AdapterValidationError, NewImageSkillContractError) as exc:
            return rejected_result(self, exc.code, str(exc))
        except Exception as exc:
            return rejected_result(
                self,
                "SKILL_MANIFEST_VALIDATION_FAILED",
                f"Skill manifest validation failed ({type(exc).__name__}).",
            )

        result = await self.delegate.execute(routed_request)
        if result.outcome != ProviderOutcome.SUCCEEDED:
            return result
        return self._validate_output_contract(result, spec)

    def prepare_request(
        self,
        request: ProviderRequest,
        *,
        content_hash: str,
    ) -> tuple[ProviderRequest, AmazonItemSpec]:
        if request.operation != AMAZON_VISUAL_SUITE_OPERATION:
            raise AdapterValidationError(
                "OPERATION_NOT_SUPPORTED",
                (
                    f"{AMAZON_VISUAL_SUITE_SKILL_ID} only accepts "
                    f"{AMAZON_VISUAL_SUITE_OPERATION}."
                ),
            )
        job_configuration = job_configuration_from(request.configuration)
        marketplace = job_configuration.get("marketplace", AMAZON_DEFAULT_MARKETPLACE)
        if not isinstance(marketplace, str) or marketplace not in AMAZON_MARKETPLACES:
            raise AdapterValidationError(
                "AMAZON_MARKETPLACE_UNSUPPORTED",
                f"Unsupported Amazon marketplace: {marketplace!r}.",
            )
        item_configuration = _item_configuration(request.configuration)
        item_key = _required_item_key(item_configuration)
        spec = amazon_item_spec(item_key)
        _validate_contact_sheet_semantics(item_configuration)
        _validate_requested_dimensions(item_configuration, spec)
        _validate_group_semantics(item_configuration, spec)

        input_configuration = _job_input_configuration(request.configuration)
        source_assets = _amazon_source_assets(input_configuration)
        item_ordinal = AMAZON_ITEM_KEYS.index(spec.item_key)
        prompt_input = _amazon_prompt_input(job_configuration, spec)
        aspect_ratio = _aspect_ratio(spec.width, spec.height)
        adapter_configuration = {
            "schema_version": AMAZON_ADAPTER_CONTRACT_VERSION,
            "skill_id": AMAZON_VISUAL_SUITE_SKILL_ID,
            "skill_content_hash": content_hash,
            "operation": AMAZON_VISUAL_SUITE_OPERATION,
            "item_key": spec.item_key,
            "item_ordinal": item_ordinal,
            "source_assets": source_assets,
            "target": {
                "aspect_ratio": aspect_ratio,
                "width": spec.width,
                "height": spec.height,
                "quality": "high",
                "output_format": "png",
                "fit": "cover",
            },
            "prompt_input": prompt_input,
        }
        audit_configuration = {
            "expected_item_count": AMAZON_EXPECTED_ITEM_COUNT,
            "canonical_item_keys": AMAZON_ITEM_KEYS,
            "contact_sheet": False,
            "item": {
                "item_key": spec.item_key,
                "delegate_item_key": spec.item_key,
                "group": spec.group,
                "group_ordinal": spec.group_ordinal,
                "target_width": spec.width,
                "target_height": spec.height,
                "deliverable_counted": True,
                "contact_sheet": False,
            },
        }
        return (
            replace(
                request,
                configuration={
                    **request.configuration,
                    SKILL_ADAPTER_CONFIGURATION_KEY: adapter_configuration,
                    AMAZON_AUDIT_CONFIGURATION_KEY: audit_configuration,
                },
            ),
            spec,
        )

    def _validate_output_contract(
        self,
        result: ProviderResult,
        spec: AmazonItemSpec,
    ) -> ProviderResult:
        artifact = result.persisted_artifact or result.artifact
        if artifact is None:
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="AMAZON_OUTPUT_ARTIFACT_MISSING",
                error_message=(
                    f"{spec.item_key} succeeded without a deliverable artifact."
                ),
                retryable=False,
                artifact=None,
                persisted_artifact=None,
            )
        if (artifact.width, artifact.height) == (spec.width, spec.height):
            return result
        return replace(
            result,
            outcome=ProviderOutcome.FAILED,
            error_code="AMAZON_OUTPUT_DIMENSIONS_INVALID",
            error_message=(
                f"{spec.item_key} requires {spec.width}x{spec.height}, got "
                f"{artifact.width}x{artifact.height}."
            ),
            retryable=False,
            artifact=None,
            persisted_artifact=None,
        )


def _item_configuration(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = configuration.get("item")
    if nested is None:
        return configuration
    if not isinstance(nested, Mapping):
        raise AdapterValidationError(
            "AMAZON_ITEM_CONFIGURATION_INVALID",
            "Amazon item configuration must be an object.",
        )
    return nested


def _job_input_configuration(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    job = configuration.get("job")
    if job is None:
        return {}
    if not isinstance(job, Mapping):
        raise AdapterValidationError(
            "JOB_CONFIGURATION_INVALID",
            "Provider request job configuration must be an object.",
        )
    value = job.get("input")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AdapterValidationError(
            "JOB_INPUT_INVALID",
            "Provider request job input must be an object.",
        )
    return value


def _amazon_source_assets(
    input_configuration: Mapping[str, Any],
) -> list[dict[str, str]]:
    white_background = require_asset_ids(
        input_configuration,
        "white_background_product_asset_ids",
    )
    detail = validate_optional_asset_ids(input_configuration, "detail_asset_ids")
    package = validate_optional_asset_ids(input_configuration, "package_asset_ids")
    scene = validate_optional_asset_ids(input_configuration, "scene_asset_ids")
    brand = validate_optional_asset_ids(input_configuration, "brand_asset_ids")
    return role_labelled_assets(
        ("white_background_product", white_background),
        ("product_detail", detail),
        ("package_reference", package),
        ("scene_reference", scene),
        ("brand_reference", brand),
    )


def _amazon_prompt_input(
    job_configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> dict[str, Any]:
    """Compile only the explicit Amazon prompt whitelist."""

    listing_title = optional_string(job_configuration, "listing_title")
    bullet_points = optional_string_list(job_configuration, "bullet_points")
    product_information = [
        value for value in (listing_title, *bullet_points) if value
    ]
    return compact_prompt_input(
        {
            "marketplace": optional_string(
                job_configuration,
                "marketplace",
                default=AMAZON_DEFAULT_MARKETPLACE,
            ),
            "product_name": optional_string(job_configuration, "product_name"),
            "product_information": product_information,
            "color_palette": optional_string_list(
                job_configuration, "brand_colors"
            ),
            "language": optional_string(
                job_configuration, "language", default="en-US"
            ),
            "composition": spec.group,
            "image_count": 1,
        }
    )


def _aspect_ratio(width: int, height: int) -> str:
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _required_item_key(configuration: Mapping[str, Any]) -> str:
    value = configuration.get("item_key")
    if not isinstance(value, str) or not value.strip():
        raise AdapterValidationError(
            "AMAZON_ITEM_KEY_MISSING",
            "Amazon item configuration requires item_key.",
        )
    return value.strip()


def _validate_contact_sheet_semantics(configuration: Mapping[str, Any]) -> None:
    if configuration.get("contact_sheet") is True:
        raise AdapterValidationError(
            "AMAZON_CONTACT_SHEET_NOT_DELIVERABLE",
            "Contact sheets cannot be counted among the 21 Amazon deliverables.",
        )


def _validate_group_semantics(
    configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> None:
    value = configuration.get("group")
    if value is None:
        return
    if str(value).strip().lower() != spec.group:
        raise AdapterValidationError(
            "AMAZON_ITEM_GROUP_MISMATCH",
            f"{spec.item_key} belongs to group {spec.group}.",
        )


def _validate_requested_dimensions(
    configuration: Mapping[str, Any],
    spec: AmazonItemSpec,
) -> None:
    width, height = _requested_dimensions(configuration)
    if width is None or height is None:
        raise AdapterValidationError(
            "AMAZON_TARGET_SIZE_MISSING",
            f"{spec.item_key} requires an explicit target size.",
        )
    if (width, height) != (spec.width, spec.height):
        raise AdapterValidationError(
            "AMAZON_TARGET_SIZE_MISMATCH",
            (
                f"{spec.item_key} requires {spec.width}x{spec.height}, got "
                f"{width}x{height}."
            ),
        )


def _requested_dimensions(
    configuration: Mapping[str, Any],
) -> tuple[int | None, int | None]:
    width = configuration.get("target_width")
    height = configuration.get("target_height")
    target_size = configuration.get("target_size")
    if isinstance(target_size, Mapping):
        width = target_size.get("width", width)
        height = target_size.get("height", height)
    elif isinstance(target_size, str) and "x" in target_size.lower():
        raw_width, raw_height = target_size.lower().split("x", maxsplit=1)
        width, height = raw_width.strip(), raw_height.strip()
    return _positive_int_or_none(width), _positive_int_or_none(height)


def _positive_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed > 0 else None
