# ruff: noqa: E501
"""Domestic six-image main campaign authored in one planning call.

Same shape as the fast detail page and one-click replica pipelines: one
vision planning call reads every original image and the user's facts, and
authors the shared locks plus one prompt per page; the server joins the
shared locks and the page's own fields verbatim into the image prompt; the
six pages are generated in parallel and delivered without a pixel review.

The original Aurora v2.0 Skill's know-how stays in the planner: its
core-policy, six-page strategy, visual strategy and commercial-performance
references are given to the planner verbatim.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import default_aurora_v20_skill_root

VERSION = "aurora-main-image-authored-v1"
SCHEMA_VERSION = "aurora-main-image-authored-plan-v1"
PROFILE = "aurora_main_image_authored"
# Recorded as the plan's skill_id: the original Skill's references it was
# authored with (their content hash is the plan's skill_content_hash).
REFERENCE_ID = "aurora-domestic-ecommerce-main-image-v20-references"
CANVAS = (1024, 1024)
MAX_PAGE_SOURCES = 3

PAGE_ROLES = (
    "SEARCH_MAIN_IMAGE_LISTING_COVER",
    "CAROUSEL_IDENTITY_HERO",
    "CAROUSEL_CORE_FEATURE_PROOF",
    "CAROUSEL_SCENE_OR_OPERATION",
    "CAROUSEL_DETAIL_OR_TRUST",
    "CAROUSEL_OFFER_OR_SPEC_CLOSURE",
)
PAGE_DUTIES = (
    "搜索主图：在搜索结果缩略图里第一眼抢点击。完整大商品 + 4–10 字强钩子标题 + 真实证据 + 底部商业闭合，两到三个扫描停顿，至少四级文字角色。",
    "身份主视觉：换一个镜头（三分之四侧角或侧面）建立商品身份与质感，较低信息密度，一个真实关系加少量文字。",
    "核心卖点证明：完整商品与真实局部、质地、成分或机制形成大小双尺度，遮住文字也能看出利益方向。",
    "场景与使用：在可信的真实使用环境里，人或手与商品发生接触动作，展示怎么用、用在哪。",
    "细节与信任：真实微距、结构、材质或包装细节成为主视觉，配有主次分明的说明。",
    "规格与收口：完整商品或包装加规格、数量、服务或适用人群的规格簇，作为整套的收口；不复用首页钩子。",
)

_REFERENCES = (
    "core-policy.md",
    "six-page-strategy.md",
    "visual-strategy.md",
    "commercial-performance.md",
)

_PREFIX = (
    "Square 1:1 Chinese domestic e-commerce main image (Taobao/Tmall carousel), "
    "one finished commercial image at 1024x1024"
)
_BOUNDARIES = (
    "Render exactly ONE finished image, never several panels or a contact sheet. "
    "The attached product photos are the only authority for the product: keep its "
    "silhouette, proportions, colors and materials, components, closures, logo and "
    "label positions, and reproduce every legible character printed on the product "
    "exactly; never redraw the product, add parts or change its packaging. The "
    "photos' backgrounds, desks, floors, boxes, props, lighting and any poster "
    "layout or slogans around the product are capture material: build a new "
    "commercial scene and layout for this page. Visible copy outside the product "
    "may only use the confirmed facts below (verbatim or a faithful shortening that "
    "keeps every number and condition); never invent claims, numbers, "
    "certifications, prices or reviews, and never leave a label without its value. "
    "All newly added copy is Simplified Chinese, sharp and legible, with a clear "
    "hierarchy. Physically plausible contact, perspective, shadows and occlusion. "
    "No watermark, UI chrome, frame borders or placeholder text."
)


def enabled() -> bool:
    """New main-image plans are authored in one pass (default on)."""

    value = os.environ.get("POLARIS_MAIN_IMAGE_AUTHORED_PLAN", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


@lru_cache(maxsize=2)
def _reference_bundle(root: str) -> tuple[str, str]:
    sections = []
    for name in _REFERENCES:
        text = (Path(root) / "references" / name).read_text(encoding="utf-8").strip()
        sections.append(f"===== {name} =====\n{text}")
    bundle = "\n\n".join(sections)
    return bundle, hashlib.sha256(bundle.encode()).hexdigest()


def reference_bundle(skill_root: Path | None = None) -> tuple[str, str]:
    """The original Skill's planning references and their content hash."""

    return _reference_bundle(str(skill_root or default_aurora_v20_skill_root()))


def _string(min_length: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length}


def _strings(min_items: int = 0, max_items: int = 24) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": min_items,
        "maxItems": max_items,
        "items": _string(),
    }


def strategy_schema() -> dict[str, Any]:
    page = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_role",
            "buyer_question",
            "main_selling_point",
            "supporting_selling_points",
            "headline",
            "visible_copy",
            "visual_proof",
            "camera",
            "scene",
            "composition_and_subject",
            "reading_path_and_type_hierarchy",
            "non_repetition_reason",
            "commercial_closure",
            "reference_sources",
            "page_prompt",
        ],
        "properties": {
            "page_role": {"type": "string", "enum": list(PAGE_ROLES)},
            "buyer_question": _string(),
            "main_selling_point": _string(),
            "supporting_selling_points": _strings(max_items=6),
            "headline": _string(),
            "visible_copy": _strings(max_items=10),
            "visual_proof": _string(),
            "camera": _string(),
            "scene": _string(),
            "composition_and_subject": _string(),
            "reading_path_and_type_hierarchy": _string(),
            "non_repetition_reason": _string(),
            "commercial_closure": _string(),
            "reference_sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_PAGE_SOURCES,
                "items": {"type": "integer", "minimum": 1},
            },
            "page_prompt": _string(20),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["analysis", "plan"],
        "properties": {
            "analysis": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_copy_lines", "confirmed_facts", "buyer_insight"],
                "properties": {
                    "source_copy_lines": _strings(max_items=24),
                    "confirmed_facts": _strings(min_items=1, max_items=40),
                    "buyer_insight": _string(),
                },
            },
            "plan": {
                "type": "object",
                "additionalProperties": False,
                "required": ["product_identity_lock", "campaign_style_lock", "pages"],
                "properties": {
                    "product_identity_lock": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "primary_product_source",
                            "identity",
                            "label_text",
                            "do_not_change",
                            "physical_logic",
                        ],
                        "properties": {
                            "primary_product_source": {"type": "integer", "minimum": 1},
                            "identity": _string(),
                            "label_text": _strings(max_items=20),
                            "do_not_change": _strings(min_items=1, max_items=12),
                            "physical_logic": _string(),
                        },
                    },
                    "campaign_style_lock": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "visual_world",
                            "palette",
                            "lighting",
                            "typography",
                            "graphic_language",
                        ],
                        "properties": {
                            "visual_world": _string(),
                            "palette": _string(),
                            "lighting": _string(),
                            "typography": _string(),
                            "graphic_language": _string(),
                        },
                    },
                    "pages": {
                        "type": "array",
                        "minItems": 6,
                        "maxItems": 6,
                        "items": page,
                    },
                },
            },
        },
    }


def system_prompt(skill_root: Path | None = None) -> str:
    bundle, _ = reference_bundle(skill_root)
    duties = "\n".join(
        f"- 第 {index + 1} 页 {role}：{duty}"
        for index, (role, duty) in enumerate(zip(PAGE_ROLES, PAGE_DUTIES, strict=True))
    )
    return (
        "You are the art director and planner of a Chinese domestic e-commerce "
        "six-image main campaign (Taobao/Tmall: one search listing cover plus five "
        "carousel images). In ONE pass you read every attached original product "
        "image and the user's facts, and author the complete campaign. There is no "
        "later review or repair: each page_prompt you write goes to the image model "
        "as is, so it must be concrete, visual and self-sufficient.\n\n"
        "The six pages, in this exact order:\n"
        + duties
        + "\n\nRules:\n"
        "1. Transcribe, before planning, every clearly readable text block on the "
        "original images that is NOT printed on the product itself (headlines, "
        "slogans, badges, claims, numbers, spec boxes) into "
        "analysis.source_copy_lines: one entry per visual block, copied in full "
        "exactly as printed; a multi-line headline is one entry. Skip anything "
        "partly hidden or ambiguous; never guess. Text printed on the product "
        "goes into product_identity_lock.label_text instead, exactly as printed.\n"
        "2. analysis.confirmed_facts = the user's facts plus source_copy_lines, "
        "cleaned of list markers such as '•', '1.' or headings, without changing "
        "meaning, numbers or conditions. Only confirmed facts may become visible "
        "copy. Pick what sells each page; do not force every fact onto a page.\n"
        "3. product_identity_lock describes only the product itself, as visible "
        "geometry: shapes, positions, counts and colors (e.g. 'two rounded ears on "
        "the left and right sides of the lid, two curved eye lines, no nose'). "
        "Never name an animal, character or object the product merely resembles "
        "(no 'panda', 'bear', 'monkey' ...) unless that word is printed on the "
        "product; the image model would draw the named thing instead of the "
        "real part. choose "
        "primary_product_source as the 1-based position of the clearest complete "
        "product image. Backgrounds, boxes, floors and poster layouts are not "
        "identity.\n"
        "4. Each page has its own buyer_question and main selling point; adjacent "
        "pages never repeat the same lead claim, camera, scene or layout skeleton. "
        "Every page uses a different camera (e.g. front hero, three-quarter, in hand, "
        "in use, macro, top-down flat lay) and a different scene/environment fitting "
        "the category; the colors follow campaign_style_lock so the set stays "
        "coherent. Never reuse the source photos' backdrop.\n"
        "5. headline: the exact headline text to print (search cover 4–10 Chinese "
        "characters, never more than 12; others short). visible_copy: every other "
        "exact text to print on the image, each with a complete value.\n"
        "6. reference_sources: 1–3 one-based image positions this page needs, the "
        "image that best shows the product from this page's camera first.\n"
        "7. page_prompt: a vivid, specific Chinese image brief for this page only: "
        "camera and framing, scene and props, where the product sits and how big, "
        "where each piece of copy sits and its relative size, lighting and "
        "material feel, and the visual proof of the selling point. Do not repeat "
        "the shared locks; the server adds them.\n\n"
        "Reference material from the original six-image Skill (follow it):\n\n"
        + bundle
    )


def planner_prompt(
    *,
    product_name: str,
    category: str,
    facts: Sequence[str],
    source_count: int,
) -> str:
    return (
        f"商品名：{product_name}\n类目：{category}\n"
        f"原图数量：{source_count}（按附件顺序编号 1–{source_count}）\n"
        "用户提供的事实（逐条，原样）：\n"
        + json.dumps(list(facts), ensure_ascii=False)
        + "\n\nReturn only the JSON instance (analysis and plan at the root) that "
        "matches this schema:\n"
        + json.dumps(strategy_schema(), ensure_ascii=False)
    )


class AuthoredPlanError(ValueError):
    pass


def validate_strategy(value: object, source_count: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthoredPlanError("规划结果不是 JSON 对象")
    errors = sorted(
        Draft202012Validator(strategy_schema()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "/".join(str(part) for part in error.absolute_path)
        raise AuthoredPlanError(f"规划结果不完整：{path} {error.message}"[:300])
    strategy = json.loads(json.dumps(value, ensure_ascii=False))
    pages = strategy["plan"]["pages"]
    if [page["page_role"] for page in pages] != list(PAGE_ROLES):
        raise AuthoredPlanError("六页职责顺序不对")
    primary = strategy["plan"]["product_identity_lock"]["primary_product_source"]
    if primary > source_count:
        raise AuthoredPlanError("商品主参考图编号超出原图数量")
    for page in pages:
        if any(index > source_count for index in page["reference_sources"]):
            raise AuthoredPlanError("页面参考图编号超出原图数量")
        page["reference_sources"] = list(dict.fromkeys(page["reference_sources"]))
    prompts = [page["page_prompt"].strip() for page in pages]
    if len(set(prompts)) != len(prompts):
        raise AuthoredPlanError("六页的画面描述有重复")
    return strategy


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compile_prompt(strategy: Mapping[str, Any], page_index: int) -> str:
    """Shared locks and the current page's own fields, joined verbatim."""

    plan = strategy["plan"]
    page = plan["pages"][page_index]
    shared = {
        "confirmed_facts": strategy["analysis"]["confirmed_facts"],
        "product_identity_lock": {
            key: value
            for key, value in plan["product_identity_lock"].items()
            if key != "primary_product_source"
        },
        "campaign_style_lock": plan["campaign_style_lock"],
    }
    current = {
        "page": f"{page_index + 1}/6",
        "duty": PAGE_DUTIES[page_index],
        **{
            key: value
            for key, value in page.items()
            if key not in {"page_prompt", "reference_sources", "page_role"}
        },
    }
    return "\n".join(
        (
            _PREFIX,
            _BOUNDARIES,
            "SHARED LOCKS: " + _json(shared),
            "THIS PAGE: " + _json(current),
            "IMAGE BRIEF: " + page["page_prompt"].strip(),
        )
    )


def page_source_ids(
    strategy: Mapping[str, Any], page_index: int, asset_ids: Sequence[str]
) -> list[str]:
    page = strategy["plan"]["pages"][page_index]
    primary = strategy["plan"]["product_identity_lock"]["primary_product_source"]
    order = list(dict.fromkeys([*page["reference_sources"], primary]))
    return [asset_ids[index - 1] for index in order][:MAX_PAGE_SOURCES]


def public_page(page: Mapping[str, Any], page_index: int) -> dict[str, Any]:
    """Plan fields shown in the workspace (no prompts or paths)."""

    supporting = list(page["supporting_selling_points"])
    return {
        "page_index": page_index,
        "page_role": page["page_role"],
        "main_selling_point": page["main_selling_point"],
        "supporting_selling_points": supporting,
        "visual_proof": page["visual_proof"],
        "composition_and_subject": f"{page['camera']}；{page['scene']}；{page['composition_and_subject']}",
        "reading_path_and_type_hierarchy": page["reading_path_and_type_hierarchy"],
        "non_repetition_reason": page["non_repetition_reason"],
        "commercial_closure": page["commercial_closure"],
        "headline": page["headline"],
    }


def fake_strategy(product_name: str, source_count: int) -> dict[str, Any]:
    """Deterministic offline plan for the mock gateway and tests."""

    cameras = ("正面英雄视角", "三分之四侧角", "手持特写", "使用中的斜向视角", "微距", "俯拍平铺")
    scenes = ("几何展台", "浴室台面一角", "浅色无缝空间", "卧室使用场景", "质感台面", "纸面平铺")
    pages = []
    for index, role in enumerate(PAGE_ROLES):
        pages.append(
            {
                "page_role": role,
                "buyer_question": f"第{index + 1}页买家想确认的问题",
                "main_selling_point": f"{product_name}卖点{index + 1}",
                "supporting_selling_points": [],
                "headline": f"卖点{index + 1}",
                "visible_copy": [],
                "visual_proof": "商品本体与卖点的真实关系",
                "camera": cameras[index],
                "scene": scenes[index],
                "composition_and_subject": "商品占画面主体，文字在留白处",
                "reading_path_and_type_hierarchy": "商品 → 标题 → 证据",
                "non_repetition_reason": f"第{index + 1}页使用独立镜头与场景",
                "commercial_closure": "以已确认事实收口",
                "reference_sources": [1],
                "page_prompt": f"离线测试第{index + 1}页：{cameras[index]}，{scenes[index]}，商品完整居中占画面六成，标题位于左上方清晰醒目，光线柔和自然，接触阴影真实。",
            }
        )
    return {
        "analysis": {
            "source_copy_lines": [],
            "confirmed_facts": [f"{product_name}"],
            "buyer_insight": "离线测试",
        },
        "plan": {
            "product_identity_lock": {
                "primary_product_source": 1,
                "identity": "仅使用合成测试输入",
                "label_text": [],
                "do_not_change": ["合成主体与包装身份"],
                "physical_logic": "合成空间的接触、阴影和透视一致",
            },
            "campaign_style_lock": {
                "visual_world": "明亮干净的商业摄影",
                "palette": "品牌色为主，中性色为辅",
                "lighting": "柔和侧光",
                "typography": "粗黑标题加细体说明",
                "graphic_language": "简洁信息块",
            },
            "pages": pages,
        },
    }
