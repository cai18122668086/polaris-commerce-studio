"""Fail-closed Xinghe delegate for one durable single-image JobItem.

Only the canonical new_skill_adapter envelope may influence the prompt. Skill
integrity, durable scope, and source assets are checked before one gateway call.
Provider payloads, prompts, credentials, and source bytes are never returned as
diagnostics.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from io import BytesIO
from typing import Any, Protocol, cast

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    AssetLifecycleStatus,
    AssetMediaKind,
    AttemptStatus,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    WorkspaceStatus,
)
from .models import (
    AssetRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobRecord,
    WorkspaceRecord,
)
from .provider import ProviderArtifact, ProviderOutcome, ProviderRequest, ProviderResult
from .skill_protocol import (
    SkillProtocol,
    SkillProtocolError,
    load_skill_protocol,
)
from .storage import ImageStorage
from .xinghe_agent import (
    ImageCallResult,
    ImageEditRequest,
    SourceImage,
    XingheGateway,
    normalize_usage,
)

SINGLE_IMAGE_ADAPTER_CONFIGURATION_KEY = "new_skill_adapter"
SINGLE_IMAGE_ADAPTER_SCHEMA_VERSION = "single-image-skill-adapter-v1"
SINGLE_IMAGE_PROMPT_SCHEMA_VERSION = "single-image-prompt-v1"

DEFAULT_ALLOWED_PROMPT_FIELDS = frozenset(
    {
        "aspect_ratio",
        "background",
        "brand_requirements",
        "camera_angle",
        "color_palette",
        "composition",
        "copy_requirements",
        "creative_direction",
        "image_count",
        "language",
        "lighting",
        "marketplace",
        "material",
        "negative_constraints",
        "platform_code",
        "product_category",
        "product_information",
        "product_name",
        "reference_guidance",
        "scene",
        "style",
        "subject",
        "target_color",
        "task_type",
        "usage_scenario",
    }
)
_ALLOWED_ENVELOPE_KEYS = frozenset(
    {
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
)
_ALLOWED_SOURCE_KEYS = frozenset({"asset_id", "role"})
_ALLOWED_TARGET_KEYS = frozenset(
    {"width", "height", "aspect_ratio", "quality", "output_format", "fit"}
)
_ALLOWED_QUALITIES = frozenset({"low", "medium", "high", "auto"})
_ALLOWED_OUTPUT_FORMATS = frozenset({"jpeg", "png", "webp"})
_ALLOWED_FITS = frozenset({"cover", "contain", "pad"})
_IMAGE_CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_OUTPUT_FORMATS = {
    "jpeg": ("JPEG", "image/jpeg", ".jpg"),
    "png": ("PNG", "image/png", ".png"),
    "webp": ("WEBP", "image/webp", ".webp"),
}
_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_ITEM_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_ERROR_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|bearer|password|secret|token)", re.IGNORECASE
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)
_MAX_SOURCE_COUNT = 8
_MAX_TARGET_DIMENSION = 8192
_MAX_TARGET_PIXELS = 64_000_000
_MAX_PROMPT_FIELDS = 32
_MAX_PROMPT_STRING_LENGTH = 2_000
_MAX_PROMPT_LIST_LENGTH = 32
_MAX_COMPILED_PROMPT_BYTES = 256 * 1024
_MAX_SOURCE_PIXELS = 100_000_000


class ManifestValidator(Protocol):
    def __call__(self, skill_id: str) -> object: ...


class SingleImageProviderError(RuntimeError):
    """A stable, redaction-safe failure returned before a gateway call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SourceAssetSpec:
    asset_id: str
    role: str
    ordinal: int


@dataclass(frozen=True)
class TargetSpec:
    width: int | None
    height: int | None
    aspect_ratio: str
    quality: str
    output_format: str
    fit: str

    @property
    def dimensions(self) -> tuple[int, int]:
        if self.width is None or self.height is None:
            raise SingleImageProviderError(
                "TARGET_CONFIGURATION_INVALID",
                "The delivery target has not been resolved.",
            )
        return self.width, self.height

    @property
    def size(self) -> str:
        width, height = self.dimensions
        return f"{width}x{height}"


@dataclass(frozen=True)
class SingleImageEnvelope:
    skill_id: str
    skill_content_hash: str
    operation: str
    item_key: str
    item_ordinal: int
    source_assets: tuple[SourceAssetSpec, ...]
    target: TargetSpec
    prompt_input: dict[str, Any]


class XingheSingleImageProvider:
    """Independent real-provider delegate for one single-image JobItem.

    This class performs no retry. Every invocation that passes all local gates
    calls gateway.edit exactly once.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        *,
        storage: ImageStorage,
        operation: str,
        skill_id: str,
        manifest_validator: ManifestValidator | Callable[[str], object],
        max_concurrency: int = 2,
        allowed_prompt_fields: frozenset[str] | None = None,
    ) -> None:
        if not operation or not skill_id:
            raise ValueError("operation and skill_id are required.")
        if isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 8:
            raise ValueError("max_concurrency must be between 1 and 8.")
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.operation = operation
        self.skill_id = skill_id
        self.manifest_validator = manifest_validator
        self.allowed_prompt_fields = (
            allowed_prompt_fields
            if allowed_prompt_fields is not None
            else DEFAULT_ALLOWED_PROMPT_FIELDS
        )
        if not self.allowed_prompt_fields or any(
            not isinstance(field, str)
            or not _IDENTIFIER_PATTERN.fullmatch(field)
            or _SENSITIVE_FIELD_PATTERN.search(field)
            for field in self.allowed_prompt_fields
        ):
            raise ValueError("allowed_prompt_fields contains an unsafe field name.")
        self.name = gateway.provider_name
        self.model = gateway.image_model
        self.pricing_version = gateway.pricing_version
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            envelope = self._parse_envelope(request)
            source_content_hash = self._verify_manifest(envelope)
            protocol = self._load_protocol(source_content_hash)
            source_records = self._authorize_durable_records(request, envelope)
            sources = await self._load_sources(source_records)
            envelope = self._resolve_follow_reference_target(envelope, sources)
            prompt = self._compile_prompt(envelope, protocol)
        except SingleImageProviderError as exc:
            return self._rejection(exc.code, str(exc))
        except Exception as exc:
            return self._rejection(
                "SINGLE_IMAGE_AUTHORIZATION_FAILED",
                f"Single-image authorization failed ({type(exc).__name__}).",
            )

        image_request = ImageEditRequest(
            workspace_id=request.workspace_id,
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            attempt_id=request.attempt_id,
            page_number=envelope.item_ordinal,
            group_key=envelope.item_key,
            sources=sources,
            prompt=prompt,
            quality=envelope.target.quality,
            idempotency_key=request.idempotency_key,
            size=_provider_generation_size(
                envelope.target,
                skill_id=envelope.skill_id,
            ),
            output_format="jpeg",
            preserve_provider_artifact=True,
        )
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        started_at = asyncio.get_running_loop().time()
        async with self._semaphore:
            try:
                call_result = await self.gateway.edit(image_request)
            except Exception as exc:
                elapsed = asyncio.get_running_loop().time() - started_at
                return ProviderResult(
                    outcome=ProviderOutcome.FAILED,
                    error_code="IMAGE_PROVIDER_FAILED",
                    error_message=f"Image provider failed ({type(exc).__name__}).",
                    usage_reported=False,
                    raw_usage=self._safe_usage(
                        None,
                        source_count=len(sources),
                        target=envelope.target,
                        prompt_sha256=prompt_sha256,
                        prompt_length=len(prompt),
                        protocol_sha256=protocol.sha256,
                        protocol_length=protocol.byte_length,
                        measured_latency=elapsed,
                    ),
                    estimated_cost_micros=None,
                    actual_cost_micros=None,
                    retryable=False,
                    provider_name=self.name,
                    model_name=self.model,
                    pricing_version=self.pricing_version,
                )
        elapsed = asyncio.get_running_loop().time() - started_at
        return self._finalize_result(
            call_result,
            envelope=envelope,
            source_count=len(sources),
            prompt_sha256=prompt_sha256,
            prompt_length=len(prompt),
            protocol_sha256=protocol.sha256,
            protocol_length=protocol.byte_length,
            measured_latency=elapsed,
        )

    def _parse_envelope(self, request: ProviderRequest) -> SingleImageEnvelope:
        if request.operation != self.operation:
            raise SingleImageProviderError(
                "OPERATION_NOT_SUPPORTED",
                "The single-image delegate does not support this operation.",
            )
        envelope_value = request.configuration.get(
            SINGLE_IMAGE_ADAPTER_CONFIGURATION_KEY
        )
        envelope = _require_mapping(
            envelope_value,
            "SINGLE_IMAGE_ENVELOPE_INVALID",
            "The single-image adapter envelope is required.",
        )
        _require_exact_keys(
            envelope,
            allowed=_ALLOWED_ENVELOPE_KEYS,
            required=_ALLOWED_ENVELOPE_KEYS,
            code="SINGLE_IMAGE_ENVELOPE_INVALID",
        )
        if envelope["schema_version"] != SINGLE_IMAGE_ADAPTER_SCHEMA_VERSION:
            raise SingleImageProviderError(
                "SINGLE_IMAGE_SCHEMA_UNSUPPORTED",
                "The single-image adapter schema is not supported.",
            )
        skill_id = _require_identifier(envelope["skill_id"], "skill_id")
        if skill_id != self.skill_id:
            raise SingleImageProviderError(
                "SKILL_ID_MISMATCH",
                "The adapter Skill does not match the registered delegate.",
            )
        content_hash = _require_hash(envelope["skill_content_hash"])
        operation = _require_identifier(envelope["operation"], "operation")
        if operation != request.operation:
            raise SingleImageProviderError(
                "OPERATION_MISMATCH",
                "The adapter operation does not match the provider request.",
            )
        item_key = _require_item_key(envelope["item_key"])
        item_ordinal = _require_nonnegative_int(
            envelope["item_ordinal"], "item_ordinal"
        )
        return SingleImageEnvelope(
            skill_id=skill_id,
            skill_content_hash=content_hash,
            operation=operation,
            item_key=item_key,
            item_ordinal=item_ordinal,
            source_assets=self._parse_source_assets(envelope["source_assets"]),
            target=self._parse_target(envelope["target"]),
            prompt_input=self._parse_prompt_input(envelope["prompt_input"]),
        )

    def _parse_source_assets(self, value: object) -> tuple[SourceAssetSpec, ...]:
        if not isinstance(value, list) or not 1 <= len(value) <= _MAX_SOURCE_COUNT:
            raise SingleImageProviderError(
                "SOURCE_ASSETS_INVALID",
                "The adapter must contain a bounded non-empty source asset list.",
            )
        specs: list[SourceAssetSpec] = []
        seen: set[str] = set()
        role_ordinals: dict[str, int] = {}
        for entry_value in value:
            entry = _require_mapping(
                entry_value,
                "SOURCE_ASSETS_INVALID",
                "Each source asset must be an object.",
            )
            _require_exact_keys(
                entry,
                allowed=_ALLOWED_SOURCE_KEYS,
                required=_ALLOWED_SOURCE_KEYS,
                code="SOURCE_ASSETS_INVALID",
            )
            asset_id = _require_identifier(entry["asset_id"], "asset_id")
            role = _require_identifier(entry["role"], "role")
            if asset_id in seen:
                raise SingleImageProviderError(
                    "SOURCE_ASSET_DUPLICATE",
                    "A source asset may appear only once per JobItem.",
                )
            seen.add(asset_id)
            ordinal = role_ordinals.get(role, 0)
            role_ordinals[role] = ordinal + 1
            specs.append(
                SourceAssetSpec(asset_id=asset_id, role=role, ordinal=ordinal)
            )
        return tuple(specs)

    def _parse_target(self, value: object) -> TargetSpec:
        target = _require_mapping(
            value,
            "TARGET_CONFIGURATION_INVALID",
            "The target configuration must be an object.",
        )
        _require_exact_keys(
            target,
            allowed=_ALLOWED_TARGET_KEYS,
            required=_ALLOWED_TARGET_KEYS,
            code="TARGET_CONFIGURATION_INVALID",
        )
        quality = _require_choice(target["quality"], _ALLOWED_QUALITIES, "quality")
        output_format = _require_choice(
            target["output_format"], _ALLOWED_OUTPUT_FORMATS, "output_format"
        )
        fit = _require_choice(target["fit"], _ALLOWED_FITS, "fit")
        if target["aspect_ratio"] == "follow-reference":
            if target["width"] is not None or target["height"] is not None:
                raise SingleImageProviderError(
                    "TARGET_CONFIGURATION_INVALID",
                    "A follow-reference target cannot declare fixed dimensions.",
                )
            if fit != "contain":
                raise SingleImageProviderError(
                    "TARGET_CONFIGURATION_INVALID",
                    "A follow-reference target must preserve composition.",
                )
            return TargetSpec(
                width=None,
                height=None,
                aspect_ratio="follow-reference",
                quality=quality,
                output_format=output_format,
                fit=fit,
            )
        width = _require_positive_int(target["width"], "width")
        height = _require_positive_int(target["height"], "height")
        _validate_target_dimensions(width, height)
        return TargetSpec(
            width=width,
            height=height,
            aspect_ratio=_require_aspect_ratio(
                target["aspect_ratio"], width, height
            ),
            quality=quality,
            output_format=output_format,
            fit=fit,
        )

    def _resolve_follow_reference_target(
        self,
        envelope: SingleImageEnvelope,
        sources: tuple[SourceImage, ...],
    ) -> SingleImageEnvelope:
        if envelope.target.aspect_ratio != "follow-reference":
            return envelope
        for spec, source in zip(envelope.source_assets, sources, strict=True):
            if spec.role != "style_reference":
                continue
            width, height, _ = _inspect_image(source.payload)
            _validate_target_dimensions(width, height)
            divisor = math.gcd(width, height)
            return replace(
                envelope,
                target=TargetSpec(
                    width=width,
                    height=height,
                    aspect_ratio=f"{width // divisor}:{height // divisor}",
                    quality=envelope.target.quality,
                    output_format=envelope.target.output_format,
                    fit="contain",
                ),
            )
        raise SingleImageProviderError(
            "FOLLOW_REFERENCE_SOURCE_REQUIRED",
            "A follow-reference target requires a readable style reference.",
        )

    def _parse_prompt_input(self, value: object) -> dict[str, Any]:
        prompt_input = _require_mapping(
            value,
            "PROMPT_INPUT_INVALID",
            "The prompt input must be an object.",
        )
        if len(prompt_input) > _MAX_PROMPT_FIELDS:
            raise SingleImageProviderError(
                "PROMPT_INPUT_INVALID", "The prompt input contains too many fields."
            )
        unknown = set(prompt_input) - self.allowed_prompt_fields
        if unknown or any(
            not isinstance(key, str) or _SENSITIVE_FIELD_PATTERN.search(key)
            for key in prompt_input
        ):
            raise SingleImageProviderError(
                "PROMPT_INPUT_FIELD_NOT_ALLOWED",
                "The prompt input contains a field that is not allowed.",
            )
        return {
            key: _normalize_prompt_value(prompt_input[key])
            for key in sorted(prompt_input)
        }


    def _verify_manifest(self, envelope: SingleImageEnvelope) -> str:
        try:
            validate_method = getattr(self.manifest_validator, "validate", None)
            if callable(validate_method):
                result = validate_method(self.skill_id)
            else:
                result = self.manifest_validator(self.skill_id)
        except Exception as exc:
            raise SingleImageProviderError(
                "SKILL_MANIFEST_VALIDATION_FAILED",
                f"Skill manifest validation failed ({type(exc).__name__}).",
            ) from None
        content_hash = _manifest_content_hash(result)
        if content_hash != envelope.skill_content_hash:
            raise SingleImageProviderError(
                "SKILL_CONTENT_HASH_MISMATCH",
                "The adapter Skill content hash does not match the installed source.",
            )
        return content_hash

    def _load_protocol(self, source_content_hash: str) -> SkillProtocol:
        try:
            return load_skill_protocol(
                self.skill_id,
                source_content_hash=source_content_hash,
            )
        except SkillProtocolError as exc:
            raise SingleImageProviderError(exc.code, str(exc)) from None

    def _authorize_durable_records(
        self,
        request: ProviderRequest,
        envelope: SingleImageEnvelope,
    ) -> tuple[tuple[SourceAssetSpec, AssetRecord], ...]:
        with self.session_factory() as session:
            workspace = session.get(WorkspaceRecord, request.workspace_id)
            job = session.get(JobRecord, request.job_id)
            item = session.get(JobItemRecord, request.job_item_id)
            attempt = session.get(JobAttemptRecord, request.attempt_id)
            if workspace is None or job is None or item is None or attempt is None:
                raise SingleImageProviderError(
                    "DURABLE_REQUEST_NOT_FOUND",
                    "The durable single-image request is incomplete.",
                )
            if (
                job.workspace_id != workspace.id
                or item.workspace_id != workspace.id
                or attempt.workspace_id != workspace.id
                or item.job_id != job.id
                or attempt.job_id != job.id
                or attempt.job_item_id != item.id
            ):
                raise SingleImageProviderError(
                    "WORKSPACE_SCOPE_MISMATCH",
                    "The request is outside its durable workspace scope.",
                )
            if (
                workspace.status != WorkspaceStatus.ACTIVE.value
                or workspace.deleted_at is not None
                or job.status != JobStatus.PROCESSING.value
                or item.status != JobItemStatus.RUNNING.value
                or attempt.status != AttemptStatus.RUNNING.value
            ):
                raise SingleImageProviderError(
                    "SINGLE_IMAGE_CALL_NOT_AUTHORIZED",
                    "The durable records do not authorize a provider call.",
                )
            if (
                job.type != request.operation
                or attempt.operation != request.operation
                or attempt.provider_idempotency_key != request.idempotency_key
            ):
                raise SingleImageProviderError(
                    "DURABLE_REQUEST_MISMATCH",
                    "The durable operation or idempotency contract does not match.",
                )
            if (
                item.item_key != envelope.item_key
                or item.ordinal != envelope.item_ordinal
            ):
                raise SingleImageProviderError(
                    "ITEM_CONTRACT_MISMATCH",
                    "The adapter item does not match the durable JobItem.",
                )

            durable_inputs = tuple(
                session.scalars(
                    select(JobAssetRecord)
                    .where(
                        JobAssetRecord.workspace_id == workspace.id,
                        JobAssetRecord.job_id == job.id,
                        JobAssetRecord.direction == JobAssetDirection.INPUT.value,
                        or_(
                            JobAssetRecord.job_item_id.is_(None),
                            JobAssetRecord.job_item_id == item.id,
                        ),
                    )
                    .order_by(JobAssetRecord.role, JobAssetRecord.ordinal)
                )
            )
            durable_inventory = sorted(
                (binding.asset_id, binding.role, binding.ordinal)
                for binding in durable_inputs
            )
            envelope_inventory = sorted(
                (spec.asset_id, spec.role, spec.ordinal)
                for spec in envelope.source_assets
            )
            if durable_inventory != envelope_inventory:
                raise SingleImageProviderError(
                    "INPUT_ASSET_AUTHORIZATION_MISMATCH",
                    "The adapter source inventory does not match durable Job inputs.",
                )

            records: list[tuple[SourceAssetSpec, AssetRecord]] = []
            for spec in envelope.source_assets:
                asset = session.get(AssetRecord, spec.asset_id)
                if asset is None or asset.workspace_id != workspace.id:
                    raise SingleImageProviderError(
                        "INPUT_ASSET_NOT_FOUND",
                        "A source asset is unavailable in this workspace.",
                    )
                if asset.media_kind != AssetMediaKind.IMAGE.value:
                    raise SingleImageProviderError(
                        "INPUT_ASSET_NOT_IMAGE",
                        "Every source asset must be an image.",
                    )
                if (
                    asset.lifecycle_status != AssetLifecycleStatus.READY.value
                    or asset.deleted_at is not None
                ):
                    raise SingleImageProviderError(
                        "INPUT_ASSET_NOT_READABLE",
                        "A source asset is not in a readable lifecycle state.",
                    )
                if (
                    asset.storage_provider != self.storage.provider_name
                    or asset.storage_bucket != self.storage.bucket_name
                ):
                    raise SingleImageProviderError(
                        "INPUT_ASSET_STORAGE_MISMATCH",
                        "A source asset is not available through configured storage.",
                    )
                session.expunge(asset)
                records.append((spec, asset))
            return tuple(records)

    async def _load_sources(
        self,
        records: tuple[tuple[SourceAssetSpec, AssetRecord], ...],
    ) -> tuple[SourceImage, ...]:
        sources: list[SourceImage] = []
        for spec, asset in records:
            try:
                payload = await self.storage.read_bytes(asset.object_key)
            except Exception as exc:
                raise SingleImageProviderError(
                    "INPUT_ASSET_READ_FAILED",
                    f"A source asset could not be read ({type(exc).__name__}).",
                ) from None
            if not isinstance(payload, bytes) or not payload:
                raise SingleImageProviderError(
                    "INPUT_ASSET_INTEGRITY_FAILED",
                    "A source asset failed its integrity check.",
                )
            digest = hashlib.sha256(payload).hexdigest()
            if len(payload) != asset.byte_size or digest != asset.sha256:
                raise SingleImageProviderError(
                    "INPUT_ASSET_INTEGRITY_FAILED",
                    "A source asset failed its integrity check.",
                )
            width, height, content_type = _inspect_image(payload)
            if (
                content_type != asset.content_type.lower()
                or (asset.width is not None and asset.width != width)
                or (asset.height is not None and asset.height != height)
            ):
                raise SingleImageProviderError(
                    "INPUT_ASSET_INTEGRITY_FAILED",
                    "A source asset failed its image metadata check.",
                )
            sources.append(
                SourceImage(
                    asset_id=asset.id,
                    group_key=spec.role,
                    filename=asset.original_filename,
                    content_type=asset.content_type,
                    sha256=asset.sha256,
                    payload=payload,
                )
            )
        return tuple(sources)

    def _compile_prompt(
        self,
        envelope: SingleImageEnvelope,
        protocol: SkillProtocol,
    ) -> str:
        prompt_contract = {
            "schema_version": SINGLE_IMAGE_PROMPT_SCHEMA_VERSION,
            "skill_id": envelope.skill_id,
            "operation": envelope.operation,
            "item": {"key": envelope.item_key, "ordinal": envelope.item_ordinal},
            "source_roles": [spec.role for spec in envelope.source_assets],
            "target": {
                "aspect_ratio": envelope.target.aspect_ratio,
                "fit": envelope.target.fit,
                "height": envelope.target.height,
                "output_format": envelope.target.output_format,
                "quality": envelope.target.quality,
                "width": envelope.target.width,
            },
            "instructions": envelope.prompt_input,
            "skill_protocol": protocol.prompt_payload(),
        }
        prompt = json.dumps(
            prompt_contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(prompt.encode("utf-8")) > _MAX_COMPILED_PROMPT_BYTES:
            raise SingleImageProviderError(
                "PROMPT_INPUT_INVALID",
                "The compiled prompt exceeds the local safety limit.",
            )
        return prompt

    def _finalize_result(
        self,
        call_result: object,
        *,
        envelope: SingleImageEnvelope,
        source_count: int,
        prompt_sha256: str,
        prompt_length: int,
        protocol_sha256: str,
        protocol_length: int,
        measured_latency: float,
    ) -> ProviderResult:
        if not isinstance(call_result, ImageCallResult):
            return self._rejection(
                "IMAGE_PROVIDER_RESPONSE_INVALID",
                "The image provider returned an invalid response type.",
                raw_usage=self._safe_usage(
                    None,
                    source_count=source_count,
                    target=envelope.target,
                    prompt_sha256=prompt_sha256,
                    prompt_length=prompt_length,
                    protocol_sha256=protocol_sha256,
                    protocol_length=protocol_length,
                    measured_latency=measured_latency,
                ),
            )
        raw_usage = self._safe_usage(
            call_result,
            source_count=source_count,
            target=envelope.target,
            prompt_sha256=prompt_sha256,
            prompt_length=prompt_length,
            protocol_sha256=protocol_sha256,
            protocol_length=protocol_length,
            measured_latency=measured_latency,
        )
        provider_request_id = _safe_request_id(call_result.provider_request_id)
        usage_reported = bool(raw_usage["reported"])
        estimated_cost_micros = _safe_cost(call_result.estimated_cost_micros)
        actual_cost_micros = _safe_cost(call_result.actual_cost_micros)
        http_status = _safe_http_status(call_result.http_status)
        if call_result.outcome != ProviderOutcome.SUCCEEDED:
            return ProviderResult(
                outcome=call_result.outcome,
                error_code=_safe_error_code(call_result.error_code),
                error_message="Image provider returned a controlled failure.",
                retryable=bool(call_result.retryable),
                provider_request_id=provider_request_id,
                usage_reported=usage_reported,
                raw_usage=raw_usage,
                estimated_cost_micros=estimated_cost_micros,
                actual_cost_micros=actual_cost_micros,
                http_status=http_status,
                provider_name=self.name,
                model_name=self.model,
                pricing_version=self.pricing_version,
            )
        if call_result.artifact is None:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                error_code="IMAGE_OUTPUT_ARTIFACT_MISSING",
                error_message="The image provider succeeded without an artifact.",
                retryable=False,
                provider_request_id=provider_request_id,
                usage_reported=usage_reported,
                raw_usage=raw_usage,
                estimated_cost_micros=estimated_cost_micros,
                actual_cost_micros=actual_cost_micros,
                http_status=http_status,
                provider_name=self.name,
                model_name=self.model,
                pricing_version=self.pricing_version,
            )
        try:
            artifact = _target_artifact(call_result.artifact, envelope.target)
        except Exception as exc:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                error_code="IMAGE_OUTPUT_INVALID",
                error_message=(
                    "The image output could not be validated "
                    f"({type(exc).__name__})."
                ),
                retryable=False,
                provider_request_id=provider_request_id,
                usage_reported=usage_reported,
                raw_usage=raw_usage,
                estimated_cost_micros=estimated_cost_micros,
                actual_cost_micros=actual_cost_micros,
                http_status=http_status,
                provider_name=self.name,
                model_name=self.model,
                pricing_version=self.pricing_version,
            )
        raw_usage["locally_resampled"] = artifact.locally_resampled
        raw_usage["provider_width"] = artifact.provider_width
        raw_usage["provider_height"] = artifact.provider_height
        raw_usage["output_images"] = 1
        raw_usage["artifact_kind"] = "image"
        raw_usage["perceptual_dhash"] = _perceptual_dhash(artifact.payload)
        return ProviderResult(
            outcome=ProviderOutcome.SUCCEEDED,
            artifact=artifact,
            retryable=False,
            provider_request_id=provider_request_id,
            usage_reported=usage_reported,
            raw_usage=raw_usage,
            estimated_cost_micros=estimated_cost_micros,
            actual_cost_micros=actual_cost_micros,
            http_status=http_status,
            provider_name=self.name,
            model_name=self.model,
            pricing_version=self.pricing_version,
        )
    def _safe_usage(
        self,
        call_result: ImageCallResult | None,
        *,
        source_count: int,
        target: TargetSpec,
        prompt_sha256: str,
        prompt_length: int,
        protocol_sha256: str,
        protocol_length: int,
        measured_latency: float,
    ) -> dict[str, Any]:
        normalized = normalize_usage(
            call_result.raw_usage if call_result is not None else None
        )
        if (
            call_result is not None
            and call_result.raw_usage is None
            and isinstance(call_result.normalized_usage, Mapping)
        ):
            normalized = {
                "reported": call_result.normalized_usage.get("reported") is True,
                "input_tokens": _safe_usage_integer(
                    call_result.normalized_usage.get("input_tokens")
                ),
                "output_tokens": _safe_usage_integer(
                    call_result.normalized_usage.get("output_tokens")
                ),
                "cached_tokens": _safe_usage_integer(
                    call_result.normalized_usage.get("cached_tokens")
                ),
                "total_tokens": _safe_usage_integer(
                    call_result.normalized_usage.get("total_tokens")
                ),
            }
        provider_latency = (
            call_result.api_latency_seconds if call_result is not None else None
        )
        return {
            "provider_type": self.name,
            "reported": bool(normalized["reported"]),
            "input_tokens": _safe_usage_integer(normalized.get("input_tokens")),
            "output_tokens": _safe_usage_integer(normalized.get("output_tokens")),
            "cached_tokens": _safe_usage_integer(normalized.get("cached_tokens")),
            "total_tokens": _safe_usage_integer(normalized.get("total_tokens")),
            "input_images": source_count,
            "output_images": 0,
            "request_count": 1,
            "source_count": source_count,
            "target_width": target.width,
            "target_height": target.height,
            "api_latency_seconds": _safe_latency(provider_latency, measured_latency),
            "prompt_sha256": prompt_sha256,
            "prompt_length": prompt_length,
            "skill_protocol_sha256": protocol_sha256,
            "skill_protocol_length": protocol_length,
        }

    def _rejection(
        self,
        code: str,
        message: str,
        *,
        raw_usage: dict[str, Any] | None = None,
    ) -> ProviderResult:
        return ProviderResult(
            outcome=ProviderOutcome.FAILED,
            error_code=code,
            error_message=message,
            usage_reported=False,
            raw_usage=raw_usage
            or {
                "provider_type": self.name,
                "reported": False,
                "request_count": 0,
                "input_images": 0,
                "output_images": 0,
            },
            estimated_cost_micros=0,
            actual_cost_micros=0,
            retryable=False,
            provider_name=self.name,
            model_name=self.model,
            pricing_version=self.pricing_version,
        )


def _require_mapping(value: object, code: str, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise SingleImageProviderError(code, message)
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    code: str,
) -> None:
    if set(value) - allowed or required - set(value):
        raise SingleImageProviderError(
            code, "The adapter object contains missing or unsupported fields."
        )


def _require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise SingleImageProviderError(
            "SINGLE_IMAGE_ENVELOPE_INVALID", f"The adapter {field} is invalid."
        )
    return value


def _require_item_key(value: object) -> str:
    if not isinstance(value, str) or not _ITEM_KEY_PATTERN.fullmatch(value):
        raise SingleImageProviderError(
            "SINGLE_IMAGE_ENVELOPE_INVALID", "The adapter item_key is invalid."
        )
    return value


def _require_hash(value: object) -> str:
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        raise SingleImageProviderError(
            "SKILL_CONTENT_HASH_INVALID",
            "The adapter Skill content hash is invalid.",
        )
    return value.lower()


def _require_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SingleImageProviderError(
            "SINGLE_IMAGE_ENVELOPE_INVALID", f"The adapter {field} is invalid."
        )
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SingleImageProviderError(
            "TARGET_CONFIGURATION_INVALID", f"The target {field} is invalid."
        )
    return value


def _validate_target_dimensions(width: int, height: int) -> None:
    if (
        width > _MAX_TARGET_DIMENSION
        or height > _MAX_TARGET_DIMENSION
        or width * height > _MAX_TARGET_PIXELS
    ):
        raise SingleImageProviderError(
            "TARGET_CONFIGURATION_INVALID",
            "The target dimensions exceed the local safety limit.",
        )


def _require_aspect_ratio(value: object, width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    expected = f"{width // divisor}:{height // divisor}"
    if value != expected:
        raise SingleImageProviderError(
            "TARGET_CONFIGURATION_INVALID",
            "The target aspect ratio does not match its dimensions.",
        )
    return expected


def _require_choice(value: object, allowed: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SingleImageProviderError(
            "TARGET_CONFIGURATION_INVALID", f"The target {field} is invalid."
        )
    return value


def _normalize_prompt_value(value: object) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or len(normalized) > _MAX_PROMPT_STRING_LENGTH:
            raise SingleImageProviderError(
                "PROMPT_INPUT_INVALID",
                "A prompt value is empty or exceeds the local safety limit.",
            )
        if any(pattern.search(normalized) for pattern in _SENSITIVE_VALUE_PATTERNS):
            raise SingleImageProviderError(
                "PROMPT_INPUT_SENSITIVE",
                "The prompt input appears to contain a credential.",
            )
        return normalized
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list) and len(value) <= _MAX_PROMPT_LIST_LENGTH:
        normalized_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                break
            normalized_item = item.strip()
            if (
                not normalized_item
                or len(normalized_item) > _MAX_PROMPT_STRING_LENGTH
                or any(
                    pattern.search(normalized_item)
                    for pattern in _SENSITIVE_VALUE_PATTERNS
                )
            ):
                break
            normalized_items.append(normalized_item)
        else:
            return normalized_items
    raise SingleImageProviderError(
        "PROMPT_INPUT_INVALID",
        "Prompt values must be bounded scalar values or string arrays.",
    )


def _manifest_content_hash(result: object) -> str:
    value = result
    if isinstance(result, Mapping):
        value = result.get("content_hash")
    elif not isinstance(result, str):
        value = getattr(result, "content_hash", None)
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        raise SingleImageProviderError(
            "SKILL_MANIFEST_VALIDATION_FAILED",
            "Skill manifest validation did not return a content hash.",
        )
    return value.lower()


def _inspect_image(payload: bytes) -> tuple[int, int, str]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = image.format
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > _MAX_SOURCE_PIXELS:
                raise ValueError("unsafe image dimensions")
            image.verify()
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise SingleImageProviderError(
            "INPUT_ASSET_INTEGRITY_FAILED",
            f"A source asset is not a valid bounded image ({type(exc).__name__}).",
        ) from None
    content_type = _IMAGE_CONTENT_TYPES.get(str(image_format))
    if content_type is None:
        raise SingleImageProviderError(
            "INPUT_ASSET_INTEGRITY_FAILED",
            "A source asset uses an unsupported image format.",
        )
    return width, height, content_type


def _provider_generation_size(target: TargetSpec, *, skill_id: str = "") -> str:
    target_width, target_height = target.dimensions
    if skill_id == "xinghe-amazon-visual-suite":
        amazon_canvas = {
            (2000, 2000): "2048x2048",
            (1200, 1600): "1200x1600",
            (1464, 600): "1536x640",
            (1600, 1200): "1600x1200",
        }.get((target_width, target_height))
        if amazon_canvas is not None:
            return amazon_canvas
    if target_width == target_height:
        return "1024x1024"
    if target_width > target_height:
        return "1536x1024"
    return "1024x1536"


def _target_artifact(
    artifact: ProviderArtifact,
    target: TargetSpec,
) -> ProviderArtifact:
    target_width, target_height = target.dimensions
    try:
        with Image.open(BytesIO(artifact.payload)) as opened:
            image_format = str(opened.format)
            opened.load()
            materialized = ImageOps.exif_transpose(opened).copy()
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise SingleImageProviderError(
            "IMAGE_OUTPUT_INVALID",
            f"The provider artifact is not a valid image ({type(exc).__name__}).",
        ) from None
    provider_width, provider_height = materialized.size
    if (
        provider_width <= 0
        or provider_height <= 0
        or provider_width * provider_height > _MAX_SOURCE_PIXELS
        or artifact.width != provider_width
        or artifact.height != provider_height
        or artifact.content_type.lower() != _IMAGE_CONTENT_TYPES.get(image_format)
        or artifact.sha256 != hashlib.sha256(artifact.payload).hexdigest()
    ):
        raise SingleImageProviderError(
            "IMAGE_OUTPUT_INVALID",
            "The provider artifact metadata does not match its payload.",
        )
    requested_format, content_type, suffix = _OUTPUT_FORMATS[target.output_format]
    if (
        (provider_width, provider_height) == (target_width, target_height)
        and image_format == requested_format
    ):
        return artifact

    if target.fit == "cover":
        rendered = ImageOps.fit(
            materialized,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    else:
        contained = ImageOps.contain(
            materialized,
            (target_width, target_height),
            method=Image.Resampling.LANCZOS,
        )
        if target.output_format == "jpeg":
            rendered = Image.new("RGB", (target_width, target_height), "white")
            offset = _center_offset(rendered, contained)
            if "A" in contained.getbands():
                rendered.paste(contained, offset, contained)
            else:
                rendered.paste(contained, offset)
        else:
            rendered = Image.new(
                "RGBA", (target_width, target_height), (0, 0, 0, 0)
            )
            offset = _center_offset(rendered, contained)
            if "A" in contained.getbands():
                rendered.paste(contained, offset, contained)
            else:
                rendered.paste(contained, offset)

    payload = _encode_image(rendered, target.output_format)
    return ProviderArtifact(
        payload=payload,
        filename=_replace_suffix(artifact.filename, suffix),
        content_type=content_type,
        width=target_width,
        height=target_height,
        sha256=hashlib.sha256(payload).hexdigest(),
        locally_resampled=True,
        provider_width=provider_width,
        provider_height=provider_height,
    )


def _center_offset(canvas: Image.Image, image: Image.Image) -> tuple[int, int]:
    return ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2)


def _encode_image(image: Image.Image, output_format: str) -> bytes:
    buffer = BytesIO()
    if output_format == "jpeg":
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, (0, 0), image)
            else:
                background.paste(image.convert("RGB"), (0, 0))
            image = background
        image.save(buffer, format="JPEG", quality=95, optimize=True)
    elif output_format == "png":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.save(buffer, format="WEBP", quality=95, method=6)
    return buffer.getvalue()


def _replace_suffix(filename: str, suffix: str) -> str:
    stem = filename.rsplit(".", maxsplit=1)[0] if "." in filename else filename
    safe_stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:100] or "image"
    return f"{safe_stem}{suffix}"


def _perceptual_dhash(payload: bytes) -> str:
    """Return a deterministic 64-bit difference hash for zero-cost set QA."""

    with Image.open(BytesIO(payload)) as image:
        grayscale = ImageOps.grayscale(image).resize(
            (9, 8),
            Image.Resampling.LANCZOS,
        )
        pixels = list(
            cast(Sequence[int], grayscale.get_flattened_data())
        )
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(
                pixels[offset + column] > pixels[offset + column + 1]
            )
    return f"{value:016x}"


def _safe_usage_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_cost(value: object) -> int | None:
    return _safe_usage_integer(value)


def _safe_latency(provider_value: object, measured_value: float) -> float:
    if (
        isinstance(provider_value, (int, float))
        and not isinstance(provider_value, bool)
        and math.isfinite(provider_value)
        and provider_value >= 0
    ):
        return round(float(provider_value), 6)
    return round(max(0.0, measured_value), 6)


def _safe_http_status(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 100 <= value <= 599
    ):
        return None
    return value


def _safe_request_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    return value


def _safe_error_code(value: object) -> str:
    if isinstance(value, str) and _ERROR_CODE_PATTERN.fullmatch(value):
        return value
    return "IMAGE_PROVIDER_FAILED"
