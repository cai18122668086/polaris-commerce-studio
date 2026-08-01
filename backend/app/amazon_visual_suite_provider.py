"""Independent manifest-gated adapter for the Amazon 21-image suite."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
from app.provider import Provider, ProviderOutcome, ProviderRequest, ProviderResult
from app.skill_runtime import SkillRuntimeError

AMAZON_VISUAL_SUITE_OPERATION = "amazon_visual_suite"
AMAZON_VISUAL_SUITE_SKILL_ID = "xinghe-amazon-visual-suite"
AMAZON_ADAPTER_CONTRACT_VERSION = "amazon-visual-suite-adapter-v1"
AMAZON_EXPECTED_ITEM_COUNT = 21


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
            routed_request, spec = self.prepare_request(
                request,
                content_hash=content_hash,
            )
        except SkillRuntimeError as exc:
            return rejected_result(self, exc.code, str(exc))
        except AdapterValidationError as exc:
            return rejected_result(self, exc.code, str(exc))

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

        adapter_configuration = {
            "schema_version": AMAZON_ADAPTER_CONTRACT_VERSION,
            "skill_id": AMAZON_VISUAL_SUITE_SKILL_ID,
            "skill_content_hash": content_hash,
            "expected_item_count": AMAZON_EXPECTED_ITEM_COUNT,
            "canonical_item_keys": AMAZON_ITEM_KEYS,
            "item": {
                "item_key": spec.item_key,
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
