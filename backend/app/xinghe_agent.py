"""Bounded Xinghe detail-pack planning and provider boundary.

This module adapts the installed ``xinghe-ecommerce-detail`` batch-runtime
template to Polaris' existing PostgreSQL job, plan, attempt, usage, audit, and
credit records.  It deliberately contains no chat loop, subjective review
loop, or static planning fallback.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import (
    AssetLifecycleStatus,
    AttemptStatus,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    JobType,
    PlanValidationStatus,
    UsageCompleteness,
)
from .masked_repair import (
    MASKED_REPAIR_MODEL,
    MaskedEditCallResult,
    MaskedEditGatewayRequest,
    MaskedVisualReviewCallResult,
    MaskedVisualReviewRequest,
)
from .models import (
    AssetRecord,
    AuditEventRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    UsageEventRecord,
    utc_now,
)
from .provider import (
    Provider,
    ProviderArtifact,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from .provider_quota import require_provider_job_quota
from .services import (
    canonical_hash,
    new_id,
    quota_enabled,
    settle_credits,
    transition_job,
)
from .skill_runtime import SkillManifestRegistry, SkillRuntimeError
from .storage import ImageStorage

WORKFLOW_VERSION = "xinghe-bounded-agent-v2"
PLANNING_POLICY_VERSION = "xinghe-skill-parity-plan-v2"
QUALITY_POLICY_VERSION = "xinghe-all-high-v2"
PROMPT_POLICY_VERSION = "xinghe-skill-parity-prompt-v2"
RESUME_SIGNATURE_VERSION = "xinghe-resume-v2"
PLAN_SCHEMA_VERSION = "xinghe-plan-v2"
PLANNER_OBSERVABILITY_VERSION = "xinghe-planner-observability-v3"

# This is the native Aurora v2 visual-judgment check order.  Keep the gateway
# response contract in the same order as the Skill/runtime contract; the
# provider still validates the order again before it can advance the Harness.
_AURORA_V20_VISUAL_CHECKS = (
    "product_identity_match",
    "factual_copy_match",
    "typography_style_match",
    "typography_legibility",
    "page_role_expression",
    "evidence_relation_visible",
    "campaign_style_match",
    "headline_treatment_match",
    "palette_role_match",
    "graphic_language_match",
    "photography_finish_match",
    "information_surface_match",
    "layout_not_cloned",
    "set_diversity_match",
    "product_separation",
    "numeric_hierarchy_if_applicable",
    "design_intensity_controlled",
    "visual_performance_match",
    "baseline_performance_match",
    "approved_plan_fidelity_match",
    "campaign_constitution_match",
    "source_background_noise_absent",
    "selling_point_visible_without_copy",
    "selling_point_visual_dominance",
    "claim_to_evidence_relation_clear",
    "text_not_substituting_for_visual_proof",
    "thumbnail_success",
    "no_unsupported_claim",
    "no_hard_error",
)
_AURORA_V20_MATERIAL_CHECKS = frozenset(
    {
        "product_identity_match",
        "factual_copy_match",
        "source_background_noise_absent",
        "no_unsupported_claim",
        "no_hard_error",
        "typography_legibility",
        "page_role_expression",
        "evidence_relation_visible",
        "visual_performance_match",
        "baseline_performance_match",
        "approved_plan_fidelity_match",
        "campaign_constitution_match",
        "selling_point_visible_without_copy",
        "selling_point_visual_dominance",
        "claim_to_evidence_relation_clear",
        "text_not_substituting_for_visual_proof",
        "thumbnail_success",
        "layout_not_cloned",
    }
)
PLANNER_DIAGNOSTICS_SCHEMA = "xinghe-planner-diagnostics"
IMAGE_SIZE = "1024x1536"
SUPPORTED_IMAGE_SIZES = frozenset(
    {
        IMAGE_SIZE,
        "750x1000",
        "1000x1000",
        "1024x1024",
        "1200x1200",
        "1200x1600",
        "1600x1600",
        "2000x2000",
        "2048x2048",
        "2200x2200",
    }
)
IMAGE_FORMAT = "jpeg"
JPEG_QUALITY = 92
DEFAULT_MEDIUM_PRICE_MICROS = 45_000
DEFAULT_HIGH_PRICE_MICROS = 90_000
DEFAULT_BUDGET_LIMIT_MICROS = 200_000_000
MAX_PAGE_RETRIES = 2
PLANNER_LEASE_SECONDS = 900
_MISSING_JSON_VALUE = object()
_MAX_PROTOCOL_JSON_BYTES = 48 * 1024
_MAX_PROTOCOL_STRING_LENGTH = 4_000
_MAX_PROTOCOL_COLLECTION_LENGTH = 96
_MAX_PROTOCOL_DEPTH = 8
_SENSITIVE_PROTOCOL_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)

_PLANNER_JSON_FENCE = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n"
    r"(?P<body>.*?)\r?\n```[ \t]*\Z",
    re.IGNORECASE | re.DOTALL,
)
_HIGH_ROLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"灏侀潰",
        r"缁撴瀯",
        r"缁嗚妭",
        r"鐗瑰啓",
        r"鏉愯川",
        r"琛ㄩ潰",
        r"宸ヨ壓",
        r"绾圭悊",
        r"寰窛",
        r"\bcover\b",
        r"\bstructur(?:e|al)\b",
        r"\bdetail(?:ed)?\b",
        r"\bclose[\s-]?up\b",
        r"\bmaterial\b",
        r"\bsurface\b",
        r"\bcraft(?:smanship)?\b",
        r"\btexture\b",
        r"\bmacro\b",
    )
)

_DEFAULT_PLANNER_PROTOCOL_FILES = (
    "SKILL.md",
    "references/category-router.md",
    "references/design-strength-system.md",
    "references/prompt-contract.md",
    "references/compliance.md",
    "references/quality-control.md",
    "references/fashion-page-structures.md",
    "references/food-page-structures.md",
    "references/pet-page-structures.md",
    "references/beauty-personalcare-structures.md",
    "references/home-daily-structures.md",
    "references/electronics-structures.md",
    "references/general-page-structures.md",
)
_CROSSBORDER_PLANNER_PROTOCOL_FILES = (
    "SKILL.md",
    "references/buyer-demand-strategy.md",
    "references/platform-profiles.md",
    "references/reference-page-analysis.md",
    "references/page-planning-strategy.md",
    "references/page-task-table.md",
    "references/scene-layout-standard.md",
    "references/style-system-standard.md",
    "references/design-strength-system.md",
    "references/visual-quality-rules.md",
    "references/product-consistency-physics.md",
    "references/anti-template-check.md",
    "references/prompt-contract.md",
    "references/prompt-templates.md",
)
_AMAZON_PLANNER_PROTOCOL_FILES = (
    "SKILL.md",
    "references/workflow.md",
    "references/image-specs.md",
    "references/page-task-table.md",
    "references/quality-rules.md",
    "references/generation-backend.md",
)
_COMPLETE_REFERENCE_PROTOCOL_SKILLS = frozenset({"xinghe-ecommerce-detail-domestic-3"})
_PLANNER_PROTOCOL_FILES_BY_SKILL = {
    "xinghe-crossborder-detail-3": _CROSSBORDER_PLANNER_PROTOCOL_FILES,
    "xinghe-amazon-visual-suite": _AMAZON_PLANNER_PROTOCOL_FILES,
}
_SUBJECT_SCALES = {
    "hero",
    "medium",
    "macro",
    "scene",
    "information",
    "cutaway",
    "overhead",
}


class XingheAgentError(RuntimeError):
    """Controlled, redaction-safe Agent failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        json_pointer: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.json_pointer = json_pointer


@dataclass(frozen=True)
class SourceImage:
    asset_id: str
    group_key: str
    filename: str
    content_type: str
    sha256: str
    payload: bytes
    source_role: str = "product_reference"


@dataclass(frozen=True)
class PlannerRequest:
    workspace_id: str
    job_id: str
    group_key: str
    sources: tuple[SourceImage, ...]
    page_count: int
    language: str
    product_name: str
    product_information: tuple[str, ...]
    platform_code: str
    size: str
    idempotency_key: str
    system_prompt: str = ""
    domestic_protocol: bool = False
    planning_profile: str = "detail_pack"


@dataclass(frozen=True)
class PlannerCallResult:
    payload: object | None
    provider_request_id: str | None
    raw_usage: dict[str, Any] | None
    normalized_usage: dict[str, Any]
    api_latency_seconds: float
    actual_cost_micros: int | None
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    parse_trace: tuple[str, ...] = ()
    structure_fingerprint: str | None = None
    structure_profile: dict[str, Any] | None = None
    error_path: str | None = None
    provider_envelope: dict[str, Any] | None = None
    content_utf8_bytes: int | None = None
    content_sha256: str | None = None
    request_id_presence: str = "not_available"
    usage_presence: str = "not_available"
    usage_completeness: str = "not_available"


@dataclass(frozen=True)
class ImageEditRequest:
    workspace_id: str
    job_id: str
    job_item_id: str
    attempt_id: str
    page_number: int
    group_key: str
    sources: tuple[SourceImage, ...]
    prompt: str
    quality: str
    idempotency_key: str
    size: str
    output_format: str = IMAGE_FORMAT
    jpeg_quality: int = JPEG_QUALITY
    input_fidelity: str = "high"
    preserve_provider_artifact: bool = False


@dataclass(frozen=True)
class ImageCallResult:
    outcome: ProviderOutcome
    provider_request_id: str | None
    raw_usage: dict[str, Any] | None
    normalized_usage: dict[str, Any]
    api_latency_seconds: float
    actual_cost_micros: int | None
    estimated_cost_micros: int | None = None
    artifact: ProviderArtifact | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    http_status: int | None = None
    rate_limited: bool = False
    active_concurrency: int = 0


@dataclass(frozen=True)
class AmazonVisualReviewImage:
    item_key: str
    filename: str
    content_type: str
    payload: bytes


@dataclass(frozen=True)
class AmazonVisualReviewRequest:
    workspace_id: str
    job_id: str
    scope: str
    item_key: str | None
    references: tuple[SourceImage, ...]
    candidates: tuple[AmazonVisualReviewImage, ...]
    generation_contract: str
    skill_protocol: Mapping[str, Any]
    idempotency_key: str
    review_item_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class AmazonVisualReviewCallResult:
    visual_success: bool | None
    provider_request_id: str | None
    raw_usage: dict[str, Any] | None
    normalized_usage: dict[str, Any]
    actual_cost_micros: int | None
    estimated_cost_micros: int | None = None
    summary: str = ""
    reason_codes: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    retry_guidance: str = ""
    failed_item_keys: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    http_status: int | None = None


class XingheGateway(Protocol):
    provider_name: str
    planner_model: str
    image_model: str
    pricing_version: str
    medium_price_micros: int
    high_price_micros: int
    external_network_request_count: int

    async def plan(self, request: PlannerRequest) -> PlannerCallResult: ...

    async def edit(self, request: ImageEditRequest) -> ImageCallResult: ...

    async def review_amazon(
        self, request: AmazonVisualReviewRequest
    ) -> AmazonVisualReviewCallResult: ...


def normalize_usage(raw_usage: object) -> dict[str, Any]:
    """Preserve missing usage as unreported instead of fabricating zeros."""

    if not isinstance(raw_usage, dict):
        return {
            "reported": False,
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "total_tokens": None,
        }
    input_tokens = _usage_integer(
        raw_usage.get("input_tokens", raw_usage.get("prompt_tokens"))
    )
    output_tokens = _usage_integer(
        raw_usage.get("output_tokens", raw_usage.get("completion_tokens"))
    )
    cached_tokens = _usage_integer(
        raw_usage.get("cached_tokens", raw_usage.get("cached_input_tokens"))
    )
    total_tokens = _usage_integer(raw_usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "reported": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
    }


def quality_for_role(role: str) -> str:
    """Apply the user-approved all-high detail-page quality policy."""

    del role
    return "high"


def cost_range(
    page_count: int,
    group_count: int,
    medium_price_micros: int,
    high_price_micros: int,
) -> tuple[int, int]:
    del medium_price_micros
    total_pages = page_count * group_count
    high_total = total_pages * high_price_micros
    return high_total, high_total


def build_resume_signature(
    *,
    groups: Sequence[tuple[str, Sequence[tuple[str, str] | tuple[str, str, str]]]],
    base_url: str,
    planner_model: str,
    image_model: str,
    page_count: int,
    language: str,
    product_name: str,
    product_information: Sequence[str],
    platform_code: str,
    size: str,
    medium_price_micros: int,
    high_price_micros: int,
) -> str:
    """Hash every output-affecting input and versioned strategy."""

    payload = {
        "version": RESUME_SIGNATURE_VERSION,
        "groups": [
            {
                "label": label,
                "sources": [
                    (
                        {
                            "role": source[0],
                            "filename": source[1],
                            "sha256": source[2],
                        }
                        if len(source) == 3
                        else {"filename": source[0], "sha256": source[1]}
                    )
                    for source in sources
                ],
            }
            for label, sources in groups
        ],
        "base_url": base_url.rstrip("/"),
        "planner_model": planner_model,
        "image_model": image_model,
        "workflow_version": WORKFLOW_VERSION,
        "planning_policy_version": PLANNING_POLICY_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "page_count": page_count,
        "language": language,
        "product_name": product_name,
        "product_information": list(product_information),
        "platform_code": platform_code,
        "image_field_name": "image",
        "size": size,
        "output_format": IMAGE_FORMAT,
        "jpeg_quality": JPEG_QUALITY,
        "medium_price_micros": medium_price_micros,
        "high_price_micros": high_price_micros,
    }
    return canonical_hash(payload)


def _safe_protocol_value(
    value: object,
    *,
    path: str,
    depth: int = 0,
) -> Any:
    """Return bounded JSON data while omitting unknown credential-like keys."""

    if depth > _MAX_PROTOCOL_DEPTH:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner protocol data exceeds the nesting limit.",
            json_pointer=path,
        )
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Planner protocol numbers must be finite.",
                json_pointer=path,
            )
        return value
    if isinstance(value, str):
        if len(value) > _MAX_PROTOCOL_STRING_LENGTH:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Planner protocol text exceeds the field limit.",
                json_pointer=path,
            )
        return value
    if isinstance(value, list):
        if len(value) > _MAX_PROTOCOL_COLLECTION_LENGTH:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Planner protocol arrays exceed the item limit.",
                json_pointer=path,
            )
        return [
            _safe_protocol_value(
                item,
                path=f"{path}/{index}",
                depth=depth + 1,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        if len(value) > _MAX_PROTOCOL_COLLECTION_LENGTH:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Planner protocol objects exceed the member limit.",
                json_pointer=path,
            )
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 160:
                raise XingheAgentError(
                    "PLANNER_SCHEMA_INVALID",
                    "Planner protocol object keys are invalid.",
                    json_pointer=path,
                )
            if _SENSITIVE_PROTOCOL_KEY.search(key):
                continue
            normalized[key] = _safe_protocol_value(
                item,
                path=f"{path}/{key.replace('~', '~0').replace('/', '~1')}",
                depth=depth + 1,
            )
        return normalized
    raise XingheAgentError(
        "PLANNER_SCHEMA_INVALID",
        "Planner protocol fields must contain JSON values only.",
        json_pointer=path,
    )


def _bounded_protocol_mapping(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    normalized = _safe_protocol_value(value, path=path)
    if not isinstance(normalized, dict):  # pragma: no cover - mapping invariant
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner protocol field must be an object.",
            json_pointer=path,
        )
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_PROTOCOL_JSON_BYTES:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner protocol object exceeds the serialized size limit.",
            json_pointer=path,
        )
    return normalized


def validate_planner_payload(
    payload: object,
    page_count: int,
    *,
    preserve_protocol_fields: bool = False,
    require_cross_page_locks: bool = False,
    enforce_background_repeat_limit: bool = True,
) -> dict[str, Any]:
    """Validate the mandatory structured plan and exact screen count."""

    root = _require_mapping(
        payload,
        "PLANNER_SCHEMA_INVALID",
        path="/",
    )
    analysis = _require_mapping(
        root.get("analysis"),
        "PLANNER_SCHEMA_INVALID",
        path=_json_pointer("analysis"),
    )
    plan = _require_mapping(
        root.get("plan"),
        "PLANNER_SCHEMA_INVALID",
        path=_json_pointer("plan"),
    )
    for key in (
        "category_key",
        "category_reason",
    ):
        _require_nonempty_string(
            analysis.get(key),
            key,
            path=_json_pointer("analysis", key),
        )
    for key in (
        "product_image_analysis",
        "product_consistency_anchors",
    ):
        _require_mapping(
            analysis.get(key),
            "PLANNER_SCHEMA_INVALID",
            path=_json_pointer("analysis", key),
        )
    product_master: Mapping[str, Any] | None = None
    product_consistency_lock: Mapping[str, Any] | None = None
    if require_cross_page_locks:
        product_master = _require_mapping(
            analysis.get("product_master_description"),
            "PLANNER_SCHEMA_INVALID",
            path=_json_pointer("analysis", "product_master_description"),
        )
        if not product_master:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Product Master Description cannot be empty.",
                json_pointer=_json_pointer("analysis", "product_master_description"),
            )
    objections = analysis.get("buyer_objections")
    if not isinstance(objections, list) or not objections:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner buyer objections must be a non-empty array.",
            json_pointer=_json_pointer("analysis", "buyer_objections"),
        )
    campaign_lock = _require_mapping(
        plan.get("campaign_style_lock"),
        "PLANNER_SCHEMA_INVALID",
        path=_json_pointer("plan", "campaign_style_lock"),
    )
    for key in (
        "palette",
        "typography",
        "background",
        "lighting",
        "icon_style",
        "whitespace",
        "product_scale",
    ):
        _require_nonempty_string(
            campaign_lock.get(key),
            key,
            path=_json_pointer("plan", "campaign_style_lock", key),
        )
    design_lock = _require_mapping(
        plan.get("design_strength_lock"),
        "PLANNER_SCHEMA_INVALID",
        path=_json_pointer("plan", "design_strength_lock"),
    )
    layout_diversity_lock: Mapping[str, Any] | None = None
    if require_cross_page_locks:
        product_consistency_lock = _require_mapping(
            plan.get("product_consistency_lock"),
            "PLANNER_SCHEMA_INVALID",
            path=_json_pointer("plan", "product_consistency_lock"),
        )
        if not product_consistency_lock:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Product Consistency Lock cannot be empty.",
                json_pointer=_json_pointer("plan", "product_consistency_lock"),
            )
        layout_diversity_lock = _require_mapping(
            plan.get("layout_diversity_lock"),
            "PLANNER_SCHEMA_INVALID",
            path=_json_pointer("plan", "layout_diversity_lock"),
        )
        maximum = layout_diversity_lock.get("max_same_layout_family")
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or maximum < 1
            or maximum > 3
        ):
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Layout diversity lock requires max_same_layout_family from 1 to 3.",
                json_pointer=_json_pointer(
                    "plan", "layout_diversity_lock", "max_same_layout_family"
                ),
            )
    for key in (
        "category_visual_motif",
        "composition_contrast",
        "color_contrast",
        "template_ban",
    ):
        _require_nonempty_string(
            design_lock.get(key),
            key,
            path=_json_pointer("plan", "design_strength_lock", key),
        )
    signature_devices = design_lock.get("signature_devices")
    if (
        not isinstance(signature_devices, list)
        or len(signature_devices) < min(2, page_count)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in signature_devices
        )
    ):
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner design strength lock requires signature devices.",
            json_pointer=_json_pointer(
                "plan", "design_strength_lock", "signature_devices"
            ),
        )
    screens = plan.get("screens")
    if not isinstance(screens, list):
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner screens must be an array.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if len(screens) != page_count:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner returned a different number of screens than requested.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    rhythm_map = design_lock.get("rhythm_map")
    if (
        not isinstance(rhythm_map, list)
        or len(rhythm_map) != page_count
        or any(not isinstance(value, str) or not value.strip() for value in rhythm_map)
    ):
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner rhythm map must contain one entry per screen.",
            json_pointer=_json_pointer("plan", "design_strength_lock", "rhythm_map"),
        )
    safe_analysis = (
        _bounded_protocol_mapping(analysis, path="/analysis")
        if preserve_protocol_fields
        else {}
    )
    safe_plan = (
        _bounded_protocol_mapping(plan, path="/plan")
        if preserve_protocol_fields
        else {}
    )
    normalized_screens: list[dict[str, Any]] = []
    for screen_index, screen in enumerate(screens):
        screen_path = _json_pointer("plan", "screens", screen_index)
        screen_mapping = _require_mapping(
            screen,
            "PLANNER_SCHEMA_INVALID",
            path=screen_path,
        )
        normalized: dict[str, Any] = (
            _bounded_protocol_mapping(screen_mapping, path=screen_path)
            if preserve_protocol_fields
            else {}
        )
        required_screen_fields = [
            "role",
            "title",
            "label",
            "composition",
            "device",
            "difference",
            "structure",
            "subject_scale",
        ]
        if require_cross_page_locks:
            required_screen_fields.extend(
                [
                    "buyer_question",
                    "layout_family",
                    "camera_angle",
                    "product_position",
                    "background_system",
                    "prop_strategy",
                    "copy_density",
                ]
            )
        normalized.update(
            {
                key: _require_nonempty_string(
                    screen_mapping.get(key),
                    key,
                    path=_json_pointer("plan", "screens", screen_index, key),
                )
                for key in required_screen_fields
            }
        )
        if normalized["subject_scale"] not in _SUBJECT_SCALES:
            raise XingheAgentError(
                "PLANNER_SCHEMA_INVALID",
                "Planner subject scale is outside the production enum.",
                json_pointer=_json_pointer(
                    "plan", "screens", screen_index, "subject_scale"
                ),
            )
        normalized_screens.append(normalized)
    minimum_roles = min(5, page_count)
    minimum_structures = min(4, page_count)
    minimum_scales = min(3, page_count)
    minimum_devices = min(2, page_count)
    distinct_roles = {item["role"].strip().casefold() for item in normalized_screens}
    distinct_structures = {
        item["structure"].strip().casefold() for item in normalized_screens
    }
    distinct_scales = {item["subject_scale"] for item in normalized_screens}
    distinct_devices = {
        item["device"].strip().casefold() for item in normalized_screens
    }
    if len(distinct_roles) < minimum_roles:
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "Planner did not provide enough distinct page roles.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if len(distinct_structures) < minimum_structures:
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "Planner did not provide enough distinct page structures.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if len(distinct_scales) < minimum_scales:
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "Planner did not provide enough subject-scale contrast.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if len(distinct_devices) < minimum_devices:
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "Planner did not provide enough distinct signature devices.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if require_cross_page_locks:
        assert layout_diversity_lock is not None
        maximum = int(layout_diversity_lock["max_same_layout_family"])
        repeat_limited_fields = ["layout_family"]
        if enforce_background_repeat_limit:
            repeat_limited_fields.append("background_system")
        for field in repeat_limited_fields:
            counts: dict[str, int] = {}
            for item in normalized_screens:
                value = str(item[field]).strip().casefold()
                counts[value] = counts.get(value, 0) + 1
            if counts and max(counts.values()) > maximum:
                raise XingheAgentError(
                    "PLANNER_CROSS_PAGE_DIVERSITY_INVALID",
                    f"Planner repeats {field} more than the approved maximum.",
                    json_pointer=_json_pointer("plan", "screens"),
                )
        buyer_questions = [
            str(item["buyer_question"]).strip().casefold()
            for item in normalized_screens
        ]
        if len(set(buyer_questions)) != len(buyer_questions):
            raise XingheAgentError(
                "PLANNER_CROSS_PAGE_DIVERSITY_INVALID",
                "Planner buyer questions must be unique across the set.",
                json_pointer=_json_pointer("plan", "screens"),
            )
        combinations = {
            tuple(
                str(item[field]).strip().casefold()
                for field in (
                    "layout_family",
                    "subject_scale",
                    "camera_angle",
                    "product_position",
                    "background_system",
                    "prop_strategy",
                    "copy_density",
                )
            )
            for item in normalized_screens
        }
        if len(combinations) != len(normalized_screens):
            raise XingheAgentError(
                "PLANNER_CROSS_PAGE_DIVERSITY_INVALID",
                "Planner contains duplicate cross-page composition signatures.",
                json_pointer=_json_pointer("plan", "screens"),
            )
    hero_count = sum(item["subject_scale"] == "hero" for item in normalized_screens)
    if page_count > 1 and hero_count > (page_count + 1) // 2:
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "Too many screens use a full-product hero scale.",
            json_pointer=_json_pointer("plan", "screens"),
        )
    if page_count > 1 and normalized_screens[-1]["role"] != "closing_summary":
        raise XingheAgentError(
            "PLANNER_DESIGN_STRENGTH_INVALID",
            "The final screen must be the non-consultative closing summary.",
            json_pointer=_json_pointer("plan", "screens", page_count - 1, "role"),
        )
    if not preserve_protocol_fields:
        normalized_plan = {
            "campaign_style_lock": dict(campaign_lock),
            "design_strength_lock": dict(design_lock),
            "screens": normalized_screens,
        }
        if layout_diversity_lock is not None:
            normalized_plan["layout_diversity_lock"] = dict(layout_diversity_lock)
        if product_consistency_lock is not None:
            normalized_plan["product_consistency_lock"] = dict(product_consistency_lock)
        normalized_analysis = {
            "category_key": str(analysis["category_key"]),
            "category_reason": str(analysis["category_reason"]),
            "product_image_analysis": dict(analysis["product_image_analysis"]),
            "product_consistency_anchors": dict(
                analysis["product_consistency_anchors"]
            ),
            "buyer_objections": list(objections),
        }
        if product_master is not None:
            normalized_analysis["product_master_description"] = dict(product_master)
        return {
            "analysis": normalized_analysis,
            "plan": normalized_plan,
        }
    safe_analysis.update(
        {
            "category_key": str(analysis["category_key"]),
            "category_reason": str(analysis["category_reason"]),
            "product_image_analysis": dict(safe_analysis["product_image_analysis"]),
            "product_consistency_anchors": dict(
                safe_analysis["product_consistency_anchors"]
            ),
            "buyer_objections": list(safe_analysis["buyer_objections"]),
        }
    )
    safe_plan.update(
        {
            "campaign_style_lock": dict(safe_plan["campaign_style_lock"]),
            "design_strength_lock": dict(safe_plan["design_strength_lock"]),
            "screens": normalized_screens,
        }
    )
    return {"analysis": safe_analysis, "plan": safe_plan}


def compile_page_prompt(
    *,
    structured_plan: Mapping[str, Any],
    screen: Mapping[str, str],
    page_number: int,
    page_count: int,
    language: str,
    product_name: str,
    product_information: Sequence[str],
    source_count: int,
    size: str,
    source_roles: Sequence[str] | None = None,
    include_protocol_fields: bool = False,
) -> str:
    """Compile the template's fidelity and prompt-density contract."""

    analysis = _require_mapping(
        structured_plan.get("analysis"),
        "PLANNER_SCHEMA_INVALID",
    )
    plan = _require_mapping(
        structured_plan.get("plan"),
        "PLANNER_SCHEMA_INVALID",
    )
    anchors = json.dumps(
        analysis["product_consistency_anchors"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    facts = json.dumps(
        analysis["product_image_analysis"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    campaign_lock = json.dumps(
        plan["campaign_style_lock"],
        ensure_ascii=False,
        sort_keys=True,
    )
    design_lock = json.dumps(
        plan["design_strength_lock"],
        ensure_ascii=False,
        sort_keys=True,
    )
    product_master = json.dumps(
        analysis.get("product_master_description", {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    layout_lock = json.dumps(
        plan.get("layout_diversity_lock", {}),
        ensure_ascii=False,
        sort_keys=True,
    )
    consistency_lock = json.dumps(
        plan.get("product_consistency_lock", {}),
        ensure_ascii=False,
        sort_keys=True,
    )
    cross_page_fields = "\n".join(
        f"{key.replace('_', ' ').title()}: {screen[key]}"
        for key in (
            "buyer_question",
            "layout_family",
            "camera_angle",
            "product_position",
            "background_system",
            "prop_strategy",
            "copy_density",
        )
        if key in screen
    )
    supplied = "; ".join(product_information) or "visible image facts only"
    width, height = _parse_image_size(size)
    divisor = math.gcd(width, height)
    ratio = f"{width // divisor}:{height // divisor}"
    if not include_protocol_fields:
        return (
            f"e-commerce detail page image; exact canvas {width}x{height} ({ratio})\n"
            f"Page {page_number}/{page_count}. Create one independent page, not a "
            "collage or multi-panel composition.\n"
            f"All {source_count} ordered reference images are complementary angles "
            "of the same product. Reconcile them into one consistent identity; "
            "mark visible conflicts needs_confirmation.\n"
            f"Product: {product_name}. User-provided information: {supplied}.\n"
            f"Product Consistency Anchors: {anchors}\n"
            f"Product Master Description: {product_master}\n"
            f"Product Consistency Lock: {consistency_lock}\n"
            f"Visible-fact boundary: {facts}\n"
            f"Campaign Style Lock: {campaign_lock}\n"
            f"Design Strength Lock: {design_lock}\n"
            f"Layout Diversity Lock: {layout_lock}\n"
            f"Role: {screen['role']}\n"
            f"Page structure: {screen['structure']}\n"
            f"Subject scale: {screen['subject_scale']}\n"
            f"Main title ({language}): {screen['title']}\n"
            f"One short label ({language}): {screen['label']}\n"
            f"One visual hero and composition: {screen['composition']}\n"
            f"Visual device: {screen['device']}\n"
            f"Difference from adjacent pages: {screen['difference']}\n"
            f"{cross_page_fields}\n"
            "One core selling point only. Exactly one main title and one short "
            "label. At most one zoom window and at most two structural callouts. "
            "No repeated local window, no repeated display of the same part, no "
            "multi-panel collage, and no multiple crop windows. Use only supplied "
            "information and visible facts. Do not invent functions, parameters, "
            "materials, certifications, efficacy, sales, reviews, tests, rankings, "
            "comfort, durability, or authenticity claims. Treat visible source "
            "watermarks as source marks, never as product branding or page copy."
        )
    analysis_protocol = json.dumps(
        {
            key: value
            for key, value in analysis.items()
            if key
            not in {
                "category_key",
                "category_reason",
                "product_image_analysis",
                "product_consistency_anchors",
            }
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    plan_protocol = json.dumps(
        {
            key: value
            for key, value in plan.items()
            if key
            not in {
                "campaign_style_lock",
                "design_strength_lock",
                "screens",
            }
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    screen_protocol = json.dumps(
        {
            key: value
            for key, value in screen.items()
            if key
            not in {
                "role",
                "title",
                "label",
                "composition",
                "device",
                "difference",
                "structure",
                "subject_scale",
            }
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    protocol_bytes = sum(
        len(value.encode("utf-8"))
        for value in (analysis_protocol, plan_protocol, screen_protocol)
    )
    if protocol_bytes > _MAX_PROTOCOL_JSON_BYTES:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Compiled planner protocol context exceeds the prompt size limit.",
        )
    visible_product_name = (
        product_name.strip() or "visible product from supplied images"
    )
    roles = tuple(source_roles or ("product_reference",) * source_count)
    product_source_count = sum(role == "product_reference" for role in roles)
    style_source_count = sum(role == "style_reference" for role in roles)
    return (
        f"e-commerce detail page image; exact canvas {width}x{height} ({ratio})\n"
        f"Page {page_number}/{page_count}. Create one independent page, not a "
        "collage or multi-panel composition.\n"
        f"Sources: {product_source_count} product_reference image(s) and "
        f"{style_source_count} style_reference image(s), {source_count} total. "
        "Only product_reference images define product identity, visible facts, "
        "materials, structure, labels, and claims. Reconcile product sources as "
        "complementary angles of the same product and mark visible conflicts "
        "needs_confirmation. style_reference images provide layout, hierarchy, "
        "mood, color rhythm, lighting direction, and composition devices only; "
        "never treat their depicted product, brand, wording, marks, ratings, "
        "claims, or specifications as facts about the user's product.\n"
        f"Product: {visible_product_name}. User-provided information: {supplied}.\n"
        f"Product Consistency Anchors: {anchors}\n"
        f"Product Master Description: {product_master}\n"
        f"Product Consistency Lock: {consistency_lock}\n"
        f"Visible-fact boundary: {facts}\n"
        f"Analysis Protocol Fields: {analysis_protocol}\n"
        f"Campaign Style Lock: {campaign_lock}\n"
        f"Design Strength Lock: {design_lock}\n"
        f"Layout Diversity Lock: {layout_lock}\n"
        f"Plan Protocol Fields: {plan_protocol}\n"
        f"Role: {screen['role']}\n"
        f"Page structure: {screen['structure']}\n"
        f"Subject scale: {screen['subject_scale']}\n"
        f"Main title ({language}): {screen['title']}\n"
        f"One short label ({language}): {screen['label']}\n"
        f"One visual hero and composition: {screen['composition']}\n"
        f"Visual device: {screen['device']}\n"
        f"Difference from adjacent pages: {screen['difference']}\n"
        f"{cross_page_fields}\n"
        f"Current Screen Protocol Fields: {screen_protocol}\n"
        "One core selling point only. Exactly one main title and one short "
        "label. At most one zoom window and at most two structural callouts. "
        "No repeated local window, no repeated display of the same part, no "
        "multi-panel collage, and no multiple crop windows. Use only supplied "
        "information and visible facts. Do not invent functions, parameters, "
        "materials, certifications, efficacy, sales, reviews, tests, rankings, "
        "comfort, durability, or authenticity claims. Treat visible source "
        "watermarks as source marks, never as product branding or page copy."
    )


def load_planner_system_prompt(
    skill_root: Path,
    skill_id: str = "xinghe-ecommerce-detail",
) -> str:
    """Load the pinned direct-Codex protocol after manifest verification."""

    sections: list[str] = [
        (
            "You are the production runtime for the pinned "
            f"{skill_id} skill. Follow every included protocol "
            "as authoritative. Perform one combined product-analysis and "
            "page-planning pass; do not call images when planning is invalid."
        )
    ]
    try:
        if skill_id in _COMPLETE_REFERENCE_PROTOCOL_SKILLS:
            references_root = skill_root / "references"
            reference_files = tuple(
                path.relative_to(skill_root).as_posix()
                for path in sorted(
                    references_root.glob("*.md"),
                    key=lambda candidate: candidate.name,
                )
            )
            protocol_files = ("SKILL.md", *reference_files)
        else:
            protocol_files = _PLANNER_PROTOCOL_FILES_BY_SKILL.get(
                skill_id,
                _DEFAULT_PLANNER_PROTOCOL_FILES,
            )
        for relative in protocol_files:
            path = skill_root / Path(relative)
            sections.append(
                f"\n\n--- BEGIN {relative} ---\n"
                f"{path.read_text(encoding='utf-8')}"
                f"\n--- END {relative} ---"
            )
    except (OSError, UnicodeError) as exc:
        raise XingheAgentError(
            "SKILL_PROTOCOL_LOAD_FAILED",
            f"Pinned planner protocol could not be loaded ({type(exc).__name__}).",
        ) from exc
    return "".join(sections)


class FakeXingheGateway:
    """Deterministic no-network gateway with bounded fault injection."""

    provider_name = "mock"
    planner_model = "gpt-5.6-terra-fake"
    image_model = "gpt-image-2-fake"
    pricing_version = "xinghe-fake-zero-v1"
    medium_price_micros = 0
    high_price_micros = 0

    def __init__(
        self,
        *,
        delay_seconds: float = 0,
        planner_failure: str | None = None,
        image_failures: Mapping[int, int] | None = None,
        usage_reported: bool = True,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.planner_failure = planner_failure
        self.image_failures = dict(image_failures or {})
        self.usage_reported = usage_reported
        self.planner_calls: list[PlannerRequest] = []
        self.image_calls: list[ImageEditRequest] = []
        self.amazon_review_calls: list[AmazonVisualReviewRequest] = []
        self.external_network_request_count = 0
        self._image_attempts: dict[tuple[str, int], int] = {}
        self._active_images = 0
        self.max_active_images = 0
        self._activity_lock = asyncio.Lock()

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        self.planner_calls.append(request)
        started = time.perf_counter()
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        raw_usage = _fake_usage() if self.usage_reported else None
        if self.planner_failure == "transport":
            return PlannerCallResult(
                payload=None,
                provider_request_id="mock_planner_failure",
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=0,
                error_code="PLANNER_REQUEST_FAILED",
                error_message="The fake planner returned a controlled failure.",
                http_status=503,
            )
        payload: object = _fake_plan(request)
        if self.planner_failure == "invalid_json":
            payload = "{not-json"
        elif self.planner_failure == "schema":
            payload = {"analysis": {}, "plan": {"screens": []}}
        elif self.planner_failure == "wrong_page_count":
            wrong = _fake_plan(request)
            wrong["plan"]["screens"] = wrong["plan"]["screens"][:-1]
            payload = wrong
        return PlannerCallResult(
            payload=payload,
            provider_request_id=f"mock_plan_{request.group_key}",
            raw_usage=raw_usage,
            normalized_usage=normalize_usage(raw_usage),
            api_latency_seconds=time.perf_counter() - started,
            actual_cost_micros=0,
            http_status=200,
        )

    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        started = time.perf_counter()
        async with self._activity_lock:
            self._active_images += 1
            self.max_active_images = max(
                self.max_active_images,
                self._active_images,
            )
            active = self._active_images
        try:
            self.image_calls.append(request)
            attempt_key = (request.group_key, request.page_number)
            self._image_attempts[attempt_key] = (
                self._image_attempts.get(attempt_key, 0) + 1
            )
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            raw_usage: dict[str, Any] | None = _fake_usage(
                input_images=len(request.sources),
                output_images=1,
            )
            if not self.usage_reported:
                raw_usage = None
            fail_count = self.image_failures.get(request.page_number, 0)
            if self._image_attempts[attempt_key] <= fail_count:
                group_token = hashlib.sha256(request.group_key.encode()).hexdigest()[
                    :10
                ]
                return ImageCallResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_request_id=(
                        f"mock_image_{group_token}_{request.page_number}_"
                        f"{self._image_attempts[attempt_key]}"
                    ),
                    raw_usage=raw_usage,
                    normalized_usage=normalize_usage(raw_usage),
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=0,
                    estimated_cost_micros=0,
                    error_code="MOCK_IMAGE_TRANSIENT_FAILURE",
                    error_message="The fake image request failed transiently.",
                    retryable=True,
                    http_status=503,
                    active_concurrency=active,
                )
            payload = _fake_jpeg(request.page_number, request.size)
            artifact = _artifact_from_bytes(
                payload,
                filename=f"{request.group_key}-page-{request.page_number:03d}.jpg",
                expected_size=request.size,
                preserve_provider_artifact=request.preserve_provider_artifact,
            )
            group_token = hashlib.sha256(request.group_key.encode()).hexdigest()[:10]
            return ImageCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=(
                    f"mock_image_{group_token}_{request.page_number}_"
                    f"{self._image_attempts[attempt_key]}"
                ),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=0,
                estimated_cost_micros=0,
                artifact=artifact,
                http_status=200,
                active_concurrency=active,
            )
        finally:
            async with self._activity_lock:
                self._active_images -= 1

    async def review_amazon(
        self, request: AmazonVisualReviewRequest
    ) -> AmazonVisualReviewCallResult:
        self.amazon_review_calls.append(request)
        raw_usage: dict[str, Any] | None = _fake_usage(
            input_images=len(request.references) + len(request.candidates)
        )
        if not self.usage_reported:
            raw_usage = None
        return AmazonVisualReviewCallResult(
            visual_success=True,
            provider_request_id=f"mock_amazon_review_{len(self.amazon_review_calls)}",
            raw_usage=raw_usage,
            normalized_usage=normalize_usage(raw_usage),
            actual_cost_micros=0,
            estimated_cost_micros=0,
            summary="The deterministic fake reviewer accepted the candidate.",
            http_status=200,
        )


class OpenAICompatibleTransport(Protocol):
    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]: ...

    async def post_multipart(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        fields: Sequence[tuple[str, str]],
        files: Sequence[tuple[str, str, str, bytes]],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]: ...


class UrllibOpenAITransport:
    """Small dependency-free OpenAI-compatible JSON/multipart transport."""

    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {**headers, "Content-Type": "application/json"}
        return await asyncio.to_thread(
            self._send,
            url,
            request_headers,
            body,
            timeout_seconds,
        )

    async def post_multipart(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        fields: Sequence[tuple[str, str]],
        files: Sequence[tuple[str, str, str, bytes]],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]:
        boundary = f"polaris-{secrets.token_hex(16)}"
        body = _encode_multipart(boundary, fields, files)
        request_headers = {
            **headers,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        return await asyncio.to_thread(
            self._send,
            url,
            request_headers,
            body,
            timeout_seconds,
        )

    @staticmethod
    def _send(
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, dict[str, Any]]:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        error_status = False
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status = int(response.status)
                raw = response.read()
        except HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
            error_status = True
        except (TimeoutError, URLError, OSError) as exc:
            raise XingheAgentError(
                "PROVIDER_TRANSPORT_FAILED",
                f"Provider transport failed ({type(exc).__name__}).",
                retryable=True,
            ) from exc
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if error_status:
                return status, {"error": {"code": "non_json_error_response"}}
            raise XingheAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "Provider returned invalid JSON.",
            ) from exc
        if not isinstance(payload, dict):
            raise XingheAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "Provider returned a non-object JSON response.",
            )
        return status, payload


class TengliOpenAICompatibleGateway:
    """Maintainable Tengli adapter; construction alone never makes a request."""

    provider_name = "tengli"
    pricing_version = "tengli-configured-v1"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        planner_model: str,
        image_model: str,
        medium_price_micros: int = DEFAULT_MEDIUM_PRICE_MICROS,
        high_price_micros: int = DEFAULT_HIGH_PRICE_MICROS,
        review_price_micros: int = 20_000,
        timeout_seconds: float = 600,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Tengli API key is required.")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Tengli base URL must be an absolute HTTP(S) URL.")
        if not planner_model.strip() or not image_model.strip():
            raise ValueError("Planner and image models are required.")
        if medium_price_micros < 0 or high_price_micros < 0 or review_price_micros < 0:
            raise ValueError("Configured unit prices cannot be negative.")
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.planner_model = planner_model.strip()
        self.image_model = image_model.strip()
        self.medium_price_micros = medium_price_micros
        self.high_price_micros = high_price_micros
        self.review_price_micros = review_price_micros
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrllibOpenAITransport()
        self.external_network_request_count = 0

    async def plan(self, request: PlannerRequest) -> PlannerCallResult:
        started = time.perf_counter()
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _planner_prompt(request),
            }
        ]
        for ordinal, source in enumerate(request.sources, start=1):
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"Source image {ordinal}\n"
                        f"asset_id: {source.asset_id}\n"
                        f"role: {source.source_role}\n"
                        f"filename: {source.filename}"
                    ),
                }
            )
            encoded = base64.b64encode(source.payload).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{source.content_type};base64,{encoded}"
                    },
                }
            )
        payload: dict[str, Any] = {
            "model": self.planner_model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": content},
            ],
            "response_format": _planner_response_format(request),
        }
        if request.planning_profile == "amazon_visual_suite":
            payload.update(
                {
                    "max_completion_tokens": 12_000,
                }
            )
        elif request.planning_profile == "aurora_v20_visual_audit":
            payload.update(
                {
                    # A v2 audit contains 29 ordered checks plus 22 observation
                    # fields.  The previous generic default was small enough
                    # to encourage abbreviated/string observations or a stale
                    # runtime envelope before local validation could explain it.
                    "max_completion_tokens": 16_000,
                }
            )
        response: Mapping[str, Any] | None = None
        try:
            self.external_network_request_count += 1
            status, response = await self.transport.post_json(
                url=urljoin(self.base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key),
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            if status >= 400:
                envelope_diagnostics = _planner_envelope_diagnostics(response)
                return PlannerCallResult(
                    payload=None,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=_raw_usage(response),
                    normalized_usage=normalize_usage(_raw_usage(response)),
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=_usage_cost_micros(_raw_usage(response)),
                    error_code=(
                        "PLANNER_RATE_LIMITED"
                        if status == 429
                        else "PLANNER_REQUEST_FAILED"
                    ),
                    error_message=f"Planner request failed with HTTP {status}.",
                    http_status=status,
                    provider_envelope=envelope_diagnostics["provider_envelope"],
                    request_id_presence=envelope_diagnostics["request_id_presence"],
                    usage_presence=envelope_diagnostics["usage_presence"],
                    usage_completeness=envelope_diagnostics["usage_completeness"],
                )
            envelope_diagnostics = _planner_envelope_diagnostics(response)
            text = _planner_message_text(response)
            plan_payload, parse_trace = _planner_content_payload_with_trace(text)
            raw_usage = _raw_usage(response)
            content_bytes = text.encode("utf-8")
            return PlannerCallResult(
                payload=plan_payload,
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                http_status=status,
                parse_trace=parse_trace,
                structure_fingerprint=_planner_structure_fingerprint(plan_payload),
                provider_envelope=envelope_diagnostics["provider_envelope"],
                content_utf8_bytes=len(content_bytes),
                content_sha256=hashlib.sha256(content_bytes).hexdigest(),
                request_id_presence=envelope_diagnostics["request_id_presence"],
                usage_presence=envelope_diagnostics["usage_presence"],
                usage_completeness=envelope_diagnostics["usage_completeness"],
            )
        except XingheAgentError as exc:
            envelope_diagnostics = (
                _planner_envelope_diagnostics(response)
                if response is not None
                else _unavailable_planner_envelope_diagnostics()
            )
            raw_content = _planner_raw_content(response)
            rejected_content_bytes = (
                raw_content.encode("utf-8") if isinstance(raw_content, str) else None
            )
            raw_usage = _raw_usage(response) if response is not None else None
            return PlannerCallResult(
                payload=None,
                provider_request_id=(
                    _safe_request_id(response) if response is not None else None
                ),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=None,
                error_code=exc.code,
                error_message=str(exc),
                error_path=exc.json_pointer,
                parse_trace=("provider_payload:rejected_before_json_parse",),
                structure_fingerprint=_planner_structure_fingerprint(
                    response if raw_content is _MISSING_JSON_VALUE else raw_content
                ),
                provider_envelope=envelope_diagnostics["provider_envelope"],
                content_utf8_bytes=(
                    len(rejected_content_bytes)
                    if rejected_content_bytes is not None
                    else None
                ),
                content_sha256=(
                    hashlib.sha256(rejected_content_bytes).hexdigest()
                    if rejected_content_bytes is not None
                    else None
                ),
                request_id_presence=envelope_diagnostics["request_id_presence"],
                usage_presence=envelope_diagnostics["usage_presence"],
                usage_completeness=envelope_diagnostics["usage_completeness"],
            )

    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        started = time.perf_counter()
        fields = [
            ("model", self.image_model),
            ("prompt", request.prompt),
            ("n", "1"),
            ("size", request.size),
            ("quality", request.quality),
            ("output_format", request.output_format),
            ("input_fidelity", request.input_fidelity),
            ("response_format", "b64_json"),
        ]
        # Tengli rejects output_compression for PNG (even when set to 100).
        # Send compression only for formats where the API defines it.
        if request.output_format in {"jpeg", "webp"}:
            fields.insert(6, ("output_compression", str(request.jpeg_quality)))
        files = [
            ("image", source.filename, source.content_type, source.payload)
            for source in request.sources
        ]
        try:
            self.external_network_request_count += 1
            status, response = await self.transport.post_multipart(
                url=urljoin(self.base_url, "v1/images/edits"),
                headers=self._headers(request.idempotency_key),
                fields=fields,
                files=files,
                timeout_seconds=self.timeout_seconds,
            )
            raw_usage = _raw_usage(response)
            normalized = normalize_usage(raw_usage)
            estimated_cost = (
                self.high_price_micros
                if request.quality == "high"
                else self.medium_price_micros
            )
            if status >= 400:
                rate_limited = status == 429
                return ImageCallResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=raw_usage,
                    normalized_usage=normalized,
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=_usage_cost_micros(raw_usage),
                    estimated_cost_micros=estimated_cost,
                    error_code=(
                        "IMAGE_RATE_LIMITED" if rate_limited else "IMAGE_REQUEST_FAILED"
                    ),
                    error_message=f"Image request failed with HTTP {status}.",
                    retryable=rate_limited or status >= 500,
                    http_status=status,
                    rate_limited=rate_limited,
                )
            image_bytes = _image_bytes(response)
            artifact = _artifact_from_bytes(
                image_bytes,
                filename=f"{request.group_key}-page-{request.page_number:03d}.jpg",
                expected_size=request.size,
                preserve_provider_artifact=request.preserve_provider_artifact,
            )
            return ImageCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalized,
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                estimated_cost_micros=estimated_cost,
                artifact=artifact,
                http_status=status,
            )
        except XingheAgentError as exc:
            return ImageCallResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=None,
                estimated_cost_micros=(
                    self.high_price_micros
                    if request.quality == "high"
                    else self.medium_price_micros
                ),
                error_code=exc.code,
                error_message=str(exc),
                retryable=exc.retryable,
            )

    async def edit_masked(
        self,
        request: MaskedEditGatewayRequest,
    ) -> MaskedEditCallResult:
        """Send an editable canvas plus an unchanged identity reference."""

        estimated_cost = (
            self.high_price_micros
            if request.quality == "high"
            else self.medium_price_micros
        )
        try:
            editable_source = _provider_transparent_hole_png(
                request.source_png,
                request.api_mask_png,
            )
            fields = [
                ("model", MASKED_REPAIR_MODEL),
                ("prompt", _tengli_masked_prompt(request.prompt)),
                ("n", "1"),
                ("size", f"{request.width}x{request.height}"),
                ("quality", request.quality),
                ("output_format", "png"),
                ("response_format", "b64_json"),
            ]
            files = [
                ("image", "editable.png", "image/png", editable_source),
                (
                    "image",
                    "source_reference.png",
                    "image/png",
                    request.source_png,
                ),
            ]
            self.external_network_request_count += 1
            status, response = await self.transport.post_multipart(
                url=urljoin(self.base_url, "v1/images/edits"),
                headers=self._headers(request.idempotency_key),
                fields=fields,
                files=files,
                timeout_seconds=self.timeout_seconds,
            )
            raw_usage = _raw_usage(response)
            normalized = normalize_usage(raw_usage)
            if status >= 400:
                rate_limited = status == 429
                return MaskedEditCallResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=raw_usage,
                    normalized_usage=normalized,
                    actual_cost_micros=_usage_cost_micros(raw_usage),
                    estimated_cost_micros=estimated_cost,
                    error_code=(
                        "LOCAL_EDIT_RATE_LIMITED"
                        if rate_limited
                        else "LOCAL_EDIT_REQUEST_FAILED"
                    ),
                    error_message=f"Local-edit request failed with HTTP {status}.",
                    retryable=rate_limited or status >= 500,
                    http_status=status,
                )
            image_bytes = _image_bytes(response)
            artifact = _masked_png_artifact(image_bytes)
            return MaskedEditCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalized,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                estimated_cost_micros=estimated_cost,
                artifact=artifact,
                http_status=status,
            )
        except XingheAgentError as exc:
            return MaskedEditCallResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                actual_cost_micros=None,
                estimated_cost_micros=estimated_cost,
                error_code=exc.code,
                error_message=str(exc),
                retryable=exc.retryable,
            )

    async def review_amazon(
        self,
        request: AmazonVisualReviewRequest,
    ) -> AmazonVisualReviewCallResult:
        """Review Amazon candidates only against the bundled Skill contract."""

        try:
            review_item_keys = _amazon_visual_review_item_keys(request)
        except XingheAgentError as exc:
            return AmazonVisualReviewCallResult(
                visual_success=None,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                actual_cost_micros=None,
                estimated_cost_micros=self.review_price_micros,
                error_code="AMAZON_VISUAL_REVIEW_INVALID",
                error_message=str(exc),
                retryable=False,
            )

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _amazon_visual_review_prompt(
                    request,
                    review_item_keys=review_item_keys,
                ),
            }
        ]
        for ordinal, source in enumerate(request.references, start=1):
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"Reference {ordinal}: asset_id={source.asset_id}; "
                        f"role={source.source_role}; filename={source.filename}"
                    ),
                }
            )
            encoded = base64.b64encode(source.payload).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{source.content_type};base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        for ordinal, candidate in enumerate(request.candidates, start=1):
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"Candidate {ordinal}: item_key={candidate.item_key}; "
                        f"filename={candidate.filename}"
                    ),
                }
            )
            encoded = base64.b64encode(candidate.payload).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{candidate.content_type};base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        payload = {
            "model": self.planner_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the visual QA stage of the supplied Amazon Skill. "
                        "Apply only the supplied Skill protocol and generation "
                        "contract. Do not invent additional product-specific rules. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": _amazon_visual_review_response_format(review_item_keys),
            "temperature": 0,
        }
        response: Mapping[str, Any] | None = None
        try:
            self.external_network_request_count += 1
            status, response = await self.transport.post_json(
                url=urljoin(self.base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key),
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            raw_usage = _raw_usage(response)
            normalized = normalize_usage(raw_usage)
            if status >= 400:
                return AmazonVisualReviewCallResult(
                    visual_success=None,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=raw_usage,
                    normalized_usage=normalized,
                    actual_cost_micros=_usage_cost_micros(raw_usage),
                    estimated_cost_micros=self.review_price_micros,
                    error_code=(
                        "AMAZON_VISUAL_REVIEW_RATE_LIMITED"
                        if status == 429
                        else "AMAZON_VISUAL_REVIEW_REQUEST_FAILED"
                    ),
                    error_message=f"Amazon visual review failed with HTTP {status}.",
                    retryable=status == 429 or status >= 500,
                    http_status=status,
                )
            review_payload = _planner_content_payload(_planner_message_text(response))
            review = _validate_amazon_visual_review_payload(
                review_payload,
                scope=request.scope,
                review_item_keys=review_item_keys,
            )
            return AmazonVisualReviewCallResult(
                visual_success=review["visual_success"],
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalized,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                estimated_cost_micros=self.review_price_micros,
                summary=review["summary"],
                reason_codes=tuple(review["reason_codes"]),
                missing_evidence=tuple(review["missing_evidence"]),
                retry_guidance=review["retry_guidance"],
                failed_item_keys=tuple(review["failed_item_keys"]),
                http_status=status,
            )
        except (TimeoutError, URLError, OSError) as exc:
            return AmazonVisualReviewCallResult(
                visual_success=None,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                actual_cost_micros=None,
                estimated_cost_micros=self.review_price_micros,
                error_code="AMAZON_VISUAL_REVIEW_REQUEST_FAILED",
                error_message=(
                    f"Amazon visual review transport failed ({type(exc).__name__})."
                ),
                retryable=True,
            )
        except XingheAgentError as exc:
            raw_usage = _raw_usage(response) if response is not None else None
            return AmazonVisualReviewCallResult(
                visual_success=None,
                provider_request_id=(
                    _safe_request_id(response) if response is not None else None
                ),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                actual_cost_micros=(
                    _usage_cost_micros(raw_usage) if raw_usage is not None else None
                ),
                estimated_cost_micros=self.review_price_micros,
                error_code=(
                    "AMAZON_VISUAL_REVIEW_REQUEST_FAILED"
                    if exc.retryable
                    else "AMAZON_VISUAL_REVIEW_INVALID"
                ),
                error_message=str(exc),
                retryable=exc.retryable,
            )

    async def review_masked(
        self,
        request: MaskedVisualReviewRequest,
    ) -> MaskedVisualReviewCallResult:
        """Review the raw candidate once; never regenerate from this call."""

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _masked_visual_review_prompt(request.instruction),
            }
        ]
        for image_payload in (
            request.source_png,
            request.authority_png,
            request.candidate_png,
        ):
            encoded = base64.b64encode(image_payload).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        payload = {
            "model": self.planner_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict visual acceptance reviewer for a "
                        "masked image edit. Return JSON only. Do not propose "
                        "or perform regeneration."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
        }
        response: Mapping[str, Any] | None = None
        try:
            self.external_network_request_count += 1
            status, response = await self.transport.post_json(
                url=urljoin(self.base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key),
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            raw_usage = _raw_usage(response)
            normalized = normalize_usage(raw_usage)
            if status >= 400:
                return MaskedVisualReviewCallResult(
                    visual_success=None,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=raw_usage,
                    normalized_usage=normalized,
                    actual_cost_micros=_usage_cost_micros(raw_usage),
                    estimated_cost_micros=self.review_price_micros,
                    error_code=(
                        "LOCAL_EDIT_VISUAL_REVIEW_RATE_LIMITED"
                        if status == 429
                        else "LOCAL_EDIT_VISUAL_REVIEW_REQUEST_FAILED"
                    ),
                    error_message=(
                        f"Local-edit visual review failed with HTTP {status}."
                    ),
                    retryable=status == 429 or status >= 500,
                    http_status=status,
                )
            review_payload = _planner_content_payload(_planner_message_text(response))
            review = _validate_masked_visual_review_payload(review_payload)
            return MaskedVisualReviewCallResult(
                visual_success=review["visual_success"],
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalized,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                estimated_cost_micros=self.review_price_micros,
                summary=review["summary"],
                reason_codes=tuple(review["reason_codes"]),
                http_status=status,
            )
        except (TimeoutError, URLError, OSError) as exc:
            return MaskedVisualReviewCallResult(
                visual_success=None,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                actual_cost_micros=None,
                estimated_cost_micros=self.review_price_micros,
                error_code="LOCAL_EDIT_VISUAL_REVIEW_REQUEST_FAILED",
                error_message=(
                    f"Local-edit visual review transport failed ({type(exc).__name__})."
                ),
                retryable=True,
            )
        except XingheAgentError as exc:
            raw_usage = _raw_usage(response) if response is not None else None
            return MaskedVisualReviewCallResult(
                visual_success=None,
                provider_request_id=(
                    _safe_request_id(response) if response is not None else None
                ),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                actual_cost_micros=(
                    _usage_cost_micros(raw_usage) if raw_usage is not None else None
                ),
                estimated_cost_micros=self.review_price_micros,
                error_code=(
                    "LOCAL_EDIT_VISUAL_REVIEW_REQUEST_FAILED"
                    if exc.retryable
                    else "LOCAL_EDIT_VISUAL_REVIEW_INVALID"
                ),
                error_message=str(exc),
                retryable=exc.retryable,
            )

    def _headers(self, idempotency_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "Polaris-Commerce-Studio/1.2",
        }


def build_tengli_gateway(settings: Settings) -> TengliOpenAICompatibleGateway:
    """Build the real adapter explicitly; callers control whether it is used."""

    return TengliOpenAICompatibleGateway(
        api_key=settings.tengli_api_key.get_secret_value(),
        base_url=settings.tengli_base_url,
        planner_model=settings.tengli_vision_model,
        image_model=settings.tengli_image_model,
        medium_price_micros=settings.xinghe_medium_price_micros,
        high_price_micros=settings.xinghe_high_price_micros,
        review_price_micros=settings.tengli_planner_reserve_micros,
    )


class XinghePlanningCoordinator:
    """Durable one-call-per-group planning state machine."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        *,
        storage: ImageStorage | None,
        skill_root: Path,
        base_url_signature: str,
        medium_price_micros: int = DEFAULT_MEDIUM_PRICE_MICROS,
        high_price_micros: int = DEFAULT_HIGH_PRICE_MICROS,
        budget_limit_micros: int = DEFAULT_BUDGET_LIMIT_MICROS,
        skill_id: str = "xinghe-ecommerce-detail",
    ) -> None:
        if medium_price_micros < 0 or high_price_micros < 0:
            raise ValueError("Image prices cannot be negative.")
        if budget_limit_micros <= 0:
            raise ValueError("Budget limit must be positive.")
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.skill_root = skill_root
        self.base_url_signature = base_url_signature
        self.medium_price_micros = medium_price_micros
        self.high_price_micros = high_price_micros
        self.budget_limit_micros = budget_limit_micros
        self.skill_id = skill_id

    async def plan(self, job_id: str) -> JobStatus | None:
        reserved = self._reserve(job_id)
        if isinstance(reserved, JobStatus) or reserved is None:
            return reserved
        plan_id, requests = reserved
        try:
            system_prompt = load_planner_system_prompt(self.skill_root, self.skill_id)
            requests = tuple(
                replace(request, system_prompt=system_prompt) for request in requests
            )
            requests = tuple(
                [await self._with_source_payloads(request) for request in requests]
            )
        except XingheAgentError as exc:
            return self._fail_planning(
                job_id,
                plan_id,
                exc.code,
                str(exc),
                [],
            )
        results: list[PlannerCallResult] = []
        validated: list[dict[str, Any]] = []
        for request in requests:
            started = time.perf_counter()
            try:
                result = await self.gateway.plan(request)
            except Exception as exc:
                result = PlannerCallResult(
                    payload=None,
                    provider_request_id=None,
                    raw_usage=None,
                    normalized_usage=normalize_usage(None),
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=None,
                    error_code="PLANNER_PROVIDER_FAILED",
                    error_message=(f"Planner provider failed ({type(exc).__name__})."),
                )
            result = _with_planner_observability(result)
            results.append(result)
            if result.error_code is not None:
                return self._fail_planning(
                    job_id,
                    plan_id,
                    result.error_code,
                    result.error_message or "Planner request failed.",
                    results,
                    error_path=result.error_path,
                )
            try:
                if request.planning_profile == "amazon_visual_suite":
                    from .amazon_visual_suite_provider import (
                        validate_amazon_planner_payload,
                    )

                    validated.append(
                        validate_amazon_planner_payload(
                            result.payload,
                            sources=request.sources,
                        )
                    )
                else:
                    validated.append(
                        validate_planner_payload(
                            result.payload,
                            request.page_count,
                            preserve_protocol_fields=request.domestic_protocol,
                            require_cross_page_locks=(
                                request.planning_profile == "crossborder_detail"
                            ),
                        )
                    )
            except XingheAgentError as exc:
                return self._fail_planning(
                    job_id,
                    plan_id,
                    exc.code,
                    str(exc),
                    results,
                    error_path=exc.json_pointer,
                )
        return self._complete_planning(
            job_id,
            plan_id,
            requests,
            results,
            validated,
        )

    async def _with_source_payloads(
        self,
        request: PlannerRequest,
    ) -> PlannerRequest:
        if self.storage is None:
            if self.gateway.provider_name != "mock":
                raise XingheAgentError(
                    "SOURCE_STORAGE_UNAVAILABLE",
                    "Source storage is required for the configured provider.",
                )
            return request
        loaded: list[SourceImage] = []
        with self.session_factory() as session:
            assets = {
                asset.id: asset
                for asset in session.scalars(
                    select(AssetRecord).where(
                        AssetRecord.workspace_id == request.workspace_id,
                        AssetRecord.id.in_(
                            [source.asset_id for source in request.sources]
                        ),
                    )
                ).all()
            }
        for source in request.sources:
            asset = assets.get(source.asset_id)
            if asset is None:
                raise XingheAgentError(
                    "INPUT_ASSET_NOT_FOUND",
                    "A reserved source asset is no longer available.",
                )
            try:
                payload = await self.storage.read_bytes(asset.object_key)
            except Exception as exc:
                raise XingheAgentError(
                    "SOURCE_READ_FAILED",
                    f"Source image could not be read ({type(exc).__name__}).",
                ) from exc
            if not payload or hashlib.sha256(payload).hexdigest() != source.sha256:
                raise XingheAgentError(
                    "SOURCE_HASH_MISMATCH",
                    "Source image bytes no longer match the reserved input.",
                )
            loaded.append(
                SourceImage(
                    asset_id=source.asset_id,
                    group_key=source.group_key,
                    filename=source.filename,
                    content_type=source.content_type,
                    sha256=source.sha256,
                    payload=payload,
                    source_role=source.source_role,
                )
            )
        return replace(request, sources=tuple(loaded))

    def _reserve(
        self,
        job_id: str,
    ) -> tuple[str, tuple[PlannerRequest, ...]] | JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current != JobStatus.PLANNING:
                return current
            existing = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job.id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                if existing.validation_status == PlanValidationStatus.VALID.value:
                    transition_job(
                        job,
                        JobStatus.AWAITING_CONFIRMATION,
                        stage="awaiting_confirmation",
                        progress=15,
                    )
                    session.commit()
                    return JobStatus.AWAITING_CONFIRMATION
                lease_expires_at = _parse_datetime(
                    existing.payload.get("planner_lease_expires_at")
                    if isinstance(existing.payload, dict)
                    else None
                )
                now = utc_now()
                if lease_expires_at is not None:
                    if lease_expires_at.tzinfo is None and now.tzinfo is not None:
                        now = now.replace(tzinfo=None)
                    if lease_expires_at > now:
                        return JobStatus.PLANNING
                return self._fail_reserved_unknown(session, job, existing)
            try:
                requests = self._planning_requests(session, job)
                self._authorize_planning(session, job, requests)
            except XingheAgentError as exc:
                return self._fail_before_provider(session, job, exc)
            plan_id = new_id("plan")
            reservation_payload = {
                "workflow_version": WORKFLOW_VERSION,
                "state": "planner_reserved",
                "planner_lease_expires_at": (
                    datetime.now(UTC) + timedelta(seconds=PLANNER_LEASE_SECONDS)
                ).isoformat(),
                "provider": {
                    "type": self.gateway.provider_name,
                    "planner_model": self.gateway.planner_model,
                    "image_model": self.gateway.image_model,
                    "pricing_version": self.gateway.pricing_version,
                },
                "groups": [
                    {
                        "group_key": request.group_key,
                        "ordered_sources": [
                            {
                                "asset_id": source.asset_id,
                                "filename": source.filename,
                                "sha256": source.sha256,
                            }
                            for source in request.sources
                        ],
                        "planner_idempotency_key_sha256": hashlib.sha256(
                            request.idempotency_key.encode()
                        ).hexdigest(),
                    }
                    for request in requests
                ],
            }
            session.add(
                JobPlanRecord(
                    id=plan_id,
                    workspace_id=job.workspace_id,
                    job_id=job.id,
                    revision=1,
                    schema_version=PLAN_SCHEMA_VERSION,
                    payload=reservation_payload,
                    payload_hash=canonical_hash(reservation_payload),
                    validation_status=PlanValidationStatus.PENDING.value,
                    validation_errors=[],
                    validator_version=PLANNING_POLICY_VERSION,
                )
            )
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    action="xinghe.planning_reserved",
                    resource_type="job",
                    resource_id=job.id,
                    request_id=plan_id,
                    details={
                        "workflow_version": WORKFLOW_VERSION,
                        "group_count": len(requests),
                        "page_count_per_group": requests[0].page_count,
                        "provider_type": self.gateway.provider_name,
                        "budget_limit_micros": self.budget_limit_micros,
                    },
                )
            )
            session.commit()
            return plan_id, requests

    def _planning_requests(
        self,
        session: Session,
        job: JobRecord,
    ) -> tuple[PlannerRequest, ...]:
        configuration = _require_mapping(
            job.configuration,
            "AGENT_CONFIGURATION_INVALID",
        )
        input_configuration = _require_mapping(
            configuration.get("input"),
            "AGENT_CONFIGURATION_INVALID",
        )
        settings = _require_mapping(
            configuration.get("settings"),
            "AGENT_CONFIGURATION_INVALID",
        )
        if job.type == JobType.AMAZON_VISUAL_SUITE.value:
            return self._amazon_planning_requests(
                session,
                job,
                input_configuration,
                settings,
            )
        domestic_protocol = self.skill_id == "xinghe-ecommerce-detail-domestic-3"
        if domestic_protocol:
            from .domestic_detail_provider import (
                domestic_detail_prompt_configuration,
            )
            from .new_detail_skill_provider import AdapterValidationError

            try:
                detail_prompt_configuration = domestic_detail_prompt_configuration(
                    settings
                )
            except AdapterValidationError as exc:
                raise XingheAgentError(exc.code, str(exc)) from exc
        elif self.skill_id == "xinghe-crossborder-detail-3":
            from .crossborder_detail_provider import (
                crossborder_detail_prompt_configuration,
            )
            from .new_detail_skill_provider import AdapterValidationError

            try:
                detail_prompt_configuration = crossborder_detail_prompt_configuration(
                    settings
                )
            except AdapterValidationError as exc:
                raise XingheAgentError(exc.code, str(exc)) from exc
        groups = input_configuration.get("product_groups")
        if not isinstance(groups, list) or not groups:
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "At least one product group is required.",
            )
        page_count = _strict_page_count(settings.get("page_count"))
        product_name_value = settings.get("product_name")
        if domestic_protocol and isinstance(product_name_value, str):
            product_name = (
                product_name_value.strip() or "visible product from supplied images"
            )
        else:
            product_name = _require_nonempty_string(
                product_name_value,
                "product_name",
            )
        language = _require_nonempty_string(settings.get("language"), "language")
        platform_code = _require_nonempty_string(
            settings.get("platform_code"),
            "platform_code",
        )
        if domestic_protocol:
            size = _validated_image_size(detail_prompt_configuration["resolved_size"])
        else:
            size = _validated_image_size(settings.get("size") or IMAGE_SIZE)
        selling_points_value = settings.get("selling_points", [])
        if not isinstance(selling_points_value, list) or not all(
            isinstance(value, str) for value in selling_points_value
        ):
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "Product information must be an array of strings.",
            )
        reference_asset_ids: list[str] = []
        durable_roles: set[tuple[str, str]] = set()
        if domestic_protocol:
            reference_value = input_configuration.get("reference_asset_ids", [])
            if not isinstance(reference_value, list) or any(
                not isinstance(value, str) or not value for value in reference_value
            ):
                raise XingheAgentError(
                    "AGENT_CONFIGURATION_INVALID",
                    "Style reference asset identifiers must be strings.",
                )
            reference_asset_ids = list(reference_value)
            durable_roles = {
                (relation.asset_id, relation.role)
                for relation in session.scalars(
                    select(JobAssetRecord)
                    .where(
                        JobAssetRecord.workspace_id == job.workspace_id,
                        JobAssetRecord.job_id == job.id,
                        JobAssetRecord.job_item_id.is_(None),
                        JobAssetRecord.direction == JobAssetDirection.INPUT.value,
                    )
                    .order_by(JobAssetRecord.role, JobAssetRecord.ordinal)
                ).all()
            }
        requests: list[PlannerRequest] = []
        signature_groups: list[
            tuple[
                str,
                Sequence[tuple[str, str] | tuple[str, str, str]],
            ]
        ] = []
        source_groups: list[tuple[str, tuple[SourceImage, ...]]] = []
        for group_index, group_value in enumerate(groups, start=1):
            group = _require_mapping(
                group_value,
                "AGENT_CONFIGURATION_INVALID",
            )
            group_key = _require_nonempty_string(
                group.get("group_key"),
                "group_key",
            )
            asset_ids = group.get("asset_ids")
            if not isinstance(asset_ids, list) or not asset_ids:
                raise XingheAgentError(
                    "AGENT_CONFIGURATION_INVALID",
                    f"Product group {group_index} has no source assets.",
                )
            sources: list[SourceImage] = []
            role_asset_ids = [
                ("product_reference", asset_id_value) for asset_id_value in asset_ids
            ]
            if domestic_protocol:
                role_asset_ids.extend(
                    ("style_reference", asset_id) for asset_id in reference_asset_ids
                )
            for source_role, asset_id_value in role_asset_ids:
                if not isinstance(asset_id_value, str):
                    raise XingheAgentError(
                        "AGENT_CONFIGURATION_INVALID",
                        "Product source asset identifiers must be strings.",
                    )
                if (
                    domestic_protocol
                    and (
                        asset_id_value,
                        source_role,
                    )
                    not in durable_roles
                ):
                    raise XingheAgentError(
                        "RESUME_SIGNATURE_INVALID",
                        "A source role no longer matches its durable job binding.",
                    )
                asset = session.scalar(
                    select(AssetRecord).where(
                        AssetRecord.id == asset_id_value,
                        AssetRecord.workspace_id == job.workspace_id,
                        AssetRecord.lifecycle_status
                        == AssetLifecycleStatus.READY.value,
                        AssetRecord.deleted_at.is_(None),
                    )
                )
                if asset is None:
                    raise XingheAgentError(
                        "INPUT_ASSET_NOT_FOUND",
                        "A product source asset is missing or outside the workspace.",
                    )
                sources.append(
                    SourceImage(
                        asset_id=asset.id,
                        group_key=group_key,
                        filename=asset.original_filename,
                        content_type=asset.content_type,
                        sha256=asset.sha256,
                        payload=b"",
                        source_role=source_role,
                    )
                )
            source_tuple = tuple(sources)
            source_groups.append((group_key, source_tuple))
            signature_sources: Sequence[tuple[str, str] | tuple[str, str, str]]
            if domestic_protocol:
                signature_sources = tuple(
                    (source.source_role, source.filename, source.sha256)
                    for source in source_tuple
                )
            else:
                signature_sources = tuple(
                    (source.filename, source.sha256) for source in source_tuple
                )
            signature_groups.append((group_key, signature_sources))
        signature = build_resume_signature(
            groups=signature_groups,
            base_url=self.base_url_signature,
            planner_model=self.gateway.planner_model,
            image_model=self.gateway.image_model,
            page_count=page_count,
            language=language,
            product_name=product_name,
            product_information=tuple(selling_points_value),
            platform_code=platform_code,
            size=size,
            medium_price_micros=self.medium_price_micros,
            high_price_micros=self.high_price_micros,
        )
        for group_index, (group_key, group_sources) in enumerate(
            source_groups,
            start=1,
        ):
            requests.append(
                PlannerRequest(
                    workspace_id=job.workspace_id,
                    job_id=job.id,
                    group_key=group_key,
                    sources=group_sources,
                    page_count=page_count,
                    language=language,
                    product_name=product_name,
                    product_information=tuple(selling_points_value),
                    platform_code=platform_code,
                    size=size,
                    idempotency_key=(f"{job.id}:planner:{group_index}:{signature}"),
                    domestic_protocol=domestic_protocol,
                    planning_profile=(
                        "crossborder_detail"
                        if self.skill_id == "xinghe-crossborder-detail-3"
                        else "detail_pack"
                    ),
                )
            )
        return tuple(requests)

    def _amazon_planning_requests(
        self,
        session: Session,
        job: JobRecord,
        input_configuration: Mapping[str, Any],
        settings: Mapping[str, Any],
    ) -> tuple[PlannerRequest, ...]:
        from .amazon_visual_suite_provider import (
            AMAZON_EXPECTED_ITEM_COUNT,
            AMAZON_PLANNING_POLICY_VERSION,
            AMAZON_VISUAL_SUITE_SKILL_ID,
        )

        if self.skill_id != AMAZON_VISUAL_SUITE_SKILL_ID:
            raise XingheAgentError(
                "AMAZON_PLANNER_UNAVAILABLE",
                "The Amazon visual-suite planner is not registered.",
            )
        relations = session.scalars(
            select(JobAssetRecord)
            .where(
                JobAssetRecord.workspace_id == job.workspace_id,
                JobAssetRecord.job_id == job.id,
                JobAssetRecord.job_item_id.is_(None),
                JobAssetRecord.direction == JobAssetDirection.INPUT.value,
            )
            .order_by(JobAssetRecord.role, JobAssetRecord.ordinal)
        ).all()
        if not relations or not any(
            relation.role == "white_background_product" for relation in relations
        ):
            raise XingheAgentError(
                "AMAZON_WHITE_BACKGROUND_SOURCE_REQUIRED",
                "Amazon planning requires a real white-background product source.",
            )
        sources: list[SourceImage] = []
        for relation in relations:
            asset = session.scalar(
                select(AssetRecord).where(
                    AssetRecord.id == relation.asset_id,
                    AssetRecord.workspace_id == job.workspace_id,
                    AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
                    AssetRecord.deleted_at.is_(None),
                )
            )
            if asset is None:
                raise XingheAgentError(
                    "INPUT_ASSET_NOT_FOUND",
                    "An Amazon source asset is missing or outside the workspace.",
                )
            sources.append(
                SourceImage(
                    asset_id=asset.id,
                    group_key="amazon-product",
                    filename=asset.original_filename,
                    content_type=asset.content_type,
                    sha256=asset.sha256,
                    payload=b"",
                    source_role=relation.role,
                )
            )
        product_name = str(settings.get("product_name") or "").strip()
        language = _require_nonempty_string(settings.get("language"), "language")
        marketplace = _require_nonempty_string(
            settings.get("marketplace"), "marketplace"
        )
        information_parts: list[str] = []
        scalar_information_fields = (
            ("category", "Category"),
            ("target_buyer", "Target buyer"),
            ("listing_title", "Listing title"),
            ("listing_description", "Listing description"),
            ("a_plus_copy", "Existing A+ copy"),
            ("instruction", "User instruction"),
        )
        for key, label in scalar_information_fields:
            value = settings.get(key, "")
            if not isinstance(value, str):
                raise XingheAgentError(
                    "AGENT_CONFIGURATION_INVALID",
                    f"Amazon {key} must be a string.",
                )
            if value.strip():
                information_parts.append(f"{label}: {value.strip()}")
        list_information_fields = (
            ("bullet_points", "Bullet point"),
            ("product_facts", "Confirmed product fact"),
            ("parameters", "Confirmed parameter"),
            ("certifications_or_evidence", "Provided certification or evidence"),
            ("forbidden_claims", "HARD CONSTRAINT - forbidden claim"),
            ("brand_colors", "Brand color"),
            ("style_preferences", "Style preference"),
        )
        for key, label in list_information_fields:
            values = settings.get(key, [])
            if not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                raise XingheAgentError(
                    "AGENT_CONFIGURATION_INVALID",
                    f"Amazon {key} must be an array of strings.",
                )
            information_parts.extend(
                f"{label}: {value.strip()}" for value in values if value.strip()
            )
        information = tuple(information_parts)
        signature = canonical_hash(
            {
                "version": AMAZON_PLANNING_POLICY_VERSION,
                "base_url": self.base_url_signature.rstrip("/"),
                "planner_model": self.gateway.planner_model,
                "image_model": self.gateway.image_model,
                "skill_id": self.skill_id,
                "sources": [
                    {
                        "role": source.source_role,
                        "filename": source.filename,
                        "sha256": source.sha256,
                    }
                    for source in sources
                ],
                "input": dict(input_configuration),
                "settings": dict(settings),
            }
        )
        return (
            PlannerRequest(
                workspace_id=job.workspace_id,
                job_id=job.id,
                group_key="amazon-product",
                sources=tuple(sources),
                page_count=AMAZON_EXPECTED_ITEM_COUNT,
                language=language,
                product_name=product_name or "visible product from supplied images",
                product_information=information,
                platform_code=marketplace,
                size="amazon-canonical-multi-size-v1",
                idempotency_key=f"{job.id}:planner:amazon:{signature}",
                planning_profile="amazon_visual_suite",
            ),
        )

    def _authorize_planning(
        self,
        session: Session,
        job: JobRecord,
        requests: tuple[PlannerRequest, ...],
    ) -> None:
        registry = SkillManifestRegistry.bundled()
        registry.verify_source(self.skill_id, self.skill_root)
        if quota_enabled():
            reservation = session.scalar(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.job_id == job.id,
                    CreditReservationRecord.workspace_id == job.workspace_id,
                    CreditReservationRecord.status == "active",
                )
            )
            if reservation is None:
                raise XingheAgentError(
                    "BUDGET_RESERVATION_MISSING",
                    "An active credit reservation is required before planning.",
                )
        if self.gateway.provider_name == "tengli":
            try:
                require_provider_job_quota(session, job)
            except RuntimeError as exc:
                raise XingheAgentError(
                    "PROVIDER_QUOTA_RESERVATION_MISSING",
                    str(exc),
                ) from exc
        if not requests:
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "No product groups were available for planning.",
            )
        expected_min, expected_max = cost_range(
            requests[0].page_count,
            len(requests),
            self.medium_price_micros,
            self.high_price_micros,
        )
        if expected_max > self.budget_limit_micros:
            raise XingheAgentError(
                "BUDGET_LIMIT_EXCEEDED",
                "The maximum configured output cost exceeds the job budget.",
            )
        job.estimated_cost_min_micros = expected_min
        job.estimated_cost_max_micros = expected_max

    def _fail_reserved_unknown(
        self,
        session: Session,
        job: JobRecord,
        plan: JobPlanRecord,
    ) -> JobStatus:
        plan.validation_status = PlanValidationStatus.INVALID.value
        plan.validation_errors = [
            {
                "code": "PLANNER_OUTCOME_UNKNOWN",
                "message": "A reserved planner call has an unknown outcome.",
            }
        ]
        plan.validated_at = utc_now()
        job.error_code = "PLANNER_OUTCOME_UNKNOWN"
        job.error_message = "Planner outcome is unknown; the group failed closed."
        _fail_pending_items(
            session,
            job,
            job.error_code,
            job.error_message,
        )
        transition_job(job, JobStatus.FAILED, stage="planning_failed", progress=100)
        settle_credits(session, job, 0)
        session.commit()
        return JobStatus.FAILED

    def _fail_before_provider(
        self,
        session: Session,
        job: JobRecord,
        error: XingheAgentError,
    ) -> JobStatus:
        job.error_code = error.code
        job.error_message = str(error)
        _fail_pending_items(
            session,
            job,
            error.code,
            str(error),
        )
        transition_job(job, JobStatus.FAILED, stage="planning_failed", progress=100)
        settle_credits(session, job, 0)
        session.add(
            AuditEventRecord(
                workspace_id=job.workspace_id,
                action="xinghe.planning_rejected",
                resource_type="job",
                resource_id=job.id,
                request_id=job.id,
                details={
                    "error_code": error.code,
                    "provider_call_count": 0,
                },
            )
        )
        session.commit()
        return JobStatus.FAILED

    def _fail_planning(
        self,
        job_id: str,
        plan_id: str,
        error_code: str,
        error_message: str,
        results: Sequence[PlannerCallResult],
        *,
        error_path: str | None = None,
    ) -> JobStatus:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            plan = session.get(JobPlanRecord, plan_id, with_for_update=True)
            if job is None or plan is None:
                return JobStatus.FAILED
            self._fail_planning_locked(
                session,
                job,
                plan,
                error_code,
                error_message,
                results,
                error_path=error_path,
            )
            session.commit()
        return JobStatus.FAILED

    @staticmethod
    def _fail_planning_locked(
        session: Session,
        job: JobRecord,
        plan: JobPlanRecord,
        error_code: str,
        error_message: str,
        results: Sequence[PlannerCallResult],
        *,
        error_path: str | None = None,
    ) -> None:
        planner_usage = [_planner_usage_record(result) for result in results]
        planner_diagnostics = [
            _planner_diagnostics_record(result) for result in results
        ]
        failed_payload = {
            **dict(plan.payload),
            "state": "failed",
            "usage": {
                "planner": planner_usage,
                "image": {
                    "reported_requests": 0,
                    "unreported_requests": 0,
                },
            },
            "planner_diagnostics": planner_diagnostics,
            "planner_request_count": len(results),
            "image_request_count": 0,
        }
        plan.payload = failed_payload
        plan.payload_hash = canonical_hash(failed_payload)
        plan.validation_status = PlanValidationStatus.INVALID.value
        validation_error = {"code": error_code, "message": error_message}
        if error_path is not None:
            validation_error["path"] = error_path
        plan.validation_errors = [validation_error]
        plan.validated_at = utc_now()
        job.error_code = error_code
        job.error_message = error_message
        _fail_pending_items(
            session,
            job,
            error_code,
            error_message,
        )
        reported_count = sum(
            bool(result.normalized_usage["reported"]) for result in results
        )
        known_costs = [
            result.actual_cost_micros
            for result in results
            if result.actual_cost_micros is not None
        ]
        job.actual_cost_micros = (
            sum(known_costs) if results and len(known_costs) == len(results) else None
        )
        job.api_request_count = sum(
            isinstance(result.provider_request_id, str)
            and not result.provider_request_id.startswith("mock_")
            for result in results
        )
        job.usage_completeness = (
            UsageCompleteness.COMPLETE.value
            if results and reported_count == len(results)
            else (
                UsageCompleteness.PARTIAL.value
                if reported_count
                else UsageCompleteness.NONE.value
            )
        )
        if JobStatus(job.status) == JobStatus.PLANNING:
            transition_job(
                job,
                JobStatus.FAILED,
                stage="planning_failed",
                progress=100,
            )
        settle_credits(session, job, 0)
        session.add(
            AuditEventRecord(
                workspace_id=job.workspace_id,
                action="xinghe.planning_failed",
                resource_type="job",
                resource_id=job.id,
                request_id=plan.id,
                details={
                    "error_code": error_code,
                    **({"error_path": error_path} if error_path is not None else {}),
                    "planner_diagnostics": planner_diagnostics,
                    "planner_request_count": len(results),
                    "image_request_count": 0,
                },
            )
        )

    def _complete_planning(
        self,
        job_id: str,
        plan_id: str,
        requests: Sequence[PlannerRequest],
        results: Sequence[PlannerCallResult],
        validated: Sequence[dict[str, Any]],
    ) -> JobStatus:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            plan = session.get(JobPlanRecord, plan_id, with_for_update=True)
            if job is None or plan is None:
                return JobStatus.FAILED
            if JobStatus(job.status) != JobStatus.PLANNING:
                current = JobStatus(job.status)
                interrupted_payload = {
                    **dict(plan.payload),
                    "state": current.value,
                    "usage": {
                        "planner": [
                            _planner_usage_record(result) for result in results
                        ],
                        "image": {
                            "reported_requests": 0,
                            "unreported_requests": 0,
                        },
                    },
                    "planner_diagnostics": [
                        _planner_diagnostics_record(result) for result in results
                    ],
                    "image_request_count": 0,
                }
                plan.payload = interrupted_payload
                plan.payload_hash = canonical_hash(interrupted_payload)
                plan.validation_status = PlanValidationStatus.INVALID.value
                plan.validation_errors = [
                    {
                        "code": "PLANNING_INTERRUPTED",
                        "message": "Planning completed after the job stopped.",
                    }
                ]
                plan.validated_at = utc_now()
                session.commit()
                return current
            if job.type == JobType.AMAZON_VISUAL_SUITE.value:
                return self._complete_amazon_planning_locked(
                    session,
                    job,
                    plan,
                    requests,
                    results,
                    validated,
                )
            group_plans: list[dict[str, Any]] = []
            flattened_pages: list[dict[str, Any]] = []
            item_configurations: list[dict[str, Any]] = []
            all_signature_groups = [
                (
                    request.group_key,
                    (
                        tuple(
                            (
                                source.source_role,
                                source.filename,
                                source.sha256,
                            )
                            for source in request.sources
                        )
                        if request.domestic_protocol
                        else tuple(
                            (source.filename, source.sha256)
                            for source in request.sources
                        )
                    ),
                )
                for request in requests
            ]
            input_signature = build_resume_signature(
                groups=all_signature_groups,
                base_url=self.base_url_signature,
                planner_model=self.gateway.planner_model,
                image_model=self.gateway.image_model,
                page_count=requests[0].page_count,
                language=requests[0].language,
                product_name=requests[0].product_name,
                product_information=requests[0].product_information,
                platform_code=requests[0].platform_code,
                size=requests[0].size,
                medium_price_micros=self.medium_price_micros,
                high_price_micros=self.high_price_micros,
            )
            resume_signature = canonical_hash(
                {
                    "version": RESUME_SIGNATURE_VERSION,
                    "input_signature": input_signature,
                    "validated_plans": list(validated),
                }
            )
            for group_index, (request, structured) in enumerate(
                zip(requests, validated, strict=True),
                start=1,
            ):
                pages: list[dict[str, Any]] = []
                screens = structured["plan"]["screens"]
                for page_index, screen in enumerate(screens, start=1):
                    quality = quality_for_role(screen["role"])
                    prompt = compile_page_prompt(
                        structured_plan=structured,
                        screen=screen,
                        page_number=page_index,
                        page_count=request.page_count,
                        language=request.language,
                        product_name=request.product_name,
                        product_information=request.product_information,
                        source_count=len(request.sources),
                        size=request.size,
                        source_roles=(
                            tuple(source.source_role for source in request.sources)
                            if request.domestic_protocol
                            else None
                        ),
                        include_protocol_fields=request.domestic_protocol,
                    )
                    item_key = f"{request.group_key}:page-{page_index:03d}"
                    page = {
                        "item_key": item_key,
                        "group_key": request.group_key,
                        "page": page_index,
                        **screen,
                        "quality": quality,
                    }
                    pages.append(page)
                    flattened_pages.append(page)
                    item_configurations.append(
                        {
                            "workflow_version": WORKFLOW_VERSION,
                            "planning_policy_version": PLANNING_POLICY_VERSION,
                            "quality_policy_version": QUALITY_POLICY_VERSION,
                            "prompt_policy_version": PROMPT_POLICY_VERSION,
                            "resume_signature_version": RESUME_SIGNATURE_VERSION,
                            "resume_signature": resume_signature,
                            "group_key": request.group_key,
                            "group_index": group_index,
                            "page": page_index,
                            "page_count": request.page_count,
                            "quality": quality,
                            "prompt": prompt,
                            "source_assets": [
                                {
                                    "asset_id": source.asset_id,
                                    "filename": source.filename,
                                    "content_type": source.content_type,
                                    "sha256": source.sha256,
                                    **(
                                        {"role": source.source_role}
                                        if request.domestic_protocol
                                        else {}
                                    ),
                                }
                                for source in request.sources
                            ],
                            "size": request.size,
                            "output_format": IMAGE_FORMAT,
                            "jpeg_quality": JPEG_QUALITY,
                        }
                    )
                group_plans.append(
                    {
                        "group_key": request.group_key,
                        "analysis": structured["analysis"],
                        **(
                            {
                                "plan_protocol_fields": {
                                    key: value
                                    for key, value in structured["plan"].items()
                                    if key
                                    not in {
                                        "campaign_style_lock",
                                        "design_strength_lock",
                                        "screens",
                                    }
                                }
                            }
                            if request.domestic_protocol
                            else {}
                        ),
                        "campaign_style_lock": structured["plan"][
                            "campaign_style_lock"
                        ],
                        "design_strength_lock": structured["plan"][
                            "design_strength_lock"
                        ],
                        **(
                            {
                                "layout_diversity_lock": structured["plan"][
                                    "layout_diversity_lock"
                                ]
                            }
                            if "layout_diversity_lock" in structured["plan"]
                            else {}
                        ),
                        **(
                            {
                                "product_consistency_lock": structured["plan"][
                                    "product_consistency_lock"
                                ]
                            }
                            if "product_consistency_lock" in structured["plan"]
                            else {}
                        ),
                        "pages": pages,
                        "planner_usage": _planner_usage_record(
                            results[group_index - 1]
                        ),
                        "planning_time": results[group_index - 1].api_latency_seconds,
                    }
                )
            items = session.scalars(
                select(JobItemRecord)
                .where(JobItemRecord.job_id == job.id)
                .order_by(JobItemRecord.ordinal)
                .with_for_update()
            ).all()
            if len(items) != len(item_configurations):
                self._fail_planning_locked(
                    session,
                    job,
                    plan,
                    "AGENT_ITEM_COUNT_MISMATCH",
                    "Planned pages do not match the durable item count.",
                    results,
                )
                session.commit()
                return JobStatus.FAILED
            high_count = sum(item["quality"] == "high" for item in item_configurations)
            medium_count = len(item_configurations) - high_count
            estimated_pending_cost = (
                high_count * self.high_price_micros
                + medium_count * self.medium_price_micros
            )
            if estimated_pending_cost > self.budget_limit_micros:
                self._fail_planning_locked(
                    session,
                    job,
                    plan,
                    "BUDGET_LIMIT_EXCEEDED",
                    "The planned output cost exceeds the job budget.",
                    results,
                )
                session.commit()
                return JobStatus.FAILED
            for item, configuration in zip(
                items,
                item_configurations,
                strict=True,
            ):
                item.item_key = (
                    f"page-{item.ordinal + 1:03d}"
                    if len(requests) == 1
                    else (
                        f"group-{int(configuration['group_index']):02d}:"
                        f"page-{int(configuration['page']):03d}"
                    )
                )
                item.configuration = configuration
                item.quality = str(configuration["quality"])
                item.stage = "awaiting_confirmation"
            payload = {
                "workflow_version": WORKFLOW_VERSION,
                "state": "awaiting_confirmation",
                "requested_page_count": requests[0].page_count,
                "group_count": len(requests),
                "provider": {
                    "type": self.gateway.provider_name,
                    "planner_model": self.gateway.planner_model,
                    "image_model": self.gateway.image_model,
                    "pricing_version": self.gateway.pricing_version,
                },
                "groups": group_plans,
                "pages": flattened_pages,
                "input_signature": input_signature,
                "resume_signature": resume_signature,
                "controls": {
                    "automatic_reflection_rounds": 0,
                    "automatic_review_enabled": False,
                    "automatic_redraw_enabled": False,
                    "successful_page_auto_redraw_enabled": False,
                    "max_failed_page_retries": MAX_PAGE_RETRIES,
                },
                "cost": {
                    "currency": "USD",
                    "medium_unit_micros": self.medium_price_micros,
                    "high_unit_micros": self.high_price_micros,
                    "pending_medium_count": medium_count,
                    "pending_high_count": high_count,
                    "estimated_pending_micros": estimated_pending_cost,
                    "budget_limit_micros": self.budget_limit_micros,
                },
                "usage": {
                    "planner": [_planner_usage_record(result) for result in results],
                    "image": {
                        "reported_requests": 0,
                        "unreported_requests": 0,
                    },
                },
                "planner_diagnostics": [
                    _planner_diagnostics_record(result) for result in results
                ],
                "metrics": {
                    "planning_time": sum(
                        result.api_latency_seconds for result in results
                    ),
                    "image_wall_time": None,
                    "average_api_latency": None,
                    "effective_seconds_per_page": None,
                    "throughput_pages_per_second": 0.0,
                    "job_wall_time": None,
                    "success_count": 0,
                    "failure_count": 0,
                    "rate_limit_429_count": 0,
                    "actual_concurrency": 0,
                    "usage_missing_count": sum(
                        not result.normalized_usage["reported"] for result in results
                    ),
                },
            }
            plan.payload = payload
            plan.payload_hash = canonical_hash(payload)
            plan.validation_status = PlanValidationStatus.VALID.value
            plan.validation_errors = []
            plan.validated_at = utc_now()
            job.prompt_version = PROMPT_POLICY_VERSION
            job.strategy_version = PLANNING_POLICY_VERSION
            job.release_version = WORKFLOW_VERSION
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_confirmation",
                progress=15,
            )
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    action="xinghe.planning_completed",
                    resource_type="job",
                    resource_id=job.id,
                    request_id=plan.id,
                    details={
                        "group_count": len(requests),
                        "page_count": len(flattened_pages),
                        "high_count": high_count,
                        "medium_count": medium_count,
                        "estimated_pending_micros": estimated_pending_cost,
                        "planner_diagnostics": [
                            _planner_diagnostics_record(result) for result in results
                        ],
                    },
                )
            )
            session.commit()
            return JobStatus.AWAITING_CONFIRMATION

    def _complete_amazon_planning_locked(
        self,
        session: Session,
        job: JobRecord,
        plan: JobPlanRecord,
        requests: Sequence[PlannerRequest],
        results: Sequence[PlannerCallResult],
        validated: Sequence[dict[str, Any]],
    ) -> JobStatus:
        from .amazon_visual_suite_provider import (
            AMAZON_EXPECTED_ITEM_COUNT,
            AMAZON_ITEM_KEYS,
            AMAZON_PLAN_CONFIGURATION_KEY,
            AMAZON_PLANNING_POLICY_VERSION,
        )

        if len(requests) != 1 or len(validated) != 1:
            self._fail_planning_locked(
                session,
                job,
                plan,
                "AMAZON_PLANNER_REQUEST_COUNT_INVALID",
                "Amazon visual-suite planning requires exactly one planning call.",
                results,
            )
            session.commit()
            return JobStatus.FAILED
        request = requests[0]
        structured = validated[0]
        screens = structured["plan"]["screens"]
        items = session.scalars(
            select(JobItemRecord)
            .where(JobItemRecord.job_id == job.id)
            .order_by(JobItemRecord.ordinal)
            .with_for_update()
        ).all()
        if len(items) != AMAZON_EXPECTED_ITEM_COUNT or [
            item.item_key for item in items
        ] != list(AMAZON_ITEM_KEYS):
            self._fail_planning_locked(
                session,
                job,
                plan,
                "AMAZON_ITEM_INVENTORY_INVALID",
                "Durable Amazon items do not match the canonical inventory.",
                results,
            )
            session.commit()
            return JobStatus.FAILED
        input_signature = canonical_hash(
            {
                "version": AMAZON_PLANNING_POLICY_VERSION,
                "base_url": self.base_url_signature.rstrip("/"),
                "planner_model": self.gateway.planner_model,
                "image_model": self.gateway.image_model,
                "sources": [
                    {
                        "role": source.source_role,
                        "filename": source.filename,
                        "sha256": source.sha256,
                    }
                    for source in request.sources
                ],
                "language": request.language,
                "product_name": request.product_name,
                "product_information": list(request.product_information),
                "marketplace": request.platform_code,
                "item_keys": list(AMAZON_ITEM_KEYS),
            }
        )
        resume_signature = canonical_hash(
            {
                "version": AMAZON_PLANNING_POLICY_VERSION,
                "input_signature": input_signature,
                "structured_plan": structured,
            }
        )
        plan_context_base = {
            "schema_version": AMAZON_PLANNING_POLICY_VERSION,
            "analysis": structured["analysis"],
            "campaign_style_lock": structured["plan"]["campaign_style_lock"],
            "product_consistency_lock": structured["plan"]["product_consistency_lock"],
            "layout_diversity_lock": structured["plan"]["layout_diversity_lock"],
            "input_signature": input_signature,
            "resume_signature": resume_signature,
        }
        for item, screen in zip(items, screens, strict=True):
            configuration = dict(item.configuration)
            configuration.update(
                {
                    "workflow_version": AMAZON_PLANNING_POLICY_VERSION,
                    "planning_policy_version": AMAZON_PLANNING_POLICY_VERSION,
                    "resume_signature": resume_signature,
                    "quality": "high",
                    AMAZON_PLAN_CONFIGURATION_KEY: {
                        **plan_context_base,
                        "screen": screen,
                    },
                }
            )
            item.configuration = configuration
            item.quality = "high"
            item.stage = "awaiting_confirmation"
            item.state_version += 1
        estimated_pending_cost = AMAZON_EXPECTED_ITEM_COUNT * self.high_price_micros
        payload = {
            "workflow_version": AMAZON_PLANNING_POLICY_VERSION,
            "state": "awaiting_confirmation",
            "requested_page_count": AMAZON_EXPECTED_ITEM_COUNT,
            "group_count": 1,
            "provider": {
                "type": self.gateway.provider_name,
                "planner_model": self.gateway.planner_model,
                "image_model": self.gateway.image_model,
                "pricing_version": self.gateway.pricing_version,
            },
            "groups": [
                {
                    "group_key": "amazon-product",
                    "analysis": structured["analysis"],
                    "campaign_style_lock": structured["plan"]["campaign_style_lock"],
                    "product_consistency_lock": structured["plan"][
                        "product_consistency_lock"
                    ],
                    "layout_diversity_lock": structured["plan"][
                        "layout_diversity_lock"
                    ],
                    "pages": screens,
                    "planner_usage": _planner_usage_record(results[0]),
                    "planning_time": results[0].api_latency_seconds,
                }
            ],
            "pages": screens,
            "input_signature": input_signature,
            "resume_signature": resume_signature,
            "controls": {
                "automatic_review_enabled": True,
                "automatic_redraw_enabled": True,
                "successful_page_auto_redraw_enabled": False,
                "max_suite_review_rounds": 2,
                "manual_confirmation_required": True,
            },
            "business_quality": {
                "status": "pending_generation",
                "policy_version": AMAZON_PLANNING_POLICY_VERSION,
                "technical_delivery_status": "pending",
                "manual_review_required": False,
                "automatic_redraw_enabled": True,
                "deterministic_findings": [],
                "visual_review": None,
                "qa_notes": [],
                "missing_evidence": [],
                "failed_item_keys": [],
                "review_round": 0,
                "contact_sheet_asset_id": None,
                "generation_routes": [],
            },
            "cost": {
                "currency": "USD",
                "medium_unit_micros": self.medium_price_micros,
                "high_unit_micros": self.high_price_micros,
                "pending_medium_count": 0,
                "pending_high_count": AMAZON_EXPECTED_ITEM_COUNT,
                "estimated_pending_micros": estimated_pending_cost,
                "budget_limit_micros": self.budget_limit_micros,
            },
            "usage": {
                "planner": [_planner_usage_record(results[0])],
                "image": {"reported_requests": 0, "unreported_requests": 0},
            },
            "planner_diagnostics": [_planner_diagnostics_record(results[0])],
            "metrics": {
                "planning_time": results[0].api_latency_seconds,
                "image_wall_time": None,
                "average_api_latency": None,
                "effective_seconds_per_page": None,
                "job_wall_time": None,
                "success_count": 0,
                "failure_count": 0,
                "rate_limit_429_count": 0,
                "actual_concurrency": 0,
                "usage_missing_count": int(not results[0].normalized_usage["reported"]),
            },
        }
        plan.payload = payload
        plan.payload_hash = canonical_hash(payload)
        plan.validation_status = PlanValidationStatus.VALID.value
        plan.validation_errors = []
        plan.validated_at = utc_now()
        job.prompt_version = AMAZON_PLANNING_POLICY_VERSION
        job.strategy_version = AMAZON_PLANNING_POLICY_VERSION
        job.release_version = AMAZON_PLANNING_POLICY_VERSION
        transition_job(
            job,
            JobStatus.AWAITING_CONFIRMATION,
            stage="awaiting_confirmation",
            progress=15,
        )
        session.add(
            AuditEventRecord(
                workspace_id=job.workspace_id,
                action="amazon_visual_suite.planning_completed",
                resource_type="job",
                resource_id=job.id,
                request_id=plan.id,
                details={
                    "page_count": AMAZON_EXPECTED_ITEM_COUNT,
                    "high_count": AMAZON_EXPECTED_ITEM_COUNT,
                    "estimated_pending_micros": estimated_pending_cost,
                    "manual_confirmation_required": True,
                },
            )
        )
        session.commit()
        return JobStatus.AWAITING_CONFIRMATION


class XingheImageProvider:
    """Per-page provider with durable pre-call authorization and audit."""

    name = "xinghe"

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: XingheGateway,
        *,
        storage: ImageStorage | None,
        skill_root: Path,
        max_concurrency: int,
        budget_limit_micros: int = DEFAULT_BUDGET_LIMIT_MICROS,
        skill_id: str = "xinghe-ecommerce-detail",
    ) -> None:
        if max_concurrency not in {1, 2, 6}:
            raise ValueError("Xinghe concurrency must be one of 1, 2, or 6.")
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.skill_root = skill_root
        self.max_concurrency = max_concurrency
        self.budget_limit_micros = budget_limit_micros
        self.skill_id = skill_id
        self.model = gateway.image_model
        self.pricing_version = gateway.pricing_version
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._activity_lock = asyncio.Lock()
        self._active_requests = 0

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        try:
            configuration, sources = self._authorize(request)
            sources = await self._load_sources(request.workspace_id, sources)
        except (XingheAgentError, SkillRuntimeError) as exc:
            code = exc.code
            return _provider_rejection(code, str(exc), self.gateway)
        except Exception as exc:
            return _provider_rejection(
                "AUDIT_WRITE_FAILED",
                f"Image authorization audit failed ({type(exc).__name__}).",
                self.gateway,
            )
        image_request = ImageEditRequest(
            workspace_id=request.workspace_id,
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            attempt_id=request.attempt_id,
            page_number=int(configuration["page"]),
            group_key=str(configuration["group_key"]),
            sources=sources,
            prompt=str(configuration["prompt"]),
            quality=str(configuration["quality"]),
            idempotency_key=request.idempotency_key,
            size=str(configuration["size"]),
        )
        async with self._semaphore:
            try:
                self._reserve_call_budget(
                    request,
                    configuration,
                    source_count=len(sources),
                    source_roles=tuple(source.source_role for source in sources),
                )
            except XingheAgentError as exc:
                return _provider_rejection(exc.code, str(exc), self.gateway)
            except Exception as exc:
                return _provider_rejection(
                    "AUDIT_WRITE_FAILED",
                    (f"Image budget reservation audit failed ({type(exc).__name__})."),
                    self.gateway,
                )
            async with self._activity_lock:
                self._active_requests += 1
                active_concurrency = self._active_requests
            try:
                started_at = datetime.now(UTC)
                try:
                    result = await self.gateway.edit(image_request)
                except Exception as exc:
                    result = ImageCallResult(
                        outcome=ProviderOutcome.FAILED,
                        provider_request_id=None,
                        raw_usage=None,
                        normalized_usage=normalize_usage(None),
                        api_latency_seconds=(
                            datetime.now(UTC) - started_at
                        ).total_seconds(),
                        actual_cost_micros=None,
                        error_code="IMAGE_PROVIDER_FAILED",
                        error_message=(
                            f"Image provider failed ({type(exc).__name__})."
                        ),
                        retryable=False,
                    )
                finished_at = datetime.now(UTC)
                result = replace(
                    result,
                    active_concurrency=max(
                        result.active_concurrency,
                        active_concurrency,
                    ),
                )
            finally:
                async with self._activity_lock:
                    self._active_requests -= 1
        raw_usage = _image_usage_record(
            result,
            source_count=len(sources),
            started_at=started_at,
            finished_at=finished_at,
        )
        try:
            self._record_completion(request, result)
        except Exception as exc:
            return ProviderResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id=result.provider_request_id,
                error_code="AUDIT_WRITE_FAILED",
                error_message=(
                    "Provider completed but the completion audit failed "
                    f"({type(exc).__name__})."
                ),
                usage_reported=bool(result.normalized_usage["reported"]),
                raw_usage=raw_usage,
                estimated_cost_micros=result.estimated_cost_micros,
                actual_cost_micros=result.actual_cost_micros,
                retryable=False,
                http_status=result.http_status,
                artifact=None,
                provider_name=self.gateway.provider_name,
                model_name=self.gateway.image_model,
                pricing_version=self.gateway.pricing_version,
            )
        return ProviderResult(
            outcome=result.outcome,
            provider_request_id=result.provider_request_id,
            error_code=result.error_code,
            error_message=result.error_message,
            usage_reported=bool(result.normalized_usage["reported"]),
            raw_usage=raw_usage,
            estimated_cost_micros=result.estimated_cost_micros,
            actual_cost_micros=result.actual_cost_micros,
            retryable=result.retryable,
            http_status=result.http_status,
            artifact=result.artifact,
            provider_name=self.gateway.provider_name,
            model_name=self.gateway.image_model,
            pricing_version=self.gateway.pricing_version,
        )

    def _authorize(
        self,
        request: ProviderRequest,
    ) -> tuple[dict[str, Any], tuple[SourceImage, ...]]:
        SkillManifestRegistry.bundled().verify_source(
            self.skill_id,
            self.skill_root,
        )
        item_configuration = _require_mapping(
            request.configuration.get("item"),
            "AGENT_CONFIGURATION_INVALID",
        )
        domestic_protocol = self.skill_id == "xinghe-ecommerce-detail-domestic-3"
        _validate_item_configuration(
            item_configuration,
            require_source_roles=domestic_protocol,
        )
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id, with_for_update=True)
            item = session.get(
                JobItemRecord,
                request.job_item_id,
                with_for_update=True,
            )
            attempt = session.get(
                JobAttemptRecord,
                request.attempt_id,
                with_for_update=True,
            )
            plan = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == request.job_id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                job is None
                or item is None
                or attempt is None
                or plan is None
                or job.workspace_id != request.workspace_id
                or item.workspace_id != request.workspace_id
                or attempt.workspace_id != request.workspace_id
                or item.job_id != job.id
                or attempt.job_item_id != item.id
            ):
                raise XingheAgentError(
                    "WORKSPACE_SCOPE_MISMATCH",
                    "The image request is outside its durable workspace scope.",
                )
            if (
                JobStatus(job.status) != JobStatus.PROCESSING
                or plan.validation_status != PlanValidationStatus.VALID.value
                or plan.confirmed_at is None
            ):
                raise XingheAgentError(
                    "PLAN_NOT_CONFIRMED",
                    "A validated, confirmed plan is required before image calls.",
                )
            if quota_enabled():
                reservation = session.scalar(
                    select(CreditReservationRecord).where(
                        CreditReservationRecord.job_id == job.id,
                        CreditReservationRecord.workspace_id == job.workspace_id,
                        CreditReservationRecord.status == "active",
                    )
                )
                if reservation is None:
                    raise XingheAgentError(
                        "BUDGET_RESERVATION_MISSING",
                        "An active budget reservation is required before image calls.",
                    )
            if (
                job.estimated_cost_max_micros is None
                or job.estimated_cost_max_micros > self.budget_limit_micros
            ):
                raise XingheAgentError(
                    "BUDGET_LIMIT_EXCEEDED",
                    "The durable maximum cost is outside the job budget.",
                )
            source_records = item_configuration["source_assets"]
            durable_roles = (
                {
                    (relation.asset_id, relation.role)
                    for relation in session.scalars(
                        select(JobAssetRecord).where(
                            JobAssetRecord.workspace_id == job.workspace_id,
                            JobAssetRecord.job_id == job.id,
                            JobAssetRecord.job_item_id.is_(None),
                            JobAssetRecord.direction == JobAssetDirection.INPUT.value,
                        )
                    ).all()
                }
                if domestic_protocol
                else set()
            )
            sources: list[SourceImage] = []
            for source_value in source_records:
                source = _require_mapping(
                    source_value,
                    "AGENT_CONFIGURATION_INVALID",
                )
                asset_id = _require_nonempty_string(
                    source.get("asset_id"),
                    "asset_id",
                )
                source_role = (
                    _require_nonempty_string(source.get("role"), "role")
                    if domestic_protocol
                    else "product_reference"
                )
                if (
                    domestic_protocol
                    and (
                        asset_id,
                        source_role,
                    )
                    not in durable_roles
                ):
                    raise XingheAgentError(
                        "RESUME_SIGNATURE_INVALID",
                        "A planned source role no longer matches its durable binding.",
                    )
                asset = session.scalar(
                    select(AssetRecord).where(
                        AssetRecord.id == asset_id,
                        AssetRecord.workspace_id == job.workspace_id,
                        AssetRecord.lifecycle_status
                        == AssetLifecycleStatus.READY.value,
                        AssetRecord.deleted_at.is_(None),
                    )
                )
                if (
                    asset is None
                    or asset.sha256 != source.get("sha256")
                    or asset.original_filename != source.get("filename")
                ):
                    raise XingheAgentError(
                        "RESUME_SIGNATURE_INVALID",
                        "A source asset no longer matches the planned input.",
                    )
                sources.append(
                    SourceImage(
                        asset_id=asset.id,
                        group_key=str(item_configuration["group_key"]),
                        filename=asset.original_filename,
                        content_type=asset.content_type,
                        sha256=asset.sha256,
                        payload=b"",
                        source_role=source_role,
                    )
                )
            return dict(item_configuration), tuple(sources)

    def _reserve_call_budget(
        self,
        request: ProviderRequest,
        configuration: Mapping[str, Any],
        *,
        source_count: int,
        source_roles: Sequence[str] = (),
    ) -> None:
        """Atomically reserve one attempt's worst-case image-call exposure."""

        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id, with_for_update=True)
            item = session.get(
                JobItemRecord,
                request.job_item_id,
                with_for_update=True,
            )
            attempt = session.get(
                JobAttemptRecord,
                request.attempt_id,
                with_for_update=True,
            )
            plan = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == request.job_id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                job is None
                or item is None
                or attempt is None
                or plan is None
                or job.workspace_id != request.workspace_id
                or item.workspace_id != request.workspace_id
                or attempt.workspace_id != request.workspace_id
                or item.job_id != job.id
                or attempt.job_item_id != item.id
            ):
                raise XingheAgentError(
                    "WORKSPACE_SCOPE_MISMATCH",
                    "The image request is outside its durable workspace scope.",
                )
            if (
                JobStatus(job.status) != JobStatus.PROCESSING
                or JobItemStatus(item.status) != JobItemStatus.RUNNING
                or AttemptStatus(attempt.status) != AttemptStatus.RUNNING
                or plan.validation_status != PlanValidationStatus.VALID.value
                or plan.confirmed_at is None
            ):
                raise XingheAgentError(
                    "IMAGE_CALL_NOT_AUTHORIZED",
                    "The durable attempt is not authorized for an image call.",
                )
            if quota_enabled():
                reservation = session.scalar(
                    select(CreditReservationRecord).where(
                        CreditReservationRecord.job_id == job.id,
                        CreditReservationRecord.workspace_id == job.workspace_id,
                        CreditReservationRecord.status == "active",
                    )
                )
                if reservation is None:
                    raise XingheAgentError(
                        "BUDGET_RESERVATION_MISSING",
                        "An active budget reservation is required before image calls.",
                    )
            if self.gateway.provider_name == "tengli":
                try:
                    require_provider_job_quota(session, job)
                except RuntimeError as exc:
                    raise XingheAgentError(
                        "PROVIDER_QUOTA_RESERVATION_MISSING",
                        str(exc),
                    ) from exc
            existing = session.scalar(
                select(AuditEventRecord.id)
                .where(
                    AuditEventRecord.workspace_id == job.workspace_id,
                    AuditEventRecord.action == "xinghe.image_reserved",
                    AuditEventRecord.request_id == attempt.id,
                )
                .limit(1)
            )
            if existing is not None:
                raise XingheAgentError(
                    "IMAGE_CALL_ALREADY_RESERVED",
                    "This durable attempt already reserved an image call.",
                )

            quality = str(configuration["quality"])
            current_exposure = _configured_image_unit_cost(plan.payload, quality)
            prior_reservations = session.scalars(
                select(AuditEventRecord)
                .join(
                    JobAttemptRecord,
                    AuditEventRecord.request_id == JobAttemptRecord.id,
                )
                .where(
                    JobAttemptRecord.job_id == job.id,
                    AuditEventRecord.workspace_id == job.workspace_id,
                    AuditEventRecord.action == "xinghe.image_reserved",
                )
                .order_by(AuditEventRecord.id)
            ).all()
            prior_exposure = sum(
                _reserved_image_exposure(event.details, plan.payload)
                for event in prior_reservations
            )
            planner_cost = _known_planner_actual_cost(plan.payload)
            cumulative_exposure = planner_cost + prior_exposure + current_exposure
            audit_details = {
                "attempt_no": attempt.attempt_no,
                "page": int(configuration["page"]),
                "quality": quality,
                "source_count": source_count,
                "provider_type": self.gateway.provider_name,
                "estimated_cost_micros": current_exposure,
                "prior_reserved_exposure_micros": prior_exposure,
                "known_planner_cost_micros": planner_cost,
                "cumulative_exposure_micros": cumulative_exposure,
                "budget_limit_micros": self.budget_limit_micros,
                "idempotency_key_sha256": hashlib.sha256(
                    request.idempotency_key.encode()
                ).hexdigest(),
                **(
                    {
                        "source_role_counts": {
                            role: source_roles.count(role)
                            for role in sorted(set(source_roles))
                        }
                    }
                    if self.skill_id == "xinghe-ecommerce-detail-domestic-3"
                    else {}
                ),
            }
            if cumulative_exposure > self.budget_limit_micros:
                session.add(
                    AuditEventRecord(
                        workspace_id=job.workspace_id,
                        action="xinghe.image_budget_rejected",
                        resource_type="job_item",
                        resource_id=item.id,
                        request_id=attempt.id,
                        details=audit_details,
                    )
                )
                session.commit()
                raise XingheAgentError(
                    "BUDGET_LIMIT_EXCEEDED",
                    "The cumulative image-call exposure exceeds the job budget.",
                )
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    action="xinghe.image_reserved",
                    resource_type="job_item",
                    resource_id=item.id,
                    request_id=attempt.id,
                    details=audit_details,
                )
            )
            session.commit()

    async def _load_sources(
        self,
        workspace_id: str,
        sources: tuple[SourceImage, ...],
    ) -> tuple[SourceImage, ...]:
        if self.storage is None:
            if self.gateway.provider_name != "mock":
                raise XingheAgentError(
                    "SOURCE_STORAGE_UNAVAILABLE",
                    "Source storage is required for the configured provider.",
                )
            return sources
        with self.session_factory() as session:
            assets = {
                asset.id: asset
                for asset in session.scalars(
                    select(AssetRecord).where(
                        AssetRecord.workspace_id == workspace_id,
                        AssetRecord.id.in_([source.asset_id for source in sources]),
                    )
                ).all()
            }
        loaded: list[SourceImage] = []
        for source in sources:
            asset = assets.get(source.asset_id)
            if asset is None:
                raise XingheAgentError(
                    "INPUT_ASSET_NOT_FOUND",
                    "A planned source image is missing.",
                )
            try:
                payload = await self.storage.read_bytes(asset.object_key)
            except Exception as exc:
                raise XingheAgentError(
                    "SOURCE_READ_FAILED",
                    f"Source image could not be read ({type(exc).__name__}).",
                ) from exc
            if not payload or hashlib.sha256(payload).hexdigest() != source.sha256:
                raise XingheAgentError(
                    "SOURCE_HASH_MISMATCH",
                    "Source image bytes no longer match the plan.",
                )
            loaded.append(
                SourceImage(
                    asset_id=source.asset_id,
                    group_key=source.group_key,
                    filename=source.filename,
                    content_type=source.content_type,
                    sha256=source.sha256,
                    payload=payload,
                    source_role=source.source_role,
                )
            )
        return tuple(loaded)

    def _record_completion(
        self,
        request: ProviderRequest,
        result: ImageCallResult,
    ) -> None:
        with self.session_factory() as session:
            session.add(
                AuditEventRecord(
                    workspace_id=request.workspace_id,
                    action="xinghe.image_provider_completed",
                    resource_type="job_item",
                    resource_id=request.job_item_id,
                    request_id=request.attempt_id,
                    details={
                        "outcome": result.outcome.value,
                        "usage_reported": bool(result.normalized_usage["reported"]),
                        "http_status": result.http_status,
                        "rate_limited": result.rate_limited,
                        "actual_cost_micros": result.actual_cost_micros,
                    },
                )
            )
            session.commit()


class OperationRoutingProvider:
    """Keep provider-specific behavior outside the durable coordinator."""

    name = "mock"
    model = "operation-router-v1"
    pricing_version = "operation-router-v1"

    def __init__(
        self,
        default_provider: Provider,
        detail_provider: Provider,
        local_provider: Provider | None = None,
    ) -> None:
        self.default_provider = default_provider
        self.detail_provider = detail_provider
        self.local_provider = local_provider or default_provider

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if request.operation == "detail_pack":
            return await self.detail_provider.execute(request)
        if request.operation == "local_edit":
            return await self.local_provider.execute(request)
        return await self.default_provider.execute(request)


def validate_editable_plan_payload(
    payload: Mapping[str, Any],
    expected_item_count: int,
) -> list[dict[str, Any]]:
    """Validate editable Agent fields without changing the API error contract."""

    errors: list[dict[str, Any]] = []
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return [{"field": "pages", "message": "pages must be an array."}]
    if len(pages) != expected_item_count:
        errors.append(
            {
                "field": "pages",
                "message": "Plan page count must match the job.",
                "expected": expected_item_count,
                "actual": len(pages),
            }
        )
    page_keys: set[tuple[str, int]] = set()
    for index, page_value in enumerate(pages):
        if not isinstance(page_value, dict):
            errors.append(
                {
                    "field": f"pages.{index}",
                    "message": "Each page must be an object.",
                }
            )
            continue
        for key in (
            "group_key",
            "page",
            "role",
            "title",
            "label",
            "composition",
            "device",
            "difference",
            "structure",
            "subject_scale",
        ):
            value = page_value.get(key)
            if key == "page":
                valid = (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 1
                )
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                errors.append(
                    {
                        "field": f"pages.{index}.{key}",
                        "message": "Required planned page field is invalid.",
                    }
                )
        group_key = page_value.get("group_key")
        page_number = page_value.get("page")
        if isinstance(group_key, str) and isinstance(page_number, int):
            page_key = (group_key, page_number)
            if page_key in page_keys:
                errors.append(
                    {
                        "field": f"pages.{index}",
                        "message": "Planned group/page pairs must be unique.",
                    }
                )
            page_keys.add(page_key)
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        errors.append(
            {
                "field": "groups",
                "message": "Structured product-group plans are required.",
            }
        )
    else:
        group_keys: set[str] = set()
        for index, group_value in enumerate(groups):
            if not isinstance(group_value, dict):
                errors.append(
                    {
                        "field": f"groups.{index}",
                        "message": "Each product-group plan must be an object.",
                    }
                )
                continue
            group_key = group_value.get("group_key")
            if not isinstance(group_key, str) or not group_key.strip():
                errors.append(
                    {
                        "field": f"groups.{index}.group_key",
                        "message": "Product-group key is required.",
                    }
                )
            elif group_key in group_keys:
                errors.append(
                    {
                        "field": f"groups.{index}.group_key",
                        "message": "Product-group keys must be unique.",
                    }
                )
            else:
                group_keys.add(group_key)
            if not isinstance(group_value.get("analysis"), dict):
                errors.append(
                    {
                        "field": f"groups.{index}.analysis",
                        "message": "Product analysis is required.",
                    }
                )
            for key in ("campaign_style_lock", "design_strength_lock"):
                value = group_value.get(key)
                if not isinstance(value, (str, dict)) or not value:
                    errors.append(
                        {
                            "field": f"groups.{index}.{key}",
                            "message": "The planning lock is required.",
                        }
                    )
    input_signature = payload.get("input_signature")
    if not _is_sha256(input_signature):
        errors.append(
            {
                "field": "input_signature",
                "message": "The output-input signature is invalid.",
            }
        )
    return errors


def synchronize_confirmed_plan(
    session: Session,
    job: JobRecord,
    plan: JobPlanRecord,
) -> None:
    """Apply the latest user-edited plan to durable page items before dispatch."""

    if job.type != JobType.DETAIL_PACK.value:
        return
    errors = validate_editable_plan_payload(
        plan.payload,
        job.expected_item_count,
    )
    if errors:
        raise XingheAgentError(
            "PLAN_INVALID",
            "The editable Agent plan is invalid.",
        )
    payload = dict(plan.payload)
    pages = payload["pages"]
    groups = payload["groups"]
    group_lookup = {
        str(group["group_key"]): group
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("group_key"), str)
    }
    domestic_protocol = any(
        isinstance(group, dict) and "plan_protocol_fields" in group for group in groups
    )
    output_plan_signature = canonical_hash(
        {
            "version": RESUME_SIGNATURE_VERSION,
            "input_signature": payload["input_signature"],
            "groups": [
                {
                    "group_key": group.get("group_key"),
                    "analysis": group.get("analysis"),
                    **(
                        {"plan_protocol_fields": group.get("plan_protocol_fields")}
                        if domestic_protocol
                        else {}
                    ),
                    "campaign_style_lock": group.get("campaign_style_lock"),
                    "design_strength_lock": group.get("design_strength_lock"),
                    "layout_diversity_lock": group.get("layout_diversity_lock"),
                    "product_consistency_lock": group.get("product_consistency_lock"),
                }
                for group in groups
                if isinstance(group, dict)
            ],
            "pages": pages,
        }
    )
    items = session.scalars(
        select(JobItemRecord)
        .where(JobItemRecord.job_id == job.id)
        .order_by(JobItemRecord.ordinal)
        .with_for_update()
    ).all()
    high_count = 0
    for item, page_value in zip(items, pages, strict=True):
        page = dict(page_value)
        group_key = str(page["group_key"])
        group = group_lookup.get(group_key)
        if group is None:
            raise XingheAgentError(
                "PLAN_INVALID",
                "A page references a missing product-group plan.",
            )
        analysis_value = group.get("analysis")
        safe_analysis = (
            _bounded_protocol_mapping(
                _require_mapping(
                    analysis_value,
                    "PLANNER_SCHEMA_INVALID",
                ),
                path="/analysis",
            )
            if domestic_protocol
            else analysis_value
        )
        plan_protocol_value = group.get("plan_protocol_fields")
        safe_plan_protocol = (
            _bounded_protocol_mapping(
                plan_protocol_value,
                path="/plan",
            )
            if domestic_protocol and isinstance(plan_protocol_value, Mapping)
            else {}
        )
        prompt_page = (
            _bounded_protocol_mapping(page, path="/screen")
            if domestic_protocol
            else page
        )
        structured = {
            "analysis": safe_analysis,
            "plan": {
                **safe_plan_protocol,
                "campaign_style_lock": group.get("campaign_style_lock"),
                "design_strength_lock": group.get("design_strength_lock"),
                "layout_diversity_lock": group.get("layout_diversity_lock", {}),
                "product_consistency_lock": group.get("product_consistency_lock", {}),
            },
        }
        existing = dict(item.configuration)
        quality = quality_for_role(str(page["role"]))
        high_count += int(quality == "high")
        existing.update(
            {
                "resume_signature": output_plan_signature,
                "quality": quality,
                "prompt": compile_page_prompt(
                    structured_plan=structured,
                    screen=prompt_page,
                    page_number=int(page["page"]),
                    page_count=int(existing["page_count"]),
                    language=str(
                        _require_mapping(
                            job.configuration.get("settings"),
                            "AGENT_CONFIGURATION_INVALID",
                        )["language"]
                    ),
                    product_name=str(
                        _require_mapping(
                            job.configuration.get("settings"),
                            "AGENT_CONFIGURATION_INVALID",
                        )["product_name"]
                    ),
                    product_information=tuple(
                        _require_mapping(
                            job.configuration.get("settings"),
                            "AGENT_CONFIGURATION_INVALID",
                        ).get("selling_points", [])
                    ),
                    source_count=len(existing["source_assets"]),
                    size=str(existing["size"]),
                    source_roles=(
                        tuple(
                            str(source.get("role"))
                            for source in existing["source_assets"]
                            if isinstance(source, Mapping)
                        )
                        if domestic_protocol
                        else None
                    ),
                    include_protocol_fields=domestic_protocol,
                ),
            }
        )
        item.configuration = existing
        item.quality = quality
        item.stage = "queued"
        item.state_version += 1
    medium_count = len(items) - high_count
    cost_value = payload.get("cost")
    cost = dict(cost_value) if isinstance(cost_value, dict) else {}
    medium_price = int(cost.get("medium_unit_micros", DEFAULT_MEDIUM_PRICE_MICROS))
    high_price = int(cost.get("high_unit_micros", DEFAULT_HIGH_PRICE_MICROS))
    cost.update(
        {
            "pending_medium_count": medium_count,
            "pending_high_count": high_count,
            "estimated_pending_micros": (
                medium_count * medium_price + high_count * high_price
            ),
        }
    )
    payload["cost"] = cost
    payload["resume_signature"] = output_plan_signature
    payload["state"] = "confirmed"
    plan.payload = payload
    plan.payload_hash = canonical_hash(payload)


def update_job_metrics(session: Session, job: JobRecord) -> None:
    """Persist Agent metrics in the existing plan JSON without a migration."""

    if job.type not in {
        JobType.DETAIL_PACK.value,
        JobType.AMAZON_VISUAL_SUITE.value,
    }:
        return
    plan = session.scalar(
        select(JobPlanRecord)
        .where(JobPlanRecord.job_id == job.id)
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
        .with_for_update()
    )
    if plan is None:
        return
    usage_events = session.scalars(
        select(UsageEventRecord)
        .where(UsageEventRecord.job_id == job.id)
        .order_by(UsageEventRecord.occurred_at)
    ).all()
    latencies: list[float] = []
    starts: list[datetime] = []
    finishes: list[datetime] = []
    successes = 0
    failures = 0
    rate_limits = 0
    missing_usage = 0
    actual_concurrency = 0
    image_usage: list[dict[str, Any]] = []
    for event in usage_events:
        record = dict(event.raw_usage)
        metrics_value = record.get("metrics")
        metrics = metrics_value if isinstance(metrics_value, dict) else {}
        latency = metrics.get("request_api_latency")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            latencies.append(float(latency))
        started_at = _parse_datetime(metrics.get("started_at"))
        finished_at = _parse_datetime(
            metrics.get("saved_at", metrics.get("finished_at"))
        )
        if started_at is not None:
            starts.append(started_at)
        if finished_at is not None:
            finishes.append(finished_at)
        status = metrics.get("http_status")
        rate_limits += int(status == 429)
        outcome = metrics.get("outcome")
        successes += int(outcome == ProviderOutcome.SUCCEEDED.value)
        failures += int(outcome != ProviderOutcome.SUCCEEDED.value)
        actual_concurrency = max(
            actual_concurrency,
            int(metrics.get("active_concurrency") or 0),
        )
        missing_usage += int(not event.usage_reported)
        image_usage.append(
            {
                "attempt_id": event.attempt_id,
                "raw": record.get("raw"),
                "normalized": record.get("normalized"),
                "reported": event.usage_reported,
            }
        )
    image_wall_time = (
        (max(finishes) - min(starts)).total_seconds() if starts and finishes else None
    )
    completed_pages = successes
    throughput_pages_per_second = (
        completed_pages / image_wall_time
        if completed_pages > 0 and image_wall_time is not None and image_wall_time > 0
        else 0.0
    )
    payload = dict(plan.payload)
    previous_metrics = payload.get("metrics")
    metrics = dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
    metrics.update(
        {
            "average_api_latency": (
                sum(latencies) / len(latencies) if latencies else None
            ),
            "image_wall_time": image_wall_time,
            "effective_seconds_per_page": (
                image_wall_time / completed_pages
                if image_wall_time is not None and completed_pages
                else None
            ),
            "throughput_pages_per_second": throughput_pages_per_second,
            "job_wall_time": (
                _elapsed_seconds(job.started_at, utc_now())
                if job.started_at is not None
                else None
            ),
            "success_count": successes,
            "failure_count": failures,
            "rate_limit_429_count": rate_limits,
            "actual_concurrency": actual_concurrency,
            "usage_missing_count": missing_usage + _planner_usage_missing(payload),
        }
    )
    usage_value = payload.get("usage")
    usage_payload = dict(usage_value) if isinstance(usage_value, dict) else {}
    usage_payload["image"] = {
        "requests": image_usage,
        "reported_requests": len(image_usage) - missing_usage,
        "unreported_requests": missing_usage,
    }
    payload["metrics"] = metrics
    payload["usage"] = usage_payload
    payload["state"] = JobStatus(job.status).value
    plan.payload = payload
    plan.payload_hash = canonical_hash(payload)


def _configured_image_unit_cost(
    plan_payload: Mapping[str, Any],
    quality: str,
) -> int:
    cost_value = plan_payload.get("cost")
    if not isinstance(cost_value, Mapping):
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "The confirmed plan has no valid cost configuration.",
        )
    key = "high_unit_micros" if quality == "high" else "medium_unit_micros"
    value = cost_value.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "The confirmed plan has an invalid image unit cost.",
        )
    return value


def _reserved_image_exposure(
    audit_details: Mapping[str, Any],
    plan_payload: Mapping[str, Any],
) -> int:
    value = audit_details.get("estimated_cost_micros")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    quality = audit_details.get("quality")
    if quality not in {"medium", "high"}:
        raise XingheAgentError(
            "BUDGET_RESERVATION_INVALID",
            "A prior image-call reservation has invalid cost metadata.",
        )
    return _configured_image_unit_cost(plan_payload, str(quality))


def _known_planner_actual_cost(plan_payload: Mapping[str, Any]) -> int:
    usage_value = plan_payload.get("usage")
    if not isinstance(usage_value, Mapping):
        return 0
    planner_value = usage_value.get("planner")
    if not isinstance(planner_value, list):
        return 0
    total = 0
    for entry in planner_value:
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("actual_cost_micros")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            total += value
    return total


def planner_accounting(
    payload: Mapping[str, Any],
) -> tuple[int, int, int, int, int]:
    """Return request, reported, known-cost, cost-total, and real-call counts."""

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0, 0, 0
    planner = usage.get("planner")
    if not isinstance(planner, list):
        return 0, 0, 0, 0, 0
    requests = 0
    reported = 0
    known_cost = 0
    total_cost = 0
    real_calls = 0
    for value in planner:
        if not isinstance(value, dict):
            continue
        requests += 1
        reported += int(bool(value.get("reported")))
        cost = value.get("actual_cost_micros")
        if isinstance(cost, int) and not isinstance(cost, bool) and cost >= 0:
            known_cost += 1
            total_cost += cost
        real_calls += int(value.get("provider_request_id_presence") == "present")
    return requests, reported, known_cost, total_cost, real_calls


def _fail_pending_items(
    session: Session,
    job: JobRecord,
    error_code: str,
    error_message: str,
) -> None:
    now = utc_now()
    items = session.scalars(
        select(JobItemRecord)
        .where(
            JobItemRecord.job_id == job.id,
            JobItemRecord.status.in_(["pending", "queued", "running"]),
        )
        .with_for_update()
    ).all()
    for item in items:
        item.status = "failed"
        item.stage = "planning_failed"
        item.error_code = error_code
        item.error_message = error_message
        item.finished_at = now
        item.state_version += 1
    job.failed_item_count = len(items)


def _validate_item_configuration(
    configuration: Mapping[str, Any],
    *,
    require_source_roles: bool = False,
) -> None:
    expected_versions = {
        "workflow_version": WORKFLOW_VERSION,
        "planning_policy_version": PLANNING_POLICY_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "resume_signature_version": RESUME_SIGNATURE_VERSION,
        "output_format": IMAGE_FORMAT,
        "jpeg_quality": JPEG_QUALITY,
    }
    for key, expected in expected_versions.items():
        if configuration.get(key) != expected:
            raise XingheAgentError(
                "RESUME_SIGNATURE_INVALID",
                "An output-affecting Agent policy or format changed.",
            )
    _validated_image_size(configuration.get("size"))
    signature = configuration.get("resume_signature")
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        raise XingheAgentError(
            "RESUME_SIGNATURE_INVALID",
            "The page resume signature is invalid.",
        )
    _strict_page_count(configuration.get("page_count"))
    page = configuration.get("page")
    if (
        isinstance(page, bool)
        or not isinstance(page, int)
        or page < 1
        or page > int(configuration["page_count"])
    ):
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "The planned page number is invalid.",
        )
    _require_nonempty_string(configuration.get("group_key"), "group_key")
    _require_nonempty_string(configuration.get("prompt"), "prompt")
    if configuration.get("quality") not in {"medium", "high"}:
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "The planned image quality is invalid.",
        )
    sources = configuration.get("source_assets")
    if not isinstance(sources, list) or not sources:
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "Every page requires all ordered source angles.",
        )
    if require_source_roles:
        roles = [
            source.get("role") if isinstance(source, Mapping) else None
            for source in sources
        ]
        if "product_reference" not in roles or any(
            role not in {"product_reference", "style_reference"} for role in roles
        ):
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "Domestic detail sources require explicit product/style roles.",
            )


def _provider_rejection(
    code: str,
    message: str,
    gateway: XingheGateway,
) -> ProviderResult:
    return ProviderResult(
        outcome=ProviderOutcome.FAILED,
        error_code=code,
        error_message=message,
        usage_reported=False,
        raw_usage={
            "raw": None,
            "normalized": normalize_usage(None),
            "metrics": {
                "provider_called": False,
                "outcome": ProviderOutcome.FAILED.value,
            },
        },
        estimated_cost_micros=None,
        actual_cost_micros=None,
        retryable=False,
        provider_name=gateway.provider_name,
        model_name=gateway.image_model,
        pricing_version=gateway.pricing_version,
    )


def _planner_usage_record(result: PlannerCallResult) -> dict[str, Any]:
    return {
        "raw": result.raw_usage,
        "normalized": result.normalized_usage,
        "reported": bool(result.normalized_usage["reported"]),
        "provider_request_id_presence": result.request_id_presence,
        "api_latency_seconds": result.api_latency_seconds,
        "http_status": result.http_status,
        "actual_cost_micros": result.actual_cost_micros,
    }


def _planner_diagnostics_record(result: PlannerCallResult) -> dict[str, Any]:
    return {
        "schema": PLANNER_DIAGNOSTICS_SCHEMA,
        "version": PLANNER_OBSERVABILITY_VERSION,
        "parse_trace": list(result.parse_trace),
        "structure_fingerprint": result.structure_fingerprint,
        "structure_profile": result.structure_profile,
        "provider_envelope": result.provider_envelope,
        "content_utf8_bytes": result.content_utf8_bytes,
        "content_sha256": result.content_sha256,
        "request_id_presence": result.request_id_presence,
        "usage_presence": result.usage_presence,
        "usage_completeness": result.usage_completeness,
    }


def _image_usage_record(
    result: ImageCallResult,
    *,
    source_count: int,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    normalized = result.normalized_usage
    return {
        "raw": result.raw_usage,
        "normalized": normalized,
        "input_tokens": normalized.get("input_tokens"),
        "output_tokens": normalized.get("output_tokens"),
        "cached_tokens": normalized.get("cached_tokens"),
        "input_images": source_count,
        "output_images": 1 if result.artifact is not None else 0,
        "metrics": {
            "provider_called": True,
            "request_api_latency": result.api_latency_seconds,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "http_status": result.http_status,
            "rate_limited": result.rate_limited,
            "active_concurrency": result.active_concurrency,
            "outcome": result.outcome.value,
        },
    }


def _fake_usage(
    *,
    input_images: int = 0,
    output_images: int = 0,
) -> dict[str, Any]:
    return {
        "provider_type": "mock",
        "fake": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "input_images": input_images,
        "output_images": output_images,
        "network_requests": 0,
        "cost_micros": 0,
    }


def _fake_plan(request: PlannerRequest) -> dict[str, Any]:
    if request.planning_profile == "aurora_v20_visual_audit":
        page_index = max(0, min(5, request.page_count - 1))
        candidate = request.sources[-1]
        contract: dict[str, Any] = {}
        if request.product_information:
            try:
                loaded = json.loads(request.product_information[0])
                contract = loaded if isinstance(loaded, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                contract = {}
        page_contract = contract.get("page_contract")
        page_contract = page_contract if isinstance(page_contract, dict) else {}
        layout = page_contract.get("layout_contract")
        layout = layout if isinstance(layout, dict) else {}
        display = page_contract.get("display_copy_contract")
        display = display if isinstance(display, dict) else {}
        check_names = tuple(contract.get("required_check_names") or ())
        material_checks = _AURORA_V20_MATERIAL_CHECKS
        return {
            "page_index": page_index,
            "image_sha256": candidate.sha256,
            "reviewer": {
                "mode": "AGENT_DIRECT_PIXEL_REVIEW",
                "pixel_inspection_performed": True,
                "image_path": candidate.filename,
            },
            "decision_summary": (
                "模拟审图已直接检查候选图像像素，全部材料性检查满足本页合同。"
            ),
            "observations": {
                "product_prominence": 72,
                "headline_rank": "JOINT_FIRST",
                "headline_text": str(
                    display.get("headline_seed_source_segment") or "核心卖点"
                ),
                "headline_line_count": 1,
                "physical_evidence": ["当前商品与本页利益形成直接可见的证据关系"],
                "evidence_is_primary_visual": True,
                "depth_layers": 3,
                "commercial_closure_visible": True,
                "background_competition": "LOW",
                "thumbnail_scan_order": ["商品", "主标题", "证据"],
                "type_roles_seen": 4,
                "unequal_information_modules_seen": 2,
                "visual_tension_seen": "商品、标题与证据形成明确的定向阅读张力",
                "composition_archetype_seen": str(
                    layout.get("composition_archetype") or "VISIBLE_ARCHETYPE"
                ),
                "product_zone_seen": str(
                    layout.get("product_zone") or "VISIBLE_PRODUCT_ZONE"
                ),
                "copy_zone_seen": str(
                    layout.get("copy_zone") or "VISIBLE_COPY_ZONE"
                ),
                "dominant_view_seen": str(
                    layout.get("dominant_view") or "VISIBLE_DOMINANT_VIEW"
                ),
                "evidence_topology_seen": str(
                    layout.get("evidence_topology") or "VISIBLE_EVIDENCE_TOPOLOGY"
                ),
                "neighbor_layout_difference": (
                    "本页主体锚点、证据拓扑和阅读方向与相邻页面均明显不同"
                ),
                "claim_to_evidence_relation": (
                    "主卖点由当前商品的真实结构与使用关系直接承担"
                ),
                "claim_takeaway_without_copy": (
                    "遮住文字后仍能从商品与证据关系识别本页利益方向"
                ),
                "source_background_leakage": [],
            },
            "checks": [
                {
                    "name": name,
                    "passed": True,
                    "score": 92,
                    "material": name in material_checks,
                    "observed_evidence": f"候选图像像素中可见{name}满足本页合同要求",
                }
                for name in check_names
            ],
            "all_material_deficiencies": [],
            "audit_complete": True,
        }
    if request.planning_profile == "aurora_style_calibration":
        return {
            "agent_pixel_reviewed": True,
            "review_mode": "DIRECT_PIXEL_VISUAL_COMPARISON",
            "source_page_indexes": [0, 1],
            "observed_evidence": (
                "两张已通过页面共享一致的综合色彩角色、字体层级、"
                "信息面几何和商业摄影完成度，同时镜头与阅读路径明确不同。"
            ),
            "style_tokens": {
                "photography_finish": "以当前商品为主导的统一商业摄影完成度",
                "graphic_language": (
                    "由当前商品形态与页面证明关系共同提取的克制图形语言"
                ),
            },
        }
    if request.planning_profile == "aurora_set_audit":
        hashes = {
            str(index): source.sha256 for index, source in enumerate(request.sources)
        }
        return {
            "agent_pixel_reviewed": True,
            "review_mode": "BLIND_SIX_PAGE_ROLE_COMPARISON",
            "reviewed_page_indexes": [0, 1, 2, 3, 4, 5],
            "image_sha256_by_page": hashes,
            "identified_search_page_index": 0,
            "search_role_is_unique": True,
            "confusable_page_indexes": [],
            "search_identification_evidence": (
                "第0页具有唯一的搜索入口商品钩子、商业框架与闭合区，"
                "其余页面均承担轮播中的独立购买问题。"
            ),
            "carousel_distinctions": [
                {
                    "page_index": index,
                    "why_not_search_cover": (
                        f"第{index}页采用轮播职责对应的证据结构与阅读路径，"
                        "不具备搜索入口完整商业框架。"
                    ),
                }
                for index in range(1, 6)
            ],
        }
    if request.planning_profile == "aurora_visual_audit":
        page_index = max(0, min(5, request.page_count - 1))
        candidate = request.sources[-1]
        source_text = request.product_name or "当前页主卖点"
        observability = "DIRECTLY_VISIBLE"
        if request.product_information:
            try:
                contract = json.loads(request.product_information[0])
                source_text = str(contract.get("source_text") or source_text)
                observability = str(
                    contract.get("observability_class") or observability
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        check_names = (
            "product_identity_match",
            "factual_copy_match",
            "typography_style_match",
            "typography_legibility",
            "page_role_expression",
            "evidence_relation_visible",
            "campaign_style_match",
            "headline_treatment_match",
            "palette_role_match",
            "graphic_language_match",
            "photography_finish_match",
            "information_surface_match",
            "layout_not_cloned",
            "set_diversity_match",
            "product_separation",
            "numeric_hierarchy_if_applicable",
            "design_intensity_controlled",
            "visual_performance_match",
            "baseline_performance_match",
            "approved_plan_fidelity_match",
            "campaign_constitution_match",
            "source_background_noise_absent",
            "selling_point_visible_without_copy",
            "selling_point_visual_dominance",
            "claim_to_evidence_relation_clear",
            "text_not_substituting_for_visual_proof",
            "thumbnail_success",
            "no_unsupported_claim",
            "no_hard_error",
        )
        return {
            "page_index": page_index,
            "image_sha256": candidate.sha256,
            "reviewer": {
                "mode": "AGENT_DIRECT_PIXEL_REVIEW",
                "pixel_inspection_performed": True,
                "image_path": candidate.filename,
                "comparison_reference_ids": [
                    source.asset_id for source in request.sources[:-1]
                ],
            },
            "decision_summary": (
                "模拟审图已直接检查候选图像像素，商品、主张、"
                "构图与整套视觉合同均满足当前页面要求。"
            ),
            "performance_observation": {
                "estimated_product_occupancy_percent": 62,
                "headline_visual_rank": "JOINT_FIRST",
                "physical_evidence_seen": ["当前商品主体与页面职责对应的可见证明关系"],
                "depth_layers_seen": 3,
                "commercial_closure_seen": True,
                "background_competition": "LOW",
                "thumbnail_scan_order": ["商品主体", "主标题", "商业闭合"],
            },
            "plan_fidelity_observation": {
                "observed_subject_and_view": "完整商品主体以清晰可识别的商业视角呈现",
                "observed_scene_geometry": "主体、证明区域与背景形成清楚的前中后景关系",
                "observed_composition": "商品与主标题共同主导并保留明确商业闭合区域",
                "observed_reading_path": ["商品主体", "主标题", "商业闭合"],
                "missing_required_elements": [],
                "unexpected_plan_changes": [],
            },
            "selling_point_proof_observation": {
                "source_text": source_text,
                "observability_class": observability,
                "visible_without_copy": observability != "TEXT_ONLY_VERIFIED",
                "pixel_evidence": ["商品主体与真实结构或场景关系承担主利益表达"],
                "text_only_dependency": observability == "TEXT_ONLY_VERIFIED",
                "evidence_is_primary_visual": True,
                "estimated_evidence_occupancy_percent": 48,
                "claim_takeaway_without_copy": "画面能够传达当前页面主利益的明确方向",
                "expression_mode": "TEXT_ONLY"
                if observability == "TEXT_ONLY_VERIFIED"
                else "DIRECT",
            },
            "source_background_observation": {
                "leaked_source_elements": [],
                "rebuilt_scene_evidence": (
                    "背景为重新组织的干净商业场景，未见来源环境杂物"
                ),
            },
            "all_observed_deficiencies": [],
            "audit_completeness_confirmation": True,
            "checks": {
                name: {
                    "passed": True,
                    "score": 92,
                    "observed_evidence": (
                        f"候选图像像素中可见{name}对应层级满足当前合同要求"
                    ),
                }
                for name in check_names
            },
        }
    if request.planning_profile == "aurora_identity":
        return {
            "request_id": request.job_id,
            "product_form": f"{request.product_name}的可见完整商品形态",
            "identity_summary": (
                f"由{len(request.sources)}张原始商品图片共同锁定同一款"
                f"{request.product_name}；只保留素材中可见的身份特征。"
            ),
            "evidence": [
                {
                    "evidence_id": source.asset_id,
                    "view_tags": [f"原始商品视图 {index + 1}"],
                }
                for index, source in enumerate(request.sources)
            ],
            "must_preserve": [
                "原始素材中可见的商品整体轮廓与比例",
                "原始素材中可见的颜色分区与表面关系",
                "原始素材中可见的部件数量、连接和相对位置",
                "原始素材中可见的包装、开合结构与标识位置",
            ],
            "must_not_change": [
                "不得增加、删除或重设计商品结构",
                "不得改变商品颜色分区、比例或部件关系",
                "不得把来源照片背景当作商品身份或活动场景",
                "不得使用生成图片作为商品身份依据",
            ],
        }
    if request.planning_profile == "amazon_visual_suite":
        return _fake_amazon_plan(request)
    roles = (
        "Cover hero",
        "Structure detail",
        "Use scenario",
        "Surface texture",
        "Feature focus",
        "Craft close-up",
        "Buyer reassurance",
        "Purchase summary",
        "Daily pairing",
        "Visible detail",
        "Design story",
        "Final overview",
    )
    return {
        "analysis": {
            "category_key": "general",
            "category_reason": "Deterministic fake category for contract tests.",
            "product_image_analysis": {
                "visible_facts": [
                    f"{len(request.sources)} complementary source angle(s)"
                ],
                "needs_confirmation": [],
            },
            "product_consistency_anchors": {
                "overall_silhouette": "Preserve the ordered source images.",
                "color_material": "Use visible appearance only.",
                "pattern_logo_nameplate": (
                    "Preserve visible placement; ignore source watermarks."
                ),
                "structural_parts": "Do not add or remove visible parts.",
                "decorative_elements": "Preserve visible relative positions.",
                "crop_to_whole": "Crops must come from the same product.",
            },
            "product_master_description": {
                "sku_identity": "One exact product from all ordered source angles.",
                "silhouette": "Preserve visible silhouette and proportions.",
                "color_material": "Preserve visible color-area ratio and finish.",
                "structure": "Preserve every visible structural part.",
                "unknowns": [],
            },
            "buyer_objections": [
                "What is visibly distinctive?",
                "How does the structure look from multiple angles?",
            ],
        },
        "plan": {
            "campaign_style_lock": {
                "palette": "Restrained neutral palette with one product-led accent.",
                "typography": "Consistent editorial sans-serif hierarchy.",
                "background": "Alternating clean field and grounded context.",
                "lighting": "Consistent soft directional studio light.",
                "icon_style": "Minimal line icons only when information requires them.",
                "whitespace": "Deliberate negative space with changing rhythm.",
                "product_scale": (
                    "Vary hero, medium, macro, scene, and information scales."
                ),
            },
            "design_strength_lock": {
                "category_visual_motif": "Product-led geometric crop motif.",
                "rhythm_map": [
                    f"Page {index + 1}: distinct visual beat."
                    for index in range(request.page_count)
                ],
                "composition_contrast": (
                    "Alternate scale, alignment, depth, and density."
                ),
                "signature_devices": [
                    "Geometric crop frame",
                    "Restrained evidence ribbon",
                ][: max(1, min(2, request.page_count))],
                "color_contrast": "Alternate light field and accent field.",
                "template_ban": "Never repeat the same centered-product template.",
            },
            "layout_diversity_lock": {
                "max_same_layout_family": 2,
                "layout_rule": "Rotate layout families across adjacent pages.",
                "background_rule": "No background system appears more than twice.",
            },
            "product_consistency_lock": {
                "sku_identity": "Never change the SKU across pages.",
                "physical_logic": "Preserve scale, contact, perspective, and gravity.",
            },
            "screens": [
                {
                    "role": (
                        "closing_summary"
                        if index == request.page_count - 1 and request.page_count > 1
                        else roles[index % len(roles)]
                    ),
                    "title": f"{request.product_name} {index + 1}",
                    "label": f"Visible focus {index + 1}",
                    "composition": "One dominant visual hero.",
                    "device": (
                        "Geometric crop frame"
                        if index % 2 == 0
                        else "Restrained evidence ribbon"
                    ),
                    "difference": "Distinct scale and rhythm from adjacent pages.",
                    "structure": (
                        "editorial-hero",
                        "offset-detail",
                        "grounded-scene",
                        "evidence-card",
                    )[index % 4],
                    "subject_scale": (
                        "hero",
                        "medium",
                        "macro",
                        "scene",
                        "information",
                    )[index % 5],
                    "buyer_question": f"Unique buyer question {index + 1}?",
                    "layout_family": (
                        "editorial",
                        "offset-evidence",
                        "grounded-scene",
                        "technical-proof",
                    )[index % 4],
                    "camera_angle": (
                        "front",
                        "three-quarter",
                        "macro-side",
                        "overhead",
                    )[index % 4],
                    "product_position": (
                        "center",
                        "left-third",
                        "right-third",
                        "lower-center",
                    )[index % 4],
                    "background_system": (
                        "clean-field",
                        "context-scene",
                        "material-surface",
                        "contrast-field",
                    )[index % 4],
                    "prop_strategy": f"Page-specific prop strategy {index + 1}",
                    "copy_density": ("sparse" if index % 2 == 0 else "moderate"),
                }
                for index in range(request.page_count)
            ],
        },
    }


def _fake_amazon_plan(request: PlannerRequest) -> dict[str, Any]:
    from .amazon_visual_suite_provider import (
        AMAZON_ITEM_SPECS,
        AMAZON_SKILL_ROW_ID_BY_ITEM_KEY,
    )

    return {
        "analysis": {
            "product_image_analysis": {
                "visible_facts": [
                    f"{len(request.sources)} role-labelled product source image(s)"
                ],
                "possible_use_contexts": ["category-appropriate daily use"],
                "unknowns": [],
            },
            "information_confidence": {
                "confirmed": ["visible source facts"],
                "reasonable_inference": [],
                "needs_confirmation": [],
            },
            "buyer_demand_map": [
                "Attraction: recognize the exact product.",
                "Understanding: see the core use and function.",
                "Trust: verify visible structure and details.",
                "Comparison: understand why this SKU fits.",
                "Purchase: reduce choice and use risk.",
            ],
            "demand_to_selling_point_match": [
                "Recognition -> show the exact supplied SKU.",
                "Trust -> use visible structural and detail proof.",
            ],
            "product_master_description": {
                "category_and_identity": "One exact product from the supplied sources.",
                "silhouette_and_proportions": (
                    "Preserve the supplied silhouette and proportions."
                ),
                "color_material_and_texture": (
                    "Use visible color, finish, and texture only."
                ),
                "structure_parts_and_accessories": (
                    "Do not add or remove visible parts or accessories."
                ),
                "logos_labels_patterns_and_packaging": (
                    "Preserve visible identity placement and packaging facts."
                ),
                "scale_and_physics": (
                    "Keep scale, contact, perspective, shadows, and gravity credible."
                ),
                "unknowns": [],
            },
        },
        "plan": {
            "campaign_style_lock": {
                "platform": request.platform_code,
                "marketplace_language": request.language,
                "design_direction": "Product-led, evidence-first Amazon visual system.",
                "palette": (
                    "Restrained palette derived from the product and supplied brand "
                    "evidence."
                ),
                "lighting": "Consistent realistic commercial lighting.",
                "typography_mood": "Clear shopper-facing hierarchy.",
                "label_style": "Sparse labels only when they improve proof.",
                "density": "Readable at listing and phone size.",
            },
            "product_consistency_lock": {
                "product_identity": "Preserve one exact SKU across all 21 images.",
                "structure": "Preserve every visible structural part.",
                "color_area_ratio": "Preserve the visible color-area ratio.",
                "material_look": (
                    "Preserve visible material appearance without inventing "
                    "composition."
                ),
                "logo_and_label_placement": (
                    "Preserve authentic visible logo and label placement."
                ),
                "physical_scale": (
                    "Keep product scale and physical interaction credible."
                ),
            },
            "layout_diversity_lock": {
                "structure_strategy": (
                    "Use at least five distinct structures across secondary and A+ "
                    "selling images."
                ),
                "large_product_top_title_limit": 3,
            },
            "screens": [
                {
                    "id": AMAZON_SKILL_ROW_ID_BY_ITEM_KEY[spec.item_key],
                    "asset_type": spec.asset_type,
                    "final_size": f"{spec.width}x{spec.height}",
                    "buyer_question": spec.buyer_question,
                    "selling_point": f"Mock planned selling point for {spec.item_key}.",
                    "information_confidence": "confirmed",
                    "visual_proof": spec.visual_proof,
                    "headline": f"Mock planned headline for {spec.item_key}.",
                    "subcopy": "Mock planned support copy.",
                    "layout_direction": f"Mock planned layout for {spec.item_key}.",
                    "source_material": ("white_background_product and product_detail"),
                    "risk_note": "Use only confirmed source facts.",
                }
                for spec in AMAZON_ITEM_SPECS
            ],
        },
    }


def _fake_jpeg(page_number: int, size: str) -> bytes:
    buffer = BytesIO()
    color = (
        (page_number * 53) % 256,
        (page_number * 97) % 256,
        (page_number * 149) % 256,
    )
    width, height = _parse_image_size(size)
    Image.new("RGB", (width, height), color=color).save(
        buffer,
        format="JPEG",
        quality=JPEG_QUALITY,
    )
    return buffer.getvalue()


def _parse_image_size(size: object) -> tuple[int, int]:
    if not isinstance(size, str) or not re.fullmatch(r"[1-9]\d*x[1-9]\d*", size):
        raise XingheAgentError(
            "IMAGE_REQUEST_SIZE_INVALID",
            "Configured image size is invalid.",
        )
    width_text, height_text = size.split("x", maxsplit=1)
    return int(width_text), int(height_text)


def _validated_image_size(size: object) -> str:
    _parse_image_size(size)
    if size not in SUPPORTED_IMAGE_SIZES:
        raise XingheAgentError(
            "IMAGE_REQUEST_SIZE_INVALID",
            "Configured image size is not supported.",
        )
    return str(size)


def _artifact_from_bytes(
    payload: bytes,
    *,
    filename: str,
    expected_size: str,
    preserve_provider_artifact: bool = False,
) -> ProviderArtifact:
    expected_width, expected_height = _parse_image_size(expected_size)
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            image_format = str(image.format)
            if width <= 0 or height <= 0 or width * height > 100_000_000:
                raise ValueError("unsafe image dimensions")
            image.load()
            materialized = ImageOps.exif_transpose(image).copy()
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise XingheAgentError(
            "IMAGE_RESPONSE_INVALID",
            "Provider returned an invalid image.",
        ) from exc

    provider_formats = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "WEBP": ("image/webp", ".webp"),
    }
    provider_format = provider_formats.get(image_format)
    if provider_format is None:
        raise XingheAgentError(
            "IMAGE_RESPONSE_FORMAT_INVALID",
            "Provider returned an unsupported image format.",
        )
    content_type, suffix = provider_format
    if preserve_provider_artifact:
        return ProviderArtifact(
            payload=payload,
            filename=_replace_image_suffix(filename, suffix),
            content_type=content_type,
            width=width,
            height=height,
            sha256=hashlib.sha256(payload).hexdigest(),
            locally_resampled=False,
            provider_width=width,
            provider_height=height,
        )

    if image_format != "JPEG":
        raise XingheAgentError(
            "IMAGE_RESPONSE_FORMAT_INVALID",
            "Provider did not return the requested JPEG format.",
        )
    locally_resampled = width != expected_width or height != expected_height
    if locally_resampled:
        if width * expected_height != height * expected_width:
            raise XingheAgentError(
                "IMAGE_RESPONSE_SIZE_INVALID",
                "Provider returned an image with an incompatible aspect ratio.",
            )
        materialized = materialized.convert("RGB").resize(
            (expected_width, expected_height),
            Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        materialized.save(
            output,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
        )
        payload = output.getvalue()
    return ProviderArtifact(
        payload=payload,
        filename=filename,
        content_type="image/jpeg",
        width=expected_width,
        height=expected_height,
        sha256=hashlib.sha256(payload).hexdigest(),
        locally_resampled=locally_resampled,
        provider_width=width,
        provider_height=height,
    )


def _replace_image_suffix(filename: str, suffix: str) -> str:
    stem = filename.rsplit(".", maxsplit=1)[0] if "." in filename else filename
    return f"{stem}{suffix}"


def _provider_transparent_hole_png(source_png: bytes, api_mask_png: bytes) -> bytes:
    try:
        with Image.open(BytesIO(source_png)) as source_image:
            source_image.load()
            source = source_image.convert("RGBA")
        with Image.open(BytesIO(api_mask_png)) as mask_image:
            mask_image.load()
            mask = mask_image.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise XingheAgentError(
            "LOCAL_EDIT_INPUT_INVALID",
            "Local-edit source or mask is not a valid image.",
        ) from exc
    if source.size != mask.size:
        raise XingheAgentError(
            "LOCAL_EDIT_INPUT_SIZE_MISMATCH",
            "Local-edit source and mask dimensions do not match.",
        )

    source.putalpha(ImageChops.multiply(source.getchannel("A"), mask.getchannel("A")))
    output = BytesIO()
    source.save(output, format="PNG")
    return output.getvalue()


def _tengli_masked_prompt(prompt: str) -> str:
    return (
        "Image-edit instruction: the first image is the editable canvas, "
        "and its transparent target is the only area to change. The second image is "
        "the unchanged source reference. Preserve its product identity, logos, labels, "
        "text, geometry, and placement inside the target unless the request explicitly "
        "changes them. Fill only the transparent target at its current location. "
        "Do not render the target as black or as a solid-color patch.\n\n"
        f"{prompt}"
    )


def _masked_png_artifact(
    payload: bytes,
) -> ProviderArtifact:
    try:
        with Image.open(BytesIO(payload)) as image:
            actual_width, actual_height = image.size
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise XingheAgentError(
            "LOCAL_EDIT_RESPONSE_INVALID",
            "Provider returned an invalid local-edit image.",
        ) from exc
    if image_format != "PNG":
        raise XingheAgentError(
            "LOCAL_EDIT_RESPONSE_FORMAT_INVALID",
            "Provider did not return the requested PNG format.",
        )
    return ProviderArtifact(
        payload=payload,
        filename="local-edit-provider-raw.png",
        content_type="image/png",
        width=actual_width,
        height=actual_height,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _amazon_visual_review_item_keys(
    request: AmazonVisualReviewRequest,
) -> tuple[str, ...]:
    if request.scope not in {"item", "suite"}:
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review request used an invalid scope.",
        )
    if request.scope == "suite":
        review_item_keys = request.review_item_keys
        if not review_item_keys:
            raise XingheAgentError(
                "AMAZON_VISUAL_REVIEW_INVALID",
                "Suite review requires explicit review_item_keys.",
            )
    else:
        review_item_keys = request.review_item_keys or tuple(
            candidate.item_key for candidate in request.candidates
        )
    if (
        not review_item_keys
        or len(review_item_keys) > 64
        or any(
            not isinstance(item_key, str)
            or not item_key.strip()
            or item_key != item_key.strip()
            or len(item_key) > 128
            for item_key in review_item_keys
        )
        or len(set(review_item_keys)) != len(review_item_keys)
    ):
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review request used invalid review_item_keys.",
        )
    if request.scope == "item" and (
        not isinstance(request.item_key, str)
        or tuple(review_item_keys) != (request.item_key,)
    ):
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Item review must expose exactly its item_key in review_item_keys.",
        )
    return tuple(review_item_keys)


def _amazon_visual_review_json_schema(
    review_item_keys: tuple[str, ...],
) -> dict[str, Any]:
    short_string = {"type": "string", "minLength": 1, "maxLength": 300}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "visual_success",
            "summary",
            "reason_codes",
            "missing_evidence",
            "retry_guidance",
            "failed_item_keys",
        ],
        "properties": {
            "visual_success": {"type": "boolean"},
            "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
            "reason_codes": {
                "type": "array",
                "maxItems": 64,
                "items": {"type": "string", "minLength": 3, "maxLength": 64},
            },
            "missing_evidence": {
                "type": "array",
                "maxItems": 64,
                "items": short_string,
            },
            "retry_guidance": {"type": "string", "maxLength": 1800},
            "failed_item_keys": {
                "type": "array",
                "maxItems": len(review_item_keys),
                "items": {
                    "type": "string",
                    "enum": list(review_item_keys),
                },
            },
        },
    }


def _amazon_visual_review_response_format(
    review_item_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "amazon_visual_review",
            "strict": True,
            "schema": _amazon_visual_review_json_schema(review_item_keys),
        },
    }


def _amazon_visual_review_prompt(
    request: AmazonVisualReviewRequest,
    *,
    review_item_keys: tuple[str, ...],
) -> str:
    display_artifact_keys = [candidate.item_key for candidate in request.candidates]
    return (
        "Review the supplied Amazon image candidate(s) as the QA stage defined "
        "by the bundled Skill. Do not add stricter rules, preferences, or product "
        "facts. Use the real reference images as product-truth evidence. For item "
        "scope, decide whether the single candidate materially satisfies its own "
        "planned role, product consistency, copy and claim rules, physical logic, "
        "and target composition. For suite scope, judge the full-set requirements, "
        "especially cross-image product consistency, layout diversity, independent "
        "desktop/mobile composition, readable marketplace copy, and unsupported "
        "claims. Candidate image labels identify display artifacts only. In suite "
        "scope, the contact sheet is only a display carrier and its item_key or "
        "filename is never a failed item identifier. Return exactly one JSON object "
        "with: visual_success (boolean), summary (short string), reason_codes "
        "(array of short UPPER_SNAKE_CASE strings), missing_evidence (array of short "
        "strings), retry_guidance (short instruction derived only from the Skill; "
        "empty on pass), and failed_item_keys (array containing only exact, "
        "case-sensitive values from review_item_keys; empty on pass). Never emit a "
        "contact-sheet key, filename, row label, normalized spelling, lowercase "
        "alias, or any other string in failed_item_keys. Do not fail merely for "
        "subjective taste.\n"
        f"review_scope={request.scope}\n"
        f"item_key={request.item_key or ''}\n"
        f"display_artifact_keys={display_artifact_keys}\n"
        f"review_item_keys={list(review_item_keys)}\n"
        f"generation_contract={request.generation_contract}\n"
        "skill_protocol="
        + json.dumps(
            request.skill_protocol,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _validate_amazon_visual_review_payload(
    payload: object,
    *,
    scope: str,
    review_item_keys: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review returned a non-object payload.",
        )
    required = {
        "visual_success",
        "summary",
        "reason_codes",
        "missing_evidence",
        "retry_guidance",
        "failed_item_keys",
    }
    if set(payload) != required:
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review returned an invalid field set.",
        )
    visual_success = payload["visual_success"]
    summary = payload["summary"]
    retry_guidance = payload["retry_guidance"]
    if (
        not isinstance(visual_success, bool)
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 1200
        or not isinstance(retry_guidance, str)
        or len(retry_guidance) > 1800
    ):
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review returned invalid scalar fields.",
        )

    def string_list(name: str, *, pattern: re.Pattern[str] | None = None) -> list[str]:
        value = payload[name]
        if (
            not isinstance(value, list)
            or len(value) > 64
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 300
                or (pattern is not None and pattern.fullmatch(item.strip()) is None)
                for item in value
            )
        ):
            raise XingheAgentError(
                "AMAZON_VISUAL_REVIEW_INVALID",
                f"Amazon visual review returned invalid {name}.",
            )
        return [item.strip() for item in value]

    reason_codes = string_list(
        "reason_codes", pattern=re.compile(r"[A-Z][A-Z0-9_]{2,63}")
    )
    missing_evidence = string_list("missing_evidence")
    failed_item_keys = string_list("failed_item_keys")
    allowed_review_item_keys = set(review_item_keys)
    if len(set(failed_item_keys)) != len(failed_item_keys) or any(
        item_key not in allowed_review_item_keys for item_key in failed_item_keys
    ):
        raise XingheAgentError(
            "AMAZON_VISUAL_REVIEW_INVALID",
            "Amazon visual review named a key outside review_item_keys.",
        )
    if visual_success:
        if reason_codes or failed_item_keys or retry_guidance.strip():
            raise XingheAgentError(
                "AMAZON_VISUAL_REVIEW_INVALID",
                "A passing Amazon visual review cannot contain failure fields.",
            )
    else:
        if not reason_codes or not failed_item_keys or not retry_guidance.strip():
            raise XingheAgentError(
                "AMAZON_VISUAL_REVIEW_INVALID",
                "A failed Amazon visual review must identify reasons and items.",
            )
        if scope == "item" and tuple(failed_item_keys) != review_item_keys:
            raise XingheAgentError(
                "AMAZON_VISUAL_REVIEW_INVALID",
                "Item review must identify exactly its review item.",
            )
    return {
        "visual_success": visual_success,
        "summary": summary.strip(),
        "reason_codes": reason_codes,
        "missing_evidence": missing_evidence,
        "retry_guidance": retry_guidance.strip(),
        "failed_item_keys": failed_item_keys,
    }


def _masked_visual_review_prompt(instruction: str) -> str:
    return (
        "Review exactly three ordered images: (1) source, (2) binary authority "
        "mask where white pixels are editable and black pixels are locked, "
        "(3) raw provider candidate. The server will later restore every "
        "locked pixel exactly, so judge the requested change inside the white "
        "selection. Treat changes to product identity, logos, labels, text, "
        "patterns, or markings as failures only when the user did not explicitly "
        "request those exact changes; require all other identity evidence inside "
        "the selection to remain preserved. Also judge edge, lighting, and "
        "texture continuity at the selection boundary and visible artifacts. "
        f"User instruction: {instruction!r}. Return exactly one JSON object "
        "with boolean fields visual_success, instruction_satisfied, "
        "identity_inside_selection_preserved, boundary_continuity, and "
        "artifacts_absent; a reason_codes array of concise stable strings; "
        "and a concise summary string. visual_success may be true only when "
        "all four component booleans are true. Do not recommend or perform "
        "regeneration."
    )


def _validate_masked_visual_review_payload(payload: object) -> dict[str, Any]:
    root = _require_mapping(
        payload,
        "LOCAL_EDIT_VISUAL_REVIEW_INVALID",
        path="/",
    )
    components: dict[str, bool] = {}
    for key in (
        "instruction_satisfied",
        "identity_inside_selection_preserved",
        "boundary_continuity",
        "artifacts_absent",
    ):
        value = root.get(key)
        if not isinstance(value, bool):
            raise XingheAgentError(
                "LOCAL_EDIT_VISUAL_REVIEW_INVALID",
                f"Visual review field {key} must be boolean.",
                json_pointer=_json_pointer(key),
            )
        components[key] = value
    declared = root.get("visual_success")
    if not isinstance(declared, bool):
        raise XingheAgentError(
            "LOCAL_EDIT_VISUAL_REVIEW_INVALID",
            "Visual review verdict must be boolean.",
            json_pointer=_json_pointer("visual_success"),
        )
    reason_values = root.get("reason_codes")
    if not isinstance(reason_values, list) or any(
        not isinstance(value, str) for value in reason_values
    ):
        raise XingheAgentError(
            "LOCAL_EDIT_VISUAL_REVIEW_INVALID",
            "Visual review reason codes must be a string array.",
            json_pointer=_json_pointer("reason_codes"),
        )
    reason_codes = [value.strip()[:80] for value in reason_values if value.strip()][:12]
    summary = _require_nonempty_string(
        root.get("summary"),
        "summary",
        path=_json_pointer("summary"),
    )[:500]
    computed = all(components.values())
    if declared != computed:
        reason_codes.append("inconsistent_component_verdict")
    return {
        "visual_success": declared and computed,
        "reason_codes": reason_codes,
        "summary": summary,
        **components,
    }


def _strict_json_object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": dict(properties),
    }


def _string_array_schema(
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
    }
    if minimum is not None:
        schema["minItems"] = minimum
    if maximum is not None:
        schema["maxItems"] = maximum
    return schema


def _amazon_planner_json_schema() -> dict[str, Any]:
    """Return only the planning fields required by the bundled Amazon Skill."""

    string = {"type": "string", "minLength": 1}
    copy_string = {"type": "string"}
    confidence = {
        "type": "string",
        "enum": ["confirmed", "reasonable inference", "needs confirmation"],
    }
    product_image_analysis = _strict_json_object(
        {
            "visible_facts": _string_array_schema(minimum=1),
            "possible_use_contexts": _string_array_schema(),
            "unknowns": _string_array_schema(),
        }
    )
    information_confidence = _strict_json_object(
        {
            "confirmed": _string_array_schema(),
            "reasonable_inference": _string_array_schema(),
            "needs_confirmation": _string_array_schema(),
        }
    )
    product_master = _strict_json_object(
        {
            "category_and_identity": string,
            "silhouette_and_proportions": string,
            "color_material_and_texture": string,
            "structure_parts_and_accessories": string,
            "logos_labels_patterns_and_packaging": string,
            "scale_and_physics": string,
            "unknowns": _string_array_schema(),
        }
    )
    analysis = _strict_json_object(
        {
            "product_image_analysis": product_image_analysis,
            "information_confidence": information_confidence,
            "buyer_demand_map": _string_array_schema(minimum=1),
            "demand_to_selling_point_match": _string_array_schema(minimum=1),
            "product_master_description": product_master,
        }
    )
    campaign_style_lock = _strict_json_object(
        {
            "platform": string,
            "marketplace_language": string,
            "design_direction": string,
            "palette": string,
            "lighting": string,
            "typography_mood": string,
            "label_style": string,
            "density": string,
        }
    )
    product_consistency_lock = _strict_json_object(
        {
            "product_identity": string,
            "structure": string,
            "color_area_ratio": string,
            "material_look": string,
            "logo_and_label_placement": string,
            "physical_scale": string,
        }
    )
    layout_diversity_lock = _strict_json_object(
        {
            "structure_strategy": string,
            "large_product_top_title_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
            },
        }
    )
    screen = _strict_json_object(
        {
            "id": string,
            "asset_type": string,
            "final_size": string,
            "buyer_question": string,
            "selling_point": string,
            "information_confidence": confidence,
            "visual_proof": string,
            "headline": copy_string,
            "subcopy": copy_string,
            "layout_direction": string,
            "source_material": string,
            "risk_note": string,
        }
    )
    plan = _strict_json_object(
        {
            "campaign_style_lock": campaign_style_lock,
            "product_consistency_lock": product_consistency_lock,
            "layout_diversity_lock": layout_diversity_lock,
            "screens": {
                "type": "array",
                "minItems": 21,
                "maxItems": 21,
                "items": screen,
            },
        }
    )
    return _strict_json_object({"analysis": analysis, "plan": plan})


def _aurora_identity_json_schema() -> dict[str, Any]:
    string = {"type": "string", "minLength": 1}
    string_array = {
        "type": "array",
        "minItems": 1,
        "items": string,
    }
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence_id", "view_tags"],
        "properties": {
            "evidence_id": string,
            "view_tags": string_array,
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "request_id",
            "product_form",
            "identity_summary",
            "evidence",
            "must_preserve",
            "must_not_change",
        ],
        "properties": {
            "request_id": string,
            "product_form": string,
            "identity_summary": string,
            "evidence": {
                "type": "array",
                "minItems": 1,
                "items": evidence,
            },
            "must_preserve": string_array,
            "must_not_change": string_array,
        },
    }


def _aurora_v20_visual_judgment_json_schema(
    layout_observation_contract: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the strict gateway contract for native v2 semantic judgment.

    Runtime-owned fields (page index, candidate hash, reviewer attestation and
    ``audit_complete``) intentionally do not belong in this response schema.
    The local provider binds those fields after validating the semantic payload.
    This prevents a vision model from returning stale page metadata while also
    making malformed values such as a string-valued ``observations`` impossible
    to accept as a successful native judgment.
    """

    string = {"type": "string", "minLength": 1}
    observations_properties: dict[str, Any] = {
        "product_prominence": {"type": "number", "minimum": 0, "maximum": 100},
        "headline_rank": {
            "type": "string",
            "enum": ["FIRST", "JOINT_FIRST", "SECOND", "WEAK"],
        },
        "headline_text": string,
        "headline_line_count": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8,
        },
        "physical_evidence": {"type": "array", "items": string},
        "evidence_is_primary_visual": {"type": "boolean"},
        "depth_layers": {"type": "integer", "minimum": 0, "maximum": 5},
        "commercial_closure_visible": {"type": "boolean"},
        "background_competition": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH"],
        },
        "thumbnail_scan_order": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": string,
        },
        "type_roles_seen": {"type": "integer", "minimum": 0, "maximum": 8},
        "unequal_information_modules_seen": {
            "type": "integer",
            "minimum": 0,
            "maximum": 8,
        },
        "visual_tension_seen": {"type": "string", "minLength": 8},
        "composition_archetype_seen": string,
        "product_zone_seen": string,
        "copy_zone_seen": string,
        "dominant_view_seen": string,
        "evidence_topology_seen": string,
        "neighbor_layout_difference": string,
        "claim_to_evidence_relation": {"type": "string", "minLength": 8},
        "claim_takeaway_without_copy": {"type": "string", "minLength": 8},
        "source_background_leakage": {"type": "array", "items": string},
    }
    # The native audit runtime compares these five observations to the
    # page-specific layout contract by exact token, not by prose similarity.
    # Supplying the enum in the provider schema prevents a vision model from
    # returning a descriptive paraphrase such as "right half" for a required
    # contract token such as RIGHT_OR_CENTER_DOMINANT.
    if layout_observation_contract:
        for field, value in layout_observation_contract.items():
            if field in observations_properties and value:
                observations_properties[field] = {
                    "type": "string",
                    "enum": [value],
                }
    observation_names = list(observations_properties)
    check_required = [
        "name",
        "passed",
        "score",
        "material",
        "observed_evidence",
    ]
    check_variants = []
    for name in _AURORA_V20_VISUAL_CHECKS:
        check_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": check_required,
                "properties": {
                    "name": {"enum": [name]},
                    "passed": {"type": "boolean"},
                    "score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "material": {
                        "enum": [name in _AURORA_V20_MATERIAL_CHECKS]
                    },
                    "observed_evidence": {"type": "string", "minLength": 8},
                },
            }
        )
    check = {"anyOf": check_variants}
    deficiency = {
        "type": "object",
        "additionalProperties": False,
        "required": ["check", "visible_problem", "root_cause", "required_change"],
        "properties": {
            "check": {"type": "string", "enum": list(_AURORA_V20_VISUAL_CHECKS)},
            "visible_problem": {"type": "string", "minLength": 8},
            "root_cause": {"type": "string", "minLength": 8},
            "required_change": {"type": "string", "minLength": 8},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "decision_summary",
            "observations",
            "checks",
            "all_material_deficiencies",
        ],
        "properties": {
            "decision_summary": {"type": "string", "minLength": 12},
            "observations": {
                "type": "object",
                "additionalProperties": False,
                "required": observation_names,
                "properties": observations_properties,
            },
            "checks": {"type": "array", "minItems": 1, "items": check},
            "all_material_deficiencies": {
                "type": "array",
                "items": deficiency,
            },
        },
    }


def _planner_response_format(request: PlannerRequest) -> dict[str, Any]:
    if request.planning_profile == "aurora_identity":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_product_identity",
                "strict": True,
                "schema": _aurora_identity_json_schema(),
            },
        }
    if request.planning_profile == "reference_visual_remix":
        return {"type": "json_object"}
    if request.planning_profile == "aurora_v20_visual_audit":
        layout_contract: dict[str, str] = {}
        if request.product_information:
            try:
                contract = json.loads(request.product_information[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                contract = None
            if isinstance(contract, Mapping):
                raw_layout = contract.get("layout_observation_contract")
                if isinstance(raw_layout, Mapping):
                    layout_contract = {
                        str(key): str(value)
                        for key, value in raw_layout.items()
                        if str(value).strip()
                    }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_v20_visual_judgment_semantics",
                "strict": True,
                "schema": _aurora_v20_visual_judgment_json_schema(
                    layout_contract
                ),
            },
        }
    if request.planning_profile != "amazon_visual_suite":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "amazon_visual_suite_plan",
            "strict": True,
            "schema": _amazon_planner_json_schema(),
        },
    }


def _planner_prompt(request: PlannerRequest) -> str:
    if request.planning_profile == "reference_visual_remix":
        return (
            "You are the reference-visual-reverse-remix visual analysis stage. "
            "The first attached image is visual_strategy_reference and the second "
            "is product_identity_reference. Inspect the actual pixels before writing. "
            "Return one JSON object with exactly these top-level keys: "
            "product_identity_lock, product_text_inventory, selected_product_subset, "
            "excluded_product_elements, reference_visual_analysis, "
            "hard_composition_skeleton, normalized_anchors, product_role_map, "
            "typography_zones, commercial_intent, reusable_visual_strategy, "
            "original_remix_prompt, forbidden_transfer, post_generation_review. "
            "The product image is the only authority for product identity; the reference "
            "image supplies composition, scale, camera, lighting, typography geometry, "
            "depth order and commercial relationships only. Include at least five "
            "normalized 0..1 spatial anchors, explicit must_preserve/may_adapt/"
            "must_not_transfer relations, product role count and depth order. "
            "Keep original source brand, logo, watermark, exact wording and unsupported "
            "claims out of the result. The original_remix_prompt must put the hard "
            "composition skeleton before style adjectives and must be executable by "
            "an image model using the same two attached images. Return JSON only."
        )
    if request.planning_profile == "aurora_v20_visual_audit":
        return (
            "Directly inspect the last attached image as the generated Aurora "
            "v2.0 candidate; earlier images are original identity references. "
            "Return only the semantic fields in the strict native v2.0 "
            "visual-judgment response schema requested by the gateway. Do not "
            "return page_index, image_sha256, reviewer, image_path or "
            "audit_complete; the local runtime owns and binds those fields. "
            "observations must be a JSON object with every required member, "
            "never a string, list, null, prose paragraph or nested envelope. "
            "checks must be an ordered array "
            "containing every required_check_name exactly once, with material "
            "matching policy. Report only direct pixel observations and include "
            "check score values as 0-100 percentage numbers (write 98, never "
            "0.98); a passed check must have score at least 70. "
            "the exact values supplied in layout_observation_contract for "
            "composition_archetype_seen, product_zone_seen, copy_zone_seen, "
            "dominant_view_seen, and evidence_topology_seen; never paraphrase "
            "those tokens as free-form spatial prose. "
            "one complete deficiency for every material failed check. "
            "decision_summary must be a concrete direct-pixel verdict sentence "
            "with at least 12 characters; never use a one-word verdict such as "
            "PASS, 合格 or 通过."
        )
    if request.planning_profile == "aurora_style_calibration":
        return (
            "Directly compare the two attached accepted Aurora campaign pages. "
            "Return JSON with agent_pixel_reviewed=true, review_mode exactly "
            "DIRECT_PIXEL_VISUAL_COMPARISON, source_page_indexes [0,1], concrete "
            "observed_evidence, and nonempty style_tokens containing only shared "
            "photography_finish, light_direction, color_temperature, palette_roles, "
            "palette_usage_ratio, typography, graphic_language, "
            "information_surface_geometry, density_band, or prohibited_styles. "
            "Never put product identity, copy, camera, pose, or layout in style_tokens."
        )
    if request.planning_profile == "aurora_set_audit":
        return (
            "Blindly compare all six attached accepted Aurora pages in their supplied "
            "page order. Return the complete set-role-distinction JSON contract. "
            "Identify whether page 0 alone is visibly the search listing cover and "
            "give concrete pixel evidence explaining why each page 1 through 5 is "
            "not a search cover. Use the exact supplied image hashes."
        )
    if request.planning_profile == "aurora_visual_audit":
        return (
            "Directly inspect the last attached image as the generated candidate; "
            "all earlier images are original product identity references. Return a "
            "complete Aurora visual-judgment JSON object. Evaluate actual pixels, "
            "not the prompt or receipt. Cover every required check, record concrete "
            "pixel evidence, and list every material failed check exactly once in "
            "all_observed_deficiencies. Do not fail a page merely because it carries "
            "multiple related selling points. The first product_information entry "
            "contains the current approved proof contract and required field names."
        )
    if request.planning_profile == "aurora_identity":
        return (
            "Inspect all attached original images as complementary views of one "
            f"exact product named {request.product_name!r}. Return request_id "
            f"exactly as {request.job_id!r}. For every source return its asset_id "
            "and one or more concise view_tags. Build a factual product_form, an "
            "identity_summary, must_preserve invariants and must_not_change "
            "boundaries. Use only visible pixels for identity; ignore source "
            "backgrounds and do not add unverified product facts."
        )
    if request.planning_profile == "amazon_visual_suite":
        return _amazon_planner_prompt(request)
    if request.planning_profile == "crossborder_detail":
        return _legacy_planner_prompt(request) + _cross_page_lock_prompt_contract()
    if not request.domestic_protocol:
        return _legacy_planner_prompt(request)
    product_source_count = sum(
        source.source_role == "product_reference" for source in request.sources
    )
    style_source_count = sum(
        source.source_role == "style_reference" for source in request.sources
    )
    visible_request = replace(
        request,
        product_name=(
            request.product_name.strip() or "visible product from supplied images"
        ),
    )
    prompt = _legacy_planner_prompt(visible_request)
    legacy_source_contract = (
        f"All {len(request.sources)} attached images are ordered complementary "
        "angles of the same product. Analyze all angles together in this one "
    )
    domestic_source_contract = (
        f"The {product_source_count} product_reference image(s) are ordered "
        "complementary angles of the user's product and are the only images "
        "allowed to establish product identity or facts. The "
        f"{style_source_count} style_reference image(s) may provide only layout, "
        "hierarchy, mood, lighting direction, page rhythm, and composition "
        "devices. Never infer the user's product, brand, words, marks, materials, "
        "functions, specifications, ratings, claims, or other facts from a "
        "style_reference image. Analyze the product angles together in this one "
    )
    protocol_contract = (
        "needs_confirmation. Preserve all applicable skill-protocol objects in "
        "the JSON, including information confidence, buyer demand map, demand-"
        "to-selling-point match, product type strategy, reference visual style "
        "lock, page strategy, module plan, buyer demand, matched selling point, "
        "visual proof, required proof, risk reminder, and product identity or "
        "physical-logic locks. Put set-level fields under analysis or plan and "
        "current-page fields on the corresponding screen. Required object:"
    )
    return prompt.replace(
        legacy_source_contract,
        domestic_source_contract,
        1,
    ).replace(
        "needs_confirmation. Required object:",
        protocol_contract,
        1,
    )


def _cross_page_lock_prompt_contract(
    *,
    enforce_background_repeat_limit: bool = True,
) -> str:
    repeat_limit = (
        "No layout_family or background_system may occur more often than "
        "max_same_layout_family"
        if enforce_background_repeat_limit
        else "No layout_family may occur more often than max_same_layout_family"
    )
    return (
        " analysis.product_master_description is REQUIRED as a non-empty "
        "object that locks the exact SKU across all pages. "
        "plan.product_consistency_lock is REQUIRED as a non-empty object. "
        "plan.layout_diversity_lock is REQUIRED and must contain integer "
        "max_same_layout_family from 1 to 3 plus concise rules for varied "
        "layout, background, scale, camera, product position, props, and copy "
        "density. Every screen additionally requires buyer_question, "
        "layout_family, camera_angle, product_position, background_system, "
        "prop_strategy, and copy_density. Buyer questions must be unique. "
        f"{repeat_limit}, and the combined composition signature must be "
        "unique across all screens."
    )


def _amazon_planner_prompt(request: PlannerRequest) -> str:
    from .amazon_visual_suite_provider import (
        AMAZON_ITEM_ROLES,
        AMAZON_ITEM_SPECS,
        AMAZON_SKILL_ROW_ID_BY_ITEM_KEY,
    )

    task_table = [
        {
            "id": AMAZON_SKILL_ROW_ID_BY_ITEM_KEY[spec.item_key],
            "role": role,
            "asset_type": spec.asset_type,
            "final_size": f"{spec.width}x{spec.height}",
            "buyer_question": spec.buyer_question,
            "visual_proof": spec.visual_proof,
        }
        for spec, role in zip(AMAZON_ITEM_SPECS, AMAZON_ITEM_ROLES, strict=True)
    ]
    source_inventory = [
        {
            "ordinal": index,
            "asset_id": source.asset_id,
            "role": source.source_role,
            "filename": source.filename,
        }
        for index, source in enumerate(request.sources, start=1)
    ]
    return (
        "The complete bundled xinghe-amazon-visual-suite protocol in the system "
        "message is the sole authoritative creative and quality specification. "
        "Return exactly one JSON object satisfying the strict schema. Do not add "
        "extra locks, template systems, responsive pairing fields, final-screen "
        "rules, or any other planning constraint not required by that Skill. "
        "Analyze all supplied product sources together. Product, detail, package, "
        "and brand sources may establish facts only within visible evidence. Style "
        "and competitor references may guide category conventions and composition "
        "only; never copy them or infer this SKU's facts from them. Classify claims "
        "as confirmed, reasonable inference, or needs confirmation. Do not place a "
        "needs-confirmation claim in image copy. Build Product Image Analysis, "
        "Information Confidence, Buyer Demand Map, Demand-to-Selling-Point Match, "
        "Product Master Description, Campaign Style Lock, Product Consistency Lock, "
        "Layout Diversity Lock, and the complete 21-row task table. Return the rows "
        "in the exact canonical id order and preserve each final_size. Every row must "
        "answer one buyer question with one dominant selling point and visual proof. "
        "MAIN-01 must use the real uploaded white_background_product source, preserve "
        "authentic product logos, labels, and readable product text, clean the "
        "surrounding background to white, and add no new text, props, badges, ratings, "
        "or invented accessories. Do not reject a usable real-product source merely "
        "because its surrounding background is imperfect or authentic branding is "
        "visible. Desktop and mobile A+ rows may share selling logic but must describe "
        "independent compositions for their own final aspect ratios. For each "
        "source_material field, name the exact role labels from the supplied source "
        "inventory that the row needs; product truth sources remain available to every "
        "row, while optional brand, packaging, lifestyle, style, and competitor roles "
        "are attached only when named. "
        f"Product={request.product_name!r}; marketplace={request.platform_code!r}; "
        f"language={request.language!r}; supplied information="
        f"{list(request.product_information)!r}; source inventory="
        f"{json.dumps(source_inventory, ensure_ascii=False, separators=(',', ':'))}; "
        "canonical Skill task table="
        f"{json.dumps(task_table, ensure_ascii=False, separators=(',', ':'))}."
    )


def _legacy_planner_prompt(request: PlannerRequest) -> str:
    return (
        f"Return exactly one JSON object for product group {request.group_key!r}. "
        f"All {len(request.sources)} attached images are ordered complementary "
        "angles of the same product. Analyze all angles together in this one "
        f"planning call and return exactly {request.page_count} screens in "
        f"{request.language}. Use only visible facts and this user information: "
        f"product={request.product_name!r}; points="
        f"{list(request.product_information)!r}; platform="
        f"{request.platform_code!r}. Any negative instruction, exclusion, or "
        "prohibited claim in points is an explicit, non-negotiable hard "
        "constraint, not reference information. It applies to every safety-"
        "relevant field of every plan screen, including role, title, label, "
        "composition, device, and difference, and must never be violated. "
        "Never claim leather, comfort, durability, or wear resistance, even "
        "when such a claim appears visually plausible. "
        "Treat visible watermarks, including FALILIAN when visible, as source "
        "marks, not product branding or selling points. Uncertain content must "
        "be marked "
        "needs_confirmation. Required object: analysis.category_key, "
        "analysis.category_reason, analysis.product_image_analysis, "
        "analysis.product_consistency_anchors, analysis.buyer_objections, "
        "plan.campaign_style_lock, plan.design_strength_lock, and plan.screens. "
        "The JSON member at RFC 6901 path "
        "/analysis/product_consistency_anchors is REQUIRED: place it inside "
        "the top-level analysis object and always emit it as a JSON object; "
        "never omit it. "
        "campaign_style_lock MUST be an object with non-empty palette, "
        "typography, background, lighting, icon_style, whitespace, and "
        "product_scale strings. design_strength_lock MUST be an object with "
        "non-empty category_visual_motif, composition_contrast, "
        "color_contrast, and template_ban strings; signature_devices MUST "
        "contain at least two distinct devices when two or more pages are "
        "requested; rhythm_map MUST contain exactly one non-empty entry per "
        "screen. Every screen requires role, title, label, composition, "
        "device, difference, structure, and subject_scale. subject_scale "
        "MUST be exactly one of hero, medium, macro, scene, information, "
        "cutaway, or overhead. Use at least five distinct roles, four "
        "distinct structures, three subject scales, and two substantively "
        "different devices when the requested page count permits; for fewer "
        "pages use as many distinct values as there are pages. No more than "
        "half the screens rounded up may use hero. When more than one page "
        "is requested, the final role MUST be exactly closing_summary. "
        "Each page has one core selling point, one visual hero, one "
        "main title, and one short label; at most one zoom and two structural "
        "callouts; no collage, repeated crop windows, invented materials, "
        "functions, parameters, certifications, efficacy, sales, or reviews."
    )


def _planner_message_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise XingheAgentError(
            "PLANNER_RESPONSE_INVALID",
            "Planner response has no choices.",
            json_pointer=_json_pointer("choices"),
        )
    choice = _require_mapping(
        choices[0],
        "PLANNER_RESPONSE_INVALID",
        path=_json_pointer("choices", 0),
    )
    message = _require_mapping(
        choice.get("message"),
        "PLANNER_RESPONSE_INVALID",
        path=_json_pointer("choices", 0, "message"),
    )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise XingheAgentError(
            "PLANNER_RESPONSE_INVALID",
            "Planner response has no JSON content.",
            json_pointer=_json_pointer("choices", 0, "message", "content"),
        )
    return content


def _planner_content_payload(content: str) -> object:
    """Decode only a full JSON value or one complete, unambiguous JSON fence.

    Outer whitespace is stripped. A fence may be untagged or use a
    case-insensitive ``json`` tag, followed by spaces/tabs and LF or CRLF.
    Nothing except spaces/tabs may follow the closing fence before outer
    whitespace is stripped.
    """

    payload, _ = _planner_content_payload_with_trace(content)
    return payload


def _planner_content_payload_with_trace(
    content: str,
) -> tuple[object, tuple[str, ...]]:
    """Decode planner content while recording only fixed, content-free stages."""

    stripped = content.strip()
    try:
        decoded = json.loads(stripped)
        return decoded, (
            "whole_json:decoded",
            f"whole_json:decoded_kind:{_decoded_json_kind(decoded)}",
        )
    except json.JSONDecodeError:
        match = _PLANNER_JSON_FENCE.fullmatch(stripped)
        if match is None:
            return content, (
                "whole_json:decode_failed",
                "fence:not_matched",
            )
    try:
        decoded = json.loads(match.group("body"))
        return decoded, (
            "whole_json:decode_failed",
            "fence:matched",
            "fence_json:decoded",
            f"fence_json:decoded_kind:{_decoded_json_kind(decoded)}",
        )
    except json.JSONDecodeError:
        return content, (
            "whole_json:decode_failed",
            "fence:matched",
            "fence_json:decode_failed",
        )


def _with_planner_observability(
    result: PlannerCallResult,
) -> PlannerCallResult:
    trace = result.parse_trace
    if not trace:
        trace = (
            ("provider_payload:not_available",)
            if result.error_code is not None
            else ("gateway_payload:predecoded",)
        )
    fingerprint = result.structure_fingerprint
    if fingerprint is None and result.error_code is None:
        fingerprint = _planner_structure_fingerprint(result.payload)
    profile = result.structure_profile
    if profile is None and result.error_code is None:
        profile = _planner_structure_profile(result.payload)
    return replace(
        result,
        parse_trace=trace,
        structure_fingerprint=fingerprint,
        structure_profile=profile,
        provider_envelope=(
            result.provider_envelope
            if result.provider_envelope is not None
            else _unavailable_planner_envelope_diagnostics()["provider_envelope"]
        ),
    )


def _decoded_json_kind(value: object) -> str:
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    if value is None:
        return "null"
    return "scalar"


def _safe_json_kind(value: object) -> str:
    if value is _MISSING_JSON_VALUE:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "non_json"


def _planner_raw_content(payload: object) -> object:
    if not isinstance(payload, Mapping):
        return _MISSING_JSON_VALUE
    choices = payload.get("choices", _MISSING_JSON_VALUE)
    if not isinstance(choices, list) or not choices:
        return _MISSING_JSON_VALUE
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return _MISSING_JSON_VALUE
    message = choice.get("message", _MISSING_JSON_VALUE)
    if not isinstance(message, Mapping):
        return _MISSING_JSON_VALUE
    return message.get("content", _MISSING_JSON_VALUE)


def _planner_envelope_diagnostics(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    choices = payload.get("choices", _MISSING_JSON_VALUE)
    choice0 = (
        choices[0] if isinstance(choices, list) and choices else _MISSING_JSON_VALUE
    )
    message = (
        choice0.get("message", _MISSING_JSON_VALUE)
        if isinstance(choice0, Mapping)
        else _MISSING_JSON_VALUE
    )
    content = (
        message.get("content", _MISSING_JSON_VALUE)
        if isinstance(message, Mapping)
        else _MISSING_JSON_VALUE
    )
    usage = payload.get("usage", _MISSING_JSON_VALUE)
    usage_presence = "absent" if usage is _MISSING_JSON_VALUE else "present"
    usage_completeness = "absent"
    if usage_presence == "present":
        usage_completeness = (
            "complete" if _planner_usage_is_complete(usage) else "incomplete"
        )
    return {
        "provider_envelope": {
            "envelope_kind": _safe_json_kind(payload),
            "choices_kind": _safe_json_kind(choices),
            "choices_count": len(choices) if isinstance(choices, list) else None,
            "choice0_kind": _safe_json_kind(choice0),
            "message_kind": _safe_json_kind(message),
            "content_kind": _safe_json_kind(content),
        },
        "request_id_presence": (
            "present" if _safe_request_id(payload) is not None else "absent"
        ),
        "usage_presence": usage_presence,
        "usage_completeness": usage_completeness,
    }


def _unavailable_planner_envelope_diagnostics() -> dict[str, Any]:
    return {
        "provider_envelope": {
            "envelope_kind": "not_available",
            "choices_kind": "not_available",
            "choices_count": None,
            "choice0_kind": "not_available",
            "message_kind": "not_available",
            "content_kind": "not_available",
        },
        "request_id_presence": "not_available",
        "usage_presence": "not_available",
        "usage_completeness": "not_available",
    }


def _planner_usage_is_complete(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    input_tokens = value.get("input_tokens", value.get("prompt_tokens"))
    output_tokens = value.get("output_tokens", value.get("completion_tokens"))
    return all(
        _usage_integer(item) is not None
        for item in (input_tokens, output_tokens, value.get("total_tokens"))
    )


def _planner_structure_fingerprint(payload: object) -> str:
    """Hash a value-free schema profile for safe response correlation."""

    return canonical_hash(
        {
            "version": PLANNER_OBSERVABILITY_VERSION,
            "profile": _planner_structure_profile(payload),
        }
    )


def _planner_structure_profile(payload: object) -> dict[str, Any]:
    """Return a bounded, value-free profile of the planner response shape."""

    profile: dict[str, Any] = {
        "root": _json_shape_summary(payload),
    }
    if not isinstance(payload, Mapping):
        return profile
    profile["root"] = _known_fields_profile(
        payload,
        ("analysis", "plan"),
    )
    analysis = payload.get("analysis", _MISSING_JSON_VALUE)
    profile["analysis"] = _known_fields_profile(
        analysis,
        (
            "category_key",
            "category_reason",
            "product_image_analysis",
            "product_consistency_anchors",
            "buyer_objections",
            "information_confidence",
            "buyer_demand_map",
            "demand_to_selling_point_match",
            "product_master_description",
        ),
    )
    plan = payload.get("plan", _MISSING_JSON_VALUE)
    profile["plan"] = _known_fields_profile(
        plan,
        (
            "campaign_style_lock",
            "design_strength_lock",
            "product_consistency_lock",
            "suite_cohesion_lock",
            "layout_diversity_lock",
            "screens",
        ),
    )
    if isinstance(plan, Mapping):
        screens = plan.get("screens", _MISSING_JSON_VALUE)
        profile["screens"] = _json_shape_summary(screens)
        if isinstance(screens, list):
            profile["screen_items"] = [
                _known_fields_profile(
                    screen,
                    (
                        "role",
                        "title",
                        "label",
                        "composition",
                        "device",
                        "difference",
                        "structure",
                        "subject_scale",
                        "buyer_question",
                        "layout_family",
                        "camera_angle",
                        "product_position",
                        "background_system",
                        "prop_strategy",
                        "copy_density",
                        "item_key",
                        "asset_type",
                        "final_size",
                        "selling_point",
                        "information_confidence",
                        "visual_proof",
                        "headline",
                        "subcopy",
                        "layout_direction",
                        "source_material",
                        "risk_note",
                        "responsive_concept",
                    ),
                )
                for screen in screens[:_MAX_PROTOCOL_COLLECTION_LENGTH]
            ]
    return profile


def _known_fields_profile(
    value: object,
    expected_fields: Sequence[str],
) -> dict[str, Any]:
    summary = _json_shape_summary(value)
    if not isinstance(value, Mapping):
        return summary
    expected = set(expected_fields)
    return {
        **summary,
        "unknown_field_count": sum(key not in expected for key in value),
        "fields": {
            field: _json_shape_summary(value.get(field, _MISSING_JSON_VALUE))
            for field in expected_fields
        },
    }


def _json_shape_summary(value: object) -> dict[str, Any]:
    if value is _MISSING_JSON_VALUE:
        return {"type": "missing"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, int | float):
        return {"type": "number"}
    if isinstance(value, Mapping):
        return {"type": "object", "field_count": len(value)}
    if isinstance(value, list):
        sampled = value[:_MAX_PROTOCOL_COLLECTION_LENGTH]
        item_types: dict[str, int] = {}
        for item in sampled:
            item_type = str(_json_shape_summary(item)["type"])
            item_types[item_type] = item_types.get(item_type, 0) + 1
        return {
            "type": "array",
            "item_count": len(value),
            "profiled_item_count": len(sampled),
            "truncated": len(sampled) != len(value),
            "item_types": dict(sorted(item_types.items())),
        }
    return {"type": "non_json"}


def _image_bytes(payload: Mapping[str, Any]) -> bytes:
    data = payload.get("data")
    item: Mapping[str, Any] = payload
    if isinstance(data, list) and data:
        item = _require_mapping(data[0], "IMAGE_RESPONSE_INVALID")
    encoded = item.get("b64_json") or item.get("base64") or item.get("image_base64")
    if not isinstance(encoded, str) or not encoded:
        raise XingheAgentError(
            "IMAGE_RESPONSE_INVALID",
            "Image response omitted inline image bytes.",
        )
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise XingheAgentError(
            "IMAGE_RESPONSE_INVALID",
            "Image response contained invalid base64.",
        ) from exc


def _raw_usage(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    usage = payload.get("usage")
    return dict(usage) if isinstance(usage, dict) else None


def _safe_request_id(payload: Mapping[str, Any]) -> str | None:
    for key in ("request_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:255]
    return None


def _encode_multipart(
    boundary: str,
    fields: Sequence[tuple[str, str]],
    files: Sequence[tuple[str, str, str, bytes]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{_multipart_token(name)}"'
                    "\r\n\r\n"
                ).encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, filename, content_type, payload in files:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    "Content-Disposition: form-data; "
                    f'name="{_multipart_token(field_name)}"; '
                    f'filename="{_multipart_token(filename)}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                payload,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def _multipart_token(value: str) -> str:
    return (
        value.replace("\\", "_")
        .replace('"', "_")
        .replace("\r", "_")
        .replace(
            "\n",
            "_",
        )
    )


def _strict_page_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "Page count must be an integer from 1 through 12.",
        )
    return value


def _json_pointer(*tokens: str | int) -> str:
    if not tokens:
        return "/"
    return "".join(
        f"/{str(token).replace('~', '~0').replace('/', '~1')}" for token in tokens
    )


def _require_mapping(
    value: object,
    code: str,
    *,
    path: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise XingheAgentError(
            code,
            "Expected a JSON object.",
            json_pointer=path,
        )
    return dict(value)


def _require_nonempty_string(
    value: object,
    field_name: str,
    *,
    path: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            f"Required text field {field_name!r} is missing.",
            json_pointer=path,
        )
    return value.strip()


def _usage_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return None


def _usage_cost_micros(raw_usage: object) -> int | None:
    if not isinstance(raw_usage, dict):
        return None
    for key in ("actual_cost_micros", "cost_micros"):
        value = _usage_integer(raw_usage.get(key))
        if value is not None:
            return value
    return None


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _elapsed_seconds(started_at: datetime, finished_at: datetime) -> float:
    if started_at.tzinfo is None and finished_at.tzinfo is not None:
        finished_at = finished_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=started_at.tzinfo)
    return (finished_at - started_at).total_seconds()


def _planner_usage_missing(payload: Mapping[str, Any]) -> int:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0
    planner = usage.get("planner")
    if not isinstance(planner, list):
        return 0
    return sum(
        isinstance(record, dict) and not bool(record.get("reported"))
        for record in planner
    )
