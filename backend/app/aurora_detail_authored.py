# ruff: noqa: E501
"""Domestic detail page 精致版 authored in one planning call (aurora v2.3.0).

Same shape as the unified main image and the fast detail page: one vision
planning call reads every original image and the user's facts and authors the
shared locks plus one short brief per screen; the server joins the shared locks
and the screen's own fields verbatim into the image prompt; screens are
generated in parallel and delivered without a pixel review.

The original aurora detail Skill v2.3.0 (owner-supplied, vendored byte for byte
in skill_sources) supplies the know-how: its planning references are given to
the planner verbatim. Its harness is not executed: the harness plan and its
compiled prompts are far too long for one gateway call, and its per-screen
pixel audit is the step the owner chose to drop.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator
from PIL import Image

from . import refined_detail
from .new_detail_skill_provider import (
    AdapterValidationError,
    DetailSkillRoute,
    NewDetailSkillProvider,
    job_configuration_from,
)
from .provider import ProviderArtifact, ProviderOutcome

if TYPE_CHECKING:
    from .provider import (
        PersistedProviderArtifact,
        Provider,
        ProviderRequest,
        ProviderResult,
    )
    from .xinghe_agent import PlannerRequest

SKILL_ID = "aurora-domestic-ecommerce-detail-page-v23"
PIPELINE_VERSION = "aurora-domestic-detail-v2.3-authored"
PROFILE = "aurora_domestic_detail_v23_authored"
CONCURRENCY = 20

# Planning references of the original Skill, read verbatim by the planner.
# SKILL.md itself is a harness/CLI runbook; its non-negotiable gates that
# apply to one-pass authoring are restated in planner_prompt instead.
PROTOCOL_FILES = (
    "references/core-policy.md",
    "references/detail-story-grammar.md",
    "references/selling-point-depth-and-count.md",
    "references/pain-solution-visual-story.md",
    "references/pain-expression-routing.md",
    "references/commercial-aversion-control.md",
    "references/visual-proof.md",
    "references/product-presence-rhythm.md",
    "references/spatial-structure-contract.md",
    "references/adaptive-typography.md",
    "references/series-visual-dna.md",
    "references/cross-module-continuity.md",
    "references/category-routing-v2.md",
    "references/compliance-and-platform.md",
)

# Category-neutral visual archetypes named by the Skill (SKILL.md §4).
ROLES = (
    "FIRST_SCREEN_HOOK",
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
)
PRESENCE = (
    "REQUIRED_DOMINANT",
    "REQUIRED_SUPPORTING",
    "IDENTITY_TOKEN_ONLY",
    "ABSENT_PREFERRED",
)

_PREFIX = "vertical 3:4 e-commerce detail page image"
_BOUNDARIES = (
    "只画一张独立的竖版国内电商详情页单屏，不要多屏拼板、不要内嵌小海报、不要留白边框；画面铺满整个画布。"
    "随附商品照片是商品的唯一依据：保持轮廓、比例、颜色、材质、部件、数量、包装和标签位置，"
    "商品上能读清的文字逐字还原（商品身份锁列出主要印刷文字）；不得重画商品、增加部件或改动包装。照片里的背景、桌面、道具、光线和海报排版只是拍摄素材，"
    "为本屏重新搭建场景和版式。画面上新增的文字只能来自本屏可见文字清单，逐字使用，简体中文、清晰锐利、层级分明；"
    "不得编造功效、数字、认证、检测、价格、评价或对比结果，不画实验室、显微镜或检测图冒充证据。"
    "内部策划用语（屏号、职责、证据来源、风险说明、以包装为准等）绝不出现在画面上。"
    "独立品牌标识：只有首屏可以出现一个与商品原图一致的独立品牌标识，其余屏不出现独立、悬浮或角标式标识；商品包装上印的标识照常保留。"
    "接触、透视、阴影和遮挡符合物理常识。无水印、无界面元素、无占位文字。"
)


def enabled() -> bool:
    """New 精致版 detail jobs use this contract (default on)."""

    value = os.environ.get("POLARIS_DETAIL_AURORA_AUTHORED", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def is_authored(configuration: Mapping[str, Any]) -> bool:
    return configuration.get("domestic_detail_pipeline") == PIPELINE_VERSION


# Each screen is a 3:4 composition. It is generated at the model's native
# 1440x1920 and then resized exactly to the size the user picked for the
# platform (no crop: every delivery size is exactly 3:4).
GENERATION_SIZE = "1440x1920"
DELIVERY_SIZES = frozenset(
    {"750x1000", "990x1320", "1080x1440", "1242x1656", GENERATION_SIZE}
)


def delivery_size(settings: Mapping[str, Any]) -> str:
    size = str(settings.get("size") or GENERATION_SIZE).strip().lower()
    if size not in DELIVERY_SIZES:
        raise AdapterValidationError(
            "DETAIL_SIZE_UNSUPPORTED", "请选择所选平台提供的 3:4 详情图尺寸。"
        )
    return size


def prompt_configuration(settings: Mapping[str, Any]) -> dict[str, Any]:
    size = delivery_size(settings)
    width, height = (int(value) for value in size.split("x"))
    return refined_detail.prompt_configuration(
        {**settings, "size": GENERATION_SIZE}
    ) | {
        "profile_id": PROFILE,
        "delivery": {"qa_mode": "not_reviewed", "qa_status_required": False},
        "delivery_size": size,
        "delivery_dimensions": {"width": width, "height": height},
    }


def fit_to_delivery(artifact: ProviderArtifact, size: str) -> ProviderArtifact:
    """Resize one generated screen to the chosen platform size."""
    width, height = (int(value) for value in size.split("x"))
    if (artifact.width, artifact.height) == (width, height):
        return artifact
    with Image.open(BytesIO(artifact.payload)) as source:
        image = source.convert("RGB")
    # A provider canvas a few pixels off 3:4 is centre-cropped to 3:4 first.
    scale = min(image.width / width, image.height / height)
    crop_w, crop_h = round(width * scale), round(height * scale)
    left, top = (image.width - crop_w) // 2, (image.height - crop_h) // 2
    image = image.crop((left, top, left + crop_w, top + crop_h)).resize(
        (width, height), Image.Resampling.LANCZOS
    )
    buffer = BytesIO()
    if artifact.content_type == "image/jpeg":
        image.save(buffer, "JPEG", quality=92, optimize=True)
    elif artifact.content_type == "image/webp":
        image.save(buffer, "WEBP", quality=92)
    else:
        image.save(buffer, "PNG", optimize=True)
    payload = buffer.getvalue()
    return ProviderArtifact(
        payload=payload,
        filename=artifact.filename,
        content_type=artifact.content_type,
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
        locally_resampled=True,
        provider_width=artifact.provider_width or artifact.width,
        provider_height=artifact.provider_height or artifact.height,
    )


class AuroraDetailProvider(NewDetailSkillProvider):
    def __init__(self, delegate: Provider) -> None:
        super().__init__(
            delegate, DetailSkillRoute(SKILL_ID, "domestic", prompt_configuration)
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        result = await super().execute(request)
        if result.outcome != ProviderOutcome.SUCCEEDED or result.artifact is None:
            return result
        try:
            size = delivery_size(job_configuration_from(request.configuration))
        except AdapterValidationError:
            return result
        return replace(result, artifact=fit_to_delivery(result.artifact, size))

    def _native_delivery_receipt(
        self,
        artifact: ProviderArtifact | PersistedProviderArtifact,
        expected: list[int],
    ) -> dict[str, Any] | None:
        return refined_detail.native_delivery_receipt(artifact, expected)


def _string(min_length: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length}


def _strings(min_items: int = 0, max_items: int = 24) -> dict[str, Any]:
    return {"type": "array", "minItems": min_items, "maxItems": max_items, "items": _string()}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def strategy_schema(page_count: int) -> dict[str, Any]:
    screen = _object(
        {
            "role": {"type": "string", "enum": list(ROLES)},
            "title": _string(),
            "label": _string(),
            "buyer_question": _string(),
            "lead_conclusion": _string(),
            "selling_points": _strings(min_items=1, max_items=6),
            "visible_copy": _strings(min_items=0, max_items=4),
            "visual_proof": _string(),
            "product_presence": {"type": "string", "enum": list(PRESENCE)},
            "structure": _string(),
            "subject_scale": _string(),
            "composition": _string(),
            "device": _string(),
            "difference": _string(),
            "camera": _string(),
            "scene": _string(),
            "typography": _string(),
            "continuity": _string(),
            "page_prompt": _string(20),
        }
    )
    ledger_entry = _object(
        {
            "point": _string(),
            "status": {"type": "string", "enum": ["ACTIVE", "MERGED", "QUALIFIED", "DEFERRED"]},
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 12},
            "reason": _string(),
        }
    )
    extra_point = _object(
        {
            "point": _string(),
            "source": _string(),
            "basis": _string(),
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 12},
        }
    )
    return _object(
        {
            "analysis": _object(
                {
                    "source_copy_lines": _strings(max_items=24),
                    "package_facts": _strings(max_items=24),
                    "confirmed_facts": _strings(min_items=1, max_items=60),
                    "target_buyer": _string(),
                    "primary_pain": _string(),
                    "positioning": _string(),
                    "primary_selling_points": _strings(min_items=1, max_items=4),
                    "selling_point_ledger": {"type": "array", "items": ledger_entry, "maxItems": 40},
                    "extra_selling_points": {"type": "array", "items": extra_point, "maxItems": 16},
                }
            ),
            "plan": _object(
                {
                    "story_spine": _string(),
                    "product_identity_physics_lock": _object(
                        {
                            "primary_product_source": {"type": "integer", "minimum": 1},
                            "identity": _string(),
                            "label_text": _strings(max_items=20),
                            "brand_logo": _string(),
                            "do_not_change": _strings(min_items=1, max_items=12),
                            "physical_logic": _string(),
                        }
                    ),
                    "campaign_style_lock": _object(
                        {
                            "visual_world": _string(),
                            "palette": _string(),
                            "lighting": _string(),
                            "typography": _string(),
                            "graphic_language": _string(),
                            "product_finish": _string(),
                        }
                    ),
                    "design_strength_lock": _object(
                        {
                            "rhythm": {"type": "array", "items": _string(), "minItems": page_count, "maxItems": page_count},
                            "structure_variety": _string(),
                        }
                    ),
                    "screens": {"type": "array", "items": screen, "minItems": page_count, "maxItems": page_count},
                }
            ),
        }
    )


def planner_prompt(request: PlannerRequest) -> str:
    settings = request.intake_settings or {}
    count = request.page_count
    return (
        f"为下面这件商品一次写完整套国内电商详情页：正好 {count} 屏，每屏独立 3:4 竖版（画布 {request.size}），语言 {request.language}。"
        f"商品：{request.product_name}。类目：{settings.get('category') or '根据商品照片判断'}。"
        f"目标买家：{settings.get('target_buyer') or '根据商品与资料谨慎推断'}。平台：{request.platform_code}。"
        f"原图数量：{len(request.sources)}（按附件顺序编号 1–{len(request.sources)}）。\n"
        "用户提供的资料（逐条原样，均为用户确认的事实）：\n"
        + json.dumps(list(request.product_information), ensure_ascii=False)
        + "\n\n这是一次性策划，没有后续审图或返修：每屏的 page_prompt 会和共享锁一起直接交给生图模型，必须具体、可视、自足。"
        "屏数由用户确定为 "
        + str(count)
        + " 屏：按 selling-point-depth-and-count 的方法在这个屏数内分配卖点深度，不要另行增减屏数。\n\n"
        "这是网站上的一次性生成：不能暂停、不能向用户提问、不能返回空方案，plan.screens 必须正好 "
        + str(count)
        + " 屏。原版 Skill 中“先解决资料冲突再策划”的要求在这里这样执行：用户资料之间、包装不同面之间或不同原图之间的数字或说法不一致时，"
        "冲突的那几项不上图、不当卖点，在 package_facts 里照写并在末尾注明“与原图N不一致，不使用”；其余不冲突的事实照常使用，继续完成全部屏。\n\n"
        "必须遵守（来自原版 Skill 的硬性规则）：\n"
        "1. 只写已确认事实；绝不编造或加强价格、功效、检测、认证、成分、数量、配件、服务、对比结果。"
        "把原图上非商品本身印刷的可读文字块逐块原样转写进 analysis.source_copy_lines。"
        "商品包装（正面、背面、侧面）上清晰可读的宣称同样是用户提供的事实：把成分与原料占比、营养或参数数值、工艺、口味/规格/净含量、适用对象、"
        "认证或检测（仅限包装原文）等逐条原样转写进 analysis.package_facts，每条末尾用“（原图N）”注明出处；读不清的数字不要写。"
        "商品展示面的主要印刷文字另写进 product_identity_physics_lock.label_text 用于还原外观。"
        "analysis.confirmed_facts = 用户资料 + source_copy_lines + package_facts，去掉“•”“1.”或小标题等列表符号，不改含义、数字与条件。\n"
        "2. 用户给的卖点全部入账：selling_point_ledger 为每一条用户卖点记录 ACTIVE/MERGED/QUALIFIED/DEFERRED、落在哪几屏（页码从 1 开始）和原因；不能悄悄丢掉。"
        "primary_selling_points 是必须被记住的 1–4 个一级卖点：每个一级卖点要有总览出现、一屏作为主结论的独立表达、一屏使用或结果、收尾回忆。\n"
        "2b. 卖点来源与不重复：每屏要讲一个不同的卖点。先用用户卖点，不够时用 package_facts，再不够时用这个类目买家常关心的角度"
        "（例如猫粮：原料与配方、蛋白等营养含量、适用阶段、口味与颗粒、喂食与保存、规格与包装；其他类目按同样思路自行判断）。"
        "类目角度只能用已确认事实来填（例如把包装上的成分占比做成信息图、把规格与口味做成选购屏），不能凭类目常识编造本商品的功效、数值或认证；"
        "没有事实支撑的角度就不用。用户卖点以外实际用到的每个卖点写进 analysis.extra_selling_points："
        "point 为卖点短语，source 写“包装原图N”或“类目常见关注”，basis 写所依据的已确认事实原文，pages 为所在屏。"
        "同一个卖点最多做一屏的主标题（lead_conclusion / visible_copy 第一条）；除首屏和收尾外，作为副文案最多再出现在一屏。"
        "相邻屏的主结论必须是不同的卖点。\n"
        "3. 首屏 role 为 FIRST_SCREEN_HOOK，最后一屏为 PURCHASE_CLOSURE（屏数 ≥3 时）；屏数 ≥4 时必须有一屏 PAIN_SCENE 或 PAIN_TO_SOLUTION_BRIDGE，"
        "痛点要画出受影响的对象/人/环境、不想要的状态和后果，不能只是标题、词云、图标或泛泛的愁容；痛点要可识别但不令人反感（commercial-aversion-control）。\n"
        "4. 视觉优先、文字辅助：每屏 visible_copy 为 1–4 条要印在画面上的完整短文案（含主标题），逐条绑定可见的物体、动作、结果或证据区；"
        "遮住文字也要能看懂这屏的卖点。不要用“静态商品图 + 一句口号”、纯图标证明或换个商品也成立的画面。内部用语（证据来源、以包装标示为准、购买前请核对等）不得进入 visible_copy。\n"
        "5. 商品出镜是整页节奏：首屏和收尾 REQUIRED_DOMINANT；来源、材质、机理、专属证明、结果、生活方式类屏优先 ABSENT_PREFERRED，"
        "缺席时用本商品的材质、动作、结果、细节或色彩绑定身份，不要角落小包装或虚化背景包装。\n"
        "6. 空间结构是契约：structure 写清可观察的分区、几何与主次；相邻两屏结构、镜头、场景不能相同；不能连续两屏都是满版单场景；"
        "首屏只传递色彩、光线、字体气质与商品质感，不传递版式骨架。continuity 写本屏从上一屏接过哪个可见元素并如何延续或转折（首屏写进入方式）。\n"
        "7. product_identity_physics_lock 只描述商品本身的可见几何：形状、位置、数量、颜色；不要用商品“像什么”的动物或角色来命名，除非该词印在商品上。"
        "primary_product_source 为最清晰完整商品图的编号。brand_logo 写首屏使用的、原图上可读的品牌标识及其所在原图编号；读不到就写“无可读品牌标识，首屏不画独立标识”。\n"
        "8. 每屏的 label 是这屏卖点的内部摘要（不单独印刷，要印的字只写在 visible_copy）；device 是本屏的视觉手法（如前后对比、剖面、流程、大小双尺度、使用瞬间）；"
        "subject_scale 是主体尺度（整体/局部微距/场景/信息）；difference 写本屏与前一屏在结构、镜头、场景上的可见区别（首屏写与常见首屏的区别）。\n"
        "9. page_prompt：只写本屏独有的画面中文描述——镜头与取景、场景与道具、主体位置与大小、每条文字的位置与相对大小、光线与质感、卖点的视觉证明。"
        "不要重复共享锁，服务器会自动加上。\n\n"
        "10. 简洁：除 page_prompt 外，每个文字字段用一两句中文写清决定（一般不超过 80 字），不要写英文枚举名、内部代号或方法库编号；"
        "label_text 只列商品展示面上清晰可读的主要印刷文字（最多 8 条，背面成分表、厂家、执行标准等小字不列）；selling_point_ledger 的 reason 一句话。\n"
        "只返回符合下列 JSON Schema 的数据实例（根上是 analysis 和 plan），不要返回 Schema 本身：\n"
        + json.dumps(strategy_schema(count), ensure_ascii=False)
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


_PAGE_FIELDS = (
    "title",
    "lead_conclusion",
    "visible_copy",
    "visual_proof",
    "product_presence",
    "structure",
    "subject_scale",
    "composition",
    "device",
    "difference",
    "camera",
    "scene",
    "typography",
    "continuity",
)


def _compiled(structured_plan: Mapping[str, Any], screen: Mapping[str, Any]) -> str:
    """Shared locks and the current screen's own fields, joined verbatim."""

    # Facts stay in the approved plan; the per-screen visible_copy is the
    # only text whitelist the image model needs.
    plan = structured_plan["plan"]
    shared = {
        "商品身份锁": {
            ("商品身份主图（原图编号）" if key == "primary_product_source" else key): value
            for key, value in plan["product_identity_physics_lock"].items()
        },
        "系列风格锁": plan["campaign_style_lock"],
    }
    current = {key: screen[key] for key in _PAGE_FIELDS}
    return "\n".join(
        (
            _PREFIX,
            _BOUNDARIES,
            "共享锁：" + _json(shared),
            "本屏：" + _json(current),
            "画面描述：" + str(screen["page_prompt"]).strip(),
        )
    )


def _plan_error(message: str, pointer: str = "/") -> Exception:
    from .xinghe_agent import XingheAgentError

    return XingheAgentError("AURORA_DETAIL_PLAN_INVALID", message[:300], json_pointer=pointer)


def _validate_raw(value: Mapping[str, Any], page_count: int) -> None:
    if not 1 <= page_count <= 12:
        raise _plan_error("A complete 1–12 screen strategy is required.")
    errors = sorted(
        Draft202012Validator(strategy_schema(page_count)).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        raise _plan_error(error.message, "/" + "/".join(str(part) for part in error.absolute_path))


_EXTRA_POINT_KEYS = ("point", "source", "basis", "pages")


def normalize_strategy(value: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap a schema-shaped relay envelope, loosen fixable slips, freeze prompts."""

    if "type" in value or "properties" in value:
        properties = value.get("properties")
        if (
            set(value) != {"type", "properties"}
            or not isinstance(properties, Mapping)
            or set(properties) != {"analysis", "plan"}
        ):
            raise _plan_error("The strategy instance envelope is ambiguous.")
        value = properties
    result = deepcopy(dict(value))
    analysis = result.get("analysis")
    extras = analysis.get("extra_selling_points") if isinstance(analysis, dict) else None
    if isinstance(analysis, dict) and isinstance(extras, list):
        # A bookkeeping list: tolerate the ledger's "reason" key and stray keys.
        tidy = []
        for entry in extras:
            if isinstance(entry, Mapping):
                entry = dict(entry)
                if "basis" not in entry and "reason" in entry:
                    entry["basis"] = entry["reason"]
                entry = {k: v for k, v in entry.items() if k in _EXTRA_POINT_KEYS}
            tidy.append(entry)
        analysis["extra_selling_points"] = tidy
    plan = result.get("plan")
    screens = plan.get("screens") if isinstance(plan, Mapping) else None
    count = len(screens) if isinstance(screens, list) else 0
    _validate_raw(result, count)
    for screen in result["plan"]["screens"]:
        screen["image_prompt"] = _compiled(result, screen)
    return result


def validate_strategy(value: Mapping[str, Any], page_count: int) -> None:
    from .xinghe_agent import XingheAgentError

    _validate_raw(_without_prompts(value), page_count)
    for screen in value["plan"]["screens"]:
        if screen.get("image_prompt") != _compiled(value, screen):
            raise XingheAgentError(
                "AURORA_DETAIL_PROMPT_MISMATCH", "A frozen page prompt or shared lock was changed."
            )


def _without_prompts(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    for screen in result.get("plan", {}).get("screens", []) or []:
        if isinstance(screen, dict):
            screen.pop("image_prompt", None)
    return result


def validate_source_selection(structured_plan: Mapping[str, Any], source_roles: Any) -> None:
    """The primary identity image must be an uploaded product reference.

    Loosened: an out-of-range or non-product primary falls back to the first
    product-reference image instead of failing the order; prompts are refrozen.
    """
    from .xinghe_agent import XingheAgentError

    roles = list(source_roles or ())
    products = [index for index, role in enumerate(roles, 1) if role == "product_reference"]
    if not products:
        raise XingheAgentError(
            "AURORA_DETAIL_IDENTITY_SOURCE_INVALID",
            "At least one uploaded product-reference image is required.",
        )
    lock = structured_plan["plan"]["product_identity_physics_lock"]
    if lock["primary_product_source"] not in products:
        lock["primary_product_source"] = products[0]
        for screen in structured_plan["plan"]["screens"]:
            screen["image_prompt"] = _compiled(structured_plan, screen)


def compile_prompt(
    *,
    structured_plan: Mapping[str, Any],
    screen: Mapping[str, Any],
    page_number: int,
    page_count: int,
    language: str,
    product_name: str,
    product_information: Any,
    source_roles: Any,
    size: str,
) -> str:
    from .xinghe_agent import XingheAgentError

    prompt = _compiled(structured_plan, screen)
    if screen.get("image_prompt") != prompt:
        raise XingheAgentError(
            "AURORA_DETAIL_PROMPT_MISMATCH", "Frozen prompt does not match authored locks."
        )
    return prompt


_LABELS = {
    "analysis": "商品分析与卖点",
    "plan_protocol_fields": "整套策划",
    "campaign_style_lock": "系列风格",
    "design_strength_lock": "节奏与结构",
    "source_copy_lines": "原图文字",
    "confirmed_facts": "已确认事实",
    "target_buyer": "目标买家",
    "primary_pain": "核心痛点",
    "positioning": "定位",
    "primary_selling_points": "一级卖点",
    "selling_point_ledger": "用户卖点去向",
    "package_facts": "包装上的事实",
    "extra_selling_points": "补充卖点（包装与类目）",
    "story_spine": "故事线",
    "product_identity_physics_lock": "商品身份与物理关系",
    "role": "页面职责",
    "label": "卖点摘要",
    "device": "视觉手法",
    "subject_scale": "主体尺度",
    "difference": "与前一屏的区别",
    "buyer_question": "买家问题",
    "lead_conclusion": "主结论",
    "selling_points": "承载卖点",
    "visible_copy": "画面文字",
    "visual_proof": "画面如何证明",
    "product_presence": "商品出镜策略",
    "structure": "空间结构",
    "composition": "构图",
    "camera": "镜头",
    "scene": "场景",
    "typography": "文字如何进入画面",
    "continuity": "与前一屏的衔接",
}
_PRIVATE_PAGE_KEYS = {"item_key", "group_key", "page", "quality", "image_prompt", "page_prompt"}


def approval_document(payload: Mapping[str, Any]) -> str:
    lines = ["# 国内详情图·精致方案", "一次规划写出整套方案；每屏独立并行生成，成功保存后交付，不做画质复审或自动重绘。"]
    for group in payload.get("groups", []):
        for section in ("analysis", "plan_protocol_fields", "campaign_style_lock", "design_strength_lock"):
            lines.append("## " + _LABELS[section])
            for key, value in sorted(group.get(section, {}).items()):
                if key != "screens":
                    lines.append(f"{_LABELS.get(key, key)}：{json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    for index, page in enumerate(payload.get("pages", []), 1):
        lines.append(f"## 第 {index} 屏 · {page.get('title', '')}")
        lines.append(
            "执行内容指纹：" + hashlib.sha256(str(page.get("image_prompt", "")).encode("utf-8")).hexdigest()
        )
        for key, value in sorted(page.items()):
            if key not in _PRIVATE_PAGE_KEYS:
                lines.append(f"{_LABELS.get(key, key)}：{json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    return "\n\n".join(lines)


def approval_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(approval_document(payload).encode("utf-8")).hexdigest()


def approval_matches(payload: Mapping[str, Any]) -> bool:
    approval = payload.get("refined_approval") or {}
    document = approval.get("document_markdown")
    return (
        isinstance(document, str)
        and hashlib.sha256(document.encode("utf-8")).hexdigest() == approval.get("document_sha256")
        and refined_detail._document_sections(document)
        == refined_detail._document_sections(approval_document(payload))
    )


def validate_payload(payload: Mapping[str, Any], page_count: int) -> None:
    groups, pages = payload.get("groups"), payload.get("pages")
    if not isinstance(groups, list) or len(groups) != 1 or not isinstance(pages, list):
        raise _plan_error("One complete product strategy is required.")
    group = groups[0]
    screens = [
        {key: value for key, value in page.items() if key not in {"item_key", "group_key", "page", "quality"}}
        for page in pages
        if isinstance(page, Mapping)
    ]
    validate_strategy(
        {
            "analysis": group.get("analysis"),
            "plan": {
                **group.get("plan_protocol_fields", {}),
                "campaign_style_lock": group.get("campaign_style_lock"),
                "design_strength_lock": group.get("design_strength_lock"),
                "screens": screens,
            },
        },
        page_count,
    )


def fake_strategy(request: PlannerRequest) -> dict[str, Any]:
    """Deterministic offline plan for the mock gateway and tests."""

    count = request.page_count
    roles = ["FIRST_SCREEN_HOOK", "PAIN_SCENE", "DEDICATED_BENEFIT_PROOF", "SOURCE_ACTION_RESULT",
             "WHOLE_PLUS_MACRO", "ACTION_SEQUENCE", "STATE_CONTRAST", "USE_SCOPE_MATRIX",
             "SENSORY_WORLD", "SELECTION_COMPARISON", "TRUST_EVIDENCE"]
    structures = ("满版主视觉", "左右分栏", "上下叠层", "环绕关系", "流程三格", "大小双尺度")
    screens = []
    for index in range(count):
        role = "PURCHASE_CLOSURE" if count >= 3 and index == count - 1 else roles[min(index, len(roles) - 1)]
        screens.append(
            {
                "role": role,
                "title": f"第{index + 1}屏卖点",
                "label": f"卖点{index + 1}",
                "buyer_question": f"第{index + 1}屏买家想确认的问题",
                "lead_conclusion": f"{request.product_name}结论{index + 1}",
                "selling_points": [f"卖点{index + 1}"],
                "visible_copy": [f"卖点{index + 1}"],
                "visual_proof": "商品与卖点的真实关系",
                "product_presence": "REQUIRED_DOMINANT" if index in (0, count - 1) else "ABSENT_PREFERRED",
                "structure": structures[index % len(structures)],
                "subject_scale": "整体" if index % 2 == 0 else "局部微距",
                "composition": "主体占画面六成，文字在留白处",
                "device": "前后对比" if index % 2 else "主视觉",
                "difference": f"第{index + 1}屏换用独立结构与镜头",
                "camera": f"镜头{index + 1}",
                "scene": f"场景{index + 1}",
                "typography": "标题偏置，标签贴近物件",
                "continuity": "首屏进入" if index == 0 else "延续上一屏的光线方向",
                "page_prompt": f"离线测试第{index + 1}屏：独立镜头与场景，商品清晰，标题位于留白处，光线柔和自然。",
            }
        )
    return {
        "analysis": {
            "source_copy_lines": [],
            "package_facts": [],
            "confirmed_facts": [request.product_name],
            "target_buyer": "离线测试",
            "primary_pain": "离线测试",
            "positioning": "离线测试",
            "primary_selling_points": ["卖点1"],
            "selling_point_ledger": [],
            "extra_selling_points": [],
        },
        "plan": {
            "story_spine": "首屏建立价值 → 痛点 → 证明 → 收尾",
            "product_identity_physics_lock": {
                "primary_product_source": 1,
                "identity": "仅使用合成测试输入",
                "label_text": [],
                "brand_logo": "无可读品牌标识，首屏不画独立标识",
                "do_not_change": ["合成主体与包装身份"],
                "physical_logic": "合成空间的接触、阴影和透视一致",
            },
            "campaign_style_lock": {
                "visual_world": "明亮干净的商业摄影",
                "palette": "品牌色为主，中性色为辅",
                "lighting": "柔和侧光",
                "typography": "粗黑标题加细体说明",
                "graphic_language": "简洁信息块",
                "product_finish": "真实材质",
            },
            "design_strength_lock": {
                "rhythm": [f"第{index + 1}屏节奏" for index in range(count)],
                "structure_variety": "相邻屏结构不同",
            },
            "screens": screens,
        },
    }


__all__: Sequence[str] = (
    "SKILL_ID",
    "PIPELINE_VERSION",
    "PROFILE",
    "CONCURRENCY",
    "PROTOCOL_FILES",
    "AuroraDetailProvider",
    "enabled",
    "is_authored",
    "prompt_configuration",
    "strategy_schema",
    "planner_prompt",
    "normalize_strategy",
    "validate_strategy",
    "validate_source_selection",
    "compile_prompt",
    "approval_document",
    "approval_hash",
    "approval_matches",
    "validate_payload",
    "fake_strategy",
)
