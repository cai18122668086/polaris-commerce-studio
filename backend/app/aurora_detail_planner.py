"""Planning coordinator for the native Aurora detail-page Skill."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .aurora_detail_runtime import (
    AURORA_DETAIL_SKILL_ID,
    AuroraDetailRuntimeError,
)
from .aurora_detail_service import (
    AuroraDetailServiceError,
    AuroraDetailSessionService,
)
from .domain import JobStatus
from .models import (
    AssetRecord,
    AuroraDetailSessionRecord,
    JobAssetRecord,
    JobRecord,
)
from .storage import ImageStorage
from .xinghe_agent import (
    PlannerRequest,
    SourceImage,
    XingheGateway,
    load_planner_system_prompt,
)


class AuroraPlanningError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AuroraPlanningContext:
    workspace_id: str
    job_id: str
    product_name: str
    category: str
    target_buyer: str
    primary_scenario: str
    platform_code: str
    product_facts: tuple[str, ...]
    output_preferences: str
    sources: tuple[SourceImage, ...]
    stable_paths: Mapping[str, str]
    existing_session: Mapping[str, Any] | None
    revision: int


class AuroraPlanningBundleProvider(Protocol):
    async def plan(self, context: AuroraPlanningContext) -> Mapping[str, Any]: ...


class GatewayAuroraPlanningBundleProvider:
    """Use the approved vision planner; construction itself makes no request."""

    def __init__(self, gateway: XingheGateway, skill_root: Path) -> None:
        self.gateway = gateway
        self.skill_root = skill_root

    async def plan(self, context: AuroraPlanningContext) -> Mapping[str, Any]:
        information = {
            "category": context.category,
            "target_buyer": context.target_buyer,
            "primary_scenario": context.primary_scenario,
            "product_facts": list(context.product_facts),
            "output_preferences": context.output_preferences,
            "stable_asset_paths": dict(context.stable_paths),
            "resolved_session": context.existing_session,
        }
        request = PlannerRequest(
            workspace_id=context.workspace_id,
            job_id=context.job_id,
            group_key="primary-product",
            sources=context.sources,
            page_count=0,
            language="zh-CN",
            product_name=context.product_name,
            product_information=(
                json.dumps(information, ensure_ascii=False, separators=(",", ":")),
            ),
            platform_code=context.platform_code,
            size="ADAPTIVE",
            idempotency_key=(f"{context.job_id}:aurora-plan-v070:{context.revision}"),
            system_prompt=load_planner_system_prompt(
                self.skill_root, AURORA_DETAIL_SKILL_ID
            ),
            domestic_protocol=True,
            planning_profile="aurora_detail_v070",
        )
        result = await self.gateway.plan(request)
        if result.error_code is not None:
            raise AuroraPlanningError(
                result.error_code,
                result.error_message or "Aurora planning provider failed.",
            )
        if not isinstance(result.payload, Mapping):
            raise AuroraPlanningError(
                "AURORA_PLANNER_RESPONSE_INVALID",
                "Aurora planner response must be an object.",
            )
        return result.payload


class MockAuroraPlanningBundleProvider:
    """Deterministic no-network bundle used only by the mock task runner."""

    async def plan(self, context: AuroraPlanningContext) -> Mapping[str, Any]:
        return _mock_bundle(context)


class AuroraDetailPlanningCoordinator:
    """Rehydrate assets, call one planner, then let the harness validate it."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: ImageStorage,
        service: AuroraDetailSessionService,
        provider: AuroraPlanningBundleProvider,
        runtime_root: Path,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.service = service
        self.provider = provider
        self.runtime_root = runtime_root.resolve()

    async def plan(self, job_id: str) -> JobStatus | None:
        try:
            reserved = self._reserve(job_id)
        except AuroraPlanningError as exc:
            return self._fail(job_id, exc.code)
        if isinstance(reserved, JobStatus) or reserved is None:
            return reserved
        context, job_version, session_revision = reserved
        try:
            hydrated = await self._hydrate_sources(context)
            bundle = await self.provider.plan(hydrated)
        except (AuroraPlanningError, OSError) as exc:
            return self._fail(job_id, getattr(exc, "code", "AURORA_PLANNING_FAILED"))
        try:
            return self._complete(
                job_id,
                job_version=job_version,
                session_revision=session_revision,
                context=hydrated,
                bundle=bundle,
            )
        except (AuroraPlanningError, AuroraDetailRuntimeError) as exc:
            return self._fail(job_id, exc.code)

    def _reserve(
        self, job_id: str
    ) -> tuple[AuroraPlanningContext, int, int] | JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current != JobStatus.PLANNING:
                return current
            settings = job.configuration.get("settings")
            if (
                not isinstance(settings, Mapping)
                or settings.get("workflow_version") != "aurora_v0.7.0"
            ):
                return current
            record = session.scalar(
                select(AuroraDetailSessionRecord)
                .where(AuroraDetailSessionRecord.job_id == job.id)
                .with_for_update()
            )
            if record is not None and record.state != "AWAITING_IDENTITY":
                return JobStatus(job.status)
            relations = list(
                session.scalars(
                    select(JobAssetRecord)
                    .where(JobAssetRecord.job_id == job.id)
                    .order_by(JobAssetRecord.ordinal, JobAssetRecord.created_at)
                ).all()
            )
            relations.sort(
                key=lambda item: (
                    0 if item.role == "product_reference" else 1,
                    item.ordinal,
                )
            )
            assets = {
                asset.id: asset
                for asset in session.scalars(
                    select(AssetRecord).where(
                        AssetRecord.id.in_([item.asset_id for item in relations])
                    )
                ).all()
            }
            sources: list[SourceImage] = []
            stable_paths: dict[str, str] = {}
            for relation in relations:
                asset = assets.get(relation.asset_id)
                if asset is None:
                    raise AuroraPlanningError(
                        "AURORA_SOURCE_MISSING", "Planning source is missing."
                    )
                stable = self._stable_asset_path(job.id, asset)
                stable_paths[asset.id] = str(stable)
                sources.append(
                    SourceImage(
                        asset_id=asset.id,
                        group_key="primary-product",
                        filename=asset.original_filename,
                        content_type=asset.content_type,
                        sha256=asset.sha256,
                        payload=b"",
                        source_role=relation.role,
                    )
                )
            context = AuroraPlanningContext(
                workspace_id=job.workspace_id,
                job_id=job.id,
                product_name=str(settings.get("product_name") or "").strip(),
                category=str(settings.get("category") or "").strip(),
                target_buyer=str(settings.get("target_buyer") or "").strip(),
                primary_scenario=str(settings.get("primary_scenario") or "").strip(),
                platform_code=str(settings.get("platform_code") or "").strip(),
                product_facts=tuple(
                    str(item).strip()
                    for item in [
                        *settings.get("selling_points", []),
                        *settings.get("product_facts", []),
                    ]
                    if str(item).strip()
                ),
                output_preferences=str(
                    settings.get("output_preferences") or ""
                ).strip(),
                sources=tuple(sources),
                stable_paths=stable_paths,
                existing_session=(record.session_payload if record else None),
                revision=(record.revision if record else 0) + 1,
            )
            job.stage = "aurora_planner_reserved"
            job.state_version += 1
            session.commit()
            return context, job.state_version, record.revision if record else 0

    async def _hydrate_sources(
        self, context: AuroraPlanningContext
    ) -> AuroraPlanningContext:
        hydrated: list[SourceImage] = []
        for source in context.sources:
            with self.session_factory() as session:
                asset = session.get(AssetRecord, source.asset_id)
                if asset is None or asset.workspace_id != context.workspace_id:
                    raise AuroraPlanningError(
                        "AURORA_SOURCE_MISSING", "Planning source is missing."
                    )
                object_key = asset.object_key
            payload = await self.storage.read_bytes(object_key)
            if _sha256(payload) != source.sha256:
                raise AuroraPlanningError(
                    "AURORA_SOURCE_HASH_MISMATCH",
                    "Planning source no longer matches its asset record.",
                )
            stable = Path(context.stable_paths[source.asset_id])
            stable.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(stable.write_bytes, payload)
            hydrated.append(replace(source, payload=payload, filename=stable.name))
        return replace(context, sources=tuple(hydrated))

    def _complete(
        self,
        job_id: str,
        *,
        job_version: int,
        session_revision: int,
        context: AuroraPlanningContext,
        bundle: Mapping[str, Any],
    ) -> JobStatus:
        normalized = _normalize_bundle(bundle, context)
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                raise AuroraPlanningError(
                    "AURORA_JOB_MISSING", "Aurora job disappeared during planning."
                )
            if (
                job.state_version != job_version
                or JobStatus(job.status) != JobStatus.PLANNING
            ):
                raise AuroraPlanningError(
                    "AURORA_PLANNER_RESULT_STALE", "Planner result is stale."
                )
            try:
                if context.existing_session is None:
                    self.service.start_planning_bundle(session, job, normalized)
                else:
                    self.service.continue_after_conflicts(
                        session,
                        job,
                        expected_revision=session_revision,
                        bundle=normalized,
                    )
            except (AuroraDetailServiceError, AuroraDetailRuntimeError) as exc:
                job.error_code = exc.code
                job.error_message = str(exc)
                transition = JobStatus.FAILED
                from .services import transition_job

                transition_job(
                    job, transition, stage="aurora_planning_failed", progress=100
                )
            session.commit()
            return JobStatus(job.status)

    def _fail(self, job_id: str, code: str) -> JobStatus | None:
        from .services import transition_job

        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            job.error_code = code
            job.error_message = (
                "Aurora detail planning failed without image generation."
            )
            transition_job(
                job, JobStatus.FAILED, stage="aurora_planning_failed", progress=100
            )
            session.commit()
            return JobStatus.FAILED

    def _stable_asset_path(self, job_id: str, asset: AssetRecord) -> Path:
        suffix = Path(asset.original_filename).suffix.lower() or ".png"
        return self.runtime_root / job_id / "assets" / f"{asset.sha256}{suffix}"


def _normalize_bundle(
    bundle: Mapping[str, Any], context: AuroraPlanningContext
) -> dict[str, Any]:
    """Replace planner asset tokens with SHA-stable local paths."""

    normalized = json.loads(json.dumps(bundle, ensure_ascii=False))
    if context.existing_session is not None:
        normalized.setdefault("raw_input", context.existing_session.get("input"))
    raw = normalized.get("raw_input")
    if not isinstance(raw, dict):
        raise AuroraPlanningError(
            "AURORA_PLANNER_RESPONSE_INVALID", "Planner omitted raw_input."
        )
    for key in ("product_images", "reference_materials"):
        values = raw.get(key, [])
        if not isinstance(values, list):
            raise AuroraPlanningError(
                "AURORA_PLANNER_RESPONSE_INVALID", f"{key} must be an array."
            )
        for item in values:
            if not isinstance(item, dict):
                raise AuroraPlanningError(
                    "AURORA_PLANNER_RESPONSE_INVALID", f"{key} item is invalid."
                )
            asset_id = str(item.get("asset_id") or item.get("id") or "")
            stable = context.stable_paths.get(asset_id)
            if stable is None:
                raise AuroraPlanningError(
                    "AURORA_PLANNER_SOURCE_UNKNOWN",
                    f"Planner referenced unknown asset {asset_id!r}.",
                )
            item["path"] = stable
    return normalized


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _mock_bundle(context: AuroraPlanningContext) -> dict[str, Any]:
    """Build schema-valid fixture data; this is not a production planner."""

    product_sources = [
        source for source in context.sources if source.source_role != "style_reference"
    ]
    style_sources = [
        source for source in context.sources if source.source_role == "style_reference"
    ]
    facts = [
        {
            "id": f"F{index:02d}",
            "text": fact,
            "source_class": "USER_FACT",
            "evidence_ref": "user brief",
        }
        for index, fact in enumerate(
            context.product_facts or (context.product_name,), 1
        )
    ]
    profile = {
        "target_platform": context.platform_code or "淘宝移动端",
        "profile_name": "3:4 adaptive working master",
        "selection_mode": "ADAPTIVE_PLANNED",
        "selection_rationale": (
            "移动端连续阅读、商品证明关系和稳定生成共同适合三比四母版。"
        ),
        "source": "mock planning fixture; merchant backend confirmation required",
        "aspect_ratio": {"width_units": 3, "height_units": 4, "label": "3:4"},
        "canvas_width_px": 1440,
        "module_height_px": 1920,
        "safe_margin_px": 72,
        "slice_height_px": 1200,
        "format": "PNG",
        "max_file_bytes": None,
        "verification_status": "BACKEND_CONFIRMATION_REQUIRED",
    }
    raw_input = {
        "product_name": context.product_name,
        "category": context.category,
        "target_buyer": context.target_buyer,
        "primary_scenario": context.primary_scenario,
        "product_images": [
            {
                "id": source.asset_id,
                "path": context.stable_paths[source.asset_id],
                "role": source.source_role,
            }
            for source in product_sources
        ],
        "verified_facts": facts,
        "conflict_policy": "BLOCK_PLAN_AND_BATCH_ASK",
        "conflict_scan": {
            "status": "CLEAR",
            "scanned_topics": [
                "identity",
                "specification",
                "formula",
                "performance",
                "audience",
                "compliance",
            ],
            "conflict_ids": [],
        },
        "source_conflicts": [],
        "reference_materials": [
            {
                "id": source.asset_id,
                "path": context.stable_paths[source.asset_id],
                "category": context.category or "视觉参考",
                "analysis_status": "ANALYZED",
                "observed_expression_methods": ["主体、证据对象与短文案形成清晰层级"],
                "analyzed_units": [
                    {
                        "id": f"{source.asset_id}-U01",
                        "source_region": "whole image",
                        "page_duty": "visual expression reference",
                        "visual_carrier": "subject and proof objects",
                        "composition_logic": "subject-led hierarchy",
                        "typography_logic": "short copy bound to visible evidence",
                        "observed_expression_method": (
                            "主体、证据对象与短文案形成清晰层级"
                        ),
                    }
                ],
            }
            for source in style_sources
        ],
        "platform_profile": profile,
    }
    identity = {
        "canonical_name": context.product_name,
        "category": context.category,
        "reference_image_ids": [source.asset_id for source in product_sources],
        "invariant_features": ["以全部商品原图共同确认的真实轮廓与可见结构"],
        "allowed_states": [context.primary_scenario or "真实使用场景"],
        "uncertain_features": [],
        "forbidden_mutations": ["不得改变商品结构、材质、包装文字或配件"],
    }
    cluster = {
        "id": "SP1",
        "buyer_question": "这件商品为什么值得购买",
        "fact_ids": [item["id"] for item in facts],
        "purchase_role": "CORE_VALUE",
        "separation_policy": "MERGEABLE",
        "assigned_module_ids": ["M01", "M02", "M03"],
    }
    modules = [
        _mock_module(
            index,
            tuple(str(item["id"]) for item in facts),
            context,
            bool(style_sources),
        )
        for index in (1, 2, 3)
    ]
    reference_system: dict[str, Any] = {
        "coverage": [],
        "adopted_patterns": [],
        "anti_copy_rule": "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET",
    }
    if style_sources:
        ids = [source.asset_id for source in style_sources]
        reference_system = {
            "coverage": [
                {
                    "reference_id": asset_id,
                    "disposition": "ADOPTED_GRAMMAR",
                    "pattern_ids": [f"RP{index:02d}"],
                    "reason": "仅采用主体、证据对象与短文案的层级关系。",
                }
                for index, asset_id in enumerate(ids, 1)
            ],
            "adopted_patterns": [
                {
                    "id": f"RP{index:02d}",
                    "source_reference_ids": [asset_id],
                    "source_unit_ids": [f"{asset_id}-U01"],
                    "observed_method": "主体、证据对象与短文案形成清晰层级",
                    "adaptation_for_product": "用当前商品真实结构重建证明关系。",
                    "scheduled_module_ids": ["M01", "M02", "M03"],
                    "do_not_copy": ["品牌", "商品", "文案", "数字", "水印", "完整版式"],
                }
                for index, asset_id in enumerate(ids, 1)
            ],
            "anti_copy_rule": (
                "ADAPT_VISUAL_GRAMMAR_ONLY_NEVER_COPY_BRAND_COPY_OR_ASSET"
            ),
        }
        pattern_ids = [item["id"] for item in reference_system["adopted_patterns"]]
        for module in modules:
            module["reference_pattern_ids"] = pattern_ids
    return {
        "raw_input": raw_input,
        "identity": identity,
        "plan": {
            "campaign_thesis": "用商品真实结构、作用关系与使用结果逐层回答购买问题。",
            "dominant_decision_type": "functional",
            "output_strategy": {
                "target_platform": profile["target_platform"],
                "profile_name": profile["profile_name"],
                "selection_mode": "ADAPTIVE_PLANNED",
                "module_count": 3,
                "module_count_rationale": (
                    "总价值、核心证明和场景结果各承担独立购买职责，无填充屏。"
                ),
                "module_count_candidates": [
                    {
                        "count": 2,
                        "coverage_tradeoff": "核心证明与场景结果被迫合并。",
                        "selling_point_fit": "覆盖事实但视觉证明拥挤。",
                        "decision": "REJECTED",
                    },
                    {
                        "count": 3,
                        "coverage_tradeoff": "三类购买职责各有独立证明空间。",
                        "selling_point_fit": "覆盖事实且保持移动端节奏。",
                        "decision": "SELECTED",
                    },
                ],
                "selling_point_clusters": [cluster],
                "merge_decisions": ["同一事实簇按总价值、机制证明和场景结果分层表达。"],
                "claim_coverage": [
                    {
                        "claim_id": item["id"],
                        "disposition": "LEAD" if index == 0 else "SUPPORT",
                        "module_ids": ["M01", "M02", "M03"],
                        "rationale": "用户事实进入连续证明链。",
                        "defer_reason_code": "NOT_DEFERRED",
                    }
                    for index, item in enumerate(facts)
                ],
                "aspect_ratio": profile["aspect_ratio"],
                "canvas_width_px": 1440,
                "module_height_px": 1920,
                "safe_margin_px": 72,
                "slice_height_px": 1200,
                "ratio_rationale": profile["selection_rationale"],
                "dimension_rationale": "高清母版兼顾移动阅读、中文可读性和后续切片。",
                "uniform_dimensions": True,
                "verification_status": "BACKEND_CONFIRMATION_REQUIRED",
            },
            "reference_expression_system": reference_system,
            "style_constitution": {
                "visual_world": "真实、清晰的商业摄影世界",
                "color_and_light": "按商品固有色建立统一光线",
                "typography_and_graphics": "短中文与证据对象绑定",
                "product_rendering": "保持真实轮廓、结构与材质",
                "rhythm": "总价值、机制、场景递进",
            },
            "series_visual_dna": {
                "brand_anchor_system": "商品包装与固有视觉资产",
                "palette_tokens": "来自商品固有色",
                "typography_tokens": "清晰现代中文",
                "graphic_tokens": "只服务于真实关系的辅助图形",
                "photography_tokens": "通透商业摄影",
                "product_tokens": "真实轮廓、结构和材质",
                "spatial_tokens": "主体、证据、结果分层",
                "invariants": ["商品身份", "统一色光", "视觉先于文字"],
            },
            "typography_rhythm": {
                "campaign_rule": "文字绑定画面证据，不使用固定标题位。",
                "primary_mode_sequence": [
                    module["text_system"]["primary_mode"] for module in modules
                ],
                "anchor_zone_sequence": [
                    module["text_system"]["anchor_zone"] for module in modules
                ],
                "centered_hero_max": 1,
                "consecutive_anchor_repeat_limit": 1,
                "exceptions": [],
            },
            "modules": modules,
        },
    }


def _mock_module(
    order: int,
    fact_ids: tuple[str, ...],
    context: AuroraPlanningContext,
    has_reference: bool,
) -> dict[str, Any]:
    duties = ("建立核心购买价值", "证明商品结构与作用关系", "展示真实场景结果")
    questions = ("它首先解决什么问题", "它为什么能够做到", "真实使用时得到什么")
    modes = ("offset_editorial_headline", "object_label", "scene_caption")
    zones = ("top_left", "object_local", "lower_right")
    visible_copy = [
        {"text": context.product_name[:12], "role": "短标题", "anchor": "真实商品主体"},
        {"text": "看得见的真实价值", "role": "证据标签", "anchor": "商品作用结果"},
    ]
    return {
        "id": f"M{order:02d}",
        "order": order,
        "duty": duties[order - 1],
        "buyer_question": questions[order - 1],
        "lead_conclusion": duties[order - 1],
        "lead_claim_id": fact_ids[0],
        "supporting_claim_ids": list(fact_ids[1:]),
        "selling_point_cluster_ids": ["SP1"],
        "reference_pattern_ids": ["RP01"] if has_reference else [],
        "visual_proof_direction": "展示真实商品、关键作用关系和可见结果。",
        "visual_evidence": {
            "evidence_class": "DIRECT_VERIFIED",
            "proof_device": "对象动作结果关系",
            "visible_content": ["商品", "关键部件", "动作", "结果"],
            "forbidden_inventions": ["不得虚构规格、认证或效果数字"],
        },
        "visual_proof_contract": {
            "buyer_takeaway": duties[order - 1],
            "visual_verb": "商品通过可见动作产生可见结果",
            "primary_subject": "真实商品",
            "supporting_subjects": ["关键部件", "使用动作", "可见结果"],
            "required_relations": ["商品到动作到结果"],
            "minimum_visual_payload": 3,
            "visual_specificity_anchor": ["真实轮廓", "真实结构", "真实材质"],
            "allowed_metaphor": "少量不替代证明的气氛表达",
            "hidden_copy_test": "遮住文字仍能理解商品、动作和结果",
        },
        "visible_copy": visible_copy,
        "copy_intent": {
            "policy": "VISUAL_FIRST_WITH_AUXILIARY_COPY",
            "why_text_is_needed": "短文字只负责识别画面中已有关系。",
            "text_to_visual_bindings": [
                {"text": item["text"], "bound_to_visual": item["anchor"]}
                for item in visible_copy
            ],
            "hidden_copy_takeaway": "遮住文字仍能理解核心证明",
            "copy_adds": "命名画面中已经存在的购买价值",
        },
        "composition_family": ("hero_anchor", "structure_diagram", "immersive_scene")[
            order - 1
        ],
        "camera_scale": "mixed",
        "text_system": {
            "primary_mode": modes[order - 1],
            "supporting_mode": "object_label",
            "anchor_target": "visible proof object",
            "anchor_zone": zones[order - 1],
            "reading_direction": (
                "top_to_bottom",
                "object_to_result",
                "scene_to_caption",
            )[order - 1],
            "placement_logic": "文字贴近其命名的对象或结果。",
            "hierarchy": "商品第一，证明关系第二，辅助文字第三。",
            "max_lines": 3,
            "container_style": (
                "open_negative_space",
                "micro_label",
                "soft_caption_panel",
            )[order - 1],
            "negative_space_reservation": (
                "upper-left calm area",
                "local area beside key part",
                "lower-right scene area",
            )[order - 1],
            "image_text_relationship": "每个文字单元绑定可见对象、动作或结果。",
            "composition_flexibility": "CONTROLLED_REFLOW",
            "neighbor_difference": "建立系列母版。"
            if order == 1
            else "同时改变构图载体、文字锚点和阅读方向。",
        },
        "reading_path": "商品到作用关系到结果",
        "copy_density": "low",
        "visual_payload_density": "high",
        "proof_relation_strength": "strong",
        "commercial_energy": "high",
        "breathing_screen": False,
        "brand_anchor": "商品自身包装与固有色",
        "independent_logo_policy": "REQUIRED_IF_AUTHORIZED"
        if order == 1
        else "FORBIDDEN",
        "inherited_dna_tokens": ["真实商品", "统一色光"],
        "variation_from_previous": ["建立系列母版"]
        if order == 1
        else ["改变构图载体与文字锚点"],
        "output": {"width_px": 1440, "height_px": 1920, "safe_margin_px": 72},
    }
