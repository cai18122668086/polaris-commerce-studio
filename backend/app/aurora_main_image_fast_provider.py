"""Six independent main-image canvases with durable paid-call fences.

This provider validates identity bindings and files. It deliberately does not
claim to have performed a visual review or generate aesthetic repair requests.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import suppress
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select

from . import aurora_main_image_authored as authored
from .aurora_main_image_planner import PAGE_ROLES
from .errors import ApiError
from .generation_image_stage import GenerationImageStage, staged_or_stored
from .models import JobAttemptRecord, JobItemRecord, JobPlanRecord, JobRecord, utc_now
from .new_detail_skill_provider import BundledSkillManifestValidator
from .provider import ProviderArtifact, ProviderOutcome, ProviderRequest, ProviderResult
from .provider_diagnostics import retained_metrics
from .services import canonical_hash, get_ready_assets
from .storage import (
    STORAGE_PENDING_MESSAGE,
    STORAGE_RESULT_PENDING,
    ValidatedImage,
    require_image_storage_write,
)
from .xinghe_agent import ImageEditRequest, SourceImage, XingheGateway

logger = logging.getLogger(__name__)

NATIVE_VERSION = "aurora-main-image-native-fast-v1"
NATIVE_SCHEMA_VERSION = "aurora-main-image-native-fast-plan-v1"
NATIVE_SKILL_ID = "aurora-domestic-ecommerce-main-image-native-fast"
VERSION = NATIVE_VERSION
SCHEMA_VERSION = NATIVE_SCHEMA_VERSION
SKILL_ID = NATIVE_SKILL_ID
RECEIPTS_KEY = "_main_image_fast_invocations"
_GENERATION_KEYS = (
    "version",
    "skill_id",
    "skill_content_hash",
    "source_bindings",
    "product_asset_ids",
    "product_identity_lock",
    "confirmed_facts",
    "user_facts",
    "style_lock",
    "pages",
    "canvas",
)


def generation_hash(plan: dict[str, Any]) -> str:
    """Keep frozen generation independent from confirmation and retry metrics."""
    return canonical_hash({key: plan[key] for key in _GENERATION_KEYS})


def image_prompt(plan: dict[str, Any], page: dict[str, Any]) -> str:
    prompt = page.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ApiError(
            409, "FAST_MAIN_IMAGE_PLAN_CHANGED", "原生快速主图提示词不完整。"
        )
    return prompt


class FastMainImageProvider:
    def __init__(
        self,
        session_factory: Any,
        gateway: XingheGateway,
        storage: Any,
        *,
        stage_root: Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway
        self.storage = storage
        self.stage = (
            GenerationImageStage(stage_root, "main-image") if stage_root else None
        )
        self.name = getattr(gateway, "provider_name", "main-image-fast")
        self.model = getattr(gateway, "image_model", "none")
        self.pricing_version = getattr(gateway, "pricing_version", VERSION)

    def _load(
        self, request: ProviderRequest
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id)
            item = session.get(JobItemRecord, request.job_item_id)
            attempt = session.get(JobAttemptRecord, request.attempt_id)
            speed = (
                job.configuration.get("settings", {}).get("main_image_speed")
                if job is not None
                else None
            )
            if (
                request.operation != "domestic_main_image"
                or job is None
                or item is None
                or attempt is None
                or job.type != request.operation
                or job.workspace_id != request.workspace_id
                or item.workspace_id != request.workspace_id
                or item.job_id != job.id
                or attempt.workspace_id != request.workspace_id
                or attempt.job_id != job.id
                or attempt.job_item_id != item.id
                or attempt.status != "running"
                or attempt.provider_idempotency_key != request.idempotency_key
                or job.status != "processing"
                or speed != "native_fast"
            ):
                raise ApiError(
                    409,
                    "FAST_MAIN_IMAGE_SCOPE_INVALID",
                    "快速主图任务归属或执行状态无效。",
                )
            row = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job.id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
            )
            authored_plan = (
                row is not None and row.schema_version == authored.SCHEMA_VERSION
            )
            version, schema_version, skill_id = (
                (authored.VERSION, authored.SCHEMA_VERSION, authored.REFERENCE_ID)
                if authored_plan
                else (NATIVE_VERSION, NATIVE_SCHEMA_VERSION, NATIVE_SKILL_ID)
            )
            if (
                row is None
                or row.workspace_id != request.workspace_id
                or row.schema_version != schema_version
                or row.validation_status != "valid"
                or row.confirmed_at is None
                or row.payload_hash != canonical_hash(row.payload)
            ):
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_PLAN_CHANGED", "快速主图方案未确认或已变化。"
                )
            plan = dict(row.payload)
            if (
                plan.get("version") != version
                or plan.get("skill_id") != skill_id
                or len(plan.get("pages", [])) != 6
                or [p.get("page_index") for p in plan["pages"]] != list(range(6))
                or [p.get("page_role") for p in plan["pages"]] != list(PAGE_ROLES)
                or not 0 <= item.ordinal < 6
                or plan.get("canvas") != [1024, 1024]
                or plan.get("product_asset_ids")
                != job.configuration.get("input", {}).get("product_asset_ids")
            ):
                raise ApiError(
                    409,
                    "FAST_MAIN_IMAGE_PLAN_CHANGED",
                    "快速主图六图职责或素材绑定已变化。",
                )
            if speed == "native_fast":
                if not (
                    isinstance(plan.get("product_identity_lock"), dict)
                    and plan["product_identity_lock"]
                    and isinstance(plan.get("style_lock"), dict)
                    and plan["style_lock"]
                ):
                    raise ApiError(
                        409, "FAST_MAIN_IMAGE_PLAN_CHANGED", "原生身份或风格锁不完整。"
                    )
                for page in plan["pages"]:
                    source_ids = page.get("source_asset_ids")
                    if (
                        not isinstance(page.get("prompt"), str)
                        or not page["prompt"].strip()
                        or not isinstance(source_ids, list)
                        or not source_ids
                        or any(not isinstance(key, str) for key in source_ids)
                        or len(set(source_ids)) != len(source_ids)
                        or not set(source_ids).issubset(plan["product_asset_ids"])
                    ):
                        raise ApiError(
                            409,
                            "FAST_MAIN_IMAGE_SOURCE_CHANGED",
                            "原生快速主图提示词或逐页来源绑定无效。",
                        )
            if (
                authored.reference_bundle()[1]
                if authored_plan
                else BundledSkillManifestValidator().validate(skill_id)
            ) != plan["skill_content_hash"]:
                raise ApiError(
                    409,
                    "FAST_MAIN_IMAGE_SKILL_CHANGED",
                    "快速主图 Skill 已变化，请重新规划。",
                )
            assets = get_ready_assets(
                session, request.workspace_id, plan["product_asset_ids"]
            )
            records = {
                key: (
                    a.original_filename,
                    a.content_type,
                    a.sha256,
                    a.object_key,
                    a.width,
                    a.height,
                )
                for key, a in assets.items()
            }
            bindings = [
                {
                    "asset_id": key,
                    "sha256": records[key][2],
                    "width": records[key][4],
                    "height": records[key][5],
                }
                for key in plan["product_asset_ids"]
            ]
            if bindings != plan["source_bindings"]:
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_SOURCE_CHANGED", "快速主图原始素材已变化。"
                )
            return plan, plan["pages"][item.ordinal], records

    @staticmethod
    def _ancestor_ids(session: Any, job: JobRecord) -> set[str]:
        ancestors = {job.id}
        current = job
        while current.retry_of_job_id:
            if current.retry_of_job_id in ancestors:
                raise ApiError(409, "FAST_MAIN_IMAGE_SCOPE_INVALID", "重试任务链无效。")
            parent = session.get(JobRecord, current.retry_of_job_id)
            if (
                parent is None
                or parent.workspace_id != job.workspace_id
                or parent.type != job.type
            ):
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_SCOPE_INVALID", "重试任务归属无效。"
                )
            ancestors.add(parent.id)
            current = parent
        return ancestors

    def _claim(
        self,
        plan: dict[str, Any],
        page: dict[str, Any],
        request: ProviderRequest,
        *,
        skip_rejected_cache: bool = False,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id, with_for_update=True)
            attempt = session.get(JobAttemptRecord, request.attempt_id)
            if (
                job is None
                or job.status != "processing"
                or attempt is None
                or attempt.status != "running"
            ):
                raise ApiError(409, "FAST_MAIN_IMAGE_SCOPE_INVALID", "任务已中止。")
            row = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job.id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
            )
            if (
                row is None
                or canonical_hash(row.payload) != row.payload_hash
                or generation_hash(row.payload) != generation_hash(plan)
            ):
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_PLAN_CHANGED", "快速主图方案已变化。"
                )
            receipts = dict(job.configuration.get(RECEIPTS_KEY, {}))
            key = str(page["page_index"])
            old = receipts.get(key, {})
            if old and (
                old.get("plan_hash") != generation_hash(plan)
                or old.get("job_id") not in self._ancestor_ids(session, job)
            ):
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_PLAN_CHANGED", "已有图片不属于当前冻结方案。"
                )
            if (
                old.get("state") in {"invoked", "unknown", "abandoned_unknown"}
                and self.stage is not None
                and old.get("attempt_id")
            ):
                # Same receipt, same page: a worker that died after the image
                # arrived leaves it in the local stage. Recover it without a
                # new provider call.
                found = self.stage.path(
                    request.workspace_id, old["job_id"], old["attempt_id"]
                )
                if found.is_file():
                    data = self.stage.read(
                        found, self.storage.validator.max_upload_bytes
                    )
                    image = _prepared_image(
                        data,
                        f"{request.workspace_id}/main-image-fast/"
                        f"{old['job_id']}/{key}/",
                    )
                    old = {
                        **old,
                        "state": "storage_pending",
                        "object_key": image.object_key,
                        "sha256": image.sha256,
                        "recovered_from": "local_stage",
                    }
                    receipts[key] = old
                    job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
                    session.commit()
            if old.get("state") in {"returned", "storage_pending"} or (
                old.get("state") == "rejected"
                and old.get("object_key")
                and not skip_rejected_cache
            ):
                prefix = (
                    f"{request.workspace_id}/main-image-fast/{old['job_id']}/{key}/"
                )
                if not old.get("object_key", "").startswith(prefix):
                    raise ApiError(
                        409, "FAST_MAIN_IMAGE_SCOPE_INVALID", "已有图片归属无效。"
                    )
                return old
            # An explicit rejection in this same job may be called again by a
            # later automatic attempt (never by the attempt that saw it, and
            # never for an unconfirmed result).
            same_job_retry = bool(
                old
                and old.get("state") == "rejected"
                and old.get("job_id") == job.id
                and old.get("attempt_id") != request.attempt_id
            )
            # A user-confirmed redo (abandoned_unknown) may call again, but
            # only from the new job and only after the local lookup above.
            if (
                old
                and not same_job_retry
                and (
                    old.get("state") not in {"rejected", "abandoned_unknown"}
                    or old.get("job_id") == job.id
                )
            ):
                raise ApiError(
                    409,
                    "PROVIDER_OUTCOME_UNKNOWN",
                    "原生图结果尚未核实，已停止重复提交。",
                )
            retry_no = int(old.get("retry_no") or 0) + 1 if same_job_retry else 0
            receipts[key] = {
                "state": "invoked",
                "job_id": job.id,
                "attempt_id": request.attempt_id,
                "plan_hash": generation_hash(plan),
                "page_index": page["page_index"],
                "prompt_hash": hashlib.sha256(
                    image_prompt(plan, page).encode()
                ).hexdigest(),
                "started_at": utc_now().isoformat(),
                "retry_no": retry_no,
            }
            job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
            session.commit()
            return {"_invoke": True, "retry_no": retry_no}

    def _finish(
        self, page: dict[str, Any], request: ProviderRequest, receipt: dict[str, Any]
    ) -> None:
        with self.session_factory() as session:
            job = session.get(JobRecord, request.job_id, with_for_update=True)
            receipts = dict(job.configuration.get(RECEIPTS_KEY, {}))
            key = str(page["page_index"])
            old = receipts.get(key, {})
            if old.get("attempt_id") != request.attempt_id or old.get("state") not in {
                "invoked",
                "storage_pending",
            }:
                raise ApiError(
                    409, "FAST_MAIN_IMAGE_SCOPE_INVALID", "生图回执已被接续。"
                )
            receipts[key] = {**old, **receipt, "finished_at": utc_now().isoformat()}
            job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
            session.commit()

    @staticmethod
    def _artifact(
        data: bytes,
        canvas: list[int],
        *,
        strict_square: bool = True,
        normalize: bool = False,
    ) -> ProviderArtifact:
        with Image.open(BytesIO(data)) as image:
            image.load()
            w, h, fmt = *image.size, image.format
            if (
                normalize
                and fmt in {"PNG", "JPEG", "WEBP"}
                and (w != h or min(w, h) < canvas[0])
                and min(w, h) >= 768
                and 0.8 <= w / h <= 1.25
            ):
                # Loosened: a near-square or slightly small result is centre
                # cropped to square and fitted to the canvas, not rejected.
                side = min(w, h)
                left, top = (w - side) // 2, (h - side) // 2
                fitted = image.convert("RGB").crop((left, top, left + side, top + side))
                if side < canvas[0]:
                    fitted = fitted.resize(
                        (canvas[0], canvas[1]), Image.Resampling.LANCZOS
                    )
                buffer = BytesIO()
                fitted.save(buffer, format="PNG")
                data = buffer.getvalue()
                w, h, fmt = *fitted.size, "PNG"
        # Main images are square; keep the native 1024 minimum rather than
        # applying the replica channel's alternative elongated-image threshold.
        if (
            fmt not in {"PNG", "JPEG", "WEBP"}
            or min(w, h) < 1024
            or (strict_square and w != h)
            or abs((w / h) / (canvas[0] / canvas[1]) - 1) > 0.01
        ):
            raise ApiError(
                502,
                "FAST_MAIN_IMAGE_CANVAS_INVALID",
                "主图原始画幅未达要求，已保留结果。",
            )
        suffix, content_type = {
            "PNG": ("png", "image/png"),
            "JPEG": ("jpg", "image/jpeg"),
            "WEBP": ("webp", "image/webp"),
        }[fmt]
        return ProviderArtifact(
            payload=data,
            filename="main-image-fast." + suffix,
            content_type=content_type,
            width=w,
            height=h,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        return replace(
            await self._execute(request),
            provider_name=self.name,
            model_name=self.model,
            pricing_version=self.pricing_version,
        )

    async def _execute(self, request: ProviderRequest) -> ProviderResult:
        invoked = False
        result = None
        artifact: ProviderArtifact | None = None
        pending = False
        try:
            plan, page, records = self._load(request)
            sources = []
            source_ids = page["source_asset_ids"]
            for key in source_ids:
                record = records[key]
                data = await self.storage.read_bytes(record[3])
                if hashlib.sha256(data).hexdigest() != record[2]:
                    raise ApiError(
                        409, "FAST_MAIN_IMAGE_SOURCE_CHANGED", "商品原图校验不一致。"
                    )
                sources.append(
                    SourceImage(
                        asset_id=key,
                        group_key=f"main-image-{page['page_index']}",
                        filename=record[0],
                        content_type=record[1],
                        sha256=record[2],
                        payload=data,
                        source_role="product_reference",
                    )
                )
            await require_image_storage_write(self.storage)
            if self.stage:
                self.stage.require_writable(self.storage.validator.max_upload_bytes)
            cached = self._claim(plan, page, request)
            while cached and not cached.get("_invoke"):
                stage_path = (
                    self.stage.path(
                        request.workspace_id, cached["job_id"], cached["attempt_id"]
                    )
                    if self.stage and cached["state"] == "storage_pending"
                    else None
                )
                try:
                    data, staged = await staged_or_stored(
                        self.storage,
                        self.stage,
                        stage_path,
                        cached["object_key"],
                        cached["sha256"],
                    )
                except ValueError as error:
                    raise ApiError(
                        409, "FAST_MAIN_IMAGE_RESULT_CHANGED", "已生成图片校验不一致。"
                    ) from error
                if staged:
                    assert self.stage and stage_path
                    try:
                        await self.storage.save_validated(
                            _prepared_image(data, cached["object_key"])
                        )
                    except Exception as error:
                        raise ApiError(
                            503, STORAGE_RESULT_PENDING, STORAGE_PENDING_MESSAGE
                        ) from error
                    self.stage.discard(stage_path)
                try:
                    artifact = self._artifact(
                        data,
                        plan["canvas"],
                        strict_square=True,
                        normalize=plan.get("version") == authored.VERSION,
                    )
                except ApiError:
                    if cached.get("state") != "rejected":
                        raise
                    cached = self._claim(plan, page, request, skip_rejected_cache=True)
                else:
                    return ProviderResult(
                        outcome=ProviderOutcome.SUCCEEDED,
                        artifact=artifact,
                        usage_reported=True,
                        actual_cost_micros=0,
                        estimated_cost_micros=0,
                        raw_usage={
                            "network_requests": 0,
                            "reused": True,
                            "review_status": "NOT_REVIEWED",
                            "technical_status": "STRUCTURALLY_VALIDATED",
                        },
                    )
            invoked = True
            result = await self.gateway.edit(
                ImageEditRequest(
                    workspace_id=request.workspace_id,
                    job_id=request.job_id,
                    job_item_id=request.job_item_id,
                    attempt_id=request.attempt_id,
                    page_number=page["page_index"] + 1,
                    group_key=f"main-image-{page['page_index']}",
                    sources=tuple(sources),
                    prompt=image_prompt(plan, page),
                    quality="high",
                    # A retry after an explicit rejection must not replay
                    # the rejected request's cached answer.
                    idempotency_key=request.idempotency_key
                    + (
                        f":retry-{cached['retry_no']}"
                        if cached.get("retry_no")
                        else ""
                    ),
                    size=f"{plan['canvas'][0]}x{plan['canvas'][1]}",
                    output_format="png",
                    preserve_provider_artifact=True,
                    single_dispatch=True,
                )
            )
            usage = {
                **(result.normalized_usage or {}),
                "network_requests": 1,
                "review_status": "NOT_REVIEWED",
                "main_image_speed": "native_fast",
                "planning_rounds": 1,
                "metrics": {
                    **retained_metrics(result.raw_usage),
                    "api_latency_seconds": result.api_latency_seconds,
                    "skill_id": plan["skill_id"],
                    "skill_content_hash": plan["skill_content_hash"],
                    "page_index": page["page_index"],
                },
            }
            if result.outcome != ProviderOutcome.SUCCEEDED or result.artifact is None:
                unknown = result.outcome in {
                    ProviderOutcome.OUTCOME_UNKNOWN,
                    ProviderOutcome.SUCCEEDED,
                } or result.error_code in {
                    "PROVIDER_OUTCOME_UNKNOWN",
                    "IMAGE_RESULT_DOWNLOAD_UNCONFIRMED",
                }
                self._finish(
                    page,
                    request,
                    {
                        "state": "unknown" if unknown else "rejected",
                        "provider_request_id": result.provider_request_id,
                        "usage": usage,
                        "actual_cost_micros": result.actual_cost_micros,
                    },
                )
                return ProviderResult(
                    outcome=ProviderOutcome.OUTCOME_UNKNOWN
                    if unknown
                    else ProviderOutcome.FAILED,
                    error_code="PROVIDER_OUTCOME_UNKNOWN"
                    if unknown
                    else result.error_code or "FAST_MAIN_IMAGE_IMAGE_FAILED",
                    error_message="原生图结果尚未核实，请先核对原任务。"
                    if unknown
                    else "本张主图生成未完成，可重试。",
                    retryable=not unknown,
                    provider_request_id=result.provider_request_id,
                    raw_usage=usage,
                    usage_reported=bool(usage.get("reported")),
                    actual_cost_micros=result.actual_cost_micros,
                    estimated_cost_micros=result.estimated_cost_micros,
                    http_status=result.http_status,
                )
            data = result.artifact.payload
            prefix = (
                f"{request.workspace_id}/main-image-fast/{request.job_id}/"
                f"{page['page_index']}/"
            )
            image = _prepared_image(data, prefix)
            key, sha = image.object_key, image.sha256
            stage_path = (
                self.stage.path(
                    request.workspace_id, request.job_id, request.attempt_id
                )
                if self.stage
                else None
            )
            if self.stage and stage_path:
                self.stage.save(
                    stage_path, image, self.storage.validator.max_upload_bytes
                )
                self._finish(
                    page,
                    request,
                    {
                        "state": "storage_pending",
                        "object_key": key,
                        "sha256": sha,
                        "provider_request_id": result.provider_request_id,
                        "usage": usage,
                        "actual_cost_micros": result.actual_cost_micros,
                    },
                )
                pending = True
            await self.storage.save_validated(image)
            artifact = None
            with suppress(ApiError):
                artifact = self._artifact(
                        data,
                        plan["canvas"],
                        strict_square=True,
                        normalize=plan.get("version") == authored.VERSION,
                    )
            self._finish(
                page,
                request,
                {
                    "state": "returned" if artifact else "rejected",
                    "object_key": key,
                    "sha256": sha,
                    "provider_request_id": result.provider_request_id,
                    "usage": usage,
                    "actual_cost_micros": result.actual_cost_micros,
                },
            )
            if self.stage and stage_path:
                self.stage.discard(stage_path)
            return ProviderResult(
                outcome=ProviderOutcome.SUCCEEDED
                if artifact
                else ProviderOutcome.FAILED,
                artifact=artifact,
                error_code=None if artifact else "FAST_MAIN_IMAGE_CANVAS_INVALID",
                error_message=None
                if artifact
                else "本张主图原始画幅未达要求，结果已保留，可重试。",
                retryable=artifact is None,
                provider_request_id=result.provider_request_id,
                raw_usage={
                    **usage,
                    "technical_status": "STRUCTURALLY_VALIDATED"
                    if artifact
                    else "INVALID",
                },
                usage_reported=bool(usage.get("reported")),
                actual_cost_micros=result.actual_cost_micros,
                estimated_cost_micros=result.estimated_cost_micros,
                http_status=result.http_status,
            )
        except Exception as error:
            logger.warning(
                "Fast main image interrupted: job=%s type=%s code=%s",
                request.job_id,
                type(error).__name__,
                getattr(error, "code", None),
                exc_info=True,
            )
            unknown = (
                invoked
                and not pending
                and (result is None or result.outcome != ProviderOutcome.FAILED)
            )
            return ProviderResult(
                outcome=ProviderOutcome.OUTCOME_UNKNOWN
                if unknown
                else ProviderOutcome.FAILED,
                error_code=(
                    STORAGE_RESULT_PENDING
                    if pending
                    else "PROVIDER_OUTCOME_UNKNOWN"
                    if unknown
                    else getattr(error, "code", "FAST_MAIN_IMAGE_EXECUTION_FAILED")
                ),
                error_message=(
                    STORAGE_PENDING_MESSAGE
                    if pending
                    else "原生图结果尚未核实，已停止重复提交。"
                    if unknown
                    else str(error)
                    if isinstance(error, ApiError)
                    else "快速主图未完成，请核对任务后重试。"
                ),
                provider_request_id=getattr(result, "provider_request_id", None),
                usage_reported=bool(result and result.normalized_usage.get("reported")),
                actual_cost_micros=getattr(result, "actual_cost_micros", None)
                if invoked
                else 0,
                estimated_cost_micros=getattr(result, "estimated_cost_micros", None)
                if invoked
                else 0,
                raw_usage={
                    **(getattr(result, "normalized_usage", None) or {}),
                    "network_requests": 1 if invoked else 0,
                    "review_status": "NOT_REVIEWED",
                },
            )


def _prepared_image(data: bytes, key: str) -> ValidatedImage:
    with Image.open(BytesIO(data)) as image:
        image.load()
        width, height = image.size
        fmt = image.format or ""
        content_type = Image.MIME[fmt]
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[fmt]
    sha = hashlib.sha256(data).hexdigest()
    if key.endswith("/"):
        key += sha + suffix
    return ValidatedImage(
        payload=data,
        filename="generated-main-image" + suffix,
        content_type=content_type,
        width=width,
        height=height,
        object_key=key,
        sha256=sha,
    )
