"""Durable first approval checkpoint for the Aurora six-image workflow."""

from __future__ import annotations

import json
import re
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .aurora_main_image_runtime import (
    AURORA_MAIN_IMAGE_VERSION,
    AuroraHarnessRunner,
    write_contract,
)
from .domain import JobStatus, PlanValidationStatus
from .models import AuditEventRecord, JobPlanRecord, JobRecord, utc_now
from .services import canonical_hash, new_id, transition_job

PAGE_ROLES = (
    "SEARCH_MAIN_IMAGE_LISTING_COVER",
    "CAROUSEL_IDENTITY_HERO",
    "CAROUSEL_CORE_FEATURE_PROOF",
    "CAROUSEL_SCENE_OR_OPERATION",
    "CAROUSEL_DETAIL_OR_TRUST",
    "CAROUSEL_OFFER_OR_SPEC_CLOSURE",
)


class AuroraMainImagePlanner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        harness: AuroraHarnessRunner | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.harness = harness or AuroraHarnessRunner()

    async def plan(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            existing = session.scalar(
                select(JobPlanRecord.id).where(JobPlanRecord.job_id == job.id).limit(1)
            )
            if existing is not None:
                return JobStatus(job.status)
            configuration = (
                job.configuration if isinstance(job.configuration, dict) else {}
            )
            input_value = configuration.get("input", {})
            settings = configuration.get("settings", {})
            asset_ids = list(input_value.get("product_asset_ids", []))
            facts = list(settings.get("selling_points", []))
            raw = {
                "request_id": job.id,
                "profile01_semantics_read": False,
                "product": {
                    "name": settings.get("product_name", ""),
                    "category": settings.get("category", ""),
                    "original_references": asset_ids,
                    "verified_selling_points": facts,
                    "verified_attributes": settings.get("product_attributes", []),
                    "verified_scenes": settings.get("scenes", []),
                    "verified_offers": settings.get("offers", []),
                    "verified_service_or_trust_facts": settings.get(
                        "service_or_trust_facts", []
                    ),
                },
            }
            with TemporaryDirectory(prefix="polaris-aurora-plan-") as temporary:
                from pathlib import Path

                workspace = Path(temporary)
                input_path = workspace / "input.json"
                session_path = workspace / "session.json"
                write_contract(input_path, raw)
                self.harness.run(
                    "start",
                    workspace,
                    {"input": input_path, "session": session_path},
                )
                harness_session = json.loads(session_path.read_text(encoding="utf-8"))

            pages = _build_pages(settings, asset_ids)
            payload = {
                "schema_version": "aurora-main-image-plan-v1",
                "skill_id": "aurora-domestic-ecommerce-main-image",
                "skill_version": AURORA_MAIN_IMAGE_VERSION,
                "approval_checkpoint": "six_page_plan",
                "product": {
                    "name": settings.get("product_name"),
                    "category": settings.get("category"),
                },
                "pages": pages,
                "harness_session": harness_session,
                "execution_policy": {
                    "sequence": "strictly_sequential",
                    "max_automatic_repairs_per_page": 1,
                    "final_set_approval_required": True,
                },
            }
            plan = JobPlanRecord(
                id=new_id("plan"),
                workspace_id=job.workspace_id,
                job_id=job.id,
                revision=1,
                schema_version="aurora-main-image-plan-v1",
                payload=payload,
                payload_hash=canonical_hash(payload),
                validation_status=PlanValidationStatus.VALID.value,
                validation_errors=[],
                validator_version=f"aurora-harness-{AURORA_MAIN_IMAGE_VERSION}",
                validated_at=utc_now(),
            )
            session.add(plan)
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    action="aurora.plan_created",
                    resource_type="job",
                    resource_id=job.id,
                    request_id=plan.id,
                    details={
                        "page_count": 6,
                        "harness_state": harness_session["state"],
                    },
                )
            )
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_plan_confirmation",
                progress=15,
            )
            session.commit()
            return JobStatus.AWAITING_CONFIRMATION


def _build_pages(
    settings: dict[str, object], asset_ids: list[str]
) -> list[dict[str, object]]:
    """Turn verified facts into six distinct visual decisions, not six copies."""

    name = _text(settings.get("product_name"), "该商品")
    category = _text(settings.get("category"), "商品")
    raw_selling_points = _text_list(settings.get("selling_points"))
    inferred = _classify_pasted_facts(raw_selling_points)
    selling_points = inferred["selling_points"]
    attributes = _unique(
        [*_text_list(settings.get("product_attributes")), *inferred["attributes"]]
    )
    scenes = _unique([*_text_list(settings.get("scenes")), *inferred["scenes"]])
    offers = _unique([*_text_list(settings.get("offers")), *inferred["offers"]])
    trust_facts = _unique(
        [
            *_text_list(settings.get("service_or_trust_facts")),
            *inferred["trust_facts"],
        ]
    )
    style_preferences = _text_list(settings.get("style_preferences"))

    ranked_points = sorted(selling_points, key=_selling_point_score, reverse=True)
    ranked_attributes = sorted(attributes, key=_attribute_score, reverse=True)
    primary = ranked_points[0] if ranked_points else "核心购买理由"
    proof_point = (
        ranked_points[1]
        if len(ranked_points) > 1 and _selling_point_score(ranked_points[1]) > 0
        else (ranked_attributes[0] if ranked_attributes else primary)
    )
    scene = scenes[0] if scenes else "中性操作演示"
    detail_fact = next(
        (fact for fact in ranked_attributes if fact != proof_point),
        (ranked_attributes or trust_facts or selling_points or [primary])[0],
    )
    close_facts = offers or trust_facts or attributes or selling_points
    close_fact = close_facts[0]
    style = "、".join(style_preferences[:2]) or "克制、清晰的商业摄影"

    strategies = (
        {
            "headline": "大主体建立搜索识别，首屏只打一个核心钩子",
            "objective": f"让用户先认出{name}，再快速理解首要购买理由。",
            "composition": (
                "主商品占画面约 60%–70%，使用最容易辨认商品结构的角度；"
                "减少装饰元素，保证缩略图下商品轮廓与信息层级仍然清楚。"
            ),
            "copy_direction": f"围绕「{primary}」提炼一条短主张，不并列堆放其他卖点。",
            "evidence": [name, category, primary],
        },
        {
            "headline": "用英雄构图确立商品身份与整套视觉基调",
            "objective": f"把{name}作为唯一主角，建立后续五图共同遵循的视觉世界。",
            "composition": (
                f"采用三分之四或正侧英雄角度，完整展示商品；以{style}为基调，"
                "背景、光线和留白服务于商品身份，不做功能证明。"
            ),
            "copy_direction": (
                f"只说明商品名称与「{category}」身份，"
                "避免重复搜索主图的销售钩子。"
            ),
            "evidence": [name, category, *style_preferences[:2]],
        },
        {
            "headline": "把核心卖点转成一眼可懂的可视证据",
            "objective": f"围绕「{proof_point}」回答用户为什么应该相信。",
            "composition": (
                "使用局部特写、结构拆解或前后状态中的一种证据方式；"
                "只有素材能够证明时才使用对比，不虚构实验数据或性能结果。"
            ),
            "copy_direction": (
                f"标题表达「{proof_point}」带来的明确价值，"
                "辅助标注只引用已核实事实。"
            ),
            "evidence": _unique([proof_point, *ranked_attributes[:2]]),
        },
        {
            "headline": "用真实动作说明商品如何进入使用情境",
            "objective": (
                f"在「{scene}」中展示商品与人的动作关系。"
                if scenes
                else "未提供已核实场景，使用中性操作演示说明商品如何被使用。"
            ),
            "composition": (
                "以商品和关键动作作为双焦点，环境只保留解释使用方式所需的元素；"
                "不添加未经提供的人群、地点或使用结果。"
            ),
            "copy_direction": "用动作结果组织短句，不新增未经核实的场景承诺。",
            "evidence": scenes[:2] or ["商品素材中的可见结构与操作方式"],
        },
        {
            "headline": "用细节特写补足质感与信任理由",
            "objective": f"围绕「{detail_fact}」放大用户在前四页尚未看清的可信细节。",
            "composition": (
                "选择一个可由原始素材验证的结构、做工或标识做近景特写，"
                "辅以克制标注；不替商品推断材质、认证或耐久结论。"
            ),
            "copy_direction": (
                "标题回答“细节为什么值得信任”，事实不足时只描述可见内容。"
            ),
            "evidence": _unique(
                [detail_fact, *(ranked_attributes or trust_facts or selling_points)[:2]]
            )[:3],
        },
        {
            "headline": "汇总已核实决策信息，完成购买收口",
            "objective": f"以「{close_fact}」为主锚点，收束前五页信息并降低决策成本。",
            "composition": (
                "商品保持清晰完整，使用简洁信息区汇总不超过三项已核实要点；"
                "若没有价格或优惠事实，不制造促销角标和倒计时。"
            ),
            "copy_direction": (
                "按权益、服务、规格、卖点的可用顺序收口，只展示已有事实。"
            ),
            "evidence": close_facts[:3],
        },
    )

    return [
        {
            "page_index": ordinal,
            "page_role": role,
            **strategies[ordinal],
            "visual_duty": strategies[ordinal]["objective"],
            "source_asset_ids": asset_ids,
            "status": "awaiting_plan_approval",
        }
        for ordinal, role in enumerate(PAGE_ROLES)
    ]


def _text(value: object, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _classify_pasted_facts(facts: list[str]) -> dict[str, list[str]]:
    """Recover useful groups when a whole product brief is pasted as selling points."""

    groups: dict[str, list[str]] = {
        "selling_points": [],
        "attributes": [],
        "scenes": [],
        "offers": [],
        "trust_facts": [],
    }
    for original in facts:
        fact = re.sub(r"^[•·*\-]\s*", "", original).strip()
        fact = re.sub(r"^\d+[.、]\s*", "", fact).strip()
        if not fact or re.match(r"^[一二三四五六七八九十]+[、.]", fact):
            continue
        if "完整产品信息" in fact or "基础商品信息" in fact:
            continue
        if fact.startswith(("商品全称", "品牌：", "品牌:")):
            continue

        if _contains_any(
            fact,
            ("发货", "物流", "客服", "售后", "退货", "包退", "好评率", "评分"),
        ):
            groups["trust_facts"].append(fact)
        if _contains_any(fact, ("免运费", "优惠", "到手价", "满减", "赠品", "领券")):
            groups["offers"].append(fact)
        if _contains_any(
            fact,
            ("通勤", "出游", "慢跑", "办公室", "居家", "旅行", "日常休闲"),
        ):
            groups["scenes"].append(fact)
        if _contains_any(
            fact,
            (
                "配色",
                "撞色",
                "版型",
                "材质",
                "翻毛皮",
                "鞋底",
                "剪裁",
                "纹路",
                "结构",
                "尺寸",
                "容量",
            ),
        ):
            groups["attributes"].append(fact)

        if not any(
            fact in groups[key]
            for key in ("trust_facts", "offers", "scenes", "attributes")
        ):
            groups["selling_points"].append(fact)

    if not groups["selling_points"]:
        groups["selling_points"] = [
            fact
            for fact in facts
            if "完整产品信息" not in fact and "基础商品信息" not in fact
        ][:3]
    return {key: _unique(value) for key, value in groups.items()}


def _selling_point_score(fact: str) -> int:
    high_intent = (
        "主打",
        "透气",
        "轻量",
        "舒适",
        "防",
        "抓地",
        "便携",
        "耐磨",
        "显高",
        "增高",
    )
    low_intent = ("别名", "季节", "男女均可", "可作", "品类")
    return sum(keyword in fact for keyword in high_intent) * 10 - sum(
        keyword in fact for keyword in low_intent
    )


def _attribute_score(fact: str) -> int:
    visible_proof = (
        "材质",
        "翻毛皮",
        "鞋底",
        "纹路",
        "剪裁",
        "结构",
        "网孔",
        "拼接",
        "做工",
    )
    return sum(keyword in fact for keyword in visible_proof) * 10


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
