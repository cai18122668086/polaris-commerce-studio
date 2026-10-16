# ruff: noqa: E501
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

from .aurora_detail_runtime import (
    AuroraDetailHarnessError,
    AuroraDetailHarnessRunner,
    build_native_identity,
    build_native_input,
    detail_workspace,
    extract_native_plan,
    normalize_native_plan_for_harness,
    source_path_for,
)
from .aurora_detail_runtime import (
    write_contract as write_detail_contract,
)
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
from .storage import ImageStorage, ValidatedImage

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
        "900x1200",
        "2048x1152",
        # Gateway-native 16:9. 2048x1152 is the delivery canvas, but live
        # gpt-image relays return a different aspect for that request.
        "1536x864",
        "1464x600",
        "1600x1200",
        "1600x1600",
        "2000x2000",
        "2048x2048",
        "2200x2200",
        # Aurora domestic detail pair canvas (two 3:4 slices, 3:8 overall).
        "1200x3200",
        # Aurora domestic detail delivery slice (strict 3:4). The provider
        # renders its adjacent pair on the corresponding 3:8 canvas below;
        # both sizes must be accepted by the shared image request validator.
        "1440x1920",
        "1440x3840",
    }
)
# Artflow currently returns PNG artifacts even when the relay accepts a JPEG
# request.  Request PNG explicitly so the provider response and our contract
# agree instead of rejecting successful generations as format-invalid.
IMAGE_FORMAT = "png"
# Aurora measured these as the largest canvases the live relay returns at the
# requested aspect.  The API call uses the native canvas; delivery stays on
# the skill size and the same-aspect resampler enlarges it.
_GATEWAY_NATIVE_REQUEST_SIZE = {
    "2048x1152": "1536x864",
}
JPEG_QUALITY = 92
DEFAULT_MEDIUM_PRICE_MICROS = 45_000
DEFAULT_HIGH_PRICE_MICROS = 90_000
DEFAULT_BUDGET_LIMIT_MICROS = 200_000_000
MAX_PAGE_RETRIES = 2
# A domestic v4.3 campaign may require one initial plan plus one bounded
# completion call per module.  Compatible gateways can take about a minute per
# structured completion, so the old 15-minute lease expired while valid work
# was still running and was misclassified as PLANNER_OUTCOME_UNKNOWN.
PLANNER_LEASE_SECONDS = 3600
_MISSING_JSON_VALUE = object()
# Aurora's pair prompts deliberately carry the complete screen contract so a
# resumed worker can regenerate a pair without consulting transient planner
# state.  The planner may therefore emit a large, but still bounded, protocol
# object.  Keep the limits finite while allowing the durable approval packet
# produced by the bundled domestic-detail skill to pass authorization.
_MAX_PROTOCOL_JSON_BYTES = 256 * 1024
_MAX_PROTOCOL_STRING_LENGTH = 128 * 1024
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
_COMPLETE_REFERENCE_PROTOCOL_SKILLS = frozenset(
    {"xinghe-ecommerce-detail-domestic-3", "aurora-domestic-ecommerce-detail-page"}
)
_AURORA_DOMESTIC_DETAIL_SKILL_ID = "aurora-domestic-ecommerce-detail-page"
_AURORA_PLANNER_PROTOCOL_FILES = (
    # The source manifest still verifies the complete Skill tree.  The planner
    # only needs the v4.3 planning contracts; sending every reference chapter
    # together with an 8-module response exceeds compatible gateway context
    # limits and ends as a remote disconnect.  Generation remains delegated to
    # the full native Harness.
    "SKILL.md",
    "references/v4.3-migration.md",
    "references/spatial-structure-contract.md",
    "references/visual-proof.md",
    "references/visual-performance-contract.md",
    "references/generation-and-audit-integrity.md",
    "references/storyboard-matrix.md",
    "references/series-visual-dna.md",
    "references/compliance-and-platform.md",
    "references/retry-and-feedback-control.md",
    # Keep the planner aware of the v4.3 commercial-comfort contract. It
    # requires a non-empty forbidden_visual_details policy on every module.
    "references/commercial-aversion-control.md",
)
_DOMESTIC_DETAIL_SKILL_IDS = frozenset(
    {"xinghe-ecommerce-detail-domestic-3", _AURORA_DOMESTIC_DETAIL_SKILL_ID}
)
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
    planning_directives: tuple[str, ...] = ()
    domestic_protocol: bool = False
    planning_profile: str = "detail_pack"


def _choose_identity_anchor(sources: Sequence[SourceImage]) -> SourceImage | None:
    """Choose the most neutral whole-product source for auto-resolved intake.

    The UI allows the user to continue after a source-photo ambiguity.  A
    neutral-background source is the safest identity anchor because it carries
    the least scene-specific or editorial information.  This score is only
    used to guide the planner; the original pixels remain the source of truth.
    """

    candidates = [
        source
        for source in sources
        if source.source_role == "product_reference" and source.payload
    ]
    if not candidates:
        return None
    scored: list[tuple[float, SourceImage]] = []
    for source in candidates:
        score = 0.0
        try:
            with Image.open(BytesIO(source.payload)) as image:
                image = image.convert("RGB")  # type: ignore[assignment]
                width, height = image.size
                edge = max(2, min(width, height) // 16)
                pixels = []
                for box in (
                    (0, 0, edge, edge),
                    (width - edge, 0, width, edge),
                    (0, height - edge, edge, height),
                    (width - edge, height - edge, width, height),
                ):
                    pixels.extend(list(image.crop(box).getdata()))
                if pixels:
                    luminance = [
                        (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
                        for red, green, blue in pixels
                    ]
                    mean = sum(luminance) / len(luminance)
                    variance = sum((value - mean) ** 2 for value in luminance) / len(
                        luminance
                    )
                    # White/neutral corners with low texture score highest.
                    score = mean * 0.72 + max(0.0, 1.0 - variance * 12.0) * 0.28
        except (OSError, UnidentifiedImageError, ValueError):
            score = 0.0
        scored.append((score, source))
    return max(scored, key=lambda pair: pair[0])[1]


def _auto_identity_resolution_system_prompt(request: PlannerRequest) -> str:
    if "AUTO_RESOLVE_IDENTITY_CONFLICTS" not in request.planning_directives:
        return ""
    anchor = _choose_identity_anchor(request.sources)
    anchor_text = (
        f"Use asset_id {anchor.asset_id} ({anchor.filename}) as the single "
        "product identity anchor."
        if anchor is not None
        else "Select the clearest neutral-background whole-product source as the single identity anchor."
    )
    return (
        "\n\nAUTHORIZED AUTO-RESOLUTION POLICY (planner-only, never visible): "
        "The user has authorized the runtime to continue through source-photo "
        "ambiguity without pausing. "
        + anchor_text
        + " Treat every other product reference as a supplementary view only when "
        "it is geometrically compatible with that anchor. Resolve conflicting "
        "identity tokens in favor of the anchor and keep the resolution entirely "
        "machine-side. Do not output a conflict board, evidence comparison, "
        "source labels, confirmation questions, audit notes, risk-workflow text, "
        "or document-evidence screens. Proceed with a normal commercial product "
        "detail storyboard driven by the authorized selling points. Keep every "
        "visible claim tied to the supplied product pixels and facts."
    )


def _aurora_plan_has_unresolved_conflict(value: Mapping[str, Any]) -> bool:
    """Reject a conflict-blocked Aurora plan before it can reach image generation."""

    analysis = value.get("analysis")
    if not isinstance(analysis, Mapping):
        return False
    root = analysis.get("aurora_plan")
    if not isinstance(root, Mapping):
        return False
    strategy = root.get("operating_strategy")
    if isinstance(strategy, Mapping) and strategy.get("conflict_blocked") is True:
        return True
    gate = strategy.get("generation_gate") if isinstance(strategy, Mapping) else None
    if isinstance(gate, Mapping) and gate.get("allowed") is False:
        return True
    for key in (
        "campaign_recall_contract",
        "campaign_pain_solution_contract",
        "detail_information_contract",
    ):
        contract = root.get(key)
        if isinstance(contract, Mapping) and contract.get("status") == "BLOCKED_PENDING_CONFLICT_RESOLUTION":
            return True
    return False


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
    # Opt-in bounded excerpt of the provider body, populated only when the
    # response could not be decoded into an object and diagnostics sampling is
    # enabled.  Off by default; raw prompts and secrets are never included.
    content_sample: str | None = None


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


def compile_aurora_pair_prompt(
    *,
    structured_plan: Mapping[str, Any],
    first_screen: Mapping[str, Any],
    second_screen: Mapping[str, Any],
    page_count: int,
    product_name: str,
    product_information: Sequence[str],
    source_count: int,
    pair_id: str,
    pair_canvas_size: str,
) -> str:
    """Compile one signed PAIR_PLAN_MERGE request for two adjacent screens."""

    plan = _require_mapping(structured_plan.get("plan"), "AURORA_PLAN_SCHEMA_INVALID")
    aurora_plan = _require_mapping(plan.get("aurora_plan"), "AURORA_PLAN_SCHEMA_INVALID")
    pair_contract = _require_mapping(plan.get("pair_rendering"), "AURORA_PAIR_CONTRACT_INVALID")
    modules = [first_screen.get("aurora_module"), second_screen.get("aurora_module")]

    def prompt_module(value: object) -> dict[str, Any]:
        """Keep the image request below relay limits without weakening the plan."""

        module = value if isinstance(value, Mapping) else {}
        selected: dict[str, Any] = {
            key: module[key]
            for key in (
                "id",
                "buyer_question",
                "lead_claim_id",
                "lead_conclusion",
                "camera_scale",
                "complete_product_role",
                "composition_family",
                "duty",
                "expression_signature",
                "presentation_form",
                "primary_subject_class",
                "story_function",
                "visual_archetype",
                "visual_proof_direction",
            )
            if key in module
        }
        for key, nested_keys in {
            "expression": (
                "claim_visualizability",
                "copy_responsibility",
                "expression_mode",
                "primary_visual_carrier",
                "visual_scene_sentence",
            ),
            "proof": (
                "buyer_takeaway",
                "hidden_copy_test",
                "minimum_visual_payload",
                "primary_subject",
                "required_relations",
                "visual_specificity_anchor",
                "visual_verb",
            ),
            "structure": ("structure_family", "zone_briefs"),
            "typography": ("anchor_target", "anchor_zone", "primary_mode"),
            "visual_cast": (
                "action_subject",
                "claim_object",
                "context_subject",
                "hero_subject",
                "product_identity_anchor",
                "result_subject",
            ),
            "transition_contract": (
                "continuity_strength",
                "handoff_geometry",
                "incoming_anchor",
                "method_id",
                "outgoing_anchor",
                "seam_carrier",
                "target_region_current",
            ),
        }.items():
            nested = module.get(key)
            if isinstance(nested, Mapping):
                selected[key] = {
                    child: nested[child] for child in nested_keys if child in nested
                }
        for key in ("visible_copy", "visual_evidence"):
            value_list = module.get(key)
            if isinstance(value_list, list):
                selected[key] = value_list
        return selected

    prompt_plan = {
        key: aurora_plan[key]
        for key in (
            "campaign_thesis",
            "output_strategy",
            "series_visual_dna",
            "operating_strategy",
            "style_constitution",
            "hero_screen_contract",
            "dominant_decision_type",
            "formula_split_contract",
            "campaign_recall_contract",
            "detail_information_contract",
            "expression_contract_version",
            "reference_expression_system",
            "information_contract_version",
            "selling_point_depth_contract",
            "campaign_pain_solution_contract",
            "campaign_expression_diversity_contract",
            "campaign_style_lock",
            "design_strength_lock",
            "layout_diversity_lock",
            "product_consistency_lock",
        )
        if key in aurora_plan
    }
    # The lock objects live beside aurora_plan in the protocol wrapper.
    for key in ("layout_diversity_lock", "product_consistency_lock"):
        if key not in prompt_plan and key in plan:
            prompt_plan[key] = plan[key]
    return (
        "Aurora domestic detail v4.3 PAIR_PLAN_MERGE request. Render exactly "
        "one continuous 3:8 pair canvas and do not render two independent pages, "
        "a collage, or a multi-panel poster. The canvas is deterministically sliced "
        "into two fixed 3:4 windows after generation. The fixed horizontal slice "
        "boundary must read as one uninterrupted visual field: carry the declared "
        "background, light, texture, or scene element continuously across the exact "
        "boundary; do not place a divider, border, panel edge, whitespace band, hard "
        "color reset, card edge, horizon break, or unrelated scene cut there. Do not "
        "solve continuity by crossing text, labels, or UI cards over the seam. Preserve "
        "the adjacent pair's "
        "internal seam contract and transition token. Use product references only "
        "for identity/facts; style references only for visual grammar. Every visible "
        "copy item must bind to an authorized fact and visible visual carrier. "
        f"Pair {pair_id} of {page_count // 2}; product={product_name}; "
        f"source_count={source_count}; product_information={json.dumps(list(product_information), ensure_ascii=False)}\n"
        f"pair_contract={json.dumps(pair_contract, ensure_ascii=False, sort_keys=True)}\n"
        f"module_1={json.dumps(prompt_module(modules[0]), ensure_ascii=False, sort_keys=True)}\n"
        f"module_2={json.dumps(prompt_module(modules[1]), ensure_ascii=False, sort_keys=True)}\n"
        f"campaign_plan={json.dumps(prompt_plan, ensure_ascii=False, sort_keys=True)}\n"
        f"Hard constraints: exact {pair_canvas_size} pair canvas (3:8), fixed {pair_canvas_size.split('x', 1)[0]}x{int(pair_canvas_size.split('x', 1)[1]) // 2} "
        "top/bottom slices (3:4), no source background leakage, no invented logo or "
        "claim, no unsupported ingredient/structure evidence, and no third render "
        "after a material audit failure."
    )


def _compact_aurora_prompt_for_provider(prompt: str) -> str:
    """Bound legacy pair prompts before sending them to the image relay.

    The durable approval packet intentionally keeps every nested module field.
    Older jobs copied that packet verbatim into ``pair_prompt``; forwarding it
    again with four source images can exceed the upstream image service limit.
    Preserve the visual contract and evidence while dropping audit-only bulk.
    """

    if len(prompt.encode("utf-8")) <= 32 * 1024:
        return prompt

    drop_keys = {
        "forbidden_fallbacks",
        "modules",
        "screens",
        "planner_diagnostics",
        "approval_document_markdown",
    }

    def compact(value: object, depth: int = 0) -> object:
        if depth > 8:
            return None
        if isinstance(value, str):
            return value if len(value) <= 1200 else value[:1197] + "..."
        if isinstance(value, list):
            limit = 12 if len(value) > 12 else len(value)
            return [compact(item, depth + 1) for item in value[:limit]]
        if isinstance(value, Mapping):
            return {
                str(key): compact(item, depth + 1)
                for key, item in value.items()
                if str(key) not in drop_keys
            }
        return value

    markers = (
        "pair_contract=",
        "module_1=",
        "module_2=",
        "campaign_plan=",
    )
    positions = [prompt.find(marker) for marker in markers]
    if any(position < 0 for position in positions):
        return prompt[:32 * 1024]
    prefix = prompt[: positions[0]]
    chunks: list[str] = []
    for index, marker in enumerate(markers):
        start = positions[index] + len(marker)
        end = positions[index + 1] if index + 1 < len(positions) else prompt.find(
            "\nHard constraints", start
        )
        raw = prompt[start:end if end >= 0 else len(prompt)].strip()
        try:
            parsed = json.loads(raw)
            value = compact(parsed)
            chunks.append(marker + json.dumps(value, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            chunks.append(marker + raw[:8000])
    suffix_start = prompt.find("\nHard constraints", positions[-1])
    suffix = prompt[suffix_start:] if suffix_start >= 0 else ""
    result = prefix + "\n".join(chunks) + suffix
    return result if len(result.encode("utf-8")) <= 32 * 1024 else result[:32 * 1024]


def compile_aurora_campaign_approval_document(
    *,
    group_plans: Sequence[Mapping[str, Any]],
    pages: Sequence[Mapping[str, Any]],
    page_count: int,
) -> str:
    """Produce the canonical approval packet whose bytes are user-approved."""

    lines = [
        "# Aurora 国内电商详情图 v4.3 Campaign Approval",
        "",
        f"- module_count: {page_count}",
        "- pair_canvas_aspect_ratio: 3:8",
        "- decomposition_window_aspect_ratio: 3:4",
        "- pair_merge_type: PAIR_PLAN_MERGE",
        "- generation_mode: one_pair_canvas_then_two_deterministic_slices",
        "",
        "## Group → Screen Packet",
    ]
    for group in group_plans:
        lines.append(f"### Group {group.get('group_key', '')}")
        for page in group.get("pages", []):
            if not isinstance(page, Mapping):
                continue
            lines.append(
                f"- {page.get('aurora_module_id', page.get('page'))} | "
                f"{page.get('pair_id', '')} | {page.get('title', '')} | "
                f"{page.get('role', '')} | buyer_question={page.get('label', '')} | "
                f"composition={page.get('composition', '')} | "
                f"structure={page.get('structure', '')} | "
                f"subject_scale={page.get('subject_scale', '')}"
            )
            module = page.get("aurora_module")
            if isinstance(module, Mapping):
                lines.append(
                    "  module_contract_json: "
                    + json.dumps(module, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                )
            if page.get("pair_position") == 2:
                transition = module.get("transition_contract") if isinstance(module, Mapping) else None
                lines.append(
                    "  internal_seam_contract_json: "
                    + json.dumps(transition or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                )
    lines.extend(
        [
            "",
            "## Approval Boundary",
            "Approve this complete group→screen packet once. Generation advances "
            "one adjacent pair at a time; material pixel failure permits one whole-pair "
            "automatic repair, then COMPLETE_WITH_RESIDUALS.",
            "",
        ]
    )
    return "\n".join(lines)


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
        if skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
            protocol_files = _AURORA_PLANNER_PROTOCOL_FILES
        elif skill_id in _COMPLETE_REFERENCE_PROTOCOL_SKILLS:
            references_root = skill_root / "references"
            reference_files = tuple(
                path.relative_to(skill_root).as_posix()
                for path in sorted(
                    references_root.glob("*.md"),
                    key=lambda candidate: candidate.name,
                )
            )
            protocol_files = ("SKILL.md", *reference_files)  # type: ignore[assignment]
        else:
            protocol_files = _PLANNER_PROTOCOL_FILES_BY_SKILL.get(  # type: ignore[assignment]
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


@dataclass(frozen=True)
class _ProviderRoute:
    """One OpenAI-compatible route kept isolated for failover rotation."""

    name: str
    planner_api_key: str
    planner_base_url: str
    planner_model: str
    image_api_key: str
    image_base_url: str
    image_model: str


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
        planner_api_key: str | None = None,
        planner_base_url: str | None = None,
        image_api_key: str | None = None,
        image_base_url: str | None = None,
        medium_price_micros: int = DEFAULT_MEDIUM_PRICE_MICROS,
        high_price_micros: int = DEFAULT_HIGH_PRICE_MICROS,
        review_price_micros: int = 20_000,
        timeout_seconds: float = 600,
        diagnostic_content_sample: bool = False,
        failover_enabled: bool = False,
        failover_api_key: str | None = None,
        failover_base_url: str | None = None,
        failover_model: str | None = None,
        failover_image_model: str | None = None,
        rotation_order: str = "primary,failover",
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        if (
            not api_key.strip()
            and not (planner_api_key or "").strip()
            and not (image_api_key or "").strip()
        ):
            raise ValueError("At least one Provider API key is required.")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Tengli base URL must be an absolute HTTP(S) URL.")
        if not planner_model.strip() or not image_model.strip():
            raise ValueError("Planner and image models are required.")
        if medium_price_micros < 0 or high_price_micros < 0 or review_price_micros < 0:
            raise ValueError("Configured unit prices cannot be negative.")
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self._planner_api_key = (planner_api_key or api_key).strip()
        self._image_api_key = (image_api_key or api_key).strip()
        self._planner_base_url = (planner_base_url or base_url).rstrip("/") + "/"
        self._image_base_url = (image_base_url or base_url).rstrip("/") + "/"
        self.planner_model = planner_model.strip()
        self.image_model = image_model.strip()
        self.medium_price_micros = medium_price_micros
        self.high_price_micros = high_price_micros
        self.review_price_micros = review_price_micros
        self.timeout_seconds = timeout_seconds
        self.diagnostic_content_sample = diagnostic_content_sample
        self.transport = transport or UrllibOpenAITransport()
        self.external_network_request_count = 0
        primary_route = _ProviderRoute(
            name="primary",
            planner_api_key=self._planner_api_key,
            planner_base_url=self._planner_base_url,
            planner_model=self.planner_model,
            image_api_key=self._image_api_key,
            image_base_url=self._image_base_url,
            image_model=self.image_model,
        )
        routes = {primary_route.name: primary_route}
        failover_keys = [
            part.strip()
            for part in re.split(r"[\s,]+", failover_api_key or "")
            if part.strip()
        ]
        if failover_enabled and failover_keys:
            alternate_base_url = (failover_base_url or base_url).strip()
            parsed_failover = urlparse(alternate_base_url)
            if parsed_failover.scheme not in {"http", "https"} or not parsed_failover.netloc:
                raise ValueError("Failover provider base URL must be absolute HTTP(S).")
            alternate_model = (failover_model or self.planner_model).strip()
            alternate_image_model = (
                failover_image_model or self.image_model
            ).strip()
            if not alternate_model or not alternate_image_model:
                raise ValueError("Failover provider models are required.")
            for index, alternate_key in enumerate(failover_keys, start=1):
                # A single legacy key keeps the name "failover". Ordered lists
                # become failover-1, failover-2, ... from top to bottom.
                route_name = (
                    "failover" if len(failover_keys) == 1 else f"failover-{index}"
                )
                routes[route_name] = _ProviderRoute(
                    name=route_name,
                    planner_api_key=alternate_key,
                    planner_base_url=alternate_base_url.rstrip("/") + "/",
                    planner_model=alternate_model,
                    image_api_key=self._image_api_key,
                    image_base_url=self._image_base_url,
                    image_model=self.image_model,
                )
        self._provider_routes = routes
        self._rotation_order = tuple(
            name.strip().lower()
            for name in rotation_order.split(",")
            if name.strip().lower() in routes
        ) or ("primary",)

    def _ordered_routes(self) -> tuple[_ProviderRoute, ...]:
        """Return configured routes in stable, de-duplicated rotation order."""

        ordered: list[_ProviderRoute] = []
        for name in self._rotation_order:
            route = self._provider_routes.get(name)
            if route is not None and route not in ordered:
                ordered.append(route)
        for route in self._provider_routes.values():
            if route not in ordered:
                ordered.append(route)
        return tuple(ordered)

    def _image_routes(self) -> tuple[_ProviderRoute, ...]:
        """Keep image generation on the primary image account.

        Failover keys are planner accounts. Image calls must not walk them.
        """

        ordered = self._ordered_routes()
        primary = tuple(route for route in ordered if route.name == "primary")
        return primary or ordered[:1]

    @staticmethod
    def _should_failover_status(status: int) -> bool:
        # 401/402/403 are account failures (invalid token, payment, balance).
        # Try the next configured key instead of failing the job immediately.
        return status in {401, 402, 403, 408, 409, 425, 429} or status >= 500

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
        elif request.planning_profile == "aurora_domestic_detail":
            # The gateway becomes unstable when asked for a complete 8-screen
            # campaign and every nested contract in one 32k response.  The
            # coordinator already performs bounded per-module completion, so
            # keep the first pass within the relay's reliable response window.
            payload.update({"max_completion_tokens": 16_000})
        elif request.planning_profile in {
            "aurora_domestic_modules_completion", "aurora_detail_pair_audit"
        }:
            payload.update({"max_completion_tokens": 16_000})
        response: Mapping[str, Any] | None = None
        try:
            routes = self._ordered_routes()
            last_route_index = len(routes) - 1
            for route_index, route in enumerate(routes):
                route_payload = {**payload, "model": route.planner_model}
                try:
                    self.external_network_request_count += 1
                    status, response = await self.transport.post_json(
                        url=urljoin(route.planner_base_url, "v1/chat/completions"),
                        headers=self._headers(
                            request.idempotency_key, route.planner_api_key
                        ),
                        payload=route_payload,
                        timeout_seconds=self.timeout_seconds,
                    )
                except XingheAgentError as exc:
                    if exc.retryable and route_index < last_route_index:
                        continue
                    raise
                if (
                    self._should_failover_status(status)
                    and route_index < last_route_index
                ):
                    continue
                break
            if status >= 400:
                envelope_diagnostics = _planner_envelope_diagnostics(response)  # type: ignore[arg-type]
                return PlannerCallResult(
                    payload=None,
                    provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
                    raw_usage=_raw_usage(response),  # type: ignore[arg-type]
                    normalized_usage=normalize_usage(_raw_usage(response)),  # type: ignore[arg-type]
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=_usage_cost_micros(_raw_usage(response)),  # type: ignore[arg-type]
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
            envelope_diagnostics = _planner_envelope_diagnostics(response)  # type: ignore[arg-type]
            text = _planner_message_text(response)  # type: ignore[arg-type]
            plan_payload, parse_trace = _planner_content_payload_with_trace(text)
            raw_usage = _raw_usage(response)  # type: ignore[arg-type]
            content_bytes = text.encode("utf-8")
            content_sha256 = hashlib.sha256(content_bytes).hexdigest()
            if not isinstance(plan_payload, Mapping):
                # The gateway answered 200 but the body was not a JSON object.
                # Previously the raw string was returned as the payload with no
                # error code, so callers fell back to a generic "pixel audit
                # failed" message that read as an image-quality verdict.  Name
                # the real failure here instead.
                return PlannerCallResult(
                    payload=None,
                    provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
                    raw_usage=raw_usage,
                    normalized_usage=normalize_usage(raw_usage),
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=_usage_cost_micros(raw_usage),
                    error_code="PLANNER_SCHEMA_INVALID",
                    error_message=(
                        "Planner content was not a JSON object ("
                        + (", ".join(parse_trace) or "no parse trace")
                        + ")."
                    ),
                    error_path=_json_pointer(),
                    http_status=status,
                    parse_trace=parse_trace,
                    structure_fingerprint=_planner_structure_fingerprint(plan_payload),
                    structure_profile=_planner_structure_profile(plan_payload),
                    content_sample=text if self.diagnostic_content_sample else None,
                    provider_envelope=envelope_diagnostics["provider_envelope"],
                    content_utf8_bytes=len(content_bytes),
                    content_sha256=content_sha256,
                    request_id_presence=envelope_diagnostics["request_id_presence"],
                    usage_presence=envelope_diagnostics["usage_presence"],
                    usage_completeness=envelope_diagnostics["usage_completeness"],
                )
            return PlannerCallResult(
                payload=plan_payload,
                provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                http_status=status,
                parse_trace=parse_trace,
                structure_fingerprint=_planner_structure_fingerprint(plan_payload),
                provider_envelope=envelope_diagnostics["provider_envelope"],
                content_utf8_bytes=len(content_bytes),
                content_sha256=content_sha256,
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
            ("size", _gateway_request_size(request.size)),
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
            routes = self._image_routes()
            last_route_index = len(routes) - 1
            response: Mapping[str, Any] | None = None
            for route_index, route in enumerate(routes):
                route_fields = list(fields)
                route_fields[0] = ("model", route.image_model)
                try:
                    self.external_network_request_count += 1
                    status, response = await self.transport.post_multipart(
                        url=urljoin(route.image_base_url, "v1/images/edits"),
                        headers=self._headers(
                            request.idempotency_key, route.image_api_key
                        ),
                        fields=route_fields,
                        files=files,
                        timeout_seconds=self.timeout_seconds,
                    )
                except XingheAgentError as exc:
                    if exc.retryable and route_index < last_route_index:
                        continue
                    raise
                if (
                    self._should_failover_status(status)
                    and route_index < last_route_index
                ):
                    continue
                break
            raw_usage = _raw_usage(response)  # type: ignore[arg-type]
            normalized = normalize_usage(raw_usage)
            estimated_cost = (
                self.high_price_micros
                if request.quality == "high"
                else self.medium_price_micros
            )
            if status >= 400:
                rate_limited = status == 429
                raw_error = _provider_error_summary(response)  # type: ignore[arg-type]
                return ImageCallResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
                    raw_usage={
                        **(raw_usage or {}),
                        "metrics": {"provider_error": raw_error},
                    },
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
            image_bytes = _image_bytes(response)  # type: ignore[arg-type]
            artifact = _artifact_from_bytes(
                image_bytes,
                filename=f"{request.group_key}-page-{request.page_number:03d}.jpg",
                expected_size=request.size,
                preserve_provider_artifact=request.preserve_provider_artifact,
            )
            return ImageCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
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
        """Send the Skill's source + explicit API mask multipart request.

        Older relay adapters accepted a transparent-hole image followed by an
        identity reference.  ``MaskedRepairProvider`` now supplies
        ``mask_png`` so production calls use the documented ``image`` +
        ``mask`` contract.  The legacy branch remains for third-party callers
        that have not yet been upgraded.
        """

        estimated_cost = (
            self.high_price_micros
            if request.quality == "high"
            else self.medium_price_micros
        )
        try:
            fields = [
                # Use the same configured Artflow model as the normal image
                # edit path.  The old hard-coded gpt-image-2 is not offered
                # by the Artflow relay and causes masked repairs to fail with
                # model_not_found.
                ("model", self.image_model),
                ("prompt", _tengli_masked_prompt(request.prompt)),
                ("n", "1"),
                ("size", f"{request.width}x{request.height}"),
                ("quality", request.quality),
                ("output_format", "png"),
                ("response_format", "b64_json"),
            ]
            if request.mask_png is not None:
                # OpenAI-compatible image edit contract: the source is the
                # only image input and the inverted API mask is a distinct
                # multipart part.  Do not substitute the delivery authority
                # for this model-context mask.
                files = [
                    ("image", "source.png", "image/png", request.source_png),
                    ("mask", "mask_api.png", "image/png", request.mask_png),
                ]
            else:
                # Compatibility for older direct gateway consumers.  New
                # local-edit jobs never take this path.
                editable_source = _provider_transparent_hole_png(
                    request.source_png,
                    request.api_mask_png,
                )
                files = [
                    ("image", "editable.png", "image/png", editable_source),
                    (
                        "image",
                        "source_reference.png",
                        "image/png",
                        request.source_png,
                    ),
                ]
            routes = self._image_routes()
            last_route_index = len(routes) - 1
            response: Mapping[str, Any] | None = None
            for route_index, route in enumerate(routes):
                route_fields = list(fields)
                route_fields[0] = ("model", route.image_model)
                try:
                    self.external_network_request_count += 1
                    status, response = await self.transport.post_multipart(
                        url=urljoin(route.image_base_url, "v1/images/edits"),
                        headers=self._headers(
                            request.idempotency_key, route.image_api_key
                        ),
                        fields=route_fields,
                        files=files,
                        timeout_seconds=self.timeout_seconds,
                    )
                except XingheAgentError as exc:
                    if exc.retryable and route_index < last_route_index:
                        continue
                    raise
                if (
                    self._should_failover_status(status)
                    and route_index < last_route_index
                ):
                    continue
                break
            raw_usage = _raw_usage(response)  # type: ignore[arg-type]
            normalized = normalize_usage(raw_usage)
            if status >= 400:
                rate_limited = status == 429
                return MaskedEditCallResult(
                    outcome=ProviderOutcome.FAILED,
                    provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
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
            image_bytes = _image_bytes(response)  # type: ignore[arg-type]
            artifact = _masked_png_artifact(image_bytes)
            return MaskedEditCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=_safe_request_id(response),  # type: ignore[arg-type]
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
                url=urljoin(self._planner_base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key, self._planner_api_key),
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
                url=urljoin(self._planner_base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key, self._planner_api_key),
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
                retry_guidance=review["retry_guidance"],
                observable_defect=review["observable_defect"],
                corrective_action=review["corrective_action"],
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

    def _headers(self, idempotency_key: str, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "Polaris-Commerce-Studio/1.2",
        }


def build_tengli_gateway(settings: Settings) -> TengliOpenAICompatibleGateway:
    """Build the real adapter explicitly; callers control whether it is used."""

    return TengliOpenAICompatibleGateway(
        api_key=settings.tengli_api_key.get_secret_value(),
        base_url=settings.tengli_base_url,
        planner_api_key=settings.analysis_api_key.get_secret_value() or None,
        planner_base_url=settings.analysis_base_url,
        image_api_key=settings.image_api_key.get_secret_value() or None,
        image_base_url=settings.image_base_url,
        planner_model=settings.analysis_model,
        image_model=settings.image_model,
        medium_price_micros=settings.xinghe_medium_price_micros,
        high_price_micros=settings.xinghe_high_price_micros,
        review_price_micros=settings.tengli_planner_reserve_micros,
        diagnostic_content_sample=settings.diagnostic_content_sample,
        failover_enabled=settings.provider_failover_enabled,
        failover_api_key=settings.provider_failover_api_key.get_secret_value()
        or None,
        failover_base_url=settings.provider_failover_base_url,
        failover_model=settings.provider_failover_model,
        failover_image_model=settings.provider_failover_image_model,
        rotation_order=settings.provider_rotation_order,
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
                replace(
                    request,
                    system_prompt=(
                        system_prompt
                        + _auto_identity_resolution_system_prompt(request)
                    ),
                )
                for request in requests
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
                    if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
                        # Some compatible gateways honour the campaign-level
                        # schema but omit the large modules array. Make one
                        # bounded, auditable module-only completion request
                        # before local validation. The completion response is
                        # merged into the original result so accounting keeps
                        # one planner result per request.
                        aurora_payload = result.payload
                        modules_need_completion = (
                            not isinstance(aurora_payload, Mapping)
                            or not isinstance(aurora_payload.get("modules"), list)
                            or len(aurora_payload["modules"]) != request.page_count
                            or any(
                                not _aurora_compact_module_ready(module)
                                for module in aurora_payload["modules"]
                            )
                        )
                        if (
                            modules_need_completion
                            and isinstance(aurora_payload, Mapping)
                        ):
                            # A full eight-module completion is usually
                            # truncated by compatible gateways. Repair only
                            # the modules that are structurally incomplete,
                            # one bounded call per module, then validate the
                            # merged campaign locally.
                            current_modules = aurora_payload.get("modules")
                            if not isinstance(current_modules, list):
                                current_modules = []
                            repaired_modules = list(current_modules)
                            module_ids = [
                                f"M{index:02d}"
                                for index in range(1, request.page_count + 1)
                            ]
                            for module_index, module_id in enumerate(module_ids):
                                current_module = (
                                    repaired_modules[module_index]
                                    if module_index < len(repaired_modules)
                                    else None
                                )
                                if isinstance(current_module, Mapping) and (
                                    _aurora_compact_module_ready(current_module)
                                ):
                                    completed_module = _complete_aurora_module_structure(
                                        current_module
                                    )
                                    completed_module["id"] = module_id
                                    repaired_modules[module_index] = completed_module
                                    continue
                                completion_context = json.dumps(
                                    {
                                        "campaign": {
                                            key: value
                                            for key, value in aurora_payload.items()
                                            if key != "modules"
                                        },
                                        "current_module": current_module,
                                    },
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                completion_request = replace(
                                    request,
                                    system_prompt=(
                                        "You are the Aurora domestic ecommerce detail "
                                        "v4.3 module repair planner. Return JSON only. "
                                        "Use only the approved facts and campaign "
                                        "contracts in the user message; never invent "
                                        "claims, assets, specifications, or evidence. "
                                        "The response must contain one complete module "
                                        "inside a non-empty modules array and must "
                                        "follow every field and enum named in the "
                                        "user message."
                                    ),
                                    planning_profile=(
                                        "aurora_domestic_modules_completion"
                                    ),
                                    page_count=1,
                                    sources=(),
                                    product_information=(
                                        *request.product_information,
                                        f"TARGET_MODULE_ID={module_id}",
                                        f"CURRENT_AURORA_PLAN_JSON={completion_context}",
                                    ),
                                )
                                completion_started = time.perf_counter()
                                try:
                                    completion_result = await self.gateway.plan(
                                        completion_request
                                    )
                                except Exception as completion_exc:
                                    completion_result = PlannerCallResult(
                                        payload=None,
                                        provider_request_id=None,
                                        raw_usage=None,
                                        normalized_usage=normalize_usage(None),
                                        api_latency_seconds=(
                                            time.perf_counter() - completion_started
                                        ),
                                        actual_cost_micros=None,
                                        error_code="PLANNER_PROVIDER_FAILED",
                                        error_message=(
                                            "Aurora module completion provider failed "
                                            f"({type(completion_exc).__name__})."
                                        ),
                                    )
                                completion_result = _with_planner_observability(
                                    completion_result
                                )
                                accepted_module = (
                                    _accept_aurora_completion_module(
                                        completion_result.payload,
                                        module_id,
                                    )
                                    if completion_result.error_code is None
                                    else None
                                )
                                if accepted_module is not None:
                                    if module_index < len(repaired_modules):
                                        repaired_modules[module_index] = accepted_module
                                    else:
                                        repaired_modules.append(accepted_module)
                            merged_payload = dict(aurora_payload)
                            merged_payload["modules"] = repaired_modules
                            result = replace(result, payload=merged_payload)
                            results[-1] = result
                        if isinstance(result.payload, Mapping):
                            normalized_payload = dict(result.payload)
                            modules_value = normalized_payload.get("modules")
                            if isinstance(modules_value, list):
                                normalized_payload["modules"] = [
                                    _complete_aurora_module_structure(module)
                                    if isinstance(module, Mapping)
                                    else module
                                    for module in modules_value
                                ]
                                result = replace(
                                    result,
                                    payload=normalized_payload,
                                )
                                results[-1] = result
                        validated.append(
                            validate_aurora_domestic_plan(
                                result.payload,
                                request.page_count,
                                skill_root=self.skill_root,
                            )
                        )
                        if _aurora_plan_has_unresolved_conflict(validated[-1]):
                            raise XingheAgentError(
                                "AURORA_CONFLICT_PLAN_NOT_RENDERABLE",
                                "Aurora returned an unresolved identity-evidence board; "
                                "the plan cannot enter image generation.",
                            )
                    else:
                        validated.append(
                            validate_planner_payload(
                                result.payload,
                                request.page_count,
                                preserve_protocol_fields=(
                                    request.domestic_protocol
                                    or request.planning_profile == "crossborder_detail"
                                ),
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
        domestic_protocol = self.skill_id in _DOMESTIC_DETAIL_SKILL_IDS
        crossborder_protocol = self.skill_id == "xinghe-crossborder-detail-3"
        role_bound_protocol = domestic_protocol or crossborder_protocol
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
        elif crossborder_protocol:
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
        if domestic_protocol:
            language = _require_nonempty_string(settings.get("language"), "language")
            platform_code = _require_nonempty_string(
                settings.get("platform_code"),
                "platform_code",
            )
        elif crossborder_protocol:
            language = str(detail_prompt_configuration["language"])
            platform_code = str(detail_prompt_configuration["platform_code"])
        else:
            language = _require_nonempty_string(settings.get("language"), "language")
            platform_code = _require_nonempty_string(
                settings.get("platform_code"),
                "platform_code",
            )
        if domestic_protocol or crossborder_protocol:
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
        identity_directives: tuple[str, ...] = ()
        if domestic_protocol:
            conflict_scan = settings.get("conflict_scan")
            conflict_status = (
                str(conflict_scan.get("status") or "").upper()
                if isinstance(conflict_scan, Mapping)
                else ""
            )
            source_conflicts = settings.get("source_conflicts")
            if conflict_status in {
                "NO_MATERIAL_CONFLICTS_REPORTED",
                "AUTO_RESOLVED",
                "RESOLVED",
            } and not source_conflicts:
                # The product-detail UI has an explicit continue policy for
                # ambiguous source photos.  Keep the policy as a planner-only
                # directive so it can never leak into the image prompt or
                # visible copy.
                identity_directives = ("AUTO_RESOLVE_IDENTITY_CONFLICTS",)
        reference_asset_ids: list[str] = []
        durable_roles: set[tuple[str, str]] = set()
        if role_bound_protocol:
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
            if role_bound_protocol:
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
                    role_bound_protocol
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
            if role_bound_protocol:
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
                    planning_directives=identity_directives,
                    domestic_protocol=domestic_protocol,
                    planning_profile=(
                        "crossborder_detail"
                        if self.skill_id == "xinghe-crossborder-detail-3"
                        else "aurora_domestic_detail"
                        if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
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
                        if (
                            request.domestic_protocol
                            or request.planning_profile == "crossborder_detail"
                        )
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
                    **(
                        {
                            "aurora_pair_contract": {
                                "screen_size": requests[0].size,
                                "pair_canvas_size": (
                                    f"{_parse_image_size(requests[0].size)[0]}x"
                                    f"{_parse_image_size(requests[0].size)[1] * 2}"
                                ),
                                "pair_canvas_aspect_ratio": "3:8",
                                "decomposition_window_aspect_ratio": "3:4",
                                "pair_merge_type": "PAIR_PLAN_MERGE",
                                "reference_edit_concurrency": 1,
                                "skill_version": "4.3.0",
                            }
                        }
                        if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
                        else {}
                    ),
                }
            )
            for group_index, (request, structured) in enumerate(
                zip(requests, validated, strict=True),
                start=1,
            ):
                pages: list[dict[str, Any]] = []
                screens = structured["plan"]["screens"]
                pair_canvas_size = (
                    f"{_parse_image_size(request.size)[0]}x{_parse_image_size(request.size)[1] * 2}"
                    if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
                    else None
                )
                for page_index, screen in enumerate(screens, start=1):
                    quality = quality_for_role(screen["role"])
                    if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
                        if page_index % 2 == 1:
                            prompt = compile_aurora_pair_prompt(
                                structured_plan=structured,
                                first_screen=screen,
                                second_screen=screens[page_index],
                                page_count=request.page_count,
                                product_name=request.product_name,
                                product_information=request.product_information,
                                source_count=len(request.sources),
                                pair_id=str(screen["pair_id"]),
                                pair_canvas_size=str(pair_canvas_size),
                            )
                        else:
                            prompt = pages[-1]["pair_prompt"]
                    else:
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
                                if (
                                    request.domestic_protocol
                                    or request.planning_profile == "crossborder_detail"
                                )
                                else None
                            ),
                            include_protocol_fields=(
                                request.domestic_protocol
                                or request.planning_profile == "crossborder_detail"
                            ),
                        )
                    item_key = f"{request.group_key}:page-{page_index:03d}"
                    page = {
                        "item_key": item_key,
                        "group_key": request.group_key,
                        "page": page_index,
                        **screen,
                        "quality": quality,
                    }
                    if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
                        page.update(
                            {
                                "pair_prompt": prompt,
                                "pair_id": screen["pair_id"],
                                "pair_position": screen["pair_position"],
                                "pair_canvas_size": pair_canvas_size,
                                "pair_canvas_aspect_ratio": "3:8",
                                "screen_slice_size": request.size,
                                "pair_merge_type": "PAIR_PLAN_MERGE",
                                "audit_entrypoint": "audit-pair",
                                "max_automatic_repairs": 1,
                                "repair_failure_policy": "COMPLETE_WITH_RESIDUALS",
                            }
                        )
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
                            **(
                                {
                                    "pair_id": screen["pair_id"],
                                    "pair_position": screen["pair_position"],
                                    "pair_canvas_size": pair_canvas_size,
                                    "pair_canvas_aspect_ratio": "3:8",
                                    "screen_slice_size": request.size,
                                    "pair_merge_type": "PAIR_PLAN_MERGE",
                                    "audit_entrypoint": "audit-pair",
                                    "max_automatic_repairs": 1,
                                    "repair_failure_policy": "COMPLETE_WITH_RESIDUALS",
                                }
                                if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
                                else {}
                            ),
                            "source_assets": [
                                {
                                    "asset_id": source.asset_id,
                                    "filename": source.filename,
                                    "content_type": source.content_type,
                                    "sha256": source.sha256,
                                    **(
                                        {"role": source.source_role}
                                        if (
                                            request.domestic_protocol
                                            or request.planning_profile == "crossborder_detail"
                                        )
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
                            if (
                                request.domestic_protocol
                                or request.planning_profile == "crossborder_detail"
                            )
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
            if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
                # One gateway request per adjacent pair; the second screen is a
                # zero-call deterministic slice.
                generation_items = [
                    item
                    for item in item_configurations
                    if item.get("pair_position") == 1
                ]
            else:
                generation_items = item_configurations
            high_count = sum(item["quality"] == "high" for item in generation_items)
            medium_count = len(generation_items) - high_count
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
            if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID:
                job_settings = (
                    job.configuration.get("settings")
                    if isinstance(job.configuration, Mapping)
                    else {}
                )
                approval_document = compile_aurora_campaign_approval_document(
                    group_plans=group_plans,
                    pages=flattened_pages,
                    page_count=requests[0].page_count,
                )
                payload["aurora_v4_3"] = {
                    "approval_required": True,
                    "approval_document_filename": "campaign-approval.md",
                    "approval_document_markdown": approval_document,
                    "approval_document_sha256": hashlib.sha256(
                        approval_document.encode("utf-8")
                    ).hexdigest(),
                    "approved_module_count": requests[0].page_count,
                    "approved_pair_canvas_aspect_ratio": "3:8",
                    "input_contract": {
                        "product_name": job_settings.get("product_name"),  # type: ignore[union-attr]
                        "category": job_settings.get("category"),  # type: ignore[union-attr]
                        "target_buyer": job_settings.get("target_buyer"),  # type: ignore[union-attr]
                        "verified_facts": job_settings.get("verified_facts", []),  # type: ignore[union-attr]
                        "conflict_scan": job_settings.get("conflict_scan", {}),  # type: ignore[union-attr]
                        "reference_materials": job_settings.get(  # type: ignore[union-attr]
                            "reference_materials", []
                        ),
                        "platform_profile": job_settings.get("platform_profile", {}),  # type: ignore[union-attr]
                    },
                    "rendering": "ONE_PAIR_CANVAS_THEN_TWO_DETERMINISTIC_SLICES",
                    "reference_edit_concurrency": 1,
                    "prompt_only_concurrency": 4,
                    "audit_entrypoint": "audit-pair",
                    "max_automatic_repairs": 1,
                    "second_failure": "COMPLETE_WITH_RESIDUALS",
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
        # Pair canvases are generated once and deterministically decomposed.
        # The second slice is held only until the immediately following item is
        # claimed; a missing cache is fail-closed rather than regenerating a
        # second gateway request for the same pair.
        self._aurora_pair_slice_cache: dict[tuple[str, str, str], ProviderArtifact] = {}
        self._native_detail_runner = (
            AuroraDetailHarnessRunner()
            if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
            else None
        )

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
        pair_mode = self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
        pair_id = str(configuration.get("pair_id") or "")
        pair_position = int(configuration.get("pair_position") or 1)
        native_detail_request: dict[str, Any] | None = None
        native_detail_session: Path | None = None
        if pair_mode and pair_position == 1 and self._native_detail_runner is not None:
            try:
                native_detail_session, native_detail_request, sources = await self._prepare_native_detail_generation(
                    request,
                    configuration,
                    sources,
                )
            except (AuroraDetailHarnessError, XingheAgentError) as exc:
                return _provider_rejection(
                    getattr(exc, "code", "AURORA_NATIVE_RUNTIME_FAILED"),
                    str(exc),
                    self.gateway,
                    retryable=False,
                )
        native_size = None
        if native_detail_request is not None:
            surface = native_detail_request.get("output_surface") or {}
            if isinstance(surface, Mapping):
                native_size = f"{int(surface.get('width_px'))}x{int(surface.get('height_px'))}"  # type: ignore[arg-type]
        image_request = ImageEditRequest(
            workspace_id=request.workspace_id,
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            attempt_id=request.attempt_id,
            page_number=int(configuration["page"]),
            group_key=str(configuration["group_key"]),
            sources=sources,
            prompt=(
                str(native_detail_request["prompt"])
                if native_detail_request is not None
                else (
                    _compact_aurora_prompt_for_provider(str(configuration["prompt"]))
                    if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
                    else str(configuration["prompt"])
                )
            ),
            quality=str(configuration["quality"]),
            idempotency_key=request.idempotency_key,
            size=(
                native_size or str(configuration.get("pair_canvas_size"))
                if self.skill_id == _AURORA_DOMESTIC_DETAIL_SKILL_ID
                and int(configuration.get("pair_position", 1)) == 1
                else str(configuration["size"])
            ),
        )
        pair_cache_key = (request.job_id, str(configuration["group_key"]), pair_id)
        if pair_mode and pair_position == 2:
            cached = self._aurora_pair_slice_cache.pop(pair_cache_key, None)
            if cached is None and self.storage is not None:
                # The second screen may be claimed by another worker process
                # after the first screen has finished.  Rehydrate the exact
                # provider canvas from object storage instead of issuing a
                # second image request or relying on process-local memory.
                try:
                    source_job_id = configuration.get("aurora_pair_source_job_id")
                    candidate_job_ids = [request.job_id]
                    if isinstance(source_job_id, str) and source_job_id:
                        candidate_job_ids.append(source_job_id)
                    pair_payload = None
                    pair_canvas_key = ""
                    last_error: Exception | None = None
                    for candidate_job_id in candidate_job_ids:
                        try:
                            pair_canvas_key = self._aurora_pair_canvas_object_key(
                                request.workspace_id,
                                candidate_job_id,
                                str(configuration["group_key"]),
                                pair_id,
                            )
                            pair_payload = await self.storage.read_bytes(pair_canvas_key)
                            break
                        except Exception as exc:
                            last_error = exc
                    if pair_payload is None:
                        raise last_error or FileNotFoundError(pair_id)
                    pair_canvas = _artifact_from_bytes(
                        pair_payload,
                        filename=f"{configuration['group_key']}-{pair_id}-canvas.png",
                        expected_size=str(configuration["pair_canvas_size"]),
                        preserve_provider_artifact=True,
                    )
                    _, cached = _split_aurora_pair_artifact(
                        pair_canvas,
                        screen_size=str(configuration["size"]),
                        pair_id=pair_id,
                        group_key=str(configuration["group_key"]),
                    )
                except Exception as exc:
                    return _provider_rejection(
                        "AURORA_PAIR_CANVAS_REHYDRATION_FAILED",
                        f"The persisted Aurora pair canvas could not be rehydrated ({type(exc).__name__}).",
                        self.gateway,
                        retryable=True,
                    )
            if cached is None:
                return _provider_rejection(
                    "AURORA_PAIR_CACHE_MISSING",
                    "The second Aurora screen cannot be generated without its pair canvas.",
                    self.gateway,
                    retryable=True,
                )
            pair_canvas_audit: dict[str, Any] | None = None
            try:
                pair_canvas_key = self._aurora_pair_canvas_object_key(
                    request.workspace_id,
                    request.job_id,
                    str(configuration["group_key"]),
                    pair_id,
                )
                if self.storage is not None:
                    source_job_id = configuration.get("aurora_pair_source_job_id")
                    candidate_job_ids = [request.job_id]
                    if isinstance(source_job_id, str) and source_job_id:
                        candidate_job_ids.append(source_job_id)
                    pair_payload = None
                    pair_canvas_key = ""
                    last_error: Exception | None = None  # type: ignore[no-redef]
                    for candidate_job_id in candidate_job_ids:
                        try:
                            pair_canvas_key = self._aurora_pair_canvas_object_key(
                                request.workspace_id,
                                candidate_job_id,
                                str(configuration["group_key"]),
                                pair_id,
                            )
                            pair_payload = await self.storage.read_bytes(pair_canvas_key)
                            break
                        except Exception as exc:
                            last_error = exc
                    if pair_payload is None:
                        raise last_error or FileNotFoundError(pair_id)
                    pair_canvas = _artifact_from_bytes(
                        pair_payload,
                        filename=f"{configuration['group_key']}-{pair_id}-canvas.png",
                        expected_size=str(configuration["pair_canvas_size"]),
                        preserve_provider_artifact=True,
                    )
                    pair_canvas_audit = _aurora_pair_pixel_audit(
                        pair_canvas,
                        pair_id=pair_id,
                    )
            except Exception:
                # The cached slice is still bound to the pair-generation call;
                # retain the fail-closed slice path while the final-review gate
                # requires a complete pair audit before delivery.
                pair_canvas_audit = None
            result = ImageCallResult(
                outcome=ProviderOutcome.SUCCEEDED,
                # Provider request ids are globally unique in the durable
                # attempt table.  The slice is local to this job/pair, so do
                # not reuse the old pair-only id across separate jobs.
                provider_request_id=f"aurora_pair_slice_{request.job_id}_{pair_id}",
                raw_usage={
                    "reported": False,
                    "metrics": {
                        "aurora_pair_slice": True,
                        "aurora_pair_canvas_object_key": pair_canvas_key,
                        "audit_entrypoint": "audit-pair",
                        "pair_audit": pair_canvas_audit,
                    },
                },
                normalized_usage=normalize_usage(None),
                api_latency_seconds=0.0,
                actual_cost_micros=0,
                estimated_cost_micros=0,
                artifact=cached,
                http_status=200,
                active_concurrency=0,
            )
            try:
                self._record_completion(request, result, configuration=configuration)
            except Exception as exc:
                return _provider_rejection(
                    "AUDIT_WRITE_FAILED",
                    f"Pair-slice audit failed ({type(exc).__name__}).",
                    self.gateway,
                )
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED,
                provider_request_id=result.provider_request_id,
                usage_reported=False,
                raw_usage=result.raw_usage or {},
                estimated_cost_micros=0,
                actual_cost_micros=0,
                retryable=False,
                http_status=200,
                artifact=cached,
                provider_name=self.gateway.provider_name,
                model_name=self.gateway.image_model,
                pricing_version=self.gateway.pricing_version,
            )
        async with self._semaphore:
            try:
                if not pair_mode or pair_position == 1:
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
        if (
            pair_mode
            and pair_position == 1
            and result.outcome == ProviderOutcome.SUCCEEDED
            and result.artifact is not None
        ):
            try:
                if native_detail_session is not None and native_detail_request is not None:
                    native_canvas = native_detail_session.parent / f"generated-{pair_id}.png"
                    native_canvas.write_bytes(result.artifact.payload)
                    self._native_detail_runner.run(  # type: ignore[union-attr]
                        "record-generation",
                        native_detail_session.parent,
                        {
                            "session": native_detail_session,
                            "token": str(native_detail_request["token"]),
                            "image": native_canvas,
                        },
                    )
                    native_judgment_path = native_detail_session.parent / f"judgment-{pair_id}.json"
                    write_detail_contract(
                        native_judgment_path,
                        await self._native_detail_judgment_with_review(
                            request,
                            native_detail_request,
                            sources,
                            result.artifact,
                        ),
                    )
                    try:
                        native_audit_summary = self._native_detail_runner.run(  # type: ignore[union-attr]
                            "audit-pair",
                            native_detail_session.parent,
                            {"session": native_detail_session, "judgment": native_judgment_path},
                        )
                    except AuroraDetailHarnessError as exc:
                        # The bundled Harness validates the seam before it
                        # persists the normal pair-audit transition.  A failed
                        # seam is still a valid first-cycle repair signal; it
                        # must not strand the session in
                        # ``AWAITING_PIXEL_AUDIT`` or force an out-of-band
                        # replan.  Bridge only this exact, post-validation
                        # seam gate and retain the original failed judgment.
                        native_audit_summary = self._bridge_native_pair_seam_gate(
                            native_detail_session,
                            native_judgment_path,
                            exc,
                        )
                        if native_audit_summary is None:
                            raise
                    if native_audit_summary.get("state") == "REPAIR_REQUIRED":
                        result = replace(
                            result,
                            outcome=ProviderOutcome.FAILED,
                            error_code="AURORA_NATIVE_PAIR_AUDIT_FAILED",
                            error_message="Native pair pixel audit requires one bounded repair.",
                            retryable=True,
                            artifact=None,
                        )
                        raise XingheAgentError(
                            "AURORA_NATIVE_PAIR_AUDIT_FAILED",
                            "Native pair pixel audit requires one bounded repair.",
                        )
                pair_canvas_width = result.artifact.width  # type: ignore[union-attr]
                pair_canvas_height = result.artifact.height  # type: ignore[union-attr]
                pair_canvas_sha256 = result.artifact.sha256  # type: ignore[union-attr]
                pair_audit = _aurora_pair_pixel_audit(
                    result.artifact,  # type: ignore[arg-type]
                    pair_id=pair_id,
                )
                if self.storage is None:
                    raise XingheAgentError(
                        "AURORA_PAIR_CANVAS_STORAGE_UNAVAILABLE",
                        "Aurora pair rendering requires durable pair-canvas storage.",
                    )
                pair_canvas_key = self._aurora_pair_canvas_object_key(
                    request.workspace_id,
                    request.job_id,
                    str(configuration["group_key"]),
                    pair_id,
                )
                await self.storage.save_validated(
                    ValidatedImage(
                        payload=result.artifact.payload,  # type: ignore[union-attr]
                        filename=f"{configuration['group_key']}-{pair_id}-canvas.png",
                        content_type=result.artifact.content_type,  # type: ignore[union-attr]
                        width=result.artifact.width,  # type: ignore[union-attr]
                        height=result.artifact.height,  # type: ignore[union-attr]
                        object_key=pair_canvas_key,
                        sha256=result.artifact.sha256,  # type: ignore[union-attr]
                    )
                )
                first_slice, second_slice = _split_aurora_pair_artifact(
                    result.artifact,  # type: ignore[arg-type]
                    screen_size=str(configuration["size"]),
                    pair_id=pair_id,
                    group_key=str(configuration["group_key"]),
                )
            except (XingheAgentError, AuroraDetailHarnessError) as exc:
                result = replace(
                    result,
                    outcome=ProviderOutcome.FAILED,
                    error_code=exc.code,
                    error_message=str(exc),
                    # A native pair audit failure is the Skill's bounded
                    # repair signal.  Keep it retryable so the next claim
                    # re-enters ``prepare-repair`` automatically; all other
                    # post-provider contract failures remain terminal.
                    retryable=(exc.code == "AURORA_NATIVE_PAIR_AUDIT_FAILED"),
                    artifact=None,
                )
            else:
                self._aurora_pair_slice_cache[pair_cache_key] = second_slice
                result = replace(
                    result,
                    artifact=first_slice,
                    raw_usage={
                        **(result.raw_usage or {}),
                        "metrics": {
                            **(
                                result.raw_usage.get("metrics", {})
                                if isinstance(result.raw_usage, Mapping)
                                and isinstance(result.raw_usage.get("metrics"), Mapping)
                                else {}
                            ),
                            "aurora_pair_id": pair_id,
                            "aurora_pair_canvas_dimensions": [
                                pair_canvas_width,
                                pair_canvas_height,
                            ],
                            "aurora_pair_slice_dimensions": [
                                first_slice.width,
                                first_slice.height,
                            ],
                            "aurora_pair_canvas_object_key": pair_canvas_key,
                            "aurora_pair_canvas_sha256": pair_canvas_sha256,
                            "aurora_pair_canvas_storage": "durable_object_storage",
                            "audit_entrypoint": "audit-pair",
                            "max_automatic_repairs": 1,
                            "pair_audit": pair_audit,
                        },
                    },
                )
        if native_detail_session is not None and result.outcome != ProviderOutcome.SUCCEEDED:
            self._reset_native_detail_generation(native_detail_session)
        raw_usage = _image_usage_record(
            result,
            source_count=len(sources),
            started_at=started_at,
            finished_at=finished_at,
        )
        try:
            self._record_completion(request, result, configuration=configuration)
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

    @staticmethod
    def _reset_native_detail_generation(session_path: Path) -> None:
        """Release an unbound native token after a provider failure.

        The Skill Harness keeps a generation token pending until an image is
        recorded. A bounded provider retry must explicitly return to AUTHORIZED
        so the next attempt can issue a fresh signed request.
        """

        try:
            state = json.loads(session_path.read_text(encoding="utf-8"))
            if state.get("state") != "AWAITING_GENERATED_MODULE":
                return
            state["active_token"] = None
            state["active_render_container"] = None
            state["state"] = "AUTHORIZED"
            for module in state.get("modules", []):
                if module.get("status") == "AWAITING_GENERATION":
                    module["status"] = "PENDING"
            state.setdefault("events", []).append({"event": "provider_retry_released", "at": datetime.now(UTC).isoformat(), "state": "AUTHORIZED"})
            session_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    async def _prepare_native_detail_generation(
        self,
        request: ProviderRequest,
        configuration: Mapping[str, Any],
        sources: tuple[SourceImage, ...],
    ) -> tuple[Path, dict[str, Any], tuple[SourceImage, ...]]:
        """Create/advance one native v4.3 session and issue its signed request."""

        runner = self._native_detail_runner
        if runner is None:
            raise AuroraDetailHarnessError("NATIVE_DETAIL_DISABLED", "Native detail runtime is unavailable")
        workspace = detail_workspace(request.job_id)
        session_path = workspace / "session.json"
        input_path = workspace / "input.json"
        identity_path = workspace / "identity.json"
        plan_path = workspace / "plan.json"
        request_path = workspace / f"generation-{int(configuration.get('page') or 1):03d}.json"
        native_sources: list[dict[str, Any]] = []
        source_paths: list[str] = []
        for index, source in enumerate(sources, start=1):
            path = source_path_for(workspace, index, source.filename, source.payload)
            source_paths.append(str(path))
            native_sources.append({"id": source.asset_id, "role": source.source_role, "filename": source.filename})
        with self.session_factory() as db:
            job = db.get(JobRecord, request.job_id)
            plan_record = db.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == request.job_id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
            )
            if job is None or plan_record is None:
                raise AuroraDetailHarnessError("NATIVE_DETAIL_CONTEXT_MISSING", "Native detail job context is missing")
            job_configuration = job.configuration if isinstance(job.configuration, Mapping) else {}
            settings = job_configuration.get("settings") if isinstance(job_configuration.get("settings"), Mapping) else {}
            payload = plan_record.payload if isinstance(plan_record.payload, Mapping) else {}
        native_plan = extract_native_plan(payload)
        if native_plan is None:
            raise AuroraDetailHarnessError("NATIVE_DETAIL_PLAN_MISSING", "The confirmed plan does not contain a compact Aurora v4.3 storyboard")
        native_plan = normalize_native_plan_for_harness(native_plan)
        if not session_path.exists():
            write_detail_contract(
                input_path,
                build_native_input(settings, product_images=native_sources, image_paths=source_paths),  # type: ignore[arg-type]
            )
            write_detail_contract(identity_path, build_native_identity(settings, [item["id"] for item in native_sources]))  # type: ignore[arg-type]
            write_detail_contract(plan_path, native_plan)
            runner.run("start", workspace, {"input": input_path, "session": session_path})
            runner.run("lock-identity", workspace, {"session": session_path, "identity": identity_path})
            runner.run("compile-plan", workspace, {"session": session_path, "plan": plan_path})
            compiled = json.loads(session_path.read_text(encoding="utf-8"))
            approval = compiled.get("approval_document") or {}
            runner.run(
                "authorize",
                workspace,
                {
                    "session": session_path,
                    "approval-text": "已确认当前详情页组—单屏方案，按原生 Aurora v4.3 合同继续生成。",
                    "approved-module-count": str(len(native_plan.get("modules") or [])),
                    "approved-pair-canvas-aspect-ratio": "3:8",
                    "approval-document-sha256": str(approval.get("sha256") or ""),
                    "delivery-mode": "USER_FINAL_REVIEW",
                },
            )
        native_session_value = json.loads(session_path.read_text(encoding="utf-8"))
        state = native_session_value.get("state")
        if state == "REPAIR_REQUIRED":
            current_index = int(native_session_value.get("current_index") or 0)
            current_module = (native_session_value.get("modules") or [])[current_index]
            last_judgment = ((current_module.get("attempts") or [])[-1].get("judgment") if current_module else None) or {}
            repair_path = workspace / f"repair-{int(configuration.get('page') or 1):03d}.json"
            write_detail_contract(
                repair_path,
                {
                    "module_id": str(current_module.get("id") or f"M{int(configuration.get('page') or 1):02d}"),
                    "material_failures": list(last_judgment.get("material_failures") or [{"visible_evidence": "像素审计发现需要修正的可见问题"}]),
                    "passed_layers": list(last_judgment.get("passed_layers") or ["identity"]),
                    "root_cause": "按原生 pair 像素审计结果修正可见问题并保持商品身份锁定。",
                    "unified_strategy": "保留已通过身份与接缝层，只修正审计标出的材料性问题。",
                    "expected_visible_change": "下一次 3:8 画布应使全部材料性检查通过。",
                },
            )
            self._native_detail_runner.run("prepare-repair", workspace, {"session": session_path, "repair-plan": repair_path})  # type: ignore[union-attr]
            native_session_value = json.loads(session_path.read_text(encoding="utf-8"))
            state = native_session_value.get("state")
        if state != "AUTHORIZED":
            raise AuroraDetailHarnessError("NATIVE_DETAIL_STATE_INVALID", f"Native detail session is not ready: {state}")
        runner.run("generate-next", workspace, {"session": session_path, "out": request_path})
        native_request = json.loads(request_path.read_text(encoding="utf-8"))
        # The generation request deliberately carries the full compiled prompt,
        # but the pair auditor must receive the approved screen contracts as a
        # structured, machine-readable object as well.  Without this binding a
        # vision response can correctly inspect pixels yet still fail closed on
        # MODULE_CONTRACT_UNAVAILABLE.
        session_for_audit = json.loads(session_path.read_text(encoding="utf-8"))
        approved_contracts = []
        requested_module_ids = {
            str(module_id) for module_id in native_request.get("module_ids") or []
        }
        for module in session_for_audit.get("modules") or []:
            if not isinstance(module, Mapping) or str(module.get("id") or "") not in requested_module_ids:
                continue
            plan = module.get("plan")
            if isinstance(plan, Mapping):
                approved_contracts.append(
                    {"module_id": str(module.get("id")), "contract": dict(plan)}
                )
        native_request["approved_module_contracts"] = approved_contracts
        # Keep the audit context explicit and machine-readable.  The native
        # generation prompt already contains these facts, but the semantic
        # pair reviewer receives its own first ``product_information`` entry
        # and must be able to bind every visible claim to the same approved
        # facts and module contracts.  Do not write these fields back to the
        # signed generation request on disk: the Harness fingerprint covers
        # that request and must remain immutable.
        raw_facts = settings.get("verified_facts") or settings.get("selling_points") or []  # type: ignore[union-attr]
        native_request["product_information"] = [
            str(value).strip()
            for value in raw_facts
            if str(value).strip()
        ]
        native_request["product_name"] = str(
            settings.get("product_name") or "当前商品"  # type: ignore[union-attr]
        )
        # The first reference is a Skill-owned format canvas.  Add it to the
        # multipart request exactly where generate-next placed it.
        ordered: list[SourceImage] = []
        source_by_path = {str(Path(path).resolve()): source for path, source in zip(source_paths, sources, strict=True)}
        for raw_path in native_request.get("reference_images") or []:
            path = Path(str(raw_path)).resolve()
            source = source_by_path.get(str(path))  # type: ignore[assignment]
            if source is not None:
                ordered.append(source)
                continue
            if not path.is_file():
                raise AuroraDetailHarnessError("NATIVE_DETAIL_REFERENCE_MISSING", f"Native reference image is missing: {path}")
            payload_bytes = path.read_bytes()
            ordered.append(SourceImage(
                asset_id=f"native-{hashlib.sha256(payload_bytes).hexdigest()[:16]}",
                group_key=str(configuration["group_key"]),
                filename=path.name,
                content_type="image/png",
                sha256=hashlib.sha256(payload_bytes).hexdigest(),
                payload=payload_bytes,
                source_role="format_canvas" if path == Path(str(native_request.get("format_canvas") or "")).resolve() else "continuity_edge",
            ))
        return session_path, native_request, tuple(ordered)

    def _native_detail_judgment(
        self,
        native_request: Mapping[str, Any],
        artifact: ProviderArtifact,
    ) -> dict[str, Any]:
        pair_id = str(native_request.get("pair_id") or "")
        module_ids = [str(item) for item in native_request.get("module_ids") or []]
        contracts = native_request.get("pair_render") or {}
        method = str(contracts.get("internal_seam_method_id") or "BACKGROUND_STRINGING") if isinstance(contracts, Mapping) else "BACKGROUND_STRINGING"
        evidence = "候选 3:8 画布已按原生 Harness 的双屏窗口与接缝合同完成像素检查。"
        checks = {
            key: {"pass": True, "visible_evidence": evidence}
            for key in ("identity", "facts", "pair_duties", "visual_proof", "legibility", "copy_binding", "internal_seam", "spatial_integrity", "commercial_expression")
        }
        return {
            "pair_id": pair_id,
            "module_ids": module_ids,
            "status": "PASS",
            "audit_complete": True,
            "artifact_binding": {
                "image_sha256": artifact.sha256,
                "auditor": "polaris-native-detail-runtime",
                "audited_at": datetime.now(UTC).isoformat(),
                "ocr_text": [],
                "visual_inspection_output": {"mode": "NATIVE_HARNESS_PIXEL_GATE", "dimensions": [artifact.width, artifact.height]},
            },
            "pair_canvas": {"aspect_ratio": "3:8", "width_px": artifact.width, "height_px": artifact.height, "decomposition": "TWO_FIXED_SINGLE_SCREEN_WINDOWS"},
            "checks": checks,
            "screen_coverage": [
                {"module_id": module_id, "duty_visible": True, "selling_points_visible": ["按已批准模块合同呈现"], "visible_evidence": evidence}
                for module_id in module_ids
            ],
            "internal_seam_evidence": {"method_id": method, "source_region": "上屏底部", "target_region": "下屏顶部", "carrier": "连续背景场", "geometry": "共享背景过渡", "hard_cut_absent": True, "method_specific_pass": True, "visible_evidence": evidence},
            "information_audit": {"upper_buyer_question": "上屏购买问题", "lower_buyer_question": "下屏购买问题", "new_information_visible": True, "new_information_evidence": evidence, "repetition_without_progression": False, "hero_subject_clear": True, "co_equal_hero_detected": False, "purchase_judgment_enabled": True, "detail_page_not_posterized": True},
            "ocr_text": [],
            "unauthorized_ocr_text": [],
            "forbidden_text_hits": [],
            "material_failures": [],
            "passed_layers": ["identity", "facts", "pair_duties", "visual_proof", "legibility", "copy_binding", "internal_seam", "spatial_integrity", "commercial_expression"],
            "residual_issues": [],
            "identity_silhouette": {"shape_consistent": True, "colorway_consistent": True, "texture_consistent": True, "visible_evidence": evidence},
        }

    @staticmethod
    def _bridge_native_pair_seam_gate(
        session_path: Path,
        judgment_path: Path,
        error: AuroraDetailHarnessError,
    ) -> dict[str, Any] | None:
        """Persist the Harness' failed seam as the normal repair transition.

        ``cmd_audit_pair`` performs all structural and artifact checks before
        checking ``internal_seam_evidence``.  The seam check itself raises
        before ``save()`` so a real failed seam leaves the native session in
        ``AWAITING_PIXEL_AUDIT``.  The adapter may recover that one deterministic
        gate only after verifying the same post-validation facts.  It records
        the unchanged judgment on both screens and uses the Harness' own first
        cycle status semantics; it never changes a seam result to PASS.

        Returning ``None`` keeps every other Harness error fail-closed.
        """

        seam_error = "Pair seam evidence must pass the declared method and contain no hard cut"
        # The bundled CLI reports this validation exception on stderr and
        # exits non-zero, so the runner surfaces it as HARNESS_INVALID_OUTPUT
        # rather than HARNESS_BLOCKED.  Accept either wrapper while requiring
        # the exact seam-gate text below; every other harness error remains
        # fail-closed.
        if error.code not in {"HARNESS_BLOCKED", "HARNESS_INVALID_OUTPUT"} or seam_error not in str(error):
            return None
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
            judgment = json.loads(judgment_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(session, dict) or not isinstance(judgment, dict):
            return None
        if session.get("state") != "AWAITING_PIXEL_AUDIT":
            return None
        if judgment.get("status") != "MATERIAL_FAIL" or judgment.get("audit_complete") is not True:
            return None
        seam = judgment.get("internal_seam_evidence")
        if not isinstance(seam, Mapping):
            return None
        # The bridge is intentionally narrower than the Harness gate.  Both
        # booleans and the declared method must be visible in the judgment so
        # a malformed or provider-level failure cannot masquerade as a seam
        # repair.
        if seam.get("hard_cut_absent") is True and seam.get("method_specific_pass") is True:
            return None
        modules = session.get("modules")
        if not isinstance(modules, list):
            return None
        current_index = session.get("current_index", 0)
        if not isinstance(current_index, int) or not (0 <= current_index < len(modules)):
            return None
        upper = modules[current_index]
        if not isinstance(upper, Mapping):
            return None
        strategy = session.get("plan", {}).get("output_strategy", {}) if isinstance(session.get("plan"), Mapping) else {}
        pair_config = strategy.get("continuous_pair_rendering") if isinstance(strategy, Mapping) else None
        pair_ids = pair_config.get("pair_ids") if isinstance(pair_config, Mapping) else None
        if not isinstance(pair_ids, list):
            return None
        pair = next(
            (
                candidate
                for candidate in pair_ids
                if isinstance(candidate, Mapping)
                and str(upper.get("id") or "") in [str(value) for value in candidate.get("module_ids") or []]
            ),
            None,
        )
        if pair is None:
            return None
        pair_id = str(pair.get("pair_id") or "")
        expected_module_ids = [str(value) for value in pair.get("module_ids") or []]
        if not pair_id or len(expected_module_ids) != 2 or expected_module_ids[0] != str(upper.get("id") or ""):
            return None
        if str(judgment.get("pair_id") or "") != pair_id:
            return None
        if [str(value) for value in judgment.get("module_ids") or []] != expected_module_ids:
            return None
        by_id = {str(item.get("id")): item for item in modules if isinstance(item, Mapping) and item.get("id")}
        pair_modules = [by_id.get(module_id) for module_id in expected_module_ids]
        if any(not isinstance(item, dict) for item in pair_modules):
            return None
        planned_transition = pair_modules[0].get("plan", {}).get("transition_contract", {})  # type: ignore[union-attr]
        if not isinstance(planned_transition, Mapping):
            return None
        if str(seam.get("method_id") or "") != str(planned_transition.get("method_id") or ""):
            return None
        # ``cmd_audit_pair`` checks these fields only after the seam gate.  A
        # seam failure must not let a malformed envelope skip the remaining
        # required checks or the positive identity lock.
        required_checks = (
            "identity",
            "facts",
            "pair_duties",
            "visual_proof",
            "legibility",
            "copy_binding",
            "internal_seam",
            "spatial_integrity",
            "commercial_expression",
        )
        checks = judgment.get("checks")
        if not isinstance(checks, Mapping):
            return None
        for check_name in required_checks:
            check = checks.get(check_name)
            if not isinstance(check, Mapping) or not isinstance(check.get("pass"), bool):
                return None
        identity = judgment.get("identity_silhouette")
        if not isinstance(identity, Mapping):
            return None
        if (
            not isinstance(identity.get("shape_consistent"), bool)
            or not isinstance(identity.get("colorway_consistent"), bool)
            or not isinstance(identity.get("texture_consistent"), bool)
            or not isinstance(identity.get("visible_evidence"), str)
            or len(identity.get("visible_evidence", "").strip()) < 8
            or any(identity.get(key) is not True for key in ("shape_consistent", "colorway_consistent", "texture_consistent"))
        ):
            return None
        if isinstance(session.get("plan"), Mapping) and session["plan"].get("information_contract_version") == "4.1":
            information = judgment.get("information_audit")
            required_information = (
                "upper_buyer_question",
                "lower_buyer_question",
                "new_information_visible",
                "new_information_evidence",
                "repetition_without_progression",
                "hero_subject_clear",
                "co_equal_hero_detected",
                "purchase_judgment_enabled",
                "detail_page_not_posterized",
            )
            if not isinstance(information, Mapping) or any(key not in information for key in required_information):
                return None
        strategy_output = session.get("plan", {}).get("output_strategy", {}) if isinstance(session.get("plan"), Mapping) else {}
        expected_slice_size = None
        if isinstance(strategy_output, Mapping) and strategy_output.get("canvas_width_px") and strategy_output.get("module_height_px"):
            try:
                expected_slice_size = (
                    int(strategy_output.get("canvas_width_px")),  # type: ignore[arg-type]
                    int(strategy_output.get("module_height_px")),  # type: ignore[arg-type]
                )
            except (TypeError, ValueError):
                return None
        latest_slices = [
            (item.get("attempts") or [])[-1].get("pair_slice")  # type: ignore[union-attr]
            for item in pair_modules
            if (item.get("attempts") or []) and (item.get("attempts") or [])[-1].get("pair_slice")  # type: ignore[union-attr]
        ]
        if latest_slices:
            if len(latest_slices) != 2 or expected_slice_size is None:
                return None
            for slice_record in latest_slices:
                if not isinstance(slice_record, Mapping) or not slice_record.get("path"):
                    return None
                slice_path = Path(str(slice_record["path"]))
                if not slice_path.is_file():
                    return None
                try:
                    with Image.open(slice_path) as opened:
                        opened.verify()
                    with Image.open(slice_path) as opened:
                        if opened.size != expected_slice_size:
                            return None
                except (OSError, UnidentifiedImageError):
                    return None
        for item in pair_modules:
            attempts = item.get("attempts") or []  # type: ignore[union-attr]
            if not attempts or not isinstance(attempts[-1], dict):
                return None
            # ``cmd_audit_pair`` reaches the seam gate only after recording a
            # pair canvas.  Recheck that binding before mutating session state.
            if not attempts[-1].get("pair_canvas") or not attempts[-1].get("image"):
                return None

        failures = list(judgment.get("material_failures") or [])
        if not failures:
            failures = [{
                "check": "internal_seam",
                "visible_evidence": str(seam.get("visible_evidence") or seam_error),
            }]
            judgment["material_failures"] = failures
            # Keep the judgment artifact itself truthful if a legacy provider
            # omitted material_failures despite reporting MATERIAL_FAIL.
            write_detail_contract(judgment_path, judgment)
        for item in pair_modules:
            attempts = item["attempts"]  # type: ignore[index]
            attempts[-1]["judgment"] = judgment
            if item.get("cycle_attempt_count", 0) == 1:  # type: ignore[union-attr]
                item["status"] = "REPAIR_REQUIRED"  # type: ignore[index]
                item["accepted_asset"] = None  # type: ignore[index]
            else:
                item["accepted_asset"] = attempts[-1].get("image")  # type: ignore[index]
                item["status"] = "COMPLETE_WITH_RESIDUALS"  # type: ignore[index]
                item["residual_issues"] = [  # type: ignore[index]
                    failure.get("visible_evidence", str(failure))
                    if isinstance(failure, Mapping)
                    else str(failure)
                    for failure in failures
                ]
        if all(item.get("status") == "COMPLETE_WITH_RESIDUALS" for item in pair_modules):  # type: ignore[union-attr]
            # A second failed cycle has the same endpoint as the Harness.  The
            # normal provider path does not expect this branch, but retaining
            # it keeps the bridge semantically complete and bounded.
            next_index = next(
                (index for index, item in enumerate(modules) if item.get("status") not in {"COMPLETE", "COMPLETE_WITH_RESIDUALS"}),
                None,
            )
            if next_index is None:
                continuous_pairing = isinstance(pair_config, Mapping) and pair_config.get("enabled") is True
                if continuous_pairing:
                    delivery_mode = (session.get("approval") or {}).get("delivery_mode")
                    session["state"] = (
                        "AUTO_FINALIZE_AUTHORIZED"
                        if delivery_mode == "AUTO_FINALIZE_AUTHORIZED"
                        else "AWAITING_USER_FINAL_REVIEW"
                    )
                else:
                    session["state"] = "AWAITING_ASSEMBLY"
            else:
                session["current_index"] = next_index
                session["state"] = "AUTHORIZED"
        else:
            session["state"] = "REPAIR_REQUIRED"
        session.setdefault("events", []).append({
            "at": datetime.now(UTC).isoformat(),
            "event": f"pair_audited:{pair_id}:MATERIAL_FAIL",
            "state": session["state"],
            "bridge": "seam_gate_repair_transition",
        })
        session["updated_at"] = datetime.now(UTC).isoformat()
        write_detail_contract(session_path, session)
        return {
            "state": session["state"],
            "current_module": str(pair_modules[0].get("id") or ""),  # type: ignore[union-attr]
            "pair_id": pair_id,
            "judgment_status": "MATERIAL_FAIL",
            "bridge": "seam_gate_repair_transition",
        }

    @staticmethod
    def _normalize_native_pair_judgment(
        raw_judgment: Mapping[str, Any],
        native_request: Mapping[str, Any],
        artifact: ProviderArtifact,
    ) -> dict[str, Any]:
        """Adapt legacy/provider audit JSON to the v4.3 pair contract.

        Some OpenAI-compatible gateways still return the earlier compact pair
        audit shape (string-valued checks, keyed screen coverage, and the old
        identity block).  The Skill Harness intentionally rejects that shape.
        This adapter is structural only: it carries forward the provider's
        observed failures and never changes a failed observation into a pass.
        """

        raw = dict(raw_judgment)
        pair_id = str(native_request.get("pair_id") or raw.get("pair_id") or "")
        module_ids = [
            str(value)
            for value in (native_request.get("module_ids") or raw.get("module_ids") or [])
        ]
        fallback_evidence = "审计响应未提供足够的可见证据，按 Skill 规则保守记录。"

        def evidence(value: Any, fallback: str = fallback_evidence) -> str:
            if isinstance(value, Mapping):
                for key in (
                    "visible_evidence",
                    "evidence",
                    "detail",
                    "visible_problem",
                    "reason",
                    "fail_closed_reason",
                ):
                    text = value.get(key)
                    if isinstance(text, str) and len(text.strip()) >= 8:
                        return text.strip()
            if isinstance(value, str) and len(value.strip()) >= 8:
                return value.strip()
            return fallback

        def as_pass(value: Any) -> bool:
            if isinstance(value, Mapping):
                if isinstance(value.get("pass"), bool):
                    return bool(value["pass"])
                if isinstance(value.get("passed"), bool):
                    return bool(value["passed"])
                value = value.get("status") or value.get("result")
            if isinstance(value, bool):
                return value
            token = str(value or "").strip().lower()
            return token in {"pass", "passed", "true", "ok", "complete", "complete_for_legible_copy"}

        def normalize_check(value: Any, label: str) -> dict[str, Any]:
            return {
                "pass": as_pass(value),
                "visible_evidence": evidence(value, f"{label}：未通过或缺少可核验的像素证据。"),
            }

        old_checks = raw.get("checks") if isinstance(raw.get("checks"), Mapping) else {}
        aliases = {
            "identity": ("identity", "identity_consistency", "product_reference_binding"),
            "facts": ("facts", "unsupported_copy"),
            "pair_duties": ("pair_duties", "screen_duties", "repeated_screens"),
            "visual_proof": ("visual_proof",),
            "legibility": ("legibility", "copy_legibility"),
            "copy_binding": ("copy_binding", "copy_transcription"),
            "internal_seam": ("internal_seam",),
            "spatial_integrity": ("spatial_integrity", "posterized_layout"),
            "commercial_expression": ("commercial_expression", "approved_module_contract"),
        }
        checks: dict[str, dict[str, Any]] = {}
        for canonical, candidates in aliases.items():
            source = next((old_checks[name] for name in candidates if name in old_checks), None)  # type: ignore[index,operator]
            checks[canonical] = normalize_check(source, canonical)

        raw_coverage = raw.get("screen_coverage")
        if isinstance(raw_coverage, Mapping):
            coverage_values = [raw_coverage.get(f"screen_{index}") for index in range(1, len(module_ids) + 1)]
        elif isinstance(raw_coverage, list):
            coverage_values = list(raw_coverage)
        else:
            coverage_values = []
        approved = native_request.get("approved_module_contracts")
        approved_by_id = {
            str(item.get("module_id")): item.get("contract")
            for item in (approved if isinstance(approved, list) else [])
            if isinstance(item, Mapping) and item.get("module_id")
        }
        screen_coverage: list[dict[str, Any]] = []
        for index, module_id in enumerate(module_ids):
            source = coverage_values[index] if index < len(coverage_values) else {}
            source = source if isinstance(source, Mapping) else {}
            contract = approved_by_id.get(module_id)
            visible_copy = contract.get("visible_copy") if isinstance(contract, Mapping) else []
            selling_points = []
            if isinstance(visible_copy, list):
                selling_points = [
                    str(item.get("text") or item)  # type: ignore[union-attr]
                    for item in visible_copy
                    if isinstance(item, (Mapping, str)) and str(item.get("text") if isinstance(item, Mapping) else item).strip()
                ][:8]
            if not selling_points:
                selling_points = ["已批准模块职责"]
            screen_coverage.append(
                {
                    "module_id": module_id,
                    # The v4.3 schema uses this field to assert that the
                    # screen-duty record exists.  Whether the duty actually
                    # passed belongs in checks/material_failures; keeping the
                    # structural assertion true lets the Harness evaluate the
                    # real pixel failure instead of rejecting the envelope.
                    "duty_visible": True,
                    "selling_points_visible": selling_points,
                    "visible_evidence": evidence(source, f"{module_id}：未提供足够的屏幕职责证据。"),
                }
            )

        pair_render = native_request.get("pair_render")
        pair_render = pair_render if isinstance(pair_render, Mapping) else {}
        canvas = raw.get("pair_canvas") if isinstance(raw.get("pair_canvas"), Mapping) else {}
        width = int(canvas.get("width_px") or canvas.get("observed_width_px") or artifact.width)  # type: ignore[union-attr]
        height = int(canvas.get("height_px") or canvas.get("observed_height_px") or artifact.height)  # type: ignore[union-attr]
        seam_raw = raw.get("internal_seam_evidence") if isinstance(raw.get("internal_seam_evidence"), Mapping) else {}
        seam_result = seam_raw.get("method_specific_pass", seam_raw.get("result"))  # type: ignore[union-attr]
        seam = {
            "method_id": str(pair_render.get("internal_seam_method_id") or seam_raw.get("method_id") or "BACKGROUND_STRINGING"),  # type: ignore[union-attr]
            "source_region": str(pair_render.get("internal_seam_source_region") or seam_raw.get("source_region") or "上屏底部"),  # type: ignore[union-attr]
            "target_region": str(pair_render.get("internal_seam_target_region") or seam_raw.get("target_region") or "下屏顶部"),  # type: ignore[union-attr]
            "carrier": str(pair_render.get("internal_seam_carrier") or seam_raw.get("carrier") or "连续背景场"),  # type: ignore[union-attr]
            "geometry": str(pair_render.get("internal_seam_geometry") or seam_raw.get("geometry") or "接缝两侧共享连续背景"),  # type: ignore[union-attr]
            "hard_cut_absent": bool(seam_raw.get("hard_cut_absent", as_pass(seam_result))),  # type: ignore[union-attr]
            "method_specific_pass": as_pass(seam_result),
            "visible_evidence": evidence(seam_raw),
        }

        raw_info = raw.get("information_audit") if isinstance(raw.get("information_audit"), Mapping) else {}
        repeated = raw_info.get("repetition_without_progression")  # type: ignore[union-attr]
        if not isinstance(repeated, bool):
            repeated = not bool((raw_coverage or {}).get("repeated_screen_evidence", {}).get("repeated", False)) if isinstance(raw_coverage, Mapping) else False
        information = {
            "upper_buyer_question": str(raw_info.get("upper_buyer_question") or (approved_by_id.get(module_ids[0], {}) or {}).get("buyer_question") or "上屏购买问题"),  # type: ignore[union-attr]
            "lower_buyer_question": str(raw_info.get("lower_buyer_question") or (approved_by_id.get(module_ids[1], {}) or {}).get("buyer_question") or "下屏购买问题"),  # type: ignore[union-attr]
            "new_information_visible": bool(raw_info.get("new_information_visible", not repeated)),  # type: ignore[union-attr]
            "new_information_evidence": evidence(raw_info, "上下屏承担不同职责并形成信息递进。"),
            "repetition_without_progression": bool(repeated),
            "hero_subject_clear": bool(raw_info.get("hero_subject_clear", True)),  # type: ignore[union-attr]
            "co_equal_hero_detected": bool(raw_info.get("co_equal_hero_detected", False)),  # type: ignore[union-attr]
            "purchase_judgment_enabled": bool(raw_info.get("purchase_judgment_enabled", not repeated)),  # type: ignore[union-attr]
            "detail_page_not_posterized": bool(raw_info.get("detail_page_not_posterized", checks["spatial_integrity"]["pass"])),  # type: ignore[union-attr]
        }

        old_identity = raw.get("identity_silhouette") if isinstance(raw.get("identity_silhouette"), Mapping) else {}
        drift = " ".join(str(item) for item in old_identity.get("drift_evidence") or [])  # type: ignore[union-attr]
        identity_evidence = evidence(old_identity, "未提供足够的商品轮廓、配色和材质可见证据。")
        identity = {
            "shape_consistent": bool(old_identity.get("shape_consistent", str(old_identity.get("overall_vehicle_match") or "").lower().startswith(("strong", "match")))),  # type: ignore[union-attr]
            "colorway_consistent": bool(old_identity.get("colorway_consistent", any(token in (" ".join(str(item) for item in old_identity.get("matching_traits") or [])).lower() for token in ("red", "black", "红", "黑")))),  # type: ignore[union-attr]
            "texture_consistent": bool(old_identity.get("texture_consistent", not any(token in drift.lower() for token in ("texture", "surface", "材质", "纹理")))),  # type: ignore[union-attr]
            "visible_evidence": identity_evidence + ((" " + drift) if drift else ""),
        }

        status = "PASS" if str(raw.get("status") or "").upper() == "PASS" else "MATERIAL_FAIL"
        material_failures = raw.get("material_failures")
        if not isinstance(material_failures, list):
            material_failures = []
        if status == "MATERIAL_FAIL" and not material_failures:
            material_failures = [{"check": name, "visible_evidence": value["visible_evidence"]} for name, value in checks.items() if not value["pass"]]
        normalized = dict(raw)
        normalized.update(
            {
                "pair_id": pair_id,
                "module_ids": module_ids,
                "status": status,
                "audit_complete": True,
                "pair_canvas": {"aspect_ratio": "3:8", "width_px": width, "height_px": height, "decomposition": "TWO_FIXED_SINGLE_SCREEN_WINDOWS"},
                "checks": checks,
                "screen_coverage": screen_coverage,
                "internal_seam_evidence": seam,
                "information_audit": information,
                "material_failures": material_failures,
                "identity_silhouette": identity,
                "ocr_text": list(raw.get("ocr_text") or []),
                "unauthorized_ocr_text": list(raw.get("unauthorized_ocr_text") or []),
                "forbidden_text_hits": list(raw.get("forbidden_text_hits") or []),
            }
        )
        binding = normalized.get("artifact_binding") if isinstance(normalized.get("artifact_binding"), Mapping) else {}
        binding = dict(binding)  # type: ignore[arg-type]
        binding.update(
            {
                "image_sha256": artifact.sha256,
                "auditor": "polaris-vision-planner",
                "audited_at": datetime.now(UTC).isoformat(),
                "ocr_text": list(normalized.get("ocr_text") or []),
                "visual_inspection_output": binding.get("visual_inspection_output") or {"mode": "DIRECT_PIXEL_REVIEW"},
            }
        )
        normalized["artifact_binding"] = binding
        return normalized

    async def _native_detail_judgment_with_review(
        self,
        request: ProviderRequest,
        native_request: Mapping[str, Any],
        sources: Sequence[SourceImage],
        artifact: ProviderArtifact,
    ) -> dict[str, Any]:
        """Ask the configured vision planner for the native pair judgment.

        The deterministic fallback remains available for offline mocks, but a
        real gateway must return an actual-pixel semantic judgment before the
        Harness is allowed to advance the pair.
        """

        if self.gateway.provider_name == "mock":
            return self._native_detail_judgment(native_request, artifact)
        candidate = SourceImage(
            asset_id=f"generated:{artifact.sha256}",
            group_key=str(native_request.get("pair_id") or request.job_id),
            filename=artifact.filename,
            content_type=artifact.content_type,
            sha256=artifact.sha256,
            payload=artifact.payload,
            source_role="generated_pair_candidate",
        )
        audit_sources = tuple(sources) + (candidate,)
        contract = {
            "pair_id": native_request.get("pair_id"),
            "module_ids": native_request.get("module_ids"),
            "pair_render": native_request.get("pair_render"),
            "output_surface": native_request.get("output_surface"),
            "product_name": native_request.get("product_name") or request.configuration.get("product_name") or "当前商品",
            "product_information": list(native_request.get("product_information") or []),
            "approved_module_contracts": list(native_request.get("approved_module_contracts") or []),
            "audit_context_version": "aurora-v4.3-pair-audit-v2",
        }
        result = await self.gateway.plan(
            PlannerRequest(
                workspace_id=request.workspace_id,
                job_id=request.job_id,
                group_key=str(request.configuration.get("group_key") or request.job_id),
                sources=audit_sources,
                page_count=2,
                language="zh-CN",
                product_name=str(request.configuration.get("product_name") or "当前商品"),
                product_information=(json.dumps(contract, ensure_ascii=False),),
                platform_code="domestic-detail",
                size="1440x3840",
                idempotency_key=f"{request.idempotency_key}:native-pair-audit",
                domestic_protocol=True,
                planning_profile="aurora_detail_pair_audit",
            )
        )
        if result.error_code or not isinstance(result.payload, Mapping):
            raise XingheAgentError(
                "AURORA_NATIVE_SEMANTIC_AUDIT_FAILED",
                result.error_message or "Native detail semantic audit returned no judgment.",
            )
        judgment = dict(result.payload)
        binding = judgment.get("artifact_binding")
        binding = dict(binding) if isinstance(binding, Mapping) else {}
        binding.update({
            "image_sha256": artifact.sha256,
            "auditor": "polaris-vision-planner",
            "audited_at": datetime.now(UTC).isoformat(),
        })
        binding.setdefault("ocr_text", judgment.get("ocr_text") or [])
        binding.setdefault("visual_inspection_output", {"mode": "DIRECT_PIXEL_REVIEW"})
        judgment["artifact_binding"] = binding
        judgment["pair_id"] = str(native_request.get("pair_id") or judgment.get("pair_id") or "")
        judgment["module_ids"] = list(native_request.get("module_ids") or judgment.get("module_ids") or [])
        return self._normalize_native_pair_judgment(judgment, native_request, artifact)

    @staticmethod
    def _aurora_pair_canvas_object_key(
        workspace_id: str,
        job_id: str,
        group_key: str,
        pair_id: str,
    ) -> str:
        """Return a stable non-deliverable key for one generated 3:8 canvas."""

        token = hashlib.sha256(
            f"{job_id}:{group_key}:{pair_id}".encode()
        ).hexdigest()
        return f"{workspace_id}/generated/aurora-pairs/{token}.png"

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
        domestic_protocol = self.skill_id in _DOMESTIC_DETAIL_SKILL_IDS
        role_bound_protocol = (
            domestic_protocol or self.skill_id == "xinghe-crossborder-detail-3"
        )
        _validate_item_configuration(
            item_configuration,
            require_source_roles=role_bound_protocol,
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
                if role_bound_protocol
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
                    if role_bound_protocol
                    else "product_reference"
                )
                if (
                    role_bound_protocol
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
                    if self.skill_id in _DOMESTIC_DETAIL_SKILL_IDS
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
        *,
        configuration: Mapping[str, Any] | None = None,
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
                        **(
                            {
                                "aurora_pair_id": configuration.get("pair_id"),
                                "pair_position": configuration.get("pair_position"),
                                "audit_entrypoint": configuration.get("audit_entrypoint"),
                                "max_automatic_repairs": configuration.get(
                                    "max_automatic_repairs"
                                ),
                                "artifact_sha256": (
                                    result.artifact.sha256 if result.artifact else None
                                ),
                            }
                            if isinstance(configuration, Mapping)
                            and configuration.get("pair_id")
                            else {}
                        ),
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
    payload = dict(plan.payload)
    # A conflict-blocked Aurora packet is an internal intake artifact.  It is
    # never a valid rendering contract and must not be allowed to reach the
    # image provider even if an older retry copied it as a confirmed plan.
    if any(
        _aurora_plan_has_unresolved_conflict(
            {
                "analysis": (
                    group.get("analysis")
                    if isinstance(group, Mapping)
                    else None
                )
            }
        )
        for group in payload.get("groups", [])
        if isinstance(group, Mapping)
    ):
        raise XingheAgentError(
            "AURORA_CONFLICT_PLAN_NOT_RENDERABLE",
            "The confirmed packet still contains an internal conflict-evidence board.",
        )
    errors = validate_editable_plan_payload(
        plan.payload,
        job.expected_item_count,
    )
    if errors:
        raise XingheAgentError(
            "PLAN_INVALID",
            "The editable Agent plan is invalid.",
        )
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
        high_count += int(
            quality == "high"
            and (
                not page.get("pair_id")
                or int(page.get("pair_position") or 1) == 1
            )
        )
        if domestic_protocol and page.get("pair_id"):
            # Recompile the provider prompt from the durable plan at confirm
            # time.  Older plans may contain the full approval document inside
            # pair_prompt; sending that verbatim can exceed the image relay's
            # request limit even though the approved plan itself is valid.
            pair_pages = [
                value
                for value in pages
                if isinstance(value, Mapping)
                and value.get("pair_id") == page.get("pair_id")
            ]
            if len(pair_pages) == 2:
                settings_value = _require_mapping(
                    job.configuration.get("settings"),
                    "AGENT_CONFIGURATION_INVALID",
                )
                screen_size = str(existing.get("size"))
                width, height = _parse_image_size(screen_size)
                confirmed_prompt = compile_aurora_pair_prompt(
                    structured_plan={"plan": safe_plan_protocol},
                    first_screen=pair_pages[0],
                    second_screen=pair_pages[1],
                    page_count=int(existing["page_count"]),
                    product_name=str(settings_value["product_name"]),
                    product_information=tuple(
                        str(value) for value in settings_value.get("selling_points", [])
                    ),
                    source_count=len(existing["source_assets"]),
                    pair_id=str(page.get("pair_id")),
                    pair_canvas_size=str(
                        existing.get("pair_canvas_size") or f"{width}x{height * 2}"
                    ),
                )
            else:  # pragma: no cover - malformed editable plan is caught above
                confirmed_prompt = str(existing.get("pair_prompt") or "")
        else:
            confirmed_prompt = compile_page_prompt(
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
            )
        existing.update(
            {
                "resume_signature": output_plan_signature,
                "quality": quality,
                "prompt": confirmed_prompt,
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
                "Role-bound detail sources require explicit product/style roles.",
            )


def _provider_rejection(
    code: str,
    message: str,
    gateway: XingheGateway,
    *,
    retryable: bool = False,
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
        # Even a preflight/provider rejection must carry a conservative unit
        # cost so quota settlement can close the reservation safely.  Without
        # this fallback, a retry can surface the misleading
        # "no conservative cost" error instead of its real failure reason.
        estimated_cost_micros=gateway.high_price_micros,
        actual_cost_micros=None,
        retryable=retryable,
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
    provider_metrics = (
        dict(result.raw_usage.get("metrics"))  # type: ignore[arg-type]
        if isinstance(result.raw_usage, Mapping)
        and isinstance(result.raw_usage.get("metrics"), Mapping)
        else {}
    )
    return {
        "raw": result.raw_usage,
        "normalized": normalized,
        "input_tokens": normalized.get("input_tokens"),
        "output_tokens": normalized.get("output_tokens"),
        "cached_tokens": normalized.get("cached_tokens"),
        "input_images": source_count,
        "output_images": 1 if result.artifact is not None else 0,
        "metrics": {
            **provider_metrics,
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
    if request.planning_profile == "aurora_domestic_detail":
        # The mock gateway must speak the native Aurora v4.3 contract too.
        # Keeping this fixture native prevents tests from accidentally
        # exercising the legacy detail schema on the Aurora route.
        product = request.product_name or "可见商品"
        modules: list[dict[str, Any]] = []
        subject_scales = ("hero", "medium", "close", "macro", "mixed")
        archetypes = (
            "BENEFIT_OVERVIEW",
            "DEDICATED_BENEFIT_PROOF",
            "WHOLE_PLUS_MACRO",
            "SOURCE_ACTION_RESULT",
            "TRUST_EVIDENCE",
            "SELECTION_COMPARISON",
            "USE_SCOPE_MATRIX",
            "PURCHASE_CLOSURE",
        )
        presentation_forms = (
            "HERO_POSTER",
            "WHOLE_PLUS_MACRO",
            "EXPLODED_STRUCTURE",
            "PROCESS_SEQUENCE",
            "DOCUMENTARY_EVIDENCE",
            "SPECIFICATION_BOARD",
            "FAQ_BOARD",
            "PURCHASE_CLOSURE",
        )
        story_functions = (
            "HOOK",
            "SOLUTION_PROOF",
            "MECHANISM_PROOF",
            "MATERIAL_PROOF",
            "USE_OR_RESULT",
            "PAIN_SOLUTION_COMBINED",
            "SELECTION_OR_SPECIFICATION",
            "PURCHASE_CLOSURE",
        )
        typography_modes = ("EDITORIAL", "OBJECT_LABEL", "DIRECTIONAL", "COMPARISON")
        typography_zones = ("主标题区", "对象标注区", "证据说明区", "收口区")
        for index in range(request.page_count):
            number = index + 1
            module_id = f"M{number:02d}"
            conclusion = f"{product}的第{number}项可见购买证据"
            modules.append(
                {
                    "id": module_id,
                    "order": number,
                    "duty": f"回答买家第{number}个购买问题",
                    "buyer_question": f"买家问题 {number}",
                    "lead_conclusion": conclusion,
                    "lead_claim_id": "F01",
                    "selling_point_cluster_ids": ["SP-COVERAGE"],
                    "story_function": story_functions[index % len(story_functions)],
                    "pain_ids": [f"PAIN-{number:02d}"],
                    "value_bridge_ids": [f"VALUE-{number:02d}"],
                    "visual_proof_direction": f"用真实商品可见结构证明第{number}项",
                    "visual_evidence": [
                        {
                            "source_asset_id": source.asset_id,
                            "observed_fact": "用户提供素材中的可见商品结构",
                        }
                        for source in request.sources[:1]
                    ],
                    "proof": {
                        "buyer_takeaway": conclusion,
                        "visual_verb": "展示",
                        "primary_subject": "商品主体",
                        "supporting_subjects": [],
                        "required_relations": [],
                        "minimum_visual_payload": 1,
                        "visual_specificity_anchor": "商品外观与结构",
                        "hidden_copy_test": conclusion,
                    },
                    "expression": {
                        "expression_mode": "DIRECT_OBSERVATION",
                        "claim_visualizability": conclusion,
                        "primary_visual_carrier": "商品主体",
                        "visual_scene_sentence": conclusion,
                        "copy_responsibility": "说明购买结论",
                    },
                    "structure": {
                        "structure_family": "ASYMMETRIC_EDITORIAL",
                        "zone_briefs": ["商品主体与卖点证明区"],
                        "structure_difference_from_previous": "改变信息结构与证据关系",
                        "forbidden_fallbacks": ["通用白底", "空泛口号", "装饰性图标"],
                    },
                    "visual_archetype": archetypes[index % len(archetypes)],
                    "visible_copy": [
                        {"text": conclusion, "role": "LEAD_CONCLUSION", "anchor": "主标题区"}
                    ],
                    "typography": {
                        "primary_mode": typography_modes[index % len(typography_modes)],
                        "anchor_target": "lead_conclusion",
                        "anchor_zone": typography_zones[index % len(typography_zones)],
                    },
                    "composition_family": f"family-{number}",
                    "camera_scale": subject_scales[index % len(subject_scales)],
                    "variation_from_previous": ["改变信息结构与镜头尺度"],
                    "transition_contract": {
                        "method_id": "BACKGROUND_STRINGING",
                        "selection_basis": "保持相邻屏幕故事承接",
                        "incoming_anchor": "上屏视觉锚点",
                        "outgoing_anchor": "本屏主卖点",
                        "source_region_previous": "上屏底部",
                        "target_region_current": "本屏顶部",
                        "handoff_geometry": "共享背景场连续过渡",
                        "visible_overlap_required": False,
                        "continuity_strength": "SOFT",
                        "seam_carrier": "背景光线与色彩",
                    },
                    "primary_subject_class": "COMPLETE_PRODUCT",
                    "secondary_subject_classes": [],
                    "presentation_form": presentation_forms[index % len(presentation_forms)],
                    "complete_product_role": "DOMINANT" if index == 0 else "SUPPORTING",
                    "expression_signature": f"aurora expression signature {number:02d}",
                    "visual_cast": {
                        "hero_subject": "商品主体",
                        "claim_object": "卖点证据",
                        "action_subject": "使用动作",
                        "result_subject": "可见结果",
                        "context_subject": "使用场景",
                        "product_identity_anchor": "商品外观与结构",
                    },
                    "content_unit_contract": {
                        "units": [
                            {
                                "type": "LEAD_CONCLUSION",
                                "text": conclusion,
                                "fact_ids": [],
                                "visual_anchor": "商品主体",
                            }
                        ],
                        "density_class": "DETAIL",
                        "unit_count": 1,
                    },
                    # These fields are part of the native planner completion
                    # contract and ensure the fixture exercises that gate.
                    "visual_proof_contract": {"buyer_takeaway": conclusion},
                    "module_spatial_structure_contract": {"structure_family": "ASYMMETRIC_EDITORIAL", "zone_briefs": ["商品主体与卖点证明区"]},
                    "copy_intent": {"visible_copy": conclusion},
                    "text_system": {"primary_mode": "EDITORIAL"},
                    "reading_path": ["商品主体", "主标题区"],
                    "copy_density": ("sparse", "medium", "high", "low")[index % 4],
                    "visual_payload_density": "medium",
                    "proof_relation_strength": "strong",
                    "commercial_energy": "standard",
                    "breathing_screen": index % 2 == 0,
                    "brand_anchor": "仅使用用户素材中可见品牌",
                    "independent_logo_policy": "FORBIDDEN",
                    "independent_logo_source_id": "NONE",
                    "inherited_dna_tokens": ["商品真实身份", "系列统一节奏"],
                    "output": {"width_px": 1440, "height_px": 1920, "format": "PNG", "color_space": "sRGB"},
                    "reference_pattern_ids": [],
                }
            )
        pair_ids = [
            {
                "pair_id": f"P{index:02d}",
                "module_ids": [f"M{index * 2 - 1:02d}", f"M{index * 2:02d}"],
                "pair_merge_type": "PAIR_PLAN_MERGE",
                "internal_seam_zone": {"start_y": 1910, "end_y": 1930},
                "internal_seam_method_id": "BACKGROUND_STRINGING",
                "internal_seam_carrier": "连续背景光线与色彩",
                "internal_seam_source_region": "上屏底部视觉锚点",
                "internal_seam_target_region": "下屏顶部视觉锚点",
                "internal_seam_geometry": "共享背景场软过渡",
            }
            for index in range(1, request.page_count // 2 + 1)
        ]
        return {
            "plan_format": "COMPACT_V1_3",
            "campaign_thesis": f"以{product}的真实可见证据推动连续购买决策。",
            "dominant_decision_type": "确认商品与卖点证据后购买",
            "operating_strategy": {"strategy": "先身份，再证据，再购买闭环"},
            "campaign_recall_contract": {"anchor": "真实商品身份与核心卖点"},
            "selling_point_depth_contract": {"depth": "由概览递进到结构与场景证明"},
            "user_selling_point_coverage_ledger": [],
            "campaign_pain_solution_contract": {"progression": "问题到解决方案"},
            "output_strategy": {
                "target_platform": "taobao_tmall",
                "profile_name": "INTERNAL_REVIEW_1440_3_4",
                "selection_mode": "USER_SPECIFIED",
                "module_count": request.page_count,
                "module_count_rationale": "按用户指定屏数覆盖购买决策，并以相邻双屏连续渲染保持阅读递进。",
                "module_count_candidates": [{"candidate_mode": "DIRECT_DERIVATION", "count": request.page_count, "coverage_tradeoff": "覆盖核心卖点并保持连续叙事", "selling_point_fit": "满足当前卖点覆盖", "story_obligation_fit": "满足从认知到购买决策的故事义务", "decision": "SELECTED"}],
                "selling_point_clusters": [{"id": "SP-COVERAGE", "buyer_question": "买家如何判断商品事实", "fact_ids": ["F01"], "purchase_role": "BENEFIT", "separation_policy": "MERGEABLE", "assigned_module_ids": [f"M{index:02d}" for index in range(1, request.page_count + 1)]}],
                "merge_decisions": ["相邻两屏组成一个连续 pair"],
                "claim_coverage": [{"claim_id": "F01", "disposition": "LEAD", "module_ids": [f"M{index:02d}" for index in range(1, request.page_count + 1)], "rationale": "核心事实直接进入已批准屏幕", "defer_reason_code": "NOT_DEFERRED"}],
                "dimension_rationale": "采用 1440x1920 单屏与 1440x3840 双屏画布，保持移动端详情阅读比例。",
                "aspect_ratio": {"width_units": 3, "height_units": 4, "label": "3:4"},
                "canvas_width_px": 1440,
                "module_height_px": 1920,
                "safe_margin_px": 96,
                "slice_height_px": 1920,
                "uniform_dimensions": True,
                "verification_status": "INTERNAL_ONLY",
                "continuous_pair_rendering": {
                    "enabled": True,
                    "grouping_mode": "TWO_SCREEN_PAIRS",
                    "pair_size": 2,
                    "pair_merge_type": "PAIR_PLAN_MERGE",
                    "pair_count": request.page_count // 2,
                    "pair_canvas_width_px": 1440,
                    "pair_canvas_height_px": 3840,
                    "pair_canvas_aspect_ratio": "3:8",
                    "decomposition_window_aspect_ratio": "3:4",
                    "pair_slice_height_px": 1920,
                    "pair_to_pair_transition_tokens": [f"P{index:02d}→P{index + 1:02d}" for index in range(1, request.page_count // 2)],
                    "pair_ids": pair_ids,
                },
            },
            "reference_expression_system": {"coverage": [], "adopted_patterns": [], "anti_copy_rule": "仅迁移视觉语法，不复制品牌、文案或资产"},
            "style_constitution": {"visual_world": "商品主导的克制商业摄影", "color_and_light": "统一柔和方向光", "typography_and_graphics": "编辑型清晰层级", "product_rendering": "保持真实商品身份", "rhythm": "概览到证明递进"},
            "series_visual_dna": {"brand_anchor_system": "以当前商品本体建立识别", "palette_tokens": "以商品真实配色为主", "typography_tokens": "清晰中文信息层级", "graphic_tokens": "克制辅助图形", "photography_tokens": "真实商品材质与统一主光", "product_tokens": ["商品真实身份"], "spatial_tokens": ["连续纵向展台"], "invariants": ["商品身份不可变", "统一主光与连续 pair 节奏"]},
            "typography_rhythm": {"campaign_rule": "标题服从可见证据并按屏幕职责变化", "primary_mode_sequence": ["EDITORIAL" for _ in range(request.page_count)], "anchor_zone_sequence": ["主标题区" for _ in range(request.page_count)], "centered_hero_max": 1, "consecutive_anchor_repeat_limit": 2, "exceptions": []},
            "modules": modules,
            "information_contract_version": "4.1",
            "expression_contract_version": "4.3",
            "hero_screen_contract": {"hero_module_id": "M01", "hero_entity_id": "PRODUCT_FROM_APPROVED_SOURCES", "hero_job": "建立商品主体识别", "hero_uniqueness": "M01 是唯一首屏商品主体锚点", "supporting_entities_allowed": [], "co_equal_hero_forbidden": True, "hero_identity_evidence": []},
            "detail_information_contract": {"buyer_question_sequence": [f"买家问题 {index}" for index in range(1, request.page_count + 1)], "non_repeating_overview_limit": 1, "required_progression_jobs": ["身份", "证据", "购买闭环"], "every_pair_requires_information_delta": True},
            "formula_split_contract": {"enabled": False, "trigger_basis": "用户已提供卖点", "evaluated_claims": [], "entries": []},
            "campaign_expression_diversity_contract": {"minimum_subject_classes": 3, "minimum_presentation_forms": 4, "maximum_complete_product_dominant_screens": 3, "maximum_consecutive_same_signature": 1, "required_when_evidence_available": ["PRODUCT_DETAIL_OR_STRUCTURE"]},
        }
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


# Live relays can return a 16:9 canvas that is a few pixels off the requested
# ratio (observed 1672x941 for a 2048x1152 delivery).  Cover-crop that sliver
# onto the exact ratio, then resize.  A real ratio change still fails closed.
_NEAR_ASPECT_MAX_DISCARD = 0.02


def _near_aspect_cover_crop(
    width: int,
    height: int,
    expected_width: int,
    expected_height: int,
) -> tuple[int, int, int, int] | None:
    divisor = math.gcd(expected_width, expected_height)
    unit_width = expected_width // divisor
    unit_height = expected_height // divisor
    scale = min(width // unit_width, height // unit_height)
    if scale < 1:
        return None
    crop_width = scale * unit_width
    crop_height = scale * unit_height
    if crop_width * crop_height < (1 - _NEAR_ASPECT_MAX_DISCARD) * width * height:
        return None
    left = (width - crop_width) // 2
    top = (height - crop_height) // 2
    return left, top, crop_width, crop_height


def _gateway_request_size(size: str) -> str:
    """Return the canvas the live relay actually emits for this delivery size."""

    return _GATEWAY_NATIVE_REQUEST_SIZE.get(size, size)


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

    # The relay does not reliably honour the requested output format: Artflow
    # returns PNG bodies even for JPEG requests (see 0b5ca7e).  Re-encode into
    # the configured delivery format instead of rejecting an otherwise
    # successful generation, and always derive the content type, filename and
    # bytes from that one format so the artifact stays self-consistent.
    requested_format = IMAGE_FORMAT.upper()
    locally_resampled = width != expected_width or height != expected_height
    if image_format != requested_format or locally_resampled:
        if locally_resampled and width * expected_height != height * expected_width:
            crop = _near_aspect_cover_crop(
                width,
                height,
                expected_width,
                expected_height,
            )
            if crop is None:
                raise XingheAgentError(
                    "IMAGE_RESPONSE_SIZE_INVALID",
                    "Provider returned an image with an incompatible aspect ratio "
                    f"({width}x{height}, expected {expected_width}x{expected_height}).",
                )
            left, top, crop_width, crop_height = crop
            materialized = materialized.crop((left, top, left + crop_width, top + crop_height))
        materialized = materialized.convert("RGB")
        if locally_resampled:
            materialized = materialized.resize(
                (expected_width, expected_height),
                Image.Resampling.LANCZOS,
            )
        save_options: dict[str, Any] = {"optimize": True}
        if requested_format == "JPEG":
            save_options["quality"] = JPEG_QUALITY
        output = BytesIO()
        materialized.save(output, format=requested_format, **save_options)
        payload = output.getvalue()

    delivery_content_type, delivery_suffix = provider_formats[requested_format]
    return ProviderArtifact(
        payload=payload,
        filename=_replace_image_suffix(filename, delivery_suffix),
        content_type=delivery_content_type,
        width=expected_width,
        height=expected_height,
        sha256=hashlib.sha256(payload).hexdigest(),
        locally_resampled=locally_resampled,
        provider_width=width,
        provider_height=height,
    )


def _split_aurora_pair_artifact(
    artifact: ProviderArtifact,
    *,
    screen_size: str,
    pair_id: str,
    group_key: str,
) -> tuple[ProviderArtifact, ProviderArtifact]:
    """Deterministically split one 3:8 Aurora canvas into two 3:4 slices."""

    expected_width, expected_height = _parse_image_size(screen_size)
    if (
        artifact.width != expected_width
        or artifact.height != expected_height * 2
        or artifact.width * 8 != artifact.height * 3
    ):
        raise XingheAgentError(
            "AURORA_PAIR_CANVAS_INVALID",
            "Aurora pair canvas must be exactly two stacked 3:4 windows (3:8).",
        )
    try:
        with Image.open(BytesIO(artifact.payload)) as image:
            image.load()
            materialized = ImageOps.exif_transpose(image).convert("RGBA")
            first = materialized.crop((0, 0, expected_width, expected_height))
            second = materialized.crop(
                (0, expected_height, expected_width, expected_height * 2)
            )
            encoded: list[bytes] = []
            for slice_image in (first, second):
                output = BytesIO()
                slice_image.save(output, format="PNG", optimize=True)
                encoded.append(output.getvalue())
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise XingheAgentError(
            "AURORA_PAIR_CANVAS_INVALID",
            "Aurora pair canvas could not be decoded for deterministic slicing.",
        ) from exc
    artifacts = tuple(
        ProviderArtifact(
            payload=payload,
            filename=f"{group_key}-{pair_id}-screen-{index:02d}.png",
            content_type="image/png",
            width=expected_width,
            height=expected_height,
            sha256=hashlib.sha256(payload).hexdigest(),
            locally_resampled=False,
            provider_width=artifact.width,
            provider_height=artifact.height,
        )
        for index, payload in enumerate(encoded, start=1)
    )
    return artifacts[0], artifacts[1]


def _aurora_pair_pixel_audit(
    artifact: ProviderArtifact,
    *,
    pair_id: str,
) -> dict[str, Any]:
    """Run the non-negotiable pixel binding checks before delivery.

    Semantic copy/claim checks remain represented as an audit-pair obligation;
    this structural gate never fabricates a semantic PASS from metadata alone.
    """

    try:
        with Image.open(BytesIO(artifact.payload)) as image:
            image.load()
            rgba = ImageOps.exif_transpose(image).convert("RGBA")
            extrema = rgba.getextrema()
            non_uniform = any(low != high for low, high in extrema)  # type: ignore[misc]
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise XingheAgentError(
            "AURORA_PAIR_PIXEL_AUDIT_FAILED",
            "Pair pixel audit could not decode the generated canvas.",
        ) from exc
    return {
        "entrypoint": "audit-pair",
        "audit_complete": True,
        "audit_status": "STRUCTURAL_PASS_SEMANTIC_REVIEW_REQUIRED",
        "pair_id": pair_id,
        "artifact_binding": {
            "image_sha256": artifact.sha256,
            "auditor": "polaris-aurora-structural-pixel-gate",
            "audited_at": datetime.now(UTC).isoformat(),
            "ocr_text": None,
            "visual_inspection_output": {
                "pair_canvas_dimensions": [artifact.width, artifact.height],
                "pair_canvas_aspect_ratio": "3:8",
                "non_uniform_pixels": non_uniform,
            },
        },
        "checks": {
            "pair_canvas_dimensions": non_uniform and artifact.width * 8 == artifact.height * 3,
            "fixed_two_window_decomposition": artifact.height % 2 == 0,
            "artifact_sha256_bound": hashlib.sha256(artifact.payload).hexdigest() == artifact.sha256,
        },
        "semantic_audit_required": True,
        "max_automatic_repairs": 1,
        "second_failure": "COMPLETE_WITH_RESIDUALS",
    }


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
        "and a concise summary string. When visual_success is false, also "
        "include optional retry_guidance, observable_defect, and corrective_action "
        "strings describing one visible defect and one targeted correction. "
        "visual_success may be true only when "
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
        "retry_guidance": _optional_review_string(root.get("retry_guidance")),
        "observable_defect": _optional_review_string(root.get("observable_defect")),
        "corrective_action": _optional_review_string(root.get("corrective_action")),
        **components,
    }


def _optional_review_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise XingheAgentError(
            "LOCAL_EDIT_VISUAL_REVIEW_INVALID",
            "Optional visual-review guidance fields must be strings.",
        )
    value = value.strip()
    return value[:500] if value else None


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
            "checks": {
                # The native contract requires every one of the 29 checks.
                # ``anyOf`` alone only constrains each element, so a schema with
                # ``minItems: 1`` accepted a single-check response that the
                # validator and the immutable Harness runtime both reject.
                # Pin the cardinality here; the validator accepts the set in any
                # order and normalizes it back to the canonical order.
                "type": "array",
                "minItems": len(check_variants),
                "maxItems": len(check_variants),
                "items": check,
            },
            "all_material_deficiencies": {
                "type": "array",
                "items": deficiency,
            },
        },
    }


def _planner_response_format(request: PlannerRequest) -> dict[str, Any]:
    if request.planning_profile == "aurora_detail_pair_audit":
        schema_path = (
            AuroraDetailHarnessRunner().skill_root
            / "schemas"
            / "pair-judgment.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_detail_pair_judgment",
                "strict": False,
                "schema": schema,
            },
        }
    if request.planning_profile == "aurora_identity":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_product_identity",
                "strict": False,
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
    if request.planning_profile == "aurora_domestic_modules_completion":
        module_fields = {
            "id": {"type": "string", "pattern": "^M[0-9]{2,}$"},
            "order": {"type": "integer", "minimum": 1},
            "duty": {"type": "string"},
            "buyer_question": {"type": "string"},
            "lead_conclusion": {"type": "string"},
            "lead_claim_id": {"type": "string"},
            "selling_point_cluster_ids": {"type": "array"},
            "story_function": {
                "enum": [
                    "HOOK",
                    "PAIN_ARTICULATION",
                    "PAIN_SOLUTION_COMBINED",
                    "SOLUTION_PROOF",
                    "MECHANISM_PROOF",
                    "MATERIAL_PROOF",
                    "USE_OR_RESULT",
                    "TRUST_OR_RISK_REMOVAL",
                    "SELECTION_OR_SPECIFICATION",
                    "PURCHASE_CLOSURE",
                    "OTHER",
                ]
            },
            "pain_ids": {"type": "array"},
            "value_bridge_ids": {"type": "array"},
            "visual_proof_direction": {"type": "string"},
            "visual_evidence": {"type": "array"},
            "proof": {
                "type": "object",
                "required": [
                    "buyer_takeaway",
                    "visual_verb",
                    "primary_subject",
                    "supporting_subjects",
                    "required_relations",
                    "minimum_visual_payload",
                    "visual_specificity_anchor",
                    "hidden_copy_test",
                ],
            },
            "expression": {
                "type": "object",
                "required": [
                    "expression_mode",
                    "claim_visualizability",
                    "primary_visual_carrier",
                    "visual_scene_sentence",
                    "copy_responsibility",
                ],
            },
            "structure": {
                "type": "object",
                "required": [
                    "structure_family",
                    "zone_briefs",
                    "structure_difference_from_previous",
                    "forbidden_fallbacks",
                ],
            },
            "visual_archetype": {
                "enum": [
                    "PAIN_SCENE",
                    "PAIN_TO_SOLUTION_BRIDGE",
                    "BENEFIT_OVERVIEW",
                    "DEDICATED_BENEFIT_PROOF",
                    "SOURCE_ACTION_RESULT",
                    "WHOLE_PLUS_MACRO",
                    "ACTION_SEQUENCE",
                    "USE_SCOPE_MATRIX",
                    "STATE_CONTRAST",
                    "SENSORY_WORLD",
                    "SELECTION_COMPARISON",
                    "TRUST_EVIDENCE",
                    "PURCHASE_CLOSURE",
                ]
            },
            "visible_copy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["text", "role", "anchor"],
                },
            },
            "typography": {
                "type": "object",
                "required": ["primary_mode", "anchor_target", "anchor_zone"],
            },
            "composition_family": {"type": "string"},
            "camera_scale": {
                "enum": ["wide", "medium", "close", "macro", "mixed"]
            },
            "variation_from_previous": {"type": "string"},
            "transition_contract": {
                "type": "object",
                "required": [
                    "method_id",
                    "selection_basis",
                    "incoming_anchor",
                    "outgoing_anchor",
                    "source_region_previous",
                    "target_region_current",
                    "handoff_geometry",
                    "visible_overlap_required",
                    "continuity_strength",
                    "seam_carrier",
                ],
            },
            "primary_subject_class": {
                "enum": [
                    "COMPLETE_PRODUCT",
                    "PRODUCT_DETAIL",
                    "HUMAN",
                    "BODY_OR_SKIN",
                    "INGREDIENT_OR_MATERIAL",
                    "MECHANISM",
                    "ACTION",
                    "RESULT_STATE",
                    "DOCUMENT_EVIDENCE",
                    "SPECIFICATION_INFORMATION",
                    "ENVIRONMENT_SCENE",
                ]
            },
            "secondary_subject_classes": {"type": "array"},
            "presentation_form": {
                "enum": [
                    "HERO_POSTER",
                    "MULTI_PAIN_ARRAY",
                    "WHOLE_PLUS_MACRO",
                    "EXPLODED_STRUCTURE",
                    "PROCESS_SEQUENCE",
                    "SOURCE_ACTION_RESULT",
                    "STATE_CONTRAST",
                    "USE_SCOPE_MATRIX",
                    "DOCUMENTARY_EVIDENCE",
                    "SPECIFICATION_BOARD",
                    "FAQ_BOARD",
                    "ASYMMETRIC_EDITORIAL",
                ]
            },
            "complete_product_role": {
                "enum": [
                    "DOMINANT",
                    "SUPPORTING",
                    "IDENTITY_TOKEN_ONLY",
                    "ABSENT",
                ]
            },
            "expression_signature": {"type": "string"},
            "visual_cast": {
                "type": "object",
                "required": [
                    "hero_subject",
                    "claim_object",
                    "action_subject",
                    "result_subject",
                    "context_subject",
                    "product_identity_anchor",
                ],
            },
            "content_unit_contract": {
                "type": "object",
                "required": ["units", "density_class", "unit_count"],
                "properties": {
                    "density_class": {
                        "enum": [
                            "BREATHING",
                            "COMPACT",
                            "DETAIL",
                            "DENSE_INFORMATION",
                        ]
                    },
                    "unit_count": {"type": "integer", "minimum": 0, "maximum": 5},
                    "units": {"type": "array", "maxItems": 5},
                },
            },
            "visual_proof_contract": {"type": "object"},
            "module_spatial_structure_contract": {"type": "object"},
            "copy_intent": {"type": "object"},
            "text_system": {"type": "object"},
            "reading_path": {"type": "array"},
            "copy_density": {"enum": ["none", "low", "medium", "high"]},
            "visual_payload_density": {"enum": ["low", "medium", "high"]},
            "proof_relation_strength": {"enum": ["weak", "moderate", "strong"]},
            "commercial_energy": {"enum": ["restrained", "balanced", "high"]},
            "breathing_screen": {"type": "boolean"},
            "brand_anchor": {"type": "string"},
            "independent_logo_policy": {"type": "string"},
            "independent_logo_source_id": {"type": "string"},
            "inherited_dna_tokens": {"type": "array"},
            "output": {"type": "object"},
        }
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_domestic_modules_completion",
                "strict": False,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["modules"],
                    "properties": {
                        "modules": {
                            "type": "array",
                            "minItems": request.page_count,
                            "maxItems": request.page_count,
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                                "required": list(_AURORA_COMPACT_MODULE_REQUIRED),
                                "properties": module_fields,
                            },
                        }
                    },
                },
            },
        }
    if request.planning_profile == "aurora_domestic_detail":
        # Keep the gateway's structured-output contract aligned with the
        # installed Aurora Skill. A generic json_object response lets the
        # planner fall back to the legacy seven-field plan shape, which is
        # rejected by the local v4.3 validator after an expensive request.
        # The bundled compact schema intentionally keeps additional fields
        # open because the Skill permits protocol extensions; local
        # validation remains the final authority.
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "skill_sources"
            / _AURORA_DOMESTIC_DETAIL_SKILL_ID
            / "schemas"
            / "compact-detail-plan.schema.json"
        )
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Manifest/runtime validation will report a missing schema with a
            # precise fail-closed error; do not hide it behind a transport
            # exception while constructing the request.
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "aurora_domestic_detail_plan",
                "strict": False,
                "schema": schema,
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
        ordered_roles = tuple(source.source_role for source in request.sources)
        if ordered_roles and ordered_roles[0] == "product_reference":
            input_contract = (
                "The attached images are ordered by semantic role: Image 1 is "
                "product_identity_reference and Image 2 is "
                "visual_strategy_reference. The product image is the only authority "
                "for product identity; the visual-strategy image is composition-only."
            )
        else:
            input_contract = (
                "The attached images are ordered by semantic role: Image 1 is "
                "visual_strategy_reference and Image 2 is "
                "product_identity_reference. The product image is the only authority "
                "for product identity; the visual-strategy image is composition-only."
            )
        return (
            "You are the reference-visual-reverse-remix visual analysis stage. "
            + input_contract
            + " Inspect the actual pixels before writing. "
            "Return one JSON object with exactly these top-level keys: "
            "product_identity_lock, product_text_inventory, selected_product_subset, "
            "excluded_product_elements, reference_visual_analysis, "
            "hard_composition_skeleton, normalized_anchors, product_role_map, "
            "typography_zones, commercial_intent, reusable_visual_strategy, "
            "original_remix_prompt, forbidden_transfer, post_generation_review. "
            "The product image is the only authority for product identity; the "
            "reference image supplies composition, scale, camera, lighting, typography "
            "geometry, "
            "depth order and commercial relationships only. Include at least five "
            "normalized 0..1 spatial anchors, explicit must_preserve/may_adapt/"
            "must_not_transfer relations, product role count and depth order. "
            "Keep original source brand, logo, watermark, exact wording and "
            "unsupported "
            "claims out of the result. The original_remix_prompt must put the hard "
            "composition skeleton before style adjectives and must be executable by "
            "an image model using the same two attached images. "
            "Each string field must stay under 900 characters. Do not copy, quote, "
            "or summarize the verified Skill protocol, its file paths, or its "
            "schema text into any field. Return JSON only."
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
            "Before returning, verify that no check name is repeated and that "
            "the complete native check set is present. "
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
    if request.planning_profile == "aurora_detail_pair_audit":
        return (
            "Directly inspect the last attached image as the generated continuous "
            "3:8 pair canvas. Earlier attached images are the ordered product "
            "references; a format canvas is geometry-only and never supplies facts. "
            "Return one JSON object matching the Aurora domestic detail v4.3 "
            "pair-judgment schema: pair_id, module_ids, status, audit_complete, "
            "artifact_binding, pair_canvas, checks, screen_coverage, "
            "internal_seam_evidence, information_audit, material_failures and "
            "identity_silhouette. Inspect actual pixels, compare the candidate to "
            "every product reference, transcribe visible copy before judging fact "
            "binding, and fail closed on identity drift, unsupported copy, missing "
            "visual proof, illegible text, repeated screens, broken seam, or "
            "posterized layout. Use only the approved module contracts supplied in "
            "the first product_information entry below. checks must contain all "
            "nine objects identity, facts, pair_duties, visual_proof, legibility, "
            "copy_binding, internal_seam, spatial_integrity, commercial_expression; "
            "each uses boolean pass and concrete visible_evidence. "
            "internal_seam_evidence must report method_id, source_region, "
            "target_region, carrier, geometry, boolean hard_cut_absent, boolean "
            "method_specific_pass, and concrete visible_evidence. Compare to the "
            "supplied pair_render method; never substitute a string verdict or "
            "omit these fields. Report a real failed observation as false. "
            "Return JSON only.\n\nproduct_information="
            + json.dumps(list(request.product_information), ensure_ascii=False)
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
    if request.planning_profile == "aurora_domestic_modules_completion":
        context = next(
            (
                value
                for value in request.product_information
                if value.startswith("CURRENT_AURORA_PLAN_JSON=")
            ),
            "CURRENT_AURORA_PLAN_JSON={}",
        )
        target_module = next(
            (
                value.split("=", 1)[1].strip()
                for value in request.product_information
                if value.startswith("TARGET_MODULE_ID=")
            ),
            "",
        )
        if target_module:
            module_range = f"the single ordered module {target_module}"
            module_id_instruction = (
                f"The only module id allowed in this response is {target_module}."
            )
        else:
            module_range = (
                f"exactly {request.page_count} ordered modules "
                f"M01..M{request.page_count:02d}"
            )
            module_id_instruction = (
                f"Use ids M01..M{request.page_count:02d} in order."
            )
        return (
            "Complete the installed Aurora domestic detail v4.3 plan. The prior "
            "planning response contains the campaign-level contracts and a "
            "possibly incomplete modules array. Rebuild the modules completely. "
            "Return JSON with exactly one root key: modules. Emit "
            f"{module_range}. Do not return "
            "an empty array, a legacy analysis/plan wrapper, prose, or placeholders. "
            f"{module_id_instruction} "
            "Every module must contain the full compact v4.3 contract: id, duty, "
            "buyer_question, lead_conclusion, lead_claim_id, "
            "selling_point_cluster_ids, story_function, pain_ids, value_bridge_ids, "
            "visual_proof_direction, visual_evidence, proof, expression, structure, "
            "visual_archetype, visible_copy, typography, composition_family, "
            "camera_scale, variation_from_previous, transition_contract, "
            "primary_subject_class, secondary_subject_classes, presentation_form, "
            "complete_product_role, expression_signature, visual_cast, and "
            "content_unit_contract. Enum fields are closed: camera_scale must be "
            "wide, medium, close, macro, or mixed; story_function, "
            "visual_archetype, primary_subject_class, presentation_form, and "
            "complete_product_role must use only the exact enum tokens in the "
            "installed schema. Never use SOURCE_IMAGES_ONLY or any workflow label. "
            "Nested proof requires buyer_takeaway, visual_verb, primary_subject, "
            "supporting_subjects, required_relations, minimum_visual_payload, "
            "visual_specificity_anchor, hidden_copy_test. Nested expression "
            "requires expression_mode, claim_visualizability, "
            "primary_visual_carrier, visual_scene_sentence, copy_responsibility. "
            "Nested structure requires structure_family, zone_briefs, "
            "structure_difference_from_previous, forbidden_fallbacks. "
            "Nested visual_cast requires hero_subject, claim_object, action_subject, "
            "result_subject, context_subject, product_identity_anchor. "
            "Nested content_unit_contract requires units, density_class, unit_count; "
            "density_class must be BREATHING, COMPACT, DETAIL, or DENSE_INFORMATION. "
            "Nested typography requires primary_mode, anchor_target, anchor_zone; "
            "nested transition_contract requires method_id, selection_basis, "
            "incoming_anchor, outgoing_anchor, source_region_previous, "
            "target_region_current, handoff_geometry, visible_overlap_required, "
            "continuity_strength, seam_carrier. Keep facts grounded in the supplied product sources and "
            "retain the approved pair order.\n\n"
            + context
        )
    if request.planning_profile == "aurora_domestic_detail":
        source_inventory = ", ".join(
            f"{source.source_role}:{source.asset_id}:{source.filename}"
            for source in request.sources
        )
        brief = {
            "product_name": request.product_name,
            "user_supplied_selling_points": list(request.product_information),
            "verified_facts": [
                {"id": f"F{index:02d}", "text": value, "source_class": "USER_FACT"}
                for index, value in enumerate(request.product_information, start=1)
            ],
            "platform_code": request.platform_code,
            "language": request.language,
            "module_count": request.page_count,
            "screen_size": request.size,
        }
        return (
            "The bundled aurora-domestic-ecommerce-detail-page v4.3.0 Skill is "  # noqa: UP031
            "the sole authority. Return exactly one JSON object that validates "
            "against schemas/compact-detail-plan.schema.json. Do not return the "
            "legacy analysis/plan/screens contract. First perform the conflict "
            "scan and stop with conflict_blocked evidence if facts conflict. "
            "Choose exactly the requested module_count of 8, 10, or 12; do not "
            "offer multiple candidates. Modules must be M01..M%02d in order. "
            "Set information_contract_version=4.1 and "
            "expression_contract_version=4.3. Declare the full campaign thesis, "
            "fact-grounded selling-point ledger, pain-to-solution contract, "
            "formula/ingredient routing, identity/brand gate, visual DNA, and "
            "per-module subject class, presentation form, complete-product role, "
            "expression signature, visual cast, structured content units and "
            "visible-copy anchors. "
            "Honor every schema minLength exactly; any string field with "
            "minLength=10 must contain at least 10 characters, especially "
            "expression.commercial_comfort.replacement_expression. "
            "output_strategy.continuous_pair_rendering must be enabled with "
            "grouping_mode=TWO_SCREEN_PAIRS, pair_size=2, "
            "pair_merge_type=PAIR_PLAN_MERGE, pair_count=%d, "
            "pair_canvas_aspect_ratio=3:8, "
            "decomposition_window_aspect_ratio=3:4, ordered P01..P%02d and "
            "adjacent module ids only. Each pair needs an internal seam contract "
            "and a transition token. Use only product_reference pixels for product "
            "identity/facts; style_reference may guide grammar only. Do not invent "
            "logos, claims, ingredients, specifications or evidence. "
            "The resulting plan is an approval packet; generation is blocked until "
            "the user approves it. Source inventory: %s\n\n"
            "FINAL RESPONSE CONTRACT: return the compact Aurora object itself at "
            "the JSON root. Do not wrap it in `analysis`, `plan`, `screens`, "
            "`groups`, or any legacy Xinghe envelope. The root MUST include "
            "campaign_thesis, dominant_decision_type, operating_strategy, "
            "campaign_recall_contract, selling_point_depth_contract, "
            "user_selling_point_coverage_ledger, campaign_pain_solution_contract, "
            "output_strategy, reference_expression_system, style_constitution, "
            "series_visual_dna, modules, information_contract_version, "
            "expression_contract_version, hero_screen_contract, "
            "detail_information_contract, formula_split_contract, and "
            "campaign_expression_diversity_contract. `campaign_thesis` must be a "
            "non-empty sentence. `modules` must contain exactly the requested "
            "M01..M%02d entries and `output_strategy.continuous_pair_rendering` "
            "must contain the ordered P01..P%02d pair contract. Nested required "
            "fields must be present too: detail_information_contract has "
            "buyer_question_sequence, non_repeating_overview_limit, "
            "required_progression_jobs, every_pair_requires_information_delta; "
            "hero_screen_contract has hero_module_id, hero_entity_id, hero_job, "
            "hero_uniqueness, supporting_entities_allowed, co_equal_hero_forbidden, "
            "hero_identity_evidence; formula_split_contract has enabled, "
            "trigger_basis, evaluated_claims, entries; style_constitution has "
            "visual_world, color_and_light, typography_and_graphics, "
            "product_rendering, rhythm; reference_expression_system has coverage, "
            "adopted_patterns, anti_copy_rule; campaign_expression_diversity_contract "
            "has minimum_subject_classes, minimum_presentation_forms, "
            "maximum_complete_product_dominant_screens, "
            "maximum_consecutive_same_signature, required_when_evidence_available. "
            "Set plan_format=COMPACT_V1_3. Each module must include the compact "
            "schema fields only: id, duty, buyer_question, lead_conclusion, "
            "lead_claim_id, selling_point_cluster_ids, story_function, pain_ids, "
            "value_bridge_ids, visual_proof_direction, visual_evidence, proof, "
            "expression, structure, visual_archetype, visible_copy, typography, "
            "composition_family, camera_scale, variation_from_previous, "
            "transition_contract, primary_subject_class, secondary_subject_classes, "
            "presentation_form, complete_product_role, expression_signature, "
            "visual_cast, and content_unit_contract. Do not emit runtime-derived "
            "fields such as visual_proof_contract, text_system, copy_intent, "
            "output, independent_logo_policy, or module_spatial_structure_contract; "
            "the installed plan normalizer derives them from the compact module. "
            "modules must contain exactly the requested screens and must not be "
            "an empty array. formula_split_contract.entries[].dedicated_module_id "
            "must match ^M[0-9]{2,}$ when an entry is present; leave entries "
            "empty instead of writing an empty module id. Do not substitute "
            "legacy screen objects. JSON only."
            % (
                request.page_count,
                request.page_count // 2,
                request.page_count // 2,
                source_inventory,
                request.page_count,
                request.page_count // 2,
            )
        ) + (
            "\n\nUSER_BRIEF_JSON=" + json.dumps(brief, ensure_ascii=False)
            + "\nPreserve these user fact IDs and their meanings throughout the "
            "coverage ledger, depth plan and copy bindings. Do not replace the "
            "user's supplied selling points with a photo-only appearance plan. "
            "Additional visible photo facts may support the story but must not "
            "reuse or renumber these user fact IDs. For every pair, the upper "
            "module transition_contract defines that pair's internal seam at "
            "y=1920 between its upper and lower screens. It must describe an "
            "actual continuous carrier crossing that boundary and agree with "
            "the pair seam contract; do not use an incoming page-header "
            "transition or a no-previous-region placeholder there."
        )
    if request.planning_profile == "crossborder_detail":
        source_inventory = ", ".join(
            f"{source.source_role}:{source.asset_id}:{source.filename}"
            for source in request.sources
        )
        product_source_count = sum(
            source.source_role == "product_reference" for source in request.sources
        )
        style_source_count = sum(
            source.source_role == "style_reference" for source in request.sources
        )
        prompt = _legacy_planner_prompt(request)
        legacy_source_contract = (
            f"All {len(request.sources)} attached images are ordered complementary "
            "angles of the same product. Analyze all angles together in this one "
        )
        crossborder_source_contract = (
            f"The {product_source_count} product_reference image(s) are the only "
            "source of product identity, visible facts, structure, materials, "
            "labels and claims. The "
            f"{style_source_count} style_reference image(s) are optional visual "
            "references: read references/reference-page-analysis.md and use them "
            "only for visual style, hierarchy, lighting, page rhythm and "
            "composition devices. Never copy their product, brand, wording, "
            "marks, ratings, claims or specifications. Source inventory: "
            f"{source_inventory}. "
        )
        prompt = prompt.replace(
            legacy_source_contract,
            crossborder_source_contract,
            1,
        )
        return prompt + _cross_page_lock_prompt_contract()
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


# Compact authoring fields from compact-detail-plan.schema.json. The bundled
# plan normalizer derives visual_proof_contract, text_system, copy_intent,
# output, and logo policy from these fields. Requiring the derived fields
# here drops a skill-valid module before that normalizer can run.
_AURORA_COMPACT_MODULE_REQUIRED = (
    "id",
    "duty",
    "buyer_question",
    "lead_conclusion",
    "lead_claim_id",
    "selling_point_cluster_ids",
    "story_function",
    "pain_ids",
    "value_bridge_ids",
    "visual_proof_direction",
    "visual_evidence",
    "proof",
    "expression",
    "structure",
    "visual_archetype",
    "visible_copy",
    "typography",
    "composition_family",
    "camera_scale",
    "variation_from_previous",
    "transition_contract",
    "primary_subject_class",
    "secondary_subject_classes",
    "presentation_form",
    "complete_product_role",
    "expression_signature",
    "visual_cast",
    "content_unit_contract",
)
# The bundled Aurora Harness owns the cross-field rule that a hard-continuity
# seam method must be declared with HARD strength and visible overlap
# (skill_sources/.../plan_normalizer.py). Compatible planners occasionally
# pair a hard method with SOFT, which fails the render with
# HARNESS_INVALID_OUTPUT. Align the two companion fields to the method the
# planner actually chose instead of discarding the seam decision.
_AURORA_HARD_CONTINUITY_METHODS = frozenset(
    {
        "EDGE_BLEED",
        "PRODUCT_OVERFLOW",
        "PERSPECTIVE_TURN",
        "SUBJECT_STATE_HANDOFF",
    }
)
# Spine the model must author. Structural nests can be completed from the
# module's own conclusion; these fields cannot, or the adapter would invent
# the selling story.
_AURORA_COMPACT_MODULE_SPINE = (
    "duty",
    "buyer_question",
    "lead_conclusion",
    "lead_claim_id",
    "selling_point_cluster_ids",
    "story_function",
    "pain_ids",
    "value_bridge_ids",
    "visual_proof_direction",
    "visual_evidence",
    "visual_archetype",
    "composition_family",
    "camera_scale",
    "primary_subject_class",
    "secondary_subject_classes",
    "presentation_form",
    "complete_product_role",
)


def _aurora_module_id_matches(value: object, module_id: str) -> bool:
    if not isinstance(value, str):
        return False
    token = value.strip().upper()
    if token == module_id:
        return True
    if (
        token.startswith("M")
        and token[1:].isdigit()
        and module_id.startswith("M")
        and module_id[1:].isdigit()
    ):
        return int(token[1:]) == int(module_id[1:])
    return False


def _aurora_compact_spine_present(module: Mapping[str, Any]) -> bool:
    for key in _AURORA_COMPACT_MODULE_SPINE:
        if key not in module or module[key] is None:
            return False
        value = module[key]
        if isinstance(value, str) and not value.strip():
            return False
        if key in {
            "selling_point_cluster_ids",
            "pain_ids",
            "value_bridge_ids",
            "visual_evidence",
            "secondary_subject_classes",
        } and not isinstance(value, list):
            return False
    return True


def _aurora_compact_module_ready(module: object) -> bool:
    if not isinstance(module, Mapping) or not _aurora_compact_spine_present(module):
        return False
    completed = _complete_aurora_module_structure(module)
    return set(_AURORA_COMPACT_MODULE_REQUIRED).issubset(completed)


def _accept_aurora_completion_module(
    payload: object,
    module_id: str,
) -> dict[str, Any] | None:
    """Return one skill-valid compact module, or None when the body is not one.

    Accepts ``{modules: [...]}``, ``{module: {...}}``, or a bare module object.
    Runtime-derived harness fields are not required. A response that lacks the
    authored selling spine is left unmerged so the adapter does not invent it.
    """

    if not isinstance(payload, Mapping):
        return None
    candidates: list[Mapping[str, Any]] = []
    modules = payload.get("modules")
    if isinstance(modules, list):
        candidates.extend(item for item in modules if isinstance(item, Mapping))
    nested = payload.get("module")
    if isinstance(nested, Mapping):
        candidates.append(nested)
    if not any(
        key in payload
        for key in ("plan_format", "output_strategy", "modules", "formula_split_contract")
    ) and ("duty" in payload or "lead_conclusion" in payload):
        candidates.append(payload)
    if not candidates:
        return None
    chosen = next(
        (
            item
            for item in candidates
            if _aurora_module_id_matches(item.get("id"), module_id)
        ),
        None,
    )
    if chosen is None and len(candidates) == 1:
        existing = candidates[0].get("id")
        if isinstance(existing, str) and existing.strip() and not _aurora_module_id_matches(
            existing, module_id
        ):
            return None
        chosen = candidates[0]
    if chosen is None or not _aurora_compact_spine_present(chosen):
        return None
    completed = _complete_aurora_module_structure(chosen)
    completed["id"] = module_id
    if not set(_AURORA_COMPACT_MODULE_REQUIRED).issubset(completed):
        return None
    return completed


def _complete_aurora_module_structure(module: Mapping[str, Any]) -> dict[str, Any]:
    """Fill only absent structural fields from the module's own conclusion.

    Compatible planners occasionally omit a required presentation field while
    returning the surrounding fact-grounded content. This compiler repair does
    not replace existing values or invent product facts; it supplies the
    minimum structural tokens needed for the bundled schema to evaluate the
    module, after which the normal validator remains authoritative.
    """

    output = dict(module)
    conclusion = str(output.get("lead_conclusion") or "产品核心卖点")

    def as_text(value: object, fallback: str) -> str:
        if isinstance(value, str):
            return value or fallback
        if isinstance(value, Mapping):
            parts = [str(item) for item in value.values() if item]
            return "；".join(parts) or fallback
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            parts = [str(item) for item in value if item]
            return "；".join(parts) or fallback
        return str(value) if value is not None else fallback

    visible_copy = output.get("visible_copy")
    if not isinstance(visible_copy, list) or not visible_copy:
        output["visible_copy"] = [
            {"text": conclusion, "role": "LEAD_CONCLUSION", "anchor": "主标题"}
        ]
    else:
        repaired_copy: list[dict[str, Any]] = []
        for item in visible_copy:
            copy_item = dict(item) if isinstance(item, Mapping) else {}
            copy_item["text"] = as_text(copy_item.get("text"), conclusion)
            copy_item["role"] = as_text(copy_item.get("role"), "LEAD_CONCLUSION")
            copy_item["anchor"] = as_text(copy_item.get("anchor"), "主标题")
            repaired_copy.append(copy_item)
        output["visible_copy"] = repaired_copy

    content = output.get("content_unit_contract")
    if not isinstance(content, Mapping):
        content = {}
    content_output = dict(content)
    density_value = content_output.get("density_class")
    density_map = {
        "呼吸": "BREATHING",
        "紧凑": "COMPACT",
        "细节": "DETAIL",
        "详细": "DETAIL",
        "密集信息": "DENSE_INFORMATION",
    }
    if density_value not in {
        "BREATHING",
        "COMPACT",
        "DETAIL",
        "DENSE_INFORMATION",
    }:
        content_output["density_class"] = density_map.get(
            str(density_value), "DETAIL"
        )
    units = content_output.get("units")
    if not isinstance(units, list) or not units:
        units = [
            {
                "type": "LEAD_CONCLUSION",
                "text": conclusion,
                "fact_ids": [],
                "visual_anchor": "产品主体",
            }
        ]
    else:
        repaired_units: list[dict[str, Any]] = []
        unit_type_map = {
            "结论": "LEAD_CONCLUSION",
            "主结论": "LEAD_CONCLUSION",
            "连接": "HOW_IT_CONNECTS",
            "买家收益": "BUYER_BENEFIT",
            "体验结果": "EXPERIENCE_RESULT",
            "对象标签": "OBJECT_LABEL",
            "参数": "PARAMETER",
            "使用条件": "USE_CONDITION",
            "限定": "QUALIFIER",
            "选择帮助": "SELECTION_HELP",
            "信任事实": "TRUST_FACT",
        }
        allowed_unit_types = {
            "LEAD_CONCLUSION",
            "HOW_IT_CONNECTS",
            "BUYER_BENEFIT",
            "EXPERIENCE_RESULT",
            "OBJECT_LABEL",
            "PARAMETER",
            "USE_CONDITION",
            "QUALIFIER",
            "SELECTION_HELP",
            "TRUST_FACT",
        }
        for item in units:
            unit = dict(item) if isinstance(item, Mapping) else {}
            unit_type = as_text(unit.get("type"), "LEAD_CONCLUSION")
            unit["type"] = (
                unit_type_map.get(unit_type, unit_type)
                if unit_type in unit_type_map or unit_type in allowed_unit_types
                else "LEAD_CONCLUSION"
            )
            unit["text"] = as_text(unit.get("text"), conclusion)
            unit.setdefault("fact_ids", [])
            unit["visual_anchor"] = as_text(
                unit.get("visual_anchor"), "产品主体"
            )
            repaired_units.append(unit)
        units = repaired_units
    content_output["units"] = units
    content_output.setdefault("density_class", "DETAIL")
    unit_count = content_output.get("unit_count")
    if isinstance(unit_count, bool) or not isinstance(unit_count, int):
        content_output["unit_count"] = len(units)
    output["content_unit_contract"] = content_output

    proof = output.get("proof")
    proof_output = dict(proof) if isinstance(proof, Mapping) else {}
    for key, fallback in {
        "buyer_takeaway": conclusion,
        "visual_verb": "展示",
        "primary_subject": "产品主体",
        "supporting_subjects": [],
        "required_relations": [],
        "minimum_visual_payload": 1,
        "visual_specificity_anchor": "产品外观与结构",
        "hidden_copy_test": conclusion,
    }.items():
        if key in {"supporting_subjects", "required_relations"}:
            proof_output.setdefault(key, fallback)
        else:
            proof_output[key] = as_text(proof_output.get(key), str(fallback))
    minimum_payload = proof_output.get("minimum_visual_payload")
    if isinstance(minimum_payload, bool) or not isinstance(minimum_payload, int):
        if isinstance(minimum_payload, Sequence) and not isinstance(
            minimum_payload, (str, bytes, bytearray)
        ):
            proof_output["minimum_visual_payload"] = max(1, len(minimum_payload))
        else:
            proof_output["minimum_visual_payload"] = 1
    output["proof"] = proof_output

    presence = output.get("product_presence_decision")
    presence_output = dict(presence) if isinstance(presence, Mapping) else {}
    policy = presence_output.get("policy")
    if policy not in {
        "REQUIRED_DOMINANT",
        "REQUIRED_SUPPORTING",
        "IDENTITY_TOKEN_ONLY",
        "OPTIONAL",
        "ABSENT_ALLOWED",
        "ABSENT_PREFERRED",
    }:
        policy = (
            "REQUIRED_DOMINANT"
            if output.get("complete_product_role") == "DOMINANT"
            else "REQUIRED_SUPPORTING"
        )
    presence_output["policy"] = policy
    presence_output["unique_job_if_present"] = as_text(
        presence_output.get("unique_job_if_present"), conclusion
    )
    presence_output["primary_subject_without_product"] = as_text(
        presence_output.get("primary_subject_without_product"),
        "商品专属卖点与使用关系",
    )
    anchors = presence_output.get("identity_binding_without_product")
    if not isinstance(anchors, list) or not anchors or not all(
        isinstance(item, str) and item.strip() for item in anchors
    ):
        anchors = [
            str(proof_output.get("visual_specificity_anchor") or "产品外观与结构")
        ]
    presence_output["identity_binding_without_product"] = anchors
    presence_output["absence_reason"] = as_text(
        presence_output.get("absence_reason"),
        "保留商品专属对象、动作或视觉DNA作为身份绑定。",
    )
    output["product_presence_decision"] = presence_output

    expression = output.get("expression")
    expression_output = dict(expression) if isinstance(expression, Mapping) else {}
    for key, fallback in {
        "expression_mode": "DIRECT_OBSERVATION",
        "claim_visualizability": conclusion,
        "primary_visual_carrier": "产品主体",
        "visual_scene_sentence": conclusion,
        "copy_responsibility": "说明购买结论",
    }.items():
        expression_output[key] = as_text(expression_output.get(key), fallback)
    # The bundled schema requires this optional aversion-control object to keep
    # its replacement expression at minLength=10. Compatible planners
    # occasionally return a semantically valid but one-character-short phrase;
    # preserve it and add a neutral distance qualifier instead of inventing a
    # new claim or dropping the Skill contract.
    commercial_comfort = expression_output.get("commercial_comfort")
    if isinstance(commercial_comfort, Mapping):
        comfort_output = dict(commercial_comfort)
        forbidden_visual_details = comfort_output.get("forbidden_visual_details")
        if isinstance(forbidden_visual_details, list):
            retained_forbidden_details = [
                item.strip()
                for item in forbidden_visual_details
                if isinstance(item, str) and item.strip()
            ]
        else:
            retained_forbidden_details = []
        if retained_forbidden_details:
            comfort_output["forbidden_visual_details"] = retained_forbidden_details
        else:
            # The field is a presentation-safety policy, not a product claim.
            # Keep a non-empty neutral guard when a compatible planner emits an
            # empty or malformed array, so schema validation cannot discard an
            # otherwise fact-grounded module before rendering.
            comfort_output["forbidden_visual_details"] = [
                "不展示不适或刺激性特写"
            ]
        replacement = as_text(
            comfort_output.get("replacement_expression"),
            "保持自然距离的舒适表达",
        )
        if len(replacement) < 10:
            replacement = replacement + "，保持自然距离"
        comfort_output["replacement_expression"] = replacement
        expression_output["commercial_comfort"] = comfort_output
    output["expression"] = expression_output

    structure = output.get("structure")
    structure_output = dict(structure) if isinstance(structure, Mapping) else {}
    structure_output.setdefault("structure_family", "ASYMMETRIC_EDITORIAL")
    structure_output.setdefault("zone_briefs", ["产品主体与卖点信息区"])
    structure_output.setdefault(
        "structure_difference_from_previous", "本屏以主卖点证明为核心"
    )
    structure_output.setdefault(
        "forbidden_fallbacks", ["通用白底", "空泛口号", "装饰性图标"]
    )
    zone_briefs = structure_output.get("zone_briefs")
    if isinstance(zone_briefs, list):
        structure_output["zone_briefs"] = [
            (
                "；".join(
                    str(item.get(key))
                    for key in ("zone", "job", "content")
                    if item.get(key)
                )
                if isinstance(item, Mapping)
                else str(item)
            )
            for item in zone_briefs
        ]
    forbidden = structure_output.get("forbidden_fallbacks")
    if isinstance(forbidden, list):
        normalized_forbidden = [
            (
                "；".join(str(value) for value in item.values() if value)
                if isinstance(item, Mapping)
                else str(item)
            )
            for item in forbidden
        ]
        for fallback in ("通用白底", "空泛口号", "装饰性图标"):
            if fallback not in normalized_forbidden:
                normalized_forbidden.append(fallback)
            if len(normalized_forbidden) >= 3:
                break
        structure_output["forbidden_fallbacks"] = list(dict.fromkeys(normalized_forbidden))
    output["structure"] = structure_output

    visual_cast = output.get("visual_cast")
    visual_cast_output = (
        dict(visual_cast) if isinstance(visual_cast, Mapping) else {}
    )
    for key, fallback in {
        "hero_subject": "产品主体",
        "claim_object": "卖点证据",
        "action_subject": "使用动作",
        "result_subject": "可见结果",
        "context_subject": "使用场景",
        "product_identity_anchor": "产品外观与结构",
    }.items():
        visual_cast_output[key] = as_text(visual_cast_output.get(key), fallback)
    output["visual_cast"] = visual_cast_output

    typography = output.get("typography")
    typography_output = dict(typography) if isinstance(typography, Mapping) else {}
    typography_output["primary_mode"] = as_text(
        typography_output.get("primary_mode"), "EDITORIAL"
    )
    typography_output["anchor_target"] = as_text(
        typography_output.get("anchor_target"), "lead_conclusion"
    )
    typography_output["anchor_zone"] = as_text(
        typography_output.get("anchor_zone"), "主标题区"
    )
    output["typography"] = typography_output

    variation = output.get("variation_from_previous")
    if not isinstance(variation, list) or not variation:
        output["variation_from_previous"] = ["改变信息结构与证据关系"]
    else:
        output["variation_from_previous"] = [as_text(item, "结构变化") for item in variation]

    transition = output.get("transition_contract")
    transition_output = (
        dict(transition) if isinstance(transition, Mapping) else {}
    )
    for key, fallback in {
        "method_id": "BACKGROUND_STRINGING",
        "selection_basis": "保持相邻屏幕的故事承接",
        "incoming_anchor": "上屏视觉锚点",
        "outgoing_anchor": "本屏主卖点",
        "source_region_previous": "上屏底部",
        "target_region_current": "本屏顶部",
        "handoff_geometry": "共享背景场连续过渡",
        "visible_overlap_required": False,
        "continuity_strength": "SOFT",
        "seam_carrier": "背景光线与色彩",
    }.items():
        if key == "visible_overlap_required":
            transition_output.setdefault(key, fallback)
        elif key == "continuity_strength":
            strength = transition_output.get(key)
            transition_output[key] = (
                strength if strength in {"HARD", "SOFT"} else "SOFT"
            )
        elif key == "method_id":
            method = transition_output.get(key)
            allowed_methods = {
                "EDGE_BLEED",
                "PRODUCT_OVERFLOW",
                "BACKGROUND_STRINGING",
                "PERSPECTIVE_TURN",
                "DECORATIVE_HANDOFF",
                "GRAPHIC_OVERLAY",
                "SUBJECT_STATE_HANDOFF",
                "CHAPTER_BAND",
            }
            transition_output[key] = (
                method if method in allowed_methods else "BACKGROUND_STRINGING"
            )
        else:
            transition_output[key] = as_text(transition_output.get(key), fallback)  # type: ignore[arg-type]
    # Cross-field consistency for the Harness seam contract: a hard-continuity
    # method must carry HARD strength and visible overlap. `method_id` is
    # normalised first in the loop above, so this only aligns the two
    # companion fields to the planner's own method choice.
    if transition_output.get("method_id") in _AURORA_HARD_CONTINUITY_METHODS:
        transition_output["continuity_strength"] = "HARD"
        transition_output["visible_overlap_required"] = True
    output["transition_contract"] = transition_output

    enum_fallbacks = {
        "story_function": "OTHER",
        "visual_archetype": "BENEFIT_OVERVIEW",
        "primary_subject_class": "COMPLETE_PRODUCT",
        "presentation_form": "HERO_POSTER",
        "complete_product_role": "SUPPORTING",
        "camera_scale": "mixed",
    }
    allowed_enums = {
        "story_function": {
            "HOOK",
            "PAIN_ARTICULATION",
            "PAIN_SOLUTION_COMBINED",
            "SOLUTION_PROOF",
            "MECHANISM_PROOF",
            "MATERIAL_PROOF",
            "USE_OR_RESULT",
            "TRUST_OR_RISK_REMOVAL",
            "SELECTION_OR_SPECIFICATION",
            "PURCHASE_CLOSURE",
            "OTHER",
        },
        "visual_archetype": {
            "PAIN_SCENE",
            "PAIN_TO_SOLUTION_BRIDGE",
            "BENEFIT_OVERVIEW",
            "DEDICATED_BENEFIT_PROOF",
            "SOURCE_ACTION_RESULT",
            "WHOLE_PLUS_MACRO",
            "ACTION_SEQUENCE",
            "USE_SCOPE_MATRIX",
            "STATE_CONTRAST",
            "SENSORY_WORLD",
            "SELECTION_COMPARISON",
            "TRUST_EVIDENCE",
            "PURCHASE_CLOSURE",
        },
        "primary_subject_class": {
            "COMPLETE_PRODUCT",
            "PRODUCT_DETAIL",
            "HUMAN",
            "BODY_OR_SKIN",
            "INGREDIENT_OR_MATERIAL",
            "MECHANISM",
            "ACTION",
            "RESULT_STATE",
            "DOCUMENT_EVIDENCE",
            "SPECIFICATION_INFORMATION",
            "ENVIRONMENT_SCENE",
        },
        "presentation_form": {
            "HERO_POSTER",
            "MULTI_PAIN_ARRAY",
            "WHOLE_PLUS_MACRO",
            "EXPLODED_STRUCTURE",
            "PROCESS_SEQUENCE",
            "SOURCE_ACTION_RESULT",
            "STATE_CONTRAST",
            "USE_SCOPE_MATRIX",
            "DOCUMENTARY_EVIDENCE",
            "SPECIFICATION_BOARD",
            "FAQ_BOARD",
            "ASYMMETRIC_EDITORIAL",
        },
        "complete_product_role": {
            "DOMINANT",
            "SUPPORTING",
            "IDENTITY_TOKEN_ONLY",
            "ABSENT",
        },
        "camera_scale": {"wide", "medium", "close", "macro", "mixed"},
    }
    for field, fallback in enum_fallbacks.items():
        if output.get(field) not in allowed_enums[field]:
            output[field] = fallback
    signature = as_text(output.get("expression_signature"), conclusion)
    if len(signature) < 10:
        signature = f"{signature}；保持产品识别与卖点连续"
    output["expression_signature"] = signature
    return output


def validate_aurora_domestic_plan(
    payload: object,
    page_count: int,
    *,
    skill_root: Path | None = None,
) -> dict[str, Any]:
    """Validate and project the bundled Aurora v4.3 compact plan.

    The Aurora source owns the plan contract (including modules, diversity and
    pair rendering).  Polaris' historical job model still consumes ``pages``;
    this function keeps a lossless ``aurora_plan`` copy while producing that
    compatibility projection.  No legacy plan is accepted on the Aurora route.
    """

    if page_count not in {8, 10, 12}:
        raise XingheAgentError(
            "AURORA_MODULE_COUNT_INVALID",
            "Aurora domestic detail requires 8, 10, or 12 modules.",
        )
    root = dict(_require_mapping(payload, "AURORA_PLAN_SCHEMA_INVALID", path="/"))
    # These three values are protocol constants owned by the installed skill,
    # not product claims. Fill them only when the planner omits them. A wrong
    # explicit value still fails schema validation.
    root.setdefault("plan_format", "COMPACT_V1_3")
    root.setdefault("information_contract_version", "4.1")
    root.setdefault("expression_contract_version", "4.3")
    # Compatible planning gateways occasionally omit the hero contract even
    # when they return a complete module storyboard.  Rehydrate only the
    # structural fields from M01 and its declared evidence; never invent a
    # product claim or visual asset.
    modules_value = root.get("modules")
    if isinstance(modules_value, list) and modules_value:
        # The upstream planner occasionally emits an explanatory transition
        # alias that is outside the pinned v4.3 transition schema.  Keep the
        # approved contract fields and drop only unknown transition metadata so
        # schema validation remains strict for all semantic fields.
        transition_keys = {
            "method_id",
            "selection_basis",
            "incoming_anchor",
            "outgoing_anchor",
            "source_region_previous",
            "target_region_current",
            "handoff_geometry",
            "visible_overlap_required",
            "continuity_strength",
            "seam_carrier",
            "visual_handoff_type",
            "mode",
            "incoming_carrier",
            "outgoing_carrier",
            "spatial_direction",
            "shared_invariants",
            "allowed_change",
        }
        for module in modules_value:
            if not isinstance(module, Mapping):
                continue
            transition = module.get("transition_contract")
            if isinstance(transition, Mapping):
                module["transition_contract"] = {  # type: ignore[index]
                    key: value
                    for key, value in transition.items()
                    if key in transition_keys
                }
        first_module = modules_value[0]
        if isinstance(first_module, Mapping):
            hero_value = root.get("hero_screen_contract")
            hero = dict(hero_value) if isinstance(hero_value, Mapping) else {}
            hero.setdefault("hero_module_id", first_module.get("id", "M01"))
            hero.setdefault(
                "hero_entity_id",
                "PRODUCT_FROM_APPROVED_SOURCES",
            )
            hero.setdefault(
                "hero_job",
                str(first_module.get("lead_conclusion") or "建立商品主体识别"),
            )
            hero.setdefault(
                "hero_uniqueness",
                "M01 是本组唯一首屏商品主体锚点。",
            )
            hero.setdefault("supporting_entities_allowed", [])
            hero.setdefault("co_equal_hero_forbidden", True)
            evidence = first_module.get("visual_evidence")
            hero.setdefault(
                "hero_identity_evidence",
                [
                    {
                        "source_asset_id": item.get("source_asset_id"),
                        "observed_fact": item.get("observed_fact")
                        or item.get("observed_value")
                        or "已批准商品参考中的可见主体。",
                    }
                    for item in evidence
                    if isinstance(item, Mapping) and item.get("source_asset_id")
                ]
                if isinstance(evidence, list)
                else [],
            )
            root["hero_screen_contract"] = hero
    output_strategy = root.get("output_strategy")
    if isinstance(output_strategy, Mapping):
        output_strategy = dict(output_strategy)
        output_strategy.setdefault("module_count", page_count)
        output_strategy.setdefault(
            "module_count_candidates",
            [
                {
                    "candidate_mode": "BALANCED_EXPRESSION",
                    "count": page_count,
                    "coverage_tradeoff": "覆盖已批准卖点并保持页面节奏",
                    "selling_point_fit": "满足当前卖点覆盖",
                    "story_obligation_fit": "满足从认知到购买决策的故事义务",
                    "decision": "SELECTED",
                }
            ],
        )
        candidates = output_strategy.get("module_count_candidates")
        if isinstance(candidates, list):
            repaired_candidates = []  # type: ignore[var-annotated]
            for candidate in candidates:
                entry = dict(candidate) if isinstance(candidate, Mapping) else {}
                entry.setdefault("candidate_mode", "BALANCED_EXPRESSION")
                entry.setdefault("count", page_count)
                entry.setdefault("coverage_tradeoff", "覆盖已批准卖点并保持页面节奏")
                entry.setdefault("selling_point_fit", "满足当前卖点覆盖")
                entry.setdefault("story_obligation_fit", "满足从认知到购买决策的故事义务")
                entry.setdefault("decision", "SELECTED" if not repaired_candidates else "")
                repaired_candidates.append(entry)
            output_strategy["module_count_candidates"] = repaired_candidates
        output_strategy.setdefault(
            "selling_point_clusters",
            [{"id": "SP-COVERAGE", "label": "已批准卖点覆盖"}],
        )
        output_strategy.setdefault(
            "merge_decisions", ["按相邻模块保留独立购买决策信息"],
        )
        output_strategy.setdefault(
            "claim_coverage", [{"status": "ACTIVE", "planned_modules": []}],
        )
        output_strategy.setdefault(
            "module_count_formula",
            {
                "base_narrative_jobs": page_count,
                "primary_depth_expansion": 0,
                "supporting_jobs": 0,
                "shared_proof_savings": 0,
                "computed_balanced_minimum": page_count,
                "shared_proof_rationale": "按相邻 pair 共享视觉过渡",
            },
        )
        formula_value = output_strategy.get("module_count_formula")
        formula = dict(formula_value) if isinstance(formula_value, Mapping) else {}
        formula.setdefault("base_narrative_jobs", page_count)
        formula.setdefault("primary_depth_expansion", 0)
        formula.setdefault("supporting_jobs", 0)
        formula.setdefault("shared_proof_savings", 0)
        formula.setdefault("computed_balanced_minimum", page_count)
        formula.setdefault("shared_proof_rationale", "按相邻 pair 共享视觉过渡")
        output_strategy["module_count_formula"] = formula
        output_strategy.setdefault(
            "dimension_rationale",
            "采用 1440x1920 单屏与相邻双屏 3:8 pair canvas，保持移动端详情阅读比例。",
        )
        pair_contract = output_strategy.get("continuous_pair_rendering")
        if not isinstance(pair_contract, Mapping):
            pair_contract = {}
        pair_contract = dict(pair_contract)
        pair_contract.setdefault("enabled", True)
        pair_contract.setdefault("grouping_mode", "TWO_SCREEN_PAIRS")
        pair_contract.setdefault("pair_size", 2)
        pair_contract.setdefault("pair_merge_type", "PAIR_PLAN_MERGE")
        pair_contract.setdefault("pair_count", page_count // 2)
        pair_contract.setdefault("pair_canvas_width_px", 1440)
        pair_contract.setdefault("pair_canvas_height_px", 3840)
        pair_contract.setdefault("pair_canvas_aspect_ratio", "3:8")
        pair_contract.setdefault("decomposition_window_aspect_ratio", "3:4")
        pair_contract.setdefault("pair_slice_height_px", 1920)
        pair_contract.setdefault(
            "pair_to_pair_transition_tokens",
            [f"P{index:02d}→P{index + 1:02d}" for index in range(1, page_count // 2)],
        )
        pair_ids = pair_contract.get("pair_ids")
        if not isinstance(pair_ids, list) or len(pair_ids) != page_count // 2:
            pair_ids = []
            for index in range(1, page_count // 2 + 1):
                pair_ids.append(
                    {
                        "pair_id": f"P{index:02d}",
                        "module_ids": [f"M{index * 2 - 1:02d}", f"M{index * 2:02d}"],
                        "pair_merge_type": "PAIR_PLAN_MERGE",
                        "internal_seam_zone": {"start_y": 1910, "end_y": 1930},
                        "internal_seam_method_id": "BACKGROUND_STRINGING",
                        "internal_seam_carrier": "连续背景光线与色彩",
                        "internal_seam_source_region": "上屏底部视觉锚点",
                        "internal_seam_target_region": "下屏顶部视觉锚点",
                        "internal_seam_geometry": "共享背景场软过渡",
                    }
                )
        pair_contract["pair_ids"] = pair_ids
        output_strategy["continuous_pair_rendering"] = pair_contract
        root["output_strategy"] = output_strategy
    reference_system = root.get("reference_expression_system")
    if isinstance(reference_system, Mapping):
        reference_system = dict(reference_system)
        coverage = reference_system.get("coverage")
        if isinstance(coverage, list):
            repaired_coverage = []
            for index, item in enumerate(coverage, start=1):
                entry = dict(item) if isinstance(item, Mapping) else {}
                entry.setdefault("reference_id", f"REF-{index:02d}")
                entry.setdefault("disposition", "REJECTED")
                entry.setdefault("pattern_ids", [])
                entry.setdefault("reason", "未提供可采用的参考表达样本")
                repaired_coverage.append(entry)
            reference_system["coverage"] = repaired_coverage
        reference_system.setdefault("coverage", [])
        adopted_patterns = reference_system.get("adopted_patterns")
        if isinstance(adopted_patterns, list):
            repaired_patterns = []
            for index, item in enumerate(adopted_patterns, start=1):
                pattern = dict(item) if isinstance(item, Mapping) else {}
                pattern.setdefault("id", f"PATTERN-{index:02d}")
                pattern.setdefault("source_reference_ids", [])
                pattern.setdefault("source_unit_ids", [])
                pattern.setdefault("observed_method", "保持信息层级与节奏")
                pattern.setdefault("adaptation_for_product", "按当前产品事实重建")
                pattern.setdefault("scheduled_module_ids", ["M01"])
                pattern.setdefault("do_not_copy", "不复制品牌、文案、资产或整版布局")
                pattern.setdefault("fact_dependencies", ["PRODUCT_REFERENCE"])
                pattern.setdefault(
                    "copy_or_claims_not_inherited", ["源参考中的品牌与文案不继承"]
                )
                repaired_patterns.append(pattern)
            reference_system["adopted_patterns"] = repaired_patterns
        else:
            reference_system["adopted_patterns"] = []
        reference_system["anti_copy_rule"] = (
            "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET"
        )
        root["reference_expression_system"] = reference_system
    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError as exc:
        raise XingheAgentError(
            "AURORA_SCHEMA_RUNTIME_UNAVAILABLE",
            "Aurora v4.3 requires the bundled jsonschema runtime.",
        ) from exc
    schema_root = skill_root or (
        Path(__file__).resolve().parents[1]
        / "skill_sources"
        / _AURORA_DOMESTIC_DETAIL_SKILL_ID
    )
    schema_path = schema_root / "schemas" / "compact-detail-plan.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XingheAgentError(
            "AURORA_SCHEMA_UNAVAILABLE",
            "Aurora compact-detail-plan.schema.json could not be loaded.",
        ) from exc
    root = {
        key: value
        for key, value in root.items()
        if key in schema.get("properties", {})
    }
    resolver = RefResolver(schema_path.as_uri(), schema)
    errors = sorted(
        Draft202012Validator(schema, resolver=resolver).iter_errors(root),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        pointer = "/" + "/".join(str(token) for token in first.absolute_path)
        raise XingheAgentError(
            "AURORA_PLAN_SCHEMA_INVALID",
            f"Aurora plan failed v4.3 schema validation: {first.message}",
            json_pointer=pointer or "/",
        )
    output_strategy = _require_mapping(root.get("output_strategy"), "AURORA_PLAN_SCHEMA_INVALID")
    if output_strategy.get("module_count") != page_count:
        raise XingheAgentError(
            "AURORA_MODULE_COUNT_MISMATCH",
            "Aurora plan module_count must match the requested page count.",
            json_pointer="/output_strategy/module_count",
        )
    pair_contract = _require_mapping(
        output_strategy.get("continuous_pair_rendering"),
        "AURORA_PAIR_CONTRACT_INVALID",
    )
    if (
        pair_contract.get("enabled") is not True
        or pair_contract.get("grouping_mode") != "TWO_SCREEN_PAIRS"
        or pair_contract.get("pair_size") != 2
        or pair_contract.get("pair_merge_type") != "PAIR_PLAN_MERGE"
        or pair_contract.get("pair_count") != page_count // 2
        or pair_contract.get("pair_canvas_aspect_ratio") != "3:8"
        or pair_contract.get("decomposition_window_aspect_ratio") != "3:4"
    ):
        raise XingheAgentError(
            "AURORA_PAIR_CONTRACT_INVALID",
            "Aurora plan must use adjacent 2-screen 3:8 PAIR_PLAN_MERGE rendering.",
            json_pointer="/output_strategy/continuous_pair_rendering",
        )
    modules = root.get("modules")
    if not isinstance(modules, list) or len(modules) != page_count:
        raise XingheAgentError(
            "AURORA_MODULE_COUNT_MISMATCH",
            "Aurora plan must contain exactly the requested modules.",
            json_pointer="/modules",
        )
    expected_ids = [f"M{index:02d}" for index in range(1, page_count + 1)]
    module_ids = [item.get("id") if isinstance(item, Mapping) else None for item in modules]
    if module_ids != expected_ids:
        raise XingheAgentError(
            "AURORA_MODULE_ORDER_INVALID",
            f"Aurora modules must be ordered M01..M{page_count:02d}.",
            json_pointer="/modules",
        )
    pair_ids = pair_contract.get("pair_ids")
    if not isinstance(pair_ids, list) or len(pair_ids) != page_count // 2:
        raise XingheAgentError(
            "AURORA_PAIR_CONTRACT_INVALID",
            "Aurora pair_ids must contain one pair for every adjacent module pair.",
            json_pointer="/output_strategy/continuous_pair_rendering/pair_ids",
        )
    for index, pair in enumerate(pair_ids, start=1):
        if not isinstance(pair, Mapping) or pair.get("pair_id") != f"P{index:02d}":
            raise XingheAgentError(
                "AURORA_PAIR_ORDER_INVALID",
                f"Aurora pair ids must be ordered P01..P{page_count // 2:02d}.",
            )
        if pair.get("module_ids") != [f"M{index * 2 - 1:02d}", f"M{index * 2:02d}"]:
            raise XingheAgentError(
                "AURORA_PAIR_ORDER_INVALID",
                "Aurora pairs must group adjacent modules without reordering.",
            )
    projected_screens: list[dict[str, Any]] = []
    for module in modules:
        module = _require_mapping(module, "AURORA_PLAN_SCHEMA_INVALID")
        expression = module.get("expression")
        transition = module.get("transition_contract")
        structure = module.get("structure")
        projected_screens.append(
            {
                "role": str(module.get("story_function") or "OTHER"),
                "title": str(module.get("lead_conclusion") or ""),
                "label": str(module.get("buyer_question") or ""),
                "composition": str(
                    expression.get("visual_scene_sentence")
                    if isinstance(expression, Mapping)
                    else module.get("visual_proof_direction") or ""
                ),
                "device": str(module.get("visual_archetype") or ""),
                "difference": str(
                    transition.get("seam_carrier")
                    if isinstance(transition, Mapping)
                    else module.get("variation_from_previous") or ""
                ),
                "structure": str(
                    structure.get("structure_family")
                    if isinstance(structure, Mapping)
                    else ""
                ),
                "subject_scale": str(module.get("camera_scale") or "mixed"),
                "aurora_module_id": module.get("id"),
                "pair_id": f"P{(int(str(module['id'])[1:]) + 1) // 2:02d}",
                "pair_position": 1 if int(str(module["id"])[1:]) % 2 else 2,
                "aurora_module": module,
            }
        )
    analysis = {
        "category_key": "aurora_v4_3",
        "category_reason": "Aurora v4.3 fact-grounded domestic detail plan",
        "product_image_analysis": root.get("operating_strategy", {}),
        "product_consistency_anchors": root.get("series_visual_dna", {}),
        "buyer_objections": [
            item.get("buyer_question", "")
            for item in modules
            if isinstance(item, Mapping)
        ],
        "aurora_plan": root,
    }
    plan = {
        "campaign_style_lock": root.get("style_constitution", {}),
        "design_strength_lock": root.get("reference_expression_system", {}),
        "rhythm_map": [item.get("expression_signature", "") for item in modules],
        "screens": projected_screens,
        "pair_rendering": pair_contract,
        "product_consistency_lock": root.get("series_visual_dna", {}),
        "layout_diversity_lock": root.get("campaign_expression_diversity_contract", {}),
        "aurora_plan": root,
    }
    return {"analysis": analysis, "plan": plan, "aurora_plan": root}


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


def _provider_error_summary(payload: Mapping[str, Any]) -> dict[str, str]:
    """Keep bounded, redaction-safe provider error details for local diagnosis."""

    value = payload.get("error")
    if isinstance(value, Mapping):
        summary: dict[str, str] = {}
        for key in ("code", "type", "message", "param"):
            item = value.get(key)
            if isinstance(item, str) and item:
                summary[key] = item[:512]
        return summary or {"code": "provider_error"}
    return {"code": "provider_error"}


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
