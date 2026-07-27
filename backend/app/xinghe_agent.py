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

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import (
    AssetLifecycleStatus,
    AttemptStatus,
    JobItemStatus,
    JobStatus,
    PlanValidationStatus,
    UsageCompleteness,
)
from .models import (
    AssetRecord,
    AuditEventRecord,
    CreditReservationRecord,
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
from .services import canonical_hash, new_id, settle_credits, transition_job
from .skill_runtime import SkillManifestRegistry, SkillRuntimeError
from .storage import ImageStorage

WORKFLOW_VERSION = "xinghe-bounded-agent-v1"
PLANNING_POLICY_VERSION = "xinghe-structured-plan-v1"
QUALITY_POLICY_VERSION = "xinghe-semantic-quality-v1"
PROMPT_POLICY_VERSION = "xinghe-density-v1"
RESUME_SIGNATURE_VERSION = "xinghe-resume-v1"
PLAN_SCHEMA_VERSION = "xinghe-plan-v1"
IMAGE_SIZE = "1024x1536"
IMAGE_FORMAT = "jpeg"
JPEG_QUALITY = 92
DEFAULT_MEDIUM_PRICE_MICROS = 45_000
DEFAULT_HIGH_PRICE_MICROS = 90_000
DEFAULT_BUDGET_LIMIT_MICROS = 200_000_000
MAX_PAGE_RETRIES = 2
PLANNER_LEASE_SECONDS = 900

_PLANNER_JSON_FENCE = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n"
    r"(?P<body>.*?)\r?\n```[ \t]*\Z",
    re.IGNORECASE | re.DOTALL,
)
_HIGH_ROLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"封面",
        r"结构",
        r"细节",
        r"特写",
        r"材质",
        r"表面",
        r"工艺",
        r"纹理",
        r"微距",
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


class XingheAgentError(RuntimeError):
    """Controlled, redaction-safe Agent failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class SourceImage:
    asset_id: str
    group_key: str
    filename: str
    content_type: str
    sha256: str
    payload: bytes


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
    idempotency_key: str


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
    size: str = IMAGE_SIZE
    output_format: str = IMAGE_FORMAT
    jpeg_quality: int = JPEG_QUALITY


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


class XingheGateway(Protocol):
    provider_name: str
    planner_model: str
    image_model: str
    pricing_version: str
    external_network_request_count: int

    async def plan(self, request: PlannerRequest) -> PlannerCallResult: ...

    async def edit(self, request: ImageEditRequest) -> ImageCallResult: ...


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
    """Route semantic role text without relying on an exact role-name enum."""

    return (
        "high"
        if any(pattern.search(role) for pattern in _HIGH_ROLE_PATTERNS)
        else "medium"
    )


def cost_range(
    page_count: int,
    group_count: int,
    medium_price_micros: int,
    high_price_micros: int,
) -> tuple[int, int]:
    total_pages = page_count * group_count
    return (
        total_pages * min(medium_price_micros, high_price_micros),
        total_pages * max(medium_price_micros, high_price_micros),
    )


def build_resume_signature(
    *,
    groups: Sequence[tuple[str, Sequence[tuple[str, str]]]],
    base_url: str,
    planner_model: str,
    image_model: str,
    page_count: int,
    language: str,
    product_name: str,
    product_information: Sequence[str],
    platform_code: str,
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
                    {"filename": filename, "sha256": sha256}
                    for filename, sha256 in sources
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
        "size": IMAGE_SIZE,
        "output_format": IMAGE_FORMAT,
        "jpeg_quality": JPEG_QUALITY,
        "medium_price_micros": medium_price_micros,
        "high_price_micros": high_price_micros,
    }
    return canonical_hash(payload)


def validate_planner_payload(payload: object, page_count: int) -> dict[str, Any]:
    """Validate the mandatory structured plan and exact screen count."""

    root = _require_mapping(payload, "PLANNER_SCHEMA_INVALID")
    analysis = _require_mapping(
        root.get("analysis"),
        "PLANNER_SCHEMA_INVALID",
    )
    plan = _require_mapping(root.get("plan"), "PLANNER_SCHEMA_INVALID")
    for key in (
        "category_key",
        "category_reason",
    ):
        _require_nonempty_string(analysis.get(key), key)
    for key in (
        "product_image_analysis",
        "product_consistency_anchors",
    ):
        _require_mapping(analysis.get(key), "PLANNER_SCHEMA_INVALID")
    objections = analysis.get("buyer_objections")
    if not isinstance(objections, list) or not objections:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner buyer objections must be a non-empty array.",
        )
    campaign_lock = plan.get("campaign_style_lock")
    design_lock = plan.get("design_strength_lock")
    if not isinstance(campaign_lock, (str, dict)) or not campaign_lock:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner campaign style lock is invalid.",
        )
    if not isinstance(design_lock, (str, dict)) or not design_lock:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner design strength lock is invalid.",
        )
    screens = plan.get("screens")
    if not isinstance(screens, list):
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner screens must be an array.",
        )
    if len(screens) != page_count:
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            "Planner returned a different number of screens than requested.",
        )
    normalized_screens: list[dict[str, str]] = []
    for screen in screens:
        screen_mapping = _require_mapping(screen, "PLANNER_SCHEMA_INVALID")
        normalized = {
            key: _require_nonempty_string(screen_mapping.get(key), key)
            for key in (
                "role",
                "title",
                "label",
                "composition",
                "device",
                "difference",
            )
        }
        normalized_screens.append(normalized)
    return {
        "analysis": {
            "category_key": str(analysis["category_key"]),
            "category_reason": str(analysis["category_reason"]),
            "product_image_analysis": dict(analysis["product_image_analysis"]),
            "product_consistency_anchors": dict(
                analysis["product_consistency_anchors"]
            ),
            "buyer_objections": list(objections),
        },
        "plan": {
            "campaign_style_lock": campaign_lock,
            "design_strength_lock": design_lock,
            "screens": normalized_screens,
        },
    }


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
    supplied = "; ".join(product_information) or "visible image facts only"
    return (
        "vertical 3:4 e-commerce detail page image\n"
        f"Page {page_number}/{page_count}. Create one independent page, not a "
        "collage or multi-panel composition.\n"
        f"All {source_count} ordered reference images are complementary angles "
        "of the same product. Reconcile them into one consistent identity; "
        "mark visible conflicts needs_confirmation.\n"
        f"Product: {product_name}. User-provided information: {supplied}.\n"
        f"Product Consistency Anchors: {anchors}\n"
        f"Visible-fact boundary: {facts}\n"
        f"Campaign Style Lock: {campaign_lock}\n"
        f"Design Strength Lock: {design_lock}\n"
        f"Role: {screen['role']}\n"
        f"Main title ({language}): {screen['title']}\n"
        f"One short label ({language}): {screen['label']}\n"
        f"One visual hero and composition: {screen['composition']}\n"
        f"Visual device: {screen['device']}\n"
        f"Difference from adjacent pages: {screen['difference']}\n"
        "One core selling point only. Exactly one main title and one short "
        "label. At most one zoom window and at most two structural callouts. "
        "No repeated local window, no repeated display of the same part, no "
        "multi-panel collage, and no multiple crop windows. Use only supplied "
        "information and visible facts. Do not invent functions, parameters, "
        "materials, certifications, efficacy, sales, reviews, tests, rankings, "
        "comfort, durability, or authenticity claims. Treat visible source "
        "watermarks as source marks, never as product branding or page copy."
    )


class FakeXingheGateway:
    """Deterministic no-network gateway with bounded fault injection."""

    provider_name = "mock"
    planner_model = "gpt-5.6-terra-fake"
    image_model = "gpt-image-2-fake"
    pricing_version = "xinghe-fake-zero-v1"

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
                group_token = hashlib.sha256(
                    request.group_key.encode()
                ).hexdigest()[:10]
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
            payload = _fake_jpeg(request.page_number)
            artifact = _artifact_from_bytes(
                payload,
                filename=f"{request.group_key}-page-{request.page_number:03d}.jpg",
            )
            group_token = hashlib.sha256(
                request.group_key.encode()
            ).hexdigest()[:10]
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
        if medium_price_micros < 0 or high_price_micros < 0:
            raise ValueError("Configured unit prices cannot be negative.")
        self._api_key = api_key.strip()
        self.base_url = base_url.rstrip("/") + "/"
        self.planner_model = planner_model.strip()
        self.image_model = image_model.strip()
        self.medium_price_micros = medium_price_micros
        self.high_price_micros = high_price_micros
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
        for source in request.sources:
            encoded = base64.b64encode(source.payload).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{source.content_type};base64,{encoded}"
                    },
                }
            )
        payload = {
            "model": self.planner_model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        }
        try:
            self.external_network_request_count += 1
            status, response = await self.transport.post_json(
                url=urljoin(self.base_url, "v1/chat/completions"),
                headers=self._headers(request.idempotency_key),
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            if status >= 400:
                return PlannerCallResult(
                    payload=None,
                    provider_request_id=_safe_request_id(response),
                    raw_usage=_raw_usage(response),
                    normalized_usage=normalize_usage(_raw_usage(response)),
                    api_latency_seconds=time.perf_counter() - started,
                    actual_cost_micros=_usage_cost_micros(
                        _raw_usage(response)
                    ),
                    error_code=(
                        "PLANNER_RATE_LIMITED"
                        if status == 429
                        else "PLANNER_REQUEST_FAILED"
                    ),
                    error_message=f"Planner request failed with HTTP {status}.",
                    http_status=status,
                )
            text = _planner_message_text(response)
            plan_payload = _planner_content_payload(text)
            raw_usage = _raw_usage(response)
            return PlannerCallResult(
                payload=plan_payload,
                provider_request_id=_safe_request_id(response),
                raw_usage=raw_usage,
                normalized_usage=normalize_usage(raw_usage),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=_usage_cost_micros(raw_usage),
                http_status=status,
            )
        except XingheAgentError as exc:
            return PlannerCallResult(
                payload=None,
                provider_request_id=None,
                raw_usage=None,
                normalized_usage=normalize_usage(None),
                api_latency_seconds=time.perf_counter() - started,
                actual_cost_micros=None,
                error_code=exc.code,
                error_message=str(exc),
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
            ("output_compression", str(request.jpeg_quality)),
            ("response_format", "b64_json"),
        ]
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
                        "IMAGE_RATE_LIMITED"
                        if rate_limited
                        else "IMAGE_REQUEST_FAILED"
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

    async def plan(self, job_id: str) -> JobStatus | None:
        reserved = self._reserve(job_id)
        if isinstance(reserved, JobStatus) or reserved is None:
            return reserved
        plan_id, requests = reserved
        try:
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
                    error_message=(
                        "Planner provider failed "
                        f"({type(exc).__name__})."
                    ),
                )
            results.append(result)
            if result.error_code is not None:
                return self._fail_planning(
                    job_id,
                    plan_id,
                    result.error_code,
                    result.error_message or "Planner request failed.",
                    results,
                )
            try:
                validated.append(
                    validate_planner_payload(result.payload, request.page_count)
                )
            except XingheAgentError as exc:
                return self._fail_planning(
                    job_id,
                    plan_id,
                    exc.code,
                    str(exc),
                    results,
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
                )
            )
        return PlannerRequest(
            workspace_id=request.workspace_id,
            job_id=request.job_id,
            group_key=request.group_key,
            sources=tuple(loaded),
            page_count=request.page_count,
            language=request.language,
            product_name=request.product_name,
            product_information=request.product_information,
            platform_code=request.platform_code,
            idempotency_key=request.idempotency_key,
        )

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
        groups = input_configuration.get("product_groups")
        if not isinstance(groups, list) or not groups:
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "At least one product group is required.",
            )
        page_count = _strict_page_count(settings.get("page_count"))
        product_name = _require_nonempty_string(
            settings.get("product_name"),
            "product_name",
        )
        language = _require_nonempty_string(settings.get("language"), "language")
        platform_code = _require_nonempty_string(
            settings.get("platform_code"),
            "platform_code",
        )
        selling_points_value = settings.get("selling_points", [])
        if not isinstance(selling_points_value, list) or not all(
            isinstance(value, str) for value in selling_points_value
        ):
            raise XingheAgentError(
                "AGENT_CONFIGURATION_INVALID",
                "Product information must be an array of strings.",
            )
        requests: list[PlannerRequest] = []
        signature_groups: list[tuple[str, Sequence[tuple[str, str]]]] = []
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
            for asset_id_value in asset_ids:
                if not isinstance(asset_id_value, str):
                    raise XingheAgentError(
                        "AGENT_CONFIGURATION_INVALID",
                        "Product source asset identifiers must be strings.",
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
                    )
                )
            source_tuple = tuple(sources)
            source_groups.append((group_key, source_tuple))
            signature_groups.append(
                (
                    group_key,
                    tuple(
                        (source.filename, source.sha256) for source in source_tuple
                    ),
                )
            )
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
                    idempotency_key=(
                        f"{job.id}:planner:{group_index}:{signature}"
                    ),
                )
            )
        return tuple(requests)

    def _authorize_planning(
        self,
        session: Session,
        job: JobRecord,
        requests: tuple[PlannerRequest, ...],
    ) -> None:
        registry = SkillManifestRegistry.bundled()
        registry.verify_source("xinghe-ecommerce-detail", self.skill_root)
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
    ) -> None:
        planner_usage = [_planner_usage_record(result) for result in results]
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
            "planner_request_count": len(results),
            "image_request_count": 0,
        }
        plan.payload = failed_payload
        plan.payload_hash = canonical_hash(failed_payload)
        plan.validation_status = PlanValidationStatus.INVALID.value
        plan.validation_errors = [
            {"code": error_code, "message": error_message}
        ]
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
            sum(known_costs)
            if results and len(known_costs) == len(results)
            else None
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
            group_plans: list[dict[str, Any]] = []
            flattened_pages: list[dict[str, Any]] = []
            item_configurations: list[dict[str, Any]] = []
            all_signature_groups = [
                (
                    request.group_key,
                    tuple(
                        (source.filename, source.sha256)
                        for source in request.sources
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
                                }
                                for source in request.sources
                            ],
                            "size": IMAGE_SIZE,
                            "output_format": IMAGE_FORMAT,
                            "jpeg_quality": JPEG_QUALITY,
                        }
                    )
                group_plans.append(
                    {
                        "group_key": request.group_key,
                        "analysis": structured["analysis"],
                        "campaign_style_lock": structured["plan"][
                            "campaign_style_lock"
                        ],
                        "design_strength_lock": structured["plan"][
                            "design_strength_lock"
                        ],
                        "pages": pages,
                        "planner_usage": _planner_usage_record(
                            results[group_index - 1]
                        ),
                        "planning_time": results[
                            group_index - 1
                        ].api_latency_seconds,
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
            high_count = sum(
                item["quality"] == "high" for item in item_configurations
            )
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
                    "planner": [
                        _planner_usage_record(result) for result in results
                    ],
                    "image": {
                        "reported_requests": 0,
                        "unreported_requests": 0,
                    },
                },
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
                        not result.normalized_usage["reported"]
                        for result in results
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
    ) -> None:
        if max_concurrency not in {1, 2, 6}:
            raise ValueError("Xinghe concurrency must be one of 1, 2, or 6.")
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.skill_root = skill_root
        self.max_concurrency = max_concurrency
        self.budget_limit_micros = budget_limit_micros
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
        )
        async with self._semaphore:
            try:
                self._reserve_call_budget(
                    request,
                    configuration,
                    source_count=len(sources),
                )
            except XingheAgentError as exc:
                return _provider_rejection(exc.code, str(exc), self.gateway)
            except Exception as exc:
                return _provider_rejection(
                    "AUDIT_WRITE_FAILED",
                    (
                        "Image budget reservation audit failed "
                        f"({type(exc).__name__})."
                    ),
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
                            "Image provider failed "
                            f"({type(exc).__name__})."
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
            "xinghe-ecommerce-detail",
            self.skill_root,
        )
        item_configuration = _require_mapping(
            request.configuration.get("item"),
            "AGENT_CONFIGURATION_INVALID",
        )
        _validate_item_configuration(item_configuration)
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
                    )
                )
            return dict(item_configuration), tuple(sources)

    def _reserve_call_budget(
        self,
        request: ProviderRequest,
        configuration: Mapping[str, Any],
        *,
        source_count: int,
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
            cumulative_exposure = (
                planner_cost + prior_exposure + current_exposure
            )
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
                        AssetRecord.id.in_(
                            [source.asset_id for source in sources]
                        ),
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
                        "usage_reported": bool(
                            result.normalized_usage["reported"]
                        ),
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
    ) -> None:
        self.default_provider = default_provider
        self.detail_provider = detail_provider

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if request.operation == "detail_pack":
            return await self.detail_provider.execute(request)
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

    if job.type != "detail_pack":
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
    output_plan_signature = canonical_hash(
        {
            "version": RESUME_SIGNATURE_VERSION,
            "input_signature": payload["input_signature"],
            "groups": [
                {
                    "group_key": group.get("group_key"),
                    "analysis": group.get("analysis"),
                    "campaign_style_lock": group.get("campaign_style_lock"),
                    "design_strength_lock": group.get("design_strength_lock"),
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
        structured = {
            "analysis": group.get("analysis"),
            "plan": {
                "campaign_style_lock": group.get("campaign_style_lock"),
                "design_strength_lock": group.get("design_strength_lock"),
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
                    screen=page,
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

    if job.type != "detail_pack":
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
        (max(finishes) - min(starts)).total_seconds()
        if starts and finishes
        else None
    )
    completed_pages = successes
    throughput_pages_per_second = (
        completed_pages / image_wall_time
        if completed_pages > 0
        and image_wall_time is not None
        and image_wall_time > 0
        else 0.0
    )
    payload = dict(plan.payload)
    previous_metrics = payload.get("metrics")
    metrics = (
        dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
    )
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
            "usage_missing_count": missing_usage
            + _planner_usage_missing(payload),
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
        request_id = value.get("provider_request_id")
        real_calls += int(
            isinstance(request_id, str) and not request_id.startswith("mock_")
        )
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


def _validate_item_configuration(configuration: Mapping[str, Any]) -> None:
    expected_versions = {
        "workflow_version": WORKFLOW_VERSION,
        "planning_policy_version": PLANNING_POLICY_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "resume_signature_version": RESUME_SIGNATURE_VERSION,
        "size": IMAGE_SIZE,
        "output_format": IMAGE_FORMAT,
        "jpeg_quality": JPEG_QUALITY,
    }
    for key, expected in expected_versions.items():
        if configuration.get(key) != expected:
            raise XingheAgentError(
                "RESUME_SIGNATURE_INVALID",
                "An output-affecting Agent policy or format changed.",
            )
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
        "provider_request_id": result.provider_request_id,
        "api_latency_seconds": result.api_latency_seconds,
        "http_status": result.http_status,
        "actual_cost_micros": result.actual_cost_micros,
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
            "buyer_objections": [
                "What is visibly distinctive?",
                "How does the structure look from multiple angles?",
            ],
        },
        "plan": {
            "campaign_style_lock": "Consistent restrained product campaign.",
            "design_strength_lock": (
                "Use varied scale and composition without repeated templates."
            ),
            "screens": [
                {
                    "role": roles[index % len(roles)],
                    "title": f"{request.product_name} {index + 1}",
                    "label": f"Visible focus {index + 1}",
                    "composition": "One dominant visual hero.",
                    "device": "A restrained information accent.",
                    "difference": "Distinct scale and rhythm from adjacent pages.",
                }
                for index in range(request.page_count)
            ],
        },
    }


def _fake_jpeg(page_number: int) -> bytes:
    buffer = BytesIO()
    color = (
        (page_number * 53) % 256,
        (page_number * 97) % 256,
        (page_number * 149) % 256,
    )
    Image.new("RGB", (24, 32), color=color).save(
        buffer,
        format="JPEG",
        quality=JPEG_QUALITY,
    )
    return buffer.getvalue()


def _artifact_from_bytes(payload: bytes, *, filename: str) -> ProviderArtifact:
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise XingheAgentError(
            "IMAGE_RESPONSE_INVALID",
            "Provider returned an invalid image.",
        ) from exc
    if image_format != "JPEG":
        raise XingheAgentError(
            "IMAGE_RESPONSE_FORMAT_INVALID",
            "Provider did not return the requested JPEG format.",
        )
    if width * 4 != height * 3:
        raise XingheAgentError(
            "IMAGE_RESPONSE_ASPECT_INVALID",
            "Provider returned a non-3:4 image.",
        )
    return ProviderArtifact(
        payload=payload,
        filename=filename,
        content_type="image/jpeg",
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _planner_prompt(request: PlannerRequest) -> str:
    return (
        f"Return exactly one JSON object for product group {request.group_key!r}. "
        f"All {len(request.sources)} attached images are ordered complementary "
        "angles of the same product. Analyze all angles together in this one "
        f"planning call and return exactly {request.page_count} screens in "
        f"{request.language}. Use only visible facts and this user information: "
        f"product={request.product_name!r}; points="
        f"{list(request.product_information)!r}; platform="
        f"{request.platform_code!r}. Treat visible watermarks as source marks, "
        "not branding or selling points. Uncertain content must be marked "
        "needs_confirmation. Required object: analysis.category_key, "
        "analysis.category_reason, analysis.product_image_analysis, "
        "analysis.product_consistency_anchors, analysis.buyer_objections, "
        "plan.campaign_style_lock, plan.design_strength_lock, and plan.screens. "
        "Every screen requires role, title, label, composition, device, and "
        "difference. Each page has one core selling point, one visual hero, one "
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
        )
    choice = _require_mapping(choices[0], "PLANNER_RESPONSE_INVALID")
    message = _require_mapping(choice.get("message"), "PLANNER_RESPONSE_INVALID")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise XingheAgentError(
            "PLANNER_RESPONSE_INVALID",
            "Planner response has no JSON content.",
        )
    return content


def _planner_content_payload(content: str) -> object:
    """Decode only a full JSON value or one complete, unambiguous JSON fence.

    Outer whitespace is stripped. A fence may be untagged or use a
    case-insensitive ``json`` tag, followed by spaces/tabs and LF or CRLF.
    Nothing except spaces/tabs may follow the closing fence before outer
    whitespace is stripped.
    """

    stripped = content.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = _PLANNER_JSON_FENCE.fullmatch(stripped)
        if match is None:
            return content
    try:
        return json.loads(match.group("body"))
    except json.JSONDecodeError:
        return content


def _image_bytes(payload: Mapping[str, Any]) -> bytes:
    data = payload.get("data")
    item: Mapping[str, Any] = payload
    if isinstance(data, list) and data:
        item = _require_mapping(data[0], "IMAGE_RESPONSE_INVALID")
    encoded = (
        item.get("b64_json")
        or item.get("base64")
        or item.get("image_base64")
    )
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
    return value.replace("\\", "_").replace('"', "_").replace("\r", "_").replace(
        "\n",
        "_",
    )


def _strict_page_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
        raise XingheAgentError(
            "AGENT_CONFIGURATION_INVALID",
            "Page count must be an integer from 1 through 12.",
        )
    return value


def _require_mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise XingheAgentError(code, "Expected a JSON object.")
    return dict(value)


def _require_nonempty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise XingheAgentError(
            "PLANNER_SCHEMA_INVALID",
            f"Required text field {field_name!r} is missing.",
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
