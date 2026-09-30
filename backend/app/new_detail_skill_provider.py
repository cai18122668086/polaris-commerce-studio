"""Shared adapters for the new domestic and cross-border detail skills.

The adapters in this module are deliberately registration-only building blocks:
they validate the frozen skill source on every provider call, attach a canonical
planner/prompt contract, and delegate the actual provider work.  They do not
change the existing ``detail_pack`` confirmation state machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from app.provider import Provider, ProviderOutcome, ProviderRequest, ProviderResult
from app.skill_runtime import (
    SkillManifestRegistry,
    SkillRuntimeError,
)

DETAIL_PACK_OPERATION = "detail_pack"
SKILL_ADAPTER_CONFIGURATION_KEY = "new_skill_adapter"
PLANNER_CONTRACT_VERSION = "new-detail-planner-v1"


class ManifestValidator(Protocol):
    """Minimal source-integrity boundary used by the adapters."""

    def validate(self, skill_id: str) -> str: ...


class BundledSkillManifestValidator:
    """Validate bundled manifests and source trees without invoking a provider."""

    def __init__(
        self,
        registry: SkillManifestRegistry | None = None,
        *,
        source_roots: Mapping[str, Path] | None = None,
    ) -> None:
        self.registry = registry or SkillManifestRegistry.bundled()
        self.source_roots = dict(source_roots or {})

    def validate(self, skill_id: str) -> str:
        source_root = self.source_roots.get(skill_id)
        if source_root is None:
            source_root = (
                Path(__file__).resolve().parents[1] / "skill_sources" / skill_id
            )
        return self.registry.verify_source(skill_id, source_root)


class AdapterValidationError(ValueError):
    """Fail-closed request validation error with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DetailSkillRoute:
    skill_id: str
    market_region: str
    configure_prompt: Callable[[Mapping[str, Any]], dict[str, Any]]


class NewDetailSkillProvider:
    """Manifest-gated adapter for one newly installed detail skill.

    ``operation`` stays ``detail_pack`` so the durable job model can be reused.
    A future router only needs to select this adapter by ``market_region``.
    """

    def __init__(
        self,
        delegate: Provider,
        route: DetailSkillRoute,
        *,
        manifest_validator: ManifestValidator | None = None,
    ) -> None:
        self.delegate = delegate
        self.route = route
        self.manifest_validator = (
            manifest_validator or BundledSkillManifestValidator()
        )
        self.name = delegate.name
        self.model = delegate.model
        self.pricing_version = delegate.pricing_version

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            # Integrity is checked on every call and before the delegate can run.
            content_hash = self.manifest_validator.validate(self.route.skill_id)
            routed_request = self.prepare_request(request, content_hash=content_hash)
        except SkillRuntimeError as exc:
            return rejected_result(self, exc.code, str(exc))
        except AdapterValidationError as exc:
            return rejected_result(self, exc.code, str(exc))
        return await self.delegate.execute(routed_request)

    def prepare_request(
        self,
        request: ProviderRequest,
        *,
        content_hash: str,
    ) -> ProviderRequest:
        if request.operation != DETAIL_PACK_OPERATION:
            raise AdapterValidationError(
                "OPERATION_NOT_SUPPORTED",
                f"{self.route.skill_id} only accepts {DETAIL_PACK_OPERATION}.",
            )
        job_configuration = job_configuration_from(request.configuration)
        market_region = normalized_text(job_configuration.get("market_region"))
        if market_region != self.route.market_region:
            raise AdapterValidationError(
                "DETAIL_MARKET_REGION_MISMATCH",
                (
                    f"{self.route.skill_id} requires market_region="
                    f"{self.route.market_region}."
                ),
            )
        prompt_configuration = self.route.configure_prompt(job_configuration)
        adapter_configuration = {
            "schema_version": PLANNER_CONTRACT_VERSION,
            "skill_id": self.route.skill_id,
            "skill_content_hash": content_hash,
            "market_region": self.route.market_region,
            "planning": {
                "required": True,
                "persist_validated_plan": True,
                "auto_confirm_after_validation": True,
                "structure_repair_limit": 1,
                "changes_existing_confirmation_gate": False,
            },
            "prompt": prompt_configuration,
        }
        return replace(
            request,
            configuration={
                **request.configuration,
                SKILL_ADAPTER_CONFIGURATION_KEY: adapter_configuration,
            },
        )


def job_configuration_from(configuration: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read durable coordinator configuration while supporting direct unit calls."""

    nested = configuration.get("job")
    if nested is None:
        return configuration
    if not isinstance(nested, Mapping):
        raise AdapterValidationError(
            "JOB_CONFIGURATION_INVALID",
            "Provider request job configuration must be an object.",
        )
    settings = nested.get("settings")
    if settings is None:
        return nested
    if not isinstance(settings, Mapping):
        raise AdapterValidationError(
            "JOB_CONFIGURATION_INVALID",
            "Provider request job settings must be an object.",
        )
    return settings


def normalized_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def requested_page_count(configuration: Mapping[str, Any], default: int = 8) -> int:
    value = configuration.get("page_count", default)
    if type(value) is not int or not 1 <= value <= 12:
        raise AdapterValidationError(
            "DETAIL_PAGE_COUNT_INVALID",
            "Detail page_count must be an integer from 1 to 12.",
        )
    return value


def requested_language(configuration: Mapping[str, Any], default: str) -> str:
    value = configuration.get("language")
    if value is None:
        return default
    language = str(value).strip()
    if not language:
        raise AdapterValidationError(
            "DETAIL_LANGUAGE_INVALID",
            "Detail language cannot be empty.",
        )
    return language


def rejected_result(
    provider: Provider,
    error_code: str,
    error_message: str,
) -> ProviderResult:
    """Return a durable failure without fabricating an output artifact."""

    return ProviderResult(
        outcome=ProviderOutcome.FAILED,
        error_code=error_code,
        error_message=error_message,
        usage_reported=False,
        estimated_cost_micros=None,
        actual_cost_micros=None,
        retryable=False,
        provider_name=provider.name,
        model_name=provider.model,
        pricing_version=provider.pricing_version,
    )
