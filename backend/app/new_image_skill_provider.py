"""Fail-closed adapter primitives for the new single-image Skill providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from app.provider import Provider, ProviderOutcome, ProviderRequest, ProviderResult


class ManifestValidator(Protocol):
    """Validate the installed source/manifest pair for one Skill execution."""

    def __call__(self, skill_id: str) -> object | None: ...


class NewImageSkillContractError(ValueError):
    """A redaction-safe request contract violation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NewImageSkillProvider:
    """Validate a single-image operation before delegating real generation.

    The adapter deliberately owns no network or storage implementation. A caller must
    inject both a Provider-compatible delegate and a manifest validator. Omitting the
    validator fails closed, which prevents a later registration from accidentally
    bypassing source integrity checks.
    """

    operation: str
    skill_id: str

    def __init__(
        self,
        delegate: Provider,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        self.delegate = delegate
        self.manifest_validator = manifest_validator
        self.name = delegate.name
        self.model = delegate.model
        self.pricing_version = delegate.pricing_version

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if request.operation != self.operation:
            return self._rejection(
                "OPERATION_NOT_SUPPORTED",
                f"Expected operation {self.operation}.",
            )

        try:
            input_config, settings, item_config = configuration_sections(
                request.configuration
            )
            self.validate_configuration(input_config, settings, item_config)
        except NewImageSkillContractError as exc:
            return self._rejection(exc.code, str(exc))

        if self.manifest_validator is None:
            return self._rejection(
                "SKILL_MANIFEST_VALIDATOR_REQUIRED",
                "A Skill manifest validator is required before provider execution.",
            )
        try:
            validation = self.manifest_validator(self.skill_id)
            if validation is False:
                raise NewImageSkillContractError(
                    "SKILL_MANIFEST_VALIDATION_FAILED",
                    "The Skill manifest validator rejected the installed source.",
                )
        except NewImageSkillContractError as exc:
            return self._rejection(exc.code, str(exc))
        except Exception as exc:
            return self._rejection(
                "SKILL_MANIFEST_VALIDATION_FAILED",
                "Skill manifest validation failed "
                f"({type(exc).__name__}).",
            )

        result = await self.delegate.execute(request)
        if result.outcome != ProviderOutcome.SUCCEEDED:
            return result
        if not _has_independent_image_artifact(result):
            return self._rejection(
                "GENERATED_IMAGE_ARTIFACT_REQUIRED",
                "A successful generation must contain one real image artifact.",
                result=result,
            )
        return result

    def validate_configuration(
        self,
        input_config: Mapping[str, Any],
        settings: Mapping[str, Any],
        item_config: Mapping[str, Any],
    ) -> None:
        """Validate the operation-specific request contract."""

        raise NotImplementedError

    def _rejection(
        self,
        code: str,
        message: str,
        *,
        result: ProviderResult | None = None,
    ) -> ProviderResult:
        return ProviderResult(
            outcome=ProviderOutcome.FAILED,
            provider_request_id=(result.provider_request_id if result else None),
            error_code=code,
            error_message=message,
            usage_reported=(result.usage_reported if result else True),
            raw_usage=(result.raw_usage if result else _zero_rejected_usage(code)),
            estimated_cost_micros=(result.estimated_cost_micros if result else 0),
            actual_cost_micros=(result.actual_cost_micros if result else 0),
            retryable=False,
            http_status=(result.http_status if result else None),
            provider_name=(result.provider_name if result else self.name),
            model_name=(result.model_name if result else self.model),
            pricing_version=(
                result.pricing_version if result else self.pricing_version
            ),
        )


def configuration_sections(
    configuration: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Extract the durable ExecutionCoordinator configuration envelope."""

    job = require_mapping(configuration, "job", code="JOB_CONFIGURATION_REQUIRED")
    input_config = require_mapping(job, "input", code="JOB_INPUT_REQUIRED")
    settings = require_mapping(job, "settings", code="JOB_SETTINGS_REQUIRED")
    item_value = configuration.get("item", {})
    if not isinstance(item_value, Mapping):
        raise NewImageSkillContractError(
            "ITEM_CONFIGURATION_INVALID",
            "item configuration must be an object.",
        )
    return input_config, settings, item_value


def require_mapping(
    source: Mapping[str, Any],
    key: str,
    *,
    code: str,
) -> Mapping[str, Any]:
    value = source.get(key)
    if not isinstance(value, Mapping):
        raise NewImageSkillContractError(code, f"{key} must be an object.")
    return value


def require_asset_ids(source: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = source.get(key)
    if not isinstance(value, list) or not value:
        raise NewImageSkillContractError(
            "REQUIRED_IMAGE_INPUT_MISSING",
            f"{key} must contain at least one image asset id.",
        )
    if any(not isinstance(asset_id, str) or not asset_id.strip() for asset_id in value):
        raise NewImageSkillContractError(
            "IMAGE_INPUT_INVALID",
            f"{key} must contain only non-empty image asset ids.",
        )
    if len(value) != len(set(value)):
        raise NewImageSkillContractError(
            "IMAGE_INPUT_INVALID",
            f"{key} must not contain duplicate image asset ids.",
        )
    return tuple(value)


def validate_optional_asset_ids(source: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = source.get(key, [])
    if not isinstance(value, list):
        raise NewImageSkillContractError(
            "IMAGE_INPUT_INVALID",
            f"{key} must be an array of image asset ids.",
        )
    if any(not isinstance(asset_id, str) or not asset_id.strip() for asset_id in value):
        raise NewImageSkillContractError(
            "IMAGE_INPUT_INVALID",
            f"{key} must contain only non-empty image asset ids.",
        )
    if len(value) != len(set(value)):
        raise NewImageSkillContractError(
            "IMAGE_INPUT_INVALID",
            f"{key} must not contain duplicate image asset ids.",
        )
    return tuple(value)


def require_image_count(settings: Mapping[str, Any]) -> int:
    value = settings.get("image_count")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise NewImageSkillContractError(
            "IMAGE_COUNT_OUT_OF_RANGE",
            "image_count must be between 1 and 4.",
        )
    return value


def require_non_empty_string(
    source: Mapping[str, Any],
    key: str,
    *,
    code: str,
) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NewImageSkillContractError(code, f"{key} is required.")
    return value.strip()


def _has_independent_image_artifact(result: ProviderResult) -> bool:
    artifact = result.persisted_artifact or result.artifact
    if artifact is None:
        return False
    if not artifact.content_type.lower().startswith("image/"):
        return False
    if (
        result.persisted_artifact is not None
        and result.persisted_artifact.byte_size <= 0
    ):
        return False
    raw_usage = result.raw_usage
    if raw_usage.get("placeholder") is True or raw_usage.get("contact_sheet") is True:
        return False
    artifact_kind = raw_usage.get("artifact_kind")
    return artifact_kind not in {"placeholder", "contact_sheet", "prompt", "plan"}


def _zero_rejected_usage(code: str) -> dict[str, Any]:
    return {
        "provider_type": "adapter",
        "called": False,
        "runtime_rejected": True,
        "reason": code,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "input_images": 0,
        "output_images": 0,
        "request_count": 0,
    }
